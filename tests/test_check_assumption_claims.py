# -*- coding: utf-8 -*-
"""
check_assumption_claims 工具测试。

覆盖：R1 同段矛盾命中/不命中（矛盾段、正常段、跨段不误报、无标记段落模式）、
R2 引号标记、R3 完整性提示、--strict 退出码、glob 多文件、多 --paper 参数。

注意：本环境 pytest 的 tmp_path/mkdtemp 可能被沙箱拒绝，故测试一律使用仓库内
fixture（tests/fixtures/check_claims/），不使用任何临时目录。
"""

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "check_claims"
SCRIPT = REPO_ROOT / "scripts" / "check_assumption_claims.py"

# 以源码方式加载被测模块（scripts/ 不是包，故不走 import）
_spec = importlib.util.spec_from_file_location("check_assumption_claims", SCRIPT)
cac = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cac)


def analyze(name):
    """分析某个 fixture，返回 FileReport。"""
    return cac.analyze_file(FIXTURES / name)


# ---------------------------------------------------------------------------
# R1：同段自相矛盾
# ---------------------------------------------------------------------------

def test_r1_hit_contradiction_entry():
    """复刻 mcm51-b 假设 9：「依据：题面明确要求」+「合理性分析：…题面未要求」同段 → 命中。"""
    rep = analyze("contradiction_entry.md")
    assert rep.mode == "marker"
    assert rep.entry_count == 1
    assert len(rep.r1) == 1
    h = rep.r1[0]
    assert h.seg.label == "假设9"
    assert h.stem == "要求"
    assert h.pos_snippet == "题面明确要求"
    assert h.neg_snippet == "题面未要求"
    # 命中的段全文包含依据与合理性分析两行（fixture 有标题行，条目在 L5–L7，1-based）
    assert h.seg.start + 1 == 5 and h.seg.end + 1 == 7
    assert "依据" in h.seg.text and "题面未要求" in h.seg.text


def test_r1_no_hit_normal_simplification():
    """复刻 mcm51-b 假设 4：跨谓词（明确假设 + 未提供）→ 正常简化，不判矛盾。"""
    rep = analyze("normal_simplification.md")
    assert rep.r1 == []


def test_r1_no_hit_cross_paragraph():
    """跨段不误报：肯定式与否定式分处不同段落 → 不判矛盾。"""
    rep = analyze("cross_paragraph_no_hit.md")
    assert rep.mode == "paragraph"
    assert rep.r1 == []


def test_r1_hit_paragraph_mode():
    """无假设标记（空行分段）模式下，同段矛盾仍可命中且不多报。"""
    rep = analyze("paragraph_mode_hit.md")
    assert rep.mode == "paragraph"
    assert len(rep.r1) == 1
    assert rep.r1[0].stem == "要求"


def test_r1_hit_assumption_stem():
    """「题面明确假设」对「题面未假设」→ 假设谓词同样判矛盾。"""
    rep = analyze("assumption_stem_hit.md")
    assert len(rep.r1) == 1
    assert rep.r1[0].stem == "假设"


def test_r1_hit_brief_style_entries():
    """brief 稿风格三条目（假设7/9/10）→ 各命中一处、条目数正确、R3 无缺失。"""
    rep = analyze("brief_style_entries.md")
    assert rep.mode == "marker"
    assert rep.entry_count == 3
    assert len(rep.r1) == 3
    assert [h.seg.label for h in rep.r1] == ["假设7", "假设9", "假设10"]
    assert all(h.stem == "要求" for h in rep.r1)
    assert rep.r3 == []


def test_clean_skill_style():
    """干净样本（skill 轨 B 风格，只用"题设"）→ R1/R2 全零。"""
    rep = analyze("clean_skill_style.md")
    assert rep.mode == "paragraph"
    assert rep.r1 == []
    assert rep.r2 == []


# ---------------------------------------------------------------------------
# R2：声明清单与引号标记
# ---------------------------------------------------------------------------

def test_r2_quote_flags():
    """R2：同行含引号 → 可能带原文引用；同行/同段均无引号 → 疑似无原文依据。"""
    rep = analyze("r2_quote_flags.md")
    assert len(rep.r2) == 2
    quoted = [it for it in rep.r2 if it.quote_in_line]
    plain = [it for it in rep.r2 if not it.quote_in_line and not it.quote_in_segment]
    # fixture 有标题行：依据1 在 L4（含「」引号）、依据2 在 L8（无引号）
    assert len(quoted) == 1 and quoted[0].lineno == 4
    assert len(plain) == 1 and plain[0].lineno == 8
    # 输出标记文案
    assert "疑似无原文依据" in cac._quote_flag(plain[0])
    assert "同行含引号" in cac._quote_flag(quoted[0])


def test_r2_counts_brief_style():
    """brief 稿风格三条目：每条"依据"含"题面明确要求" → R2 恰好 3 行。"""
    rep = analyze("brief_style_entries.md")
    assert len(rep.r2) == 3
    assert all(not it.quote_in_line and not it.quote_in_segment for it in rep.r2)


# ---------------------------------------------------------------------------
# R3：条目完整性
# ---------------------------------------------------------------------------

def test_r3_incomplete():
    """R3：假设2 缺"合理性分析/理由"、假设3 缺"依据" → 各一条提示；假设1 完整不提示。"""
    rep = analyze("r3_incomplete.md")
    by_label = {p.seg.label: p.missing for p in rep.r3}
    assert by_label["假设2"] == ["合理性分析/理由"]
    assert by_label["假设3"] == ["依据"]
    assert "假设1" not in by_label


# ---------------------------------------------------------------------------
# 退出码与多文件
# ---------------------------------------------------------------------------

def test_exit_codes():
    """退出码：默认 0（WARN）；--strict 且 R1 命中 → 1；无输入文件 → 2。"""
    hit = str(FIXTURES / "contradiction_entry.md")
    clean = str(FIXTURES / "clean_skill_style.md")
    assert cac.main(["--paper", hit]) == 0                      # 默认 WARN
    assert cac.main(["--paper", hit, "--strict"]) == 1          # strict + R1 命中
    assert cac.main(["--paper", clean, "--strict"]) == 0        # strict + 无命中
    assert cac.main(["--paper", str(FIXTURES / "no_such_file.md")]) == 2   # 路径不存在
    assert cac.main(["--paper", str(FIXTURES / "no_such_*.md")]) == 2      # glob 无匹配
    assert cac.main([]) == 2                                    # 缺 --paper


def test_glob_multiple_files(capsys):
    """glob 展开多文件：全部 fixture 均被处理，--strict 下有命中 → 退出码 1。"""
    code = cac.main(["--paper", str(FIXTURES / "*.md"), "--strict"])
    assert code == 1
    out = capsys.readouterr().out
    assert "contradiction_entry.md" in out
    assert "clean_skill_style.md" in out
    assert "总体汇总" in out


def test_multiple_paper_args(capsys):
    """多个 --paper 参数依次处理，均无 R1 命中 → 退出码 0。"""
    code = cac.main(["--paper",
                     str(FIXTURES / "contradiction_entry.md"),
                     str(FIXTURES / "normal_simplification.md")])
    assert code == 0
    out = capsys.readouterr().out
    assert "contradiction_entry.md" in out
    assert "normal_simplification.md" in out


def test_verbose_prints_segments(capsys):
    """--verbose 输出逐段扫描明细。"""
    code = cac.main(["--paper", str(FIXTURES / "contradiction_entry.md"), "--verbose"])
    assert code == 0
    out = capsys.readouterr().out
    assert "逐段扫描明细" in out
    assert "肯定式「要求」" in out and "否定式「要求」" in out
