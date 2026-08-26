# -*- coding: utf-8 -*-
from pathlib import Path
import ast, re

p = Path(r"e:\git_clone\Beacon\src\math_agent\nodes\sensitivity.py")
text = p.read_text(encoding="utf-8")


def cut(start_anchor: str, end_anchor: str) -> None:
    global text
    i = text.index(start_anchor)
    j = text.index(end_anchor, i)
    text = text[:i] + text[j:]


# 1. formal_sensitivity_issues：删除二维契约，只保留中心同源校验
i = text.index("def formal_sensitivity_issues(")
j = text.index("_SENSITIVITY_LABELS = {")
text = text[:i] + '''def formal_sensitivity_issues(state: MathModelingState) -> list[str]:
    """校验正式敏感性证据：中心点必须与正式主方案同源。"""
    formal = formal_sensitivity_runs(state)
    if not formal:
        return ["缺少有效敏感性分析结果"]
    alignment = _center_alignment_error(formal, _canonical_primary(state)[1])
    return [alignment] if alignment else []


''' + text[j:]

# 2. 删除绿色物流标签/标题字典
cut("_SENSITIVITY_LABELS = {", "def _render_verified_figure(")
text = text.replace(
    '''    x_label, y_label = _SENSITIVITY_LABELS.get(
        run.parameter,
        (fallback_parameter, fallback_metric),
    )
''',
    "    x_label, y_label = fallback_parameter, fallback_metric\n",
    1,
)
text = text.replace(
    "    title = _SENSITIVITY_TITLES.get(run.parameter, fallback_parameter)\n",
    "    title = fallback_parameter\n",
    1,
)

# 3. _render_verified_figure：删除二维组合编码热力图分支
i = text.index('    if "二维组合编码" in run.parameter and len(values) == 9:')
j = text.index("    center = len(values) // 2", i)
text = text[:i] + text[j:]

# 4. 删除 _interaction_interpretation
cut("def _interaction_interpretation(", "def _build_sensitivity_template_code(")
old = '''    for run, text in zip(aligned, interpretations):
        run.interpretation = (
            _interaction_interpretation(run)
            if "二维组合编码" in run.parameter and len(run.results) == 9
            else text
        )
'''
new = '''    for run, text in zip(aligned, interpretations):
        run.interpretation = text
'''
assert old in text
text = text.replace(old, new, 1)

# 5. 删除 _build_canonical_replay_code / _is_green_replay_parameter / _should_use_canonical_replay
cut("def _build_canonical_replay_code(", "def _use_deterministic_sensitivity(")
old = '''    elif _should_use_canonical_replay(
        plan, main_code, previous_error=state.sensitivity_code_error,
    ):
        code_out = SensitivityCode(code=_build_canonical_replay_code(plan, main_code))
    else:
'''
new = '''    else:
'''
assert old in text
text = text.replace(old, new, 1)

# 6. sensitivity_plan_node：删除强制计划与参数规范化
old_start = '    main_code, _ = _canonical_primary(state)\n'
i = text.index(old_start, text.index("def sensitivity_plan_node("))
j = text.index('    if not plan.runs:', i)
text = text[:i] + text[j:]

# 7. sensitivity_code_execute_node：删除旧版双情景重放兼容
old = '''    # 兼容已在 checkpoint 中持久化的旧版双情景重放代码：恢复时从正式主
    # artifact 重新构造 Q2-only 扫参源码，避免继续执行已知会超时的 18 次求解。
    if "SCENARIO_BEGIN: q1_no_policy" in code_to_run:
        main_code, _ = _canonical_primary(state)
        if main_code:
            code_to_run = _build_canonical_replay_code(plan, main_code)
'''
assert old in text
text = text.replace(old, "", 1)

ast.parse(text)
p.write_text(text, encoding="utf-8")
print("ok; remaining refs:")
for n, line in enumerate(text.splitlines(), 1):
    if re.search(r"green|GREEN|物流|限行|二维组合|燃油|绿色", line, re.IGNORECASE):
        print(n, line.strip()[:120])
print("math used:", bool(re.search(r"\bmath\.", text)))
