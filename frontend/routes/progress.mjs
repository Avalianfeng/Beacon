/**
 * 进度 / 附着 / 恢复 / 任务列表 API。
 */
import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { mkdir, readFile, readdir, stat, writeFile } from "node:fs/promises";
import { isAbsolute, join, relative, resolve } from "node:path";
import { randomUUID } from "node:crypto";
import { createWriteStream } from "node:fs";
import { buildProgressDto, MACRO_STAGES } from "../lib/progress.mjs";
import { HttpError, projectRoot, readJsonBody, safeProjectPath, sendJson } from "../lib/shared.mjs";

async function readJsonSafe(filePath) {
  try {
    return JSON.parse(await readFile(filePath, "utf8"));
  } catch {
    return null;
  }
}

function splitCommandLine(command) {
  const matches = String(command || "").match(/"[^"]+"|[^\s]+/g) || [];
  const parts = matches.map((part) => part.replace(/^"(.*)"$/, "$1")).filter(Boolean);
  if (parts.length === 0) throw new Error("MATH_AGENT_COMMAND is empty.");
  return parts;
}

/**
 * 调用 `math-agent status --json`；失败时回退到直接读文件。
 */
export async function loadStatusPayload(out, thread, env, buildChildEnv) {
  const outDir = safeProjectPath(out);
  const commandParts = splitCommandLine(env.MATH_AGENT_COMMAND || "uv run math-agent");
  const command = commandParts[0];
  const args = [
    ...commandParts.slice(1),
    "status",
    "--out",
    out,
    "--thread",
    thread || "default",
    "--json",
  ];

  const fromCli = await new Promise((resolvePromise) => {
    let stdout = "";
    let stderr = "";
    let settled = false;
    const child = spawn(command, args, {
      cwd: projectRoot,
      env: buildChildEnv(),
      windowsHide: true,
    });
    const timer = setTimeout(() => {
      if (settled) return;
      settled = true;
      try { child.kill(); } catch {}
      resolvePromise(null);
    }, 45_000);
    child.stdout.on("data", (c) => { stdout += c; });
    child.stderr.on("data", (c) => { stderr += c; });
    child.on("error", () => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      resolvePromise(null);
    });
    child.on("close", (code) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      if (code !== 0) {
        resolvePromise(null);
        return;
      }
      try {
        resolvePromise(JSON.parse(stdout.trim()));
      } catch {
        resolvePromise(null);
      }
    });
  });

  if (fromCli) return fromCli;

  const supervisor = await readJsonSafe(resolve(outDir, "supervisor.json"));
  const failure = await readJsonSafe(resolve(outDir, "failure.json"));
  const completion = await readJsonSafe(resolve(outDir, "completion.json"));
  const snapshot = await readJsonSafe(resolve(outDir, "progress_snapshot.json"));
  const checkpointExists = existsSync(resolve(outDir, "checkpoints.sqlite"));
  return {
    checkpoint_exists: checkpointExists,
    next_node: snapshot?.next_node || failure?.node || supervisor?.last_node || "",
    final_status: completion?.status || "",
    supervisor,
    completion,
    failure,
    snapshot,
  };
}

export async function handleProgressGet(request, response, url, ctx) {
  const out = url.searchParams.get("out") || "runs/ui-latest";
  const thread = url.searchParams.get("thread") || "default";
  safeProjectPath(out);
  const status = await loadStatusPayload(out, thread, ctx.env, ctx.buildChildEnv);
  const memoryRun = [...ctx.runs.values()].find(
    (r) => r.out === out && (r.threadId || "default") === thread,
  ) || null;
  const dto = buildProgressDto({
    out,
    thread,
    supervisor: status.supervisor,
    failure: status.failure,
    completion: status.completion,
    nextNode: status.next_node || "",
    finalStatus: status.final_status || "",
    checkpointExists: Boolean(status.checkpoint_exists),
    snapshot: status.snapshot,
    memoryRun,
  });
  sendJson(response, 200, { ...dto, macros: MACRO_STAGES.map((s) => ({ id: s.id, label: s.label })) });
}

export async function handleAttach(request, response, ctx) {
  const body = await readJsonBody(request);
  const out = body.out || "runs/ui-latest";
  const thread = body.thread || body.threadId || "default";
  const outDir = safeProjectPath(out);
  if (!existsSync(outDir)) {
    throw new HttpError(404, `输出目录不存在：${out}`);
  }

  const existing = [...ctx.runs.values()].find(
    (r) => r.out === out && (r.threadId || "default") === thread && ["running", "paused"].includes(r.status),
  );
  if (existing) {
    const { child, sseClients, stdoutBuffer, ...safeRun } = existing;
    sendJson(response, 200, { run: safeRun, attached: true, existing: true });
    return;
  }

  const status = await loadStatusPayload(out, thread, ctx.env, ctx.buildChildEnv);
  const runId = `attach-${Date.now()}-${randomUUID().slice(0, 8)}`;
  const runDir = safeProjectPath(`runs/ui-server/${runId}`);
  await mkdir(runDir, { recursive: true });

  const candidateLogs = [
    resolve(outDir, "supervisor.log"),
    resolve(outDir, "run.log"),
  ];
  let logPath = resolve(runDir, "attached.log");
  for (const candidate of candidateLogs) {
    if (existsSync(candidate)) {
      logPath = candidate;
      break;
    }
  }
  if (!existsSync(logPath)) {
    await writeFile(logPath, `# attached ${out}\n`, "utf8");
  }

  let uiStatus = "failed";
  const sup = status.supervisor?.status;
  if (sup === "running" || sup === "starting") uiStatus = "running";
  else if (sup === "paused" || status.next_node === "human_review") uiStatus = "paused";
  else if (sup === "completed" || status.final_status === "completed") uiStatus = "completed";
  else if (sup === "degraded" || status.final_status === "degraded") uiStatus = "degraded";
  else if (sup === "rejected" || status.final_status === "rejected") uiStatus = "rejected";
  else if (sup === "blocked" || status.failure) uiStatus = "failed";
  else if (status.checkpoint_exists && status.next_node) uiStatus = "failed";
  else uiStatus = "failed";

  const run = {
    id: runId,
    status: uiStatus,
    command: `(attached) ${out}`,
    out,
    threadId: thread,
    ragEnabled: true,
    iterationDepth: 3,
    logPath,
    startedAt: status.supervisor?.started_at || new Date().toISOString(),
    endedAt: status.supervisor?.ended_at || new Date().toISOString(),
    exitCode: null,
    stdoutBuffer: "",
    sseClients: new Set(),
    attached: true,
  };
  ctx.runs.set(runId, run);
  const { child, sseClients, stdoutBuffer, ...safeRun } = run;
  sendJson(response, 200, { run: safeRun, attached: true });
}

export async function handleRecover(request, response, url, ctx) {
  const id = decodeURIComponent(url.pathname.split("/").at(-2) || "");
  const run = ctx.runs.get(id);
  if (!run) throw new HttpError(404, "Run not found.");
  if (["running", "paused"].includes(run.status) && run.child) {
    throw new HttpError(409, `Run is ${run.status}; stop or finish it before continue.`);
  }

  const commandParts = splitCommandLine(ctx.env.MATH_AGENT_COMMAND || "uv run math-agent");
  const command = commandParts[0];
  const args = [
    ...commandParts.slice(1),
    "recover",
    "--out",
    run.out,
    "--thread",
    run.threadId || "default",
  ];

  const runDir = safeProjectPath(`runs/ui-server/${run.id}`);
  await mkdir(runDir, { recursive: true });
  const logPath = resolve(runDir, "recover.log");
  const logStream = createWriteStream(logPath, { flags: "a" });
  logStream.write(`$ ${command} ${args.join(" ")}\n\n`);

  run.status = "running";
  run.endedAt = null;
  run.exitCode = null;
  run.stdoutBuffer = "";
  run.logPath = logPath;
  run.sseClients = run.sseClients || new Set();
  run.command = `${command} ${args.join(" ")}`;

  const child = spawn(command, args, {
    cwd: projectRoot,
    env: ctx.buildChildEnv({
      MATH_AGENT_RAG_ENABLED: run.ragEnabled === false ? "0" : "1",
      MATH_AGENT_MAX_MODEL_ITERATIONS: String(run.iterationDepth || 3),
    }),
    windowsHide: true,
  });
  run.child = child;
  run.pid = child.pid;
  let childSettled = false;
  child.stdout.on("data", (chunk) => {
    run.stdoutBuffer = (run.stdoutBuffer + chunk.toString()).slice(-8192);
  });
  child.stderr.on("data", (chunk) => {
    run.stdoutBuffer = (run.stdoutBuffer + chunk.toString()).slice(-8192);
  });
  child.stdout.pipe(logStream);
  child.stderr.pipe(logStream);
  child.on("error", (error) => {
    if (childSettled) return;
    childSettled = true;
    run.status = "failed";
    run.endedAt = new Date().toISOString();
    logStream.write(`\n[spawn error] ${error.message}\n`);
    logStream.end();
    ctx.notifySse(run);
  });
  child.on("close", (code) => {
    if (childSettled) return;
    childSettled = true;
    if (run.status === "stopped") {
      // keep
    } else if (code === 0 && run.stdoutBuffer.includes("pipeline paused before human_review")) {
      run.status = "paused";
    } else if (code === 0 && run.stdoutBuffer.includes("pipeline rejected at human_review")) {
      run.status = "rejected";
    } else if (run.stdoutBuffer.includes("[DEGRADED]")) {
      run.status = "degraded";
    } else if (run.stdoutBuffer.includes("[BLOCKED]")) {
      run.status = "failed";
    } else {
      run.status = code === 0 ? "completed" : "failed";
    }
    run.exitCode = code;
    run.endedAt = new Date().toISOString();
    logStream.write(`\n[exit ${code}] [status ${run.status}]\n`);
    logStream.end();
    ctx.notifySse(run);
  });

  const { child: _c, sseClients, stdoutBuffer, ...safeRun } = run;
  sendJson(response, 200, { run: safeRun });
}

export async function handleRunsHistory(request, response) {
  const runsRoot = safeProjectPath("runs");
  let names = [];
  try {
    names = await readdir(runsRoot);
  } catch {
    sendJson(response, 200, { runs: [] });
    return;
  }
  const items = [];
  for (const name of names) {
    if (name === "ui-server" || name === "rag.sqlite") continue;
    const dir = join(runsRoot, name);
    let st;
    try {
      st = await stat(dir);
    } catch {
      continue;
    }
    if (!st.isDirectory()) continue;
    const supervisor = await readJsonSafe(join(dir, "supervisor.json"));
    const failure = await readJsonSafe(join(dir, "failure.json"));
    const completion = await readJsonSafe(join(dir, "completion.json"));
    if (!supervisor && !completion && !failure) continue;
    items.push({
      out: `runs/${name}`.replace(/\\/g, "/"),
      name,
      status: supervisor?.status || completion?.status || (failure ? "blocked" : "unknown"),
      last_node: supervisor?.last_node || failure?.node || null,
      ended_at: supervisor?.ended_at || null,
      started_at: supervisor?.started_at || null,
      message: supervisor?.message || failure?.message || null,
    });
  }
  items.sort((a, b) => String(b.ended_at || b.started_at || "").localeCompare(String(a.ended_at || a.started_at || "")));
  sendJson(response, 200, { runs: items.slice(0, 40) });
}

export async function handleArtifactFile(request, response, url) {
  const out = url.searchParams.get("out") || "runs/ui-latest";
  const name = (url.searchParams.get("name") || "").replace(/\\/g, "/");
  if (!name || name.includes("..") || name.startsWith("/") || name.includes("\0")) {
    throw new HttpError(400, "Invalid file name.");
  }
  const outDir = safeProjectPath(out);
  const filePath = resolve(outDir, name);
  const rel = relative(outDir, filePath).replace(/\\/g, "/");
  if (isAbsolute(rel) || rel === ".." || rel.startsWith("../") || rel.includes("/../")) {
    throw new HttpError(403, "Path is outside the output directory.");
  }
  const body = await readFile(filePath);
  const ext = name.includes(".") ? name.slice(name.lastIndexOf(".")).toLowerCase() : "";
  const types = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".pdf": "application/pdf",
    ".md": "text/markdown; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".py": "text/x-python; charset=utf-8",
  };
  response.writeHead(200, { "Content-Type": types[ext] || "application/octet-stream" });
  response.end(body);
}
