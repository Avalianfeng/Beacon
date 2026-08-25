#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""口径偏差报告（E 类 · E2）：我们 vs 官方参考答案自动对照

用途：读 `problems/<题号>/calibration/official_answers.json`（结构约定见
`problems/mcm51-b/calibration/官方参考答案要点.md` 与 json 本身），与我们的求解数字对照，
输出每问区间/声明值命中判定、偏差百分比与 Q4 购置对比——把赛后复盘从手工 diff 变为半自动。

用法：
  python scripts/report_calibration_diff.py --official problems/mcm51-b/calibration/official_answers.json
  python scripts/report_calibration_diff.py --official ... --ours 结果.json   # 覆盖我方数字

calibration json 结构约定：
  q1..q4: {range_s: [lo, hi] | null, declared_s: number | null, ...}
  q4.purchase: {总台数 total, 各类型台数键}
  ours 数字键：q1_s / q2_s / q3_s / q4_s / q4_spent_yuan / q4_purchase{...}
  （official json 内嵌 ours_* 字段时可直接使用）

退出码：默认 0；--strict 且存在未命中项 → 1；文件缺失/结构不符 → 2。
"""

import argparse
import json
import sys
from pathlib import Path

OURS_KEY = "ours_20260824"  # official json 内嵌我方快照的默认键


def load_json(path):
    p = Path(path)
    if not p.exists():
        print(f"错误：文件不存在：{path}", file=sys.stderr)
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"错误：无法解析 {path}：{exc}", file=sys.stderr)
        return None


def hit_range(value, range_s):
    if not range_s:
        return None  # 无区间，不判定
    lo, hi = range_s
    return lo <= value <= hi


def fmt_range(range_s):
    return f"[{range_s[0]}, {range_s[1]}]" if range_s else "（无区间）"


def main(argv=None):
    ap = argparse.ArgumentParser(description="口径偏差报告（E2）：我们 vs 官方参考答案自动对照")
    ap.add_argument("--official", required=True, help="calibration/official_answers.json 路径")
    ap.add_argument("--ours", default=None, help="可选：我方数字 json（覆盖 official 内嵌快照）")
    ap.add_argument("--strict", action="store_true", help="有未命中项时退出码 1")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args(argv)

    official = load_json(args.official)
    if official is None:
        return 2

    ours = None
    if args.ours:
        ours = load_json(args.ours)
        if ours is None:
            return 2
    elif isinstance(official.get(OURS_KEY), dict):
        ours = official[OURS_KEY]
    else:
        print("错误：未提供 --ours 且 official json 无内嵌 ours 快照", file=sys.stderr)
        return 2

    q_order = ["q1", "q2", "q3", "q4"]
    okeys = ["q1_s", "q2_s", "q3_s", "q4_s"]
    missed = []

    print("===== 口径偏差报告（我们 vs 官方参考答案）=====")
    print(f"题目：{official.get('problem_id', '?')} | 获取时间：{official.get('obtained_at', '?')}")
    print()
    print("| 问 | 我们的值 | 官方区间 | 区间命中 | 官方声明 | 偏差 |")
    print("|----|----------|----------|----------|----------|------|")
    for q, ok in zip(q_order, okeys):
        qdata = official.get(q, {})
        ours_v = ours.get(ok)
        range_s = qdata.get("range_s")
        declared = qdata.get("declared_s")
        if ours_v is None:
            print(f"| {q} | （缺我方值 {ok}） | {fmt_range(range_s)} | — | {declared} | — |")
            missed.append(q)
            continue
        in_range = hit_range(ours_v, range_s)
        if range_s and in_range is False:
            missed.append(q)
        dev = ""
        if declared:
            dev = f"{ours_v / declared * 100.0 - 100.0:+.1f}%"
        mark = "✅" if in_range else ("—" if in_range is None else "❌")
        print(f"| {q} | {ours_v} | {fmt_range(range_s)} | {mark} | {declared} | {dev} |")

    # Q4 购置对比
    q4 = official.get("q4", {})
    op = q4.get("purchase")
    our_p = ours.get("q4_purchase")
    print()
    if op and our_p:
        print(f"Q4 购置对比：官方 {op}；我们 {our_p}（花费 {ours.get('q4_spent_yuan', '?')} 元）")
        if op.get("total") and our_p.get("total") != op["total"]:
            missed.append("q4_purchase")
            print("  ❌ 购置台数不符（官方 15 分项）")
        else:
            print("  ✅ 购置台数一致")
    elif our_p:
        print(f"Q4 购置（官方无结构约定数据）：{our_p}")

    print()
    print(f"汇总：未命中项 {len(missed)} 处 {missed if missed else '（全部命中）'}")
    root = ours.get("root_cause")
    if missed and root:
        print(f"根因提示：{root}")
    if missed:
        print("提示：未命中项进入口径核查流程（见 docs/实现计划-8-20/8-26-C类-评审口径核查必答项.md Q2/Q4）")
        return 1 if args.strict else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
