"""run --from writer 冷启动播种测试（无 LLM）。"""
from __future__ import annotations

import json
from pathlib import Path

from math_agent.cli import _config, _saver_cm
from math_agent.graph import build_graph
from math_agent.state import (
    CriticReport,
    MathModelingState,
    PaperSections,
)


def _install_writer_fakes(monkeypatch):
    calls = {"writer": 0, "section": 0, "paper_critic": 0}

    def fake_writer(state: MathModelingState):
        calls["writer"] += 1
        return {
            "writer_section_queue": ["abstract", "solution"],
            "writer_outline_dump": {"sections": {}},
            "writer_iteration": 1,
        }

    def fake_section(state: MathModelingState):
        calls["section"] += 1
        q = list(state.writer_section_queue)
        name = q.pop(0) if q else "abstract"
        paper = state.paper.model_dump()
        paper[name if name in paper else "abstract"] = f"text-{name}"
        if name == "solution":
            paper["abstract"] = paper.get("abstract") or "abs"
            paper["model_section"] = paper.get("model_section") or "model"
            paper["solution"] = "sol"
            paper["conclusion"] = paper.get("conclusion") or "conc"
        return {"writer_section_queue": q, "paper": PaperSections(**paper)}

    def fake_paper_critic(state: MathModelingState):
        calls["paper_critic"] += 1
        return {
            "critic_reports": [
                CriticReport(target="paper", score=3, approved=False, issues=[]),
            ],
        }

    monkeypatch.setattr("math_agent.graph.writer_node", fake_writer)
    monkeypatch.setattr("math_agent.graph.writer_section_node", fake_section)
    monkeypatch.setattr("math_agent.graph.paper_critic_node", fake_paper_critic)
    return calls


def test_seed_from_writer_reaches_paper_critic_stop(tmp_path, monkeypatch):
    from math_agent.adapters.evidence_to_state import build_writer_state

    out = tmp_path / "run"
    out.mkdir()
    calls = _install_writer_fakes(monkeypatch)
    evidence = {
        "q_lines": ["Q1: x=1", "RESULT: baseline=ours x=1"],
        "entry": "reference/_entry.py",
    }
    state = build_writer_state(
        problem_spec={"title": "t", "questions": ["q1"], "data_files": [], "data_dir": ""},
        brief=None,
        evidence=evidence,
        output_dir=out,
    )
    values = state.model_dump()
    values["figure_phase"] = "done"

    with _saver_cm(out) as saver:
        g = build_graph(checkpointer=saver)
        cfg = _config("default")
        g.update_state(cfg, values, as_node="figure_analysis")
        snap = g.get_state(cfg)
        assert snap.next == ("writer",), f"播种后应为 writer，实际 {snap.next}"
        g.invoke(None, config=cfg)
        snap2 = g.get_state(cfg)

    assert calls["writer"] == 1
    assert calls["section"] == 2
    assert calls["paper_critic"] == 1
    assert snap2.next == (), f"paper_critic 未过应 stop，实际 {snap2.next}"


def test_run_from_writer_cli_seeds(tmp_path, monkeypatch):
    from typer.testing import CliRunner
    from math_agent.cli import app

    out = tmp_path / "run"
    problem = tmp_path / "problem.json"
    problem.write_text(
        json.dumps({"title": "t", "background": "", "questions": ["q1"], "data_files": [], "data_dir": ""}),
        encoding="utf-8",
    )
    evidence = tmp_path / "evidence.json"
    evidence.write_text(
        json.dumps({"q_lines": ["Q1: a=1", "RESULT: baseline=ours a=1"]}),
        encoding="utf-8",
    )
    _install_writer_fakes(monkeypatch)
    # CLI imports build_graph from math_agent.graph — fakes already on graph module attrs
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "run",
            "--problem", str(problem),
            "--out", str(out),
            "--from", "writer",
            "--evidence", str(evidence),
            "--no-interrupt",
            "--force",
        ],
    )
    assert result.exit_code == 0, result.output
    manifest = json.loads((out / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest.get("entry") == "writer"
    assert (out / "critic-handoff.json").is_file() or "paper_critic" in result.output
