"""ModelCodeConsistency：审查代码是否真正实现 final model。

输入：ProblemBlueprint、final model、最新批次成功主方案代码摘要与 stdout、
baseline stdout、失败 artifact 的 stderr 摘要。
输出：ModelCodeConsistencyReport，含变量/目标/约束的对齐明细。
"""

SYSTEM = (
    "你是数学建模竞赛队的代码审查专家。你的职责是审查生成的代码是否真正实现了 final model 的"
    "核心变量、目标函数和约束，以及代码输出的指标是否与 blueprint 中的 metrics 对齐。"
    "只有存在【严重不一致】时才 approved=False。"
    "严重不一致 = 代码缺少模型核心变量、目标函数未实现、关键约束被忽略、"
    "stdout 没有输出 blueprint 要求的关键指标、baseline 与主方案使用了不同的指标名、"
    "【数值与工程合理范围严重不符】（如 blueprint validation pass_criteria 给出的合理区间"
    "100-500 N·m 而输出 0.37 N·m，或同一次运行内部自相矛盾：T_y_shank=928611 而 Tmax=0.37）。"
    "注意：数值严重不符（数量级错误）即使代码结构完整也必须 approved=False，且 score 不得超过 5。"
    "approved=True 需要 score >= 8。"
)


def build_prompt(blueprint_json: str, model_json: str,
                 main_code_summaries: str, main_stdout: str,
                 baseline_stdout: str, failed_stderr: str) -> str:
    return (
        f"# Problem Blueprint\n{blueprint_json}\n\n"
        f"# Final Model\n{model_json}\n\n"
        f"# 成功主方案代码摘要（最新批次）\n{main_code_summaries}\n\n"
        f"# 主方案 stdout\n{main_stdout}\n\n"
        f"# Baseline stdout\n{baseline_stdout}\n\n"
        f"# 失败 artifact stderr 摘要\n{failed_stderr}\n\n"
        f"请审查代码与模型的一致性，逐项检查：\n"
        f"1. 模型的核心变量是否在代码中实现（implemented_variables / missing_variables）\n"
        f"2. 目标函数是否在代码中实现（implemented_objectives / missing_objectives）\n"
        f"3. 约束是否在代码中实现（implemented_constraints / missing_constraints）\n"
        f"4. stdout 输出的指标是否与 blueprint.metrics 对齐（output_metric_alignment）\n"
        f"5. baseline 与主方案是否使用相同指标名\n"
        f"6. 【数值合理性】对照 blueprint.validation_mapping 中各 pass_criteria 的合理区间"
        f"（如“结果在合理范围（如 100-500 N·m）”）与工程常识检查 stdout 数值的数量级："
        f"数量级错误（如 Tmax 应为数百 N·m 却输出 0.37）、同一次运行内部数值自相矛盾、"
        f"或与 blueprint 指标单位不符，均属于严重不一致，必须 approved=False 且 score <= 5。\n\n"
        f"请输出 JSON：{{"
        f"\"score\": int,  # 0-10"
        f"\"approved\": bool,"
        f"\"implemented_variables\": [str, ...],"
        f"\"missing_variables\": [str, ...],"
        f"\"implemented_objectives\": [str, ...],"
        f"\"missing_objectives\": [str, ...],"
        f"\"implemented_constraints\": [str, ...],"
        f"\"missing_constraints\": [str, ...],"
        f"\"output_metric_alignment\": [str, ...],"
        f"\"issues\": [str, ...],"
        f"\"suggestions\": [str, ...]"
        f"}}"
    )
