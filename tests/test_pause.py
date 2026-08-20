"""P0 pause/resume 单元测试：mock 图 + MemorySaver，无 LLM。"""
from __future__ import annotations

import pytest
from langgraph.checkpoint.memory import MemorySaver

from math_agent.graph import build_graph
from math_agent.pause_control import (
    PauseRequested,
    clear_pause,
    pause_marker_path,
    pause_requested,
    request_pause,
)
from math_agent.state import (
    CriticReport, MathModelingState, ProblemBlueprint, SubQuestionBlueprint,
)
from math_agent.supervisor import SupervisorPolicy, supervise_loop


def _fake_analyst(state: MathModelingState):
    """模拟 analyst 输出一个可继续的 blueprint。"""
    return {
        "problem_blueprint": ProblemBlueprint(
            core_task="test",
            subquestions=[SubQuestionBlueprint(id="1", original_text="q1", task_type="generic")],
        ),
    }


def _fake_blueprint_critic(state: MathModelingState):
    """模拟 blueprint_critic 通过。"""
    return {
        "blueprint_iteration": 1,
        "critic_reports": [
            CriticReport(target="analyst", critic_type="blueprint", score=9, approved=True),
        ],
    }


def _fake_blueprint_critic_stop(state: MathModelingState):
    """模拟 blueprint_critic 不通过且预算耗尽，图在 critic 后 stop。"""
    from math_agent.config import MAX_BLUEPRINT_ITERATIONS
    return {
        "blueprint_iteration": MAX_BLUEPRINT_ITERATIONS,
        "critic_reports": [
            CriticReport(target="analyst", critic_type="blueprint", score=4, approved=False),
        ],
    }


def _make_graph(monkeypatch, tmp_path):
    monkeypatch.setattr("math_agent.graph.analyst_node", _fake_analyst)
    monkeypatch.setattr("math_agent.graph.blueprint_critic_node", _fake_blueprint_critic)
    return build_graph(checkpointer=MemorySaver())


def test_pause_request_stops_before_first_node_boundary(tmp_path, monkeypatch):
    graph = _make_graph(monkeypatch, tmp_path)
    config = {"configurable": {"thread_id": "pause_first"}}
    request_pause(tmp_path)
    assert pause_requested(tmp_path) is True

    with pytest.raises(PauseRequested):
        graph.invoke(
            MathModelingState(problem="p", output_dir=str(tmp_path)),
            config,
        )

    snapshot = graph.get_state(config)
    assert snapshot.next == ("analyst",)
    assert snapshot.values.get("problem_blueprint") is None  # analyst 尚未执行


def test_pause_lifecycle_and_resume_after_clear(tmp_path, monkeypatch):
    """请求暂停 -> 捕获 -> 清除 -> 从同一节点恢复，不跳跃。"""
    monkeypatch.setattr("math_agent.graph.analyst_node", _fake_analyst)
    graph = build_graph(checkpointer=MemorySaver(), interrupt_before=["blueprint_critic"])
    config = {"configurable": {"thread_id": "pause_lifecycle"}}
    request_pause(tmp_path)

    with pytest.raises(PauseRequested) as exc:
        graph.invoke(
            MathModelingState(problem="p", output_dir=str(tmp_path)),
            config,
        )
    assert exc.value.node == "analyst"
    snap = graph.get_state(config)
    assert snap.next == ("analyst",)

    clear_pause(tmp_path)
    assert pause_requested(tmp_path) is False
    graph.invoke(None, config)
    snap = graph.get_state(config)
    # analyst 执行完，停在 blueprint_critic 前
    assert snap.next == ("blueprint_critic",)
    assert snap.values.get("problem_blueprint") is not None


def test_pause_after_a_node_then_resume_no_repeat(tmp_path, monkeypatch):
    """analyst 执行完后，在 blueprint_critic 边界暂停；恢复后 critic 只执行一次。"""
    monkeypatch.setattr("math_agent.graph.analyst_node", _fake_analyst)
    monkeypatch.setattr("math_agent.graph.blueprint_critic_node", _fake_blueprint_critic_stop)
    # 路由语义由 test_routing.py 覆盖；此处 patch 为 stop 以聚焦 pause/resume 边界，
    # 避免 advance_with_warning 映射到真实 modeler 触发 LLM 调用。
    monkeypatch.setattr("math_agent.graph.after_blueprint_critic", lambda s: "stop")
    graph = build_graph(checkpointer=MemorySaver(), interrupt_before=["blueprint_critic"])
    config = {"configurable": {"thread_id": "pause_after_analyst"}}

    # 第一步：analyst 执行完，在 blueprint_critic 前中断
    graph.invoke(
        MathModelingState(problem="p", output_dir=str(tmp_path)),
        config,
    )
    snap1 = graph.get_state(config)
    assert snap1.next == ("blueprint_critic",)

    # 第二步：写入暂停，再 invoke 会被 blueprint_critic 边界拦截
    request_pause(tmp_path)
    with pytest.raises(PauseRequested) as exc:
        graph.invoke(None, config)
    assert exc.value.node == "blueprint_critic"
    snap2 = graph.get_state(config)
    assert snap2.next == ("blueprint_critic",)

    # 第三步：清除后恢复，blueprint_critic 执行一次，然后图 stop
    clear_pause(tmp_path)
    result = graph.invoke(None, config)
    from math_agent.config import MAX_BLUEPRINT_ITERATIONS
    assert result["blueprint_iteration"] == MAX_BLUEPRINT_ITERATIONS  # fake 写入的值
    # 确认 critic 只执行一次：报告中只有一条 blueprint critic
    reports = [r for r in result["critic_reports"] if r.critic_type == "blueprint"]
    assert len(reports) == 1
    final_snap = graph.get_state(config)
    assert final_snap.next == ()  # 停止态


def test_supervise_loop_returns_paused_on_marker(tmp_path, monkeypatch):
    """supervise_loop 在 worker 退出后检查到暂停标记，返回 paused 不递增 recoveries。"""
    request_pause(tmp_path)
    calls = {"attempts": 0}

    def worker(mode):
        calls["attempts"] += 1
        # 模拟一个正常退出的 worker（returncode 0），但 checkpoint 仍非终态
        from math_agent.supervisor import WorkerResult
        return WorkerResult(returncode=0)

    from math_agent.supervisor import RunInspection

    def inspect():
        # 非终态：checkpoint 存在，next 指向 analyst
        return RunInspection(checkpoint_exists=True, next_node="analyst")

    result = supervise_loop(
        worker=worker,
        inspect=inspect,
        sleep=lambda s: None,
        initial_mode="run",
        pause_requested=lambda: pause_requested(tmp_path),
    )
    assert result.status == "paused"
    assert result.attempts == 1
    assert result.recoveries == 0


def test_pause_request_idempotent_and_updates_timestamp(tmp_path):
    request_pause(tmp_path)
    t1 = pause_marker_path(tmp_path).stat().st_mtime
    request_pause(tmp_path)
    t2 = pause_marker_path(tmp_path).stat().st_mtime
    assert t2 >= t1
    clear_pause(tmp_path)
    assert pause_marker_path(tmp_path).exists() is False
    clear_pause(tmp_path)  # 幂等
