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


app = typer.Typer(help="Math modeling multi-agent system.")


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
        "run_manifest.json", "progress.jsonl",
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
    help="建模预备（Modeling Brief）：人机协同前置阶段，生成/校验 brief.json（不进主图）"
)
app.add_typer(brief_app, name="brief")


problem_app = typer.Typer(
    help="题目资产：导入/归档/总览（纯机械，智能内容按 brief-playbook 外置给人 + 外部强模型）",
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
        Path("docs/problems/brief.json"), help="brief.json 输出路径"
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
    typer.echo("建议沉淀到 docs/problems/<题号>/brief.json 跨题复用。")


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
        Path("docs/problems/brief.json"), help="brief.json 输出路径"
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


def _dry_run_preflight(
    problem_path: Path, spec: dict, brief_path: Path | None,
    brief_obj, out: Path, thread: str, force: bool,
) -> None:
    """`run --dry-run`：启动前全项预检（不建目录、不烧 token）。

    spec 五字段已由 `_read_problem_spec` 校验；本函数补查：
    feasibility.blockers（能力不可达强制中断）、附件存在性、out 目录冲突。
    """
    from math_agent.brief import brief_item_ids

    problems_found: list[str] = []
    try:
        raw = json.loads(problem_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise typer.BadParameter(f"题目文件不可读：{exc}", param_hint="--problem") from exc

    blockers = raw.get("feasibility", {}).get("blockers") or []
    if not isinstance(blockers, list):
        blockers = []
    if blockers:
        problems_found.append(f"feasibility.blockers 非空（能力不可达）：{blockers}")

    data_dir = spec.get("data_dir") or ""
    for df in spec.get("data_files", []):
        rel = (df.get("path") or "").strip()
        if not rel:
            continue
        fp = Path(rel) if os.path.isabs(rel) else Path(data_dir) / rel
        if not fp.is_file():
            problems_found.append(f"附件缺失：{fp}（data_files 的 {df.get('filename', rel)}）")

    if (out / "checkpoints.sqlite").is_file() and not force:
        problems_found.append(f"输出目录已有 checkpoint（{out}）：换 --out 或 --force")

    typer.echo("=== run --dry-run 预检 ===")
    typer.echo(f"problem : {problem_path}（{(spec.get('title') or '')[:50]}...）")
    typer.echo(f"thread  : {thread}")
    typer.echo(f"out     : {out}")
    brief_desc = str(brief_path) if brief_path is not None else "（无）"
    if brief_obj is not None:
        brief_desc += f"（{len(brief_item_ids(brief_obj))} 条待回应条目）"
    typer.echo(f"brief   : {brief_desc}")
    typer.echo(f"data    : data_dir={data_dir or '（无）'}，data_files={len(spec.get('data_files', []))} 个")
    if problems_found:
        for msg in problems_found:
            typer.echo(f"  [FAIL] {msg}", err=True)
        typer.echo(f"预检未通过（{len(problems_found)} 项），禁止启动。", err=True)
        raise typer.Exit(1)
    typer.echo("  [OK] 全部通过，可启动 run（烧 token 前请确认预算）。")


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
            typer.echo(
                f"[PAUSED] 节点 '{e.node}' 边界捕获暂停请求；checkpoint 已保存。\n"
                f"  使用 `math-agent recover --out {out} --thread {thread}` 续跑。",
                err=True,
            )
            raise typer.Exit(0)
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
