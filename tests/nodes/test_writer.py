from math_agent.nodes.writer import (
    _build_section_fallback,
    _build_sensitivity_text,
    _result_evidence,
    _should_use_deterministic_writer,
    render_markdown,
)
from math_agent.state import (
    CodeArtifact,
    MathModelingState,
    ModelVersion,
    SensitivityRun,
)


def _state() -> MathModelingState:
    return MathModelingState(
        problem="p",
        model_versions=[
            ModelVersion(
                stage="final",
                description="车辆路径与充电联合优化",
                equations=[r"\min C=\sum_{i,j}c_{ij}x_{ij}"],
                variables={"x_i_j": "车辆是否经过弧(i,j)的0-1变量"},
            )
        ],
        code_artifacts=[
            CodeArtifact(
                purpose="求解",
                code="",
                stdout=(
                    "RESULT: baseline=ours total_cost=123.4 service_rate=0.98\n"
                    r"saved=plot.png data_dir=C:\Users\demo\problem"
                ),
                success=True,
                batch=1,
            )
        ],
        sensitivity_runs=[
            SensitivityRun(
                parameter="c_v_dist",
                values=[0.8, 1.0, 1.2],
                metric="total_cost",
                results=[100.0, 110.0, 125.0],
                interpretation="成本随距离系数上升。",
            )
        ],
    )


def test_deterministic_writer_is_explicit_only(monkeypatch):
    monkeypatch.delenv("MATH_AGENT_WRITER_DETERMINISTIC", raising=False)
    assert not _should_use_deterministic_writer()
    monkeypatch.setenv("MATH_AGENT_WRITER_DETERMINISTIC", "1")
    assert _should_use_deterministic_writer()


def test_fallback_text_has_real_newlines_and_no_encoding_pollution():
    state = _state()
    for group in (
        "abstract_problem",
        "assumptions_notation",
        "model",
        "solution",
        "sensitivity",
        "conclusion",
        "references",
    ):
        output = _build_section_fallback(group, state)
        for value in output.model_dump().values():
            assert "???" not in value
            assert r"\n" not in value


def test_solution_evidence_excludes_machine_paths():
    state = _state()
    evidence = _result_evidence(state)
    assert evidence == ["RESULT: baseline=ours total_cost=123.4 service_rate=0.98"]
    assert "C:" not in "\n".join(evidence)


def test_sensitivity_names_are_markdown_code_not_raw_latex_identifiers():
    text = _build_sensitivity_text(_state())
    assert "`c_v_dist`" in text
    assert "`total_cost`" in text
    assert r"c\_v\_dist" not in text


def test_render_markdown_excludes_stale_supporting_metrics():
    state = _state()
    state.code_artifacts = [
        CodeArtifact(
            purpose="主求解", code="print('main')", success=True,
            evidence_role="primary",
            stdout="RESULT: baseline=ours total_cost=123.4 service_rate=0.98",
        ),
        CodeArtifact(
            purpose="旧补充图", code="print('stale')", success=True,
            evidence_role="supporting",
            stdout="RESULT: baseline=ours total_cost=999999 service_rate=0.01",
        ),
    ]

    markdown = render_markdown(state)

    assert "总成本=123.4" in markdown
    assert "999999" not in markdown
    assert "旧补充图" not in markdown


def test_render_markdown_demotes_embedded_section_headings():
    state = _state()
    state.paper.model_section = "## 问题一\n内容\n### 变量\n说明"

    markdown = render_markdown(state)

    assert "## 4. 模型的建立" in markdown
    assert "### 问题一" in markdown
    assert "#### 变量" in markdown
    assert "\n## 问题一" not in markdown
