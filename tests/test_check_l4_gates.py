# -*- coding: utf-8 -*-
"""check_l4_gates.py 测试（仓库内 fixture，不用 tmp_path）。"""

import importlib.util
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures" / "l4_gates"
SCRIPT = Path(__file__).parent.parent / "scripts" / "check_l4_gates.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("check_l4_gates_under_test", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def mod():
    return _load_module()


def _paper(*names: str) -> list[str]:
    return ["--paper", str(FIXTURES / names[0])]


def test_clean_no_trigger(mod, capsys):
    code = mod.main(_paper("clean.md"))
    out = capsys.readouterr().out
    assert code == 0
    assert "[WARN]" not in out
    assert "[结论] OK" in out


def test_sens_fail_strict(mod, capsys):
    code = mod.main(_paper("sens_fail.md") + ["--strict"])
    out = capsys.readouterr().out
    assert code == 1
    assert "sensitivity_no_decision" in out
    assert "[结论] WARN：L4 闸门未过 1 项" in out


def test_sens_fail_default_warn(mod, capsys):
    code = mod.main(_paper("sens_fail.md"))
    out = capsys.readouterr().out
    assert code == 0
    assert "sensitivity_no_decision" in out


def test_sens_ok(mod, capsys):
    code = mod.main(_paper("sens_ok.md") + ["--strict"])
    out = capsys.readouterr().out
    assert code == 0
    assert "sensitivity_no_decision" not in out
    assert "[结论] OK" in out


def test_recon_fail_strict(mod, capsys):
    code = mod.main(_paper("recon_fail.md") + ["--strict"])
    out = capsys.readouterr().out
    assert code == 1
    assert "reconstruction_no_y0" in out


def test_recon_ok(mod, capsys):
    code = mod.main(_paper("recon_ok.md") + ["--strict"])
    out = capsys.readouterr().out
    assert code == 0
    assert "reconstruction_no_y0" not in out
    assert "[结论] OK" in out


def test_anom_fail_strict(mod, capsys):
    code = mod.main(_paper("anom_fail.md") + ["--strict"])
    out = capsys.readouterr().out
    assert code == 1
    assert "anomaly_no_definition" in out


def test_anom_ok(mod, capsys):
    code = mod.main(_paper("anom_ok.md") + ["--strict"])
    out = capsys.readouterr().out
    assert code == 0
    assert "anomaly_no_definition" not in out
    assert "[结论] OK" in out


def test_explain_warn_strict_still_ok(mod, capsys):
    code = mod.main(_paper("explain_warn.md") + ["--strict"])
    out = capsys.readouterr().out
    assert code == 0
    assert "explanation_failure" in out
    assert "[结论] OK" in out
    assert "L4 闸门未过" not in out


def test_no_paper_exit_2(mod, capsys):
    code = mod.main([])
    err = capsys.readouterr().err
    assert code == 2
    assert "--paper" in err
