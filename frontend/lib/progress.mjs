/**
 * 运行进度聚合：把 supervisor / failure / checkpoint 翻译成非技术用户可读的 DTO。
 */

export const MACRO_STAGES = [
  {
    id: "understand",
    label: "理解题目",
    nodes: ["analyst", "blueprint_critic"],
  },
  {
    id: "model",
    label: "建立模型",
    nodes: [
      "modeler",
      "modeler_derivation",
      "modeler_consistency",
      "model_critic",
      "advance_stage",
    ],
  },
  {
    id: "compute",
    label: "计算验证",
    nodes: [
      "coder",
      "coder_generate",
      "coder_execute",
      "model_code_consistency",
      "sensitivity",
      "sensitivity_code_generate",
      "sensitivity_code_execute",
      "sensitivity_interpret",
    ],
  },
  {
    id: "figures",
    label: "图表",
    nodes: ["figure_pipeline", "figure_critic", "figure_analysis"],
  },
  {
    id: "write",
    label: "写论文",
    nodes: [
      "writer",
      "writer_section",
      "paper_critic",
      "table_assembler",
      "evaluation",
      "human_review",
    ],
  },
  {
    id: "finish",
    label: "收尾",
    nodes: ["latex", "finalizer"],
  },
];

const NODE_TO_MACRO = new Map();
for (const stage of MACRO_STAGES) {
  for (const node of stage.nodes) NODE_TO_MACRO.set(node, stage.id);
}

export function macroForNode(node) {
  if (!node) return null;
  const id = NODE_TO_MACRO.get(node);
  if (!id) return null;
  const index = MACRO_STAGES.findIndex((s) => s.id === id);
  const stage = MACRO_STAGES[index];
  return {
    macro_stage: stage.id,
    macro_label: stage.label,
    macro_index: index + 1,
    macro_total: MACRO_STAGES.length,
  };
}

/**
 * 将 failure / spawn 类英文信息映射为中文原因与建议动作。
 */
export function mapFailureMessage(message = "") {
  const text = String(message || "");
  const lower = text.toLowerCase();

  if (/provider not provided|llm provider/i.test(text)) {
    return {
      user_detail: "模型名称缺少服务商标识，当前 AI 接口无法识别。",
      suggested_action: "open_settings",
      suggested_label: "去检查模型设置",
      config_error: true,
    };
  }
  if (/supported api model names|you passed/i.test(text)) {
    return {
      user_detail: "填写的模型名称不被当前 AI 服务支持，请改成服务商提供的正式名称。",
      suggested_action: "open_settings",
      suggested_label: "去检查模型设置",
      config_error: true,
    };
  }
  if (/connection error|econnrefused|actively refused|无法连接|connect/i.test(lower)) {
    return {
      user_detail: "连不上 AI 服务。请确认网络畅通，或到设置里检查服务地址是否正确、本地路由是否已启动。",
      suggested_action: "open_settings",
      suggested_label: "去检查服务地址",
      config_error: true,
    };
  }
  if (/spawn .* enoent|uv enoent|not recognized/i.test(lower)) {
    return {
      user_detail: "本机找不到运行工具（例如 uv）。请安装后重启软件，或在设置中指定正确的启动命令。",
      suggested_action: "open_settings",
      suggested_label: "去检查运行环境",
      config_error: true,
    };
  }
  if (/timeout|未返回|deadline/i.test(lower)) {
    return {
      user_detail: "AI 响应超时。可以稍后点「继续任务」再试，或在设置里适当加大超时时间。",
      suggested_action: "continue",
      suggested_label: "继续任务",
      config_error: false,
    };
  }
  if (/image_url|unknown variant `image_url`|vision/i.test(lower)) {
    return {
      user_detail: "当前模型不支持看图，图表步骤无法继续。请在设置里把「看图模型」改成支持图像的模型，或先换一个服务商。",
      suggested_action: "open_settings",
      suggested_label: "去检查模型设置",
      config_error: true,
    };
  }
  if (/json_invalid|validation error|invalid json/i.test(lower)) {
    return {
      user_detail: "模型返回的内容格式不正确。通常可以点「继续任务」让系统从断点再试。",
      suggested_action: "continue",
      suggested_label: "继续任务",
      config_error: false,
    };
  }
  if (/same node failed/i.test(lower)) {
    return {
      user_detail: "同一环节多次失败后已暂停自动重试。请先根据上方说明修好设置，再点继续。",
      suggested_action: "continue",
      suggested_label: "继续任务",
      config_error: false,
    };
  }
  if (text.trim()) {
    return {
      user_detail: "任务在当前步骤遇到问题，可先尝试继续；若反复失败请检查设置。",
      suggested_action: "continue",
      suggested_label: "继续任务",
      config_error: false,
    };
  }
  return {
    user_detail: "",
    suggested_action: null,
    suggested_label: null,
    config_error: false,
  };
}

function readHintNode(supervisor, failure, nextNode) {
  return nextNode || failure?.node || supervisor?.last_node || "";
}

/**
 * @param {object} input
 * @param {object|null} input.supervisor
 * @param {object|null} input.failure
 * @param {object|null} input.completion
 * @param {string} input.nextNode
 * @param {string} input.finalStatus
 * @param {boolean} input.checkpointExists
 * @param {object|null} input.snapshot  progress_snapshot.json
 * @param {object|null} input.memoryRun  内存中的 UI run
 * @param {string} input.out
 * @param {string} input.thread
 */
export function buildProgressDto(input) {
  const supervisor = input.supervisor || null;
  const failure = input.failure || null;
  const completion = input.completion || null;
  const snapshot = input.snapshot || null;
  const memoryRun = input.memoryRun || null;
  const nextNode = input.nextNode || snapshot?.next_node || "";
  const finalStatus = input.finalStatus || completion?.status || "";
  const checkpointExists = Boolean(input.checkpointExists);
  const hintNode = readHintNode(supervisor, failure, nextNode);
  const macro = macroForNode(hintNode) || {
    macro_stage: "understand",
    macro_label: "准备中",
    macro_index: 0,
    macro_total: MACRO_STAGES.length,
  };

  const mapped = mapFailureMessage(failure?.message || supervisor?.message || "");
  let user_status = "idle";
  let user_title = "尚未开始";
  let user_detail = "上传题目后，点击「开始生成论文」。";
  let suggested_action = "start";
  let suggested_label = "开始生成论文";
  let can_continue = false;
  let can_stop = false;
  let can_approve = false;

  const memStatus = memoryRun?.status || "";
  const supStatus = supervisor?.status || "";
  const mode = supervisor?.mode || "";

  if (memStatus === "running" || (supStatus === "running" && memStatus !== "stopped")) {
    user_status = mode === "recover" ? "recovering" : "running";
    user_title = mode === "recover" ? "正在从中断处继续…" : "正在生成中…";
    user_detail = macro.macro_index
      ? `当前进度：${macro.macro_label}。完整流程可能需要数十分钟到数小时，请耐心等待。`
      : "任务已启动，正在准备中。";
    suggested_action = "stop";
    suggested_label = "停止";
    can_stop = true;
    can_continue = false;
  } else if (memStatus === "paused" || supStatus === "paused" || nextNode === "human_review") {
    user_status = "needs_review";
    user_title = "论文草稿已好，请你确认";
    user_detail = "系统已暂停，等待你审核后再生成最终稿。";
    suggested_action = "approve";
    suggested_label = "通过并继续";
    can_approve = true;
    can_continue = false;
  } else if (finalStatus === "completed" || memStatus === "completed" || supStatus === "completed") {
    user_status = "completed";
    user_title = "已完成";
    user_detail = "论文与相关产物已生成，可以在下方查看。";
    suggested_action = "view_paper";
    suggested_label = "查看论文";
    macro.macro_index = MACRO_STAGES.length;
    macro.macro_label = "收尾";
    macro.macro_stage = "finish";
  } else if (finalStatus === "degraded" || memStatus === "degraded" || supStatus === "degraded") {
    user_status = "degraded";
    user_title = "已出稿，但未达到质量门禁";
    const issues = Array.isArray(completion?.issues) ? completion.issues : [];
    user_detail = issues.length
      ? `论文可以查看，但仍有问题需要关注：${issues.slice(0, 3).join("；")}`
      : "论文可以查看，但篇幅或证据未完全达到竞赛门禁要求。";
    suggested_action = "view_paper";
    suggested_label = "仍打开论文";
  } else if (memStatus === "rejected" || finalStatus === "rejected" || supStatus === "rejected") {
    user_status = "rejected";
    user_title = "已驳回";
    user_detail = "人工审核未通过，未生成最终论文稿。";
    suggested_action = "start";
    suggested_label = "重新开始";
  } else if (memStatus === "stopped") {
    user_status = "stopped";
    user_title = "已停止";
    user_detail = checkpointExists
      ? "任务已手动停止。进度已保存，可以点「继续任务」接着做。"
      : "任务已停止。";
    suggested_action = checkpointExists ? "continue" : "start";
    suggested_label = checkpointExists ? "继续任务" : "开始生成论文";
    can_continue = checkpointExists;
  } else if (supStatus === "blocked" || memStatus === "failed" || failure) {
    user_status = mapped.config_error ? "needs_settings" : "needs_attention";
    user_title = "任务暂时中断";
    user_detail = mapped.user_detail || "运行遇到问题，已停在当前步骤。";
    suggested_action = mapped.suggested_action || "continue";
    suggested_label = mapped.suggested_label || "继续任务";
    can_continue = !mapped.config_error || suggested_action === "continue";
    if (mapped.config_error) {
      can_continue = true; // 仍允许用户改完设置后继续
    }
  } else if (supStatus === "stale") {
    user_status = "needs_attention";
    user_title = "上次异常退出";
    user_detail = "检测到上次运行未正常结束。进度通常还在，可以点「继续任务」。";
    suggested_action = "continue";
    suggested_label = "继续任务";
    can_continue = checkpointExists;
  } else if (checkpointExists && nextNode) {
    user_status = "needs_attention";
    user_title = "有未完成的任务";
    user_detail = `上次做到「${macro.macro_label}」附近，可以继续。`;
    suggested_action = "continue";
    suggested_label = "继续任务";
    can_continue = true;
  }

  const queueHint = formatQueueHint(snapshot);

  return {
    out: input.out,
    thread: input.thread || "default",
    user_status,
    user_title,
    user_detail: queueHint ? `${user_detail} ${queueHint}` : user_detail,
    suggested_action,
    suggested_label,
    ...macro,
    can_continue,
    can_stop,
    can_approve,
    stages: MACRO_STAGES.map((s, i) => ({
      id: s.id,
      label: s.label,
      index: i + 1,
      state:
        finalStatus === "completed" || user_status === "completed"
          ? "done"
          : i + 1 < macro.macro_index
            ? "done"
            : i + 1 === macro.macro_index
              ? user_status === "running" || user_status === "recovering"
                ? "active"
                : user_status === "needs_review" && s.id === "write"
                  ? "paused"
                  : "active"
              : "pending",
    })),
    tech: {
      supervisor,
      failure,
      completion,
      next_node: nextNode || null,
      final_status: finalStatus || null,
      checkpoint_exists: checkpointExists,
      snapshot,
      memory_run_status: memStatus || null,
      hint_node: hintNode || null,
    },
  };
}

function formatQueueHint(snapshot) {
  if (!snapshot || typeof snapshot !== "object") return "";
  const parts = [];
  if (snapshot.coder_queue_total != null && snapshot.coder_queue_done != null) {
    parts.push(`代码任务 ${snapshot.coder_queue_done}/${snapshot.coder_queue_total}`);
  } else if (snapshot.coder_queue_len != null) {
    parts.push(`代码队列 ${snapshot.coder_queue_len} 项`);
  }
  if (snapshot.writer_sections_remaining != null) {
    parts.push(`章节剩余 ${snapshot.writer_sections_remaining}`);
  }
  if (snapshot.figure_queue_len != null) {
    parts.push(`图任务 ${snapshot.figure_queue_len}`);
  }
  if (snapshot.stage_target) {
    parts.push(`模型阶段 ${snapshot.stage_target}`);
  }
  return parts.length ? `（${parts.join(" · ")}）` : "";
}
