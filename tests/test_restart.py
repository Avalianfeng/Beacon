"""P1 restart --from coder 单元测试：真实 SqliteSaver + fake 节点，无 LLM。

门禁停机态构造：fake model_code_consistency 返回不通过报告且无主证据；
after_model_code_consistency 首次未过即 stop（D-023）。
routing 语义本身由 test_routing.py 覆盖，此处不重复。
"""
from __future__ import annotations

import hashlib
import json

from typer.testing import CliRunner

from math_agent.cli import app, _saver_cm
from math_agent.state import (
    CriticReport, MathModelingState, ModelCodeConsistencyReport,
    ProblemBlueprint, SubQuestionBlueprint,
)

runner = CliRunner()
THREAD = "default"


def _fake_analyst(state: MathModelingState):
    return {
        "problem_blueprint": ProblemBlueprint(
            core_task="test",
            subquestions=[SubQuestionBlueprint(id="1", original_text="q1", task_type="generic")],
        ),
    }


def _fake_blueprint_critic(state: MathModelingState):
    return {
        "blueprint_iteration": 1,
        "critic_reports": [
            CriticReport(target="analyst", critic_type="blueprint", score=9, approved=True),
        ],
    }


def _fake_modeler(state: MathModelingState):
    return {}  # modeler_phase 默认 done -> 直接进 model_critic


def _fake_model_critic(state: MathModelingState):
    return {
        "critic_reports": [CriticReport(target="modeler", score=9, approved=True)],
    }


def _install_fakes(monkeypatch, approve_on_consistency):
    """approve_on_consistency: callable(consistency 第几次被调用) -> bool。"""
    calls = {"coder": 0, "consistency": 0}

    def fake_coder(state: MathModelingState):
        calls["coder"] += 1
        return {}

    def fake_consistency(state: MathModelingState):
        calls["consistency"] += 1
        if approve_on_consistency(calls["consistency"]):
            return {
                "model_code_reports": [
                    ModelCodeConsistencyReport(score=9, approved=True),
                ],
            }
        return {
            "model_code_reports": [
                ModelCodeConsistencyReport(score=3, approved=False),
            ],
        }

    monkeypatch.setattr("math_agent.graph.analyst_node", _fake_analyst)
    monkeypatch.setattr("math_agent.graph.blueprint_critic_node", _fake_blueprint_critic)
    monkeypatch.setattr("math_agent.graph.modeler_prepare_node", _fake_modeler)
    monkeypatch.setattr("math_agent.graph.model_critic_node", _fake_model_critic)
    monkeypatch.setattr("math_agent.graph.coder_prepare_node", fake_coder)
    monkeypatch.setattr("math_agent.graph.model_code_consistency_node", fake_consistency)
    return calls


def _config():
    return {"configurable": {"thread_id": THREAD}}


def _run_to_gate_stop(out, calls):
    """跑真实图到一致性门禁停机；返回停机快照。"""
    from math_agent.graph import build_graph

    with _saver_cm(out) as saver:
        g = build_graph(checkpointer=saver)
        g.invoke(
            MathModelingState(problem="p", output_dir=str(out)),
            _config(),
        )
        snap = g.get_state(_config())
    assert snap.next == (), f"应停在门禁停机态，实际 next={snap.next}"
    assert calls["coder"] == 1 and calls["consistency"] == 1
    return snap


def _write_manifest(out, **extra):
    manifest = {"thread": THREAD, "problem_sha256": "x" * 64}
    manifest.update(extra)
    (out / "run_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8",
    )


def _invoke_restart(out, monkeypatch, extra_args=()):
    """CLI restart；build_graph 换成 fake 节点图，并在 sensitivity 前中断。"""
    from math_agent.graph import build_graph

    def factory(checkpointer=None, interrupt_before=None):
        return build_graph(checkpointer=checkpointer, interrupt_before=["sensitivity"])

    monkeypatch.setattr("math_agent.cli.build_graph", factory)
    return runner.invoke(
        app,
        ["restart", "--out", str(out), "--reason", "人工判定守卫误杀，放行重试", *extra_args],
    )


def _snapshot(out):
    from math_agent.graph import build_graph

    with _saver_cm(out) as saver:
        g = build_graph(checkpointer=saver)
        return g.get_state(_config())


def test_restart_reexecutes_coder_and_advances(tmp_path, monkeypatch):
    """门禁停机 -> restart -> 计数器归零、coder 重执行、二次放行后推进到 sensitivity。"""
    out = tmp_path / "run"
    out.mkdir()
    calls = _install_fakes(monkeypatch, approve_on_consistency=lambda n: n >= 2)
    _run_to_gate_stop(out, calls)
    _write_manifest(out)
    (out / "gate_diagnostics.json").write_text("{}", encoding="utf-8")

    result = _invoke_restart(out, monkeypatch)

    assert result.exit_code == 0, result.output
    assert calls["coder"] == 2, "coder 应恰好重执行一次"
    assert calls["consistency"] == 2
    snap = _snapshot(out)
    assert snap.next == ("sensitivity",), f"二次放行后应推进到 sensitivity，实际 {snap.next}"
    assert snap.values["code_verify_iteration"] == 0, "计数器应被重置"

    manifest = json.loads((out / "run_manifest.json").read_text(encoding="utf-8"))
    assert len(manifest["restarts"]) == 1
    record = manifest["restarts"][0]
    assert record["from_node"] == "coder"
    assert record["reason"] == "人工判定守卫误杀，放行重试"
    assert record["checkpoint_id"]
    assert manifest["problem_sha256"] == "x" * 64, "既有键应保留"

    assert not (out / "gate_diagnostics.json").exists(), "原 gate_diagnostics 应被标注取代"
    superseded = list(out.glob("gate_diagnostics.superseded-*.json"))
    assert len(superseded) == 1


def test_restart_second_stop_does_not_auto_retry(tmp_path, monkeypatch):
    """restart 后再次门禁停机：不循环、不自动重试，停机态交还人工。"""
    out = tmp_path / "run"
    out.mkdir()
    calls = _install_fakes(monkeypatch, approve_on_consistency=lambda n: False)
    _run_to_gate_stop(out, calls)
    _write_manifest(out)

    result = _invoke_restart(out, monkeypatch)

    assert result.exit_code == 0, result.output
    assert calls["coder"] == 2, "restart 只重执行一次 coder，不得自动重试"
    assert calls["consistency"] == 2
    snap = _snapshot(out)
    assert snap.next == (), f"二次停机应回到停止态，实际 next={snap.next}"


def test_restart_rejects_non_stopped_checkpoint(tmp_path, monkeypatch):
    """checkpoint next 非空（进行中/可续跑态）时拒绝 restart。"""
    from math_agent.graph import build_graph

    out = tmp_path / "run"
    out.mkdir()
    _install_fakes(monkeypatch, approve_on_consistency=lambda n: True)
    with _saver_cm(out) as saver:
        g = build_graph(checkpointer=saver, interrupt_before=["blueprint_critic"])
        g.invoke(
            MathModelingState(problem="p", output_dir=str(out)),
            _config(),
        )
        assert g.get_state(_config()).next == ("blueprint_critic",)
    _write_manifest(out)

    result = _invoke_restart(out, monkeypatch)

    assert result.exit_code == 1
    assert "未处于停机态" in result.output


def test_restart_rejects_brief_mismatch(tmp_path, monkeypatch):
    """out/brief.json 与 manifest brief_sha256 不一致 -> 拒绝（输入已变只能全新 run）。"""
    out = tmp_path / "run"
    out.mkdir()
    calls = _install_fakes(monkeypatch, approve_on_consistency=lambda n: n >= 2)
    _run_to_gate_stop(out, calls)
    (out / "brief.json").write_text('{"changed": true}', encoding="utf-8")
    wrong_hash = hashlib.sha256(b"original brief").hexdigest()
    _write_manifest(out, brief_sha256=wrong_hash)

    result = _invoke_restart(out, monkeypatch)

    assert result.exit_code == 1
    assert "brief.json" in result.output
    assert calls["coder"] == 1, "拒绝后不得重执行任何节点"


def test_restart_rejects_missing_brief_copy(tmp_path, monkeypatch):
    """原 run 用了 brief 但 out/brief.json 缺失 -> 无法验证输入不变性，拒绝。"""
    out = tmp_path / "run"
    out.mkdir()
    calls = _install_fakes(monkeypatch, approve_on_consistency=lambda n: n >= 2)
    _run_to_gate_stop(out, calls)
    _write_manifest(out, brief_sha256=hashlib.sha256(b"brief").hexdigest())

    result = _invoke_restart(out, monkeypatch)

    assert result.exit_code == 1
    assert "brief" in result.output
    assert calls["coder"] == 1


def test_restart_rejects_other_from_node(tmp_path, monkeypatch):
    """--from 目前只接受 coder。"""
    out = tmp_path / "run"
    out.mkdir()
    (out / "checkpoints.sqlite").write_bytes(b"placeholder")

    result = _invoke_restart(out, monkeypatch, extra_args=["--from", "modeler"])

    assert result.exit_code != 0
