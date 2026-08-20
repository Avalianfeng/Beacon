"""Modeler：依据当前 stage 和 ProblemBlueprint 产出对应版本的模型。"""

SYSTEM = (
    "你是数学建模队的主建模手。请在给定 ProblemBlueprint 和假设下构建数学模型。"
    "你必须按照 stage 渐进：basic（最简可解模型）-> improved（加入更多现实因素）"
    "-> final（综合性最强、可被敏感性分析的最终模型）。"
    "模型必须沿 ProblemBlueprint 的决策变量、目标、约束建模。"
    "如果新增了不在 blueprint 中的变量、目标或约束，必须在 notes 中说明原因。"
    "输出要紧凑、可计算，不写教材式长篇解释；公式按名称分组，避免为同一约束堆叠同义公式。"
    "若公式含变量乘积或时间依赖函数，必须说明可执行的离散化、分段线性化或启发式求值方式。"
    "不要为了声称 MILP 而写不完整的大 M 或 SOS2 约束；若实现采用递推仿真与启发式，"
    "就明确给出可执行的递推、可行性判定与搜索规则。变量表必须定义方程中的每一个符号。"
    "题面已经给出的参数不得改写成经验值或另行估计。"
)


def _blueprint_summary(blueprint) -> str:
    if blueprint is None:
        return "（无 ProblemBlueprint）"
    lines = [f"核心任务：{blueprint.core_task}"]
    if blueprint.subquestions:
        sq = "\n".join(
            f"  - [{s.id}] ({s.task_type}) {s.original_text}"
            for s in blueprint.subquestions
        )
        lines.append(f"小问：\n{sq}")
    if blueprint.decision_variables:
        dv = "\n".join(f"  - {v.name}: {v.meaning}" for v in blueprint.decision_variables)
        lines.append(f"决策变量：\n{dv}")
    if blueprint.objectives:
        ob = "\n".join(f"  - [{o.direction}] {o.description}" for o in blueprint.objectives)
        lines.append(f"目标：\n{ob}")
    if blueprint.constraints:
        cs = "\n".join(f"  - [{c.source}] {c.description}" for c in blueprint.constraints)
        lines.append(f"约束：\n{cs}")
    if blueprint.metrics:
        mt = "\n".join(f"  - {m.name} ({m.direction}): {m.meaning}" for m in blueprint.metrics)
        lines.append(f"指标：\n{mt}")
    if blueprint.validation_plan:
        vp = "\n".join(f"  - {v.target}: {v.method}" for v in blueprint.validation_plan)
        lines.append(f"验证计划：\n{vp}")
    return "\n".join(lines)


def build_prompt(problem, assumptions, prev_model, stage, critic_feedback=None,
                 retrieved_context: str = "", blueprint=None, brief=None):
    asum = "\n".join(f"- {a.statement}（依据：{a.rationale}）" for a in assumptions) or "（暂无）"
    prev = "（无前一版本）"
    if prev_model is not None:
        prev = f"[{prev_model.stage}] {prev_model.description}\n方程：" + " ; ".join(prev_model.equations)
    fb = ""
    if critic_feedback:
        fb = "\n# 上一版 Critic 反馈\n" + "\n".join(
            f"- 问题: {i.problem}" for i in critic_feedback.issues
        ) + "\n" + "\n".join(f"- 建议: {s}" for s in critic_feedback.suggestions)
    ctx = f"\n{retrieved_context}\n" if retrieved_context else ""
    bp = f"\n# Problem Blueprint\n{_blueprint_summary(blueprint)}\n" if blueprint is not None else ""
    brief_block = ""
    if brief is not None:
        from math_agent.brief import render_modeler_brief
        brief_block = f"\n{render_modeler_brief(brief)}\n"

    # Plan D Phase 3：final 阶段才要求 figure_purposes（basic/improved 不需要图，
    # 字段在 ModelVersion 里默认空 list，prompt 也不提及，避免污染早期建模）
    figure_clause = ""
    coverage_clause = ""
    if stage == "final":
        figure_clause = (
            f"  \"figure_purposes\": [str, ...], # 5-10 个图任务，每个是一句话描述要画的图，"
            f"如 '需求时序图', '调度路径图', '成本构成饼图', '敏感性曲线'\n"
        )
        # final 阶段要求 blueprint 对齐映射
        coverage_clause = (
            f"  \"question_coverage\": [  # 覆盖 blueprint 中的每个小问\n"
            f'    {{"question_id": str, "how_answered": str, '
            f'"related_equations": [str], "related_metrics": [str]}}\n'
            f"    # how_answered 必须引用具体的 equation 名称或 variable 名称"
            f"（如 '由公式 E_dispatch 求解'），不允许纯自然语言描述\n"
            f"  ],\n"
            f"  \"objective_mapping\": [str, ...],   # 每个 objective 对应哪些 equation\n"
            f"  \"constraint_mapping\": [str, ...],  # 每个 constraint 对应哪些 equation\n"
            f"  \"validation_mapping\": [str, ...],  # 每个 validation_plan item 如何在模型中体现\n"
        )
        coverage_clause += (
            "  # final 质量要求：每个小问都必须有可由代码计算的回答指标；"
            "优化模型至少给出一个主方案、两个有效基线和一种稳健性/敏感性验证接口。"
            "若含拆分配送，不得把所有需求预先切成最小车辆碎片并对每个碎片重复计服务成本，"
            "应定义连续拆分量或可复算的装载/合并规则。若含动态事件，必须把未启用备用资源、"
            "增量成本、冻结边界和失败升级策略纳入模型。\n"
        )

    return (
        f"# 题目\n{problem}\n\n# 当前阶段\n{stage}\n\n"
        f"{bp}"
        f"{brief_block}"
        f"# 已确认假设\n{asum}\n\n# 上一版模型\n{prev}\n{fb}\n"
        f"{ctx}\n"
        f"请输出 JSON：{{\n"
        f"  \"stage\": \"{stage}\",\n"
        f"  \"description\": str,        # 模型定位与核心思路，200-600个中文字符\n"
        f"  \"equations\": [str, ...],   # 10-24条带名称的核心 LaTeX 公式，单条不超过500字符\n"
        f"  \"variables\": {{name: meaning}},\n"
        f"{figure_clause}{coverage_clause}"
        f"  \"notes\": str               # 与上一版的区别（basic 阶段可为空）\n"
        f"}}"
    )
