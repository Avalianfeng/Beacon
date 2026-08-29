"""Evaluation Module：与 PaperCritic 解耦的独立打分，更结构化（对齐国赛四大标准 + 加分项）。"""

SYSTEM = (
    "你是国赛阅卷打分官。请独立、严格地按下列维度打分（每项 0-10，整数）："
    "assumption_reasonableness（假设合理性）、modeling_creativity（建模创造性）、"
    "result_correctness（结果正确性）、writing_clarity（文字清晰度）、"
    "extra_depth（加分项：分析深度/敏感性/创新点）。"
    "overall = round("
    "0.2*assumption_reasonableness + 0.25*modeling_creativity + "
    "0.25*result_correctness + 0.2*writing_clarity + 0.1*extra_depth, 2)。"
    "请认真给出 issues 和 suggestions，但不要重复 PaperCritic 已经说过的内容。"
    "\n\n"
    "**口径核查必答项（必须在 issues 中覆盖，不允许省略）**\n"
    "1. 假设依据可验证性：正文『题面明确要求』类声明是否有题面原文依据；"
    "同一假设内『明确要求』与『未要求/未说明』并存视为自相矛盾。\n"
    "2. 大差距根因：任何下界/对照差距 >15% 必须给出机制性解释（瓶颈/排队/运输占比/口径差异），"
    "禁止免责声明；并判断是否源于模型假设口径（如禁止分摊类收紧口径）。\n"
    "3. 数字溯源与敏感性口径：正文数字与代码运行真实输出不符视为编造；"
    "敏感性档位必须出自实跑（不允许证据中不存在的档位数字）。\n"
    "4. 得分点覆盖：若提供评分细则/得分点清单则逐条核对；无则检查题面指定交付物（表/图/代码）齐备性。"
)


def build_prompt(
    paper, figures, sensitivity_runs, paper_critic, table_warnings=None,
    *, depth_signals=None, model_critic=None, consistency=None, brief=None,
):
    crit_summary = "（无 PaperCritic 报告）"
    if paper_critic:
        crit_summary = (
            f"score={paper_critic.score}; issues={[i.problem for i in paper_critic.issues[:5]]}; "
            f"suggestions={paper_critic.suggestions[:5]}"
        )
    warn_summary = ""
    if table_warnings:
        warn_summary = f"\n# table_assembler 清洗记录\n{len(table_warnings)} 处禁用词被替换。\n\n"
    depth_summary = ""
    if depth_signals:
        depth_summary = (
            "# 已通过有效性检查的深度实验\n"
            + "; ".join(f"{key}={bool(value)}" for key, value in depth_signals.items())
            + "\n这些信号只证明相应实验已执行，仍需检查正文是否正确解释其边界。\n\n"
        )
    def excerpt(value: str, limit: int) -> str:
        value = value or ""
        if len(value) <= limit:
            return value
        head = int(limit * 0.65)
        return value[:head] + "\n……（中部省略）……\n" + value[-(limit - head):]

    figure_summary = "\n".join(
        f"- {item.purpose}: quality={item.quality_score}; "
        f"analysis={excerpt(item.analysis, 240)}"
        for item in figures[:10]
    ) or "（无）"
    sensitivity_summary = "\n".join(
        f"- {item.parameter}: {item.values} -> {item.metric}={item.results}"
        for item in sensitivity_runs[:8]
    ) or "（无）"
    brief_block = ""
    if brief is not None:
        from math_agent.brief import render_slice
        rendered = render_slice(brief, "evaluation")
        if rendered:
            brief_block = f"{rendered}\n\n"
    return (
        f"# 论文摘要\n{paper.abstract[:1000]}\n\n"
        f"# 主体代表性节选\n模型：{excerpt(paper.model_section, 3200)}\n\n"
        f"求解：{excerpt(paper.solution, 3200)}\n\n"
        f"敏感性：{excerpt(paper.sensitivity, 1800)}\n\n"
        f"结论：{excerpt(paper.conclusion, 1600)}\n\n"
        f"# 客观信号\n图数={len(figures)}; 平均图质量="
        f"{sum(f.quality_score for f in figures)/max(1,len(figures)):.1f}; "
        f"sensitivity 数={len(sensitivity_runs)}\n\n"
        f"# 图表证据\n{figure_summary}\n\n"
        f"# 敏感性数组\n{sensitivity_summary}\n\n"
        f"# 上游质量证据\n最终模型评审="
        f"{model_critic.model_dump() if model_critic else '缺失'}\n"
        f"模型—代码一致性={consistency.model_dump() if consistency else '缺失'}\n\n"
        f"{warn_summary}"
        f"{depth_summary}"
        f"{brief_block}"
        f"# PaperCritic 摘要\n{crit_summary}\n\n"
        f"请按 schema 输出 JSON。"
    )
