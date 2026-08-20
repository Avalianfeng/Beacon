from __future__ import annotations

import os
import re
from pathlib import Path
from urllib.parse import quote

from jinja2 import Environment, FileSystemLoader, select_autoescape

from math_agent.config import (
    MODEL_ROUTING,
    RAG_CTX_MAX_CHARS_WRITER,
    RAG_DB_PATH,
    RAG_EMBEDDING_DIM,
    RAG_EMBEDDING_MODEL,
    RAG_ENABLED,
    RAG_TOPK,
)
from math_agent.llm import complete
from math_agent.nodes.figure_placement import group_figures, interleave_figures
from math_agent.nodes.sensitivity import formal_sensitivity_runs
from math_agent.nodes.rendering import (
    _curate_code,
    _curate_stdout,
    _normalize_escaped_layout_text,
)
from math_agent.nodes.table_assembler import _clean_forbidden_words
from math_agent.prompts.writer import SYSTEM, build_prompt  # noqa: F401
from math_agent.prompts.writer_section import (
    WriterOutline,
    _sections_to_rewrite,
    build_outline_prompt,
    build_section_prompt,
    schema_for_group,
    writer_sections,
)
from math_agent.rag.retrieve import format_snippets, search
from math_agent.state import FigureArtifact, MathModelingState, SensitivityRun
from math_agent.tools.runner import extract_valid_result_lines, infer_entity_upper_bound

# 分节写作输出上限。references 等长文本节曾多次因模型默认 max_tokens(8192)
# 撞墙截断 JSON（Invalid JSON: EOF while parsing a string），导致同节点连续
# 失败直至 supervisor 熔断。这里显式放大容纳度；模板侧另有条数/字数上界，
# 双保险：prompt 让模型在撞墙前主动停，max_tokens 兜底防截断。
_WRITER_SECTION_MAX_TOKENS = 16000


def writer_node(state: MathModelingState) -> dict:
    """准备论文大纲和本轮分节队列。

    分节写作使每一节完成后都能形成 LangGraph checkpoint，进程被杀或路由器
    短暂不可用时，恢复运行只需继续尚未完成的章节。
    """
    ctx = ""
    if RAG_ENABLED:
        prev_paper_hint = ""
        if state.paper is not None and state.paper.model_section:
            prev_paper_hint = state.paper.model_section[:500]
        query = (state.problem + " " + prev_paper_hint).strip()
        snippets = search(
            query,
            db_path=RAG_DB_PATH,
            k=RAG_TOPK,
            embedding_model=RAG_EMBEDDING_MODEL,
            dim=RAG_EMBEDDING_DIM,
            source_type="paper",
        )
        ctx = format_snippets(snippets, max_chars=RAG_CTX_MAX_CHARS_WRITER)

    prior_critic = state.latest_critic("paper")
    if state.writer_iteration == 0:
        outline = complete(
            build_outline_prompt(state, retrieved_context=ctx),
            schema=WriterOutline,
            system=SYSTEM,
            model=MODEL_ROUTING["writer"],
            profile="long",
        )
    else:
        outline = WriterOutline(**state.writer_outline_dump)

    if state.writer_iteration > 0 and prior_critic is not None and prior_critic.issues:
        run_set = set(_sections_to_rewrite(prior_critic.issues))
    else:
        run_set = {group.name for group in writer_sections()}

    return {
        "writer_section_queue": [
            group.name for group in writer_sections() if group.name in run_set
        ],
        "writer_outline_dump": outline.model_dump(),
        "writer_retrieved_context": ctx,
        "writer_iteration": state.writer_iteration + 1,
    }


def _coerce_unit_and_type(description: str) -> tuple[str, str]:
    text = (description or "").lower()
    if any(word in text for word in ("binary", "0-1", "是否", "选择")):
        return "—", "0-1变量"
    if any(word in text for word in ("integer", "整数", "数量", "辆")):
        return "按定义", "整数变量"
    if any(word in text for word in ("continuous", "连续", "距离", "时间", "成本")):
        return "按定义", "连续变量"
    return "—", "参数或变量"


def _build_assumptions_text(state: MathModelingState) -> str:
    blocks: list[str] = []
    for index, item in enumerate(state.assumptions[:8], 1):
        rationale = item.rationale or "该假设用于明确模型边界，并保证求解过程可计算。"
        impact = "若该假设偏离实际，应通过场景分析检验结论是否稳定。"
        if item.sensitivity_relevant:
            impact += "该项已列入敏感性分析的重点参数。"
        blocks.append(
            f"**假设{index}**：{item.statement}\n"
            f"**依据**：{rationale}\n"
            f"**影响与检验**：{impact}"
        )
    if blocks:
        return "\n\n".join(blocks)
    return (
        "**假设1**：题目给出的数据在研究周期内有效，未给出的随机扰动不作为基准模型输入。\n"
        "**依据**：该假设使模型与现有数据口径一致。\n"
        "**影响与检验**：在扩展分析中通过扰动关键参数评估结论的稳健性。"
    )


def _build_notation_text(state: MathModelingState) -> str:
    model = state.latest_model()
    variables = model.variables if model else {}
    lines = ["| 符号 | 含义 | 单位 | 类型 |", "|---|---|---|---|"]
    for symbol, meaning in list(variables.items())[:20]:
        unit, kind = _coerce_unit_and_type(meaning)
        lines.append(f"| `{symbol}` | {meaning} | {unit} | {kind} |")
    if len(lines) == 2:
        lines.append("| `x` | 模型的核心决策变量 | 按定义 | 决策变量 |")
    lines.append(
        "\n同一符号在全文中保持唯一含义；集合索引、决策变量与外生参数分别说明，"
        "0-1变量取值为1表示相应方案被采用。"
    )
    return "\n".join(lines)


def _build_model_section_text(state: MathModelingState) -> str:
    model = state.latest_model()
    if model is None:
        return (
            "## 建模思路\n"
            "依据题目目标定义决策变量，并将业务规则转化为可检验的约束。\n\n"
            "## 目标函数与约束\n"
            "以题目要求的核心指标为目标，并保留可行性、容量和时序约束。\n\n"
            "## 求解与验证\n"
            "采用可复现程序求解，并通过边界检查和敏感性分析验证结果。"
        )

    equation_lines = "\n".join(
        f"- $${equation}$$" for equation in model.equations[:10]
    ) or "- 目标函数与约束以程序实现为准。"
    objectives = "；".join(model.objective_mapping[:4]) or model.description
    constraints = "；".join(model.constraint_mapping[:6]) or "满足题目给定的业务约束"
    validations = "；".join(model.validation_mapping[:4]) or "进行可行性与边界检查"
    return (
        "## 模型结构与目标\n"
        f"模型围绕以下目标建立：{objectives}。通过统一决策变量连接各子问题，"
        "确保目标、约束、算法输出和评价指标具有一致的数据口径。\n\n"
        f"{equation_lines}\n\n"
        "## 约束体系\n"
        f"约束映射为：{constraints}。求解时逐项检查容量、时序、资源和逻辑可行性，"
        "不以惩罚值代替必须满足的硬约束。\n\n"
        "## 验证设计\n"
        f"验证计划包括：{validations}。同时使用程序输出、边界场景和敏感性结果"
        "相互校验，避免仅凭单次最优值下结论。"
    )


def _result_evidence(state: MathModelingState) -> list[str]:
    evidence: list[str] = []
    upper_bound = infer_entity_upper_bound(state.data_files)
    for artifact in state.latest_code_artifacts():
        # 正文的主结果证据只取正式主求解器；基线由专门的比较段落承载。
        if not artifact.success or artifact.evidence_role != "primary":
            continue
        expected = (
            artifact.category.split(":", 1)[1]
            if artifact.category.startswith("baseline:") else None
        )
        for raw_line in extract_valid_result_lines(
            artifact.stdout,
            stderr=artifact.stderr,
            expected_identifier=expected,
            max_entity_count=upper_bound,
        ):
            line = raw_line.strip()
            # 只保留结构化结果行，避免把 saved/data_dir 等本机路径写入论文。
            if re.search(r"(?:[A-Za-z]:[\\/]|[/\\](?:Users|home)[/\\])", line):
                continue
            evidence.append(line.replace("\\", "/"))
    return evidence[:6]


def _build_solution_text(state: MathModelingState) -> str:
    evidence = _result_evidence(state)
    evidence_text = (
        "\n".join(f"- `{line}`" for line in evidence)
        if evidence
        else "- 当前 checkpoint 未提供可引用的结构化 RESULT 行。"
    )
    return (
        "## 求解流程\n"
        "先完成数据一致性检查，再构造可行初解并执行优化；每次求解后重新计算目标值、"
        "约束违反量和题目要求的评价指标。中间结果按节点写入 checkpoint，恢复运行时"
        "复用已完成计算。\n\n"
        "## 可复现结果\n"
        f"程序提供的结构化证据如下：\n{evidence_text}\n\n"
        "论文只引用上述程序实际输出的数值。若某项指标缺少结构化结果，则将其标记为"
        "待验证项，不用推测值补齐。"
    )


def _build_sensitivity_text(state: MathModelingState) -> str:
    formal_runs = formal_sensitivity_runs(state)
    if not formal_runs:
        return (
            "当前运行未形成有效的敏感性结果，因此不报告未经计算的变化幅度。"
            "建议围绕成本、容量、需求和时间约束分别设置扰动场景后重新计算。"
        )

    ranked = sorted(
        (
            (run, max(run.results) - min(run.results) if run.results else 0.0)
            for run in formal_runs
        ),
        key=lambda item: item[1],
        reverse=True,
    )
    paragraphs = [
        "采用单因素扰动保持其他条件不变，并在每个扰动点重新求解模型。",
        "结果跨度用于比较局部敏感程度，但不替代可行性和业务边界检查。",
    ]
    for index, (run, span) in enumerate(ranked, 1):
        interpretation = run.interpretation or "该参数变化会影响模型输出，应结合业务边界解释。"
        paragraphs.append(
            f"{index}. 参数 `{run.parameter}` 取值为 {run.values}，指标 `{run.metric}` "
            f"对应结果为 {run.results}，观测跨度为 {span:.4g}。{interpretation}"
        )
    return "\n\n".join(paragraphs)


def _build_conclusion_text(state: MathModelingState) -> str:
    model = state.latest_model()
    stage = model.stage if model else "最终模型"
    return (
        f"本文围绕题目要求完成了从问题拆解、{stage}建立、程序求解到稳健性检验的完整链路。"
        "结论以程序的结构化输出为证据，并对缺少数据支持的指标保留限制说明。\n\n"
        "模型的优点是目标与约束映射明确、运行过程可恢复、结果可复算；主要局限在于"
        "输入数据口径和场景假设会影响外推能力。\n\n"
        "后续可引入更细粒度的需求分布、动态路况或多场景联合优化，并使用独立数据"
        "进行样本外验证。"
    )


def _build_references_text(references) -> str:
    if not references:
        return (
            "[1] 运筹学教材编写组. 运筹学基础与应用[M].\n"
            "[2] 数学建模课程组. 数学建模方法与实践[M].\n"
            "[3] 相关行业标准与题目所附数据说明[R]."
        )

    lines: list[str] = []
    for index, reference in enumerate(references[:8], 1):
        authors = "，".join(reference.authors[:3]) if reference.authors else "佚名"
        if len(reference.authors) > 3:
            authors += "，等"
        venue = f". {reference.venue}" if reference.venue else ""
        year = f"，{reference.year}" if reference.year else ""
        doi = f". DOI: {reference.doi}" if reference.doi else ""
        lines.append(f"[{index}] {authors}. {reference.title}{venue}{year}{doi}.")
    return "\n".join(lines)


def _build_section_fallback(group_name: str, state: MathModelingState, references=None):
    schema = schema_for_group(group_name)
    if group_name == "abstract_problem":
        return schema(
            abstract=(
                "本文针对题目所给的多约束优化问题，建立目标、约束和评价指标相互对应的"
                "数学模型。首先完成数据与问题拆解，其次使用可复现程序求解并输出结构化"
                "结果，最后通过敏感性分析检验关键参数变化对方案的影响。全文仅引用实际"
                "计算结果，对缺少证据的指标明确保留限制。"
            ),
            problem_restatement=(
                "题目要求在给定数据和业务规则下形成可执行方案，并回答各子问题。"
                "建模时需要同时处理目标冲突、资源限制、时序约束和结果验证，最终给出"
                "能够由程序复算的决策依据。"
            ),
            keywords="数学规划；多约束优化；可恢复计算；敏感性分析；结果验证",
        )
    if group_name == "assumptions_notation":
        return schema(
            assumptions=_build_assumptions_text(state),
            notation=_build_notation_text(state),
        )
    if group_name == "model":
        return schema(model_section=_build_model_section_text(state))
    if group_name == "solution":
        return schema(solution=_build_solution_text(state))
    if group_name == "sensitivity":
        return schema(sensitivity=_build_sensitivity_text(state))
    if group_name == "conclusion":
        return schema(conclusion=_build_conclusion_text(state))
    if group_name == "references":
        return schema(references=_build_references_text(references))
    return schema()


def _should_use_deterministic_writer() -> bool:
    """确定性写作仅用于显式离线/应急模式，不因 prompt 较长而自动降质。"""
    return os.getenv("MATH_AGENT_WRITER_DETERMINISTIC", "").strip() == "1"


_MIN_SECTION_NONSPACE_CHARS = {
    "abstract": 250,
    "problem_restatement": 800,
    "keywords": 5,
    "assumptions": 800,
    "notation": 500,
    "model_section": 2500,
    "solution": 1800,
    "sensitivity": 1000,
    "conclusion": 800,
    "references": 150,
}


_MIN_SENSITIVITY_CHARS_WITHOUT_RUNS = 400


def _section_min_chars(field: str, state: MathModelingState | None) -> int:
    minimum = _MIN_SECTION_NONSPACE_CHARS[field]
    if (
        field == "sensitivity"
        and state is not None
        and not formal_sensitivity_runs(state)
    ):
        return min(minimum, _MIN_SENSITIVITY_CHARS_WITHOUT_RUNS)
    return minimum


def _section_quality_issues(
    group_name: str, section_out, state: MathModelingState | None = None,
) -> list[str]:
    group = next(item for item in writer_sections() if item.name == group_name)
    issues: list[str] = []
    for field in group.fields:
        minimum = _section_min_chars(field, state)
        value = str(getattr(section_out, field, "") or "")
        actual = len("".join(value.split()))
        if actual < minimum:
            issues.append(f"{field}={actual}，至少需要 {minimum} 个非空白字符")
    return issues


def _section_repair_prompt(prompt: str, issues: list[str]) -> str:
    return (
        prompt
        + "\n\n---\n\n## 篇幅质量门禁：上一稿必须重写\n\n"
        + "上一稿存在以下篇幅不足：\n- "
        + "\n- ".join(issues)
        + "\n请在不编造数字、不重复段落、不改变输出 schema 的前提下，补足问题分析、"
          "数据处理、公式推导、算法步骤、结果解释、误差边界与管理含义。"
    )


def writer_section_node(state: MathModelingState) -> dict:
    """写队首一节并弹出队列；一次调用对应一个可恢复 checkpoint。"""
    queue = list(state.writer_section_queue)
    group_name = queue.pop(0)
    print(f"[writer] writing section: {group_name} ({len(queue)} remaining)", flush=True)

    outline = WriterOutline(**state.writer_outline_dump)
    prior_critic = state.latest_critic("paper")

    references = None
    if group_name == "references":
        from math_agent.tools.references import select_references

        references = select_references(state.problem, state.problem_domains)

    prompt = build_section_prompt(
        group_name,
        state,
        outline,
        prior_critic=prior_critic,
        retrieved_context=state.writer_retrieved_context,
        references_list=references,
    )
    if _should_use_deterministic_writer():
        print(f"[writer] deterministic fallback for: {group_name}", flush=True)
        section_out = _build_section_fallback(
            group_name, state, references=references
        )
    else:
        section_out = complete(
            prompt,
            schema=schema_for_group(group_name),
            system=SYSTEM,
            model=MODEL_ROUTING["writer"],
            profile="long",
            max_tokens=_WRITER_SECTION_MAX_TOKENS,
        )
    group = next(item for item in writer_sections() if item.name == group_name)
    for field in group.fields:
        cleaned, _warnings = _clean_forbidden_words(
            str(getattr(section_out, field, "") or ""), field,
        )
        setattr(section_out, field, cleaned)

    issues = _section_quality_issues(group_name, section_out, state)
    if issues and not _should_use_deterministic_writer():
        section_out = complete(
            _section_repair_prompt(prompt, issues),
            schema=schema_for_group(group_name),
            system=SYSTEM,
            model=MODEL_ROUTING["writer"],
            profile="long",
            max_tokens=_WRITER_SECTION_MAX_TOKENS,
        )
        for field in group.fields:
            cleaned, _warnings = _clean_forbidden_words(
                str(getattr(section_out, field, "") or ""), field,
            )
            setattr(section_out, field, cleaned)
        issues = _section_quality_issues(group_name, section_out, state)
    if issues and not _should_use_deterministic_writer():
        if group_name == "sensitivity" and not formal_sensitivity_runs(state):
            print(
                "[writer] sensitivity below budget but no formal runs; "
                "keep honest draft instead of crashing",
                flush=True,
            )
        else:
            raise ValueError(
                f"writer section quality gate failed for {group_name}: "
                + "；".join(issues)
            )

    paper = state.paper.model_copy(deep=True)
    for group in writer_sections():
        if group.name == group_name:
            for field in group.fields:
                setattr(paper, field, getattr(section_out, field))
            break

    return {"paper": paper, "writer_section_queue": queue}


_TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"
_env = Environment(loader=FileSystemLoader(_TEMPLATE_DIR), autoescape=select_autoescape([]))


def _demote_embedded_headings(value: str) -> str:
    """Markdown 模板已提供二级章标题，字段内标题统一下沉一级。"""
    return re.sub(
        r"(?m)^(#{2,5})(?=\s)",
        lambda match: "#" + match.group(1),
        value or "",
    )


def render_markdown(
    state: MathModelingState,
    *,
    figures: list[FigureArtifact] | None = None,
    sensitivity_runs: list[SensitivityRun] | None = None,
    problem_override: str | None = None,
) -> str:
    """渲染 Markdown，并允许 LaTeX 节点传入同一组正式证据视图。

    state 中的 figures / sensitivity_runs 是 append-only 历史。直接渲染整个列表会把
    旧轮次的图和自由文本解释重新带回 paper.md，而 paper.tex 已经只选择最新正式证据。
    可选参数用于让两种正式论文产物共享完全相同的证据选择结果。
    """
    template = _env.get_template("paper.md.j2")
    paper = state.paper.model_copy(deep=True)
    for field, value in paper.model_dump().items():
        if isinstance(value, str):
            normalized = _normalize_escaped_layout_text(value) or ""
            setattr(paper, field, _demote_embedded_headings(normalized))

    upper_bound = infer_entity_upper_bound(state.data_files)
    evidence_artifacts = []
    for artifact in state.latest_code_artifacts():
        # 论文附录只承载正式主求解器。基线仍作为正文中的已校验对照证据，
        # 但不重复附入整段代码，避免把“对照职责”误写成“主方案职责”。
        if not artifact.success or artifact.evidence_role != "primary":
            continue
        expected = (
            artifact.category.split(":", 1)[1]
            if artifact.category.startswith("baseline:") else None
        )
        if not extract_valid_result_lines(
            artifact.stdout,
            stderr=artifact.stderr,
            expected_identifier=expected,
            max_entity_count=upper_bound,
        ):
            continue
        evidence_artifacts.append(artifact)
    curated = [
        {
            "purpose": artifact.purpose,
            "code": artifact.code,
            "stdout": artifact.stdout,
            "success": artifact.success,
            "artifact_paths": artifact.artifact_paths,
            "curated_code": _curate_code(artifact.code),
            "curated_stdout": _curate_stdout(artifact.stdout),
        }
        for artifact in evidence_artifacts
    ]
    selected_figures = state.figures if figures is None else figures
    selected_sensitivity_runs = (
        state.sensitivity_runs if sensitivity_runs is None else sensitivity_runs
    )
    markdown_figures = [
        figure.model_copy(
            update={"path": quote(figure.path.replace("\\", "/"), safe="/:")}
        )
        for figure in selected_figures
    ]
    grouped = group_figures(markdown_figures)

    def _markdown_figure(figure: FigureArtifact) -> str:
        caption = figure.caption or figure.purpose
        analysis = figure.analysis.strip()
        explanation = f"\n\n**图示结论：** {analysis}" if analysis else ""
        return f"![{caption}]({figure.path}){explanation}"

    for field, field_figures in grouped.items():
        if not field_figures:
            continue
        setattr(
            paper,
            field,
            interleave_figures(
                getattr(paper, field), field_figures, _markdown_figure, latex=False,
            ),
        )
    return template.render(
        problem=problem_override or state.problem,
        paper=paper,
        code_artifacts=curated,
        sensitivity_runs=selected_sensitivity_runs,
    )
