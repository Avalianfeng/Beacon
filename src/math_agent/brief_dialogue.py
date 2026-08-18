"""brief 对话式生成（CLI 前置阶段，不进 LangGraph 主图）。

职责：把"人机协同建模预备"落到命令行——按题面 + 附件数据摘要，逐字段由 LLM
起草建议（--assist），人工逐条确认/修改后落盘 brief.json。方向正确性只在此处
（前置对话）确定，流水线内不评审方向本身。
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

# 字段定义：(字段名, 中文名, 说明, 条目结构提示)
FIELD_SPECS: list[tuple[str, str, str, str]] = [
    ("per_question_direction", "逐题方向", "逐题建模类型指引 + 明确禁止的方向",
     '{"id": str, "question_id": str, "direction": str, "forbidden": str}'),
    ("formula_notes", "公式注意", "关键公式原文、参数选择注意事项",
     '{"id": str, "question_id": str, "note": str}'),
    ("required_discussions", "讨论点", "论文必须体现的讨论点（工程意义/假设声明）",
     '{"id": str, "sections": [str, ...], "topic": str, "requirement": str}'),
    ("red_lines", "红线", "方向性错误红线（禁止清单）",
     '{"id": str, "question_id": str, "prohibition": str}'),
    ("figure_plan", "图表规划", "必做图清单 + 标注要求",
     '{"id": str, "question_id": str, "figure": str, "requirements": str}'),
    ("scoring_notes", "评分要点", "评分标准要点（分值分布/容差/参考区间）",
     '{"id": str, "question_id": str, "note": str}'),
    ("data_notes", "数据注意", "数据使用注意（均值化/范围/缺失处理）",
     '{"id": str, "question_id": str, "note": str}'),
    ("reference_direction", "文献方向", "参考文献方向（字符串数组）",
     '["巷道支护", "Winkler 地基", ...]'),
]

_FIELD_EXPLAIN = {
    "per_question_direction": "每个小问用什么建模方法、必须避免的方向。例如：\n"
    '  [{"id": "1.2-direction", "question_id": "1.2", '
    '"direction": "必须变点检测/分段回归", "forbidden": "禁止用工况A参数直接算临界值"}]',
    "formula_notes": "关键公式原文与参数选择注意。例如：\n"
    '  [{"id": "2.2-fbond", "question_id": "2.2", '
    '"note": "F_bond=π·D_hole·L_bond·τ（钻孔直径，非锚杆直径）"}]',
    "required_discussions": "论文必须体现的讨论点，sections 限：abstract/problem_restatement/"
    "assumptions/notation/model_section/solution/sensitivity/conclusion/references。例如：\n"
    '  [{"id": "3.1-e0", "sections": ["model_section", "solution"], '
    '"topic": "e=0 参考线意义与 233% 解读", "requirement": "必须出现"}]',
    "red_lines": "禁止出现的方向性错误。例如：\n"
    '  [{"id": "1.2-600", "question_id": "1.2", "prohibition": "不得硬编码 600.71/0.8·T_max"}]',
    "figure_plan": "必做图清单与标注要求。例如：\n"
    '  [{"id": "fig6", "question_id": "3.1", "figure": "T_max-e 曲线", '
    '"requirements": "三条线+e_cr 标注"}]',
    "scoring_notes": "评分标准要点。例如：\n"
    '  [{"id": "1.2-tc", "question_id": "1.2", "note": "T_c∈[100,150] ±5% 容差"}]',
    "data_notes": "数据注意。例如：\n"
    '  [{"id": "1.2-mean", "question_id": "1.2", "note": "表2/3 五测点均值化"}]',
    "reference_direction": '文献方向，字符串数组。例如：["巷道支护", "Winkler 地基", "螺纹力学"]',
}

# id 自动补全时的后缀（无 question_id 时的兜底后缀）
_FIELD_ID_SUFFIX = {
    "per_question_direction": "direction",
    "formula_notes": "formula",
    "required_discussions": "discussion",
    "red_lines": "redline",
    "figure_plan": "figure",
    "scoring_notes": "scoring",
    "data_notes": "data",
}


class _DraftOut(BaseModel):
    """LLM 起草输出的统一外壳。"""

    items: list[dict[str, Any]] = Field(default_factory=list)


def build_context(problem: str, background: str, questions: list[str],
                  data_files=None) -> str:
    """组装对话上下文字符串（题目 + 小问 + 附件数据摘要）。"""
    qs = "\n".join(f"- {q}" for q in questions) or "（题目本身未列出独立小问）"
    data_hint = ""
    if data_files:
        from math_agent.prompts._data_hint import build_data_summary_hint
        data_hint = build_data_summary_hint(data_files)
    return (
        f"# 题目\n{problem}\n\n"
        f"# 背景\n{background or '（无）'}\n\n"
        f"# 小问\n{qs}\n\n"
        f"{data_hint}"
    )


_DRAFT_SYSTEM = (
    "你是数学建模竞赛教练。根据题目与附件数据概况，为“建模预备 brief”的单个字段起草内容。"
    "只写题面/官方资料明示或领域常识可确证的内容，不确定就留空；"
    "每条内容 ≤200 字符；id 用「小问号-语义」风格（如 1.2-direction、2.2-fbond）。"
    "输出严格 JSON：{\"items\": [...]}。"
)


def draft_field(field_name: str, context: str, *, model: str) -> list[dict] | None:
    """调用 LLM 起草某一字段的条目数组；失败返回 None（由调用方决定重试/跳过）。"""
    if field_name == "reference_direction":
        schema_hint = "items 的元素是字符串（文献方向）"
    else:
        schema_hint = _FIELD_EXPLAIN[field_name]
    field_label = next(label for name, label, _, _ in FIELD_SPECS if name == field_name)
    prompt = (
        f"{context}\n"
        f"# 请起草字段：{field_name}（{field_label}）\n"
        f"{schema_hint}\n"
    )
    try:
        from math_agent.llm import complete
        out: _DraftOut = complete(
            prompt, schema=_DraftOut, system=_DRAFT_SYSTEM, model=model
        )
        items = list(out.items)
    except Exception:
        return None
    # 按字段类型清洗草稿：不合规条目视为起草失败（提示人工填写/跳过），
    # 不在最后组装时才因 schema 报错。
    if field_name == "reference_direction":
        cleaned = [
            item if isinstance(item, str)
            else (item.get("content") if isinstance(item, dict)
                  and isinstance(item.get("content"), str) else None)
            for item in items
        ]
        cleaned = [c for c in cleaned if c is not None]
    else:
        cleaned = [item for item in items if isinstance(item, dict)]
    return cleaned or None


def auto_fill_ids(items: list, field_name: str) -> list:
    """为缺失 id 的条目自动补全（question_id-后缀；重复时追加序号）。

    reference_direction 等为 list[str]，原样返回，不做 id 补全。
    """
    if field_name == "reference_direction":
        return list(items)
    suffix = _FIELD_ID_SUFFIX.get(field_name, field_name)
    used: set[str] = set()
    result: list[dict] = []
    for index, item in enumerate(items, 1):
        if not isinstance(item, dict):
            continue
        item = dict(item)
        if not (item.get("id") or "").strip():
            qid = str(item.get("question_id") or "").strip()
            base = f"{qid}-{suffix}" if qid else suffix
            candidate = base
            counter = 1
            while candidate in used:
                counter += 1
                candidate = f"{base}-{counter}"
            item["id"] = candidate
        item_id = str(item.get("id") or "")
        if item_id in used:
            item["id"] = f"{item_id}-{index}"
        used.add(str(item["id"]))
        result.append(item)
    return result


def assemble_brief(
    fields: dict[str, list[dict]],
    *,
    problem_id: str = "",
    source: list[str] | None = None,
    created_at: str = "",
) -> dict:
    """把对话结果组装为可校验的 brief dict（id 自动补全）。"""
    payload: dict[str, Any] = {
        "schema_version": 1,
        "problem_id": problem_id,
        "created_at": created_at,
    }
    if source:
        payload["source"] = source
    for field_name, _, _, _ in FIELD_SPECS:
        raw = fields.get(field_name) or []
        payload[field_name] = auto_fill_ids(raw, field_name)
    return payload
