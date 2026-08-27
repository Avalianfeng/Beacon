"""ops_recertify 独立复核登记 v0。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from math_agent.ops_recertify import (
    build_review,
    compare_results,
    load_review,
    recertify,
    review_pass,
    write_review,
)
from math_agent.ops_verify import write_package


def _good_evidence() -> dict:
    return {
        "run": {"success": True},
        "result": {"ours": {"a": 1.0}},
        "q_lines": ["Q1: a=1"],
    }


def _good_package(*, problem_id: str = "x", evidence_path: str = "evidence.json") -> dict:
    return {
        "version": 1,
        "problem_id": problem_id,
        "solver": {"path": "s", "sha256": ""},
        "evidence_path": evidence_path,
        "checks": [
            {"id": "run_success", "pass": True},
            {"id": "no_nan_inf", "pass": True},
            {"id": "has_result", "pass": True},
        ],
        "ok": True,
    }


def _fail_package(*, problem_id: str = "x", evidence_path: str = "evidence.json") -> dict:
    package = _good_package(problem_id=problem_id, evidence_path=evidence_path)
    package["checks"][0] = {"id": "run_success", "pass": False}
    package["ok"] = False
    return package


def _setup_problem(tmp_path: Path, *, package: dict, evidence: dict | None = None) -> tuple[Path, Path]:
    problem_dir = tmp_path / "problem"
    problem_dir.mkdir()
    evidence_path = problem_dir / "evidence.json"
    evidence_path.write_text(json.dumps(evidence or _good_evidence()), encoding="utf-8")
    write_package(package, problem_dir / "evidence-package.json")
    return problem_dir, evidence_path


def test_no_package_raises_on_pass(tmp_path: Path):
    problem_dir = tmp_path / "problem"
    problem_dir.mkdir()
    evidence_path = problem_dir / "evidence.json"
    evidence_path.write_text(json.dumps(_good_evidence()), encoding="utf-8")

    with pytest.raises(ValueError, match="缺少 evidence-package.json"):
        recertify(
            problem_dir=problem_dir,
            evidence=evidence_path,
            actor="reviewer",
            verdict="pass",
        )


def test_package_ok_no_rerun_writes_pass(tmp_path: Path):
    problem_dir, evidence_path = _setup_problem(tmp_path, package=_good_package())

    review = recertify(
        problem_dir=problem_dir,
        evidence=evidence_path,
        actor="reviewer",
        notes="ok",
    )

    assert review["verdict"] == "pass"
    assert review["rerun"] == {"ran": False}
    assert review["actor"] == "reviewer"
    assert review["notes"] == "ok"
    assert review["version"] == 1
    assert review["problem_id"] == "x"
    assert review["evidence_sha256"]

    dest = problem_dir / "independent-review.json"
    assert dest.is_file()
    loaded = json.loads(dest.read_text(encoding="utf-8"))
    assert loaded == review


def test_package_fail_verdict_pass_raises(tmp_path: Path):
    problem_dir, evidence_path = _setup_problem(tmp_path, package=_fail_package())

    with pytest.raises(ValueError, match="缺少通过的 evidence-package，不能登记 pass"):
        recertify(
            problem_dir=problem_dir,
            evidence=evidence_path,
            actor="reviewer",
            verdict="pass",
        )


def test_package_fail_verdict_fail_allowed(tmp_path: Path):
    problem_dir, evidence_path = _setup_problem(tmp_path, package=_fail_package())

    review = recertify(
        problem_dir=problem_dir,
        evidence=evidence_path,
        actor="reviewer",
        verdict="fail",
        notes="package not ok",
    )

    assert review["verdict"] == "fail"
    assert review["rerun"] == {"ran": False}
    assert (problem_dir / "independent-review.json").is_file()


def test_rerun_same_result_passes(tmp_path: Path):
    problem_dir, evidence_path = _setup_problem(tmp_path, package=_good_package())
    rerun_evidence = {"result": {"ours": {"a": 1.0}}}

    review = recertify(
        problem_dir=problem_dir,
        evidence=evidence_path,
        actor="reviewer",
        rerun_evidence=rerun_evidence,
    )

    assert review["verdict"] == "pass"
    assert review["rerun"] == {"ran": True, "pass": True}


def test_rerun_drifted_result_forces_fail(tmp_path: Path):
    problem_dir, evidence_path = _setup_problem(tmp_path, package=_good_package())
    rerun_evidence = {"result": {"ours": {"a": 2.0}}}

    review = recertify(
        problem_dir=problem_dir,
        evidence=evidence_path,
        actor="reviewer",
        verdict="pass",
        rerun_evidence=rerun_evidence,
    )

    assert review["verdict"] == "fail"
    assert review["rerun"] == {"ran": True, "pass": False}


def test_review_pass():
    assert review_pass({"verdict": "pass"}) is True
    assert review_pass({"verdict": "fail"}) is False


def test_compare_results_matching_and_mismatching():
    left = {"result": {"ours": {"a": 1.0}}}
    right = {"result": {"ours": {"a": 1.0}}}
    assert compare_results(left, right) is True

    drifted = {"result": {"ours": {"a": 2.0}}}
    assert compare_results(left, drifted) is False


def test_write_load_roundtrip(tmp_path: Path):
    review = build_review(
        problem_id="x",
        evidence_path="evidence.json",
        evidence_sha256="abc",
        verdict="pass",
        actor="reviewer",
        notes="",
        rerun={"ran": False},
        at="2026-08-27T00:00:00+00:00",
    )
    dest = tmp_path / "nested" / "independent-review.json"
    write_review(review, dest)
    assert dest.is_file()
    assert load_review(dest) == review
