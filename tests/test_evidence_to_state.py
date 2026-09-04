"""evidence → writer state 适配器单测（无 LLM）。"""
from __future__ import annotations

import json
from pathlib import Path

from math_agent.adapters.evidence_to_state import (
    build_code_stdout,
    build_writer_state,
    minimal_model_card_from_brief,
    parse_sensitivity_from_q_lines,
    validate_writer_state,
)
from math_agent.brief import ModelingBrief, PerQuestionDirectionItem, FormulaNoteItem


def test_build_code_stdout_joins_q_lines():
    ev = {"q_lines": ["Q1: a=1", "RESULT: baseline=ours x=2"]}
    assert "Q1: a=1" in build_code_stdout(ev)
    assert "RESULT:" in build_code_stdout(ev)


def test_parse_sensitivity_markup():
    lines = [
        "Q2: markup_p=[25,50,75] markup_profit=[1.0,2.0,3.0] other=1",
    ]
    runs = parse_sensitivity_from_q_lines(lines)
    assert len(runs) == 1
    assert runs[0].parameter == "markup_percentile"
    assert runs[0].values == [25.0, 50.0, 75.0]
    assert runs[0].results == [1.0, 2.0, 3.0]


def test_build_writer_state_minimal(tmp_path: Path):
    evidence = {
        "problem_id": "t",
        "entry": "reference/_entry.py",
        "q_lines": ["Q1: x=1.5", "RESULT: baseline=ours x=1.5"],
        "result": {"ours": {"x": 1.5}},
    }
    brief = ModelingBrief(
        schema_version=1,
        problem_id="t",
        per_question_direction=[
            PerQuestionDirectionItem(id="1", question_id="1", direction="解释分布"),
            PerQuestionDirectionItem(id="2", question_id="2", direction="优化补货"),
        ],
        formula_notes=[
            FormulaNoteItem(id="f1", note=r"q=d/(1-\lambda)"),
        ],
    )
    spec = {
        "title": "测试题",
        "questions": ["问1", "问2"],
        "background": "bg",
        "data_dir": str(tmp_path),
        "data_files": [],
    }
    out = tmp_path / "run"
    state = build_writer_state(
        problem_spec=spec,
        brief=brief,
        evidence=evidence,
        output_dir=out,
    )
    issues = validate_writer_state(state)
    assert issues == [], issues
    assert state.brief is not None
    assert state.code_artifacts[0].evidence_role == "primary"
    assert "RESULT:" in state.code_artifacts[0].stdout
    assert state.figure_phase == "done"
    assert state.problem_blueprint is not None
    assert len(state.problem_blueprint.subquestions) == 2
    assert state.model_versions[0].stage == "final"


def test_model_card_override(tmp_path: Path):
    evidence = {
        "q_lines": ["Q1: a=1", "RESULT: baseline=ours a=1"],
    }
    card = {
        "assumptions": [{"statement": "卡假设", "rationale": "x"}],
        "model_versions": [{
            "stage": "final",
            "description": "override model",
            "equations": ["a=1"],
        }],
        "problem_blueprint": {
            "core_task": "override",
            "subquestions": [
                {"id": "1", "original_text": "q", "task_type": "generic"},
            ],
        },
        "sensitivity_runs": [],
        "problem_domains": ["retail"],
    }
    card_path = tmp_path / "card.json"
    card_path.write_text(json.dumps(card), encoding="utf-8")
    state = build_writer_state(
        problem_spec={"title": "t", "questions": ["q"]},
        brief=None,
        evidence=evidence,
        output_dir=tmp_path / "out",
        model_card=card_path,
    )
    assert state.model_versions[0].description == "override model"
    assert state.assumptions[0].statement == "卡假设"
    assert validate_writer_state(state) == []


def test_minimal_model_card_from_brief():
    brief = ModelingBrief(
        schema_version=1,
        per_question_direction=[
            PerQuestionDirectionItem(id="1", direction="策略建议"),
        ],
    )
    assumptions, models, bp, domains = minimal_model_card_from_brief(brief)
    assert assumptions
    assert models
    assert bp.subquestions[0].task_type == "strategy"
    assert domains
