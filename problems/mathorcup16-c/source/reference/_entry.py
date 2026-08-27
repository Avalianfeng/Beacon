# -*- coding: utf-8 -*-
import matplotlib

matplotlib.use("Agg")
import os
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from pathlib import Path as _P

_f = globals().get("__file__")
if _f is not None:
    REF_DIR = Path(_f).resolve().parent
else:
    _dd = globals().get("data_dir")
    REF_DIR = Path(_dd) / "reference" if _dd is not None else Path.cwd()

exec((REF_DIR / "common.py").read_text(encoding="utf-8"), globals())

DATA_DIR = resolve_data_dir()
OUT = Path.cwd()
df = load_frame(DATA_DIR)

feat_cols = [src for _name, src in FEAT_MAP]
X_raw = df[feat_cols].to_numpy(dtype=float)
y_phlegm = df[COL_PHLEGM].to_numpy(dtype=float)
y_lip = df[COL_Y].to_numpy(dtype=float)
Xz = zscore(X_raw)
yz = (y_phlegm - y_phlegm.mean()) / (y_phlegm.std() + 1e-12)
phlegm_coef = np.linalg.lstsq(Xz, yz, rcond=None)[0]
resid = yz - Xz @ phlegm_coef
sst = float(np.sum((yz - yz.mean()) ** 2))
q1_r2 = 1.0 - float(np.sum(resid ** 2)) / max(sst, 1e-12)

# nine constitution contribution: dummy vs 平和质 (label 1)
lab = df[COL_LABEL].to_numpy(dtype=int)
dummies = []
or_labels = []
for k in range(2, 10):
    dummies.append((lab == k).astype(float))
    or_labels.append(k)
Xd = np.column_stack([np.ones(len(df))] + dummies)
w_lab = fit_logit(Xd, y_lip)
# OR relative to 平和 = exp(coef)
const_or = np.exp(w_lab[1:])

# Q2 logistic: features = zscored blood/activity + 痰湿积分 + 体质标签 (NOT 高血脂)
X2 = np.column_stack([np.ones(len(df)), Xz, zscore(y_phlegm.reshape(-1, 1)), zscore(lab.reshape(-1, 1).astype(float))])
w2 = fit_logit(X2, y_lip)
prob = sigmoid(X2 @ w2)
q2_auc = float(auc_score(y_lip, prob))
# tertile cuts on predicted probability
c1, c2 = np.quantile(prob, [1.0 / 3.0, 2.0 / 3.0])
tier = np.ones(len(df), dtype=int)
tier[prob >= c1] = 2
tier[prob >= c2] = 3
n_low = int((tier == 1).sum())
n_mid = int((tier == 2).sum())
n_high = int((tier == 3).sum())

# Q3: label==5
sub = df[df[COL_LABEL] == 5].copy()
n_phlegm = int(len(sub))
cases = {}
for sid in (1, 2, 3):
    row = df[df[COL_ID] == sid].iloc[0]
    s0 = int(round(float(row[COL_PHLEGM])))
    kmax = max_intensity(int(row[COL_AGE]), float(row[COL_ACT]))
    k, f, cost, s6, traj = best_policy(s0, kmax)
    cases[sid] = (k, f, cost, s6, traj, kmax)

mismatch = int((df[COL_LABEL].to_numpy() != (df[
    ["平和质", "气虚质", "阳虚质", "阴虚质", "痰湿质", "湿热质", "血瘀质", "气郁质", "特禀质"]
].to_numpy().argmax(axis=1) + 1)).sum())

# figures
names = ["TC", "TG", "LDL-C", "HDL-C", "glucose", "UA", "BMI", "ADL", "IADL", "activity"]
fig, ax = plt.subplots(figsize=(8, 4))
ax.barh(names, phlegm_coef)
ax.axvline(0, color="k", lw=0.6)
ax.set_title("Q1 standardized coef (phlegm score)")
fig.tight_layout()
fig.savefig(OUT / "fig_q1_phlegm_coef.png", dpi=120)
plt.close(fig)

fig, ax = plt.subplots(figsize=(5, 4))
ax.bar(["low", "mid", "high"], [n_low, n_mid, n_high])
ax.set_title(f"Q2 tiers (cuts {c1:.3f}/{c2:.3f})")
fig.tight_layout()
fig.savefig(OUT / "fig_q2_tiers.png", dpi=120)
plt.close(fig)

fig, ax = plt.subplots(figsize=(6, 4))
for sid, (_k, _f, _c, _s6, traj, _km) in cases.items():
    ax.plot(range(7), traj, marker="o", label=f"ID{sid}")
ax.set_xlabel("month")
ax.set_ylabel("phlegm score")
ax.legend()
ax.set_title("Q3 ID1/2/3 phlegm trajectory")
fig.tight_layout()
fig.savefig(OUT / "fig_q3_traj.png", dpi=120)
plt.close(fig)

phlegm_list = ",".join(f"{v:.6f}" for v in phlegm_coef)
print(
    f"Q1: phlegm_coef=[{phlegm_list}] r2={q1_r2:.6f} mismatch={mismatch} "
    f"or_qixu={const_or[0]:.4f} or_tanshi={const_or[3]:.4f}"
)
print(
    f"Q2: tier_n=[{n_low},{n_mid},{n_high}] auc={q2_auc:.6f} cut1={c1:.6f} cut2={c2:.6f}"
)
flat = []
for sid in (1, 2, 3):
    k, f, cost, s6, _traj, _km = cases[sid]
    flat.extend([k, f, cost, s6])
flat_s = ",".join(str(int(v) if float(v).is_integer() else v) for v in flat)
print(
    f"Q3: case_flat=[{flat_s}] n_phlegm={n_phlegm} "
    f"id1_kmax={cases[1][5]} id2_kmax={cases[2][5]} id3_kmax={cases[3][5]}"
)
print(
    f"RESULT: baseline=ours q1_r2={q1_r2:.6f} q2_auc={q2_auc:.6f} "
    f"q3_s1={cases[1][3]} q3_s2={cases[2][3]} q3_s3={cases[3][3]} "
    f"n_phlegm={n_phlegm} mismatch={mismatch} n_high={n_high}"
)
