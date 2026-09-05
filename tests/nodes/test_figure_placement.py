from math_agent.nodes.figure_placement import (
    ensure_figure_citations,
    unique_figures,
)
from math_agent.state import FigureArtifact, PaperSections


def test_unique_figures_keeps_first_order_and_latest_caption():
    figs = [
        FigureArtifact(path="a.png", purpose="旧A", caption="旧A"),
        FigureArtifact(path="b/x.png", purpose="B", caption="B"),
        FigureArtifact(path="a.png", purpose="新A", caption="新A"),
    ]
    out = unique_figures(figs)
    assert [f.path for f in out] == ["a.png", "b/x.png"]
    assert out[0].caption == "新A"


def test_ensure_figure_citations_appends_missing_numbers():
    paper = PaperSections(solution="求解结论。", sensitivity="敏感性结论。")
    figs = [
        FigureArtifact(path="q2.png", purpose="Q2一周补货堆叠", caption="品类日补货"),
        FigureArtifact(
            path="sens.png", purpose="敏感性分析：成本冲击", caption="成本冲击扫描",
        ),
    ]
    ensure_figure_citations(paper, figs)
    assert "如图1所示" in paper.solution
    assert "如图2所示" in paper.sensitivity
    ensure_figure_citations(paper, figs)
    assert paper.solution.count("如图1所示") == 1
