"""T-11 / A-01：paper_expand 槽位扫描、缺料策略、mock 展开。"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from math_agent.paper_expand import (
    ExpandSlotOut,
    build_available_numbers,
    classify_slot,
    expand_paper,
    find_slots,
    new_untraced_numbers,
    remaining_analysis_placeholders,
)

REPO = Path(__file__).resolve().parents[1]
MATHORCUP_EV = REPO / "runs" / "mathorcup16-c-p3" / "evidence.json"


_SAMPLE_SKELETON = """# 测试题

## 摘要

结果 makespan=41600。

## 模型假设

- 假设一：设备不可抢占。

> 【待展开：逐条论证假设的建模影响与依据讨论】

## 求解结果

### 问题1

- **方向**：只用班组1
- **Q1 行数字**：`Q1: makespan=41600`

> 【待展开：问题1的模型推导/分析/检验 prose】

### 问题2

- **方向**：> 【待展开：brief 缺失，问题2方向待补充】
- **Q2 行数字**：> 【待展开：evidence 缺 Q2 行，该问数字待补充】

> 【待展开：问题2的模型推导/分析/检验 prose】

## 附录 B 代码清单

> 【待展开：problems/<problem_id>/source/reference/ 不存在，代码清单待补充】
"""


def test_classify_analysis_vs_material():
    assert classify_slot("逐条论证假设的建模影响与依据讨论") == "analysis"
    assert classify_slot("问题1的模型推导/分析/检验 prose") == "analysis"
    assert classify_slot("brief.json 缺失（--brief 未给），模型假设待人工补充") == "material"
    assert classify_slot("evidence 缺 Q2 行，该问数字待补充") == "material"
    assert classify_slot("problems/x/source/reference/ 不存在，代码清单待补充") == "material"


def test_find_slots_separates_kinds():
    slots = find_slots(_SAMPLE_SKELETON)
    analysis = [s for s in slots if s.kind == "analysis"]
    material = [s for s in slots if s.kind == "material"]
    assert len(analysis) == 3
    assert len(material) == 1
    assert analysis[0].qid is None
    assert analysis[1].qid == "1"
    assert analysis[2].qid == "2"


def test_build_available_numbers_from_evidence():
    ev = {
        "result": {"ours": {"makespan": 41600}},
        "q_lines": ["Q1: makespan=41600 q2=215303", "RESULT: baseline=ours makespan=41600"],
    }
    text = build_available_numbers(ev)
    assert "41600" in text
    assert "215303" in text
    assert "result.ours" in text


def test_expand_paper_mock_zero_llm_preserves_numbers():
    calls: list[str] = []

    def fake_complete(prompt, *, schema, **kwargs):
        calls.append(prompt)
        body = (
            "本问采用构造式调度。关键指标 makespan=41600 来自 evidence Q1 行。"
            "假设设备不可抢占，与题面一致。推导从工序依赖展开到设备分配，"
            "再校验 RESULT 行 makespan=41600。待验证项：全局最优性。"
            + ("补充分析说明建模步骤与口径。" * 30)
        )
        return ExpandSlotOut(prose=body)

    ev = {
        "result": {"ours": {"makespan": 41600}},
        "q_lines": ["Q1: makespan=41600", "RESULT: baseline=ours makespan=41600"],
    }
    result = expand_paper(
        _SAMPLE_SKELETON,
        evidence=ev,
        brief=None,
        complete_fn=fake_complete,
    )
    assert not result.errors, result.errors
    assert len(result.expanded) == 3
    assert remaining_analysis_placeholders(result.paper) == []
    assert "makespan=41600" in result.paper
    assert "## 摘要" in result.paper
    assert "附录 B" in result.paper
    assert "reference/ 不存在" in result.paper
    assert len(calls) >= 3
    assert any("41600" in p for p in calls)


def test_expand_rejects_short_prose_after_repair():
    def fake_complete(prompt, *, schema, **kwargs):
        return ExpandSlotOut(prose="太短")

    result = expand_paper(
        "> 【待展开：逐条论证假设的建模影响与依据讨论】\n",
        evidence={"result": {"ours": {}}, "q_lines": []},
        complete_fn=fake_complete,
    )
    assert result.errors
    assert any("quality gate" in e for e in result.errors)


def test_material_only_no_expand():
    paper = "> 【待展开：brief.json 缺失，模型假设待人工补充】\n"
    result = expand_paper(
        paper,
        evidence={"q_lines": ["Q1: a=1"]},
        complete_fn=lambda *a, **k: ExpandSlotOut(prose="不应调用"),
    )
    assert result.expanded == []
    assert result.skipped_material
    assert "brief.json 缺失" in result.paper


def test_new_untraced_numbers_detects_injected(tmp_path):
    evid = tmp_path / "ev.json"
    evid.write_text(
        json.dumps({"result": {"ours": {"a": 1}}, "q_lines": ["Q1: a=1"]}),
        encoding="utf-8",
    )
    skeleton = "结果 a=1"
    expanded_ok = "结果 a=1。分析说明 a=1 含义。"
    expanded_bad = "结果 a=1。另有编造 99999。"
    assert new_untraced_numbers(skeleton, expanded_ok, [evid]) == []
    assert "99999" in new_untraced_numbers(skeleton, expanded_bad, [evid])


def test_cli_expand_mock(mocker, tmp_path):
    from typer.testing import CliRunner

    from math_agent.cli import app

    skeleton = tmp_path / "paper.md"
    skeleton.write_text(
        "# t\n\n> 【待展开：逐条论证假设的建模影响与依据讨论】\n\n"
        "> 【待展开：问题1的模型推导/分析/检验 prose】\n",
        encoding="utf-8",
    )
    evid = tmp_path / "evidence.json"
    evid.write_text(
        json.dumps({
            "result": {"ours": {"x": 2}},
            "q_lines": ["Q1: x=2", "RESULT: baseline=ours x=2"],
        }),
        encoding="utf-8",
    )
    prob_dir = tmp_path / "problems" / "toy-a01"
    prob_dir.mkdir(parents=True)
    (prob_dir / "problem.json").write_text(
        json.dumps({
            "schema_version": 2,
            "problem_id": "toy-a01",
            "title": "t",
            "background": "b",
            "questions": ["q1"],
            "data_dir": "source",
            "data_files": [],
            "source": {"source_files": []},
        }),
        encoding="utf-8",
    )
    (prob_dir / "source").mkdir()
    (prob_dir / "evidence-package.json").write_text(
        json.dumps({
            "version": 1,
            "problem_id": "toy-a01",
            "ok": True,
            "evidence_path": str(evid.resolve()),
            "checks": [
                {"id": "run_success", "pass": True},
                {"id": "no_nan_inf", "pass": True},
                {"id": "has_result", "pass": True},
            ],
        }),
        encoding="utf-8",
    )
    (prob_dir / "independent-review.json").write_text(
        json.dumps({"verdict": "pass"}),
        encoding="utf-8",
    )

    def fake_complete(prompt, *, schema, **kwargs):
        return ExpandSlotOut(prose=("假设与问题一推导，引用 x=2。" + "论述。" * 80))

    mocker.patch("math_agent.paper_expand.complete", fake_complete)
    out = tmp_path / "paper-prose.md"
    runner = CliRunner()
    old = os.getcwd()
    try:
        os.chdir(tmp_path)
        res = runner.invoke(
            app,
            [
                "reference", "expand",
                "--problem", str(prob_dir / "problem.json"),
                "--paper", str(skeleton),
                "--evidence", str(evid),
                "--out", str(out),
            ],
        )
    finally:
        os.chdir(old)
    assert res.exit_code == 0, res.output
    text = out.read_text(encoding="utf-8")
    assert "【待展开：逐条论证" not in text
    assert "x=2" in text


@pytest.mark.skipif(not MATHORCUP_EV.is_file(), reason="mathorcup evidence missing")
def test_mathorcup_skeleton_slots_after_reference_paper(tmp_path):
    """用真实 reference paper 产物检查分析槽可识别（不烧 LLM）。"""
    from typer.testing import CliRunner

    from math_agent.cli import app

    out = tmp_path / "paper.md"
    runner = CliRunner()
    res = runner.invoke(
        app,
        [
            "reference", "paper",
            "--problem", str(REPO / "problems" / "mathorcup16-c" / "problem.json"),
            "--evidence", str(MATHORCUP_EV),
            "--brief", str(REPO / "problems" / "mathorcup16-c" / "brief.json"),
            "--out", str(out),
        ],
    )
    assert res.exit_code == 0, res.output
    text = out.read_text(encoding="utf-8")
    analysis = [s for s in find_slots(text) if s.kind == "analysis"]
    assert analysis, "应有假设/逐问分析槽"
    assert any("论证假设" in s.body for s in analysis)
    assert any(s.qid == "1" for s in analysis)
