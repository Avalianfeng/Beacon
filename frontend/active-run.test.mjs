import test from "node:test";
import assert from "node:assert/strict";
import { mkdir, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { randomUUID } from "node:crypto";
import {
  mapSupervisorToUiStatus,
  peekProgressNodeFromText,
  reconcileSupervisorState,
  resolveActiveRun,
  resolveNextNode,
} from "./lib/active-run.mjs";

test("reconcile marks expired heartbeat as stale", () => {
  const state = reconcileSupervisorState(
    {
      status: "running",
      heartbeat_at: "2000-01-01T00:00:00+00:00",
    },
    { now: Date.now(), staleAfterMs: 1000 },
  );
  assert.equal(state.status, "stale");
});

test("mapSupervisorToUiStatus covers blocked", () => {
  assert.equal(mapSupervisorToUiStatus({ status: "blocked" }), "blocked");
  assert.equal(mapSupervisorToUiStatus({ status: "starting" }), "running");
});

test("resolveActiveRun prefers running supervisor", async () => {
  const root = join(tmpdir(), `beacon-active-${randomUUID()}`);
  const out = join(root, "runs", "demo");
  await mkdir(out, { recursive: true });
  await writeFile(
    join(out, "supervisor.json"),
    JSON.stringify({
      status: "running",
      thread: "default",
      heartbeat_at: new Date().toISOString(),
      last_node: "modeler",
    }),
    "utf8",
  );
  const found = await resolveActiveRun(root);
  assert.ok(found);
  assert.equal(found.how, "active-running");
  assert.match(found.outRel.replace(/\\/g, "/"), /runs\/demo$/);
});

test("peekProgressNodeFromText ignores nodes before run_boundary", () => {
  const text = [
    JSON.stringify({ type: "node_end", node: "writer" }),
    JSON.stringify({ type: "run_boundary", attempt: 2 }),
    JSON.stringify({ type: "node_start", node: "modeler" }),
  ].join("\n");
  assert.equal(peekProgressNodeFromText(text), "modeler");
});

test("peekProgressNodeFromText returns empty right after boundary", () => {
  const text = [
    JSON.stringify({ type: "node_end", node: "writer" }),
    JSON.stringify({ type: "run_boundary", attempt: 3 }),
  ].join("\n");
  assert.equal(peekProgressNodeFromText(text), "");
});

test("resolveActiveRun prefers progress after boundary over stale last_node", async () => {
  const root = join(tmpdir(), `beacon-active-${randomUUID()}`);
  const out = join(root, "runs", "recover");
  await mkdir(out, { recursive: true });
  await writeFile(
    join(out, "supervisor.json"),
    JSON.stringify({
      status: "running",
      thread: "default",
      heartbeat_at: new Date().toISOString(),
      last_node: "writer",
    }),
    "utf8",
  );
  await writeFile(
    join(out, "progress.jsonl"),
    [
      JSON.stringify({ type: "node_end", node: "writer" }),
      JSON.stringify({ type: "run_boundary", attempt: 2 }),
      JSON.stringify({ type: "node_start", node: "modeler" }),
    ].join("\n") + "\n",
    "utf8",
  );
  const found = await resolveActiveRun(root);
  assert.ok(found);
  assert.equal(found.nextNode, "modeler");
});

test("resolveNextNode keeps progress node across poll-style refresh", async () => {
  const out = join(tmpdir(), `beacon-next-${randomUUID()}`);
  await mkdir(out, { recursive: true });
  const supervisor = {
    status: "running",
    last_node: "writer",
    heartbeat_at: new Date().toISOString(),
  };
  await writeFile(
    join(out, "progress.jsonl"),
    [
      JSON.stringify({ type: "run_boundary", attempt: 2 }),
      JSON.stringify({ type: "node_start", node: "model_critic" }),
    ].join("\n") + "\n",
    "utf8",
  );
  assert.equal(await resolveNextNode(out, supervisor), "model_critic");
  // 模拟第二次轮询：last_node 仍陈旧，结果不得回退
  assert.equal(await resolveNextNode(out, supervisor), "model_critic");
});
