# Q2 一周品类方案 + Q3 7/1 硬池方案。需求用 BLEND。只读 source/。
from __future__ import annotations

import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "source"
DATA = ROOT / "研究" / "data"
FIG = ROOT / "研究" / "figures"
DIFF_Q3 = ROOT / "认知地图集" / "diff" / "data" / "Q3窗口SKU.csv"
SAT = ROOT / "认知地图集" / "diff" / "data" / "周六抬升_品类与硬池SKU.csv"

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

CATS = ["花叶类", "花菜类", "水生根茎类", "茄类", "辣椒类", "食用菌"]
LOSS_CAT = {
    "花菜类": 0.1551,
    "水生根茎类": 0.1365,
    "花叶类": 0.1283,
    "食用菌": 0.0945,
    "辣椒类": 0.0924,
    "茄类": 0.0668,
}
HEAD_943 = {
    "云南生菜(份)",
    "云南油麦菜(份)",
    "菠菜(份)",
    "小米椒(份)",
    "小皱皮(份)",
    "螺丝椒(份)",
    "姜蒜小米椒组合装(小份)",
    "枝江青梗散花",
}


def load():
    a1 = pd.read_excel(SRC / "附件1.xlsx", dtype={"单品编码": str})
    a2 = pd.read_excel(SRC / "附件2.xlsx", dtype={"单品编码": str})
    a2["销售日期"] = pd.to_datetime(a2["销售日期"]).dt.normalize()
    a3 = pd.read_excel(SRC / "附件3.xlsx", dtype={"单品编码": str})
    a3["日期"] = pd.to_datetime(a3["日期"]).dt.normalize()
    a4 = pd.read_excel(SRC / "附件4.xlsx", sheet_name=1, dtype={"单品编码": str})
    m = a2.merge(a1[["单品编码", "单品名称", "分类名称"]], on="单品编码")
    m = m.merge(a3.rename(columns={"日期": "销售日期"}), on=["销售日期", "单品编码"], how="left")
    m["额"] = m["销量(千克)"] * m["销售单价(元/千克)"]
    m["成本额"] = m["销量(千克)"] * m["批发价格(元/千克)"]
    return a1, m, a4


def cat_cost_markup(m: pd.DataFrame) -> pd.DataFrame:
    w0, w1 = pd.Timestamp("2023-06-24"), pd.Timestamp("2023-06-30")
    win = m[(m["销售日期"] >= w0) & (m["销售日期"] <= w1)]
    rec = m[(m["销售日期"] >= "2023-04-02") & (m["销售日期"] <= "2023-06-30")]
    rec_nd = rec[rec["是否打折销售"] == "否"].copy()
    rec_nd = rec_nd[rec_nd["销量(千克)"] > 0]
    rec_nd["加成"] = rec_nd["销售单价(元/千克)"] / rec_nd["批发价格(元/千克)"] - 1
    rows = []
    for cat in CATS:
        g = win[win["分类名称"] == cat]
        qty = g["销量(千克)"].sum()
        cost = (g["成本额"].sum() / qty) if qty else np.nan
        h = rec_nd[rec_nd["分类名称"] == cat]["加成"]
        rows.append(
            {
                "品类": cat,
                "窗加权批发_元kg": float(cost),
                "加成_P25": float(h.quantile(0.25)),
                "加成_P50": float(h.quantile(0.50)),
                "加成_P75": float(h.quantile(0.75)),
                "损耗率": LOSS_CAT[cat],
            }
        )
    return pd.DataFrame(rows)


def q2_plan(july: pd.DataFrame, cm: pd.DataFrame) -> pd.DataFrame:
    j = july.merge(cm, on="品类")
    j["需求_BLEND"] = j["BLEND"]
    j["加成"] = j["加成_P50"]
    j["售价"] = j["窗加权批发_元kg"] * (1 + j["加成"])
    j["补货"] = j["需求_BLEND"] / (1 - j["损耗率"])
    # 有界：卖完需求代理，可售=(1-λ)q = 需求
    j["收入"] = j["售价"] * j["需求_BLEND"]
    j["进货成本"] = j["窗加权批发_元kg"] * j["补货"]
    j["收益代理"] = j["收入"] - j["进货成本"]
    j["单位可售毛利"] = j["售价"] - j["窗加权批发_元kg"] / (1 - j["损耗率"])
    return j


def cost_shock(j: pd.DataFrame) -> pd.DataFrame:
    """标价按预期成本钉死，实际成本 ±10/20%。"""
    recs = []
    for shock in (-0.2, -0.1, 0.0, 0.1, 0.2):
        c = j["窗加权批发_元kg"] * (1 + shock)
        cost = c * j["补货"]
        profit = j["收入"] - cost  # 售价不变
        recs.append(
            {
                "成本冲击": shock,
                "周收益代理_元": float(profit.sum()),
                "相对0冲击": float(profit.sum() / j["收益代理"].sum() - 1) if j["收益代理"].sum() else np.nan,
            }
        )
    return pd.DataFrame(recs)


def markup_band(j: pd.DataFrame, cm: pd.DataFrame) -> pd.DataFrame:
    """需求固定时，加成带内收益只随 m 线性变。"""
    recs = []
    base = j[["日期", "品类", "需求_BLEND", "窗加权批发_元kg", "损耗率"]].merge(
        cm[["品类", "加成_P25", "加成_P50", "加成_P75"]], on="品类"
    )
    for col, name in [("加成_P25", "P25"), ("加成_P50", "P50"), ("加成_P75", "P75")]:
        p = base["窗加权批发_元kg"] * (1 + base[col])
        q = base["需求_BLEND"] / (1 - base["损耗率"])
        profit = p * base["需求_BLEND"] - base["窗加权批发_元kg"] * q
        recs.append({"加成点": name, "周收益代理_元": float(profit.sum())})
    return pd.DataFrame(recs)


def yoy_stress(july: pd.DataFrame, cm: pd.DataFrame) -> pd.DataFrame:
    """若真需求是 YOY，但按 BLEND 补货：可售过剩或不足。"""
    j = july.merge(cm, on="品类")
    d_hat = j["BLEND"]
    d_yoy = j["YOY"].clip(lower=0)
    lam = j["损耗率"]
    q = d_hat / (1 - lam)
    avail = (1 - lam) * q  # = d_hat
    sold = np.minimum(d_yoy, avail)
    p = j["窗加权批发_元kg"] * (1 + j["加成_P50"])
    profit = p * sold - j["窗加权批发_元kg"] * q
    out = j[["日期", "品类"]].copy()
    out["BLEND需求"] = d_hat
    out["YOY需求"] = d_yoy
    out["补货_按BLEND"] = q
    out["售出"] = sold
    out["缺货"] = (d_yoy - avail).clip(lower=0)
    out["剩余可售"] = (avail - d_yoy).clip(lower=0)
    out["收益_YOY情景"] = profit
    return out


def q3_plan(m: pd.DataFrame, a4: pd.DataFrame, july: pd.DataFrame, cm: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    q3 = pd.read_csv(DIFF_Q3, dtype={"单品编码": str})
    sat = pd.read_csv(SAT)
    sat_sku = sat[sat["层"] == "硬池SKU"][["名称", "比"]].rename(columns={"名称": "单品名称", "比": "周六比"})
    hard = q3[q3["硬池"]].copy()
    hard = hard.merge(sat_sku, on="单品名称", how="left")
    hard["周六比"] = hard["周六比"].fillna(hard.groupby("分类名称")["周六比"].transform("median"))
    # 7/1 品类需求
    d1 = july[july["日期"] == "2023-07-01"][["品类", "BLEND"]].rename(columns={"品类": "分类名称", "BLEND": "品类需求"})
    hard = hard.merge(d1, on="分类名称")
    hard["窗内品类份额"] = hard.groupby("分类名称")["net"].transform(lambda s: s / s.sum())
    hard["需求_7_1"] = hard["品类需求"] * hard["窗内品类份额"]
    hard["损耗率"] = hard["损耗率(%)"] / 100.0
    hard["损耗_品类"] = hard["分类名称"].map(LOSS_CAT)
    # 成本：窗口 成本额/净销
    hard["批发"] = hard["cost"] / hard["net"]
    # SKU 加成：窗口非打折，不足则用品类 P50
    w0, w1 = pd.Timestamp("2023-06-24"), pd.Timestamp("2023-06-30")
    win = m[(m["销售日期"] >= w0) & (m["销售日期"] <= w1)]
    win_nd = win[(win["是否打折销售"] == "否") & (win["销量(千克)"] > 0)].copy()
    win_nd["加成"] = win_nd["销售单价(元/千克)"] / win_nd["批发价格(元/千克)"] - 1
    sku_m = win_nd.groupby("单品编码")["加成"].median()
    hard["加成"] = hard["单品编码"].map(sku_m)
    hard = hard.merge(cm[["品类", "加成_P50"]].rename(columns={"品类": "分类名称"}), on="分类名称")
    hard["加成"] = hard["加成"].fillna(hard["加成_P50"])
    hard["售价"] = hard["批发"] * (1 + hard["加成"])

    def apply_q(df, loss_col):
        out = df.copy()
        lam = out[loss_col]
        need = out["需求_7_1"] / (1 - lam)
        out["补货"] = np.maximum(2.5, need)
        out["可售"] = (1 - lam) * out["补货"]
        out["售出"] = np.minimum(out["需求_7_1"], out["可售"])
        out["收入"] = out["售价"] * out["售出"]
        out["进货成本"] = out["批发"] * out["补货"]
        out["收益代理"] = out["收入"] - out["进货成本"]
        out["抬到2.5"] = need < 2.5
        return out

    main = apply_q(hard, "损耗率")
    # 敏感性：头部 9.43 改用品类损耗
    alt = hard.copy()
    mask = alt["单品名称"].isin(HEAD_943)
    alt.loc[mask, "损耗率"] = alt.loc[mask, "损耗_品类"]
    alt943 = apply_q(alt, "损耗率")

    # 27：硬池按收益代理丢掉最低 2 个，但每品类至少 1
    ranked = main.sort_values("收益代理")
    drop = []
    for _, r in ranked.iterrows():
        remain_cat = main.loc[~main["单品编码"].isin(drop + [r["单品编码"]])]
        if (remain_cat["分类名称"] == r["分类名称"]).sum() >= 1 and len(drop) < 2:
            drop.append(r["单品编码"])
    plan27 = apply_q(hard[~hard["单品编码"].isin(drop)], "损耗率")

    # 33：硬池 + 下 4 个日均最高非硬池，补货至少 2.5
    rest = q3[~q3["硬池"]].sort_values("日均", ascending=False).head(4).copy()
    rest = rest.merge(d1, on="分类名称")
    # 这 4 个不从品类需求再分份额（否则会挤硬池）；按其窗日均×品类周六比给一个小需求
    cat_sat = sat[sat["层"] == "品类"][["名称", "比"]].rename(columns={"名称": "分类名称", "比": "周六比"})
    rest = rest.merge(cat_sat, on="分类名称", how="left")
    rest["需求_7_1"] = rest["日均"] * rest["周六比"].fillna(1.3)
    rest["损耗率"] = rest["损耗率(%)"] / 100.0
    rest["损耗_品类"] = rest["分类名称"].map(LOSS_CAT)
    rest["批发"] = rest["cost"] / rest["net"].replace(0, np.nan)
    rest["加成"] = rest["单品编码"].map(sku_m)
    rest = rest.merge(cm[["品类", "加成_P50"]].rename(columns={"品类": "分类名称"}), on="分类名称")
    rest["加成"] = rest["加成"].fillna(rest["加成_P50"])
    rest["售价"] = rest["批发"] * (1 + rest["加成"])
    rest["窗内品类份额"] = np.nan
    plan33 = apply_q(pd.concat([hard, rest], ignore_index=True), "损耗率")

    summary = pd.DataFrame(
        [
            {"方案": "硬池29", "n": len(main), "补货kg": float(main["补货"].sum()), "收益代理": float(main["收益代理"].sum()), "品类覆盖": int(main["分类名称"].nunique())},
            {"方案": "缩27", "n": len(plan27), "补货kg": float(plan27["补货"].sum()), "收益代理": float(plan27["收益代理"].sum()), "品类覆盖": int(plan27["分类名称"].nunique())},
            {"方案": "扩33抬2.5", "n": len(plan33), "补货kg": float(plan33["补货"].sum()), "收益代理": float(plan33["收益代理"].sum()), "品类覆盖": int(plan33["分类名称"].nunique())},
            {"方案": "29_头部9.43改品类损耗", "n": len(alt943), "补货kg": float(alt943["补货"].sum()), "收益代理": float(alt943["收益代理"].sum()), "品类覆盖": int(alt943["分类名称"].nunique())},
        ]
    )
    main["方案"] = "硬池29"
    plan27["方案"] = "缩27"
    plan33["方案"] = "扩33"
    alt943["方案"] = "29_9.43改品类"
    allp = pd.concat([main, plan27, plan33, alt943], ignore_index=True)
    dropped = main.loc[main["单品编码"].isin(drop), ["单品名称", "分类名称", "收益代理"]]
    dropped.to_csv(DATA / "Q3_缩27丢掉的2个.csv", index=False, encoding="utf-8-sig")
    return allp, summary


def main():
    print("load...")
    a1, m, a4 = load()
    july = pd.read_csv(DATA / "Q2_7月周_四种预测.csv")
    cm = cat_cost_markup(m)
    cm.to_csv(DATA / "Q2_品类成本加成损耗.csv", index=False, encoding="utf-8-sig")

    j = q2_plan(july, cm)
    cols = [
        "日期", "星期名", "品类", "需求_BLEND", "YOY", "窗加权批发_元kg", "加成",
        "售价", "损耗率", "补货", "收入", "进货成本", "收益代理", "单位可售毛利",
    ]
    j[cols].to_csv(DATA / "Q2_7月周_补货定价.csv", index=False, encoding="utf-8-sig")
    week = j.groupby("品类", as_index=False).agg(
        周需求=("需求_BLEND", "sum"),
        周补货=("补货", "sum"),
        周收益=("收益代理", "sum"),
        日均售价=("售价", "mean"),
        加成=("加成", "first"),
        批发=("窗加权批发_元kg", "first"),
    )
    week.to_csv(DATA / "Q2_周汇总.csv", index=False, encoding="utf-8-sig")
    shock = cost_shock(j)
    shock.to_csv(DATA / "Q2_成本冲击_粘性售价.csv", index=False, encoding="utf-8-sig")
    band = markup_band(j, cm)
    band.to_csv(DATA / "Q2_加成带收益.csv", index=False, encoding="utf-8-sig")
    yoy = yoy_stress(july, cm)
    yoy.to_csv(DATA / "Q2_YOY压力_按BLEND补货.csv", index=False, encoding="utf-8-sig")

    print("Q2 week profit", float(j["收益代理"].sum()))
    print(week.to_string(index=False))
    print(shock.to_string(index=False))
    print(band.to_string(index=False))
    print("YOY stress week profit", float(yoy["收益_YOY情景"].sum()), "stockout kg", float(yoy["缺货"].sum()), "leftover", float(yoy["剩余可售"].sum()))

    allp, summary = q3_plan(m, a4, july, cm)
    allp.to_csv(DATA / "Q3_方案明细.csv", index=False, encoding="utf-8-sig")
    summary.to_csv(DATA / "Q3_方案对照.csv", index=False, encoding="utf-8-sig")
    print(summary.to_string(index=False))

    # 图：Q2 一周补货
    fig, ax = plt.subplots(figsize=(9, 4.2))
    piv = j.pivot(index="日期", columns="品类", values="补货")
    piv.plot(kind="bar", stacked=True, ax=ax, width=0.8)
    ax.set_ylabel("补货量 (kg)")
    ax.set_title("Q2：2023-07-01–07 品类日补货（BLEND 需求 / (1−损耗)）")
    ax.legend(ncol=3, fontsize=8)
    fig.tight_layout()
    fig.savefig(FIG / "Q2_一周补货堆叠.png", dpi=140)
    plt.close(fig)

    main29 = allp[allp["方案"] == "硬池29"].sort_values("补货", ascending=False)
    fig, ax = plt.subplots(figsize=(9, 5.5))
    ax.barh(main29["单品名称"], main29["补货"], color="#2a6f97")
    ax.axvline(2.5, color="0.3", ls="--", lw=1)
    ax.set_xlabel("补货 (kg)")
    ax.set_title("Q3：7/1 硬池 29 补货量")
    fig.tight_layout()
    fig.savefig(FIG / "Q3_硬池29补货.png", dpi=140)
    plt.close(fig)

    (DATA / "Q2Q3_摘要.json").write_text(
        json.dumps(
            {
                "Q2周收益代理": float(j["收益代理"].sum()),
                "Q2周补货kg": float(j["补货"].sum()),
                "Q3_29收益": float(summary.loc[summary["方案"] == "硬池29", "收益代理"].iloc[0]),
                "Q3对照": summary.to_dict(orient="records"),
                "加成带": band.to_dict(orient="records"),
                "成本冲击": shock.to_dict(orient="records"),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
