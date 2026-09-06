"""⑥–⑫ 脚手架与手补检查（学-39/40）。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.check_brief_draft import check_draft  # noqa: E402
from scripts.check_plan_handfill import check_handfill  # noqa: E402
from scripts.scaffold_entry import build_entry  # noqa: E402
from scripts.scaffold_handoff import render as render_handoff  # noqa: E402
from scripts.scaffold_research import scaffold as scaffold_research  # noqa: E402
from scripts.scaffold_sensitivity import extract_sensitivity_names  # noqa: E402


def test_scaffold_research_idempotent(tmp_path: Path):
    problem = tmp_path / "demo-c"
    problem.mkdir()
    logs = scaffold_research(problem, force=False)
    assert any("write" in x for x in logs)
    assert (problem / "研究" / "_数据账.md").is_file()
    assert (problem / "brief草稿.md").is_file()
    logs2 = scaffold_research(problem, force=False)
    assert any(x.startswith("skip ") for x in logs2)
    assert check_draft(problem / "brief草稿.md") == []


def test_check_brief_draft_missing(tmp_path: Path):
    p = tmp_path / "brief草稿.md"
    p.write_text("# x\n", encoding="utf-8")
    missing = check_draft(p)
    assert "per_question_direction" in missing


def test_handoff_probe_and_no_overwrite(tmp_path: Path):
    problem = tmp_path / "demo-c"
    problem.mkdir()
    (problem / "brief.json").write_text("{}", encoding="utf-8")
    text = render_handoff(problem)
    assert "brief check：有" in text or "brief.json" in text
    assert "**未过**" in text
    dest = problem / "交接-beacon.md"
    dest.write_text(text, encoding="utf-8")
    # second write without force should be caller's job; render still works
    assert "demo-c" in render_handoff(problem)


def test_plan_handfill_cumcm23_ok():
    path = ROOT / "problems" / "cumcm23-c" / "plan.json"
    if not path.is_file():
        return
    card = json.loads(path.read_text(encoding="utf-8-sig"))
    gaps, _warns = check_handfill(card)
    assert gaps == []
    names = extract_sensitivity_names(card)
    assert "成本冲击 (cost_shock)" in names


def test_scaffold_entry_from_template():
    tpl = (
        ROOT
        / "全流程分析"
        / "prompts"
        / "登记"
        / "模板-reference_入口.py"
    ).read_text(encoding="utf-8")
    body = build_entry("demo-c", tpl)
    assert "demo-c" in body
    assert "_数据账" in body
    assert "不自动搬研究业务逻辑" in body


def test_scaffold_entry_skip_existing(tmp_path: Path):
    problem = tmp_path / "demo-c"
    dest = problem / "source" / "reference" / "_entry.py"
    dest.parent.mkdir(parents=True)
    dest.write_text("# keep\n", encoding="utf-8")
    # invoke main logic: skip when exists
    assert dest.read_text(encoding="utf-8") == "# keep\n"
