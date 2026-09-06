"""为题目脚手架研究会话目录与收束空壳（学-39）。

示例：
  python scripts/scaffold_research.py --problem problems/cumcm24-c
"""
from __future__ import annotations

import argparse
from pathlib import Path

DATA_LEDGER = """# 研究 · 数据账

> 对标外部 `_共享/切片/_索引.md`：表多时回答「哪张表喂哪问、进不进 `_entry`」。

| 表ID | 路径 | 服务哪问 | 口径一句话 | 用途 |
|---|---|---|---|---|
| （尚无） | `研究/data/…` | Q? | | `_entry` 重读 / 仅定 inject 网格 / 仅人读 |

规则：新表落盘后登记本表；写 `_entry`/inject 前先对账。
"""

LOG_MD = """# _研究日志

| 时间 | 问题 | 做了什么 | 结果 | 认识变化 | 下一步 |
|---|---|---|---|---|---|
| | 从 Diff 续跑开工 | | | 工作假设：（带来源：本地 / 外部-Vn / Diff拍板） | |
"""

SOLVE_MD = """# 解题说明

> 非论文体。Q1–Qn 交代实际方向与验证。

## Q1
## Q2
## Q3
## Q4
"""

PITS_MD = """# 经验与坑

- （可复用失败与口径坑）
"""

EXPLORATION_MD = """# exploration（人读收束）

> 与 brief草稿同期；不是对撞地图。

## 稳定认识
## 证据要点（指向 研究/data）
## 可被推翻
"""

BRIEF_DRAFT_MD = """# brief草稿

> **最后**生成。下列标题与 `brief.json`（schema v2）对照；正式过闸是 `math-agent brief check`，本草稿检查只做章节存在性。

## per_question_direction
<!-- → brief.json per_question_direction -->

## data_notes
<!-- → data_notes -->

## red_lines
<!-- → red_lines + redline_rules（人认） -->

## formula_notes
<!-- → formula_notes -->

## figure_plan
<!-- → figure_plan -->

## background_knowledge
<!-- → background_knowledge -->

## required_discussions
<!-- → required_discussions -->

## scoring_notes（可选）
<!-- → scoring_notes -->
"""

SCRIPTS_README = """# 研究/scripts

研究用脚本放这里。目标是「算明白」，**不必**与 `_entry` 同构。
收束后对照 `../_数据账.md` 写插座（`scripts/scaffold_entry.py`）。
"""


def _write(path: Path, text: str, *, force: bool) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not force:
        return f"skip {path}"
    body = text if text.endswith("\n") else text + "\n"
    path.write_text(body, encoding="utf-8")
    return f"write {path}"


def scaffold(problem: Path, *, force: bool) -> list[str]:
    logs: list[str] = []
    research = problem / "研究"
    for sub in ("scripts", "data", "figures"):
        d = research / sub
        d.mkdir(parents=True, exist_ok=True)
        keep = d / ".gitkeep"
        if not keep.exists():
            keep.write_text("", encoding="utf-8")
            logs.append(f"mkdir {d}")
    logs.append(_write(research / "scripts" / "README.md", SCRIPTS_README, force=force))
    logs.append(_write(research / "_数据账.md", DATA_LEDGER, force=force))
    logs.append(_write(problem / "_研究日志.md", LOG_MD, force=force))
    logs.append(_write(problem / "解题说明.md", SOLVE_MD, force=force))
    logs.append(_write(problem / "经验与坑.md", PITS_MD, force=force))
    logs.append(_write(problem / "exploration.md", EXPLORATION_MD, force=force))
    logs.append(_write(problem / "brief草稿.md", BRIEF_DRAFT_MD, force=force))
    return logs


def main() -> None:
    parser = argparse.ArgumentParser(description="脚手架研究会话目录与收束空壳")
    parser.add_argument("--problem", type=Path, required=True)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    problem = args.problem.resolve()
    if not problem.is_dir():
        raise SystemExit(f"题目目录不存在：{problem}")
    for line in scaffold(problem, force=args.force):
        print(line)
    print("[OK] 研究脚手架就绪。收束后：填 _数据账 → 压 brief.json → 再 13/14。")
    print(f"  草稿检查：python scripts/check_brief_draft.py --problem {problem}")


if __name__ == "__main__":
    main()
