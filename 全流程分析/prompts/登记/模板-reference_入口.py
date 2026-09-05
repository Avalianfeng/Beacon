# -*- coding: utf-8 -*-
"""<题ID> · Beacon 主求解插座（_entry）。

契约与验收见 全流程分析/prompts/登记/契约-代码插座.md。
数值从 研究/data 重读（研究已算）；附件只做血缘触碰；执行 cwd 落 PNG。
"""
from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path


def _problem_root() -> Path:
    """定位题根。exec 包装只注入 data_dir（绝对 source/），不传 __file__；
    cwd 是 runs/<id>，不能当题根。"""
    dd = globals().get("data_dir")
    if dd is not None:
        d = Path(dd)
        if not d.is_absolute():
            d = d.resolve()
        return d.parent if d.name == "source" else d
    f = globals().get("__file__")
    if f is not None:
        p = Path(f).resolve()
        if p.parent.name == "reference":  # source/reference/_entry.py → parents[2] = 题根
            return p.parents[2]
    raise SystemExit("_entry: 无法定位题根（无 data_dir 且无 __file__）")


ROOT = _problem_root()
DATA = ROOT / "研究" / "data"          # 数值唯一来源：研究摘要/表（自己重读，不手抄）
SRC = ROOT / "source" if (ROOT / "source").is_dir() else ROOT


def _touch_given_attachments(src: Path) -> None:
    """血缘门禁：真实 open problem.json 声明的附件（读字节即可）。
    数值仍读研究摘要——血缘证明"代码接触过原始附件"，不是重扫附件。"""
    # TODO: 按 problem.json 的 data_files 声明取附件名，不要手写死
    names = ["附件1.xlsx", "附件2.xlsx", "附件3.xlsx", "附件4.xlsx"]
    for name in names:
        path = src / name
        if not path.is_file():
            continue
        with path.open("rb") as fh:
            fh.read(64)


def _export_evidence_pngs() -> None:
    """证据图：把研究产出的 PNG 拷进执行 cwd（runner 按 cwd 收图）。"""
    dest = Path.cwd()
    for folder in (ROOT / "研究" / "figures",):
        if not folder.is_dir():
            continue
        for png in folder.glob("*.png"):
            shutil.copy2(png, dest / png.name)


_touch_given_attachments(SRC)
_export_evidence_pngs()

# ---------------------------------------------------------------------------
# TODO: 读研究摘要（JSON/CSV），取各问关键结果；只读不抄
#   bt = json.loads((DATA / "<回测摘要>.json").read_text(encoding="utf-8"))
#   rows = list(csv.DictReader((DATA / "<方案>.csv").open(encoding="utf-8-sig")))
# ---------------------------------------------------------------------------

# 健全断言（写清"为什么"）：无 NaN、量级关系、结构计数
# TODO: vals = [ ... ]; assert all(v == v for v in vals)
# TODO: assert <关键结构> == <预期>          # 如 n == 28

# ---------------------------------------------------------------------------
# 输出契约（格式见契约 §3）：
#   Q<id>: k=v k=v …                       字段名 ASCII；值=数字或 [a,b,c]
#   RESULT: baseline=ours <指标>=<值> …    至少 3 个指标
#   RESULT: baseline=<对照名> <共同指标>=<值> …   每套对照独立一行（finalizer 计数）
# ---------------------------------------------------------------------------
# TODO: print(f"Q1: key_result={...:.4f}")
# TODO: print(f"Q2: ...")
# TODO: print("RESULT: baseline=ours m1=... m2=... m3=...")
# TODO: print("RESULT: baseline=<对照1> m1=... m2=...")   # 与 ours 有共同指标且数值不同
