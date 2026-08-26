# -*- coding: utf-8 -*-
"""One-shot: strip green-logistics-only code from writer.py / writer_section.py.

All operations are expressed against ORIGINAL 1-based line numbers and applied
in a single pass. Every boundary is asserted before splicing; on mismatch the
script aborts without writing.
"""
import ast
import sys

WRITER = r"e:\git_clone\Beacon\src\math_agent\nodes\writer.py"
SECTION = r"e:\git_clone\Beacon\src\math_agent\prompts\writer_section.py"


def load(path):
    with open(path, encoding="utf-8", newline="") as f:
        return f.readlines()


def body(line):
    return line.rstrip("\r\n")


def apply(path, ops):
    """ops: list of (start, end, replacement_lines) 1-based inclusive.
    replacement_lines: list of str without newline, or None for pure delete."""
    lines = load(path)
    for start, end, repl, checks in ops:
        for lineno, expected in checks:
            actual = body(lines[lineno - 1])
            if actual != expected:
                print("ABORT %s line %d" % (path, lineno))
                print("  expected: %r" % expected)
                print("  actual  : %r" % actual)
                sys.exit(1)
    out = []
    cursor = 1  # 1-based
    for start, end, repl, _checks in sorted(ops, key=lambda o: o[0]):
        out.extend(lines[cursor - 1:start - 1])
        if repl is not None:
            out.extend(r + "\n" for r in repl)
        cursor = end + 1
    out.extend(lines[cursor - 1:])
    text = "".join(out)
    ast.parse(text)  # syntax gate before writing
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    print("OK %s (%d -> %d lines)" % (path, len(lines), text.count("\n")))


# ---------------------------------------------------------------- writer.py
new_outline = [
    "        outline = complete(",
    "            build_outline_prompt(state, retrieved_context=ctx),",
    "            schema=WriterOutline,",
    "            system=SYSTEM,",
    '            model=MODEL_ROUTING["writer"],',
    '            profile="long",',
    "        )",
]

new_dispatch = [
    "    if _should_use_deterministic_writer():",
    '        print(f"[writer] deterministic fallback for: {group_name}", flush=True)',
    "        section_out = _build_section_fallback(",
    "            group_name, state, references=references",
    "        )",
    "    else:",
    "        section_out = complete(",
    "            prompt,",
    "            schema=schema_for_group(group_name),",
    "            system=SYSTEM,",
    '            model=MODEL_ROUTING["writer"],',
    '            profile="long",',
    "            max_tokens=_WRITER_SECTION_MAX_TOKENS,",
    "        )",
]

writer_ops = [
    # 1. drop paper_evidence import (only used by deleted wrappers)
    (22, 25, None, [
        (22, "from math_agent.nodes.paper_evidence import ("),
        (25, ")"),
    ]),
    # 2. writer_node: remove green hardcoded outline branch
    (76, 95, new_outline, [
        (76, "        if _has_green_safe_solver(state):"),
        (88, "        else:"),
        (95, "            )"),
    ]),
    # 3. delete _has_green_safe_solver .. _enforce_section_contract (incl.
    #    _verified_result_map/_verified_structured_map wrappers,
    #    _verified_green_references, _verified_abstract_problem,
    #    _verified_assumptions_notation, _verified_solution,
    #    _verified_model_section, _verified_sensitivity_section,
    #    _verified_factorial_sensitivity_section)
    (340, 1421, None, [
        (340, "def _has_green_safe_solver(state: MathModelingState) -> bool:"),
        (361, "def _verified_green_references() -> str:"),
        (967, "def _verified_model_section() -> str:"),
        (1364, 'def _enforce_section_contract(group_name: str, section_out, state: MathModelingState):'),
        (1419, "    return section_out"),
        (1420, ""),
        (1421, ""),
        (1422, "_MIN_SECTION_NONSPACE_CHARS = {"),
    ]),
    # 4. delete _verified_conclusion_section
    (1475, 1697, None, [
        (1475, "def _verified_conclusion_section(state: MathModelingState) -> str:"),
        (1695, "    ])"),
        (1696, ""),
        (1697, ""),
        (1698, "def writer_section_node(state: MathModelingState) -> dict:"),
    ]),
    # 5. writer_section_node: drop verified-green fallback + contract call
    (1721, 1759, new_dispatch, [
        (1721, "    use_verified_green_fallback = ("),
        (1745, "    elif _should_use_deterministic_writer():"),
        (1759, "    section_out = _enforce_section_contract(group_name, section_out, state)"),
    ]),
    # 6. drop the second _enforce_section_contract call after repair
    (1777, 1777, None, [
        (1776, "        )"),
        (1777, "        section_out = _enforce_section_contract(group_name, section_out, state)"),
        (1778, "        for field in group.fields:"),
    ]),
]

apply(WRITER, writer_ops)

# ---------------------------------------------------------- writer_section.py
new_evidence = [
    "        # 结构化证据 = RESULT 行 + 逐问输出行（Q<id>:，r6 曾因只保留 RESULT 行",
    "        # 导致 writer 拿不到逐问数值而编造细节）+ LIMITATION 声明。",
    "        evidence_lines = list(dict.fromkeys(structured_evidence_lines(a.stdout)))",
]

section_ops = [
    # 1. delete _DEPTH_EVIDENCE_LABELS (green-only evidence label whitelist)
    (172, 177, None, [
        (171, "_MAX_WRITER_CODE_ARTIFACTS = 3"),
        (172, "_DEPTH_EVIDENCE_LABELS = ("),
        (177, ")"),
    ]),
    # 2. delete _depth_evidence_lines (green-only SAFE_SOLVER gate)
    (215, 228, None, [
        (215, "def _depth_evidence_lines(artifact) -> list[str]:"),
        (226, "    ]"),
        (228, ""),
        (229, "def _compact_code_artifacts(state: MathModelingState):"),
    ]),
    # 3. _compact_code_artifacts: drop green depth lines from evidence
    (244, 248, new_evidence, [
        (247, "            structured_evidence_lines(a.stdout) + _depth_evidence_lines(a)"),
        (248, "        ))"),
    ]),
    # 4. _extract_available_numbers: drop green depth lines
    (288, 289, None, [
        (288, "        for line in _depth_evidence_lines(a):"),
        (289, '            lines.append(f"  [{a.purpose}] {line}")'),
    ]),
    # 5. delete green scenario-identity hard constraint block
    (410, 424, None, [
        (410, '        if "SCENARIO_Q1:" in numbers and "RESULT: baseline=ours" in numbers:'),
        (424, "            )"),
        (425, "    if retrieved_context:"),
    ]),
]

apply(SECTION, section_ops)
print("ALL DONE")
