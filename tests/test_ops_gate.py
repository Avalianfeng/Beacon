"""ops_gate S6 装配闸门测试。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from math_agent.ops_gate import require_injected_package


def _ok_package(evidence_path: str) -> dict:
    return {
        "version": 1,
        "problem_id": "demo",
        "solver": {"path": "source/reference/_entry.py", "sha256": "abc123"},
        "evidence_path": evidence_path,
        "checks": [
            {"id": "run_success", "pass": True},
            {"id": "no_nan_inf", "pass": True},
            {"id": "has_result", "pass": True},
        ],
        "ok": True,
    }


def _fail_package(evidence_path: str) -> dict:
    package = _ok_package(evidence_path)
    package["checks"][0] = {"id": "run_success", "pass": False}
    package["ok"] = False
    return package


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def test_missing_evidence_package(tmp_path: Path):
    evidence = tmp_path / "evidence.json"
    evidence.write_text("{}", encoding="utf-8")

    with pytest.raises(ValueError, match="evidence-package"):
        require_injected_package(tmp_path, evidence)


def test_package_not_ok(tmp_path: Path):
    evidence = tmp_path / "evidence.json"
    evidence.write_text("{}", encoding="utf-8")
    _write_json(tmp_path / "evidence-package.json", _fail_package(str(evidence.resolve())))

    with pytest.raises(ValueError, match="机械三项"):
        require_injected_package(tmp_path, evidence)


def test_evidence_path_mismatch(tmp_path: Path):
    evidence = tmp_path / "evidence.json"
    evidence.write_text("{}", encoding="utf-8")
    other = tmp_path / "other-evidence.json"
    other.write_text("{}", encoding="utf-8")
    _write_json(tmp_path / "evidence-package.json", _ok_package(str(other.resolve())))

    with pytest.raises(ValueError, match="不一致"):
        require_injected_package(tmp_path, evidence)


def test_missing_independent_review(tmp_path: Path):
    evidence = tmp_path / "evidence.json"
    evidence.write_text("{}", encoding="utf-8")
    _write_json(tmp_path / "evidence-package.json", _ok_package(str(evidence.resolve())))

    with pytest.raises(ValueError, match="recertify"):
        require_injected_package(tmp_path, evidence)


def test_review_verdict_not_pass(tmp_path: Path):
    evidence = tmp_path / "evidence.json"
    evidence.write_text("{}", encoding="utf-8")
    _write_json(tmp_path / "evidence-package.json", _ok_package(str(evidence.resolve())))
    _write_json(tmp_path / "independent-review.json", {"verdict": "fail"})

    with pytest.raises(ValueError, match="独立复核"):
        require_injected_package(tmp_path, evidence)


def test_success_absolute_evidence_path(tmp_path: Path):
    evidence = tmp_path / "evidence.json"
    evidence.write_text(json.dumps({"result": {"x": 1}, "run": {"success": True}}), encoding="utf-8")
    package = _ok_package(str(evidence.resolve()))
    review = {"verdict": "pass"}
    _write_json(tmp_path / "evidence-package.json", package)
    _write_json(tmp_path / "independent-review.json", review)

    result = require_injected_package(tmp_path, evidence)

    assert result["package"] == package
    assert result["review"] == review


def test_success_relative_evidence_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.chdir(tmp_path)
    evidence = tmp_path / "evidence.json"
    evidence.write_text(json.dumps({"result": {"x": 1}, "run": {"success": True}}), encoding="utf-8")
    package = _ok_package("evidence.json")
    review = {"verdict": "pass"}
    _write_json(tmp_path / "evidence-package.json", package)
    _write_json(tmp_path / "independent-review.json", review)

    result = require_injected_package(tmp_path, evidence)

    assert result["package"] == package
    assert result["review"] == review
