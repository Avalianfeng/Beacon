#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
论文假设声明自相矛盾检测工具（check_assumption_claims）
========================================================

背景
----
mcm51-b 论文（runs/mcm51-b-brief-v1/paper.md）假设 9 条目曾经这样写：

    **假设9**：一道工序由一台设备承担，不允许多台同类设备分摊工程量。
    **依据**：题面明确要求，且每道工序的工程量由单一设备完成……
    **合理性分析**：该假设使设备分配变量为0-1……但题面未要求，故合理。

同一假设条目内"依据：题面明确要求"与"合理性分析：题面未要求"自相矛盾，
而题面原文（problems/mcm51-b/problem.json / 题目信息.md）通篇没有
"一道工序只能由一台设备服务"的表述。该矛盾历经
writer→review→A/B 评审→论文化 四道关卡无人发现。
本工具把这类矛盾机械化检测，作为 Beacon 评审层补盲的一部分。

三条规则
--------
R1（硬规则，核心）：同段自相矛盾检测
  - 分段：以 `**假设N**`、`假设N：`、`假设 N` 等开头的行作为假设条目起点；
    无假设标记的 md 文件按空行分段（段落）。
  - 判定边界（务必理解）：仅当同一段内"肯定式题面声明"与"否定式题面声明"
    **谓词相同**时才判为自相矛盾，例如：
      · 「题面明确要求 / 题面要求」 对 「题面未要求 / 题面没有要求」 → 矛盾（要求）
      · 「题面明确假设」 对 「题面未假设 / 题面没有假设」 → 矛盾（假设）
    跨谓词同段（如「题面明确假设」+「题面未提供」、假设 4 的
    "题面未提供车间内距离数据"；「题面明确要求」+「题面未说明」、假设 6）
    **不**判矛盾——"题面明确假设了 A"与"题面未提供数据 B"可以同时为真，
    属正常合理简化；而"题面明确要求 X"与"题面未要求 X"必有一句为假。
    这类跨谓词组合交给 R2 清单人工核对。

R2（辅助）：无依据的"题面明确要求/假设"清单
  - 列出论文中所有出现「题面明确要求 / 题面明确假设」的行（文件、行号、整行），
    供人逐条对照题面原文核查（按协议，"题面明确要求"字样只允许出现在
    有原文引用的假设上）。
  - 每条标注同行/同段是否含引号（"…"或「…」）：有引号 → 可能带原文引用
    （仍需人工核对）；无引号 → 提示"疑似无原文依据，需人工核查"。

R3（辅助）：假设条目完整性提示
  - 对识别到的每个假设条目（R1 的标记分段条目），检查是否包含
    "依据"与"合理性分析/理由"两部分；缺失的提示补全（不判失败）。

退出码
------
  0  默认（WARN，仅提示）
  1  --strict 且 R1 有命中（自相矛盾）
  2  无输入文件（--paper 未给出，或给出的路径/glob 均未匹配）

用法
----
  python scripts/check_assumption_claims.py --paper runs/mcm51-b-brief-v1/paper.md
  python scripts/check_assumption_claims.py --paper 'runs/mcm51-b-*/paper.md' --strict
  python scripts/check_assumption_claims.py --paper a.md b.md --verbose

本脚本仅依赖 Python 标准库（argparse / glob / re / sys / pathlib），
可离线运行；注释与输出均为中文（UTF-8）。
"""

import argparse
import glob
import re
import sys
from dataclasses import dataclass
from pathlib import Path

# ---------------------------------------------------------------------------
# 常量：退出码 / 正则
# ---------------------------------------------------------------------------

EXIT_OK = 0            # 默认 WARN
EXIT_STRICT_FAIL = 1   # --strict 且 R1 有命中
EXIT_NO_INPUT = 2      # 无输入文件

# 假设条目起点：**假设1**： / 假设1： / 假设 1 等
# （允许全角/半角冒号；"**假设N**"独立成行也可识别；刻意避开散文中的"假设 N 台设备"）
ASSUMPTION_MARKER_RE = re.compile(r"^\s*\**\s*假设\s*\d+\s*(?:\*\*[:：]?|[:：]|$)")

# R1 谓词：只对"要求 / 假设"两个谓词做肯定式/否定式成对判定
POSITIVE_STEMS = ("要求", "假设")


def _pos_re(stem):
    # 肯定式：题面[明确]谓词（题面要求 / 题面明确要求 / 题面明确假设）
    return re.compile(r"题面(?:明确\s*)?%s" % stem)


def _neg_re(stem):
    # 否定式：题面[未|没有][明确]谓词（题面未要求 / 题面没有要求 / 题面未明确要求 …）
    return re.compile(r"题面(?:(?:未|没有)(?:明确\s*)?%s)" % stem)


POSITIVE_RE = {s: _pos_re(s) for s in POSITIVE_STEMS}
NEGATIVE_RE = {s: _neg_re(s) for s in POSITIVE_STEMS}

# R2：声明行关键词（协议允许的两种写法）
R2_RE = re.compile(r"题面明确(?:要求|假设)")

# R3：条目内"依据"与"合理性分析/理由"两部分
BAJU_RE = re.compile(r"^\s*\**\s*依据\**\s*[:：]")
RATIONALE_RE = re.compile(r"^\s*\**\s*(?:合理性分析|合理性说明|理由)\**\s*[:：]")

# 引号字符（原文引用标记：中文弯引号 "…" 与直角引号 「…」）
QUOTE_CHARS = frozenset('""「」')


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------

@dataclass
class Segment:
    """一段文本（假设条目或空行分隔的段落）。行号为 0-based，含 end。"""
    start: int
    end: int
    label: str
    text: str


@dataclass
class R1Hit:
    path: Path
    seg: Segment
    stem: str
    pos_snippet: str
    neg_snippet: str


@dataclass
class R2Item:
    path: Path
    lineno: int  # 1-based
    line: str
    quote_in_line: bool
    quote_in_segment: bool


@dataclass
class R3Prompt:
    path: Path
    seg: Segment
    missing: list


@dataclass
class FileReport:
    path: Path
    mode: str  # "marker"（假设标记分段）| "paragraph"（空行分段）
    segments: list
    r1: list
    r2: list
    r3: list

    @property
    def entry_count(self):
        """假设条目数：仅标记分段模式有意义。"""
        return len(self.segments) if self.mode == "marker" else 0


# ---------------------------------------------------------------------------
# 分段
# ---------------------------------------------------------------------------

def split_segments(lines):
    """把行列表切分为段落。返回 (segments, mode)。

    mode == "marker"：以 `**假设N**：`/`假设N：`/`假设 N` 开头的行作为条目起点，
        条目从标记行延续到下一个标记行或下一个空行（先到者）——真实论文中
        条目（假设句 + 依据 + 合理性分析）是连续行，彼此以空行分隔。
    mode == "paragraph"：无假设标记，按空行分段。
    """
    markers = [i for i, ln in enumerate(lines) if ASSUMPTION_MARKER_RE.match(ln)]
    if markers:
        segs = []
        for idx, m in enumerate(markers):
            nxt = markers[idx + 1] if idx + 1 < len(markers) else len(lines)
            end = nxt - 1
            for j in range(m, nxt):
                if lines[j].strip() == "":
                    end = j - 1
                    break
            if end < m:
                end = m  # 至少保留标记行本身
            mnum = re.match(r"^\s*\**\s*假设\s*(\d+)", lines[m]).group(1)
            segs.append(Segment(m, end, "假设%s" % mnum, "\n".join(lines[m:end + 1])))
        return segs, "marker"

    segs = []
    start = None
    for i, ln in enumerate(lines):
        if ln.strip() == "":
            if start is not None:
                segs.append(Segment(start, i - 1, "段落%d" % (len(segs) + 1),
                                    "\n".join(lines[start:i])))
                start = None
        elif start is None:
            start = i
    if start is not None:
        segs.append(Segment(start, len(lines) - 1, "段落%d" % (len(segs) + 1),
                            "\n".join(lines[start:])))
    return segs, "paragraph"


# ---------------------------------------------------------------------------
# 三条规则
# ---------------------------------------------------------------------------

def find_r1_in_text(text):
    """R1：同段自相矛盾检测。返回 [(stem, 肯定式片段, 否定式片段), ...]。

    仅当同一段内"肯定式题面声明"与"否定式题面声明"谓词相同（如
    「题面明确要求」对「题面未要求」）时判为矛盾；跨谓词（如
    「题面明确假设」+「题面未提供」）视为正常合理简化，不判矛盾。
    """
    hits = []
    for stem in POSITIVE_STEMS:
        pm = POSITIVE_RE[stem].search(text)
        nm = NEGATIVE_RE[stem].search(text)
        if pm and nm:
            hits.append((stem, pm.group(0), nm.group(0)))
    return hits


def segment_of(segs, lineno):
    """返回包含 lineno（0-based）的段落，找不到返回 None。"""
    for s in segs:
        if s.start <= lineno <= s.end:
            return s
    return None


def analyze_file(path):
    """分析单个文件，返回 FileReport。"""
    text = Path(path).read_text(encoding="utf-8-sig", errors="replace")
    lines = text.splitlines()
    segments, mode = split_segments(lines)

    # R1：只在假设条目/段落内部判定，跨段不误报
    r1 = []
    for seg in segments:
        for stem, pos, neg in find_r1_in_text(seg.text):
            r1.append(R1Hit(Path(path), seg, stem, pos, neg))

    # R2：全文逐行扫描"题面明确要求/假设"声明
    r2 = []
    for i, ln in enumerate(lines):
        if R2_RE.search(ln):
            seg = segment_of(segments, i)
            seg_text = seg.text if seg else ln
            r2.append(R2Item(Path(path), i + 1, ln,
                             any(ch in QUOTE_CHARS for ch in ln),
                             any(ch in QUOTE_CHARS for ch in seg_text)))

    # R3：仅对标记分段的假设条目做完整性检查
    r3 = []
    if mode == "marker":
        for seg in segments:
            missing = []
            if not any(BAJU_RE.match(l) for l in seg.text.splitlines()):
                missing.append("依据")
            if not any(RATIONALE_RE.match(l) for l in seg.text.splitlines()):
                missing.append("合理性分析/理由")
            if missing:
                r3.append(R3Prompt(Path(path), seg, missing))

    return FileReport(Path(path), mode, segments, r1, r2, r3)


# ---------------------------------------------------------------------------
# 输出
# ---------------------------------------------------------------------------

def _quote_flag(item):
    if item.quote_in_line:
        return "同行含引号（可能带原文引用，仍需人工核对）"
    if item.quote_in_segment:
        return "同段含引号（可能带原文引用，仍需人工核对）"
    return "无引号 → 疑似无原文依据，需人工核查"


def format_report(rep, verbose=False):
    out = []
    out.append("=" * 76)
    out.append("文件：%s" % rep.path)
    if rep.mode == "marker":
        out.append("分段：假设标记分段（识别到 %d 个假设条目）" % len(rep.segments))
    else:
        out.append("分段：无假设标记，按空行分段（%d 个段落）" % len(rep.segments))

    out.append("")
    out.append("【R1 自相矛盾（硬规则）】命中 %d 处" % len(rep.r1))
    for h in rep.r1:
        out.append("  ★ %s（第 %d–%d 行）：谓词「%s」——「%s」与「%s」同段冲突"
                   % (h.seg.label, h.seg.start + 1, h.seg.end + 1,
                      h.stem, h.pos_snippet, h.neg_snippet))
        for ln in h.seg.text.splitlines():
            out.append("      | %s" % ln)

    out.append("")
    out.append("【R2 无依据的「题面明确要求/假设」声明清单】共 %d 行" % len(rep.r2))
    for it in rep.r2:
        out.append("  行 %d | %s" % (it.lineno, _quote_flag(it)))
        out.append("      %s" % it.line)

    out.append("")
    out.append("【R3 假设条目完整性提示】共 %d 条" % len(rep.r3))
    for p in rep.r3:
        out.append("  %s（第 %d–%d 行）缺失：%s"
                   % (p.seg.label, p.seg.start + 1, p.seg.end + 1, "、".join(p.missing)))

    if verbose:
        out.append("")
        out.append("[verbose] 逐段扫描明细：")
        for seg in rep.segments:
            found = []
            for stem in POSITIVE_STEMS:
                if POSITIVE_RE[stem].search(seg.text):
                    found.append("肯定式「%s」" % stem)
                if NEGATIVE_RE[stem].search(seg.text):
                    found.append("否定式「%s」" % stem)
            out.append("  %s（第 %d–%d 行）：%s"
                       % (seg.label, seg.start + 1, seg.end + 1,
                          "，".join(found) if found else "无命中"))

    out.append("")
    out.append("文件级汇总：假设条目=%d，R1命中=%d，R2声明行=%d，R3提示=%d"
               % (rep.entry_count, len(rep.r1), len(rep.r2), len(rep.r3)))
    return "\n".join(out)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def resolve_inputs(patterns):
    """展开 --paper 的路径/glob 列表。返回 (文件列表[去重保序], 未找到的路径列表)。"""
    files, missing = [], []
    for pat in patterns:
        if glob.has_magic(pat):
            files.extend(glob.glob(pat))
        else:
            p = Path(pat)
            if p.is_file():
                files.append(str(p))
            else:
                missing.append(pat)
    seen, uniq = set(), []
    for f in files:
        key = str(Path(f).resolve())
        if key not in seen:
            seen.add(key)
            uniq.append(f)
    return uniq, missing


def build_parser():
    p = argparse.ArgumentParser(
        prog="check_assumption_claims.py",
        description="论文假设声明自相矛盾检测：R1 同段矛盾（硬）/ R2 题面声明清单 / R3 条目完整性。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--paper", nargs="+", default=[], metavar="md或glob",
                   help="论文 md 文件或 glob（可多个）；无输入文件时退出码为 2")
    p.add_argument("--strict", action="store_true",
                   help="R1 有命中时退出码为 1（默认 0=WARN）")
    p.add_argument("--verbose", action="store_true",
                   help="打印逐段扫描明细")
    return p


def main(argv=None):
    """CLI 入口，返回退出码（0/1/2）。"""
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    args = build_parser().parse_args(argv)
    if not args.paper:
        print("[错误] 需要至少一个 --paper 参数（md 文件或 glob）。", file=sys.stderr)
        return EXIT_NO_INPUT

    files, missing = resolve_inputs(args.paper)
    if missing:
        print("[提示] 以下路径未找到（已忽略）：%s" % "，".join(missing))
    if not files:
        print("[错误] 未找到任何输入文件（--paper 给出的路径/glob 均未匹配）。",
              file=sys.stderr)
        return EXIT_NO_INPUT

    reports = []
    for f in files:
        rep = analyze_file(f)
        reports.append(rep)
        print(format_report(rep, args.verbose))
        print()

    total_entries = sum(r.entry_count for r in reports)
    total_r1 = sum(len(r.r1) for r in reports)
    total_r2 = sum(len(r.r2) for r in reports)
    total_r3 = sum(len(r.r3) for r in reports)

    print("=" * 76)
    print("总体汇总：文件=%d，假设条目=%d，R1命中=%d，R2声明行=%d，R3提示=%d"
          % (len(reports), total_entries, total_r1, total_r2, total_r3))
    if total_r1:
        print("[结论] WARN：发现 %d 处同段自相矛盾（建议人工复核；--strict 时退出码为 1）"
              % total_r1)
        return EXIT_STRICT_FAIL if args.strict else EXIT_OK
    print("[结论] OK：未发现同段自相矛盾（R2/R3 提示项请人工核对）。")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
