"""运行进度事件流（progress.jsonl）：观察面机器可读契约。

写入一律 best-effort：失败不得影响主流程。不写入 prompt、响应正文或附件内容。
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

PROGRESS_FILENAME = "progress.jsonl"


def progress_path(out: str | Path) -> Path:
    return Path(out) / PROGRESS_FILENAME


def append_supervisor_log(out: str | Path | None, line: str) -> None:
    """把关键节奏行追加到 out/supervisor.log，供 watch 跟随（与 stdout 并行）。"""
    if out is None:
        return
    text = (line or "").rstrip("\n")
    if not text:
        return
    try:
        from datetime import datetime, timedelta, timezone
        stamp = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")
        # 避免重复打时间戳
        if len(text) >= 19 and text[4] == "-" and text[10] == " ":
            payload = text
        else:
            payload = f"{stamp} {text}"
        path = Path(out) / "supervisor.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(payload + "\n")
    except Exception:
        return


def append_progress(out: str | Path | None, event: dict[str, Any]) -> None:
    """追加一行 JSON 事件；任何 I/O/序列化错误均吞掉。"""
    if out is None:
        return
    try:
        path = progress_path(out)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = dict(event)
        payload.setdefault("ts", time.time())
        line = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        with path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception:
        return


def reset_progress(
    out: str | Path,
    *,
    epoch: int = 1,
    attempt: int = 1,
) -> None:
    """与 ``--force`` 清理同生命周期：截断后写入新的 run_boundary。"""
    try:
        path = progress_path(out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
    except Exception:
        return
    append_progress(out, {
        "type": "run_boundary",
        "epoch": int(epoch),
        "attempt": int(attempt),
    })


def emit_run_boundary(
    out: str | Path | None,
    *,
    attempt: int = 1,
    epoch: int | None = None,
    mode: str = "",
) -> None:
    if out is None:
        return
    event: dict[str, Any] = {
        "type": "run_boundary",
        "attempt": int(attempt),
    }
    if epoch is not None:
        event["epoch"] = int(epoch)
    else:
        last = _last_epoch(out)
        event["epoch"] = last if last is not None else 1
    if mode:
        event["mode"] = mode
    append_progress(out, event)


def emit_node_start(out: str | Path | None, node: str, **extra: Any) -> None:
    payload = {"type": "node_start", "node": node, **extra}
    append_progress(out, payload)


def emit_node_end(
    out: str | Path | None, node: str, *, duration_ms: int, **extra: Any
) -> None:
    append_progress(out, {
        "type": "node_end",
        "node": node,
        "duration_ms": int(duration_ms),
        **extra,
    })


def emit_llm_call(
    out: str | Path | None,
    *,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    latency_ms: int,
    **extra: Any,
) -> None:
    append_progress(out, {
        "type": "llm_call",
        "model": model,
        "prompt_tokens": int(prompt_tokens),
        "completion_tokens": int(completion_tokens),
        "latency_ms": int(latency_ms),
        **extra,
    })


def emit_error(
    out: str | Path | None,
    *,
    node: str,
    kind: str,
    message: str = "",
    **extra: Any,
) -> None:
    append_progress(out, {
        "type": "error",
        "node": node,
        "kind": kind,
        "message": (message or "").replace("\r", " ").replace("\n", " ")[:500],
        **extra,
    })


def read_progress_events(out: str | Path) -> list[dict[str, Any]]:
    """读取全部事件；跳过坏行。"""
    path = progress_path(out)
    if not path.is_file():
        return []
    events: list[dict[str, Any]] = []
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            events.append(payload)
    return events


def events_since_last_boundary(
    events: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    items = list(events)
    start = 0
    for i, event in enumerate(items):
        if event.get("type") == "run_boundary":
            start = i
    return items[start:]


@dataclass
class ProgressSummary:
    epoch: int | None = None
    attempt: int | None = None
    current_node: str = ""
    completed_nodes: list[str] = field(default_factory=list)
    llm_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    recent_events: list[dict[str, Any]] = field(default_factory=list)


def summarize_progress(
    events: Iterable[dict[str, Any]],
    *,
    recent: int = 12,
) -> ProgressSummary:
    scoped = events_since_last_boundary(events)
    summary = ProgressSummary()
    open_node = ""
    for event in scoped:
        etype = event.get("type")
        if etype == "run_boundary":
            if event.get("epoch") is not None:
                try:
                    summary.epoch = int(event["epoch"])
                except (TypeError, ValueError):
                    pass
            if event.get("attempt") is not None:
                try:
                    summary.attempt = int(event["attempt"])
                except (TypeError, ValueError):
                    pass
        elif etype == "node_start":
            node = str(event.get("node", "") or "")
            if node:
                open_node = node
        elif etype == "node_end":
            node = str(event.get("node", "") or "")
            if node:
                summary.completed_nodes.append(node)
                if open_node == node:
                    open_node = ""
        elif etype == "llm_call":
            summary.llm_calls += 1
            try:
                summary.prompt_tokens += int(event.get("prompt_tokens", 0) or 0)
                summary.completion_tokens += int(event.get("completion_tokens", 0) or 0)
            except (TypeError, ValueError):
                pass
    summary.current_node = open_node
    summary.recent_events = scoped[-max(0, recent):] if recent else []
    return summary


def _last_epoch(out: str | Path) -> int | None:
    for event in reversed(read_progress_events(out)):
        if event.get("type") != "run_boundary":
            continue
        try:
            return int(event["epoch"])
        except (KeyError, TypeError, ValueError):
            return 1
    return None
