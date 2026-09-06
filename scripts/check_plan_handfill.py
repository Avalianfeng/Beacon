"""检查 plan.json 手补缺口（零 token；可与 plan check 并用）。

额外盯：recommended_route、data_requirements、coverage.reason 过短。
正式语义门仍是：uv run math-agent plan check

示例：
  python scripts/check_plan_handfill.py --plan problems/cumcm23-c/plan.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def _bp(card: dict[str, Any]) -> dict[str, Any]:
    return card.get("problem_blueprint") or card.get("blueprint") or card


def check_handfill(card: dict[str, Any]) -> tuple[list[str], list[str]]:
    gaps: list[str] = []
    warns: list[str] = []
    bp = _bp(card)

    dvs = bp.get("decision_variables") or []
    if not dvs:
        gaps.append("decision_variables 为空")

    route = bp.get("recommended_route") or {}
    if not isinstance(route, dict) or not str(route.get("route") or "").strip():
        gaps.append("recommended_route.route 为空")
    elif not str(route.get("reason") or "").strip():
        gaps.append("recommended_route.reason 为空")

    data_req = bp.get("data_requirements") or []
    if not data_req:
        gaps.append("data_requirements 为空（附件标 given）")

    vplan = bp.get("validation_plan") or []
    if not vplan:
        gaps.append("validation_plan 为空")
    else:
        for i, item in enumerate(vplan):
            if not str((item or {}).get("pass_criteria") or "").strip():
                gaps.append(f"validation_plan[{i}] 缺 pass_criteria")

    for i, cov in enumerate(bp.get("brief_coverage") or []):
        reason = str((cov or {}).get("reason") or "").strip()
        if not reason:
            gaps.append(f"brief_coverage[{i}] reason 为空")
        elif len(reason) < 8 or reason.lower() in {"todo", "tbd", "骨架", "followed"}:
            warns.append(f"brief_coverage[{i}] reason 可能过短/占位：{reason[:40]!r}")
        status = str((cov or {}).get("status") or "")
        if status == "followed" and not (
            (cov or {}).get("question_ids") or (cov or {}).get("equation_ids")
        ):
            gaps.append(f"brief_coverage[{i}] followed 但无 question_ids/equation_ids")

    sens = [
        a
        for a in (card.get("assumptions") or [])
        if isinstance(a, dict) and a.get("sensitivity_relevant")
    ]
    if not sens:
        warns.append("无 sensitivity_relevant=true 的 assumptions（inject 参数名无处对齐）")

    return gaps, warns


def main() -> None:
    parser = argparse.ArgumentParser(description="plan 手补缺口检查")
    parser.add_argument("--plan", type=Path, required=True)
    args = parser.parse_args()
    path = args.plan.resolve()
    if not path.is_file():
        raise SystemExit(f"无 plan：{path}")
    card = json.loads(path.read_text(encoding="utf-8-sig"))
    gaps, warns = check_handfill(card)
    for w in warns:
        print(f"[WARN] {w}")
    if gaps:
        print(f"[FAIL] {path} 手补缺口 {len(gaps)}：")
        for g in gaps:
            print(f"  - {g}")
        print("写够后：uv run math-agent plan check --plan … --brief …")
        sys.exit(1)
    print(f"[OK] {path} 手补字段看起来齐（非正式门禁）")


if __name__ == "__main__":
    main()
