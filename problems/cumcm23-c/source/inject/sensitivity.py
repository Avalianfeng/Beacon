# -*- coding: utf-8 -*-
"""cumcm23-c 图内敏感性：按研究参数网格重跑，不以研究 CSV 数字交差。

图执行时由 sensitivity 节点注入 ``data_dir``（题根 ``source/``）。
网格与研究脚本 02_q2q3_plan 一致：成本冲击、加成分位、损耗率缩放。
"""
from __future__ import annotations

import csv
from pathlib import Path


def _source_dir() -> Path:
    dd = globals().get("data_dir")
    if dd is not None:
        p = Path(dd)
        if not p.is_absolute():
            p = p.resolve()
        return p.parent if p.name == "inject" else p
    here = Path(__file__).resolve()
    if here.parent.name == "inject":
        return here.parents[1]
    raise SystemExit("sensitivity: 缺少 data_dir，且无法从 __file__ 推断 source/")


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def _f(row: dict[str, str], key: str) -> float:
    return float(row[key])


def _emit(parameter: str, values: list[float], results: list[float]) -> None:
    print(f"RESULT: parameter={parameter} values={values} results={results}")


def _markup_at(cm: dict[str, dict[str, float]], cat: str, q: float) -> float:
    p25, p50, p75 = cm[cat]["p25"], cm[cat]["p50"], cm[cat]["p75"]
    if q <= 50.0:
        t = (q - 25.0) / 25.0
        return p25 + t * (p50 - p25)
    t = (q - 50.0) / 25.0
    return p50 + t * (p75 - p50)


SRC = _source_dir()
ROOT = SRC.parent if SRC.name == "source" else SRC
DATA = ROOT / "研究" / "data"
PLAN_PATH = DATA / "Q2_7月周_补货定价.csv"
CM_PATH = DATA / "Q2_品类成本加成损耗.csv"
if not PLAN_PATH.is_file() or not CM_PATH.is_file():
    raise SystemExit(f"sensitivity: 缺少研究计划表 {PLAN_PATH} 或 {CM_PATH}")

plan = _read_csv(PLAN_PATH)
cm_rows = _read_csv(CM_PATH)
cm = {
    r["品类"]: {
        "p25": _f(r, "加成_P25"),
        "p50": _f(r, "加成_P50"),
        "p75": _f(r, "加成_P75"),
    }
    for r in cm_rows
}

shocks = [-0.2, -0.1, 0.0, 0.1, 0.2]
shock_profit = []
for shock in shocks:
    total = 0.0
    for row in plan:
        cost = _f(row, "窗加权批发_元kg") * (1.0 + shock) * _f(row, "补货")
        total += _f(row, "收入") - cost
    shock_profit.append(round(total, 6))
_emit("成本冲击 (cost_shock)", shocks, shock_profit)

quantiles = [25.0, 37.5, 50.0, 62.5, 75.0]
markup_profit = []
for q in quantiles:
    total = 0.0
    for row in plan:
        cat = row["品类"]
        wholesale = _f(row, "窗加权批发_元kg")
        demand = _f(row, "需求_BLEND")
        lam = _f(row, "损耗率")
        price = wholesale * (1.0 + _markup_at(cm, cat, q))
        qty = demand / (1.0 - lam)
        total += price * demand - wholesale * qty
    markup_profit.append(round(total, 6))
_emit("加成分位 (markup_p)", quantiles, markup_profit)

scales = [0.8, 0.9, 1.0, 1.1, 1.2]
loss_profit = []
for scale in scales:
    total = 0.0
    for row in plan:
        lam = _f(row, "损耗率") * scale
        if lam >= 1.0:
            raise RuntimeError(f"sensitivity: 损耗率缩放后非法 λ={lam}")
        demand = _f(row, "需求_BLEND")
        wholesale = _f(row, "窗加权批发_元kg")
        price = _f(row, "售价")
        qty = demand / (1.0 - lam)
        total += price * demand - wholesale * qty
    loss_profit.append(round(total, 6))
_emit("损耗率缩放 (loss_scale)", scales, loss_profit)
