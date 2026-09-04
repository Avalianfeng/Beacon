# Q2 需求主锚走步回测。不联网、只读 source/。
from __future__ import annotations

import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "source"
OUT = ROOT / "研究"
DATA = OUT / "data"
FIG = OUT / "figures"
DATA.mkdir(parents=True, exist_ok=True)
FIG.mkdir(parents=True, exist_ok=True)

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

CATS = ["花叶类", "花菜类", "水生根茎类", "茄类", "辣椒类", "食用菌"]
WD_NAME = "一二三四五六日"


def load_cat_day() -> pd.DataFrame:
    a1 = pd.read_excel(SRC / "附件1.xlsx", dtype={"单品编码": str})
    a2 = pd.read_excel(SRC / "附件2.xlsx", dtype={"单品编码": str})
    a2["销售日期"] = pd.to_datetime(a2["销售日期"]).dt.normalize()
    m = a2.merge(a1[["单品编码", "分类名称"]], on="单品编码", how="left")
    dc = m.groupby(["销售日期", "分类名称"], as_index=False)["销量(千克)"].sum()
    dc = dc.rename(columns={"销量(千克)": "qty", "分类名称": "品类"})
    # 日历补 0：店有销售的日，缺品类当 0
    all_days = pd.DatetimeIndex(sorted(a2["销售日期"].unique()))
    grid = pd.MultiIndex.from_product([all_days, CATS], names=["销售日期", "品类"])
    dc = dc.set_index(["销售日期", "品类"]).reindex(grid, fill_value=0.0).reset_index()
    dc["星期"] = dc["销售日期"].dt.dayofweek
    return dc.sort_values(["品类", "销售日期"]).reset_index(drop=True)


def walk_forward(dc: pd.DataFrame) -> pd.DataFrame:
    """对 2023-04-01..06-30 每个有记录日、每个品类给出四种预测。"""
    start, end = pd.Timestamp("2023-04-01"), pd.Timestamp("2023-06-30")
    days = sorted(dc.loc[(dc["销售日期"] >= start) & (dc["销售日期"] <= end), "销售日期"].unique())
    rows = []
    by = {cat: g.set_index("销售日期")["qty"] for cat, g in dc.groupby("品类")}
    for t in days:
        t = pd.Timestamp(t)
        wd = int(t.dayofweek)
        yoy_t = t - pd.DateOffset(years=1)
        for cat in CATS:
            s = by[cat]
            hist = s[s.index < t]
            win90 = hist[hist.index >= t - pd.Timedelta(days=90)]
            win7 = hist[hist.index >= t - pd.Timedelta(days=7)]
            actual = float(s.loc[t]) if t in s.index else np.nan
            wd90 = win90[win90.index.dayofweek == wd]
            f_wd90 = float(wd90.mean()) if len(wd90) else np.nan
            f_win7 = float(win7.mean()) if len(win7) else np.nan
            f_yoy = float(s.loc[yoy_t]) if yoy_t in s.index else np.nan
            mu90 = float(win90.mean()) if len(win90) else np.nan
            if np.isfinite(f_wd90) and np.isfinite(f_win7) and mu90 and mu90 > 0:
                f_blend = f_wd90 * (f_win7 / mu90)
            else:
                f_blend = np.nan
            rows.append(
                {
                    "日期": t.date().isoformat(),
                    "星期": wd,
                    "品类": cat,
                    "实际": actual,
                    "WD90": f_wd90,
                    "WIN7": f_win7,
                    "YOY": f_yoy,
                    "BLEND": f_blend,
                }
            )
    return pd.DataFrame(rows)


def metrics(df: pd.DataFrame) -> pd.DataFrame:
    recs = []
    methods = ["WD90", "WIN7", "YOY", "BLEND"]
    for cat in ["合计"] + CATS:
        sub = df if cat == "合计" else df[df["品类"] == cat]
        for m in methods:
            a = sub["实际"].to_numpy(dtype=float)
            p = sub[m].to_numpy(dtype=float)
            mask = np.isfinite(a) & np.isfinite(p)
            a, p = a[mask], p[mask]
            if len(a) == 0:
                continue
            mae = float(np.mean(np.abs(a - p)))
            mape = float(np.mean(np.abs(a - p) / np.clip(np.abs(a), 1e-6, None)))
            bias = float(np.mean(p - a))
            recs.append(
                {
                    "范围": cat,
                    "方法": m,
                    "n": int(len(a)),
                    "MAE": mae,
                    "MAPE": mape,
                    "偏差_预测减实际": bias,
                }
            )
    return pd.DataFrame(recs)


def july_forecast(dc: pd.DataFrame) -> pd.DataFrame:
    """用 6/30 截止的信息预测 7/1–7/7。四种方法都出，主方法后选。"""
    t0 = pd.Timestamp("2023-07-01")
    cut = pd.Timestamp("2023-06-30")
    rows = []
    by = {cat: g.set_index("销售日期")["qty"] for cat, g in dc.groupby("品类")}
    win_start = pd.Timestamp("2023-06-24")
    for i in range(7):
        t = t0 + pd.Timedelta(days=i)
        wd = int(t.dayofweek)
        yoy_t = t - pd.DateOffset(years=1)
        for cat in CATS:
            s = by[cat]
            hist = s[s.index <= cut]
            win90 = hist[hist.index >= t0 - pd.Timedelta(days=90)]
            win7 = hist[(hist.index >= win_start) & (hist.index <= cut)]
            wd90 = win90[win90.index.dayofweek == wd]
            f_wd90 = float(wd90.mean()) if len(wd90) else np.nan
            f_win7 = float(win7.mean()) if len(win7) else np.nan
            f_yoy = float(s.loc[yoy_t]) if yoy_t in s.index else np.nan
            mu90 = float(win90.mean()) if len(win90) else np.nan
            f_blend = f_wd90 * (f_win7 / mu90) if mu90 and mu90 > 0 else np.nan
            rows.append(
                {
                    "日期": t.date().isoformat(),
                    "星期": wd,
                    "星期名": WD_NAME[wd],
                    "品类": cat,
                    "WD90": f_wd90,
                    "WIN7": f_win7,
                    "YOY": f_yoy,
                    "BLEND": f_blend,
                    "窗7日均": f_win7,
                    "近90日均": mu90,
                }
            )
    return pd.DataFrame(rows)


def main():
    print("load...")
    dc = load_cat_day()
    dc.to_csv(DATA / "品类日销量_日历补0.csv", index=False, encoding="utf-8-sig")
    print("walk-forward...")
    bt = walk_forward(dc)
    bt.to_csv(DATA / "Q2回测_202304-06_逐日.csv", index=False, encoding="utf-8-sig")
    met = metrics(bt)
    met.to_csv(DATA / "Q2回测_误差汇总.csv", index=False, encoding="utf-8-sig")
    print(met.to_string(index=False))

    july = july_forecast(dc)
    july.to_csv(DATA / "Q2_7月周_四种预测.csv", index=False, encoding="utf-8-sig")

    # 图：合计 MAE 条形
    tot = met[met["范围"] == "合计"].set_index("方法")["MAE"]
    fig, ax = plt.subplots(figsize=(7, 3.8))
    colors = {"WD90": "#2a6f97", "BLEND": "#4c956c", "WIN7": "#e8c547", "YOY": "#c56a6a"}
    ax.bar(tot.index, tot.values, color=[colors.get(i, "#888") for i in tot.index])
    ax.set_ylabel("MAE (kg / 品类日)")
    ax.set_title("2023-04–06 走步回测：品类日需求预测 MAE（合计）")
    fig.tight_layout()
    fig.savefig(FIG / "Q2回测_合计MAE.png", dpi=140)
    plt.close(fig)

    # 图：分品类 MAE
    fig, ax = plt.subplots(figsize=(9, 4.2))
    piv = met[met["范围"] != "合计"].pivot(index="范围", columns="方法", values="MAE").reindex(CATS)
    x = np.arange(len(CATS))
    w = 0.18
    for i, col in enumerate(["WD90", "BLEND", "WIN7", "YOY"]):
        ax.bar(x + (i - 1.5) * w, piv[col].to_numpy(), width=w, label=col)
    ax.set_xticks(x)
    ax.set_xticklabels(CATS)
    ax.set_ylabel("MAE (kg)")
    ax.set_title("分品类走步回测 MAE")
    ax.legend()
    fig.tight_layout()
    fig.savefig(FIG / "Q2回测_分品类MAE.png", dpi=140)
    plt.close(fig)

    # 胜者：合计 MAE 最低
    winner = tot.idxmin()
    summary = {
        "回测窗": "2023-04-01..06-30",
        "合计MAE": {k: float(v) for k, v in tot.items()},
        "胜者_合计MAE": winner,
        "日历补0": True,
        "BLEND定义": "WD90 * (近7日均 / 近90日均)",
    }
    (DATA / "Q2回测_摘要.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("winner", winner)


if __name__ == "__main__":
    main()
