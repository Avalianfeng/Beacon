"""ops_verify 机械证据包 v0。"""
from __future__ import annotations

import json
from pathlib import Path

from math_agent.ops_verify import (
    build_package,
    check_evidence,
    load_evidence,
    package_ok,
    write_package,
)


def _good_evidence() -> dict:
    return {
        "problem_id": "demo",
        "entry": "reference/_entry.py",
        "result": {"ours": {"gain": 0.88}, "or_flat": 1.2},
        "q_lines": ["Q1 line"],
        "run": {"success": True, "elapsed_s": 1.0, "stdout_chars": 10},
    }


def test_success_numeric_result_all_pass():
    evidence = _good_evidence()
    checks = check_evidence(evidence)
    assert [c["id"] for c in checks] == ["run_success", "no_nan_inf", "has_result"]
    assert all(c["pass"] for c in checks)

    package = build_package(
        problem_id="demo",
        solver_path="source/reference/_entry.py",
        solver_sha256="abc123",
        evidence_path="runs/demo/evidence.json",
        evidence=evidence,
    )
    assert package_ok(package)
    assert package["ok"] is True
    assert package["version"] == 1
    assert package["checks"] == checks


def test_run_success_false():
    evidence = _good_evidence()
    evidence["run"]["success"] = False
    checks = check_evidence(evidence)
    assert checks[0] == {"id": "run_success", "pass": False}
    assert checks[1]["pass"] is True
    assert checks[2]["pass"] is True

    package = build_package(
        problem_id="demo",
        solver_path="source/reference/_entry.py",
        solver_sha256="abc123",
        evidence_path="runs/demo/evidence.json",
        evidence=evidence,
    )
    assert package_ok(package) is False
    assert package["ok"] is False


def test_result_contains_nan():
    evidence = _good_evidence()
    evidence["result"] = {"x": float("nan")}
    checks = check_evidence(evidence)
    assert checks[1] == {"id": "no_nan_inf", "pass": False}

    package = build_package(
        problem_id="demo",
        solver_path="source/reference/_entry.py",
        solver_sha256="abc123",
        evidence_path="runs/demo/evidence.json",
        evidence=evidence,
    )
    assert package_ok(package) is False


def test_has_result_empty_or_missing():
    evidence = _good_evidence()
    evidence["result"] = {}
    checks = check_evidence(evidence)
    assert checks[2] == {"id": "has_result", "pass": False}

    missing = _good_evidence()
    del missing["result"]
    checks_missing = check_evidence(missing)
    assert checks_missing[2] == {"id": "has_result", "pass": False}


def test_write_package_roundtrip(tmp_path: Path):
    evidence = _good_evidence()
    evidence_path = tmp_path / "evidence.json"
    evidence_path.write_text(json.dumps(evidence), encoding="utf-8")

    package = build_package(
        problem_id="demo",
        solver_path="source/reference/_entry.py",
        solver_sha256="abc123",
        evidence_path=str(evidence_path),
        evidence=evidence,
    )
    dest = tmp_path / "pkg" / "evidence-package.json"
    written = write_package(package, dest)
    assert written == dest
    assert dest.is_file()

    loaded = json.loads(dest.read_text(encoding="utf-8"))
    assert loaded == package
    assert load_evidence(evidence_path) == evidence
