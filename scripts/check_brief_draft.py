"""检查 brief草稿.md 是否含 schema v2 对照章节（零 token；不冒充 brief check）。

示例：
  python scripts/check_brief_draft.py --problem problems/cumcm24-c
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REQUIRED_HEADINGS = (
    "per_question_direction",
    "data_notes",
    "red_lines",
    "formula_notes",
    "figure_plan",
    "background_knowledge",
    "required_discussions",
)


def check_draft(path: Path) -> list[str]:
    if not path.is_file():
        return [f"缺文件：{path}"]
    text = path.read_text(encoding="utf-8-sig").lower()
    missing: list[str] = []
    for h in REQUIRED_HEADINGS:
        # 接受 ## heading 或纯标题行
        if h.lower() not in text:
            missing.append(h)
    return missing


def main() -> None:
    parser = argparse.ArgumentParser(description="brief草稿章节存在性检查")
    parser.add_argument("--problem", type=Path, required=True)
    args = parser.parse_args()
    draft = args.problem.resolve() / "brief草稿.md"
    missing = check_draft(draft)
    if missing:
        print(f"[FAIL] {draft} 缺章节：{', '.join(missing)}")
        print("正式过闸仍是：uv run math-agent brief check --brief …/brief.json")
        sys.exit(1)
    print(f"[OK] {draft} 含对照章节（非正式门禁）")
    print("下一步：压成 brief.json → uv run math-agent brief check")


if __name__ == "__main__":
    main()
