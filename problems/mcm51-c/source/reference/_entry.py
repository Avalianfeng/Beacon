# -*- coding: utf-8 -*-
import matplotlib
matplotlib.use('Agg')
r"""
_entry.py —— 多文件参考实现入口（方案甲：脚本层重组，不改 pipeline 源码）
=====================================================================
由轨 A coder wrapper 用 `exec((data_dir/'reference/_entry.py').read_text(encoding='utf-8'))`
执行（wrapper 仍只 exec 一个入口）。本文件职责：
  1. 顶部 Agg 无头后端（先于任何 pyplot 导入）；
  2. 数据目录四级定位（顺序）：命名空间 data_dir（exec 前定义）→ 环境变量
     MATH_AGENT_DATA_DIR → Path(__file__).resolve().parent.parent（entry 在
     reference/ 下，数据在 reference 的父目录 source/）→ Path.cwd()；
  3. REF_DIR = Path(__file__).resolve().parent（若 __file__ 在 globals）否则
     Path(data_dir)/'reference'；
  4. 按序 exec 兄弟模块 common.py → q1.py → q2.py → q3.py → q4.py → q5.py
     （exec 共享命名空间：common 里定义的函数/常量、各问算出的变量互相可见）；
  5. 全部 exec 完后，打印唯一一行合并 RESULT（各问变量聚合，f-string 计算值）。
"""
import os
from pathlib import Path


# =====================================================================
# 数据目录定位（四级优先级：data_dir 命名空间 > 环境变量 > 本文件父目录的父目录 > cwd）
# 用 globals().get() 防 exec 场景 NameError（coder wrapper exec 前定义 data_dir）。
# =====================================================================
def _resolve_data_dir():
    if globals().get('data_dir') is not None:
        return Path(globals().get('data_dir'))
    env = os.environ.get('MATH_AGENT_DATA_DIR')
    if env:
        return Path(env)
    f = globals().get('__file__')
    if f is not None:
        # _entry.py 在 reference/ 下；数据（5 个 xlsx）在 reference 的父目录 source/
        return Path(f).resolve().parent.parent
    return Path.cwd()


DATA_DIR = _resolve_data_dir()
OUT = Path.cwd()          # 所有图片输出到 cwd（流水线可检测 PNG）

_REF = globals().get('__file__')
if _REF is not None:
    REF_DIR = Path(_REF).resolve().parent
else:
    REF_DIR = Path(DATA_DIR) / 'reference'

# =====================================================================
# 按序 exec 兄弟模块（共享命名空间）
# =====================================================================
exec((REF_DIR / 'common.py').read_text(encoding='utf-8'), globals())
exec((REF_DIR / 'q1.py').read_text(encoding='utf-8'), globals())
exec((REF_DIR / 'q2.py').read_text(encoding='utf-8'), globals())
exec((REF_DIR / 'q3.py').read_text(encoding='utf-8'), globals())
exec((REF_DIR / 'q4.py').read_text(encoding='utf-8'), globals())
exec((REF_DIR / 'q5.py').read_text(encoding='utf-8'), globals())

# =====================================================================
# 末尾唯一一行合并 RESULT（7 个纯数值指标，f-string 变量计算值，禁止写死常量）
# =====================================================================
print(f"RESULT: baseline=ours q1_gain={Q1_gain:.4f} q1_rmse={Q1_rmse:.4f} "
      f"q2_node1={Q2_node1} q2_node2={Q2_node2} q3_common={Q3_common} "
      f"q4_rmse={Q4_rmse:.4f} q5_rmse={Q5_rmse:.4f}")
