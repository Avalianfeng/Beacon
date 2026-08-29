"""T-11 / A-01：骨架 paper.md 原地展开【待展开】分析槽。

不整篇重写摘要/表/附录；只替换分析类占位（假设论证、逐问推导）。
缺料占位（brief/evidence/reference 缺失）不编造，保留或记入 errors。
数字必须来自 evidence / tables / 骨架已出现数字（白名单）。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from math_agent.config import MODEL_ROUTING
from math_agent.llm import complete
from math_agent.prompts.writer import SYSTEM as WRITER_SYSTEM

# 分析槽篇幅下限（非空白字符）；低于则一修。低于 writer 整章预算——只填槽。
_MIN_ASSUMPTION_CHARS = 400
_MIN_QUESTION_CHARS = 500

_PLACEHOLDER_LINE_RE = re.compile(
    r"^(?P<prefix>\s*>\s*)【待展开：(?P<body>[^】]+)】\s*$",
    re.MULTILINE,
)

SlotKind = Literal["analysis", "material"]


class ExpandSlotOut(BaseModel):
    """单槽展开输出：纯 prose，不得引入白名单外数字。"""

    prose: str = Field(description="替换【待展开】的分析正文（Markdown，可多段）")


@dataclass
class ExpandSlot:
    kind: SlotKind
    body: str
    start: int
    end: int
    full_match: str
    prefix: str
    qid: str | None = None  # 问题槽时为 "1"/"2"/…


@dataclass
class ExpandResult:
    paper: str
    expanded: list[str] = field(default_factory=list)
    skipped_material: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def classify_slot(body: str) -> SlotKind:
    """区分分析槽 vs 缺料槽。"""
    b = body.strip()
    if "逐条论证假设" in b:
        return "analysis"
    if re.search(r"问题\d+的模型推导", b) or "模型推导/分析/检验" in b:
        return "analysis"
    if any(
        k in b
        for k in (
            "brief.json 缺失",
            "brief 缺失",
            "evidence 缺",
            "未在 evidence",
            "不存在",
            "待补充",
            "待人工",
            "该问无 evidence",
        )
    ):
        return "material"
    if "论证" in b or "分析" in b or "prose" in b or "推导" in b:
        return "analysis"
    return "material"


def _qid_from_body(body: str) -> str | None:
    m = re.search(r"问题(\d+)", body)
    return m.group(1) if m else None


def find_slots(paper: str) -> list[ExpandSlot]:
    """扫描 blockquote 【待展开：…】行。"""
    slots: list[ExpandSlot] = []
    for m in _PLACEHOLDER_LINE_RE.finditer(paper):
        body = m.group("body")
        slots.append(
            ExpandSlot(
                kind=classify_slot(body),
                body=body,
                start=m.start(),
                end=m.end(),
                full_match=m.group(0),
                prefix=m.group("prefix"),
                qid=_qid_from_body(body),
            )
        )
    return slots


def build_available_numbers(evidence: dict, *, tables_spec: dict | None = None) -> str:
    """从 evidence.json（及可选 tables.json）构造可引用数字清单。"""
    lines: list[str] = []
    result = evidence.get("result")
    if isinstance(result, dict):
        ours = result.get("ours")
        if isinstance(ours, dict):
            for k, v in ours.items():
                lines.append(f"  [result.ours] {k}={v}")
    q_lines = evidence.get("q_lines")
    if isinstance(q_lines, list):
        for ln in q_lines:
            if isinstance(ln, str) and ln.strip():
                lines.append(f"  [q_lines] {ln.strip()}")
    if tables_spec and isinstance(tables_spec.get("tables"), list):
        for table in tables_spec["tables"]:
            if not isinstance(table, dict):
                continue
            lead = table.get("lead_columns") or {}
            if not isinstance(lead, dict):
                continue
            title = table.get("title") or table.get("id") or "table"
            for col, values in lead.items():
                if not isinstance(values, list):
                    continue
                for v in values:
                    if isinstance(v, (int, float)):
                        lines.append(f"  [tables/{title}] {col}={v}")
    if not lines:
        return "（无可用数字——禁止在 prose 中写任何具体数值）"
    return "\n".join(lines[:80])


def _context_window(paper: str, start: int, *, radius: int = 1200) -> str:
    lo = max(0, start - radius)
    hi = min(len(paper), start + radius)
    return paper[lo:hi]


def _min_chars_for_slot(slot: ExpandSlot) -> int:
    if "假设" in slot.body:
        return _MIN_ASSUMPTION_CHARS
    return _MIN_QUESTION_CHARS


def _nonspace_len(text: str) -> int:
    return len("".join(text.split()))


def _build_expand_prompt(
    slot: ExpandSlot,
    *,
    context: str,
    available_numbers: str,
    brief_excerpt: str,
) -> str:
    role = (
        "逐条论证模型假设的建模影响与依据"
        if "假设" in slot.body
        else f"问题{slot.qid or '?'}的模型推导、分析与检验"
    )
    return f"""你是数学建模论文主笔。任务：把骨架中的【待展开】分析槽写成正文。

## IRON RULES
1. 禁止编造任何具体数值；正文每个数字必须逐字出现在下方「可引用数字」或「骨架上下文」中。
2. 查不到就写「待验证 / 见 evidence Q 行」，绝不臆造。
3. 不要改写摘要、交付表、附录；只输出本槽 prose。
4. 不要输出【待展开】字样；不要用 JSON 以外的包装。
5. 禁止引入白名单没有的系数/阈值/百分比（如自造 0.03、23.4、-5）；公式只用文字描述或 brief 已写明且骨架已出现的数字。

## 槽位说明
{role}
占位原文：【待展开：{slot.body}】

## brief / 方向摘录（口径，非新数字来源）
{brief_excerpt or "（无 brief 摘录）"}

## 可引用数字（唯一事实源）
{available_numbers}

## 骨架上下文（供衔接，勿整段复制表）
```
{context}
```

请输出 JSON，键名仅 `prose`：多段 Markdown 分析正文，非空白字符至少 {_min_chars_for_slot(slot)}。
"""


def _brief_excerpt(brief, slot: ExpandSlot) -> str:
    if not brief:
        return ""
    parts: list[str] = []
    for item in brief.required_discussions:
        if item.id == "disc-assumptions" and item.topic:
            parts.append(item.topic[:800])
    if slot.qid:
        for item in brief.per_question_direction:
            if str(item.question_id) == slot.qid:
                if item.direction:
                    parts.append(item.direction[:600])
                break
    return "\n---\n".join(parts)


def _repair_prompt(base: str, issues: list[str]) -> str:
    return (
        base
        + "\n\n---\n\n## 篇幅质量门禁：上一稿必须重写\n\n"
        + "上一稿存在以下问题：\n- "
        + "\n- ".join(issues)
        + "\n请在不编造数字、不改变 JSON schema 的前提下加长分析。"
    )


def expand_one_slot(
    slot: ExpandSlot,
    *,
    paper: str,
    available_numbers: str,
    brief=None,
    complete_fn=complete,
) -> str:
    """调用 LLM 展开单槽；返回 prose 文本。"""
    prompt = _build_expand_prompt(
        slot,
        context=_context_window(paper, slot.start),
        available_numbers=available_numbers,
        brief_excerpt=_brief_excerpt(brief, slot),
    )
    out = complete_fn(
        prompt,
        schema=ExpandSlotOut,
        system=WRITER_SYSTEM,
        model=MODEL_ROUTING["writer"],
        profile="long",
        max_tokens=8000,
    )
    prose = (out.prose or "").strip()
    issues: list[str] = []
    need = _min_chars_for_slot(slot)
    if _nonspace_len(prose) < need:
        issues.append(f"prose 非空白字符={_nonspace_len(prose)}，至少 {need}")
    if "【待展开" in prose:
        issues.append("prose 仍含【待展开】")
    if issues:
        out = complete_fn(
            _repair_prompt(prompt, issues),
            schema=ExpandSlotOut,
            system=WRITER_SYSTEM,
            model=MODEL_ROUTING["writer"],
            profile="long",
            max_tokens=8000,
        )
        prose = (out.prose or "").strip()
        if _nonspace_len(prose) < need:
            raise ValueError(
                f"expand slot quality gate failed ({slot.body[:40]}…): "
                f"非空白={_nonspace_len(prose)} < {need}"
            )
    return prose


def _format_replacement(prose: str) -> str:
    """把 prose 格式化为可替换 blockquote 的正文（非 > 引用，直接段落）。"""
    text = prose.strip()
    if not text.endswith("\n"):
        text += "\n"
    return text


def expand_paper(
    paper: str,
    *,
    evidence: dict,
    brief: dict | None = None,
    tables_spec: dict | None = None,
    complete_fn=complete,
    require_analysis: bool = True,
) -> ExpandResult:
    """原地展开分析槽；返回新 paper 与元数据。

    require_analysis=True：若无任何分析槽可展开且仍有分析意图失败，记 errors。
    缺料槽保留原文，记入 skipped_material。
    """
    slots = find_slots(paper)
    analysis = [s for s in slots if s.kind == "analysis"]
    material = [s for s in slots if s.kind == "material"]
    result = ExpandResult(paper=paper)
    result.skipped_material = [s.body for s in material]

    if not analysis:
        if require_analysis and any("模型推导" in s.body or "论证假设" in s.body for s in slots):
            result.errors.append("未识别到可展开的分析槽")
        elif require_analysis and not slots:
            result.errors.append("骨架中无【待展开】占位")
        # 仅有缺料槽：不算失败（调用方决定是否 exit）
        return result

    available = build_available_numbers(evidence, tables_spec=tables_spec)
    # 从后向前替换，避免偏移
    new_paper = paper
    for slot in sorted(analysis, key=lambda s: s.start, reverse=True):
        try:
            prose = expand_one_slot(
                slot,
                paper=new_paper,
                available_numbers=available,
                brief=brief,
                complete_fn=complete_fn,
            )
        except Exception as exc:  # noqa: BLE001 — 汇总到 errors
            result.errors.append(f"{slot.body[:60]}: {exc}")
            continue
        replacement = _format_replacement(prose)
        new_paper = new_paper[: slot.start] + replacement + new_paper[slot.end :]
        result.expanded.append(slot.body)

    result.paper = new_paper
    # 验收：分析槽应已消失
    remaining = [
        s for s in find_slots(new_paper) if s.kind == "analysis"
    ]
    if remaining:
        result.errors.append(
            "展开后仍残留分析槽：" + "; ".join(s.body[:40] for s in remaining)
        )
    return result


def load_json(path: Path) -> dict:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path} 顶层必须是对象")
    return raw


def remaining_analysis_placeholders(paper: str) -> list[str]:
    return [s.body for s in find_slots(paper) if s.kind == "analysis"]


def new_untraced_numbers(
    skeleton: str,
    expanded: str,
    evidence_paths: list[Path],
) -> list[str]:
    """展开相对骨架新增、且不在 evidence 白名单中的数字 token。

    骨架本身常含题面/brief/sha256 噪音，check_paper_numbers --strict 会误杀；
    A-01 红线 = 展开不得引入新的未溯源结果数字。
    """
    from math_agent.ops_review import load_check_module

    mod = load_check_module("check_paper_numbers")
    whitelist, _, _ = mod.load_evidence_whitelist([str(p) for p in evidence_paths])
    skel = set(mod.extract_number_tokens(skeleton))
    exp = set(mod.extract_number_tokens(expanded))
    introduced = exp - skel
    return sorted(t for t in introduced if t not in whitelist)
