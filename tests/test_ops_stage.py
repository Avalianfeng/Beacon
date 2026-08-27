"""ops_stage：从磁盘工件推断问题阶段。"""
from __future__ import annotations

from pathlib import Path

import pytest

from math_agent.ops_stage import infer_stage, format_stage_text


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


def test_s0_through_s3_no_preflight(tmp_path: Path):
    (tmp_path / "problem.json").write_text("{}", encoding="utf-8")
    (tmp_path / "data_profile.md").write_text("# profile", encoding="utf-8")
    (tmp_path / "exploration.md").write_text("# explore", encoding="utf-8")
    (tmp_path / "brief.json").write_text("{}", encoding="utf-8")
    result = infer_stage(tmp_path)
    assert result["completed"] == ["S0", "S1", "S2", "S3"]
    assert result["next"] == "S4"
    assert "preflight.json" in result["missing"]


def test_skip_ahead_brief_without_data_profile(tmp_path: Path):
    (tmp_path / "problem.json").write_text("{}", encoding="utf-8")
    (tmp_path / "brief.json").write_text("{}", encoding="utf-8")
    result = infer_stage(tmp_path)
    assert result["completed"] == ["S0"]
    assert result["next"] == "S1"
    assert "S3" not in result["completed"]


def test_s5_via_source_reference_dir(tmp_path: Path):
    (tmp_path / "problem.json").write_text("{}", encoding="utf-8")
    (tmp_path / "data_profile.md").write_text("#", encoding="utf-8")
    (tmp_path / "exploration.md").write_text("#", encoding="utf-8")
    (tmp_path / "brief.json").write_text("{}", encoding="utf-8")
    (tmp_path / "preflight.json").write_text("{}", encoding="utf-8")
    (tmp_path / "source" / "reference").mkdir(parents=True)
    result = infer_stage(tmp_path)
    assert "S5" in result["completed"]
    assert result["next"] == "S6"


def test_s5_via_evidence_package_without_reference_dir(tmp_path: Path):
    (tmp_path / "problem.json").write_text("{}", encoding="utf-8")
    (tmp_path / "data_profile.md").write_text("#", encoding="utf-8")
    (tmp_path / "exploration.md").write_text("#", encoding="utf-8")
    (tmp_path / "brief.json").write_text("{}", encoding="utf-8")
    (tmp_path / "preflight.json").write_text("{}", encoding="utf-8")
    (tmp_path / "evidence-package.json").write_text("{}", encoding="utf-8")
    result = infer_stage(tmp_path)
    assert "S5" in result["completed"]
    assert result["next"] == "S6"


def test_s8_runs_root_with_paper_md(tmp_path: Path):
    problem = tmp_path / "prob"
    problem.mkdir()
    for name in (
        "problem.json",
        "data_profile.md",
        "exploration.md",
        "brief.json",
        "preflight.json",
        "reference.json",
        "review-report.json",
    ):
        (problem / name).write_text("{}", encoding="utf-8")
    (problem / "source" / "reference").mkdir(parents=True)
    runs = tmp_path / "runs"
    run_dir = runs / "attempt-1"
    run_dir.mkdir(parents=True)
    (run_dir / "paper.md").write_text("# paper", encoding="utf-8")
    result = infer_stage(problem, runs_root=runs)
    assert result["completed"] == [
        "S0", "S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8",
    ]
    assert result["next"] is None


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
    result = infer_stage(tmp_path)
    text = format_stage_text(result)
    assert "completed" in text
    assert "next" in text
    assert "missing" in text


@pytest.mark.skipif(
    not Path("problems/mcm51-c").is_dir(),
    reason="problems/mcm51-c not present",
)
def test_real_repo_mcm51_c_stages():
    problem = Path("problems/mcm51-c")
    result = infer_stage(problem)
    for stage in ("S0", "S1", "S2", "S3"):
        assert stage in result["completed"]
