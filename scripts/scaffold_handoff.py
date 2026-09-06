"""从题目录探测状态，生成交接-beacon.md 骨架（人闸默认未过）。

不覆盖已有交接文件，除非 --force。

示例：
  python scripts/scaffold_handoff.py --problem problems/cumcm24-c
"""
from __future__ import annotations

import argparse
from pathlib import Path


def _probe(problem: Path) -> dict[str, str]:
    slug = problem.name
    research_data = problem / "研究" / "data"
    n_data = (
        len(list(research_data.glob("*")))
        if research_data.is_dir()
        else 0
    )
    entry = problem / "source" / "reference" / "_entry.py"
    inject = problem / "source" / "inject" / "sensitivity.py"
    brief = problem / "brief.json"
    plan = problem / "plan.json"
    ledger = problem / "研究" / "_数据账.md"
    return {
        "slug": slug,
        "brief": "有" if brief.is_file() else "无",
        "plan": "有" if plan.is_file() else "无",
        "entry": "有" if entry.is_file() else "无",
        "inject": "有" if inject.is_file() else "无",
        "n_data": str(n_data),
        "ledger": "有" if ledger.is_file() else "无",
    }


def render(problem: Path) -> str:
    p = _probe(problem)
    slug = p["slug"]
    return f"""# {slug} · 交接：研究 → Beacon 操作

> 由 `scripts/scaffold_handoff.py` 生成骨架。人闸未真做过的写「未过」。  
> 模板原文：`全流程分析/全流程定稿/13附-交接文档模板.md`

## 0. 一句话状态

研究收束：☐；brief check：{p['brief']}；plan：{p['plan']}；`_entry`：{p['entry']}；inject：{p['inject']}；研究/data 文件数：{p['n_data']}；数据账：{p['ledger']}。当前卡点：（待填）

## 1. 磁盘真相（勿靠聊天记忆）

| 路径 | 含义 |
|---|---|
| `{slug}/_研究日志.md` 等 | 过程记忆 / 解题说明 / 经验与坑 / exploration |
| `{slug}/研究/_数据账.md` | 表→问→插座用途 |
| `{slug}/研究/{{scripts,data,figures}}/` | 实算；不是论文数字源 |
| `{slug}/source/reference/_entry.py` | 冻结主求解 |
| `{slug}/brief.json` / `plan.json` | 方向手柄 / 机读卡 |
| `runs/{slug}-reference/evidence.json` | 图外冒烟对账锚 |
| `{slug}/source/inject/sensitivity.py` | 图内敏感性重跑 |

## 2. 关键数（与 CSV/JSON 对齐）

| 关键数 | 值 | 出处 |
|---|---|---|
| （待填） | | `研究/data/…` |

## 3. 人闸记录

| 时间 | 谁 | 确认了什么 | 记录处 |
|---|---|---|---|
| — | — | **未过** | — |

## 4. 定稿站位

| 定稿站 | 状态 | 下一步 |
|---|---|---|
| 10 研究 | ☐ | |
| 11 brief | ☐ | brief check |
| 12 预检 | ☐ | dry-run |
| 14 plan与登记 | ☐ | plan check + add/run/verify |
| 15 启动图 | ☐ | `run --plan --out runs/{slug}-graph` |

## 5. 命令序（登记 → 启动图）

```text
uv run math-agent plan check --plan problems/{slug}/plan.json --brief problems/{slug}/brief.json
python scripts/check_plan_handfill.py --plan problems/{slug}/plan.json
uv run math-agent reference add --problem problems/{slug}/problem.json --solver problems/{slug}/source/reference --entry _entry.py --force
uv run math-agent reference run --problem problems/{slug}/problem.json --out runs/{slug}-reference
uv run math-agent reference verify --problem problems/{slug}/problem.json --evidence runs/{slug}-reference/evidence.json
uv run math-agent reference recertify --problem problems/{slug}/problem.json --evidence runs/{slug}-reference/evidence.json --actor "<谁>" --notes "人闸见第3节" --verdict pass

uv run math-agent run --problem problems/{slug}/problem.json --brief problems/{slug}/brief.json --plan problems/{slug}/plan.json --out runs/{slug}-graph
```

改代码后必须再 `add --force`。改 plan/brief 后新开 `--out`（如 `runs/{slug}-graph-r2`）。

## 6. 已知缺口

- （待填）

## 7. 禁止

- 首枪 `--from writer`；手抄研究敏感数字进论文；只读研究摘要不 open 附件。

## 8. 可粘贴开工白

```text
读 problems/{slug}/交接-beacon.md → brief.json → 研究/_数据账.md → 按第5节命令序执行。
人闸第3节未过则先做人抽查再 recertify。
```
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="生成交接-beacon.md 骨架")
    parser.add_argument("--problem", type=Path, required=True)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    problem = args.problem.resolve()
    if not problem.is_dir():
        raise SystemExit(f"无题目目录：{problem}")
    dest = problem / "交接-beacon.md"
    if dest.exists() and not args.force:
        print(f"skip {dest}（已有；--force 覆盖）")
        return
    dest.write_text(render(problem), encoding="utf-8")
    print(f"write {dest}")
    print("[OK] 人闸默认未过；填关键数与站位后再登记。")


if __name__ == "__main__":
    main()
