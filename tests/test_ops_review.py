# -*- coding: utf-8 -*-
"""ops_review 模块测试（复用 tests/fixtures/check_numbers/）。"""

import json
from pathlib import Path

from math_agent.ops_review import load_check_module, run_review, write_review_report

FIXTURES = Path(__file__).parent / "fixtures" / "check_numbers"


def test_load_check_module():
    mod = load_check_module("check_paper_numbers")
    assert hasattr(mod, "main")


def test_run_review_paper_and_evidence():
    paper = FIXTURES / "paper_clean.md"
    evidence = [FIXTURES / "evidence_a.txt", FIXTURES / "evidence_b.json"]
    result = run_review(paper=paper, evidence=evidence, strict=False)

    assert isinstance(result, dict)
    assert set(result.keys()) == {"ok", "exit_code", "tools", "strict"}
    assert result["strict"] is False
    assert result["exit_code"] == 0
    assert result["ok"] is True

    names = {t["name"] for t in result["tools"]}
    assert "check_paper_numbers" in names
    assert "check_assumption_claims" in names
    assert "check_l4_gates" in names
    l4 = next(t for t in result["tools"] if t["name"] == "check_l4_gates")
    assert l4["exit_code"] == 0
    for tool in result["tools"]:
        assert set(tool.keys()) == {"name", "exit_code"}
        assert tool["exit_code"] in (0, 1, 2)


def test_run_review_missing_inputs():
    result = run_review(paper=None, json_evidence=None, traceability=None)
    assert result["ok"] is False
    assert result["exit_code"] == 2
    assert result["tools"] == []


def test_write_review_report_to_dir():
    payload = {"ok": True, "exit_code": 0, "tools": [], "strict": False}
    path = write_review_report(payload, FIXTURES)
    assert path == FIXTURES / "review-report.json"
    assert path.is_file()
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert loaded == payload
    path.unlink(missing_ok=True)


def test_write_review_report_to_json_file():
    target = FIXTURES / "custom-review.json"
    payload = {"ok": False, "exit_code": 1, "tools": [{"name": "x", "exit_code": 1}], "strict": True}
    path = write_review_report(payload, target)
    assert path == target
    assert json.loads(path.read_text(encoding="utf-8")) == payload
    path.unlink(missing_ok=True)
