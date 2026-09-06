"""从登记模板生成题级 _entry.py（不覆盖除非 --force）。

示例：
  python scripts/scaffold_entry.py --problem problems/cumcm24-c
"""
from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "全流程分析" / "prompts" / "登记" / "模板-reference_入口.py"


def build_entry(slug: str, template_text: str) -> str:
    text = template_text.replace("<题ID>", slug)
    # 模板在 coding 行之后才有 docstring
    text = text.replace(
        "数值从 研究/data 重读（研究已算）；附件只做血缘触碰；执行 cwd 落 PNG。",
        "数值从 研究/data 重读（对照 研究/_数据账.md）；"
        "必须另 open 声明附件做血缘；cwd 落 PNG。"
        "脚手架不自动搬研究业务逻辑。",
        1,
    )
    if "对照 研究/_数据账.md" not in text:
        text = text.replace(
            'DATA = ROOT / "研究" / "data"',
            'DATA = ROOT / "研究" / "data"  # 对照 研究/_数据账.md',
            1,
        )
    return text


def main() -> None:
    parser = argparse.ArgumentParser(description="脚手架 source/reference/_entry.py")
    parser.add_argument("--problem", type=Path, required=True)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    problem = args.problem.resolve()
    if not problem.is_dir():
        raise SystemExit(f"无题目目录：{problem}")
    if not TEMPLATE.is_file():
        raise SystemExit(f"无模板：{TEMPLATE}")
    dest = problem / "source" / "reference" / "_entry.py"
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and not args.force:
        print(f"skip {dest}（已有；--force 覆盖）")
        return
    body = build_entry(problem.name, TEMPLATE.read_text(encoding="utf-8"))
    dest.write_text(body if body.endswith("\n") else body + "\n", encoding="utf-8")
    print(f"write {dest}")
    print("[OK] 填 TODO：读数据账 → 打 Q/RESULT 行；登记前 reference add --force")
    print(
        "  uv run math-agent reference add "
        f"--problem {problem}/problem.json "
        f"--solver {problem}/source/reference --entry _entry.py --force"
    )


if __name__ == "__main__":
    main()
