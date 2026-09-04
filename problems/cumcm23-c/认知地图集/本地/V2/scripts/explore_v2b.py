"""续算：星期去均值后品类相关；Q3 候选池约束粗探（非求解定案）。"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

DATA = Path(__file__).resolve().parents[1] / "data"
CAT_ORDER = ["花叶类", "花菜类", "水生根茎类", "茄类", "辣椒类", "食用菌"]


def main() -> None:
    panel = pd.read_csv(DATA / "品类日面板.csv", parse_dates=["日期"])
    panel["日期"] = panel["日期"].dt.date
    start, end = pd.Timestamp("2022-07-01").date(), pd.Timestamp("2023-06-30").date()
    sub = panel[(panel["日期"] >= start) & (panel["日期"] <= end)].copy()
    # 去星期均值
    sub["wd_mean"] = sub.groupby(["品类", "星期"])["净销量_kg"].transform("mean")
    sub["resid"] = sub["净销量_kg"] - sub["wd_mean"]
    wide = sub.pivot(index="日期", columns="品类", values="resid")[CAT_ORDER]
    corr = wide.corr()
    corr.to_csv(DATA / "品类日相关_近365_去星期.csv", encoding="utf-8-sig")
    print("去星期后相关:\n", corr.round(3))

    # 原始近365也读一下对比
    raw = pd.read_csv(DATA / "品类日相关_近365.csv", index_col=0)
    print("\n原始-去星期 差值:\n", (raw - corr).round(3))

    win = pd.read_csv(DATA / "Q3窗口SKU画像.csv")
    # 候选：日均>=2.5 共29，落在27-33内；若放宽用「窗口至少1天且补货抬到2.5」
    hard = win[win["日均是否>=2.5"]].copy()
    soft = win.copy()
    print("\n硬约束日均>=2.5: n=", len(hard), "按品类:\n", hard.groupby("品类").size())
    # 按窗口销量排序取 top27 / top33
    ranked = win.sort_values("窗口净销量_kg", ascending=False)
    for k in (27, 29, 33):
        top = ranked.head(k)
        print(f"\n按窗口销量 top{k}:")
        print(top.groupby("品类").size())
        print("其中日均<2.5个数", int((~top["日均是否>=2.5"]).sum()))

    # 硬池29已在区间；若强制每品类至少1个：硬池已覆盖6品类
    print("\n硬池是否覆盖6品类:", set(hard["品类"]) == set(CAT_ORDER))

    # 粗利润代理：窗口日均 * 近窗口批发中位 * 假设加成0.5 * (1-loss/100) — 仅排序敏感度
    hard = hard.copy()
    hard["粗单位毛利代理"] = hard["窗口批发价中位"] * 0.5 * (1 - hard["单品损耗率pct"] / 100.0)
    hard["粗日贡献代理"] = hard["窗口日均_kg"] * hard["粗单位毛利代理"]
    by_contrib = hard.sort_values("粗日贡献代理", ascending=False)
    print("\n硬池按粗贡献 top10:")
    print(by_contrib.head(10)[["单品名称", "品类", "窗口日均_kg", "粗日贡献代理"]].to_string(index=False))
    # 若从硬池29再砍到27：砍掉贡献最低2个
    drop2 = by_contrib.tail(2)["单品名称"].tolist()
    print("硬池砍到27时末两位:", drop2)

    # 近90同星期基线周合计 vs 历年7月初
    fc = pd.read_csv(DATA / "2023-07周_近90同星期基线.csv")
    hist = pd.read_csv(DATA / "历年7月初周汇总.csv")
    fc_week = fc.groupby("品类", as_index=False)["近90同星期日均_kg"].sum()
    fc_week = fc_week.rename(columns={"近90同星期日均_kg": "近90同星期周合计代理"})
    cmp = hist.merge(fc_week, on="品类")
    cmp["相对2022周合计"] = cmp["近90同星期周合计代理"] / cmp.loc[cmp["年"] == 2022].set_index("品类").loc[cmp["品类"], "周合计"].values
    # cleaner
    h2022 = hist[hist["年"] == 2022][["品类", "周合计"]].rename(columns={"周合计": "2022周合计"})
    out = fc_week.merge(h2022, on="品类")
    out["代理/2022"] = out["近90同星期周合计代理"] / out["2022周合计"]
    out.to_csv(DATA / "7月周需求基线对照.csv", index=False, encoding="utf-8-sig")
    print("\n基线对照:\n", out.to_string(index=False))


if __name__ == "__main__":
    main()
