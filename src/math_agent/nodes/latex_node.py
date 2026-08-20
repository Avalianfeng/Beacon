"""latex 节点：渲染 .tex → 编译 .pdf → 失败时回退到 Markdown。"""
from __future__ import annotations

import shutil
from pathlib import Path
from jinja2 import Environment, FileSystemLoader, select_autoescape

from math_agent.nodes.latex_transform import (
    _prepare_section, _prepare_inline_text, _prepare_title, _gmcm_bibliography,
)
from math_agent.nodes.figure_placement import group_figures, interleave_figures
from math_agent.nodes.rendering import (
    _curate_code, _curate_stdout, _latex_path, _truncate_caption, _latex_plain_text,
)
from math_agent.nodes.sensitivity import formal_sensitivity_runs
from math_agent.nodes.writer import render_markdown
from math_agent.state import FigureArtifact, MathModelingState, PaperSections, SensitivityRun
from math_agent.tools.latex_compile import compile_latex
from math_agent.tools.runner import extract_valid_result_lines, infer_entity_upper_bound

_TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"
_env = Environment(loader=FileSystemLoader(_TEMPLATE_DIR), autoescape=select_autoescape([]))


def _latest_sensitivity_runs(state: MathModelingState) -> list[SensitivityRun]:
    """Select the newest formal run per parameter from append-only history."""
    return formal_sensitivity_runs(state)


def _formal_figures(
    state: MathModelingState, sensitivity_runs: list[SensitivityRun]
) -> list[FigureArtifact]:
    """Select figures backed by the current formal evidence set."""
    artifact_paths = {
        str(Path(path).resolve())
        for artifact in state.latest_code_artifacts()
        if artifact.success
        and artifact.evidence_role in {"primary", "supporting"}
        for path in artifact.artifact_paths
    }
    sensitivity_history_paths = {
        str(Path(run.figure_path).resolve())
        for run in state.sensitivity_runs
        if run.figure_path
    }
    by_path: dict[str, FigureArtifact] = {}
    for figure in state.figures:
        path = str(Path(figure.path).resolve())
        if path in sensitivity_history_paths:
            continue
        if not artifact_paths or path in artifact_paths:
            by_path[path] = figure

    figures = list(by_path.values())
    seen = set(by_path)
    for run in sensitivity_runs:
        if not run.figure_path:
            continue
        path = str(Path(run.figure_path).resolve())
        if path in seen:
            continue
        seen.add(path)
        figures.append(FigureArtifact(
            path=run.figure_path,
            purpose=f"敏感性分析：{run.parameter}",
            caption=f"{run.parameter}的敏感性结果",
            analysis=_sensitivity_figure_analysis(run),
        ))
    return figures


def _sensitivity_figure_analysis(run: SensitivityRun) -> str:
    """只由扫描数组生成可复核图解，不引入图外数值。"""
    if not run.values or not run.results or len(run.values) != len(run.results):
        return "该图用于核对参数扰动与评价指标的对应关系；由于扫描数组不完整，本文不据此判断变化方向。"
    pairs = [(float(value), float(result)) for value, result in zip(run.values, run.results)]
    differences = [pairs[index + 1][1] - pairs[index][1] for index in range(len(pairs) - 1)]
    if differences and all(delta >= 0 for delta in differences):
        trend = "随参数增大总体不下降"
    elif differences and all(delta <= 0 for delta in differences):
        trend = "随参数增大总体不升高"
    else:
        trend = "在扫描区间内呈非单调变化"
    minimum = min(pairs, key=lambda item: item[1])
    maximum = max(pairs, key=lambda item: item[1])
    center = pairs[len(pairs) // 2]
    metric_name = {
        "total_cost": "总成本", "cost": "总成本", "total_carbon": "碳排放",
        "service_rate": "服务率", "timewin_rate": "时间窗满足率",
    }.get(run.metric, run.metric)
    return (
        f"结论上，{run.parameter}对{metric_name}{trend}。图中最低值 {minimum[1]:.2f} "
        f"出现在参数 {minimum[0]:.6g}，最高值 {maximum[1]:.2f} 出现在参数 "
        f"{maximum[0]:.6g}，中心点为 {center[1]:.2f}。这些离散点支持局部方向判断，"
        "但不能替代连续响应拟合或参数交互检验。"
    )


def _verified_comparison_figure(
    state: MathModelingState, workdir: Path
) -> FigureArtifact | None:
    """由通过 RESULT 门禁的主方案与基线生成同口径比较图。"""
    import re
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    upper_bound = infer_entity_upper_bound(state.data_files)
    rows: list[tuple[str, dict[str, float]]] = []
    for artifact in state.latest_code_artifacts():
        if not artifact.success or artifact.evidence_role not in {"primary", "baseline"}:
            continue
        expected = (
            artifact.category.split(":", 1)[1]
            if artifact.evidence_role == "baseline" and ":" in artifact.category
            else "ours"
        )
        lines = extract_valid_result_lines(
            artifact.stdout,
            stderr=artifact.stderr,
            expected_identifier=expected,
            max_entity_count=upper_bound,
        )
        if not lines:
            continue
        values = {
            match.group(1): float(match.group(2))
            for match in re.finditer(
                r"([A-Za-z_][\w]*)=(-?\d+(?:\.\d+)?)", lines[0]
            )
        }
        rows.append((expected, values))
    order = {name: index for index, name in enumerate(
        ("ours", "no_schedule", "simple_pred", "greedy")
    )}
    rows.sort(key=lambda item: order.get(item[0], 99))
    if len(rows) < 2 or rows[0][0] != "ours":
        return None

    labels = [name for name, _ in rows]
    costs = np.asarray([item.get("total_cost", 0.0) for _, item in rows])
    carbons = np.asarray([item.get("total_carbon", 0.0) for _, item in rows])
    timewins = np.asarray([item.get("timewin_rate", 0.0) for _, item in rows])
    if costs[0] <= 0 or carbons[0] <= 0:
        return None
    cost_index = 100.0 * costs / costs[0]
    carbon_index = 100.0 * carbons / carbons[0]
    colors = ["#4C78A8", "#72B7B2", "#F58518", "#E45756"][:len(rows)]
    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False
    fig, axes = plt.subplots(1, 3, figsize=(12, 4.2), dpi=180)
    for ax, values, title, ylabel in (
        (axes[0], cost_index, "总成本指数", "主方案=100"),
        (axes[1], carbon_index, "碳排放指数", "主方案=100"),
        (axes[2], 100.0 * timewins, "时间窗满足率", "%"),
    ):
        bars = ax.bar(labels, values, color=colors, width=0.68)
        ax.set_title(title)
        ax.set_ylabel(ylabel)
        ax.tick_params(axis="x", rotation=25)
        ax.grid(axis="y", alpha=0.2)
        for bar, value in zip(bars, values):
            ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height(),
                    f"{value:.1f}", ha="center", va="bottom", fontsize=8)
    fig.suptitle("主方案与同口径基线比较", fontsize=15)
    fig.tight_layout()
    target = workdir / "baseline_comparison.png"
    fig.savefig(target, dpi=240, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return FigureArtifact(
        path=str(target),
        purpose="主方案与同口径基线比较",
        caption="主方案与三类同口径基线的成本、碳排放和时间窗率比较",
        analysis=(
            "总成本和碳排放采用主方案归一化指数，时间窗率保留百分比。"
            "比较结果表明，不同方案在经济、环境和服务指标上的优劣并不完全一致，"
            "因此不能只凭单一成本柱高判断综合表现。指数只用于消除量纲差异，"
            "应与原始结果表联合阅读，也不构成统计显著性检验。"
        ),
    )


def _numbered_references(value: str) -> str:
    """把同一行或多行的 ``[n]`` 文献整理为紧凑编号列表。"""
    import re

    matches = list(re.finditer(r"(?<!\w)\[(\d+)\]\s*", value or ""))
    if not matches:
        return value
    items: list[str] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(value)
        content = value[match.end():end].strip()
        if content:
            items.append(content)
    if not items:
        return value
    body = "\n".join(f"\\item {item}" for item in items)
    return (
        "\\begin{enumerate}\n"
        "\\renewcommand{\\labelenumi}{[\\arabic{enumi}]}\n"
        "\\setlength{\\itemsep}{0.15em}\n"
        "\\setlength{\\parsep}{0pt}\n"
        f"{body}\n"
        "\\end{enumerate}"
    )


def latex_node(state: MathModelingState) -> dict:
    workdir = Path(state.output_dir or ".")
    workdir.mkdir(parents=True, exist_ok=True)

    # ponytail: 为图重打一份 LaTeX 安全视图，避免 caption/path 里的 _/&/% 炸编译
    # caption 尽量截到最近的句/短语边界，避免"曲线呈下降趋势，"这种半截逗号结尾
    # analysis 走完整 _prepare_section（v8 实测：figure_pipeline LLM 在图说里
    # 会写 sensitivity_capacity.png 这种文件名，必须 escape）
    formal_sens = _latest_sensitivity_runs(state)
    formal_figures = _formal_figures(state, formal_sens)
    comparison_figure = _verified_comparison_figure(state, workdir)
    if comparison_figure is not None:
        formal_figures.append(comparison_figure)
    safe_figures = [
        FigureArtifact(
            path=_latex_path(f.path),
            purpose=_prepare_inline_text(f.purpose),
            caption=_prepare_inline_text(_truncate_caption(f.caption or f.purpose, max_chars=55)),
            quality_score=f.quality_score,
            quality_issues=list(f.quality_issues),
            analysis=_prepare_section(f.analysis),
        )
        for f in formal_figures
    ]

    # paper 各段做 markdown → LaTeX 的确定性预处理（粗体/表格/列表/标题/数学）
    safe_paper = PaperSections(**{
        k: _prepare_section(v) if isinstance(v, str) else v
        for k, v in state.paper.model_dump().items()
    })
    grouped_figures = group_figures(safe_figures)
    figure_number = 0

    def _latex_figure(figure: FigureArtifact) -> str:
        nonlocal figure_number
        figure_number += 1
        analysis = figure.analysis.strip() or (
            f"该图呈现{figure.purpose}。图中信息用于辅助核对对应模型与计算结果；"
            "在缺少进一步数值分解时，不据此扩展新的定量结论。"
        )
        return (
            "\\begin{figure}[!htbp]\n"
            "\\centering\n"
            f"\\includegraphics[width=0.75\\linewidth]{{{figure.path}}}\n"
            f"\\caption{{{figure.caption or figure.purpose}}}\n"
            f"\\label{{fig:{figure_number}}}\n"
            "\\begin{minipage}{0.92\\linewidth}\n"
            "\\small\n"
            f"\\noindent\\textbf{{图示结论：}}{analysis}\n"
            "\\end{minipage}\n"
            "\\end{figure}\n\n"
        )

    for field, field_figures in grouped_figures.items():
        if not field_figures:
            continue
        setattr(
            safe_paper,
            field,
            interleave_figures(
                getattr(safe_paper, field), field_figures, _latex_figure, latex=True,
            ),
        )
    safe_sens = [
        SensitivityRun(
            parameter=_latex_plain_text(r.parameter) or "",
            values=r.values, metric=r.metric,
            results=r.results,
            interpretation=_prepare_section(r.interpretation),
            figure_path=r.figure_path,
        )
        for r in formal_sens
    ]

    # title 取 problem 第一行（避免把整段问题描述塞进 \title{}）
    title_line = state.problem.split("\n", 1)[0].strip()

    # 选模板：default 用 article 简版；gmcm 用 gmcmthesis 国赛规范
    use_gmcm = state.latex_template == "gmcm"
    tmpl_name = "gmcm.tex.j2" if use_gmcm else "paper.tex.j2"
    if use_gmcm:
        safe_paper.references = _gmcm_bibliography(safe_paper.references)
    else:
        safe_paper.references = _numbered_references(safe_paper.references)

    upper_bound = infer_entity_upper_bound(state.data_files)
    primary_artifacts = [
        artifact
        for artifact in state.latest_code_artifacts()
        if (
            artifact.success
            and artifact.evidence_role == "primary"
            and extract_valid_result_lines(
                artifact.stdout,
                stderr=artifact.stderr,
                max_entity_count=upper_bound,
            )
        )
    ]

    render_kwargs = dict(
        # 标题保留数学段，并完整转义纯文本字符。
        problem=_prepare_title(title_line),
        paper=safe_paper, figures=safe_figures, sensitivity_runs=safe_sens,
        appendix_title="关键算法代码",
        code_artifacts=[
            {
                "purpose": _prepare_inline_text(a.purpose),
                "code": a.code, "stdout": a.stdout,
                "success": a.success, "artifact_paths": a.artifact_paths,
                "curated_code": _curate_code(a.code, max_lines=55),
                "curated_stdout": _curate_stdout(a.stdout),
            }
            for a in primary_artifacts
        ],
    )
    if use_gmcm:
        # 队员逗号拆分到 a/b/c，空位补占位
        mem = (state.members or "").split(",")
        mem = [m.strip() for m in mem] + ["", "", ""]
        render_kwargs.update(
            school=_latex_plain_text(state.school or "XX大学"),
            team_id=_latex_plain_text(state.team_id or "No.00000001"),
            member_a=_latex_plain_text(mem[0] or "队员A"),
            member_b=_latex_plain_text(mem[1] or "队员B"),
            member_c=_latex_plain_text(mem[2] or "队员C"),
            keywords=_latex_plain_text((state.paper.keywords or "数学建模").strip()),
        )
        # cls 必须和 .tex 在同一目录才能被 xelatex 找到；封面图也要带上
        cls_src = _TEMPLATE_DIR / "gmcmthesis.cls"
        cls_dst = workdir / "gmcmthesis.cls"
        shutil.copyfile(cls_src, cls_dst)
        fig_src = _TEMPLATE_DIR / "gmcm_figures"
        fig_dst = workdir / "figures"
        if fig_src.is_dir():
            fig_dst.mkdir(parents=True, exist_ok=True)
            for f in fig_src.iterdir():
                shutil.copyfile(f, fig_dst / f.name)

    tmpl = _env.get_template(tmpl_name)
    tex = tmpl.render(**render_kwargs)
    tex_path = workdir / "paper.tex"
    tex_path.write_text(tex, encoding="utf-8")

    # 始终也写一份 Markdown，作为降级 / 备查。它必须与 TeX 使用同一组最新正式
    # 图和敏感性证据，不能重新渲染 append-only 历史。
    (workdir / "paper.md").write_text(
        render_markdown(
            state,
            figures=formal_figures,
            sensitivity_runs=formal_sens,
            problem_override=title_line,
        ),
        encoding="utf-8",
    )

    res = compile_latex(tex_path)
    if not res.success:
        return {"errors": [f"latex compile failed: {res.log[:500]}"]}
    return {}
