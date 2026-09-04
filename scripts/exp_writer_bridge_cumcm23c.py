#!/usr/bin/env python
"""【追溯】D-029 接桥实验脚本。正式入口请用：

  uv run math-agent run --problem problems/cumcm23-c/problem.json \\
    --brief problems/cumcm23-c/brief.json \\
    --from writer --evidence runs/cumcm23-c-reference/evidence.json \\
    --out runs/cumcm23-c-writer-graph

本脚本直调 writer_node，不经 LangGraph/checkpoint，仅作历史对照。
"""
from __future__ import annotations

import argparse
import json
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from math_agent.brief import load_brief
from math_agent.nodes.writer import render_markdown, writer_node, writer_section_node
from math_agent.state import (
    Assumption,
    CodeArtifact,
    MathModelingState,
    ModelVersion,
    ProblemBlueprint,
    SensitivityRun,
    SubQuestionBlueprint,
)


def _build_state(out_dir: Path) -> MathModelingState:
    problem = (ROOT / "problems/cumcm23-c/problem.md").read_text(encoding="utf-8")
    brief = load_brief(ROOT / "problems/cumcm23-c/brief.json")
    evidence = json.loads(
        (ROOT / "runs/cumcm23-c-reference/evidence.json").read_text(encoding="utf-8")
    )
    evidence_md = (ROOT / "runs/cumcm23-c-reference/data/evidence.md").read_text(
        encoding="utf-8"
    )
    # 语义卡进 stdout 尾部：writer 的 available_numbers 主要吃 Q/RESULT 行；
    # 额外把 evidence.md 关键行以 NOTE: 形式保留供人工对照（不进白名单提取也无妨）。
    q_block = "\n".join(evidence.get("q_lines") or [])
    stdout = (
        q_block
        + "\n\n# --- evidence.md (semantic bridge input) ---\n"
        + evidence_md[:12000]
    )

    assumptions = [
        Assumption(
            statement="净销量是需求代理；退货量级可忽略但仍声明口径【推断】",
            rationale="附件流水无库存/缺货标记",
            sensitivity_relevant=False,
        ),
        Assumption(
            statement="有界易腐：π=p·d̂−c·q，点预测下卖完代理需求【推断】",
            rationale="无报童参数可估",
            sensitivity_relevant=True,
        ),
        Assumption(
            statement="可售=窗内有销；一周成本用窗加权批发且一周不变【推断】",
            rationale="凌晨信息不完全",
            sensitivity_relevant=True,
        ),
        Assumption(
            statement="定价取近90非打折加成P50，不做弹性最优价【推断】",
            rationale="无稳定品类需求曲线",
            sensitivity_relevant=True,
        ),
    ]

    model = ModelVersion(
        stage="final",
        description=(
            "蔬菜补货定价：Q1分布与相关；Q2 BLEND需求+品类损耗+加成P50；"
            "Q3硬池去负毛利28SKU；Q4数据采集优先级。"
        ),
        equations=[
            r"\hat d_{\mathrm{BLEND}}(c,t)=\mathrm{WD90}(c,t)\times\frac{\mathrm{WIN7}(c)}{\mathrm{MU90}(c)}",
            r"q=\hat d/(1-\lambda),\quad p=\hat c(1+m_{P50}),\quad \pi=p\cdot\hat d-\hat c\cdot q",
        ],
        variables={
            "d_hat": "品类日需求预测",
            "q": "补货量",
            "lambda": "损耗率",
            "m_P50": "加成中位数",
            "pi": "有界收益代理",
        },
        notes="数字唯一来自 reference run / 研究 data；禁止编造。",
        objective_mapping=["品类周收益代理最大（有界）", "单品在27-33约束下收益代理"],
        constraint_mapping=["最小陈列2.5kg", "可售单品27-33", "单位可售毛利>0"],
        validation_mapping=["2023-04–06走步MAE", "加成P25/P75", "成本±20%", "硬池29对照"],
        question_coverage=[],
    )

    sens = [
        SensitivityRun(
            parameter="markup_percentile",
            values=[25.0, 50.0, 75.0],
            metric="week_profit",
            results=[2522.7113, 3502.5203, 5256.6165],
            interpretation="无弹性时冲高加成抬收益，属政策带选择非最优价。",
        ),
        SensitivityRun(
            parameter="cost_shock",
            values=[-0.2, 0.0, 0.2],
            metric="week_profit",
            results=[5526.140766740978, 3502.5203, 1478.8998376936163],
            interpretation="粘性售价下成本±20%使周收益大幅波动。",
        ),
    ]

    blueprint = ProblemBlueprint(
        core_task="蔬菜品类/单品补货与成本加成定价，信息不完全下可计算收益代理",
        subquestions=[
            SubQuestionBlueprint(
                id="1",
                original_text="分布规律与相互关系",
                task_type="explanation",
                expected_output="结构描述+非弹性对照",
            ),
            SubQuestionBlueprint(
                id="2",
                original_text="品类一周补货与定价",
                task_type="optimization",
                expected_output="日补货表+一周定价+收益",
            ),
            SubQuestionBlueprint(
                id="3",
                original_text="7月1日单品补货定价",
                task_type="optimization",
                expected_output="27-33内SKU方案",
            ),
            SubQuestionBlueprint(
                id="4",
                original_text="还应采集的数据",
                task_type="strategy",
                expected_output="按识别边界优先级",
            ),
        ],
    )

    return MathModelingState(
        problem=problem,
        brief=brief,
        assumptions=assumptions,
        model_versions=[model],
        problem_blueprint=blueprint,
        problem_domains=["operations_research", "retail", "perishable_inventory"],
        code_artifacts=[
            CodeArtifact(
                purpose="cumcm23-c reference/_entry (frozen)",
                code="# see problems/cumcm23-c/source/reference/_entry.py",
                stdout=stdout,
                success=True,
                evidence_role="primary",
                category="figure",
                batch=1,
            )
        ],
        sensitivity_runs=sens,
        data_dir=str(ROOT / "problems/cumcm23-c/source"),
        output_dir=str(out_dir),
        allow_coder_llm=False,
    )


def _apply(state: MathModelingState, delta: dict) -> MathModelingState:
    data = state.model_dump()
    for key, value in delta.items():
        data[key] = value
    return MathModelingState.model_validate(data)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-sections", type=int, default=0, help="0=全部7节")
    parser.add_argument(
        "--out",
        type=Path,
        default=ROOT / "runs/cumcm23-c-writer-bridge",
    )
    args = parser.parse_args()
    out: Path = args.out
    out.mkdir(parents=True, exist_ok=True)
    log_path = out / "experiment_log.md"
    lines: list[str] = [
        f"# writer 接桥实验 · {datetime.now(timezone.utc).isoformat()}",
        "",
        "目标：reference/evidence → state → writer_node → writer_section* → paper.md",
        "对照：`runs/cumcm23-c-reference/paper-prose.md`（会话轨 B）",
        "",
    ]

    state = _build_state(out)
    (out / "state_input.json").write_text(
        state.model_dump_json(indent=2), encoding="utf-8"
    )
    lines.append("## 1. state 构造 OK")
    lines.append(f"- code stdout chars: {len(state.code_artifacts[0].stdout)}")
    lines.append(f"- brief: {state.brief.problem_id if state.brief else None}")
    lines.append("")

    try:
        lines.append("## 2. writer_node（大纲）")
        delta = writer_node(state)
        state = _apply(state, delta)
        queue = list(state.writer_section_queue)
        lines.append(f"- queue: {queue}")
        lines.append(f"- writer_iteration: {state.writer_iteration}")
        (out / "outline.json").write_text(
            json.dumps(state.writer_outline_dump, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        lines.append("")

        if args.max_sections > 0:
            state = _apply(
                state, {"writer_section_queue": queue[: args.max_sections]}
            )
            lines.append(f"## 3. 分节（截断 max={args.max_sections}）")
        else:
            lines.append("## 3. 分节（全部）")

        while state.writer_section_queue:
            name = state.writer_section_queue[0]
            lines.append(f"- writing `{name}` …")
            log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            delta = writer_section_node(state)
            # list reducer 语义：节点返回新 queue；直接覆盖
            state = _apply(state, delta)
            lines.append(f"  done `{name}`; remaining={list(state.writer_section_queue)}")

        md = render_markdown(state)
        paper_path = out / "paper.md"
        paper_path.write_text(md, encoding="utf-8")
        lines.append("")
        lines.append(f"## 4. 产出 `{paper_path}` ({len(md)} chars)")
        (out / "state_final.json").write_text(
            state.model_dump_json(indent=2), encoding="utf-8"
        )
        lines.append("- status: **PASS**（writer 链跑完）")
        lines.append(
            "- 下一步人工：`check_paper_numbers --paper runs/cumcm23-c-writer-bridge/paper.md "
            "--evidence …` 对照 paper-prose.md"
        )
        rc = 0
    except Exception as exc:
        lines.append("")
        lines.append("## FAIL")
        lines.append(f"```\n{exc}\n```")
        lines.append("```\n" + traceback.format_exc() + "\n```")
        # 尽量落盘已有 paper 片段
        try:
            md = render_markdown(state)
            (out / "paper_partial.md").write_text(md, encoding="utf-8")
            lines.append(f"- partial paper chars: {len(md)}")
        except Exception:
            pass
        (out / "state_fail.json").write_text(
            state.model_dump_json(indent=2), encoding="utf-8"
        )
        rc = 1

    log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
