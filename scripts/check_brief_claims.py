#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""S7：核对论文是否覆盖 brief.figure_plan / scoring_notes / data_notes。

无 brief 跳过。默认 WARN；--strict 时缺项退出 1。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

EXIT_OK = 0
EXIT_FAIL = 1
EXIT_NO_INPUT = 2


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="check_brief_claims.py")
    p.add_argument("--brief", metavar="json", required=False)
    p.add_argument("--paper", metavar="md")
    p.add_argument("--strict", action="store_true")
    return p


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    args = build_parser().parse_args(argv)
    if not args.brief:
        print("[结论] OK（无 --brief，跳过 claims）")
        return EXIT_OK
    if not args.paper:
        print("[错误] 需要 --paper", file=sys.stderr)
        return EXIT_NO_INPUT
    brief_path = Path(args.brief)
    paper_path = Path(args.paper)
    if not brief_path.is_file() or not paper_path.is_file():
        print("[错误] brief 或 paper 不存在", file=sys.stderr)
        return EXIT_NO_INPUT

    from math_agent.brief import load_brief

    try:
        brief = load_brief(brief_path)
    except ValueError as exc:
        print(f"[错误] {exc}", file=sys.stderr)
        return EXIT_NO_INPUT
    paper = paper_path.read_text(encoding="utf-8")
    missing: list[str] = []
    for item in brief.figure_plan:
        needle = (item.figure or "").strip()
        if needle and needle not in paper:
            missing.append(f"figure_plan {item.id}: 正文未见「{needle}」")
    for item in brief.scoring_notes:
        needle = (item.note or "")[:24]
        if needle and needle not in paper:
            missing.append(f"scoring_notes {item.id}: 正文未见评分要点片段")
    for item in brief.data_notes:
        if item.id and item.id not in paper and (item.note or "")[:16] not in paper:
            missing.append(f"data_notes {item.id}: 正文未见数据口径片段")
    for msg in missing:
        print(f"[WARN] {msg}")
    if missing and args.strict:
        print(f"[结论] FAIL：{len(missing)} 条 claims 未覆盖")
        return EXIT_FAIL
    if missing:
        print(f"[结论] OK（{len(missing)} 条 WARN）")
        return EXIT_OK
    print("[结论] OK")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
