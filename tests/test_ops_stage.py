"""ops_stage：从磁盘工件推断问题阶段。"""
from __future__ import annotations

from pathlib import Path

import pytest

from math_agent.ops_stage import infer_stage, format_stage_text


def _write_s0_s4(problem: Path) -> None:
    (problem / "problem.json").write_text("{}", encoding="utf-8")
    (problem / "data_profile.md").write_text("#", encoding="utf-8")
    (problem / "exploration.md").write_text("#", encoding="utf-8")
    (problem / "brief.json").write_text("{}", encoding="utf-8")
    (problem / "preflight.json").write_text("{}", encoding="utf-8")


def _write_s5_pass(problem: Path) -> None:
    (problem / "evidence-package.json").write_text("{}", encoding="utf-8")
    (problem / "independent-review.json").write_text(
        '{"verdict": "pass"}', encoding="utf-8"
    )


def test_empty_dir_next_s0(tmp_path: Path):
    result = infer_stage(tmp_path)
    assert result["problem_id"] == tmp_path.name
    assert result["completed"] == []
    assert result["next"] == "S0"
    assert "problem.json" in result["missing"]


def test_only_problem_json(tmp_path: Path):
    (tmp_path / "problem.json").write_text("{}", encoding="utf-8")
    result = infer_stage(tmp_path)
    assert result["completed"] == ["S0"]
    assert result["next"] == "S1"
    assert "data_profile.md" in result["missing"]
    assert result["next_command"] is None


def test_s0_through_s3_no_preflight(tmp_path: Path):
    (tmp_path / "problem.json").write_text("{}", encoding="utf-8")
    (tmp_path / "data_profile.md").write_text("# profile", encoding="utf-8")
    (tmp_path / "exploration.md").write_text("# explore", encoding="utf-8")
    (tmp_path / "brief.json").write_text("{}", encoding="utf-8")
    result = infer_stage(tmp_path)
    assert result["completed"] == ["S0", "S1", "S2", "S3"]
    assert result["next"] == "S4"
    assert "preflight.json" in result["missing"]
    assert "math-agent run" in result["next_command"]


def test_skip_ahead_brief_without_data_profile(tmp_path: Path):
    (tmp_path / "problem.json").write_text("{}", encoding="utf-8")
    (tmp_path / "brief.json").write_text("{}", encoding="utf-8")
    result = infer_stage(tmp_path)
    assert result["completed"] == ["S0"]
    assert result["next"] == "S1"
    assert "S3" not in result["completed"]


def test_s5_via_source_reference_dir(tmp_path: Path):
    _write_s0_s4(tmp_path)
    (tmp_path / "source" / "reference").mkdir(parents=True)
    result = infer_stage(tmp_path)
    assert "S5" not in result["completed"]
    assert result["next"] == "S5"
    assert "evidence-package.json" in result["missing"]
    assert "independent-review.json" in result["missing"]


def test_s5_via_evidence_package_without_reference_dir(tmp_path: Path):
    _write_s0_s4(tmp_path)
    (tmp_path / "evidence-package.json").write_text("{}", encoding="utf-8")
    result = infer_stage(tmp_path)
    assert "S5" not in result["completed"]
    assert result["next"] == "S5"
    assert "independent-review.json" in result["missing"]
    assert "math-agent reference recertify" in result["next_command"]


def test_s5_complete_with_package_and_review_pass(tmp_path: Path):
    _write_s0_s4(tmp_path)
    _write_s5_pass(tmp_path)
    result = infer_stage(tmp_path)
    assert "S5" in result["completed"]
    assert result["next"] == "S6"
    assert "math-agent reference paper" in result["next_command"]


def test_s5_not_complete_when_verdict_fail(tmp_path: Path):
    _write_s0_s4(tmp_path)
    (tmp_path / "evidence-package.json").write_text("{}", encoding="utf-8")
    (tmp_path / "independent-review.json").write_text(
        '{"verdict": "fail"}', encoding="utf-8"
    )
    result = infer_stage(tmp_path)
    assert "S5" not in result["completed"]
    assert result["next"] == "S5"
    assert "independent-review.json" in result["missing"]


def test_s8_complete_via_acceptance_json(tmp_path: Path):
    problem = tmp_path / "prob"
    problem.mkdir()
    _write_s0_s4(problem)
    _write_s5_pass(problem)
    (problem / "reference.json").write_text("{}", encoding="utf-8")
    (problem / "review-report.json").write_text("{}", encoding="utf-8")
    (problem / "acceptance.json").write_text(
        '{"approved": true}', encoding="utf-8"
    )
    runs = tmp_path / "runs"
    run_dir = runs / "attempt-1"
    run_dir.mkdir(parents=True)
    (run_dir / "paper.md").write_text("# paper", encoding="utf-8")
    result = infer_stage(problem, runs_root=runs)
    assert result["completed"] == [
        "S0", "S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8",
    ]
    assert result["next"] is None
    assert result["next_command"] is None


def test_s8_not_complete_without_acceptance_even_with_paper_md(tmp_path: Path):
    problem = tmp_path / "prob"
    problem.mkdir()
    _write_s0_s4(problem)
    _write_s5_pass(problem)
    (problem / "reference.json").write_text("{}", encoding="utf-8")
    (problem / "review-report.json").write_text("{}", encoding="utf-8")
    runs = tmp_path / "runs"
    run_dir = runs / "attempt-1"
    run_dir.mkdir(parents=True)
    (run_dir / "paper.md").write_text("# paper", encoding="utf-8")
    result = infer_stage(problem, runs_root=runs)
    assert "S8" not in result["completed"]
    assert result["next"] == "S8"
    assert "acceptance.json" in result["missing"]


def test_s8_not_complete_when_approved_false(tmp_path: Path):
    problem = tmp_path / "prob"
    problem.mkdir()
    _write_s0_s4(problem)
    _write_s5_pass(problem)
    (problem / "reference.json").write_text("{}", encoding="utf-8")
    (problem / "review-report.json").write_text("{}", encoding="utf-8")
    (problem / "acceptance.json").write_text(
        '{"approved": false}', encoding="utf-8"
    )
    result = infer_stage(problem)
    assert "S8" not in result["completed"]
    assert result["next"] == "S8"
    assert "acceptance.json" in result["missing"]


def test_s9_optional_checkpoints_does_not_change_next(tmp_path: Path):
    (tmp_path / "problem.json").write_text("{}", encoding="utf-8")
    runs = tmp_path / "runs"
    ckpt_dir = runs / "sub" / "nested"
    ckpt_dir.mkdir(parents=True)
    (ckpt_dir / "checkpoints.sqlite").write_bytes(b"")
    result = infer_stage(tmp_path, runs_root=runs)
    assert result["next"] == "S1"
    assert "S9" in result["optional"]


def test_format_stage_text_includes_fields(tmp_path: Path):
    (tmp_path / "problem.json").write_text("{}", encoding="utf-8")
    (tmp_path / "data_profile.md").write_text("#", encoding="utf-8")
    (tmp_path / "exploration.md").write_text("#", encoding="utf-8")
    (tmp_path / "brief.json").write_text("{}", encoding="utf-8")
    result = infer_stage(tmp_path)
    text = format_stage_text(result)
    assert "completed" in text
    assert "next" in text
    assert "missing" in text
    assert "next_command:" in text
    assert "math-agent run" in text


def test_format_stage_text_no_next_command_line_when_none(tmp_path: Path):
    (tmp_path / "problem.json").write_text("{}", encoding="utf-8")
    result = infer_stage(tmp_path)
    text = format_stage_text(result)
    assert "next_command:" not in text


@pytest.mark.skipif(
    not Path("problems/mcm51-c").is_dir(),
    reason="problems/mcm51-c not present",
)
def test_real_repo_mcm51_c_stages():
    problem = Path("problems/mcm51-c")
    result = infer_stage(problem)
    for stage in ("S0", "S1", "S2", "S3"):
        assert stage in result["completed"]
    # P2 走通后该题可已越过 S4；前缀 S0–S3 仍必须成立。
