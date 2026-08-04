"""观察面：日志增量、面板组装、progress 事件、非 TTY 降级。"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from math_agent.cli import app
from math_agent.progress import (
    append_progress,
    events_since_last_boundary,
    read_progress_events,
    reset_progress,
    summarize_progress,
)
from math_agent.supervisor import RunInspection
from math_agent.watch import (
    LogTailer,
    assemble_watch_view,
    build_next_hint,
    format_watch_text,
    resolve_mode,
    WatchView,
)

runner = CliRunner()


def test_watch_help_lists_mode_and_follow_exit():
    result = runner.invoke(app, ["watch", "--help"])
    assert result.exit_code == 0
    assert "--mode" in result.output
    assert "--follow-exit" in result.output
    assert "自动" in result.output or "auto" in result.output.lower()


def test_log_tailer_reads_appends_and_handles_truncation(tmp_path: Path):
    path = tmp_path / "supervisor.log"
    path.write_text("a\nb\n", encoding="utf-8")
    tailer = LogTailer(path)
    assert tailer.read_new_lines() == ["a", "b"]
    assert tailer.read_new_lines() == []

    with path.open("a", encoding="utf-8") as fh:
        fh.write("c\n")
    assert tailer.read_new_lines() == ["c"]

    path.write_text("fresh\n", encoding="utf-8")
    assert tailer.read_new_lines() == ["fresh"]


def test_progress_skips_bad_lines_and_respects_boundary(tmp_path: Path):
    reset_progress(tmp_path, epoch=1, attempt=1)
    append_progress(tmp_path, {"type": "node_start", "node": "analyst"})
    append_progress(tmp_path, {"type": "node_end", "node": "analyst", "duration_ms": 10})
    # 坏行
    (tmp_path / "progress.jsonl").open("a", encoding="utf-8").write("{not-json\n")
    append_progress(tmp_path, {"type": "run_boundary", "epoch": 2, "attempt": 3})
    append_progress(tmp_path, {"type": "node_start", "node": "writer_section"})
    append_progress(tmp_path, {
        "type": "llm_call", "model": "openai/x",
        "prompt_tokens": 100, "completion_tokens": 20, "latency_ms": 5,
    })

    events = read_progress_events(tmp_path)
    assert any(e.get("type") == "node_start" and e.get("node") == "analyst" for e in events)
    scoped = events_since_last_boundary(events)
    assert scoped[0]["type"] == "run_boundary"
    assert scoped[0]["epoch"] == 2
    summary = summarize_progress(events)
    assert summary.epoch == 2
    assert summary.attempt == 3
    assert summary.current_node == "writer_section"
    assert "analyst" not in summary.completed_nodes
    assert summary.llm_calls == 1
    assert summary.prompt_tokens == 100


def test_force_run_resets_progress_jsonl(tmp_path: Path):
    problem = tmp_path / "problem.json"
    problem.write_text(json.dumps({"title": "t", "questions": ["q"]}), encoding="utf-8")
    out = tmp_path / "run"
    out.mkdir()
    (out / "checkpoints.sqlite").write_bytes(b"old")
    reset_progress(out, epoch=1, attempt=1)
    append_progress(out, {"type": "node_start", "node": "old_node"})

    fake_graph = MagicMock()
    fake_graph.get_state.return_value = MagicMock(values={"problem": "p"})
    saver_cm = MagicMock()
    saver_cm.__enter__.return_value = object()
    saver_cm.__exit__.return_value = False
    with patch("math_agent.cli._saver_cm", return_value=saver_cm), \
         patch("math_agent.cli.build_graph", return_value=fake_graph), \
         patch("math_agent.cli._dump_state_summary"):
        result = runner.invoke(app, [
            "run", "--problem", str(problem), "--out", str(out),
            "--force", "--no-interrupt",
        ])

    assert result.exit_code == 0, result.output
    events = read_progress_events(out)
    assert events
    assert all(e.get("node") != "old_node" for e in events)
    assert any(e.get("type") == "run_boundary" for e in events)


def test_assemble_watch_view_waiting(tmp_path: Path):
    view = assemble_watch_view(tmp_path / "missing", "default")
    assert view.waiting
    assert "等待任务创建" in view.next_hint


def test_assemble_watch_view_paused_hint(tmp_path: Path):
    out = tmp_path / "run"
    out.mkdir()
    (out / "supervisor.json").write_text(json.dumps({
        "status": "paused",
        "supervisor_pid": None,
        "attempt": 1,
        "recoveries": 0,
        "heartbeat_at": "2026-08-04T00:00:00+00:00",
    }), encoding="utf-8")
    with patch(
        "math_agent.watch.inspect_checkpoint",
        return_value=RunInspection(True, next_node="human_review"),
    ), patch("math_agent.watch.load_verified_completion", return_value=None):
        view = assemble_watch_view(out, "default")
    assert view.status == "paused"
    assert "supervise-resume" in view.next_hint
    assert "--approve" in view.next_hint


def test_assemble_watch_view_blocked_hint(tmp_path: Path):
    out = tmp_path / "run"
    out.mkdir()
    (out / "supervisor.json").write_text(json.dumps({
        "status": "blocked",
        "message": "same node failed 3 times",
        "supervisor_pid": None,
    }), encoding="utf-8")
    (out / "failure.json").write_text(json.dumps({
        "node": "modeler",
        "kind": "LLMValidationError",
        "retriable": True,
        "message": (
            "1 validation error for ModelVersion   Invalid JSON: "
            "EOF while parsing a value at line 1 column 0 "
            "[type=json_invalid, input_value='', input_type=str]"
        ),
    }), encoding="utf-8")
    (out / ".recover_failed_node").write_text(
        json.dumps({"node": "modeler", "count": 3}), encoding="utf-8",
    )
    with patch(
        "math_agent.watch.inspect_checkpoint",
        return_value=RunInspection(True, next_node="modeler"),
    ), patch("math_agent.watch.load_verified_completion", return_value=None):
        view = assemble_watch_view(out, "default")
    assert view.status == "blocked"
    assert "不是 timeout" in view.next_hint or "空/非法 JSON" in view.next_hint
    assert "Remove-Item" in view.next_hint
    assert "supervise-recover" in view.next_hint
    assert "空转" in view.next_hint
    assert view.recover_marker_count == 3
    assert view.failure is not None
    assert view.failure.node == "modeler"


def test_stale_failure_hidden_after_node_succeeds(tmp_path: Path):
    out = tmp_path / "run"
    out.mkdir()
    (out / "supervisor.json").write_text(json.dumps({
        "status": "running",
        "supervisor_pid": None,
        "attempt": 2,
        "mode": "recover",
        "heartbeat_at": "2026-08-04T08:00:00+00:00",
    }), encoding="utf-8")
    (out / "failure.json").write_text(json.dumps({
        "node": "modeler",
        "kind": "LLMValidationError",
        "retriable": True,
        "message": "Invalid JSON: EOF",
    }), encoding="utf-8")
    (out / ".recover_failed_node").write_text(
        json.dumps({"node": "modeler", "count": 1}), encoding="utf-8",
    )
    from math_agent.progress import append_progress, reset_progress
    reset_progress(out, epoch=1, attempt=2)
    append_progress(out, {"type": "node_start", "node": "modeler"})
    append_progress(out, {"type": "error", "node": "modeler", "kind": "LLMValidationError",
                          "message": "Invalid JSON"})
    append_progress(out, {"type": "node_start", "node": "modeler"})
    append_progress(out, {"type": "node_end", "node": "modeler", "duration_ms": 100})
    append_progress(out, {"type": "node_start", "node": "model_critic"})
    with patch(
        "math_agent.watch.inspect_checkpoint",
        return_value=RunInspection(True, next_node="model_critic"),
    ), patch("math_agent.watch.load_verified_completion", return_value=None):
        view = assemble_watch_view(out, "default")
    assert view.status == "running"
    assert view.failure is None
    assert view.recover_marker_count == 0
    assert "modeler" in view.completed_nodes


def test_explain_failure_empty_llm_error():
    from math_agent.supervisor import FailureRecord
    from math_agent.watch import explain_failure
    text = explain_failure(FailureRecord(
        node="modeler", kind="LLMError", retriable=True, message="",
    ))
    assert "未留下错误正文" in text
    assert "modeler" in text


def test_explain_failure_json_empty():
    from math_agent.supervisor import FailureRecord
    from math_agent.watch import explain_failure
    text = explain_failure(FailureRecord(
        node="modeler",
        kind="LLMValidationError",
        retriable=True,
        message="Invalid JSON: EOF while parsing a value ... input_value=''",
    ))
    assert "不是 timeout" in text
    assert "modeler" in text


def test_assemble_uses_reconcile_and_verified_completion(tmp_path: Path):
    out = tmp_path / "run"
    out.mkdir()
    (out / "supervisor.json").write_text(json.dumps({
        "status": "running",
        "supervisor_pid": 1,
        "started_at": "2000-01-01T00:00:00+00:00",
        "heartbeat_at": "2000-01-01T00:00:00+00:00",
        "attempt": 2,
    }), encoding="utf-8")
    verified = MagicMock(status="completed")
    with patch(
        "math_agent.watch.inspect_checkpoint",
        return_value=RunInspection(True, final_status="completed"),
    ), patch("math_agent.watch.load_verified_completion", return_value=verified), \
         patch(
             "math_agent.watch.reconcile_supervisor_state",
             side_effect=lambda payload, **_: {**payload, "status": "stale",
                                               "stale_reason": "supervisor_pid_not_alive"},
         ):
        view = assemble_watch_view(out, "default")
    assert view.status == "stale"
    assert view.effective_status == "completed"
    assert "report" in view.next_hint or "completion" in view.next_hint


def test_resolve_mode_auto_non_tty():
    assert resolve_mode("auto", is_tty=False) == "log"
    assert resolve_mode("auto", is_tty=True) == "panel"
    assert resolve_mode("panel", is_tty=False) == "log"


def test_format_watch_text_mentions_quit():
    view = WatchView(out=Path("runs/x"), thread="default", status="running")
    text = format_watch_text(view)
    assert "does not kill task" in text or "quit" in text.lower()


def test_format_heartbeat_to_seconds_plus8():
    from math_agent.watch import format_heartbeat, format_ts_local
    # UTC 07:18:07 → +8 = 15:18:07
    assert format_heartbeat("2026-08-04T07:18:07.728802+00:00") == "2026-08-04 15:18:07"
    assert format_ts_local(1722754800.0).count(":") == 2
    assert format_heartbeat("") == "-"


def test_format_history_lines_include_local_time():
    from math_agent.watch import format_history_lines
    lines = format_history_lines([
        {"ts": 1722754800.0, "type": "run_boundary", "attempt": 1, "mode": "run"},
        {"ts": 1722754810.0, "type": "node_start", "node": "analyst", "stage": "basic"},
        {"ts": 1722754900.0, "type": "node_end", "node": "analyst", "duration_ms": 90000},
    ])
    assert len(lines) == 3
    assert "开始 analyst" in lines[1]
    assert "结束 analyst" in lines[2]
    assert lines[0][:4] == "2024" or lines[0][:4] == "2026" or ":" in lines[0]


def test_cycle_panel_view():
    from math_agent.watch import cycle_panel_view
    assert cycle_panel_view("overview") == "history"
    assert cycle_panel_view("history") == "log"
    assert cycle_panel_view("log") == "overview"


def test_append_supervisor_log(tmp_path: Path):
    from math_agent.progress import append_supervisor_log
    append_supervisor_log(tmp_path, "[pipeline] node: analyst")
    text = (tmp_path / "supervisor.log").read_text(encoding="utf-8")
    assert "[pipeline] node: analyst" in text
    # 带东八区时间前缀
    assert text.split(" ", 1)[0].count("-") == 2


def test_build_next_hint_running_empty():
    view = WatchView(out=Path("runs/x"), thread="default", status="running")
    assert build_next_hint(view) == ""
    view.locked = True
    assert build_next_hint(view) == ""


def test_start_prints_watch_hint(tmp_path: Path):
    problem = tmp_path / "problem.json"
    problem.write_text(json.dumps({"title": "t", "questions": ["q"]}), encoding="utf-8")
    out = tmp_path / "run"
    with patch("math_agent.cli.start_detached_supervisor", return_value=4242), \
         patch("math_agent.cli._validate_existing_run_manifest"):
        result = runner.invoke(app, [
            "start", "--problem", str(problem), "--out", str(out), "--no-interrupt",
        ])
    assert result.exit_code == 0, result.output
    assert "math-agent watch" in result.output
