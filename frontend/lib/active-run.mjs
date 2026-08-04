/**
 * 与 Python ``math_agent.run_pointer`` 对齐：发现进行中或最近一次运行目录。
 */
import { existsSync } from "node:fs";
import { readdir, readFile, stat } from "node:fs/promises";
import { join, relative, resolve } from "node:path";

export const ACTIVE_FILENAME = ".beacon-active.json";

function toPosix(path) {
  return path.replace(/\\/g, "/");
}

async function readJson(path) {
  try {
    return JSON.parse(await readFile(path, "utf8"));
  } catch {
    return null;
  }
}

function parseUtc(value) {
  if (!value || typeof value !== "string") return null;
  const ms = Date.parse(value.replace(/Z$/, "+00:00"));
  return Number.isFinite(ms) ? ms : null;
}

/** 轻量 reconcile：无 psutil 时用心跳年龄判断陈旧（与 Python 默认 30s 对齐）。 */
export function reconcileSupervisorState(payload, { now = Date.now(), staleAfterMs = 30_000 } = {}) {
  if (!payload || typeof payload !== "object") return payload;
  const state = { ...payload };
  if (!["starting", "running"].includes(state.status)) return state;
  const heartbeat = parseUtc(state.heartbeat_at);
  if (heartbeat != null && now - heartbeat > staleAfterMs) {
    state.status = "stale";
    state.stale_reason = `heartbeat_expired:${Math.floor((now - heartbeat) / 1000)}s`;
  }
  return state;
}

async function collectSupervisorFiles(runsRoot, maxDepth = 3) {
  const found = [];
  async function walk(dir, depth) {
    if (depth > maxDepth) return;
    let entries;
    try {
      entries = await readdir(dir, { withFileTypes: true });
    } catch {
      return;
    }
    for (const entry of entries) {
      const full = join(dir, entry.name);
      if (entry.isFile() && entry.name === "supervisor.json") {
        found.push(full);
      } else if (entry.isDirectory() && !entry.name.startsWith(".")) {
        // ui-server 元数据目录通常没有 supervisor.json；仍允许浅层扫描
        await walk(full, depth + 1);
      }
    }
  }
  await walk(runsRoot, 0);
  return found;
}

async function mtimeMs(path) {
  try {
    return (await stat(path)).mtimeMs;
  } catch {
    return 0;
  }
}

/**
 * @param {string} projectRoot
 * @returns {Promise<{ outAbs: string, outRel: string, thread: string, how: string, supervisor: object|null, nextNode: string }|null>}
 */
export async function resolveActiveRun(projectRoot) {
  const runsRoot = resolve(projectRoot, "runs");
  const supervisors = await collectSupervisorFiles(runsRoot);

  let bestRunning = null;
  for (const supPath of supervisors) {
    const payload = await readJson(supPath);
    if (!payload) continue;
    const state = reconcileSupervisorState(payload);
    if (!["starting", "running"].includes(state.status)) continue;
    const score = await mtimeMs(supPath);
    if (!bestRunning || score > bestRunning.score) {
      bestRunning = { score, supPath, state, outAbs: resolve(supPath, "..") };
    }
  }
  if (bestRunning) {
    return finalize(projectRoot, bestRunning.outAbs, bestRunning.state, "active-running");
  }

  const pointer = await readJson(join(runsRoot, ACTIVE_FILENAME));
  if (pointer?.out && existsSync(pointer.out)) {
    const outAbs = resolve(pointer.out);
    const state = reconcileSupervisorState(await readJson(join(outAbs, "supervisor.json")));
    return finalize(projectRoot, outAbs, state, "pointer", pointer.thread);
  }

  let bestRecent = null;
  for (const supPath of supervisors) {
    const outAbs = resolve(supPath, "..");
    const score = Math.max(await mtimeMs(supPath), await mtimeMs(join(outAbs, "checkpoints.sqlite")));
    if (!bestRecent || score > bestRecent.score) {
      bestRecent = { score, outAbs, state: await readJson(supPath) };
    }
  }
  if (bestRecent) {
    return finalize(
      projectRoot,
      bestRecent.outAbs,
      reconcileSupervisorState(bestRecent.state),
      "recent",
    );
  }
  return null;
}

async function finalize(projectRoot, outAbs, supervisor, how, threadHint) {
  const outRel = toPosix(relative(projectRoot, outAbs)) || ".";
  const thread = threadHint || supervisor?.thread || "default";
  return {
    outAbs,
    outRel,
    thread: String(thread),
    how,
    supervisor: supervisor || null,
    nextNode: await resolveNextNode(outAbs, supervisor),
  };
}

/**
 * 运行中优先 progress.jsonl（本 epoch）；终态可用 supervisor.last_node 兜底。
 * 轮询刷新必须走同一规则，否则会用陈旧 last_node 盖掉接回时的正确节点。
 */
export async function resolveNextNode(outAbs, supervisor) {
  const status = String(supervisor?.status || "");
  if (["starting", "running", "paused"].includes(status)) {
    return String((await peekProgressNode(outAbs)) || "");
  }
  return String(supervisor?.last_node || (await peekProgressNode(outAbs)) || "");
}

/**
 * 与 Python ``events_since_last_boundary`` 对齐：忽略上一 attempt 的节点事件。
 * @param {string} text progress.jsonl 全文
 */
export function peekProgressNodeFromText(text) {
  const lines = String(text || "")
    .trim()
    .split(/\r?\n/)
    .filter(Boolean);
  let start = 0;
  for (let i = 0; i < lines.length; i += 1) {
    try {
      if (JSON.parse(lines[i]).type === "run_boundary") start = i + 1;
    } catch {
      /* skip */
    }
  }
  for (let i = lines.length - 1; i >= start; i -= 1) {
    try {
      const event = JSON.parse(lines[i]);
      if (event.type === "node_start" && event.node) return String(event.node);
      if (event.type === "node_end" && event.node) return String(event.node);
    } catch {
      /* skip */
    }
  }
  return "";
}

async function peekProgressNode(outAbs) {
  try {
    const text = await readFile(join(outAbs, "progress.jsonl"), "utf8");
    return peekProgressNodeFromText(text);
  } catch {
    return "";
  }
}

export function mapSupervisorToUiStatus(supervisor) {
  if (!supervisor) return "failed";
  const status = String(supervisor.status || "");
  if (["starting", "running"].includes(status)) return "running";
  if (status === "paused") return "paused";
  if (status === "blocked") return "blocked";
  if (status === "completed") return "completed";
  if (status === "degraded") return "degraded";
  if (status === "rejected") return "rejected";
  if (status === "stale") {
    // 心跳过期但仍可能有 checkpoint，交给前端当 failed/blocked 处理
    return "failed";
  }
  return status || "failed";
}

export function adoptedRunId(outRel) {
  const slug = toPosix(outRel).replace(/[^a-zA-Z0-9._-]+/g, "-").slice(0, 48);
  return `adopted-${slug || "run"}`;
}
