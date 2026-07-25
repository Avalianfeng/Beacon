import test from "node:test";
import assert from "node:assert/strict";
import {
  buildHumanTimeline,
  buildLiveWaitHint,
  formatDurationZh,
  titleForNode,
  titleForWriterSection,
} from "./timeline.mjs";

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

test("buildLiveWaitHint 在写作中且运行时提示等待 AI", () => {
  assert.equal(titleForWriterSection("assumptions_notation"), "假设与符号说明");
  const live = buildLiveWaitHint({
    snapshot: {
      next_node: "writer_section",
      writer_section_current: "assumptions_notation",
      writer_sections_remaining: 5,
    },
    workerBusy: true,
    running: true,
  });
  assert.equal(live.active, true);
  assert.equal(live.waiting_api, true);
  assert.equal(live.section, "assumptions_notation");
  assert.match(live.message, /假设与符号说明/);
  assert.match(live.message, /等待 AI/);
});

test("buildLiveWaitHint 空闲时不制造假忙碌", () => {
  const live = buildLiveWaitHint({
    snapshot: { next_node: "human_review", writer_sections_remaining: 0 },
    workerBusy: false,
    running: false,
  });
  assert.equal(live.active, false);
  assert.equal(live.waiting_api, false);
  assert.equal(live.message, "");
});
