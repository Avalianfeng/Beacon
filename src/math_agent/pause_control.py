"""运行级暂停控制：通过 run 目录内的标记文件实现 pause/resume 协调。

与 supervisor 解耦：本模块只提供文件级标记与异常类型，不直接访问 checkpoint。
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path


PAUSE_MARKER_NAME = ".pause_request"


class PauseRequested(Exception):
    """节点边界捕获的暂停信号。

    抛出时当前节点尚未执行，LangGraph 上一条 checkpoint 的 next 仍指向该节点，
    因此清除标记后 recover 会从该节点继续，不会重复/跳过。
    """

    def __init__(self, node: str | None = None):
        self.node = node or "(unknown)"
        super().__init__(f"pause requested at node boundary '{self.node}'")


def _marker_path(out: str | Path) -> Path:
    return Path(out) / PAUSE_MARKER_NAME


def pause_marker_path(out: str | Path) -> Path:
    """返回暂停标记文件路径（供观察面使用）。"""
    return _marker_path(out)


def request_pause(out: str | Path) -> None:
    """写入暂停请求标记。幂等：重复调用更新时间戳。"""
    path = _marker_path(out)
    payload = {
        "requested_at": datetime.now(timezone.utc).isoformat(),
    }
    path.write_text(
        __import__("json").dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def clear_pause(out: str | Path) -> None:
    """清除暂停标记（恢复入口必须先调用）。不存在时静默返回。"""
    _marker_path(out).unlink(missing_ok=True)


def pause_requested(out: str | Path) -> bool:
    """run 目录是否存在未处理的暂停请求。"""
    return _marker_path(out).is_file()


def pause_request_time(out: str | Path) -> datetime | None:
    """返回标记中的 requested_at；无标记或解析失败返回 None。"""
    path = _marker_path(out)
    if not path.is_file():
        return None
    try:
        payload = __import__("json").loads(path.read_text(encoding="utf-8"))
        raw = payload.get("requested_at")
        if raw:
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except Exception:
        pass
    return None
