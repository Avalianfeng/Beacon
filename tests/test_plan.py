"""plan build / check 单测（无 LLM）。"""
from __future__ import annotations

import json

from math_agent.brief import ModelingBrief, PerQuestionDirectionItem, FormulaNoteItem
from math_agent.plan import (
    build_anchored_coverage,
    build_plan_v0,
    check_plan,
    load_plan,
)


def _tiny_brief() -> ModelingBrief:
    return ModelingBrief(
        schema_version=2,
        problem_id="t",
        per_question_direction=[
            PerQuestionDirectionItem(
                id="1-direction",
                question_id="1",
                direction="分布描述",
            )
        ],
        formula_notes=[
            FormulaNoteItem(id="1-eq", question_id="1", note="n = count"),
        ],
    )


def test_anchored_coverage_not_empty_followed():
    brief = _tiny_brief()
    cov = build_anchored_coverage(brief)
    assert {c.brief_item_id for c in cov} == {"1-direction", "1-eq"}
    for item in cov:
        assert item.status == "followed"
        assert item.question_ids or item.equation_ids


def test_plan_v0_then_check_reports_gaps(tmp_path):
    brief = _tiny_brief()
    card = build_plan_v0(brief, questions=["第一问"], title="题")
    result = check_plan(card, brief=brief)
    assert not result.ok
    joined = " ".join(result.errors)
    assert "decision_variables" in joined
    assert "pass_criteria" in joined
    assert "validation_mapping" in joined
    bp = card["problem_blueprint"]
    assert bp["brief_coverage"][0]["question_ids"]
    assert bp["brief_coverage"][0]["equation_ids"]


def test_check_plan_passes_when_fields_filled():
    brief = _tiny_brief()
    card = build_plan_v0(brief, questions=["第一问"], title="题")
    bp = card["problem_blueprint"]
    bp["decision_variables"] = [
        {"name": "n", "meaning": "计数", "domain": ">=0", "unit": "1"}
    ]
    if not bp.get("constraints"):
        bp["constraints"] = [{"description": "n>=0", "source": "assumed"}]
    bp["validation_plan"][0]["pass_criteria"] = "n>0"
    card["model_versions"][0]["validation_mapping"] = ["stdout n 对照 n>0"]
    card["model_versions"][0]["constraint_mapping"] = ["n>=0"]
    result = check_plan(card, brief=brief)
    assert result.ok, result.errors


def test_cumcm23c_plan_check_zero_gaps():
    from pathlib import Path
    from math_agent.brief import load_brief
    from math_agent.plan import check_plan, load_plan

    plan_path = Path("problems/cumcm23-c/plan.json")
    brief_path = Path("problems/cumcm23-c/brief.json")
    if not plan_path.is_file() or not brief_path.is_file():
        import pytest
        pytest.skip("cumcm23-c plan/brief 不在工作区")
    result = check_plan(load_plan(plan_path), brief=load_brief(brief_path))
    assert result.ok, result.errors


def test_load_plan_roundtrip(tmp_path):
    brief = _tiny_brief()
    card = build_plan_v0(brief, title="题")
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(card), encoding="utf-8")
    loaded = load_plan(path)
    assert loaded["problem_blueprint"]["core_task"]
