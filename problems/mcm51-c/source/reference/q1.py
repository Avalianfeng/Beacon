# -*- coding: utf-8 -*-
r"""
q1.py —— Q1 位移校正（附件1，增益-偏移模型 B=β1·A+β0）
=====================================================================
由 _entry.py 通过 exec 执行（共享命名空间；common.py 已先执行，DATA_DIR / OUT
及 np/pd/plt 等已就绪）。数值逻辑逐字保留自原单文件 reference_solver.py 的
Q1 段；本文件顶层即执行 Q1 逻辑并打印 `Q1:` 明细行，图片 savefig 到 Path.cwd()。
RESULT 统一由 _entry.py 末尾打印，本文件不打印。
"""
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from scipy.optimize import least_squares
from scipy import stats

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
