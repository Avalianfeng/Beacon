"""cumcm23-c inject/sensitivity.py：图内重跑，中心点对齐主方案周收益。"""
from __future__ import annotations

from pathlib import Path

from math_agent.inject_asset import wrap_inject_sensitivity
from math_agent.nodes.sensitivity import _parse_results
from math_agent.tools.runner import extract_numeric_results, run_python

REPO = Path(__file__).resolve().parents[1]
PROBLEM = REPO / "problems" / "cumcm23-c"
SOURCE = PROBLEM / "source"
INJECT = SOURCE / "inject" / "sensitivity.py"
ENTRY = SOURCE / "reference" / "_entry.py"


def test_cumcm23c_inject_sensitivity_reruns_and_centers(tmp_path: Path):
    code = wrap_inject_sensitivity(INJECT.read_text(encoding="utf-8"), SOURCE)
    result = run_python(code, workdir=tmp_path / "sens", timeout=60)
    assert result.success, result.stderr
    parsed = {name: (vals, res) for name, vals, res in _parse_results(result.stdout)}
    assert "成本冲击 (cost_shock)" in parsed
    assert "加成分位 (markup_p)" in parsed
    assert "损耗率缩放 (loss_scale)" in parsed

    shock_vals, shock_res = parsed["成本冲击 (cost_shock)"]
    markup_vals, markup_res = parsed["加成分位 (markup_p)"]
    loss_vals, loss_res = parsed["损耗率缩放 (loss_scale)"]
    assert shock_vals == [-0.2, -0.1, 0.0, 0.1, 0.2]
    assert markup_vals == [25.0, 37.5, 50.0, 62.5, 75.0]
    assert loss_vals == [0.8, 0.9, 1.0, 1.1, 1.2]

    center_shock = shock_res[len(shock_vals) // 2]
    center_markup = markup_res[len(markup_vals) // 2]
    center_loss = loss_res[len(loss_vals) // 2]
    assert abs(center_shock - center_markup) < 1e-4
    assert abs(center_shock - center_loss) < 1e-4
    assert 3300 < center_shock < 3700
    assert shock_res[0] > shock_res[-1]
    assert markup_res[0] < markup_res[-1]


def test_cumcm23c_inject_center_matches_entry_stdout(tmp_path: Path):
    entry_ns = (
        "from pathlib import Path\n"
        f"_ns = {{'data_dir': Path({SOURCE.resolve().as_posix()!r}), "
        f"'__file__': {ENTRY.resolve().as_posix()!r}}}\n"
        f"exec({ENTRY.read_text(encoding='utf-8')!r}, _ns)\n"
    )
    entry_ran = run_python(entry_ns, workdir=tmp_path / "entry", timeout=30)
    assert entry_ran.success, entry_ran.stderr
    profit = extract_numeric_results(entry_ran.stdout).get("ours", {})["q2_week_profit"]

    inject_code = wrap_inject_sensitivity(INJECT.read_text(encoding="utf-8"), SOURCE)
    sens = run_python(inject_code, workdir=tmp_path / "sens", timeout=60)
    assert sens.success, sens.stderr
    parsed = {name: (vals, res) for name, vals, res in _parse_results(sens.stdout)}
    shock_vals, shock_res = parsed["成本冲击 (cost_shock)"]
    center = shock_res[len(shock_vals) // 2]
    assert abs(center - profit) <= max(abs(profit) * 0.2, 1e-6)

    inject_code = wrap_inject_sensitivity(INJECT.read_text(encoding="utf-8"), SOURCE)
    sens = run_python(inject_code, workdir=tmp_path / "sens", timeout=60)
    assert sens.success, sens.stderr
    parsed = {name: (vals, res) for name, vals, res in _parse_results(sens.stdout)}
    shock_vals, shock_res = parsed["成本冲击 (cost_shock)"]
    center = shock_res[len(shock_vals) // 2]
    assert abs(center - profit) <= max(abs(profit) * 0.2, 1e-6)
