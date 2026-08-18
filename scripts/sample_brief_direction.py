"""brief 方向/红线抽样检查脚本（只读，不调 LLM）。

对应 docs/12-ModelingBrief验证与下一步.md 第四节 4.2 清单：
对一次 run 的产物做"方向是否落地 / 红线是否被触碰"的关键词抽样，
输出 命中/未命中 + file:line 证据。脚本只收集证据，最终判定由人做
（"源头杜绝方向错成立" = 抽样方向在代码与论文中可指认）。

用法:
  python scripts/sample_brief_direction.py <run_dir> [--brief-source <brief.json>]

证据范围（自动发现，均只读）:
  - 论文: paper.md / paper.tex / paper_preview*.md
  - 评审摘要: insights/*.md
  - 代码: run_dir 下所有 *.py（fig_*/sensitivity/attempt 等）
  - 状态: final_state.json / state_summary.json
  - 蓝图: checkpoints.sqlite 中任一含 brief_coverage / ProblemBlueprint 的 JSON 文本
  - brief 副本: <run_dir>/brief.json（与 --brief-source 比对 sha256，有则输出）

--brief-source 存在时额外输出:
  - brief 副本一致性（sha256 是否一致）
  - brief_coverage 完整性（39 个 id 中 followed/deviated/缺失 各多少）

抽样检查项（对照 iteration-plan 第四节"代码思路更迭清单"）:
  1.2-change-point  1.2 变点检测/分段回归 是否出现
  2.2-fbond-hole    F_bond 用钻孔直径（D_hole/28/30mm）是否出现
  3.1-washer        3.1 调心垫圈定量（233%/404.97/e_cr≈3.66）是否出现
  redline-60071    红线: 600.71 出现次数（出现≠违反，需看上下文）
  redline-topt-08  红线: T_opt=0.8·T_max 出现次数（出现≠违反，需看上下文）

退出码: 0 = 完成（无论命中与否）；任何异常 = 非 0。
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import sys
from pathlib import Path

CHECKS: list[dict] = [
    {
        "id": "1.2-change-point",
        "desc": "1.2 变点检测/分段回归",
        "patterns": [r"变点", r"分段", r"piecewise", r"changepoint",
                     r"change[ _-]?point", r"网格搜索", r"grid[ _-]?search",
                     r"T_c\b", r"T\s*=\s*[abAB]"],
        "scope": ["paper", "blueprint", "code"],
    },
    {
        "id": "2.2-fbond-hole",
        "desc": "F_bond 用钻孔直径（D_hole / 28/30mm）",
        "patterns": [r"D_hole", r"D\s*[hH]ole", r"钻孔直径", r"钻孔", r"\b28\s*mm", r"\b30\s*mm"],
        "scope": ["paper", "code"],
    },
    {
        "id": "3.1-washer",
        "desc": "3.1 调心垫圈定量（233% / 404.97 / e_cr≈3.66）",
        "patterns": [r"调心", r"垫圈", r"233", r"404\.97", r"121\.74", r"e_cr", r"3\.66"],
        "scope": ["paper", "blueprint"],
    },
    {
        "id": "redline-60071",
        "desc": "红线：600.71 出现（出现≠违反，看上下文）",
        "patterns": [r"600\.71"],
        "scope": ["paper", "code"],
    },
    {
        "id": "redline-topt-08",
        "desc": "红线：T_opt=0.8·T_max 出现（出现≠违反，看上下文）",
        "patterns": [r"T_opt.*0\.8", r"0\.8.*T_max", r"T_opt\s*=\s*0\.8", r"0\.8\s*·\s*T"],
        "scope": ["paper", "code"],
    },
]


def _iter_text_files(run_dir: Path) -> list[tuple[str, Path]]:
    """返回 (类别, 路径) 列表：paper / insights / code / state。"""
    found: list[tuple[str, Path]] = []
    for p in run_dir.rglob("*"):
        if not p.is_file():
            continue
        name = p.name.lower()
        if name in ("paper.md", "paper.tex") or name.startswith("paper_preview"):
            found.append(("paper", p))
        elif p.name.startswith("insights") or "insights" in p.parts:
            found.append(("insights", p))
        elif name.endswith(".py"):
            found.append(("code", p))
        elif name in ("final_state.json", "state_summary.json"):
            found.append(("state", p))
    return found


def _read_ok(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _extract_blueprint_text(run_dir: Path) -> str:
    """从 checkpoints.sqlite 尽力提取含 brief_coverage / 蓝图的 JSON 文本。"""
    db = run_dir / "checkpoints.sqlite"
    if not db.is_file():
        return ""
    texts: list[str] = []
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            for (t,) in con.execute(
                "select name from sqlite_master where type='table'"
            ):
                try:
                    cols = [r[1] for r in con.execute(f"pragma table_info({t})")]
                except sqlite3.Error:
                    continue
                for col in cols:
                    try:
                        rows = con.execute(
                            f"select {col} from {t} where {col} like '%brief%' "
                            f"or {col} like '%blueprint%' or {col} like '%ProblemBlueprint%'"
                        ).fetchall()
                    except sqlite3.Error:
                        continue
                    for (v,) in rows:
                        if isinstance(v, (str, bytes)):
                            s = v.decode("utf-8", "replace") if isinstance(v, bytes) else v
                            if any(k in s for k in ("brief_coverage", "ProblemBlueprint",
                                                    "core_task", "blueprint")):
                                texts.append(s)
        finally:
            con.close()
    except sqlite3.Error:
        return ""
    return "\n".join(texts)


def _coverage_from_checkpoint(run_dir: Path) -> dict[str, str] | None:
    """从 checkpoint 正规读取 brief_coverage（msgpack 序列化，文本正则不可靠）。

    checkpoint 的 state 经 JsonPlusSerializer 序列化，直接扫文本是乱码；
    这里用仓库自己的 sqlite_saver + graph 反序列化，读 problem_blueprint.brief_coverage。
    thread 从 run_manifest.json 取（默认 default）。
    """
    db = run_dir / "checkpoints.sqlite"
    if not db.is_file():
        return None
    thread = "default"
    try:
        manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
        thread = str(manifest.get("thread", "default"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        pass
    try:
        from math_agent import cli as c
        from math_agent.checkpointing import sqlite_saver
        with sqlite_saver(db) as saver:
            g = c.build_graph(checkpointer=saver, interrupt_before=[])
            snap = g.get_state(c._config(thread))
            bp = snap.values.get("problem_blueprint")
            if bp is None:
                return None
            return {item.brief_item_id: item.status for item in (bp.brief_coverage or [])}
    except Exception as exc:  # noqa: BLE001 - 只读工具，失败降级
        print(f"[warn] checkpoint 正规读取失败（{type(exc).__name__}: {exc}），退回文本扫描")
        return None


def _brief_coverage_report(run_dir: Path, brief_source: Path | None) -> list[str]:
    lines: list[str] = []
    brief_copy = run_dir / "brief.json"
    if brief_source is not None and brief_copy.is_file():
        h1 = hashlib.sha256(brief_source.read_bytes()).hexdigest()
        h2 = hashlib.sha256(brief_copy.read_bytes()).hexdigest()
        lines.append(f"brief 副本: {brief_copy} sha256={'一致' if h1 == h2 else '不一致!'}")
        lines.append(f"  源文件 sha256: {h1}")
        lines.append(f"  副本   sha256: {h2}")
    elif brief_copy.is_file():
        lines.append(f"brief 副本: {brief_copy}（未提供 --brief-source，跳过一致性比对）")
    else:
        lines.append("brief 副本: 未找到 <run_dir>/brief.json")

    try:
        brief = json.loads(brief_copy.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return lines

    ids: list[str] = []
    for field in ("per_question_direction", "formula_notes", "required_discussions",
                  "red_lines", "figure_plan", "scoring_notes", "data_notes"):
        for item in brief.get(field, []):
            if isinstance(item, dict) and item.get("id"):
                ids.append(item["id"])

    covered = _coverage_from_checkpoint(run_dir)
    if covered is None:
        blob = _extract_blueprint_text(run_dir)
        if not blob:
            lines.append(f"brief_coverage: 未在 checkpoint 中找到含 brief_coverage 的状态（{len(ids)} 个 id 无法核对）")
            return lines
        covered = {}
        for m in re.finditer(r'"brief_item_id"\s*:\s*"([^"]+)"\s*,\s*"status"\s*:\s*"([^"]+)"', blob):
            covered[m.group(1)] = m.group(2)
    missing = [i for i in ids if i not in covered]
    deviated = [i for i, s in covered.items() if s == "deviated"]
    followed = [i for i, s in covered.items() if s == "followed"]
    lines.append(
        f"brief_coverage: 共 {len(ids)} 个 id；followed={len(followed)} "
        f"deviated={len(deviated)} 缺失={len(missing)}"
    )
    if missing:
        lines.append(f"  缺失 id: {', '.join(missing)}")
    if deviated:
        lines.append(f"  deviated id: {', '.join(deviated)}")
    return lines


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    run_dir = Path(argv[1])
    brief_source = None
    if "--brief-source" in argv:
        i = argv.index("--brief-source")
        if i + 1 < len(argv):
            brief_source = Path(argv[i + 1])
    if not run_dir.is_dir():
        print(f"[ERROR] run 目录不存在: {run_dir}")
        return 2

    files = _iter_text_files(run_dir)
    blueprint_text = _extract_blueprint_text(run_dir)

    print(f"== 抽样 run: {run_dir}")
    print(f"证据文件: paper={sum(1 for k, _ in files if k == 'paper')} "
          f"insights={sum(1 for k, _ in files if k == 'insights')} "
          f"code={sum(1 for k, _ in files if k == 'code')} "
          f"state={sum(1 for k, _ in files if k == 'state')} "
          f"blueprint(checkpoint)={'有' if blueprint_text else '无'}")
    print()

    for check in CHECKS:
        patterns = [re.compile(p) for p in check["patterns"]]
        hits: list[str] = []
        scope = check["scope"]
        for kind, path in files:
            if kind not in scope:
                continue
            text = _read_ok(path)
            if not text:
                continue
            for ln, line in enumerate(text.splitlines(), 1):
                if any(pat.search(line) for pat in patterns):
                    snippet = line.strip()[:120]
                    hits.append(f"  {path.relative_to(run_dir)}:{ln}  {snippet}")
                    if len(hits) >= 6:
                        break
            if len(hits) >= 6:
                break
        if "blueprint" in scope and blueprint_text:
            for ln, line in enumerate(blueprint_text.splitlines(), 1):
                if any(pat.search(line) for pat in patterns):
                    snippet = line.strip()[:120]
                    hits.append(f"  [checkpoint-blueprint] 行{ln}  {snippet}")
                    if len(hits) >= 6:
                        break
        verdict = f"命中 {len(hits)} 处（是否真落地需人工看上下文，如 r11 论文自认\"未实现\"）" if hits else "无命中（方向未见落地 / 未触碰）"
        if check["id"].startswith("redline"):
            verdict = f"出现 {len(hits)} 处（需人工看上下文判定是否违反）" if hits else "无出现（未触碰）"
        print(f"[{check['id']}] {check['desc']}")
        print(f"  判定: {verdict}")
        for h in hits:
            print(h)
        print()

    print("== brief 副本与 coverage ==")
    for line in _brief_coverage_report(run_dir, brief_source):
        print(line)
    print()
    print("说明: 本脚本只做关键词证据收集；方向是否落地、红线是否违反的最终判定由人按")
    print("docs/12-ModelingBrief验证与下一步.md 4.3 的语言做（管道成立/防忽略成立/源头杜绝成立）。")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
