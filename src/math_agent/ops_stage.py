"""从磁盘工件推断问题流程阶段（S0–S8；S9 可选）。无工作流引擎。"""
from __future__ import annotations

import json
import re
from pathlib import Path

from math_agent.ops_handoff import next_command, resolve_run_file

# data_profile 是否列出概览图路径（D-007 人检提示，不进完成门槛）
_OVERVIEW_FIG_RE = re.compile(
    r"概览图|\.(?:png|jpe?g|svg|webp)\b",
    re.IGNORECASE,
)

# 阶段顺序与缺失时报告的相对路径（posix）
_STAGE_ORDER: tuple[str, ...] = (
    "S0", "S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8",
)

_STAGE_MISSING: dict[str, list[str]] = {
    "S0": ["problem.json"],
    "S1": ["data_profile.md"],
    "S2": ["exploration.md"],
    "S3": ["brief.json"],
    "S4": ["preflight.json"],
    "S5": ["evidence-package.json", "independent-review.json"],
    "S6": ["reference.json", "paper.md"],
    "S7": ["review-report.json"],
    "S8": ["acceptance.json"],
}


def _is_file(problem_dir: Path, name: str) -> bool:
    return (problem_dir / name).is_file()


def _read_json_object(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def _s5_complete(problem_dir: Path) -> bool:
    if not (problem_dir / "evidence-package.json").is_file():
        return False
    review_path = problem_dir / "independent-review.json"
    if not review_path.is_file():
        return False
    review = _read_json_object(review_path)
    if review is None:
        return False
    return review.get("verdict") == "pass"


def _s5_missing(problem_dir: Path) -> list[str]:
    missing: list[str] = []
    if not (problem_dir / "evidence-package.json").is_file():
        missing.append("evidence-package.json")
    review_path = problem_dir / "independent-review.json"
    review = _read_json_object(review_path) if review_path.is_file() else None
    if review is None or review.get("verdict") != "pass":
        missing.append("independent-review.json")
    return missing


def _s6_complete(problem_dir: Path, runs_root: Path | None) -> bool:
    if not (problem_dir / "reference.json").is_file():
        return False
    if runs_root is None:
        return False
    return resolve_run_file(runs_root, problem_dir.name, "paper.md") is not None


def _s6_missing(problem_dir: Path, runs_root: Path | None) -> list[str]:
    missing: list[str] = []
    if not (problem_dir / "reference.json").is_file():
        missing.append("reference.json")
    if runs_root is None or resolve_run_file(
        runs_root, problem_dir.name, "paper.md"
    ) is None:
        missing.append("paper.md")
    return missing


def _s8_complete(problem_dir: Path) -> bool:
    acceptance_path = problem_dir / "acceptance.json"
    if not acceptance_path.is_file():
        return False
    acceptance = _read_json_object(acceptance_path)
    if acceptance is None:
        return False
    return acceptance.get("approved") is True


def _s9_optional_found(runs_root: Path | None) -> bool:
    if runs_root is None or not runs_root.is_dir():
        return False
    return any(runs_root.rglob("checkpoints.sqlite"))


def _data_profile_lists_overview(problem_dir: Path) -> bool:
    path = problem_dir / "data_profile.md"
    if not path.is_file():
        return False
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return False
    return _OVERVIEW_FIG_RE.search(text) is not None


def d007_missing(problem_dir: Path) -> list[str]:
    """D-007 人检缺口（不打断 S0–S8 连续前缀）。

    - 缺 ``领域知识.md``（题根或 ``认知地图集/清点/``，后者为现行 09 站落点）
    - ``data_profile.md`` 不存在，或存在但未列出概览图路径/「概览图」字样
    """
    problem_dir = Path(problem_dir)
    missing: list[str] = []
    if not (problem_dir / "领域知识.md").is_file() and not (
        problem_dir / "认知地图集" / "清点" / "领域知识.md"
    ).is_file():
        missing.append("领域知识.md（题根或 认知地图集/清点/）")
    profile = problem_dir / "data_profile.md"
    if not profile.is_file():
        missing.append("data_profile.md#概览图")
    elif not _data_profile_lists_overview(problem_dir):
        missing.append("data_profile.md#概览图")
    return missing


def _stage_complete(
    stage: str,
    problem_dir: Path,
    runs_root: Path | None,
) -> bool:
    if stage == "S0":
        return _is_file(problem_dir, "problem.json")
    if stage == "S1":
        return _is_file(problem_dir, "data_profile.md")
    if stage == "S2":
        return _is_file(problem_dir, "exploration.md")
    if stage == "S3":
        return _is_file(problem_dir, "brief.json")
    if stage == "S4":
        return _is_file(problem_dir, "preflight.json")
    if stage == "S5":
        return _s5_complete(problem_dir)
    if stage == "S6":
        return _s6_complete(problem_dir, runs_root)
    if stage == "S7":
        return _is_file(problem_dir, "review-report.json")
    if stage == "S8":
        return _s8_complete(problem_dir)
    return False


def _missing_for_stage(stage: str, problem_dir: Path, runs_root: Path | None) -> list[str]:
    if stage == "S5":
        return _s5_missing(problem_dir)
    if stage == "S6":
        return _s6_missing(problem_dir, runs_root)
    if stage == "S8":
        return list(_STAGE_MISSING["S8"])
    return list(_STAGE_MISSING[stage])


def infer_stage(problem_dir: Path, runs_root: Path | None = None) -> dict:
    """从 problem_dir 与可选 runs_root 推断连续已完成阶段与下一步。"""
    problem_dir = Path(problem_dir)
    if runs_root is not None:
        runs_root = Path(runs_root)

    completed: list[str] = []
    for stage in _STAGE_ORDER:
        if _stage_complete(stage, problem_dir, runs_root):
            completed.append(stage)
        else:
            break

    next_stage: str | None
    if len(completed) < len(_STAGE_ORDER):
        next_stage = _STAGE_ORDER[len(completed)]
    else:
        next_stage = None

    missing: list[str] = []
    next_cmd: str | None = None
    if next_stage is not None:
        missing = _missing_for_stage(next_stage, problem_dir, runs_root)
        next_cmd = next_command(
            next_stage, problem_dir.name, missing, runs_root=runs_root
        )

    optional: list[str] = []
    if _s9_optional_found(runs_root):
        optional.append("S9")

    return {
        "problem_id": problem_dir.name,
        "completed": completed,
        "next": next_stage,
        "missing": missing,
        "next_command": next_cmd,
        "optional": optional,
        "d007_missing": d007_missing(problem_dir),
    }


def format_stage_text(result: dict) -> str:
    """人类可读的阶段摘要（含 completed / next / missing / d007_missing）。"""
    pid = result.get("problem_id", "?")
    completed = result.get("completed") or []
    next_stage = result.get("next")
    missing = result.get("missing") or []
    optional = result.get("optional") or []
    d007 = result.get("d007_missing") or []

    lines = [
        f"problem: {pid}",
        f"completed: {', '.join(completed) if completed else '(none)'}",
    ]
    if next_stage is not None:
        lines.append(f"next: {next_stage}")
        if missing:
            lines.append(f"missing: {', '.join(missing)}")
        else:
            lines.append("missing: (none)")
        next_cmd = result.get("next_command")
        if next_cmd:
            lines.append(f"next_command: {next_cmd}")
    else:
        lines.append("next: (all S0–S8 complete)")

    if optional:
        lines.append(f"optional: {', '.join(optional)}")
    if d007:
        lines.append(f"d007_missing: {', '.join(d007)}")
    else:
        lines.append("d007_missing: (none)")

    return "\n".join(lines)
