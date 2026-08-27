# -*- coding: utf-8 -*-
"""结构探查：sheet 名、shape、列名、前3行样本值。只读，不改附件。"""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import pandas as pd

FILES = [
    r"E:\git_clone\Beacon\problems\mcm51-c\source\附件1：两组位移时序数据-问题1.xlsx",
    r"E:\git_clone\Beacon\problems\mcm51-c\source\附件2：位移时序数据-问题2.xlsx",
    r"E:\git_clone\Beacon\problems\mcm51-c\source\附件3：监测数据（训练集与实验集）-问题3.xlsx",
    r"E:\git_clone\Beacon\problems\mcm51-c\source\附件4：监测数据（训练集与实验集）-问题4.xlsx",
    r"E:\git_clone\Beacon\problems\mcm51-c\source\附件5：监测数据-问题5.xlsx",
]

for f in FILES:
    print("=" * 100)
    print("FILE:", f)
    xl = pd.ExcelFile(f)
    print("SHEETS:", xl.sheet_names)
    for sh in xl.sheet_names:
        df = pd.read_excel(f, sheet_name=sh, header=None, nrows=6)
        print("-" * 80)
        print("SHEET:", sh, "shape(head6):", df.shape)
        # 逐行打印前6行，看是否有标题行
        for i in range(df.shape[0]):
            print(f"  row{i}:", [repr(v) for v in df.iloc[i].tolist()])
