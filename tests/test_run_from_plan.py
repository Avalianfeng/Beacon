"""run --plan 冷启动播种测试（无 LLM）。"""
from __future__ import annotations

import json
from pathlib import Path

from math_agent.brief import ModelingBrief, PerQuestionDirectionItem, FormulaNoteItem
from math_agent.cli import _config, _saver_cm
from math_agent.graph import build_graph
from math_agent.plan import build_plan_state, build_plan_v0
from math_agent.state import CriticReport, MathModelingState


def _tiny_brief() -> ModelingBrief:
    return ModelingBrief(
        schema_version=2,
        problem_id="t",
        per_question_direction=[
            PerQuestionDirectionItem(
                id="1-direction", question_id="1", direction="分布描述",
            )
        ],
        formula_notes=[
            FormulaNoteItem(id="1-eq", question_id="1", note="n = count"),
        ],
    )


def _filled_plan(brief: ModelingBrief) -> dict:
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
    return card


def _install_plan_fakes(monkeypatch):
    calls = {"blueprint": 0, "model_critic": 0, "coder": 0}

    def fake_blueprint(state: MathModelingState):
        calls["blueprint"] += 1
        return {
            "critic_reports": [
                CriticReport(
                    target="analyst", score=9, approved=True, critic_type="blueprint",
                )
            ],
            "blueprint_gate_problems": [],
        }

    def fake_model_critic(state: MathModelingState):
        calls["model_critic"] += 1
        return {
            "critic_reports": [
                CriticReport(target="modeler", score=9, approved=True, stage="final"),
            ]
        }

    def fake_coder(state: MathModelingState):
        calls["coder"] += 1
        return {"coder_phase": "done", "coder_work_queue": []}

    def boom(*_a, **_k):
        raise AssertionError("modeler 不应调用 LLM")

    monkeypatch.setattr("math_agent.graph.blueprint_critic_node", fake_blueprint)
    monkeypatch.setattr("math_agent.graph.model_critic_node", fake_model_critic)
    monkeypatch.setattr("math_agent.graph.coder_prepare_node", fake_coder)
    monkeypatch.setattr("math_agent.nodes.modeler.complete", boom)
    return calls


def test_seed_from_plan_reaches_coder_without_modeler_llm(tmp_path, monkeypatch):
    out = tmp_path / "run"
    out.mkdir()
    brief = _tiny_brief()
    card = _filled_plan(brief)
    state = build_plan_state(
        problem_spec={"title": "t", "questions": ["第一问"], "data_files": [], "data_dir": ""},
        brief=brief,
        plan=card,
        output_dir=out,
    )
    assert state.plan_injected is True
    assert state.stage_target == "final"
    values = state.model_dump()
    calls = _install_plan_fakes(monkeypatch)

    with _saver_cm(out) as saver:
        g = build_graph(checkpointer=saver)
        cfg = _config("default")
        g.update_state(cfg, values, as_node="analyst")
        snap = g.get_state(cfg)
        assert snap.next == ("blueprint_critic",), f"播种后应为 blueprint_critic，实际 {snap.next}"
        g.invoke(None, config=cfg)
        snap2 = g.get_state(cfg)

    assert calls["blueprint"] == 1
    assert calls["model_critic"] == 1
    assert calls["coder"] == 1
    # 无一致性报告 → 停在 END
    assert snap2.next == ()


def test_run_plan_cli_seeds(tmp_path, monkeypatch):
    from typer.testing import CliRunner
    from math_agent.cli import app

    brief = _tiny_brief()
    card = _filled_plan(brief)
    problem = tmp_path / "problem.json"
    problem.write_text(
        json.dumps({"title": "t", "background": "", "questions": ["第一问"], "data_files": [], "data_dir": ""}),
        encoding="utf-8",
    )
    brief_path = tmp_path / "brief.json"
    brief_path.write_text(brief.model_dump_json(), encoding="utf-8")
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(card, ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "run"
    _install_plan_fakes(monkeypatch)
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "run",
            "--problem", str(problem),
            "--brief", str(brief_path),
            "--plan", str(plan_path),
            "--out", str(out),
            "--no-interrupt",
            "--force",
        ],
    )
    assert result.exit_code == 0, result.output
    manifest = json.loads((out / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest.get("entry") == "plan"
    assert manifest.get("plan_sha256")
    assert (out / "plan.json").is_file()
