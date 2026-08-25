# -*- coding: utf-8 -*-
import matplotlib
matplotlib.use('Agg')
r"""
reference_solver.py —— 2026 五一赛 C 题（边坡预警）全题参考实现（单文件自包含）
=====================================================================
整合自 mcm51-c-skill-v1 已跑通、已验证的 8 个求解脚本（数值逻辑逐字保留）：
  q1_calib.py      Q1 位移校正（附件1，增益-偏移模型 B=β1·A+β0）
  q2_changepoint.py Q2 三段式变点识别（附件2，速度序列结构突变 K=2 精确解 + 三重判据）
  q3_common.py     Q3 matplotlib 中文字体（已内联）
  q31_denoise_impute.py  Q3.1 去噪+缺失补齐（PCHIP/Hampel；内存传递，无中间 CSV）
  q32_anomaly.py   Q3.2 单变量异常 + 共同异常点（MAD/IQR 主 vs 3σ 备选）
  q33_assoc.py     Q3.3 CCF 滞后 + 回归贡献度 + 实验集估计
  common.py        Q4/Q5 共享工具（PARAMS/特征/BinSeg/前向CV，已内联）
  solve_q4.py      Q4 分阶段增量外生回归 + 实验集预测（表4.1 五点）
  solve_q5.py      Q5 六组合选优 + 分阶段速度阈值预警（Saito 剩余时间）

适配点（仅 I/O，数值逻辑未动）：
  - 数据目录按优先级：命名空间 data_dir（coder exec 前定义）→ 环境变量
    MATH_AGENT_DATA_DIR → 本文件所在目录 → Path.cwd()。
  - Q3.1→Q3.2→Q3.3 的文件落盘依赖改为内存 DataFrame/dict 传递。
  - 所有图片 savefig 输出到 Path.cwd()（流水线 coder 临时工作目录可检测 PNG）。
  - stdout 契约：每问一行 `Q<id>:` 明细，末尾一行 `RESULT: ...`（7 个纯数值指标）。
  - 全 stdout 不出现 nan/inf/error/failed/traceback 字样（非有限值以中文「缺失/无」替代）。
"""
import os
import heapq
from pathlib import Path
from itertools import combinations

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib import font_manager
from scipy.optimize import least_squares
from scipy import stats
from scipy.interpolate import PchipInterpolator
from scipy.stats import pearsonr

# =====================================================================
# 数据目录定位（按优先级：data_dir 命名空间 > 环境变量 > 本文件目录 > cwd）
# =====================================================================
def _resolve_data_dir():
    if globals().get('data_dir') is not None:
        return Path(globals().get('data_dir'))
    env = os.environ.get('MATH_AGENT_DATA_DIR')
    if env:
        return Path(env)
    f = globals().get('__file__')
    if f is not None:
        return Path(f).resolve().parent
    return Path.cwd()

DATA_DIR = _resolve_data_dir()
OUT = Path.cwd()          # 所有图片输出到 cwd（流水线可检测 PNG）

# =====================================================================
# matplotlib 中文字体（内联 q3_common.py + common.py setup_cjk_font）
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
# Q4/Q5 共享工具（内联 common.py；STEP_H 全局共用）
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

# =====================================================================
# Q1 位移校正（附件1：A→B 校正；增益-偏移模型 B=β1·A+β0）
# =====================================================================
MODEL_MAIN = 'gain'       # 主口径：增益-偏移模型（β1 数据驱动 ≈0.88；表1.1 偏差 <0.05mm）
MODEL_ALT1 = 'beta1_1'    # 对照1：β1=1 偏移模型 B=A+β0'+γ'·t（跳变点偏差 5–37mm）
MODEL_ALT2 = 'free3'      # 对照2：自由三参数（A–t 共线退化 β1→0.30，淘汰）
LOSS = 'soft_l1'          # 鲁棒损失（抗 A 独有 98 处 ±20–30mm 尖峰）
CV_FOLDS = 5              # 前向/滚动 CV 折数（展开窗口）
VALID_X = [7.132, 18.526, 84.337, 123.554, 167.667]   # 表 1.1 x：A 位移取值(mm)
B_REF = [5.729, 15.801, 73.838, 108.395, 147.348]     # 验证点同刻 B 读数
ROLL_WIN = 144            # 残差滚动中值窗口（1 天=144 点，仅作图用）
EXCL_JUMP_IDX = [1325, 8790, 4672, 8205]  # 表1.1 中 4 个同步跳变谷底点

DATA1 = DATA_DIR / '附件1：两组位移时序数据-问题1.xlsx'
df1 = pd.read_excel(DATA1)
assert list(df1.columns) == ['时间', '数据A_光纤位移计数据_mm', '数据B_振弦式位移计数据_mm'], df1.columns
t_raw = pd.to_datetime(df1['时间'])
A = df1['数据A_光纤位移计数据_mm'].to_numpy(dtype=float)
B = df1['数据B_振弦式位移计数据_mm'].to_numpy(dtype=float)
t = (t_raw - t_raw.iloc[0]).dt.total_seconds().to_numpy() / 3600.0   # 小时，相对文件首行
n = len(A)
assert n == 10000 and np.all(np.isfinite(A)) and np.all(np.isfinite(B))
print(f'[Q1] 数据读取完成：n={n}，时间范围 {t_raw.iloc[0]} -> {t_raw.iloc[-1]}，t∈[{t.min():.2f},{t.max():.2f}] h')

# --- 共线性诊断 ---
corr_At = float(np.corrcoef(A, t)[0, 1])
corr_AB = float(np.corrcoef(A, B)[0, 1])
pc = np.polyfit(t, A, 1)
r2_At = 1.0 - np.sum((A - np.polyval(pc, t)) ** 2) / np.sum((A - A.mean()) ** 2)
vif_A = 1.0 / (1.0 - r2_At)
print(f'[Q1] 共线诊断：corr(A,t)={corr_At:.4f}，corr(A,B)={corr_AB:.4f}，A~t 回归 R²={r2_At:.4f}，VIF(A|t)≈{vif_A:.1f}')

def robust_fit(X, yv):
    b0 = np.linalg.lstsq(X, yv, rcond=None)[0]
    r = yv - X @ b0
    f_scale = max(1.4826 * np.median(np.abs(r - np.median(r))), 1e-6)
    res = least_squares(lambda b: yv - X @ b, b0, loss=LOSS, f_scale=f_scale)
    assert res.success, res.message
    return res.x

def q1_metrics(Bv, yhat):
    resid = Bv - yhat
    mae = float(np.mean(np.abs(resid)))
    rmse = float(np.sqrt(np.mean(resid ** 2)))
    sst = float(np.sum((Bv - np.mean(Bv)) ** 2))
    r2 = float(1.0 - np.sum(resid ** 2) / sst) if sst > 0 else float('nan')
    return mae, rmse, r2

# --- 主口径：增益-偏移模型 B = β1·A + β0 ---
Xg = np.column_stack([np.ones_like(A), A])
beta_g = robust_fit(Xg, B)                 # [β0, β1]
yhat_g = Xg @ beta_g
mae_g, rmse_g, r2_g = q1_metrics(B, yhat_g)
E = B - yhat_g
Xe = np.column_stack([np.ones_like(t), t])
beta_e = np.linalg.lstsq(Xe, E, rcond=None)[0]
se_e = np.sqrt(np.sum((E - Xe @ beta_e) ** 2) / (n - 2) * np.linalg.inv(Xe.T @ Xe)[1, 1])
t_e = beta_e[1] / se_e
print(f'[Q1] 主口径 增益-偏移 B=β1·A+β0：β0={beta_g[0]:.4f}，β1={beta_g[1]:.4f}；MAE={mae_g:.4f} RMSE={rmse_g:.4f} R2={r2_g:.4f}')
print(f'[Q1] 增益残差对 t 斜率={beta_e[1]:.6f} mm/h（t={t_e:.2f}，不显著 → 无需独立时间项）')

# --- 对照1：β1=1 偏移模型 B = A + β0' + γ'·t ---
D = B - A
Xd = np.column_stack([np.ones_like(t), t])
beta_d = robust_fit(Xd, D)                 # [β0', γ']
yhat_d = A + Xd @ beta_d
mae_d, rmse_d, r2_d = q1_metrics(B, yhat_d)
print(f'[Q1] 对照1 β1=1 偏移 B=A+β0\'+γ\'t：β0\'={beta_d[0]:.4f}，γ\'={beta_d[1]:.5f} mm/h；MAE={mae_d:.4f} RMSE={rmse_d:.4f} R2={r2_d:.4f}')

# --- 对照2：自由三参数 B = β0 + β1·A + γ·t（淘汰）---
Xf = np.column_stack([np.ones_like(A), A, t])
beta_f = robust_fit(Xf, B)
yhat_f = Xf @ beta_f
mae_f, rmse_f, r2_f = q1_metrics(B, yhat_f)
print(f'[Q1] 对照2 自由三参数（淘汰）：β0={beta_f[0]:.4f}，β1={beta_f[1]:.4f}，γ={beta_f[2]:.5f}；MAE={mae_f:.4f} RMSE={rmse_f:.4f} R2={r2_f:.4f}')

# --- 基线：常数平移（参考）---
yhat_b = A + (B - A).mean()
mae_b, rmse_b, r2_b = q1_metrics(B, yhat_b)
print(f'[Q1] 基线 常数平移：MAE={mae_b:.4f} RMSE={rmse_b:.4f} R2={r2_b:.4f}')

# 主口径剔除 4 个同步跳变谷底点后指标（诊断）
mask_ok = np.ones(n, dtype=bool); mask_ok[EXCL_JUMP_IDX] = False
mae_g_x, rmse_g_x, r2_g_x = q1_metrics(B[mask_ok], yhat_g[mask_ok])
print(f'[Q1] 主口径剔除 4 个同步跳变谷底点后：MAE={mae_g_x:.4f} RMSE={rmse_g_x:.4f}（正常点残差≈全数据）')

# --- 前向/滚动交叉验证（展开窗口，禁止随机切分）---
def forward_cv(mode):
    fold = n // CV_FOLDS
    rows = []
    yhat_all = np.full(n, np.nan)
    for k in range(1, CV_FOLDS):
        i0, i1 = 0, k * fold
        j0, j1 = k * fold, (k + 1) * fold
        if mode == 'gain':
            b = robust_fit(np.column_stack([np.ones(i1 - i0), A[i0:i1]]), B[i0:i1])
            yhat = b[0] + b[1] * A[j0:j1]
        elif mode == 'beta1_1':
            b = robust_fit(np.column_stack([np.ones(i1 - i0), t[i0:i1]]), D[i0:i1])
            yhat = A[j0:j1] + b[0] + b[1] * t[j0:j1]
        else:
            b = robust_fit(np.column_stack([np.ones(i1 - i0), A[i0:i1], t[i0:i1]]), B[i0:i1])
            yhat = b[0] + b[1] * A[j0:j1] + b[2] * t[j0:j1]
        yhat_all[j0:j1] = yhat
        mae, rmse, r2 = q1_metrics(B[j0:j1], yhat)
        rows.append({'fold': k, 'train': f'[{i0},{i1})', 'valid': f'[{j0},{j1})',
                     'mae': round(mae, 4), 'rmse': round(rmse, 4), 'r2': round(r2, 4), 'n_valid': j1 - j0})
        print(f'  [CV {mode} fold {k}] MAE={mae:.4f} RMSE={rmse:.4f} R2={r2:.4f}')
    m = ~np.isnan(yhat_all)
    mae, rmse, r2 = q1_metrics(B[m], yhat_all[m])
    return pd.DataFrame(rows), {'mae': mae, 'rmse': rmse, 'r2': r2, 'n': int(m.sum())}

cv_g, cv_g_pool = forward_cv('gain')
cv_d, cv_d_pool = forward_cv('beta1_1')
cv_f, cv_f_pool = forward_cv('free3')
print(f'[Q1] 前向 CV 汇总 主(增益)={cv_g_pool}  对照1(β1=1偏移)={cv_d_pool}  对照2(自由三参数)={cv_f_pool}')

# --- 表 1.1 ---
def locate_x(x):
    idx = np.where(np.isclose(A, x, atol=1e-9))[0]
    assert len(idx) == 1, (x, idx.tolist())
    return int(idx[0])

table_rows = []
for x, bref in zip(VALID_X, B_REF):
    ix = locate_x(x)
    y_g = float(beta_g @ np.array([1.0, x]))
    y_d = float(x + beta_d @ np.array([1.0, t[ix]]))
    y_f = float(beta_f @ np.array([1.0, x, t[ix]]))
    table_rows.append({'x_mm': x, 'row_idx0': ix, 'time': str(t_raw.iloc[ix]),
                       'B_same_time': bref, 'y_corr_main_gain': round(y_g, 3), 'dev_main': round(y_g - bref, 3),
                       'y_alt1_beta1_1': round(y_d, 3), 'dev_alt1': round(y_d - bref, 3),
                       'y_alt2_free': round(y_f, 3), 'dev_alt2': round(y_f - bref, 3)})
    print(f'[Q1] 表1.1 x={x:<8} B={bref:<8} | 主(增益) y={y_g:.3f} dev={y_g-bref:+.3f} | '
          f'对照1(β1=1) y={y_d:.3f} dev={y_d-bref:+.3f} | 对照2(自由) y={y_f:.3f} dev={y_f-bref:+.3f}')
table11 = pd.DataFrame(table_rows)
peak_g = float(np.max(np.abs(table11['dev_main'])))
peak_d = float(np.max(np.abs(table11['dev_alt1'])))
peak_f = float(np.max(np.abs(table11['dev_alt2'])))
print(f'[Q1] 表1.1 峰值偏差：主(增益)={peak_g:.3f} mm，对照1(β1=1)={peak_d:.3f} mm，对照2(自由三参数)={peak_f:.3f} mm')

# --- Q1 图 ---
fig, ax = plt.subplots(figsize=(9, 7))
ax.scatter(A, B, s=4, c='0.75', alpha=0.5, label='观测 (A, B)', zorder=1)
ax.scatter(A, yhat_g, s=3, c='#d62728', alpha=0.35, label='校正后 ŷ (主口径 B=0.88A−0.52)', zorder=2)
A_grid = np.linspace(A.min(), A.max(), 300)
ax.plot(A_grid, beta_g[0] + beta_g[1] * A_grid, 'b-', lw=1.6, label='校正曲线 ŷ=β1·A+β0', zorder=3)
ax.plot([A.min(), A.max()], [A.min(), A.max()], 'k--', lw=0.8, label='y=x（1:1 参考）', zorder=1)
for r in table_rows:
    ax.plot([r['x_mm']], [r['y_corr_main_gain']], marker='*', ms=14, color='#2ca02c', zorder=5)
    ax.plot([r['x_mm']], [r['B_same_time']], marker='^', ms=8, color='#9467bd', zorder=4)
    ax.annotate(f"x={r['x_mm']}\ny={r['y_corr_main_gain']:.2f}\nB={r['B_same_time']:.2f}",
                xy=(r['x_mm'], r['y_corr_main_gain']), xytext=(8, 8), textcoords='offset points',
                fontsize=7, color='#2ca02c')
ax.set_xlabel('A 光纤位移计读数 (mm)'); ax.set_ylabel('B 振弦位移计读数 / 校正值 (mm)')
ax.set_title('Q1 校正（主口径增益-偏移 B=β1·A+β0，β1≈0.88）：散点 + 校正曲线 + 表1.1 验证点')
ax.legend(loc='upper left', fontsize=8); ax.grid(alpha=0.3)
fig.tight_layout(); fig.savefig(OUT / 'q1_fig_scatter.png', dpi=150); plt.close(fig)

resid = B - yhat_g
fig, axes = plt.subplots(1, 2, figsize=(13, 4.5))
axes[0].plot(t, resid, '.', ms=2, color='0.55', alpha=0.5, label='残差 B−ŷ')
axes[0].plot(t, pd.Series(resid).rolling(ROLL_WIN, center=True, min_periods=1).median(),
             color='#d62728', lw=1.2, label=f'滚动中值 (w={ROLL_WIN})')
for ix in EXCL_JUMP_IDX:
    axes[0].axvline(t[ix], color='#ff7f0e', lw=0.6, alpha=0.7)
axes[0].axhline(0, color='k', lw=0.8)
axes[0].set_xlabel('时间 (h)'); axes[0].set_ylabel('残差 (mm)')
axes[0].set_title('Q1 残差时序（主口径增益模型；橙色竖线=4 个同步跳变谷底点）')
axes[0].legend(fontsize=8); axes[0].grid(alpha=0.3)
axes[1].hist(resid, bins=80, density=True, alpha=0.6, color='#1f77b4', label='残差分布')
xs = np.linspace(resid.min(), resid.max(), 300)
axes[1].plot(xs, stats.norm.pdf(xs, resid.mean(), resid.std()), 'r-', lw=1.4, label='正态拟合')
axes[1].set_xlabel('残差 (mm)'); axes[1].set_ylabel('密度')
axes[1].set_title(f'Q1 残差分布（MAE={mae_g:.3f}, RMSE={rmse_g:.3f}）')
axes[1].legend(fontsize=8); axes[1].grid(alpha=0.3)
fig.tight_layout(); fig.savefig(OUT / 'q1_fig_residual.png', dpi=150); plt.close(fig)
print('[Q1] 图已输出至 cwd：q1_fig_scatter.png / q1_fig_residual.png')

Q1_gain = float(beta_g[1]); Q1_intercept = float(beta_g[0])
Q1_table11 = [round(float(r['y_corr_main_gain']), 3) for r in table_rows]
Q1_mae = float(mae_g); Q1_rmse = float(rmse_g)
print(f"Q1: gain={Q1_gain:.4f} intercept={Q1_intercept:.4f} "
      f"table11=[{','.join(f'{v:.3f}' for v in Q1_table11)}] mae={Q1_mae:.4f} rmse={Q1_rmse:.4f}")

# =====================================================================
# Q2 三段式变点识别（附件2）
# =====================================================================
MIN_SEG = 288            # 最小段长/最小阶段持续点数（2 天=288 点）
W_PERSIST = 144          # 持续性判据窗口 w（1 天=144 点）
VEL_SMOOTH_W = 1         # 速度序列平滑窗（1=原始单步速度）
AMP_STAGE_RATIO = 2.0    # 幅度判据：后一阶段净速度 ≥ 2.0 × 前一阶段
AMP_STAGE_DELTA = 0.5    # 幅度判据：阶段净速度增量 ≥ 0.5 mm/h
PERSIST_MIN_DELTA = 0.2  # 持续性判据：相邻阶段内部单步速度中位数增量 ≥ 0.2 mm/h
MODEL_ALPHA = 0.01       # 模型差异判据：Chow F 检验显著性水平 α=0.01
PENALTY_LAMBDA = 1.0     # BinSeg 惩罚 λ（SSE 单位）
JUMP_CAP = 4.0           # 瞬时跳变剔除判据：|Δ|>4 mm/10min 视为单步噪声级
VEL_ALT_K = 6.0          # 备选口径（单点速度阈值）：τ = median(v) + k·MAD(v)
RNG = np.random.default_rng(2026)

DATA2 = DATA_DIR / '附件2：位移时序数据-问题2.xlsx'
BASE_TIME = pd.Timestamp('2024-05-04 00:00:00')   # rl-timebase：附件2 时刻基准

df2 = pd.read_excel(DATA2)
assert list(df2.columns) == ['编号', '表面位移_mm'], df2.columns
idx1 = df2['编号'].to_numpy(dtype=int)          # 1..10000（1-based）
y = df2['表面位移_mm'].to_numpy(dtype=float)
n = len(y)
assert n == 10000 and np.all(np.isfinite(y))
t = (idx1 - 1) * STEP_H                          # 小时（t=2024-05-04 00:00+(编号−1)×10min）
times = pd.Series(BASE_TIME + pd.to_timedelta(idx1 - 1, unit='m') * 10)
v = 6.0 * np.diff(y)                             # 单步速度 mm/h
print(f'[Q2] 数据读取完成：n={n}，编号 {idx1[0]}..{idx1[-1]}，时刻 {times.iloc[0]} -> {times.iloc[-1]}')
print(f'[Q2] 位移 {y.min():.3f} -> {y.max():.3f} mm；单步速度 v∈[{v.min():.2f},{v.max():.2f}] mm/h')

def build_prefix(tv, yv):
    nv = len(yv)
    S = {}
    for name, arr in [('st', tv), ('st2', tv * tv), ('sy', yv), ('sty', tv * yv), ('sy2', yv * yv)]:
        S[name] = np.concatenate([[0.0], np.cumsum(arr)])
    return S

def seg_cost(i, j, S):
    """段 [i,j]（0-based 闭区间）OLS 拟合的 SSE 与系数 (a,b)，O(1)"""
    m = j - i + 1
    st = S['st'][j + 1] - S['st'][i]; st2 = S['st2'][j + 1] - S['st2'][i]
    sy = S['sy'][j + 1] - S['sy'][i]; sty = S['sty'][j + 1] - S['sty'][i]; sy2 = S['sy2'][j + 1] - S['sy2'][i]
    denom = m * st2 - st * st
    if denom <= 1e-12:
        b = 0.0
    else:
        b = (m * sty - st * sy) / denom
    a = (sy - b * st) / m
    sse = sy2 - 2 * a * sy - 2 * b * sty + a * a * m + 2 * a * b * st + b * b * st2
    return max(float(sse), 0.0), (float(a), float(b))

_tt = RNG.uniform(0, 100, 500); _yy = 0.3 + 1.5 * _tt + RNG.normal(0, 2, 500)
_sse, (aa, bb) = seg_cost(0, 499, build_prefix(_tt, _yy))
_pc = np.polyfit(_tt, _yy, 1)
assert abs(_sse - np.sum((_yy - _pc[0] * _tt - _pc[1]) ** 2)) < 1e-6
print('[Q2] seg_cost 自检通过（与 np.polyfit 一致）')

def seg_ols(tv, yv):
    """段 OLS 系数 (a,b)：y=a+b·t，b 单位 mm/h（t 为小时）"""
    m = len(yv)
    if m < 2:
        return float(yv[0]), 0.0
    st = tv.sum(); st2 = (tv * tv).sum(); sy = yv.sum(); sty = (tv * yv).sum()
    denom = m * st2 - st * st
    if denom <= 1e-12:
        return float(np.mean(yv)), 0.0
    b = (m * sty - st * sy) / denom
    a = (sy - b * st) / m
    return float(a), float(b)

def sse_vec(i0, js, P, nv, right_side=False):
    """段 [i0, j]（j∈js）的 OLS SSE（向量化，前缀和实现）。right_side=True 时计算段 [j+1, nv-1]。"""
    if right_side:
        st = P['st'][nv] - P['st'][js + 1]; st2 = P['st2'][nv] - P['st2'][js + 1]
        sy = P['sy'][nv] - P['sy'][js + 1]; sty = P['sty'][nv] - P['sty'][js + 1]
        sy2 = P['sy2'][nv] - P['sy2'][js + 1]
        m = (nv - 1) - js
    else:
        st = P['st'][js + 1] - P['st'][i0]; st2 = P['st2'][js + 1] - P['st2'][i0]
        sy = P['sy'][js + 1] - P['sy'][i0]; sty = P['sty'][js + 1] - P['sty'][i0]
        sy2 = P['sy2'][js + 1] - P['sy2'][i0]
        m = js - i0 + 1
    denom = m * st2 - st * st
    with np.errstate(divide='ignore', invalid='ignore'):
        b = np.where(denom > 1e-12, (m * sty - st * sy) / np.where(denom > 0, denom, 1.0), 0.0)
    a = (sy - b * st) / m
    c = sy2 - 2 * a * sy - 2 * b * sty + a * a * m + 2 * a * b * st + b * b * st2
    return np.maximum(c, 0.0)

def best_two_breaks(tv, yv, min_seg):
    """min 总 SSE(k1,k2)：cost[0,k1]+cost[k1+1,k2]+cost[k2+1,n-1]，各段长 ≥ min_seg。

    性能适配：C(j)=段[j+1,nv-1] 的 SSE 与 k1 无关，原实现每个 k1 都整段重算；
    此处预先对全部候选 j 计算一次 C_all 再按 js 切片，数值逐位相同（同 A/B/C → 同 argmin）。
    """
    nv = len(yv)
    P = build_prefix(tv, yv)
    j_all = np.arange(min_seg, nv - min_seg)          # 所有可能断点 j 的并集
    C_all = sse_vec(None, j_all, P, nv, right_side=True)
    best = (np.inf, None, None)
    for k1 in range(min_seg, nv - 2 * min_seg + 1):
        lo, hi = k1 + min_seg, nv - 1 - min_seg
        if lo > hi:
            continue
        js = np.arange(lo, hi + 1)
        B = sse_vec(k1 + 1, js, P, nv, right_side=False)
        C = C_all[js - min_seg]
        A = seg_cost(0, k1, P)[0]
        total = A + B + C
        j = int(js[np.argmin(total)])
        if total[np.argmin(total)] < best[0]:
            best = (float(total[np.argmin(total)]), k1, j)
    assert best[1] is not None
    return best

def vel_series(yv, smooth_w):
    """单步速度序列（mm/h）；smooth_w>1 时对速度取滚动中值（仅敏感性对照用）。"""
    vv = 6.0 * np.diff(yv)
    if smooth_w > 1:
        vv = pd.Series(vv).rolling(smooth_w, center=True, min_periods=1).median().to_numpy()
    return vv

def detect_nodes(yv, tv, min_seg, smooth_w):
    """速度序列结构突变 → (k1, k2)。k 为速度序列断点索引。"""
    vv = vel_series(yv, smooth_w)
    ttv = tv[1:]
    sse, k1, k2 = best_two_breaks(ttv, vv, min_seg)
    return sse, k1, k2

SSE_vel, k1, k2 = detect_nodes(y, t, MIN_SEG, VEL_SMOOTH_W)
node1_no, node2_no = k1 + 1, k2 + 1
node1_time = BASE_TIME + pd.to_timedelta(k1 * 10, unit='m')
node2_time = BASE_TIME + pd.to_timedelta(k2 * 10, unit='m')
print(f'[Q2] 结构检测（速度序列结构突变，K=2 精确解，smooth_w={VEL_SMOOTH_W}）：速度段拟合总 SSE={SSE_vel:.1f}')
print(f'[Q2] 节点1（缓慢→加速）：切分 k={k1}，编号 {node1_no}，时刻 {node1_time}')
print(f'[Q2] 节点2（加速→快速）：切分 k={k2}，编号 {node2_no}，时刻 {node2_time}')

# --- 三重判据 ---
stages = [('缓慢匀速', 0, k1), ('加速', k1 + 1, k2), ('快速', k2 + 1, n - 1)]
def stage_net_speed(s0, s1):
    return (y[s1] - y[s0]) / (t[s1] - t[s0])
def stage_int_median(s0, s1):
    return float(np.median(6.0 * np.diff(y[s0:s1 + 1]))) if s1 > s0 else float('nan')

vnet = [stage_net_speed(s0, s1) for _, s0, s1 in stages]
med_int = [stage_int_median(s0, s1) for _, s0, s1 in stages]
len_st = [s1 - s0 + 1 for _, s0, s1 in stages]
amp12 = (vnet[1] > vnet[0]) and (vnet[1] - vnet[0] >= AMP_STAGE_DELTA) and (vnet[0] <= 0 or vnet[1] >= AMP_STAGE_RATIO * vnet[0])
amp23 = (vnet[2] > vnet[1]) and (vnet[2] - vnet[1] >= AMP_STAGE_DELTA) and (vnet[1] <= 0 or vnet[2] >= AMP_STAGE_RATIO * vnet[1])
amp_ok = amp12 and amp23
persist_len_ok = all(m >= MIN_SEG for m in len_st)
persist_med12 = (med_int[1] >= med_int[0] + PERSIST_MIN_DELTA)
persist_med23 = (med_int[2] >= med_int[1] + PERSIST_MIN_DELTA)
persist_ok = persist_len_ok and persist_med12 and persist_med23
def chow_between(s0, s1, s2_):
    P = build_prefix(t[s0:s2_ + 1], y[s0:s2_ + 1])
    SSE_pool, _ = seg_cost(0, s2_ - s0, P)
    SSE_1, _ = seg_cost(0, s1 - s0, P)
    SSE_2, _ = seg_cost(s1 + 1 - s0, s2_ - s0, P)
    n1, n2 = s1 - s0 + 1, s2_ - s1
    F = ((SSE_pool - SSE_1 - SSE_2) / 2) / (max(SSE_1 + SSE_2, 1e-12) / (n1 + n2 - 4))
    p = 1.0 - stats.f.cdf(F, 2, n1 + n2 - 4)
    return float(F), float(p)
F12, p12 = chow_between(0, k1, k2)
F23, p23 = chow_between(k1 + 1, k2, n - 1)
model_ok = (p12 < MODEL_ALPHA) and (p23 < MODEL_ALPHA)
criterion_pass = amp_ok and persist_ok and model_ok
print(f'[Q2] 判据数值：阶段净速度 v={[f"{x:.4f}" for x in vnet]} mm/h；内部中位速度={[f"{x:.4f}" for x in med_int]} mm/h；阶段点数={len_st}')
print(f'[Q2] 三重判据：幅度(倍率≥{AMP_STAGE_RATIO})={amp_ok}；持续性(≥{MIN_SEG}点+中位递增)={persist_ok}；'
      f'模型差异(Chow p<{MODEL_ALPHA})={model_ok} -> 通过={criterion_pass}')
print(f'[Q2] Chow：节点1 F={F12:.1f} p={p12:.3g}；节点2 F={F23:.1f} p={p23:.3g}')

# --- 瞬时跳变剔除论证：注入单点 ±20mm 跳变后节点位移 ---
spike_shifts = []
for inj_idx, inj_amp in [(5000, 20.0), (9000, -20.0)]:
    y_sp = y.copy(); y_sp[inj_idx] += inj_amp
    _, k1s, k2s = detect_nodes(y_sp, t, MIN_SEG, VEL_SMOOTH_W)
    shift = max(abs(k1s - k1), abs(k2s - k2))
    spike_shifts.append({'注入位置': int(inj_idx), '注入幅度_mm': inj_amp,
                         'k1_注入后': int(k1s), 'k2_注入后': int(k2s), '节点最大位移_样本': int(shift)})
    print(f'[Q2] 注入跳变 @编号{inj_idx + 1} ±{inj_amp}mm：节点仍为 ({k1s},{k2s})，最大位移 {shift} 样本')
reg_daily_speed = (y[1871] - y[1728]) / (t[1871] - t[1728])
print(f'[Q2] 负回退段（编号 1729–1872）净速度={reg_daily_speed:.4f} mm/h <0 → 幅度判据排除（不切分为新阶段）')

# --- 分段建模（参数+检验）与各阶段平均速度（主=净变化，备选=Σ|Δ|）---
stage_rows = []
speed_main = {}
speed_alt = {}
for name, s0, s1 in stages:
    m = s1 - s0 + 1
    dur = t[s1] - t[s0]
    a, b = seg_ols(t[s0:s1 + 1], y[s0:s1 + 1])
    yhat = a + b * t[s0:s1 + 1]
    resid = y[s0:s1 + 1] - yhat
    sse = float(np.sum(resid ** 2)); rmse = float(np.sqrt(np.mean(resid ** 2)))
    sst = float(np.sum((y[s0:s1 + 1] - np.mean(y[s0:s1 + 1])) ** 2))
    r2 = 1.0 - sse / sst if sst > 0 else float('nan')
    s2_ = sse / max(m - 2, 1)
    sxx = float(np.sum((t[s0:s1 + 1] - np.mean(t[s0:s1 + 1])) ** 2))
    se_b = float(np.sqrt(s2_ / sxx)) if sxx > 0 else float('nan')
    tstat_b = b / se_b if se_b and se_b > 0 else float('nan')
    p_b = 2 * (1 - stats.t.cdf(abs(tstat_b), df=m - 2)) if np.isfinite(tstat_b) else float('nan')
    v_main = (y[s1] - y[s0]) / dur
    v_alt = float(np.sum(np.abs(np.diff(y[s0:s1 + 1])))) / dur
    speed_main[name] = v_main
    speed_alt[name] = v_alt
    stage_rows.append({'阶段': name, '编号范围': f'{idx1[s0]}..{idx1[s1]}',
                       '时刻范围': f'{times.iloc[s0]} -> {times.iloc[s1]}', 'n': m,
                       '时长_h': round(dur, 3), 'y_start': round(float(y[s0]), 3), 'y_end': round(float(y[s1]), 3),
                       'a': round(a, 4), 'b_mmh': round(b, 4), 'se_b': round(se_b, 5), 't_b': round(tstat_b, 3),
                       'p_b': float(p_b), 'R2': round(r2, 4), 'RMSE': round(rmse, 4),
                       'speed_net_mmh': round(v_main, 4), 'speed_path_mmh': round(v_alt, 4)})
    print(f'[Q2] 阶段[{name}] 编号 {idx1[s0]}..{idx1[s1]} 时长 {dur:.2f}h | y {y[s0]:.2f}->{y[s1]:.2f} | '
          f'拟合 y={a:.3f}+{b:.4f}t | R2={r2:.4f} RMSE={rmse:.3f} | t(b)={tstat_b:.2f} p={p_b:.3g} | '
          f'均速(净)={v_main:.4f} 均速(路径)={v_alt:.4f} mm/h')

# --- 备选口径：单点速度阈值 ---
tau = float(np.median(v) + VEL_ALT_K * 1.4826 * np.median(np.abs(v - np.median(v))))
above = np.where(v >= tau)[0]
alt_k1 = int(above[0]); alt_k2 = int(above[-1])
alt_stages = [('缓慢匀速', 0, alt_k1), ('加速', alt_k1 + 1, alt_k2), ('快速', alt_k2 + 1, n - 1)]
alt_speed_main = {}
for name, s0, s1 in alt_stages:
    dur = t[s1] - t[s0]
    alt_speed_main[name] = (y[s1] - y[s0]) / dur if dur > 0 else None
print(f'[Q2] 备选(单点速度阈值 τ={tau:.3f} mm/h)：节点1 编号 {alt_k1 + 1} '
      f'{BASE_TIME + pd.to_timedelta(alt_k1 * 10, unit="m")}，节点2 编号 {alt_k2 + 1} '
      f'{BASE_TIME + pd.to_timedelta(alt_k2 * 10, unit="m")}；v≥τ 的单步数={len(above)}（噪声±24mm/h 远超 τ，备选被噪声主导）')

# --- 敏感性：min_seg 与速度平滑窗 ---
sens_rows = []
for ms in [144, 288, 576]:
    _, k1s, k2s = detect_nodes(y, t, ms, VEL_SMOOTH_W)
    sens_rows.append({'参数': f'min_seg={ms}', 'smooth_w': VEL_SMOOTH_W, 'k1': int(k1s), 'k2': int(k2s),
                      'node1_编号': int(k1s + 1), 'node2_编号': int(k2s + 1)})
for sw in [72, 144]:
    _, k1s, k2s = detect_nodes(y, t, MIN_SEG, sw)
    sens_rows.append({'参数': f'smooth_w={sw}', 'smooth_w': sw, 'k1': int(k1s), 'k2': int(k2s),
                      'node1_编号': int(k1s + 1), 'node2_编号': int(k2s + 1)})
print('[Q2] 敏感性（min_seg 144/288/576；smooth_w 72/144）：', sens_rows)

# --- Q2 图 ---
fig, ax = plt.subplots(figsize=(11, 6))
ax.plot(idx1, y, color='0.65', lw=0.8, label='表面位移（原始）')
colors = {'缓慢匀速': '#1f77b4', '加速': '#ff7f0e', '快速': '#d62728'}
for name, s0, s1 in stages:
    a, b = seg_ols(t[s0:s1 + 1], y[s0:s1 + 1])
    ax.plot(idx1[s0:s1 + 1], a + b * t[s0:s1 + 1], color=colors[name], lw=2.2,
            label=f'{name}段拟合 y={a:.2f}+{b:.3f}t，均速 {speed_main[name]:.2f} mm/h')
ymax = y.max()
for k, no, tm, lab in [(k1, node1_no, node1_time, '节点1 缓慢→加速'), (k2, node2_no, node2_time, '节点2 加速→快速')]:
    ax.axvline(no, color='k', ls='--', lw=1.2)
    ax.annotate(f'{lab}\n编号 {no}  {tm:%m-%d %H:%M}', xy=(no, ymax), xytext=(0, 8),
                textcoords='offset points', ha='center', fontsize=9)
ax.set_xlabel('编号（10min/点，t=2024-05-04 00:00+(编号−1)×10min）'); ax.set_ylabel('表面位移 (mm)')
ax.set_title('Q2 三段式分段拟合与两个转换节点')
ax.legend(loc='upper left', fontsize=8); ax.grid(alpha=0.3)
fig.tight_layout(); fig.savefig(OUT / 'q2_fig_segmentation.png', dpi=150); plt.close(fig)

fig, axes = plt.subplots(2, 1, figsize=(11, 8), sharex=True)
ax = axes[0]
ax.plot(idx1[1:], v, color='0.75', lw=0.5, label='单步速度 (mm/h)')
ax.plot(idx1[1:], pd.Series(v).rolling(W_PERSIST, center=True, min_periods=1).median(),
        color='#1f77b4', lw=1.5, label=f'滚动中值 w={W_PERSIST}')
for k, no, tm, lab in [(k1, node1_no, node1_time, '节点1'), (k2, node2_no, node2_time, '节点2')]:
    ax.axvline(no, color='k', ls='--', lw=1.2)
    ax.annotate(f'{lab} 编号{no}\n{tm:%m-%d %H:%M}', xy=(no, ax.get_ylim()[1]), xytext=(0, 5),
                textcoords='offset points', ha='center', fontsize=8)
ax.axhline(tau, color='#d62728', ls=':', lw=1.2, label=f'备选单点阈值 τ={tau:.2f} mm/h（噪声±24 mm/h 远超，备选失效）')
for name, c in colors.items():
    ax.axhline(speed_main[name], color=c, lw=1.0, alpha=0.7)
    ax.text(n - 250, speed_main[name], f'{name} 净均速 {speed_main[name]:.2f}', color=c, fontsize=8, va='center')
ax.set_ylabel('速度 (mm/h)'); ax.set_title('Q2 速度序列 + 阶段净均速水平（持续性/幅度判据图示）')
ax.legend(loc='upper left', fontsize=8); ax.grid(alpha=0.3)
ax = axes[1]
ax.hist(v, bins=120, density=True, alpha=0.6, color='#2ca02c')
ax.axvline(tau, color='#d62728', ls=':', lw=1.5, label=f'备选阈值 τ={tau:.2f} mm/h')
ax.axvline(0, color='k', lw=0.8)
ax.set_xlabel('单步速度 (mm/h)'); ax.set_ylabel('密度')
ax.set_title('Q2 单步速度分布：噪声 ±24 mm/h 与备选阈值重叠，单点阈值无法区分瞬时跳变')
ax.legend(fontsize=8); ax.grid(alpha=0.3)
fig.tight_layout(); fig.savefig(OUT / 'q2_fig_speed.png', dpi=150); plt.close(fig)
print('[Q2] 图已输出至 cwd：q2_fig_segmentation.png / q2_fig_speed.png')

Q2_node1 = int(node1_no); Q2_node2 = int(node2_no)
Q2_time1 = node1_time.strftime('%Y-%m-%d_%H:%M')
Q2_time2 = node2_time.strftime('%Y-%m-%d_%H:%M')
Q2_speeds = [speed_main['缓慢匀速'], speed_main['加速'], speed_main['快速']]
print(f"Q2: node1={Q2_node1} node2={Q2_node2} time1={Q2_time1} time2={Q2_time2} "
      f"speeds=[{','.join(f'{x:.4f}' for x in Q2_speeds)}]")

# =====================================================================
# Q3 附件3（Q3.1 去噪补齐 → Q3.2 异常检测 → Q3.3 关联贡献；内存传递）
# =====================================================================
# ---------------- Q3.1 顶层口径参数 ----------------
IMPUTE_METHOD_CONT = 'pchip'        # 连续量插补：PCHIP 保形三次（缺失短段<=4 行）
IMPUTE_METHOD_RAIN = 'linear'       # 降雨（重尾）：线性，仅填缺失格
IMPUTE_METHOD_COUNT = 'nearest'     # 微震计数：最近邻，保整数
DENOISE_METHOD_CONT = 'hampel'      # 连续量去噪：Hampel 稳健局部（保边）
DENOISE_METHOD_RAIN = 'none'        # 降雨去噪：none（重尾大值=真实事件信号）
DENOISE_METHOD_COUNT = 'none'       # 微震计数不去噪（保整数）
HAMPEL_HALF_WINDOW = 5              # Hampel 半窗：总窗 2*5+1=11 点 ≈ 100min
HAMPEL_K_CONT = 6.0                 # 连续量 Hampel 阈值（k * 1.4826 * 局部 MAD）
HAMPEL_K_RAIN = 5.0                 # 降雨重尾：更高阈值，只清极端孤立尖峰
HAMPEL_RAIN_ISOLATED_ONLY = True    # 降雨：仅替换「孤立尖峰」（保降雨过程）
MAD_TO_SIGMA = 1.4826               # MAD -> sigma 换算

VARS = ['a', 'b', 'c', 'd', 'e']
VAR_CN = {'a': '降雨量(mm)', 'b': '孔隙水压力(kPa)', 'c': '微震事件数',
          'd': '深部位移(mm)', 'e': '表面位移(mm)'}
VAR_KIND = {'a': 'rain', 'b': 'cont', 'c': 'count', 'd': 'cont', 'e': 'cont'}

SRC3 = DATA_DIR / '附件3：监测数据（训练集与实验集）-问题3.xlsx'

def read_unify3():
    """读取附件3 两个 sheet，统一列名为 编号/a..e。"""
    xl = pd.ExcelFile(SRC3)
    tr = xl.parse('训练集')
    ex = xl.parse('实验集')
    tr = tr.rename(columns={'a:降雨量_mm': 'a', 'b:孔隙水压力_kPa': 'b',
                            'c:微震事件数': 'c', 'd:深部位移_mm': 'd',
                            'e:表面位移_mm': 'e'})
    ex = ex.rename(columns={'降雨量_mm': 'a', '孔隙水压力_kPa': 'b',
                            '微震事件数': 'c', '深部位移_mm': 'd',
                            '表面位移_mm': 'e'})
    return tr, ex

def impute_cont_pchip(x):
    """连续量 PCHIP 保形插值（首尾缺失用最近有效值钳制）。"""
    x = np.asarray(x, dtype=float)
    idx = np.arange(len(x))
    valid = ~np.isnan(x)
    if valid.sum() == 0:
        return x
    if valid.sum() == 1:
        return np.full(len(x), x[valid][0])
    x2 = x.copy()
    if np.isnan(x2[0]):
        f = int(np.argmax(valid))
        x2[:f] = x[f]
    if np.isnan(x2[-1]):
        b = int(len(x) - 1 - np.argmax(valid[::-1]))
        x2[b + 1:] = x[b]
    mask = np.isnan(x2)
    if mask.any():
        p = PchipInterpolator(idx[~mask], x2[~mask])
        x2[mask] = p(idx[mask])
    return x2

def impute_linear(x):
    """线性插值（np.interp 端点钳制为最近有效值）。"""
    x = np.asarray(x, dtype=float)
    idx = np.arange(len(x))
    valid = ~np.isnan(x)
    if valid.sum() == 0:
        return x
    return np.interp(idx, idx[valid], x[valid])

def impute_count_nearest(x):
    """微震计数最近邻插补，取整保整数。"""
    x = np.asarray(x, dtype=float)
    valid = np.where(~np.isnan(x))[0]
    if len(valid) == 0:
        return x
    miss = np.where(np.isnan(x))[0]
    out = x.copy()
    for i in miss:
        j = valid[np.argmin(np.abs(valid - i))]
        out[i] = x[j]
    return np.round(out).astype(int)

def hampel(x, half_win, k, isolated_only=False):
    """Hampel 滤波器：|x_i - M_i| > k*1.4826*MAD_i 时以窗口内中位数替换。"""
    x = np.asarray(x, dtype=float)
    n = len(x)
    y = x.copy()
    replaced = 0
    for i in range(n):
        lo, hi = max(0, i - half_win), min(n, i + half_win + 1)
        w = x[lo:hi]
        med = float(np.median(w))
        mad = float(np.median(np.abs(w - med)))
        if mad <= 0:
            continue
        thr = k * MAD_TO_SIGMA * mad
        if abs(x[i] - med) > thr:
            if isolated_only:
                left_ok = (i == 0) or (abs(x[i - 1] - med) <= thr)
                right_ok = (i == n - 1) or (abs(x[i + 1] - med) <= thr)
                if not (left_ok and right_ok):
                    continue
            y[i] = med
            replaced += 1
    return y, replaced

def process_q31(df, tag):
    """对单个 sheet 做 插补 -> 去噪，返回 (清洗 DataFrame, 诊断 dict)。"""
    diag = {}
    clean = df[['编号']].copy()
    for v in VARS:
        kind = VAR_KIND[v]
        raw = df[v].to_numpy(dtype=float)
        miss_n = int(np.isnan(raw).sum())

        if kind == 'cont':
            x = impute_cont_pchip(raw)
        elif kind == 'rain':
            x = impute_linear(raw)
        else:
            x = impute_count_nearest(raw).astype(float)

        filled = int(np.isnan(raw).sum() - np.isnan(x).sum())
        if kind == 'cont':
            yc, rep = hampel(x, HAMPEL_HALF_WINDOW, HAMPEL_K_CONT)
        elif kind == 'rain':
            yc, rep = x.copy(), 0
        else:
            yc, rep = x.copy(), 0

        clean[v] = yc
        if np.isnan(raw).all():
            diag[v] = {'var_cn': VAR_CN[v], 'kind': kind, 'missing_n': miss_n,
                       'filled_n': 0, 'all_nan': True,
                       'note': '整列空（实验集表面位移=预测目标，本问不补齐）'}
            clean[v] = np.nan
            continue
        d = np.abs(np.diff(yc))
        diag[v] = {
            'var_cn': VAR_CN[v],
            'kind': kind,
            'missing_n': miss_n,
            'filled_n': filled,
            'denoise_method': (DENOISE_METHOD_CONT if kind == 'cont'
                               else DENOISE_METHOD_RAIN if kind == 'rain'
                               else DENOISE_METHOD_COUNT),
            'hampel_replaced_n': int(rep),
            'after_mean': round(float(np.mean(yc)), 4),
            'after_std': round(float(np.std(yc)), 4),
            'after_median': round(float(np.median(yc)), 4),
            'after_max_abs_step': round(float(np.max(d)), 4),
            'after_zero_frac': round(float(np.mean(yc == 0)), 4),
        }
        if not np.isnan(raw).all():
            d_raw = np.abs(np.diff(np.where(np.isnan(raw), np.nan, raw)))
            diag[v].update({
                'before_mean': round(float(np.nanmean(raw)), 4),
                'before_std': round(float(np.nanstd(raw)), 4),
                'before_median': round(float(np.nanmedian(raw)), 4),
                'before_max_abs_step': round(float(np.nanmax(d_raw)), 4),
            })
    return clean, diag

# ---------- Q3.1 主流程（内存传递，不落盘 CSV） ----------
tr3, ex3 = read_unify3()
assert ex3['e'].isna().all(), '实验集表面位移应 100% 空（预测目标）'
assert tr3['e'].notna().sum() + tr3['e'].isna().sum() == 10000

tr_clean, tr_diag = process_q31(tr3, 'train')
ex_clean, ex_diag = process_q31(ex3, 'exp')
ex_clean['e'] = np.nan
ex_diag['e'] = {'target_nan': True,
                'note': '实验集表面位移 100% 空 = 预测目标，本问(Q3.1)不补齐'}
d31 = {'train': tr_diag, 'exp': ex_diag,
       'params': {'impute_cont': IMPUTE_METHOD_CONT,
                  'impute_rain': IMPUTE_METHOD_RAIN,
                  'impute_count': IMPUTE_METHOD_COUNT,
                  'denoise_cont': DENOISE_METHOD_CONT,
                  'denoise_rain': DENOISE_METHOD_RAIN,
                  'denoise_count': DENOISE_METHOD_COUNT,
                  'hampel_half_window': HAMPEL_HALF_WINDOW,
                  'hampel_k_cont': HAMPEL_K_CONT,
                  'hampel_k_rain': HAMPEL_K_RAIN,
                  'hampel_rain_isolated_only': HAMPEL_RAIN_ISOLATED_ONLY}}

print('===== Q3.1 去噪+缺失补齐 诊断（训练集） =====')
tot_filled = 0
for v in VARS:
    d = tr_diag[v]
    tot_filled += d['filled_n']
    print(f"{v}({VAR_CN[v]}) 缺失 {d['missing_n']} 补齐 {d['filled_n']} | "
          f"去噪 {d['denoise_method']} 替换 {d['hampel_replaced_n']} 点 | "
          f"std {d['before_std']}->{d['after_std']} | "
          f"max|Δ| {d['before_max_abs_step']}->{d['after_max_abs_step']}")
print(f"训练集总补齐格数 = {tot_filled}")
print(f"实验集 e 保持空（预测目标，未补齐）: {int(ex_clean['e'].isna().sum())} / 5000")
for v in ['a', 'b', 'c', 'd']:
    d = ex_diag[v]
    print(f"实验集 {v} 补齐 {d['filled_n']} 格，去噪替换 {d['hampel_replaced_n']} 点")

# Q3.1 图：去噪/补齐前后对比
fig, axes = plt.subplots(5, 1, figsize=(14, 16), sharex=False)
for ax, v in zip(axes, VARS):
    raw = tr3[v].to_numpy(dtype=float)
    cl = tr_clean[v].to_numpy(dtype=float)
    idx = np.arange(1, len(raw) + 1)
    ax.plot(idx, raw, color='0.75', lw=0.8, label='原始(含缺失)')
    ax.plot(idx, cl, color='C0', lw=0.9, label='补齐+去噪后')
    miss = np.where(np.isnan(raw))[0]
    if len(miss):
        ax.scatter(idx[miss], cl[miss], s=12, c='C3', zorder=3,
                   label=f'补齐点 n={len(miss)}')
    d = tr_diag[v]
    ax.set_title(f"{v} {VAR_CN[v]} | 补齐 {d['filled_n']} 去噪替换 "
                 f"{d['hampel_replaced_n']} (max|Δ| {d['before_max_abs_step']}"
                 f"->{d['after_max_abs_step']})")
    ax.legend(loc='upper left', fontsize=8)
fig.suptitle('Q3.1 附件3 训练集：缺失补齐 + 稳健局部去噪（Hampel 保边）前后对比',
             fontsize=14)
fig.tight_layout(rect=[0, 0, 1, 0.97])
fig.savefig(OUT / 'q31_fig_denoise.png', dpi=150)
plt.close(fig)
print('[Q3.1] 图已输出至 cwd：q31_fig_denoise.png（清洗 DataFrame 内存传递至 Q3.2/Q3.3）')

# ---------------- Q3.2 异常检测（基于内存中的 tr_clean） ----------------
RESID_HALF_WINDOW = 5            # 滚动中值基线半窗（总窗 11 点 ≈ 100min）
CONT_RESID_K_MAD = 3.0           # 连续量：|resid| > k * 1.4826 * MAD(resid)
RAIN_RESID_K_IQR = 6.0           # 降雨（重尾）：|resid| > max(Q3 + k*IQR, MIN_ABS_MM)
RAIN_RESID_MIN_ABS_MM = 10.0     # 降雨绝对下限：>10mm/10min（≈60mm/h 极端雨强）
COUNT_RESID_K_IQR = 1.5          # 微震计数：|resid| > max(k*IQR, MIN_ABS)
COUNT_RESID_MIN_ABS = 1.0        # 计数阈值下限
SIGMA_K = 3.0                    # 备选：|resid| > 3*std(resid)
COMMON_MIN_VARS = 2              # 同一编号 ≥2 个变量同时异常（题面 Q3.2）

def rolling_median_baseline(x, half_win):
    """滚动中值局部基线（稳健，中心对齐，边缘最少 1 点）。"""
    s = pd.Series(x)
    return s.rolling(2 * half_win + 1, center=True, min_periods=1).median().to_numpy()

def detect_main(resid, kind):
    """主判据 MAD/IQR（按变量类型分治）。返回 (掩码, 阈值, 说明)。"""
    if kind == 'cont':
        mad = float(np.median(np.abs(resid - np.median(resid))))
        if mad <= 0:
            mad = 1e-12
        thr = CONT_RESID_K_MAD * MAD_TO_SIGMA * mad
        flag = np.abs(resid) > thr
        note = f'|resid| > {CONT_RESID_K_MAD}*1.4826*MAD(resid)={thr:.4f}'
    elif kind == 'rain':
        q1, q3 = np.quantile(resid, [0.25, 0.75])
        iqr = q3 - q1
        thr = max(q3 + RAIN_RESID_K_IQR * iqr, RAIN_RESID_MIN_ABS_MM)
        flag = np.abs(resid) > thr
        note = (f'|resid| > max(Q3+{RAIN_RESID_K_IQR}*IQR={q3 + RAIN_RESID_K_IQR * iqr:.4f}, '
                f'MIN_ABS={RAIN_RESID_MIN_ABS_MM}mm)={thr:.4f} '
                f'(Q3={q3:.4f}, IQR={iqr:.4f})')
    else:  # count
        q1, q3 = np.quantile(resid, [0.25, 0.75])
        iqr = q3 - q1
        thr = max(COUNT_RESID_K_IQR * iqr, COUNT_RESID_MIN_ABS)
        flag = np.abs(resid) > thr
        note = (f'|resid| > max({COUNT_RESID_K_IQR}*IQR={COUNT_RESID_K_IQR*iqr:.4f}, '
                f'MIN_ABS={COUNT_RESID_MIN_ABS})={thr:.4f}')
    return flag, thr, note

def detect_sigma(resid):
    """备选判据 3σ：|resid| > 3*std(resid)。"""
    s = float(np.std(resid))
    if s <= 0:
        s = 1e-12
    thr = SIGMA_K * s
    return np.abs(resid) > thr, thr

df32 = tr_clean
n32 = len(df32)
resid_all = {}
diag32 = {'params': {'resid_half_window': RESID_HALF_WINDOW,
                     'cont_k_mad': CONT_RESID_K_MAD,
                     'rain_k_iqr': RAIN_RESID_K_IQR,
                     'rain_min_abs_mm': RAIN_RESID_MIN_ABS_MM,
                     'count_k_iqr': COUNT_RESID_K_IQR,
                     'count_min_abs': COUNT_RESID_MIN_ABS,
                     'sigma_k': SIGMA_K,
                     'common_min_vars': COMMON_MIN_VARS},
          'vars': {}}

flags_main = {}
flags_sigma = {}
for v in VARS:
    x = df32[v].to_numpy(dtype=float)
    base = rolling_median_baseline(x, RESID_HALF_WINDOW)
    resid = x - base
    resid_all[v] = resid
    fm, thrm, notem = detect_main(resid, VAR_KIND[v])
    fs, thrs = detect_sigma(resid)
    flags_main[v] = fm
    flags_sigma[v] = fs
    diag32['vars'][v] = {
        'var_cn': VAR_CN[v], 'kind': VAR_KIND[v],
        'resid_MAD': round(float(np.median(np.abs(resid - np.median(resid)))), 4),
        'resid_IQR': round(float(np.quantile(resid, 0.75) - np.quantile(resid, 0.25)), 4),
        'resid_std': round(float(np.std(resid)), 4),
        'main_criterion': notem,
        'main_threshold': round(float(thrm), 4),
        'main_n': int(fm.sum()),
        'main_rate_pct': round(100.0 * fm.sum() / n32, 3),
        'sigma_criterion': f'|resid| > {SIGMA_K}*std={thrs:.4f}',
        'sigma_threshold': round(float(thrs), 4),
        'sigma_n': int(fs.sum()),
        'sigma_rate_pct': round(100.0 * fs.sum() / n32, 3),
    }

# 表 3.1
rows31 = [{'变量': v, '中文': VAR_CN[v], '异常点数量': int(flags_main[v].sum())}
          for v in VARS]
total_main = int(sum(flags_main[v].sum() for v in VARS))
rows31.append({'变量': '总数', '中文': '—',
               '异常点数量': total_main})
t31 = pd.DataFrame(rows31)

# 表 3.2（主判据）
nvar = np.zeros(n32, dtype=int)
for v in VARS:
    nvar += flags_main[v].astype(int)
common_mask = nvar >= COMMON_MIN_VARS
ids = df32['编号'].to_numpy()
rows32 = []
for i in np.where(common_mask)[0]:
    combo = ''.join(v for v in VARS if flags_main[v][i])
    rows32.append({'时间点对应编号': int(ids[i]), '异常变量': combo,
                   '异常变量数': int(nvar[i])})
t32 = pd.DataFrame(rows32)

# 备选判据（3σ）共同异常
nvar_s = np.zeros(n32, dtype=int)
for v in VARS:
    nvar_s += flags_sigma[v].astype(int)
common_sigma = int((nvar_s >= COMMON_MIN_VARS).sum())

diag32['table31_main'] = {v: int(flags_main[v].sum()) for v in VARS}
diag32['table31_total_main'] = total_main
diag32['table32_common_main_n'] = int(common_mask.sum())
diag32['common_sigma_n'] = common_sigma
diag32['common_distribution'] = {
    'n_common_by_var_count': {str(k): int((nvar[common_mask] == k).sum())
                              for k in range(2, 6)}
}

print('===== Q3.2 异常检测（主=MAD/IQR，备选=3σ） =====')
for v in VARS:
    d = diag32['vars'][v]
    print(f"{v}({d['var_cn']}) 主[{d['main_n']}点 {d['main_rate_pct']}%] "
          f"备选3σ[{d['sigma_n']}点 {d['sigma_rate_pct']}%] | "
          f"主阈值={d['main_threshold']} 3σ阈值={d['sigma_threshold']}")
print(f"表3.1 总数(主) = {total_main}")
print(f"表3.2 共同异常点(主) = {common_mask.sum()}  | 3σ备选共同 = {common_sigma}")
print('共同异常点组合分布:',
      {k: int((nvar[common_mask] == int(k)).sum()) for k in range(2, 6)})
print('表3.2 前 10 行:')
print(t32.head(10).to_string(index=False))

# Q3.2 图
fig, axes = plt.subplots(6, 1, figsize=(15, 17))
idx32 = np.arange(1, n32 + 1)
for ax, v in zip(axes[:5], VARS):
    x = df32[v].to_numpy(dtype=float)
    ax.plot(idx32, x, color='0.75', lw=0.7, label='预处理后')
    fm = flags_main[v]
    ax.scatter(idx32[fm], x[fm], s=14, c='C3', zorder=3,
               label=f"异常 n={int(fm.sum())}")
    d = diag32['vars'][v]
    ax.set_title(f"{v} {d['var_cn']} | 主判据异常 {d['main_n']} 点 "
                 f"({d['main_rate_pct']}%)，3σ备选 {d['sigma_n']} 点")
    ax.legend(loc='upper right', fontsize=8)
ax = axes[5]
ax.step(idx32, nvar, where='mid', lw=0.9, color='0.4')
ax.scatter(idx32[common_mask], nvar[common_mask], s=20, c='C3', zorder=3,
           label=f"共同异常(≥{COMMON_MIN_VARS}变量) n={int(common_mask.sum())}")
ax.axhline(COMMON_MIN_VARS - 0.5, color='C3', lw=1, ls='--')
ax.set_ylim(-0.2, 5.5)
ax.set_title(f'每时刻异常变量数（≥{COMMON_MIN_VARS} = 共同异常点，主判据）')
ax.set_xlabel('训练集编号')
ax.legend(loc='upper left', fontsize=8)
fig.suptitle('Q3.2 附件3 训练集：单变量异常（红点）+ 共同异常点分布', fontsize=14)
fig.tight_layout(rect=[0, 0, 1, 0.98])
fig.savefig(OUT / 'q3_fig_anomaly.png', dpi=150)
plt.close(fig)
print('[Q3.2] 图已输出至 cwd：q3_fig_anomaly.png')

# ---------------- Q3.3 关联分析 + 贡献度 + 实验集估计（内存传递） ----------------
CCF_MAX_LAG = 288              # CCF 候选滞后上限：288 步 × 10min = 48h
DETREND_WINDOW = 144           # 去趋势滚动中值窗：144 步 = 1 天
CV_VAL_FRACTION = 0.20         # 前向验证：末 20% 作验证集（时序前向）
PI_Z = 1.96                    # 预测区间 z 值（±1.96*SE ≈ 95%）
DO_VIF = True                  # VIF 共线性诊断
DO_PARTIAL_R2 = True           # 偏 R²（方差分解，与进入顺序无关）
INCR_ORDER_MAIN = ['a', 'b', 'c', 'd']   # 增量 R² 主序：物理链 降雨→孔压→微震→深部
INCR_ORDER_REV = ['d', 'c', 'b', 'a']    # 增量 R² 逆序：共线敏感性对照

PREDICTORS = ['a', 'b', 'c', 'd']

def ccf(x, y, max_lag):
    """归一化互相关函数 CCF(L) = corr(x_t, y_{t+L})，L=0..max_lag。"""
    x = x - np.mean(x)
    y = y - np.mean(y)
    n = len(x)
    sx, sy = np.std(x), np.std(y)
    c = np.correlate(x, y, mode='full')
    out = np.zeros(max_lag + 1)
    for L in range(max_lag + 1):
        m = n - L
        if m < 100 or sx == 0 or sy == 0:
            out[L] = np.nan
            continue
        out[L] = c[n - 1 - L] / (m * sx * sy)
    return out

def lag_feature(x, lag):
    """表面位移 t 用 特征_{t-lag}：y[t] = x[t-lag]（t>=lag），t<lag 用首值。"""
    x = np.asarray(x, dtype=float)
    n = len(x)
    if lag == 0:
        return x.copy()
    y = np.full(n, x[0])
    y[lag:] = x[:n - lag]
    return y

def ols(X, y):
    """OLS：最小二乘系数 + 残差。"""
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    yhat = X @ beta
    resid = y - yhat
    return beta, yhat, resid

def r2_score(y, yhat):
    ss_res = float(np.sum((y - yhat) ** 2))
    ss_tot = float(np.sum((y - np.mean(y)) ** 2))
    return 1.0 - ss_res / ss_tot

def build_X3(df, lags):
    """按滞后构造设计矩阵 [1, a_lag, b_lag, c_lag, d_lag]。"""
    cols = [np.ones(len(df))]
    for v in PREDICTORS:
        cols.append(lag_feature(df[v].to_numpy(dtype=float), lags[v]))
    return np.column_stack(cols)

tr33 = tr_clean
ex33 = ex_clean
n33 = len(tr33)
assert ex33['e'].isna().all(), '实验集 e 应为全空（预测目标）'

# 1) CCF 定候选滞后
det = {}
for v in VARS:
    x = tr33[v].to_numpy(dtype=float)
    if v in 'bde':
        det[v] = x - pd.Series(x).rolling(DETREND_WINDOW, center=True,
                                          min_periods=1).median().to_numpy()
    else:
        det[v] = x

ccf_pairs = [('a', 'b'), ('b', 'd'), ('d', 'e'), ('a', 'e'), ('c', 'e')]
ccf_out = {}
lags_pair = {}
for u, v in ccf_pairs:
    cc = ccf(det[u], det[v], CCF_MAX_LAG)
    ccf_out[f'{u}->{v}'] = cc
    L = int(np.nanargmax(cc))
    lags_pair[f'{u}->{v}'] = L
    print(f"CCF {u}->{v}: 峰值滞后 L={L} 步 (10min/步) CCF={cc[L]:.4f}")

L1 = lags_pair['a->b']
L2 = lags_pair['b->d']
L3 = lags_pair['d->e']
Lc = lags_pair['c->e']
La = lags_pair['a->e']
lags = {'a': L1 + L2 + L3, 'b': L2 + L3, 'c': Lc, 'd': L3}
lag_info = {'L1_rain_to_pore': int(L1), 'L2_pore_to_deep': int(L2),
            'L3_deep_to_surface': int(L3),
            'Lc_micro_to_surface': int(Lc),
            'La_rain_to_surface_direct': int(La),
            'feature_lags_steps': {k: int(v) for k, v in lags.items()},
            'feature_lags_hours': {k: round(v * 10 / 60, 2)
                                   for k, v in lags.items()},
            'note_ccf_not_causal': 'CCF 定的是候选滞后（线性相关峰值），非因果，因果需机制/实验论证'}
print('特征滞后(步):', lag_info['feature_lags_steps'],
      '≈小时:', lag_info['feature_lags_hours'])

# 2) 回归 + 贡献度（滞后对齐主）
y33 = tr33['e'].to_numpy(dtype=float)
X33 = build_X3(tr33, lags)
beta, yhat, resid33 = ols(X33, y33)
r2_main = r2_score(y33, yhat)
se = float(np.std(resid33))

Xs = (X33[:, 1:] - X33[:, 1:].mean(axis=0)) / X33[:, 1:].std(axis=0)
ys = (y33 - y33.mean()) / y33.std()
beta_s, _, _ = ols(np.column_stack([np.ones(n33), Xs]), ys)
std_coef = {v: float(beta_s[i + 1]) for i, v in enumerate(PREDICTORS)}

vif = {}
if DO_VIF:
    for j, v in enumerate(PREDICTORS):
        Xo = X33[:, [0] + [k + 1 for k in range(4) if k != j]]
        bj, yhatj, _ = ols(Xo, X33[:, j + 1])
        rj = r2_score(X33[:, j + 1], yhatj)
        vif[v] = float(1.0 / (1.0 - rj))

def incremental_r2(order):
    out = {}
    cur = None
    for v in order:
        cols = [0] + [PREDICTORS.index(w) + 1 for w in order[:order.index(v) + 1]]
        b, yh, _ = ols(X33[:, cols], y33)
        r2 = r2_score(y33, yh)
        out[v] = r2 if cur is None else r2 - cur
        cur = r2
    return out, cur

incr_main, r2_after_main = incremental_r2(INCR_ORDER_MAIN)
incr_rev, r2_after_rev = incremental_r2(INCR_ORDER_REV)

partial_r2, partial_corr = {}, {}
if DO_PARTIAL_R2:
    for j, v in enumerate(PREDICTORS):
        keep = [0] + [k + 1 for k in range(4) if k != j]
        bf, yhf, _ = ols(X33, y33)
        bw, yhw, _ = ols(X33[:, keep], y33)
        r2f = r2_score(y33, yhf)
        r2w = r2_score(y33, yhw)
        partial_r2[v] = float((r2f - r2w) / (1.0 - r2w))
        Xo = X33[:, [0] + [k + 1 for k in range(4) if k != j]]
        _, yhx, rx = ols(Xo, X33[:, j + 1])
        _, yhy, ry = ols(Xo, y33)
        pc = pearsonr(rx, ry)[0]
        partial_corr[v] = float(pc)

# 3) 双跑：零滞后（备选）
lags0 = {'a': 0, 'b': 0, 'c': 0, 'd': 0}
X0 = build_X3(tr33, lags0)
beta0, yhat0, resid0 = ols(X0, y33)
r2_zero = r2_score(y33, yhat0)
Xs0 = (X0[:, 1:] - X0[:, 1:].mean(axis=0)) / X0[:, 1:].std(axis=0)
beta_s0, _, _ = ols(np.column_stack([np.ones(n33), Xs0]), ys)
std_coef0 = {v: float(beta_s0[i + 1]) for i, v in enumerate(PREDICTORS)}
incr0, _ = incremental_r2(INCR_ORDER_MAIN)

# 4) 前向验证（末 20%）
n_tr = int(n33 * (1 - CV_VAL_FRACTION))
Xtr, ytr = X33[:n_tr], y33[:n_tr]
Xva, yva = X33[n_tr:], y33[n_tr:]
btr, yhat_tr, _ = ols(Xtr, ytr)
yhat_va = Xva @ btr
rmse_va = float(np.sqrt(np.mean((yva - yhat_va) ** 2)))
mae_va = float(np.mean(np.abs(yva - yhat_va)))
r2_va = r2_score(yva, yhat_va)

# 5) 实验集预测
Xe = build_X3(ex33, lags)
y_pred = Xe @ beta
pred = pd.DataFrame({'编号': ex33['编号'].to_numpy(dtype=int),
                     '表面位移估计_mm': np.round(y_pred, 4)})

print('\n===== Q3.3 回归（滞后对齐主） =====')
print(f"R²(主) = {r2_main:.4f}   残差 SE = {se:.4f} mm")
print('标准化系数:', {k: round(v, 4) for k, v in std_coef.items()})
print('VIF:', {k: round(v, 3) for k, v in vif.items()})
print('增量R²(物理链序 a,b,c,d):',
      {k: round(v, 4) for k, v in incr_main.items()})
print('增量R²(逆序 d,c,b,a):',
      {k: round(v, 4) for k, v in incr_rev.items()})
print('偏R²:', {k: round(v, 4) for k, v in partial_r2.items()})
print('偏相关:', {k: round(v, 4) for k, v in partial_corr.items()})
print('\n===== 双跑：零滞后（备选） =====')
print(f"R²(零滞后) = {r2_zero:.4f}  vs  R²(滞后对齐) = {r2_main:.4f}")
print('零滞后标准化系数:', {k: round(v, 4) for k, v in std_coef0.items()})
print('零滞后增量R²:', {k: round(v, 4) for k, v in incr0.items()})
print('\n===== 前向验证（末 20%） =====')
print(f"RMSE={rmse_va:.4f} mm  MAE={mae_va:.4f} mm  R²={r2_va:.4f}")
print('\n===== 实验集预测 =====')
print(f"n={len(pred)} 估计 mean={pred['表面位移估计_mm'].mean():.4f} "
      f"std={pred['表面位移估计_mm'].std():.4f} "
      f"min={pred['表面位移估计_mm'].min():.4f} max={pred['表面位移估计_mm'].max():.4f}")
print(f"预测区间半宽 ±{PI_Z * se:.4f} mm")

# Q3.3 图 1：CCF 滞后
fig, axes = plt.subplots(len(ccf_pairs), 1, figsize=(13, 3.4 * len(ccf_pairs)))
for ax, (u, v) in zip(axes, ccf_pairs):
    cc = ccf_out[f'{u}->{v}']
    L = lags_pair[f'{u}->{v}']
    lags_x = np.arange(0, CCF_MAX_LAG + 1)
    ax.plot(lags_x, cc, lw=0.9, color='C0')
    ax.axvline(L, color='C3', ls='--', lw=1)
    ax.set_title(f'CCF {VAR_CN[u]} → {VAR_CN[v]}  峰值滞后 L={L} 步 '
                 f'({L * 10 / 60:.1f}h)，CCF={cc[L]:.4f}')
    ax.set_xlabel('滞后 L（10min 步）')
    ax.set_ylabel('CCF')
fig.suptitle('Q3.3 物理链 CCF 候选滞后（CCF≠因果，仅作特征对齐）', fontsize=14)
fig.tight_layout(rect=[0, 0, 1, 0.98])
fig.savefig(OUT / 'q3_fig_ccf.png', dpi=150)
plt.close(fig)

# Q3.3 图 2：贡献度三方对比
labels = [f"{v}\n{VAR_CN[v].split('(')[0]}" for v in PREDICTORS]
xpos = np.arange(4)
w = 0.27
fig, ax = plt.subplots(figsize=(11, 6))
ax.bar(xpos - w, [std_coef[v] for v in PREDICTORS], w, label='标准化系数',
       color='C0')
ax.bar(xpos, [partial_r2[v] * 10 for v in PREDICTORS], w,
       label='偏R²(×10)', color='C3')
ax.bar(xpos + w, [incr_main[v] * 10 for v in PREDICTORS], w,
       label='增量R²物理链序(×10)', color='C2')
ax.set_xticks(xpos)
ax.set_xticklabels(labels)
ax.axhline(0, color='k', lw=0.8)
ax.set_ylabel('贡献度（偏R²/增量R² ×10 便于同图对比）')
ax.set_title('Q3.3 各因素对表面位移的贡献度三方对比'
             '（标准化系数 / 偏R² / 增量R²方差分解）')
ax.legend()
fig.tight_layout()
fig.savefig(OUT / 'q3_fig_contrib.png', dpi=150)
plt.close(fig)

# Q3.3 图 3：实验集估计散点图
idx_e = pred['编号'].to_numpy(dtype=int)
ye = pred['表面位移估计_mm'].to_numpy(dtype=float)
fig, ax = plt.subplots(figsize=(13, 5.5))
ax.scatter(idx_e, ye, s=3, c='C1', alpha=0.7, label='实验集表面位移估计值')
ax.fill_between(idx_e, ye - PI_Z * se, ye + PI_Z * se, color='C0',
                alpha=0.15, label=f'±{PI_Z}·SE 预测区间（SE={se:.2f} mm）')
ax.set_xlabel('实验集编号（10min 步）')
ax.set_ylabel('表面位移估计值 (mm)')
ax.set_title('Q3.3 实验集表面位移估计散点图（训练集模型外推，'
             '实验集表面位移 100% 空=预测目标，无真值可对照）')
ax.legend()
fig.tight_layout()
fig.savefig(OUT / 'q3_fig_scatter.png', dpi=150)
plt.close(fig)
print('[Q3.3] 图已输出至 cwd：q3_fig_ccf.png / q3_fig_contrib.png / q3_fig_scatter.png')

Q3_table31 = [int(diag32['table31_main'][v]) for v in 'abcde']
Q3_common = int(diag32['table32_common_main_n'])
Q3_r2 = float(r2_main)
Q3_cr = float(partial_r2['a']); Q3_cp = float(partial_r2['b'])
Q3_cd = float(partial_r2['d']); Q3_cm = float(partial_r2['c'])
print(f"Q3: table31={Q3_table31} common={Q3_common} r2={Q3_r2:.4f} "
      f"contrib_rain={Q3_cr:.3f} contrib_pore={Q3_cp:.3f} "
      f"contrib_deep={Q3_cd:.3f} contrib_micro={Q3_cm:.3f}")

# =====================================================================
# Q4 附件4：分阶段增量外生回归 + 实验集预测（表4.1 五点）
# =====================================================================
P = PARAMS
F4 = DATA_DIR / '附件4：监测数据（训练集与实验集）-问题4.xlsx'
rng = np.random.default_rng(0)

tr4 = pd.read_excel(F4, sheet_name="训练集")
ex4 = pd.read_excel(F4, sheet_name="实验集")
y_tr = tr4["表面位移_mm"].values.astype(float)
t_tr = pd.to_datetime(tr4["时间"])
y_ex_true = ex4["表面位移_mm"].values.astype(float)   # 全 NaN（预测目标）
t_ex = pd.to_datetime(ex4["时间"])
stage_ex = ex4["阶段标签"].values.astype(int)

n_tr, n_ex = len(tr4), len(ex4)
assert np.all(np.isnan(y_ex_true)), "实验集表面位移应为空"

# 2. 训练集阶段识别（BinSeg + 三重判据）
bounds, stage_info = detect_stages(y_tr, P)
assert len(bounds) == 3
train_breaks = [b for a, b in bounds[:-1]]

stage_v = [stage_mean_velocity(y_tr, a, b) for a, b in bounds]

# 3. 特征与目标
X_tr, feat_names = make_features(tr4, P)          # (n_tr, 7)
rows = np.arange(1, n_tr)
dy = np.diff(y_tr)
X_inc = X_tr[1:]
stage_of_row = np.zeros(n_tr - 1, dtype=int)
for s, (a, b) in enumerate(bounds):
    mask = (rows >= max(a, 1)) & (rows < b)
    stage_of_row[mask] = s

# 4. 分阶段 OLS 模型（全样本拟合）
stage_models = {}
for s in range(3):
    a, b = bounds[s]
    m = (stage_of_row == s)
    coef, sigma, se, resid = ols_fit(X_inc[m], dy[m])
    std_beta = std_coefs(coef, X_inc[m], dy[m], feat_names)
    stage_models[s] = dict(
        stage=s, rows_range=[int(a), int(b)],
        n=int(m.sum()),
        coef=[float(c) for c in coef],
        se=[float(x) for x in se],
        std_beta=std_beta,
        sigma=float(sigma),
        mean_dy=float(dy[m].mean()),
        r2=float(metrics(dy[m], np.column_stack([np.ones(m.sum()), X_inc[m]]) @ coef)[2]),
    )

# 5. 前向验证（每阶段末 20% 作验证）
folds = stage_folds(bounds, P["cv_val_frac"], P["cv_min_val"])

def fit_incremental(X, y):
    return ols_fit(X, y)

def predict_incremental(coef, X):
    return np.column_stack([np.ones(len(X)), X]) @ coef

def fit_level_ar1(X_lag, X, y):
    A = np.column_stack([np.ones(len(y)), X_lag, X])
    coef, *_ = np.linalg.lstsq(A, y, rcond=None)
    resid = y - A @ coef
    dof = len(y) - A.shape[1]
    sigma = float(np.sqrt(np.maximum(resid @ resid, 0.0) / max(dof, 1)))
    return coef, sigma

def predict_level_ar1(coef, X_lag0, X):
    n = len(X)
    yhat = np.empty(n)
    yprev = X_lag0
    for i in range(n):
        yhat[i] = coef[0] + coef[1] * yprev + X[i] @ coef[2:]
        yprev = yhat[i]
    return yhat

fold_results = []
for s, (train_slice, val_slice) in enumerate(folds):
    a_tr, b_tr = train_slice
    a_va, b_va = val_slice
    trm = (rows >= max(a_tr, 1)) & (rows < b_tr)
    vam = (rows >= a_va) & (rows < b_va)
    X_t, y_t = X_inc[trm], dy[trm]
    X_v, y_v = X_inc[vam], dy[vam]

    coef_s, _, _, _ = ols_fit(X_t, y_t)
    p_s = predict_incremental(coef_s, X_v)
    rmse_s, mae_s, r2_s = metrics(y_v, p_s)

    allm = (rows >= 1) & (rows < b_tr)
    X_all, y_all = X_inc[allm], dy[allm]
    st_all = stage_of_row[allm]
    D = np.column_stack([(st_all == 1).astype(float), (st_all == 2).astype(float)])
    Xd = np.column_stack([X_all, D])
    coef_d, _, _, _ = ols_fit(Xd, y_all)
    Dv = np.column_stack([(stage_of_row[vam] == 1).astype(float),
                          (stage_of_row[vam] == 2).astype(float)])
    p_d = predict_incremental(coef_d, np.column_stack([X_v, Dv]))
    rmse_d, mae_d, r2_d = metrics(y_v, p_d)

    coef_u, _, _, _ = ols_fit(X_all, y_all)
    p_u = predict_incremental(coef_u, X_v)
    rmse_u, mae_u, r2_u = metrics(y_v, p_u)

    y_lag = y_tr[max(a_tr, 1) - 1: b_tr - 1]
    y_lvl_t = y_tr[max(a_tr, 1): b_tr]
    coef_ar, sigma_ar = fit_level_ar1(y_lag, X_t, y_lvl_t)
    y_lag0 = y_tr[a_va - 1]
    yhat_ar = predict_level_ar1(coef_ar, y_lag0, X_v)
    yhat_s_level = y_tr[a_va - 1] + np.cumsum(p_s)
    yhat_u_level = y_tr[a_va - 1] + np.cumsum(p_u)
    y_level_true = y_tr[a_va:b_va]
    rmse_lvl_s = float(np.sqrt(np.mean((yhat_s_level - y_level_true) ** 2)))
    rmse_lvl_ar = float(np.sqrt(np.mean((yhat_ar - y_level_true) ** 2)))
    rmse_lvl_u = float(np.sqrt(np.mean((yhat_u_level - y_level_true) ** 2)))
    y_fit = coef_ar[0] + coef_ar[1] * y_lag + X_t @ coef_ar[2:]
    r2_ar_insample = metrics(y_lvl_t, y_fit)[2]

    fold_results.append(dict(
        stage=s, train_range=[int(a_tr), int(b_tr)], val_range=[int(a_va), int(b_va)],
        n_train=int(trm.sum()), n_val=int(vam.sum()),
        staged=dict(rmse=rmse_s, mae=mae_s, r2=r2_s),
        unified_dummy=dict(rmse=rmse_d, mae=mae_d, r2=r2_d),
        unified_plain=dict(rmse=rmse_u, mae=mae_u, r2=r2_u),
        level_ar1=dict(rmse_lvl=rmse_lvl_ar, rmse_insample_r2=r2_ar_insample),
        level_staged=dict(rmse_lvl=rmse_lvl_s),
        level_unified=dict(rmse_lvl=rmse_lvl_u),
    ))

lvl_main = np.mean([f["level_staged"]["rmse_lvl"] for f in fold_results])
lvl_ar = np.mean([f["level_ar1"]["rmse_lvl"] for f in fold_results])
lvl_unif = np.mean([f["level_unified"]["rmse_lvl"] for f in fold_results])
inc_rmse_main = np.mean([f["staged"]["rmse"] for f in fold_results])
inc_rmse_unif = np.mean([f["unified_plain"]["rmse"] for f in fold_results])
inc_rmse_dummy = np.mean([f["unified_dummy"]["rmse"] for f in fold_results])

r2_inc_all = []
for s in range(3):
    m = stage_of_row == s
    r2_inc_all.append(stage_models[s]["r2"])
r2_inc_pooled = np.mean(r2_inc_all)
y_lag_full = y_tr[:-1]
coef_ar_full, _ = fit_level_ar1(y_lag_full, X_inc, y_tr[1:])
y_fit_full = coef_ar_full[0] + coef_ar_full[1] * y_lag_full + X_inc @ coef_ar_full[2:]
r2_ar_full = metrics(y_tr[1:], y_fit_full)[2]

# 6. 24h 超前多步预测检验
multi_step = []
for origin_frac in [0.40, 0.60, 0.80]:
    o = int(origin_frac * n_tr)
    H = 144
    if o + H >= n_tr:
        H = n_tr - o - 1
    trm = (rows >= 1) & (rows < o)
    vam = (rows >= o) & (rows < o + H)
    X_t, y_t = X_inc[trm], dy[trm]
    X_v, y_v = X_inc[vam], dy[vam]
    coefs_s = {}
    for s in range(3):
        a, b = bounds[s]
        ms = (rows >= max(a, 1)) & (rows < min(b, o))
        if ms.sum() >= 30:
            coefs_s[s], *_ = ols_fit(X_inc[ms], dy[ms])
        else:
            coefs_s[s] = None
    p_s = np.zeros(len(X_v))
    vrows = np.where(vam)[0]
    for i, r in enumerate(vrows):
        s = stage_of_row[r]
        if coefs_s[s] is not None:
            p_s[i] = coefs_s[s][0] + X_inc[r] @ coefs_s[s][1:]
        else:
            p_s[i] = 0.0
    y_lag_t = y_tr[0: o - 1]
    y_lvl_t = y_tr[1: o]
    coef_ar, _ = fit_level_ar1(y_lag_t, X_t, y_lvl_t)
    yhat_ar = predict_level_ar1(coef_ar, y_tr[o - 1], X_v)
    y_lvl_true = y_tr[o:o + H]
    yhat_s = y_tr[o - 1] + np.cumsum(p_s)
    multi_step.append(dict(
        origin=int(o), horizon=int(H),
        rmse_level_staged=float(np.sqrt(np.mean((yhat_s - y_lvl_true) ** 2))),
        rmse_level_ar1=float(np.sqrt(np.mean((yhat_ar - y_lvl_true) ** 2))),
        mae_level_staged=float(np.mean(np.abs(yhat_s - y_lvl_true))),
        mae_level_ar1=float(np.mean(np.abs(yhat_ar - y_lvl_true))),
    ))

# 7. 实验集预测（按给定阶段标签套对应阶段模型，增量累加恢复位移）
X_ex, _ = make_features(ex4, P)
pred_dy = np.zeros(n_ex)
pred_sigma = np.zeros(n_ex)
for t in range(n_ex):
    s = stage_ex[t] - 1
    m = stage_models[s]
    x = X_ex[t]
    pred_dy[t] = m["coef"][0] + x @ np.array(m["coef"][1:])
    pred_sigma[t] = m["sigma"]

yhat = np.zeros(n_ex)
for t in range(1, n_ex):
    yhat[t] = yhat[t - 1] + pred_dy[t]
cum_var = np.cumsum(pred_sigma ** 2)
z = 1.96
lo = yhat - z * np.sqrt(cum_var)
hi = yhat + z * np.sqrt(cum_var)

X_tr_min, X_tr_max = X_tr.min(axis=0), X_tr.max(axis=0)
X_ex_clip = np.clip(X_ex, X_tr_min, X_tr_max)
pred_dy_clip = np.zeros(n_ex)
for t in range(n_ex):
    s = stage_ex[t] - 1
    m = stage_models[s]
    x = X_ex_clip[t]
    pred_dy_clip[t] = m["coef"][0] + x @ np.array(m["coef"][1:])
yhat_clip = np.zeros(n_ex)
for t in range(1, n_ex):
    yhat_clip[t] = yhat_clip[t - 1] + pred_dy_clip[t]
clip_diff = float(yhat_clip[-1] - yhat[-1])

stage_bounds_ex = []
for s in [1, 2, 3]:
    idxs = np.where(stage_ex == s)[0]
    stage_bounds_ex.append([int(idxs[0]), int(idxs[-1]) + 1])

# 表 4.1 五点（时间→行号：t = 2025-05-01 16:40 + (行号-1)*10min）
base_time = pd.Timestamp("2025-05-01 16:40")
table41 = [
    ("2025-05-09 12:00", 1125),
    ("2025-05-27 08:00", 3693),
    ("2025-06-01 12:00", 4437),
    ("2025-06-03 22:00", 4785),
    ("2025-06-04 01:40", 4807),
]
t41 = []
for ts, row1 in table41:
    idx = row1 - 1
    assert t_ex[idx] == pd.Timestamp(ts), (ts, t_ex[idx])
    t41.append(dict(
        time=ts, row=int(row1), stage=int(stage_ex[idx]),
        pred_mm=float(yhat[idx]), lo95_mm=float(lo[idx]), hi95_mm=float(hi[idx]),
        pred_dy_mm=float(pred_dy[idx]),
    ))

# 跨年泛化：训练/实验特征分布偏移统计
dist_shift = {}
for col in ["孔隙水压力_kPa", "微震事件数", "降雨量_mm"]:
    a = tr4[col].values.astype(float)
    b = ex4[col].values.astype(float)
    dist_shift[col] = dict(train_mean=float(np.nanmean(a)), train_std=float(np.nanstd(a)),
                           exp_mean=float(np.nanmean(b)), exp_std=float(np.nanstd(b)),
                           mean_shift_sd=float((np.nanmean(b) - np.nanmean(a)) / np.nanstd(a)))
dist_shift["爆破"] = dict(train_n=int(tr4["爆破点距离_m"].notna().sum()),
                         exp_n=int(ex4["爆破点距离_m"].notna().sum()))

# Q4 图：训练分阶段拟合 + 实验集预测
fig, axes = plt.subplots(1, 2, figsize=(15, 5.2))
ax = axes[0]
ax.plot(t_tr, y_tr, lw=0.7, color="#555", label="训练集表面位移")
for s, (a, b) in enumerate(bounds):
    xs = t_tr[a:b - 1]
    ax.plot([t_tr[a], t_tr[b - 1]], [y_tr[a], y_tr[b - 1]], lw=2.2,
            color=["#1f77b4", "#ff7f0e", "#d62728"][s],
            label=f"阶段{s + 1} 均速 {stage_v[s]:.2f} mm/h")
for b_ in train_breaks:
    ax.axvline(t_tr.iloc[b_], color="k", ls="--", lw=1)
    ax.annotate(f"变点 {b_}\n{t_tr.iloc[b_]:%m-%d %H:%M}", xy=(t_tr.iloc[b_], y_tr[b_]),
                xytext=(t_tr.iloc[b_], y_tr[b_] + 90), fontsize=8, ha="center",
                arrowprops=dict(arrowstyle="->", lw=0.7))
ax.set_title("(a) 训练集(2023) 分阶段拟合与变点")
ax.set_xlabel("时间"); ax.set_ylabel("表面位移 (mm)")
ax.legend(fontsize=8, loc="upper left")
ax.grid(alpha=0.3)

ax = axes[1]
ax.plot(t_ex, yhat, lw=1.0, color="#1f77b4", label="预测表面位移（累计）")
ax.fill_between(t_ex, lo, hi, color="#1f77b4", alpha=0.18, label="95% 预测带")
for a, b in stage_bounds_ex:
    ax.axvline(t_ex.iloc[a], color="k", ls="--", lw=1)
    ax.annotate(f"阶段{stage_ex[a]}", xy=(t_ex.iloc[a], 0.05),
                xytext=(t_ex.iloc[a] + pd.Timedelta(minutes=30), 1.05),
                fontsize=9, ha="left", color="k")
for r in t41:
    ax.scatter([pd.Timestamp(r["time"])], [r["pred_mm"]], color="red", zorder=5, s=28)
    ax.annotate(f"{r['pred_mm']:.1f}\n{r['time'][5:]}", xy=(pd.Timestamp(r["time"]), r["pred_mm"]),
                xytext=(pd.Timestamp(r["time"]), r["pred_mm"] + 0.06 * (hi[-1] - lo[-1])),
                fontsize=8, ha="center", color="red")
ax.set_title("(b) 实验集(2025) 预测表面位移与表4.1五点")
ax.set_xlabel("时间"); ax.set_ylabel("预测位移（mm，相对实验起始）")
ax.legend(fontsize=8, loc="upper left")
ax.grid(alpha=0.3)
plt.tight_layout()
plt.savefig(OUT / "q4_fig_prediction.png", dpi=140)
plt.close(fig)

print("== Q4 摘要 ==")
print("训练阶段:", bounds, "速度(mm/h):", [f"{v:.4f}" for v in stage_v])
for s in range(3):
    m = stage_models[s]
    print(f"  阶段{s+1}: n={m['n']} 截距={m['coef'][0]:+.4f} sigma={m['sigma']:.4f} "
          f"R2(增量)={m['r2']:.4f} std_beta={ {k: round(v,3) for k,v in m['std_beta'].items()} }")
print("前向CV（增量RMSE mm/10min）: 分阶段=%.4f  统一哑变量=%.4f  统一无阶段=%.4f" %
      (inc_rmse_main, inc_rmse_dummy, inc_rmse_unif))
print("前向CV（水平空间RMSE mm）: 分阶段=%.3f  统一=%.3f  水平+AR=%.3f" %
      (lvl_main, lvl_unif, lvl_ar))
print("样本内R²: 增量(分阶段均值)=%.4f  水平+AR=%.6f" % (r2_inc_pooled, r2_ar_full))
print("24h 超前 RMSE(水平mm):", [(m["rmse_level_staged"], m["rmse_level_ar1"]) for m in multi_step])
print("表4.1:")
for r in t41:
    print("  %s 行%d 阶段%d 预测=%.3f [%.3f, %.3f]" %
          (r["time"], r["row"], r["stage"], r["pred_mm"], r["lo95_mm"], r["hi95_mm"]))
print("实验集最终预测: %.2f mm [%.2f, %.2f]；裁剪特征敏感性=%.2f mm" %
      (yhat[-1], lo[-1], hi[-1], clip_diff))
print("实验集预测增量 min=%.3f max=%.3f mean=%.3f mm/10min" %
      (pred_dy.min(), pred_dy.max(), pred_dy.mean()))
print("特征分布偏移(孔压 mean 差/训练std):", round(dist_shift["孔隙水压力_kPa"]["mean_shift_sd"], 2))
print('[Q4] 图已输出至 cwd：q4_fig_prediction.png')

Q4_table41 = [round(float(r['pred_mm']), 3) for r in t41]
Q4_rmse = float(inc_rmse_main)
Q4_level_rmse = float(lvl_main)
Q4_final = float(yhat[-1]); Q4_lo = float(lo[-1]); Q4_hi = float(hi[-1])
print(f"Q4: table41=[{','.join(f'{x:.3f}' for x in Q4_table41)}] rmse={Q4_rmse:.4f} "
      f"level_rmse={Q4_level_rmse:.4f} final={Q4_final:.3f} ci=[{Q4_lo:.3f},{Q4_hi:.3f}]")

# =====================================================================
# Q5 附件5：六组合选优 + 分阶段速度阈值预警 + Saito 剩余时间
# =====================================================================
F5 = DATA_DIR / '附件5：监测数据-问题5.xlsx'

df5 = pd.read_excel(F5)
y5 = df5["表面位移_mm"].values.astype(float)
t5 = pd.to_datetime(df5["时间"])
n5 = len(df5)

# 0. 阶段识别（同 Q4：BinSeg + 三重判据）
bounds5, stage_info5 = detect_stages(y5, P)
assert len(bounds5) == 3
stage_v5 = [stage_mean_velocity(y5, a, b) for a, b in bounds5]
stage_of_row5 = np.zeros(n5 - 1, dtype=int)
rows5 = np.arange(1, n5)
for s, (a, b) in enumerate(bounds5):
    mask = (rows5 >= max(a, 1)) & (rows5 < b)
    stage_of_row5[mask] = s
dy5 = np.diff(y5)
v5 = dy5 * 6.0                                  # 速度 mm/h（10min = 1/6h）

# 1. Q5.1 六组合：统一前向 CV 比 RMSE/MAE + 相对误差
def api_features(df, P):
    rain = df["降雨量_mm"].values.astype(float)
    n_ = len(rain)
    dec = P["api_decay"]
    M = P["api_max_steps"]
    w_api = dec ** np.arange(M)
    api = np.convolve(rain, w_api)[:n_]
    w24 = np.ones(P["rain24_steps"])
    rain24 = np.convolve(rain, w24)[:n_]
    return api, rain24

api5, rain245 = api_features(df5, P)

def build_X5(df, P, include):
    """include: 变量子集（rain/pore/micro/infil/blast_dist/blast_charge）。"""
    cols = {}
    if "rain" in include:
        cols["api"] = api5
        cols["rain24"] = rain245
    if "pore" in include:
        cols["pore"] = df["孔隙水压力_kPa"].values.astype(float)
    if "micro" in include:
        cols["micro"] = df["微震事件数"].values.astype(float)
    if "infil" in include:
        cols["infil"] = df["干湿入渗系数"].values.astype(float)
    if "blast_dist" in include or "blast_charge" in include:
        is_blast = df["爆破点距离_m"].notna().values.astype(float)
        cols["is_blast"] = is_blast
        if "blast_dist" in include:
            cols["blast_dist"] = np.nan_to_num(df["爆破点距离_m"].values.astype(float))
        if "blast_charge" in include:
            cols["blast_charge"] = np.nan_to_num(df["单段最大药量_kg"].values.astype(float))
    X = np.column_stack([cols[k] for k in cols])
    return X, list(cols.keys())

VARS5 = ["rain", "pore", "micro", "infil", "blast_dist", "blast_charge"]
VAR_CN5 = {"rain": "降雨量", "pore": "孔压", "micro": "微震",
           "infil": "干湿入渗", "blast_dist": "爆破距离", "blast_charge": "药量"}
combos = {"全6变量(参照)": set(VARS5)}
for vv in VARS5:
    combos[f"剔除{VAR_CN5[vv]}"] = set(VARS5) - {vv}

origins = [int(f * n5) for f in P["q5_cv_origins"]]
H = P["q5_cv_horizon"]

combo_results = {}
pooled = {}
for cname, include in combos.items():
    X5c, fnames = build_X5(df5, P, include)
    X_inc5 = X5c[1:]
    per_win = []
    lvl_pool_res = []
    lvl_pool_true = []
    for o in origins:
        trm = (rows5 >= 1) & (rows5 < o)
        vam = (rows5 >= o) & (rows5 < o + H)
        coef, *_ = ols_fit(X_inc5[trm], dy5[trm])
        p = np.column_stack([np.ones(vam.sum()), X_inc5[vam]]) @ coef
        rmse, mae, r2 = metrics(dy5[vam], p)
        y_lvl = y5[o - 1] + np.cumsum(p)
        y_true = y5[o:o + H]
        rmse_lvl = float(np.sqrt(np.mean((y_lvl - y_true) ** 2)))
        rel = rmse_lvl / np.mean(np.abs(y_true))
        per_win.append(dict(origin=int(o), rmse_inc=rmse, mae_inc=mae, r2_inc=r2,
                            rmse_lvl=rmse_lvl, rel_err=rel))
        lvl_pool_res.append(y_lvl - y_true)
        lvl_pool_true.append(y_true)
    res = np.concatenate(lvl_pool_res)
    tru = np.concatenate(lvl_pool_true)
    rmse_lvl_pool = float(np.sqrt(np.mean(res ** 2)))
    rel_pool = rmse_lvl_pool / np.mean(np.abs(tru))
    inc_res = []
    for o in origins:
        vam = (rows5 >= o) & (rows5 < o + H)
        trm = (rows5 >= 1) & (rows5 < o)
        coef, *_ = ols_fit(X_inc5[trm], dy5[trm])
        inc_res.append(dy5[vam] - (np.column_stack([np.ones(vam.sum()), X_inc5[vam]]) @ coef))
    inc_res = np.concatenate(inc_res)
    combo_results[cname] = dict(
        include=sorted(include), features=fnames,
        rmse_inc=float(np.sqrt(np.mean(inc_res ** 2))),
        mae_inc=float(np.mean(np.abs(inc_res))),
        rmse_lvl=rmse_lvl_pool, rel_err_lvl=rel_pool,
        windows=per_win,
    )
    pooled[cname] = dict(rmse_inc=combo_results[cname]["rmse_inc"],
                         rmse_lvl=combo_results[cname]["rmse_lvl"],
                         rel=combo_results[cname]["rel_err_lvl"])

# 最优组合（增量 RMSE 最小；水平 RMSE 作辅助）
best_key = min(combo_results, key=lambda k: combo_results[k]["rmse_inc"])

# ---- 干湿入渗×降雨 交互项检查（在全6变量组合上加 api*infil）----
interact_check = {}
Xb, fb = build_X5(df5, P, combos["全6变量(参照)"])
Xb_inc = Xb[1:]
Xint = np.column_stack([Xb_inc, api5[1:] * df5["干湿入渗系数"].values.astype(float)[1:]])
base_rmse = combo_results["全6变量(参照)"]["rmse_inc"]
coef_i, sig_i, se_i, _ = ols_fit(Xint, dy5)
inc_res_i = []
for o in origins:
    trm = (rows5 >= 1) & (rows5 < o)
    vam = (rows5 >= o) & (rows5 < o + H)
    c, *_ = ols_fit(Xint[trm], dy5[trm])
    inc_res_i.append(dy5[vam] - (np.column_stack([np.ones(vam.sum()), Xint[vam]]) @ c))
inc_res_i = np.concatenate(inc_res_i)
rmse_i = float(np.sqrt(np.mean(inc_res_i ** 2)))
interact_check = dict(
    coef=float(coef_i[-1]), se=float(se_i[-1]),
    rmse_base=base_rmse, rmse_with_interaction=rmse_i,
    delta_rmse=rmse_i - base_rmse,
    note="api(前期雨量)×干湿入渗系数 交互项（基于全6变量组合）；降雨 98% 为零，"
         "交互主要在降雨事件期非零",
)

# 2. Q5.2 分阶段速度阈值预警
spike_abs = P.get("spike_abs_mm10", 3.0)
spike_mask = np.abs(dy5) <= spike_abs
n_spikes = int((~spike_mask).sum())

v_eval = v5.copy()
for s, (a, b) in enumerate(bounds5):
    med = float(np.median(v5[a:b - 1]))
    m = ~spike_mask[a:b - 1]
    v_eval[a:b - 1][m] = med

def causal_mean(arr, win=6):
    out = np.full(len(arr), np.nan)
    cs = np.cumsum(np.concatenate([[0.0], arr]))
    for i in range(win - 1, len(arr)):
        out[i] = (cs[i + 1] - cs[i + 1 - win]) / win
    out[:win - 1] = np.nan
    return out

v6 = causal_mean(v_eval, 6)          # 1h 滑动平均速度（mm/h）
valid6 = ~np.isnan(v6)
v6_clean = v6[spike_mask & valid6]

st = {}
for s, (a, b) in enumerate(bounds5):
    vs_raw = v5[a:b - 1]
    m6 = valid6[a:b - 1]
    vs6 = v6[a:b - 1][m6]
    st[s] = dict(
        rows=[int(a), int(b)],
        mean=float(vs_raw.mean()), std=float(vs_raw.std()),
        p50=float(np.percentile(vs_raw, 50)),
        p90=float(np.percentile(vs_raw, 90)),
        p95=float(np.percentile(vs_raw, 95)),
        p99=float(np.percentile(vs_raw, 99)),
        max=float(vs_raw.max()),
        n_spikes=int((~spike_mask[a:b - 1]).sum()),
        v6_p90=float(np.percentile(vs6, 90)),
        v6_p95=float(np.percentile(vs6, 95)),
        v6_p99=float(np.percentile(vs6, 99)),
    )

w_levels = P["warn_levels"]
thr_stage = {}
for s in range(3):
    m6s = valid6 & (stage_of_row5 == s) & spike_mask
    vs = v6[m6s]
    thr_stage[s] = [float(np.percentile(vs, 100 * q)) for q in w_levels]
thr_global = [float(np.percentile(v6_clean, 100 * q)) for q in w_levels]

m6f = valid6 & (stage_of_row5 == 2) & spike_mask
D = float(np.percentile(v6[m6f], 100 * P["danger_q_fast"]))
w_ = P["warn_persist_steps"]
over_D = v6 >= D
danger = np.zeros(n5 - 1, dtype=bool)
run = 0
for i in range(n5 - 1):
    run = run + 1 if over_D[i] else 0
    danger[i] = run >= w_

def evaluate_warning(theta_by_row, w, H_steps, L_steps):
    """theta_by_row: 每步速度阈值数组；返回统计量 + 真报提前量。"""
    over = v6 > theta_by_row
    onset = np.zeros(n5 - 1, dtype=bool)
    if w == 1:
        onset = over
    else:
        for i in range(w - 1, n5 - 1):
            onset[i] = bool(over[i - w + 1:i + 1].all())
    tp = np.zeros(n5 - 1, dtype=bool)
    leads = []
    for i in np.where(onset)[0]:
        j = min(i + H_steps, n5 - 1)
        hit = danger[i:j]
        if hit.any():
            tp[i] = True
            leads.append(float(np.argmax(hit) * STEP_H))
    n_onset = int(onset.sum())
    n_tp = int((onset & tp).sum())
    n_fp = n_onset - n_tp
    covered = np.zeros(n5 - 1, dtype=bool)
    for i in np.where(onset)[0]:
        j = max(0, i - L_steps)
        covered[j:i + 1] = True
    n_danger = int(danger.sum())
    n_miss = int((danger & ~covered).sum())
    miss_rate = n_miss / n_danger if n_danger else 0.0
    hours = (n5 - 1) * STEP_H
    far_per_day = n_fp / (hours / 24.0)
    return dict(n_onset=n_onset, n_tp=n_tp, n_fp=n_fp, n_danger=n_danger,
                n_miss=n_miss, miss_rate=miss_rate, far_per_day=far_per_day,
                lead_time_h=float(np.median(leads)) if leads else np.nan)

w = P["warn_persist_steps"]
H_steps = int(P["warn_horizon_h"] / STEP_H)
L_steps = int(P["warn_lookback_h"] / STEP_H)

theta_row_stage = np.zeros(n5 - 1)
theta_row_global = np.zeros(n5 - 1)
for i in range(n5 - 1):
    s = stage_of_row5[i]
    theta_row_stage[i] = thr_stage[s][2]          # 报警级 P99（评估用）
    theta_row_global[i] = thr_global[2]
eval_stage = evaluate_warning(theta_row_stage, w, H_steps, L_steps)
eval_global = evaluate_warning(theta_row_global, w, H_steps, L_steps)

fs = np.linspace(0.50, 0.995, 40)
curve_stage = []
curve_global = []
for f in fs:
    theta_s = np.zeros(n5 - 1)
    for s in range(3):
        m6s = valid6 & (stage_of_row5 == s) & spike_mask
        q = float(np.percentile(v6[m6s], 100 * f))
        for i in range(n5 - 1):
            if stage_of_row5[i] == s:
                theta_s[i] = q
    e = evaluate_warning(theta_s, w, H_steps, L_steps)
    curve_stage.append(dict(f=float(f), miss_rate=e["miss_rate"],
                            far_per_day=e["far_per_day"], n_fp=e["n_fp"]))
    qg = float(np.percentile(v6_clean, 100 * f))
    e2 = evaluate_warning(np.full(n5 - 1, qg), w, H_steps, L_steps)
    curve_global.append(dict(f=float(f), miss_rate=e2["miss_rate"],
                             far_per_day=e2["far_per_day"], n_fp=e2["n_fp"]))

def op_cost(c):
    return P["cost_miss"] * c["miss_rate"] + P["cost_fp"] * (c["far_per_day"] / 24.0)
best_op = min(curve_stage, key=op_cost)
best_op_g = min(curve_global, key=op_cost)

# ---- Saito 剩余时间（速度倒数幂律：ln T_rem = a + b ln v6，快速段标定）----
a_f, b_f = bounds5[2]
fast_idx = np.where((stage_of_row5 == 2) & spike_mask & valid6)[0]
vs_fast = v6[fast_idx]
t_rem_h = ((b_f - 1 - fast_idx) * STEP_H).astype(float)
msk = (vs_fast > 0.5) & (t_rem_h > 0.5)
A5 = np.column_stack([np.ones(msk.sum()), np.log(vs_fast[msk])])
c_saito, *_ = np.linalg.lstsq(A5, np.log(t_rem_h[msk]), rcond=None)
a_saito, b_saito = float(c_saito[0]), float(c_saito[1])
resid5 = np.log(t_rem_h[msk]) - A5 @ c_saito
rmse_saito = float(np.sqrt(np.mean(resid5 ** 2)))

def saito_trem(v_mmh):
    """剩余时间（h）：T = exp(a) * v^b。"""
    return float(np.exp(a_saito) * v_mmh ** b_saito)

saito_examples = {}
lvl_names = [f"注意P{int(w_levels[0]*100)}", f"预警P{int(w_levels[1]*100)}",
             f"报警P{int(w_levels[2]*100)}"]
for s in [2]:
    thr = thr_stage[s]
    saito_examples[f"阶段{s + 1}"] = {
        lvl_names[i]: dict(thr=thr[i], t_rem_h=saito_trem(thr[i])) for i in range(3)
    }
a2, b2 = bounds5[1]
th_al_accel = thr_stage[1][2]
over_acc = (v6 > th_al_accel) & (stage_of_row5 == 1) & valid6
first_acc_onset = None
for i in range(2, n5 - 1):
    if stage_of_row5[i] == 1 and over_acc[i - 2] and over_acc[i - 1] and over_acc[i]:
        first_acc_onset = int(i)
        break
lead_acc_to_fast = (bounds5[2][0] - 1 - first_acc_onset) * STEP_H if first_acc_onset else np.nan
over_fast_al = (v6 > thr_stage[2][1]) & (stage_of_row5 == 2) & valid6
first_fast_onset = None
for i in range(2, n5 - 1):
    if stage_of_row5[i] == 2 and over_fast_al[i - 2] and over_fast_al[i - 1] and over_fast_al[i]:
        first_fast_onset = int(i)
        break
lead_fast_to_end = ((n5 - 2) - first_fast_onset) * STEP_H if first_fast_onset else np.nan

lvl_stats = {}
for li, lvl in enumerate(["注意", "预警", "报警"]):
    th = np.zeros(n5 - 1)
    for s in range(3):
        for i in range(n5 - 1):
            if stage_of_row5[i] == s:
                th[i] = thr_stage[s][li]
    e = evaluate_warning(th, w, H_steps, L_steps)
    lvl_stats[lvl] = dict(thresholds=[round(thr_stage[s][li], 3) for s in range(3)],
                          n_onset=e["n_onset"], n_tp=e["n_tp"], n_fp=e["n_fp"],
                          miss_rate=e["miss_rate"], far_per_day=e["far_per_day"],
                          lead_time_h=e["lead_time_h"])

# Q5 图 1：六组合误差对比
keys = [k for k in combos if k != "全6变量(参照)"] + ["全6变量(参照)"]
rmse_i = [combo_results[k]["rmse_inc"] for k in keys]
mae_i = [combo_results[k]["mae_inc"] for k in keys]
rmse_l = [combo_results[k]["rmse_lvl"] for k in keys]
xpos = np.arange(len(keys))
fig, ax1 = plt.subplots(figsize=(11, 5))
b1 = ax1.bar(xpos - 0.18, rmse_i, 0.36, label="增量 RMSE (mm/10min)", color="#4c72b0")
b2 = ax1.bar(xpos + 0.18, mae_i, 0.36, label="增量 MAE (mm/10min)", color="#9ecae1")
ax1.set_xticks(xpos); ax1.set_xticklabels(keys, rotation=20, fontsize=9)
ax1.set_ylabel("增量误差 (mm/10min)")
ax1.set_title("Q5.1 六种 5 变量组合 + 全变量参照（统一前向 CV）")
ax2 = ax1.twinx()
ax2.plot(xpos, rmse_l, "o--", color="#c44e52", label="水平空间 RMSE (mm)")
ax2.set_ylabel("水平空间 RMSE (mm)")
for i, k in enumerate(keys):
    ax1.annotate(f"{rmse_i[i]:.4f}", (xpos[i] - 0.18, rmse_i[i]), ha="center",
                 fontsize=8, xytext=(0, 3), textcoords="offset points")
best_i = keys.index(best_key)
ax1.axvline(xpos[best_i], color="k", ls=":", lw=1)
ax1.annotate("最优", (xpos[best_i], max(rmse_i) * 1.02), ha="center", color="k", fontsize=11)
h1, l1 = ax1.get_legend_handles_labels()
h2, l2 = ax2.get_legend_handles_labels()
ax1.legend(h1 + h2, l1 + l2, fontsize=8, loc="upper right")
plt.tight_layout()
plt.savefig(OUT / "q5_fig_combo.png", dpi=140)
plt.close(fig)

# Q5 图 2：分阶段速度 + 三级阈值
fig, ax = plt.subplots(figsize=(14, 5))
tt = t5.iloc[1:]
ax.plot(tt, v5, lw=0.3, color="#bbbbbb", alpha=0.6, label="10min 瞬时速度")
ax.plot(tt, v6, lw=0.9, color="#333333", alpha=0.85, label="1h 滑动平均速度 v6（预警指标）")
colors5 = ["#1f77b4", "#ff7f0e", "#d62728"]
for s, (a, b) in enumerate(bounds5):
    ax.axvspan(t5.iloc[a], t5.iloc[b - 1], color=colors5[s], alpha=0.08)
    ax.axvline(t5.iloc[a], color=colors5[s], ls="--", lw=1)
    ax.annotate(f"阶段{s + 1}\n均值 {stage_v5[s]:.2f} mm/h", xy=(t5.iloc[(a + b) // 2], 1.02),
                xytext=(t5.iloc[(a + b) // 2], 24), ha="center", fontsize=9, color=colors5[s])
    for li, lvl in enumerate(["注意", "预警", "报警"]):
        ax.axhline(thr_stage[s][li], color=colors5[s], ls=":", lw=1.0, alpha=0.6)
        ax.annotate(f"{lvl} {thr_stage[s][li]:.1f}", xy=(t5.iloc[b - 1], thr_stage[s][li]),
                    fontsize=7, color=colors5[s], ha="right", va="bottom")
ax.axhline(D, color="k", ls="-", lw=1.2, label=f"危险事件线 D={D:.1f} mm/h（快速段 v6 P95）")
ax.set_yscale("symlog", linthresh=1.0)
ax.set_ylim(-1, 60)
ax.set_title("Q5.2 分阶段速度与数据驱动阈值（注意/预警/报警 = v6 P90/P95/P99）")
ax.set_xlabel("时间"); ax.set_ylabel("速度 (mm/h, symlog)")
ax.legend(fontsize=8, loc="upper left")
plt.tight_layout()
plt.savefig(OUT / "q5_fig_threshold.png", dpi=140)
plt.close(fig)

# Q5 图 3：误报-漏报权衡曲线
fig, ax = plt.subplots(figsize=(8, 6))
cs = np.array([c["far_per_day"] for c in curve_stage])
ms = np.array([c["miss_rate"] for c in curve_stage])
cg = np.array([c["far_per_day"] for c in curve_global])
mg = np.array([c["miss_rate"] for c in curve_global])
ax.plot(cs, ms, "o-", lw=1.5, color="#1f77b4", label="阶段化阈值（主）")
ax.plot(cg, mg, "s--", lw=1.5, color="#d62728", label="全局阈值（备选）")
ax.scatter([best_op["far_per_day"]], [best_op["miss_rate"]], marker="*", s=220,
           color="#1f77b4", zorder=5, label="阶段化操作点")
ax.scatter([best_op_g["far_per_day"]], [best_op_g["miss_rate"]], marker="*", s=160,
           color="#d62728", zorder=5, label="全局操作点")
ax.annotate(f"阶段化: 漏报{best_op['miss_rate']:.2%}, 误报{best_op['far_per_day']:.2f}/天",
            (best_op["far_per_day"], best_op["miss_rate"]), xytext=(6, 0.35),
            fontsize=9, arrowprops=dict(arrowstyle="->", lw=0.7))
ax.annotate(f"全局: 漏报{best_op_g['miss_rate']:.2%}, 误报{best_op_g['far_per_day']:.2f}/天",
            (best_op_g["far_per_day"], best_op_g["miss_rate"]), xytext=(1.5, 0.75),
            fontsize=9, arrowprops=dict(arrowstyle="->", lw=0.7))
ax.set_xlabel("误报率（报警/天）"); ax.set_ylabel("漏报率（危险事件未预警占比）")
ax.set_title("Q5.2 误报-漏报权衡曲线（f∈[0.50,0.995]，持续性 w=3 步）")
ax.legend(fontsize=9)
ax.grid(alpha=0.3)
plt.tight_layout()
plt.savefig(OUT / "q5_fig_tradeoff.png", dpi=140)
plt.close(fig)

print("== Q5 摘要 ==")
print("阶段:", bounds5, "均速(mm/h):", [f"{x:.3f}" for x in stage_v5])
print("六组合前向 CV（增量RMSE / 水平RMSE / 相对误差）:")
for k in keys:
    r = combo_results[k]
    print("  %-16s rmse_inc=%.4f mae=%.4f rmse_lvl=%.3f rel=%.2f%%" %
          (k, r["rmse_inc"], r["mae_inc"], r["rmse_lvl"], 100 * r["rel_err_lvl"]))
print("最优组合:", best_key, "rmse_inc=%.4f rmse_lvl=%.3f rel=%.2f%%" %
      (combo_results[best_key]["rmse_inc"], combo_results[best_key]["rmse_lvl"],
       100 * combo_results[best_key]["rel_err_lvl"]))
print("交互项检查:", interact_check)
print("分阶段阈值(注意/预警/报警 mm/h, 清洗后):", {str(s): [round(x, 2) for x in thr_stage[s]] for s in range(3)})
print("全局阈值:", [round(x, 2) for x in thr_global], "危险线 D=%.2f" % D)
print("跳变对识别: 共剔除/中性化 %d 步" % n_spikes)
print("阶段化评估: 报警数=%d 真报=%d 误报=%d 漏报率=%.3f 误报率=%.2f/天 提前量中位=%sh" %
      (eval_stage["n_onset"], eval_stage["n_tp"], eval_stage["n_fp"],
       eval_stage["miss_rate"], eval_stage["far_per_day"], _fs(eval_stage["lead_time_h"], '.1f')))
print("全局评估:   报警数=%d 真报=%d 误报=%d 漏报率=%.3f 误报率=%.2f/天" %
      (eval_global["n_onset"], eval_global["n_tp"], eval_global["n_fp"],
       eval_global["miss_rate"], eval_global["far_per_day"]))
print("操作点(阶段化): f=%.3f 漏报=%.3f 误报=%.2f/天" %
      (best_op["f"], best_op["miss_rate"], best_op["far_per_day"]))
print("Saito: a=%.3f b=%.3f (T_rem=exp(a)*v^b, 小时, 对数RMSE=%.3f, 标定范围 v6∈[%.1f,%.1f])" %
      (a_saito, b_saito, rmse_saito, vs_fast[msk].min(), vs_fast[msk].max()))
for li, lvl in enumerate(["注意", "预警", "报警"]):
    ex = saito_examples["阶段3"][lvl_names[li]]
    print("  快速段 %s: 阈值=%.2f mm/h -> 剩余约 %.1f h" % (lvl, ex["thr"], ex["t_rem_h"]))
print("提前量: 加速段首次报警(%.2f mm/h)→快速段起始 = %s h；快速段首次预警→数据末端 = %s h" %
      (th_al_accel, _fs(lead_acc_to_fast, '.1f'), _fs(lead_fast_to_end, '.1f')))
print("三级预警触发统计:")
for lvl in ["注意", "预警", "报警"]:
    e = lvl_stats[lvl]
    print("  %s: 触发=%d 真报=%d 误报=%d 漏报率=%.3f 误报=%.2f/天 提前量中位=%sh" %
          (lvl, e["n_onset"], e["n_tp"], e["n_fp"], e["miss_rate"],
           e["far_per_day"], _fs(e["lead_time_h"], '.1f')))
print('[Q5] 图已输出至 cwd：q5_fig_combo.png / q5_fig_threshold.png / q5_fig_tradeoff.png')

Q5_best = best_key
Q5_rmse = float(combo_results[best_key]["rmse_inc"])
Q5_rel = float(100 * combo_results[best_key]["rel_err_lvl"])
Q5_thr = [[round(float(x), 2) for x in thr_stage[s]] for s in range(3)]
print(f"Q5: best={Q5_best} rmse={Q5_rmse:.4f} rel_err={Q5_rel:.2f} "
      f"thresholds_slow={Q5_thr[0]} thresholds_accel={Q5_thr[1]} thresholds_fast={Q5_thr[2]}")

# =====================================================================
# 末尾一行 RESULT（7 个纯数值指标，f-string 变量计算值）
# =====================================================================
print(f"RESULT: baseline=ours q1_gain={Q1_gain:.4f} q1_rmse={Q1_rmse:.4f} "
      f"q2_node1={Q2_node1} q2_node2={Q2_node2} q3_common={Q3_common} "
      f"q4_rmse={Q4_rmse:.4f} q5_rmse={Q5_rmse:.4f}")
