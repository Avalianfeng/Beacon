"""评审检查包装：通过 importlib 调用 scripts/check_*.py。"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

_CHECK_NAMES = frozenset(
    {
        "check_paper_numbers",
        "check_assumption_claims",
        "check_gap_trigger",
        "check_l4_gates",
    }
)


def _scripts_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "scripts"


def load_check_module(name: str):
    """name in {'check_paper_numbers','check_assumption_claims','check_gap_trigger','check_l4_gates'}

    Load scripts/<name>.py via importlib.util.spec_from_file_location.
    """
    if name not in _CHECK_NAMES:
        raise ValueError(f"unknown check module: {name}")
    script = _scripts_dir() / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, script)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {script}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _overall_exit(tools: list[dict], *, strict: bool) -> int:
    if not tools:
        return 2
    codes = [t["exit_code"] for t in tools]
    if strict:
        return max(codes)
    if any(c == 2 for c in codes):
        return 2
    return 0


def run_review(
    *,
    paper: Path | None,
    evidence: list[Path] | None = None,
    json_evidence: list[Path] | None = None,
    strict: bool = False,
    traceability: Path | None = None,
) -> dict:
    """Run the checkers that have inputs."""
    if paper is None and not json_evidence and traceability is None:
        return {
            "ok": False,
            "exit_code": 2,
            "tools": [],
            "strict": strict,
        }

    tools: list[dict] = []

    if paper is not None or traceability is not None:
        mod = load_check_module("check_paper_numbers")
        argv: list[str] = []
        if paper is not None:
            argv.extend(["--paper", str(paper)])
        if evidence:
            argv.append("--evidence")
            argv.extend(str(p) for p in evidence)
        if traceability is not None:
            argv.extend(["--traceability", str(traceability)])
        if strict:
            argv.append("--strict")
        tools.append({"name": "check_paper_numbers", "exit_code": mod.main(argv)})

    if paper is not None:
        mod = load_check_module("check_assumption_claims")
        argv = ["--paper", str(paper)]
        if strict:
            argv.append("--strict")
        tools.append({"name": "check_assumption_claims", "exit_code": mod.main(argv)})

        mod = load_check_module("check_l4_gates")
        argv = ["--paper", str(paper)]
        if strict:
            argv.append("--strict")
        tools.append({"name": "check_l4_gates", "exit_code": mod.main(argv)})

    if json_evidence:
        mod = load_check_module("check_gap_trigger")
        argv: list[str] = []
        for path in json_evidence:
            argv.extend(["--json", str(path)])
        if strict:
            argv.append("--strict")
        tools.append({"name": "check_gap_trigger", "exit_code": mod.main(argv)})

    exit_code = _overall_exit(tools, strict=strict)
    return {
        "ok": exit_code == 0,
        "exit_code": exit_code,
        "tools": tools,
        "strict": strict,
    }


def write_review_report(payload: dict, out: Path) -> Path:
    """Write JSON to `out` if out.suffix=='.json' else to out/"review-report.json"."""
    out = Path(out)
    target = out if out.suffix == ".json" else out / "review-report.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return target
