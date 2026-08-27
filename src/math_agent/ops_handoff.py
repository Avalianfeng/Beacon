"""交棒观察面：下一步可复制命令模板。"""
from __future__ import annotations


def next_command(
    stage: str,
    problem_id: str,
    missing: list[str] | None = None,
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
        return (
            f"math-agent reference paper --problem problems/{problem_id}/problem.json "
            f"--evidence runs/{problem_id}-reference/evidence.json"
        )
    if stage == "S7":
        return (
            f"math-agent review-check --paper runs/{problem_id}-reference/paper.md "
            f"--evidence runs/{problem_id}-reference/evidence.json"
        )
    if stage == "S8":
        return (
            f"math-agent accept --problem problems/{problem_id}/problem.json "
            f"--paper runs/{problem_id}-reference/paper.md --approve"
        )
    return None
