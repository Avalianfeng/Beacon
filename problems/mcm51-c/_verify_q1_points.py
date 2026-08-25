# -*- coding: utf-8 -*-
"""独立复核 data_profile.md F1：表1.1 五个 x 值是否精确命中附件1 A 列唯一行。"""
import pandas as pd

P = r"E:\git_clone\Beacon\problems\mcm51-c\source\附件1：两组位移时序数据-问题1.xlsx"
df = pd.read_excel(P)
print("columns:", list(df.columns))
print("shape:", df.shape)
A = df.iloc[:, 1].astype(float)
B = df.iloc[:, 2].astype(float)
targets = [7.132, 18.526, 84.337, 123.554, 167.667]
print("-" * 60)
for x in targets:
    idx = A[A == x].index.tolist()
    if idx:
        i = idx[0]
        print(f"x={x:>8}  ->  A行 idx={i}, 时刻={df.iloc[i,0]}, A={A[i]}, B={B[i]}, A-B={A[i]-B[i]:.3f}")
    else:
        print(f"x={x:>8}  ->  未命中")
print("-" * 60)
print("A-B 全序列: mean=%.3f std=%.3f  r(A,B)=%.6f" % ((A-B).mean(), (A-B).std(), A.corr(B)))
