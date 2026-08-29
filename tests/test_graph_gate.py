"""brief_coverage 门禁 stop 路径的图级集成测试（B09）。

覆盖：analyst 不回应 brief（brief_coverage 为空）→ after_blueprint_critic
立即 stop（D-023 / 学-11）→ 图到达 END、checkpoint next == ()。
无 brief 的向后兼容（恒 advance）由 routing/brief 单测覆盖，不在此重复。
"""
from langgraph.checkpoint.memory import MemorySaver

from math_agent.brief import BriefCoverageItem, ModelingBrief, PerQuestionDirectionItem
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


def test_coverage_gate_stops_graph_on_first_gap(monkeypatch, tmp_path):
    monkeypatch.setattr("math_agent.graph.analyst_node", _fake_analyst_no_coverage)
    monkeypatch.setattr("math_agent.graph.blueprint_critic_node", _fake_blueprint_critic)
    graph = build_graph(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": "t1"}}
    result = graph.invoke(
        MathModelingState(problem="p", brief=_brief(), output_dir=str(tmp_path)),
        config,
    )
    assert result["blueprint_iteration"] == 1
    snapshot = graph.get_state(config)
    assert snapshot.next == ()


def test_coverage_gate_does_not_retry_analyst(monkeypatch, tmp_path):
    """coverage 缺口首次即停，不绕回 analyst。"""
    calls = {"analyst": 0}

    def counting_analyst(state):
        calls["analyst"] += 1
        return _fake_analyst_no_coverage(state)

    monkeypatch.setattr("math_agent.graph.analyst_node", counting_analyst)
    monkeypatch.setattr("math_agent.graph.blueprint_critic_node", _fake_blueprint_critic)
    graph = build_graph(checkpointer=MemorySaver())
    graph.invoke(
        MathModelingState(problem="p", brief=_brief(), output_dir=str(tmp_path)),
        {"configurable": {"thread_id": "t2"}},
    )
    assert calls["analyst"] == 1


def test_coverage_gate_passes_when_all_items_followed(monkeypatch, tmp_path):
    """全部 followed → 门禁通过 → advance；后续 model_critic 未过也立即 stop。"""

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
        return {
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
    assert result["blueprint_iteration"] == 1
    assert result["stage_target"] == "basic"
    snapshot = graph.get_state({"configurable": {"thread_id": "t3"}})
    assert snapshot.next == ()
