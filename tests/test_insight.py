from pathlib import Path

from math_agent.insight import extract_insight, read_latest_meta, record_node_insight
from math_agent.state import CriticIssue, CriticReport, ModelCodeConsistencyReport


def test_extract_skips_phase_only_delta():
    assert extract_insight("coder", {"coder_phase": "generate"}) is None


def test_extract_critic_report_text():
    report = CriticReport(
        target="modeler",
        score=6,
        approved=False,
        stage="final",
        issues=[CriticIssue(section="model_section", problem="约束未闭合")],
        suggestions=["补上容量约束"],
    )
    snap = extract_insight("model_critic", {"critic_reports": [report]})
    assert snap is not None
    assert "未通过" in snap["headline"]
    assert "约束未闭合" in snap["body"]
    assert "补上容量约束" in snap["body"]


def test_extract_coder_execute_failure_without_code():
    snap = extract_insight("coder_execute", {
        "coder_phase": "generate",
        "coder_work_artifacts": [{
            "purpose": "fig 1",
            "success": False,
            "stderr": "ValueError: NaN in cost",
            "stdout": "ok",
            "code": "print('secret-source')",
            "evidence_role": "none",
        }],
        "coder_work_queue": [{"kind": "figure", "attempt": 2, "prev_err": "ValueError: NaN in cost"}],
    })
    assert snap is not None
    assert "执行失败" in snap["headline"]
    assert "NaN in cost" in snap["body"]
    assert "secret-source" not in snap["body"]


def test_record_steps_are_ordered_and_timestamped(tmp_path: Path):
    from math_agent.insight import read_recent_steps, record_llm_result, record_node_result

    record_node_result(tmp_path, "model_critic", {
        "critic_reports": [{"target": "modeler", "score": 8, "approved": True, "issues": [], "suggestions": []}],
    })
    record_llm_result(
        tmp_path,
        node="coder_generate",
        model="openai/deepseek-v4-flash",
        content='{"purpose":"fig","code":"print(1)"}',
        parsed={"purpose": "fig", "code": "print(1)"},
        schema="CoderDraft",
        prompt_chars=120,
        completion_tokens=20,
    )
    rows = read_recent_steps(tmp_path)
    assert [row["node"] for row in rows] == ["model_critic", "coder_generate"]
    dirs = list((tmp_path / "steps").iterdir())
    named = [p.name for p in dirs if p.is_dir()]
    assert any(name.startswith("0001_model_critic_") for name in named)
    assert any(name.startswith("0002_coder_generate_") for name in named)
    output = (tmp_path / "steps" / next(p.name for p in dirs if p.is_dir() and p.name.startswith("0002_")) / "output.json")
    text = output.read_text(encoding="utf-8")
    assert "print(1)" in text
    assert "system prompt" not in text.lower()
    assert '"reasoning_chars"' in text


def test_record_writes_markdown_and_latest(tmp_path: Path):
    report = ModelCodeConsistencyReport(
        score=8,
        approved=True,
        missing_variables=["x_i"],
        issues=[],
        suggestions=["核对符号表"],
    )
    record_node_insight(tmp_path, "model_code_consistency", {
        "model_code_reports": [report],
    })
    latest = tmp_path / "insights" / "latest.md"
    assert latest.is_file()
    text = latest.read_text(encoding="utf-8")
    assert "缺失变量" in text
    assert "x_i" in text
    meta = read_latest_meta(tmp_path)
    assert meta is not None
    assert meta["node"] == "model_code_consistency"
    assert "通过" in meta["headline"]
