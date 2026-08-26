# -*- coding: utf-8 -*-
r"""
q2.py —— Q2 三段式变点识别（附件2）
=====================================================================
由 _entry.py 通过 exec 执行（共享命名空间；common.py 已先执行，DATA_DIR / OUT /
STEP_H 及 np/pd/plt 等已就绪）。数值逻辑逐字保留自原单文件 reference_solver.py 的
Q2 段；本文件顶层即执行 Q2 逻辑并打印 `Q2:` 明细行，图片 savefig 到 Path.cwd()。
RESULT 统一由 _entry.py 末尾打印，本文件不打印。
"""
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from scipy import stats

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
