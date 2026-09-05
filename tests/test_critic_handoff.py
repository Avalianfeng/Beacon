"""critic-handoff 聚合单测（无 LLM）。"""
from __future__ import annotations

from pathlib import Path

from math_agent.critic_handoff import (
    build_critic_handoff,
    infer_handoff_action,
    write_critic_handoff,
)
from math_agent.state import (
    CriticIssue,
    CriticReport,
    MathModelingState,
    ModelCodeConsistencyReport,
    PaperSections,
)


def test_handoff_edit_code_for_consistency(tmp_path: Path):
    state = MathModelingState(
        problem="p",
        output_dir=str(tmp_path),
        model_code_reports=[
            ModelCodeConsistencyReport(
                score=3, approved=False, issues=["missing primary"],
            )
        ],
    )
    payload = build_critic_handoff(
        state, out=tmp_path, gate_reason="code_verify 无主证据",
    )
    assert payload["gate_node"] == "model_code_consistency"
    assert payload["handoff_action"] == "edit_code"
    assert payload["consistency"]["issues"] == ["missing primary"]
    assert any("restart" in c and "coder" in c for c in payload["next_commands"])
    assert any("reference add" in c and "--force" in c for c in payload["next_commands"])
    path = write_critic_handoff(tmp_path, payload)
    assert path.is_file()
    assert (tmp_path / "critic-handoff.md").is_file()


def test_handoff_edit_paper_for_paper_critic(tmp_path: Path):
    state = MathModelingState(
        problem="p",
        output_dir=str(tmp_path),
        paper=PaperSections(
            abstract="a", model_section="m", solution="s", conclusion="c",
        ),
        critic_reports=[
            CriticReport(
                target="paper",
                score=4,
                approved=False,
                issues=[CriticIssue(section="solution", problem="缺对照")],
            )
        ],
    )
    payload = build_critic_handoff(
        state, out=tmp_path, gate_reason="paper_critic 未通过",
    )
    assert payload["gate_node"] == "paper_critic"
    assert payload["handoff_action"] == "edit_paper"
    assert payload["critic"]["issues"][0]["problem"] == "缺对照"
    assert any("--from writer" in c for c in payload["next_commands"])
    assert infer_handoff_action("brief_coverage 缺口", "blueprint_critic") == "edit_brief"
    assert infer_handoff_action(
        "blueprint_critic 未通过", "blueprint_critic", plan_injected=True,
    ) == "edit_plan"


def test_handoff_edit_plan_when_injected(tmp_path: Path):
    state = MathModelingState(
        problem="p",
        output_dir=str(tmp_path),
        plan_injected=True,
        critic_reports=[
            CriticReport(target="modeler", score=3, approved=False, stage="final"),
        ],
    )
    payload = build_critic_handoff(
        state, out=tmp_path, gate_reason="model_critic 未通过",
    )
    assert payload["handoff_action"] == "edit_plan"
    assert any("--plan" in c for c in payload["next_commands"])
