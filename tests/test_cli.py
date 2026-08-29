import json
import os
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from math_agent.cli import app
from math_agent.run_lock import RunLock
from math_agent.supervisor import SupervisorResult


runner = CliRunner()


def _problem(tmp_path):
    path = tmp_path / "problem.json"
    path.write_text(json.dumps({"title": "t", "questions": ["q"]}), encoding="utf-8")
    return path


def test_run_help_exposes_only_meaningful_no_interrupt_flag():
    result = runner.invoke(app, ["run", "--help"])
    assert result.exit_code == 0
    assert "--no-interrupt" in result.output
    assert "--no-no-interrupt" not in result.output


def test_run_force_removes_existing_checkpoint_files(tmp_path):
    problem = _problem(tmp_path)
    out = tmp_path / "run"
    out.mkdir()
    checkpoint = out / "checkpoints.sqlite"
    checkpoint.write_bytes(b"old")
    (out / "checkpoints.sqlite-wal").write_bytes(b"old")
    (out / "checkpoints.sqlite-shm").write_bytes(b"old")

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
    assert not checkpoint.exists()
    assert not (out / "checkpoints.sqlite-wal").exists()
    assert not (out / "checkpoints.sqlite-shm").exists()
    initial = fake_graph.invoke.call_args.args[0]
    assert initial["human_decision"].approved is True
    manifest = json.loads((out / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["thread"] == "default"
    assert manifest["no_interrupt"] is True


def test_run_does_not_claim_pause_when_graph_already_ended(tmp_path):
    problem = _problem(tmp_path)
    out = tmp_path / "run"
    out.mkdir()
    fake_graph = MagicMock()
    fake_graph.get_state.return_value = MagicMock(values={"problem": "p"}, next=())
    saver_cm = MagicMock()
    saver_cm.__enter__.return_value = object()
    saver_cm.__exit__.return_value = False
    ended = MagicMock(checkpoint_exists=True, next_node="", final_status="")
    with patch("math_agent.cli._saver_cm", return_value=saver_cm), \
         patch("math_agent.cli.build_graph", return_value=fake_graph), \
         patch("math_agent.cli._dump_state_summary"), \
         patch("math_agent.cli.inspect_checkpoint", return_value=ended):
        result = runner.invoke(app, [
            "run", "--problem", str(problem), "--out", str(out),
        ])

    assert result.exit_code == 0, result.output
    assert "paused before human_review" not in result.output
    assert "stopped before human_review" in result.output


def test_run_without_force_preserves_existing_checkpoint(tmp_path):
    problem = _problem(tmp_path)
    out = tmp_path / "run"
    out.mkdir()
    checkpoint = out / "checkpoints.sqlite"
    checkpoint.write_bytes(b"old")

    result = runner.invoke(app, ["run", "--problem", str(problem), "--out", str(out)])

    assert result.exit_code == 1
    assert checkpoint.read_bytes() == b"old"
    assert "already has a checkpoint" in result.output


def test_run_force_cannot_delete_checkpoint_held_by_active_worker(tmp_path):
    problem = _problem(tmp_path)
    out = tmp_path / "run"
    out.mkdir()
    checkpoint = out / "checkpoints.sqlite"
    checkpoint.write_bytes(b"active")

    with RunLock(out):
        result = runner.invoke(app, [
            "run", "--problem", str(problem), "--out", str(out), "--force",
        ])

    assert result.exit_code == 75
    assert checkpoint.read_bytes() == b"active"


def test_supervise_delegates_to_process_supervisor(tmp_path):
    problem = _problem(tmp_path)
    out = tmp_path / "run"
    with patch(
        "math_agent.cli.run_process_supervisor",
        return_value=SupervisorResult(status="completed", attempts=2, recoveries=1),
    ) as supervised:
        result = runner.invoke(app, [
            "supervise", "--problem", str(problem), "--out", str(out),
            "--thread", "t1", "--no-interrupt",
        ])

    assert result.exit_code == 0, result.output
    kwargs = supervised.call_args.kwargs
    assert kwargs["thread"] == "t1"
    assert "--no-interrupt" in kwargs["run_args"]


def test_supervise_recover_starts_supervisor_from_existing_checkpoint(tmp_path):
    out = tmp_path / "run"
    out.mkdir()
    (out / "checkpoints.sqlite").write_bytes(b"checkpoint")

    with patch("math_agent.cli._require_trace_thread"), patch(
        "math_agent.cli.run_process_supervisor",
        return_value=SupervisorResult(status="completed", attempts=1),
    ) as supervised:
        result = runner.invoke(app, [
            "supervise-recover", "--out", str(out), "--thread", "recover-thread",
        ])

    assert result.exit_code == 0, result.output
    kwargs = supervised.call_args.kwargs
    assert kwargs["out"] == out.resolve()
    assert kwargs["thread"] == "recover-thread"
    assert kwargs["initial_mode"] == "recover"
    assert kwargs["persistent_recover_failures"] is True
    assert kwargs["persistent_recovery_budget"] is True


def test_supervise_returns_nonzero_for_degraded_completion(tmp_path):
    problem = _problem(tmp_path)
    with patch(
        "math_agent.cli.run_process_supervisor",
        return_value=SupervisorResult(status="degraded"),
    ):
        result = runner.invoke(app, ["supervise", "--problem", str(problem)])
    assert result.exit_code == 2
    assert "DEGRADED" in result.output


def test_supervise_refuses_checkpoint_for_different_problem(tmp_path):
    first = _problem(tmp_path)
    second = tmp_path / "other.json"
    second.write_text(json.dumps({"title": "other", "questions": ["different"]}), encoding="utf-8")
    out = tmp_path / "run"
    out.mkdir()
    (out / "checkpoints.sqlite").write_bytes(b"checkpoint")
    from math_agent.cli import _problem_fingerprint, _read_problem_spec
    (out / "run_manifest.json").write_text(json.dumps({
        "thread": "default",
        "problem_sha256": _problem_fingerprint(_read_problem_spec(first)),
    }), encoding="utf-8")

    with patch("math_agent.cli.run_process_supervisor") as supervised:
        result = runner.invoke(app, [
            "supervise", "--problem", str(second), "--out", str(out),
        ])

    assert result.exit_code != 0
    assert "另一道题" in result.output
    supervised.assert_not_called()


def test_start_launches_detached_supervisor(tmp_path):
    problem = _problem(tmp_path)
    out = tmp_path / "run"
    with patch("math_agent.cli.start_detached_supervisor", return_value=4321) as detached:
        result = runner.invoke(app, [
            "start", "--problem", str(problem), "--out", str(out), "--no-interrupt",
        ])
    assert result.exit_code == 0
    assert "4321" in result.output
    assert "--no-interrupt" in detached.call_args.kwargs["supervise_args"]


def test_status_reads_persisted_supervisor_and_completion(tmp_path):
    (tmp_path / "supervisor.json").write_text(
        json.dumps({"status": "running", "heartbeat_at": "now", "worker_pid": 7}),
        encoding="utf-8",
    )
    (tmp_path / "completion.json").write_text(
        json.dumps({"status": "completed"}), encoding="utf-8",
    )
    with patch("math_agent.cli.inspect_checkpoint") as inspect:
        inspect.return_value = MagicMock(
            checkpoint_exists=True, next_node="writer_section", final_status="",
        )
        result = runner.invoke(app, ["status", "--out", str(tmp_path)])
    assert result.exit_code == 0
    assert "writer_section" in result.output
    assert "running" in result.output
    assert "completed" in result.output


def test_status_marks_running_supervisor_with_dead_pid_as_stale(tmp_path):
    (tmp_path / "supervisor.json").write_text(
        json.dumps({
            "status": "running",
            "supervisor_pid": 99999999,
            "started_at": "2026-07-15T05:31:50+00:00",
            "heartbeat_at": "2026-07-15T05:35:56+00:00",
            "worker_pid": 99999998,
        }),
        encoding="utf-8",
    )
    with patch("math_agent.cli.inspect_checkpoint") as inspect:
        inspect.return_value = MagicMock(
            checkpoint_exists=True, next_node="coder_generate", final_status="pending",
        )
        result = runner.invoke(app, ["status", "--out", str(tmp_path)])

    assert result.exit_code == 0
    assert "supervisor_status: stale" in result.output
    assert "supervisor_pid_not_alive" in result.output


def test_status_marks_supervisor_superseded_by_verified_completion_as_stale(tmp_path):
    (tmp_path / "supervisor.json").write_text(
        json.dumps({"status": "degraded", "worker_pid": 99999998}),
        encoding="utf-8",
    )
    (tmp_path / "completion.json").write_text(
        json.dumps({"status": "completed"}), encoding="utf-8",
    )
    with (
        patch("math_agent.cli.inspect_checkpoint") as inspect,
        patch("math_agent.cli.load_verified_completion") as verified,
    ):
        inspect.return_value = MagicMock(
            checkpoint_exists=True, next_node="", final_status="completed",
        )
        verified.return_value = MagicMock(status="completed")
        result = runner.invoke(app, ["status", "--out", str(tmp_path)])

    assert result.exit_code == 0
    assert "supervisor_status: stale" in result.output
    assert "superseded_by_verified_completion:completed" in result.output
    assert "effective_status: completed" in result.output


def test_resume_and_recover_require_checkpoint(tmp_path):
    resume_result = runner.invoke(app, ["resume", "--out", str(tmp_path), "--approve"])
    recover_result = runner.invoke(app, ["recover", "--out", str(tmp_path)])
    assert resume_result.exit_code == 1
    assert recover_result.exit_code == 1
    assert "no checkpoint" in resume_result.output
    assert "no checkpoint" in recover_result.output
    assert not (tmp_path / "trace.json").exists()


def test_no_interrupt_recover_does_not_reroute_checkpoint_to_inject_decision(tmp_path):
    (tmp_path / "checkpoints.sqlite").write_bytes(b"checkpoint")
    fake_graph = MagicMock()
    fake_graph.get_state.return_value = MagicMock(
        values={"human_decision": None},
        next=("sensitivity_code_generate",),
    )

    def invoke_without_checkpoint_mutation(*_args, **_kwargs):
        assert os.environ["MATH_AGENT_AUTO_APPROVE_HUMAN_REVIEW"] == "1"

    fake_graph.invoke.side_effect = invoke_without_checkpoint_mutation
    saver_cm = MagicMock()
    saver_cm.__enter__.return_value = object()
    saver_cm.__exit__.return_value = False
    with patch("math_agent.cli._require_trace_thread"), \
         patch("math_agent.cli._saver_cm", return_value=saver_cm), \
         patch("math_agent.cli.build_graph", return_value=fake_graph), \
         patch("math_agent.cli._dump_state_summary"):
        result = runner.invoke(app, [
            "recover", "--out", str(tmp_path), "--no-interrupt",
        ])

    assert result.exit_code == 0, result.output
    fake_graph.update_state.assert_not_called()
    assert "MATH_AGENT_AUTO_APPROVE_HUMAN_REVIEW" not in os.environ


def test_resume_requires_explicit_human_decision(tmp_path):
    result = runner.invoke(app, ["resume", "--out", str(tmp_path)])
    assert result.exit_code != 0
    assert "--approve" in result.output


def test_run_force_does_not_destroy_checkpoint_for_invalid_problem(tmp_path):
    problem = tmp_path / "invalid.json"
    problem.write_text("{not json", encoding="utf-8")
    out = tmp_path / "run"
    out.mkdir()
    checkpoint = out / "checkpoints.sqlite"
    checkpoint.write_bytes(b"old")

    result = runner.invoke(app, [
        "run", "--problem", str(problem), "--out", str(out), "--force",
    ])

    assert result.exit_code != 0
    assert checkpoint.read_bytes() == b"old"


def test_run_rejects_invalid_problem_schema_and_template(tmp_path):
    wrong_questions = tmp_path / "wrong.json"
    wrong_questions.write_text(
        json.dumps({"title": "t", "questions": "not-a-list"}), encoding="utf-8",
    )
    bad_schema = runner.invoke(app, ["run", "--problem", str(wrong_questions)])
    assert bad_schema.exit_code != 0
    assert "questions" in bad_schema.output

    valid = _problem(tmp_path)
    bad_template = runner.invoke(app, [
        "run", "--problem", str(valid), "--template", "gmcn",
    ])
    assert bad_template.exit_code != 0
    assert "default" in bad_template.output


def test_resume_wrong_thread_preserves_existing_trace(tmp_path):
    out = tmp_path / "run"
    out.mkdir()
    (out / "checkpoints.sqlite").write_bytes(b"checkpoint")
    trace = {"thread_id": "t1", "llm_calls": 3}
    trace_path = out / "trace.json"
    trace_path.write_text(json.dumps(trace), encoding="utf-8")

    result = runner.invoke(app, [
        "resume", "--out", str(out), "--thread", "t2", "--approve",
    ])

    assert result.exit_code == 1
    assert "belongs to thread=t1" in result.output
    assert json.loads(trace_path.read_text(encoding="utf-8")) == trace


def test_run_passes_data_files_to_initial_state(tmp_path):
    problem = tmp_path / "problem.json"
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "orders.xlsx").write_bytes(b"fake")
    problem.write_text(json.dumps({
        "title": "t",
        "questions": ["q"],
        "data_dir": str(data_dir),
        "data_files": [
            {"filename": "orders.xlsx", "file_type": "xlsx", "path": "orders.xlsx",
             "summary": {"sheets": [{"name": "Sheet1", "rows": 10, "cols": 3}]}}
        ],
    }), encoding="utf-8")
    out = tmp_path / "run"
    out.mkdir()

    fake_graph = MagicMock()
    fake_graph.get_state.return_value = MagicMock(values={"problem": "p"})
    saver_cm = MagicMock()
    saver_cm.__enter__.return_value = object()
    saver_cm.__exit__.return_value = False
    with patch("math_agent.cli._saver_cm", return_value=saver_cm), \
         patch("math_agent.cli.build_graph", return_value=fake_graph), \
         patch("math_agent.cli._dump_state_summary"):
        result = runner.invoke(app, [
            "run", "--problem", str(problem), "--out", str(out), "--no-interrupt",
        ])

    assert result.exit_code == 0, result.output
    initial = fake_graph.invoke.call_args.args[0]
    assert initial["data_dir"] == str(data_dir)
    assert len(initial["data_files"]) == 1
    assert initial["data_files"][0].filename == "orders.xlsx"


def test_run_rejects_nonexistent_data_dir(tmp_path):
    problem = tmp_path / "problem.json"
    problem.write_text(json.dumps({
        "title": "t", "questions": ["q"],
        "data_dir": str(tmp_path / "nonexistent"),
    }), encoding="utf-8")
    out = tmp_path / "run"
    out.mkdir()
    result = runner.invoke(app, ["run", "--problem", str(problem), "--out", str(out), "--no-interrupt"])
    assert result.exit_code != 0
    assert "data_dir" in result.output


def test_review_rejects_when_paper_incomplete(tmp_path):
    """论文关键 section 为空时 review 必须拒绝，不能送半成品进人审。"""
    out = tmp_path / "run"
    out.mkdir()
    (out / "checkpoints.sqlite").write_bytes(b"x")
    (out / "trace.json").write_text(json.dumps({"thread_id": "default"}), encoding="utf-8")

    from math_agent.state import MathModelingState, CriticReport, CriticIssue
    state = MathModelingState(problem="p")
    state.paper.abstract = ""
    state.paper.model_section = ""
    state.paper.solution = ""
    state.paper.conclusion = ""

    fake_graph = MagicMock()
    fake_graph.get_state.return_value = MagicMock(values=state)
    saver_cm = MagicMock()
    saver_cm.__enter__.return_value = object()
    saver_cm.__exit__.return_value = False

    with patch("math_agent.cli._saver_cm", return_value=saver_cm), \
         patch("math_agent.cli.build_graph", return_value=fake_graph), \
         patch("math_agent.cli._require_checkpoint"), \
         patch("math_agent.cli._require_trace_thread"):
        result = runner.invoke(app, ["review", "--out", str(out)])

    assert result.exit_code == 1
    assert "论文关键 section 为空" in result.output
    fake_graph.invoke.assert_not_called()


def test_review_skips_when_paper_already_approved(tmp_path):
    """论文评审已通过时 review 提示跳过，不重复接管。"""
    out = tmp_path / "run"
    out.mkdir()
    (out / "checkpoints.sqlite").write_bytes(b"x")
    (out / "trace.json").write_text(json.dumps({"thread_id": "default"}), encoding="utf-8")

    from math_agent.state import MathModelingState, CriticReport, CriticIssue
    state = MathModelingState(problem="p")
    state.paper.abstract = "a"
    state.paper.model_section = "m"
    state.paper.solution = "s"
    state.paper.conclusion = "c"
    critic = CriticReport(target="paper", approved=True, score=9)
    state.critic_reports.append(critic)

    fake_graph = MagicMock()
    fake_graph.get_state.return_value = MagicMock(values=state)
    saver_cm = MagicMock()
    saver_cm.__enter__.return_value = object()
    saver_cm.__exit__.return_value = False

    with patch("math_agent.cli._saver_cm", return_value=saver_cm), \
         patch("math_agent.cli.build_graph", return_value=fake_graph), \
         patch("math_agent.cli._require_checkpoint"), \
         patch("math_agent.cli._require_trace_thread"):
        result = runner.invoke(app, ["review", "--out", str(out)])

    assert result.exit_code == 0
    assert "[SKIP]" in result.output
    fake_graph.invoke.assert_not_called()


def test_review_reroutes_stopped_run_to_human_review(tmp_path):
    """评审未过但论文完整：review 用 as_node=paper_critic 重新路由并 invoke。"""
    out = tmp_path / "run"
    out.mkdir()
    (out / "checkpoints.sqlite").write_bytes(b"x")
    (out / "trace.json").write_text(json.dumps({"thread_id": "default"}), encoding="utf-8")

    from math_agent.state import MathModelingState, CriticReport, CriticIssue
    state = MathModelingState(problem="p")
    state.paper.abstract = "a"
    state.paper.model_section = "m"
    state.paper.solution = "s"
    state.paper.conclusion = "c"
    state.writer_iteration = 3
    critic = CriticReport(target="paper", approved=False, score=6)
    state.critic_reports.append(critic)

    fake_graph = MagicMock()
    fake_graph.get_state.return_value = MagicMock(values=state)
    saver_cm = MagicMock()
    saver_cm.__enter__.return_value = object()
    saver_cm.__exit__.return_value = False

    with patch("math_agent.cli._saver_cm", return_value=saver_cm), \
         patch("math_agent.cli.build_graph", return_value=fake_graph), \
         patch("math_agent.cli._require_checkpoint"), \
         patch("math_agent.cli._require_trace_thread"), \
         patch("math_agent.cli._dump_state_summary"), \
         patch("math_agent.cli._echo_run_outcome"):
        result = runner.invoke(app, ["review", "--out", str(out)])

    assert result.exit_code == 0, result.output
    kwargs = fake_graph.update_state.call_args.kwargs
    assert kwargs["as_node"] == "paper_critic"
    fake_graph.invoke.assert_called_once()


# ---------------------------------------------------------------------------
# brief CLI 与 --brief 传参
# ---------------------------------------------------------------------------

_MINIMAL_BRIEF_JSON = (
    '{"schema_version":1,"per_question_direction":[{"id":"d1","direction":"x"}]}'
)


def test_run_brief_invalid_json_exits_nonzero(tmp_path):
    problem = _problem(tmp_path)
    bad_brief = tmp_path / "bad_brief.json"
    bad_brief.write_text("{not json", encoding="utf-8")
    result = runner.invoke(app, [
        "run", "--problem", str(problem), "--out", str(tmp_path / "run"),
        "--brief", str(bad_brief), "--no-interrupt",
    ])
    assert result.exit_code != 0


def test_supervise_passes_brief_to_run_args(tmp_path):
    problem = _problem(tmp_path)
    out = tmp_path / "run"
    brief_path = tmp_path / "brief.json"
    brief_path.write_text(_MINIMAL_BRIEF_JSON, encoding="utf-8")
    with patch(
        "math_agent.cli.run_process_supervisor",
        return_value=SupervisorResult(status="completed", attempts=1),
    ) as supervised:
        result = runner.invoke(app, [
            "supervise", "--problem", str(problem), "--out", str(out),
            "--brief", str(brief_path), "--no-interrupt",
        ])
    assert result.exit_code == 0, result.output
    run_args = supervised.call_args.kwargs["run_args"]
    assert "--brief" in run_args
    assert str(brief_path.resolve()) in run_args


def test_start_passes_brief_to_supervise_args(tmp_path):
    problem = _problem(tmp_path)
    out = tmp_path / "run"
    brief_path = tmp_path / "brief.json"
    brief_path.write_text(_MINIMAL_BRIEF_JSON, encoding="utf-8")
    with patch("math_agent.cli.start_detached_supervisor", return_value=4321) as detached:
        result = runner.invoke(app, [
            "start", "--problem", str(problem), "--out", str(out),
            "--brief", str(brief_path), "--no-interrupt",
        ])
    assert result.exit_code == 0, result.output
    supervise_args = detached.call_args.kwargs["supervise_args"]
    assert "--brief" in supervise_args
    assert str(brief_path.resolve()) in supervise_args


def test_brief_check_valid_exits_zero(tmp_path):
    brief_path = tmp_path / "brief.json"
    brief_path.write_text(_MINIMAL_BRIEF_JSON, encoding="utf-8")
    result = runner.invoke(app, ["brief", "check", "--brief", str(brief_path)])
    assert result.exit_code == 0, result.output
    assert "[OK]" in result.output


def test_brief_check_invalid_exits_nonzero(tmp_path):
    bad_path = tmp_path / "bad.json"
    bad_path.write_text("{bad", encoding="utf-8")
    result = runner.invoke(app, ["brief", "check", "--brief", str(bad_path)])
    assert result.exit_code != 0
    assert "[FAIL]" in result.output


def test_brief_init_generates_valid_template(tmp_path):
    problem = _problem(tmp_path)
    out = tmp_path / "brief.json"
    result = runner.invoke(app, [
        "brief", "init", "--problem", str(problem), "--out", str(out), "--force",
    ])
    assert result.exit_code == 0, result.output
    assert out.exists()
    check = runner.invoke(app, ["brief", "check", "--brief", str(out)])
    assert check.exit_code == 0, check.output
    assert "[OK]" in check.output

# ---------------------------------------------------------------------------
# 落盘链路：out/brief.json 副本 + run_manifest.brief_sha256
# ---------------------------------------------------------------------------

def test_copy_brief_and_write_manifest_roundtrip(tmp_path):
    """纯函数级：_copy_brief_to_out + _write_run_manifest 写副本与 brief_sha256。"""
    import hashlib

    from math_agent.cli import _copy_brief_to_out, _problem_fingerprint, _write_run_manifest

    out = tmp_path / "out"
    out.mkdir()
    brief_path = tmp_path / "brief.json"
    brief_path.write_text(_MINIMAL_BRIEF_JSON, encoding="utf-8")
    src_hash = hashlib.sha256(brief_path.read_bytes()).hexdigest()
    spec = {"title": "t", "questions": ["q"], "background": "",
            "data_files": [], "data_dir": ""}

    _copy_brief_to_out(out, brief_path)
    _write_run_manifest(out, "default", spec, no_interrupt=True, brief_sha256=src_hash)

    assert (out / "brief.json").read_bytes() == brief_path.read_bytes()
    manifest = json.loads((out / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["brief_sha256"] == src_hash
    assert manifest["thread"] == "default"
    assert manifest["no_interrupt"] is True
    assert manifest["problem_sha256"] == _problem_fingerprint(spec)


def test_copy_brief_to_out_same_path_early_returns(tmp_path):
    """源 == 目标（out/brief.json）时早退，不覆盖已有文件。"""
    from math_agent.cli import _copy_brief_to_out

    out = tmp_path / "out"
    out.mkdir()
    target = out / "brief.json"
    target.write_text('{"schema_version":1}', encoding="utf-8")
    _copy_brief_to_out(out, target)  # brief_path.resolve() == target.resolve()
    assert target.read_text(encoding="utf-8") == '{"schema_version":1}'


def test_run_writes_brief_copy_and_manifest_before_invoke(tmp_path):
    """run --brief：副本与 manifest 在 invoke 之前已写；initial.brief 是 ModelingBrief。"""
    import hashlib

    from math_agent.brief import ModelingBrief, brief_item_ids

    problem = _problem(tmp_path)
    out = tmp_path / "run"
    brief_path = tmp_path / "brief.json"
    brief_path.write_text(_MINIMAL_BRIEF_JSON, encoding="utf-8")
    src_hash = hashlib.sha256(brief_path.read_bytes()).hexdigest()

    fake_graph = MagicMock()
    fake_graph.get_state.return_value = MagicMock(values={"problem": "p"})

    def fake_invoke(initial, config=None):
        # invoke 被调用时副本与 manifest 必须已落盘（顺序断言）
        assert (out / "brief.json").read_bytes() == brief_path.read_bytes()
        manifest = json.loads((out / "run_manifest.json").read_text(encoding="utf-8"))
        assert manifest["brief_sha256"] == src_hash
        return {}

    fake_graph.invoke.side_effect = fake_invoke
    saver_cm = MagicMock()
    saver_cm.__enter__.return_value = object()
    saver_cm.__exit__.return_value = False
    with patch("math_agent.cli._saver_cm", return_value=saver_cm), \
         patch("math_agent.cli.build_graph", return_value=fake_graph), \
         patch("math_agent.cli._dump_state_summary"):
        result = runner.invoke(app, [
            "run", "--problem", str(problem), "--out", str(out),
            "--brief", str(brief_path), "--no-interrupt",
        ])

    assert result.exit_code == 0, result.output
    initial = fake_graph.invoke.call_args.args[0]
    assert isinstance(initial["brief"], ModelingBrief)
    assert brief_item_ids(initial["brief"]) == ["d1"]
    assert (out / "brief.json").read_bytes() == brief_path.read_bytes()
    manifest = json.loads((out / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["brief_sha256"] == src_hash
    assert manifest["thread"] == "default"


# ---- B04: brief.problem_id 与题目匹配规范化 ----

def test_brief_mismatch_warns_on_wrong_problem(capsys):
    from math_agent.cli import _warn_brief_problem_mismatch

    class _Brief:
        problem_id = "mcm52-a"

    _warn_brief_problem_mismatch(
        _Brief(), {"title": "2026 51MCM Problem A", "questions": ["问题1"]}
    )
    assert "[WARN]" in capsys.readouterr().err


def test_brief_mismatch_silent_on_normalized_match(capsys):
    """mcm51-a vs '2026 51MCM Problem A'：裸子串双向都不包含，规范化后必须静默。"""
    from math_agent.cli import _warn_brief_problem_mismatch

    class _Brief:
        problem_id = "mcm51-a"

    _warn_brief_problem_mismatch(
        _Brief(), {"title": "2026 51MCM Problem A", "questions": ["问题1"]}
    )
    assert capsys.readouterr().err == ""


def test_brief_mismatch_silent_on_empty_pid(capsys):
    from math_agent.cli import _warn_brief_problem_mismatch

    class _Brief:
        problem_id = ""

    _warn_brief_problem_mismatch(
        _Brief(), {"title": "2026 51MCM Problem A", "questions": []}
    )
    assert capsys.readouterr().err == ""


def test_brief_mismatch_silent_when_spec_problem_id_matches(capsys):
    """canonical id 一致即匹配：title 无阿拉伯数字 16 也不误报。"""
    from math_agent.cli import _warn_brief_problem_mismatch

    class _Brief:
        problem_id = "mathorcup16-c"

    _warn_brief_problem_mismatch(
        _Brief(),
        {
            "problem_id": "mathorcup16-c",
            "title": "2026年第十六届MathorCup数学应用挑战赛 C题：中老年人群高血脂症的风险预警",
            "questions": ["问题1：筛选指标"],
        },
    )
    assert capsys.readouterr().err == ""


def test_brief_mismatch_warns_mathorcup_without_spec_problem_id(capsys):
    """无 spec.problem_id 时仍走 token 检查：title 无阿拉伯数字 16 → WARN。"""
    from math_agent.cli import _warn_brief_problem_mismatch

    class _Brief:
        problem_id = "mathorcup16-c"

    _warn_brief_problem_mismatch(
        _Brief(),
        {
            "title": "2026年第十六届MathorCup数学应用挑战赛 C题：中老年人群高血脂症的风险预警",
            "questions": ["问题1：筛选指标"],
        },
    )
    assert "[WARN]" in capsys.readouterr().err


def test_root_help_lists_stage_markers():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0, result.output
    for marker in ("S0", "S3", "S5", "S6", "S7", "S8", "S9"):
        assert marker in result.output
    assert "review-check" in result.output
    assert "recertify" in result.output
    assert "accept" in result.output
    assert "supervise" in result.output


def test_review_check_cli_writes_report(tmp_path):
    from pathlib import Path

    fixtures = Path(__file__).parent / "fixtures" / "check_numbers"
    paper = fixtures / "paper_clean.md"
    evidence = fixtures / "evidence_a.txt"
    report = tmp_path / "review-report.json"
    result = runner.invoke(app, [
        "review-check",
        "--paper", str(paper),
        "--evidence", str(evidence),
        "--out", str(report),
        "--json",
    ])
    assert result.exit_code == 0, result.output
    assert report.is_file()
    payload = json.loads(report.read_text(encoding="utf-8"))
    names = {t["name"] for t in payload["tools"]}
    assert "check_paper_numbers" in names
    assert "check_l4_gates" in names
    assert "brief_sha256" not in payload


def test_brief_check_mcm51_c_v2_ok():
    result = runner.invoke(app, [
        "brief", "check", "--brief", "problems/mcm51-c/brief.json",
    ])
    assert result.exit_code == 0, result.output
    assert "schema_version=2" in result.output
    assert "redline_rules" in result.output


def test_review_check_cli_with_brief_records_sha256(tmp_path):
    from pathlib import Path
    import hashlib

    fixtures = Path(__file__).parent / "fixtures" / "check_numbers"
    paper = fixtures / "paper_clean.md"
    brief = Path("problems/mcm51-c/brief.json")
    report = tmp_path / "review-report.json"
    result = runner.invoke(app, [
        "review-check",
        "--paper", str(paper),
        "--evidence", str(fixtures / "evidence_a.txt"),
        "--brief", str(brief),
        "--out", str(report),
        "--json",
    ])
    assert result.exit_code == 0, result.output
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["brief_sha256"] == hashlib.sha256(brief.read_bytes()).hexdigest()
    names = {t["name"] for t in payload["tools"]}
    assert "check_redlines" in names
    assert "check_brief_claims" in names


def test_reference_verify_cli_ok_and_fail(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    pid = "v1"
    spec_dir = tmp_path / "problems" / pid
    spec_dir.mkdir(parents=True)
    spec = {
        "problem_id": pid,
        "title": "t",
        "background": "b",
        "questions": ["q"],
        "data_files": [],
        "data_dir": "",
    }
    spec_path = spec_dir / "problem.json"
    spec_path.write_text(json.dumps(spec), encoding="utf-8")
    ev_dir = tmp_path / "runs" / f"{pid}-reference"
    ev_dir.mkdir(parents=True)
    evidence = {
        "problem_id": pid,
        "entry": "reference/_entry.py",
        "result": {"ours": {"gain": 0.88}},
        "q_lines": [],
        "run": {"success": True, "elapsed_s": 1.0, "stdout_chars": 3},
    }
    ev_path = ev_dir / "evidence.json"
    ev_path.write_text(json.dumps(evidence), encoding="utf-8")
    pkg = tmp_path / "pkg.json"
    result = runner.invoke(app, [
        "reference", "verify",
        "--problem", str(spec_path),
        "--evidence", str(ev_path),
        "--out", str(pkg),
    ])
    assert result.exit_code == 0, result.output
    assert pkg.is_file()
    body = json.loads(pkg.read_text(encoding="utf-8"))
    assert body["version"] == 1
    assert all(c["pass"] for c in body["checks"])

    evidence["result"] = {"x": float("nan")}
    ev_path.write_text(json.dumps(evidence), encoding="utf-8")
    result_fail = runner.invoke(app, [
        "reference", "verify",
        "--problem", str(spec_path),
        "--evidence", str(ev_path),
        "--out", str(tmp_path / "pkg-fail.json"),
    ])
    assert result_fail.exit_code == 1


def _min_spec(tmp_path, pid="p2"):
    spec_dir = tmp_path / "problems" / pid
    spec_dir.mkdir(parents=True)
    spec = {
        "problem_id": pid,
        "title": "t",
        "background": "b",
        "questions": ["q"],
        "data_files": [],
        "data_dir": "",
    }
    spec_path = spec_dir / "problem.json"
    spec_path.write_text(json.dumps(spec), encoding="utf-8")
    return spec_dir, spec_path


def test_reference_paper_refuses_without_package(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    spec_dir, spec_path = _min_spec(tmp_path)
    evidence = tmp_path / "evidence.json"
    evidence.write_text("{}", encoding="utf-8")
    result = runner.invoke(app, [
        "reference", "paper",
        "--problem", str(spec_path),
        "--evidence", str(evidence),
    ])
    assert result.exit_code == 1
    assert "evidence-package" in result.output


def test_reference_tables_refuses_without_package(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    spec_dir, spec_path = _min_spec(tmp_path, pid="p2t")
    evidence = tmp_path / "evidence.json"
    evidence.write_text("{}", encoding="utf-8")
    result = runner.invoke(app, [
        "reference", "tables",
        "--problem", str(spec_path),
        "--evidence", str(evidence),
    ])
    assert result.exit_code == 1
    assert "evidence-package" in result.output


def test_reference_recertify_cli_writes_review(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    spec_dir, spec_path = _min_spec(tmp_path, pid="p2r")
    evidence = {
        "run": {"success": True},
        "result": {"ours": {"a": 1.0}},
        "q_lines": ["Q1: a=1"],
    }
    ev_path = spec_dir / "evidence.json"
    ev_path.write_text(json.dumps(evidence), encoding="utf-8")
    package = {
        "version": 1,
        "problem_id": "p2r",
        "solver": {"path": "s", "sha256": ""},
        "evidence_path": str(ev_path),
        "checks": [
            {"id": "run_success", "pass": True},
            {"id": "no_nan_inf", "pass": True},
            {"id": "has_result", "pass": True},
        ],
        "ok": True,
    }
    (spec_dir / "evidence-package.json").write_text(
        json.dumps(package), encoding="utf-8",
    )
    result = runner.invoke(app, [
        "reference", "recertify",
        "--problem", str(spec_path),
        "--evidence", str(ev_path),
        "--actor", "p2",
        "--notes", "cli",
    ])
    assert result.exit_code == 0, result.output
    dest = spec_dir / "independent-review.json"
    assert dest.is_file()
    body = json.loads(dest.read_text(encoding="utf-8"))
    assert body["verdict"] == "pass"
    assert body["actor"] == "p2"


def test_accept_cli_requires_explicit_flag(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    spec_dir, spec_path = _min_spec(tmp_path, pid="p2a")
    paper = spec_dir / "paper.md"
    paper.write_text("# p\n", encoding="utf-8")
    missing = runner.invoke(app, [
        "accept",
        "--problem", str(spec_path),
        "--paper", str(paper),
    ])
    assert missing.exit_code != 0

    approved = runner.invoke(app, [
        "accept",
        "--problem", str(spec_path),
        "--paper", str(paper),
        "--approve",
        "--actor", "p2",
    ])
    assert approved.exit_code == 0, approved.output
    body = json.loads((spec_dir / "acceptance.json").read_text(encoding="utf-8"))
    assert body["approved"] is True

    rejected = runner.invoke(app, [
        "accept",
        "--problem", str(spec_path),
        "--paper", str(paper),
        "--no-approve",
        "--actor", "p2",
    ])
    assert rejected.exit_code == 1
    body = json.loads((spec_dir / "acceptance.json").read_text(encoding="utf-8"))
    assert body["approved"] is False


def test_reference_add_same_dir_registers_without_deleting(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    spec_dir, spec_path = _min_spec(tmp_path, pid="same1")
    ref = spec_dir / "source" / "reference"
    ref.mkdir(parents=True)
    (ref / "_entry.py").write_text("print('ok')\n", encoding="utf-8")
    (ref / "q1.py").write_text("x = 1\n", encoding="utf-8")
    result = runner.invoke(app, [
        "reference", "add",
        "--problem", str(spec_path),
        "--solver", str(ref),
        "--entry", "_entry.py",
    ])
    assert result.exit_code == 0, result.output
    assert (ref / "_entry.py").is_file()
    assert (ref / "q1.py").is_file()
    meta = json.loads((spec_dir / "reference.json").read_text(encoding="utf-8"))
    assert meta["entry"] == "_entry.py"
    assert len(meta["files"]) == 2
