"""一次性脚本：为 mcm51-c 生成 D-007 每附件概览图（eda/附件1.png … 附件5.png）。"""
from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "source"
OUT = Path(__file__).resolve().parent

SOURCES = {
    1: SOURCE / "附件1：两组位移时序数据-问题1.xlsx",
    2: SOURCE / "附件2：位移时序数据-问题2.xlsx",
    3: SOURCE / "附件3：监测数据（训练集与实验集）-问题3.xlsx",
    4: SOURCE / "附件4：监测数据（训练集与实验集）-问题4.xlsx",
    5: SOURCE / "附件5：监测数据-问题5.xlsx",
}

# 附件1 同步跳变下跳点索引（data_profile §1.5）
SYNC_JUMP_IDX = [1325, 4672, 8205, 8790]
# 附件2 三段粗分界（data_profile §2.6）
PHASE_BOUNDS = [7900, 9500]


def _setup_cn_font() -> None:
    for name in ("Microsoft YaHei", "SimHei", "DejaVu Sans"):
        try:
            plt.rcParams["font.sans-serif"] = [name]
            plt.rcParams["axes.unicode_minus"] = False
            return
        except Exception:
            continue


def _save(fig: plt.Figure, n: int) -> Path:
    out = OUT / f"附件{n}.png"
    fig.savefig(out, dpi=120, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return out


def make_attachment1() -> Path:
    df = pd.read_excel(SOURCES[1], sheet_name="Sheet1")
    a = df["数据A_光纤位移计数据_mm"]
    b = df["数据B_振弦式位移计数据_mm"]
    d = a - b
    # 全图统一用行索引，避免 sharex 混用 datetime/整数导致轴错位
    x = np.arange(len(df))

    fig, axes = plt.subplots(3, 1, figsize=(12, 8), sharex=True, gridspec_kw={"height_ratios": [2, 2, 1.2]})

    axes[0].plot(x, a, lw=0.6, color="#1f77b4", label="A 光纤")
    axes[0].plot(x, b, lw=0.6, color="#ff7f0e", label="B 振弦")
    axes[0].set_ylabel("位移 (mm)")
    axes[0].legend(loc="upper left", fontsize=8)
    axes[0].set_title("附件1：A/B 时序与 A−B 漂移（x=行索引）")

    for idx in SYNC_JUMP_IDX:
        axes[0].axvline(idx, color="crimson", ls="--", lw=0.7, alpha=0.7)
        axes[0].annotate(
            f"idx={idx}",
            xy=(idx, a.iloc[idx]),
            fontsize=6,
            color="crimson",
            rotation=90,
            va="bottom",
        )

    axes[1].plot(x, d, lw=0.6, color="#2ca02c")
    axes[1].set_ylabel("A−B (mm)")
    coef = np.polyfit(x, d, 1)
    # 每步 10min → mm/h = coef[0]*6（与 data_profile ≈0.0268 mm/h 对齐）
    axes[1].plot(
        x,
        np.polyval(coef, x),
        "--",
        color="gray",
        lw=1,
        label=f"线性趋势 ≈{coef[0]*6:.4f} mm/h",
    )
    axes[1].legend(loc="upper left", fontsize=8)

    diff_a = a.diff().abs()
    axes[2].semilogy(x[1:], diff_a.iloc[1:], lw=0.4, color="#9467bd")
    axes[2].axhline(20, color="gray", ls=":", lw=0.8, label="|ΔA|>20 阈值")
    axes[2].set_ylabel("|ΔA| (mm)")
    axes[2].set_xlabel("索引")
    axes[2].legend(loc="upper right", fontsize=7)

    fig.tight_layout()
    return _save(fig, 1)


def make_attachment2() -> Path:
    df = pd.read_excel(SOURCES[2], sheet_name="Sheet1")
    idx = df["编号"].values
    disp = df["表面位移_mm"].values

    fig, axes = plt.subplots(2, 1, figsize=(12, 7), sharex=True, gridspec_kw={"height_ratios": [2.2, 1]})

    axes[0].plot(idx, disp, lw=0.5, color="#1f77b4")
    axes[0].set_ylabel("表面位移 (mm)")
    axes[0].set_title("附件2：位移 vs 编号（三段式）")

    ymax = disp.max()
    for bound, label, color in [
        (PHASE_BOUNDS[0], "缓慢→加速 ~7900", "#ff7f0e"),
        (PHASE_BOUNDS[1], "加速→快速 ~9500", "#d62728"),
    ]:
        axes[0].axvline(bound, color=color, ls="--", lw=0.9, alpha=0.8)
        axes[0].text(bound + 30, ymax * 0.92, label, fontsize=7, color=color)

    axes[0].axvspan(1, PHASE_BOUNDS[0], alpha=0.06, color="green", label="缓慢")
    axes[0].axvspan(PHASE_BOUNDS[0], PHASE_BOUNDS[1], alpha=0.06, color="orange", label="加速")
    axes[0].axvspan(PHASE_BOUNDS[1], len(idx), alpha=0.06, color="red", label="快速")
    axes[0].legend(loc="upper left", fontsize=7, ncol=3)

    vel = np.diff(disp)
    axes[1].plot(idx[1:], vel, lw=0.3, color="#2ca02c", alpha=0.7)
    axes[1].axhline(0, color="gray", lw=0.5)
    axes[1].set_ylabel("Δ位移/10min")
    axes[1].set_xlabel("编号")

    fig.tight_layout()
    return _save(fig, 2)


def make_attachment3() -> Path:
    train = pd.read_excel(SOURCES[3], sheet_name="训练集")
    test = pd.read_excel(SOURCES[3], sheet_name="实验集")

    fig, axes = plt.subplots(2, 2, figsize=(12, 8))
    fig.suptitle("附件3：训练集关键列 + 两集缺失对照", fontsize=11)

    x = train["编号"]
    axes[0, 0].plot(x, train["d:深部位移_mm"], lw=0.4, color="#1f77b4", label="深部位移")
    axes[0, 0].plot(x, train["e:表面位移_mm"], lw=0.4, color="#ff7f0e", label="表面位移")
    axes[0, 0].set_title("训练集：深部/表面位移")
    axes[0, 0].legend(fontsize=7)
    axes[0, 0].set_ylabel("mm")

    axes[0, 1].plot(x, train["b:孔隙水压力_kPa"], lw=0.4, color="#2ca02c")
    axes[0, 1].set_title("训练集：孔隙水压力")
    axes[0, 1].set_ylabel("kPa")

    axes[1, 0].bar(
        ["a降雨", "b孔压", "c微震", "d深部", "e表面"],
        [train[c].isna().mean() * 100 for c in train.columns if c != "编号"],
        color="#1f77b4",
        alpha=0.8,
    )
    axes[1, 0].set_title("训练集缺失率 (%)")
    axes[1, 0].set_ylim(0, 105)

    test_cols = [c for c in test.columns if c != "编号"]
    miss = [test[c].isna().mean() * 100 for c in test_cols]
    colors = ["#d62728" if m >= 99 else "#ff7f0e" for m in miss]
    axes[1, 1].bar(test_cols, miss, color=colors, alpha=0.8)
    axes[1, 1].set_title("实验集缺失率 (%) — 表面位移 100% 空")
    axes[1, 1].tick_params(axis="x", rotation=30, labelsize=7)
    axes[1, 1].set_ylim(0, 105)

    fig.tight_layout()
    return _save(fig, 3)


def make_attachment4() -> Path:
    train = pd.read_excel(SOURCES[4], sheet_name="训练集")
    test = pd.read_excel(SOURCES[4], sheet_name="实验集")

    t_tr = pd.to_datetime(train["时间"], format="%Y-%m-%d %H:%M")
    t_te = pd.to_datetime(test["时间"], format="%Y-%m-%d %H:%M")

    fig, axes = plt.subplots(2, 1, figsize=(12, 8))

    axes[0].plot(t_tr, train["表面位移_mm"], lw=0.5, color="#1f77b4", label="表面位移")
    blast = train["爆破点距离_m"].notna()
    axes[0].scatter(
        t_tr[blast],
        train.loc[blast, "表面位移_mm"],
        s=18,
        color="red",
        zorder=5,
        label=f"爆破时刻 ({blast.sum()} 点)",
    )
    axes[0].set_title("附件4 训练集：位移时序 + 爆破稀疏点")
    axes[0].set_ylabel("位移 (mm)")
    axes[0].legend(fontsize=8)

    axes[1].plot(t_te, test["孔隙水压力_kPa"], lw=0.4, color="#2ca02c", label="孔压（实验集有值）")
    surf_miss = test["表面位移_mm"].isna().mean() * 100
    axes[1].fill_between(t_te, 0, 1, transform=axes[1].get_xaxis_transform(), alpha=0.08, color="red")
    axes[1].text(
        t_te.iloc[len(t_te) // 2],
        test["孔隙水压力_kPa"].median(),
        f"表面位移 100% 缺失（{surf_miss:.0f}% 空）",
        ha="center",
        fontsize=9,
        color="crimson",
        bbox=dict(boxstyle="round", facecolor="white", alpha=0.8),
    )
    blast_te = test["爆破点距离_m"].notna()
    axes[1].scatter(t_te[blast_te], test.loc[blast_te, "孔隙水压力_kPa"], s=18, color="red", zorder=5, label="爆破")
    axes[1].set_title("附件4 实验集：表面位移全空（示意孔压/爆破）")
    axes[1].set_ylabel("kPa")
    axes[1].legend(fontsize=8)

    fig.tight_layout()
    return _save(fig, 4)


def make_attachment5() -> Path:
    df = pd.read_excel(SOURCES[5], sheet_name="Sheet1")
    t = pd.to_datetime(df["时间"], format="%Y-%m-%d %H:%M")

    fig, axes = plt.subplots(2, 1, figsize=(12, 7), sharex=True, gridspec_kw={"height_ratios": [2.2, 1]})

    axes[0].plot(t, df["表面位移_mm"], lw=0.5, color="#1f77b4", label="表面位移")
    blast = df["爆破点距离_m"].notna()
    axes[0].scatter(
        t[blast],
        df.loc[blast, "表面位移_mm"],
        s=22,
        color="red",
        zorder=5,
        label=f"爆破时刻 ({blast.sum()} 点)",
    )
    axes[0].set_ylabel("位移 (mm)")
    axes[0].set_title("附件5：位移时序 + 爆破稀疏点")
    axes[0].legend(fontsize=8)

    axes[1].plot(t, df["微震事件数"], lw=0.4, color="#9467bd", alpha=0.8, label="微震")
    axes[1].scatter(t[blast], df.loc[blast, "微震事件数"], s=18, color="red", zorder=5, label="爆破行")
    axes[1].set_ylabel("微震事件数")
    axes[1].set_xlabel("时间")
    axes[1].legend(fontsize=8)

    fig.tight_layout()
    return _save(fig, 5)


def main() -> None:
    _setup_cn_font()
    makers = [make_attachment1, make_attachment2, make_attachment3, make_attachment4, make_attachment5]
    for i, fn in enumerate(makers, start=1):
        path = fn()
        size = path.stat().st_size
        print(f"Wrote {path.name} ({size:,} bytes)")


if __name__ == "__main__":
    main()
