"""一次性脚本：为 cumcm23-c 生成每附件概览图（eda/附件1.png … 附件4.png）。

附件2（~39MB / 约数十万行）只用 openpyxl read_only 流式扫描一次，
按日/品类聚合后再作图，禁止整表载入内存再复制多份，禁止百万散点。
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib import font_manager
from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "source"
OUT = Path(__file__).resolve().parent

SOURCES = {
    1: SOURCE / "附件1.xlsx",
    2: SOURCE / "附件2.xlsx",
    3: SOURCE / "附件3.xlsx",
    4: SOURCE / "附件4.xlsx",
}

STATS: dict = {}


def _setup_cn_font() -> str:
    candidates = ("Microsoft YaHei", "SimHei", "Microsoft YaHei UI")
    available = {f.name for f in font_manager.fontManager.ttflist}
    chosen = next((n for n in candidates if n in available), "DejaVu Sans")
    plt.rcParams["font.sans-serif"] = [chosen, "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False
    return chosen


def _save(fig: plt.Figure, n: int) -> Path:
    out = OUT / f"附件{n}.png"
    fig.savefig(out, dpi=120, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return out


def _norm_code(x) -> str | None:
    if x is None:
        return None
    if isinstance(x, float):
        if np.isnan(x):
            return None
        if x.is_integer():
            return str(int(x))
        return str(x).strip()
    if isinstance(x, int):
        return str(x)
    s = str(x).strip()
    return s or None


def _as_date(x) -> date | None:
    if x is None:
        return None
    if isinstance(x, datetime):
        return x.date()
    if isinstance(x, date):
        return x
    try:
        return pd.Timestamp(x).date()
    except Exception:
        return None


def _missing_report(df: pd.DataFrame) -> dict:
    out = {}
    n = len(df)
    for c in df.columns:
        k = int(df[c].isna().sum())
        out[str(c)] = {"n": k, "pct": round(k / n * 100, 4) if n else None}
    return out


def load_attachment1() -> pd.DataFrame:
    df = pd.read_excel(SOURCES[1], sheet_name="Sheet1", dtype=object)
    df.columns = [str(c).strip() for c in df.columns]
    df["单品编码"] = df["单品编码"].map(_norm_code)
    df["分类编码"] = df["分类编码"].map(_norm_code)
    return df


def make_attachment1(df1: pd.DataFrame) -> Path:
    vc = df1["分类名称"].value_counts()
    fig, ax = plt.subplots(figsize=(10, 5.5))
    colors = plt.cm.Set2(np.linspace(0, 1, len(vc)))
    bars = ax.barh(list(vc.index)[::-1], list(vc.values)[::-1], color=colors[::-1])
    ax.set_xlabel("单品数")
    ax.set_title(f"附件1：各品类单品数（合计 {len(df1)} 个单品，{df1['分类名称'].nunique()} 个品类）")
    for bar, val in zip(bars, list(vc.values)[::-1]):
        ax.text(val + 0.3, bar.get_y() + bar.get_height() / 2, str(val), va="center", fontsize=9)
    ax.set_xlim(0, max(vc.values) * 1.15)
    fig.tight_layout()
    return _save(fig, 1)


def stream_attachment2(sku_to_cat: dict[str, str]) -> dict:
    """只读流式扫描附件2，返回聚合结果；不保留行级明细。"""
    p = SOURCES[2]
    wb = load_workbook(p, read_only=True, data_only=True)
    sheet_names = list(wb.sheetnames)
    ws = wb[sheet_names[0]]
    it = ws.iter_rows(values_only=True)
    header = [h if h is None else str(h).strip() for h in next(it)]
    idx = {name: i for i, name in enumerate(header)}
    required = ["销售日期", "扫码销售时间", "单品编码", "销量(千克)", "销售单价(元/千克)", "销售类型", "是否打折销售"]
    missing_cols = [c for c in required if c not in idx]
    if missing_cols:
        wb.close()
        raise KeyError(f"附件2 缺列: {missing_cols}; header={header}")

    n = 0
    empty_rows = 0
    miss = Counter()
    sale_types = Counter()
    discounts = Counter()
    skus: set[str] = set()
    unknown_sku_rows = 0
    unknown_skus: set[str] = set()
    qty_neg = 0
    qty_zero = 0
    qty_min = None
    qty_max = None
    price_min = None
    price_max = None
    qty_sum = 0.0
    amt_sum = 0.0
    date_min = None
    date_max = None
    n_dates: set[date] = set()
    first_row = None
    last_nonempty = None
    daily_qty: dict[date, float] = defaultdict(float)
    daily_cat_qty: dict[date, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    monthly_cat_qty: dict[tuple[int, int], dict[str, float]] = defaultdict(lambda: defaultdict(float))
    monthly_disc: dict[tuple[int, int], Counter] = defaultdict(Counter)
    in_att1 = 0
    # 与附件3对齐计数：先占位，主流程稍后用 att3 的 (date,sku) 集合二次扫描太贵，
    # 这里只记 (date, sku) 出现次数的近似：用销售日集合 + SKU 集合。
    pair_n = 0
    pair_set_sample_overflow = False
    # 55k 量级可承受；设上限防止意外膨胀
    sold_pairs: set[tuple[date, str]] = set()
    PAIR_CAP = 120_000

    i_date = idx["销售日期"]
    i_time = idx["扫码销售时间"]
    i_sku = idx["单品编码"]
    i_qty = idx["销量(千克)"]
    i_price = idx["销售单价(元/千克)"]
    i_type = idx["销售类型"]
    i_disc = idx["是否打折销售"]
    ncols = len(header)

    for raw in it:
        if raw is None or all(v is None for v in raw):
            empty_rows += 1
            continue
        n += 1
        if first_row is None:
            first_row = [raw[j] if j < len(raw) else None for j in range(ncols)]
        last_nonempty = [raw[j] if j < len(raw) else None for j in range(ncols)]

        d = _as_date(raw[i_date] if i_date < len(raw) else None)
        sku = _norm_code(raw[i_sku] if i_sku < len(raw) else None)
        qty = raw[i_qty] if i_qty < len(raw) else None
        price = raw[i_price] if i_price < len(raw) else None
        stype = raw[i_type] if i_type < len(raw) else None
        disc = raw[i_disc] if i_disc < len(raw) else None
        tscan = raw[i_time] if i_time < len(raw) else None

        if d is None:
            miss["销售日期"] += 1
        if tscan is None or (isinstance(tscan, str) and not tscan.strip()):
            miss["扫码销售时间"] += 1
        if sku is None:
            miss["单品编码"] += 1
        if qty is None:
            miss["销量(千克)"] += 1
        if price is None:
            miss["销售单价(元/千克)"] += 1
        if stype is None:
            miss["销售类型"] += 1
        if disc is None:
            miss["是否打折销售"] += 1

        if stype is not None:
            sale_types[str(stype).strip()] += 1
        if disc is not None:
            discounts[str(disc).strip()] += 1
        if sku is not None:
            skus.add(sku)
            if sku in sku_to_cat:
                in_att1 += 1
            else:
                unknown_sku_rows += 1
                unknown_skus.add(sku)

        qv = None
        if qty is not None:
            try:
                qv = float(qty)
            except (TypeError, ValueError):
                miss["销量(千克)_非数值"] += 1
        pv = None
        if price is not None:
            try:
                pv = float(price)
            except (TypeError, ValueError):
                miss["销售单价_非数值"] += 1

        if qv is not None:
            qty_sum += qv
            if qv < 0:
                qty_neg += 1
            elif qv == 0:
                qty_zero += 1
            qty_min = qv if qty_min is None else min(qty_min, qv)
            qty_max = qv if qty_max is None else max(qty_max, qv)
        if pv is not None:
            price_min = pv if price_min is None else min(price_min, pv)
            price_max = pv if price_max is None else max(price_max, pv)
        if qv is not None and pv is not None:
            amt_sum += qv * pv

        if d is not None:
            n_dates.add(d)
            date_min = d if date_min is None else min(date_min, d)
            date_max = d if date_max is None else max(date_max, d)
            if qv is not None:
                daily_qty[d] += qv
                cat = sku_to_cat.get(sku, "未知") if sku else "未知"
                daily_cat_qty[d][cat] += qv
                monthly_cat_qty[(d.year, d.month)][cat] += qv
            if disc is not None:
                monthly_disc[(d.year, d.month)][str(disc).strip()] += 1
            if sku is not None:
                pair_n += 1
                if len(sold_pairs) < PAIR_CAP:
                    sold_pairs.add((d, sku))
                else:
                    pair_set_sample_overflow = True

        if n % 200_000 == 0:
            print(f"  附件2 已扫描 {n:,} 行…", flush=True)

    claimed_max_row = ws.max_row
    wb.close()

    # 压缩 daily 为可 JSON / 作图的序列
    days_sorted = sorted(daily_qty)
    cat_names = sorted({c for dd in daily_cat_qty.values() for c in dd})
    months_sorted = sorted(monthly_cat_qty)

    return {
        "sheet_names": sheet_names,
        "header": header,
        "n_data_rows": n,
        "n_empty_rows": empty_rows,
        "claimed_max_row": claimed_max_row,
        "missing": dict(miss),
        "sale_types": dict(sale_types),
        "discounts": dict(discounts),
        "n_unique_sku": len(skus),
        "n_rows_sku_in_att1": in_att1,
        "n_rows_sku_unknown": unknown_sku_rows,
        "unknown_skus": sorted(unknown_skus)[:20],
        "n_unknown_sku_codes": len(unknown_skus),
        "qty_neg": qty_neg,
        "qty_zero": qty_zero,
        "qty_min": qty_min,
        "qty_max": qty_max,
        "qty_sum": qty_sum,
        "price_min": price_min,
        "price_max": price_max,
        "amt_sum": amt_sum,
        "date_min": date_min.isoformat() if date_min else None,
        "date_max": date_max.isoformat() if date_max else None,
        "n_unique_dates": len(n_dates),
        "first_row": [str(x) if x is not None else None for x in (first_row or [])],
        "last_row": [str(x) if x is not None else None for x in (last_nonempty or [])],
        "pair_n": pair_n,
        "n_unique_date_sku": len(sold_pairs),
        "pair_set_capped": pair_set_sample_overflow,
        "sold_pairs": sold_pairs,  # 供对齐检查后删除
        "days_sorted": days_sorted,
        "daily_qty": daily_qty,
        "cat_names": cat_names,
        "monthly_cat_qty": monthly_cat_qty,
        "months_sorted": months_sorted,
        "monthly_disc": monthly_disc,
        "skus": skus,
    }


def make_attachment2(agg: dict) -> Path:
    days = agg["days_sorted"]
    daily_qty = agg["daily_qty"]
    y = [daily_qty[d] for d in days]
    months = agg["months_sorted"]
    cat_names = [c for c in agg["cat_names"] if c != "未知"] + (["未知"] if "未知" in agg["cat_names"] else [])
    month_labels = [f"{y:04d}-{m:02d}" for y, m in months]
    pal = plt.cm.Set2(np.linspace(0, 1, max(len(cat_names), 1)))

    fig, axes = plt.subplots(3, 1, figsize=(12, 10), gridspec_kw={"height_ratios": [1.4, 1.8, 1.1]})
    fig.suptitle("附件2：销售流水按日/按月品类聚合（非行级散点）", fontsize=12)

    axes[0].plot(days, y, lw=0.7, color="#1f77b4")
    axes[0].set_ylabel("日销量合计 (千克)")
    axes[0].set_title(
        f"日销量合计  {agg['date_min']} → {agg['date_max']}  "
        f"({agg['n_unique_dates']} 个有销售日 / {agg['n_data_rows']:,} 行)"
    )
    axes[0].grid(True, alpha=0.25)

    bottoms = np.zeros(len(months))
    for i, cat in enumerate(cat_names):
        vals = np.array([agg["monthly_cat_qty"][k].get(cat, 0.0) for k in months], dtype=float)
        axes[1].bar(month_labels, vals, bottom=bottoms, width=0.9, label=cat, color=pal[i % len(pal)])
        bottoms += vals
    axes[1].set_ylabel("月销量合计 (千克)")
    axes[1].set_title("按月 × 品类堆叠销量")
    axes[1].legend(loc="upper left", fontsize=8, ncol=3)
    axes[1].tick_params(axis="x", rotation=60, labelsize=7)
    axes[1].grid(True, axis="y", alpha=0.25)

    # 销售类型 + 是否打折
    types = agg["sale_types"]
    discs = agg["discounts"]
    ax = axes[2]
    labels = []
    values = []
    colors = []
    for k, v in sorted(types.items(), key=lambda kv: -kv[1]):
        labels.append(f"类型:{k}")
        values.append(v)
        colors.append("#d62728" if "退" in k else "#1f77b4")
    for k, v in sorted(discs.items(), key=lambda kv: -kv[1]):
        labels.append(f"打折:{k}")
        values.append(v)
        colors.append("#ff7f0e" if k in {"是", "Y", "1"} else "#2ca02c")
    ax.bar(labels, values, color=colors)
    ax.set_ylabel("行数")
    ax.set_title(
        f"销售类型 / 是否打折（负销量行数={agg['qty_neg']:,}；"
        f"销量范围 {agg['qty_min']:.4g} ~ {agg['qty_max']:.4g} 千克）"
    )
    ax.tick_params(axis="x", labelsize=8)
    for i, v in enumerate(values):
        ax.text(i, v, f"{v:,}", ha="center", va="bottom", fontsize=7)

    fig.tight_layout()
    return _save(fig, 2)


def load_attachment3() -> pd.DataFrame:
    df = pd.read_excel(SOURCES[3], sheet_name="Sheet1", dtype=object)
    df.columns = [str(c).strip() for c in df.columns]
    df["单品编码"] = df["单品编码"].map(_norm_code)
    df["日期"] = pd.to_datetime(df["日期"], errors="coerce")
    df["批发价格(元/千克)"] = pd.to_numeric(df["批发价格(元/千克)"], errors="coerce")
    return df


def make_attachment3(df3: pd.DataFrame, sku_to_cat: dict[str, str]) -> Path:
    df = df3.copy()
    df["品类"] = df["单品编码"].map(lambda x: sku_to_cat.get(x, "未知"))
    daily = df.groupby(df["日期"].dt.date, dropna=True).agg(
        mean_price=("批发价格(元/千克)", "mean"),
        n_sku=("单品编码", "nunique"),
    )
    monthly_cat = (
        df.dropna(subset=["日期", "批发价格(元/千克)"])
        .assign(ym=lambda x: x["日期"].dt.to_period("M").astype(str))
        .groupby(["ym", "品类"], dropna=False)["批发价格(元/千克)"]
        .mean()
        .unstack(fill_value=np.nan)
    )

    fig, axes = plt.subplots(2, 1, figsize=(12, 8), gridspec_kw={"height_ratios": [1.3, 1.5]})
    fig.suptitle("附件3：批发价（按日均值 / 按月×品类）", fontsize=12)

    axes[0].plot(list(daily.index), daily["mean_price"].to_numpy(), lw=0.8, color="#1f77b4", label="日均批发价")
    ax2 = axes[0].twinx()
    ax2.plot(list(daily.index), daily["n_sku"].to_numpy(), lw=0.7, color="#ff7f0e", alpha=0.7, label="当日有报价单品数")
    axes[0].set_ylabel("元/千克")
    ax2.set_ylabel("单品数")
    axes[0].set_title(
        f"日均批发价  {daily.index.min()} → {daily.index.max()}  （{len(df):,} 行）"
    )
    h1, l1 = axes[0].get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    axes[0].legend(h1 + h2, l1 + l2, loc="upper left", fontsize=8)
    axes[0].grid(True, alpha=0.25)

    pal = plt.cm.Set2(np.linspace(0, 1, max(monthly_cat.shape[1], 1)))
    for i, col in enumerate(monthly_cat.columns):
        axes[1].plot(monthly_cat.index.to_numpy(), monthly_cat[col].to_numpy(), lw=1.2, label=str(col), color=pal[i])
    axes[1].set_ylabel("月均批发价 (元/千克)")
    axes[1].set_title("各品类月均批发价")
    axes[1].legend(loc="upper left", fontsize=8, ncol=3)
    axes[1].tick_params(axis="x", rotation=60, labelsize=7)
    axes[1].grid(True, alpha=0.25)

    fig.tight_layout()
    return _save(fig, 3)


def load_attachment4() -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    xl = pd.ExcelFile(SOURCES[4])
    sheets = list(xl.sheet_names)
    # 按实际 sheet 名读取，不假设顺序
    cat_sheet = next(s for s in sheets if "损耗率" in s and "分类" in s)
    sku_sheet = "Sheet1" if "Sheet1" in sheets else [s for s in sheets if s != cat_sheet][0]
    df_cat = pd.read_excel(xl, sheet_name=cat_sheet, dtype=object)
    df_sku = pd.read_excel(xl, sheet_name=sku_sheet, dtype=object)
    df_cat.columns = [str(c).strip() for c in df_cat.columns]
    df_sku.columns = [str(c).strip() for c in df_sku.columns]
    if "单品编码" in df_sku.columns:
        df_sku["单品编码"] = df_sku["单品编码"].map(_norm_code)
    if "小分类编码" in df_cat.columns:
        df_cat["小分类编码"] = df_cat["小分类编码"].map(_norm_code)
    rate_cat_col = [c for c in df_cat.columns if "损耗率" in c][0]
    df_cat[rate_cat_col] = pd.to_numeric(df_cat[rate_cat_col], errors="coerce")
    df_sku["损耗率(%)"] = pd.to_numeric(df_sku["损耗率(%)"], errors="coerce")
    return df_cat, df_sku, sheets


def make_attachment4(df_cat: pd.DataFrame, df_sku: pd.DataFrame) -> Path:
    rate_cat_col = [c for c in df_cat.columns if "损耗率" in c][0]
    name_col = "小分类名称" if "小分类名称" in df_cat.columns else df_cat.columns[1]
    cat = df_cat.sort_values(rate_cat_col, ascending=True)

    fig, axes = plt.subplots(1, 2, figsize=(12, 5.5))
    fig.suptitle("附件4：损耗率（品类口径 vs 单品口径）", fontsize=12)

    axes[0].barh(cat[name_col].astype(str), cat[rate_cat_col], color="#1f77b4")
    axes[0].set_xlabel("平均损耗率 (%)")
    axes[0].set_title(f"6 个品类平均损耗率（sheet: 分类口径）")
    for y, v in enumerate(cat[rate_cat_col]):
        axes[0].text(v + 0.15, y, f"{v:.2f}%", va="center", fontsize=8)
    axes[0].set_xlim(0, float(cat[rate_cat_col].max()) * 1.25)

    rates = df_sku["损耗率(%)"].dropna().to_numpy(dtype=float)
    axes[1].hist(rates, bins=20, color="#ff7f0e", edgecolor="white")
    axes[1].axvline(np.median(rates), color="crimson", ls="--", lw=1, label=f"中位数 {np.median(rates):.2f}%")
    axes[1].set_xlabel("单品损耗率 (%)")
    axes[1].set_ylabel("单品数")
    axes[1].set_title(f"单品损耗率分布（n={len(rates)}）")
    axes[1].legend(fontsize=8)

    # 标注极值单品
    imin = df_sku["损耗率(%)"].idxmin()
    imax = df_sku["损耗率(%)"].idxmax()
    lo = df_sku.loc[imin]
    hi = df_sku.loc[imax]
    axes[1].annotate(
        f"最低 {lo['单品名称']} {lo['损耗率(%)']:.2f}%",
        xy=(lo["损耗率(%)"], 1),
        fontsize=7,
        color="#2ca02c",
    )
    axes[1].annotate(
        f"最高 {hi['单品名称']} {hi['损耗率(%)']:.2f}%",
        xy=(hi["损耗率(%)"], 1),
        fontsize=7,
        color="#d62728",
        xytext=(max(rates) * 0.45, max(np.histogram(rates, bins=20)[0]) * 0.7),
        arrowprops=dict(arrowstyle="->", color="#d62728", lw=0.8),
    )

    fig.tight_layout()
    return _save(fig, 4)


def _json_ready(obj):
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, Path):
        return str(obj)
    raise TypeError(type(obj))


def main() -> None:
    font = _setup_cn_font()
    print(f"中文字体: {font}", flush=True)

    df1 = load_attachment1()
    cat_counts = df1["分类名称"].value_counts().to_dict()
    sku_to_cat = dict(zip(df1["单品编码"], df1["分类名称"]))
    STATS["att1"] = {
        "path": str(SOURCES[1]),
        "sheets": ["Sheet1"],
        "columns": list(df1.columns),
        "n_rows": int(len(df1)),
        "n_cols": int(df1.shape[1]),
        "missing": _missing_report(df1),
        "n_unique_sku": int(df1["单品编码"].nunique()),
        "n_dup_sku": int(len(df1) - df1["单品编码"].nunique()),
        "n_unique_name": int(df1["单品名称"].nunique()),
        "n_unique_cat": int(df1["分类名称"].nunique()),
        "cat_counts": cat_counts,
        "cat_codes": (
            df1.groupby(["分类编码", "分类名称"], dropna=False)
            .size()
            .reset_index(name="n")
            .to_dict(orient="records")
        ),
        "head3": df1.head(3).astype(str).to_dict(orient="records"),
        "tail3": df1.tail(3).astype(str).to_dict(orient="records"),
    }
    p1 = make_attachment1(df1)
    print(f"Wrote {p1.name} ({p1.stat().st_size:,} bytes)", flush=True)

    print("流式扫描附件2…", flush=True)
    agg = stream_attachment2(sku_to_cat)
    sold_pairs = agg.pop("sold_pairs")
    daily_qty = agg.pop("daily_qty")
    monthly_cat_qty = agg.pop("monthly_cat_qty")
    monthly_disc = agg.pop("monthly_disc")
    days_sorted = agg.pop("days_sorted")
    months_sorted = agg.pop("months_sorted")
    cat_names = agg.pop("cat_names")
    skus2 = agg.pop("skus")
    plot_agg = {
        "days_sorted": days_sorted,
        "daily_qty": daily_qty,
        "months_sorted": months_sorted,
        "monthly_cat_qty": monthly_cat_qty,
        "cat_names": cat_names,
        "sale_types": agg["sale_types"],
        "discounts": agg["discounts"],
        "qty_neg": agg["qty_neg"],
        "qty_min": agg["qty_min"],
        "qty_max": agg["qty_max"],
        "date_min": agg["date_min"],
        "date_max": agg["date_max"],
        "n_unique_dates": agg["n_unique_dates"],
        "n_data_rows": agg["n_data_rows"],
    }
    p2 = make_attachment2(plot_agg)
    print(f"Wrote {p2.name} ({p2.stat().st_size:,} bytes)", flush=True)

    att1_skus = set(df1["单品编码"].dropna())
    STATS["att2"] = {
        **{k: v for k, v in agg.items()},
        "n_sku_in_att1_catalog": len(skus2 & att1_skus),
        "n_sku_sold_not_in_att1": len(skus2 - att1_skus),
        "n_sku_in_att1_never_sold": len(att1_skus - skus2),
        "never_sold_skus": sorted(att1_skus - skus2)[:30],
        "monthly_disc": {f"{y:04d}-{m:02d}": dict(c) for (y, m), c in sorted(monthly_disc.items())},
        "monthly_qty_by_cat": {
            f"{y:04d}-{m:02d}": {k: round(v, 4) for k, v in sorted(d.items())}
            for (y, m), d in sorted(monthly_cat_qty.items())
        },
    }

    df3 = load_attachment3()
    pair3 = set(
        zip(df3["日期"].dt.date, df3["单品编码"])
    )
    pair3.discard((pd.NaT, None))
    # 去掉无效
    pair3 = {(d, s) for d, s in pair3 if d is not pd.NaT and pd.notna(d) and s}
    n_sold_in_wh = sum(1 for p in sold_pairs if p in pair3)
    n_sold_not_wh = len(sold_pairs) - n_sold_in_wh
    dup3 = int(df3.duplicated(["日期", "单品编码"]).sum())
    STATS["att3"] = {
        "path": str(SOURCES[3]),
        "sheets": ["Sheet1"],
        "columns": list(df3.columns),
        "n_rows": int(len(df3)),
        "n_cols": int(df3.shape[1]),
        "missing": _missing_report(df3),
        "date_min": str(df3["日期"].min()),
        "date_max": str(df3["日期"].max()),
        "n_unique_dates": int(df3["日期"].dt.date.nunique()),
        "n_unique_sku": int(df3["单品编码"].nunique()),
        "n_dup_date_sku": dup3,
        "price_min": float(df3["批发价格(元/千克)"].min()),
        "price_max": float(df3["批发价格(元/千克)"].max()),
        "price_mean": float(df3["批发价格(元/千克)"].mean()),
        "price_median": float(df3["批发价格(元/千克)"].median()),
        "n_price_nonpositive": int((df3["批发价格(元/千克)"] <= 0).sum()),
        "head3": df3.head(3).astype(str).to_dict(orient="records"),
        "tail3": df3.tail(3).astype(str).to_dict(orient="records"),
        "n_sku_in_att1": int(df3["单品编码"].dropna().isin(att1_skus).sum()),
        "n_unique_sku_not_in_att1": int(len(set(df3["单品编码"].dropna()) - att1_skus)),
        "align_sold_date_sku_capped": agg["pair_set_capped"],
        "align_n_unique_sold_date_sku": len(sold_pairs),
        "align_n_sold_pairs_with_wholesale": n_sold_in_wh,
        "align_n_sold_pairs_without_wholesale": n_sold_not_wh,
        "n_wholesale_pairs": len(pair3),
        "n_wholesale_pairs_never_sold_in_att2_set": len(pair3 - sold_pairs),
    }
    p3 = make_attachment3(df3, sku_to_cat)
    print(f"Wrote {p3.name} ({p3.stat().st_size:,} bytes)", flush=True)

    df_cat, df_sku, sheets4 = load_attachment4()
    rate_cat_col = [c for c in df_cat.columns if "损耗率" in c][0]
    att4_skus = set(df_sku["单品编码"].dropna())
    STATS["att4"] = {
        "path": str(SOURCES[4]),
        "sheets": sheets4,
        "cat_sheet_columns": list(df_cat.columns),
        "cat_n_rows": int(len(df_cat)),
        "cat_missing": _missing_report(df_cat),
        "cat_rows": df_cat.astype(str).to_dict(orient="records"),
        "sku_sheet_columns": list(df_sku.columns),
        "sku_n_rows": int(len(df_sku)),
        "sku_missing": _missing_report(df_sku),
        "sku_rate_min": float(df_sku["损耗率(%)"].min()),
        "sku_rate_max": float(df_sku["损耗率(%)"].max()),
        "sku_rate_mean": float(df_sku["损耗率(%)"].mean()),
        "sku_rate_median": float(df_sku["损耗率(%)"].median()),
        "n_rate_zero": int((df_sku["损耗率(%)"] == 0).sum()),
        "n_rate_gt100": int((df_sku["损耗率(%)"] > 100).sum()),
        "n_rate_negative": int((df_sku["损耗率(%)"] < 0).sum()),
        "head3": df_sku.head(3).astype(str).to_dict(orient="records"),
        "tail3": df_sku.tail(3).astype(str).to_dict(orient="records"),
        "min_row": df_sku.loc[df_sku["损耗率(%)"].idxmin(), ["单品编码", "单品名称", "损耗率(%)"]].astype(str).to_dict(),
        "max_row": df_sku.loc[df_sku["损耗率(%)"].idxmax(), ["单品编码", "单品名称", "损耗率(%)"]].astype(str).to_dict(),
        "n_sku_match_att1": len(att4_skus & att1_skus),
        "n_sku_only_att4": len(att4_skus - att1_skus),
        "n_sku_only_att1": len(att1_skus - att4_skus),
        "codes_equal_att1": att4_skus == att1_skus,
    }
    p4 = make_attachment4(df_cat, df_sku)
    print(f"Wrote {p4.name} ({p4.stat().st_size:,} bytes)", flush=True)

    STATS["png"] = {
        1: str(p1.relative_to(ROOT)).replace("\\", "/"),
        2: str(p2.relative_to(ROOT)).replace("\\", "/"),
        3: str(p3.relative_to(ROOT)).replace("\\", "/"),
        4: str(p4.relative_to(ROOT)).replace("\\", "/"),
    }
    STATS["font"] = font

    stats_path = OUT / "_profile_stats.json"
    stats_path.write_text(json.dumps(STATS, ensure_ascii=False, indent=2, default=_json_ready), encoding="utf-8")
    print(f"Wrote {stats_path.name}", flush=True)
    print("=== PROFILE KEYS ===", flush=True)
    print(
        json.dumps(
            {
                "att1_n": STATS["att1"]["n_rows"],
                "att1_cats": STATS["att1"]["cat_counts"],
                "att2_n": STATS["att2"]["n_data_rows"],
                "att2_dates": [STATS["att2"]["date_min"], STATS["att2"]["date_max"]],
                "att2_types": STATS["att2"]["sale_types"],
                "att2_sku": STATS["att2"]["n_unique_sku"],
                "att3_n": STATS["att3"]["n_rows"],
                "att3_align_with": STATS["att3"]["align_n_sold_pairs_with_wholesale"],
                "att3_align_without": STATS["att3"]["align_n_sold_pairs_without_wholesale"],
                "att4_cat": STATS["att4"]["cat_rows"],
                "att4_sku_n": STATS["att4"]["sku_n_rows"],
            },
            ensure_ascii=False,
            indent=2,
            default=_json_ready,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
