"""评审检查包装：通过 importlib 调用 scripts/check_*.py。

新增 check 工具只需两步：在 _CHECK_BUILDERS 注册表加一行（name → builder），
并在 scripts/ 下提供同名脚本（实现 main(argv) 返回退出码）。
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


@dataclass(frozen=True)
class _RunCtx:
    """run_review 的统一输入上下文，传给每个 check builder 用于构造 argv。"""

    paper: Path | None = None
    evidence: list[Path] | None = None
    json_evidence: list[Path] | None = None
    traceability: Path | None = None
    brief: Path | None = None
    code: list[Path] | None = None
    stdout: Path | None = None
    strict: bool = False


def _build_paper_numbers(ctx: _RunCtx) -> list[str] | None:
    """paper 或 traceability 任一存在才运行；写后对账用 --key-results（只核 RESULT 键）。"""
    if ctx.paper is None and ctx.traceability is None:
        return None
    argv: list[str] = []
    if ctx.paper is not None:
        argv.extend(["--paper", str(ctx.paper)])
    if ctx.evidence:
        argv.append("--evidence")
        argv.extend(str(p) for p in ctx.evidence)
    if ctx.traceability is not None:
        argv.extend(["--traceability", str(ctx.traceability)])
    if ctx.paper is not None and ctx.evidence:
        argv.append("--key-results")
    if ctx.strict:
        argv.append("--strict")
    return argv


def _build_assumption_claims(ctx: _RunCtx) -> list[str] | None:
    """需要 paper。"""
    if ctx.paper is None:
        return None
    argv = ["--paper", str(ctx.paper)]
    if ctx.strict:
        argv.append("--strict")
    return argv


def _build_l4_gates(ctx: _RunCtx) -> list[str] | None:
    """需要 paper；brief 可选并入扫描语料。"""
    if ctx.paper is None:
        return None
    argv = ["--paper", str(ctx.paper)]
    if ctx.brief is not None:
        argv.extend(["--brief", str(ctx.brief)])
    if ctx.strict:
        argv.append("--strict")
    return argv


def _build_redlines(ctx: _RunCtx) -> list[str] | None:
    """需要 paper + brief；--code/--stdout 展开 + --strict。"""
    if ctx.paper is None or ctx.brief is None:
        return None
    argv = ["--paper", str(ctx.paper), "--brief", str(ctx.brief)]
    for path in ctx.code or []:
        argv.extend(["--code", str(path)])
    if ctx.stdout is not None:
        argv.extend(["--stdout", str(ctx.stdout)])
    if ctx.strict:
        argv.append("--strict")
    return argv


def _build_brief_claims(ctx: _RunCtx) -> list[str] | None:
    """需要 paper + brief。"""
    if ctx.paper is None or ctx.brief is None:
        return None
    argv = ["--paper", str(ctx.paper), "--brief", str(ctx.brief)]
    if ctx.strict:
        argv.append("--strict")
    return argv


def _build_gap_trigger(ctx: _RunCtx) -> list[str] | None:
    """需要 json_evidence；每个文件一个 --json。"""
    if not ctx.json_evidence:
        return None
    argv: list[str] = []
    for path in ctx.json_evidence:
        argv.extend(["--json", str(path)])
    if ctx.strict:
        argv.append("--strict")
    return argv


# 声明式注册表：新增 check 工具 = 这里加一行 + scripts/<name>.py 实现 main(argv)。
# 键名即脚本文件名；builder 返回 None 表示该工具在当前输入下不运行；
# 注册表插入顺序即 tools 输出顺序（与旧 run_review 手写分支一致）。
_CHECK_BUILDERS: dict[str, Callable[[_RunCtx], list[str] | None]] = {
    "check_paper_numbers": _build_paper_numbers,
    "check_assumption_claims": _build_assumption_claims,
    "check_l4_gates": _build_l4_gates,
    "check_redlines": _build_redlines,
    "check_brief_claims": _build_brief_claims,
    "check_gap_trigger": _build_gap_trigger,
}

_CHECK_NAMES = frozenset(_CHECK_BUILDERS)


def _scripts_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "scripts"


def load_check_module(name: str):
    """Load scripts/<name>.py via importlib.util.spec_from_file_location."""
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
    if any(c == 2 for c in codes):
        return 2
    if any(c == 1 for c in codes):
        # hard 红线等工具在非 --strict 下也会返回 1；其余脚本仅在传入 --strict 时返回 1
        return 1
    if strict:
        return max(codes)
    return 0


def run_review(
    *,
    paper: Path | None,
    evidence: list[Path] | None = None,
    json_evidence: list[Path] | None = None,
    strict: bool = False,
    traceability: Path | None = None,
    brief: Path | None = None,
    code: list[Path] | None = None,
    stdout: Path | None = None,
) -> dict:
    """按 _CHECK_BUILDERS 遍历：builder 返回 None 的工具跳过，否则加载脚本并执行。"""
    if paper is None and not json_evidence and traceability is None:
        return {
            "ok": False,
            "exit_code": 2,
            "tools": [],
            "strict": strict,
        }

    ctx = _RunCtx(
        paper=paper,
        evidence=evidence,
        json_evidence=json_evidence,
        traceability=traceability,
        brief=brief,
        code=code,
        stdout=stdout,
        strict=strict,
    )

    tools: list[dict] = []
    for name, build_argv in _CHECK_BUILDERS.items():
        argv = build_argv(ctx)
        if argv is None:
            continue  # 该工具在当前输入下不运行
        mod = load_check_module(name)
        tools.append({"name": name, "exit_code": mod.main(argv)})

    exit_code = _overall_exit(tools, strict=strict)
    payload = {
        "ok": exit_code == 0,
        "exit_code": exit_code,
        "tools": tools,
        "strict": strict,
    }
    if brief is not None and Path(brief).is_file():
        payload["brief_sha256"] = hashlib.sha256(Path(brief).read_bytes()).hexdigest()
        payload["brief"] = str(brief)
    return payload


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
