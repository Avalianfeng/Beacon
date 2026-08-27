"""机械证据包 v0：run 成功、result 非空、数值无 nan/inf。"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Iterator


def iter_numbers(obj: Any) -> Iterator[float | int]:
    """Yield floats/ints from nested dict/list."""
    if isinstance(obj, dict):
        for value in obj.values():
            yield from iter_numbers(value)
    elif isinstance(obj, list):
        for item in obj:
            yield from iter_numbers(item)
    elif isinstance(obj, bool):
        return
    elif isinstance(obj, int):
        yield obj
    elif isinstance(obj, float):
        yield obj


def check_evidence(evidence: dict) -> list[dict]:
    """Return checks list of {id, pass} for run_success, no_nan_inf, has_result."""
    run = evidence.get("run")
    run_success = isinstance(run, dict) and run.get("success") is True

    result = evidence.get("result")
    has_result = isinstance(result, dict) and len(result) > 0

    no_nan_inf = True
    if isinstance(result, dict):
        for num in iter_numbers(result):
            if math.isnan(num) or math.isinf(num):
                no_nan_inf = False
                break

    return [
        {"id": "run_success", "pass": run_success},
        {"id": "no_nan_inf", "pass": no_nan_inf},
        {"id": "has_result", "pass": has_result},
    ]


def build_package(
    *,
    problem_id: str,
    solver_path: str,
    solver_sha256: str,
    evidence_path: str,
    evidence: dict,
) -> dict:
    checks = check_evidence(evidence)
    package = {
        "version": 1,
        "problem_id": problem_id,
        "solver": {"path": solver_path, "sha256": solver_sha256},
        "evidence_path": evidence_path,
        "checks": checks,
    }
    if package_ok(package):
        package["ok"] = True
    else:
        package["ok"] = False
    return package


def package_ok(package: dict) -> bool:
    """True iff all checks pass."""
    checks = package.get("checks")
    if not isinstance(checks, list):
        return False
    return all(
        isinstance(check, dict) and check.get("pass") is True for check in checks
    )


def write_package(package: dict, dest: Path) -> Path:
    """Write dest as JSON utf-8 indent=2. Create parents."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(
        json.dumps(package, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return dest


def load_evidence(path: Path) -> dict:
    """JSON load; raise ValueError with Chinese message if invalid."""
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"无法读取证据文件：{path}") from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"证据文件 JSON 无效：{path}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"证据文件根节点必须是对象：{path}")
    return data
