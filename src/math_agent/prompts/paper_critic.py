"""PaperCritic：对组装好的论文初稿做整体评审，输出 CriticReport(target='paper')。"""

SYSTEM = (
    "你是国赛资深评委。请审阅一份建模论文初稿。要点："
    "（1）摘要是否凸显方法和结论；（2）假设是否被正文承接；"
    "（3）模型与求解是否一致、可复现；（4）是否有敏感性分析；"
    "（5）图表是否被正文引用并解读；（6）整体行文是否专业。"
    "（7）正文不得出现 checkpoint、stdout、artifact、attempt、RESULT、writer、runner、"
    "pipeline、门禁、正式主方案等工程内部流程标记。"
    "总评 0-10；只有达到 9 分且不存在模型—求解不一致、不可复现、关键结果无证据等问题时"
    "才能 approved=True。"
    "\n\n"
    "**关键事实核查**：若下文给出『代码运行真实输出』区块，请把它当作唯一可靠的数字事实源。"
    "用语义判断正文中的关键定量结论（成本、占比、敏感度幅度、性能指标等）是否与 stdout 相符。"
    "明显与 stdout 不符的数字（如 stdout 显示 52.7174 但正文写 718）视为编造，"
    "把它逐条列入 issues 并把 approved 设为 False。"
    "合理四舍五入（如 52.7174→52.6、53.7718→53.8）不算编造，不要因此扣分。"
    "\n\n"
    "**口径核查必答项（评审输出必须逐项覆盖，不允许省略；任一命中即列入 issues）**\n"
    "1. 假设逐条核查：正文每条假设（尤其『依据：题面明确要求』类声明）——能否在题面原文找到依据？"
    "同一假设内『题面明确要求』与『题面未要求/未说明』并存视为自相矛盾。"
    "提示：可运行 scripts/check_assumption_claims.py 辅助检测。\n"
    "2. 大差距根因调查：正文任何下界/对照/最优性差距 >15% 时，issues 必须给出机制性解释"
    "（瓶颈设备/排队/运输占比/口径差异），禁止只写『启发式非全局最优』免责声明；"
    "并判断差距是否源于模型假设口径（如禁止分摊类收紧口径）。提示：scripts/check_gap_trigger.py。\n"
    "3. 数字溯源与敏感性口径：正文数字与『代码运行真实输出』不符即按编造处理（见上）；"
    "敏感性档位/口径必须与 stdout 实跑一致（速度扫描档位、预算档位必须出自实际运行，"
    "不允许出现证据中不存在的档位数字）。提示：scripts/check_paper_numbers.py --strict。\n"
    "4. 得分点覆盖：若提供评分细则/得分点清单则逐条核对，未命中项列入 issues 并估计失分幅度；"
    "无细则时检查题面指定交付物（表/图/代码）是否齐备。"
)


def _section_excerpt(value: str, limit: int) -> str:
    """保留章节开头与结尾，避免只看到铺垫而看不到结果和边界。"""
    value = value or ""
    if len(value) <= limit:
        return value
    head = int(limit * 0.65)
    tail = limit - head
    return value[:head] + "\n……（中部省略）……\n" + value[-tail:]


def build_prompt(
    paper,
    n_figures,
    n_sensitivity,
    code_stdout: str = "",
    *,
    model_critic=None,
    consistency=None,
    figures=None,
    sensitivity_runs=None,
    brief=None,
):
    sections = {
        "abstract": paper.abstract, "problem_restatement": paper.problem_restatement,
        "assumptions": paper.assumptions, "notation": paper.notation,
        "model_section": paper.model_section, "solution": paper.solution,
        "sensitivity": paper.sensitivity, "conclusion": paper.conclusion,
    }
    limits = {
        "abstract": 1200, "problem_restatement": 1500, "assumptions": 1400,
        "notation": 1000, "model_section": 3000, "solution": 3000,
        "sensitivity": 1800, "conclusion": 1800,
    }
    body = "\n\n".join(
        f"## {key}\n{_section_excerpt(value, limits[key])}"
        for key, value in sections.items()
    )
    stdout_block = ""
    limitation_note = ""
    if code_stdout.strip():
        stdout_block = (
            f"\n# 代码运行真实输出（事实源；用于核对正文数字）\n"
            f"```\n{code_stdout[:12000]}\n```\n"
        )
        limitation_note = (
            "\n# LIMITATION 声明处理规则\n"
            "stdout 中形如 `LIMITATION: <问题id> <原因>` 的行，是模型在参数域内数学"
            "不可用时的**合法声明**（如应力公式在极端边界下根号内为负）。正文可将其"
            "如实写入「模型局限」小节，这**不算编造，不因此扣分**。"
            "但被声明字段的正文**不得给出具体数值**；若正文对被声明字段给出了数字，"
            "仍按编造处理，approved 设 False。\n"
        )
    upstream = (
        "# 上游质量证据\n"
        f"- 最终模型评审：{model_critic.model_dump() if model_critic else '缺失'}\n"
        f"- 模型—代码一致性：{consistency.model_dump() if consistency else '缺失'}\n"
    )
    figure_summary = "\n".join(
        f"- {figure.purpose}：quality={figure.quality_score}；"
        f"caption={figure.caption}；analysis={_section_excerpt(figure.analysis, 300)}"
        for figure in (figures or [])[:12]
    ) or "（无）"
    sensitivity_summary = "\n".join(
        f"- {run.parameter}: values={run.values}; {run.metric}={run.results}; "
        f"interpretation={run.interpretation}"
        for run in (sensitivity_runs or [])[:8]
    ) or "（无）"
    brief_block = ""
    if brief is not None:
        from math_agent.brief import render_slice
        rendered = render_slice(brief, "paper_critic")
        if rendered:
            brief_block = f"\n{rendered}\n"
    return (
        f"# 章节素材\n{body}\n\n"
        f"# 客观信号\n- 图表数：{n_figures}\n- 敏感性 run 数：{n_sensitivity}\n"
        f"{upstream}\n"
        f"# 图表证据清单\n{figure_summary}\n\n"
        f"# 敏感性数组\n{sensitivity_summary}\n"
        f"{stdout_block}"
        f"{limitation_note}"
        f"{brief_block}\n"
        f"请输出 JSON：{{\"target\":\"paper\",\"score\":int,"
        f"\"issues\":[{{\"section\":\"abstract|problem_restatement|assumptions|notation|model_section|solution|sensitivity|conclusion|references|general\",\"problem\":str}}, ...],"
        f"\"suggestions\":[str],\"approved\":bool}}。"
    )
