"""交棒观察面：下一步可复制命令模板。"""
from __future__ import annotations

from pathlib import Path


def iter_problem_run_dirs(runs_root: Path, problem_id: str) -> list[Path]:
    """本题在 runs_root 下的直接子目录（名等于 id，或 id- 前缀）。"""
    if not Path(runs_root).is_dir():
        return []
    prefix = f"{problem_id}-"
    matched: list[Path] = []
    for child in Path(runs_root).iterdir():
        if not child.is_dir():
            continue
        name = child.name
        if name == problem_id or name.startswith(prefix):
            matched.append(child)
    return matched


def resolve_run_file(
    runs_root: Path | None,
    problem_id: str,
    filename: str,
) -> Path | None:
    """在本题 run 目录中找 filename；多份时取该文件 mtime 最新者。"""
    if runs_root is None:
        return None
    candidates: list[Path] = []
    for run_dir in iter_problem_run_dirs(runs_root, problem_id):
        path = run_dir / filename
        if path.is_file():
            candidates.append(path)
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def _command_artifact_path(
    runs_root: Path | None,
    problem_id: str,
    filename: str,
) -> str:
    found = resolve_run_file(runs_root, problem_id, filename)
    if found is None:
        return f"runs/{problem_id}-reference/{filename}"
    try:
        return found.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return found.as_posix()


def next_command(
    stage: str,
    problem_id: str,
    missing: list[str] | None = None,
    runs_root: Path | None = None,
) -> str | None:
    """给外部 agent 一条可复制的 math-agent 命令模板。"""
    if stage == "S0":
        return f"math-agent problem import <题面文件> --problem-id {problem_id}"
    if stage in ("S1", "S2"):
        return None
    if stage == "S3":
        return f"math-agent brief check --brief problems/{problem_id}/brief.json"
    if stage == "S4":
        return (
            f"math-agent run --problem problems/{problem_id}/problem.json "
            f"--brief problems/{problem_id}/brief.json "
            f"--out runs/{problem_id}-preflight --dry-run"
        )
    if stage == "S5":
        missing_list = missing or []
        if "evidence-package.json" in missing_list:
            return (
                f"math-agent reference verify "
                f"--problem problems/{problem_id}/problem.json"
            )
        if "independent-review.json" in missing_list:
            return (
                f"math-agent reference recertify "
                f"--problem problems/{problem_id}/problem.json"
            )
        return (
            f"math-agent reference verify "
            f"--problem problems/{problem_id}/problem.json"
        )
    if stage == "S6":
        evidence = _command_artifact_path(runs_root, problem_id, "evidence.json")
        return (
            f"math-agent reference paper --problem problems/{problem_id}/problem.json "
            f"--evidence {evidence}"
        )
    if stage == "S7":
        paper = _command_artifact_path(runs_root, problem_id, "paper.md")
        evidence = _command_artifact_path(runs_root, problem_id, "evidence.json")
        return (
            f"math-agent review-check --paper {paper} "
            f"--evidence {evidence}"
        )
    if stage == "S8":
        paper = _command_artifact_path(runs_root, problem_id, "paper.md")
        return (
            f"math-agent accept --problem problems/{problem_id}/problem.json "
            f"--paper {paper} --approve"
        )
    return None
