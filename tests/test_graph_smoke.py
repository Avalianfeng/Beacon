from PIL import Image
from pathlib import Path

from math_agent.graph import build_graph
from math_agent.state import (
    Assumption, ModelVersion, CriticReport, CriticIssue, PaperSections,
    EvaluationReport, HumanDecision, DerivationStep, ProblemBlueprint,
    ModelCodeConsistencyReport,
)
from math_agent.nodes.analyst import AnalystOutput
from math_agent.nodes.coder import CoderDraft
from math_agent.nodes.sensitivity import SensitivityPlan, SensitivityCode, Interpretations
from math_agent.nodes.figure_pipeline import FigureCriticOut, FigureAnalysisOut
from math_agent.prompts.modeler_derivation import ConsistencyCheck


def _png(p: Path):
    p.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (320, 240), "white").save(p)
    return str(p)


def _full_mocks(mocker, workdir, *, stages=("basic", "improved", "final"), critics=None):
    """给所有 LLM 节点装上桩，保证 graph 端到端能跑通。"""
    mocker.patch.dict("os.environ", {"MATH_AGENT_ALLOW_CODER_LLM": "1"})
    mocker.patch("math_agent.nodes.analyst.complete",
                 return_value=ProblemBlueprint(
                     core_task="test task",
                     assumptions=[
                         Assumption(statement="A", rationale="r", sensitivity_relevant=True)],
                     problem_domains=["optimization"],
                 ))

    # blueprint_critic 审查通过
    mocker.patch("math_agent.nodes.blueprint_critic.complete",
                 return_value=CriticReport(target="analyst", score=9, approved=True, critic_type="blueprint"))

    stage_iter = iter(stages)

    def _modeler_complete(prompt, *, schema, **kw):
        # final 阶段会额外调用 derivation steps + consistency gate，
        # 需按请求的 schema 返回正确类型，否则解析出错。
        if schema is ModelVersion:
            return ModelVersion(stage=next(stage_iter), description="d" * 200)
        if schema is DerivationStep:
            return DerivationStep(title="step", motivation="m", statement="s", result="r")
        if schema is ConsistencyCheck:
            return ConsistencyCheck(coherent=True, issues=[])
        return ModelVersion(stage="basic", description="d" * 200)

    mocker.patch("math_agent.nodes.modeler.complete", side_effect=_modeler_complete)

    crit_iter = iter(critics) if critics else None
    if crit_iter is not None:
        mocker.patch("math_agent.nodes.model_critic.complete",
                     side_effect=lambda *a, **k: next(crit_iter))
    else:
        mocker.patch("math_agent.nodes.model_critic.complete",
                     return_value=CriticReport(target="modeler", score=9, approved=True))

    mocker.patch("math_agent.nodes.coder.complete",
                 return_value=CoderDraft(
                     purpose="ok",
                     code=(
                         "import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt\n"
                         "plt.plot([1, 2], [3, 4]); plt.savefig('main_result.png')\n"
                         "for name, cost in [('ours', 100), ('no_schedule', 110), "
                         "('simple_pred', 105), ('greedy', 120)]:\n"
                         " print(f'RESULT: baseline={name} T_max={cost} K=0.18')"
                     ),
                 ))

    # model_code_consistency 审查通过
    mocker.patch("math_agent.nodes.model_code_consistency.complete",
                 return_value=ModelCodeConsistencyReport(score=9, approved=True))

    sens_plan = SensitivityPlan(runs=[{"parameter": "speed_multiplier", "values": [0.8, 1.0, 1.2],
                                       "metric": "total_cost", "rationale": "r"}])
    sens_code = SensitivityCode(code=(
        "import matplotlib\nmatplotlib.use('Agg')\nimport matplotlib.pyplot as plt\n"
        "v=[0.8,1.0,1.2]; r=[100,100,100]\n"
        "plt.plot(v,r); plt.savefig('speed_multiplier.png')\n"
        "print(f'RESULT: parameter=speed_multiplier values={v} results={r}')\n"
    ))
    sens_interp = Interpretations(interpretations=["速度扰动下总成本保持稳定。"])

    def _sensitivity_complete(prompt, *, schema, **kw):
        if schema is SensitivityPlan:
            return sens_plan
        if schema is SensitivityCode:
            return sens_code
        if schema is Interpretations:
            return sens_interp
        raise AssertionError(f"unexpected sensitivity schema: {schema}")

    mocker.patch("math_agent.nodes.sensitivity.complete",
                 side_effect=_sensitivity_complete)

    def _figure_complete(prompt, *, schema, **kw):
        if schema is FigureCriticOut:
            return FigureCriticOut(score=9, approved=True)
        return FigureAnalysisOut(analysis="趋势单调，敏感度中等。")

    mocker.patch("math_agent.nodes.figure_pipeline.complete",
                 side_effect=_figure_complete)

    mocker.patch("math_agent.nodes.writer.complete",
                 return_value=PaperSections(
                     abstract="x"*300, problem_restatement="x"*1600,
                     keywords="建模、优化", assumptions="x"*1600,
                     notation="x"*600, model_section="x"*4500,
                     solution="x"*2800, sensitivity="x"*1800,
                     conclusion="x"*1600, references="参考文献"*40,
                 ))
    mocker.patch("math_agent.nodes.paper_critic.complete",
                 return_value=CriticReport(target="paper", score=9, approved=True))
    mocker.patch("math_agent.nodes.evaluation.complete",
                 return_value=EvaluationReport(
                     assumption_reasonableness=8, modeling_creativity=8,
                     result_correctness=8, writing_clarity=8, extra_depth=8, overall=8.0,
                 ))
    mocker.patch("math_agent.nodes.latex_node.compile_latex",
                 return_value=type("R", (), {"success": True, "pdf_path": "", "log": ""})())


def test_graph_runs_full_modeling_loop(mocker, workdir):
    _full_mocks(mocker, workdir)
    g = build_graph()
    final = g.invoke({
        "problem": "p", "stage_target": "basic", "iteration": 0,
        "output_dir": str(workdir),
        "human_decision": HumanDecision(approved=True),
    })
    stages = [m.stage for m in final["model_versions"]]
    assert stages == ["basic", "improved", "final"]


def test_graph_stops_modeler_on_low_score(mocker, workdir):
    """basic 阶段 critic 不通过：立即 stop，不在同阶段重试 modeler。"""
    critics = [
        CriticReport(target="modeler", score=4, approved=False),
    ]
    _full_mocks(mocker, workdir, stages=("basic",), critics=critics)
    g = build_graph()
    final = g.invoke({
        "problem": "p", "stage_target": "basic", "iteration": 0,
        "output_dir": str(workdir),
        "human_decision": HumanDecision(approved=True),
    })
    basic_versions = [m for m in final["model_versions"] if m.stage == "basic"]
    basic_critics = [c for c in final["critic_reports"] if c.stage == "basic"]
    assert len(basic_versions) == 1
    assert len(basic_critics) == 1
    assert basic_critics[0].approved is False
    assert not any(m.stage == "final" for m in final["model_versions"])


def test_graph_writes_paper_md(mocker, workdir):
    _full_mocks(mocker, workdir)
    g = build_graph()
    g.invoke({
        "problem": "single bike", "stage_target": "basic", "iteration": 0,
        "output_dir": str(workdir),
        "human_decision": HumanDecision(approved=True),
    })
    assert (workdir / "paper.md").exists()
    assert (workdir / "paper.tex").exists()
    md = (workdir / "paper.md").read_text(encoding="utf-8")
    assert "## 摘要" in md
    assert "## 6. 敏感性分析" in md


def test_writer_paper_critic_stops_on_first_reject(mocker):
    """隔离测试：paper_critic 首次未过立即 stop，不自动重开 writer。"""
    from langgraph.graph import StateGraph, END
    from math_agent.state import MathModelingState as _S
    from math_agent.nodes.writer import writer_node, writer_section_node
    from math_agent.nodes.paper_critic import paper_critic_node
    from math_agent.routing import after_paper_critic, after_writer_step
    from math_agent.prompts.writer_section import (
        WriterOutline, writer_sections, schema_for_group,
        _AbstractProblemOut, _AssumptionsNotationOut,
        _ModelOut, _SolutionOut, _SensitivityOut, _ConclusionOut, _ReferencesOut,
    )

    def _section_out(schema, mk):
        if schema is _AbstractProblemOut:
            return _AbstractProblemOut(
                abstract=mk*150, problem_restatement="x"*1600, keywords="建模、优化")
        if schema is _AssumptionsNotationOut:
            return _AssumptionsNotationOut(assumptions="x"*1600, notation="x"*600)
        if schema is _ModelOut:
            return _ModelOut(model_section="x"*4500)
        if schema is _SolutionOut:
            return _SolutionOut(solution="x"*2800)
        if schema is _SensitivityOut:
            return _SensitivityOut(sensitivity="x"*1800)
        if schema is _ConclusionOut:
            return _ConclusionOut(conclusion="x"*1600)
        if schema is _ReferencesOut:
            return _ReferencesOut(references="参考文献"*40)
        return None

    def _writer_complete(prompt, *, schema, **kw):
        if schema is WriterOutline:
            return WriterOutline(abstract="v1")
        return _section_out(schema, "v1")

    mocker.patch("math_agent.nodes.writer.complete", side_effect=_writer_complete)
    mocker.patch("math_agent.nodes.paper_critic.complete", side_effect=[
        CriticReport(target="paper", score=4, approved=False,
                     issues=[CriticIssue(problem="编数字")], suggestions=["改定性"]),
    ])

    g = StateGraph(_S)
    g.add_node("writer", writer_node)
    g.add_node("writer_section", writer_section_node)
    g.add_node("paper_critic", paper_critic_node)
    g.set_entry_point("writer")
    g.add_conditional_edges("writer", after_writer_step,
                            {"section": "writer_section", "done": "paper_critic"})
    g.add_conditional_edges("writer_section", after_writer_step,
                            {"section": "writer_section", "done": "paper_critic"})
    g.add_conditional_edges("paper_critic", after_paper_critic,
                            {"advance": END, "stop": END})
    compiled = g.compile()

    final = compiled.invoke({
        "problem": "p",
        "critic_reports": [
            CriticReport(
                target="modeler", stage="final", score=8, approved=True,
            ),
        ],
        "model_code_reports": [
            ModelCodeConsistencyReport(score=8, approved=True),
        ],
    })
    assert final["writer_iteration"] == 1
    paper_critics = [r for r in final["critic_reports"] if r.target == "paper"]
    assert len(paper_critics) == 1
    assert paper_critics[0].approved is False


def test_graph_has_table_assembler_node():
    """table_assembler 必须在 paper_critic 和 evaluation 之间。"""
    from math_agent.graph import build_graph
    g = build_graph()
    # 构建后的 graph 节点名可通过 .nodes 访问
    assert "table_assembler" in g.nodes
    assert "evaluation" in g.nodes
    assert "paper_critic" in g.nodes


def test_graph_commits_outputs_through_finalizer():
    g = build_graph()
    assert "latex" in g.nodes
    assert "finalizer" in g.nodes
