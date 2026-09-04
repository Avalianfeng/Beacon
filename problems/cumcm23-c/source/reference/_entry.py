# -*- coding: utf-8 -*-
"""cumcm23-c · Beacon S5 适配入口（读研究/data 摘要，不重扫附件2）。

由 `math-agent reference add/run` 执行。打印 RESULT + Q1..Q4 行供 verify。
"""
from __future__ import annotations

import csv
import json
import os
import re
from pathlib import Path


def _problem_root() -> Path:
    # reference run wrapper：exec(..., {"data_dir": <绝对 source/>})，不传 __file__。
    # cwd 是 runs/<id>-reference，不能当题根。
    dd = globals().get("data_dir")
    if dd is not None:
        d = Path(dd)
        if not d.is_absolute():
            d = d.resolve()
        return d.parent if d.name == "source" else d
    f = globals().get("__file__")
    if f is not None:
        # source/reference/_entry.py → parents[2] = 题根
        p = Path(f).resolve()
        if p.parent.name == "reference":
            return p.parents[2]
    env = os.environ.get("MATH_AGENT_DATA_DIR")
    if env:
        d = Path(env)
        return d.parent if d.name == "source" else d
    return Path.cwd()


ROOT = _problem_root()
DATA = ROOT / "研究" / "data"

bt = json.loads((DATA / "Q2回测_摘要.json").read_text(encoding="utf-8"))
sm = json.loads((DATA / "Q2Q3_摘要.json").read_text(encoding="utf-8"))

mae = bt["合计MAE"]
blend_mae = float(mae["BLEND"])
wd90_mae = float(mae["WD90"])
yoy_mae = float(mae["YOY"])

q2_profit = float(sm["Q2周收益代理"])
q2_qty = float(sm["Q2周补货kg"])

band = {str(x["加成点"]): float(x["周收益代理_元"]) for x in sm["加成带"]}
p25, p50, p75 = band["P25"], band["P50"], band["P75"]
ctrl_n = sorted({int(x["n"]) for x in sm["Q3对照"]})
q3_29_profit = float(sm["Q3_29收益"])
spoil_m = re.search(r"(\d+\.\d+)", next(
    str(x["方案"]) for x in sm["Q3对照"] if "9.43" in str(x["方案"])
))
spoilage_head = float(spoil_m.group(1)) if spoil_m else float("nan")
cost_shock_pct = int(round(max(abs(float(x["成本冲击"])) for x in sm["成本冲击"]) * 100))

rows28 = list(
    csv.DictReader((DATA / "Q3_主方案_去高瓜28.csv").open(encoding="utf-8-sig"))
)
q3_n = len(rows28)
q3_profit = sum(float(r["收益代理"]) for r in rows28)
q3_qty = sum(float(r["补货"]) for r in rows28)

# 健全性：无 nan
vals = [
    blend_mae, wd90_mae, yoy_mae, q2_profit, q2_qty, q3_profit, q3_qty,
    float(q3_n), p25, p50, p75, q3_29_profit, spoilage_head,
]
assert all(v == v and abs(v) != float("inf") for v in vals)
assert q3_n == 28
assert blend_mae < wd90_mae < yoy_mae
assert ctrl_n == [27, 29, 33]

print(
    f"Q1: note=distribution_corr_not_elasticity "
    f"blend_beats_yoy=1 blend_mae={blend_mae:.4f}"
)
print(
    f"Q2: demand=BLEND week_qty_kg={q2_qty:.4f} week_profit={q2_profit:.4f} "
    f"blend_mae={blend_mae:.4f} wd90_mae={wd90_mae:.4f} yoy_mae={yoy_mae:.4f} "
    f"mae_list=[{blend_mae:.4f},{wd90_mae:.4f},{yoy_mae:.4f}] "
    f"week_list=[{q2_qty:.4f},{q2_profit:.4f}] "
    f"markup_p=[25,50,75] "
    f"markup_profit=[{p25:.4f},{p50:.4f},{p75:.4f}] "
    f"cost_shock_pct={cost_shock_pct}"
)
print(
    f"Q3: scheme=drop_neg_margin_28 n={q3_n} qty_kg={q3_qty:.4f} "
    f"profit={q3_profit:.4f} metrics=[{q3_n},{q3_qty:.4f},{q3_profit:.4f}] "
    f"ctrl_n=[{','.join(str(x) for x in ctrl_n)}] "
    f"pool_n=29 q3_29_profit={q3_29_profit:.4f} spoilage_head={spoilage_head}"
)
print(
    "Q4: priority=inbound_stock_spoilage_stockout price_discount_split "
    "shelf_slots=1"
)
print(
    f"RESULT: baseline=ours blend_mae={blend_mae:.4f} "
    f"q2_week_profit={q2_profit:.4f} q2_week_qty={q2_qty:.4f} "
    f"q3_n={q3_n} q3_profit={q3_profit:.4f} q3_qty={q3_qty:.4f}"
)
