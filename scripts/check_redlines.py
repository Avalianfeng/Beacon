#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""S7 红线产物校验：消费 brief.redline_rules。

退出码
------
  0  无 brief / 无规则 / 仅 warn（非 --strict）
  1  存在 severity=hard 违规；或 --strict 且存在 warn 违规
  2  输入不可用
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
    p = argparse.ArgumentParser(prog="check_redlines.py")
    p.add_argument("--brief", metavar="json", help="brief.json")
    p.add_argument("--paper", metavar="md", help="论文 md")
    p.add_argument("--code", metavar="py", action="append", default=[], help="代码文件（可多次）")
    p.add_argument("--stdout", metavar="txt", help="运行输出文本")
    p.add_argument("--strict", action="store_true", help="warn 级也失败")
    return p


def _read(path: Path | None) -> str:
    if path is None or not path.is_file():
        return ""
    return path.read_text(encoding="utf-8")


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    args = build_parser().parse_args(argv)
    if not args.brief:
        print("[结论] OK（无 --brief，跳过红线）")
        return EXIT_OK
    brief_path = Path(args.brief)
    if not brief_path.is_file():
        print(f"[错误] 文件不存在：{args.brief}", file=sys.stderr)
        return EXIT_NO_INPUT

    from math_agent.brief import load_brief, redline_violations

    try:
        brief = load_brief(brief_path)
    except ValueError as exc:
        print(f"[错误] {exc}", file=sys.stderr)
        return EXIT_NO_INPUT

    code = "\n".join(_read(Path(p)) for p in args.code)
    paper = _read(Path(args.paper) if args.paper else None)
    stdout = _read(Path(args.stdout) if args.stdout else None)
    hits = redline_violations(brief, code=code, stdout=stdout, paper=paper)
    hard = [v for v in hits if v.severity == "hard"]
    warn = [v for v in hits if v.severity != "hard"]
    for v in hits:
        tag = "HARD" if v.severity == "hard" else "WARN"
        print(f"[{tag}] {v.rule_id} ({v.target}): {v.message}")
    if hard:
        print(f"[结论] FAIL：hard 红线 {len(hard)} 条")
        return EXIT_FAIL
    if warn and args.strict:
        print(f"[结论] FAIL：--strict 下 warn 红线 {len(warn)} 条")
        return EXIT_FAIL
    if warn:
        print(f"[结论] OK（{len(warn)} 条 warn 未阻断）")
        return EXIT_OK
    print("[结论] OK")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
