# -*- coding: utf-8 -*-
"""核查：x 值作为 A 位移取值时的定位 + 附件1 跳变点全景。只读。"""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd

f1 = r"E:\git_clone\Beacon\problems\mcm51-c\source\附件1：两组位移时序数据-问题1.xlsx"
d1 = pd.read_excel(f1)
A = pd.to_numeric(d1["数据A_光纤位移计数据_mm"])
B = pd.to_numeric(d1["数据B_振弦式位移计数据_mm"])
tt = pd.to_datetime(d1["时间"])

OUT = []
def P(*a): OUT.append(" ".join(str(x) for x in a))

xs = [7.132, 18.526, 84.337, 123.554, 167.667]
P("### 验证点 x 按 'A 的位移取值' 解释 ###")
for x in xs:
    # 精确相等行
    exact = (A - x).abs() < 1e-9
    if exact.any():
        idxs = np.where(exact)[0]
        for i in idxs:
            P(f"  x={x}: A 精确等于 {x} 的行 idx={i} 时间={tt.iloc[i]} A={A.iloc[i]} B={B.iloc[i]}")
    # 最近行
    i = (A - x).abs().idxmin()
    P(f"  x={x}: 最近行 idx={i} 时间={tt.iloc[i]} A={A.iloc[i]:.6g} B={B.iloc[i]:.6g} |A-x|={abs(A.iloc[i]-x):.6g}")

P("")
P("### 附件1 A 中所有 |Δ|>20 mm/10min 的跳变点 ###")
dv = A.diff()
big = dv.abs() > 20
P(f"  跳变点数(>20mm/10min)={int(big.sum())}")
for i in np.where(big)[0]:
    P(f"  idx={i} 时间={tt.iloc[i]} A前={A.iloc[i-1]:.4f} -> A={A.iloc[i]:.4f} Δ={dv.iloc[i]:.4f} B={B.iloc[i]:.4f}")

P("")
P("### A 值域内 x 出现的次数(允许±0.005容差) ###")
for x in xs:
    cnt = ((A - x).abs() <= 0.005).sum()
    P(f"  x={x}: 出现行数={cnt}")

with open(r"E:\git_clone\Beacon\problems\mcm51-c\_probe_x.txt", "w", encoding="utf-8") as fh:
    fh.write("\n".join(OUT))
print("\n".join(OUT))
