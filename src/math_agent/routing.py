"""集中放图的条件边路由函数，便于单元测试。

约定的返回值是字符串字面量，graph.py 会把它映射到具体节点名。

学-11 / D-023：阻止性门禁首次未通过即 stop（人/agent 断点续跑）。
自动重试不在本层：留给 complete() 的 JSON/传输修复，以及 coder 单任务 MAX_CODE_RETRIES。
"""
from math_agent.config import (
    MIN_MODEL_CRITIC_SCORE, MIN_MODEL_CODE_SCORE, MIN_PAPER_CRITIC_SCORE,
)
from math_agent.state import MathModelingState


def _paper_has_content(state: MathModelingState) -> bool:
    return all([
        (state.paper.abstract or "").strip(),
        (state.paper.model_section or "").strip(),
        (state.paper.solution or "").strip(),
        (state.paper.conclusion or "").strip(),
    ])


def after_blueprint_critic(state: MathModelingState) -> str:
    """blueprint_critic 审查完后的去向。

    无 report、brief_coverage 缺口、或 critic 未通过 → 立即 stop。
    无 brief 时 coverage 恒通过（向后兼容）。
    """
    report = state.latest_critic("analyst", critic_type="blueprint")
    if report is None:
        return "stop"
    from math_agent.brief import brief_coverage_problems
    problems = brief_coverage_problems(state.brief, state.problem_blueprint)
    if problems:
        return "stop"
    if report.approved:
        return "advance"
    return "stop"


def after_model_critic(state: MathModelingState) -> str:
    """basic/improved/final 任一阶段评审完后的去向。未通过不再带病前进。"""
    critic = state.latest_critic("modeler")
    if critic is None:
        return "stop"
    passed = critic.approved and critic.score >= MIN_MODEL_CRITIC_SCORE
    if state.stage_target == "final":
        return "to_coder" if passed else "stop"
    return "advance" if passed else "stop"


def after_paper_critic(state: MathModelingState) -> str:
    """论文门槛通过才前进；未通过立即 stop。

    ``paper_review_takeover`` 仅供 ``math-agent review`` 人工接管：内容完整时
    走 advance → table_assembler → human_review，不恢复自动 retry。
    """
    paper_ok = _paper_has_content(state)
    if state.paper_review_takeover and paper_ok:
        return "advance"
    if not paper_ok:
        return "stop"
    critic = state.latest_critic("paper")
    if critic is None:
        return "stop"
    if critic.approved and critic.score >= MIN_PAPER_CRITIC_SCORE:
        return "advance"
    return "stop"


def after_writer_step(state: MathModelingState) -> str:
    """writer 子流程：队列还有章节 -> 继续写 section；空 -> 进 paper_critic。

    prep（writer_node）和 section（writer_section_node）共用此路由。
    """
    return "section" if state.writer_section_queue else "done"


def after_modeler_work(state: MathModelingState) -> str:
    """模型子流程：每个推导步骤和一致性检查分别形成 checkpoint。"""
    return state.modeler_phase if state.modeler_phase in {"derive", "check"} else "done"


def after_coder_work(state: MathModelingState) -> str:
    if state.coder_work_queue and state.coder_phase in {"generate", "execute"}:
        return state.coder_phase
    return "done"


def after_sensitivity_work(state: MathModelingState) -> str:
    if state.sensitivity_phase == "stop":
        return "stop"
    valid = {"code_generate", "code_execute", "interpret"}
    return state.sensitivity_phase if state.sensitivity_phase in valid else "done"


def after_figure_work(state: MathModelingState) -> str:
    return state.figure_phase if state.figure_phase in {"critic", "analysis"} else "done"


def after_model_code_consistency(state: MathModelingState) -> str:
    """model_code_consistency 审查完后的去向。

    hard 红线（D-022）与未通过/无主证据/无报告一律立即 stop。
    通过且达到配置门槛 → advance。
    接续：编码门禁用 ``restart --from coder``；写作门禁用 ``restart --from writer``。
    """
    if not state.model_code_reports:
        return "stop"

    from math_agent.brief import hard_redline_violations
    latest = state.latest_code_artifacts()
    code = "\n".join(a.code or "" for a in latest)
    stdout = "\n".join(a.stdout or "" for a in latest if a.success)
    paper = ""
    if state.paper:
        paper = "\n".join(
            getattr(state.paper, name, "") or ""
            for name in (
                "abstract", "model_section", "solution", "sensitivity", "conclusion",
            )
        )
    if hard_redline_violations(state.brief, code=code, stdout=stdout, paper=paper):
        return "stop"

    report = state.model_code_reports[-1]
    if report.approved and report.score >= MIN_MODEL_CODE_SCORE:
        return "advance"
    return "stop"


def after_human_review(state: MathModelingState) -> str:
    """只有明确批准才进入最终 LaTeX；拒绝或缺少决定都停止。"""
    decision = state.human_decision
    return "finalize" if decision is not None and decision.approved else "stop"
