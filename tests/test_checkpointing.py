from math_agent.checkpointing import checkpoint_serializer, sqlite_saver
from math_agent.state import Assumption, MathModelingState, PaperSections


def test_checkpoint_serializer_roundtrips_registered_state_types():
    serde = checkpoint_serializer()
    state = MathModelingState(
        problem="p",
        assumptions=[Assumption(statement="a")],
        paper=PaperSections(abstract="x"),
    )

    typed = serde.dumps_typed(state)
    restored = serde.loads_typed(typed)

    assert isinstance(restored, MathModelingState)
    assert isinstance(restored.assumptions[0], Assumption)
    assert isinstance(restored.paper, PaperSections)


def test_sqlite_saver_uses_beacon_serializer(tmp_path):
    with sqlite_saver(tmp_path / "checkpoints.sqlite") as saver:
        typed = saver.serde.dumps_typed(Assumption(statement="safe"))
        restored = saver.serde.loads_typed(typed)
    assert isinstance(restored, Assumption)


def test_checkpoint_allowlist_contains_brief_types():
    """brief 类型（ModelingBrief / BriefCoverageItem）必须在 checkpoint 白名单内。

    回归：它们定义在 math_agent.brief（不是 math_agent.state），曾不在 allowlist，
    读取含 brief 的 checkpoint 时被 JsonPlusSerializer 拦截（降级为 dict + 警告）。
    """
    from math_agent.brief import BriefCoverageItem, ModelingBrief
    from math_agent.checkpointing import _allowed_state_types

    names = {t.__name__ for t in _allowed_state_types()}
    assert ModelingBrief.__name__ in names
    assert BriefCoverageItem.__name__ in names


def test_checkpoint_roundtrip_preserves_modeling_brief(tmp_path, caplog):
    """含 brief 的 checkpoint：invoke → get_state → 续跑（recover 语义）全链路。

    断言：a) state.brief 类型是 ModelingBrief（不是 dict）；
    b) 没有 "Blocked deserialization" 警告；c) ProblemBlueprint.brief_coverage
    元素类型是 BriefCoverageItem；recover（invoke(None)）时节点收到 ModelingBrief。
    """
    import logging

    from langgraph.graph import END, StateGraph

    from math_agent.brief import (
        BriefCoverageItem,
        ModelingBrief,
        PerQuestionDirectionItem,
    )
    from math_agent.state import MathModelingState, ProblemBlueprint

    brief = ModelingBrief(
        problem_id="mcm51-a",
        per_question_direction=[
            PerQuestionDirectionItem(id="dir-1", question_id="1.2", direction="变点检测"),
        ],
    )
    blueprint = ProblemBlueprint(
        core_task="t",
        brief_coverage=[BriefCoverageItem(brief_item_id="dir-1", status="followed")],
    )
    received = {}

    def _first(state):
        return {"iteration": state.iteration + 1}

    def _second(state):
        received["brief_type"] = type(state.brief).__name__
        return {"iteration": state.iteration + 1}

    g = StateGraph(MathModelingState)
    g.add_node("first", _first)
    g.add_node("second", _second)
    g.set_entry_point("first")
    g.add_edge("first", "second")
    g.add_edge("second", END)

    with sqlite_saver(tmp_path / "checkpoints.sqlite") as saver:
        compiled = g.compile(checkpointer=saver, interrupt_before=["second"])
        cfg = {"configurable": {"thread_id": "t1"}}
        caplog.set_level(logging.WARNING, logger="langgraph.checkpoint.serde.jsonplus")
        compiled.invoke({
            "problem": "p",
            "brief": brief,
            "problem_blueprint": blueprint,
        }, config=cfg)

        snap = compiled.get_state(cfg)
        assert type(snap.values["brief"]).__name__ == "ModelingBrief"
        assert isinstance(snap.values["brief"], ModelingBrief)
        assert snap.values["brief"].per_question_direction[0].id == "dir-1"
        assert isinstance(snap.values["problem_blueprint"].brief_coverage[0], BriefCoverageItem)
        assert "Blocked deserialization" not in caplog.text

        # 模拟 recover：从 checkpoint 续跑（invoke(None)），节点收到 ModelingBrief
        compiled.invoke(None, config=cfg)
        assert received["brief_type"] == "ModelingBrief"
