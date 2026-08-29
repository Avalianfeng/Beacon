"""Analyst：把题目分解为 ProblemBlueprint（结构化题目理解资产）。"""

SYSTEM = (
    "你是数学建模竞赛队的首席分析师。你的职责是把题目拆解为一份结构化的 ProblemBlueprint，"
    "覆盖：核心任务、每个小问的任务类型、决策变量、目标、约束、指标、数据需求、假设、"
    "建模候选路线、推荐路线与验证计划。"
    "禁止编造未给出的数据；题目、背景和附件概况中明确出现的数值或字段都属于 given，"
    "不得因为它们不在 Excel 列中就标为 missing。附件坐标若明确为 X/Y 平面坐标，"
    "不得改写成经纬度；题面给出的车型、车速、能耗、价格、排放和政策参数必须进入蓝图。"
    "若题面明确允许拆分配送，不得擅自改成“每个客户只能由一辆车服务”；应把总重量/总体积守恒、"
    "同车同客户至多一次到访、每次真实到访只计一次服务时间写入约束。"
    "数据需求中 given_or_missing 必须如实标注。"
    "problem_domains 从下列固定集合中选取 1-3 个："
    "['optimization', 'time_series', 'machine_learning', 'graph', "
    "'probability', 'queueing', 'simulation', 'generic']。"
    "若提供了# 人工建模预备（Modeling Brief）输入，它是人工确认的建模方向约束："
    "优先级为 题面 > brief > 预训练直觉；blueprint 必须通过 brief_coverage 字段逐条回应"
    "brief 的每一个条目（status=followed 表示遵守并体现在蓝图中；status=deviated 表示"
    "偏离并必须给出理由，如与题面冲突）；与题面冲突时以题面为准并标注偏离。"
    "brief_coverage 条目必须与 brief 条目一一对应，一条不落，不得用笼统的'总体遵守'代替。"
)

# ProblemBlueprint 的 JSON schema 描述（供 LLM 参照输出）
_SCHEMA_HINT = """请输出 JSON，结构与 ProblemBlueprint 一致：
{
  "core_task": str,                          # 题目的核心任务一句话概括
  "subquestions": [                          # 每个小问一条
    {"id": str, "original_text": str,
     "task_type": "evaluation|prediction|optimization|simulation|classification|explanation|strategy|generic",
     "depends_on": [str, ...], "expected_output": str, "success_criteria": [str, ...]}
  ],
  "decision_variables": [                    # 决策变量
    {"name": str, "meaning": str, "domain": str, "unit": str}
  ],
  "objectives": [                            # 目标
    {"direction": "minimize|maximize|evaluate|predict|explain", "description": str, "math_hint": str}
  ],
  "constraints": [                           # 约束
    {"description": str, "math_hint": str, "source": "given|derived|assumed"}
  ],
  "metrics": [                               # 评估指标
    {"name": str, "meaning": str, "direction": "higher_better|lower_better|target|neutral", "unit": str}
  ],
  "data_requirements": [                     # 数据需求（given_or_missing 必须如实标注）
    {"field": str, "meaning": str, "needed_for": str,
     "given_or_missing": "given|missing|derived|unknown", "handling_strategy": str}
  ],
  "assumptions": [                           # 建模假设（至少 5 条）
    {"statement": str, "rationale": str}
  ],
  "problem_domains": [str, ...],
  "modeling_candidates": [                   # 建模候选路线（至少 2 条）
    {"name": str, "route": str, "suitable_for": [str, ...], "data_required": [str, ...],
     "pros": [str, ...], "cons": [str, ...], "risk": str, "recommendation_score": int}
  ],
  "recommended_route": {"route": str, "reason": str, "baseline": str, "fallback": str},
  "validation_plan": [                       # 验证计划
    {"target": str, "method": str, "pass_criteria": str}
  ],
  "risks": [str, ...],
  "brief_coverage": [             # 人工建模预备逐条回应（若提供了 brief；必须与 brief 条目一一对应）
    {"brief_item_id": str,       # brief 中的条目 id（如 "1.2-direction"）
     "status": "followed|deviated",  # deviated 必须给出非空 reason
     "reason": str}
  ]
}"""


def build_prompt(problem: str, background: str, questions: list[str],
                 retrieved_context: str = "",
                 critic_feedback=None,
                 data_files=None,
                 brief=None,
                 gate_problems: list[str] | None = None) -> str:
    qs = "\n".join(f"- {q}" for q in questions) or "（题目本身未列出独立小问）"
    ctx = f"\n{retrieved_context}\n\n" if retrieved_context else ""
    fb = ""
    if critic_feedback is not None:
        issues = "\n".join(f"- {i.problem}" for i in critic_feedback.issues)
        sugs = "\n".join(f"- {s}" for s in critic_feedback.suggestions)
        fb = f"\n# 上一轮 Blueprint Critic 反馈\n问题：\n{issues}\n建议：\n{sugs}\n请据此修正蓝图。\n"
    if gate_problems:
        missing = "\n".join(f"- {p}" for p in gate_problems)
        fb += (
            "\n# brief_coverage 门禁缺口（必须逐条回应下列 id）\n"
            f"{missing}\n"
            "请在 brief_coverage 中为上述每条给出 followed 或 deviated+理由。\n"
        )
    data_hint = ""
    if data_files:
        from math_agent.prompts._data_hint import build_data_summary_hint
        data_hint = build_data_summary_hint(data_files)
    brief_block = ""
    if brief is not None:
        from math_agent.brief import render_slice
        brief_block = render_slice(brief, "analyst") + "\n\n"
    return (
        f"# 题目\n{problem}\n\n"
        f"# 背景\n{background or '（无）'}\n\n"
        f"# 小问\n{qs}\n\n"
        f"{brief_block}{ctx}{data_hint}{fb}{_SCHEMA_HINT}"
    )
