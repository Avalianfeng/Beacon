"""ops_handoff：交棒命令模板。"""
from __future__ import annotations

from math_agent.ops_handoff import next_command


def test_s1_returns_none():
    assert next_command("S1", "mcm51-c") is None


def test_s4_dry_run_command():
    cmd = next_command("S4", "mcm51-c")
    assert cmd is not None
    assert "math-agent run" in cmd
    assert "problems/mcm51-c/problem.json" in cmd
    assert "problems/mcm51-c/brief.json" in cmd
    assert "runs/mcm51-c-preflight" in cmd
    assert "--dry-run" in cmd


def test_s5_verify_when_package_missing():
    cmd = next_command("S5", "mcm51-c", missing=["evidence-package.json"])
    assert cmd is not None
    assert "math-agent reference verify" in cmd
    assert "problems/mcm51-c/problem.json" in cmd
    assert "recertify" not in cmd


def test_s5_recertify_when_review_missing():
    cmd = next_command(
        "S5",
        "mcm51-c",
        missing=["independent-review.json"],
    )
    assert cmd is not None
    assert "math-agent reference recertify" in cmd
    assert "problems/mcm51-c/problem.json" in cmd


def test_s5_verify_when_both_missing():
    cmd = next_command(
        "S5",
        "mcm51-c",
        missing=["evidence-package.json", "independent-review.json"],
    )
    assert cmd is not None
    assert "math-agent reference verify" in cmd
    assert "recertify" not in cmd


def test_s6_paper_command():
    cmd = next_command("S6", "mcm51-c")
    assert cmd is not None
    assert "math-agent reference paper" in cmd
    assert "problems/mcm51-c/problem.json" in cmd
    assert "runs/mcm51-c-reference/evidence.json" in cmd


def test_s7_review_check_command():
    cmd = next_command("S7", "mcm51-c")
    assert cmd is not None
    assert "math-agent review-check" in cmd
    assert "runs/mcm51-c-reference/paper.md" in cmd
    assert "runs/mcm51-c-reference/evidence.json" in cmd


def test_s8_accept_command():
    cmd = next_command("S8", "mcm51-c")
    assert cmd is not None
    assert "math-agent accept" in cmd
    assert "problems/mcm51-c/problem.json" in cmd
    assert "runs/mcm51-c-reference/paper.md" in cmd
    assert "--approve" in cmd


def test_s9_returns_none():
    assert next_command("S9", "mcm51-c") is None
