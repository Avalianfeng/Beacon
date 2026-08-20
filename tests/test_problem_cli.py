"""problem 命令组（import/show）与 run --dry-run 预检的测试（纯机械，不联网）。"""
import json

import pytest
from typer.testing import CliRunner

from math_agent.cli import app

runner = CliRunner()


def _write_spec(tmp_path, *, name="problem.json", blockers=None, data_files=None, data_dir=""):
    spec = {
        "title": "Test Problem",
        "background": "bg",
        "questions": ["Q1?", "Q2?"],
        "data_files": data_files or [],
        "data_dir": data_dir,
    }
    if blockers is not None:
        spec["feasibility"] = {"blockers": blockers, "checklist": [], "assessment": ""}
    path = tmp_path / name
    path.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# run --dry-run
# ---------------------------------------------------------------------------


def test_run_dry_run_ok_without_llm(tmp_path):
    problem = _write_spec(tmp_path)
    result = runner.invoke(app, [
        "run", "--problem", str(problem), "--out", str(tmp_path / "runs" / "x"), "--dry-run",
    ])
    assert result.exit_code == 0, result.output
    assert "[OK] 全部通过" in result.output


def test_run_dry_run_rejects_feasibility_blocker(tmp_path):
    problem = _write_spec(tmp_path, blockers=["需要真实仿真平台"])
    result = runner.invoke(app, [
        "run", "--problem", str(problem), "--out", str(tmp_path / "runs" / "x"), "--dry-run",
    ])
    assert result.exit_code == 1
    assert "feasibility.blockers 非空" in result.output


def test_run_dry_run_rejects_missing_attachment(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    problem = _write_spec(
        tmp_path,
        data_files=[{"filename": "att.xlsx", "file_type": "xlsx", "path": "att.xlsx", "summary": {}}],
        data_dir="data",
    )
    result = runner.invoke(app, [
        "run", "--problem", str(problem), "--out", str(tmp_path / "runs" / "x"), "--dry-run",
    ])
    assert result.exit_code == 1
    assert "附件缺失" in result.output


def test_run_dry_run_rejects_out_conflict(tmp_path):
    problem = _write_spec(tmp_path)
    out = tmp_path / "runs" / "existing"
    out.mkdir(parents=True)
    (out / "checkpoints.sqlite").write_bytes(b"x")
    result = runner.invoke(app, [
        "run", "--problem", str(problem), "--out", str(out), "--dry-run",
    ])
    assert result.exit_code == 1
    assert "已有 checkpoint" in result.output


def test_run_dry_run_accepts_out_with_force(tmp_path):
    problem = _write_spec(tmp_path)
    out = tmp_path / "runs" / "existing"
    out.mkdir(parents=True)
    (out / "checkpoints.sqlite").write_bytes(b"x")
    result = runner.invoke(app, [
        "run", "--problem", str(problem), "--out", str(out), "--dry-run", "--force",
    ])
    assert result.exit_code == 0, result.output


# ---------------------------------------------------------------------------
# problem import / show
# ---------------------------------------------------------------------------


def test_problem_import_creates_assets(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    src_md = tmp_path / "题面.md"
    src_md.write_text("# 题目\n\nQ1?", encoding="utf-8")
    att_dir = tmp_path / "att"
    att_dir.mkdir()
    (att_dir / "data.xlsx").write_bytes(b"PK\x03\x04fake")
    result = runner.invoke(app, [
        "problem", "import", str(src_md), "--problem-id", "t1", "--attachments", str(att_dir),
    ])
    assert result.exit_code == 0, result.output
    root = tmp_path / "problems" / "t1"
    assert (root / "problem.md").is_file()
    assert (root / "source" / "题面.md").is_file()
    assert (root / "source" / "data.xlsx").is_file()
    manifest = json.loads((root / "source" / "manifest.json").read_text(encoding="utf-8"))
    assert set(manifest) == {"题面.md", "data.xlsx"}
    assert len(manifest["题面.md"]) == 64
    spec = json.loads((root / "problem.json").read_text(encoding="utf-8"))
    assert spec["data_dir"] == "source"
    paths = {df["path"] for df in spec["data_files"]}
    assert paths == {"题面.md", "data.xlsx"}  # 相对 data_dir，不带前缀
    assert spec["feasibility"]["blockers"] == []


def test_problem_import_rejects_existing_without_force(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    src_md = tmp_path / "题面.md"
    src_md.write_text("# 题目", encoding="utf-8")
    first = runner.invoke(app, ["problem", "import", str(src_md), "--problem-id", "t2"])
    assert first.exit_code == 0, first.output
    second = runner.invoke(app, ["problem", "import", str(src_md), "--problem-id", "t2"])
    assert second.exit_code != 0
    assert "已存在" in second.output


def test_problem_import_parses_pdf_via_ingest_pipeline(tmp_path, monkeypatch, mocker):
    monkeypatch.chdir(tmp_path)
    fake_pdf = tmp_path / "题面.pdf"
    fake_pdf.write_bytes(b"%PDF-fake")
    parsed = mocker.Mock()
    parsed.text = "# 解析出的题目"
    mocker.patch("math_agent.problem_ingest.parse_problem_file", return_value=parsed)
    result = runner.invoke(app, ["problem", "import", str(fake_pdf), "--problem-id", "t3"])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "problems" / "t3" / "problem.md").read_text(encoding="utf-8") == "# 解析出的题目"


def test_problem_show_lists_brief_and_run(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    src_md = tmp_path / "题面.md"
    src_md.write_text("# 题目", encoding="utf-8")
    runner.invoke(app, ["problem", "import", str(src_md), "--problem-id", "t4"])
    (tmp_path / "problems" / "t4" / "brief.json").write_text(
        json.dumps({"schema_version": 1, "source": ["human"]}), encoding="utf-8",
    )
    result = runner.invoke(app, ["problem", "show", "t4"])
    assert result.exit_code == 0, result.output
    assert "brief" in result.output
    assert "最近 run" in result.output


def test_problem_show_missing_spec_fails(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["problem", "show", "nope"])
    assert result.exit_code != 0
    assert "不存在" in result.output
