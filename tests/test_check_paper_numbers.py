# -*- coding: utf-8 -*-
"""论文数字红线校验工具（scripts/check_paper_numbers.py）的单元测试。

约定：本环境 pytest 的 tmp_path / tempfile.mkdtemp 可能被沙箱拒绝，
因此全部测试只使用仓库内 fixture 文件（tests/fixtures/check_numbers/），
定位方式为 Path(__file__).parent / "fixtures" / "check_numbers"。
"""

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures" / "check_numbers"
SCRIPT = Path(__file__).parent.parent / "scripts" / "check_paper_numbers.py"


def _load_module():
    """通过 importlib 从 scripts/ 加载被测试脚本（不污染 sys.modules 命名空间）。"""
    spec = importlib.util.spec_from_file_location("check_paper_numbers_under_test", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def mod():
    return _load_module()


def _paths(*names):
    return [str(FIXTURES / n) for n in names]


# ---------------------------------------------------------------------------
# 数字 token 提取规则
# ---------------------------------------------------------------------------

def test_timestamp_whole_token(mod):
    """时间戳 h:mm:ss 作为整体 token，不拆成三个数字。"""
    assert mod.extract_number_tokens("10:03:21") == ["10:03:21"]
    assert mod.extract_number_tokens("120:26:49") == ["120:26:49"]
    toks = mod.extract_number_tokens("设备于 01:33:20 开始，120:26:49 结束，耗时 7200 s")
    assert toks == ["01:33:20", "120:26:49", "7200"]


def test_decimal_thousands_minus(mod):
    """小数/千分位/负号提取；百分比与单位不并入 token；U+2212 负号归一。"""
    text = "41600、0.3100、74.2、-2141、155000、1,234,567.89、74.2%、−1.68%"
    assert mod.extract_number_tokens(text) == [
        "41600", "0.3100", "74.2", "-2141", "155000",
        "1,234,567.89", "74.2", "-1.68",
    ]


# ---------------------------------------------------------------------------
# 白名单构建（含 json 证据）
# ---------------------------------------------------------------------------

def test_json_evidence_whitelist(mod):
    """json 证据：解析后按字符串提取数字，键（"1.5"/"2.0"）与值都进入白名单。"""
    whitelist, total, warns = mod.load_evidence_whitelist(_paths("evidence_b.json"))
    assert not warns
    assert "2.0" in whitelist          # 键/值中的小数
    assert "100000" in whitelist       # 值中的整数
    assert "2026" in whitelist         # 键中的年份
    assert "124944" in whitelist
    assert "2" in whitelist            # 整数形浮点归一（2.0 → 2）
    assert total >= 10


# ---------------------------------------------------------------------------
# 功能 A：白名单 diff
# ---------------------------------------------------------------------------

def test_whitelist_match_clean(mod, capsys):
    """干净论文：全部数字命中白名单，未溯源为 0，默认退出码 0。"""
    rc = mod.main(["--paper", *_paths("paper_clean.md"),
                   "--evidence", *_paths("evidence_a.txt", "evidence_b.json")])
    out = capsys.readouterr().out
    assert rc == 0
    assert "未溯源：0" in out
    assert "[结论] OK" in out


def test_polluted_reports_all_six(mod, capsys):
    """污染论文：必须报出 216203 / 127985 / 214853 / 126635 / 250000 / 350000。"""
    rc = mod.main(["--paper", *_paths("paper_polluted.md"),
                   "--evidence", *_paths("evidence_a.txt", "evidence_b.json")])
    out = capsys.readouterr().out
    assert rc == 0
    assert "未溯源：6" in out
    for tok in ("216203", "127985", "214853", "126635", "250000", "350000"):
        assert tok in out
    # 未溯源清单应带行号与上下文
    assert ":2 | 216203 |" in out or "| 216203 |" in out


def test_allow_passes_noise(mod, capsys):
    """--allow 放行后未溯源归零。"""
    rc = mod.main(["--paper", *_paths("paper_polluted.md"),
                   "--evidence", *_paths("evidence_a.txt", "evidence_b.json"),
                   "--allow", "216203,127985,214853,126635,250000,350000"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "未溯源：0" in out


def test_strict_exit_code(mod, capsys):
    """--strict 时存在未溯源数字则退出码 1；无未溯源则 0。"""
    assert mod.main(["--paper", *_paths("paper_polluted.md"),
                     "--evidence", *_paths("evidence_a.txt", "evidence_b.json"),
                     "--strict"]) == 1
    assert mod.main(["--paper", *_paths("paper_clean.md"),
                     "--evidence", *_paths("evidence_a.txt", "evidence_b.json"),
                     "--strict"]) == 0


def test_paper_glob(mod, capsys):
    """--paper 支持 glob：多个论文文件按文件分组输出统计。"""
    rc = mod.main(["--paper", str(FIXTURES / "papers" / "*.md"),
                   "--evidence", *_paths("evidence_a.txt", "evidence_b.json")])
    out = capsys.readouterr().out
    assert rc == 0
    assert "paper1.md" in out
    assert "paper2.md" in out
    assert out.count("未溯源：0") == 2


def test_missing_paper_exit_2(mod, capsys):
    """没有可用论文文件时退出码 2。"""
    rc = mod.main(["--paper", str(FIXTURES / "no_such_*.md"),
                   "--evidence", *_paths("evidence_a.txt")])
    capsys.readouterr()
    assert rc == 2


def test_no_args_exit_2(mod, capsys):
    """既无 --paper 也无 --traceability 时退出码 2。"""
    assert mod.main([]) == 2


# ---------------------------------------------------------------------------
# 功能 B：附录 A 溯源核对
# ---------------------------------------------------------------------------

def test_traceability(mod, capsys):
    """溯源表断言：通过 4 / 失败 1 / 无法解析 1，默认退出码 0。"""
    rc = mod.main(["--traceability", *_paths("appendix_a.md")])
    out = capsys.readouterr().out
    assert rc == 0
    assert "通过：4" in out
    assert "失败：1" in out
    assert "无法解析：1" in out
    assert "99999" in out            # 伪造数字应出现在失败条目中
    assert "未找到：99999" in out


def test_traceability_strict_fail(mod, capsys):
    """--strict 且存在失败条目时退出码 1。"""
    rc = mod.main(["--traceability", *_paths("appendix_a.md"), "--strict"])
    capsys.readouterr()
    assert rc == 1


# ---------------------------------------------------------------------------
# 真实 CLI 退出码（子进程）
# ---------------------------------------------------------------------------

def test_cli_subprocess_exit_codes():
    """子进程方式验证真实退出码：默认 0，--strict 为 1，全放行后为 0。"""
    paper, eva, evb = _paths("paper_polluted.md", "evidence_a.txt", "evidence_b.json")
    r1 = subprocess.run([sys.executable, str(SCRIPT), "--paper", paper,
                         "--evidence", eva, evb],
                        capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert r1.returncode == 0
    r2 = subprocess.run([sys.executable, str(SCRIPT), "--paper", paper,
                         "--evidence", eva, evb, "--strict"],
                        capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert r2.returncode == 1
    r3 = subprocess.run([sys.executable, str(SCRIPT), "--paper", paper,
                         "--evidence", eva, evb, "--strict",
                         "--allow", "216203,127985,214853,126635,250000,350000"],
                        capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert r3.returncode == 0
