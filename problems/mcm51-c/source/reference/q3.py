# -*- coding: utf-8 -*-
r"""
q3.py —— Q3 去噪+补齐+异常+关联（附件3，三步内存传递）
=====================================================================
由 _entry.py 通过 exec 执行（共享命名空间；common.py 已先执行，DATA_DIR / OUT
及 np/pd/plt 等已就绪）。数值逻辑逐字保留自原单文件 reference_solver.py 的
Q3 段（Q3.1 去噪补齐 → Q3.2 异常检测 → Q3.3 关联贡献，内存 DataFrame/dict 传递）；
本文件顶层即执行 Q3 逻辑并打印 `Q3:` 明细行，图片 savefig 到 Path.cwd()。
RESULT 统一由 _entry.py 末尾打印，本文件不打印。
"""
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from scipy.interpolate import PchipInterpolator
from scipy.stats import pearsonr

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
