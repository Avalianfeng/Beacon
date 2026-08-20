import pytest
from math_agent.state import (
    MathModelingState, PaperSections, FigureArtifact, SensitivityRun,
    CriticReport, EvaluationReport, ModelCodeConsistencyReport, CodeArtifact,
)
from math_agent.nodes.evaluation import _offline_evaluation, evaluation_node


def _full_state():
    s = MathModelingState(problem="p")
    s.paper = PaperSections(
        abstract="a"*200, problem_restatement="x"*200, assumptions="x"*200,
        notation="x"*200, model_section="x"*200, solution="x"*200,
        sensitivity="x"*200, conclusion="x"*200, references="-",
    )
    s.figures.append(FigureArtifact(path="a.png", purpose="t", quality_score=8))
    s.sensitivity_runs.append(SensitivityRun(parameter="a", values=[1], metric="m", results=[1]))
    s.critic_reports.extend([
        CriticReport(target="modeler", stage="final", score=8, approved=True),
        CriticReport(target="paper", score=9, approved=True),
    ])
    s.model_code_reports.append(ModelCodeConsistencyReport(score=8, approved=True))
    return s


def _attach_offline_evidence(state):
    state.code_artifacts.append(CodeArtifact(
        purpose="main",
        code="print(1)",
        success=True,
        evidence_role="primary",
        stdout="RESULT: baseline=ours total_cost=91544.49 service_rate=1\n",
    ))
    scan = SensitivityRun(
        parameter="容量系数",
        values=[0.9, 1.0, 1.1],
        metric="total_cost",
        results=[91600.0, 91544.49, 91700.0],
    )
    state.sensitivity_runs.append(scan)
    state.sensitivity_formal_parameters = [scan.parameter]


def test_evaluation_returns_report(mocker):
    fake = EvaluationReport(
        assumption_reasonableness=8, modeling_creativity=8,
        result_correctness=8, writing_clarity=8, extra_depth=8, overall=8.0,
        issues=[], suggestions=[],
    )
    mocker.patch("math_agent.nodes.evaluation.complete", return_value=fake)
    delta = evaluation_node(_full_state())
    assert isinstance(delta["evaluation"], EvaluationReport)
    assert delta["evaluation"].overall == 8.0


def test_evaluation_recomputes_overall_if_llm_wrong(mocker):
    fake = EvaluationReport(
        assumption_reasonableness=8, modeling_creativity=8,
        result_correctness=8, writing_clarity=8, extra_depth=8, overall=10.0,
    )
    mocker.patch("math_agent.nodes.evaluation.complete", return_value=fake)
    delta = evaluation_node(_full_state())
    assert delta["evaluation"].overall == pytest.approx(8.0, abs=0.01)


def test_evaluation_skips_without_paper(mocker):
    s = MathModelingState(problem="p")
    delta = evaluation_node(s)
    assert delta["errors"]
    assert delta.get("evaluation") is None


def test_evaluation_caps_correctness_without_upstream_quality(mocker):
    state = _full_state()
    state.critic_reports = [
        report for report in state.critic_reports if report.target == "paper"
    ]
    state.model_code_reports = []
    fake = EvaluationReport(
        assumption_reasonableness=9, modeling_creativity=9,
        result_correctness=9, writing_clarity=9, extra_depth=9, overall=9.0,
    )
    mocker.patch("math_agent.nodes.evaluation.complete", return_value=fake)

    report = evaluation_node(state)["evaluation"]

    assert report.modeling_creativity == 6
    assert report.result_correctness == 5
    assert report.overall < 8


def test_offline_evaluation_scores_only_present_evidence():
    state = _full_state()
    _attach_offline_evidence(state)
    state.paper = PaperSections(
        assumptions="假" * 700,
        model_section="模" * 3000,
        solution="主方案总成本91544.49。" + "解" * 4000,
        sensitivity="敏" * 1000,
        conclusion="结" * 1500,
    )

    report = _offline_evaluation(state)

    assert report.overall >= 8
    assert report.result_correctness == 9

    state.code_artifacts[0].stdout = state.code_artifacts[0].stdout.replace(
        "total_cost=91544.49", "total_cost=99999.99",
    )
    stale = _offline_evaluation(state)
    assert stale.result_correctness == 6
    assert any("99999.99" in issue for issue in stale.issues)

    state.paper.sensitivity += " 图Sensitivity"
    rejected = _offline_evaluation(state)
    assert rejected.writing_clarity == 6
