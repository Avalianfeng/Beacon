"""当前/最近运行目录指针：减少用户手填 --out。

约定（产品层默认单任务）：
- 启动 supervise/start/run 时写入 ``runs/.beacon-active.json``；
- ``watch`` / ``status`` 未显式指定 ``--out`` 时：优先活跃任务 → 指针 → 最近一次运行。
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

ACTIVE_FILENAME = ".beacon-active.json"
RUNS_DIRNAME = "runs"


def runs_root(cwd: Path | None = None) -> Path:
    base = Path(cwd) if cwd is not None else Path.cwd()
    return (base / RUNS_DIRNAME).resolve()


def active_pointer_path(cwd: Path | None = None) -> Path:
    return runs_root(cwd) / ACTIVE_FILENAME


def write_active_run(
    out: str | Path,
    *,
    thread: str = "default",
    cwd: Path | None = None,
    status: str = "",
) -> None:
    """best-effort 记录当前/最近运行目录。"""
    try:
        out_path = Path(out).resolve()
        root = runs_root(cwd)
        root.mkdir(parents=True, exist_ok=True)
        payload = {
            "out": str(out_path),
            "thread": thread,
            "status": status,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "pid": os.getpid(),
        }
        path = active_pointer_path(cwd)
        tmp = path.with_name(f"{path.name}.tmp-{os.getpid()}")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)
    except Exception:
        return


def read_active_run(cwd: Path | None = None) -> dict | None:
    path = active_pointer_path(cwd)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    out = payload.get("out")
    if not isinstance(out, str) or not out.strip():
        return None
    return payload


def _supervisor_candidates(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    found: list[Path] = []
    try:
        for path in root.rglob("supervisor.json"):
            # 跳过明显非产物的深层噪音；保留 runs/<name>/supervisor.json
            try:
                path.relative_to(root)
            except ValueError:
                continue
            found.append(path)
    except OSError:
        return []
    return found


def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def find_running_out(cwd: Path | None = None) -> Path | None:
    """扫描 runs/ 下仍标记为 starting/running 且 reconcile 后仍活跃的目录。"""
    from math_agent.supervisor import reconcile_supervisor_state

    root = runs_root(cwd)
    best: tuple[float, Path] | None = None
    for sup in _supervisor_candidates(root):
        try:
            payload = json.loads(sup.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        state = reconcile_supervisor_state(payload)
        if state.get("status") not in {"starting", "running"}:
            continue
        out_dir = sup.parent
        score = _mtime(sup)
        if best is None or score > best[0]:
            best = (score, out_dir)
    return best[1] if best else None


def find_recent_out(cwd: Path | None = None) -> Path | None:
    """最近一次含 supervisor.json / checkpoints.sqlite 的运行目录。"""
    root = runs_root(cwd)
    best: tuple[float, Path] | None = None
    for sup in _supervisor_candidates(root):
        out_dir = sup.parent
        score = max(_mtime(sup), _mtime(out_dir / "checkpoints.sqlite"))
        if best is None or score > best[0]:
            best = (score, out_dir)
    if best:
        return best[1]
    # 退化：指针
    active = read_active_run(cwd)
    if active:
        path = Path(str(active["out"]))
        if path.exists():
            return path
    return None


def resolve_out_dir(
    explicit: str | Path | None,
    *,
    cwd: Path | None = None,
    allow_auto: bool = True,
) -> tuple[Path, str]:
    """解析输出目录。

    返回 ``(path, how)``，how ∈ explicit|active-running|pointer|recent|default。
    ``explicit`` 为 None / '' / 'auto' 时启用自动发现。
    """
    raw = None if explicit is None else str(explicit).strip()
    auto_tokens = {"", "auto", "."}
    if raw is not None and raw.lower() not in auto_tokens:
        # 兼容旧默认：若仍是占位 runs/latest 且目录不存在/无产物，则走自动发现
        path = Path(raw)
        if allow_auto and raw.replace("\\", "/") in {"runs/latest", "runs\\latest"}:
            if not _looks_like_run(path):
                resolved = _auto_resolve(cwd)
                if resolved is not None:
                    return resolved
        return path.resolve(), "explicit"

    if allow_auto:
        resolved = _auto_resolve(cwd)
        if resolved is not None:
            return resolved
    fallback = (Path(cwd) if cwd else Path.cwd()) / "runs" / "latest"
    return fallback.resolve(), "default"


def _looks_like_run(path: Path) -> bool:
    try:
        p = path.resolve()
    except OSError:
        return False
    return any(
        (p / name).exists()
        for name in (
            "supervisor.json", "checkpoints.sqlite", "progress.jsonl",
            "completion.json", "supervisor.log",
        )
    )


def _auto_resolve(cwd: Path | None) -> tuple[Path, str] | None:
    running = find_running_out(cwd)
    if running is not None:
        return running.resolve(), "active-running"

    active = read_active_run(cwd)
    if active:
        path = Path(str(active["out"]))
        if path.exists():
            return path.resolve(), "pointer"

    recent = find_recent_out(cwd)
    if recent is not None:
        return recent.resolve(), "recent"
    return None
