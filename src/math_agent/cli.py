"""math-agent CLI（Plan C 版）。

run     : 启动一次任务（默认在 human_review 处中断）
resume  : 提供 human decision 并续跑
watch   : 只读跟随运行进度与日志（不杀任务）
report  : 打印一次运行的 trace 报告
ingest  : 把语料目录嵌入到向量库（RAG 索引）
bench   : 真跑历年题回归基准（live 模式）
"""
from __future__ import annotations
import hashlib
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from math_agent.config import (
    MIN_PAPER_CRITIC_SCORE,
    MIN_MODEL_CODE_SCORE,
    MAX_CODE_VERIFY_ITERATIONS,
    MAX_CODE_NO_PRIMARY_ITERATIONS,
)
from math_agent.graph import build_graph
from math_agent.checkpointing import sqlite_saver
from math_agent.state import HumanDecision, DataFileInfo, MathModelingState
from math_agent.errors import LLMError, LLMRateLimitError, LLMTransportError
from math_agent.nodes.finalizer import load_verified_completion
from math_agent.run_lock import RunLock, RunLockedError
from math_agent.supervisor import (
    SupervisorPolicy,
    clear_failure_report,
    failure_record_for_exception,
    inspect_checkpoint,
    reconcile_supervisor_state,
    run_process_supervisor,
    start_detached_supervisor,
    write_failure_report,
)
from math_agent.tracing import (
    Tracer, get_last_node, set_current, reset_current, clear_failed_node,
)
from math_agent import pause_control
from math_agent.pause_control import PauseRequested
from math_agent.ops_help import GROUP_HELP, ROOT_HELP
from math_agent.ops_preflight import run_preflight, write_preflight_json
from math_agent.ops_review import run_review, write_review_report
from math_agent.ops_stage import format_stage_text, infer_stage
from math_agent.ops_verify import (
    build_package,
    load_evidence,
    package_ok,
    write_package,
)


app = typer.Typer(help=ROOT_HELP, no_args_is_help=True)


def _field(obj, key: str, default=None):
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _dump_model(obj):
    if isinstance(obj, dict):
        return obj
    return obj.model_dump()


def _read_state_summary_data(out: Path, thread: str = "default") -> dict | None:
    """从 checkpoint 读 final state，提取 blueprint/critic/consistency 摘要数据。

    _dump_state_summary 和 _print_blueprint_summary 共用此函数，避免重复代码。
    无 checkpoint 或读取失败时返回 None。
    """
    chk = out / "checkpoints.sqlite"
    if not chk.exists():
        return None
    try:
        with _saver_cm(out) as saver:
            g = build_graph(checkpointer=saver)
            snap = g.get_state(_config(thread))
    except Exception:
        return None
    if snap is None or snap.values is None:
        return None

    state = snap.values

    def _get(key, default=None):
        return _field(state, key, default)

    bp = _get("problem_blueprint")
    critics = _get("critic_reports") or []
    mc_reports = _get("model_code_reports") or []
    models = _get("model_versions") or []
    evaluation = _get("evaluation")

    bp_critic = next(
        (r for r in reversed(critics)
         if _field(r, "target", "") == "analyst" and _field(r, "critic_type", "") == "blueprint"), None)
    model_critic = next(
        (r for r in reversed(critics) if _field(r, "target", "") == "modeler"), None)
    paper_critic = next(
        (r for r in reversed(critics) if _field(r, "target", "") == "paper"), None)

    total_sq = len(_field(bp, "subquestions", []) or []) if bp else 0
    covered = len(_field(models[-1], "question_coverage", []) or []) if models else 0

    unresolved = 0
    for r in critics:
        if not _field(r, "approved", True):
            unresolved += len(_field(r, "issues", []) or [])
    for r in mc_reports:
        if not _field(r, "approved", True):
            unresolved += len(_field(r, "issues", []) or [])

    return {
        "bp": bp,
        "bp_critic": bp_critic,
        "model_critic": model_critic,
        "paper_critic": paper_critic,
        "mc_reports": mc_reports,
        "models": models,
        "total_sq": total_sq,
        "covered": covered,
        "unresolved": unresolved,
        "stage_target": _get("stage_target"),
        "iteration": _get("iteration"),
        "evaluation_overall": _field(evaluation, "overall", None) if evaluation else None,
    }


def _dump_state_summary(out: Path, thread: str = "default") -> None:
    """从 checkpoint 读 final state，写 state_summary.json 供 Web UI 消费。

    ponytail: 直接从 checkpoint 读，不侵入 graph 节点。无 checkpoint 时静默跳过。
    """
    data = _read_state_summary_data(out, thread)
    if data is None:
        return

    bp = data["bp"]
    bp_critic = data["bp_critic"]
    model_critic = data["model_critic"]
    paper_critic = data["paper_critic"]
    mc_reports = data["mc_reports"]

    summary = {
        "problem_blueprint": _dump_model(bp) if bp else None,
        "blueprint_critic": {
            "score": _field(bp_critic, "score", None),
            "approved": _field(bp_critic, "approved", None),
            "issues": [_field(i, "problem", str(i)) for i in _field(bp_critic, "issues", []) or []]
                       if bp_critic else [],
            "suggestions": _field(bp_critic, "suggestions", []) or [] if bp_critic else [],
        } if bp_critic else None,
        "model_critic": {
            "score": _field(model_critic, "score", None),
            "approved": _field(model_critic, "approved", None),
        } if model_critic else None,
        "paper_critic": {
            "score": _field(paper_critic, "score", None),
            "approved": _field(paper_critic, "approved", None),
        } if paper_critic else None,
        "model_code_consistency": {
            "score": _field(mc_reports[-1], "score", None) if mc_reports else None,
            "approved": _field(mc_reports[-1], "approved", None) if mc_reports else None,
            "missing_variables": _field(mc_reports[-1], "missing_variables", []) or [] if mc_reports else [],
            "missing_objectives": _field(mc_reports[-1], "missing_objectives", []) or [] if mc_reports else [],
            "missing_constraints": _field(mc_reports[-1], "missing_constraints", []) or [] if mc_reports else [],
            "issues": _field(mc_reports[-1], "issues", []) or [] if mc_reports else [],
        } if mc_reports else None,
        "question_coverage": f"{data['covered']}/{data['total_sq']}",
        "unresolved_issues": data["unresolved"],
        "stage_target": data["stage_target"],
        "iteration": data["iteration"],
        "evaluation_overall": data["evaluation_overall"],
    }
    (out / "state_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


def _saver_cm(out: Path):
    """返回 SqliteSaver 的 contextmanager；调用方需用 with 包起来。"""
    out.mkdir(parents=True, exist_ok=True)
    return sqlite_saver(out / "checkpoints.sqlite")


def _config(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id}}


def _failure_node(exc: BaseException) -> str:
    return str(getattr(exc, "_math_agent_failed_node", "") or get_last_node())


def _record_failure(out: Path, exc: BaseException):
    record = failure_record_for_exception(_failure_node(exc), exc)
    write_failure_report(out, record)
    try:
        from math_agent.progress import emit_error
        emit_error(out, node=record.node, kind=record.kind, message=record.message)
    except Exception:
        pass
    return record


def _require_checkpoint(out: Path) -> None:
    checkpoint = out / "checkpoints.sqlite"
    if not checkpoint.is_file():
        typer.echo(f"no checkpoint at {checkpoint}; run a pipeline first", err=True)
        raise typer.Exit(1)


def _require_trace_thread(out: Path, thread: str) -> None:
    """防止错误 thread 的 resume/recover 覆盖同目录中另一任务的 trace。"""
    trace_path = out / "trace.json"
    if not trace_path.is_file():
        return
    try:
        blob = json.loads(trace_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return  # 损坏 trace 不阻止 checkpoint 恢复；Tracer 会从空统计开始
    existing_thread = blob.get("thread_id") if isinstance(blob, dict) else None
    if existing_thread and existing_thread != thread:
        typer.echo(
            f"trace at {trace_path} belongs to thread={existing_thread}, not {thread}",
            err=True,
        )
        raise typer.Exit(1)


def _read_problem_spec(problem: Path) -> dict:
    """读取并校验题目 JSON；任何破坏性 ``--force`` 操作都必须晚于此步骤。"""
    try:
        spec = json.loads(problem.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise typer.BadParameter(f"题目文件不是有效的 UTF-8 JSON：{exc}", param_hint="--problem") from exc
    if not isinstance(spec, dict):
        raise typer.BadParameter("题目 JSON 顶层必须是对象", param_hint="--problem")

    title = spec.get("title", "")
    background = spec.get("background", "")
    questions = spec.get("questions", [])
    if not isinstance(title, str) or not isinstance(background, str):
        raise typer.BadParameter("title 和 background 必须是字符串", param_hint="--problem")
    if not isinstance(questions, list) or not all(isinstance(q, str) for q in questions):
        raise typer.BadParameter("questions 必须是字符串数组", param_hint="--problem")
    if not title.strip() and not any(q.strip() for q in questions):
        raise typer.BadParameter("title 与 questions 不能同时为空", param_hint="--problem")

    data_files = spec.get("data_files", [])
    data_dir = spec.get("data_dir", "")
    if not isinstance(data_files, list):
        raise typer.BadParameter("data_files 必须是数组", param_hint="--problem")
    if not isinstance(data_dir, str):
        raise typer.BadParameter("data_dir 必须是字符串", param_hint="--problem")
    if data_dir:
        data_dir_path = Path(data_dir)
        if not data_dir_path.is_absolute():
            data_dir_path = problem.parent / data_dir_path
        if not data_dir_path.is_dir():
            raise typer.BadParameter(
                f"data_dir 不存在: {data_dir_path}", param_hint="--problem"
            )
        data_dir = str(data_dir_path.resolve())

    return {"title": title, "background": background, "questions": questions,
            "data_files": data_files, "data_dir": data_dir}


def _cli_problem_id(problem: Path) -> str:
    """从 problem.json 的 problem_id 或父目录名取题号。"""
    try:
        raw = json.loads(problem.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise typer.BadParameter(
            f"题目文件不是有效的 UTF-8 JSON：{exc}", param_hint="--problem"
        ) from exc
    problem_id = raw.get("problem_id") if isinstance(raw, dict) else None
    if not isinstance(problem_id, str) or not problem_id.strip():
        problem_id = problem.parent.name
    if not re.fullmatch(r"[A-Za-z0-9-]+", problem_id):
        raise typer.BadParameter(
            f"无法确定 problem_id（problem.json 无 problem_id 且目录名 {problem.parent.name!r} 非法）",
            param_hint="--problem",
        )
    return problem_id


def _problem_fingerprint(spec: dict) -> str:
    canonical = json.dumps(spec, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _write_run_manifest(
    out: Path, thread: str, spec: dict, *, no_interrupt: bool = False,
    brief_sha256: str | None = None,
) -> None:
    path = out / "run_manifest.json"
    tmp = path.with_name(f"{path.name}.tmp-{os.getpid()}")
    payload = {
        "thread": thread,
        "problem_sha256": _problem_fingerprint(spec),
        "no_interrupt": no_interrupt,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    if brief_sha256:
        payload["brief_sha256"] = brief_sha256
    try:
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def _load_brief_or_raise(brief: Path) -> "object":
    """读取并校验 --brief；失败抛 typer.BadParameter（带 param_hint）。"""
    from math_agent.brief import load_brief
    try:
        return load_brief(brief)
    except ValueError as exc:
        raise typer.BadParameter(str(exc), param_hint="--brief") from exc


def _copy_brief_to_out(out: Path, brief_path: Path) -> None:
    """把 brief 原文复制到输出目录，保证运行证据链可审计。"""
    import shutil
    target = out / "brief.json"
    if brief_path.resolve() == target.resolve():
        return
    shutil.copyfile(brief_path, target)

def _validate_existing_run_manifest(out: Path, thread: str, spec: dict, force: bool) -> None:
    if force or not (out / "checkpoints.sqlite").is_file():
        return
    path = out / "run_manifest.json"
    if not path.is_file():
        typer.echo("[supervisor] 旧 checkpoint 没有 run_manifest，按 thread 兼容恢复。", err=True)
        return
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise typer.BadParameter(f"run_manifest.json 损坏：{exc}", param_hint="--out") from exc
    if manifest.get("thread") != thread:
        raise typer.BadParameter(
            f"输出目录属于 thread={manifest.get('thread')}，不是 {thread}", param_hint="--thread",
        )
    if manifest.get("problem_sha256") != _problem_fingerprint(spec):
        raise typer.BadParameter(
            "输出目录中的 checkpoint 属于另一道题；请换 --out，或明确使用 --force",
            param_hint="--problem",
        )


def _prepare_run_output(out: Path, thread: str, force: bool) -> None:
    """在 worker 锁内检查/清理输出目录，防止 --force 与活跃任务竞态。"""
    checkpoint = out / "checkpoints.sqlite"
    if checkpoint.exists() and not force:
        typer.echo(
            f"Output dir {out} already has a checkpoint (thread={thread}).\n"
            f"  - Use a different --out to start a fresh run.\n"
            f"  - Or append --force to overwrite the existing run.\n"
            f"  - Or use `recover` to continue the existing run.",
            err=True,
        )
        raise typer.Exit(1)
    if not force:
        return
    for checkpoint_file in (
        checkpoint, Path(str(checkpoint) + "-wal"), Path(str(checkpoint) + "-shm"),
    ):
        checkpoint_file.unlink(missing_ok=True)
    for stale_name in (
        "trace.json", "state_summary.json", "paper.md", "paper.tex", "paper.pdf",
        "completion.json", "final_state.json", "failure.json", "supervisor.json",
        "run_manifest.json", "progress.jsonl", "gate_diagnostics.json",
    ):
        (out / stale_name).unlink(missing_ok=True)
    (out / pause_control.PAUSE_MARKER_NAME).unlink(missing_ok=True)
    insights = out / "insights"
    if insights.is_dir():
        import shutil
        shutil.rmtree(insights, ignore_errors=True)
    steps = out / "steps"
    if steps.is_dir():
        import shutil
        shutil.rmtree(steps, ignore_errors=True)
    try:
        from math_agent.progress import reset_progress
        reset_progress(out, epoch=1, attempt=1)
    except Exception:
        pass


brief_app = typer.Typer(
    help=GROUP_HELP["brief"],
)
app.add_typer(brief_app, name="brief")


reference_app = typer.Typer(
    help=GROUP_HELP["reference"],
)
app.add_typer(reference_app, name="reference")


@reference_app.command("add")
def reference_add(
    problem: Path = typer.Option(
        ..., "--problem", exists=True, readable=True, help="题目 spec JSON"
    ),
    solver: Path = typer.Option(
        ..., "--solver", exists=True, file_okay=False, help="求解脚本目录"
    ),
    entry: str = typer.Option(
        ..., "--entry", help="入口文件相对 solver 目录的路径（如 _entry.py）"
    ),
    force: bool = typer.Option(False, "--force", help="覆盖已有 reference 目录"),
):
    """登记参考实现：把 solver 目录的 *.py 归档为 problems/<id>/source/reference/ 并更新清单。"""
    import shutil

    # 校验 spec（title/background/questions/data_dir 等）；problem_id 与 source 从原始 JSON 另取
    _read_problem_spec(problem)
    try:
        raw = json.loads(problem.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise typer.BadParameter(
            f"题目文件不是有效的 UTF-8 JSON：{exc}", param_hint="--problem"
        ) from exc

    problem_id = raw.get("problem_id")
    if not isinstance(problem_id, str) or not problem_id.strip():
        problem_id = problem.parent.name
    if not re.fullmatch(r"[A-Za-z0-9-]+", problem_id):
        raise typer.BadParameter(
            f"无法确定 problem_id（problem.json 无 problem_id 且目录名 {problem.parent.name!r} 非法）",
            param_hint="--problem",
        )

    target = Path("problems") / problem_id / "source" / "reference"
    if target.exists() and not force:
        raise typer.BadParameter(
            f"problems/{problem_id}/source/reference 已存在；换 solver 目录或 --force 覆盖"
        )
    target.mkdir(parents=True, exist_ok=True)
    if force:
        for old in target.iterdir():
            if old.is_file() and old.suffix == ".py":
                old.unlink()

    py_files = sorted(
        (f for f in solver.iterdir() if f.is_file() and f.suffix == ".py"),
        key=lambda p: p.name,
    )
    if not py_files:
        raise typer.BadParameter("solver 目录下没有 *.py 文件", param_hint="--solver")

    ref_files = []
    for f in py_files:
        dest = target / f.name
        shutil.copyfile(f, dest)
        digest = hashlib.sha256(dest.read_bytes()).hexdigest()
        ref_files.append({"path": f"reference/{f.name}", "sha256": digest})

    source = raw.get("source")
    if not isinstance(source, dict):
        source = {}
        raw["source"] = source
    source_files = source.get("source_files")
    if not isinstance(source_files, list):
        source_files = []
        source["source_files"] = source_files
    source_files[:] = [
        item for item in source_files
        if not (
            isinstance(item, dict)
            and str(item.get("path", "")).startswith("reference/")
        )
    ]
    source_files.extend(ref_files)
    problem.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")

    ref_path = Path("problems") / problem_id / "reference.json"
    ref_path.write_text(
        json.dumps(
            {
                "entry": entry,
                "files": ref_files,
                "added_at": datetime.now(timezone.utc).isoformat(),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    typer.echo(f"[OK] reference 登记完成：problems/{problem_id}")
    typer.echo(f"入口：{entry}")
    typer.echo(f"文件数：{len(ref_files)}")
    for item in ref_files:
        typer.echo(f"  {item['path']}  sha256={item['sha256'][:12]}")


@reference_app.command("run")
def reference_run(
    problem: Path = typer.Option(
        ..., "--problem", exists=True, readable=True, help="题目 spec JSON"
    ),
    out: Path | None = typer.Option(
        None, "--out", help="evidence 输出目录（默认 runs/<problem_id>-reference）"
    ),
):
    """运行参考实现入口，提取 RESULT/Q 行/PNG 并写 evidence.json。"""
    from math_agent.tools.runner import (
        extract_numeric_results,
        run_python,
        structured_evidence_lines,
    )

    spec = _read_problem_spec(problem)
    try:
        raw = json.loads(problem.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise typer.BadParameter(
            f"题目文件不是有效的 UTF-8 JSON：{exc}", param_hint="--problem"
        ) from exc

    problem_id = raw.get("problem_id")
    if not isinstance(problem_id, str) or not problem_id.strip():
        problem_id = problem.parent.name
    if not re.fullmatch(r"[A-Za-z0-9-]+", problem_id):
        raise typer.BadParameter(
            f"无法确定 problem_id（problem.json 无 problem_id 且目录名 {problem.parent.name!r} 非法）",
            param_hint="--problem",
        )

    ref_path = Path("problems") / problem_id / "reference.json"
    entry = None
    if ref_path.is_file():
        try:
            ref = json.loads(ref_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            ref = {}
        candidate = ref.get("entry") if isinstance(ref, dict) else None
        if isinstance(candidate, str) and candidate.strip():
            entry = candidate.strip()
    if entry is None:
        typer.echo("未登记参考实现，先 `reference add`", err=True)
        raise typer.Exit(1)

    data_dir = spec.get("data_dir") or ""
    data_dir_posix = Path(data_dir).as_posix() if data_dir else "."
    wrapper_code = (
        "import matplotlib; matplotlib.use('Agg')\n"
        "from pathlib import Path\n"
        f"data_dir = Path({data_dir_posix!r})\n"
        f"exec((data_dir / 'reference' / {entry!r}).read_text(encoding='utf-8'), "
        "{'data_dir': data_dir})\n"
    )

    expected_input_paths: list[Path] = []
    for df in spec.get("data_files", []):
        if not isinstance(df, dict):
            continue
        rel = (df.get("path") or df.get("filename") or "").strip()
        if not rel:
            continue
        path = Path(rel)
        if not path.is_absolute():
            path = (Path(data_dir) / path) if data_dir else path
        expected_input_paths.append(path.resolve())

    if out is None:
        out = Path("runs") / f"{problem_id}-reference"
    out.mkdir(parents=True, exist_ok=True)

    start = time.monotonic()
    result = run_python(
        wrapper_code,
        workdir=out,
        timeout=120,
        expected_input_paths=expected_input_paths,
    )
    elapsed = time.monotonic() - start

    if not result.success:
        typer.echo(f"[FAIL] 参考实现运行失败：{(result.stderr or '')[-800:]}", err=True)
        raise typer.Exit(1)

    result_map = extract_numeric_results(result.stdout)
    q_lines = structured_evidence_lines(result.stdout)
    png = sorted(
        Path(a).name
        for a in result.artifact_paths
        if Path(a).name.lower().endswith(".png")
    )

    evidence = {
        "problem_id": problem_id,
        "entry": f"reference/{entry}",
        "result": result_map,
        "q_lines": q_lines,
        "artifacts": {"png": png},
        "run": {
            "success": result.success,
            "elapsed_s": round(elapsed, 1),
            "stdout_chars": len(result.stdout or ""),
        },
    }
    evidence_path = out / "evidence.json"
    evidence_path.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    ours_count = len(result_map.get("ours", {}))
    q_count = sum(1 for line in q_lines if re.match(r"^Q\d", line))
    typer.echo(f"[OK] reference 运行完成：{problem_id}")
    typer.echo(f"RESULT 指标数（ours）：{ours_count}")
    typer.echo(f"Q 行数：{q_count}")
    typer.echo(f"PNG 数：{len(png)}")
    typer.echo(f"evidence.json：{evidence_path.resolve()}")


# ---------------------------------------------------------------------------
# reference tables：Q 行结构化字段 → 交付表（md/csv）
# ---------------------------------------------------------------------------

# C 题内置默认表 spec：problems/<problem_id>/tables.json 缺失时兜底（与落盘文件同构）。
# 结构：每张表 {id, title, columns, lead_columns?, field?, total?}
#   - lead_columns: {列名: 静态题面值列表}（如校正前 x / 时间点），各列等长，定行数 N
#   - field: "<qid>.<字段名>"，指向 q_fields 里某问的某字段（值必须为列表），
#     按行主序填"未被 lead_columns 覆盖的剩余列"：长度须等于 N×剩余列数
#     （无 lead_columns 时 N=1，单行汇总表；如表3.1 5 个值填 5 列）
#   - total: true 时末列填本行数值格之和（如表3.1 的"总数"）
_DEFAULT_TABLES_SPEC = {
    "tables": [
        {
            "id": "table11",
            "title": "表1.1 位移数据校正验证",
            "columns": ["校正前 x (mm)", "校正后 y (mm)"],
            "lead_columns": {
                "校正前 x (mm)": [7.132, 18.526, 84.337, 123.554, 167.667]
            },
            "field": "q1.table11",
        },
        {
            "id": "table31",
            "title": "表3.1 单变量异常点数量",
            "columns": ["降雨量 a", "孔压 b", "微震 c", "深部位移 d", "表面位移 e", "总数"],
            "field": "q3.table31",
            "total": True,
        },
        {
            "id": "table41",
            "title": "表4.1 实验集表面位移预测值",
            "columns": ["时间点", "预测位移 (mm)"],
            "lead_columns": {
                "时间点": [
                    "2025-05-09 12:00", "2025-05-27 08:00",
                    "2025-06-01 12:00", "2025-06-03 22:00", "2025-06-04 01:40",
                ]
            },
            "field": "q4.table41",
        },
    ]
}


def _parse_evidence_value(raw: str):
    """Q 行 ``k=v`` 的值解析：``[...]`` → 元素保留原文的字符串列表；纯数字 → float；否则原串。

    列表元素保留 evidence 原文（不转 float），保证表格输出逐字一致、不丢精度
    （如 ``268.700`` 不会被压成 ``268.7``）；需要数值计算（total 求和）时再转。
    """
    raw = raw.strip()
    if raw.startswith("[") and raw.endswith("]"):
        inner = raw[1:-1].strip()
        if not inner:
            return []
        return [p.strip() for p in inner.split(",")]
    try:
        return float(raw)
    except ValueError:
        return raw


def _parse_q_lines_to_fields(q_lines: list[str]) -> dict:
    """把 evidence.q_lines 里每条 ``Q<id>:`` 行解析成结构化字段。

    返回 ``{"q1": {"gain": 0.8817, "table11": ["5.764", ...], ...}, ...}``；
    RESULT:/LIMITATION: 等非 Q 行忽略（表格装配只消费 Q 行）。
    """
    fields: dict[str, dict] = {}
    for line in q_lines or []:
        m = re.match(r"^Q(\d+):\s*(.+)$", line.strip())
        if not m:
            continue
        q_fields = fields.setdefault(f"q{m.group(1)}", {})
        for km in re.finditer(r"([A-Za-z_][\w]*)=(\[[^\]]*\]|[^\s]+)", m.group(2)):
            q_fields[km.group(1)] = _parse_evidence_value(km.group(2))
    return fields


def _cell_text(value) -> str:
    """单元格显示文本：整数型浮点去尾零；其余 str() 原样（字符串/浮点/整型）。"""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _format_number(x: float) -> str:
    """合计列数值格式化：整数输出整数；小数去掉浮点噪声尾零。"""
    if x.is_integer() and abs(x) < 1e15:
        return str(int(x))
    return format(x, ".10f").rstrip("0").rstrip(".")


def _lookup_field(q_fields: dict, field_ref: str, table_id: str) -> list:
    """解析 ``q1.table11`` 式字段引用 → evidence 值列表；失败抛 ValueError。"""
    qid, _, key = field_ref.partition(".")
    if not qid or not key:
        raise ValueError(f"field 必须形如 <qid>.<字段名>（当前 {field_ref!r}）")
    qf = q_fields.get(qid)
    if qf is None:
        raise ValueError(f"evidence 缺 {qid} 行（表 {table_id} 引用 {field_ref}）")
    if key not in qf:
        raise ValueError(f"evidence {qid} 行缺字段 {key}（表 {table_id} 引用 {field_ref}）")
    value = qf[key]
    if not isinstance(value, list):
        raise ValueError(f"{field_ref} 的值必须是列表（当前 {type(value).__name__}）")
    return value


def _build_table_rows(table: dict, q_fields: dict) -> list[list[str]]:
    """按表声明装配行：lead_columns（题面静态列）+ field（evidence 值，行主序填剩余列）。

    行数 N 由 lead_columns 各列长度决定；无 lead_columns 时 N=1（单行汇总表）。
    field 列表长度必须等于 ``N × 剩余列数``（``total: true`` 时剩余列去掉末列），
    按行主序填充：第 i 行依次取第 ``i×R`` 到 ``(i+1)×R-1`` 个值填入剩余列。
    这样表1.1（5 行 × 1 列）与表3.1（1 行 × 5 列）可用同一条规则。
    ``total: true`` 时末列填本行数值格之和。返回已格式化的数据行（不含表头）。
    """
    table_id = table.get("id") or "?"
    columns = table.get("columns")
    if not isinstance(columns, list) or not columns or not all(
        isinstance(c, str) for c in columns
    ):
        raise ValueError("columns 必须是非空字符串列表")

    lead = table.get("lead_columns") or {}
    if not isinstance(lead, dict):
        raise ValueError("lead_columns 必须是对象")
    lead_values: dict[str, list] = {}
    for name, values in lead.items():
        if not isinstance(values, list):
            raise ValueError(f"lead_columns[{name!r}] 必须是列表")
        lead_values[name] = values

    field_ref = table.get("field")
    field_values = _lookup_field(q_fields, field_ref, table_id) if field_ref else None
    want_total = bool(table.get("total", False))

    lead_lengths = [len(v) for v in lead_values.values()]
    if lead_lengths:
        n = lead_lengths[0]
        if any(length != n for length in lead_lengths):
            raise ValueError(f"lead_columns 各列行数不一致：{lead_lengths}")
    elif field_values is not None:
        n = 1  # 无 lead_columns → 单行汇总表（如表3.1）
    else:
        raise ValueError("表没有行数据来源（lead_columns/field 至少其一）")

    remaining = [c for c in columns if c not in lead_values]
    field_cols = remaining[:-1] if (want_total and remaining) else remaining
    if field_values is None:
        if len(field_cols) > 0 or (want_total and not remaining):
            raise ValueError(
                f"无 field，但剩余列未填：{remaining}（lead_columns 外需 field 或 total）"
            )
    else:
        expected = n * len(field_cols)
        if len(field_values) != expected:
            raise ValueError(
                f"field {field_ref} 有 {len(field_values)} 个值，"
                f"期望 {n} 行 × {len(field_cols)} 列（剩余列{'去掉末列' if want_total else ''}）"
                f"= {expected}"
            )

    rows: list[list[str]] = []
    for i in range(n):
        cells = {name: _cell_text(values[i]) for name, values in lead_values.items()}
        if field_values is not None:
            base = i * len(field_cols)
            for j, col in enumerate(field_cols):
                cells[col] = _cell_text(field_values[base + j])
        row = [cells.get(col, "") for col in columns]
        if want_total:
            acc = 0.0
            counted = False
            for cell in row[:-1]:
                try:
                    acc += float(cell)
                    counted = True
                except (TypeError, ValueError):
                    continue
            row[-1] = _format_number(acc) if counted else ""
        rows.append(row)
    return rows


def _write_table_files(out_dir: Path, table: dict, rows: list[list[str]]) -> tuple[Path, Path]:
    """写 <table_id>.md（标题 + markdown 表）与 <table_id>.csv（UTF-8/LF）。"""
    import csv

    table_id = table["id"]
    header = [_cell_text(c) for c in table["columns"]]

    md_path = out_dir / f"{table_id}.md"
    md_lines = [f"# {table['title']}", ""]
    md_lines.append("| " + " | ".join(header) + " |")
    md_lines.append("|" + "|".join(["---"] * len(header)) + "|")
    for row in rows:
        md_lines.append("| " + " | ".join(row) + " |")
    md_path.write_text("\n".join(md_lines) + "\n", encoding="utf-8")

    csv_path = out_dir / f"{table_id}.csv"
    with open(csv_path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)
    return md_path, csv_path


@reference_app.command("tables")
def reference_tables(
    problem: Path = typer.Option(
        ..., "--problem", exists=True, readable=True, help="题目 spec JSON"
    ),
    evidence: Path = typer.Option(
        ..., "--evidence", exists=True, readable=True,
        help="reference run 产出的 evidence.json",
    ),
    out: Path | None = typer.Option(
        None, "--out", help="表格输出目录（默认 runs/<problem_id>-reference/tables）"
    ),
):
    """Q 行结构化字段 → 交付表（md/csv）：按题级 tables.json 声明装配，evidence 为唯一事实源。"""
    # problem_id（与 reference add/run 同一取法）
    try:
        raw = json.loads(problem.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise typer.BadParameter(
            f"题目文件不是有效的 UTF-8 JSON：{exc}", param_hint="--problem"
        ) from exc
    problem_id = raw.get("problem_id")
    if not isinstance(problem_id, str) or not problem_id.strip():
        problem_id = problem.parent.name
    if not re.fullmatch(r"[A-Za-z0-9-]+", problem_id):
        raise typer.BadParameter(
            f"无法确定 problem_id（problem.json 无 problem_id 且目录名 {problem.parent.name!r} 非法）",
            param_hint="--problem",
        )

    # evidence.json：取 result / q_lines
    try:
        ev = json.loads(evidence.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise typer.BadParameter(
            f"evidence.json 不是有效的 UTF-8 JSON：{exc}", param_hint="--evidence"
        ) from exc
    if not isinstance(ev, dict):
        raise typer.BadParameter("evidence.json 顶层必须是对象", param_hint="--evidence")
    q_lines = ev.get("q_lines")
    if not isinstance(q_lines, list):
        raise typer.BadParameter("evidence.json 缺少 q_lines 列表", param_hint="--evidence")

    q_fields = _parse_q_lines_to_fields(q_lines)
    if not q_fields:
        typer.echo("[FAIL] evidence 中没有 Q<id>: 行，无可装配数据", err=True)
        raise typer.Exit(1)

    # 表 spec：题级 tables.json 优先，缺省用内置 C 题默认
    tables_path = Path("problems") / problem_id / "tables.json"
    if tables_path.is_file():
        try:
            tables_spec = json.loads(tables_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise typer.BadParameter(f"{tables_path} 不是有效的 UTF-8 JSON：{exc}") from exc
        spec_note = str(tables_path)
    else:
        tables_spec = _DEFAULT_TABLES_SPEC
        spec_note = "内置 C 题默认 spec（problems/mcm51-c/tables.json 不存在）"
    if not isinstance(tables_spec, dict) or not isinstance(tables_spec.get("tables"), list):
        raise typer.BadParameter("表 spec 顶层必须是 {tables: [...]}")

    if out is None:
        out = Path("runs") / f"{problem_id}-reference" / "tables"
    out.mkdir(parents=True, exist_ok=True)

    typer.echo(f"[OK] reference tables：{problem_id}")
    typer.echo(f"表 spec：{spec_note}")
    for table in tables_spec["tables"]:
        if not isinstance(table, dict):
            raise typer.BadParameter(f"表定义必须是对象：{table!r}")
        if not isinstance(table.get("id"), str) or not isinstance(table.get("title"), str):
            raise typer.BadParameter(f"表定义缺 id/title（字符串）：{table!r}")
        try:
            rows = _build_table_rows(table, q_fields)
        except ValueError as exc:
            raise typer.BadParameter(f"表 {table.get('id')} 装配失败：{exc}") from exc
        md_path, csv_path = _write_table_files(out, table, rows)
        typer.echo(
            f"[OK] {table['id']}  {table['title']}  {len(rows)} 行 → "
            f"{md_path.resolve()}, {csv_path.resolve()}"
        )

    typer.echo("[提示] 表3.2（共同异常点清单）需参考实现额外输出清单数据，暂不装配")


# ---------------------------------------------------------------------------
# reference paper：evidence + brief → paper.md 骨架（零编造）
# ---------------------------------------------------------------------------

# 摘要模板：内置 C 题默认模板（题级占位符模板，不是结果数字）。
# 覆盖方式：problems/<problem_id>/paper_abstract.md 存在时优先读取（纯文本/markdown，
# 数字一律用 {占位符}；占位符 = result.ours 字段名 或 <qid>.<字段名>，如 {q1_gain}、
# {q1.table11}）。装配时占位符由 evidence.json 填充；缺失的占位符渲染为
# 【待展开：<key> 未在 evidence 中】，不编造数字。
_DEFAULT_PAPER_ABSTRACT = """针对边坡多源监测数据下的位移校正、阶段识别、数据治理、分阶段预测与滑坡预警问题，本文以统一状态观为主线，构建数据驱动的时序建模链（校正 → 变点识别 → 数据治理 → 分阶段预测 → 变量组合与预警）。主要量化结果：

- 问题一（位移校正）：校正增益 {q1_gain}，校正后 RMSE {q1_rmse}；表1.1 校正后 y = {q1.table11}；
- 问题二（阶段识别）：两个转换节点编号 {q2_node1}、{q2_node2}；
- 问题三（异常检测）：共同异常点 {q3_common} 个；
- 问题四（分阶段预测）：实验集预测增量 RMSE {q4_rmse}；表4.1 五点预测 {q4.table41}；
- 问题五（变量组合与预警）：最优组合增量 RMSE {q5_rmse}；各阶段速度阈值 {q5.thresholds_slow} / {q5.thresholds_accel} / {q5.thresholds_fast}。"""

_PAPER_NUM_RE = re.compile(
    r"(?<!\d)(\d{1,3}:\d{2}:\d{2})(?!\d)"          # 时间戳 h:mm:ss（整体）
    r"|-?\d{1,3}(?:,\d{3})+(?:\.\d+)?(?!\d)"       # 千分位整数/小数
    r"|-?\d+\.\d+"                                 # 小数
    r"|-?\d+"                                      # 整数
)
_CN_NUMS = "一二三四五六七八九十"


def _cn_num(n: int) -> str:
    """1..10 → 中文数字（章节/假设序号用，避免引入 ASCII 数字 token）。"""
    return _CN_NUMS[n - 1] if 1 <= n <= 10 else str(n)


def _count_paper_numbers(text: str) -> int:
    """数字 token 计数（口径与 scripts/check_paper_numbers.py 一致，仅用于回显统计）。"""
    return len(_PAPER_NUM_RE.findall(text.replace("\u2212", "-")))


def _load_paper_abstract_template(problem_id: str) -> tuple[str, str]:
    """摘要模板：problems/<id>/paper_abstract.md 优先，缺省内置 C 题默认模板。

    返回 (模板文本, 模板来源说明)。模板为纯文本/markdown，数字一律用 {占位符}。
    """
    override = Path("problems") / problem_id / "paper_abstract.md"
    if override.is_file():
        try:
            return override.read_text(encoding="utf-8"), f"problems/{problem_id}/paper_abstract.md"
        except OSError:
            pass
    return _DEFAULT_PAPER_ABSTRACT, "内置 C 题默认模板（src/math_agent/cli.py _DEFAULT_PAPER_ABSTRACT）"


def _fill_paper_abstract(template: str, result_ours: dict, q_fields: dict) -> str:
    """把模板 {占位符} 用 evidence 值替换（正则替换，兼容模板中的字面花括号）。

    - ``{q1_gain}`` 等 → result.ours 字段（整数形浮点按 _cell_text 去尾零）；
    - ``{q1.table11}`` 等 → q_fields 的 <qid>.<字段>（列表以 ", " 连接，保留原文精度）；
    - 缺失的占位符 → 【待展开：<key> 未在 evidence 中】（不编造数字）。
    """

    def _repl(match: re.Match) -> str:
        key = match.group(1).strip()
        if "." in key:
            qid, _, field = key.partition(".")
            qf = q_fields.get(qid) or {}
            if field in qf:
                value = qf[field]
                return ", ".join(str(v) for v in value) if isinstance(value, list) else str(value)
        elif key in result_ours:
            return _cell_text(result_ours[key])
        return f"【待展开：{key} 未在 evidence 中】"

    return re.sub(r"\{([^{}]+)\}", _repl, template)


def _load_paper_brief(brief: Path | None, problem_id: str) -> dict | None:
    """读 brief.json：--brief 缺省尝试 problems/<id>/brief.json；都没有返回 None。"""
    if brief is None:
        candidate = Path("problems") / problem_id / "brief.json"
        if candidate.is_file():
            brief = candidate
        else:
            return None
    try:
        obj = json.loads(brief.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise typer.BadParameter(f"brief.json 不是有效的 UTF-8 JSON：{exc}", param_hint="--brief") from exc
    if not isinstance(obj, dict):
        raise typer.BadParameter("brief.json 顶层必须是对象", param_hint="--brief")
    return obj


def _split_numbered_items(text: str) -> list[str]:
    """把文本按 ①②③… 条目拆分：条目以（文本开头或 ；；：: 之后的）①②③ 开头。

    分级标注（如"（分级①题面原文）"）里的 ① 前面是普通字符、非分隔符，不误拆；
    条目保留各自的 ①②③ 前缀（由调用方决定是否剥离）。
    """
    out: list[str] = []
    buf = ""
    for ch in text:
        if ch in "①②③④⑤⑥⑦⑧⑨⑩" and (
            not buf or buf.rstrip().endswith(("；", ";", "：", ":"))
        ):
            if buf.strip():
                out.append(buf.strip())
            buf = ch
        else:
            buf += ch
    if buf.strip():
        out.append(buf.strip())
    return out


def _paper_assumptions(brief: dict | None) -> tuple[str, list[str], str]:
    """从 brief.required_discussions 取 disc-assumptions。

    返回 (导语, 假设条目列表, 要求说明)；条目保留 brief 原文（含分级标注 ①/②/③），
    只机械去掉条目开头的 ①②③ 编号，不重写、不编造。
    """
    if not brief:
        return "", [], ""
    for item in brief.get("required_discussions") or []:
        if not isinstance(item, dict):
            continue
        if item.get("id") == "disc-assumptions":
            topic = item.get("topic")
            if isinstance(topic, str) and topic.strip():
                parts = _split_numbered_items(topic)
                preamble = parts[0] if parts and not parts[0].startswith("①") else ""
                items = [
                    re.sub(r"^[①②③④⑤⑥⑦⑧⑨⑩]\s*", "", p)
                    for p in parts
                    if p.startswith(("①", "②", "③", "④", "⑤", "⑥", "⑦", "⑧", "⑨", "⑩"))
                ]
                requirement = item.get("requirement")
                return preamble, items, requirement if isinstance(requirement, str) else ""
    return "", [], ""


def _direction_first_clause(text: str) -> str:
    """取 direction 的第一句（到首个 ；或 。 为止），作为"方向一句话"。"""
    for sep in ("；", "。", "\n"):
        idx = text.find(sep)
        if idx > 0:
            return text[:idx].strip()
    return text.strip()


def _question_direction(brief: dict | None, qid: str) -> str:
    """per_question_direction 里 question_id==qid 的 direction 第一句；无则空串。"""
    if not brief:
        return ""
    for item in brief.get("per_question_direction") or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("question_id", "")) == qid:
            direction = item.get("direction")
            if isinstance(direction, str) and direction.strip():
                return _direction_first_clause(direction)
    return ""


def _evidence_line_no(lines: list[str], needle: str) -> int | None:
    """找文件行列表里包含 needle 的行号（1 起）；找不到返回 None。"""
    for i, line in enumerate(lines, 1):
        if needle in line:
            return i
    return None


def _relpath_from(path: Path, base_dir: Path) -> str:
    """path 相对 base_dir 的路径（正斜杠），供溯源表"来源"列引用。"""
    try:
        return os.path.relpath(str(path), str(base_dir)).replace("\\", "/")
    except ValueError:
        return str(path)


def _table_md(table: dict, rows: list[list[str]]) -> str:
    """表 → markdown 表字符串（不含标题行；标题由调用方作为小标题渲染）。"""
    header = [_cell_text(c) for c in table["columns"]]
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join(["---"] * len(header)) + "|"]
    for row in rows:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def _reference_file_hashes(problem_id: str) -> list[tuple[str, str]]:
    """reference 目录 *.py 的文件名（reference/xxx.py）+ sha256：重算自 source/reference/。"""
    base = Path("problems") / problem_id / "source" / "reference"
    if not base.is_dir():
        return []
    return sorted(
        (f"reference/{f.name}", hashlib.sha256(f.read_bytes()).hexdigest())
        for f in base.glob("*.py")
    )


def _paper_section_stats(paper_text: str) -> list[tuple[str, int, int]]:
    """按 ## 顶级章节统计（章节名, 字数, 数字数）；标题前内容并入"（引言）"。"""
    stats: list[tuple[str, int, int]] = []
    current = "（引言）"
    buffer: list[str] = []
    for line in paper_text.splitlines():
        if line.startswith("## "):
            if buffer:
                text = "\n".join(buffer)
                stats.append((current, len(text), _count_paper_numbers(text)))
            current = line[3:].strip()
            buffer = []
        else:
            buffer.append(line)
    if buffer:
        text = "\n".join(buffer)
        stats.append((current, len(text), _count_paper_numbers(text)))
    return stats


def _build_trace_table(
    result_ours: dict,
    q_fields: dict,
    evidence_lines: list[str],
    tables_spec: dict,
    tables_path: Path | None,
    out: Path,
) -> str:
    """附录 A 溯源表：每个关键数字 → evidence.json（或 tables.json）「文件 + 行号」。

    行号在生成时实扫文件得到，保证 scripts/check_paper_numbers.py --traceability --strict
    可逐条断言；多值字段（表行）一行断言全部值。标签一律不含 ASCII 数字，
    避免被当作所声称数字。
    """
    rows: list[str] = []
    seen: set[str] = set()

    def add(*cells: str) -> None:
        rows.append("| " + " | ".join(cells) + " |")

    def cite_evidence(needle: str) -> str:
        # Q 行列表值可能以 ", "（含空格）或 "," 分隔，两种 needle 都试
        line_no = _evidence_line_no(evidence_lines, needle)
        if line_no is None:
            line_no = _evidence_line_no(evidence_lines, needle.replace(",", ", "))
        if line_no is not None:
            return f"`evidence.json` 第 {line_no} 行"
        return "`evidence.json`（全文）"

    # result.ours 7 指标（RESULT 行）
    for key, label in (
        ("q1_gain", "Q1 校正增益"),
        ("q1_rmse", "Q1 校正后 RMSE"),
        ("q2_node1", "Q2 转换节点一编号"),
        ("q2_node2", "Q2 转换节点二编号"),
        ("q3_common", "Q3 共同异常点数量"),
        ("q4_rmse", "Q4 预测增量 RMSE"),
        ("q5_rmse", "Q5 最优组合增量 RMSE"),
    ):
        value = result_ours.get(key)
        if value is None:
            continue
        rendered = _cell_text(value)
        if rendered in seen:
            continue
        seen.add(rendered)
        needle = json.dumps({key: value})[1:-1]
        add(rendered, label, cite_evidence(needle))

    # Q 行字段（多值一行，值来自该 Q 行原文）
    qfield_groups = (
        ("q1", "table11", "Q1 校正后 y（五行）"),
        ("q2", "speeds", "Q2 各阶段平均速度（mm/h）"),
        ("q3", "table31", "Q3 单变量异常点数量（五列）"),
        ("q4", "table41", "Q4 实验集预测值（五点）"),
        ("q5", "thresholds_slow", "Q5 缓慢阶段速度阈值"),
        ("q5", "thresholds_accel", "Q5 加速阶段速度阈值"),
        ("q5", "thresholds_fast", "Q5 快速阶段速度阈值"),
    )
    for qid, field, label in qfield_groups:
        qf = q_fields.get(qid) or {}
        value = qf.get(field)
        if not isinstance(value, list) or not value:
            continue
        cells = [str(v) for v in value]
        if all(c in seen for c in cells):
            continue
        seen.update(cells)
        add(*cells, label, cite_evidence(f"{field}=[" + ",".join(cells) + "]"))

    # tables.json 题面静态列（lead_columns）：数字列一行断言；字符串列（时间点）逐行断言
    if tables_path is not None and isinstance(tables_spec, dict):
        try:
            tlines = tables_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            tlines = []
        if tlines:
            src = _relpath_from(tables_path, out.parent)
            for table in tables_spec.get("tables") or []:
                if not isinstance(table, dict):
                    continue
                lead = table.get("lead_columns") or {}
                if not isinstance(lead, dict):
                    continue
                for col, values in lead.items():
                    if not isinstance(values, list) or not values:
                        continue
                    numeric = all(isinstance(v, (int, float)) for v in values)
                    if numeric:
                        cells = [_cell_text(v) for v in values]
                        if all(c in seen for c in cells):
                            continue
                        seen.update(cells)
                        joined = ", ".join(cells)
                        line_no = _evidence_line_no(tlines, joined)
                        if line_no is not None:
                            label = f"{col}（题面静态列）"
                            add(*cells, label, f"`{src}` 第 {line_no} 行")
                    else:
                        for v in values:
                            text = str(v)
                            line_no = _evidence_line_no(tlines, text)
                            if line_no is None:
                                continue
                            label = f"{col}（题面静态列）"
                            add(text, label, f"`{src}` 第 {line_no} 行")
    return "\n".join(rows)


def _build_paper_md(
    *,
    title: str,
    questions: list,
    abstract: str,
    template_source: str,
    brief: dict | None,
    q_lines: list[str],
    q_fields: dict,
    result_ours: dict,
    table_rows: list,
    evidence_lines: list[str],
    tables_spec: dict,
    tables_path: Path | None,
    out: Path,
    problem_id: str,
) -> str:
    """装配 paper.md 全文（骨架）：数字全部来自 evidence/tables/题面/brief，prose 用占位行。"""
    parts: list[str] = []
    parts.append("# " + title + "\n")
    parts.append(
        "<!-- 本文档由 `math-agent reference paper` 自动装配（论文骨架，零编造）："
        "数字唯一事实源=evidence.json；题面静态列来源 tables.json；"
        "prose 分析以 【待展开】 占位，待人工或后续阶段展开 -->\n"
    )

    # 摘要（题级模板，占位符由 evidence 填充）
    parts.append("## 摘要\n")
    parts.append(abstract + "\n")
    parts.append(f"<!-- 摘要模板来源：{template_source}；占位符由 evidence.json 填充 -->\n")

    # 问题重述（题面原文）
    parts.append("## 问题重述\n")
    for q in questions:
        if isinstance(q, str) and q.strip():
            parts.append(q + "\n")
    parts.append("> 注：本节为题目原文（problem.json questions），数字属题面常量，非结果数字。\n")

    # 模型假设（brief disc-assumptions，分级标注）
    parts.append("## 模型假设\n")
    preamble, assumptions, requirement = _paper_assumptions(brief)
    if assumptions:
        parts.append("> 来源：brief.json required_discussions[\"disc-assumptions\"]（人工起草口径，非本文生成）。\n")
        if preamble:
            parts.append(preamble + "\n")
        for i, item in enumerate(assumptions, 1):
            parts.append(f"- 假设{_cn_num(i)}：{item}")
        parts.append("")
        if requirement:
            parts.append(f"> 要求：{requirement}")
            parts.append("")
    else:
        parts.append(
            "> 【待展开：brief.json 缺失（--brief 未给且 problems/<id>/brief.json 不存在），"
            "模型假设待人工补充】\n"
        )
    parts.append("> 【待展开：逐条论证假设的建模影响与依据讨论】\n")

    # 求解结果（Q1~Q5：方向一句话 + Q 行原文数字）
    parts.append("## 求解结果\n")
    for qid in ("1", "2", "3", "4", "5"):
        direction = _question_direction(brief, qid)
        qline = next((ln for ln in q_lines if re.match(rf"^Q{qid}:", ln.strip())), None)
        parts.append(f"### 问题{qid}\n")
        if direction:
            parts.append(f"- **方向**（brief per_question_direction q{qid}-direction 首句）：{direction}")
        else:
            parts.append(f"- **方向**：> 【待展开：brief 缺失，问题{qid}方向待补充】")
        if qline:
            parts.append(f"- **Q{qid} 行数字**（evidence.json q_lines 原文）：`{qline}`")
        else:
            parts.append(f"- **Q{qid} 行数字**：> 【待展开：evidence 缺 Q{qid} 行，该问数字待补充】")
        parts.append("")
        parts.append(f"> 【待展开：问题{qid}的模型推导/分析/检验 prose】\n")

    # 交付表（三张表，复用 P3 装配逻辑）
    parts.append("## 交付表\n")
    parts.append("> 来源：evidence.json q_lines（Q 行字段）+ tables.json 题面静态列；装配逻辑与 `reference tables` 一致。\n")
    for table, rows in table_rows:
        parts.append(f"### {table['title']}\n")
        parts.append(_table_md(table, rows) + "\n")
    parts.append("> 注：题面表3.2（多变量共同异常点清单）不在 evidence 范围（Q 行只输出计数），骨架不装配该清单。\n")

    # 附录 A 数字溯源
    parts.append("## 附录 A 数字溯源\n")
    parts.append(
        "> 格式约定：每行「论文数字 … | 来源」，来源 = evidence.json（result.ours / Q 行字段）"
        "或 tables.json（题面静态列）的「文件 + 行号」；"
        "可用 scripts/check_paper_numbers.py --traceability 核对。"
        "问题重述/模型假设/方向摘要中的数字为题面与 brief 原文（problem.json / brief.json），"
        "非结果数字，不逐条列入本表。\n"
    )
    trace_md = _build_trace_table(
        result_ours, q_fields, evidence_lines, tables_spec, tables_path, out
    )
    if trace_md:
        parts.append("| 论文数字 | 来源 |")
        parts.append("| --- | --- |")
        parts.append(trace_md + "\n")
    parts.append(
        "> 注：表3.1 总数列为派生值（Q3 table31 五行求和），不在 evidence 原文中，"
        "属允许标注的派生值；表3.2 清单不在 evidence 范围。\n"
    )

    # 附录 B 代码清单（reference 目录 7 文件 + sha256，重算）
    parts.append("## 附录 B 代码清单\n")
    hashes = _reference_file_hashes(problem_id)
    if hashes:
        parts.append("> 来源：重算自 problems/<problem_id>/source/reference/（sha256 与 problem.json source_files 登记一致）。\n")
        parts.append("| 文件 | sha256 |")
        parts.append("| --- | --- |")
        for name, digest in hashes:
            parts.append(f"| {name} | {digest} |")
        parts.append("")
    else:
        parts.append("> 【待展开：problems/<problem_id>/source/reference/ 不存在，代码清单待补充】\n")

    return "\n".join(parts)


@reference_app.command("paper")
def reference_paper(
    problem: Path = typer.Option(
        ..., "--problem", exists=True, readable=True, help="题目 spec JSON"
    ),
    evidence: Path = typer.Option(
        ..., "--evidence", exists=True, readable=True,
        help="reference run 产出的 evidence.json",
    ),
    brief: Path | None = typer.Option(
        None, "--brief", exists=True, readable=True,
        help="brief.json（缺省尝试 problems/<id>/brief.json）",
    ),
    out: Path | None = typer.Option(
        None, "--out", help="paper.md 输出路径（默认 runs/<problem_id>-reference/paper.md）"
    ),
):
    """evidence + brief → paper.md 骨架：摘要/问题重述/模型假设/求解结果/交付表/附录A溯源/附录B代码清单。

    零编造：所有数字均来自 evidence.json（result.ours + Q 行）、tables.json（题面静态列）
    或题面/brief 原文；分析 prose 留 【待展开】 占位行。摘要模板可被
    problems/<problem_id>/paper_abstract.md 覆盖（占位符 = result.ours 字段名或 <qid>.<字段>）。
    """
    _read_problem_spec(problem)
    try:
        raw = json.loads(problem.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise typer.BadParameter(
            f"题目文件不是有效的 UTF-8 JSON：{exc}", param_hint="--problem"
        ) from exc
    problem_id = raw.get("problem_id")
    if not isinstance(problem_id, str) or not problem_id.strip():
        problem_id = problem.parent.name
    if not re.fullmatch(r"[A-Za-z0-9-]+", problem_id):
        raise typer.BadParameter(
            f"无法确定 problem_id（problem.json 无 problem_id 且目录名 {problem.parent.name!r} 非法）",
            param_hint="--problem",
        )
    title = raw.get("title", "")
    questions = raw.get("questions", [])
    if not isinstance(title, str):
        title = ""
    if not isinstance(questions, list):
        questions = []

    # evidence.json：result.ours / q_lines（数字唯一事实源）
    try:
        ev = json.loads(evidence.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise typer.BadParameter(
            f"evidence.json 不是有效的 UTF-8 JSON：{exc}", param_hint="--evidence"
        ) from exc
    if not isinstance(ev, dict):
        raise typer.BadParameter("evidence.json 顶层必须是对象", param_hint="--evidence")
    result_map = ev.get("result")
    result_ours = result_map.get("ours", {}) if isinstance(result_map, dict) else {}
    if not isinstance(result_ours, dict):
        result_ours = {}
    q_lines = ev.get("q_lines")
    if not isinstance(q_lines, list):
        raise typer.BadParameter("evidence.json 缺少 q_lines 列表", param_hint="--evidence")
    q_fields = _parse_q_lines_to_fields(q_lines)
    if not q_fields:
        typer.echo("[FAIL] evidence 中没有 Q<id>: 行，无可装配数据", err=True)
        raise typer.Exit(1)

    brief_data = _load_paper_brief(brief, problem_id)

    # 表 spec + 装配（与 reference tables 同一套逻辑）
    tables_path = Path("problems") / problem_id / "tables.json"
    if tables_path.is_file():
        try:
            tables_spec = json.loads(tables_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise typer.BadParameter(f"{tables_path} 不是有效的 UTF-8 JSON：{exc}") from exc
    else:
        tables_spec = _DEFAULT_TABLES_SPEC
    if not isinstance(tables_spec, dict) or not isinstance(tables_spec.get("tables"), list):
        raise typer.BadParameter("表 spec 顶层必须是 {tables: [...]}")
    table_rows: list[tuple[dict, list[list[str]]]] = []
    for table in tables_spec["tables"]:
        if not isinstance(table, dict):
            raise typer.BadParameter(f"表定义必须是对象：{table!r}")
        try:
            table_rows.append((table, _build_table_rows(table, q_fields)))
        except ValueError as exc:
            raise typer.BadParameter(f"表 {table.get('id')} 装配失败：{exc}") from exc

    if out is None:
        out = Path("runs") / f"{problem_id}-reference" / "paper.md"
    out.parent.mkdir(parents=True, exist_ok=True)

    template, template_source = _load_paper_abstract_template(problem_id)
    abstract = _fill_paper_abstract(template, result_ours, q_fields)
    evidence_lines = evidence.read_text(encoding="utf-8").splitlines()
    paper = _build_paper_md(
        title=title,
        questions=questions,
        abstract=abstract,
        template_source=template_source,
        brief=brief_data,
        q_lines=q_lines,
        q_fields=q_fields,
        result_ours=result_ours,
        table_rows=table_rows,
        evidence_lines=evidence_lines,
        tables_spec=tables_spec,
        tables_path=tables_path if tables_path.is_file() else None,
        out=out,
        problem_id=problem_id,
    )
    out.write_text(paper, encoding="utf-8")

    brief_note = "--brief 指定"
    if brief is None:
        cand = Path("problems") / problem_id / "brief.json"
        brief_note = str(cand) if cand.is_file() else "缺失（假设/方向用【待展开】占位）"
    typer.echo(f"[OK] reference paper：{problem_id}")
    typer.echo(f"paper.md：{out.resolve()}")
    typer.echo(f"摘要模板：{template_source}")
    typer.echo(f"brief：{brief_note}")
    typer.echo("[章节统计]（字数 / 数字数）")
    for name, chars, nums in _paper_section_stats(paper):
        typer.echo(f"  ## {name}：{chars} 字 / {nums} 数字")
    typer.echo(
        "[提示] 数字红线校验：python scripts/check_paper_numbers.py "
        f"--paper {out} --evidence {evidence}"
    )
    typer.echo("[提示] 或：math-agent review check --paper <md> --evidence <证据>")


@reference_app.command("verify")
def reference_verify(
    problem: Path = typer.Option(
        ..., "--problem", exists=True, readable=True, help="题目 spec JSON"
    ),
    evidence: Path | None = typer.Option(
        None, "--evidence", exists=True, readable=True,
        help="reference run 的 evidence.json（默认 runs/<id>-reference/evidence.json）",
    ),
    out: Path | None = typer.Option(
        None, "--out", help="evidence-package.json 输出路径（默认 problems/<id>/evidence-package.json）",
    ),
):
    """S5 机械验证 v0：读 evidence.json，检查 run 成功 / 无 nan-inf / 有 result。"""
    _read_problem_spec(problem)
    problem_id = _cli_problem_id(problem)
    if evidence is None:
        evidence = Path("runs") / f"{problem_id}-reference" / "evidence.json"
        if not evidence.is_file():
            typer.echo(f"[FAIL] 未找到 evidence.json：{evidence}（先 `reference run` 或传 --evidence）", err=True)
            raise typer.Exit(1)
    try:
        ev = load_evidence(evidence)
    except ValueError as exc:
        typer.echo(f"[FAIL] {exc}", err=True)
        raise typer.Exit(1)

    ref_meta: dict = {}
    ref_json = Path("problems") / problem_id / "reference.json"
    if ref_json.is_file():
        try:
            loaded = json.loads(ref_json.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                ref_meta = loaded
        except (OSError, UnicodeError, json.JSONDecodeError):
            ref_meta = {}
    entry = str(ref_meta.get("entry") or ev.get("entry") or "").strip()
    solver_path = f"source/reference/{Path(entry).name}" if entry else "source/reference"
    solver_sha = ""
    for item in ref_meta.get("files") or []:
        if not isinstance(item, dict):
            continue
        item_path = str(item.get("path") or "")
        if entry and item_path.endswith(Path(entry).name):
            solver_path = item_path if item_path.startswith("source/") else f"source/{item_path}"
            solver_sha = str(item.get("sha256") or "")
            break
    if not solver_sha and entry:
        entry_file = Path("problems") / problem_id / "source" / "reference" / Path(entry).name
        if entry_file.is_file():
            solver_sha = hashlib.sha256(entry_file.read_bytes()).hexdigest()
            solver_path = f"source/reference/{entry_file.name}"

    package = build_package(
        problem_id=problem_id,
        solver_path=solver_path,
        solver_sha256=solver_sha,
        evidence_path=str(evidence),
        evidence=ev,
    )
    dest = out if out is not None else Path("problems") / problem_id / "evidence-package.json"
    write_package(package, dest)
    ok = package_ok(package)
    typer.echo(json.dumps(package, ensure_ascii=False, indent=2))
    typer.echo(f"evidence-package: {dest}")
    if not ok:
        raise typer.Exit(1)


@app.command("review-check", help=GROUP_HELP["review"])
def review_check(
    paper: Path | None = typer.Option(
        None, "--paper", exists=True, readable=True, help="论文 md",
    ),
    evidence: list[Path] = typer.Option(
        [], "--evidence", help="数字溯源证据文件（可多次）",
    ),
    gap_json: list[Path] = typer.Option(
        [], "--gap-json", help="check_gap_trigger 的证据 json（可多次；可选）",
    ),
    traceability: Path | None = typer.Option(
        None, "--traceability", exists=True, readable=True, help="附录 A 溯源表 md",
    ),
    strict: bool = typer.Option(False, "--strict", help="脚本 --strict：有问题则退出码 1"),
    out: Path | None = typer.Option(
        None, "--out", help="评审报告 JSON（默认 stdout 旁的 review-report.json）",
    ),
    as_json: bool = typer.Option(False, "--json", help="向 stdout 打印 JSON 报告"),
):
    """S7 包装 check_paper_numbers / check_assumption_claims / check_gap_trigger。"""
    payload = run_review(
        paper=paper,
        evidence=list(evidence) or None,
        json_evidence=list(gap_json) or None,
        strict=strict,
        traceability=traceability,
    )
    report_path = out if out is not None else Path("review-report.json")
    write_review_report(payload, report_path)
    if as_json:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        typer.echo(f"review exit={payload['exit_code']} ok={payload['ok']}")
        for tool in payload.get("tools") or []:
            typer.echo(f"  {tool.get('name')}: {tool.get('exit_code')}")
        typer.echo(f"report: {report_path if report_path.suffix == '.json' else report_path / 'review-report.json'}")
    if payload["exit_code"] != 0:
        raise typer.Exit(payload["exit_code"])


problem_app = typer.Typer(
    help=GROUP_HELP["problem"],
    no_args_is_help=True,
)


@problem_app.command("import")
def problem_import(
    source: Path = typer.Argument(..., exists=True, readable=True, help="题面文件（md/txt 直接复制；pdf/docx 走现有 ingest 管线）"),
    problem_id: str = typer.Option(..., "--problem-id", help="题号（字母/数字/连字符，如 mcm51-b）"),
    attachments: Path | None = typer.Option(
        None, "--attachments", exists=True, file_okay=False, help="附件目录（可选，逐文件归档+哈希）",
    ),
    force: bool = typer.Option(False, "--force", help="覆盖已存在的题目目录（慎用）"),
):
    """最小导入：source/ 归档 + sha256 清单 + problem.md + spec v2 骨架（不含 AI 起草）。"""
    import shutil
    from datetime import datetime, timezone

    if not re.fullmatch(r"[A-Za-z0-9-]+", problem_id):
        raise typer.BadParameter("problem_id 只能是字母/数字/连字符", param_hint="--problem-id")
    target = Path("problems") / problem_id
    if target.exists() and not force:
        raise typer.BadParameter(
            f"problems/{problem_id} 已存在；换题号或 --force 覆盖", param_hint="--problem-id",
        )
    target.mkdir(parents=True, exist_ok=True)
    (target / "source").mkdir(exist_ok=True)

    def _archive(path: Path) -> dict:
        dest = target / "source" / path.name
        shutil.copyfile(path, dest)
        digest = hashlib.sha256(dest.read_bytes()).hexdigest()
        # path 为相对 data_dir（"source"）的文件名，data_hint 用 data_dir+path 拼接
        return {"path": path.name, "sha256": digest, "name": path.name}

    archived = [_archive(source)]
    if attachments is not None:
        for f in sorted(attachments.iterdir()):
            if f.is_file():
                archived.append(_archive(f))

    # 事实层 problem.md：md/txt 直接复制；pdf/docx 走现有 ingest 管线（乱码可视觉回退）
    if source.suffix.lower() in {".md", ".txt"}:
        shutil.copyfile(source, target / "problem.md")
    else:
        from math_agent.problem_ingest import parse_problem_file

        try:
            parsed = parse_problem_file(source, write_md=False)
        except Exception as exc:  # noqa: BLE001
            raise typer.BadParameter(
                f"题面解析失败：{exc}；请先人工整理为 md 再 import（复杂文件可用 scripts/extract_file_meta.py）",
            ) from exc
        (target / "problem.md").write_text(parsed.text, encoding="utf-8")

    (target / "source" / "manifest.json").write_text(
        json.dumps({a["name"]: a["sha256"] for a in archived}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    data_files = []
    for a in archived:
        lower = a["name"].lower()
        if lower.endswith((".xlsx", ".xls")):
            file_type = "xlsx"
        elif lower.endswith(".csv"):
            file_type = "csv"
        elif lower.endswith(".pdf"):
            file_type = "pdf"
        elif lower.endswith(".docx"):
            file_type = "docx"
        elif lower.endswith((".md", ".txt")):
            file_type = "md"
        else:
            file_type = "txt"
        data_files.append({
            "filename": a["name"], "file_type": file_type, "path": a["path"], "summary": {},
        })

    spec = {
        "schema_version": 2,
        "problem_id": problem_id,
        "title": "",
        "background": "",
        "questions": [],
        "source": {
            "md_path": "problem.md",
            "source_files": [{"path": a["path"], "sha256": a["sha256"]} for a in archived],
            "imported_at": datetime.now(timezone.utc).isoformat(),
            "imported_by": "cli",
        },
        "feasibility": {
            "checklist": ["external_data", "simulation", "survey", "supercomputer"],
            "blockers": [],
            "assessment": "",
        },
        "data_files": data_files,
        "data_dir": "source",
    }
    (target / "problem.json").write_text(
        json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8",
    )

    typer.echo(f"[OK] problems/{problem_id} 已导入：source 归档 {len(archived)} 个文件 + 哈希 + problem.md + spec 骨架")
    typer.echo("下一步（按 brief-playbook）：人工填写 problem.json 的 title/background/questions/feasibility，")
    typer.echo(f"然后 `math-agent brief init --problem problems/{problem_id}/problem.json --out problems/{problem_id}/brief.json`")


@problem_app.command("show")
def problem_show(
    problem_id: str = typer.Argument(..., help="题号（problems/<题号>/ 目录名）"),
):
    """总览：spec 摘要 + 附件 + feasibility + brief 状态 + 最近 run 指针。"""
    target = Path("problems") / problem_id
    spec_path = target / "problem.json"
    if not spec_path.is_file():
        raise typer.BadParameter(f"problems/{problem_id}/problem.json 不存在", param_hint="problem_id")
    try:
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise typer.BadParameter(f"problem.json 损坏：{exc}") from exc

    typer.echo(f"=== problem show {problem_id} ===")
    typer.echo(f"title    : {spec.get('title') or '（未填）'}")
    qs = spec.get("questions") or []
    typer.echo(f"questions: {len(qs)} 条" + ("" if qs else "（未填）"))
    blockers = spec.get("feasibility", {}).get("blockers") or []
    typer.echo(f"blockers : {blockers if blockers else '空（可达）'}")
    src = spec.get("source", {})
    files = src.get("source_files") or []
    typer.echo(f"source   : {len(files)} 个文件已归档（md={src.get('md_path')}）")
    brief_path = target / "brief.json"
    if brief_path.is_file():
        digest = hashlib.sha256(brief_path.read_bytes()).hexdigest()[:12]
        typer.echo(f"brief    : {brief_path}（sha256 前 12 位 {digest}）→ 运行 `brief check` 校验")
    else:
        typer.echo("brief    : 未生成（`brief init --problem problems/<id>/problem.json ...`）")

    fp = _problem_fingerprint({
        k: spec.get(k) for k in ("title", "background", "questions", "data_files", "data_dir")
    })
    hits = []
    runs_root = Path("runs")
    if runs_root.is_dir():
        for manifest_path in sorted(runs_root.glob("*/run_manifest.json"), reverse=True):
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                continue
            if manifest.get("problem_sha256") == fp:
                hits.append(manifest_path.parent.name)
    typer.echo("最近 run  : " + ("、".join(hits[:5]) + "（见 runs/ 对应目录）" if hits else "无（尚未跑过本题）"))


@problem_app.command("stage")
def problem_stage(
    problem_id: str = typer.Argument(..., help="题号（problems/<题号>/ 目录名）"),
    as_json: bool = typer.Option(False, "--json", help="输出 JSON"),
    runs: Path | None = typer.Option(
        None, "--runs", help="runs 根目录（默认 ./runs，不存在则不查 S8/S9）",
    ),
):
    """S0–S8 阶段推演（只看磁盘文件，无工作流引擎）。"""
    target = Path("problems") / problem_id
    if not target.is_dir():
        raise typer.BadParameter(f"problems/{problem_id} 不存在", param_hint="problem_id")
    runs_root = runs
    if runs_root is None:
        default_runs = Path("runs")
        runs_root = default_runs if default_runs.is_dir() else None
    result = infer_stage(target, runs_root)
    if as_json:
        typer.echo(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        typer.echo(format_stage_text(result))


app.add_typer(problem_app, name="problem")


def _write_brief_file(out: Path, payload: dict, force: bool) -> None:
    """原子写入 brief.json；已存在且未 --force 时拒绝。"""
    if out.exists() and not force:
        raise typer.BadParameter(f"输出文件已存在：{out}（用 --force 覆盖）", param_hint="--out")
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + f".tmp-{os.getpid()}")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    os.replace(tmp, out)


def _brief_norm_tokens(s: str) -> tuple[set[str], set[str]]:
    """提取匹配用的数字段与字母段集合（小写、字母段 len>=2 才保留）。

    `mcm51-a` -> ({"51"}, {"mcm"})；`2026 51MCM Problem A` -> ({"2026","51"}, {"mcm","problem"})。
    裸子串对这两种写法双向都不包含（B04 真跑误报案例），token 集合则稳定匹配。
    """
    digits = set(re.findall(r"\d+", s))
    letters = {t.lower() for t in re.findall(r"[A-Za-z]+", s) if len(t) >= 2}
    return digits, letters


def _brief_problem_mismatch(pid: str, title: str) -> bool:
    """brief.problem_id 与题目（标题+小问）是否不匹配：pid 的 token 全部在题目 token 中才匹配。"""
    pd, pl = _brief_norm_tokens(pid)
    td, tl = _brief_norm_tokens(title)
    if not pd and not pl:
        return False  # pid 无语义 token（如纯符号）→ 不判断，避免噪音
    return not (pd <= td and pl <= tl)


def _warn_brief_problem_mismatch(brief_obj, spec: dict) -> None:
    """brief.problem_id 与题目宽松匹配；不匹配仅警告（防误用，不阻塞）。"""
    pid = (getattr(brief_obj, "problem_id", "") or "").strip()
    if not pid:
        return
    title = (spec.get("title") or "") + " " + " ".join(spec.get("questions", []))
    if _brief_problem_mismatch(pid, title):
        typer.echo(
            f"[WARN] brief.problem_id={pid!r} 与题目（{title[:40]}...）不匹配；"
            f"请确认 brief 是否属于本题",
            err=True,
        )


@brief_app.command("init")
def brief_init(
    problem: Path = typer.Option(..., exists=True, readable=True, help="题目 spec JSON"),
    out: Path = typer.Option(
        Path("problems/brief.json"), help="brief.json 输出路径"
    ),
    force: bool = typer.Option(False, "--force", help="覆盖已存在的文件"),
):
    """生成空白 brief 模板（人工填写后运行 `brief check` 校验）。"""
    spec = _read_problem_spec(problem)
    payload = {
        "schema_version": 1,
        "problem_id": "",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source": ["human"],
        "per_question_direction": [],
        "formula_notes": [],
        "required_discussions": [],
        "red_lines": [],
        "figure_plan": [],
        "scoring_notes": [],
        "data_notes": [],
        "reference_direction": [],
    }
    _write_brief_file(out, payload, force)
    title = spec.get("title") or (spec.get("questions") or [""])[0]
    typer.echo(f"brief 模板已生成：{out}")
    typer.echo(f"题目：{title[:60]}")
    typer.echo("八字段结构与示例见 docs/10-ModelingBrief实施计划书.md；")
    typer.echo("填写后运行 `math-agent brief check --brief <path>` 校验；")
    typer.echo("建议沉淀到 problems/<题号>/brief.json 跨题复用。")


@brief_app.command("check")
def brief_check(
    brief: Path = typer.Option(..., exists=True, readable=True, help="brief.json 路径"),
):
    """校验 brief.json 是否符合 schema（纯校验，不调用 LLM）。"""
    from math_agent.brief import brief_item_ids, load_brief
    from math_agent.brief_dialogue import FIELD_SPECS

    try:
        obj = load_brief(brief)
    except ValueError as exc:
        typer.echo(f"[FAIL] {exc}", err=True)
        raise typer.Exit(1)
    ids = brief_item_ids(obj)
    typer.echo(f"[OK] {brief} 通过校验（schema_version={obj.schema_version}）")
    for field_name, label, _, _ in FIELD_SPECS:
        count = len(getattr(obj, field_name) or [])
        typer.echo(f"  - {field_name}（{label}）：{count} 条")
    typer.echo(f"共 {len(ids)} 条待回应条目（brief_coverage 门禁按这些 id 校验）")
    if not ids:
        typer.echo("[WARN] brief 全为空——不会注入任何约束（如需约束请填写）")


@brief_app.command("dialogue")
def brief_dialogue(
    problem: Path = typer.Option(..., exists=True, readable=True, help="题目 spec JSON"),
    out: Path = typer.Option(
        Path("problems/brief.json"), help="brief.json 输出路径"
    ),
    assist: bool = typer.Option(
        True, "--assist/--no-assist",
        help="每字段先由 LLM 按题面+数据摘要起草建议，再人工确认/修改",
    ),
    force: bool = typer.Option(False, "--force", help="覆盖已存在的文件"),
):
    """交互式生成 brief：逐字段问答（--assist 时 LLM 先起草，人工确认）。"""
    from math_agent.brief import ModelingBrief
    from math_agent.brief_dialogue import (
        FIELD_SPECS, assemble_brief, build_context, draft_field,
    )
    from math_agent.config import STRONG_MODEL
    from math_agent.state import DataFileInfo

    spec = _read_problem_spec(problem)
    data_files = [DataFileInfo(**f) for f in spec.get("data_files", [])]
    context = build_context(
        spec.get("title", ""), spec.get("background", ""),
        spec.get("questions", []), data_files,
    )
    fields: dict[str, list] = {}
    for field_name, label, desc, schema_hint in FIELD_SPECS:
        typer.echo(f"\n=== 字段 {field_name}（{label}）===")
        typer.echo(desc)
        typer.echo(f"结构：{schema_hint}")
        draft = None
        if assist:
            draft = draft_field(field_name, context, model=STRONG_MODEL)
            if draft:
                typer.echo("[AI 草稿]")
                typer.echo(json.dumps(draft, ensure_ascii=False, indent=2))
            else:
                typer.echo("[AI 起草失败——请人工填写或回车跳过]")
        typer.echo("回车=采用草稿/跳过；粘贴 JSON 数组=替换；输入 skip=跳过")
        while True:
            try:
                raw = typer.prompt("内容", default="")
            except EOFError:
                typer.echo("\n[dialogue 中止]")
                raise typer.Exit(130)
            raw = (raw or "").strip()
            if raw == "skip":
                break
            if raw == "":
                if draft:
                    fields[field_name] = draft
                break
            try:
                parsed = json.loads(raw)
                if not isinstance(parsed, list):
                    raise ValueError("必须是 JSON 数组")
            except (ValueError, json.JSONDecodeError) as exc:
                typer.echo(f"解析失败：{exc}，请重新粘贴（或回车采用草稿/跳过）")
                continue
            fields[field_name] = parsed
            break
    payload = assemble_brief(
        fields,
        problem_id="",
        source=["human", "model_draft"] if assist else ["human"],
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    try:
        ModelingBrief.model_validate(payload)
    except Exception as exc:
        typer.echo(f"[FAIL] 组装结果不符合 schema：{exc}", err=True)
        typer.echo("可手动修正文件后运行 `brief check` 校验。", err=True)
        raise typer.Exit(1)
    _write_brief_file(out, payload, force)
    total = sum(len(v) for v in fields.values())
    typer.echo(f"[OK] brief 已写入：{out}（共 {total} 条条目）")
    typer.echo("运行：math-agent run --problem <spec> --brief <path>")


# 可选 ML 库清单已迁至 ops_preflight.OPTIONAL_ML_LIBS


def _dry_run_preflight(
    problem_path: Path, spec: dict, brief_path: Path | None,
    brief_obj, out: Path, thread: str, force: bool,
) -> None:
    """`run --dry-run`：启动前全项预检（不烧 token）；写入 preflight.json。"""
    from math_agent.brief import brief_item_ids

    payload = run_preflight(
        problem_path=problem_path,
        spec=spec,
        brief_path=brief_path,
        out=out,
        force=force,
    )
    write_preflight_json(payload, out)
    if problem_path.name == "problem.json":
        write_preflight_json(payload, problem_path.parent)

    problems_found = payload.get("problems") or []
    typer.echo("=== run --dry-run 预检 ===")
    typer.echo(f"problem : {problem_path}（{(spec.get('title') or '')[:50]}...）")
    typer.echo(f"thread  : {thread}")
    typer.echo(f"out     : {out}")
    brief_desc = str(brief_path) if brief_path is not None else "（无）"
    if brief_obj is not None:
        brief_desc += f"（{len(brief_item_ids(brief_obj))} 条待回应条目）"
    typer.echo(f"brief   : {brief_desc}")
    data_dir = spec.get("data_dir") or ""
    typer.echo(f"data    : data_dir={data_dir or '（无）'}，data_files={len(spec.get('data_files', []))} 个")
    if problems_found:
        for msg in problems_found:
            typer.echo(f"  [FAIL] {msg}", err=True)
        typer.echo(f"预检未通过（{len(problems_found)} 项），禁止启动。", err=True)
        raise typer.Exit(1)

    for lib in payload.get("ok_libs") or []:
        typer.echo(f"  [OK] lib {lib} 可用")
    for warn in payload.get("warns") or []:
        typer.echo(f"  [WARN] {warn}")

    typer.echo("  [OK] 全部通过，可启动 run（烧 token 前请确认预算）。")
    typer.echo(f"preflight: {out / 'preflight.json'}")


@app.command()
def run(
    problem: Path = typer.Option(..., exists=True, readable=True),
    out: Path = typer.Option(Path("runs/latest")),
    thread: str = typer.Option("default"),
    brief: Path | None = typer.Option(None, "--brief", exists=True, readable=True,
                                      help="人工建模预备 brief.json（可选）"),
    no_interrupt: bool = typer.Option(False, "--no-interrupt", help="跳过 HITL，直接跑到底"),
    dry_run: bool = typer.Option(False, "--dry-run", help="只做启动前预检（spec/brief/feasibility/附件/out 冲突），不烧 token"),
    template: str = typer.Option("default", help="LaTeX 模板：default | gmcm（国赛 gmcmthesis）"),
    school: str = typer.Option("", help="学校名称（gmcm 模板用）"),
    team_id: str = typer.Option("", help="参赛报名号（gmcm 模板用）"),
    members: str = typer.Option("", help="队员名字，逗号分隔：'张三,李四,王五'（gmcm 模板用）"),
    force: bool = typer.Option(False, "--force", help="即使已有 checkpoint 也覆盖（慎用）"),
):
    spec = _read_problem_spec(problem)
    brief_obj = None
    brief_sha256 = None
    if brief is not None:
        brief_obj = _load_brief_or_raise(brief)
        brief_sha256 = hashlib.sha256(brief.read_bytes()).hexdigest()
        _warn_brief_problem_mismatch(brief_obj, spec)
    if template not in {"default", "gmcm"}:
        raise typer.BadParameter("template 只能是 default 或 gmcm", param_hint="--template")

    if dry_run:
        _dry_run_preflight(problem, spec, brief, brief_obj, out, thread, force)
        return

    # 防止以同一 --thread 重复输出到同一目录，掩盖上次 runs
    out.mkdir(parents=True, exist_ok=True)
    interrupt = [] if no_interrupt else ["human_review"]

    initial = {
        "problem": spec.get("title", "") + "\n" + "\n".join(spec.get("questions", [])),
        "background": spec.get("background", ""),
        "questions": spec.get("questions", []),
        "brief": brief_obj,
        "stage_target": "basic",
        "iteration": 0,
        "output_dir": str(out),
        "data_dir": spec.get("data_dir") or None,
        "data_files": [DataFileInfo(**f) for f in spec.get("data_files", [])],
        "latex_template": template,
        "school": school or None,
        "team_id": team_id or None,
        "members": members or None,
        # --no-interrupt 表示显式跳过人审，等价于自动批准；否则拒绝路由
        # 无法区分“自动模式”与“恢复时遗漏决定”。
        "human_decision": HumanDecision(approved=True, notes="--no-interrupt") if no_interrupt else None,
    }
    clear_failed_node()
    tracer = None
    tok = None
    try:
        with RunLock(out):
            _prepare_run_output(out, thread, force)
            if brief_obj is not None:
                _copy_brief_to_out(out, brief)
            _write_run_manifest(out, thread, spec, no_interrupt=no_interrupt, brief_sha256=brief_sha256)
            clear_failure_report(out)
            try:
                from math_agent.progress import emit_run_boundary
                emit_run_boundary(out, attempt=1, mode="run")
            except Exception:
                pass
            try:
                from math_agent.run_pointer import write_active_run
                write_active_run(out, thread=thread, status="running")
            except Exception:
                pass
            tracer = Tracer(thread_id=thread, out_dir=out)
            tok = set_current(tracer)
            with _saver_cm(out) as saver:
                g = build_graph(checkpointer=saver, interrupt_before=interrupt)
                g.invoke(initial, config=_config(thread))
    except RunLockedError as e:
        typer.echo(f"[BUSY] {e}", err=True)
        raise typer.Exit(75)
    except LLMTransportError as e:
        failure = _record_failure(out, e)
        typer.echo(f"\n[FAILED] LLM transport error at node '{failure.node}': {e}", err=True)
        typer.echo(f"  Checkpoint saved (thread={thread}). Router may be temporarily unavailable.", err=True)
        typer.echo(f"  Recover: uv run math-agent recover --out {out} --thread {thread}", err=True)
        raise typer.Exit(1)
    except LLMRateLimitError as e:
        failure = _record_failure(out, e)
        typer.echo(f"\n[FAILED] Rate limit exhausted at node '{failure.node}': {e}", err=True)
        typer.echo(f"  Retry budget used up. Wait and resume:", err=True)
        typer.echo(f"  uv run math-agent recover --out {out} --thread {thread}")
        raise typer.Exit(1)
    except PauseRequested as e:
        typer.echo(
            f"\n[PAUSED] 节点 '{e.node}' 边界捕获暂停请求；checkpoint 已保存。\n"
            f"  使用 `math-agent recover --out {out} --thread {thread}` 续跑。",
            err=True,
        )
        raise typer.Exit(0)
    except LLMError as e:
        failure = _record_failure(out, e)
        typer.echo(f"\n[FAILED] LLM error at node '{failure.node}': {e}", err=True)
        typer.echo(f"  Checkpoint saved (thread={thread}). This error may not be retriable.", err=True)
        raise typer.Exit(1)
    except typer.Exit:
        raise
    except Exception as e:
        failure = _record_failure(out, e)
        typer.echo(f"\n[FAILED] Unexpected error: {type(e).__name__}: {e}", err=True)
        typer.echo(f"  Checkpoint saved (thread={thread}). Debug trace at {out / 'trace.json'}")
        raise typer.Exit(1)
    finally:
        if tracer is not None:
            tracer.flush()
        if tok is not None:
            reset_current(tok)
    clear_failure_report(out)
    pause_control.clear_pause(out)
    _dump_state_summary(out, thread)
    _echo_run_outcome(out, thread)


@app.command()
def pause(
    out: Path = typer.Option(Path("runs/latest")),
):
    """向运行中的 run 写入暂停请求；worker 在当前节点结束后停止。"""
    out = out.resolve()
    if not out.is_dir():
        typer.echo(f"[FAIL] 输出目录不存在：{out}", err=True)
        raise typer.Exit(1)
    pause_control.request_pause(out)
    typer.echo(f"[PAUSE] 已写入暂停请求到 {out / pause_control.PAUSE_MARKER_NAME}")
    typer.echo(f"  worker 将在当前节点边界停止，之后可用 recover 续跑。")


def _echo_run_outcome(out: Path, thread: str) -> None:
    """按 checkpoint 的真实 next 汇报，避免图已 END 时谎报人审暂停。"""
    inspection = inspect_checkpoint(out, thread)
    if inspection.next_node == "human_review":
        typer.echo(
            f"pipeline paused before human_review (thread={thread}); "
            f"trace at {out / 'trace.json'}"
        )
        typer.echo(f"use `math-agent resume --out {out} --thread {thread} --approve` to continue.")
        return
    if inspection.next_node:
        typer.echo(
            f"pipeline left at node '{inspection.next_node}' (thread={thread}); "
            f"trace at {out / 'trace.json'}"
        )
        return
    if inspection.final_status == "rejected":
        typer.echo(f"pipeline rejected at human_review; no finalization was performed for {out}")
        return
    if inspection.final_status in {"completed", "degraded"}:
        typer.echo(f"done. paper at {out / 'paper.md'}; trace at {out / 'trace.json'}")
        return
    if inspection.checkpoint_exists:
        typer.echo(
            f"pipeline stopped before human_review (thread={thread}); "
            f"quality gate or graph ended. trace at {out / 'trace.json'}"
        )
        return
    typer.echo(f"done. paper at {out / 'paper.md'}; trace at {out / 'trace.json'}")


@app.command()
def review(
    out: Path = typer.Option(Path("runs/latest")),
    thread: str = typer.Option("default"),
    no_interrupt: bool = typer.Option(
        False, "--no-interrupt", help="接管后自动批准并直接产出（degraded 状态）"
    ),
):
    """人工接管：把停在论文评审（paper_critic 未过）的 run 推进到 human_review。

    自动评审未达门槛且 writer 修复轮耗尽时，流程原本 stop，论文永远到不了
    人工评估环节。本命令从已保存 checkpoint 把流程重新路由到
    table_assembler → evaluation → human_review，由人工整体评估后
    resume --approve / --no-approve 决定；--no-interrupt 则自动批准并
    直接产出（质量警告会如实写入 completion.json，状态为 degraded）。
    """
    _require_checkpoint(out)
    _require_trace_thread(out, thread)
    clear_failed_node()
    clear_failure_report(out)
    tracer = Tracer(thread_id=thread, out_dir=out, append_existing=True)
    tok = set_current(tracer)
    try:
        with RunLock(out):
            with _saver_cm(out) as saver:
                g = build_graph(
                    checkpointer=saver,
                    interrupt_before=[] if no_interrupt else ["human_review"],
                )
                snapshot = g.get_state(_config(thread))
                if snapshot is None or not snapshot.values:
                    raise ValueError(f"checkpoint has no state for thread={thread}")
                state = MathModelingState.model_validate(snapshot.values)
                empty = [
                    field for field in ("abstract", "model_section", "solution", "conclusion")
                    if not (getattr(state.paper, field, "") or "").strip()
                ]
                if empty:
                    typer.echo(
                        f"[REJECT] 论文关键 section 为空（{', '.join(empty)}），"
                        "不能进入人工评估。",
                        err=True,
                    )
                    raise typer.Exit(1)
                critic = state.latest_critic("paper")
                if critic is None or (
                    critic.approved and critic.score >= MIN_PAPER_CRITIC_SCORE
                ):
                    typer.echo(
                        "[SKIP] 论文评审已通过或无需人工接管；"
                        "若流程中断请用 recover。",
                    )
                    return
                # 把 checkpoint 视为 paper_critic 刚执行完，重新走条件边路由：
                # after_paper_critic 对“内容完整但未达门槛且迭代耗尽”返回
                # advance_review → table_assembler → evaluation → human_review。
                g.update_state(
                    _config(thread),
                    {"writer_iteration": state.writer_iteration},
                    as_node="paper_critic",
                )
                g.invoke(None, config=_config(thread))
    except RunLockedError as e:
        typer.echo(f"[BUSY] {e}", err=True)
        raise typer.Exit(75)
    except LLMError as e:
        failure = _record_failure(out, e)
        typer.echo(f"[FAILED] LLM error at node '{failure.node}': {e}", err=True)
        typer.echo(
            f"  已暂停在 human_review 之前；修复后重试 review 或直接 "
            f"resume --approve/--no-approve 继续。",
            err=True,
        )
        raise typer.Exit(1)
    except typer.Exit:
        raise
    except Exception as e:
        failure = _record_failure(out, e)
        typer.echo(
            f"[FAILED] review error at node '{failure.node}': "
            f"{type(e).__name__}: {e}",
            err=True,
        )
        raise typer.Exit(1)
    finally:
        tracer.flush()
        reset_current(tok)
    clear_failure_report(out)
    _dump_state_summary(out, thread)
    _echo_run_outcome(out, thread)


@app.command()
def resume(

    out: Path = typer.Option(Path("runs/latest")),
    thread: str = typer.Option("default"),
    approve: bool | None = typer.Option(
        None, "--approve/--no-approve",
        help="必须明确批准或拒绝，避免无参数恢复时意外最终定稿",
    ),
    notes: str = typer.Option(""),
):
    if approve is None:
        raise typer.BadParameter(
            "必须显式传入 --approve 或 --no-approve", param_hint="--approve/--no-approve",
        )
    _require_checkpoint(out)
    _require_trace_thread(out, thread)
    clear_failed_node()
    clear_failure_report(out)
    pause_control.clear_pause(out)
    tracer = Tracer(thread_id=thread, out_dir=out, append_existing=True)
    tok = set_current(tracer)
    try:
        with RunLock(out):
            with _saver_cm(out) as saver:
                g = build_graph(checkpointer=saver, interrupt_before=["human_review"])
                snapshot = g.get_state(_config(thread))
                if snapshot is None or not snapshot.values:
                    raise ValueError(f"checkpoint has no state for thread={thread}")
                g.update_state(_config(thread),
                               {"human_decision": HumanDecision(approved=approve, notes=notes)})
                g.invoke(None, config=_config(thread))
    except RunLockedError as e:
        typer.echo(f"[BUSY] {e}", err=True)
        raise typer.Exit(75)
    except PauseRequested as e:
        typer.echo(
            f"[PAUSED] 节点 '{e.node}' 边界捕获暂停请求；checkpoint 已保存。\n"
            f"  使用 `math-agent recover --out {out} --thread {thread}` 续跑。",
            err=True,
        )
        raise typer.Exit(0)
    except LLMError as e:
        failure = _record_failure(out, e)
        typer.echo(f"[FAILED] LLM error at node '{failure.node}': {e}", err=True)
        raise typer.Exit(1)
    except Exception as e:
        failure = _record_failure(out, e)
        typer.echo(f"[FAILED] resume error at node '{failure.node}': {type(e).__name__}: {e}", err=True)
        raise typer.Exit(1)
    finally:
        tracer.flush()
        reset_current(tok)
    clear_failure_report(out)
    pause_control.clear_pause(out)
    _dump_state_summary(out, thread)
    if approve:
        typer.echo(f"done. tex/md written to {out}")
    else:
        typer.echo(f"pipeline rejected at human_review; no finalization was performed for {out}")


@app.command()
def recover(
    out: Path = typer.Option(Path("runs/latest")),
    thread: str = typer.Option("default"),
    no_interrupt: bool = typer.Option(
        False, "--no-interrupt", help="沿用自动批准策略，不在 human_review 暂停"
    ),
):
    """从最近 checkpoint 续跑，不注入 human_decision。

    用于 writer/coder/figure 等节点崩溃后的恢复。与 resume 的区别：
    resume 注入 human_decision 服务 human_review；recover 纯续跑。
    writer 子流程拆成 prep + section 循环后，section 崩溃不丢已完成节。

    附录 A.4 死循环防护：recover 检测同一节点连续失败次数，超过阈值后停止。
    """
    _require_checkpoint(out)
    _require_trace_thread(out, thread)
    try:
        manifest = json.loads((out / "run_manifest.json").read_text(encoding="utf-8"))
        no_interrupt = no_interrupt or bool(manifest.get("no_interrupt", False))
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError):
        pass
    clear_failed_node()
    clear_failure_report(out)
    pause_control.clear_pause(out)
    tracer = Tracer(thread_id=thread, out_dir=out, append_existing=True)
    tok = set_current(tracer)
    # 连续失败计数只防止真正的死循环；间歇性 502 至少允许三次人工 recover。
    fail_marker = out / ".recover_failed_node"
    supervised = os.getenv("MATH_AGENT_SUPERVISED", "") == "1"
    failure_state = {"node": "", "count": 0}
    if fail_marker.exists() and not supervised:
        try:
            loaded = json.loads(fail_marker.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                failure_state = {"node": str(loaded.get("node", "")),
                                 "count": int(loaded.get("count", 0))}
        except (OSError, ValueError, json.JSONDecodeError):
            # 兼容旧版本只写节点名的 marker：视为失败一次，而不是立即阻断。
            failure_state = {"node": fail_marker.read_text(encoding="utf-8").strip(), "count": 1}
    _RECOVER_FAIL_LIMIT = 3

    def _record_recover_failure(node: str) -> None:
        count = failure_state["count"] + 1 if failure_state["node"] == node else 1
        fail_marker.write_text(json.dumps({"node": node, "count": count}, ensure_ascii=False),
                               encoding="utf-8")
    try:
        with RunLock(out), _saver_cm(out) as saver:
            g = build_graph(
                checkpointer=saver,
                interrupt_before=[] if no_interrupt else ["human_review"],
            )
            snapshot = g.get_state(_config(thread))
            if snapshot is None or not snapshot.values:
                raise ValueError(f"checkpoint has no state for thread={thread}")
            # 同一微节点已经连续失败三次才停止自动重跑。
            current_node = ""
            try:
                current_node = snapshot.next[0] if snapshot.next else ""
            except (IndexError, TypeError):
                pass
            if (not supervised and current_node and failure_state["node"] == current_node
                    and failure_state["count"] >= _RECOVER_FAIL_LIMIT):
                typer.echo(
                    f"[BLOCKED] 节点 '{current_node}' 已连续 recover 失败 "
                    f"{failure_state['count']} 次。\n"
                    f"  可能是 prompt 过长或输出过大导致持续 timeout。\n"
                    f"  建议：1) 检查该节点的 prompt/schema  2) 手动调整 .env 中的 timeout\n"
                    f"  3) 确认问题后删除 {fail_marker} 再重试 recover。",
                    err=True,
                )
                raise typer.Exit(1)
            auto_approve_key = "MATH_AGENT_AUTO_APPROVE_HUMAN_REVIEW"
            previous_auto_approve = os.environ.get(auto_approve_key)
            if no_interrupt:
                # 不在任意中间 checkpoint 上调用 update_state。LangGraph 无法从一条
                # 人工恢复分支可靠推断“最后执行节点”，这会把 next_node 错路由到旧节点。
                # 自动批准只在 human_review 节点真正执行时生效，因此不改变恢复点。
                os.environ[auto_approve_key] = "1"
            try:
                g.invoke(None, config=_config(thread))
            finally:
                if previous_auto_approve is None:
                    os.environ.pop(auto_approve_key, None)
                else:
                    os.environ[auto_approve_key] = previous_auto_approve
        # 成功则清除失败标记
        fail_marker.unlink(missing_ok=True)
    except RunLockedError as e:
        typer.echo(f"[BUSY] {e}", err=True)
        raise typer.Exit(75)
    except PauseRequested as e:
        typer.echo(
            f"[PAUSED] 节点 '{e.node}' 边界捕获暂停请求；checkpoint next 已指向下一节点。\n"
            f"  清除标记后可用 `math-agent recover --out {out} --thread {thread}` 续跑。",
            err=True,
        )
        raise typer.Exit(0)
    except LLMError as e:
        failure = _record_failure(out, e)
        failed = failure.node
        if not supervised:
            _record_recover_failure(failed)
        typer.echo(f"[FAILED] LLM error at node '{failed}': {e}", err=True)
        typer.echo(f"  若同一节点反复失败，检查 prompt/timeout 或手动干预。", err=True)
        raise typer.Exit(1)
    except typer.Exit:
        raise
    except Exception as e:
        failure = _record_failure(out, e)
        failed = failure.node
        if not supervised:
            _record_recover_failure(failed)
        typer.echo(f"[FAILED] recover error at node '{failed}': {type(e).__name__}: {e}", err=True)
        raise typer.Exit(1)
    finally:
        tracer.flush()
        reset_current(tok)
    clear_failure_report(out)
    _dump_state_summary(out, thread)
    typer.echo(f"recovered. trace at {out / 'trace.json'}")


def _is_gate_stop_state(state: MathModelingState) -> bool:
    """从 state 推导是否因 coder/一致性门禁耗尽而停机（不依赖 nodes/ 内部）。"""
    reports = state.model_code_reports
    if not reports:
        return False
    last = reports[-1]
    if last.approved and last.score >= MIN_MODEL_CODE_SCORE:
        return False
    over_no_primary = state.code_verify_iteration >= MAX_CODE_NO_PRIMARY_ITERATIONS
    over_low_score = state.code_verify_low_score_iteration >= MAX_CODE_VERIFY_ITERATIONS
    return over_no_primary or over_low_score


def _gate_stop_reason(state: MathModelingState) -> str:
    if state.code_verify_iteration >= MAX_CODE_NO_PRIMARY_ITERATIONS:
        return "code_verify 无主证据轮次耗尽"
    if state.code_verify_low_score_iteration >= MAX_CODE_VERIFY_ITERATIONS:
        return "code_verify 低分修复轮次耗尽"
    return "code_verify 门禁上限"


def _find_restart_checkpoint(g, config: dict, node_name: str):
    """在历史 checkpoint 中找 next 指向 node_name 的最近快照。"""
    try:
        history = list(g.get_state_history(config))
    except Exception:
        return None
    for snap in history:
        try:
            if snap.next and snap.next[0] == node_name:
                return snap
        except Exception:
            continue
    return None


def _checkpoint_id_of(snapshot) -> str | None:
    """从 StateSnapshot 取出可传给 config 的 checkpoint_id。"""
    if snapshot is None:
        return None
    if hasattr(snapshot, "checkpoint_id") and snapshot.checkpoint_id:
        return str(snapshot.checkpoint_id)
    if hasattr(snapshot, "checkpoint") and snapshot.checkpoint:
        chk = snapshot.checkpoint
        if hasattr(chk, "id"):
            return str(chk.id)
        if isinstance(chk, dict):
            return str(chk.get("id"))
    if hasattr(snapshot, "config") and isinstance(snapshot.config, dict):
        cid = snapshot.config.get("configurable", {}).get("checkpoint_id")
        if cid:
            return str(cid)
    return None


def _append_restart_record(out: Path, from_node: str, reason: str, checkpoint_id: str) -> None:
    path = out / "run_manifest.json"
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        manifest = {}
    restarts = manifest.setdefault("restarts", [])
    restarts.append({
        "from_node": from_node,
        "reason": reason,
        "at": datetime.now(timezone.utc).isoformat(),
        "checkpoint_id": str(checkpoint_id),
    })
    tmp = path.with_name(f"{path.name}.tmp-{os.getpid()}")
    try:
        tmp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def _supersede_gate_diagnostics(out: Path) -> None:
    path = out / "gate_diagnostics.json"
    if path.is_file():
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        path.rename(out / f"gate_diagnostics.superseded-{ts}.json")


def _emit_restart_boundary(out: Path) -> None:
    try:
        from math_agent.progress import emit_run_boundary
        emit_run_boundary(out, attempt=1, mode="restart")
    except Exception:
        pass


@app.command()
def restart(
    out: Path = typer.Option(Path("runs/latest")),
    thread: str = typer.Option("default"),
    from_node: str = typer.Option("coder", "--from", help="目前仅支持 coder"),
    reason: str = typer.Option(..., "--reason", help="人工判定重启原因，写入 run_manifest"),
    problem: Path | None = typer.Option(None, "--problem", exists=True, readable=True, help="用于校验输入不变性"),
):
    """门禁停机后，从指定节点前重新执行。

    仅当 checkpoint 处于门禁停机态（next 为空、一致性门禁计数器耗尽）时可用；
    不绕过任何门禁，只是让人工判定守卫/方向无问题后重试一次合法节点。
    """
    _require_checkpoint(out)
    _require_trace_thread(out, thread)
    if from_node != "coder":
        raise typer.BadParameter("目前 --from 只支持 coder", param_hint="--from")
    out = out.resolve()

    # 1. 读取当前 checkpoint 并验证停机态
    with _saver_cm(out) as saver:
        g = build_graph(checkpointer=saver)
        config = _config(thread)
        snapshot = g.get_state(config)
        if snapshot is None or not snapshot.values:
            raise ValueError(f"checkpoint has no state for thread={thread}")
        state = MathModelingState.model_validate(snapshot.values)

        if snapshot.next:
            typer.echo(
                f"[REJECT] checkpoint 未处于停机态（next={snapshot.next}），不能 restart。",
                err=True,
            )
            raise typer.Exit(1)
        inspection = inspect_checkpoint(out, thread)
        if inspection.final_status in {"completed", "degraded", "rejected"}:
            typer.echo(f"[REJECT] run 已终态完成（{inspection.final_status}），不能 restart。", err=True)
            raise typer.Exit(1)
        if not _is_gate_stop_state(state):
            typer.echo(
                "[REJECT] checkpoint 不是 coder/一致性门禁停机态，不能 restart。\n"
                "  只有 code_verify 计数器耗尽导致的停机才允许人工放行重试。",
                err=True,
            )
            raise typer.Exit(1)

    # 2. 输入不变性校验
    manifest_path = out / "run_manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError) as exc:
        typer.echo(f"[REJECT] 无法读取 run_manifest.json：{exc}", err=True)
        raise typer.Exit(1)
    if problem is not None:
        spec = _read_problem_spec(problem)
        if manifest.get("problem_sha256") != _problem_fingerprint(spec):
            typer.echo(
                "[REJECT] --problem 与 run_manifest 不匹配；题目或 brief 已变，只能全新 run。",
                err=True,
            )
            raise typer.Exit(1)
    brief_path = out / "brief.json"
    if brief_path.is_file() and manifest.get("brief_sha256"):
        if hashlib.sha256(brief_path.read_bytes()).hexdigest() != manifest["brief_sha256"]:
            typer.echo(
                "[REJECT] out/brief.json 与 run_manifest 不匹配；输入已变，只能全新 run。",
                err=True,
            )
            raise typer.Exit(1)
    elif not brief_path.is_file() and manifest.get("brief_sha256"):
        typer.echo(
            "[REJECT] 原 run 使用了 brief，但 out/brief.json 缺失；无法验证输入不变性。",
            err=True,
        )
        raise typer.Exit(1)

    # 3.5 自注册监督状态（restart 是前台进程；不写 supervisor.json 会让
    #     watch/status 显示旧 worker 的过期状态——2026-08-21 实证）
    import threading
    from math_agent.supervisor import _now, write_supervisor_state

    _pid = os.getpid()
    _started_at = _now()

    def _supervisor_payload(**kw) -> dict:
        payload = {
            "thread": thread,
            "status": "running",
            "mode": "restart",
            "supervisor_pid": _pid,
            "worker_pid": _pid,
            "started_at": _started_at,
            "heartbeat_at": _now(),
            "command": ["math-agent", "restart", "--from", from_node, "--reason", reason],
        }
        payload.update(kw)
        return payload

    write_supervisor_state(out, _supervisor_payload())
    _heartbeat_stop = threading.Event()

    def _heartbeat() -> None:
        while not _heartbeat_stop.wait(5.0):
            try:
                write_supervisor_state(out, _supervisor_payload())
            except Exception:
                pass

    _heartbeat_thread = threading.Thread(target=_heartbeat, daemon=True)
    _heartbeat_thread.start()

    try:
        # 3. 回退到目标节点前并重置计数器、标注血缘
        with RunLock(out), _saver_cm(out) as saver:
            g = build_graph(checkpointer=saver, interrupt_before=[] if state.human_decision else ["human_review"])
            target = _find_restart_checkpoint(g, config, from_node)
            if target is None:
                typer.echo(
                    f"[FAIL] 未在 checkpoint 历史中找 next={from_node} 的快照，无法 restart。",
                    err=True,
                )
                raise typer.Exit(1)
            checkpoint_id = _checkpoint_id_of(target)
            if checkpoint_id is None:
                typer.echo("[FAIL] 无法读取目标 checkpoint 的 id。", err=True)
                raise typer.Exit(1)
            # fork 配置必须带 checkpoint_ns（LangGraph 要求 thread_id+ns+checkpoint_id 三元组），
            # 直接从目标快照的 config 继承，避免手写缺键。
            restart_config = {"configurable": {**target.config.get("configurable", {}), "checkpoint_id": checkpoint_id}}
            g.update_state(
                restart_config,
                {
                    "code_verify_iteration": 0,
                    "code_verify_low_score_iteration": 0,
                },
                as_node="model_code_consistency",
            )
            _append_restart_record(out, from_node, reason, checkpoint_id)
            _supersede_gate_diagnostics(out)
            clear_failure_report(out)
            pause_control.clear_pause(out)
            _emit_restart_boundary(out)
            try:
                g.invoke(None, config=restart_config)
            except PauseRequested as e:
                write_supervisor_state(
                    out, _supervisor_payload(status="paused", last_node=str(e.node)),
                )
                typer.echo(
                    f"[PAUSED] 节点 '{e.node}' 边界捕获暂停请求；checkpoint 已保存。\n"
                    f"  使用 `math-agent recover --out {out} --thread {thread}` 续跑。",
                    err=True,
                )
                raise typer.Exit(0)
            except (LLMTransportError, LLMRateLimitError, LLMError) as e:
                failure = _record_failure(out, e)
                write_supervisor_state(
                    out, _supervisor_payload(status="blocked", last_node=failure.node, message=str(e)),
                )
                typer.echo(f"\n[FAILED] LLM error at node '{failure.node}': {e}", err=True)
                typer.echo(f"  Checkpoint saved (thread={thread}).", err=True)
                raise typer.Exit(1)
            except typer.Exit:
                raise
            except Exception as e:
                failure = _record_failure(out, e)
                write_supervisor_state(
                    out, _supervisor_payload(status="blocked", last_node=failure.node, message=str(e)),
                )
                typer.echo(f"\n[FAILED] Unexpected error: {type(e).__name__}: {e}", err=True)
                raise typer.Exit(1)
            # 正常完成：按 checkpoint 判定终态（人审暂停 / 门禁停机 / 收口）
            inspection = inspect_checkpoint(out, thread)
            if inspection.next_node == "human_review":
                write_supervisor_state(out, _supervisor_payload(status="paused", last_node="human_review"))
            elif inspection.final_status:
                write_supervisor_state(out, _supervisor_payload(
                    status=inspection.final_status,
                    last_node=getattr(inspection, "last_node", "") or "",
                ))
            else:
                write_supervisor_state(out, _supervisor_payload(
                    status="stopped", last_node=inspection.next_node or "",
                ))
    finally:
        _heartbeat_stop.set()
    _dump_state_summary(out, thread)
    _echo_run_outcome(out, thread)


def _supervisor_exit(result, out: Path, thread: str) -> None:
    if result.status == "completed":
        typer.echo(f"supervised run completed (thread={thread}); paper at {out / 'paper.md'}")
        return
    if result.status == "paused":
        typer.echo(f"pipeline paused before human_review (thread={thread}); trace at {out / 'trace.json'}")
        return
    if result.status == "stopped":
        typer.echo(
            f"pipeline stopped before human_review (thread={thread}); "
            f"quality gate or graph ended. trace at {out / 'trace.json'}"
        )
        return
    if result.status == "rejected":
        typer.echo(f"pipeline rejected at human_review; no finalization was performed for {out}")
        return
    if result.status == "degraded":
        typer.echo(
            f"[DEGRADED] 流程已收口但存在警告；查看 {out / 'completion.json'}",
            err=True,
        )
        raise typer.Exit(2)
    typer.echo(
        f"[BLOCKED] 自动恢复停止于节点 '{result.last_node}'：{result.message}\n"
        f"  状态：{out / 'supervisor.json'}\n"
        f"  失败：{out / 'failure.json'}",
        err=True,
    )
    raise typer.Exit(1)


@app.command()
def supervise(
    problem: Path = typer.Option(..., exists=True, readable=True),
    out: Path = typer.Option(Path("runs/latest")),
    thread: str = typer.Option("default"),
    brief: Path | None = typer.Option(None, "--brief", exists=True, readable=True,
                                      help="人工建模预备 brief.json（可选）"),
    no_interrupt: bool = typer.Option(False, "--no-interrupt", help="跳过 HITL，直接跑到底"),
    template: str = typer.Option("default", help="LaTeX 模板：default | gmcm"),
    school: str = typer.Option(""),
    team_id: str = typer.Option(""),
    members: str = typer.Option(""),
    force: bool = typer.Option(False, "--force", help="清除旧 checkpoint 后启动新任务"),
    same_node_limit: int = typer.Option(3, min=1, help="同一微节点连续失败上限"),
    max_recoveries: int = typer.Option(20, min=1, help="整次任务自动恢复总上限"),
    retry_delay: float = typer.Option(2.0, min=0.0, help="恢复退避基准秒数"),
):
    """以独立 worker 运行完整流程；崩溃或可恢复故障后自动从 checkpoint 续跑。"""
    spec = _read_problem_spec(problem)
    brief_obj = None
    if brief is not None:
        brief_obj = _load_brief_or_raise(brief)
        _warn_brief_problem_mismatch(brief_obj, spec)
    if template not in {"default", "gmcm"}:
        raise typer.BadParameter("template 只能是 default 或 gmcm", param_hint="--template")
    out = out.resolve()
    _validate_existing_run_manifest(out, thread, spec, force)
    args = ["--problem", str(problem.resolve()), "--out", str(out), "--thread", thread,
            "--template", template]
    if no_interrupt:
        args.append("--no-interrupt")
    if school:
        args.extend(["--school", school])
    if team_id:
        args.extend(["--team-id", team_id])
    if members:
        args.extend(["--members", members])
    if force:
        args.append("--force")
    if brief is not None:
        args.extend(["--brief", str(brief.resolve())])
    try:
        result = run_process_supervisor(
            out=out,
            thread=thread,
            run_args=args,
            initial_mode="run" if force else None,
            policy=SupervisorPolicy(
                same_node_limit=same_node_limit,
                max_recoveries=max_recoveries,
                base_delay=retry_delay,
                auto_approve=no_interrupt,
            ),
        )
    except RunLockedError as e:
        typer.echo(f"[BUSY] {e}", err=True)
        raise typer.Exit(75)
    _supervisor_exit(result, out, thread)


@app.command()
def start(
    problem: Path = typer.Option(..., exists=True, readable=True),
    out: Path = typer.Option(Path("runs/latest")),
    thread: str = typer.Option("default"),
    brief: Path | None = typer.Option(None, "--brief", exists=True, readable=True,
                                      help="人工建模预备 brief.json（可选）"),
    no_interrupt: bool = typer.Option(False, "--no-interrupt"),
    template: str = typer.Option("default"),
    force: bool = typer.Option(False, "--force"),
    same_node_limit: int = typer.Option(3, min=1),
    max_recoveries: int = typer.Option(20, min=1),
    retry_delay: float = typer.Option(2.0, min=0.0),
):
    """在后台启动受监管任务，适合 Codex CLI、Claude CLI 和短生命周期终端。"""
    spec = _read_problem_spec(problem)
    brief_obj = None
    if brief is not None:
        brief_obj = _load_brief_or_raise(brief)
        _warn_brief_problem_mismatch(brief_obj, spec)
    if template not in {"default", "gmcm"}:
        raise typer.BadParameter("template 只能是 default 或 gmcm", param_hint="--template")
    out = out.resolve()
    _validate_existing_run_manifest(out, thread, spec, force)
    args = [
        "--problem", str(problem.resolve()), "--out", str(out), "--thread", thread,
        "--template", template, "--same-node-limit", str(same_node_limit),
        "--max-recoveries", str(max_recoveries), "--retry-delay", str(retry_delay),
    ]
    if no_interrupt:
        args.append("--no-interrupt")
    if force:
        args.append("--force")
    if brief is not None:
        args.extend(["--brief", str(brief.resolve())])
    pid = start_detached_supervisor(out=out, supervise_args=args, cwd=Path.cwd())
    try:
        from math_agent.run_pointer import write_active_run
        write_active_run(out, thread=thread, status="starting")
    except Exception:
        pass
    typer.echo(f"Beacon supervisor 已在后台启动，PID={pid}")
    typer.echo(f"观察：uv run math-agent watch")
    typer.echo(f"     （或显式）uv run math-agent watch --out {out} --thread {thread}")
    typer.echo(f"状态：uv run math-agent status --out {out} --thread {thread}")
    typer.echo(f"日志：{out / 'supervisor.log'}")


@app.command()
def watch(
    out: Path | None = typer.Option(
        None,
        "--out",
        help="运行目录；省略则自动指向进行中的任务，否则最近一次运行",
    ),
    thread: str = typer.Option("default"),
    mode: str = typer.Option(
        "auto",
        "--mode",
        help="auto=TTY 面板否则纯文本；log=纯文本；panel=强制面板",
    ),
    tail: int = typer.Option(200, min=1, help="日志尾部行数"),
    refresh: float = typer.Option(1.0, min=0.2, help="刷新间隔秒"),
    follow_exit: bool = typer.Option(
        False,
        "--follow-exit",
        help="在 completed/degraded/rejected/blocked 时自动退出观察（非 TTY 管道场景建议开启）",
    ),
):
    """只读跟随运行进度与日志；退出观察不会终止后台任务。

    默认无需 ``--out``：自动发现进行中的任务，否则跟随最近一次运行。
    """
    if mode not in {"auto", "log", "panel"}:
        raise typer.BadParameter("mode 只能是 auto | log | panel", param_hint="--mode")
    from math_agent.run_pointer import resolve_out_dir
    from math_agent.watch import watch_loop

    resolved, how = resolve_out_dir(out)
    if how != "explicit":
        typer.echo(f"[watch] auto → {resolved}  ({how})", err=True)
    raise typer.Exit(watch_loop(
        resolved,
        thread,
        mode=mode,  # type: ignore[arg-type]
        tail=tail,
        refresh=refresh,
        follow_exit=follow_exit,
        resolve_how=how,
    ))


@app.command()
def status(
    out: Path | None = typer.Option(
        None,
        "--out",
        help="运行目录；省略则自动指向进行中或最近一次运行",
    ),
    thread: str = typer.Option("default"),
):
    """读取 checkpoint、supervisor 和最终提交标记，不修改运行状态。"""
    from math_agent.run_pointer import resolve_out_dir

    out, how = resolve_out_dir(out)
    if how != "explicit":
        typer.echo(f"[status] auto → {out}  ({how})")
    inspection = inspect_checkpoint(out, thread)
    supervisor_state = None
    completion = None
    for path, target in ((out / "supervisor.json", "supervisor"),
                         (out / "completion.json", "completion")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            payload = None
        if target == "supervisor":
            supervisor_state = (
                reconcile_supervisor_state(payload) if isinstance(payload, dict) else payload
            )
        else:
            completion = payload
    verified_completion = load_verified_completion(out)
    if (
        supervisor_state
        and verified_completion is not None
        and supervisor_state.get("status") != verified_completion.status
    ):
        supervisor_state = dict(supervisor_state)
        supervisor_state["status"] = "stale"
        supervisor_state["stale_reason"] = (
            f"superseded_by_verified_completion:{verified_completion.status}"
        )
        supervisor_state["effective_status"] = verified_completion.status
    typer.echo(f"checkpoint: {'yes' if inspection.checkpoint_exists else 'no'}")
    typer.echo(f"next_node: {inspection.next_node or '-'}")
    typer.echo(f"final_status: {inspection.final_status or '-'}")
    if supervisor_state:
        typer.echo(f"supervisor_status: {supervisor_state.get('status', '-')}")
        typer.echo(f"heartbeat_at: {supervisor_state.get('heartbeat_at', '-')}")
        typer.echo(f"worker_pid: {supervisor_state.get('worker_pid', '-')}")
        if supervisor_state.get("stale_reason"):
            typer.echo(f"stale_reason: {supervisor_state['stale_reason']}")
        if supervisor_state.get("effective_status"):
            typer.echo(f"effective_status: {supervisor_state['effective_status']}")
    if completion:
        typer.echo(f"completion: {completion.get('status', '-')}")


@app.command("supervise-resume")
def supervise_resume(
    out: Path = typer.Option(Path("runs/latest")),
    thread: str = typer.Option("default"),
    approve: bool | None = typer.Option(None, "--approve/--no-approve"),
    notes: str = typer.Option(""),
    same_node_limit: int = typer.Option(3, min=1),
    max_recoveries: int = typer.Option(20, min=1),
    retry_delay: float = typer.Option(2.0, min=0.0),
):
    """提交人审决定，并监管 LaTeX/finalizer 直到形成明确终态。"""
    if approve is None:
        raise typer.BadParameter(
            "必须显式传入 --approve 或 --no-approve", param_hint="--approve/--no-approve",
        )
    _require_checkpoint(out)
    _require_trace_thread(out, thread)
    out = out.resolve()
    args = ["--out", str(out), "--thread", thread,
            "--approve" if approve else "--no-approve"]
    if notes:
        args.extend(["--notes", notes])
    try:
        result = run_process_supervisor(
            out=out,
            thread=thread,
            resume_args=args,
            initial_mode="resume",
            policy=SupervisorPolicy(
                same_node_limit=same_node_limit,
                max_recoveries=max_recoveries,
                base_delay=retry_delay,
                auto_approve=bool(approve),
            ),
        )
    except RunLockedError as e:
        typer.echo(f"[BUSY] {e}", err=True)
        raise typer.Exit(75)
    _supervisor_exit(result, out, thread)


@app.command("supervise-recover")
def supervise_recover(
    out: Path = typer.Option(Path("runs/latest")),
    thread: str = typer.Option("default"),
    same_node_limit: int = typer.Option(3, min=1),
    max_recoveries: int = typer.Option(20, min=1),
    retry_delay: float = typer.Option(2.0, min=0.0),
):
    """从最近 checkpoint 恢复，并监管任务直到形成明确终态。"""
    _require_checkpoint(out)
    _require_trace_thread(out, thread)
    out = out.resolve()
    try:
        result = run_process_supervisor(
            out=out,
            thread=thread,
            initial_mode="recover",
            persistent_recover_failures=True,
            persistent_recovery_budget=True,
            policy=SupervisorPolicy(
                same_node_limit=same_node_limit,
                max_recoveries=max_recoveries,
                base_delay=retry_delay,
            ),
        )
    except RunLockedError as e:
        typer.echo(f"[BUSY] {e}", err=True)
        raise typer.Exit(75)
    _supervisor_exit(result, out, thread)


@app.command()
def report(
    out: Path = typer.Option(Path("runs/latest")),
    thread: str = typer.Option("default"),
):
    """打印一次运行的 trace 报告 + per-model / per-node 摘要 + blueprint/一致性摘要。"""
    trace_path = out / "trace.json"
    if not trace_path.exists():
        typer.echo(f"no trace at {trace_path}")
        raise typer.Exit(1)
    try:
        blob = json.loads(trace_path.read_text(encoding="utf-8"))
        if not isinstance(blob, dict) or not isinstance(blob.get("tokens"), dict):
            raise ValueError("trace 顶层或 tokens 结构无效")
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        typer.echo(f"invalid trace at {trace_path}: {exc}", err=True)
        raise typer.Exit(1)

    c = Console()
    t = Table(title=f"Run report ({blob.get('thread_id', thread)})")
    t.add_column("metric"); t.add_column("value")
    t.add_row("LLM calls", str(blob.get("llm_calls", 0)))
    t.add_row("Prompt tokens", str(blob["tokens"].get("prompt", 0)))
    t.add_row("Completion tokens", str(blob["tokens"].get("completion", 0)))
    c.print(t)

    tm = Table(title="Per model")
    tm.add_column("model"); tm.add_column("calls"); tm.add_column("prompt"); tm.add_column("completion")
    per_model = blob.get("per_model", {})
    if not isinstance(per_model, dict):
        per_model = {}
    for m, d in per_model.items():
        if isinstance(d, dict):
            tm.add_row(
                m, str(d.get("calls", 0)), str(d.get("prompt_tokens", 0)),
                str(d.get("completion_tokens", 0)),
            )
    c.print(tm)

    tn = Table(title="Nodes")
    tn.add_column("node"); tn.add_column("duration_ms")
    for n in blob.get("nodes", []):
        if isinstance(n, dict):
            tn.add_row(str(n.get("name", "(unknown)")), str(n.get("duration_ms", 0)))
    c.print(tn)

    # P2 §6.3: blueprint + 一致性摘要（从 checkpoint 读 final state）
    _print_blueprint_summary(c, out, thread)


def _print_blueprint_summary(c: Console, out: Path, thread: str = "default") -> None:
    """从 checkpoint 读取 final state，打印 blueprint/一致性摘要。"""
    data = _read_state_summary_data(out, thread)
    if data is None:
        return

    tq = Table(title="Blueprint & Consistency")
    tq.add_column("metric"); tq.add_column("value")

    # Blueprint critic score
    bp_critic = data["bp_critic"]
    if bp_critic is not None:
        tq.add_row("Blueprint Score", f"{_field(bp_critic, 'score', '?')}/10")
    else:
        tq.add_row("Blueprint Score", "N/A")

    # Model-code consistency score
    mc_reports = data["mc_reports"]
    if mc_reports:
        last = mc_reports[-1]
        tq.add_row("Model-Code Score", f"{_field(last, 'score', '?')}/10")
    else:
        tq.add_row("Model-Code Score", "N/A")

    # Question coverage
    tq.add_row("Question Coverage", f"{data['covered']}/{data['total_sq']}")

    # Unresolved issues
    tq.add_row("Unresolved Issues", str(data["unresolved"]))

    c.print(tq)


@app.command()
def ingest(
    src: Path = typer.Option(..., exists=True, readable=True),
    db: Path = typer.Option(Path("runs/rag.sqlite")),
    embedding_model: str = typer.Option("text-embedding-3-small"),
    dim: int = typer.Option(1536),
):
    """扫描语料目录 → 切块 → 嵌入 → 入 sqlite-vec 库。"""
    from math_agent.rag.ingest import ingest_directory
    rep = ingest_directory(src_dir=src, db_path=db,
                           embedding_model=embedding_model, dim=dim)
    typer.echo(f"files={rep.files_processed} chunks={rep.chunks_added} skipped={len(rep.skipped)}")


@app.command()
def bench(out: Path = typer.Option(Path("runs/bench"))):
    """真跑历年题回归基准（live 模式，需要真 LLM API key）。

    要跑 mock 模式（结构性校验，不消耗 API），用：pytest tests/bench/
    """
    from math_agent.bench.runner import run_bench
    rep = run_bench(out_dir=out)
    for c in rep.cases:
        flag = "PASS" if c.passed else "FAIL"
        typer.echo(f"[{flag}] {c.problem_id} overall={c.overall} failures={c.failures}")


if __name__ == "__main__":
    app()
