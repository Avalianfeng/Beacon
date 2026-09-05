"""门禁停机交棒包：聚合 critic issues，给本地 agent 手改依据。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from math_agent.config import (
    MIN_MODEL_CODE_SCORE,
    MIN_MODEL_CRITIC_SCORE,
    MIN_PAPER_CRITIC_SCORE,
)
from math_agent.state import MathModelingState


def infer_gate_node(state: MathModelingState, gate_reason: str) -> str:
    if "coder LLM" in gate_reason:
        return "coder"
    if "sensitivity" in gate_reason:
        return "sensitivity"
    if gate_reason.startswith("hard ") or gate_reason.startswith("code_verify"):
        return "model_code_consistency"
    if "brief_coverage" in gate_reason or "blueprint_critic" in gate_reason:
        return "blueprint_critic"
    if "model_critic" in gate_reason:
        return "model_critic"
    if "paper" in gate_reason or "论文" in gate_reason:
        return "paper_critic"
    if getattr(state, "sensitivity_phase", "") == "stop":
        return "sensitivity"
    # fallback：看最近报告
    if state.model_code_reports:
        last = state.model_code_reports[-1]
        if not (last.approved and last.score >= MIN_MODEL_CODE_SCORE):
            return "model_code_consistency"
    paper_c = state.latest_critic("paper")
    if paper_c is not None and not (
        paper_c.approved and paper_c.score >= MIN_PAPER_CRITIC_SCORE
    ):
        return "paper_critic"
    return "unknown"


def infer_handoff_action(
    gate_reason: str,
    gate_node: str,
    *,
    plan_injected: bool = False,
) -> str:
    if gate_node == "sensitivity":
        return "edit_code"
    if gate_node == "model_code_consistency" or "coder LLM" in gate_reason:
        return "edit_code"
    if gate_node in {"blueprint_critic", "model_critic"} or "brief_coverage" in gate_reason:
        return "edit_plan" if plan_injected else "edit_brief"
    if gate_node == "paper_critic":
        if "论文关键 section 为空" in gate_reason:
            return "edit_paper"
        return "edit_paper"  # 或 review_takeover；命令里两行都给
    return "new_run"


def build_next_commands(
    out: Path,
    *,
    gate_node: str,
    handoff_action: str,
    thread: str = "default",
) -> list[str]:
    out_s = str(out)
    cmds: list[str] = []
    if handoff_action == "edit_code":
        cmds.append(
            "# 改 source/reference 或 source/inject/sensitivity.py 后必须重登记"
        )
        cmds.append(
            "math-agent reference add --problem <problem.json> "
            "--solver problems/<id>/source/reference --entry _entry.py --force"
        )
        cmds.append(
            f'math-agent restart --out {out_s} --thread {thread} '
            f'--from coder --reason "手改代码后放行"'
        )
    elif handoff_action == "edit_plan":
        cmds.append(
            "# 改 plan.json / brief.json 后请新开 run（勿 restart；输入戳会拒）"
        )
        cmds.append(
            "math-agent run --problem <problem.json> --brief <brief.json> "
            "--plan <plan.json> --out <new-run>"
        )
    elif handoff_action == "edit_brief":
        cmds.append(
            f"# 改 brief 后请新开 run（勿 recover 旧 checkpoint）"
        )
        cmds.append(
            f"math-agent run --problem <problem.json> --brief <brief.json> --out <new-run>"
        )
    elif handoff_action in {"edit_paper", "review_takeover"}:
        cmds.append(
            f'math-agent restart --out {out_s} --thread {thread} '
            f'--from writer --reason "按 paper_critic 意见重写"'
        )
        cmds.append(
            f"math-agent review --out {out_s} --thread {thread}"
        )
    else:
        cmds.append(f"math-agent status --out {out_s}")
    cmds.append(f"math-agent critic-handoff --out {out_s} --thread {thread}")
    return cmds


def build_critic_handoff(
    state: MathModelingState,
    *,
    out: Path,
    gate_reason: str,
    thread: str = "default",
) -> dict[str, Any]:
    gate_node = infer_gate_node(state, gate_reason)
    action = infer_handoff_action(
        gate_reason, gate_node, plan_injected=bool(state.plan_injected),
    )

    critic_payload = None
    if gate_node == "blueprint_critic":
        c = state.latest_critic("analyst", critic_type="blueprint")
        if c is not None:
            critic_payload = c.model_dump()
    elif gate_node == "model_critic":
        c = state.latest_critic("modeler")
        if c is not None:
            critic_payload = c.model_dump()
    elif gate_node == "paper_critic":
        c = state.latest_critic("paper")
        if c is not None:
            critic_payload = c.model_dump()

    consistency_payload = None
    if state.model_code_reports:
        consistency_payload = state.model_code_reports[-1].model_dump()

    primary = [
        a for a in state.latest_code_artifacts()
        if a.success and a.evidence_role == "primary"
    ]
    stdout_tail = ""
    stderr_snips: list[str] = []
    if primary:
        stdout_tail = (primary[-1].stdout or "")[-2000:]
        err = (primary[-1].stderr or "").strip()
        if err:
            stderr_snips.append(err[-800:])

    payload: dict[str, Any] = {
        "schema_version": 1,
        "run_id": out.name,
        "thread": thread,
        "gate_reason": gate_reason,
        "gate_node": gate_node,
        "thresholds": {
            "min_model_critic_score": MIN_MODEL_CRITIC_SCORE,
            "min_model_code_score": MIN_MODEL_CODE_SCORE,
            "min_paper_critic_score": MIN_PAPER_CRITIC_SCORE,
        },
        "critic": critic_payload,
        "consistency": consistency_payload,
        "blueprint_gate_problems": list(state.blueprint_gate_problems or []),
        "code_context": {
            "has_primary": bool(primary),
            "latest_stderr_snippets": stderr_snips,
            "latest_stdout_tail": stdout_tail,
        },
        "artifact_paths": {
            "paper_md": str(out / "paper.md"),
            "brief_json": str(out / "brief.json"),
            "insight_dir": str(out / "insights"),
            "gate_diagnostics": str(out / "gate_diagnostics.json"),
            "state_summary": str(out / "state_summary.json"),
            "critic_handoff": str(out / "critic-handoff.json"),
        },
        "handoff_action": action,
        "next_commands": build_next_commands(
            out, gate_node=gate_node, handoff_action=action, thread=thread,
        ),
    }
    return payload


def write_critic_handoff(out: Path, payload: dict[str, Any]) -> Path:
    path = out / "critic-handoff.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
    # 短 md 方便人扫
    md = out / "critic-handoff.md"
    lines = [
        f"# Critic 交棒 · {payload.get('run_id')}",
        "",
        f"- gate_reason: `{payload.get('gate_reason')}`",
        f"- gate_node: `{payload.get('gate_node')}`",
        f"- handoff_action: **{payload.get('handoff_action')}**",
        "",
        "## next_commands",
        "",
    ]
    for cmd in payload.get("next_commands") or []:
        lines.append(f"```\n{cmd}\n```")
        lines.append("")
    critic = payload.get("critic")
    if critic and critic.get("issues"):
        lines.append("## critic.issues")
        lines.append("")
        for issue in critic["issues"]:
            if isinstance(issue, dict):
                lines.append(f"- [{issue.get('section', 'general')}] {issue.get('problem', '')}")
            else:
                lines.append(f"- {issue}")
        lines.append("")
    consistency = payload.get("consistency")
    if consistency and consistency.get("issues"):
        lines.append("## consistency.issues")
        lines.append("")
        for issue in consistency["issues"]:
            lines.append(f"- {issue}")
        lines.append("")
    md.write_text("\n".join(lines), encoding="utf-8")
    return path


def maybe_write_critic_handoff_from_checkpoint(
    out: Path,
    thread: str,
    *,
    gate_reason_fn,
    build_graph_fn,
    saver_cm,
    config_fn,
) -> Path | None:
    """run/restart 结束后：若门禁停机则写交棒包。"""
    try:
        with saver_cm(out) as saver:
            g = build_graph_fn(checkpointer=saver)
            snap = g.get_state(config_fn(thread))
            if snap is None or not snap.values:
                return None
            if snap.next:
                return None  # 未停机
            state = MathModelingState.model_validate(snap.values)
            reason = gate_reason_fn(state)
            if not reason or reason == "quality gate 停机":
                # 仍写，但 reason 保留
                reason = reason or "quality gate 停机"
            # 终态完成则不写
            fin = getattr(state, "finalization", None)
            if fin is not None and getattr(fin, "status", None) in {
                "completed", "degraded", "failed",
            }:
                return None
            payload = build_critic_handoff(
                state, out=out, gate_reason=reason, thread=thread,
            )
            return write_critic_handoff(out, payload)
    except Exception:
        return None
