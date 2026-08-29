"""T-19 冻结资产直接执行：检测 / 零 LLM / 哈希失败 / mcm51-b 冒烟。"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from math_agent.frozen_asset import (
    FrozenAsset,
    FrozenDetectError,
    build_frozen_wrapper,
    detect_frozen_asset,
)
from math_agent.nodes.coder import (
    coder_execute_node,
    coder_generate_node,
    coder_prepare_node,
)
from math_agent.state import DataFileInfo, MathModelingState, ModelVersion


REPO = Path(__file__).resolve().parents[2]
MCM51B = REPO / "problems" / "mcm51-b"
MCM51B_SOURCE = MCM51B / "source"
MCM51B_SOLVER = MCM51B_SOURCE / "reference_solver.py"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_detect_none_without_data_dir():
    assert detect_frozen_asset(None) is None
    assert detect_frozen_asset("") is None


def test_detect_none_without_reference_asset(tmp_path: Path):
    data = tmp_path / "source"
    data.mkdir()
    (tmp_path / "problem.json").write_text(
        json.dumps({
            "title": "t",
            "background": "b",
            "questions": ["q"],
            "source": {"source_files": [{"path": "a.xlsx", "sha256": "abc"}]},
            "data_dir": "source",
        }),
        encoding="utf-8",
    )
    assert detect_frozen_asset(data) is None


def test_detect_mcm51b_single_file():
    asset = detect_frozen_asset(MCM51B_SOURCE)
    assert isinstance(asset, FrozenAsset)
    assert asset.kind == "single"
    assert asset.entry_path.resolve() == MCM51B_SOLVER.resolve()


def test_detect_hash_mismatch_fail_closed(tmp_path: Path):
    data = tmp_path / "source"
    data.mkdir()
    solver = data / "reference_solver.py"
    solver.write_text("def main(a, b): pass\n", encoding="utf-8")
    (tmp_path / "problem.json").write_text(
        json.dumps({
            "title": "t",
            "background": "b",
            "questions": ["q"],
            "source": {
                "source_files": [{
                    "path": "source/reference_solver.py",
                    "sha256": "0" * 64,
                }],
            },
            "data_dir": "source",
        }),
        encoding="utf-8",
    )
    result = detect_frozen_asset(data)
    assert isinstance(result, FrozenDetectError)
    assert "哈希不匹配" in result.message


def test_build_wrapper_contains_attachment_literal_and_no_listdir():
    asset = FrozenAsset(
        kind="single",
        data_dir=MCM51B_SOURCE.resolve(),
        problem_dir=MCM51B.resolve(),
        entry_path=MCM51B_SOLVER.resolve(),
        verified_files=(MCM51B_SOLVER.resolve(),),
        entry_name="reference_solver.py",
    )
    code = build_frozen_wrapper(asset, data_filenames=["B-附件.xlsx"])
    assert "B-附件.xlsx" in code
    assert "listdir" not in code
    assert "glob" not in code
    assert "main(" in code
    assert "Path.cwd()" in code


def test_prepare_hash_fail_closed(tmp_path: Path):
    data = tmp_path / "source"
    data.mkdir()
    solver = data / "reference_solver.py"
    solver.write_text("def main(a, b): pass\n", encoding="utf-8")
    (tmp_path / "problem.json").write_text(
        json.dumps({
            "title": "t",
            "background": "b",
            "questions": ["q"],
            "source": {
                "source_files": [{
                    "path": "source/reference_solver.py",
                    "sha256": "deadbeef" * 8,
                }],
            },
            "data_dir": "source",
        }),
        encoding="utf-8",
    )
    state = MathModelingState(problem="p", data_dir=str(data), output_dir=str(tmp_path / "out"))
    state.model_versions.append(ModelVersion(stage="final", description="d"))
    delta = coder_prepare_node(state)
    assert delta["coder_phase"] == "done"
    assert delta["coder_work_queue"] == []
    assert any("frozen asset" in e for e in delta["errors"])


def test_prepare_hit_shrinks_queue_to_one_primary():
    state = MathModelingState(
        problem="p",
        data_dir=str(MCM51B_SOURCE.resolve()),
        output_dir=str(REPO / "runs" / "mcm51-b-t19-smoke"),
    )
    state.model_versions.append(
        ModelVersion(
            stage="final",
            description="d",
            figure_purposes=["主图", "补充1", "补充2"],
        )
    )
    delta = coder_prepare_node(state)
    assert delta["coder_phase"] == "generate"
    assert len(delta["coder_work_queue"]) == 1
    assert delta["coder_work_queue"][0]["frozen"] is True
    assert delta["coder_work_queue"][0]["evidence_target"] == "primary"


def test_generate_frozen_zero_llm(mocker, tmp_path: Path):
    complete = mocker.patch("math_agent.nodes.coder.complete")
    state = MathModelingState(
        problem="p",
        data_dir=str(MCM51B_SOURCE.resolve()),
        output_dir=str(tmp_path),
        data_files=[DataFileInfo(filename="B-附件.xlsx", file_type="xlsx", path="B-附件.xlsx")],
    )
    state.model_versions.append(ModelVersion(stage="final", description="d"))
    state = state.model_copy(update=coder_prepare_node(state))
    delta = coder_generate_node(state)
    assert complete.call_count == 0
    assert delta["coder_phase"] == "execute"
    draft = delta["coder_pending_draft"]
    assert "T-19 frozen" in draft["code"]
    assert "B-附件.xlsx" in draft["code"]


def test_no_asset_still_calls_llm(mocker, tmp_path: Path, monkeypatch):
    monkeypatch.setenv("MATH_AGENT_ALLOW_CODER_LLM", "1")
    data = tmp_path / "source"
    data.mkdir()
    (tmp_path / "problem.json").write_text(
        json.dumps({
            "title": "t",
            "background": "b",
            "questions": ["q"],
            "source": {"source_files": []},
            "data_dir": "source",
        }),
        encoding="utf-8",
    )
    from math_agent.nodes.coder import CoderDraft

    complete = mocker.patch(
        "math_agent.nodes.coder.complete",
        return_value=CoderDraft(
            purpose="x",
            code=("import matplotlib; matplotlib.use('Agg'); "
                  "import matplotlib.pyplot as plt; plt.savefig('fig.png'); "
                  "print('RESULT: baseline=ours a=1 b=2 c=3 d=4')"),
        ),
    )
    state = MathModelingState(problem="p", data_dir=str(data), output_dir=str(tmp_path / "out"))
    state.model_versions.append(ModelVersion(stage="final", description="d"))
    state = state.model_copy(update=coder_prepare_node(state))
    assert not state.coder_work_queue[0].get("frozen")
    delta = coder_generate_node(state)
    assert complete.call_count == 1
    assert delta["coder_phase"] == "execute"


def test_mcm51b_frozen_smoke(tmp_path: Path):
    """真实 reference_solver：零 LLM，RESULT + PNG + read_paths。"""
    if not MCM51B_SOLVER.is_file():
        pytest.skip("mcm51-b reference_solver.py missing")
    # 登记哈希必须与磁盘一致
    registered = json.loads((MCM51B / "problem.json").read_text(encoding="utf-8"))
    entry = next(
        f for f in registered["source"]["source_files"]
        if "reference_solver" in f["path"]
    )
    assert entry["sha256"] == _sha256(MCM51B_SOLVER)

    out = REPO / "runs" / "mcm51-b-t19-smoke"
    out.mkdir(parents=True, exist_ok=True)
    state = MathModelingState(
        problem="mcm51-b",
        data_dir=str(MCM51B_SOURCE.resolve()),
        output_dir=str(out),
        data_files=[
            DataFileInfo(filename="B-附件.xlsx", file_type="xlsx", path="B-附件.xlsx"),
        ],
    )
    state.model_versions.append(
        ModelVersion(stage="final", description="多工序协同", figure_purposes=["甘特"])
    )

    # 不 patch complete —— 命中冻结路径不得调用
    state = state.model_copy(update=coder_prepare_node(state))
    assert state.coder_work_queue[0].get("frozen")
    state = state.model_copy(update=coder_generate_node(state))
    assert state.coder_phase == "execute"
    delta = coder_execute_node(state)

    arts = delta["code_artifacts"]
    assert arts, delta
    primary = arts[0]
    assert primary.success, primary.stderr
    assert "RESULT: baseline=ours" in primary.stdout
    pngs = [p for p in primary.artifact_paths if str(p).lower().endswith(".png")]
    assert pngs, primary.artifact_paths
    assert any("B-附件.xlsx" in str(p) or "b-附件.xlsx" in str(p).casefold() for p in primary.read_paths)
    # 证据落盘摘要
    summary = out / "smoke_summary.txt"
    summary.write_text(
        f"success={primary.success}\n"
        f"result_line={[ln for ln in primary.stdout.splitlines() if ln.startswith('RESULT:')]}\n"
        f"pngs={pngs}\n"
        f"read_paths={primary.read_paths}\n",
        encoding="utf-8",
    )
