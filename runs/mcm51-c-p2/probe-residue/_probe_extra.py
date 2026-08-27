# -*- coding: utf-8 -*-
"""补充精确数字：阶段边界、分段速度、负跳变、D首末段。只读。"""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd

OUT = []
def P(*a): OUT.append(" ".join(str(x) for x in a))

# ---- 附件4 实验集 阶段边界 ----
f4 = r"E:\git_clone\Beacon\problems\mcm51-c\source\附件4：监测数据（训练集与实验集）-问题4.xlsx"
df = pd.read_excel(f4, sheet_name="实验集")
t = pd.to_datetime(df["时间"])
lbl = df["阶段标签"]
for v in [1, 2, 3]:
    idx = np.where(lbl == v)[0]
    P(f"[附件4实验集 阶段{v}] 行数={len(idx)} 起={t.iloc[idx[0]]} 止={t.iloc[idx[-1]]}")
P(f"[附件4实验集 阶段切换] 1->2 在 {t.iloc[2959]} 之后; 2->3 在 {t.iloc[4489]} 之后 (按索引)")

# ---- 附件2 分段 ----
f2 = r"E:\git_clone\Beacon\problems\mcm51-c\source\附件2：位移时序数据-问题2.xlsx"
d2 = pd.read_excel(f2)
D = pd.to_numeric(d2["表面位移_mm"], errors="coerce")
num = d2["编号"]
v = D.diff()
P("=" * 60)
P("[附件2 速度分位数 mm/10min]")
for q in [0.05, 0.25, 0.5, 0.75, 0.95, 0.99]:
    P(f"  q{q:.2f} = {v.quantile(q):.4f}")
P("[附件2 负跳变(绝对值最大前8)]:")
for idx, vv in v.abs().sort_values(ascending=False).head(8).items():
    P(f"  idx={idx} 编号={num.loc[idx]} Δ={v.loc[idx]:.4f} mm/10min 位移={D.loc[idx]:.6g}")
# 三个候选窗口速度
wins = [("编号1-7900", 0, 7900), ("编号7901-9500", 7900, 9500), ("编号9501-10000", 9500, 10000)]
P("[附件2 窗口速度统计]")
for name, a, b in wins:
    seg = v.iloc[a:b]
    dseg = D.iloc[a:b]
    P(f"  {name}: 点数={len(seg)} 均速={seg.mean():.4f} mm/10min 位移起={dseg.iloc[0]:.4f} 止={dseg.iloc[-1]:.4f} "
      f"位移增量={dseg.iloc[-1]-dseg.iloc[0]:.4f}")
P("[附件2 累计位移分位(更细)]")
D0 = D - D.iloc[0]
tot = D0.iloc[-1]
for q in [0.05, 0.2, 0.33, 0.5, 0.66, 0.8, 0.95]:
    idxq = (D0 / tot - q).abs().idxmin()
    P(f"  {int(q*100)}%位移: idx={idxq} 编号={num.loc[idxq]} 位移={D.loc[idxq]:.4f}")

# ---- 附件1 D 首末段 ----
f1 = r"E:\git_clone\Beacon\problems\mcm51-c\source\附件1：两组位移时序数据-问题1.xlsx"
d1 = pd.read_excel(f1)
A = pd.to_numeric(d1["数据A_光纤位移计数据_mm"]); B = pd.to_numeric(d1["数据B_振弦式位移计数据_mm"])
tt = pd.to_datetime(d1["时间"])
D1 = A - B
h = (tt - tt.iloc[0]).dt.total_seconds() / 3600.0
P("=" * 60)
P(f"[附件1 D=A-B 首24h 均值={D1[h<=24].mean():.4f} 末24h 均值={D1[h>=h.max()-24].mean():.4f} 全段均值={D1.mean():.4f}]")
P(f"[附件1 D 前3行: {D1.iloc[:3].tolist()} 最后3行: {D1.iloc[-3:].tolist()}]")
P(f"[附件1 D 每24h末均值]")
for day in range(1, 8):
    seg = D1[(h >= (day-1)*24) & (h < day*24)]
    if len(seg): P(f"  第{day}天: 均值={seg.mean():.4f}")

# ---- 附件1/4/5 表面位移 相邻差最大跳变 ----
def big_jumps(df, disp_col, time_col, label, topk=6):
    s = pd.to_numeric(df[disp_col], errors="coerce")
    tt = pd.to_datetime(df[time_col])
    dv = s.diff()
    P(f"[{label} {disp_col} 相邻差 |Δ| 最大前{topk}]")
    for idx, vv in dv.abs().sort_values(ascending=False).head(topk).items():
        P(f"  idx={idx} 时间={tt.loc[idx]} Δ={dv.loc[idx]:.4f} mm/10min 值={s.loc[idx]:.6g}")

big_jumps(pd.read_excel(f1), "数据A_光纤位移计数据_mm", "时间", "附件1")
big_jumps(pd.read_excel(f1), "数据B_振弦式位移计数据_mm", "时间", "附件1")
f4t = pd.read_excel(f4, sheet_name="训练集")
big_jumps(f4t, "表面位移_mm", "时间", "附件4训练集")
f5 = r"E:\git_clone\Beacon\problems\mcm51-c\source\附件5：监测数据-问题5.xlsx"
d5 = pd.read_excel(f5)
big_jumps(d5, "表面位移_mm", "时间", "附件5")

# ---- 附件4 训练集 爆破行 微震/位移 快照 ----
P("=" * 60)
P("[附件4训练集 爆破行(前10) 微震事件数与表面位移]")
b = f4t["爆破点距离_m"].notna()
for _, r in f4t[b].head(10).iterrows():
    P(f"  {r['时间']} 距离={r['爆破点距离_m']} 药量={r['单段最大药量_kg']} 微震={r['微震事件数']} 位移={r['表面位移_mm']} 降雨={r['降雨量_mm']}")
P("[附件5 爆破行(前10) 微震/位移快照]")
b5 = d5["爆破点距离_m"].notna()
for _, r in d5[b5].head(10).iterrows():
    P(f"  {r['时间']} 距离={r['爆破点距离_m']} 药量={r['单段最大药量_kg']} 微震={r['微震事件数']} 位移={r['表面位移_mm']} 干湿={r['干湿入渗系数']}")

# ---- 附件3 训练/实验集 编号与统计对比 ----
f3 = r"E:\git_clone\Beacon\problems\mcm51-c\source\附件3：监测数据（训练集与实验集）-问题3.xlsx"
tr = pd.read_excel(f3, sheet_name="训练集"); ex = pd.read_excel(f3, sheet_name="实验集")
P("=" * 60)
P(f"[附件3 训练集编号 {tr['编号'].min()}..{tr['编号'].max()}; 实验集编号 {ex['编号'].min()}..{ex['编号'].max()}]")
P("[附件3 缺失并集检查(同一行同列双缺的比例, 仅描述性): 各列缺失率已在上文]")

with open(r"E:\git_clone\Beacon\problems\mcm51-c\_probe_extra.txt", "w", encoding="utf-8") as fh:
    fh.write("\n".join(OUT))
print("EXTRA_LINES:", len(OUT))
print("\n".join(OUT))
