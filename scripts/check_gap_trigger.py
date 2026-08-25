#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""大 gap 触发口径核查检查（C 类 · C2）

用途：从证据 json（如 sensitivity.json 的 cpm_lower_bounds）中找出「下界 LB vs 实际 makespan」
配对，当差距超过阈值（默认 15%）时输出口径核查提醒——mcm51-b 教训：Q2 差距 74.2%
（215303 vs 123614）被当作「诚实声明」加分项而非红旗，实际根因是假设 9 口径收紧
（禁止同类多机分摊），赛后评估 39 分结果分丢失（docs/20 §三 M4、§五 S3）。

用法：
  python scripts/check_gap_trigger.py --json <证据.json> [--json <更多.json>] [--threshold 15] [--strict] [--verbose]

退出码：默认 0；--strict 且有触发 → 1；无输入文件/文件缺失 → 2。
"""

import argparse
import json
import sys
from pathlib import Path

# 下界与 makespan 的候选键名（递归扫描时按这些键配对）
LB_KEYS = ("lb", "lb_pure_duration", "lb_with_first_entry_transport", "lower_bound", "lb_s", "lb_s_pure")
MS_KEYS = ("makespan", "makespan_s", "ms", "makespan_s_pure")


def find_gap_candidates(obj, path=""):
    """递归扫描 dict/list，返回所有「下界 + makespan」配对：(路径, lb, makespan)。"""
    results = []
    if isinstance(obj, dict):
        ms = None
        lb = None
        for k, v in obj.items():
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                if k in MS_KEYS:
                    ms = v
                elif k in LB_KEYS and lb is None:
                    lb = v
        if ms is not None and lb is not None and lb > 0:
            results.append((path, lb, ms))
        for k, v in obj.items():
            child = f"{path}.{k}" if path else str(k)
            results.extend(find_gap_candidates(v, child))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            child = f"{path}[{i}]" if path else f"[{i}]"
            results.extend(find_gap_candidates(v, child))
    return results


def main(argv=None):
    ap = argparse.ArgumentParser(description="大 gap（下界 vs makespan）触发口径核查检查（C2）")
    ap.add_argument("--json", action="append", default=[], metavar="FILE",
                    help="证据 json 文件（可多次指定）")
    ap.add_argument("--threshold", type=float, default=15.0,
                    help="差距阈值（百分比），默认 15")
    ap.add_argument("--strict", action="store_true", help="有触发时退出码 1")
    ap.add_argument("--verbose", action="store_true", help="打印详细过程")
    args = ap.parse_args(argv)

    if not args.json:
        print("错误：未提供 --json 证据文件", file=sys.stderr)
        return 2

    rows = []
    for f in args.json:
        p = Path(f)
        if not p.exists():
            print(f"错误：文件不存在：{f}", file=sys.stderr)
            return 2
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"错误：无法解析 {f}：{exc}", file=sys.stderr)
            return 2
        for path, lb, ms in find_gap_candidates(data):
            rows.append((f, path, lb, ms))

    if args.verbose:
        print(f"配对候选 {len(rows)} 处（LB_KEYS={LB_KEYS}，MS_KEYS={MS_KEYS}）")

    print("===== 大 gap 触发口径核查检查（阈值 >%.1f%%）=====" % args.threshold)
    if not rows:
        print("未找到「下界 + makespan」配对数据")
        return 0

    triggered = [r for r in rows if (r[3] - r[2]) / r[2] * 100.0 > args.threshold]
    print(f"配对 {len(rows)} 处 | 触发 {len(triggered)} 处")
    for f, path, lb, ms in rows:
        gap = (ms - lb) / lb * 100.0
        flag = "⚠ 触发" if gap > args.threshold else "  正常"
        print(f"{flag} | {f} | {path} | LB={lb} | makespan={ms} | gap={gap:.2f}%")

    if triggered:
        print()
        print("触发条目必须输出口径核查结论（C 类评审必答项 Q2）：")
        print("  1. 差距的机制性解释（瓶颈设备 / 排队 / 运输占比 / 口径差异），")
        print("     禁止只写『启发式非全局最优』这类免责声明；")
        print("  2. 口径核查：差距是否源于模型假设（如禁止分摊类收紧口径）→ 引用假设分级与备选口径；")
        print("  3. 参考：docs/实现计划-8-20/8-26-C类-评审口径核查必答项.md")
        return 1 if args.strict else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
