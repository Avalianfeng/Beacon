# -*- coding: utf-8 -*-
from pathlib import Path
import ast

p = Path(r"e:\git_clone\Beacon\src\math_agent\nodes\paper_evidence.py")
text = p.read_text(encoding="utf-8")


def cut(a, b):
    global text
    i = text.index(a)
    j = text.index(b, i)
    text = text[:i] + text[j:]


# 删除未再使用的 _contains_number 与 _contains_number_near
cut("def _contains_number(body: str", "def _contains_number_after_label(")
# 删除未再使用的 _contains_number_before_label
cut("def _contains_number_before_label(", "def offline_evidence_issues(")

text = text.replace(
    "from math_agent.nodes.sensitivity import (\n"
    "    formal_sensitivity_issues,\n"
    "    formal_sensitivity_runs,\n"
    ")\n",
    "from math_agent.nodes.sensitivity import formal_sensitivity_issues\n",
    1,
)
text = text.replace(
    "from math_agent.state import MathModelingState, SensitivityRun\n",
    "from math_agent.state import MathModelingState\n",
    1,
)
ast.parse(text)
p.write_text(text, encoding="utf-8")
print("ok")
