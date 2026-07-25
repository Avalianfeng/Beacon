/**
 * 将 trace.json 聚合成非技术用户可读的时间线事件（Step 1：仅 DTO，不改 UI）。
 */

import { MACRO_STAGES, macroForNode } from "./progress.mjs";

/** 写作分组名 → 中文（与 writer_section SectionGroup.name 对齐） */
export const WRITER_SECTION_TITLES = {
  abstract_problem: "摘要与问题重述",
  assumptions_notation: "假设与符号说明",
  model: "模型建立",
  solution: "模型求解",
  sensitivity: "敏感性分析",
  conclusion: "结论",
  references: "参考文献",
};

/** @type {Record<string, string>} */
const NODE_TITLES = {
  analyst: "理解并拆解题目",
  blueprint_critic: "检查题目理解是否靠谱",
  modeler: "建立数学模型",
  modeler_derivation: "推导模型细节",
  modeler_consistency: "检查模型内部一致性",
  model_critic: "评审模型",
  advance_stage: "推进模型阶段",
  coder: "准备计算任务",
  coder_generate: "生成计算代码",
  coder_execute: "运行计算代码",
  model_code_consistency: "核对模型与代码是否一致",
  sensitivity: "准备敏感性分析",
  sensitivity_code_generate: "生成敏感性脚本",
  sensitivity_code_execute: "运行敏感性分析",
  sensitivity_interpret: "解读敏感性结果",
  figure_pipeline: "准备图表任务",
  figure_critic: "检查图表质量",
  figure_analysis: "解读图表",
  writer: "准备论文写作",
  writer_section: "撰写论文章节",
  paper_critic: "评审论文草稿",
  table_assembler: "整理表格",
  evaluation: "综合评分",
  human_review: "等待人工确认",
  latex: "排版编译",
  finalizer: "收尾检查",
};

/**
 * @param {number} ms
 * @returns {string}
 */
export function formatDurationZh(ms) {
  const n = Number(ms) || 0;
  if (n < 1000) return `${Math.round(n)} 毫秒`;
  if (n < 60_000) return `${(n / 1000).toFixed(n < 10_000 ? 1 : 0)} 秒`;
  const minutes = Math.floor(n / 60_000);
  const seconds = Math.round((n % 60_000) / 1000);
  if (seconds === 0) return `${minutes} 分钟`;
  return `${minutes} 分 ${seconds} 秒`;
}

/**
 * @param {string} node
 * @returns {string}
 */
export function titleForNode(node) {
  const name = String(node || "");
  if (NODE_TITLES[name]) return NODE_TITLES[name];
  const macro = macroForNode(name);
  if (macro?.macro_label) return `${macro.macro_label}（${name}）`;
  return name || "未知步骤";
}

/**
 * @param {object|null|undefined} trace
 * @param {{ limit?: number }} [opts]
 * @returns {{
 *   events: Array<{
 *     id: string,
 *     kind: "node"|"llm",
 *     node: string|null,
 *     title: string,
 *     detail: string,
 *     status: "ok"|"timeout"|"failed"|"info",
 *     duration_ms: number,
 *     model?: string|null,
 *   }>,
 *   stats: {
 *     llm_calls: number,
 *     llm_failures: number,
 *     llm_timeouts: number,
 *     node_count: number,
 *     event_count: number,
 *   },
 *   latest_node: string|null,
 *   latest_title: string|null,
 * }}
 */
export function buildHumanTimeline(trace, opts = {}) {
  const limit = Math.max(1, Number(opts.limit) || 80);
  const empty = {
    events: [],
    stats: {
      llm_calls: 0,
      llm_failures: 0,
      llm_timeouts: 0,
      node_count: 0,
      event_count: 0,
    },
    latest_node: null,
    latest_title: null,
  };
  if (!trace || typeof trace !== "object") return empty;

  /** @type {typeof empty.events} */
  const events = [];
  const nodes = Array.isArray(trace.nodes) ? trace.nodes : [];
  for (let i = 0; i < nodes.length; i += 1) {
    const item = nodes[i] || {};
    const node = String(item.name || "");
    const duration_ms = Number(item.duration_ms) || 0;
    const title = titleForNode(node);
    const macro = macroForNode(node);
    const stageHint = macro?.macro_label ? `（${macro.macro_label}）` : "";
    events.push({
      id: `node-${i}`,
      kind: "node",
      node: node || null,
      title,
      detail: `已完成${stageHint}，耗时 ${formatDurationZh(duration_ms)}`,
      status: "ok",
      duration_ms,
      model: null,
    });
  }

  // 把超时/失败调用附在时间线末尾附近（不打断节点主序），便于「刚发生了什么」看见卡点
  const attempts = Array.isArray(trace.llm_attempt_records) ? trace.llm_attempt_records : [];
  const notable = attempts.filter((a) => {
    const status = String(a?.status || "").toLowerCase();
    return status === "timeout" || status === "failed" || status === "error";
  });
  const notableTail = notable.slice(-12);
  for (let i = 0; i < notableTail.length; i += 1) {
    const a = notableTail[i] || {};
    const statusRaw = String(a.status || "").toLowerCase();
    const status = statusRaw === "timeout" ? "timeout" : "failed";
    const duration_ms = Number(a.latency_ms) || 0;
    const model = a.model ? String(a.model) : null;
    const profile = a.profile ? String(a.profile) : "";
    const title = status === "timeout" ? "AI 响应超时" : "AI 调用失败";
    const bits = [
      model ? `模型 ${model}` : null,
      profile ? `类型 ${profile}` : null,
      duration_ms ? `已等待 ${formatDurationZh(duration_ms)}` : null,
      a.error_kind ? String(a.error_kind) : null,
    ].filter(Boolean);
    events.push({
      id: `llm-${i}`,
      kind: "llm",
      node: null,
      title,
      detail: bits.join(" · ") || "调用未成功",
      status,
      duration_ms,
      model,
    });
  }

  const trimmed = events.length > limit ? events.slice(-limit) : events;
  const lastNode = [...nodes].reverse().find((n) => n?.name)?.name || null;

  return {
    events: trimmed,
    stats: {
      llm_calls: Number(trace.llm_calls) || 0,
      llm_failures: Number(trace.llm_failures) || 0,
      llm_timeouts: Number(trace.llm_timeouts) || 0,
      node_count: nodes.length,
      event_count: trimmed.length,
    },
    latest_node: lastNode ? String(lastNode) : null,
    latest_title: lastNode ? titleForNode(lastNode) : null,
  };
}

/** 供测试或调试：已知节点标题表是否覆盖 MACRO_STAGES */
export function knownTimelineNodes() {
  const fromMacro = MACRO_STAGES.flatMap((s) => s.nodes);
  return { fromMacro, titled: Object.keys(NODE_TITLES) };
}

/**
 * @param {string} section
 * @returns {string}
 */
export function titleForWriterSection(section) {
  const key = String(section || "");
  return WRITER_SECTION_TITLES[key] || key || "论文章节";
}

/**
 * Step4：无 trace / 旧 run / 仅有产物时的空态与降级说明。
 * @param {object} payload /api/artifacts 响应（或同形对象）
 * @returns {{
 *   mode: "ready"|"empty"|"degraded_no_trace"|"degraded_tech_only",
 *   title: string,
 *   body: string,
 *   openTech: boolean,
 * }}
 */
export function describeTimelineView(payload = {}) {
  const timeline = payload.timeline || null;
  const t = payload.traceSummary || null;
  const events = Array.isArray(timeline?.events) ? timeline.events : [];
  const techNodes = Array.isArray(t?.nodeDurations) ? t.nodeDurations.length : Number(t?.nodes) || 0;
  const techAttempts = Array.isArray(t?.attempts) ? t.attempts.length : 0;
  const hasHuman = events.length > 0;
  const hasTech = Boolean(t) && (techNodes > 0 || techAttempts > 0 || Number(t?.llmCalls) > 0);
  const mid = payload.intermediate || {};
  const hasArtifacts = Boolean(
    mid.hasPaper || mid.hasPdf || mid.hasBlueprint
    || (mid.figureCount || 0) > 0
    || (mid.scriptCount || 0) > 0,
  );

  if (hasHuman) {
    return {
      mode: "ready",
      title: "运行详情",
      body: "",
      openTech: false,
    };
  }

  if (hasTech) {
    return {
      mode: "degraded_tech_only",
      title: "运行详情（兼容旧记录）",
      body: "这份任务还没有可翻译的人话时间线，已为你展开下方技术明细。较新的运行会直接显示「刚完成了什么」。",
      openTech: true,
    };
  }

  if (hasArtifacts || (payload.exists && Array.isArray(payload.files) && payload.files.length > 0)) {
    return {
      mode: "degraded_no_trace",
      title: "没有可展示的运行轨迹",
      body: "目录里已有部分产物，但缺少或无法解析运行记录（trace）。可先查看「论文 / 图表」页；若任务未结束，点继续后会逐步补全这里的时间线。",
      openTech: false,
    };
  }

  return {
    mode: "empty",
    title: "还没有运行记录",
    body: "任务开始后，这里会按时间列出刚完成的步骤。完整流程可能需要数十分钟，请耐心等待。",
    openTech: false,
  };
}

/**
 * Step3：从 progress snapshot 生成「正在等 AI / 当前节」提示。
 * @param {object} input
 * @param {object|null} [input.snapshot]
 * @param {string} [input.nextNode]
 * @param {boolean} [input.workerBusy]
 * @param {boolean} [input.running]  UI 认为任务在跑（running/recovering）
 */
export function buildLiveWaitHint(input = {}) {
  const snapshot = input.snapshot || null;
  const nextNode = String(input.nextNode || snapshot?.next_node || "");
  const section = String(snapshot?.writer_section_current || "");
  const remaining = Number(snapshot?.writer_sections_remaining);
  const workerBusy = Boolean(input.workerBusy);
  const running = Boolean(input.running) || workerBusy;
  const writing = nextNode === "writer_section" && Boolean(section);

  if (!writing && !workerBusy) {
    return {
      active: false,
      waiting_api: false,
      node: nextNode || null,
      section: null,
      section_title: null,
      remaining: Number.isFinite(remaining) ? remaining : null,
      message: "",
    };
  }

  const sectionTitle = section ? titleForWriterSection(section) : null;
  const remText = Number.isFinite(remaining) ? `，本章后大约还剩 ${Math.max(0, remaining - 1)} 节` : "";
  let message = "";
  if (writing && running) {
    message = `正在等待 AI 撰写「${sectionTitle}」${remText}。完整一节常需数分钟，请耐心等待。`;
  } else if (writing) {
    message = `下一节将写「${sectionTitle}」${remText}。`;
  } else if (running) {
    message = `后台任务进行中（${titleForNode(nextNode) || "当前步骤"}）。`;
  }

  return {
    active: true,
    waiting_api: Boolean(writing && running),
    node: nextNode || null,
    section: section || null,
    section_title: sectionTitle,
    remaining: Number.isFinite(remaining) ? remaining : null,
    message,
  };
}
