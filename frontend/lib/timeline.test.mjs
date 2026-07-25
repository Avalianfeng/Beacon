import test from "node:test";
import assert from "node:assert/strict";
import { buildHumanTimeline, formatDurationZh, titleForNode } from "./timeline.mjs";

test("buildHumanTimeline 把 trace 节点译成人话事件", () => {
  const timeline = buildHumanTimeline({
    llm_calls: 3,
    llm_failures: 1,
    llm_timeouts: 1,
    nodes: [
      { name: "figure_analysis", duration_ms: 13283 },
      { name: "writer_section", duration_ms: 179614 },
    ],
    llm_attempt_records: [
      {
        model: "openai/glm-5.2",
        profile: "long",
        status: "timeout",
        latency_ms: 240000,
        error_kind: "LLMTimeoutError",
      },
    ],
  });
  assert.equal(timeline.stats.node_count, 2);
  assert.equal(timeline.latest_node, "writer_section");
  assert.equal(titleForNode("writer_section"), "撰写论文章节");
  assert.match(formatDurationZh(179614), /分/);
  const titles = timeline.events.map((e) => e.title);
  assert.ok(titles.includes("解读图表"));
  assert.ok(titles.includes("撰写论文章节"));
  assert.ok(titles.includes("AI 响应超时"));
  assert.equal(timeline.events.find((e) => e.kind === "llm")?.status, "timeout");
});

test("buildHumanTimeline 在无 trace 时返回空结构", () => {
  const timeline = buildHumanTimeline(null);
  assert.deepEqual(timeline.events, []);
  assert.equal(timeline.stats.event_count, 0);
  assert.equal(timeline.latest_node, null);
});
