"""独立复核登记 v0：写 independent-review.json。"""
from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path

from math_agent.ops_verify import iter_numbers, load_evidence, package_ok


def file_sha256(path: Path) -> str:
    """Return hex digest of file bytes."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_package(path: Path) -> dict:
    """Load evidence-package JSON; raise ValueError (Chinese) on failure."""
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"无法读取 evidence-package：{path}") from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"evidence-package JSON 无效：{path}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"evidence-package 根节点必须是对象：{path}")
    return data


def load_review(path: Path) -> dict:
    """Load independent-review JSON; raise ValueError (Chinese) on failure."""
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"无法读取 independent-review：{path}") from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"independent-review JSON 无效：{path}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"independent-review 根节点必须是对象：{path}")
    return data


def review_pass(review: dict) -> bool:
    return review.get("verdict") == "pass"


def compare_results(left: dict, right: dict) -> bool:
    """Compare numeric values under ``result`` using iter_numbers traversal order."""
    left_result = left.get("result")
    right_result = right.get("result")
    if not isinstance(left_result, dict) or not isinstance(right_result, dict):
        return False
    left_nums = list(iter_numbers(left_result))
    right_nums = list(iter_numbers(right_result))
    if len(left_nums) != len(right_nums):
        return False
    for a, b in zip(left_nums, right_nums):
        if isinstance(a, float) or isinstance(b, float):
            if not math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-9):
                return False
        elif a != b:
            return False
    return True


def build_review(
    *,
    problem_id: str,
    evidence_path: str,
    evidence_sha256: str,
    verdict: str,
    actor: str,
    notes: str,
    rerun: dict,
    at: str | None = None,
) -> dict:
    if verdict not in ("pass", "fail"):
        raise ValueError(f"verdict 只能是 pass 或 fail，收到：{verdict}")
    if at is None:
        at = datetime.now(timezone.utc).isoformat()
    return {
        "version": 1,
        "problem_id": problem_id,
        "evidence_path": evidence_path,
        "evidence_sha256": evidence_sha256,
        "verdict": verdict,
        "actor": actor,
        "notes": notes,
        "rerun": rerun,
        "at": at,
    }


def write_review(review: dict, dest: Path) -> Path:
    """Write review JSON utf-8 indent=2 with trailing newline; mkdir parents."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(
        json.dumps(review, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return dest


def recertify(
    *,
    problem_dir: Path,
    evidence: Path,
    actor: str,
    notes: str = "",
    verdict: str = "pass",
    rerun_evidence: dict | None = None,
) -> dict:
    problem_dir = Path(problem_dir)
    evidence = Path(evidence)

    package_path = problem_dir / "evidence-package.json"
    if not package_path.is_file():
        raise ValueError("缺少 evidence-package.json")

    package = load_package(package_path)
    if not package_ok(package):
        if verdict == "pass":
            raise ValueError("缺少通过的 evidence-package，不能登记 pass")

    if verdict not in ("pass", "fail"):
        raise ValueError(f"verdict 只能是 pass 或 fail，收到：{verdict}")

    evidence_sha256 = file_sha256(evidence)
    evidence_data = load_evidence(evidence)

    problem_id = package.get("problem_id", "")
    if not isinstance(problem_id, str):
        problem_id = str(problem_id)

    if rerun_evidence is None:
        rerun: dict = {"ran": False}
    else:
        if not isinstance(rerun_evidence, dict):
            raise ValueError("rerun_evidence 必须是 dict")
        if compare_results(evidence_data, rerun_evidence):
            rerun = {"ran": True, "pass": True}
        else:
            rerun = {"ran": True, "pass": False}
            verdict = "fail"

    review = build_review(
        problem_id=problem_id,
        evidence_path=str(evidence),
        evidence_sha256=evidence_sha256,
        verdict=verdict,
        actor=actor,
        notes=notes,
        rerun=rerun,
    )

    write_review(review, problem_dir / "independent-review.json")
    return review
