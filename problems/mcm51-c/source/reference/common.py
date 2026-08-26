# -*- coding: utf-8 -*-
r"""
common.py —— 共享模块（被 _entry.py 以 exec 方式先执行，命名空间共享）
=====================================================================
由 _entry.py 通过 `exec((REF_DIR/'common.py').read_text(encoding='utf-8'), globals())`
执行：本文件定义的函数/常量（中文字体、_fs、STEP_H、PARAMS、特征构造、
BinSeg、前向 CV、ols_fit/metrics 等）对其后 exec 的 q1.py~q5.py 全部可见。
DATA_DIR / OUT 由 _entry.py 先定义注入共享命名空间，本文件不重复定义。
数值逻辑逐字保留自原单文件 reference_solver.py 的公共段。
"""
import heapq
from pathlib import Path
from itertools import combinations

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib import font_manager
from scipy import stats

# =====================================================================
# matplotlib 中文字体（原 q3_common.py + common.py setup_cjk_font 内联）
# =====================================================================
def setup_cjk_font():
    for fp in [r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\simhei.ttc",
               r"C:\Windows\Fonts\Deng.ttf", r"C:\Windows\Fonts\simsun.ttc"]:
        if Path(fp).exists():
            try:
                font_manager.fontManager.addfont(fp)
            except Exception:
                pass
    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DengXian",
                                       "Noto Sans SC", "SimSun", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False

setup_cjk_font()

def _fs(x, spec='.4f'):
    """数值格式化：非有限值以「缺失」替代（stdout 禁出 nan/inf）。"""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return '缺失'
    if not np.isfinite(v):
        return '缺失'
    return format(v, spec)

# =====================================================================
# Q4/Q5 共享工具（原 common.py；STEP_H 全局共用）
# =====================================================================
STEP_H = 1.0 / 6.0  # 10min 采样 = 1/6 h（速度统一 mm/h 的量纲换算基准）

PARAMS = {
    # ---- 降雨滞后累计特征（API / 前期雨量）----
    "api_decay": 0.95,        # 每 10min 指数衰减系数；半衰期 = ln0.5/ln0.95 ≈ 13.5 步 ≈ 2.25 h
    "api_max_steps": 288,     # API 回溯上限 48 h
    "rain24_steps": 144,      # 附加 24 h 累计雨量特征（144 步）
    # ---- 爆破编码 ----
    "blast_encoding": "binary_value",   # 主口径：是否爆破二值 + 事件数值特征（非爆破填 0）
    "blast_alt_encoding": "ffill",      # 备选口径：前向填充
    "blast_lag_steps": 0,               # 爆破当期效应（不滞后）
    # ---- 阶段划分（BinSeg + 三重判据）----
    "biseg_min_seg": 300,     # 最小段长（行）
    "biseg_pen": 1.0,         # 每新增一段的 SSE 惩罚
    "biseg_persist_w": 144,   # 持续性判据窗口 = 1 天（144 行）
    "biseg_mag_min": 0.04,    # 幅度判据：两段斜率差下限（mm/10min/步 = 0.24 mm/h）
    "biseg_alpha": 0.05,      # Chow 型 F 检验显著性水平
    "n_stages": 3,            # 三段式：缓慢匀速 → 加速 → 快速
    "final_min_seg": 400,     # 最终各段最小行数
    # ---- 前向 CV（全题禁止随机切分）----
    "cv_val_frac": 0.20,      # Q4 每阶段末 20% 作验证（前向）
    "cv_min_val": 150,        # 验证窗口最少行数
    "q5_cv_origins": [0.40, 0.55, 0.70, 0.85],  # Q5.1 滚动起点（时间序）
    "q5_cv_horizon": 700,     # Q5.1 每个验证窗口长度（行 ≈ 4.9 天）
    # ---- Q5.2 预警阈值（数据驱动分位数）----
    "warn_levels": [0.90, 0.95, 0.99],   # 注意 / 预警 / 报警 分位数
    "warn_persist_steps": 3,  # 持续性报警：连续超阈 w=3 步（30 min）
    "warn_horizon_h": 24.0,   # 报警有效性窗口（h）
    "warn_lookback_h": 24.0,  # 事件回溯窗口（h）
    "spike_abs_mm10": 3.0,    # 数据跳变识别：|d|>3.0 mm/10min（18 mm/h）为跳变噪声
    "cost_miss": 10.0,        # 漏报成本（生命损失 >> 误报疏散成本）
    "cost_fp": 1.0,           # 误报成本
    "danger_q_fast": 0.90,    # “危险事件”定义：快速段 v6（1h 均速）分位数
}

def make_features(df, params, blast_encoding="binary_value", blast_lag=0,
                  keep_cols=None):
    """
    构造增量回归特征（不含截距），返回 (X, 特征名列表)。
    特征：api / rain24 / pore / micro / is_blast / blast_dist / blast_charge
    """
    rain = df["降雨量_mm"].values.astype(float)
    n = len(rain)
    dec = params["api_decay"]
    M = params["api_max_steps"]
    w_api = dec ** np.arange(M)
    api = np.convolve(rain, w_api)[:n]
    w24 = np.ones(params["rain24_steps"])
    rain24 = np.convolve(rain, w24)[:n]

    pore = df["孔隙水压力_kPa"].values.astype(float)
    micro = df["微震事件数"].values.astype(float)

    is_blast = df["爆破点距离_m"].notna().values.astype(float)
    dist = df["爆破点距离_m"].values.astype(float)
    charge = df["单段最大药量_kg"].values.astype(float)
    dist = np.nan_to_num(dist)
    charge = np.nan_to_num(charge)
    if blast_encoding == "ffill":               # 备选口径：前向填充
        dist = pd.Series(df["爆破点距离_m"].values).ffill().fillna(0.0).values
        charge = pd.Series(df["单段最大药量_kg"].values).ffill().fillna(0.0).values
        is_blast = pd.Series(is_blast).ffill().fillna(0.0).values
    if blast_lag > 0:
        is_blast = np.roll(is_blast, blast_lag)
        dist = np.roll(dist, blast_lag)
        charge = np.roll(charge, blast_lag)
        is_blast[:blast_lag] = 0.0
        dist[:blast_lag] = 0.0
        charge[:blast_lag] = 0.0

    cols = {
        "api": api, "rain24": rain24, "pore": pore, "micro": micro,
        "is_blast": is_blast, "blast_dist": dist, "blast_charge": charge,
    }
    if keep_cols is not None:
        cols = {k: cols[k] for k in keep_cols}
    X = np.column_stack([cols[k] for k in cols])
    return X, list(cols.keys())

def ols_fit(X, y):
    """带截距 OLS。返回 (coef[含截距], sigma, se, resid)。"""
    A = np.column_stack([np.ones(len(y)), X])
    coef, *_ = np.linalg.lstsq(A, y, rcond=None)
    resid = y - A @ coef
    dof = len(y) - A.shape[1]
    sigma = float(np.sqrt(np.maximum(resid @ resid, 0.0) / max(dof, 1)))
    try:
        cov = np.linalg.pinv(A.T @ A) * sigma ** 2
        se = np.sqrt(np.maximum(np.diag(cov), 0.0))
    except np.linalg.LinAlgError:
        se = np.full_like(coef, np.nan)
    return coef, sigma, se, resid

def metrics(y_true, y_pred):
    """RMSE / MAE / R²（相对常数均值）。"""
    e = np.asarray(y_true) - np.asarray(y_pred)
    rmse = float(np.sqrt(np.mean(e ** 2)))
    mae = float(np.mean(np.abs(e)))
    ss_tot = float(np.sum((np.asarray(y_true) - np.mean(y_true)) ** 2))
    r2 = 1.0 - float(np.sum(e ** 2)) / ss_tot if ss_tot > 0 else np.nan
    return rmse, mae, r2

def _linfit_ss(x, y):
    """区间 [i0,i1) 内线性拟合的 SSE。"""
    n = len(y)
    if n < 2:
        return 0.0
    xm = x - x.mean()
    A = np.vstack([np.ones(n), xm]).T
    c, *_ = np.linalg.lstsq(A, y, rcond=None)
    r = y - A @ c
    return float(r @ r)

def _seg_slope(x, y, i0, i1):
    """区间 [i0,i1) 线性拟合斜率（mm/步）。"""
    if i1 - i0 < 2:
        return 0.0
    A = np.vstack([np.ones(i1 - i0), x[i0:i1] - x[i0:i1].mean()]).T
    c, *_ = np.linalg.lstsq(A, y[i0:i1], rcond=None)
    return float(c[1])

def biseg_candidates(y, min_seg=300, pen=1.0, max_cps=8):
    """二叉分割（BinSeg）候选断点，返回 [(break_idx, cost_reduction), ...] 升序。"""
    n = len(y)
    x = np.arange(n, dtype=float)

    def cost(l, r):
        return _linfit_ss(x[l:r], y[l:r])

    heap = []

    def push(l, r):
        if r - l < 2 * min_seg:
            return
        base = cost(l, r)
        best = None
        for k in range(l + min_seg, r - min_seg + 1):
            red = base - cost(l, k) - cost(k, r)
            if best is None or red > best[0]:
                best = (red, k)
        if best is not None and best[0] > pen:
            heapq.heappush(heap, (-best[0], l, r, best[1]))

    push(0, n)
    cps = []
    while heap and len(cps) < max_cps:
        neg_red, l, r, k = heapq.heappop(heap)
        cps.append((int(k), -neg_red))
        push(l, k)
        push(k, r)
    cps.sort()
    return cps

def _chow_f(y, x, k, min_seg):
    """Chow 型结构断点 F 检验（两段线性 vs 一段线性）。"""
    n = len(y)
    A1 = np.vstack([np.ones(k), x[:k] - x[:k].mean()]).T
    A2 = np.vstack([np.ones(n - k), x[k:] - x[k:].mean()]).T
    A0 = np.vstack([np.ones(n), x - x.mean()]).T
    c1, *_ = np.linalg.lstsq(A1, y[:k], rcond=None)
    c2, *_ = np.linalg.lstsq(A2, y[k:], rcond=None)
    c0, *_ = np.linalg.lstsq(A0, y, rcond=None)
    rss1 = float(np.sum((y[:k] - A1 @ c1) ** 2))
    rss2 = float(np.sum((y[k:] - A2 @ c2) ** 2))
    rss0 = float(np.sum((y - A0 @ c0) ** 2))
    p = 2
    df2 = n - 2 * p
    if df2 <= 0 or rss1 + rss2 <= 0:
        return np.nan, np.nan
    F = ((rss0 - rss1 - rss2) / p) / ((rss1 + rss2) / df2)
    pv = 1.0 - stats.f.cdf(F, p, df2)
    return float(F), float(pv)

def detect_stages(y, params):
    """
    自识别三段式阶段边界（BinSeg + 持续性/幅度/模型差异三重判据）。
    返回 (bounds, info)：bounds: [(a0,b0),(a1,b1),(a2,b2)] 行号区间（0-based, b 排他）
    """
    n = len(y)
    x = np.arange(n, dtype=float)
    cps = biseg_candidates(y, params["biseg_min_seg"], params["biseg_pen"])
    mag_min = params["biseg_mag_min"]
    w = params["biseg_persist_w"]
    alpha = params["biseg_alpha"]
    accepted = []
    info = []
    for k, red in cps:
        sl = _seg_slope(x, y, max(0, k - w), k)
        sr = _seg_slope(x, y, k, min(n, k + w))
        mag = abs(sr - sl)
        F, pv = _chow_f(y, x, k, params["biseg_min_seg"])
        wl = np.mean(np.diff(y[max(0, k - w):k])) if k - max(0, k - w) >= 2 else 0.0
        wr = np.mean(np.diff(y[k:min(n, k + w)])) if min(n, k + w) - k >= 2 else 0.0
        persist = (wr - wl) * (sr - sl) > 0 and abs(wr - wl) >= 0.5 * mag_min
        ok = mag >= mag_min and (pv is not None and not np.isnan(pv) and pv < alpha) and persist
        accepted.append((k, mag, F, pv, persist, ok, red))
        info.append(dict(break_idx=k, mag=mag, F=F, p_value=pv, persist=persist,
                         ok=ok, cost_reduction=red,
                         slope_left=sl, slope_right=sr))
    ok_cps = sorted(set([k for k, mag, F, pv, persist, ok, red in accepted if ok]))
    x = np.arange(n, dtype=float)

    def combo_ss(picks):
        bounds = [0] + sorted(picks) + [n]
        if any(b - a < params["final_min_seg"] for a, b in zip(bounds[:-1], bounds[1:])):
            return np.inf
        vs = [stage_mean_velocity(y, a, b) for a, b in zip(bounds[:-1], bounds[1:])]
        if not all(vs[i] < vs[i + 1] for i in range(len(vs) - 1)):
            return np.inf
        return sum(_linfit_ss(x[a:b], y[a:b]) for a, b in zip(bounds[:-1], bounds[1:]))

    best_picks, best_ss = None, np.inf
    if len(ok_cps) >= params["n_stages"] - 1:
        for picks in combinations(ok_cps, params["n_stages"] - 1):
            ss = combo_ss(picks)
            if ss < best_ss:
                best_ss, best_picks = ss, picks
    chosen = sorted(best_picks) if best_picks is not None else []
    if len(chosen) < params["n_stages"] - 1:
        fallback = sorted(set([c[0] for c in cps]))
        best_picks, best_ss = None, np.inf
        for picks in combinations(fallback, params["n_stages"] - 1):
            ss = combo_ss(picks)
            if ss < best_ss:
                best_ss, best_picks = ss, picks
        chosen = sorted(best_picks) if best_picks is not None else []
    bounds = [(a, b) for a, b in zip([0] + chosen, chosen + [n])]
    return bounds, info

def stage_mean_velocity(y, a, b):
    """阶段平均速度（mm/h）：(y[b-1]-y[a]) / ((b-1-a)*STEP_H)（净变化口径）。"""
    dt_h = (b - 1 - a) * STEP_H
    return (y[b - 1] - y[a]) / dt_h if dt_h > 0 else np.nan

def stage_folds(bounds, cv_val_frac=0.20, cv_min_val=150):
    """每阶段末段作验证（前向）：返回 [(train_slice, val_slice)]，行号切片。"""
    folds = []
    for a, b in bounds:
        L = int(round((b - a) * cv_val_frac))
        L = min(max(L, cv_min_val), b - a - 30)
        folds.append(((a, b - L), (b - L, b)))
    return folds

def std_coefs(coef, X, y, names):
    """标准化回归系数：beta = coef_i * std(X_i) / std(y)。"""
    sx = np.std(X, axis=0)
    sy = np.std(y)
    return {names[i]: float(coef[i + 1] * sx[i] / sy) for i in range(len(names))}
