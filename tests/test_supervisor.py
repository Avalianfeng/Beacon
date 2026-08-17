import json
import os
import sys
import time

import pytest

from math_agent.errors import LLMEmptyContentError, LLMValidationError
from math_agent.supervisor import (
    FailureRecord,
    RunInspection,
    SupervisorPolicy,
    WorkerResult,
    run_process_supervisor,
    supervise_loop,
    start_detached_supervisor,
    _atomic_json,
    _merge_gate_diagnostics,
    _process_worker,
    failure_record_for_exception,
)


def test_merge_gate_diagnostics_into_state(tmp_path):
    """心跳合并：gate_diagnostics.json 存在时进入 state["gate"]，删除后移除。"""
    (tmp_path / "gate_diagnostics.json").write_text(
        json.dumps({"code_verify_iteration": 5, "stall": True}),
        encoding="utf-8",
    )
    state: dict = {}
    _merge_gate_diagnostics(state, tmp_path)
    assert state["gate"]["code_verify_iteration"] == 5
    assert state["gate"]["stall"] is True

    (tmp_path / "gate_diagnostics.json").unlink()
    _merge_gate_diagnostics(state, tmp_path)
    assert "gate" not in state


def test_merge_gate_diagnostics_ignores_bad_payload(tmp_path):
    (tmp_path / "gate_diagnostics.json").write_text("{not-json", encoding="utf-8")
    state: dict = {"gate": {"old": 1}}
    _merge_gate_diagnostics(state, tmp_path)
    assert "gate" not in state


def test_supervisor_recovers_retriable_502_then_completes():
    calls = []
    worker_results = iter([
        WorkerResult(1, FailureRecord(node="writer_section", kind="server", retriable=True,
                                      message="502")),
        WorkerResult(0),
    ])
    inspections = iter([
        RunInspection(checkpoint_exists=False),
        RunInspection(checkpoint_exists=True, next_node="writer_section"),
        RunInspection(checkpoint_exists=True, final_status="completed"),
    ])

    result = supervise_loop(
        worker=lambda mode: calls.append(mode) or next(worker_results),
        inspect=lambda: next(inspections),
        policy=SupervisorPolicy(base_delay=0),
        sleep=lambda _: None,
    )

    assert result.status == "completed"
    assert calls == ["run", "recover"]
    assert result.attempts == 2


def test_supervisor_stops_after_same_node_fails_three_times():
    calls = []
    inspections = iter([
        RunInspection(checkpoint_exists=False),
        RunInspection(checkpoint_exists=True, next_node="sensitivity_interpret"),
        RunInspection(checkpoint_exists=True, next_node="sensitivity_interpret"),
        RunInspection(checkpoint_exists=True, next_node="sensitivity_interpret"),
    ])

    result = supervise_loop(
        worker=lambda mode: calls.append(mode) or WorkerResult(
            1, FailureRecord(node="sensitivity_interpret", kind="timeout", retriable=True,
                             message="timeout")
        ),
        inspect=lambda: next(inspections),
        policy=SupervisorPolicy(same_node_limit=3, max_recoveries=20, base_delay=0),
        sleep=lambda _: None,
    )

    assert result.status == "blocked"
    assert result.same_node_failures == 3
    assert calls == ["run", "recover", "recover"]


def test_supervisor_does_not_retry_non_retriable_configuration_error():
    calls = []
    inspections = iter([
        RunInspection(checkpoint_exists=False),
        RunInspection(checkpoint_exists=True, next_node="analyst"),
    ])

    result = supervise_loop(
        worker=lambda mode: calls.append(mode) or WorkerResult(
            1, FailureRecord(node="analyst", kind="authentication", retriable=False,
                             message="401")
        ),
        inspect=lambda: next(inspections),
        policy=SupervisorPolicy(base_delay=0),
        sleep=lambda _: None,
    )

    assert result.status == "blocked"
    assert calls == ["run"]


def test_supervisor_treats_abrupt_worker_death_as_recoverable_interruption():
    calls = []
    worker_results = iter([WorkerResult(-9), WorkerResult(0)])
    inspections = iter([
        RunInspection(checkpoint_exists=False),
        RunInspection(checkpoint_exists=True, next_node="coder_execute"),
        RunInspection(checkpoint_exists=True, final_status="completed"),
    ])

    result = supervise_loop(
        worker=lambda mode: calls.append(mode) or next(worker_results),
        inspect=lambda: next(inspections),
        policy=SupervisorPolicy(base_delay=0),
        sleep=lambda _: None,
    )

    assert result.status == "completed"
    assert calls == ["run", "recover"]


def test_supervisor_returns_paused_without_spawning_worker():
    calls = []
    result = supervise_loop(
        worker=lambda mode: calls.append(mode) or WorkerResult(0),
        inspect=lambda: RunInspection(checkpoint_exists=True, next_node="human_review"),
        policy=SupervisorPolicy(base_delay=0),
        sleep=lambda _: None,
    )
    assert result.status == "paused"
    assert calls == []


def test_supervisor_auto_approve_continues_from_human_review():
    calls = []
    inspections = iter([
        RunInspection(checkpoint_exists=True, next_node="human_review"),
        RunInspection(checkpoint_exists=True, final_status="completed"),
    ])
    result = supervise_loop(
        worker=lambda mode: calls.append(mode) or WorkerResult(0),
        inspect=lambda: next(inspections),
        policy=SupervisorPolicy(base_delay=0, auto_approve=True),
        sleep=lambda _: None,
    )
    assert result.status == "completed"
    assert calls == ["recover"]


def test_supervisor_reports_degraded_terminal_state():
    result = supervise_loop(
        worker=lambda mode: WorkerResult(0),
        inspect=lambda: RunInspection(checkpoint_exists=True, final_status="degraded"),
        policy=SupervisorPolicy(base_delay=0),
        sleep=lambda _: None,
    )
    assert result.status == "degraded"


def test_supervisor_treats_empty_next_as_stopped_without_recover():
    calls = []
    inspections = iter([
        RunInspection(checkpoint_exists=False),
        RunInspection(checkpoint_exists=True),
    ])

    result = supervise_loop(
        worker=lambda mode: calls.append(mode) or WorkerResult(0),
        inspect=lambda: next(inspections),
        policy=SupervisorPolicy(base_delay=0),
        sleep=lambda _: None,
    )

    assert result.status == "stopped"
    assert calls == ["run"]


def test_detached_supervisor_redirects_logs_and_records_pid(mocker, tmp_path):
    proc = mocker.MagicMock(pid=4321)
    popen = mocker.patch("math_agent.supervisor.subprocess.Popen", return_value=proc)

    pid = start_detached_supervisor(
        out=tmp_path, supervise_args=["--problem", "problem.json", "--no-interrupt"],
        cwd=tmp_path,
    )

    assert pid == 4321
    command = popen.call_args.args[0]
    assert command[-3:] == ["--problem", "problem.json", "--no-interrupt"]
    assert popen.call_args.kwargs["env"]["PYTHONIOENCODING"] == "utf-8"
    assert (tmp_path / "launcher.json").exists()


def test_process_worker_returns_immediately_when_child_finishes(tmp_path):
    state = {"attempt": 1}
    started = time.monotonic()
    result = _process_worker(
        mode="run",
        command=[sys.executable, "-c", "raise SystemExit(0)"],
        out=tmp_path,
        state=state,
        heartbeat_seconds=2.0,
    )
    elapsed = time.monotonic() - started
    assert result.returncode == 0
    assert elapsed < 1.5


def test_process_worker_marks_child_as_supervised(tmp_path):
    result = _process_worker(
        mode="recover",
        command=[
            sys.executable,
            "-c",
            "import os; raise SystemExit(0 if os.getenv('MATH_AGENT_SUPERVISED') == '1' else 9)",
        ],
        out=tmp_path,
        state={"attempt": 1},
        heartbeat_seconds=0.1,
    )

    assert result.returncode == 0


def test_process_worker_can_preserve_manual_recover_failure_counter(tmp_path, monkeypatch):
    monkeypatch.setenv("MATH_AGENT_SUPERVISED", "1")
    result = _process_worker(
        mode="recover",
        command=[
            sys.executable,
            "-c",
            "import os; raise SystemExit(9 if os.getenv('MATH_AGENT_SUPERVISED') else 0)",
        ],
        out=tmp_path,
        state={"attempt": 1},
        heartbeat_seconds=0.1,
        supervised=False,
    )

    assert result.returncode == 0


def test_process_worker_persists_recovery_budget_in_heartbeat_state(tmp_path):
    result = _process_worker(
        mode="recover",
        command=[sys.executable, "-c", "raise SystemExit(0)"],
        out=tmp_path,
        state={"attempt": 4, "recoveries": 3},
        heartbeat_seconds=0.1,
        supervised=False,
    )

    persisted = json.loads((tmp_path / "supervisor.json").read_text(encoding="utf-8"))
    assert result.returncode == 0
    assert persisted["recoveries"] == 3


def test_persistent_recovery_budget_blocks_before_starting_another_worker(mocker, tmp_path):
    (tmp_path / "supervisor.json").write_text(
        '{"attempt": 21, "recoveries": 20}',
        encoding="utf-8",
    )
    process_worker = mocker.patch("math_agent.supervisor._process_worker")
    mocker.patch(
        "math_agent.supervisor.inspect_checkpoint",
        return_value=RunInspection(checkpoint_exists=True, next_node="writer_section"),
    )

    result = run_process_supervisor(
        out=tmp_path,
        thread="default",
        initial_mode="recover",
        policy=SupervisorPolicy(max_recoveries=20, base_delay=0),
        persistent_recovery_budget=True,
    )

    assert result.status == "blocked"
    assert result.attempts == 21
    assert result.recoveries == 20
    assert result.message == "recovery budget exhausted (20)"
    process_worker.assert_not_called()


def test_persistent_recovery_budget_is_reserved_before_manual_worker_starts(
    mocker, tmp_path,
):
    (tmp_path / "supervisor.json").write_text(
        '{"attempt": 3, "recoveries": 2}',
        encoding="utf-8",
    )
    mocker.patch(
        "math_agent.supervisor.inspect_checkpoint",
        return_value=RunInspection(checkpoint_exists=True, next_node="writer_section"),
    )
    process_worker = mocker.patch(
        "math_agent.supervisor._process_worker",
        side_effect=KeyboardInterrupt(),
    )

    with pytest.raises(KeyboardInterrupt):
        run_process_supervisor(
            out=tmp_path,
            thread="default",
            initial_mode="recover",
            policy=SupervisorPolicy(max_recoveries=20, base_delay=0),
            persistent_recovery_budget=True,
        )

    state = process_worker.call_args.kwargs["state"]
    assert state["attempt"] == 4
    assert state["recoveries"] == 3


def test_failure_record_marks_validation_error_retriable():
    record = failure_record_for_exception("analyst", LLMValidationError("bad json"))
    assert record.retriable is True
    assert record.node == "analyst"


def test_failure_record_marks_empty_content_retriable():
    record = failure_record_for_exception(
        "modeler", LLMEmptyContentError("LLM 返回空 content，无法解析结构化 JSON"),
    )
    assert record.retriable is True
    assert record.kind == "LLMEmptyContentError"
    assert record.node == "modeler"


def test_atomic_json_retries_windows_replace_permission(monkeypatch, tmp_path):
    target = tmp_path / "supervisor.json"
    calls = {"n": 0}
    original = os.replace

    def flaky_replace(src, dst):
        calls["n"] += 1
        if calls["n"] < 3:
            raise PermissionError(5, "拒绝访问。")
        return original(src, dst)

    monkeypatch.setattr("math_agent.supervisor.os.replace", flaky_replace)
    monkeypatch.setattr("math_agent.supervisor.time.sleep", lambda _: None)
    _atomic_json(target, {"status": "running"})
    assert json.loads(target.read_text(encoding="utf-8"))["status"] == "running"
    assert calls["n"] == 3
