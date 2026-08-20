"""逐节点成本遥测 v0：从 progress.jsonl 聚合 LLM 调用与节点时长。

数据源（已核实，runs/51mcm-a-brief-v1/progress.jsonl）：
  - llm_call    : model / node / prompt_tokens / completion_tokens / latency_ms
  - node_start  : 节点进入次数（重试代理）
  - node_end    : duration_ms（墙钟）
  - run_boundary: attempt/epoch 边界（当前为聚合值；分 attempt 统计属 v1）

用法:
  python scripts/run_cost_summary.py <run_dir> [--out <path>]

输出: 写 <run_dir>/cost_summary.md（派生文件，幂等覆盖），同时打印。
退出码: 0 = 成功；1 = 无 progress.jsonl。
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path


def load_events(run_dir: Path) -> list[dict]:
    p = run_dir / "progress.jsonl"
    if not p.exists():
        print(f"no progress.jsonl in {run_dir}", file=sys.stderr)
        sys.exit(1)
    events: list[dict] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("run_dir", type=Path)
    ap.add_argument("--out", type=Path, default=None, help="输出 md 路径（默认 <run_dir>/cost_summary.md）")
    args = ap.parse_args()
    run_dir: Path = args.run_dir.resolve()
    events = load_events(run_dir)

    calls: dict[str, dict] = defaultdict(
        lambda: {"count": 0, "prompt": 0, "completion": 0, "latency_ms": 0, "models": set()}
    )
    node_start: dict[str, int] = defaultdict(int)
    node_dur: dict[str, float] = defaultdict(float)
    boundaries = 0

    # llm_call 事件不带 node 字段（历史事实），用时间戳归属：
    # 按 node 名顺序配对 node_start.ts ~ node_end.ts 构成执行区间。
    starts: dict[str, list[float]] = defaultdict(list)
    ends: dict[str, list[float]] = defaultdict(list)
    raw_calls: list[dict] = []
    for e in events:
        t = e.get("type")
        if t == "run_boundary":
            boundaries += 1
        elif t == "llm_call":
            raw_calls.append(e)
        elif t == "node_start":
            name = str(e.get("node") or "?")
            node_start[name] += 1
            starts[name].append(float(e.get("ts") or 0.0))
        elif t == "node_end":
            name = str(e.get("node") or "?")
            node_dur[name] += float(e.get("duration_ms") or 0)
            ends[name].append(float(e.get("ts") or 0.0))

    intervals: list[tuple[str, float, float]] = []
    for name in starts:
        for i, s in enumerate(starts[name]):
            e_ts = ends[name][i] if i < len(ends[name]) else s
            intervals.append((name, s, e_ts))

    def _node_for_ts(ts: float) -> str | None:
        hit = None
        hit_span = float("inf")
        for name, s, e_ts in intervals:
            if s <= ts <= e_ts and (e_ts - s) < hit_span:
                hit, hit_span = name, e_ts - s
        return hit

    for e in raw_calls:
        node = str(e.get("node") or "")
        if not node or node == "?":
            node = _node_for_ts(float(e.get("ts") or 0.0)) or "?"
        c = calls[node]
        c["count"] += 1
        c["prompt"] += int(e.get("prompt_tokens") or 0)
        c["completion"] += int(e.get("completion_tokens") or 0)
        c["latency_ms"] += float(e.get("latency_ms") or 0)
        if e.get("model"):
            c["models"].add(str(e["model"]))

    nodes = sorted(set(calls) | set(node_start) | set(node_dur))
    rows: list[tuple] = []
    tot = {"count": 0, "prompt": 0, "completion": 0, "latency_ms": 0, "dur": 0.0}
    for n in nodes:
        c = calls.get(n)
        cnt = c["count"] if c else 0
        prompt = c["prompt"] if c else 0
        comp = c["completion"] if c else 0
        lat = c["latency_ms"] if c else 0.0
        starts = node_start.get(n, 0)
        dur = node_dur.get(n, 0.0)
        models = ",".join(sorted(c["models"])) if c and c["models"] else "-"
        rows.append((n, starts, cnt, prompt, comp, dur / 1000.0, lat / 1000.0, models))
        tot["count"] += cnt
        tot["prompt"] += prompt
        tot["completion"] += comp
        tot["latency_ms"] += lat
        tot["dur"] += dur

    lines = [
        f"# 成本遥测（{run_dir.name}）",
        "",
        f"- run_boundary 次数：{boundaries}（跨 attempt/epoch 时为聚合值；分 attempt 属 v1）",
        "- 来源：progress.jsonl（llm_call / node_start / node_end），只读聚合",
        "",
        "| 节点 | 进入次数 | LLM 调用 | prompt tokens | completion tokens | 墙钟(s) | LLM 时延(s) | 模型 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append("| %s | %d | %d | %d | %d | %.1f | %.1f | %s |" % r)
    lines.append(
        "| **合计** | - | %d | %d | %d | %.1f | %.1f | - |"
        % (tot["count"], tot["prompt"], tot["completion"], tot["dur"] / 1000.0, tot["latency_ms"] / 1000.0)
    )
    text = "\n".join(lines) + "\n"

    out: Path = (args.out or run_dir / "cost_summary.md").resolve()
    out.write_text(text, encoding="utf-8")
    print(text)
    print(f"[written] {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
