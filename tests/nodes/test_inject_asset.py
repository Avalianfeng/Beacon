"""D-025 inject 资产：检测 / 零 LLM / T-19 优先 / 多候选失败闭环。"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from math_agent.inject_asset import (
    InjectAsset,
    InjectDetectError,
    build_inject_wrapper,
    detect_inject_asset,
    read_inject_sensitivity,
)
from math_agent.nodes.coder import (
    coder_execute_node,
    coder_generate_node,
    coder_prepare_node,
)
from math_agent.nodes.sensitivity import (
    SensitivityPlan,
    sensitivity_code_generate_node,
)
from math_agent.state import DataFileInfo, MathModelingState, ModelVersion

REPO = Path(__file__).resolve().parents[2]
MCM51B = REPO / "problems" / "mcm51-b"
MCM51B_SOURCE = MCM51B / "source"
MCM51B_SOLVER = MCM51B_SOURCE / "reference_solver.py"

_INJECT_ENTRY = '''import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from pathlib import Path

def main(data_dir, out_dir):
    out = Path(out_dir) / "inject_fig.png"
    fig, ax = plt.subplots()
    ax.plot([1, 2, 3], [1, 4, 9])
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print("RESULT: baseline=ours metric_0=1.0 metric_1=2.0 metric_2=3.0 metric_3=4.0")
'''


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _problem_with_reference(data: Path, solver: Path) -> None:
    (data.parent / "problem.json").write_text(
        json.dumps({
            "title": "t",
            "background": "b",
            "questions": ["q"],
            "source": {
                "source_files": [{
                    "path": "source/reference_solver.py",
                    "sha256": _sha256(solver),
                }],
            },
            "data_dir": "source",
        }),
        encoding="utf-8",
    )


def test_detect_none_without_inject(tmp_path: Path):
    data = tmp_path / "source"
    data.mkdir()
    assert detect_inject_asset(data) is None
    assert detect_inject_asset(None) is None


def test_detect_entry_priority(tmp_path: Path):
    data = tmp_path / "source"
    inject = data / "inject"
    inject.mkdir(parents=True)
    (inject / "other.py").write_text("x = 1\n", encoding="utf-8")
    (inject / "_entry.py").write_text("def main(a, b): pass\n", encoding="utf-8")
    asset = detect_inject_asset(data)
    assert isinstance(asset, InjectAsset)
    assert asset.entry_path.name == "_entry.py"


def test_detect_single_py_candidate(tmp_path: Path):
    data = tmp_path / "source"
    inject = data / "inject"
    inject.mkdir(parents=True)
    only = inject / "solver.py"
    only.write_text("def main(a, b): pass\n", encoding="utf-8")
    asset = detect_inject_asset(data)
    assert isinstance(asset, InjectAsset)
    assert asset.entry_path == only.resolve()


def test_detect_multi_py_fail_closed(tmp_path: Path):
    data = tmp_path / "source"
    inject = data / "inject"
    inject.mkdir(parents=True)
    (inject / "a.py").write_text("x=1\n", encoding="utf-8")
    (inject / "b.py").write_text("y=2\n", encoding="utf-8")
    result = detect_inject_asset(data)
    assert isinstance(result, InjectDetectError)
    assert "多个 Python 文件" in result.message


def test_sensitivity_py_not_counted_as_entry(tmp_path: Path):
    data = tmp_path / "source"
    inject = data / "inject"
    inject.mkdir(parents=True)
    (inject / "sensitivity.py").write_text("print('s')\n", encoding="utf-8")
    assert detect_inject_asset(data) is None


def test_read_inject_sensitivity(tmp_path: Path):
    data = tmp_path / "source"
    inject = data / "inject"
    inject.mkdir(parents=True)
    path = inject / "sensitivity.py"
    path.write_text("print('scan')\n", encoding="utf-8")
    assert read_inject_sensitivity(data) == "print('scan')\n"
    assert read_inject_sensitivity(tmp_path / "missing") is None
    path.write_text("   \n", encoding="utf-8")
    assert read_inject_sensitivity(data) is None


def test_prepare_inject_queue_one_primary(tmp_path: Path):
    data = tmp_path / "source"
    inject = data / "inject"
    inject.mkdir(parents=True)
    (inject / "_entry.py").write_text(_INJECT_ENTRY, encoding="utf-8")
    state = MathModelingState(problem="p", data_dir=str(data), output_dir=str(tmp_path / "out"))
    state.model_versions.append(
        ModelVersion(stage="final", description="d", figure_purposes=["主图", "补充"])
    )
    delta = coder_prepare_node(state)
    assert delta["coder_phase"] == "generate"
    assert len(delta["coder_work_queue"]) == 1
    assert delta["coder_work_queue"][0].get("injected") is True
    assert not delta["coder_work_queue"][0].get("frozen")


def test_generate_inject_zero_llm(mocker, tmp_path: Path):
    data = tmp_path / "source"
    inject = data / "inject"
    inject.mkdir(parents=True)
    (inject / "main.py").write_text(_INJECT_ENTRY, encoding="utf-8")
    complete = mocker.patch("math_agent.nodes.coder.complete")
    state = MathModelingState(
        problem="p",
        data_dir=str(data),
        output_dir=str(tmp_path / "out"),
        data_files=[DataFileInfo(filename="a.csv", file_type="csv", path="a.csv")],
    )
    state.model_versions.append(ModelVersion(stage="final", description="d"))
    state = state.model_copy(update=coder_prepare_node(state))
    delta = coder_generate_node(state)
    assert complete.call_count == 0
    assert delta["coder_phase"] == "execute"
    assert "D-025 inject wrapper" in delta["coder_pending_draft"]["code"]
    assert "a.csv" in delta["coder_pending_draft"]["code"]


def test_prepare_multi_py_fail_closed(tmp_path: Path):
    data = tmp_path / "source"
    inject = data / "inject"
    inject.mkdir(parents=True)
    (inject / "a.py").write_text("x=1\n", encoding="utf-8")
    (inject / "b.py").write_text("y=2\n", encoding="utf-8")
    state = MathModelingState(problem="p", data_dir=str(data), output_dir=str(tmp_path / "out"))
    state.model_versions.append(ModelVersion(stage="final", description="d"))
    delta = coder_prepare_node(state)
    assert delta["coder_phase"] == "done"
    assert delta["coder_work_queue"] == []
    assert any("inject asset" in e for e in delta["errors"])


def test_t19_takes_priority_over_inject(tmp_path: Path, mocker):
    data = tmp_path / "source"
    data.mkdir()
    solver = data / "reference_solver.py"
    solver.write_text("def main(a, b): pass\n", encoding="utf-8")
    _problem_with_reference(data, solver)
    inject = data / "inject"
    inject.mkdir()
    (inject / "_entry.py").write_text("def main(a, b): raise RuntimeError('inject')\n", encoding="utf-8")

    complete = mocker.patch("math_agent.nodes.coder.complete")
    state = MathModelingState(problem="p", data_dir=str(data), output_dir=str(tmp_path / "out"))
    state.model_versions.append(ModelVersion(stage="final", description="d"))
    delta = coder_prepare_node(state)
    assert delta["coder_work_queue"][0].get("frozen") is True
    assert not delta["coder_work_queue"][0].get("injected")
    state = state.model_copy(update=delta)
    gen = coder_generate_node(state)
    assert complete.call_count == 0
    assert "T-19 frozen" in gen["coder_pending_draft"]["code"]


def test_inject_execute_smoke(tmp_path: Path, mocker):
    data = tmp_path / "source"
    inject = data / "inject"
    inject.mkdir(parents=True)
    (inject / "_entry.py").write_text(_INJECT_ENTRY, encoding="utf-8")
    out = tmp_path / "out"
    out.mkdir()
    complete = mocker.patch("math_agent.nodes.coder.complete")
    state = MathModelingState(problem="p", data_dir=str(data), output_dir=str(out))
    state.model_versions.append(ModelVersion(stage="final", description="d"))
    state = state.model_copy(update=coder_prepare_node(state))
    state = state.model_copy(update=coder_generate_node(state))
    delta = coder_execute_node(state)
    assert complete.call_count == 0
    arts = delta["code_artifacts"]
    assert arts and arts[0].success, arts[0].stderr if arts else delta
    assert "RESULT: baseline=ours" in arts[0].stdout
    pngs = [p for p in arts[0].artifact_paths if str(p).lower().endswith(".png")]
    assert pngs


def test_build_wrapper_has_main_call():
    asset = InjectAsset(
        entry_path=Path("/tmp/inject/_entry.py"),
        data_dir=Path("/tmp/source"),
    )
    code = build_inject_wrapper(asset, data_filenames=["x.xlsx"])
    assert "main(" in code
    assert "x.xlsx" in code
    assert "no hash" in code.lower() or "D-025" in code
