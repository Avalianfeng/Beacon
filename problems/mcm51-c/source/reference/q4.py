# -*- coding: utf-8 -*-
r"""
q4.py —— Q4 分阶段增量外生回归 + 实验集预测（附件4）
=====================================================================
由 _entry.py 通过 exec 执行（共享命名空间；common.py 已先执行，DATA_DIR / OUT /
PARAMS / make_features / ols_fit / metrics / std_coefs / detect_stages /
stage_mean_velocity / stage_folds 及 np/pd/plt 等已就绪）。数值逻辑逐字保留自
原单文件 reference_solver.py 的 Q4 段；本文件顶层即执行 Q4 逻辑并打印 `Q4:` 明细行，
图片 savefig 到 Path.cwd()。RESULT 统一由 _entry.py 末尾打印，本文件不打印。
"""
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

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
