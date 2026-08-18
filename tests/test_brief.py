"""Modeling Brief 单元测试（load/校验/渲染/门禁/prompt 注入）。"""
import json
import pytest

from math_agent.brief import (
    ModelingBrief,
    PerQuestionDirectionItem,
    BriefCoverageItem,
    FormulaNoteItem,
    RedLineItem,
    RequiredDiscussionItem,
    load_brief,
    brief_item_ids,
    brief_coverage_problems,
    render_full_brief,
    render_modeler_brief,
    render_coder_brief,
    render_discussions_for_group,
)
from math_agent.brief_dialogue import auto_fill_ids, assemble_brief, draft_field
from math_agent.state import ProblemBlueprint, ModelVersion
from math_agent.prompts.analyst import build_prompt as analyst_build_prompt
from math_agent.prompts.modeler import build_prompt as modeler_build_prompt
from math_agent.prompts.coder_figure_one import build_prompt_figure_one
from math_agent.prompts.model_critic import build_prompt as model_critic_build_prompt
from math_agent.prompts.writer_section import build_section_prompt, WriterOutline
from math_agent.state import MathModelingState


def _minimal_brief():
    return ModelingBrief(per_question_direction=[
        PerQuestionDirectionItem(id="dir-q1", question_id="q1", direction="MILP"),
    ])


def _rich_brief():
    return ModelingBrief(
        per_question_direction=[
            PerQuestionDirectionItem(id="dir-q1", question_id="q1", direction="MILP", forbidden="贪心"),
        ],
        formula_notes=[FormulaNoteItem(id="fn-1", note="F=ma")],
        required_discussions=[
            RequiredDiscussionItem(
                id="disc-1", sections=["model_section"], topic="参数假设", requirement="必须声明",
            ),
            RequiredDiscussionItem(id="disc-2", sections=["conclusion"], topic="结论讨论"),
        ],
        red_lines=[RedLineItem(id="rl-1", prohibition="禁止硬编码")],
        figure_plan=[],
        scoring_notes=[],
        data_notes=[],
        reference_direction=["巷道支护", "Winkler 地基"],
        source=["human"],
    )


# ---------------------------------------------------------------------------
# load_brief
# ---------------------------------------------------------------------------

def test_load_brief_valid_json(tmp_path):
    path = tmp_path / "brief.json"
    path.write_text(
        json.dumps({"schema_version": 1, "per_question_direction": [{"id": "d1", "direction": "x"}]}),
        encoding="utf-8",
    )
    obj = load_brief(path)
    assert obj.per_question_direction[0].id == "d1"


def test_load_brief_invalid_json_raises_with_path(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError, match="bad.json") as exc_info:
        load_brief(path)
    assert "brief 文件" in str(exc_info.value)


def test_load_brief_invalid_schema_raises_with_path(tmp_path):
    path = tmp_path / "bad_schema.json"
    path.write_text(json.dumps({"schema_version": 2}), encoding="utf-8")
    with pytest.raises(ValueError, match="bad_schema.json") as exc_info:
        load_brief(path)
    assert "schema" in str(exc_info.value).lower()


# ---------------------------------------------------------------------------
# ModelingBrief 校验
# ---------------------------------------------------------------------------

def test_modeling_brief_rejects_duplicate_ids():
    with pytest.raises(ValueError, match="id 必须唯一"):
        ModelingBrief(
            per_question_direction=[
                PerQuestionDirectionItem(id="dup", direction="a"),
            ],
            formula_notes=[FormulaNoteItem(id="dup", note="b")],
        )


def test_modeling_brief_rejects_invalid_discussion_section():
    with pytest.raises(ValueError, match="required_discussions.sections"):
        ModelingBrief(
            required_discussions=[
                RequiredDiscussionItem(id="d1", sections=["invalid_section"], topic="x"),
            ],
        )


# ---------------------------------------------------------------------------
# brief_item_ids / brief_coverage_problems
# ---------------------------------------------------------------------------

def test_brief_item_ids_collects_all_fields():
    brief = _rich_brief()
    ids = brief_item_ids(brief)
    assert ids == ["dir-q1", "fn-1", "disc-1", "disc-2", "rl-1"]


def test_brief_coverage_problems_none_brief_returns_empty():
    bp = ProblemBlueprint(core_task="t")
    assert brief_coverage_problems(None, bp) == []


def test_brief_coverage_problems_missing_entry():
    brief = _minimal_brief()
    bp = ProblemBlueprint(core_task="t", brief_coverage=[])
    problems = brief_coverage_problems(brief, bp)
    assert any("dir-q1" in p for p in problems)


def test_brief_coverage_problems_deviated_without_reason():
    brief = _minimal_brief()
    bp = ProblemBlueprint(
        core_task="t",
        brief_coverage=[BriefCoverageItem(brief_item_id="dir-q1", status="deviated", reason="")],
    )
    problems = brief_coverage_problems(brief, bp)
    assert any("未给出理由" in p for p in problems)


def test_brief_coverage_problems_followed_and_deviated_with_reason_pass():
    brief = ModelingBrief(
        per_question_direction=[
            PerQuestionDirectionItem(id="a", direction="x"),
            PerQuestionDirectionItem(id="b", direction="y"),
        ],
    )
    bp = ProblemBlueprint(
        core_task="t",
        brief_coverage=[
            BriefCoverageItem(brief_item_id="a", status="followed"),
            BriefCoverageItem(brief_item_id="b", status="deviated", reason="与题面冲突"),
        ],
    )
    assert brief_coverage_problems(brief, bp) == []


# ---------------------------------------------------------------------------
# render_* helpers
# ---------------------------------------------------------------------------

def test_render_full_brief_none_returns_empty():
    assert render_full_brief(None) == ""


def test_render_full_brief_contains_blocks():
    text = render_full_brief(_rich_brief())
    assert "# 人工建模预备（Modeling Brief）" in text
    assert "## 逐题方向" in text
    assert "## 公式注意" in text
    assert "## 论文必须体现的讨论点" in text
    assert "## 红线（禁止清单）" in text
    assert "## 参考文献方向" in text
    assert "巷道支护" in text


def test_render_modeler_brief_none_and_content():
    assert render_modeler_brief(None) == ""
    text = render_modeler_brief(_rich_brief())
    assert "# 人工建模预备（方向与公式约束）" in text
    assert "MILP" in text
    assert "F=ma" in text


def test_render_coder_brief_none_and_content():
    assert render_coder_brief(None) == ""
    text = render_coder_brief(_rich_brief())
    assert "# 人工建模预备（实现红线）" in text
    assert "禁止硬编码" in text
    assert "F=ma" in text


def test_render_discussions_for_group_filters_by_group():
    brief = _rich_brief()
    model_text = render_discussions_for_group(brief, "model")
    assert "参数假设" in model_text
    assert "结论讨论" not in model_text
    conclusion_text = render_discussions_for_group(brief, "conclusion")
    assert "结论讨论" in conclusion_text
    assert "参数假设" not in conclusion_text


# ---------------------------------------------------------------------------
# auto_fill_ids / assemble_brief
# ---------------------------------------------------------------------------

def test_auto_fill_ids_reference_direction_list_str_preserved():
    items = ["文献A", "文献B"]
    assert auto_fill_ids(items, "reference_direction") == items


def test_assemble_brief_reference_direction_preserved():
    payload = assemble_brief(
        {"reference_direction": ["巷道支护", "Winkler 地基"]},
        problem_id="p1",
    )
    assert payload["reference_direction"] == ["巷道支护", "Winkler 地基"]
    ModelingBrief.model_validate(payload)

# ---------------------------------------------------------------------------
# draft_field 草稿清洗（reference_direction 字符串化；其余字段只收 dict）
# ---------------------------------------------------------------------------

def _fake_complete(monkeypatch, items):
    from types import SimpleNamespace

    def fake_complete(prompt, schema=None, system=None, model=None):
        return SimpleNamespace(items=items)

    monkeypatch.setattr("math_agent.llm.complete", fake_complete)


def test_draft_field_reference_direction_dict_content_extracted(monkeypatch):
    _fake_complete(monkeypatch, [
        {"id": "1.1-direction", "content": "锚杆预紧力矩与预紧力关系"},
        "巷道支护",
    ])
    out = draft_field("reference_direction", "ctx", model="m")
    assert out == ["锚杆预紧力矩与预紧力关系", "巷道支护"]


def test_draft_field_reference_direction_all_invalid_returns_none(monkeypatch):
    _fake_complete(monkeypatch, [{"id": "x", "content": 3}, 42])
    assert draft_field("reference_direction", "ctx", model="m") is None


def test_draft_field_reference_direction_empty_list_returns_none(monkeypatch):
    _fake_complete(monkeypatch, [])
    assert draft_field("reference_direction", "ctx", model="m") is None


def test_draft_field_other_field_drops_non_dict(monkeypatch):
    _fake_complete(monkeypatch, [
        {"id": "a", "direction": "MILP"},
        "junk-string",
        None,
    ])
    out = draft_field("per_question_direction", "ctx", model="m")
    assert out == [{"id": "a", "direction": "MILP"}]


def test_auto_fill_ids_assigns_missing_ids():
    result = auto_fill_ids(
        [{"question_id": "q1", "direction": "MILP"}],
        "per_question_direction",
    )
    assert result[0]["id"] == "q1-direction"


# ---------------------------------------------------------------------------
# Prompt 直测
# ---------------------------------------------------------------------------

def test_analyst_prompt_with_brief_contains_block():
    brief = _minimal_brief()
    prompt = analyst_build_prompt("题", "", ["小问1"], brief=brief)
    assert "# 人工建模预备（Modeling Brief）" in prompt
    assert "dir-q1" in prompt


def test_analyst_prompt_without_brief_excludes_block():
    prompt = analyst_build_prompt("题", "", ["小问1"], brief=None)
    assert "# 人工建模预备（Modeling Brief）" not in prompt


def test_modeler_prompt_with_brief_contains_block():
    brief = _minimal_brief()
    prompt = modeler_build_prompt(
        "题", [], None, "basic", brief=brief,
        blueprint=ProblemBlueprint(core_task="t"),
    )
    assert "# 人工建模预备" in prompt
    assert "MILP" in prompt


def test_modeler_prompt_without_brief_excludes_block():
    prompt = modeler_build_prompt(
        "题", [], None, "basic", brief=None,
        blueprint=ProblemBlueprint(core_task="t"),
    )
    assert "# 人工建模预备" not in prompt


def test_coder_figure_one_prompt_with_brief_contains_block():
    model = ModelVersion(stage="basic", description="d", equations=["x=1"], variables={"x": "v"})
    brief = _rich_brief()
    prompt = build_prompt_figure_one(model, "fig1", brief=brief)
    assert "# 人工建模预备" in prompt
    assert "禁止硬编码" in prompt


def test_coder_figure_one_prompt_without_brief_excludes_block():
    model = ModelVersion(stage="basic", description="d", equations=["x=1"], variables={"x": "v"})
    prompt = build_prompt_figure_one(model, "fig1", brief=None)
    assert "# 人工建模预备" not in prompt


def test_model_critic_prompt_with_brief_contains_block():
    model = ModelVersion(stage="basic", description="d", equations=["x=1"], variables={"x": "v"})
    brief = _rich_brief()
    prompt = model_critic_build_prompt("题", [], model, brief=brief)
    assert "# 人工建模预备" in prompt
    assert "F=ma" in prompt


def test_model_critic_prompt_without_brief_excludes_block():
    model = ModelVersion(stage="basic", description="d", equations=["x=1"], variables={"x": "v"})
    prompt = model_critic_build_prompt("题", [], model, brief=None)
    assert "# 人工建模预备" not in prompt


def test_writer_section_prompt_with_brief_contains_discussions():
    brief = _rich_brief()
    state = MathModelingState(problem="p", brief=brief)
    outline = WriterOutline()
    prompt = build_section_prompt("model", state, outline)
    assert "人工建模预备要求" in prompt
    assert "参数假设" in prompt


def test_writer_section_prompt_without_brief_excludes_block():
    state = MathModelingState(problem="p", brief=None)
    outline = WriterOutline()
    prompt = build_section_prompt("model", state, outline)
    assert "# 人工建模预备" not in prompt
    assert "人工建模预备要求" not in prompt
