"""Modeling Brief（建模预备）：人机协同前置阶段的产物与校验。

定位（与《体系流程优化报告》A2 一致）：
- brief 是 run 的可选输入（``run --brief brief.json``），在流水线之外由人机对话产生，
  可沉淀为 ``problems/<题号>/brief.json`` 跨题复用；
- 流水线内**不评审 brief 的方向正确性**（方向只在前置对话中定，方向错了的反馈回路
  是回到前置对话修订 brief 重跑），只做两件事：
  1. 把 brief 作为约束注入各 prompt（analyst / blueprint_critic / model_critic /
     modeler / coder / writer）；
  2. ``brief_coverage`` 门禁：确定性校验 analyst 的 ProblemBlueprint 是否逐条回应了
     brief（传递完整性校验、防忽略，不依赖 LLM 判断）。

优先级：题面 > brief > 预训练直觉；brief 与题面冲突时以题面为准，并在
``brief_coverage`` 中标注"偏离 + 理由"。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

# ---------------------------------------------------------------------------
# 八字段条目模型：每条目带稳定 id，供 brief_coverage 逐条引用（门禁确定性的前提）
# ---------------------------------------------------------------------------


class PerQuestionDirectionItem(BaseModel):
    id: str
    question_id: str = ""
    direction: str          # 建模类型指引
    forbidden: str = ""     # 明确禁止的方向


class FormulaNoteItem(BaseModel):
    id: str
    question_id: str = ""
    note: str               # 公式原文 / 参数选择注意


class RequiredDiscussionItem(BaseModel):
    id: str
    sections: list[str] = Field(default_factory=list)  # 论文章节白名单
    topic: str              # 必须体现的讨论点
    requirement: str = ""   # 具体写法要求（如"必须声明参数化假设非唯一"）


class RedLineItem(BaseModel):
    id: str
    question_id: str = ""
    prohibition: str        # 方向性错误红线（禁止清单）


class FigurePlanItem(BaseModel):
    id: str
    question_id: str = ""
    figure: str             # 必做图名称
    requirements: str = ""  # 标注/元素要求


class ScoringNoteItem(BaseModel):
    id: str
    question_id: str = ""
    note: str               # 评分标准要点（分值分布/容差/参考区间）


class DataNoteItem(BaseModel):
    id: str
    question_id: str = ""
    note: str               # 数据注意（均值化/范围/缺失处理）


_BRIEF_ITEM_FIELDS = (
    "per_question_direction",
    "formula_notes",
    "required_discussions",
    "red_lines",
    "figure_plan",
    "scoring_notes",
    "data_notes",
)

# required_discussions.sections 白名单（与 PaperSections 章节名一致）
_SECTION_WHITELIST = frozenset({
    "abstract", "problem_restatement", "assumptions", "notation",
    "model_section", "solution", "sensitivity", "conclusion", "references",
})


class ModelingBrief(BaseModel):
    """建模预备 brief：8 个内容字段 + 元信息。"""

    schema_version: int = 1
    problem_id: str = ""
    created_at: str = ""
    # 来源分级约定：official_standard（官方文件）> human（人工整理）> model_draft（模型推演）
    source: list[str] = Field(default_factory=list)
    per_question_direction: list[PerQuestionDirectionItem] = Field(default_factory=list)
    formula_notes: list[FormulaNoteItem] = Field(default_factory=list)
    required_discussions: list[RequiredDiscussionItem] = Field(default_factory=list)
    red_lines: list[RedLineItem] = Field(default_factory=list)
    figure_plan: list[FigurePlanItem] = Field(default_factory=list)
    scoring_notes: list[ScoringNoteItem] = Field(default_factory=list)
    data_notes: list[DataNoteItem] = Field(default_factory=list)
    reference_direction: list[str] = Field(default_factory=list)

    @field_validator("schema_version")
    @classmethod
    def _check_version(cls, value: int) -> int:
        if value != 1:
            raise ValueError(f"不支持的 brief schema_version={value}（当前仅支持 1）")
        return value

    @model_validator(mode="after")
    def _check_unique_ids(self) -> "ModelingBrief":
        ids = brief_item_ids(self)
        if len(ids) != len(set(ids)):
            raise ValueError(f"brief 条目 id 必须唯一，重复：{sorted({i for i in ids if ids.count(i) > 1})}")
        return self

    @model_validator(mode="after")
    def _check_discussion_sections(self) -> "ModelingBrief":
        bad: list[str] = []
        for item in self.required_discussions:
            for section in item.sections:
                if section not in _SECTION_WHITELIST:
                    bad.append(f"{item.id}: {section}")
        if bad:
            raise ValueError(
                f"required_discussions.sections 必须是白名单之一"
                f"（{sorted(_SECTION_WHITELIST)}），违规：{bad}"
            )
        return self


class BriefCoverageItem(BaseModel):
    """analyst 对 brief 单一条目的回应（位于 ProblemBlueprint.brief_coverage）。"""

    brief_item_id: str
    status: Literal["followed", "deviated"]
    reason: str = ""  # deviated 时必须非空


# ---------------------------------------------------------------------------
# 读取与校验
# ---------------------------------------------------------------------------


def load_brief(path: str | Path) -> ModelingBrief:
    """读取并校验 brief.json；失败抛出 ValueError（含路径与原因）。"""
    p = Path(path)
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"brief 文件不是有效的 UTF-8 JSON（{p}）：{exc}") from exc
    try:
        return ModelingBrief.model_validate(raw)
    except ValidationError as exc:
        raise ValueError(f"brief 文件不符合 schema（{p}）：{exc}") from exc


def brief_item_ids(brief: ModelingBrief | None) -> list[str]:
    """收集 brief 全部条目 id（按字段声明顺序）。"""
    if brief is None:
        return []
    ids: list[str] = []
    for field_name in _BRIEF_ITEM_FIELDS:
        for item in getattr(brief, field_name):
            ids.append(item.id)
    return ids


def brief_coverage_problems(brief: ModelingBrief | None, blueprint) -> list[str]:
    """确定性门禁：brief 每条目必须在 blueprint.brief_coverage 中逐条回应。

    - brief 为 None → 通过（向后兼容，无 brief 不设门禁）；
    - status=followed → 通过；status=deviated → reason 非空 → 通过（显式偏离）；
    - 条目缺失或 deviated 无理由 → 记问题。

    纯函数，不调用 LLM；供 routing.after_blueprint_critic 使用。
    """
    if brief is None:
        return []
    if blueprint is None:
        return ["ProblemBlueprint 缺失，无法校验 brief_coverage"]
    covered = {item.brief_item_id: item for item in (blueprint.brief_coverage or [])}
    problems: list[str] = []
    for item_id in brief_item_ids(brief):
        entry = covered.get(item_id)
        if entry is None:
            problems.append(f"brief 条目 {item_id} 未在 blueprint.brief_coverage 中回应")
        elif entry.status == "deviated" and not (entry.reason or "").strip():
            problems.append(f"brief 条目 {item_id} 声明偏离但未给出理由")
    return problems


# ---------------------------------------------------------------------------
# prompt 渲染（各注入点按需取用；容量控制：整块 ≤1500 字符级）
# ---------------------------------------------------------------------------


def _qid(item) -> str:
    return f"（问题 {item.question_id}）" if getattr(item, "question_id", "") else ""


def render_full_brief(brief: ModelingBrief | None) -> str:
    """完整 brief 块：analyst / blueprint_critic 注入用。"""
    if brief is None:
        return ""
    lines = [
        "# 人工建模预备（Modeling Brief）",
        "> 以下为人工确认的建模方向约束。优先级：题面 > brief > 预训练直觉；"
        "brief 与题面冲突时以题面为准，并在 brief_coverage 中标注“偏离+理由”。",
    ]
    if brief.source:
        lines.append(f"> 来源分级：{' > '.join(brief.source)}")
    if brief.per_question_direction:
        lines.append("\n## 逐题方向")
        for item in brief.per_question_direction:
            line = f"- [{item.id}]{_qid(item)} 方向：{item.direction}"
            if item.forbidden:
                line += f"；禁止：{item.forbidden}"
            lines.append(line)
    if brief.formula_notes:
        lines.append("\n## 公式注意")
        for item in brief.formula_notes:
            lines.append(f"- [{item.id}]{_qid(item)} {item.note}")
    if brief.required_discussions:
        lines.append("\n## 论文必须体现的讨论点")
        for item in brief.required_discussions:
            where = f"（章节：{', '.join(item.sections)}）" if item.sections else ""
            line = f"- [{item.id}]{where} {item.topic}"
            if item.requirement:
                line += f"；要求：{item.requirement}"
            lines.append(line)
    if brief.red_lines:
        lines.append("\n## 红线（禁止清单）")
        for item in brief.red_lines:
            lines.append(f"- [{item.id}]{_qid(item)} 禁止：{item.prohibition}")
    if brief.figure_plan:
        lines.append("\n## 图表规划")
        for item in brief.figure_plan:
            line = f"- [{item.id}]{_qid(item)} {item.figure}"
            if item.requirements:
                line += f"；要求：{item.requirements}"
            lines.append(line)
    if brief.scoring_notes:
        lines.append("\n## 评分标准要点")
        for item in brief.scoring_notes:
            lines.append(f"- [{item.id}]{_qid(item)} {item.note}")
    if brief.data_notes:
        lines.append("\n## 数据注意")
        for item in brief.data_notes:
            lines.append(f"- [{item.id}]{_qid(item)} {item.note}")
    if brief.reference_direction:
        lines.append("\n## 参考文献方向")
        for item in brief.reference_direction:
            lines.append(f"- {item}")
    return "\n".join(lines)


def _dimension_note_lines() -> list[str]:
    """M5（单位/量纲口径，prompt 层）：modeler/coder 渲染器共用的量纲要求块。"""
    return [
        "## 单位/量纲口径（必须遵循）",
        "- 数值必须携带并匹配物理单位；应力/力矩/力不得混比（如 MPa 应力 vs kN·m 力矩）",
        "- 同一物理量全篇口径一致（力统一 kN 或 N，换算必须明确）；求解章口径必须与模型章一致",
    ]


def render_modeler_brief(brief: ModelingBrief | None) -> str:
    """modeler 注入：逐题方向 + 公式注意（路线选择约束）。"""
    if brief is None:
        return ""
    lines = ["# 人工建模预备（方向与公式约束）"]
    if brief.per_question_direction:
        lines.append("## 逐题方向")
        for item in brief.per_question_direction:
            line = f"- [{item.id}]{_qid(item)} 方向：{item.direction}"
            if item.forbidden:
                line += f"；禁止：{item.forbidden}"
            lines.append(line)
    if brief.formula_notes:
        lines.append("## 公式注意")
        for item in brief.formula_notes:
            lines.append(f"- [{item.id}]{_qid(item)} {item.note}")
    lines.extend(_dimension_note_lines())
    if not lines[1:]:
        return ""
    return "\n".join(lines)


def render_coder_brief(brief: ModelingBrief | None) -> str:
    """coder 注入：红线 + 公式注意（实现级硬约束）。"""
    if brief is None:
        return ""
    lines = ["# 人工建模预备（实现红线）"]
    if brief.red_lines:
        lines.append("## 红线（违反即失败，必须避开）")
        for item in brief.red_lines:
            lines.append(f"- [{item.id}]{_qid(item)} 禁止：{item.prohibition}")
    if brief.formula_notes:
        lines.append("## 公式与参数注意（实现必须遵循）")
        for item in brief.formula_notes:
            lines.append(f"- [{item.id}]{_qid(item)} {item.note}")
    lines.extend(_dimension_note_lines())
    if not lines[1:]:
        return ""
    return "\n".join(lines)


def render_critic_brief(brief: ModelingBrief | None) -> str:
    """model_critic 注入：公式注意 + 红线作为实现级评审基准（不评审方向本身）。"""
    if brief is None:
        return ""
    lines = ["# 人工建模预备（实现级评审基准）"]
    if brief.formula_notes:
        lines.append("## 公式注意（模型违反记 issue）")
        for item in brief.formula_notes:
            lines.append(f"- [{item.id}]{_qid(item)} {item.note}")
    if brief.red_lines:
        lines.append("## 红线（模型/推导触碰记 issue）")
        for item in brief.red_lines:
            lines.append(f"- [{item.id}]{_qid(item)} 禁止：{item.prohibition}")
    if not lines[1:]:
        return ""
    return "\n".join(lines)


# 分组名 → 论文章节（writer_section 分组与 PaperSections 章节的映射）
_GROUP_TO_SECTIONS: dict[str, tuple[str, ...]] = {
    "abstract_problem": ("abstract", "problem_restatement"),
    "assumptions_notation": ("assumptions", "notation"),
    "model": ("model_section",),
    "solution": ("solution",),
    "sensitivity": ("sensitivity",),
    "conclusion": ("conclusion",),
    "references": ("references",),
}


def render_discussions_for_group(
    brief: ModelingBrief | None, group_name: str
) -> str:
    """writer 分节注入：按分组过滤 required_discussions（命中任一章节目录即注入）。"""
    if brief is None:
        return ""
    group_sections = _GROUP_TO_SECTIONS.get(group_name, ())
    items = [
        item for item in brief.required_discussions
        if not item.sections or any(s in group_sections for s in item.sections)
    ]
    if not items:
        return ""
    lines = ["## 人工建模预备要求（讨论点必须体现）"]
    for item in items:
        line = f"- [{item.id}] {item.topic}"
        if item.requirement:
            line += f"；要求：{item.requirement}"
        lines.append(line)
    return "\n".join(lines)
