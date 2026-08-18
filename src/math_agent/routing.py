"""集中放图的条件边路由函数，便于单元测试。

约定的返回值是字符串字面量，graph.py 会把它映射到具体节点名。
"""
from math_agent.config import (
    MAX_MODEL_ITERATIONS, MAX_WRITER_ITERATIONS,
    MAX_BLUEPRINT_ITERATIONS, MAX_CODE_VERIFY_ITERATIONS,
    MAX_CODE_NO_PRIMARY_ITERATIONS,
    MIN_MODEL_CRITIC_SCORE, MIN_MODEL_CODE_SCORE, MIN_PAPER_CRITIC_SCORE,
)
from math_agent.state import MathModelingState


def after_blueprint_critic(state: MathModelingState) -> str:
    """blueprint_critic 审查完后的去向。

    blueprint_iteration 语义：blueprint_critic_node 返回时已递增。
    - == 0：尚未审查（不应到此，但防御性返回 retry）
    - == 1：analyst 首轮输出已被审查一次。若未通过，允许一次 retry。
    - >= 2：第二次审查仍未通过，则带警告前进（最多一次 retry）。
    """
    report = state.latest_critic("analyst", critic_type="blueprint")
    if report is None:
        return "retry"
    # brief_coverage 门禁（确定性，不依赖 LLM）：提供 --brief 时，blueprint 必须
    # 逐条回应 brief 条目（followed，或 deviated+理由）。不满足 → 重试；预算耗尽
    # 仍不满足 → stop 硬停（人工输入方向不能被忽略；无 brief 时恒通过，向后兼容）。
    from math_agent.brief import brief_coverage_problems
    problems = brief_coverage_problems(state.brief, state.problem_blueprint)
    if problems:
        if state.blueprint_iteration >= MAX_BLUEPRINT_ITERATIONS:
            return "stop"
        return "retry"
    if report.approved:
        return "advance"
    if state.blueprint_iteration >= MAX_BLUEPRINT_ITERATIONS:
        return "advance_with_warning"
    return "retry"


def after_model_critic(state: MathModelingState) -> str:
    """basic/improved/final 任一阶段评审完后的去向。"""
    critic = state.latest_critic("modeler")
    if critic is None:
        return "retry"
    passed = critic.approved and critic.score >= MIN_MODEL_CRITIC_SCORE

    if state.stage_target == "final":
        if passed:
            return "to_coder"
        if state.iteration >= MAX_MODEL_ITERATIONS:
            return "stop"
        return "retry"

    # basic / improved
    if passed or state.iteration >= MAX_MODEL_ITERATIONS:
        return "advance"
    return "retry"


def after_paper_critic(state: MathModelingState) -> str:
    """writer 闭环：优秀论文门槛通过才前进；重试耗尽仍不通过则停止。

    自动评审只是质量预筛，不是最终裁决。修复轮耗尽仍未达门槛时，只要论文
    关键 section 全部有实质内容，就移交 human_review 由人工整体评估决定
    （approve 走 finalize；reject 停止），不再直接 stop 掐断人工机会。
    论文不完整（关键 section 为空）时仍 stop，防止半成品流入人工环节。
    """
    paper_has_content = all([
        (state.paper.abstract or "").strip(),
        (state.paper.model_section or "").strip(),
        (state.paper.solution or "").strip(),
        (state.paper.conclusion or "").strip(),
    ])
    if not paper_has_content:
        return "stop" if state.writer_iteration >= MAX_WRITER_ITERATIONS else "retry"
    critic = state.latest_critic("paper")
    if critic is None:
        return "stop" if state.writer_iteration >= MAX_WRITER_ITERATIONS else "retry"
    if critic.approved and critic.score >= MIN_PAPER_CRITIC_SCORE:
        return "advance"
    if state.writer_iteration >= MAX_WRITER_ITERATIONS:
        return "advance_review"
    return "retry"


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
    valid = {"code_generate", "code_execute", "interpret"}
    return state.sensitivity_phase if state.sensitivity_phase in valid else "done"


def after_figure_work(state: MathModelingState) -> str:
    return state.figure_phase if state.figure_phase in {"critic", "analysis"} else "done"


def after_model_code_consistency(state: MathModelingState) -> str:
    """model_code_consistency 审查完后的去向。

    无主证据与“有主证据但低分”使用两个独立预算：
    - 无主证据轮次计 code_verify_iteration，上限 MAX_CODE_NO_PRIMARY_ITERATIONS；
    - 有主证据低分轮次计 code_verify_low_score_iteration，上限 MAX_CODE_VERIFY_ITERATIONS。
    分开计避免无主证据轮次提前耗尽低分修复预算（r3 曾因此拿到证据后立即停机）。
    approved 且达到配置门槛 -> advance；未通过则 retry_coder；
    任一预算耗尽仍不达标时停止，禁止带病进入论文阶段。
    """
    if not state.model_code_reports:
        return "retry_coder"

    report = state.model_code_reports[-1]
    if report.approved and report.score >= MIN_MODEL_CODE_SCORE:
        return "advance"
    latest = state.latest_code_artifacts()
    has_primary = any(
        artifact.success and artifact.evidence_role == "primary"
        for artifact in latest
    )
    # 没有主证据不是“低分但可继续”的软问题，任何重试上限都不能把它放行到
    # sensitivity/writer。下一 coder 批次可使用确定性安全求解器或明确失败。
    # 但也不再无限重试：连续无主证据达到专门上限后停止整条流水线，由人工先检查
    # 失败原因（通常意味着门禁与 prompt 的系统性矛盾，重试本身不会解决）。
    if not has_primary:
        if state.code_verify_iteration >= MAX_CODE_NO_PRIMARY_ITERATIONS:
            return "stop"
        return "retry_coder"
    if state.code_verify_low_score_iteration >= MAX_CODE_VERIFY_ITERATIONS:
        return "stop"
    return "retry_coder"


def after_human_review(state: MathModelingState) -> str:
    """只有明确批准才进入最终 LaTeX；拒绝或缺少决定都停止。"""
    decision = state.human_decision
    return "finalize" if decision is not None and decision.approved else "stop"
