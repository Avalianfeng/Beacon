from math_agent.state import MathModelingState, ModelVersion, CriticReport, CriticIssue, ModelCodeConsistencyReport
from math_agent.routing import (
    after_model_critic, after_paper_critic,
    after_blueprint_critic, after_model_code_consistency,
)


def _state_with(stage, score, iteration):
    s = MathModelingState(problem="x", iteration=iteration, stage_target=stage)
    s.model_versions.append(ModelVersion(stage=stage, description="d"))
    s.critic_reports.append(
        CriticReport(target="modeler", score=score, approved=score >= 8, stage=stage)
    )
    return s


def test_routing_approved_basic_goes_to_improved():
    assert after_model_critic(_state_with("basic", 9, 0)) == "advance"


def test_routing_low_score_retries():
    assert after_model_critic(_state_with("basic", 4, 0)) == "retry"


def test_routing_caps_retries():
    # 即使分数低，达到迭代上限也必须前进
    assert after_model_critic(_state_with("basic", 4, 3)) == "advance"


def test_routing_after_final_goes_to_coder():
    assert after_model_critic(_state_with("final", 9, 0)) == "to_coder"


def _state_with_paper_critic(score: int, approved: bool, writer_iter: int,
                                *, complete: bool = True):
    s = MathModelingState(problem="p")
    if complete:
        s.paper.abstract = "非空论文"
        s.paper.model_section = "非空模型"
        s.paper.solution = "非空求解"
        s.paper.conclusion = "非空结论"
    else:
        s.paper.abstract = "非空论文"
    s.writer_iteration = writer_iter
    s.critic_reports.append(CriticReport(
        target="paper", score=score, approved=approved,
        issues=[CriticIssue(section="general", problem="编造数字")], suggestions=["核对附录"],
    ))
    return s


def test_after_paper_critic_advances_when_approved():
    s = _state_with_paper_critic(score=9, approved=True, writer_iter=0)
    assert after_paper_critic(s) == "advance"


def test_after_paper_critic_retries_when_below_threshold_and_iter_left():
    s = _state_with_paper_critic(score=4, approved=False, writer_iter=0)
    assert after_paper_critic(s) == "retry"


def test_after_paper_critic_advances_to_review_when_iter_cap_hit():
    # 论文内容完整但自动评审未达门槛且修复轮耗尽：移交人工整体评估，
    # 而不是直接 stop 掐断人工机会。
    from math_agent.config import MAX_WRITER_ITERATIONS
    s = _state_with_paper_critic(score=4, approved=False, writer_iter=MAX_WRITER_ITERATIONS)
    assert after_paper_critic(s) == "advance_review"


def test_after_paper_critic_stops_when_incomplete_paper_at_iter_cap():
    # 论文关键 section 为空：不允许进入人工评估（半成品不能送审）。
    from math_agent.config import MAX_WRITER_ITERATIONS
    s = _state_with_paper_critic(score=4, approved=False, writer_iter=MAX_WRITER_ITERATIONS,
                                 complete=False)
    assert after_paper_critic(s) == "stop"


def test_after_paper_critic_retries_when_no_critic():
    s = MathModelingState(problem="p")
    s.paper.abstract = "非空论文"
    assert after_paper_critic(s) == "retry"


def test_after_paper_critic_stops_empty_paper_at_iteration_cap():
    from math_agent.config import MAX_WRITER_ITERATIONS
    s = MathModelingState(problem="p", writer_iteration=MAX_WRITER_ITERATIONS)
    assert after_paper_critic(s) == "stop"


# ---------------------------------------------------------------------------
# after_blueprint_critic
# ---------------------------------------------------------------------------

def _state_with_blueprint_critic(approved: bool, iteration: int):
    s = MathModelingState(problem="p", blueprint_iteration=iteration)
    s.critic_reports.append(CriticReport(
        target="analyst", score=9 if approved else 4, approved=approved,
        critic_type="blueprint",
    ))
    return s


def test_blueprint_critic_advances_when_approved():
    s = _state_with_blueprint_critic(approved=True, iteration=1)
    assert after_blueprint_critic(s) == "advance"


def test_blueprint_critic_retries_when_not_approved_and_under_cap():
    s = _state_with_blueprint_critic(approved=False, iteration=1)
    assert after_blueprint_critic(s) == "retry"


def test_blueprint_critic_advances_with_warning_at_cap():
    from math_agent.config import MAX_BLUEPRINT_ITERATIONS
    s = _state_with_blueprint_critic(approved=False, iteration=MAX_BLUEPRINT_ITERATIONS)
    assert after_blueprint_critic(s) == "advance_with_warning"


def test_blueprint_critic_retries_when_no_report():
    s = MathModelingState(problem="p", blueprint_iteration=0)
    assert after_blueprint_critic(s) == "retry"


# ---------------------------------------------------------------------------
# after_model_code_consistency
# ---------------------------------------------------------------------------

def _state_with_consistency_report(approved: bool, score: int, iteration: int):
    s = MathModelingState(problem="p", code_verify_iteration=iteration)
    s.model_code_reports.append(ModelCodeConsistencyReport(score=score, approved=approved))
    return s


def test_consistency_advances_when_approved_and_high_score():
    s = _state_with_consistency_report(approved=True, score=8, iteration=1)
    assert after_model_code_consistency(s) == "advance"


def test_hard_redline_stops_even_when_consistency_would_advance():
    from math_agent.brief import load_brief
    from math_agent.state import CodeArtifact
    from pathlib import Path

    s = _state_with_consistency_report(approved=True, score=8, iteration=1)
    s.brief = load_brief(Path("problems/mcm51-c/brief.json"))
    s.code_artifacts.append(CodeArtifact(
        purpose="primary",
        code="print(1)",
        stdout="no RESULT line",
        success=True,
        evidence_role="primary",
        batch=1,
    ))
    assert after_model_code_consistency(s) == "stop"


def test_consistency_retries_coder_when_not_approved():
    s = _state_with_consistency_report(approved=False, score=4, iteration=1)
    assert after_model_code_consistency(s) == "retry_coder"


def test_consistency_retries_when_approved_but_low_score():
    """approved=True 但 score < 7 仍不 advance。"""
    s = _state_with_consistency_report(approved=True, score=5, iteration=1)
    assert after_model_code_consistency(s) == "retry_coder"


def test_consistency_stops_at_cap():
    from math_agent.config import MAX_CODE_VERIFY_ITERATIONS
    from math_agent.state import CodeArtifact
    s = _state_with_consistency_report(approved=False, score=4, iteration=1)
    s.code_verify_low_score_iteration = MAX_CODE_VERIFY_ITERATIONS
    s.code_artifacts.append(CodeArtifact(
        purpose="primary", code="print(1)", success=True,
        evidence_role="primary", batch=1,
    ))
    assert after_model_code_consistency(s) == "stop"


def test_consistency_low_score_budget_separate_from_no_primary_budget():
    """有主证据时只消耗低分预算：即使总轮次已超无主证据上限，低分轮未达上限仍 retry。"""
    from math_agent.config import MAX_CODE_NO_PRIMARY_ITERATIONS, MAX_CODE_VERIFY_ITERATIONS
    from math_agent.state import CodeArtifact
    s = _state_with_consistency_report(
        approved=True, score=5, iteration=MAX_CODE_NO_PRIMARY_ITERATIONS,
    )
    s.code_verify_low_score_iteration = MAX_CODE_VERIFY_ITERATIONS - 1
    s.code_artifacts.append(CodeArtifact(
        purpose="primary", code="print(1)", success=True,
        evidence_role="primary", batch=1,
    ))
    assert after_model_code_consistency(s) == "retry_coder"


def test_consistency_stops_without_primary_at_no_primary_cap():
    """无主证据不再无限重试：达到专门上限后 stop（仍绝不 advance 进 sensitivity）。"""
    from math_agent.config import MAX_CODE_NO_PRIMARY_ITERATIONS
    s = _state_with_consistency_report(
        approved=False, score=0, iteration=MAX_CODE_NO_PRIMARY_ITERATIONS,
    )
    assert after_model_code_consistency(s) == "stop"


def test_consistency_retries_without_primary_below_cap():
    """无主证据在专门上限之内仍继续 retry_coder。"""
    from math_agent.config import MAX_CODE_NO_PRIMARY_ITERATIONS
    s = _state_with_consistency_report(
        approved=False, score=0, iteration=MAX_CODE_NO_PRIMARY_ITERATIONS - 1,
    )
    assert after_model_code_consistency(s) == "retry_coder"


def test_consistency_retries_coder_when_no_reports():
    s = MathModelingState(problem="p", code_verify_iteration=0)
    assert after_model_code_consistency(s) == "retry_coder"


def test_human_review_routes_rejection_to_stop():
    from math_agent.routing import after_human_review
    from math_agent.state import HumanDecision
    s = MathModelingState(problem="p", human_decision=HumanDecision(approved=False))
    assert after_human_review(s) == "stop"


def test_human_review_routes_approval_to_finalize():
    from math_agent.routing import after_human_review
    from math_agent.state import HumanDecision
    s = MathModelingState(problem="p", human_decision=HumanDecision(approved=True))
    assert after_human_review(s) == "finalize"


# ---------------------------------------------------------------------------
# after_blueprint_critic + brief_coverage 门禁
# ---------------------------------------------------------------------------

def _state_with_brief_coverage(
    approved: bool,
    iteration: int,
    brief,
    blueprint,
):
    s = MathModelingState(problem="p", blueprint_iteration=iteration)
    s.brief = brief
    s.problem_blueprint = blueprint
    s.critic_reports.append(CriticReport(
        target="analyst", score=9 if approved else 4, approved=approved,
        critic_type="blueprint",
    ))
    return s


def test_blueprint_critic_retries_on_coverage_gap_under_cap():
    from math_agent.brief import ModelingBrief, PerQuestionDirectionItem
    from math_agent.config import MAX_BLUEPRINT_ITERATIONS
    from math_agent.state import ProblemBlueprint

    brief = ModelingBrief(per_question_direction=[
        PerQuestionDirectionItem(id="dir-1", direction="MILP"),
    ])
    blueprint = ProblemBlueprint(core_task="t", brief_coverage=[])
    s = _state_with_brief_coverage(
        approved=True, iteration=1, brief=brief, blueprint=blueprint,
    )
    assert s.blueprint_iteration < MAX_BLUEPRINT_ITERATIONS
    assert after_blueprint_critic(s) == "retry"


def test_blueprint_critic_stops_on_coverage_gap_at_cap():
    from math_agent.brief import ModelingBrief, PerQuestionDirectionItem
    from math_agent.config import MAX_BLUEPRINT_ITERATIONS
    from math_agent.state import ProblemBlueprint

    brief = ModelingBrief(per_question_direction=[
        PerQuestionDirectionItem(id="dir-1", direction="MILP"),
    ])
    blueprint = ProblemBlueprint(core_task="t", brief_coverage=[])
    s = _state_with_brief_coverage(
        approved=True, iteration=MAX_BLUEPRINT_ITERATIONS, brief=brief, blueprint=blueprint,
    )
    assert after_blueprint_critic(s) == "stop"


def test_blueprint_critic_advances_on_full_coverage_and_approved():
    from math_agent.brief import ModelingBrief, PerQuestionDirectionItem, BriefCoverageItem
    from math_agent.state import ProblemBlueprint

    brief = ModelingBrief(per_question_direction=[
        PerQuestionDirectionItem(id="dir-1", direction="MILP"),
    ])
    blueprint = ProblemBlueprint(
        core_task="t",
        brief_coverage=[BriefCoverageItem(brief_item_id="dir-1", status="followed")],
    )
    s = _state_with_brief_coverage(
        approved=True, iteration=1, brief=brief, blueprint=blueprint,
    )
    assert after_blueprint_critic(s) == "advance"
