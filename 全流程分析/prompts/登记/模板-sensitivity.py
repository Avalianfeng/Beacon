# -*- coding: utf-8 -*-
"""<题ID> · 图内敏感性插座（inject/sensitivity.py）。

契约与验收见 全流程分析/prompts/登记/契约-代码插座.md。
按研究网格【重算】，不把研究 CSV 的敏感性数字原样交差。
"""
from __future__ import annotations

import csv
from pathlib import Path


def _source_dir() -> Path:
    """定位 source/。图内由 sensitivity 节点 exec 注入 data_dir（题根 source/）。
    不要用文本拼接注入 data_dir（from __future__ 等会挤到文件头之外 → SyntaxError）。"""
    dd = globals().get("data_dir")
    if dd is not None:
        p = Path(dd)
        if not p.is_absolute():
            p = p.resolve()
        return p.parent if p.name == "inject" else p
    here = Path(__file__).resolve()
    if here.parent.name == "inject":  # source/inject/sensitivity.py → parents[1] = source
        return here.parents[1]
    raise SystemExit("sensitivity: 无法定位 source/（无 data_dir 且无 __file__）")


SRC = _source_dir()
ROOT = SRC.parent if SRC.name == "source" else SRC
DATA = ROOT / "研究" / "data"


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def _f(row: dict[str, str], key: str) -> float:
    return float(row[key])


def _emit(parameter: str, values: list[float], results: list[float]) -> None:
    """输出约定：parameter 名必须与 plan.json 的 sensitivity_relevant 钉死
    的名字一致（中文名带英文别名括号）；values/results 等长。"""
    assert len(values) == len(results) and len(values) >= 3
    print(f"RESULT: parameter={parameter} values={values} results={results}")


# ---------------------------------------------------------------------------
# TODO: 读研究计划表（补货/成本/损耗等），参数网格来自研究结论
#   plan = _read_csv(DATA / "<补货计划>.csv")
# ---------------------------------------------------------------------------

# TODO: 网格 1 —— 例：成本冲击 ±20%；总收益按成本缩放重算
# shocks = [-0.2, -0.1, 0.0, 0.1, 0.2]
# profit = [...重算...]
# _emit("成本冲击 (cost_shock)", shocks, profit)

# TODO: 网格 2 —— 例：加成分位（注意与主方案口径一致：q=d/(1-λ) 之类）
# quantiles = [...]
# _emit("加成分位 (markup_p)", quantiles, profit)

# TODO: 网格 3 —— 例：损耗率缩放；缩放后 λ≥1 必须抛错（fail loud）
# _emit("损耗率缩放 (loss_scale)", scales, profit)

# TODO: 中心点对齐主方案（如与 _entry 的 q2_week_profit 一致），
#       否则解读/评审会说"对不上主结果"。参数网格不全时宁可少一行，不要硬凑。
