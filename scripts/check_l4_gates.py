#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""L4 闸门：敏感性回流 / y0 声明 / 异常操作定义；L5 解释失败仅 WARN。

背景
----
五一 C 题（边坡预警）赛后诊断把错误从「口径级全错」下移到 L4/L5：
敏感性当附录装饰、Δy 重建默认 y0=0、统计异常当领域异常、正文见过的现象
被改写成误报。本脚本把诊断 §6 规则 1–4 做成机械扫描，挂在操作面 S5/S7，
不注入 LangGraph。

规则
----
G1 敏感性回流：出现「敏感性分析」则提示主口径取舍（仅 WARN，--strict 不因此失败）。
G2 状态重建：出现 cumsum / 累加重建 / Δy 等则必须声明 y0 或重建公式。
G3 异常操作定义：出现「异常检测 / 离群点 / outlier」则必须有本题操作定义。
G4 解释失败：同时出现「看见过」现象词与「误报/纯噪声/不存在」→ 仅 WARN。

无触发信号则直接通过（排程题、血脂题不会无端失败）。

退出码
------
  0  默认；或无 G2/G3 未过（G1/G4 永不因此失败）
  1  --strict 且 G2/G3 至少一项未过
  2  未提供 --paper，或路径不存在

用法
----
  python scripts/check_l4_gates.py --paper <md> [--brief <brief.json>] [--strict]
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

EXIT_OK = 0
EXIT_STRICT_FAIL = 1
EXIT_NO_INPUT = 2

G1_TRIGGER = re.compile(r"敏感性分析|sensitivity\s+analysis", re.IGNORECASE)
G1_PASS = ("主口径取舍", "敏感性决策", "敏感性回流", "不采用该敏感性口径")

G2_TRIGGER = re.compile(
    r"cumsum|累加重建|差分重建|Δy|\\Delta y|积分重建",
    re.IGNORECASE,
)
G2_PASS = re.compile(
    r"y\s*(?:_?\s*0|₀)\s*[=＝]|初值\s*[=＝]|重建公式",
    re.IGNORECASE,
)

G3_TRIGGER = re.compile(r"异常检测|离群点|outlier", re.IGNORECASE)
# 「无操作定义」不含通过义，故排除「无」前缀（比光秃子串更窄）
G3_PASS = re.compile(r"(?<!无)操作定义|本题要抓|领域异常|统计异常")

G4_SEEN = ("恢复期", "双周期", "回落", "双峰")
G4_NEG = ("误报", "纯噪声", "不存在该现象")

MSG = {
    "sensitivity_no_decision": "敏感性已出现，但没有主口径取舍/决策记录",
    "reconstruction_no_y0": "出现 Δy/累加重建，但未声明 y0/重建公式",
    "anomaly_no_definition": "出现异常检测/离群点，但没有本题操作定义/领域异常说明",
    "explanation_failure": "正文描述过的现象（恢复期/双周期/回落/双峰）与误报/纯噪声/不存在该现象并存，请核对应解释失败专项",
}

# G1/G4 只提示；--strict 仅 G2/G3 失败
L4_FAIL_IDS = frozenset({"reconstruction_no_y0", "anomaly_no_definition"})


def _has_any(text: str, needles: tuple[str, ...]) -> bool:
    return any(n in text for n in needles)


def scan_corpus(corpus: str) -> list[tuple[str, str, bool]]:
    """返回 (issue_id, 中文说明, 是否计入 L4 失败)。顺序 G1→G4。"""
    issues: list[tuple[str, str, bool]] = []
    if G1_TRIGGER.search(corpus) and not _has_any(corpus, G1_PASS):
        issues.append(
            ("sensitivity_no_decision", MSG["sensitivity_no_decision"], False)
        )
    if G2_TRIGGER.search(corpus) and not G2_PASS.search(corpus):
        issues.append(
            ("reconstruction_no_y0", MSG["reconstruction_no_y0"], True)
        )
    if G3_TRIGGER.search(corpus) and not G3_PASS.search(corpus):
        issues.append(
            ("anomaly_no_definition", MSG["anomaly_no_definition"], True)
        )
    if _has_any(corpus, G4_SEEN) and _has_any(corpus, G4_NEG):
        issues.append(
            ("explanation_failure", MSG["explanation_failure"], False)
        )
    return issues


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="check_l4_gates.py",
        description="L4 闸门：敏感性回流 / y0 声明 / 异常操作定义；解释失败仅 WARN。",
    )
    p.add_argument("--paper", metavar="md", help="论文 md")
    p.add_argument("--brief", metavar="json", help="可选 brief.json，全文并入扫描语料")
    p.add_argument(
        "--strict",
        action="store_true",
        help="G2/G3 未过时退出码 1（G1/G4 不因此失败）",
    )
    return p


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    args = build_parser().parse_args(argv)
    if not args.paper:
        print("[错误] 需要 --paper 参数。", file=sys.stderr)
        return EXIT_NO_INPUT

    paper = Path(args.paper)
    if not paper.is_file():
        print(f"[错误] 文件不存在：{args.paper}", file=sys.stderr)
        return EXIT_NO_INPUT

    parts = [_read_text(paper)]
    if args.brief:
        brief = Path(args.brief)
        if not brief.is_file():
            print(f"[错误] 文件不存在：{args.brief}", file=sys.stderr)
            return EXIT_NO_INPUT
        parts.append(_read_text(brief))
    corpus = "\n".join(parts)

    issues = scan_corpus(corpus)
    for issue_id, msg, _fail in issues:
        print(f"[WARN] {issue_id}：{msg}")

    l4_n = sum(1 for _i, _m, fail in issues if fail)
    if l4_n:
        print(f"[结论] WARN：L4 闸门未过 {l4_n} 项")
        return EXIT_STRICT_FAIL if args.strict else EXIT_OK
    print("[结论] OK")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
