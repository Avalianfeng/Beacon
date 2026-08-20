"""Coder：单图代码生成 prompt。"""

import re

from math_agent.prompts.coder import SYSTEM  # noqa: F401


def metric_vars(metrics) -> list[tuple[str, str]]:
    """返回 [(指标名, 示例变量名), ...]；变量名保证是合法 Python 标识符。

    指标名（如“R²”“安全裕度”）原样保留在 RESULT 行里作标签，变量名统一为
    m0/m1/…，避免把中文或上标硬拼进 Python 变量。
    """
    return [(m.name, f"m{i}") for i, m in enumerate(metrics)]


def _blueprint_metrics_hint(blueprint) -> str:
    """从 blueprint 提取关键指标，提醒代码至少输出这些数值。"""
    if blueprint is None or not blueprint.metrics:
        return ""
    metric_names = ", ".join(m.name for m in blueprint.metrics)
    return (
        f"\n# Blueprint 指标（代码至少输出以下关键指标）\n{metric_names}\n"
        f"代码需要覆盖 final model 的核心变量、目标函数与关键约束。\n"
    )


def _subquestions_output_hint(blueprint) -> str:
    """逐问列出 blueprint.subquestions 的 expected_output，要求主证据代码
    对每个子问题都输出对应的可核验数值。

    背景：paper_critic 以代码 stdout 为唯一数字事实源；若主证据代码只输出
    metrics 而漏掉各问的关键结论，正文声称的定量结论会被判为“无证据”。
    因此这里把 analyst 解析出的每问预期输出织入 coder prompt，强制代码逐问打印。
    """
    if blueprint is None or not blueprint.subquestions:
        return ""
    items = []
    for sub in blueprint.subquestions:
        qid = str(sub.id or "")
        expect = str(sub.expected_output or "").strip()
        if not qid or not expect:
            continue
        short = expect.replace("\n", " ")[:120]
        items.append(f"- 问题 {qid}：{short}")
    if not items:
        return ""
    return (
        "\n# 逐问数值输出要求（论文评审以 stdout 为唯一数字事实源）\n"
        "主证据脚本必须对下列每个子问题都计算并打印其 expected_output 中的"
        "关键数值，不得只输出 Blueprint 指标：\n"
        + "\n".join(items)
        + "\n"
        "输出约定：每个子问题的数值用一行 `Q<问题id>: <字段名>=<数值> ...` "
        "打印（字段名可用中文或英文，数值为有限浮点），例如：\n"
        "print(f'Q1.2: 临界预紧力矩={critical_torque:.2f} N·m')\n"
        "print(f'Q2.2: Tmax_A={tmax_a:.2f} Tmax_B={tmax_b:.2f} 加钢带={use_steel}')\n"
        "缺失或无法计算的子问题必须在 stdout 明确说明原因，不得静默跳过。\n"
    )


def _no_masking_hint() -> str:
    """禁止用 max(0, x)/clip 掩盖真实负值或越界结果。"""
    return (
        "\n# 禁止截断掩盖（硬性要求）\n"
        "凡指标为负值、比例越界或物理上不允许的结果，必须打印真实计算值并"
        "说明含义（如“安全裕度为负表示超限”），禁止用 max(0, ...)/clip/截断"
        "把它伪装成 0 或边界值；仅当指标定义本身要求裁剪（如拟合 R² 因数值"
        "噪声略超 [0,1]）时才允许 clip，且必须在 stdout 打印裁剪前的原始值。\n"
    )


def _result_format_hint(blueprint) -> str:
    """按 blueprint.metrics 生成 RESULT 行的格式约束。"""
    if blueprint is None or not blueprint.metrics:
        return (
            "脚本末尾必须用 print 输出 RESULT 行，格式：\n"
            "print(f'RESULT: baseline=ours <本题指标名>=<数值> ...')\n"
            "指标名必须来自本题模型/Blueprint，不得套用其它赛题的指标口径。\n"
        )
    pairs = metric_vars(blueprint.metrics)
    fields = " ".join(f"{name}={{{var}}}" for name, var in pairs)
    names = "、".join(m.name for m in blueprint.metrics)
    return (
        "脚本末尾必须用 print 输出 RESULT 行，格式严格为：\n"
        f"print(f'RESULT: baseline=ours {fields}')\n"
        "（f-string 里的数值变量名（如 m0/m1）可替换为你的变量名；"
        "但 RESULT 行里的指标标签名必须与 Blueprint 指标一字不差，"
        f"共 {len(blueprint.metrics)} 个：{names}。\n"
        "禁止改名、禁止只输出其中一部分、禁止新增未要求的指标字段。）\n"
    )


def _truncate_model_context(model) -> tuple[str, str, str]:
    """压缩 coder prompt，避免把完整建模细节都喂给画图代码生成。"""
    desc = (model.description or "")[:1200]

    equations = list(model.equations or [])
    eq_preview = equations[:12]
    eqs = "\n".join(f"- {e}" for e in eq_preview) or "（暂时无）"
    if len(equations) > len(eq_preview):
        eqs += f"\n- ……其余 {len(equations) - len(eq_preview)} 条方程省略"

    variables = list((model.variables or {}).items())
    var_preview = variables[:20]
    vars_ = "\n".join(f"- {k}: {v}" for k, v in var_preview) or "（暂时无）"
    if len(variables) > len(var_preview):
        vars_ += f"\n- ……其余 {len(variables) - len(var_preview)} 个变量省略"

    return desc, eqs, vars_


def build_prompt_figure_one(model, purpose: str, prev_failure=None, prev_error_kind: str = "",
                            blueprint=None, data_dir=None, data_files=None,
                            canonical_evidence: str = "", previous_code: str = "",
                            brief=None):
    """构造单图代码生成 prompt。"""
    desc, eqs, vars_ = _truncate_model_context(model)
    fb = ""
    if prev_failure:
        if prev_error_kind == "timeout":
            fb = (
                "\n# 上次运行超时\n"
                f"标记：{prev_failure[:200]}\n"
                "请大幅缩小数据规模、迭代次数或求解精度，确保单脚本 60 秒内完成；"
                "优先保留图所需的核心逻辑，不必追求完整大规模最优求解。\n"
            )
        else:
            fb = (
                "\n# 上次运行失败（runtime）\n"
                f"stderr 节选：\n{prev_failure[:1000]}\n"
                "请修复后重试。\n"
            )

    metrics_hint = _blueprint_metrics_hint(blueprint)
    # 支撑图复用主方案证据，不再重复逐问求解；只有主证据图需要逐问数值输出。
    subquestions_hint = _subquestions_output_hint(blueprint) if not canonical_evidence else ""
    no_masking_hint = _no_masking_hint()
    data_hint = ""
    if data_dir and data_files:
        from math_agent.prompts._data_hint import build_data_hint
        data_hint = build_data_hint(data_dir, data_files)
    brief_hint = ""
    if brief is not None:
        from math_agent.brief import render_coder_brief
        brief_hint = render_coder_brief(brief) + "\n"
    canonical_hint = ""
    if canonical_evidence:
        canonical_hint = (
            "\n# 已通过校验的唯一主方案证据\n"
            f"{canonical_evidence[:1500]}\n"
            "本任务是补充可视化：必须复用上述数值，不得重新求解出另一套主方案指标；"
            "脚本末尾原样输出同一组 RESULT。\n"
            "补充图代码控制在 100 行以内，只读取绘图所需列。\n"
            "禁止改用另一套指标名。\n"
        )
    else:
        canonical_hint = (
            "\n# 首次主求解的资源约束\n"
            "这是本批次唯一的主数值证据。必须基于真实附件数据完成一个可复现的轻量求解，"
            "代码建议不超过 180 行、运行不超过 60 秒、内存不超过 1 GB。\n"
            "先完整计算题目要求的全部指标并得到 RESULT 行，再绘制一张核心证据图。\n"
            "必须真正读取附件数据，注意列名与单位换算，不得硬编码结果数值或伪造中间量；"
            "所有输出数值必须是有限数（禁止 NaN/Inf），比例类指标必须在 [0,1]。\n"
            "禁止用占位随机数据代替真实数据；数据缺失时按题面约定处理或 raise，"
            "不得打印错误后继续输出 RESULT。\n"
            "Excel 附件必须遍历全部工作表（pd.ExcelFile.sheet_names 或 "
            "sheet_name=None），禁止只读默认第一张表。\n"
        )

    repair_hint = ""
    if previous_code:
        repair_hint = (
            "\n# 上一版可运行脚本（本次应做最小定向修复）\n"
            f"```python\n{previous_code[:24000]}\n```\n"
            "保留其中已经正确的数据读取、算法和输出结构，只修复 stderr 指向的问题；"
            "不要从零重写，也不要改变已有 RESULT 指标口径。\n"
        )

    return (
        f"# 模型摘要\n{desc}\n\n"
        f"# 核心方程（节选）\n{eqs}\n\n"
        f"# 核心变量（节选）\n{vars_}\n\n"
        f"# 当前绘图任务\n{purpose}\n"
        f"{metrics_hint}{subquestions_hint}{data_hint}{brief_hint}{canonical_hint}{fb}{repair_hint}\n"
        f"请为上述绘图任务生成一段独立可运行的 Python 脚本。\n"
        f"优先使用标准库 + numpy + matplotlib；除非确有必要，不要依赖 pandas、seaborn、networkx 等额外库。\n"
        f"如果任务属于鲁棒性或敏感性图，请用小规模、轻量级实验设计，保证单脚本 60 秒内完成。\n"
        "算法只服务本题模型，禁止套用无关赛题或模板。\n"
        "请直接输出正常的多行 Python 源码，不要把整段 code 写成带字面量 \\n 的转义字符串。\n"
        f"若标题、注释、docstring 里需要反斜杠或 LaTeX 记号，请使用原始字符串或双反斜杠，避免非法转义。\n"
        f"注释纪律：代码无需任何行内注释；如需说明，只能在功能块上方写一行中文注释；"
        f"注释内禁止出现字面量 \\n、\\t 等转义序列——需要换行就写真正的换行，"
        f"否则 # 之后同一行的语句会被吞进注释导致 NameError/SyntaxError。\n"
        f"{no_masking_hint}"
        f"{_result_format_hint(blueprint)}"
        f"{_result_common_hint()}"
        f"{_unit_sanity_hint(blueprint)}"
        f"请输出 JSON：{{\"purpose\": str, \"code\": str}}，code 字段是完整的 Python 源码。"
    )


def _unit_sanity_hint(blueprint) -> str:
    """数值数量级自检：把 blueprint 的校验标准与单位约定变成硬性要求。"""
    criteria: list[str] = []
    if blueprint is not None:
        plan = getattr(blueprint, "validation_plan", None) or []
        for item in plan:
            pc = str(getattr(item, "pass_criteria", "") or "").strip()
            if pc and pc not in criteria:
                criteria.append(pc)
        for metric in getattr(blueprint, "metrics", None) or []:
            unit = str(getattr(metric, "unit", "") or "").strip()
            name = str(getattr(metric, "name", "") or "").strip()
            if unit and name:
                criteria.append(f"{name} 的单位应为 {unit}")
    if not criteria:
        return ""
    bullets = "\n".join(f"- {c}" for c in criteria[:6])
    return (
        "\n# 数值数量级自检（硬性要求）\n"
        f"blueprint 的校验标准（必须逐条满足，否则视为执行失败）：\n{bullets}\n"
        "输出 RESULT 行前必须做单位自检：若任一数值偏离工程合理数量级，"
        "说明单位换算错误（kN↔N、mm↔m、MPa↔Pa 等），修正公式后再输出；"
        "同一次运行内部数值必须自洽。\n"
    )


def _result_common_hint() -> str:
    """RESULT 行的公共约束。"""
    lines = [
        "stdout 不允许只输出自然语言总结，必须包含 RESULT: 行并带具体数值。\n\n",
        "发生数据读取或求解异常时必须 raise 并以非零状态退出，不能打印错误后继续输出 RESULT。\n",
        "stdout 全部输出（含调试 print、Q<id> 行、图表标题标签）都不得出现 nan 或 inf 字样；"
        "所有打印数值必须是有限数。\n",
        "模型真实不可用时的声明协议：若某字段因数学模型在参数域内数学上不可用，"
        "禁止伪造一个数值凑数，也禁止打印 nan/inf；应在 stdout 输出一行：\n"
        "  LIMITATION: <问题id或字段> <具体数学原因，不得含 nan/inf 字样>\n"
        "被声明字段允许从 RESULT 行缺失（门禁按 LIMITATION 豁免），其余字段仍须"
        "输出有限数值且至少保留一半指标；空洞声明（如“LIMITATION: 无”）无效。\n",
    ]
    return "\n# RESULT 行输出规范\n" + "".join(lines)
