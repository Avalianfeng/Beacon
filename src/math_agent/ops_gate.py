"""S6 装配闸门：evidence-package 已注入且独立复核通过。"""
from __future__ import annotations

import json
from pathlib import Path

from math_agent.ops_verify import package_ok


def _load_json(path: Path, label: str) -> dict:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"无法读取{label}：{path}") from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} JSON 无效：{path}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{label} 根节点必须是对象：{path}")
    return data


def require_injected_package(problem_dir: Path, evidence_path: Path) -> dict:
    """校验题级 evidence-package 与 independent-review，通过则返回 package 与 review。"""
    problem_dir = Path(problem_dir)
    evidence_path = Path(evidence_path)

    pkg_path = problem_dir / "evidence-package.json"
    if not pkg_path.is_file():
        raise ValueError("缺少 evidence-package.json，先 `reference verify`")

    package = _load_json(pkg_path, "evidence-package.json")
    if not package_ok(package):
        raise ValueError("evidence-package 未通过机械三项，不能装配论文")

    pkg_evidence = package.get("evidence_path")
    if not isinstance(pkg_evidence, str):
        raise ValueError("--evidence 与 evidence-package.json 中的 evidence_path 不一致")
    if evidence_path.resolve() != Path(pkg_evidence).resolve():
        raise ValueError("--evidence 与 evidence-package.json 中的 evidence_path 不一致")

    rev_path = problem_dir / "independent-review.json"
    if not rev_path.is_file():
        raise ValueError("缺少 independent-review.json，先 `reference recertify`")

    review = _load_json(rev_path, "independent-review.json")
    if review.get("verdict") != "pass":
        raise ValueError("独立复核未通过，不能装配论文")

    return {"package": package, "review": review}
