# -*- coding: utf-8 -*-
from pathlib import Path
import ast

p = Path(r"e:\git_clone\Beacon\src\math_agent\nodes\model_code_consistency.py")
text = p.read_text(encoding="utf-8")
i = text.index("def _numeric_evidence_lines(")
j = text.index("def _consistency_delta(")
text = text[:i] + text[j:]
old = """    verified_report = _verified_green_contract_report(
        model, main_artifacts, baseline_artifacts,
    )
    if verified_report is not None:
        _write_gate_diagnostics(state, verified_report, has_primary=True)
        return _consistency_delta(state, verified_report, has_primary=True)

"""
assert old in text
text = text.replace(old, "", 1)
ast.parse(text)
p.write_text(text, encoding="utf-8")
print("ok")
