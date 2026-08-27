# -*- coding: utf-8 -*-
"""Load 附件1 and shared helpers (numpy/scipy only)."""
from pathlib import Path

import numpy as np
import pandas as pd

XLSX_NAME = "附件1：样例数据.xlsx"

COL_PHLEGM = "痰湿质"
COL_LABEL = "体质标签"
COL_Y = "高血脂症二分类标签"
COL_ACT = "活动量表总分（ADL总分+IADL总分）"
COL_AGE = "年龄组"
COL_ID = "样本ID"

FEAT_MAP = [
    ("TC", "TC（总胆固醇）"),
    ("TG", "TG（甘油三酯）"),
    ("LDL_C", "LDL-C（低密度脂蛋白）"),
    ("HDL_C", "HDL-C（高密度脂蛋白）"),
    ("血糖", "空腹血糖"),
    ("血尿酸", "血尿酸"),
    ("BMI", "BMI"),
    ("ADL总分", "ADL总分"),
    ("IADL总分", "IADL总分"),
    ("活动量表总分", COL_ACT),
]


def resolve_data_dir():
    if globals().get("data_dir") is not None:
        return Path(globals().get("data_dir"))
    f = globals().get("__file__")
    if f is not None:
        return Path(f).resolve().parent.parent
    return Path.cwd()


def load_frame(data_dir: Path) -> pd.DataFrame:
    path = data_dir / XLSX_NAME
    df = pd.read_excel(path)
    if len(df) != 1000:
        raise RuntimeError(f"expected 1000 rows, got {len(df)}")
    return df


def zscore(X: np.ndarray) -> np.ndarray:
    mu = X.mean(axis=0)
    sd = X.std(axis=0)
    sd = np.where(sd < 1e-12, 1.0, sd)
    return (X - mu) / sd


def sigmoid(z: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(z, -30.0, 30.0)))


def fit_logit(X: np.ndarray, y: np.ndarray, l2: float = 1e-2, steps: int = 80) -> np.ndarray:
    """Newton logistic; X already includes intercept."""
    w = np.zeros(X.shape[1], dtype=float)
    for _ in range(steps):
        p = sigmoid(X @ w)
        wgt = p * (1.0 - p) + 1e-6
        hess = X.T @ (wgt[:, None] * X) + l2 * np.eye(X.shape[1])
        grad = X.T @ (p - y) + l2 * w
        try:
            delta = np.linalg.solve(hess, grad)
        except np.linalg.LinAlgError:
            delta = np.linalg.lstsq(hess, grad, rcond=None)[0]
        w = w - delta
        if float(np.max(np.abs(delta))) < 1e-8:
            break
    return w


def auc_score(y: np.ndarray, s: np.ndarray) -> float:
    y = y.astype(int)
    pos = s[y == 1]
    neg = s[y == 0]
    if len(pos) == 0 or len(neg) == 0:
        return 0.5
    # Mann–Whitney
    order = np.argsort(s)
    ranks = np.empty_like(order, dtype=float)
    ranks[order] = np.arange(1, len(s) + 1)
    sum_pos = float(ranks[y == 1].sum())
    u = sum_pos - len(pos) * (len(pos) + 1) / 2.0
    return u / (len(pos) * len(neg))


def max_intensity(age_group: int, activity: float) -> int:
    if age_group <= 2:
        age_max = 3
    elif age_group <= 4:
        age_max = 2
    else:
        age_max = 1
    if activity < 40:
        act_max = 1
    elif activity < 60:
        act_max = 2
    else:
        act_max = 3
    return min(age_max, act_max)


def tcm_grade(s: int) -> int:
    if s <= 58:
        return 1
    if s <= 61:
        return 2
    return 3


TCM_FEE = {1: 30, 2: 80, 3: 130}
ACT_FEE = {1: 3, 2: 5, 3: 8}


def month_delta(k: int, f: int) -> float:
    if f < 5:
        return 0.0
    return 0.03 * (k - 1) + 0.01 * max(0, f - 5)


def simulate_policy(s0: int, k: int, f: int) -> tuple[int, int, list[int]]:
    s = int(s0)
    cost = 0
    traj = [s]
    for _ in range(6):
        cost += TCM_FEE[tcm_grade(s)] + ACT_FEE[k] * f * 4
        dlt = month_delta(k, f)
        s = int(round(s * (1.0 - dlt)))
        s = max(0, s)
        traj.append(s)
    return s, cost, traj


def best_policy(s0: int, kmax: int) -> tuple[int, int, int, int, list[int]]:
    """Min final S, then min cost, then min k then min f. Feasible cost<=2000."""
    best = None
    for k in range(1, kmax + 1):
        for f in range(1, 11):
            s6, cost, traj = simulate_policy(s0, k, f)
            if cost > 2000:
                continue
            key = (s6, cost, k, f)
            if best is None or key < best[0]:
                best = (key, traj)
    if best is None:
        # fallback: cheapest legal
        k, f = 1, 1
        s6, cost, traj = simulate_policy(s0, k, f)
        return k, f, cost, s6, traj
    (_s6, cost, k, f), traj = best
    return k, f, cost, _s6, traj
