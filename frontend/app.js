const runButton = document.querySelector("#runPipeline");
const importDemoButton = document.querySelector("#importDemo");
const chooseProblemButton = document.querySelector("#chooseProblem");
const resetPipelineButton = document.querySelector("#resetPipeline");
const openOutputsButton = document.querySelector("#openOutputs");
const currentStage = document.querySelector("#currentStage");
const nodeProgress = document.querySelector("#nodeProgress");
const qualityScore = document.querySelector("#qualityScore");
const outputSummary = document.querySelector("#outputSummary");
const problemTitle = document.querySelector("#problemTitle");
const problemBrief = document.querySelector("#problemBrief");
const problemBadge = document.querySelector("#problemBadge");
const artifactPreview = document.querySelector("#artifactPreview");
const insightMeta = document.querySelector("#insightMeta");
const insightBody = document.querySelector("#insightBody");
const commandPreview = document.querySelector("#commandPreview");
const outputDir = document.querySelector("#outputDir");
const threadId = document.querySelector("#threadId");
const iterationDepth = document.querySelector("#iterationDepth");
const iterationValue = document.querySelector("#iterationValue");
const ragToggle = document.querySelector("#ragToggle");
const confirmProblemToggle = document.querySelector("#confirmProblemToggle");
const hitlToggle = document.querySelector("#hitlToggle");
const forceToggle = document.querySelector("#forceToggle");
const parseQualityBanner = document.querySelector("#parseQualityBanner");
const parseQualityTitle = document.querySelector("#parseQualityTitle");
const parseQualityDetail = document.querySelector("#parseQualityDetail");
const parseQualityPathRow = document.querySelector("#parseQualityPathRow");
const parseQualityPath = document.querySelector("#parseQualityPath");
const copyParsedMdPath = document.querySelector("#copyParsedMdPath");
const knowledgeBadge = document.querySelector("#knowledgeBadge");
const runState = document.querySelector("#runState");
const uploadZone = document.querySelector("#uploadZone");
const problemFile = document.querySelector("#problemFile");
const uploadTitle = document.querySelector("#uploadTitle");
const uploadMeta = document.querySelector("#uploadMeta");
const attachmentZone = document.querySelector("#attachmentZone");
const attachmentFile = document.querySelector("#attachmentFile");
const attachmentList = document.querySelector("#attachmentList");
const toast = document.querySelector("#toast");
const tabButtons = document.querySelectorAll("[data-tab]");
const navLinks = document.querySelectorAll(".nav-list a");
const templateButtons = document.querySelectorAll("[data-template]");
const templateHint = document.querySelector("#templateHint");
const pipelineItems = [...document.querySelectorAll("#pipelineList li")];
const onboardingOverlay = document.querySelector("#onboardingOverlay");
const onboardingBody = document.querySelector("#onboardingBody");
const onboardingTitle = document.querySelector("#onboardingTitle");
const onboardingSubtitle = document.querySelector("#onboardingSubtitle");
const onboardingPrev = document.querySelector("#onboardingPrev");
const onboardingNext = document.querySelector("#onboardingNext");
const stepDots = document.querySelectorAll(".step-dot");
const readinessBadge = document.querySelector("#readinessBadge");
const importStep = document.querySelector("#importStep");
const reviewStep = document.querySelector("#reviewStep");
const runStep = document.querySelector("#runStep");
const reviewStepHint = document.querySelector("#reviewStepHint");
const runStepHint = document.querySelector("#runStepHint");
const settingsPanel = document.querySelector("#settings");
const settingsContent = document.querySelector("#settingsContent");
const settingsSave = document.querySelector("#settingsSave");
const settingsReset = document.querySelector("#settingsReset");
const settingsNavButtons = document.querySelectorAll("[data-settings-tab]");
const dashboardSections = document.querySelectorAll(
  "#workspace > .topbar, #workspace > .start-guide, #workspace > .status-strip, #workspace > .layout-grid",
);

const stages = ["Analyst", "Blueprint Critic", "Modeler", "Model Critic", "Coder", "Code Consistency", "Sensitivity", "Figure Pipeline", "Writer", "Paper Critic", "Table Assembler", "Evaluation", "Human Review", "LaTeX"];
const stageLogNames = ["analyst", "blueprint_critic", "modeler", "model_critic", "coder", "model_code_consistency", "sensitivity", "figure_pipeline", "writer", "paper_critic", "table_assembler", "evaluation", "human_review", "latex"];
const MAX_PROBLEM_TEXT_CHARS = 400_000;
let latestParsedMdPath = "";
let problemConfirmArmed = false;
const templateHints = {
  default: "适配建模论文、代码、敏感性分析与 LaTeX 编译流程。",
  gmcm: "启用国赛论文封面字段，命令会追加 --template gmcm。",
};

let stageIndex = -1;
let activeTemplate = "default";
let toastTimer;
let currentRunId = null;
let currentRunStatus = null;
let pollTimer = null;
let logStream = null;
let lastArtifacts = null;
let currentFixturePath = null;
let uploadedAttachments = [];

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
  return payload;
}

function showToast(message) {
  toast.textContent = message;
  toast.classList.add("show");
  window.clearTimeout(toastTimer);
  toastTimer = window.setTimeout(() => toast.classList.remove("show"), 2400);
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[<>&"']/g, (char) => ({
    "<": "&lt;", ">": "&gt;", "&": "&amp;", '"': "&quot;", "'": "&#39;",
  })[char]);
}

function setPreview(title, body, extra = "") {
  artifactPreview.innerHTML = `<h3>${escapeHtml(title)}</h3><p>${escapeHtml(body)}</p>${extra}`;
}

let lastInsightStamp = "";
let insightTimer = 0;

async function refreshInsightPane() {
  if (!insightBody || !outputDir) return;
  try {
    const payload = await api(`/api/insights?out=${encodeURIComponent(outputDir.value || "runs/ui-latest")}`);
    const stamp = `${payload.updatedAt || ""}|${payload.headline || ""}|${payload.body?.length || 0}`;
    if (stamp === lastInsightStamp) return;
    lastInsightStamp = stamp;
    if (!payload.exists) {
      insightMeta.textContent = "尚无评审/校验正文";
      return;
    }
    insightMeta.textContent = [payload.headline, payload.updatedAt, payload.path]
      .filter(Boolean)
      .join(" · ");
    const steps = Array.isArray(payload.recentSteps) ? payload.recentSteps : [];
    const listing = steps.length
      ? steps.map((row) => `${row.seq ?? "?"}  ${row.node || "?"}  ${row.dir || ""}`).join("\n") + "\n\n"
      : "";
    insightBody.textContent = listing + (payload.body || "");
  } catch {
    // 观察窗失败不影响主流程
  }
}

function startInsightPolling() {
  window.clearInterval(insightTimer);
  refreshInsightPane().catch(() => {});
  insightTimer = window.setInterval(() => {
    refreshInsightPane().catch(() => {});
  }, 4000);
}

function setRunLogPreview(run) {
  const log = run.log ? run.log.replace(/[<>&]/g, (char) => ({ "<": "&lt;", ">": "&gt;", "&": "&amp;" })[char]) : "暂无日志。";
  artifactPreview.innerHTML = `
    <h3>运行日志</h3>
    <p>${escapeHtml(run.command || "math-agent run")}</p>
    <pre class="log-preview">${log}</pre>
  `;
}

function updatePipeline(mode = "local") {
  pipelineItems.forEach((item, index) => {
    item.classList.toggle("done", index < stageIndex);
    item.classList.toggle("active", index === stageIndex && stageIndex < stages.length);
    item.classList.toggle("paused", mode === "paused" && index === stageIndex);
  });
  const isComplete = stageIndex >= stages.length;
  currentStage.textContent = stageIndex < 0
    ? "Ready"
    : isComplete
      ? "Completed"
      : (mode === "paused" ? "Paused" : stages[Math.min(stageIndex, stages.length - 1)]);
  nodeProgress.textContent = `${Math.max(0, Math.min(stageIndex + 1, stages.length))} / ${stages.length}`;
  const actualScore = lastArtifacts?.stateSummary?.evaluation_overall;
  qualityScore.textContent = isComplete && Number.isFinite(Number(actualScore))
    ? Number(actualScore).toFixed(2)
    : "--";
  if (mode === "running") {
    runButton.textContent = "正在生成…";
  } else if (isComplete) {
    runButton.textContent = "重新生成";
  } else if (problemConfirmArmed) {
    runButton.textContent = "题面无误，开始生成";
  } else {
    runButton.textContent = "开始生成论文";
  }
  runState.textContent = mode === "running" ? "Running" : mode === "paused" ? "Paused" : isComplete ? "Done" : "Ready";
  updateStartGuide();
}

function setUploadBusy(busy) {
  uploadZone?.classList.toggle("busy", Boolean(busy));
  if (uploadZone) uploadZone.setAttribute("aria-busy", busy ? "true" : "false");
}

function showParseProgress(message, detail = "") {
  if (!parseQualityBanner) return;
  parseQualityBanner.hidden = false;
  parseQualityBanner.classList.remove("ok", "warn");
  parseQualityBanner.classList.add("working");
  parseQualityTitle.textContent = message;
  parseQualityDetail.textContent = detail || "请勿关闭页面；视觉转写按页进行，可能需要数分钟。";
  parseQualityPathRow.hidden = !latestParsedMdPath;
  if (latestParsedMdPath) parseQualityPath.textContent = latestParsedMdPath;
}

function showParseQuality(result) {
  if (!parseQualityBanner) return;
  const quality = result?.parseQuality;
  const mdPath = result?.parsedMdPath || "";
  latestParsedMdPath = mdPath;
  if (!quality && !mdPath) {
    parseQualityBanner.hidden = true;
    return;
  }
  parseQualityBanner.hidden = false;
  parseQualityBanner.classList.remove("working");
  const ok = quality?.ok !== false;
  const method = quality?.method || "direct";
  const warnings = Array.isArray(quality?.warnings) ? quality.warnings : [];
  const needsVision = Boolean(quality?.needsVision);
  parseQualityBanner.classList.toggle("ok", ok && warnings.length === 0 && !needsVision);
  parseQualityBanner.classList.toggle("warn", !ok || warnings.length > 0 || needsVision);
  const methodLabel = PARSE_METHOD_LABELS[method] || method;
  const emptyText = warnings.includes("empty_text");
  parseQualityTitle.textContent = needsVision
    ? (emptyText ? `文本层为空，将视觉转写（${methodLabel}）` : `检测到公式乱码（${methodLabel}）`)
    : ok && warnings.length === 0
      ? `题面解析完成（${methodLabel}）`
      : `请核对题面公式（${methodLabel}）`;
  const ratio = Number(quality?.garbleRatio);
  const parts = [];
  if (Number.isFinite(ratio) && ratio > 0) parts.push(`乱码比例 ${(ratio * 100).toFixed(1)}%`);
  if (quality?.pages) parts.push(`${quality.pages} 页`);
  if (warnings.length) parts.push(`警告: ${warnings.join(", ")}`);
  if (needsVision) {
    parts.push(emptyText
      ? "扫描件或无文本层 PDF，将自动启动视觉转写。"
      : "将自动启动视觉转写，进度会显示在此处。");
  } else if (!parts.length) {
    parts.push("可将下方 Markdown 中间产物作为校对参考；启动时以文本框内容为准。");
  } else {
    parts.push("建议打开中间产物核对公式后再启动。");
  }
  parseQualityDetail.textContent = parts.join(" · ");
  if (mdPath) {
    parseQualityPathRow.hidden = false;
    parseQualityPath.textContent = mdPath;
  } else {
    parseQualityPathRow.hidden = true;
    parseQualityPath.textContent = "";
  }
}

function clearParseQuality() {
  latestParsedMdPath = "";
  problemConfirmArmed = false;
  if (!parseQualityBanner) return;
  parseQualityBanner.hidden = true;
  parseQualityBanner.classList.remove("ok", "warn", "working");
}

async function runVisionTranscribe(storedPath, onProgress, mdFilename = "problem_parsed.md") {
  const response = await fetch("/api/upload/vision", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ storedPath, mdFilename }),
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.error || `HTTP ${response.status}`);
  }
  if (!response.body) throw new Error("视觉转写响应缺少数据流");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let finalResult = null;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";
    for (const line of lines) {
      if (!line.trim()) continue;
      let event;
      try {
        event = JSON.parse(line);
      } catch {
        continue;
      }
      if (event.type === "progress") {
        onProgress?.(event);
      } else if (event.type === "result") {
        finalResult = event;
      } else if (event.type === "error") {
        throw new Error(event.error || "视觉转写失败");
      }
    }
  }
  if (buffer.trim()) {
    try {
      const event = JSON.parse(buffer);
      if (event.type === "result") finalResult = event;
      else if (event.type === "error") throw new Error(event.error || "视觉转写失败");
      else if (event.type === "progress") onProgress?.(event);
    } catch (error) {
      if (error instanceof SyntaxError) {
        // trailing incomplete line — ignore
      } else {
        throw error;
      }
    }
  }
  if (!finalResult) throw new Error("视觉转写未返回结果");
  return finalResult;
}

function updateCommand() {
  const parts = [
    "math-agent run",
    "--problem problem.json",
    `--out ${outputDir.value || "runs/ui-latest"}`,
    `--thread ${threadId.value || "default"}`,
  ];
  if (!hitlToggle.checked) parts.push("--no-interrupt");
  if (activeTemplate !== "default") parts.push(`--template ${activeTemplate}`);
  if (forceToggle.checked) parts.push("--force");
  commandPreview.textContent = parts.join(" ");
  outputSummary.textContent = outputDir.value || "runs/ui-latest";
  iterationValue.textContent = iterationDepth.value;
  knowledgeBadge.textContent = ragToggle.checked ? "RAG On" : "RAG Off";
}

function updateStartGuide() {
  const hasTitle = problemTitle.value.trim().length > 0;
  const hasBrief = problemBrief.value.trim().length > 0;
  const ready = hasTitle && hasBrief;
  const isActive = ["running", "paused"].includes(currentRunStatus);
  const isFinished = Boolean(currentRunStatus) && !isActive;
  const isSuccessful = ["completed", "degraded"].includes(currentRunStatus);
  const needsRetry = isFinished && !isSuccessful;

  importStep?.classList.toggle("done", ready);
  importStep?.classList.toggle("active", !ready && !isActive);
  reviewStep?.classList.toggle("done", ready);
  reviewStep?.classList.toggle("active", ready && !currentRunStatus);
  runStep?.classList.toggle("active", isActive || (ready && (!currentRunStatus || needsRetry)));
  runStep?.classList.toggle("done", isSuccessful);
  runButton.disabled = !ready || isActive;

  // 接回磁盘任务时表单可能仍空：活跃任务优先于「等待导入」
  if (isActive) {
    if (currentRunStatus === "running") {
      readinessBadge.textContent = "任务生成中";
      readinessBadge.dataset.state = "running";
      runStepHint.textContent = "任务正在处理，进度会持续更新。";
    } else {
      readinessBadge.textContent = "等待人工确认";
      readinessBadge.dataset.state = "attention";
      runStepHint.textContent = "请在产物区域审核当前结果后继续。";
    }
    reviewStepHint.textContent = ready
      ? (uploadedAttachments.length
        ? `题目已就绪，并附有 ${uploadedAttachments.length} 个数据文件。`
        : "题目已就绪；如有数据文件，可在下方继续添加。")
      : "题目表单尚未填写；不影响已接回的运行任务。导入只会改表单，不会中断当前任务。";
    return;
  }

  if (!hasTitle && !hasBrief) {
    readinessBadge.textContent = "等待导入赛题";
    readinessBadge.dataset.state = "waiting";
    reviewStepHint.textContent = "导入后检查标题、任务目标和数据附件。";
    runStepHint.textContent = "准备好后，一键启动完整建模流水线。";
  } else if (!ready) {
    readinessBadge.textContent = "还需补全题目信息";
    readinessBadge.dataset.state = "attention";
    reviewStepHint.textContent = hasTitle ? "请补充背景、问题与输出要求。" : "请补充一个清晰的赛题标题。";
    runStepHint.textContent = "补全标题和目标后即可启动。";
  } else {
    reviewStepHint.textContent = uploadedAttachments.length
      ? `题目已就绪，并附有 ${uploadedAttachments.length} 个数据文件。`
      : "题目已就绪；如有数据文件，可在下方继续添加。";
    if (["completed", "degraded"].includes(currentRunStatus)) {
      readinessBadge.textContent = "生成已完成";
      readinessBadge.dataset.state = "ready";
      runStepHint.textContent = "论文产物已经生成，可查看或重新运行。";
    } else if (isFinished) {
      readinessBadge.textContent = "任务已结束";
      readinessBadge.dataset.state = "attention";
      runStepHint.textContent = "请检查运行日志，处理问题后可以重新生成。";
    } else if (confirmProblemToggle?.checked && !problemConfirmArmed) {
      readinessBadge.textContent = "请先确认题面";
      readinessBadge.dataset.state = "attention";
      runStepHint.textContent = latestParsedMdPath
        ? `已开启启动前确认：请核对题面或 ${latestParsedMdPath}，再点击开始。`
        : "已开启启动前确认：请核对题面文本，再点击开始进入确认。";
    } else if (problemConfirmArmed) {
      readinessBadge.textContent = "题面待最终确认";
      readinessBadge.dataset.state = "attention";
      runStepHint.textContent = "确认公式无误后，再次点击「题面无误，开始生成」。";
    } else {
      readinessBadge.textContent = "可以开始生成";
      readinessBadge.dataset.state = "ready";
      runStepHint.textContent = "默认设置已配置好，点击即可启动。";
    }
  }
}

/** @returns {boolean} 用户确认继续导入 */
function confirmImportWhileActive() {
  if (!["running", "paused"].includes(currentRunStatus)) return true;
  return window.confirm(
    "当前任务仍在运行中。\n\n导入只会修改题目表单，不会中断或替换正在生成的任务。是否继续？",
  );
}

function activateNav(hash) {
  navLinks.forEach((link) => link.classList.toggle("active", link.getAttribute("href") === hash));
  setSettingsView(hash === "#settings");
  if (hash === "#settings") loadSettings();
}

async function loadFixturesIntoProblem() {
  const { fixtures } = await api("/api/fixtures");
  const fixture = fixtures[0];
  if (!fixture) throw new Error("tests/fixtures 中没有可导入的题目。");
  problemTitle.value = fixture.title;
  problemBrief.value = [fixture.background, ...fixture.questions].filter(Boolean).join("\n");
  problemBadge.textContent = fixture.name.split(".").pop().toUpperCase();
  currentFixturePath = fixture.path;
  stageIndex = -1;
  updatePipeline();
  updateStartGuide();
  showToast(`已导入 ${fixture.name}`);
}

function renderBlueprint(summary) {
  if (!summary) {
    setPreview("Problem Blueprint", "还没有 Blueprint 数据。先运行流水线，完成后在此查看结构化题目理解。");
    return;
  }
  const bp = summary.problem_blueprint;
  const esc = escapeHtml;
  let html = '<div class="blueprint-view">';

  // scores row
  const bc = summary.blueprint_critic;
  const mc = summary.model_code_consistency;
  html += '<div class="bp-scores">';
  if (bc) {
    html += `<div class="bp-score-card ${bc.approved ? "pass" : "fail"}"><span>Blueprint</span><strong>${esc(bc.score ?? "?")}/10</strong><small>${bc.approved ? "通过" : "未通过"}</small></div>`;
  }
  if (summary.model_critic) {
    html += `<div class="bp-score-card ${summary.model_critic.approved ? "pass" : "fail"}"><span>Model</span><strong>${esc(summary.model_critic.score ?? "?")}/10</strong><small>${summary.model_critic.approved ? "通过" : "未通过"}</small></div>`;
  }
  if (mc) {
    html += `<div class="bp-score-card ${mc.approved ? "pass" : "fail"}"><span>Code</span><strong>${esc(mc.score ?? "?")}/10</strong><small>${mc.approved ? "通过" : "未通过"}</small></div>`;
  }
  if (summary.paper_critic) {
    html += `<div class="bp-score-card ${summary.paper_critic.approved ? "pass" : "fail"}"><span>Paper</span><strong>${esc(summary.paper_critic.score ?? "?")}/10</strong><small>${summary.paper_critic.approved ? "通过" : "未通过"}</small></div>`;
  }
  html += "</div>";

  // coverage + unresolved
  html += '<div class="bp-meta">';
  html += `<span class="bp-tag">Question Coverage: ${esc(summary.question_coverage)}</span>`;
  html += `<span class="bp-tag ${summary.unresolved_issues > 0 ? "warn" : "ok"}">Unresolved Issues: ${esc(summary.unresolved_issues)}</span>`;
  html += "</div>";

  // blueprint details
  if (bp) {
    html += `<h4>核心任务</h4><p>${esc(bp.core_task)}</p>`;
    if (bp.subquestions && bp.subquestions.length) {
      html += "<h4>小问</h4><ul class=\"bp-list\">";
      bp.subquestions.forEach((sq) => {
        html += `<li><strong>[${esc(sq.id)}]</strong> ${esc(sq.original_text)} <em>(${esc(sq.task_type)})</em></li>`;
      });
      html += "</ul>";
    }
    if (bp.decision_variables && bp.decision_variables.length) {
      html += "<h4>决策变量</h4><ul class=\"bp-list\">";
      bp.decision_variables.forEach((v) => {
        html += `<li><code>${esc(v.name)}</code> ${esc(v.meaning)}</li>`;
      });
      html += "</ul>";
    }
    if (bp.objectives && bp.objectives.length) {
      html += "<h4>目标</h4><ul class=\"bp-list\">";
      bp.objectives.forEach((o) => {
        html += `<li>[${esc(o.direction)}] ${esc(o.description)}</li>`;
      });
      html += "</ul>";
    }
    if (bp.constraints && bp.constraints.length) {
      html += "<h4>约束</h4><ul class=\"bp-list\">";
      bp.constraints.forEach((c) => {
        html += `<li>${esc(c.description)} <em>(${esc(c.source)})</em></li>`;
      });
      html += "</ul>";
    }
    if (bp.metrics && bp.metrics.length) {
      html += "<h4>指标</h4><ul class=\"bp-list\">";
      bp.metrics.forEach((m) => {
        html += `<li><code>${esc(m.name)}</code> ${esc(m.meaning)}</li>`;
      });
      html += "</ul>";
    }
  }

  // consistency details
  if (mc && (mc.missing_variables?.length || mc.missing_objectives?.length || mc.missing_constraints?.length || mc.issues?.length)) {
    html += "<h4>模型-代码一致性</h4>";
    if (mc.missing_variables?.length) html += `<p class="bp-warn">缺失变量: ${esc(mc.missing_variables.join(", "))}</p>`;
    if (mc.missing_objectives?.length) html += `<p class="bp-warn">缺失目标: ${esc(mc.missing_objectives.join(", "))}</p>`;
    if (mc.missing_constraints?.length) html += `<p class="bp-warn">缺失约束: ${esc(mc.missing_constraints.join(", "))}</p>`;
    if (mc.issues?.length) {
      html += "<ul class=\"bp-list\">";
      mc.issues.forEach((i) => { html += `<li>${esc(i)}</li>`; });
      html += "</ul>";
    }
  }

  // blueprint critic issues
  if (bc && bc.issues?.length) {
    html += "<h4>Blueprint Critic 意见</h4><ul class=\"bp-list\">";
    bc.issues.forEach((i) => { html += `<li>${esc(i)}</li>`; });
    html += "</ul>";
  }

  html += "</div>";
  artifactPreview.innerHTML = html;
}

async function loadArtifacts(tab = "paper") {
  const payload = await api(`/api/artifacts?out=${encodeURIComponent(outputDir.value || "runs/ui-latest")}`);
  lastArtifacts = payload;
  const actualScore = payload.stateSummary?.evaluation_overall;
  qualityScore.textContent = Number.isFinite(Number(actualScore))
    ? Number(actualScore).toFixed(2)
    : "--";
  if (tab === "paper") {
    setPreview(
      payload.paperExcerpt ? "论文预览" : "还没有论文产物",
      payload.paperExcerpt ? payload.paperExcerpt.slice(0, 700) : `未在 ${payload.out} 找到 paper.md。先启动流水线，或检查输出目录。`,
    );
  } else if (tab === "blueprint") {
    renderBlueprint(payload.stateSummary);
  } else if (tab === "trace") {
    setPreview(
      payload.traceSummary ? "Trace 摘要" : "还没有 Trace",
      payload.traceSummary
        ? `thread=${payload.traceSummary.threadId || "-"}，LLM 调用 ${payload.traceSummary.llmCalls || 0} 次，节点 ${payload.traceSummary.nodes || 0} 个。`
        : `未在 ${payload.out} 找到 trace.json。`,
      payload.traceSummary ? `<pre class="log-preview">${escapeHtml(JSON.stringify(payload.traceSummary, null, 2))}</pre>` : "",
    );
  } else {
    const fileTags = payload.files.length
      ? `<div class="artifact-list">${payload.files.map((file) => `<span>${file.type === "dir" ? "dir" : "file"} · ${escapeHtml(file.name)}</span>`).join("")}</div>`
      : `<div class="artifact-list"><span>暂无文件</span></div>`;
    setPreview("输出目录", `当前目录：${payload.out}`, fileTags);
  }
}

async function startProjectRun() {
  if (!problemTitle.value.trim() || !problemBrief.value.trim()) {
    document.querySelector("#task-title")?.scrollIntoView({ behavior: "smooth", block: "start" });
    updateStartGuide();
    throw new Error("请先填写赛题标题和背景目标，再开始生成。");
  }
  if (confirmProblemToggle?.checked && !problemConfirmArmed) {
    problemConfirmArmed = true;
    document.querySelector("#task-title")?.scrollIntoView({ behavior: "smooth", block: "start" });
    updatePipeline(currentRunStatus || "local");
    showToast(latestParsedMdPath
      ? `请核对题面与 ${latestParsedMdPath}，确认后再次点击开始`
      : "请核对题面文本中的公式，确认后再次点击开始");
    return;
  }
  problemConfirmArmed = false;
  lastArtifacts = null;
  updateCommand();
  stageIndex = 0;
  currentRunStatus = "running";
  updatePipeline("running");
  setPreview("正在启动 math-agent", "本地服务正在写入 problem.json 并调用项目 CLI，日志会自动刷新。", "<div class=\"paper-lines\"><span></span><span></span><span></span></div>");
  const { run } = await api("/api/run", {
    method: "POST",
    body: JSON.stringify({
      title: problemTitle.value,
      background: problemBrief.value,
      fixturePath: currentFixturePath,
      outputDir: outputDir.value || "runs/ui-latest",
      threadId: threadId.value || "default",
      template: activeTemplate,
      noInterrupt: !hitlToggle.checked,
      ragEnabled: ragToggle.checked,
      iterationDepth: Number.parseInt(iterationDepth.value, 10),
      force: forceToggle.checked,
      attachments: uploadedAttachments,
    }),
  });
  currentRunId = run.id;
  currentRunStatus = run.status || "running";
  updateStartGuide();
  showToast("已启动项目流水线");
  startLogStream(currentRunId);
  startInsightPolling();
  // 慢速状态轮询：SSE 活跃时仅检测 paused/终态（不写日志），SSE 断开时作为日志 fallback
  pollTimer = window.setTimeout(pollCurrentRun, 2000);
}

async function pollCurrentRun() {
  if (!currentRunId) return;
  window.clearTimeout(pollTimer);
  try {
    const run = await api(`/api/runs/${encodeURIComponent(currentRunId)}`);
    currentRunStatus = run.status;
    if (run.status === "running") {
      if (run.nextNode) applyNextNodeToStage(run.nextNode);
      refreshInsightPane().catch(() => {});
      if (!logStream) {
        // SSE 未连接 -> 用 API 轮询作为日志 fallback
        setRunLogPreview(run);
        pollTimer = window.setTimeout(pollCurrentRun, 3000);
      } else {
        // SSE 活跃 -> 不写日志，只做慢速状态探测（SSE 断开时的 safety net）
        pollTimer = window.setTimeout(pollCurrentRun, 5000);
      }
      return;
    }
    if (run.status === "paused") {
      handlePaused(run);
      return;
    }
    handleRunEnd(run);
  } catch (error) {
    updatePipeline("running");
    showToast(`状态刷新失败，将自动重试：${error.message}`);
    if (currentRunId) {
      pollTimer = window.setTimeout(pollCurrentRun, 3000);
    }
  }
}

function startLogStream(runId) {
  // 关闭旧的 SSE 连接
  if (logStream) { try { logStream.close(); } catch {} }
  try {
    logStream = new EventSource(`/api/runs/${encodeURIComponent(runId)}/log`);
  } catch {
    // EventSource 不可用 -> 回退到纯轮询
    return;
  }
  let logBuffer = "";
  logStream.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      if (data.log) {
        logBuffer = (logBuffer + data.log).slice(-6000);
        updateLogPreview(logBuffer);
        advanceStageFromLog(data.log);
      }
    } catch {}
  };
  logStream.addEventListener("status", (event) => {
    try {
      const data = JSON.parse(event.data);
      // SSE 推送了终态 -> 拉取最终 run 信息
      if (data.status && data.status !== "running") {
        logStream.close();
        logStream = null;
        pollCurrentRun();
      }
    } catch {}
  });
  logStream.onerror = () => {
    // SSE 断开 -> 回退到轮询
    try { logStream.close(); } catch {}
    logStream = null;
    if (currentRunId) pollTimer = window.setTimeout(pollCurrentRun, 2000);
  };
}

function updateLogPreview(logText) {
  const esc = logText.replace(/[<>&]/g, (c) => ({ "<": "&lt;", ">": "&gt;", "&": "&amp;" })[c]);
  artifactPreview.innerHTML = `
    <h3>运行日志</h3>
    <pre class="log-preview">${esc}</pre>
  `;
}

function advanceStageFromLog(logChunk) {
  const lower = logChunk.toLowerCase();
  for (let i = stageIndex; i < stages.length; i++) {
    if (lower.includes(`node: ${stageLogNames[i]}`)) {
      stageIndex = i;
      updatePipeline("running");
      break;
    }
  }
}

function handlePaused(run) {
  // Evaluation 完成后暂停在 Human Review。
  stageIndex = stages.indexOf("Human Review");
  if (stageIndex < 0) stageIndex = stages.length - 3;
  currentRunStatus = "paused";
  updatePipeline("paused");
  setRunLogPreview(run);
  showToast("流水线暂停，等待人工审核");
  showResumeBar(run);
}

function handleRunEnd(run) {
  if (logStream) { try { logStream.close(); } catch {} logStream = null; }
  stageIndex = run.status === "completed" ? stages.length : stageIndex;
  currentRunStatus = run.status;
  updatePipeline();
  setRunLogPreview(run);
  if (["completed", "failed", "rejected", "stopped"].includes(run.status)) {
    // 终态后再次点击运行即是明确重跑；勾选状态可见，用户仍可手动取消。
    forceToggle.checked = true;
    updateCommand();
  }
  if (run.status === "completed") {
    showToast("流水线完成");
    loadArtifacts("paper").catch(() => {});
  } else if (run.status === "paused") {
    handlePaused(run);
  } else if (run.status === "rejected") {
    showToast("人工审核已拒绝，未生成最终稿");
  } else if (run.status === "stopped") {
    showToast("流水线已停止");
  } else if (run.status === "degraded") {
    showToast("流水线已收口，但存在需要检查的警告");
    loadArtifacts("paper").catch(() => {});
  } else if (run.status === "blocked") {
    showToast("恢复已达到安全上限，请先处理日志中的问题后再用 CLI recover");
  } else if (run.status === "failed" && run.recoverable) {
    showToast("流水线失败，可从最近检查点恢复");
    showRecoverBar(run);
  } else {
    showToast("流水线失败，当前没有可用 checkpoint");
  }
}

function showRecoverBar(run) {
  artifactPreview.innerHTML = `
    <h3>流水线已中断</h3>
    <p>任务运行失败。如果已有 checkpoint，可以从最近保存的节点继续，无需从头重跑。</p>
    <div class="resume-bar">
      <button class="primary-button" type="button" id="recoverRun">从最近检查点恢复</button>
    </div>
    <pre class="log-preview">${escapeHtml(run.log || "")}</pre>
  `;
  document.querySelector("#recoverRun")?.addEventListener("click", recoverFailedRun);
}

function showResumeBar(run) {
  const esc = escapeHtml;
  artifactPreview.innerHTML = `
    <h3>等待人工审核</h3>
    <p>流水线已暂停在 human_review 节点。请审核当前结果后选择继续或拒绝。</p>
    <div class="resume-bar">
      <button class="primary-button" type="button" id="resumeApprove">批准并继续</button>
      <button class="ghost-button" type="button" id="resumeReject">拒绝</button>
    </div>
    <pre class="log-preview">${esc(run.log || "")}</pre>
  `;
  document.querySelector("#resumeApprove")?.addEventListener("click", () => resumeRun(true));
  document.querySelector("#resumeReject")?.addEventListener("click", () => resumeRun(false));
}

async function resumeRun(approve) {
  if (!currentRunId) return;
  try {
    const { run } = await api(`/api/runs/${encodeURIComponent(currentRunId)}/resume`, {
      method: "POST",
      body: JSON.stringify({ approve }),
    });
    showToast(approve ? "已批准，继续运行" : "已拒绝，正在安全结束");
    stageIndex = stages.indexOf("Human Review");
    setPreview("正在恢复运行", "正在执行 resume 命令，日志会自动刷新。");
    restartRunMonitoring(run);
  } catch (error) {
    showToast(`恢复失败: ${error.message}`);
  }
}

function restartRunMonitoring(run) {
  currentRunId = run.id;
  currentRunStatus = "running";
  if (logStream) { try { logStream.close(); } catch {} logStream = null; }
  updatePipeline("running");
  startLogStream(currentRunId);
  pollTimer = window.setTimeout(pollCurrentRun, 2000);
}

async function recoverFailedRun() {
  if (!currentRunId) return;
  const button = document.querySelector("#recoverRun");
  if (button) {
    button.disabled = true;
    button.textContent = "正在恢复…";
  }
  try {
    const { run } = await api(`/api/runs/${encodeURIComponent(currentRunId)}/recover`, {
      method: "POST",
      body: "{}",
    });
    showToast("已从最近检查点恢复运行");
    setPreview("正在恢复运行", "正在从最近 checkpoint 继续，日志会自动刷新。");
    restartRunMonitoring(run);
  } catch (error) {
    if (button) {
      button.disabled = false;
      button.textContent = "从最近检查点恢复";
    }
    showToast(`恢复失败: ${error.message}`);
  }
}

runButton?.addEventListener("click", () => {
  startProjectRun().catch((error) => {
    currentRunStatus = null;
    updatePipeline();
    setPreview("启动失败", error.message);
    showToast(error.message);
  });
});

resetPipelineButton?.addEventListener("click", () => {
  currentRunId = null;
  currentRunStatus = null;
  window.clearTimeout(pollTimer);
  if (logStream) { try { logStream.close(); } catch {} logStream = null; }
  stageIndex = -1;
  updatePipeline();
  setPreview("流水线状态已刷新", "已回到 Analyst 起点。再次点击启动会调用项目 CLI。");
  showToast("流水线状态已刷新");
});

importDemoButton?.addEventListener("click", () => {
  if (!confirmImportWhileActive()) return;
  loadFixturesIntoProblem().catch((error) => showToast(error.message));
});

chooseProblemButton?.addEventListener("click", () => {
  if (!confirmImportWhileActive()) return;
  problemFile?.click();
});

openOutputsButton?.addEventListener("click", () => {
  document.querySelector("#outputs")?.scrollIntoView({ behavior: "smooth", block: "start" });
  loadArtifacts("files").catch((error) => {
    setPreview("读取输出目录失败", error.message);
    showToast(error.message);
  });
});

templateButtons.forEach((button) => {
  button.addEventListener("click", () => {
    templateButtons.forEach((item) => item.classList.remove("active"));
    button.classList.add("active");
    activeTemplate = button.dataset.template;
    templateHint.textContent = templateHints[activeTemplate];
    updateCommand();
    showToast(`已切换到 ${button.textContent} 模板`);
  });
});

tabButtons.forEach((button) => {
  button.addEventListener("click", () => {
    tabButtons.forEach((item) => item.classList.remove("active"));
    button.classList.add("active");
    loadArtifacts(button.dataset.tab).catch((error) => {
      setPreview("读取产物失败", error.message);
      showToast(error.message);
    });
  });
});

[problemTitle, problemBrief].forEach((control) => {
  control?.addEventListener("input", () => {
    currentFixturePath = null;
    problemBadge.textContent = problemTitle.value.trim() || problemBrief.value.trim() ? "手动填写" : "未导入";
    if (problemConfirmArmed) {
      problemConfirmArmed = false;
      updatePipeline(currentRunStatus || "local");
    }
    updateStartGuide();
  });
});
[outputDir, threadId, iterationDepth, ragToggle, hitlToggle, forceToggle, confirmProblemToggle].forEach((control) => {
  control?.addEventListener("input", updateCommand);
  control?.addEventListener("change", () => {
    if (control === confirmProblemToggle) {
      problemConfirmArmed = false;
      updatePipeline(currentRunStatus || "local");
    }
    updateCommand();
    updateStartGuide();
  });
});
copyParsedMdPath?.addEventListener("click", async () => {
  if (!latestParsedMdPath) return;
  try {
    await navigator.clipboard.writeText(latestParsedMdPath);
    showToast("已复制 Markdown 路径");
  } catch {
    showToast(latestParsedMdPath);
  }
});

async function uploadFile(file, purpose) {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("purpose", purpose);
  const response = await fetch("/api/upload", { method: "POST", body: formData });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
  return payload;
}

const PARSE_METHOD_LABELS = {
  direct: "直接读取",
  text: "文本层抽取",
  vision: "视觉转写",
  text_fallback: "文本抽取（视觉回退失败）",
  docx: "Word 抽取",
  user_confirmed: "用户确认",
};

function attachmentQualityLabel(att) {
  const q = att.parseQuality;
  if (!q) return "";
  if (att._visionProgress) return att._visionProgress;
  const method = PARSE_METHOD_LABELS[q.method] || q.method;
  if (q.needsVision) return `待视觉 · ${method}`;
  if (q.ok === false || (Array.isArray(q.warnings) && q.warnings.length)) return `需核对 · ${method}`;
  return method;
}

function renderAttachmentList() {
  attachmentList.innerHTML = uploadedAttachments.map((att, i) => {
    let meta = "";
    if (att.summary?.sheets?.length) {
      const s = att.summary.sheets[0];
      meta = `${s.rows}行×${s.cols}列`;
      if (s.columns?.length) meta += ` · ${s.columns.slice(0, 4).join(", ")}`;
    } else if (att.summary?.text_excerpt) {
      meta = `${Math.ceil(att.summary.text_excerpt.length / 1024)} KB 文本`;
    }
    const quality = attachmentQualityLabel(att);
    const qClass = att._visionProgress
      ? "working"
      : att.parseQuality?.needsVision || att.parseQuality?.ok === false
        ? "warn"
        : att.parseQuality
          ? "ok"
          : "";
    const pathHtml = att.parsedMdPath
      ? `<div class="att-path-row">
          <code class="att-path" title="${escapeHtml(att.parsedMdPath)}">${escapeHtml(att.parsedMdPath)}</code>
          <button class="ghost-button compact att-copy-path" type="button" data-path="${escapeHtml(att.parsedMdPath)}">复制路径</button>
        </div>`
      : "";
    return `<div class="attachment-item ${qClass}">
      <div class="att-main">
        <span class="att-name">${escapeHtml(att.filename)}</span>
        <span class="att-meta">${escapeHtml(att.fileType)}${meta ? ` · ${escapeHtml(meta)}` : ""}${quality ? ` · ${escapeHtml(quality)}` : ""}</span>
        ${pathHtml}
      </div>
      <button class="att-remove" type="button" data-idx="${i}" ${att._visionProgress ? "disabled" : ""}>×</button>
    </div>`;
  }).join("");
  attachmentList.querySelectorAll(".att-remove").forEach((btn) => {
    btn.addEventListener("click", () => {
      uploadedAttachments.splice(Number(btn.dataset.idx), 1);
      renderAttachmentList();
    });
  });
  attachmentList.querySelectorAll(".att-copy-path").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const path = btn.dataset.path || "";
      if (!path) return;
      try {
        await navigator.clipboard.writeText(path);
        showToast("已复制附件解析路径");
      } catch {
        showToast(path);
      }
    });
  });
  updateStartGuide();
}

async function loadAttachmentFile(file) {
  if (!file) return;
  const ext = file.name.split(".").pop()?.toLowerCase();
  showToast(`正在上传 ${file.name}...`);
  if (attachmentZone) attachmentZone.classList.add("busy");
  try {
    let result = await uploadFile(file, "attachment");
    uploadedAttachments.push(result);
    renderAttachmentList();

    if (ext === "pdf" && result.parseQuality?.needsVision && result.storedPath) {
      const idx = uploadedAttachments.length - 1;
      const pages = result.parseQuality.pages || result.summary?.total_pages || "?";
      uploadedAttachments[idx] = {
        ...result,
        _visionProgress: `视觉转写中（约 ${pages} 页）…`,
      };
      renderAttachmentList();
      showToast(`${file.name} 公式乱码，开始视觉转写…`);
      try {
        const visionResult = await runVisionTranscribe(
          result.storedPath,
          (event) => {
            uploadedAttachments[idx] = {
              ...uploadedAttachments[idx],
              _visionProgress: event.message || "视觉转写中…",
            };
            renderAttachmentList();
          },
          "attachment_parsed.md",
        );
        uploadedAttachments[idx] = {
          ...result,
          ...visionResult,
          id: result.id,
          filename: result.filename,
          fileType: result.fileType || "pdf",
          size: result.size,
          storedPath: result.storedPath,
          summary: {
            ...(result.summary || {}),
            ...(visionResult.summary || {}),
            text_excerpt: visionResult.text || result.summary?.text_excerpt,
          },
          text: visionResult.text || result.text,
          parsedMdPath: visionResult.parsedMdPath || result.parsedMdPath,
          parseQuality: visionResult.parseQuality || result.parseQuality,
          _visionProgress: "",
        };
        renderAttachmentList();
        showToast(visionResult.parseQuality?.method === "vision"
          ? `${file.name} 已视觉转写，请核对公式`
          : `${file.name} 视觉转写未完全成功，已保留文本层`);
      } catch (visionError) {
        uploadedAttachments[idx] = { ...result, _visionProgress: "" };
        renderAttachmentList();
        showToast(`${file.name} 视觉转写失败：${visionError.message}（已保留文本层）`);
      }
      return;
    }

    const q = result.parseQuality;
    if (q && (q.ok === false || q.needsVision)) {
      showToast(`${file.name} 已上传，建议核对解析文本`);
    } else {
      showToast(`${file.name} 已上传`);
    }
  } catch (error) {
    showToast(`上传失败：${error.message}`);
  } finally {
    attachmentZone?.classList.remove("busy");
  }
}

function loadProblemFile(file) {
  if (!file) return;
  if (!problemTitle.value.trim()) {
    problemTitle.value = file.name.replace(/\.[^.]+$/, "").replace(/[_-]+/g, " ").trim() || "未命名赛题";
  }
  uploadTitle.textContent = file.name;
  uploadMeta.textContent = `${Math.ceil(file.size / 1024)} KB · ${file.type || "本地文件"}`;
  problemBadge.textContent = file.name.split(".").pop()?.toUpperCase() || "FILE";
  currentFixturePath = null;
  problemConfirmArmed = false;
  updateStartGuide();
  const ext = file.name.split(".").pop()?.toLowerCase();
  if (ext === "json") {
    clearParseQuality();
    const reader = new FileReader();
    reader.addEventListener("load", () => {
      const text = String(reader.result || "");
      try {
        const data = JSON.parse(text);
        const questions = Array.isArray(data.questions)
          ? data.questions.filter((item) => typeof item === "string")
          : [];
        if (typeof data.title === "string" && data.title) problemTitle.value = data.title;
        const background = typeof data.background === "string" ? data.background : "";
        problemBrief.value = [background, ...questions].filter(Boolean).join("\n") || text.slice(0, MAX_PROBLEM_TEXT_CHARS);
      } catch {
        problemBrief.value = text.slice(0, MAX_PROBLEM_TEXT_CHARS) || problemBrief.value;
      }
      updateStartGuide();
      showToast("题目 JSON 已读取");
    });
    reader.readAsText(file, "utf-8");
  } else if (ext === "md" || ext === "txt" || ext === "pdf" || ext === "docx") {
    const label = (ext === "md" || ext === "txt") ? "导入" : "提取";
    setUploadBusy(true);
    showParseProgress(
      ext === "pdf" ? "正在抽取 PDF 文本层…" : `正在${label} ${file.name}…`,
      ext === "pdf"
        ? "先快速抽取文本；若公式乱码，会自动进入视觉转写并显示分页进度。"
        : "请稍候。",
    );
    showToast(`正在${label} ${file.name}...`);
    uploadFile(file, "problem")
      .then(async (result) => {
        // 扫描件/全乱码 PDF：文本层为空但 needsVision=true，必须先走视觉，不能因空文本提前 return
        const canVision = ext === "pdf" && result.parseQuality?.needsVision && result.storedPath;

        if (result.text) {
          problemBrief.value = result.text.slice(0, MAX_PROBLEM_TEXT_CHARS);
        }
        showParseQuality(result);
        updatePipeline(currentRunStatus || "local");
        updateStartGuide();

        if (canVision) {
          const pages = result.parseQuality.pages || result.summary?.total_pages || "?";
          showParseProgress(
            result.text ? "检测到公式乱码，正在视觉转写…" : "文本层为空，正在视觉转写扫描件…",
            `约 ${pages} 页。进度会在此更新，请勿关闭页面。`,
          );
          showToast(result.text ? "公式乱码，开始视觉转写…" : "文本层为空，开始视觉转写…");
          try {
            const visionResult = await runVisionTranscribe(result.storedPath, (event) => {
              showParseProgress(
                event.message || "正在视觉转写…",
                event.pages
                  ? `共 ${event.pages} 页` + (event.batch ? ` · 第 ${event.batch}/${event.batches || "?"} 批` : "")
                  : "请勿关闭页面。",
              );
              if (uploadMeta) {
                uploadMeta.textContent = event.message || "视觉转写中…";
              }
            });
            if (visionResult.text) {
              problemBrief.value = visionResult.text.slice(0, MAX_PROBLEM_TEXT_CHARS);
            }
            showParseQuality(visionResult);
            updatePipeline(currentRunStatus || "local");
            updateStartGuide();
            if (!visionResult.text && !result.text) {
              showToast("视觉转写后仍无可用文本，请改传 Markdown/TXT 或检查 PDF");
              return;
            }
            showToast(visionResult.parseQuality?.method === "vision"
              ? `${file.name} 已视觉转写，请核对公式`
              : `${file.name} 视觉转写未完全成功，已保留文本层`);
          } catch (visionError) {
            if (!result.text) {
              clearParseQuality();
              showToast(`视觉转写失败：${visionError.message}`);
              return;
            }
            showParseQuality(result);
            showToast(`视觉转写失败：${visionError.message}（已保留文本层）`);
          }
          return;
        }

        if (!result.text) {
          clearParseQuality();
          showToast("未能从文件中提取文本");
          return;
        }

        showToast(`${file.name} 已${label === "导入" ? "导入" : "提取"}`);
      })
      .catch((error) => {
        clearParseQuality();
        showToast(`提取失败：${error.message}`);
      })
      .finally(() => {
        setUploadBusy(false);
      });
  } else {
    showToast("当前仅支持 JSON、Markdown、TXT、PDF、Word 文件");
  }
}

uploadZone?.addEventListener("click", () => {
  if (!confirmImportWhileActive()) return;
  problemFile.click();
});
uploadZone?.addEventListener("keydown", (event) => {
  if (event.key === "Enter" || event.key === " ") {
    event.preventDefault();
    if (!confirmImportWhileActive()) return;
    problemFile.click();
  }
});
problemFile?.addEventListener("change", () => loadProblemFile(problemFile.files[0]));
uploadZone?.addEventListener("dragover", (event) => {
  event.preventDefault();
  uploadZone.classList.add("dragging");
});
uploadZone?.addEventListener("dragleave", () => uploadZone.classList.remove("dragging"));
uploadZone?.addEventListener("drop", (event) => {
  event.preventDefault();
  uploadZone.classList.remove("dragging");
  if (!confirmImportWhileActive()) return;
  loadProblemFile(event.dataTransfer.files[0]);
});

attachmentZone?.addEventListener("click", () => attachmentFile.click());
attachmentZone?.addEventListener("keydown", (event) => {
  if (event.key === "Enter" || event.key === " ") {
    event.preventDefault();
    attachmentFile.click();
  }
});
attachmentFile?.addEventListener("change", () => {
  for (const file of attachmentFile.files) {
    loadAttachmentFile(file);
  }
  attachmentFile.value = "";
});
attachmentZone?.addEventListener("dragover", (event) => {
  event.preventDefault();
  attachmentZone.classList.add("dragging");
});
attachmentZone?.addEventListener("dragleave", () => attachmentZone.classList.remove("dragging"));
attachmentZone?.addEventListener("drop", (event) => {
  event.preventDefault();
  attachmentZone.classList.remove("dragging");
  for (const file of event.dataTransfer.files) {
    loadAttachmentFile(file);
  }
});

function applyNextNodeToStage(nextNode) {
  if (!nextNode) return;
  const key = String(nextNode).toLowerCase();
  const exact = stageLogNames.indexOf(key);
  if (exact >= 0) {
    stageIndex = exact;
    return;
  }
  // 最长子串匹配，避免 model_code_consistency 误命中 coder
  let best = -1;
  let bestLen = -1;
  for (let i = 0; i < stageLogNames.length; i += 1) {
    const name = stageLogNames[i];
    if (key.includes(name) && name.length > bestLen) {
      best = i;
      bestLen = name.length;
    }
  }
  if (best >= 0) stageIndex = best;
}

async function restoreActiveRunFromDisk() {
  try {
    const payload = await api("/api/active-run");
    if (!payload?.run) return false;
    const run = payload.run;
    if (outputDir && payload.out) {
      outputDir.value = payload.out;
    }
    if (threadId && payload.thread) {
      threadId.value = payload.thread;
    }
    updateCommand();
    currentRunId = run.id;
    currentRunStatus = run.status;
    applyNextNodeToStage(payload.nextNode || run.nextNode);
    if (["running", "paused"].includes(run.status)) {
      updatePipeline(run.status === "paused" ? "paused" : "running");
      setRunLogPreview(run);
      if (run.status === "paused") {
        showResumeBar(run);
      } else {
        startLogStream(currentRunId);
        pollTimer = window.setTimeout(pollCurrentRun, 2000);
      }
      showToast(`已接回任务：${payload.out} (${payload.how || "auto"})`);
      startInsightPolling();
    } else {
      handleRunEnd(run);
      showToast(`已加载最近任务：${payload.out} · ${run.status}`);
    }
    updateStartGuide();
    return true;
  } catch (error) {
    showToast(`接回任务失败：${error.message}`);
    return false;
  }
}

window.addEventListener("hashchange", () => {
  const hash = window.location.hash || "#workspace";
  activateNav(hash);
});
updatePipeline();
updateCommand();
updateStartGuide();
api("/api/health")
  .then(async (health) => {
    if (health.onboarding && health.onboarding.needed) {
      showOnboarding();
    } else {
      showToast(`已连接项目：${health.fixtures} 个示例题`);
      await restoreActiveRunFromDisk();
      startInsightPolling();
    }
  })
  .catch((error) => showToast(`项目 API 未连接：${error.message}`));

// ============ 引导向导 ============

let onboardingStep = 1;
let onboardingData = {
  provider: null,
  apiBase: "",
  apiKey: "",
  defaultModel: "",
  strongModel: "",
  figureModel: "",
};

const onboardingSteps = [
  { title: "检查运行环境", subtitle: "确认 Beacon 所需工具已经就绪" },
  { title: "选择模型服务", subtitle: "选择你正在使用的 LLM 提供商" },
  { title: "连接模型服务", subtitle: "填写访问端点与 API 密钥" },
  { title: "验证模型连接", subtitle: "确认所选模型可以正常响应" },
  { title: "可以开始了", subtitle: "配置已保存，接下来只需导入赛题" },
];

function showOnboarding() {
  onboardingOverlay.hidden = false;
  onboardingStep = 1;
  renderOnboardingStep();
}

function hideOnboarding() {
  onboardingOverlay.hidden = true;
  document.querySelector("#start-guide-title")?.focus();
}

function updateStepDots() {
  stepDots.forEach((dot, i) => {
    dot.classList.toggle("active", i + 1 === onboardingStep);
    dot.classList.toggle("done", i + 1 < onboardingStep);
  });
}

function renderOnboardingStep() {
  const step = onboardingSteps[onboardingStep - 1];
  onboardingTitle.textContent = step.title;
  onboardingSubtitle.textContent = `第 ${onboardingStep} / ${onboardingSteps.length} 步 · ${step.subtitle}`;
  updateStepDots();
  onboardingPrev.disabled = onboardingStep === 1;
  onboardingNext.textContent = onboardingStep === 5 ? "进入工作台" : "下一步";

  if (onboardingStep === 1) renderEnvCheckStep();
  else if (onboardingStep === 2) renderProviderStep();
  else if (onboardingStep === 3) renderApiKeyStep();
  else if (onboardingStep === 4) renderModelTestStep();
  else if (onboardingStep === 5) renderCompleteStep();
}

async function renderEnvCheckStep() {
  onboardingBody.innerHTML = `
    <h3>环境检测</h3>
    <p>正在检测运行所需依赖...</p>
    <div class="env-check-list" id="envCheckList"></div>
  `;
  try {
    const data = await api("/api/env/check");
    const list = document.querySelector("#envCheckList");
    list.innerHTML = renderEnvItem("Python", "3.11–3.13", data.python) +
      renderEnvItem("Node.js", "≥ 18", data.node) +
      renderEnvItem("uv", "Python 包管理器", data.uv);
    onboardingNext.disabled = !data.allOk;
    if (!data.allOk) {
      list.querySelectorAll(".env-install-btn").forEach((btn) => {
        btn.addEventListener("click", () => installTool(btn.dataset.tool, btn));
      });
    }
  } catch (error) {
    onboardingBody.innerHTML = `<p>检测失败: ${escapeHtml(error.message)}</p>`;
  }
}

function renderEnvItem(name, requirement, info) {
  const ok = info.ok;
  const toolName = name === "Python" ? "python" : name === "Node.js" ? "node" : name === "uv" ? "uv" : "";
  const status = ok
    ? `<span class="env-status-ok">✓ ${escapeHtml(info.version)}</span>`
    : `<span class="env-status-missing">✗ ${info.installed ? escapeHtml(info.version) + " 版本过低" : "未检测到"}</span>`;
  const actionBtn = ok ? "" : `<button class="env-install-btn" data-tool="${toolName}">一键安装</button>`;
  return `
    <div class="env-check-item ${ok ? "ok" : "missing"}">
      <div>
        <span class="env-name">${escapeHtml(name)}</span>
        <span class="env-version">${escapeHtml(requirement)}</span>
      </div>
      <div style="display:flex;align-items:center;gap:10px;">
        ${status}
        ${actionBtn}
      </div>
    </div>
  `;
}

async function installTool(tool, btn) {
  btn.disabled = true;
  btn.classList.add("installing");
  btn.textContent = "安装中...";
  try {
    const result = await api("/api/env/install", {
      method: "POST",
      body: JSON.stringify({ tool }),
    });
    if (result.status === "done") {
      showToast(`${tool} 安装完成`);
      renderEnvCheckStep();
    } else {
      btn.disabled = false;
      btn.classList.remove("installing");
      btn.textContent = "重试";
      showToast(`${tool} 安装失败: ${result.message}`);
      if (result.downloadUrl) {
        onboardingBody.insertAdjacentHTML("beforeend",
          `<p style="margin-top:12px;color:var(--rose);">手动安装: <a href="${escapeHtml(result.downloadUrl)}" target="_blank">${escapeHtml(result.downloadUrl)}</a></p>`);
      }
    }
  } catch (error) {
    btn.disabled = false;
    btn.classList.remove("installing");
    btn.textContent = "重试";
    showToast(`安装失败: ${error.message}`);
  }
}

async function renderProviderStep() {
  onboardingNext.disabled = !onboardingData.provider;
  onboardingBody.innerHTML = `
    <p>选择后会自动填入访问端点和推荐模型；你仍可在下一步修改。</p>
    <div class="provider-grid" id="providerGrid"></div>
  `;
  try {
    const providers = await api("/api/providers");
    const grid = document.querySelector("#providerGrid");
    grid.innerHTML = providers.map((p) => `
      <button class="provider-card ${onboardingData.provider === p.id ? "selected" : ""}" type="button" data-provider="${escapeHtml(p.id)}" aria-pressed="${onboardingData.provider === p.id}">
        <strong>${escapeHtml(p.name)}</strong>
        <span>${escapeHtml(p.description)}</span>
      </button>
    `).join("");
    grid.querySelectorAll(".provider-card").forEach((card) => {
      card.addEventListener("click", () => {
        grid.querySelectorAll(".provider-card").forEach((c) => c.classList.remove("selected"));
        grid.querySelectorAll(".provider-card").forEach((c) => c.setAttribute("aria-pressed", "false"));
        card.classList.add("selected");
        card.setAttribute("aria-pressed", "true");
        const provider = providers.find((p) => p.id === card.dataset.provider);
        const previousProvider = onboardingData.provider;
        onboardingData.provider = provider.id;
        onboardingData.apiBase = provider.apiBase;
        onboardingData.defaultModel = provider.defaultModel;
        onboardingData.strongModel = provider.strongModel;
        onboardingData.figureModel = provider.figureModel || provider.strongModel || "";
        if (provider.id === "ollama" && !onboardingData.apiKey) {
          onboardingData.apiKey = "ollama";
        } else if (previousProvider === "ollama" && onboardingData.apiKey === "ollama") {
          onboardingData.apiKey = "";
        }
        onboardingNext.disabled = false;
      });
    });
  } catch (error) {
    onboardingBody.innerHTML = `<p>加载提供商列表失败: ${escapeHtml(error.message)}</p>`;
  }
}

function renderApiKeyStep() {
  onboardingBody.innerHTML = `
    <p>端点已根据提供商自动填入。密钥只会保存在当前项目的 <code>.env</code> 文件中。</p>
    <label class="field" for="obApiBase">
      <span>API 端点（Base URL）</span>
      <input id="obApiBase" value="${escapeHtml(onboardingData.apiBase)}" placeholder="https://api.deepseek.com/v1" />
    </label>
    <div class="field">
      <label for="obApiKey">API 密钥${onboardingData.provider === "ollama" ? "（本地 Ollama 可填写 ollama）" : ""}</label>
      <div class="secret-field">
        <input id="obApiKey" type="password" value="${escapeHtml(onboardingData.apiKey)}" placeholder="sk-..." autocomplete="off" />
        <button class="ghost-button" type="button" id="obToggleKey" aria-label="显示 API 密钥">显示</button>
      </div>
      <span class="field-hint">${onboardingData.provider === "ollama" ? "兼容令牌已自动填写，无需修改。" : "填写完整后即可继续。"}</span>
    </div>
  `;
  const apiBaseInput = document.querySelector("#obApiBase");
  const apiKeyInput = document.querySelector("#obApiKey");
  const toggleBtn = document.querySelector("#obToggleKey");

  const updateApiStep = () => {
    onboardingData.apiBase = apiBaseInput.value.trim();
    onboardingData.apiKey = apiKeyInput.value.trim();
    onboardingNext.disabled = !onboardingData.apiBase || !onboardingData.apiKey;
  };
  apiBaseInput.addEventListener("input", updateApiStep);
  apiKeyInput.addEventListener("input", updateApiStep);
  toggleBtn.addEventListener("click", () => {
    if (apiKeyInput.type === "password") {
      apiKeyInput.type = "text";
      toggleBtn.textContent = "隐藏";
      toggleBtn.setAttribute("aria-label", "隐藏 API 密钥");
    } else {
      apiKeyInput.type = "password";
      toggleBtn.textContent = "显示";
      toggleBtn.setAttribute("aria-label", "显示 API 密钥");
    }
  });
  updateApiStep();
}

function renderModelTestStep() {
  onboardingBody.innerHTML = `
    <p>推荐模型已自动填写。点击测试，确认写作与实验所需模型都能正常响应。</p>
    <label class="field" for="obDefaultModel">
      <span>主力模型 <small>用于编码、灵敏度分析</small></span>
      <input id="obDefaultModel" value="${escapeHtml(onboardingData.defaultModel)}" />
    </label>
    <label class="field" for="obStrongModel">
      <span>强力模型 <small>用于分析、建模、写作与评审</small></span>
      <input id="obStrongModel" value="${escapeHtml(onboardingData.strongModel)}" />
    </label>
    <label class="field" for="obFigureModel">
      <span>图像模型 <small>用于图表评审与图说生成</small></span>
      <input id="obFigureModel" value="${escapeHtml(onboardingData.figureModel)}" />
      <span class="field-hint">需支持视觉输入；留空则回退到强力模型</span>
    </label>
    <button class="primary-button" type="button" id="obTestBtn">测试模型连接</button>
    <div id="obTestResult"></div>
  `;
  const dmInput = document.querySelector("#obDefaultModel");
  const smInput = document.querySelector("#obStrongModel");
  const fmInput = document.querySelector("#obFigureModel");
  dmInput.addEventListener("input", () => { onboardingData.defaultModel = dmInput.value; });
  smInput.addEventListener("input", () => { onboardingData.strongModel = smInput.value; });
  fmInput.addEventListener("input", () => { onboardingData.figureModel = fmInput.value; });

  document.querySelector("#obTestBtn").addEventListener("click", async () => {
    const result = document.querySelector("#obTestResult");
    result.innerHTML = '<p style="color:var(--muted);">测试中...</p>';
    try {
      const figureModel = onboardingData.figureModel || onboardingData.strongModel;
      const [defaultModelResult, strongModelResult, figureModelResult] = await Promise.all([
        testLlm(onboardingData.apiBase, onboardingData.apiKey, onboardingData.defaultModel),
        testLlm(onboardingData.apiBase, onboardingData.apiKey, onboardingData.strongModel),
        figureModel ? testLlm(onboardingData.apiBase, onboardingData.apiKey, figureModel) : Promise.resolve(null),
      ]);
      let html = renderTestResult("主力模型", defaultModelResult) + renderTestResult("强力模型", strongModelResult);
      if (figureModelResult) html += renderTestResult("图像模型", figureModelResult);
      result.innerHTML = html;
      const allOk = defaultModelResult.success && strongModelResult.success && (!figureModelResult || figureModelResult.success);
      onboardingNext.disabled = !allOk;
    } catch (error) {
      result.innerHTML = `<div class="test-result fail">测试失败: ${escapeHtml(error.message)}</div>`;
    }
  });
  onboardingNext.disabled = true;
}

async function testLlm(apiBase, apiKey, model) {
  return await api("/api/config/test-llm", {
    method: "POST",
    body: JSON.stringify({ apiBase, apiKey, model }),
  });
}

function renderTestResult(label, result) {
  const cls = result.success ? "ok" : "fail";
  const text = result.success
    ? `✓ ${escapeHtml(label)} 连接成功 · ${result.latency_ms}ms`
    : `✗ ${escapeHtml(label)} 失败: ${escapeHtml(result.error || "未知错误")}`;
  return `<div class="test-result ${cls}">${text}</div>`;
}

async function renderCompleteStep() {
  onboardingNext.disabled = true;
  try {
    await api("/api/config", {
      method: "POST",
      body: JSON.stringify({
        apiBase: onboardingData.apiBase,
        apiKey: onboardingData.apiKey,
        defaultModel: onboardingData.defaultModel,
        strongModel: onboardingData.strongModel,
        figureModel: onboardingData.figureModel,
      }),
    });
  } catch (error) {
    showToast(`保存配置失败: ${error.message}`);
    onboardingBody.innerHTML = `
      <div class="save-error">
        <strong>配置暂未保存</strong>
        <p>${escapeHtml(error.message)}</p>
        <button class="primary-button" type="button" id="obRetrySave">重试保存</button>
      </div>
    `;
    document.querySelector("#obRetrySave").addEventListener("click", renderCompleteStep);
    return;
  }

  onboardingBody.innerHTML = `
    <div class="onboarding-complete">
      <div class="complete-mark" aria-hidden="true">✓</div>
      <h3>配置完成</h3>
      <p>配置已保存。进入工作台后，先上传赛题或使用示例体验。</p>
      <div class="config-summary">
        <p><strong>端点:</strong> ${escapeHtml(onboardingData.apiBase)}</p>
        <p><strong>主力模型:</strong> ${escapeHtml(onboardingData.defaultModel)}</p>
        <p><strong>强力模型:</strong> ${escapeHtml(onboardingData.strongModel)}</p>
        <p><strong>图像模型:</strong> ${escapeHtml(onboardingData.figureModel || "(回退到强力模型)")}</p>
      </div>
    </div>
  `;
  onboardingNext.disabled = false;
}

onboardingPrev?.addEventListener("click", () => {
  if (onboardingStep > 1) {
    onboardingStep--;
    renderOnboardingStep();
  }
});

onboardingNext?.addEventListener("click", () => {
  if (onboardingStep < 5) {
    onboardingStep++;
    renderOnboardingStep();
  } else {
    hideOnboarding();
    showToast("配置完成，请先导入赛题");
  }
});

// ============ 设置页面 ============

let settingsTab = "api";
let settingsConfig = null;

async function loadSettings() {
  try {
    settingsConfig = await api("/api/config");
    renderSettings();
  } catch (error) {
    settingsContent.innerHTML = `<p>加载配置失败: ${escapeHtml(error.message)}</p>`;
  }
}

function renderSettings() {
  if (!settingsConfig) return;
  if (settingsTab === "api") renderSettingsApi();
  else if (settingsTab === "models") renderSettingsModels();
  else if (settingsTab === "rag") renderSettingsRag();
  else if (settingsTab === "advanced") renderSettingsAdvanced();
}

function renderSettingsApi() {
  settingsContent.innerHTML = `
    <div class="field">
      <span>API 端点</span>
      <input id="setApiBase" value="${escapeHtml(settingsConfig.apiBase)}" />
      <span class="field-hint">OpenAI 兼容端点地址</span>
    </div>
    <div class="field">
      <span>API 密钥</span>
      <div style="display:flex;gap:8px;">
        <input id="setApiKey" type="password" value="${escapeHtml(settingsConfig.apiKey)}" style="flex:1;" />
        <button class="ghost-button" type="button" id="setToggleKey">👁 显示</button>
        <button class="primary-button" type="button" id="setTestBtn">🔍 测试</button>
      </div>
      <div id="setTestResult"></div>
    </div>
  `;
  document.querySelector("#setToggleKey")?.addEventListener("click", (e) => {
    const input = document.querySelector("#setApiKey");
    if (input.type === "password") { input.type = "text"; e.target.textContent = "👁 隐藏"; }
    else { input.type = "password"; e.target.textContent = "👁 显示"; }
  });
  document.querySelector("#setTestBtn")?.addEventListener("click", async () => {
    const apiBase = document.querySelector("#setApiBase").value;
    const apiKey = document.querySelector("#setApiKey").value;
    const model = settingsConfig.defaultModel || "test";
    const result = document.querySelector("#setTestResult");
    result.innerHTML = '<p class="field-hint">测试中...</p>';
    try {
      const r = await testLlm(apiBase, apiKey.includes("***") ? "" : apiKey, model);
      result.innerHTML = r.success
        ? `<div class="test-result ok">✓ 连接成功 · ${r.latency_ms}ms</div>`
        : `<div class="test-result fail">✗ ${escapeHtml(r.error)}</div>`;
    } catch (error) {
      result.innerHTML = `<div class="test-result fail">✗ ${escapeHtml(error.message)}</div>`;
    }
  });
}

function renderSettingsModels() {
  settingsContent.innerHTML = `
    <div class="field">
      <span>主力模型（编码、灵敏度分析）</span>
      <input id="setDefaultModel" value="${escapeHtml(settingsConfig.defaultModel)}" />
      <span class="field-hint">用于 routine 节点，格式：provider/model</span>
    </div>
    <div class="field">
      <span>强力模型（分析、建模、写作、评审）</span>
      <input id="setStrongModel" value="${escapeHtml(settingsConfig.strongModel)}" />
      <span class="field-hint">用于核心节点</span>
    </div>
    <div class="field">
      <span>图像模型（图表评审与图说生成）</span>
      <input id="setFigureModel" value="${escapeHtml(settingsConfig.figureModel)}" />
      <span class="field-hint">需支持视觉输入；留空则回退到强力模型</span>
    </div>
  `;
}

function renderSettingsRag() {
  settingsContent.innerHTML = `
    <div class="toggle-row">
      <div>
        <strong>启用 RAG 知识库</strong>
        <p class="field-hint">启用后注入经典模型模式到提示词</p>
      </div>
      <div class="toggle-switch ${settingsConfig.ragEnabled ? "on" : ""}" id="setRagToggle"></div>
    </div>
    <div class="field">
      <span>Embedding 模型</span>
      <input id="setRagEmbed" value="${escapeHtml(settingsConfig.ragEmbeddingModel)}" />
    </div>
    <div class="field">
      <span>检索 Top-K</span>
      <input id="setRagTopK" type="number" value="${settingsConfig.ragTopK}" />
    </div>
  `;
  document.querySelector("#setRagToggle")?.addEventListener("click", (e) => {
    e.currentTarget.classList.toggle("on");
  });
}

function renderSettingsAdvanced() {
  settingsContent.innerHTML = `
    <div class="field">
      <span>模型迭代轮次上限</span>
      <div style="display:flex;align-items:center;gap:12px;">
        <input id="setIterations" type="range" min="1" max="5" value="${settingsConfig.maxModelIterations}" style="flex:1;" />
        <span id="setIterationsVal" style="font-weight:700;color:var(--blue);">${settingsConfig.maxModelIterations}</span>
      </div>
    </div>
    <div class="field">
      <span>普通调用最长等待（秒）</span>
      <input id="setLlmTimeout" type="number" value="${settingsConfig.llmAttemptTimeout ?? settingsConfig.llmTimeout ?? 180}" />
      <span class="field-hint">analyst、critic、coder 等常规节点；新设置将在下一次新运行或恢复运行时生效</span>
    </div>
    <div class="field">
      <span>长文本调用最长等待（秒）</span>
      <input id="setLlmLongTimeout" type="number" value="${settingsConfig.llmLongAttemptTimeout ?? 300}" />
      <span class="field-hint">writer 大纲/章节、modeler 主模型；包含必要的等待与重试</span>
    </div>
    <div class="field">
      <span>前端端口</span>
      <input id="setPort" type="number" value="${settingsConfig.port}" />
      <span class="field-hint">修改后需重启服务生效</span>
    </div>
  `;
  document.querySelector("#setIterations")?.addEventListener("input", (e) => {
    document.querySelector("#setIterationsVal").textContent = e.target.value;
  });
}

function collectSettings() {
  const config = {};
  const apiBase = document.querySelector("#setApiBase");
  const apiKey = document.querySelector("#setApiKey");
  const defaultModel = document.querySelector("#setDefaultModel");
  const strongModel = document.querySelector("#setStrongModel");
  const figureModel = document.querySelector("#setFigureModel");
  const ragToggle = document.querySelector("#setRagToggle");
  const ragEmbed = document.querySelector("#setRagEmbed");
  const ragTopK = document.querySelector("#setRagTopK");
  const iterations = document.querySelector("#setIterations");
  const llmTimeout = document.querySelector("#setLlmTimeout");
  const llmLongTimeout = document.querySelector("#setLlmLongTimeout");
  const port = document.querySelector("#setPort");

  if (apiBase) config.apiBase = apiBase.value;
  if (apiKey && !apiKey.value.includes("***")) config.apiKey = apiKey.value;
  if (defaultModel) config.defaultModel = defaultModel.value;
  if (strongModel) config.strongModel = strongModel.value;
  if (figureModel) config.figureModel = figureModel.value;
  if (ragToggle) config.ragEnabled = ragToggle.classList.contains("on");
  if (ragEmbed) config.ragEmbeddingModel = ragEmbed.value;
  if (ragTopK) config.ragTopK = Number(ragTopK.value);
  if (iterations) config.maxModelIterations = Number(iterations.value);
  if (llmTimeout) config.llmAttemptTimeout = Number(llmTimeout.value);
  if (llmLongTimeout) config.llmLongAttemptTimeout = Number(llmLongTimeout.value);
  if (port) config.port = Number(port.value);
  return config;
}

settingsNavButtons.forEach((btn) => {
  btn.addEventListener("click", () => {
    settingsNavButtons.forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    settingsTab = btn.dataset.settingsTab;
    renderSettings();
  });
});

settingsSave?.addEventListener("click", async () => {
  try {
    const config = collectSettings();
    await api("/api/config", { method: "POST", body: JSON.stringify(config) });
    showToast("配置已保存。新设置将在下一次新运行或恢复运行时生效。");
    await loadSettings();
  } catch (error) {
    showToast(`保存失败: ${error.message}`);
  }
});

settingsReset?.addEventListener("click", async () => {
  if (!confirm("确定要重置为默认值吗？（模型配置保留，仅重置端点、密钥与运行参数）")) return;
  try {
    await api("/api/config", {
      method: "POST",
      body: JSON.stringify({
        apiBase: "http://localhost:20128/v1",
        apiKey: "123456",
        llmAttemptTimeout: 180,
        llmLongAttemptTimeout: 300,
        maxModelIterations: 3,
        ragEnabled: false,
        ragEmbeddingModel: "ollama/bge-m3",
        ragTopK: 4,
        port: 5173,
      }),
    });
    showToast("已重置为默认值（模型配置保留）");
    await loadSettings();
  } catch (error) {
    showToast(`重置失败: ${error.message}`);
  }
});

// 设置页面导航
function setSettingsView(isSettingsView) {
  dashboardSections.forEach((section) => {
    section.hidden = isSettingsView;
  });
  settingsPanel.hidden = !isSettingsView;
}

activateNav(window.location.hash || "#workspace");

