"""brief_coverage 门禁 stop 路径的图级集成测试（B09）。

覆盖：analyst 持续不回应 brief（brief_coverage 为空）→ after_blueprint_critic
retry → retry → stop（MAX_BLUEPRINT_ITERATIONS 后）→ 图到达 END、
checkpoint 的 next == ()（recover 空转语义：next 为空即无续跑点）。
无 brief 的向后兼容（恒 advance）由 routing/brief 单测覆盖，不在此重复。
"""
from langgraph.checkpoint.memory import MemorySaver

from math_agent.brief import BriefCoverageItem, ModelingBrief, PerQuestionDirectionItem
from math_agent.config import MAX_BLUEPRINT_ITERATIONS
from math_agent.graph import build_graph
from math_agent.state import CriticReport, MathModelingState, ProblemBlueprint


def _brief() -> ModelingBrief:
    return ModelingBrief(
        schema_version=1,
        problem_id="p1",
        per_question_direction=[
            PerQuestionDirectionItem(id="1.1-direction", question_id="1.1", direction="d"),
        ],
    )


def _fake_analyst_no_coverage(state):
    """模拟 analyst 无视 brief：blueprint 不带任何 brief_coverage 回应。"""
    return {"problem_blueprint": ProblemBlueprint(core_task="x", brief_coverage=[])}


def _fake_blueprint_critic(state):
    """真实节点语义：返回时 blueprint_iteration 已递增；评审通过但门禁仍会拦。"""
    return {
        "blueprint_iteration": (state.blueprint_iteration or 0) + 1,
        "critic_reports": [
            CriticReport(target="analyst", critic_type="blueprint", score=9, approved=True),
        ],
    }


def test_coverage_gate_stops_graph_after_retry_budget(monkeypatch, tmp_path):
    monkeypatch.setattr("math_agent.graph.analyst_node", _fake_analyst_no_coverage)
    monkeypatch.setattr("math_agent.graph.blueprint_critic_node", _fake_blueprint_critic)
    graph = build_graph(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": "t1"}}
    result = graph.invoke(
        MathModelingState(problem="p", brief=_brief(), output_dir=str(tmp_path)),
        config,
    )
    # 预算耗尽后 stop：blueprint_iteration 达到上限，图正常收敛到 END
    assert result["blueprint_iteration"] >= MAX_BLUEPRINT_ITERATIONS
    snapshot = graph.get_state(config)
    assert snapshot.next == ()  # recover 空转：next 为空 = 无续跑点


def test_coverage_gate_retries_then_stops_exactly_at_budget(monkeypatch, tmp_path):
    """每次重试都走 analyst→blueprint_critic 一圈；预算用尽即停，不多绕。"""
    monkeypatch.setattr("math_agent.graph.analyst_node", _fake_analyst_no_coverage)
    monkeypatch.setattr("math_agent.graph.blueprint_critic_node", _fake_blueprint_critic)
    graph = build_graph(checkpointer=MemorySaver())
    result = graph.invoke(
        MathModelingState(problem="p", brief=_brief(), output_dir=str(tmp_path)),
        {"configurable": {"thread_id": "t2"}},
    )
    # 首次审查后 iteration=1（< 上限 → retry）；第二次审查后 iteration=2（>= 上限 → stop）
    assert result["blueprint_iteration"] == MAX_BLUEPRINT_ITERATIONS


def test_coverage_gate_passes_when_all_items_followed(monkeypatch, tmp_path):
    """全部 followed → 门禁通过 → advance（不进入 stop 路径）。"""
    from math_agent.config import MAX_MODEL_ITERATIONS

    def _analyst_followed(state):
        return {
            "problem_blueprint": ProblemBlueprint(
                core_task="x",
                brief_coverage=[
                    BriefCoverageItem(brief_item_id="1.1-direction", status="followed"),
                ],
            ),
        }

    def _fake_modeler_prepare(state):
        return {}

    def _fake_model_critic(state):
        # 持续不通过并递增 iteration：basic/improved 到上限后 advance，
        # final 到上限后 stop（终止图运行，不触碰 coder 真实节点）。
        return {
            "iteration": (state.iteration or 0) + 1,
            "critic_reports": [
                CriticReport(target="modeler", score=4, approved=False),
            ],
        }

    monkeypatch.setattr("math_agent.graph.analyst_node", _analyst_followed)
    monkeypatch.setattr("math_agent.graph.blueprint_critic_node", _fake_blueprint_critic)
    monkeypatch.setattr("math_agent.graph.modeler_prepare_node", _fake_modeler_prepare)
    monkeypatch.setattr("math_agent.graph.model_critic_node", _fake_model_critic)
    graph = build_graph(checkpointer=MemorySaver())
    result = graph.invoke(
        MathModelingState(problem="p", brief=_brief(), output_dir=str(tmp_path)),
        {"configurable": {"thread_id": "t3"}},
    )
    # 门禁放行：blueprint 只审查一次（无 retry），流程一路走到 final 阶段才停
    assert result["blueprint_iteration"] == 1
    assert result["stage_target"] == "final"
    assert result["iteration"] == MAX_MODEL_ITERATIONS
