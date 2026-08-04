"""控制台观察面：只读跟随运行目录，不向 worker/supervisor 发信号。"""
from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.text import Text

from math_agent.nodes.finalizer import load_verified_completion
from math_agent.progress import (
    events_since_last_boundary,
    read_progress_events,
    summarize_progress,
)
from math_agent.supervisor import (
    FailureRecord,
    inspect_checkpoint,
    load_failure_report,
    reconcile_supervisor_state,
)

WatchMode = Literal["auto", "log", "panel"]
PanelView = Literal["overview", "history", "log"]
_PANEL_VIEWS: tuple[PanelView, ...] = ("overview", "history", "log")

_CST = timezone(timedelta(hours=8))

_TERMINAL_EXIT_STATUSES = frozenset({
    "completed", "degraded", "rejected", "blocked",
})


@dataclass
class LogTailer:
    """按 offset 增量读日志；文件变小时重定位到开头。"""

    path: Path
    offset: int = 0
    _last_size: int = 0

    def read_new_lines(self) -> list[str]:
        if not self.path.is_file():
            self.offset = 0
            self._last_size = 0
            return []
        try:
            size = self.path.stat().st_size
        except OSError:
            return []
        if size < self._last_size or size < self.offset:
            self.offset = 0
        self._last_size = size
        try:
            with self.path.open("r", encoding="utf-8", errors="replace") as fh:
                fh.seek(self.offset)
                chunk = fh.read()
                self.offset = fh.tell()
        except OSError:
            return []
        if not chunk:
            return []
        return chunk.splitlines()


@dataclass
class WatchView:
    out: Path
    thread: str
    waiting: bool = False
    status: str = "unknown"
    effective_status: str = ""
    stale_reason: str = ""
    worker_pid: object = None
    supervisor_pid: object = None
    attempt: object = None
    recoveries: object = None
    max_recoveries: object = None
    same_node_failures: object = None
    next_node: str = ""
    checkpoint_exists: bool = False
    heartbeat_at: str = ""
    mode: str = ""
    message: str = ""
    failure: FailureRecord | None = None
    recover_marker_node: str = ""
    recover_marker_count: int = 0
    locked: bool = False
    next_hint: str = ""
    log_lines: list[str] = field(default_factory=list)
    history_lines: list[str] = field(default_factory=list)
    progress_current_node: str = ""
    completed_nodes: list[str] = field(default_factory=list)
    llm_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    progress_attempt: int | None = None
    progress_epoch: int | None = None


def load_recover_marker(out: str | Path) -> tuple[str, int]:
    """读取 ``.recover_failed_node``；兼容旧版纯节点名。"""
    path = Path(out) / ".recover_failed_node"
    if not path.is_file():
        return "", 0
    try:
        raw = path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        return "", 0
    if not raw:
        return "", 0
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return raw, 1
    if isinstance(payload, dict):
        node = str(payload.get("node", "") or "")
        try:
            count = int(payload.get("count", 0) or 0)
        except (TypeError, ValueError):
            count = 0
        return node, max(0, count)
    return str(payload), 1


def explain_failure(failure: FailureRecord | None) -> str:
    """把 failure.json 转成用户可读根因（纠正误导性 timeout 文案）。"""
    if failure is None:
        return ""
    kind = (failure.kind or "").strip()
    msg = (failure.message or "").replace("\r", " ").replace("\n", " ").strip()
    lower = f"{kind} {msg}".lower()
    if "json_invalid" in lower or "invalid json" in lower or "eof while parsing" in lower:
        return (
            f"{failure.node} · {kind or 'LLMValidationError'}："
            f"模型返回空/非法 JSON，结构化解析失败（通常不是 timeout）"
        )
    if "validation" in kind.lower():
        return (
            f"{failure.node} · {kind}：输出未通过 schema/JSON 校验"
            + (f"；{msg[:160]}" if msg else "")
        )
    if "timeout" in kind.lower() or "timeout" in lower or "budget" in lower:
        return (
            f"{failure.node} · {kind or 'timeout'}：调用超时或总预算耗尽"
            + (f"；{msg[:120]}" if msg else "")
        )
    if "connection" in lower or "transport" in lower or "internalserver" in lower:
        return (
            f"{failure.node} · {kind or 'LLMConnectionError'}：上游连接/网关失败"
            + (f"；{msg[:120]}" if msg else "")
        )
    if kind in {"LLMError", "Exception", "BaseException"} and not msg:
        return (
            f"{failure.node} · {kind}：LLM 调用失败但未留下错误正文"
            f"（常见于上游空响应/网关异常；请查 failure.json 与网关日志）"
        )
    if kind or msg:
        detail = msg[:180] if msg else "（无详细正文）"
        return f"{failure.node} · {kind or 'error'}：{detail}"
    return f"{failure.node} · 未知失败"


def _blocked_hint(view: WatchView) -> str:
    out = view.out
    thread = view.thread
    marker = out / ".recover_failed_node"
    lines: list[str] = ["已阻断。"]

    root = explain_failure(view.failure)
    if root:
        lines.append(f"根因：{root}")
    elif view.message:
        lines.append(f"监督消息：{view.message}")

    fused = view.recover_marker_count >= 3
    if view.recover_marker_count > 0:
        lines.append(
            f"本地熔断：{marker.name} 记录 "
            f"{view.recover_marker_node or '?'} × {view.recover_marker_count}"
            + ("（已达上限，supervise-recover 会立刻空转 BLOCKED）" if fused else "")
        )

    if "same node" in (view.message or "").lower():
        lines.append("说明：同节点连续失败达到上限；未清熔断前不要反复 recover。")

    lines.append("建议按序执行：")
    step = 1
    if fused:
        lines.append(
            f"{step}) 确认网关/模型正常后清除熔断："
            f"Remove-Item -Force '{marker}'"
        )
        step += 1
    lines.append(
        f"{step}) 再恢复："
        f"uv run math-agent supervise-recover --out {out} --thread {thread}"
    )
    step += 1
    fail_blob = f"{getattr(view.failure, 'kind', '')} {getattr(view.failure, 'message', '')}"
    if view.failure and (
        "Validation" in (view.failure.kind or "")
        or "json" in fail_blob.lower()
        or "eof" in fail_blob.lower()
    ):
        lines.append(
            f"{step}) 若仍空 JSON：检查 .env 中 STRONG/DEFAULT 模型与 "
            f"OPENAI_API_BASE，勿只加 timeout。"
        )
    elif view.failure and "timeout" in fail_blob.lower():
        lines.append(
            f"{step}) 若确为超时：再考虑调大 MATH_AGENT_LLM_*_TIMEOUT。"
        )
    lines.append(f"详情文件：{out / 'failure.json'}")
    return "\n".join(lines)


def _load_json(path: Path) -> dict | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _lock_held(out: Path) -> bool:
    for name in (".beacon-worker.lock", ".beacon-supervisor.lock"):
        path = out / name
        if not path.is_file():
            continue
        try:
            if path.stat().st_size > 0:
                return True
        except OSError:
            continue
    return False


def format_ts_local(value: object) -> str:
    """统一显示为东八区到秒：YYYY-MM-DD HH:MM:SS。"""
    if value is None or value == "":
        return "-"
    try:
        if isinstance(value, (int, float)):
            dt = datetime.fromtimestamp(float(value), tz=timezone.utc)
        else:
            raw = str(value).strip().replace("Z", "+00:00")
            dt = datetime.fromisoformat(raw)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(_CST).strftime("%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError, OSError, OverflowError):
        text = str(value)
        if "." in text:
            text = text.split(".", 1)[0]
        return text.replace("T", " ")


def format_heartbeat(value: str) -> str:
    return format_ts_local(value)


def format_history_lines(events: list[dict], *, limit: int = 80) -> list[str]:
    """把 progress 事件格式化为带东八区时间的历程行。"""
    lines: list[str] = []
    scoped = events_since_last_boundary(events)
    for event in scoped[-max(1, limit):]:
        stamp = format_ts_local(event.get("ts"))
        etype = event.get("type")
        if etype == "run_boundary":
            lines.append(
                f"{stamp}  [run] attempt={event.get('attempt', '?')} "
                f"mode={event.get('mode', '-')}"
            )
        elif etype == "node_start":
            stage = event.get("stage")
            stage_bit = f" stage={stage}" if stage else ""
            lines.append(f"{stamp}  → 开始 {event.get('node', '?')}{stage_bit}")
        elif etype == "node_end":
            lines.append(
                f"{stamp}  ✓ 结束 {event.get('node', '?')} "
                f"({event.get('duration_ms', '?')}ms)"
            )
        elif etype == "llm_call":
            lines.append(
                f"{stamp}  · LLM {event.get('model', '?')} "
                f"tokens={event.get('prompt_tokens', 0)}+"
                f"{event.get('completion_tokens', 0)} "
                f"({event.get('latency_ms', '?')}ms)"
            )
        elif etype == "error":
            lines.append(
                f"{stamp}  ✗ {event.get('node', '?')}: {event.get('kind', '')} "
                f"{str(event.get('message', ''))[:80]}"
            )
        elif etype == "stage":
            lines.append(f"{stamp}  ◆ stage={event.get('stage', '?')}")
    return lines


def build_next_hint(view: WatchView) -> str:
    """只读提示：不执行控制动作。"""
    if view.waiting:
        return (
            f"等待任务创建… 可先启动："
            f"uv run math-agent start --out {view.out} --no-interrupt"
        )
    status = (view.effective_status or view.status or "").lower()
    out = view.out
    thread = view.thread
    if status == "paused" or view.next_node == "human_review":
        return (
            f"人审暂停。批准：uv run math-agent supervise-resume "
            f"--out {out} --thread {thread} --approve\n"
            f"         拒绝：uv run math-agent supervise-resume "
            f"--out {out} --thread {thread} --no-approve"
        )
    if status == "blocked":
        return _blocked_hint(view)
    if status == "stale":
        reason = view.stale_reason or "监督状态可能已过期"
        return (
            f"{reason}。若任务已停，可："
            f"uv run math-agent supervise-recover --out {out} --thread {thread}"
        )
    if status in {"completed", "degraded"}:
        return (
            f"已收口（{status}）。查看："
            f"uv run math-agent report --out {out} --thread {thread}；"
            f"产物见 {out / 'completion.json'}"
        )
    if status == "rejected":
        return f"人审拒绝，未最终化。详见 {out / 'completion.json'} 或 checkpoint 状态。"
    if status in {"running", "starting"}:
        return ""
    return f"状态={status or 'unknown'}。可用：uv run math-agent status --out {out}"


def assemble_watch_view(
    out: str | Path,
    thread: str,
    *,
    log_lines: list[str] | None = None,
) -> WatchView:
    out = Path(out)
    view = WatchView(out=out, thread=thread, log_lines=list(log_lines or []))

    has_any = any(
        (out / name).exists()
        for name in (
            "supervisor.json", "supervisor.log", "checkpoints.sqlite",
            "completion.json", "progress.jsonl", "launcher.json",
        )
    )
    if not has_any:
        view.waiting = True
        view.status = "waiting"
        view.next_hint = build_next_hint(view)
        return view

    inspection = inspect_checkpoint(out, thread)
    view.checkpoint_exists = inspection.checkpoint_exists
    view.next_node = inspection.next_node or ""

    supervisor_raw = _load_json(out / "supervisor.json")
    supervisor = (
        reconcile_supervisor_state(supervisor_raw) if supervisor_raw else None
    )
    verified = load_verified_completion(out)
    view.failure = load_failure_report(out)
    view.recover_marker_node, view.recover_marker_count = load_recover_marker(out)
    view.locked = _lock_held(out)

    if supervisor:
        view.status = str(supervisor.get("status", "") or "unknown")
        view.worker_pid = supervisor.get("worker_pid")
        view.supervisor_pid = supervisor.get("supervisor_pid")
        view.attempt = supervisor.get("attempt")
        view.recoveries = supervisor.get("recoveries")
        view.same_node_failures = supervisor.get("same_node_failures")
        view.heartbeat_at = str(supervisor.get("heartbeat_at", "") or "")
        view.mode = str(supervisor.get("mode", "") or "")
        view.message = str(supervisor.get("message", "") or "")
        view.stale_reason = str(supervisor.get("stale_reason", "") or "")
        if supervisor.get("effective_status"):
            view.effective_status = str(supervisor["effective_status"])

    if (
        supervisor
        and verified is not None
        and supervisor.get("status") != verified.status
    ):
        view.status = "stale"
        view.stale_reason = (
            view.stale_reason
            or f"superseded_by_verified_completion:{verified.status}"
        )
        view.effective_status = verified.status

    if verified is not None and not view.effective_status:
        if view.status in {"", "unknown", "starting", "running"} and not view.next_node:
            view.effective_status = verified.status

    if view.next_node == "human_review" and (view.status or "") not in _TERMINAL_EXIT_STATUSES:
        if (view.effective_status or view.status) not in {"rejected", "completed", "degraded"}:
            view.status = "paused"

    if not view.status or view.status == "unknown":
        if inspection.final_status:
            view.status = inspection.final_status
        elif view.next_node:
            view.status = "running"
        elif verified is not None:
            view.status = verified.status

    events = read_progress_events(out)
    progress = summarize_progress(events)
    view.progress_current_node = progress.current_node
    view.completed_nodes = list(progress.completed_nodes)
    view.llm_calls = progress.llm_calls
    view.prompt_tokens = progress.prompt_tokens
    view.completion_tokens = progress.completion_tokens
    view.progress_attempt = progress.attempt
    view.progress_epoch = progress.epoch
    view.history_lines = format_history_lines(events, limit=120)
    if progress.current_node and not view.next_node:
        view.next_node = progress.current_node

    if view.failure is None:
        view.failure = _latest_unresolved_error(events)
    _suppress_stale_failure_alerts(view)

    view.next_hint = build_next_hint(view)
    return view


def _latest_unresolved_error(events: list[dict]) -> FailureRecord | None:
    """仅当本 epoch 内最后一次 error 之后没有成功进展时，才当作当前失败。"""
    scoped = events_since_last_boundary(events)
    last_err_i = -1
    for i, event in enumerate(scoped):
        if event.get("type") == "error":
            last_err_i = i
    if last_err_i < 0:
        return None
    for event in scoped[last_err_i + 1:]:
        if event.get("type") in {"node_start", "node_end", "llm_call", "stage"}:
            return None
    event = scoped[last_err_i]
    return FailureRecord(
        node=str(event.get("node", "(unknown)")),
        kind=str(event.get("kind", "unknown")),
        retriable=True,
        message=str(event.get("message", "") or "").strip()
        or (
            f"(no detail; lasted {event.get('duration_ms')}ms)"
            if event.get("duration_ms") is not None
            else "(no detail)"
        ),
    )


def _suppress_stale_failure_alerts(view: WatchView) -> None:
    """运行中已越过失败节点时，不再把旧 failure/熔断顶在状态区。"""
    status = (view.effective_status or view.status or "").lower()
    if status not in {"running", "starting", "paused"}:
        return
    completed = set(view.completed_nodes)
    if view.failure and view.failure.node in completed:
        view.failure = None
    if view.recover_marker_node and view.recover_marker_node in completed:
        view.recover_marker_node = ""
        view.recover_marker_count = 0
    # 当前节点已离开熔断节点，也不再强调 recover_fuse
    if (
        view.recover_marker_node
        and view.next_node
        and view.recover_marker_node != view.next_node
        and view.recover_marker_node != view.progress_current_node
    ):
        view.recover_marker_node = ""
        view.recover_marker_count = 0


def format_watch_text(
    view: WatchView,
    *,
    include_logs: bool = True,
    panel_view: PanelView = "overview",
) -> str:
    lines = [
        f"Beacon watch  out={view.out}  thread={view.thread}  view={panel_view}",
        (
            f"status: {view.status}"
            + (f"  effective: {view.effective_status}" if view.effective_status else "")
            + (f"  stale: {view.stale_reason}" if view.stale_reason else "")
        ),
        (
            f"worker_pid: {view.worker_pid or '-'}  "
            f"attempt: {view.attempt or view.progress_attempt or '-'}  "
            f"recoveries: {view.recoveries if view.recoveries is not None else '-'}"
        ),
        (
            f"next_node: {view.next_node or view.progress_current_node or '-'}  "
            f"checkpoint: {'yes' if view.checkpoint_exists else 'no'}  "
            f"heartbeat: {format_heartbeat(view.heartbeat_at)}"
        ),
    ]
    if view.completed_nodes:
        lines.append("已完成: " + " → ".join(view.completed_nodes[-12:]))
    if view.llm_calls:
        tokens = (view.prompt_tokens + view.completion_tokens) / 1000.0
        lines.append(f"LLM: calls={view.llm_calls}  tokens≈{tokens:.1f}k")
    if view.failure:
        lines.append(f"failure: {explain_failure(view.failure)}")
    if view.recover_marker_count:
        lines.append(
            f"recover_fuse: {view.recover_marker_node or '?'} × "
            f"{view.recover_marker_count}"
        )
    if view.next_hint:
        lines.append(f"下一步: {view.next_hint}")
    lines.append("f switch view  q / Ctrl+C quit (does not kill task)")
    if include_logs:
        if panel_view == "log":
            lines.append("--- log ---")
            lines.extend(view.log_lines or ["(no supervisor.log yet)"])
        else:
            lines.append("--- history ---")
            hist = view.history_lines
            if panel_view == "overview":
                hist = hist[-12:]
            lines.extend(hist or ["(no events yet)"])
    return "\n".join(lines)


def _status_block(view: WatchView) -> Text:
    header = Text()
    header.append("status: ", style="bold")
    status = view.effective_status or view.status
    style = {
        "running": "green",
        "starting": "green",
        "paused": "yellow",
        "blocked": "red",
        "stale": "yellow",
        "completed": "cyan",
        "degraded": "yellow",
        "rejected": "red",
        "waiting": "dim",
    }.get(status, "white")
    header.append(f"{view.status}", style=style)
    if view.effective_status and view.effective_status != view.status:
        header.append(f"  effective={view.effective_status}", style="cyan")
    if view.stale_reason:
        header.append(f"\nstale: {view.stale_reason}", style="yellow")

    body = Text()
    body.append(
        f"worker_pid: {view.worker_pid or '-'}   "
        f"attempt: {view.attempt or view.progress_attempt or '-'}   "
        f"recoveries: {view.recoveries if view.recoveries is not None else '-'}\n"
    )
    body.append(
        f"next_node: {view.next_node or view.progress_current_node or '-'}   "
        f"checkpoint: {'yes' if view.checkpoint_exists else 'no'}\n"
    )
    body.append(f"heartbeat: {format_heartbeat(view.heartbeat_at)}")
    if view.mode:
        body.append(f"   mode: {view.mode}")
    body.append("\n")
    if view.completed_nodes:
        body.append("已完成: ", style="bold")
        body.append(" → ".join(view.completed_nodes[-12:]))
        body.append("\n")
    if view.llm_calls:
        tokens = (view.prompt_tokens + view.completion_tokens) / 1000.0
        body.append(f"LLM: calls={view.llm_calls}  tokens≈{tokens:.1f}k\n", style="dim")
    if view.failure:
        body.append(f"failure: {explain_failure(view.failure)}\n", style="red")
    if view.recover_marker_count:
        body.append(
            f"recover_fuse: {view.recover_marker_node or '?'} × "
            f"{view.recover_marker_count}\n",
            style="yellow",
        )
    return Text.assemble(header, "\n\n", body)


def render_watch_panel(
    view: WatchView,
    *,
    panel_view: PanelView = "overview",
    resolve_how: str = "explicit",
) -> Panel:
    where = Text()
    where.append("out: ", style="bold")
    where.append(str(view.out))
    if resolve_how and resolve_how != "explicit":
        where.append(f"   [{resolve_how}]", style="dim")
    where.append("\n")

    parts: list = [where, _status_block(view), Text("─" * 40, style="dim")]

    content = Text()
    if panel_view == "log":
        lines = view.log_lines[-200:]
        if not lines:
            content.append("(no supervisor.log yet)\n", style="dim")
        for line in lines:
            content.append(line + "\n", style="dim")
    else:
        hist = view.history_lines
        if panel_view == "overview":
            hist = hist[-12:]
        else:
            hist = hist[-80:]
        if not hist:
            content.append(
                "(no events yet; lines appear on node start/end and after LLM calls)\n",
                style="dim",
            )
        for line in hist:
            content.append(line + "\n")
    parts.append(content)

    if view.next_hint:
        hint = Text("下一步: ", style="bold yellow")
        hint.append(view.next_hint)
        parts.append(Text())
        parts.append(hint)

    parts.append(Text(
        f"\nview: {panel_view}   f cycle(overview/history/log)   "
        "q / Ctrl+C quit (does not kill task)",
        style="dim",
    ))

    title = f"Beacon  (thread={view.thread})"
    return Panel(Group(*parts), title=title, border_style="blue")


def _stdin_key() -> str | None:
    """非阻塞读一个按键；失败返回 None。"""
    try:
        if not sys.stdin or not sys.stdin.isatty():
            return None
        if sys.platform == "win32":
            import msvcrt
            while msvcrt.kbhit():
                ch = msvcrt.getwch()
                if ch:
                    return ch
            return None
        import select
        ready, _, _ = select.select([sys.stdin], [], [], 0)
        if not ready:
            return None
        return sys.stdin.read(1) or None
    except Exception:
        return None


def resolve_mode(mode: WatchMode, *, is_tty: bool) -> Literal["log", "panel"]:
    if mode == "auto":
        return "panel" if is_tty else "log"
    if mode == "panel" and not is_tty:
        return "log"
    return "log" if mode == "log" else "panel"


def cycle_panel_view(current: PanelView) -> PanelView:
    idx = _PANEL_VIEWS.index(current)
    return _PANEL_VIEWS[(idx + 1) % len(_PANEL_VIEWS)]


def watch_loop(
    out: str | Path,
    thread: str = "default",
    *,
    mode: WatchMode = "auto",
    tail: int = 200,
    refresh: float = 1.0,
    follow_exit: bool = False,
    console: Console | None = None,
    resolve_how: str = "explicit",
) -> int:
    """跟随运行目录。返回 0；仅观察进程退出，不杀任务。"""
    out = Path(out).resolve()
    console = console or Console(stderr=False)
    effective = resolve_mode(mode, is_tty=console.is_terminal)
    tailer = LogTailer(out / "supervisor.log")
    buffer: list[str] = []
    refresh = max(0.2, float(refresh))
    tail = max(1, int(tail))
    panel_view: PanelView = "overview"
    how_label = resolve_how

    if tailer.path.is_file():
        try:
            existing = tailer.path.read_text(encoding="utf-8", errors="replace").splitlines()
            buffer = existing[-tail:]
            tailer.offset = tailer.path.stat().st_size
            tailer._last_size = tailer.offset
        except OSError:
            pass

    def snapshot() -> tuple[WatchView, int]:
        nonlocal buffer
        buffer.extend(tailer.read_new_lines())
        dropped = 0
        if len(buffer) > tail * 2:
            dropped = len(buffer) - tail
            buffer = buffer[-tail:]
        return assemble_watch_view(out, thread, log_lines=buffer[-tail:]), dropped

    try:
        if effective == "log":
            printed_logs = 0
            last_header = ""
            while True:
                view, dropped = snapshot()
                if dropped:
                    printed_logs = max(0, printed_logs - dropped)
                header = format_watch_text(
                    view, include_logs=False, panel_view=panel_view,
                )
                if header != last_header:
                    console.print(header)
                    console.print(f"--- {panel_view} ---")
                    last_header = header
                if panel_view == "log":
                    if printed_logs < len(buffer):
                        for line in buffer[printed_logs:]:
                            console.print(line)
                        printed_logs = len(buffer)
                else:
                    hist = view.history_lines
                    show = hist[-12:] if panel_view == "overview" else hist[-40:]
                    for line in show:
                        console.print(line)
                status = (view.effective_status or view.status or "").lower()
                if follow_exit and status in _TERMINAL_EXIT_STATUSES:
                    return 0
                key = _stdin_key()
                if key in {"q", "Q"}:
                    return 0
                if key in {"f", "F"}:
                    panel_view = cycle_panel_view(panel_view)
                    last_header = ""
                time.sleep(refresh)
        else:
            with Live(
                render_watch_panel(
                    snapshot()[0], panel_view=panel_view, resolve_how=how_label,
                ),
                console=console,
                refresh_per_second=max(1, int(1 / refresh)),
                transient=False,
            ) as live:
                while True:
                    view, _dropped = snapshot()
                    live.update(render_watch_panel(
                        view, panel_view=panel_view, resolve_how=how_label,
                    ))
                    status = (view.effective_status or view.status or "").lower()
                    if follow_exit and status in _TERMINAL_EXIT_STATUSES:
                        return 0
                    key = _stdin_key()
                    if key in {"q", "Q"}:
                        return 0
                    if key in {"f", "F"}:
                        panel_view = cycle_panel_view(panel_view)
                    time.sleep(refresh)
    except KeyboardInterrupt:
        return 0
