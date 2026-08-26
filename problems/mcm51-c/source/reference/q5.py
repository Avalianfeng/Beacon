# -*- coding: utf-8 -*-
r"""
q5.py —— Q5 六组合选优 + 分阶段速度阈值预警（附件5）
=====================================================================
由 _entry.py 通过 exec 执行（共享命名空间；common.py 已先执行，DATA_DIR / OUT /
PARAMS / ols_fit / metrics / detect_stages / stage_mean_velocity / _fs / STEP_H
及 np/pd/plt 等已就绪）。数值逻辑逐字保留自原单文件 reference_solver.py 的
Q5 段；本文件顶层即执行 Q5 逻辑并打印 `Q5:` 明细行，图片 savefig 到 Path.cwd()。
RESULT 统一由 _entry.py 末尾打印，本文件不打印。
"""
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

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
