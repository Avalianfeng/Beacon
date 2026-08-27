"""ops_accept 分阶段人审登记 v0。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from math_agent.ops_accept import (
    accept,
    acceptance_approved,
    build_acceptance,
    file_sha256,
    load_acceptance,
    write_acceptance,
)


def test_accept_approved_true(tmp_path: Path):
    problem_dir = tmp_path / "demo-prob"
    problem_dir.mkdir()
    paper = tmp_path / "paper.md"
    paper.write_text("# paper\n", encoding="utf-8")

    payload = accept(
        problem_dir=problem_dir,
        paper=paper,
        approved=True,
        actor="alice",
        notes="LGTM",
    )

    dest = problem_dir / "acceptance.json"
    assert dest.is_file()
    assert acceptance_approved(payload) is True
    assert payload["paper_sha256"] == file_sha256(paper)
    assert payload["problem_id"] == "demo-prob"
    assert payload["approved"] is True
    assert payload["actor"] == "alice"
    assert payload["notes"] == "LGTM"


def test_accept_approved_false(tmp_path: Path):
    problem_dir = tmp_path / "demo-prob"
    problem_dir.mkdir()
    paper = tmp_path / "paper.md"
    paper.write_text("# paper\n", encoding="utf-8")

    payload = accept(
        problem_dir=problem_dir,
        paper=paper,
        approved=False,
        actor="bob",
    )

    dest = problem_dir / "acceptance.json"
    assert dest.is_file()
    assert acceptance_approved(payload) is False
    assert payload["approved"] is False


def test_accept_missing_paper_raises(tmp_path: Path):
    problem_dir = tmp_path / "demo-prob"
    problem_dir.mkdir()
    missing = tmp_path / "no-such-paper.md"

    with pytest.raises(ValueError, match="论文文件不存在"):
        accept(
            problem_dir=problem_dir,
            paper=missing,
            approved=True,
            actor="alice",
        )


def test_load_write_roundtrip(tmp_path: Path):
    payload = build_acceptance(
        problem_id="p1",
        paper_path="/runs/p1/paper.md",
        paper_sha256="abc" * 21 + "a",
        approved=True,
        actor="carol",
        notes="ok",
        at="2026-08-27T09:00:00+00:00",
    )
    dest = tmp_path / "nested" / "acceptance.json"
    written = write_acceptance(payload, dest)
    assert written == dest
    assert dest.is_file()

    loaded = load_acceptance(dest)
    assert loaded == payload
    assert json.loads(dest.read_text(encoding="utf-8")) == payload


def test_acceptance_approved_strict_bool():
    assert acceptance_approved({}) is False
    assert acceptance_approved({"approved": False}) is False
    assert acceptance_approved({"approved": 1}) is False
    assert acceptance_approved({"approved": True}) is True
