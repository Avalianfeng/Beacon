"""把正式图表放到其所支撑的论证附近。

图表生成顺序通常由脚本决定，不能直接当作论文叙事顺序。本模块只依据图的
文件名、用途和正文小节标题做确定性分配，不修改图像，也不推断新的数值结论。
"""
from __future__ import annotations

import re
from collections.abc import Callable

from math_agent.state import FigureArtifact


_SENSITIVITY_TERMS = ("sensitivity", "敏感性", "参数扫描", "单因素")
_PROBLEM_TERMS = (
    "data_profile", "data profile", "数据画像", "数据概况", "数据分布",
    "附件数据", "数据预处理", "缺失值", "异常值",
)
_MODEL_TERMS = (
    "model_structure", "model framework", "模型结构", "模型框架", "机理图",
    "变量关系", "约束关系",
)


def figure_section(figure: FigureArtifact) -> str:
    """返回图表应进入的 PaperSections 字段。"""
    haystack = f"{figure.path} {figure.purpose} {figure.caption}".casefold()
    if any(term.casefold() in haystack for term in _SENSITIVITY_TERMS):
        return "sensitivity"
    if any(term.casefold() in haystack for term in _PROBLEM_TERMS):
        return "problem_restatement"
    if any(term.casefold() in haystack for term in _MODEL_TERMS):
        return "model_section"
    return "solution"


def figure_anchor_terms(figure: FigureArtifact) -> tuple[str, ...]:
    """给出寻找正文小节的高置信关键词，顺序即优先级。"""
    haystack = f"{figure.path} {figure.purpose} {figure.caption}".casefold()
    rules: list[tuple[tuple[str, ...], tuple[str, ...]]] = [
        (("baseline_comparison", "基线比较", "方案比较", "对比"),
         ("各方案结果对比表", "基线比较", "对比分析")),
        (("cost_composition", "cost_pie", "成本构成", "成本分解"),
         ("成本分解", "成本结构")),
    ]
    for markers, anchors in rules:
        if any(marker.casefold() in haystack for marker in markers):
            return anchors
    if figure_section(figure) == "sensitivity":
        purpose = re.sub(r"^敏感性分析\s*[:：]\s*", "", figure.purpose).strip()
        return tuple(item for item in (purpose, figure.caption, "敏感性") if item)
    return tuple(item for item in (figure.purpose, figure.caption) if item)


def _section_chunks(text: str, *, latex: bool) -> list[str]:
    if not text:
        return [""]
    pattern = r"(?=\\sub(?:sub)?section\*?\{)" if latex else r"(?m)(?=^#{2,3}\s+)"
    chunks = [chunk for chunk in re.split(pattern, text) if chunk]
    if len(chunks) > 1:
        return chunks
    paragraphs = [chunk for chunk in re.split(r"\n{2,}", text) if chunk]
    return paragraphs or [text]


def interleave_figures(
    text: str,
    figures: list[FigureArtifact],
    render: Callable[[FigureArtifact], str],
    *,
    latex: bool,
) -> str:
    """按小节语义把图插入正文；无匹配时均匀分散，不把图堆到章节末尾。"""
    if not figures:
        return text
    chunks = _section_chunks(text, latex=latex)
    placements: dict[int, list[FigureArtifact]] = {}
    used: set[int] = set()

    for position, figure in enumerate(figures):
        anchors = tuple(term.casefold() for term in figure_anchor_terms(figure) if term)
        scores = [
            sum(3 if term in chunk.casefold()[:160] else 1 for term in anchors
                if term in chunk.casefold())
            for chunk in chunks
        ]
        best = max(range(len(chunks)), key=lambda idx: scores[idx]) if chunks else 0
        if not scores or scores[best] == 0:
            best = min(len(chunks) - 1, round((position + 1) * len(chunks) / (len(figures) + 1)))
        elif best in used and len(chunks) > len(used):
            alternatives = sorted(range(len(chunks)), key=lambda idx: scores[idx], reverse=True)
            best = next((idx for idx in alternatives if scores[idx] > 0 and idx not in used), best)
        used.add(best)
        placements.setdefault(best, []).append(figure)

    out: list[str] = []
    for index, chunk in enumerate(chunks):
        out.append(chunk.rstrip())
        out.extend(render(figure).strip() for figure in placements.get(index, []))
    return "\n\n".join(item for item in out if item).strip()


def group_figures(figures: list[FigureArtifact]) -> dict[str, list[FigureArtifact]]:
    grouped = {key: [] for key in ("problem_restatement", "model_section", "solution", "sensitivity")}
    for figure in figures:
        grouped[figure_section(figure)].append(figure)
    return grouped
