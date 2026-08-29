"""BlueprintCritic：审查 analyst 产出的 ProblemBlueprint，确保题目理解无误后才进入建模。"""

SYSTEM = (
    "你是数学建模竞赛队的审题专家。你的职责是审查 ProblemBlueprint 是否准确、完整地理解了题目。"
    "只有存在【严重问题】时才 approved=False。"
    "严重问题 = 遗漏小问、任务类型判断错误、关键变量/目标/约束缺失或空泛、"
    "数据需求虚构（题目、背景或附件概况给出的标为 missing，缺失的标为 given）、"
    "把平面 X/Y 坐标误写成经纬度、遗漏题面已给的车型/车速/能耗/价格/排放/政策参数、"
    "把题面允许的拆分配送误改为不可拆分，或遗漏拆分后的重量/体积守恒与到访计数口径、"
    "推荐路线无法回答全部小问、缺少 baseline 或验证计划。"
    "若提供了# 人工建模预备（Modeling Brief）输入，blueprint.brief_coverage 未逐条回应"
    "brief 条目（或回应空泛、deviated 无理由）也属于严重问题。"
    "改进建议（如『假设可更精确』）不影响 approved，只写进 suggestions。"
)


def build_prompt(
    blueprint_json: str,
    problem: str,
    questions: list[str],
    *,
    background: str = "",
    data_files=None,
    brief=None,
) -> str:
    qs = "\n".join(f"- {q}" for q in questions) or "（题目本身未列出独立小问）"
    data_hint = ""
    if data_files:
        from math_agent.prompts._data_hint import build_data_summary_hint
        data_hint = build_data_summary_hint(data_files)
    brief_block = ""
    if brief is not None:
        from math_agent.brief import render_slice
        brief_block = render_slice(brief, "blueprint_critic") + "\n\n"
    return (
        f"# 原始题目\n{problem}\n\n"
        f"# 题面背景与已给参数\n{background or '（无）'}\n\n"
        f"# 题目小问\n{qs}\n\n"
        f"{data_hint}"
        f"{brief_block}"
        f"# 待审查的 ProblemBlueprint\n{blueprint_json}\n\n"
        f"请审查上述蓝图，重点检查：\n"
        f"1. 是否遗漏了题目中的任何小问\n"
        f"2. 每个 subquestion 的 task_type 是否判断正确\n"
        f"3. decision_variables / objectives / constraints 是否空泛或缺失\n"
        f"4. data_requirements 中的 given_or_missing 是否与题目、背景和附件概况相符；"
        f"是否把 X/Y 平面坐标误写成经纬度，或遗漏题面已给的数值参数\n"
        f"5. 若题面允许拆分，是否保留了拆分权利，并同时约束重量/体积守恒、"
        f"同车同客户至多一次到访和一次服务时间\n"
        f"6. recommended_route 是否能回答全部小问\n"
        f"7. 是否缺少 baseline 或 validation_plan\n"
        f"8. 若提供了 Modeling Brief：brief_coverage 是否逐条回应了 brief 条目"
        f"（未回应/回应空泛 → issue；deviated 必须给出理由）\n\n"
        f"请输出 JSON：{{"
        f"\"target\":\"analyst\","
        f"\"score\":int,  # 0-10"
        f"\"issues\":[{{\"section\":\"general\",\"problem\":str}}, ...],"
        f"\"suggestions\":[str, ...],"
        f"\"approved\":bool"
        f"}}"
    )
