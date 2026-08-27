"""ops_preflight.run_preflight / write_preflight_json 单元测试。"""
import json

from math_agent.ops_preflight import run_preflight, write_preflight_json


def _write_problem(tmp_path, *, blockers=None, extra=None):
    spec = {
        "title": "Test Problem",
        "background": "bg",
        "questions": ["Q1?"],
        "data_files": [],
        "data_dir": "",
    }
    if blockers is not None:
        spec["feasibility"] = {"blockers": blockers, "checklist": [], "assessment": ""}
    if extra:
        spec.update(extra)
    path = tmp_path / "problem.json"
    path.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
    return path


def _validated_spec(problem_path, *, data_files=None, data_dir=""):
    raw = json.loads(problem_path.read_text(encoding="utf-8"))
    resolved_dir = data_dir
    if data_dir:
        p = problem_path.parent / data_dir
        resolved_dir = str(p.resolve())
    return {
        "title": raw["title"],
        "background": raw["background"],
        "questions": raw["questions"],
        "data_files": data_files if data_files is not None else raw.get("data_files", []),
        "data_dir": resolved_dir,
    }


def test_ok_case_writes_preflight_json(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "math_agent.ops_preflight.importlib.util.find_spec",
        lambda lib: object(),
    )
    problem = _write_problem(tmp_path)
    spec = _validated_spec(problem)
    out = tmp_path / "runs" / "x"
    payload = run_preflight(
        problem_path=problem,
        spec=spec,
        brief_path=None,
        out=out,
        force=False,
    )
    assert payload["ok"] is True
    assert payload["problems"] == []
    assert payload["brief_path"] is None
    written = write_preflight_json(payload, out)
    assert written == out / "preflight.json"
    saved = json.loads(written.read_text(encoding="utf-8"))
    assert saved["ok"] is True
    assert saved["warns"] == []
    assert saved["blockers"] == []
    assert saved["brief_path"] is None


def test_blockers_fail(tmp_path):
    problem = _write_problem(tmp_path, blockers=["需要真实仿真平台"])
    spec = _validated_spec(problem)
    payload = run_preflight(
        problem_path=problem,
        spec=spec,
        brief_path=None,
        out=tmp_path / "out",
        force=False,
    )
    assert payload["ok"] is False
    assert any("feasibility.blockers 非空" in p for p in payload["problems"])
    assert payload["blockers"] == ["需要真实仿真平台"]
    assert payload["warns"] == []


def test_missing_attachment_fails(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    problem = _write_problem(
        tmp_path,
        extra={
            "data_dir": "data",
            "data_files": [
                {"filename": "att.xlsx", "file_type": "xlsx", "path": "att.xlsx", "summary": {}},
            ],
        },
    )
    spec = _validated_spec(
        problem,
        data_files=[
            {"filename": "att.xlsx", "file_type": "xlsx", "path": "att.xlsx", "summary": {}},
        ],
        data_dir="data",
    )
    payload = run_preflight(
        problem_path=problem,
        spec=spec,
        brief_path=None,
        out=tmp_path / "out",
        force=False,
    )
    assert payload["ok"] is False
    assert any("附件缺失" in p for p in payload["problems"])


def test_checkpoint_without_force_fails(tmp_path):
    problem = _write_problem(tmp_path)
    spec = _validated_spec(problem)
    out = tmp_path / "runs" / "existing"
    out.mkdir(parents=True)
    (out / "checkpoints.sqlite").write_bytes(b"x")
    payload = run_preflight(
        problem_path=problem,
        spec=spec,
        brief_path=None,
        out=out,
        force=False,
    )
    assert payload["ok"] is False
    assert any("已有 checkpoint" in p for p in payload["problems"])


def test_checkpoint_with_force_ok(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "math_agent.ops_preflight.importlib.util.find_spec",
        lambda lib: object(),
    )
    problem = _write_problem(tmp_path)
    spec = _validated_spec(problem)
    out = tmp_path / "runs" / "existing"
    out.mkdir(parents=True)
    (out / "checkpoints.sqlite").write_bytes(b"x")
    payload = run_preflight(
        problem_path=problem,
        spec=spec,
        brief_path=None,
        out=out,
        force=True,
    )
    assert payload["ok"] is True
    assert payload["problems"] == []


def test_brief_path_recorded(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "math_agent.ops_preflight.importlib.util.find_spec",
        lambda lib: object(),
    )
    problem = _write_problem(tmp_path)
    spec = _validated_spec(problem)
    out = tmp_path / "out"

    none_payload = run_preflight(
        problem_path=problem,
        spec=spec,
        brief_path=None,
        out=out,
        force=False,
    )
    assert none_payload["brief_path"] is None

    brief = tmp_path / "brief.json"
    brief.write_text("{}", encoding="utf-8")
    path_payload = run_preflight(
        problem_path=problem,
        spec=spec,
        brief_path=brief,
        out=out,
        force=False,
    )
    assert path_payload["brief_path"] == str(brief)
    written = write_preflight_json(path_payload, out)
    saved = json.loads(written.read_text(encoding="utf-8"))
    assert saved["brief_path"] == str(brief)
