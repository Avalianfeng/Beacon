# Diff 自算：核对双方冲突与结合方向。不闭合进货/最优价。
from __future__ import annotations

import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]  # problems/cumcm23-c
SRC = ROOT / "source"
OUT = Path(__file__).resolve().parents[1]
DATA = OUT / "data"
FIG = OUT / "figures"
DATA.mkdir(exist_ok=True)
FIG.mkdir(exist_ok=True)

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

CATS = ["花叶类", "花菜类", "水生根茎类", "茄类", "辣椒类", "食用菌"]


def load():
    a1 = pd.read_excel(SRC / "附件1.xlsx", dtype={"单品编码": str, "分类编码": str})
    a2 = pd.read_excel(SRC / "附件2.xlsx", dtype={"单品编码": str})
    a2["销售日期"] = pd.to_datetime(a2["销售日期"])
    a3 = pd.read_excel(SRC / "附件3.xlsx", dtype={"单品编码": str})
    a3["日期"] = pd.to_datetime(a3["日期"])
    a4 = pd.read_excel(SRC / "附件4.xlsx", sheet_name=1, dtype={"单品编码": str})
    m = a2.merge(a1[["单品编码", "单品名称", "分类名称"]], on="单品编码", how="left")
    m = m.merge(
        a3.rename(columns={"日期": "销售日期"}),
        on=["销售日期", "单品编码"],
        how="left",
    )
    m["额"] = m["销量(千克)"] * m["销售单价(元/千克)"]
    m["成本额"] = m["销量(千克)"] * m["批发价格(元/千克)"]
    m["星期"] = m["销售日期"].dt.dayofweek
    return a1, a2, a3, a4, m


def cat_day(m: pd.DataFrame) -> pd.DataFrame:
    dc = m.groupby(["销售日期", "分类名称"], as_index=False).agg(
        qty=("销量(千克)", "sum"),
        rev=("额", "sum"),
        cost=("成本额", "sum"),
    )
    dc = dc[dc["qty"] > 0].copy()
    dc["w_price"] = dc["rev"] / dc["qty"]
    dc["w_cost"] = dc["cost"] / dc["qty"]
    dc["加成"] = dc["w_price"] / dc["w_cost"] - 1
    dc["星期"] = dc["销售日期"].dt.dayofweek
    dc["年月"] = dc["销售日期"].dt.to_period("M").astype(str)
    return dc


def corr_markup_qty(dc: pd.DataFrame, label: str) -> pd.DataFrame:
    rows = []
    for cat, g in dc.groupby("分类名称"):
        if len(g) < 20:
            continue
        r = float(np.corrcoef(g["加成"], g["qty"])[0, 1])
        rows.append(
            {
                "窗口": label,
                "品类": cat,
                "n": len(g),
                "pearson_加成_销量": r,
                "加成_p50": float(g["加成"].median()),
                "销量_p50": float(g["qty"].median()),
            }
        )
    return pd.DataFrame(rows)


def same_sku_pearson(m: pd.DataFrame, start: str | None = None) -> pd.DataFrame:
    x = m[m["销量(千克)"] > 0].copy()
    if start:
        x = x[x["销售日期"] >= start]
    sd = x.groupby(["单品编码", "单品名称", "分类名称", "销售日期"], as_index=False).agg(
        qty=("销量(千克)", "sum"),
        rev=("额", "sum"),
    )
    sd["price"] = sd["rev"] / sd["qty"]
    rows = []
    for (sku, name, cat), g in sd.groupby(["单品编码", "单品名称", "分类名称"]):
        if len(g) < 10:
            continue
        if g["price"].std() == 0 or g["qty"].std() == 0:
            continue
        r = float(np.corrcoef(g["price"], g["qty"])[0, 1])
        rows.append(
            {
                "单品编码": sku,
                "单品名称": name,
                "品类": cat,
                "n日": len(g),
                "pearson_价_量": r,
            }
        )
    return pd.DataFrame(rows)


def residual_corr(dc: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    """品类日销量：对给定哑元回归后残差相关。"""
    wide = dc.pivot(index="销售日期", columns="分类名称", values="qty")
    meta = dc.drop_duplicates("销售日期")[["销售日期"] + cols]
    wide = wide.merge(meta, on="销售日期", how="left").set_index("销售日期")
    resid = {}
    for cat in CATS:
        if cat not in wide.columns:
            continue
        y = wide[cat].astype(float)
        mask = y.notna()
        dummies = pd.get_dummies(wide.loc[mask, cols], drop_first=True)
        X = np.column_stack([np.ones(mask.sum()), dummies.to_numpy(dtype=float)])
        beta, *_ = np.linalg.lstsq(X, y[mask].to_numpy(), rcond=None)
        r = pd.Series(np.nan, index=wide.index)
        r.loc[mask] = y[mask].to_numpy() - X @ beta
        resid[cat] = r
    rdf = pd.DataFrame(resid)
    return rdf.corr()


def q3_sets(m: pd.DataFrame, a3: pd.DataFrame, a4: pd.DataFrame) -> dict:
    w0, w1 = pd.Timestamp("2023-06-24"), pd.Timestamp("2023-06-30")
    win = m[(m["销售日期"] >= w0) & (m["销售日期"] <= w1)].copy()
    sku = (
        win.groupby(["单品编码", "单品名称", "分类名称"], as_index=False)
        .agg(
            net=("销量(千克)", "sum"),
            days=("销售日期", "nunique"),
            rev=("额", "sum"),
            cost=("成本额", "sum"),
        )
    )
    sku = sku[sku["net"] != 0].copy()
    sku["日均"] = sku["net"] / 7.0
    sku["硬池"] = sku["日均"] >= 2.5
    sku = sku.merge(a4[["单品编码", "损耗率(%)"]], on="单品编码", how="left")
    june = m[(m["销售日期"] >= "2023-06-01") & (m["销售日期"] <= "2023-06-30")]
    june_sku = set(june.loc[june["销量(千克)"] != 0, "单品编码"])
    sku["六月有售"] = sku["单品编码"].isin(june_sku)
    # 窗口有批发价但无销售
    a3w = a3[(a3["日期"] >= w0) & (a3["日期"] <= w1)]
    quoted = set(a3w["单品编码"])
    sold = set(sku["单品编码"])
    quoted_unsold = quoted - sold
    # 日 SKU
    daily = win.groupby(win["销售日期"].dt.date)["单品编码"].nunique()
    recent = m[m["销售日期"] >= "2023-04-01"]
    daily_r = recent.groupby(recent["销售日期"].dt.date)["单品编码"].nunique()
    hard = sku[sku["硬池"]].copy()
    cat_cov = hard.groupby("分类名称").size().to_dict()
    # topK
    sku_sorted = sku.sort_values("net", ascending=False)
    top27 = sku_sorted.head(27)
    top33 = sku_sorted.head(33)
    # 份装
    sku["份装"] = sku["单品名称"].str.contains(r"\(份\)|\(盒\)|\(包\)|\(袋\)", regex=True)
    # 配对：同名散称 vs 份
    names = sku[["单品编码", "单品名称", "分类名称", "日均", "硬池"]].copy()
    return {
        "sku": sku,
        "n_window": int(len(sku)),
        "n_hard": int(sku["硬池"].sum()),
        "cat_cov_hard": cat_cov,
        "cat_cov_win": sku.groupby("分类名称").size().to_dict(),
        "daily_win": daily.to_dict(),
        "daily_apr_min": int(daily_r.min()),
        "daily_apr_p50": float(daily_r.median()),
        "daily_apr_max": int(daily_r.max()),
        "n_quoted_unsold": len(quoted_unsold),
        "top27_all_hard": bool(top27["硬池"].all()),
        "top33_n_below": int((~top33["硬池"]).sum()),
        "top27_cat": top27.groupby("分类名称").size().to_dict(),
        "hard_cat": cat_cov,
        "share_hard_net": float(hard["net"].sum() / sku["net"].sum()),
        "share_portion_net": float(sku.loc[sku["份装"], "net"].sum() / sku["net"].sum()),
        "n_portion_hard": int(sku.loc[sku["硬池"] & sku["份装"]].shape[0]),
        "june_sold_not_in_win": int(len(june_sku - sold)),
    }


def saturday_lift(m: pd.DataFrame, hard_skus: list[str]) -> pd.DataFrame:
    rec = m[m["销售日期"] >= "2023-04-01"].copy()
    rec["is_sat"] = rec["星期"] == 5
    rows = []
    # 品类
    dc = rec.groupby(["销售日期", "分类名称", "is_sat"], as_index=False)["销量(千克)"].sum()
    for cat, g in dc.groupby("分类名称"):
        mu_all = g["销量(千克)"].mean()
        mu_sat = g.loc[g["is_sat"], "销量(千克)"].mean()
        rows.append({"层": "品类", "名称": cat, "总体日均": mu_all, "周六日均": mu_sat, "比": mu_sat / mu_all})
    # 硬池 SKU
    sd = rec[rec["单品编码"].isin(hard_skus)]
    sd = sd.groupby(["销售日期", "单品编码", "单品名称", "分类名称", "is_sat"], as_index=False)["销量(千克)"].sum()
    # 补 0：SKU 未出现的日
    dates = pd.Index(rec["销售日期"].dt.normalize().unique())
    for sku, g in sd.groupby("单品编码"):
        name = g["单品名称"].iloc[0]
        cat = g["分类名称"].iloc[0]
        by = g.groupby(g["销售日期"].dt.normalize())["销量(千克)"].sum()
        by = by.reindex(dates, fill_value=0.0)
        sat = dates.dayofweek == 5
        mu_all = by.mean()
        mu_sat = by[sat].mean() if sat.any() else np.nan
        rows.append(
            {
                "层": "硬池SKU",
                "名称": name,
                "品类": cat,
                "总体日均": mu_all,
                "周六日均": mu_sat,
                "比": mu_sat / mu_all if mu_all else np.nan,
            }
        )
    return pd.DataFrame(rows)


def main():
    print("loading...")
    a1, a2, a3, a4, m = load()
    dc = cat_day(m)
    summary = {}

    # --- V1 量加成：多窗口 ---
    windows = {
        "全期": dc,
        "近365": dc[dc["销售日期"] >= "2022-07-01"],
        "近90": dc[dc["销售日期"] >= "2023-04-02"],
        "近30": dc[dc["销售日期"] >= "2023-06-01"],
    }
    parts = [corr_markup_qty(g, k) for k, g in windows.items()]
    markup = pd.concat(parts, ignore_index=True)
    markup.to_csv(DATA / "量加成相关_多窗口.csv", index=False, encoding="utf-8-sig")
    print("markup windows written")

    # --- 同SKU ---
    sku_r = same_sku_pearson(m, start="2022-07-01")
    sku_r.to_csv(DATA / "同SKU价量_近365.csv", index=False, encoding="utf-8-sig")
    med = sku_r.groupby("品类")["pearson_价_量"].median()
    summary["同SKU价量中位_近365"] = {k: float(v) for k, v in med.items()}
    summary["同SKU_n"] = int(len(sku_r))
    summary["同SKU_|r|>0.3"] = int((sku_r["pearson_价_量"].abs() > 0.3).sum())
    print("same-sku", summary["同SKU价量中位_近365"])

    # --- 品类残差相关 ---
    raw = dc.pivot(index="销售日期", columns="分类名称", values="qty").corr()
    raw.to_csv(DATA / "品类相关_全期原始.csv", encoding="utf-8-sig")
    r_wd = residual_corr(dc[dc["销售日期"] >= "2022-07-01"], ["星期"])
    r_wd.to_csv(DATA / "品类残差相关_近365_去星期.csv", encoding="utf-8-sig")
    dc365 = dc[dc["销售日期"] >= "2022-07-01"].copy()
    r_m = residual_corr(dc365, ["年月"])
    r_m.to_csv(DATA / "品类残差相关_近365_去月份.csv", encoding="utf-8-sig")
    r_wm = residual_corr(dc365, ["星期", "年月"])
    r_wm.to_csv(DATA / "品类残差相关_近365_去星期和月份.csv", encoding="utf-8-sig")
    def offdiag_mean(c):
        a = c.loc[CATS, CATS].to_numpy(dtype=float)
        return float((a.sum() - np.trace(a)) / (a.size - len(CATS)))
    summary["品类相关_近365原始均值"] = offdiag_mean(
        dc365.pivot(index="销售日期", columns="分类名称", values="qty").corr()
    )
    summary["品类相关_去星期均值"] = offdiag_mean(r_wd)
    summary["品类相关_去月份均值"] = offdiag_mean(r_m)
    summary["品类相关_去星期月份均值"] = offdiag_mean(r_wm)
    # 茄类平均
    def eggplant_mean(c):
        return float(c.loc["茄类", [x for x in CATS if x != "茄类"]].mean())
    c365 = dc365.pivot(index="销售日期", columns="分类名称", values="qty").corr()
    summary["茄类_原始均值"] = eggplant_mean(c365)
    summary["茄类_去星期月份均值"] = eggplant_mean(r_wm)
    print("resid corr", summary["品类相关_近365原始均值"], summary["品类相关_去星期月份均值"])

    # --- Q3 ---
    q3 = q3_sets(m, a3, a4)
    q3["sku"].to_csv(DATA / "Q3窗口SKU.csv", index=False, encoding="utf-8-sig")
    for k in [
        "n_window",
        "n_hard",
        "cat_cov_hard",
        "cat_cov_win",
        "daily_win",
        "daily_apr_min",
        "daily_apr_p50",
        "daily_apr_max",
        "n_quoted_unsold",
        "top27_all_hard",
        "top33_n_below",
        "top27_cat",
        "share_hard_net",
        "share_portion_net",
        "n_portion_hard",
        "june_sold_not_in_win",
    ]:
        summary[k] = q3[k]
    print("Q3 hard", q3["n_hard"], "share", q3["share_hard_net"])

    # --- 周六 ---
    hard_ids = q3["sku"].loc[q3["sku"]["硬池"], "单品编码"].tolist()
    lift = saturday_lift(m, hard_ids)
    lift.to_csv(DATA / "周六抬升_品类与硬池SKU.csv", index=False, encoding="utf-8-sig")
    sku_lift = lift[lift["层"] == "硬池SKU"]
    summary["硬池SKU周六比_中位"] = float(sku_lift["比"].median())
    summary["硬池SKU周六比_p10"] = float(sku_lift["比"].quantile(0.1))
    summary["硬池SKU周六比_p90"] = float(sku_lift["比"].quantile(0.9))
    summary["品类周六比"] = {
        r["名称"]: float(r["比"]) for _, r in lift[lift["层"] == "品类"].iterrows()
    }
    print("sat lift sku median", summary["硬池SKU周六比_中位"])

    # --- 日历 ---
    summary["2023-07-01_星期"] = int(pd.Timestamp("2023-07-01").dayofweek)  # 5=Sat
    summary["目标周星期"] = [
        str(pd.Timestamp("2023-07-01") + pd.Timedelta(days=i))[:10]
        + "="
        + "一二三四五六日"[ (pd.Timestamp("2023-07-01") + pd.Timedelta(days=i)).dayofweek ]
        for i in range(7)
    ]

    # --- 近90打折销量占比（核对本地） ---
    rec = m[m["销售日期"] >= "2023-04-02"]
    disc = []
    for cat, g in rec.groupby("分类名称"):
        pos = g[g["销量(千克)"] > 0]
        disc.append(
            {
                "品类": cat,
                "打折销量占比": float(
                    pos.loc[pos["是否打折销售"] == "是", "销量(千克)"].sum()
                    / pos["销量(千克)"].sum()
                ),
            }
        )
    pd.DataFrame(disc).to_csv(DATA / "近90打折销量占比.csv", index=False, encoding="utf-8-sig")

    # --- 图1：量加成多窗口 ---
    fig, ax = plt.subplots(figsize=(9, 4.5))
    piv = markup.pivot(index="品类", columns="窗口", values="pearson_加成_销量").reindex(CATS)
    x = np.arange(len(CATS))
    w = 0.18
    for i, col in enumerate(["全期", "近365", "近90", "近30"]):
        ax.bar(x + (i - 1.5) * w, piv[col].to_numpy(), width=w, label=col)
    ax.axhline(0, color="0.4", lw=0.8)
    ax.set_xticks(x)
    ax.set_xticklabels(CATS)
    ax.set_ylabel("Pearson(加成率, 日销量)")
    ax.set_title("品类日：加成率–销量相关随窗口变化")
    ax.legend()
    fig.tight_layout()
    fig.savefig(FIG / "量加成相关_多窗口.png", dpi=140)
    plt.close(fig)

    # --- 图2：残差相关 ---
    fig, axes = plt.subplots(1, 3, figsize=(12, 3.8))
    mats = [
        (c365.loc[CATS, CATS], "近365 原始"),
        (r_m.loc[CATS, CATS], "去月份"),
        (r_wm.loc[CATS, CATS], "去星期+月份"),
    ]
    for ax, (mat, title) in zip(axes, mats):
        im = ax.imshow(mat.to_numpy(), vmin=-0.2, vmax=1, cmap="YlOrRd")
        ax.set_xticks(range(6))
        ax.set_yticks(range(6))
        ax.set_xticklabels([c[:2] for c in CATS], fontsize=8)
        ax.set_yticklabels([c[:2] for c in CATS], fontsize=8)
        ax.set_title(title)
        for i in range(6):
            for j in range(6):
                ax.text(j, i, f"{mat.iloc[i, j]:.2f}", ha="center", va="center", fontsize=7)
    fig.colorbar(im, ax=axes.ravel().tolist(), fraction=0.02)
    fig.suptitle("品类日销量相关：共同时间因子剥掉之后")
    fig.tight_layout()
    fig.savefig(FIG / "品类残差相关.png", dpi=140)
    plt.close(fig)

    # --- 图3：Q3 嵌套集合 ---
    fig, ax = plt.subplots(figsize=(8, 4.2))
    sku = q3["sku"].sort_values("日均", ascending=False).reset_index(drop=True)
    ax.bar(range(len(sku)), sku["日均"], color=["#2a6f97" if h else "#c56a6a" for h in sku["硬池"]])
    ax.axhline(2.5, color="0.2", ls="--", lw=1, label="最小陈列 2.5 kg")
    ax.axvline(26.5, color="0.3", ls=":", lw=1, label="第 27 名")
    ax.axvline(32.5, color="0.3", ls=":", lw=1, label="第 33 名")
    ax.set_xlabel("窗口 49 SKU（按日均降序）")
    ax.set_ylabel("窗口日均净销量 (kg)")
    ax.set_title("Q3：硬池 29 已落入 27–33；扩到 33 必带入 <2.5")
    ax.legend(loc="upper right")
    fig.tight_layout()
    fig.savefig(FIG / "Q3硬池与27-33.png", dpi=140)
    plt.close(fig)

    # --- 图4：日上架宽度 vs 27-33 ---
    recent = m[m["销售日期"] >= "2023-01-01"]
    daily_n = recent.groupby(recent["销售日期"].dt.date)["单品编码"].nunique()
    fig, ax = plt.subplots(figsize=(8, 3.8))
    ax.plot(pd.to_datetime(list(daily_n.index)), daily_n.values, lw=0.9, color="#2a6f97")
    ax.axhspan(27, 33, color="#e8c547", alpha=0.35, label="Q3 约束 27–33")
    ax.set_ylabel("当日有销售 SKU 数")
    ax.set_title("2023 年以来日上架宽度大多在 35–45，27–33 是收紧")
    ax.legend()
    fig.tight_layout()
    fig.savefig(FIG / "日SKU数_vs_2733.png", dpi=140)
    plt.close(fig)

    with open(DATA / "摘要.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
