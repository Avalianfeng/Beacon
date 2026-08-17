"""Coder：单图代码生成 prompt。"""

import re

from math_agent.prompts.coder import SYSTEM  # noqa: F401

# 城市绿色物流题独有的附件清单；其它题目一律不得使用物流模板语义。
_GREEN_LOGISTICS_FILES = frozenset({
    "订单信息.xlsx", "距离矩阵.xlsx", "时间窗.xlsx", "客户坐标信息.xlsx",
})

# 城市绿色物流题的专用指标名；非物流题生成代码必须禁止。
_GREEN_METRIC_NAMES = (
    "total_cost", "vehicles", "service_rate", "total_carbon",
    "avg_delivery_time", "fuel_vehicles", "ev_vehicles",
    "total_distance", "timewin_rate", "response_time",
)


def _green_logistics(data_files) -> bool:
    """data_files 是否命中城市绿色物流附件 schema。"""
    if not data_files:
        return False
    filenames = {
        str(info.get("filename") if isinstance(info, dict) else info.filename)
        for info in data_files
    }
    return _GREEN_LOGISTICS_FILES <= filenames


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
    metrics 而漏掉各问的关键结论（如临界预紧力矩、工况 A/B 的 Tmax、钢带
    结论、Topt(f) 等），正文声称的定量结论会被判为“无证据”。因此这里把
    analyst 解析出的每问预期输出织入 coder prompt，强制代码逐问打印。
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
        "缺失或无法计算的子问题必须在 stdout 明确说明原因（如“Q3.2: 附件无偏心"
        "数据，按规范取 e=0 计算”），不得静默跳过。\n"
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


def _forbidden_green_metrics_hint() -> str:
    return (
        "禁止输出与本题无关的物流指标名，包括但不限于："
        + ", ".join(_GREEN_METRIC_NAMES) + "。\n"
    )


def _result_format_hint(blueprint, green: bool) -> str:
    """按 blueprint.metrics 生成 RESULT 行的格式约束。"""
    if green:
        return (
            "脚本末尾必须用 print 输出关键指标，格式严格如下：\n"
            "print(f'RESULT: baseline=ours total_cost={{total_cost}} vehicles={{vehicles}} "
            "service_rate={{service_rate}} total_carbon={{total_carbon}} "
            "avg_delivery_time={{avg_delivery_time}}')\n"
        )
    if blueprint is None or not blueprint.metrics:
        return (
            "脚本末尾必须用 print 输出 RESULT 行，格式：\n"
            "print(f'RESULT: baseline=ours <本题指标名>=<数值> ...')\n"
            "指标名必须来自本题模型/Blueprint，不得套用其它赛题的指标口径。\n"
            + _forbidden_green_metrics_hint()
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
        "禁止改名（如 R² 不得写成 R_squared、安全裕度不得写成 safety_margin）、"
        "禁止只输出其中一部分、禁止新增未要求的指标字段。）\n"
        + _forbidden_green_metrics_hint()
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
                            canonical_evidence: str = "", previous_code: str = ""):
    """构造单图代码生成 prompt。"""
    green = _green_logistics(data_files)
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
    canonical_hint = ""
    if canonical_evidence:
        base = (
            "\n# 已通过校验的唯一主方案证据\n"
            f"{canonical_evidence[:1500]}\n"
            "本任务是补充可视化：必须复用上述数值，不得重新求解出另一套主方案指标；"
            "脚本末尾原样输出同一组 RESULT。\n"
            "补充图代码控制在 100 行以内，只读取绘图所需列。\n"
        )
        if green:
            canonical_hint = base + "禁止重新运行路径优化。\n"
        else:
            canonical_hint = (
                base + "禁止改用另一套指标名；尤其不得改成物流调度指标。\n"
            )
    elif green:
        canonical_hint = (
            "\n# 首次主求解的资源约束\n"
            "这是本批次唯一的主数值证据。必须基于真实数据完成一个可复现的轻量启发式，"
            "代码建议不超过 180 行、运行不超过 60 秒、内存不超过 1 GB。\n"
            "允许按客户聚合订单后使用最近邻/贪心插入/滚动局部搜索；"
            "主解不能只做路线内 2-opt：至少加入一种可复算的跨路线 relocate、swap、"
            "路线消除或受限大邻域，并报告改进前后目标值与运行时间。"
            "算法单轮复杂度宜不高于 O(n^2)，可设置少量有上限的改进轮次；"
            "禁止 permutations、全路径枚举、"
            "指数分支搜索、超大三维数组和无上限 while。\n"
            "必须明确解析跨表 customer_id 与 HH:MM 时间窗，并输出车辆数、总成本、"
            "服务率、碳排放等可核验指标。\n"
            "客户聚合需求可能超过单车容量：必须拆成容量可行的多次访问，或保持订单级求解；"
            "不得把全部客户机械预切成最小车型碎片后对每个碎片重复收取服务成本；"
            "应在装载过程中按车辆剩余容量动态拆分，或在同客户连续碎片之间合并服务访问。"
            "动态新增订单、地址/时间窗变更与车辆故障必须同时检查现有路线和未启用备用车辆，"
            "并把新增车辆固定成本计入增量目标。\n"
            "禁止 `while unserved` 在无可行客户时原地循环。每轮外层循环必须移除至少一个任务，"
            "否则立即 raise 报错。大型 Excel 距离矩阵应使用 read_only 流式读取或按需距离访问，"
            "禁止复制成 `(i,j)->distance` 的数百万项 Python 字典。\n"
        )
    else:
        canonical_hint = (
            "\n# 首次主求解的资源约束\n"
            "这是本批次唯一的主数值证据。必须基于真实附件数据完成一个可复现的轻量求解，"
            "代码建议不超过 180 行、运行不超过 60 秒、内存不超过 1 GB。\n"
            "先完整计算题目要求的全部指标并得到 RESULT 行，再绘制一张核心证据图。\n"
            "必须真正读取附件数据，注意列名与单位换算（如 kN 与 N、mm 与 m、"
            "角度制与弧度制），不得硬编码结果数值或伪造中间量；"
            "所有输出数值必须是有限数（禁止 NaN/Inf），比例类指标必须在 [0,1]。\n"
            "禁止用占位随机数据代替真实数据；数据缺失时按题面约定处理或 raise，"
            "不得打印错误后继续输出 RESULT。\n"
            "Excel 附件必须遍历全部工作表（pd.ExcelFile.sheet_names 或 "
            "sheet_name=None），禁止只读默认第一张表。\n"
            + _forbidden_green_metrics_hint()
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
        f"{metrics_hint}{subquestions_hint}{data_hint}{canonical_hint}{fb}{repair_hint}\n"
        f"请为上述绘图任务生成一段独立可运行的 Python 脚本。\n"
        f"优先使用标准库 + numpy + matplotlib；除非确有必要，不要依赖 pandas、seaborn、networkx 等额外库。\n"
        f"如果任务属于鲁棒性或敏感性图，请用小规模、轻量级实验设计，保证单脚本 60 秒内完成。\n"
        + (
            "如果完整 Branch-and-Cut 太重，必须使用上述轻量启发式处理完整客户集合，"
            "不得通过指数枚举追求精确最优。\n"
            if green else
            "算法只服务本题模型，禁止套用车辆路径、配送成本或车队调度模板。\n"
        )
        + "请直接输出正常的多行 Python 源码，不要把整段 code 写成带字面量 \\n 的转义字符串。\n"
        f"若标题、注释、docstring 里需要反斜杠或 LaTeX 记号，请使用原始字符串或双反斜杠，避免非法转义。\n"
        f"{no_masking_hint}"
        f"{_result_format_hint(blueprint, green)}"
        f"{_result_common_hint(green)}"
        f"{_unit_sanity_hint(blueprint)}"
        f"请输出 JSON：{{\"purpose\": str, \"code\": str}}，code 字段是完整的 Python 源码。"
    )


def _unit_sanity_hint(blueprint) -> str:
    """数值数量级自检：把 blueprint 的校验标准与单位约定变成硬性要求。

    r6 根因之一：代码把 P 从 kN 换算成 N 后，K 回归与 Tmax 计算混用两套单位，
    输出 Tmax=0.37 N·m（工程合理范围 100-500 N·m，blueprint validation_plan
    的 pass_criteria 白纸黑字），且同一次运行内 T_y_shank=928611 与 Tmax=0.37
    自相矛盾——一致性评审放行后，错误数值一路流进论文。
    """
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
        "输出 RESULT 行前必须做单位自检：若任一数值偏离工程合理数量级"
        "（如力矩应为数百 N·m 却算出 0.37，或 K 与常规量级差 1000 倍），"
        "说明单位换算错误（kN↔N、mm↔m、MPa↔Pa），修正公式后再输出；"
        "同一次运行内部数值必须自洽（约束上限与最终 Tmax 不可能相差 10^6 倍）。\n"
    )


def _result_common_hint(green: bool) -> str:
    """RESULT 行的公共约束（物流/非物流共有，但计数类表述不同）。"""
    lines = [
        "stdout 不允许只输出自然语言总结，必须包含 RESULT: 行并带具体数值。\n\n",
        "发生数据读取或求解异常时必须 raise 并以非零状态退出，不能打印错误后继续输出 RESULT。\n",
        "stdout 全部输出（含调试 print、Q<id> 行、图表标题标签）都不得出现 nan 或 inf 字样；"
        "对不存在/无约束的项（如无偏心距时的 P_ecc）禁止用 np.inf 或 np.nan 占位，"
        "应改用条件分支跳过该项输出，或用有限数值（如极大有限值）并在文本中说明，"
        "或直接输出“无该项约束”的文字。所有打印数值必须是有限数。\n",
        "模型真实不可用时的声明协议：若某字段因数学模型在参数域内数学上不可用"
        "（如应力公式在极端边界下根号内为负、经验公式超出适用范围、指标无定义），"
        "禁止伪造一个数值凑数，也禁止打印 nan/inf；应在 stdout 输出一行：\n"
        "  LIMITATION: <问题id或字段> <具体数学原因，不得含 nan/inf 字样>\n"
        "例如：LIMITATION: Q3.2 当 e>10mm 时 P_ecc 公式根号内为负，模型不可用。\n"
        "被声明字段允许从 RESULT 行缺失（门禁按 LIMITATION 豁免），其余字段仍须"
        "输出有限数值且至少保留一半指标；空洞声明（如“LIMITATION: 无”）无效。\n"
        "LIMITATION 只用于模型数学边界，不得用于掩盖代码 bug（数据读取失败、"
        "除零、列名错误等必须 raise 修复）。\n",
    ]
    if green:
        lines.append(
            "所有比例指标必须位于 [0,1]，车辆数等计数必须为整数且不得超过输入订单/节点规模。\n\n"
        )
    else:
        lines.append(
            "所有比例指标必须位于 [0,1]，计数类指标必须为整数；任何数值都必须是有限数。\n\n"
        )
    return "\n".join(lines)
