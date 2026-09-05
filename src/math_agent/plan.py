"""plan.json：研究收束的机读蓝图+模型卡（复用 model-card schema）。

``plan build`` 从 brief 合成 v0（coverage 带小问/方程锚）。
``plan check`` 零 token 对照 critic / coverage 硬门会打回的缺口。
``run --plan`` 播种到 analyst 产出位；敏感性数字不从本文件进图。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from math_agent.adapters.evidence_to_state import apply_model_card, load_model_card
from math_agent.brief import (
    BriefCoverageItem,
    ModelingBrief,
    _BRIEF_ITEM_FIELDS,
    brief_coverage_problems,
    brief_item_ids,
)
from math_agent.state import (
    Assumption,
    ConstraintSpec,
    DataFileInfo,
    MathModelingState,
    MetricSpec,
    ModelQuestionCoverage,
    ModelVersion,
    ObjectiveSpec,
    ProblemBlueprint,
    SubQuestionBlueprint,
    ValidationPlanItem,
)


def load_plan(path: Path | str | dict) -> dict[str, Any]:
    if isinstance(path, dict):
        return path
    return load_model_card(path)


def _guess_task_type(text: str) -> str:
    low = (text or "").lower()
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
        if key in text or key in low:
            return typ
    return "generic"


def _item_question_id(item: Any) -> str:
    qid = str(getattr(item, "question_id", "") or "").strip()
    if qid:
        return qid
    match = re.match(r"^(\d+)", str(getattr(item, "id", "") or ""))
    return match.group(1) if match else ""


def _formula_ids_for_question(brief: ModelingBrief, question_id: str) -> list[str]:
    if not question_id:
        return [item.id for item in brief.formula_notes[:3]]
    matched = [item.id for item in brief.formula_notes if item.question_id == question_id]
    return matched or [item.id for item in brief.formula_notes[:1]]


def build_anchored_coverage(brief: ModelingBrief) -> list[BriefCoverageItem]:
    """每条 brief 条目锚到小问 id 与公式 id，默认 followed。"""
    out: list[BriefCoverageItem] = []
    for field_name in _BRIEF_ITEM_FIELDS:
        for item in getattr(brief, field_name):
            qid = _item_question_id(item)
            eq_ids: list[str] = []
            q_ids = [qid] if qid else []
            if field_name == "formula_notes":
                eq_ids = [item.id]
                if not q_ids and item.question_id:
                    q_ids = [item.question_id]
            else:
                eq_ids = _formula_ids_for_question(brief, qid)
            if not q_ids and not eq_ids:
                eq_ids = [f"anchor:{item.id}"]
            snippet = ""
            for attr in ("direction", "note", "statement", "text", "title", "rule"):
                val = getattr(item, attr, None)
                if isinstance(val, str) and val.strip():
                    snippet = val.strip().replace("\n", " ")[:160]
                    break
            reason = snippet or (
                f"followed：条目 {item.id} 锚到小问 {q_ids or ['—']}、方程 {eq_ids}"
            )
            out.append(
                BriefCoverageItem(
                    brief_item_id=item.id,
                    status="followed",
                    reason=reason,
                    question_ids=q_ids,
                    equation_ids=eq_ids,
                )
            )
    return out


def _subquestions_from_brief(
    brief: ModelingBrief,
    questions: list[str] | None,
) -> list[SubQuestionBlueprint]:
    texts = list(questions or [])
    out: list[SubQuestionBlueprint] = []
    for item in brief.per_question_direction:
        qid = (item.question_id or item.id or "").strip() or str(len(out) + 1)
        idx = None
        if qid.isdigit():
            idx = int(qid) - 1
        original = ""
        if idx is not None and 0 <= idx < len(texts):
            original = texts[idx]
        out.append(
            SubQuestionBlueprint(
                id=qid,
                original_text=original or item.direction[:400],
                task_type=_guess_task_type(item.direction),  # type: ignore[arg-type]
                expected_output=item.direction[:240],
            )
        )
    if out:
        return out
    for i, text in enumerate(texts, start=1):
        out.append(
            SubQuestionBlueprint(
                id=str(i),
                original_text=text,
                task_type="generic",
            )
        )
    return out


def build_plan_v0(
    brief: ModelingBrief,
    *,
    questions: list[str] | None = None,
    title: str = "",
) -> dict[str, Any]:
    """brief → plan v0。变量表/验证区间等留给研究者补；coverage 已带锚。"""
    subq = _subquestions_from_brief(brief, questions)
    coverage = build_anchored_coverage(brief)
    formulas = list(brief.formula_notes)
    equations = [f.note for f in formulas if f.note] or [
        r"\text{results from registered solver}"
    ]
    eq_ids = [f.id for f in formulas] or ["eq:main"]
    variables: dict[str, str] = {}
    question_coverage: list[ModelQuestionCoverage] = []
    for sq in subq:
        related = [f.id for f in formulas if f.question_id == sq.id] or eq_ids[:1]
        dirs = [d.direction for d in brief.per_question_direction if d.question_id == sq.id]
        how = dirs[0] if dirs else f"覆盖小问 {sq.id}"
        question_coverage.append(
            ModelQuestionCoverage(
                question_id=sq.id,
                how_answered=how[:400],
                related_equations=related,
            )
        )
        for fid in related:
            note = next((f.note for f in formulas if f.id == fid), "")
            if note and fid not in variables:
                variables[fid] = note[:160]

    directions = [d.direction for d in brief.per_question_direction if d.direction]
    description = "；".join(directions[:4]) if directions else (title or "plan v0 from brief")
    objectives = [
        ObjectiveSpec(
            direction="evaluate" if "分布" in d.direction or d.question_id == "1" else "maximize",
            description=d.direction[:240],
        )
        for d in brief.per_question_direction
    ] or [ObjectiveSpec(direction="evaluate", description=description[:240])]
    constraints = [
        ConstraintSpec(description=r.prohibition[:240], source="assumed")
        for r in brief.red_lines[:8]
    ]
    metrics = [
        MetricSpec(name="RESULT", meaning="主方案 stdout 指标", direction="neutral")
    ]
    validation_plan = [
        ValidationPlanItem(
            target="主方案数字",
            method="冻结脚本 stdout 的 Q*/RESULT 行",
            pass_criteria="",  # 故意留空：plan check 会标缺口
        )
    ]
    blueprint = ProblemBlueprint(
        core_task=(title or description)[:400],
        subquestions=subq,
        decision_variables=[],
        objectives=objectives,
        constraints=constraints,
        metrics=metrics,
        validation_plan=validation_plan,
        brief_coverage=coverage,
        assumptions=[
            Assumption(
                statement=item.topic or item.requirement or item.id,
                rationale=f"required_discussions:{item.id}",
            )
            for item in brief.required_discussions
            if "假设" in (item.topic or "") or "assumption" in item.id.lower()
        ],
    )
    model = ModelVersion(
        stage="final",
        description=description[:800],
        equations=equations,
        variables=variables,
        notes=(
            "plan v0：coverage 已锚到小问/公式 id。"
            "决策变量、验证区间、映射请手补后再 plan check。"
            "敏感数字不以本文件为准，由图内 inject/sensitivity.py 重跑。"
        ),
        figure_purposes=[f.figure for f in brief.figure_plan[:6]],
        question_coverage=question_coverage,
        objective_mapping=[o.description for o in objectives],
        constraint_mapping=[c.description for c in constraints],
        validation_mapping=[],
    )
    assumptions = list(blueprint.assumptions) or [
        Assumption(
            statement="以图内 coder_execute stdout 为论文数字唯一来源",
            rationale="plan inject",
        )
    ]
    return {
        "schema": "model-card",
        "assumptions": [a.model_dump() for a in assumptions],
        "model_versions": [model.model_dump()],
        "problem_blueprint": blueprint.model_dump(),
        "problem_domains": ["operations_research"],
        "sensitivity_runs": [],
        "notes": (
            "sensitivity_runs 仅作研究参考，不进图状态。"
            "论文敏感性节数字由 source/inject/sensitivity.py 图内重跑产生。"
        ),
    }


@dataclass
class PlanCheckResult:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def _coverage_anchor_gaps(
    brief: ModelingBrief | None, blueprint: ProblemBlueprint
) -> list[str]:
    if brief is None:
        return []
    by_id = {c.brief_item_id: c for c in blueprint.brief_coverage or []}
    gaps: list[str] = []
    for item_id in brief_item_ids(brief):
        cov = by_id.get(item_id)
        if cov is None:
            continue
        if cov.status != "followed":
            continue
        if not (cov.question_ids or cov.equation_ids):
            gaps.append(
                f"brief_coverage[{item_id}] followed 但无 question_ids/equation_ids 锚"
            )
    return gaps


def check_plan(
    card: dict[str, Any],
    *,
    brief: ModelingBrief | None = None,
) -> PlanCheckResult:
    result = PlanCheckResult()
    try:
        assumptions, models, blueprint, _sens, _domains = apply_model_card(card)
    except (ValueError, Exception) as exc:
        result.errors.append(f"plan 无法按 model-card 解析：{exc}")
        return result

    if not blueprint.decision_variables:
        result.errors.append("blueprint.decision_variables 为空（blueprint_critic 会打回）")
    if not blueprint.objectives:
        result.errors.append("blueprint.objectives 为空")
    if not blueprint.constraints:
        result.errors.append("blueprint.constraints 为空")
    if not blueprint.validation_plan:
        result.errors.append("blueprint.validation_plan 为空")
    elif any(not (item.pass_criteria or "").strip() for item in blueprint.validation_plan):
        result.errors.append(
            "blueprint.validation_plan 缺 pass_criteria（一致性 critic 用它查数量级）"
        )
    if not blueprint.subquestions:
        result.errors.append("blueprint.subquestions 为空")

    final = next((m for m in reversed(models) if m.stage == "final"), None)
    if final is None:
        result.errors.append("缺少 stage=final 的 model_versions")
        return result
    if not final.equations:
        result.errors.append("final model.equations 为空")
    if not final.variables:
        result.errors.append("final model.variables 为空")
    if not final.question_coverage:
        result.errors.append("final model.question_coverage 为空")
    else:
        covered = {c.question_id for c in final.question_coverage}
        for sq in blueprint.subquestions:
            if sq.id not in covered:
                result.errors.append(f"question_coverage 未覆盖小问 {sq.id}")
            else:
                cov = next(c for c in final.question_coverage if c.question_id == sq.id)
                if not cov.related_equations:
                    result.errors.append(
                        f"question_coverage[{sq.id}] 缺 related_equations"
                    )
    if not final.objective_mapping:
        result.errors.append("final model.objective_mapping 为空")
    if not final.constraint_mapping:
        result.errors.append("final model.constraint_mapping 为空")
    if not final.validation_mapping:
        result.errors.append("final model.validation_mapping 为空")

    if brief is not None:
        result.errors.extend(brief_coverage_problems(brief, blueprint))
        result.errors.extend(_coverage_anchor_gaps(brief, blueprint))
    else:
        result.warnings.append("未提供 brief，跳过 brief_coverage 硬门预检")

    if not assumptions:
        result.warnings.append("assumptions 为空")
    if card.get("sensitivity_runs"):
        result.warnings.append(
            "plan.sensitivity_runs 只作研究参考，不会进图；"
            "论文敏感数字须由 source/inject/sensitivity.py 重跑"
        )
    return result


def write_plan(path: Path | str, card: dict[str, Any]) -> Path:
    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(
        json.dumps(card, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return dest


def build_plan_state(
    *,
    problem_spec: dict,
    brief: ModelingBrief,
    plan: dict | Path | str,
    output_dir: Path | str,
    problem_text: str | None = None,
) -> MathModelingState:
    """播种用 state：蓝图+final 模型进产出位；不带 code_artifact / 敏感 run。"""
    card = load_plan(plan)
    assumptions, models, blueprint, _sens, domains = apply_model_card(card)
    if not blueprint.brief_coverage:
        blueprint.brief_coverage = build_anchored_coverage(brief)
    title = problem_spec.get("title") or ""
    questions = list(problem_spec.get("questions") or [])
    if problem_text is None:
        problem_text = title + ("\n" + "\n".join(questions) if questions else "")
    data_dir = problem_spec.get("data_dir") or None
    data_files = [DataFileInfo(**f) for f in problem_spec.get("data_files") or []]
    final_models = [m for m in models if m.stage == "final"] or models
    return MathModelingState(
        problem=problem_text or "",
        background=problem_spec.get("background") or "",
        questions=questions,
        brief=brief,
        assumptions=assumptions,
        model_versions=final_models,
        problem_blueprint=blueprint,
        problem_domains=domains or ["operations_research"],
        output_dir=str(output_dir),
        data_dir=str(data_dir) if data_dir else None,
        data_files=data_files,
        allow_coder_llm=False,
        plan_injected=True,
        stage_target="final",
        modeler_phase="done",
        sensitivity_runs=[],
        sensitivity_formal_parameters=[],
    )
