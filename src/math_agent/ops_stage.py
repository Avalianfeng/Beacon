"""从磁盘工件推断问题流程阶段（S0–S8；S9 可选）。无工作流引擎。"""
from __future__ import annotations

from pathlib import Path

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
    "S5": ["source/reference", "evidence-package.json"],
    "S6": ["reference.json"],
    "S7": ["review-report.json"],
    "S8": ["paper.md"],
}


def _is_file(problem_dir: Path, name: str) -> bool:
    return (problem_dir / name).is_file()


def _s5_complete(problem_dir: Path) -> bool:
    ref_dir = problem_dir / "source" / "reference"
    evidence = problem_dir / "evidence-package.json"
    return ref_dir.is_dir() or evidence.is_file()


def _s8_complete(runs_root: Path | None) -> bool:
    if runs_root is None:
        return False
    if not runs_root.is_dir():
        return False
    direct = runs_root / "paper.md"
    if direct.is_file():
        return True
    for child in runs_root.iterdir():
        if child.is_dir() and (child / "paper.md").is_file():
            return True
    return False


def _s9_optional_found(runs_root: Path | None) -> bool:
    if runs_root is None or not runs_root.is_dir():
        return False
    return any(runs_root.rglob("checkpoints.sqlite"))


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
        return _is_file(problem_dir, "reference.json")
    if stage == "S7":
        return _is_file(problem_dir, "review-report.json")
    if stage == "S8":
        return _s8_complete(runs_root)
    return False


def _missing_for_stage(stage: str, problem_dir: Path, runs_root: Path | None) -> list[str]:
    if stage == "S5":
        missing: list[str] = []
        ref_dir = problem_dir / "source" / "reference"
        if not ref_dir.is_dir():
            missing.append("source/reference")
        if not (problem_dir / "evidence-package.json").is_file():
            missing.append("evidence-package.json")
        return missing
    if stage == "S8":
        if runs_root is None:
            return ["paper.md"]
        return _STAGE_MISSING["S8"]
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
    if next_stage is not None:
        missing = _missing_for_stage(next_stage, problem_dir, runs_root)

    optional: list[str] = []
    if _s9_optional_found(runs_root):
        optional.append("S9")

    return {
        "problem_id": problem_dir.name,
        "completed": completed,
        "next": next_stage,
        "missing": missing,
        "optional": optional,
    }


def format_stage_text(result: dict) -> str:
    """人类可读的阶段摘要（含 completed / next / missing）。"""
    pid = result.get("problem_id", "?")
    completed = result.get("completed") or []
    next_stage = result.get("next")
    missing = result.get("missing") or []
    optional = result.get("optional") or []

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
    else:
        lines.append("next: (all S0–S8 complete)")

    if optional:
        lines.append(f"optional: {', '.join(optional)}")

    return "\n".join(lines)
