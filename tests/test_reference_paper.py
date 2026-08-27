"""reference paper 摘要模板与表 spec 按题分派。"""
from math_agent.cli import (
    _DEFAULT_TABLES_SPEC,
    _load_paper_abstract_template,
    _load_tables_spec,
    _paper_question_ids,
)


def test_mcm51_c_default_abstract_when_no_override(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    template, _source = _load_paper_abstract_template("mcm51-c")
    assert "位移校正" in template
    assert "{q4_rmse}" in template


def test_non_c_generic_abstract_omits_c_content():
    questions = ["问题1：筛指标，含题面数字 7.132 不得拷进摘要"]
    q_fields = {"q1": {"phlegm_coef": 0.42}}
    template, source = _load_paper_abstract_template(
        "mathorcup16-c",
        questions=questions,
        q_fields=q_fields,
        result_ours={"q1_gain": 0.88},
    )
    assert "边坡" not in template
    assert "位移校正" not in template
    assert "q4_rmse" not in template
    assert "表1.1" not in template
    assert "7.132" not in template
    assert "问题一" in template
    assert "{q1.phlegm_coef}" in template
    assert "{q1_gain}" in template
    assert "按题生成" in source
    assert "非内置 C 题模板" in source


def test_generic_abstract_empty_fields_placeholder():
    template, _source = _load_paper_abstract_template(
        "mathorcup16-c",
        questions=["问题1：无 evidence"],
        q_fields={},
        result_ours={},
    )
    assert "【待展开：该问无 evidence 字段】" in template
    assert "问题一" in template


def test_generic_abstract_from_q_fields_when_no_questions():
    template, _source = _load_paper_abstract_template(
        "other-id",
        questions=None,
        q_fields={"q2": {"auc": 0.9}},
        result_ours={},
    )
    assert "问题二" in template
    assert "{q2.auc}" in template
    assert "问题一" not in template


def test_override_file_preferred(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    dest = tmp_path / "problems" / "foo"
    dest.mkdir(parents=True)
    (dest / "paper_abstract.md").write_text("自定义摘要 {q1.x}\n", encoding="utf-8")
    template, source = _load_paper_abstract_template(
        "foo",
        questions=["题面原文不应出现"],
        q_fields={"q1": {"phlegm_coef": 1}},
    )
    assert "自定义摘要 {q1.x}" in template
    assert "题面原文不应出现" not in template
    assert source == "problems/foo/paper_abstract.md"


def test_tables_spec_non_c_empty_without_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    spec, source = _load_tables_spec("mathorcup16-c")
    assert spec == {"tables": []}
    assert "无 tables.json" in source
    assert "不套用 C 题默认表" in source


def test_tables_spec_mcm51_c_default_without_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    spec, source = _load_tables_spec("mcm51-c")
    assert spec is _DEFAULT_TABLES_SPEC
    ids = [t["id"] for t in spec["tables"]]
    assert "table11" in ids
    assert "仅 mcm51-c 缺省" in source


def test_tables_spec_uses_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    dest = tmp_path / "problems" / "foo"
    dest.mkdir(parents=True)
    (dest / "tables.json").write_text(
        '{"tables": [{"id": "custom", "title": "自定义表"}]}',
        encoding="utf-8",
    )
    spec, source = _load_tables_spec("foo")
    assert spec["tables"][0]["id"] == "custom"
    assert "tables.json" in source.replace("\\", "/")
    assert spec is not _DEFAULT_TABLES_SPEC


def test_paper_question_ids_follow_questions_not_five():
    assert _paper_question_ids(["q1", "q2", "q3"], ["Q1: a=1", "Q2: b=2"]) == [
        "1",
        "2",
        "3",
    ]
    assert "4" not in _paper_question_ids(["only-one"], [])
    assert _paper_question_ids([], ["Q2: x=1", "Q1: y=2"]) == ["1", "2"]
