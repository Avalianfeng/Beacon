#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
论文数字红线校验工具（check_paper_numbers）
============================================

背景
----
数学建模自动化体系（Beacon）在"论文化（论文 Word 化）"阶段出现过"无证据数字"：
例如某敏感性表使用了 1/2/4 m/s 速度档位的数字（216203 / 127985 / 214853 / 126635），
而实际求解器脚本只扫描 1.5/2.0/2.5/3.0 四档；附录 A 声称数字来自某脚本，
但脚本输出与表不符（溯源断链）。

本工具把"论文/章节 md 中出现的数字必须能在证据文件中找到溯源"机械化：

  功能 A（主功能，白名单 diff）
    从 --evidence 证据文件（md/txt/json 均可）提取全部数字 token 构成白名单；
    扫描 --paper 论文/章节 md 的每个数字 token，凡不在白名单（且未被 --allow
    放行）者记入"未溯源清单"（文件、行号、行内上下文约 40 字符）。
    默认退出码 0（WARN）；--strict 时存在未溯源数字则退出码 1。

  功能 B（附录 A 溯源核对，可选模式）
    --traceability 给定附录 A 数值溯源表 md，解析"文件名 + 行号/行号范围"引用，
    读取被引用文件对应行，断言该行内容包含所声称的数字，逐条输出 通过/失败/无法解析。

数字 token 提取规则
-------------------
1. 时间戳 h:mm:ss（如 10:03:21、120:26:49）作为整体 token，不拆成三个数字；
2. 其余数字按 整数/小数/千分位/带负号 提取（41600、0.3100、74.2、-2141、155000、1,234,567.89）；
3. 百分比符号、单位符号（s、m、元、% 等）不并入 token（74.2% → 74.2）；
4. 全角负号 U+2212（−）归一为 ASCII 连字符 '-'，避免同一数字两种写法互相漏配。

本脚本仅依赖 Python 标准库（argparse / re / json / glob / os / sys / pathlib），
可离线运行；注释与输出均为中文（UTF-8）。

用法示例
--------
  python scripts/check_paper_numbers.py \
      --paper runs/mcm51-b-skill-v1/paper.md \
      --evidence runs/mcm51-b-skill-v1/data/evidence.md \
                 runs/mcm51-b-skill-v1/data/solver_full_output.txt \
                 runs/mcm51-b-skill-v1/data/sensitivity.json
  python scripts/check_paper_numbers.py --paper 章节/07-6-敏感性分析.md \
      --evidence 结果/关键数字.md --strict
  python scripts/check_paper_numbers.py --traceability 章节/10-附录.md --strict
"""

import argparse
import glob
import json
import os
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# 数字 token 提取
# ---------------------------------------------------------------------------

# 合并正则：组 1 = 时间戳整体；其余分支 = 千分位 / 小数 / 整数（可带负号）。
# 负号已在提取前把 U+2212（−）归一为 ASCII '-'，故这里只需 "-?"。
# 千分位分支末尾的 (?!\d) 防止把数学列表里的元素误拼成千分位，
# 例如 \{0,25000,50000\} 应提取 0 / 25000 / 50000，而不是 "0,250" / "00,500"。
_NUMBER_RE = re.compile(
    r"(?<!\d)(\d{1,3}:\d{2}:\d{2})(?!\d)"          # 时间戳 h:mm:ss（整体）
    r"|-?\d{1,3}(?:,\d{3})+(?:\.\d+)?(?!\d)"       # 千分位整数/小数，如 1,234,567.89
    r"|-?\d+\.\d+"                                 # 小数，如 0.3100、74.2、-1.68
    r"|-?\d+"                                      # 整数，如 41600、-2141
)


def extract_number_tokens(text):
    """从文本中提取数字 token 列表（保留出现顺序）。

    - 时间戳 h:mm:ss（如 10:03:21、120:26:49）作为整体 token；
    - 其余按 整数/小数/千分位/带负号 提取；
    - 百分比、单位符号不并入 token（74.2% → 74.2）。
    """
    if not text:
        return []
    text = text.replace("\u2212", "-")  # 全角负号 − 归一为 ASCII '-'
    out = []
    for m in _NUMBER_RE.finditer(text):
        out.append(m.group(1) if m.group(1) else m.group(0))
    return out


# ---------------------------------------------------------------------------
# 功能 A：白名单构建与论文扫描
# ---------------------------------------------------------------------------

def _read_text(path):
    """按 UTF-8 读取文本（容错替换非法字节）。"""
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        return fh.read()


def load_evidence_whitelist(paths):
    """从证据文件构建白名单集合。

    - .json：先 json.load 解析，再 json.dumps 序列化为字符串后提取数字
      （键与值都会进入白名单，如 speed 字典的键 "1.5"/"2.0"）；
    - 其余（md/txt 等）：按原文提取；
    - 整数形浮点归一：JSON 中 155000.0 序列化为 "155000.0" 的同时放行 "155000"，
      避免论文写 155000 而证据写 155000.0 造成的假漏报。
    """
    whitelist = set()
    total_tokens = 0
    warnings = []
    for p in paths:
        try:
            text = _read_text(p)
        except OSError as e:
            warnings.append("无法读取证据文件：%s（%s）" % (p, e))
            continue
        if p.lower().endswith(".json"):
            try:
                obj = json.loads(text)
                text = json.dumps(obj, ensure_ascii=False)
            except (ValueError, TypeError) as e:
                warnings.append("证据文件 %s 不是合法 JSON，按纯文本提取（%s）" % (p, e))
        toks = extract_number_tokens(text)
        total_tokens += len(toks)
        whitelist.update(toks)
        # 整数形浮点归一：155000.0 → 同时放行 155000
        for t in toks:
            if re.fullmatch(r"-?\d+\.0+", t):
                whitelist.add(t.split(".")[0])
    return whitelist, total_tokens, warnings


def _context(line, token, width=20):
    """取 token 所在行的行内上下文（token 前后各约 width 字符）。"""
    idx = line.find(token)
    if idx < 0:
        idx = 0
    start = max(0, idx - width)
    end = min(len(line), idx + len(token) + width)
    ctx = line[start:end]
    if start > 0:
        ctx = "…" + ctx
    if end < len(line):
        ctx += "…"
    return ctx


def scan_paper(path, whitelist, allowed):
    """逐行扫描论文 md，返回统计与未溯源明细。"""
    lines = _read_text(path).splitlines()
    total = hit = 0
    unmatched = []      # (lineno, token, context)
    matched = []        # verbose 用：命中的 token 示例
    for i, line in enumerate(lines, 1):
        for tok in extract_number_tokens(line):
            total += 1
            if tok in whitelist or tok in allowed:
                hit += 1
                matched.append(tok)
            else:
                unmatched.append((i, tok, _context(line, tok)))
    return {
        "path": str(path),
        "total": total,
        "hit": hit,
        "unmatched": len(unmatched),
        "items": unmatched,
        "matched": matched,
    }


def _expand(patterns, what):
    """展开（支持 glob）并去重文件列表；未匹配的模式给出警告。"""
    out, seen = [], set()
    for pat in patterns:
        hits = sorted(glob.glob(pat))
        if not hits and os.path.isfile(pat):
            hits = [pat]
        if not hits:
            print("[警告] %s 未匹配任何文件：%s" % (what, pat), file=sys.stderr)
            continue
        for h in hits:
            if h not in seen:
                seen.add(h)
                out.append(h)
    return out


def run_whitelist_check(paper_pats, evid_pats, allow_csv, strict, verbose):
    """功能 A 主流程，返回退出码（0 正常 / 1 strict 失败 / 2 用法或 IO 错误）。"""
    papers = _expand(paper_pats, "论文文件")
    evidences = _expand(evid_pats, "证据文件")

    allowed = set()
    if allow_csv:
        allowed = {t.strip() for t in allow_csv.split(",") if t.strip()}

    if not evidences:
        print("[错误] 没有可用的证据文件，无法构建白名单。", file=sys.stderr)
        return 2
    whitelist, ev_total, warns = load_evidence_whitelist(evidences)
    for w in warns:
        print("[警告] %s" % w, file=sys.stderr)
    if not whitelist:
        print("[错误] 白名单为空（证据文件中未提取到任何数字）。", file=sys.stderr)
        return 2
    if not papers:
        print("[错误] 没有可用的论文文件。", file=sys.stderr)
        return 2

    print("\n===== 功能 A：白名单 diff =====")
    print("证据文件 %d 个 → 数字 token 共 %d 个，去重后白名单大小 %d"
          % (len(evidences), ev_total, len(whitelist)))
    if allowed:
        print("--allow 放行：%s" % ", ".join(sorted(allowed)))

    results = [scan_paper(p, whitelist, allowed) for p in papers]
    for r in results:
        print("\n[论文] %s" % r["path"])
        print("  数字 token 总数：%d | 命中（白名单/放行）：%d | 未溯源：%d"
              % (r["total"], r["hit"], r["unmatched"]))
        if verbose and r["matched"]:
            print("  （verbose 命中示例：%s）" % " ".join(r["matched"][:30]))

    total_all = sum(r["total"] for r in results)
    hit_all = sum(r["hit"] for r in results)
    un_all = sum(r["unmatched"] for r in results)
    print("\n[汇总] 论文数字总数 %d | 命中 %d | 未溯源 %d" % (total_all, hit_all, un_all))

    if un_all:
        print("\n[未溯源清单]（文件:行号 | token | 行内上下文）")
        for r in results:
            for lineno, tok, ctx in r["items"]:
                print("  %s:%d | %s | %s" % (r["path"], lineno, tok, ctx))
        print("\n[结论] WARN：存在 %d 个未溯源数字（建议人工核对或在证据中补录；"
              "--allow 可放行，--strict 时退出码为 1）" % un_all)
        return 1 if strict else 0
    print("\n[结论] OK：论文全部数字均可在证据白名单中找到溯源。")
    return 0


# ---------------------------------------------------------------------------
# 功能 B：附录 A 溯源核对
# ---------------------------------------------------------------------------

_TRACE_EXTS = ("py", "txt", "json", "md", "csv", "log", "out", "xlsx")

# 路径引用：反引号包裹（`代码/sensitivity.py`）或裸路径（对照/轨B-solver_full_output.txt）。
_PATH_RE = re.compile(
    r"`([^`]+)`|([^\s|,;，；:：()（）<>\"'`]+\.(?:py|txt|json|md|csv|log|out|xlsx))"
)

# 行号引用：第 N 行 / 第 N–M 行 / 第 N 至 M 行 / 第 1/10/55/100 行 / N–M 行。
_LINE_GROUP_RE = re.compile(r"第\s*([\d\s/\-–~至到、,，和及与]+)\s*行")
_BARE_RANGE_RE = re.compile(r"(\d+)\s*[-–~至到]\s*(\d+)\s*行")


def _collect_paths(text):
    """从文本中找出疑似文件路径引用（带扩展名、无空白）。"""
    out = []
    for m in _PATH_RE.finditer(text):
        cand = (m.group(1) or m.group(2)).strip()
        if len(cand) > 1 and cand.lower().endswith(_TRACE_EXTS) and " " not in cand:
            out.append(cand)
    return out


def _collect_line_numbers(text):
    """从文本中收集全部被引用的行号（区间展开为集合，支持 1/10/55 等斜杠列表）。"""
    nums = set()

    def add_range(a, b):
        nums.update(range(a, b + 1))

    for m in _BARE_RANGE_RE.finditer(text):          # 无"第"的裸区间：N–M 行
        add_range(int(m.group(1)), int(m.group(2)))
    for m in _LINE_GROUP_RE.finditer(text):          # 第 … 行（单号 / 区间 / 斜杠列表）
        inner = m.group(1)
        covered = set()
        for rm in re.finditer(r"(\d+)\s*[-–~至到]\s*(\d+)", inner):
            a, b = int(rm.group(1)), int(rm.group(2))
            add_range(a, b)
            covered.update(range(a, b + 1))
        for dm in re.finditer(r"\d+", inner):
            n = int(dm.group(0))
            if n not in covered:
                nums.add(n)
    return nums


def _drop_trivial(tokens):
    """去掉单数字（及单数字负号）等标签噪音：Q4→4、班组1→1、表5→5 不参与断言。"""
    return [t for t in tokens if len(t.replace("-", "")) > 1]


def resolve_path(p, base):
    """按"溯源文件目录 → 逐级上级（最多 4 层）→ 当前工作目录"解析相对路径。"""
    if re.match(r"^[A-Za-z]:[\\/]", p):          # Windows 盘符绝对路径
        cand = Path(p)
        return cand if cand.is_file() else None
    if p.startswith(("\\", "/")):                # 根相对路径：剥离前导斜杠按相对解析
        p = p.lstrip("\\/")
    dirs = [base] + list(base.parents[:4]) + [Path.cwd()]
    for d in dirs:
        c = d / p
        if c.is_file():
            return c
    return None


def iter_trace_entries(text):
    """把溯源 md 拆成条目（yield lineno, claimed, source, inherit_paths）。

    - 表格行（以 | 开头）：末列视为"来源"，其余列视为"论文数字"；
    - 非表格行：仅当行内包含反引号文件引用（如 `xx.py`）时，按"整行 = 数字 + 来源"
      尽力解析；路径/引号内文本（`mcm51-b`、`Q1 makespan: 41600 秒`）先掩码，
      行号引用里的数字（第 5 行）不计入所声称数字；
    - 单个数字（0–9，含负号）视为标签噪音（Q4→4、班组1→1、表5→5），不参与断言；
    - inherit_paths：文档中最近一次出现的文件路径。evidence.md 等文档采用
      "首个引用给文件名、后续行只写第 N 行"的接续风格，此处把上一路径带下去，
      供"来源"未引用文件时继承（见 run_traceability）。
    """
    last_paths = []
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        if line.startswith("|"):
            cells = [c.strip() for c in line.strip("|").split("|")]
            if len(cells) < 2:
                continue
            claimed_cells = cells[:-1]
            source = cells[-1]
            claimed = _drop_trivial(extract_number_tokens(" ".join(claimed_cells)))
            paths = _collect_paths(source)
            if paths:
                last_paths = paths
            if claimed:
                yield lineno, claimed, source, list(last_paths)
        else:
            paths = _collect_paths(line)
            if paths:
                last_paths = paths
                masked = _PATH_RE.sub(lambda m: " " * len(m.group(0)), line)
                claimed = extract_number_tokens(masked)
                ref_nums = {str(n) for n in _collect_line_numbers(line)}
                claimed = _drop_trivial([t for t in claimed if t not in ref_nums])
                if claimed:
                    yield lineno, claimed, line, list(last_paths)


def run_traceability(trace_pat, strict, verbose):
    """功能 B 主流程，返回退出码（0 正常 / 1 strict 失败 / 2 用法或 IO 错误）。"""
    files = _expand([trace_pat], "溯源文件")
    if not files:
        print("[错误] 没有可用的溯源文件。", file=sys.stderr)
        return 2
    f = files[0]
    text = _read_text(f)
    base = Path(f).parent
    entries = list(iter_trace_entries(text))

    rows = []
    for lineno, claimed, source, inherit_paths in entries:
        paths = _collect_paths(source)
        inherited = False
        if not paths and inherit_paths and _collect_line_numbers(source):
            paths = inherit_paths
            inherited = True
        nums = _collect_line_numbers(source)
        if not paths:
            status = "无法解析"
            detail = "来源未引用可定位文件（如仅算式/口头描述）"
        else:
            segs, missing = [], []
            for p in paths:
                rp = resolve_path(p, base)
                if rp is None:
                    missing.append(p)
                    continue
                content = _read_text(rp)
                lines = content.splitlines()
                if nums:
                    seg = "\n".join(lines[i - 1] for i in sorted(nums) if 1 <= i <= len(lines))
                else:
                    seg = content
                segs.append(seg)
            if not segs:
                status = "无法解析"
                detail = "找不到文件：" + "、".join(missing)
            else:
                blob = "\n".join(segs)
                miss_toks = [t for t in claimed if t not in blob]
                if miss_toks:
                    status = "失败"
                    detail = "被引用文件内容中未找到：" + ", ".join(miss_toks)
                    if missing:
                        detail += "；另有文件未找到：" + "、".join(missing)
                else:
                    status = "通过"
                    where = ("第 %d–%d 行" % (min(nums), max(nums))) if nums else "全文"
                    detail = "%s 命中：%s" % (where, ", ".join(claimed))
                    if missing:
                        detail += "（另有文件未找到：" + "、".join(missing) + "）"
            if inherited:
                detail += "（文件路径继承自上文）"
        rows.append((lineno, claimed, source, status, detail))

    n_pass = sum(1 for r in rows if r[3] == "通过")
    n_fail = sum(1 for r in rows if r[3] == "失败")
    n_na = sum(1 for r in rows if r[3] == "无法解析")

    print("\n===== 功能 B：附录 A 溯源核对 =====")
    print("溯源文件：%s" % f)
    print("解析假设：")
    print("  1) 仅处理 markdown 表格行（|…|…|…|），末列视为\"来源\"，其余列视为\"论文数字\"；")
    print("     非表格行若含反引号文件引用（`xx.py`）也按\"整行\"尽力解析。")
    print("  2) \"来源\"列须含可定位文件名（扩展名 .py/.txt/.json/.md/.csv/.log/.out/.xlsx）才会断言；")
    print("     仅算式/口头描述（如 \"215303 − 127085\"）判为无法解析。")
    print("  3) 相对路径按：溯源文件所在目录 → 逐级上级（最多 4 层）→ 当前工作目录 解析。")
    print("  4) 行号引用支持\"第 N 行 / 第 N–M 行 / 第 N 至 M 行 / 第 N 行、第 M 行\"等；")
    print("     未指明行号时检查整个文件。")
    print("  5) 断言：所声称数字以子串形式出现在被引用行文本中；U+2212（−）负号归一为 '-'。")
    print("  6) \"来源\"未引用文件时，继承该文档上文最近一次出现的文件路径（evidence.md 等")
    print("     文档采用\"首个引用给文件名、后续行只写第 N 行\"的接续风格）。")
    print("  7) 单个数字（0–9）视为编号/标签噪音（Q4、班组1、表5 中的 4/1/5），不参与断言；")
    print("     散文行中路径与引号内文本（`mcm51-b` 等）不提取为所声称数字。")
    print("\n条目总数：%d | 通过：%d | 失败：%d | 无法解析：%d" % (len(rows), n_pass, n_fail, n_na))

    print("\n[失败条目]（溯源断链风险）")
    for lineno, claimed, source, status, detail in rows:
        if status == "失败":
            print("  行 %d | 数字 [%s] | 来源 %s" % (lineno, ", ".join(claimed), source))
            print("    → 失败：%s" % detail)
    if verbose:
        print("\n[通过条目]")
        for lineno, claimed, source, status, detail in rows:
            if status == "通过":
                print("  行 %d | 数字 [%s] | → %s" % (lineno, ", ".join(claimed), detail))
        print("\n[无法解析条目]")
        for lineno, claimed, source, status, detail in rows:
            if status == "无法解析":
                print("  行 %d | 数字 [%s] | 来源 %s | → %s"
                      % (lineno, ", ".join(claimed), source, detail))

    print("\n[汇总] 通过 %d / 失败 %d / 无法解析 %d" % (n_pass, n_fail, n_na))
    if n_fail:
        print("[结论] WARN：%d 条断言失败（溯源断链风险；--strict 时退出码为 1）" % n_fail)
        return 1 if strict else 0
    print("[结论] OK：全部可解析条目均通过断言（无法解析条目需人工核对）。")
    return 0


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

def build_parser():
    p = argparse.ArgumentParser(
        prog="check_paper_numbers.py",
        description="论文数字红线校验：论文 md 中的数字必须能在证据文件（白名单）中找到溯源。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--paper", nargs="+", default=[],
                   help="论文/章节 md 文件或 glob（可多个），功能 A 扫描对象")
    p.add_argument("--evidence", nargs="+", default=[],
                   help="证据文件 md/txt/json（可多个），用于构建白名单")
    p.add_argument("--allow", default="",
                   help="逗号分隔的放行数字（人工确认的噪音，如 2026,2001,2010）")
    p.add_argument("--strict", action="store_true",
                   help="存在未溯源数字（或功能 B 失败条目）时退出码为 1")
    p.add_argument("--verbose", action="store_true", help="打印匹配明细与白名单大小")
    p.add_argument("--traceability", default=None, metavar="附录A.md",
                   help="附录 A 数值溯源表 md（功能 B 溯源核对）")
    return p


def main(argv=None):
    """CLI 入口，返回退出码（0/1/2）。"""
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    args = build_parser().parse_args(argv)
    if not args.paper and not args.traceability:
        print("[错误] 至少需要 --paper（功能 A）或 --traceability（功能 B）之一。",
              file=sys.stderr)
        return 2

    exit_code = 0
    if args.paper:
        exit_code = max(exit_code, run_whitelist_check(
            args.paper, args.evidence, args.allow, args.strict, args.verbose))
    if args.traceability:
        exit_code = max(exit_code, run_traceability(
            args.traceability, args.strict, args.verbose))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
