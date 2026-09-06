"""生成 source/inject/sensitivity.py；若有 plan.json 则预填 sensitivity 参数名。

示例：
  python scripts/scaffold_sensitivity.py --problem problems/cumcm24-c
  python scripts/scaffold_sensitivity.py --problem problems/cumcm23-c
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "全流程分析" / "prompts" / "登记" / "模板-sensitivity.py"

PARAM_RE = re.compile(r"参数名必须用\s*([^，,；;]+)")
PAREN_RE = re.compile(r"（([^）]+)）|\(([^)]+)\)")


def extract_sensitivity_names(plan: dict) -> list[str]:
    names: list[str] = []
    for a in plan.get("assumptions") or []:
        if not isinstance(a, dict) or not a.get("sensitivity_relevant"):
            continue
        stmt = str(a.get("statement") or "")
        m = PARAM_RE.search(stmt)
        if m:
            names.append(m.group(1).strip())
            continue
        # 退而求其次：取中文名+(英文) 片段
        pm = PAREN_RE.search(stmt)
        if pm:
            eng = pm.group(1) or pm.group(2)
            # 试图取括号前短名
            head = stmt[: pm.start()].strip()
            chunk = head.split("：")[-1].split(":")[-1].strip()
            if chunk and eng:
                names.append(f"{chunk} ({eng})" if "（" not in chunk and "(" not in chunk else chunk)
            else:
                names.append(eng)
    # 去重保序
    seen: set[str] = set()
    out: list[str] = []
    for n in names:
        if n not in seen:
            seen.add(n)
            out.append(n)
    return out


def build_body(slug: str, template: str, param_names: list[str]) -> str:
    text = template.replace("<题ID>", slug)
    banner = (
        f'"""{slug} · 图内敏感性插座（inject/sensitivity.py）。\n\n'
        "契约：全流程分析/prompts/登记/契约-代码插座.md\n"
        "按研究网格重算；参数名须与 plan assumptions（sensitivity_relevant）钉死一致。\n"
        "对照 研究/_数据账.md 定网格；不手抄研究 CSV 敏感数字。\n"
        '"""\n'
    )
    text = re.sub(r'^"""[\s\S]*?"""\n', banner, text, count=1)
    if param_names:
        lines = [
            "",
            "# --- 自 plan.json 解析的参数名（网格值请人填）---",
            "PARAM_NAMES = [",
        ]
        for n in param_names:
            lines.append(f"    {n!r},")
        lines.append("]")
        lines.append("# 例：_emit(PARAM_NAMES[0], values, results)")
        lines.append("")
        text = text.rstrip() + "\n" + "\n".join(lines) + "\n"
    return text


def main() -> None:
    parser = argparse.ArgumentParser(description="脚手架 inject/sensitivity.py")
    parser.add_argument("--problem", type=Path, required=True)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    problem = args.problem.resolve()
    if not problem.is_dir():
        raise SystemExit(f"无题目目录：{problem}")
    if not TEMPLATE.is_file():
        raise SystemExit(f"无模板：{TEMPLATE}")
    dest = problem / "source" / "inject" / "sensitivity.py"
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and not args.force:
        print(f"skip {dest}（已有；--force 覆盖）")
        return
    names: list[str] = []
    plan_path = problem / "plan.json"
    if plan_path.is_file():
        names = extract_sensitivity_names(
            json.loads(plan_path.read_text(encoding="utf-8-sig"))
        )
        print(f"[plan] sensitivity 参数名：{names or '（未解析到）'}")
    body = build_body(problem.name, TEMPLATE.read_text(encoding="utf-8"), names)
    dest.write_text(body if body.endswith("\n") else body + "\n", encoding="utf-8")
    print(f"write {dest}")
    print("[OK] 填网格并 _emit；缺本文件则 run --plan 敏感性节点停机")


if __name__ == "__main__":
    main()
