# -*- coding: utf-8 -*-
from pathlib import Path
import ast

p = Path(r"e:\git_clone\Beacon\src\math_agent\nodes\latex_node.py")
text = p.read_text(encoding="utf-8")


def cut(a, b):
    global text
    i = text.index(a)
    j = text.index(b, i)
    text = text[:i] + text[j:]


# 1. 删除 _refresh_verified_cost_figure（BREAKDOWN 成本构成重绘，物流专属）
cut("def _refresh_verified_cost_figure(", "def _verified_comparison_figure(")

# 2. _verified_comparison_figure：删除 Q1/Q2 政策情景块
old = '''    upper_bound = infer_entity_upper_bound(state.data_files)
    primary = next((
        artifact for artifact in reversed(state.latest_code_artifacts())
        if artifact.success
        and artifact.evidence_role == "primary"
        and "BEACON_GREEN_LOGISTICS_SAFE_SOLVER" in artifact.code
    ), None)

'''
assert old in text
text = text.replace(old, "    upper_bound = infer_entity_upper_bound(state.data_files)\n", 1)

i = text.index("    # 绿色物流题的正文核心比较是 Q1 无政策与 Q2 限行政策。")
j = text.index("    rows: list[tuple[str, dict[str, float]]] = []", i)
text = text[:i] + text[j:]

# 3. 删除 _green_publication_stdout
cut("def _green_publication_stdout(", "def latex_node(")

# 4. latex_node 内的 green 分支
old = '''    formal_sens = _latest_sensitivity_runs(state)
    if _has_green_safe_solver(state):
        formal_sens = [
            run.model_copy(update={
                "figure_path": _render_verified_figure(
                    run, Path(run.figure_path).resolve().parent
                ) if run.figure_path else run.figure_path,
            })
            for run in formal_sens
        ]
    formal_figures = _formal_figures(state, formal_sens)
    _refresh_verified_cost_figure(state, formal_figures)
'''
new = '''    formal_sens = _latest_sensitivity_runs(state)
    formal_figures = _formal_figures(state, formal_sens)
'''
assert old in text
text = text.replace(old, new, 1)

old = '''            # The verified green-logistics paper already derives its complete
            # sensitivity interpretation from the numeric arrays. Do not
            # append older free-form model prose a second time.
            interpretation=(
                "" if _has_green_safe_solver(state)
                else _prepare_section(r.interpretation)
            ),
'''
new = '''            interpretation=_prepare_section(r.interpretation),
'''
assert old in text
text = text.replace(old, new, 1)

old = '''    title_line = (
        "多约束异构车队绿色配送与动态局部重调度"
        if _has_green_safe_solver(state)
        else state.problem.split("\\n", 1)[0].strip()
    )
'''
new = '''    title_line = state.problem.split("\\n", 1)[0].strip()
'''
assert old in text
text = text.replace(old, new, 1)

old = '''        appendix_title=(
            "计算证据摘要" if _has_green_safe_solver(state) else "关键算法代码"
        ),
'''
new = '''        appendix_title="关键算法代码",
'''
assert old in text
text = text.replace(old, new, 1)

old = '''                "purpose": _prepare_inline_text(
                    "主方案结构化运行结果"
                    if _has_green_safe_solver(state) else a.purpose
                ),
'''
new = '''                "purpose": _prepare_inline_text(a.purpose),
'''
assert old in text
text = text.replace(old, new, 1)

old = '''                "curated_code": (
                    "" if _has_green_safe_solver(state)
                    else _curate_code(a.code, max_lines=55)
                ),
                "curated_stdout": (
                    _green_publication_stdout(a.stdout)
                    if _has_green_safe_solver(state) else _curate_stdout(a.stdout)
                ),
'''
new = '''                "curated_code": _curate_code(a.code, max_lines=55),
                "curated_stdout": _curate_stdout(a.stdout),
'''
assert old in text
text = text.replace(old, new, 1)

old = '''    # 始终也写一份 Markdown，作为降级 / 备查。它必须与 TeX 使用同一组最新正式
    # 图和敏感性证据，不能重新渲染 append-only 历史。绿色物流安全求解器的完整
    # 敏感性解释已经由 paper.sensitivity 从数值数组确定性生成，不重复追加自由文本。
    markdown_sens = [
        run.model_copy(update={
            "interpretation": "" if _has_green_safe_solver(state) else run.interpretation,
        })
        for run in formal_sens
    ]
    (workdir / "paper.md").write_text(
        render_markdown(
            state,
            figures=formal_figures,
            sensitivity_runs=markdown_sens,
            problem_override=title_line,
        ),
        encoding="utf-8",
    )
'''
new = '''    # 始终也写一份 Markdown，作为降级 / 备查。它必须与 TeX 使用同一组最新正式
    # 图和敏感性证据，不能重新渲染 append-only 历史。
    (workdir / "paper.md").write_text(
        render_markdown(
            state,
            figures=formal_figures,
            sensitivity_runs=formal_sens,
            problem_override=title_line,
        ),
        encoding="utf-8",
    )
'''
assert old in text
text = text.replace(old, new, 1)

ast.parse(text)
p.write_text(text, encoding="utf-8")
print("ok")
import re
for n, line in enumerate(text.splitlines(), 1):
    if re.search(r"green|GREEN|物流|限行|绿色|_has_green|_render_verified_figure", line, re.IGNORECASE):
        print(n, line.strip()[:120])
