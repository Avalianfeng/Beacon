"""evidence.json + brief → MathModelingState（writer 冷启动接桥）。"""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from typing import Any

from math_agent.brief import ModelingBrief, load_brief
from math_agent.state import (
    Assumption,
    CodeArtifact,
    DataFileInfo,
    MathModelingState,
    ModelVersion,
    ProblemBlueprint,
    SensitivityRun,
    SubQuestionBlueprint,
)

_TASK_TYPES = frozenset({
    "evaluation", "prediction", "optimization", "simulation",
    "classification", "explanation", "strategy", "generic",
})


def load_evidence(path: Path | str | dict) -> dict:
    if isinstance(path, dict):
        return path
    raw = Path(path).read_text(encoding="utf-8")
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("evidence.json 根必须是 object")
    return data


def build_code_stdout(evidence: dict) -> str:
    """仅拼接 q_lines（含 Q*/RESULT）。不把 evidence.md 拼进 stdout。"""
    lines = evidence.get("q_lines") or []
    if not isinstance(lines, list):
        raise ValueError("evidence.q_lines 必须是 list")
    return "\n".join(str(x) for x in lines)


def _parse_listish(raw: str) -> list[float] | None:
    text = raw.strip()
    try:
        val = ast.literal_eval(text)
    except (SyntaxError, ValueError):
        return None
    if not isinstance(val, (list, tuple)) or not val:
        return None
    out: list[float] = []
    for item in val:
        try:
            out.append(float(item))
        except (TypeError, ValueError):
            return None
    return out


def parse_sensitivity_from_q_lines(q_lines: list[str]) -> list[SensitivityRun]:
    """从约定字段解析敏感性；解析不了则跳过，不编造。"""
    runs: list[SensitivityRun] = []
    joined = "\n".join(q_lines)
    # markup_p=[25,50,75] markup_profit=[a,b,c]
    m_p = re.search(r"markup_p\s*=\s*(\[[^\]]+\])", joined)
    m_profit = re.search(r"markup_profit\s*=\s*(\[[^\]]+\])", joined)
    if m_p and m_profit:
        values = _parse_listish(m_p.group(1))
        results = _parse_listish(m_profit.group(1))
        if values and results and len(values) == len(results):
            runs.append(
                SensitivityRun(
                    parameter="markup_percentile",
                    values=values,
                    metric="week_profit",
                    results=results,
                    interpretation="从 evidence q_lines 的 markup_p/markup_profit 解析",
                )
            )
    # cost_shock_pct=20 与对称结果：若有 cost_shock_profit=[-/0/+] 类字段则解析
    m_shock = re.search(r"cost_shock_profit\s*=\s*(\[[^\]]+\])", joined)
    m_pct = re.search(r"cost_shock_pct\s*=\s*([0-9.]+)", joined)
    if m_shock and m_pct:
        results = _parse_listish(m_shock.group(1))
        try:
            pct = float(m_pct.group(1)) / (100.0 if float(m_pct.group(1)) > 1 else 1.0)
        except ValueError:
            pct = None
        if results and pct is not None and len(results) == 3:
            runs.append(
                SensitivityRun(
                    parameter="cost_shock",
                    values=[-pct, 0.0, pct],
                    metric="week_profit",
                    results=results,
                    interpretation="从 evidence q_lines 的 cost_shock_* 解析",
                )
            )
    return runs


def _guess_task_type(direction: str) -> str:
    low = direction.lower()
    for key, typ in (
        ("优化", "optimization"),
        ("预测", "prediction"),
        ("评价", "evaluation"),
        ("评估", "evaluation"),
        ("分类", "classification"),
        ("模拟", "simulation"),
        ("策略", "strategy"),
        ("解释", "explanation"),
        ("分布", "explanation"),
    ):
        if key in direction or key in low:
            return typ
    return "generic"


def minimal_model_card_from_brief(
    brief: ModelingBrief | None,
    *,
    questions: list[str] | None = None,
) -> tuple[list[Assumption], list[ModelVersion], ProblemBlueprint, list[str]]:
    """够 writer 吃的最小模型卡（可被 --model-card 覆盖）。"""
    assumptions: list[Assumption] = []
    if brief:
        for item in brief.required_discussions:
            if "assumption" in (item.id or "").lower() or "假设" in (item.topic or ""):
                assumptions.append(
                    Assumption(
                        statement=item.topic or item.requirement or item.id,
                        rationale=item.requirement or "from brief required_discussions",
                        sensitivity_relevant=False,
                    )
                )
        for item in brief.formula_notes[:6]:
            assumptions.append(
                Assumption(
                    statement=item.note[:240],
                    rationale=f"formula_notes:{item.id}",
                    sensitivity_relevant=False,
                )
            )
    if not assumptions:
        assumptions = [
            Assumption(
                statement="以 evidence 登记的计算结果为论文数值唯一来源",
                rationale="writer 接桥默认假设",
                sensitivity_relevant=False,
            )
        ]

    directions = list(brief.per_question_direction) if brief else []
    formulas = list(brief.formula_notes) if brief else []
    desc_parts = [d.direction for d in directions[:4] if d.direction]
    description = "；".join(desc_parts) if desc_parts else "本地 evidence 接桥：按 brief/题面写作"
    equations = [f.note for f in formulas[:8] if f.note] or [
        r"\text{results from registered evidence}"
    ]
    model = ModelVersion(
        stage="final",
        description=description[:800],
        equations=equations,
        variables={},
        notes="数字唯一来自 reference evidence；禁止编造。",
        objective_mapping=[d.direction for d in directions[:4] if d.direction],
        constraint_mapping=[r.prohibition for r in (brief.red_lines if brief else [])[:4]],
        validation_mapping=[],
        question_coverage=[],
    )

    subquestions: list[SubQuestionBlueprint] = []
    if directions:
        for d in directions:
            qid = (d.question_id or d.id or "").strip() or str(len(subquestions) + 1)
            subquestions.append(
                SubQuestionBlueprint(
                    id=qid,
                    original_text=d.direction[:200] or qid,
                    task_type=_guess_task_type(d.direction),  # type: ignore[arg-type]
                    expected_output="",
                )
            )
    elif questions:
        for i, q in enumerate(questions, start=1):
            subquestions.append(
                SubQuestionBlueprint(
                    id=str(i),
                    original_text=q[:200],
                    task_type="generic",
                    expected_output="",
                )
            )
    else:
        subquestions.append(
            SubQuestionBlueprint(
                id="1",
                original_text="主问题",
                task_type="generic",
                expected_output="",
            )
        )

    # 校正非法 task_type
    fixed: list[SubQuestionBlueprint] = []
    for sq in subquestions:
        tt = sq.task_type if sq.task_type in _TASK_TYPES else "generic"
        fixed.append(sq.model_copy(update={"task_type": tt}))

    blueprint = ProblemBlueprint(
        core_task=description[:400] or "建模求解",
        subquestions=fixed,
    )
    domains = ["operations_research"]
    return assumptions, [model], blueprint, domains


def load_model_card(path: Path | str) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("model-card 根必须是 object")
    return data


def apply_model_card(
    card: dict[str, Any],
) -> tuple[list[Assumption], list[ModelVersion], ProblemBlueprint, list[SensitivityRun], list[str]]:
    assumptions = [Assumption.model_validate(x) for x in card.get("assumptions") or []]
    models = [ModelVersion.model_validate(x) for x in card.get("model_versions") or []]
    if not models and card.get("model"):
        models = [ModelVersion.model_validate(card["model"])]
    bp_raw = card.get("problem_blueprint") or card.get("blueprint")
    if bp_raw is None:
        raise ValueError("model-card 缺少 problem_blueprint")
    blueprint = ProblemBlueprint.model_validate(bp_raw)
    sens = [SensitivityRun.model_validate(x) for x in card.get("sensitivity_runs") or []]
    domains = list(card.get("problem_domains") or ["operations_research"])
    if not assumptions:
        assumptions = [
            Assumption(statement="model-card 未提供 assumptions", rationale="override"),
        ]
    if not models:
        raise ValueError("model-card 缺少 model_versions")
    return assumptions, models, blueprint, sens, domains


def validate_writer_state(state: MathModelingState) -> list[str]:
    """无 LLM 门禁：缺啥列啥。"""
    issues: list[str] = []
    if not (state.problem or "").strip():
        issues.append("problem 为空")
    primary = [
        a for a in state.code_artifacts
        if a.success and a.evidence_role == "primary"
    ]
    if not primary:
        issues.append("缺少 success 的 primary code_artifact")
    else:
        stdout = primary[-1].stdout or ""
        if "RESULT:" not in stdout and not re.search(r"^Q\d+:", stdout, re.M):
            issues.append("primary stdout 缺少 Q*/RESULT 行")
    if not state.model_versions:
        issues.append("model_versions 为空")
    if state.problem_blueprint is None or not state.problem_blueprint.subquestions:
        issues.append("problem_blueprint.subquestions 为空")
    return issues


def build_writer_state(
    *,
    problem_spec: dict,
    brief: ModelingBrief | Path | str | None,
    evidence: dict | Path | str,
    output_dir: Path | str,
    model_card: dict | Path | str | None = None,
    reference_entry: str | None = None,
    problem_text: str | None = None,
) -> MathModelingState:
    """主入口：evidence + brief + problem → 可喂 writer / 图冷启动的 state。"""
    ev = load_evidence(evidence)
    brief_obj: ModelingBrief | None
    if brief is None:
        brief_obj = None
    elif isinstance(brief, ModelingBrief):
        brief_obj = brief
    else:
        brief_obj = load_brief(Path(brief))

    title = problem_spec.get("title") or ""
    questions = list(problem_spec.get("questions") or [])
    if problem_text is None:
        problem_text = title + ("\n" + "\n".join(questions) if questions else "")
        md_path = problem_spec.get("problem_md")
        # 若旁路有 problem.md 路径约定，调用方可直接传 problem_text
        if not problem_text.strip() and isinstance(md_path, str):
            p = Path(md_path)
            if p.is_file():
                problem_text = p.read_text(encoding="utf-8")

    stdout = build_code_stdout(ev)
    entry = reference_entry or ev.get("entry") or "reference/_entry.py"
    data_dir = problem_spec.get("data_dir") or None
    data_files = [DataFileInfo(**f) for f in problem_spec.get("data_files") or []]

    if model_card is not None:
        card = model_card if isinstance(model_card, dict) else load_model_card(model_card)
        assumptions, models, blueprint, sens, domains = apply_model_card(card)
    else:
        assumptions, models, blueprint, domains = minimal_model_card_from_brief(
            brief_obj, questions=questions,
        )
        sens = parse_sensitivity_from_q_lines(list(ev.get("q_lines") or []))

    formal = [r.parameter for r in sens]

    state = MathModelingState(
        problem=problem_text or "",
        background=problem_spec.get("background") or "",
        questions=questions,
        brief=brief_obj,
        assumptions=assumptions,
        model_versions=models,
        problem_blueprint=blueprint,
        problem_domains=domains,
        code_artifacts=[
            CodeArtifact(
                purpose=f"frozen reference: {entry}",
                code=f"# see {entry}",
                stdout=stdout,
                success=True,
                evidence_role="primary",
                category="figure",
                batch=1,
            )
        ],
        sensitivity_runs=sens,
        sensitivity_formal_parameters=formal,
        data_dir=str(data_dir) if data_dir else None,
        data_files=data_files,
        output_dir=str(output_dir),
        allow_coder_llm=False,
        figure_phase="done",
    )
    return state
