"""常驻 LiteLLM 工作进程入口与 IPC 协议（§4.3）。

worker 通过 multiprocessing spawn 启动，用 Pipe 传普通 dict。
父进程 connection.poll(timeout_s) 实现 deadline；超时 terminate/kill 回收。

IPC 协议（父 -> 子 -> 父）：
  父->子: {"type":"req", "payload": <request dict>}
  子->父: {"type":"ready"}                       # import 完成握手（A.1）
  子->父: {"type":"ok", "payload": <response dict>}
  子->父: {"type":"err", "error": <error dict>}
  父->子: {"type":"stop"}                        # 优雅退出

错误 dict: {"class": str, "msg": str, "status_code": int|None, "retry_after": float|None}
"""
from __future__ import annotations

import logging
import os

# spawn 上下文：子进程重新 import 本模块，这些 setdefault 在子进程也生效。
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")
os.environ.setdefault("LITELLM_LOG", "CRITICAL")
os.environ.setdefault("NO_PROXY", "localhost,127.0.0.1")
os.environ.setdefault("no_proxy", "localhost,127.0.0.1")

import litellm  # noqa: E402  顶层 import：子进程启动即摊销，A.1

litellm.suppress_debug_info = True
litellm.set_verbose = False

_pl = logging.getLogger("LiteLLM")
_pl.propagate = False
_pl.handlers.clear()
_pl.addHandler(logging.NullHandler())


def _worker_main(conn) -> None:
    """worker 主循环。conn 为 Pipe 的一端。"""
    # A.1 握手：import 已在模块顶层完成，发 ready 通知父进程可以开始计时
    if not _safe_send(conn, {"type": "ready"}):
        return

    while True:
        try:
            msg = conn.recv()
        except (EOFError, OSError):
            return  # 父进程关闭连接
        if not isinstance(msg, dict):
            continue
        if msg.get("type") == "stop":
            return
        if msg.get("type") not in {"req", "embed"}:
            continue

        req = msg.get("payload", {})
        try:
            if msg.get("type") == "embed":
                embed_kwargs = dict(req.get("extra") or {})
                embed_kwargs.update(
                    model=req["model"], input=req["input"],
                    timeout=req.get("timeout_s"), num_retries=0,
                )
                resp = litellm.embedding(**embed_kwargs)
                embeddings = [
                    item.get("embedding") if isinstance(item, dict) else getattr(item, "embedding")
                    for item in resp.data
                ]
                if not _safe_send(
                    conn, {"type": "embed_ok", "payload": {"embeddings": embeddings}}
                ):
                    return
            else:
                resp = _litellm_completion(_to_litellm_kwargs(req))
                content, reasoning = _message_text(resp)
                usage = getattr(resp, "usage", None)
                payload = {
                    "content": content,
                    "reasoning_content": reasoning,
                    "prompt_tokens": getattr(usage, "prompt_tokens", 0) or 0,
                    "completion_tokens": getattr(usage, "completion_tokens", 0) or 0,
                    "model": req.get("model", ""),
                    "thinking_off": getattr(resp, "_beacon_thinking_off", "") or "",
                }
                if not _safe_send(conn, {"type": "ok", "payload": payload}):
                    return
        except BaseException as e:  # 连 KeyboardInterrupt 也序列化
            err = _serialize_error(e)
            # 父进程在 deadline/人工终止时会先关闭 Pipe；此时 worker 应安静退出，
            # 不能再因 BrokenPipeError 打出一整段误导性的二次 traceback。
            if not _safe_send(conn, {"type": "err", "error": err}):
                return


def _safe_send(conn, payload: dict) -> bool:
    try:
        conn.send(payload)
        return True
    except (BrokenPipeError, EOFError, OSError):
        return False


# 结构化输出时必须关 thinking。不同网关字段不同；被拒时换写法，不要直接去掉
# 关闭参数（去掉后会回到默认 thinking，reasoning 占满 max_tokens，content 变空）。
_THINKING_OFF_BODIES: tuple[dict, ...] = (
    {"thinking": {"type": "disabled"}},
    {"enable_thinking": False},
    {"chat_template_kwargs": {"enable_thinking": False}},
)


def _to_litellm_kwargs(req: dict) -> dict:
    """把 IPC request dict 转为 litellm.completion 入参。"""
    kw = {
        "model": req["model"],
        "messages": req["messages"],
        "temperature": req.get("temperature", 0.3),
        # §6.3：Beacon 是唯一重试编排者，关闭 LiteLLM client 内部重试
        "num_retries": 0,
    }
    if req.get("response_format"):
        kw["response_format"] = req["response_format"]
    extra = dict(req.get("extra") or {})
    extra_body = dict(extra.pop("extra_body", None) or {})
    if req.get("response_format"):
        extra_body = {
            **extra_body,
            **_THINKING_OFF_BODIES[0],
            "reasoning_effort": "none",
        }
    if extra_body:
        extra["extra_body"] = extra_body
    for k, v in extra.items():
        kw[k] = v
    return kw


def _thinking_kwarg_rejected(exc: BaseException) -> bool:
    msg = str(exc).lower()
    if "thinking" not in msg and "reasoning" not in msg:
        return False
    return (
        "unexpected keyword argument" in msg
        or "unknown parameter" in msg
        or "unknown argument" in msg
        or "invalid parameter" in msg
        or "unrecognized request argument" in msg
    )


def _with_thinking_body(kwargs: dict, body: dict) -> dict:
    patched = dict(kwargs)
    extra_body = dict(patched.get("extra_body") or {})
    extra_body.pop("thinking", None)
    extra_body.pop("enable_thinking", None)
    extra_body.pop("chat_template_kwargs", None)
    extra_body.update(body)
    extra_body["reasoning_effort"] = "none"
    patched["extra_body"] = extra_body
    patched.pop("thinking", None)
    patched.pop("enable_thinking", None)
    patched.pop("reasoning_effort", None)
    return patched


def _drop_thinking(kwargs: dict) -> dict:
    stripped = dict(kwargs)
    stripped.pop("thinking", None)
    stripped.pop("enable_thinking", None)
    stripped.pop("reasoning_effort", None)
    stripped.pop("reasoning_effort", None)
    extra_body = stripped.get("extra_body")
    if isinstance(extra_body, dict):
        body = {
            k: v for k, v in extra_body.items()
            if k not in {"thinking", "enable_thinking", "chat_template_kwargs", "reasoning_effort"}
        }
        if body:
            stripped["extra_body"] = body
        else:
            stripped.pop("extra_body", None)
    return stripped


def _thinking_off_label(kwargs: dict) -> str:
    extra_body = kwargs.get("extra_body") or {}
    parts: list[str] = []
    if extra_body.get("thinking") == {"type": "disabled"}:
        parts.append("extra_body.thinking=disabled")
    if extra_body.get("enable_thinking") is False:
        parts.append("extra_body.enable_thinking=false")
    chat = extra_body.get("chat_template_kwargs") or {}
    if isinstance(chat, dict) and chat.get("enable_thinking") is False:
        parts.append("chat_template_kwargs.enable_thinking=false")
    if extra_body.get("reasoning_effort") == "none" or kwargs.get("reasoning_effort") == "none":
        parts.append("reasoning_effort=none")
    if parts:
        return "+".join(parts)
    if "thinking" not in extra_body and "enable_thinking" not in extra_body:
        return "removed_after_reject"
    return "unknown"


def _message_text(resp) -> tuple[str, str]:
    choice0 = resp.choices[0]
    message = getattr(choice0, "message", None)
    if message is None and isinstance(choice0, dict):
        message = choice0.get("message")
    content = _field(message, "content") or ""
    reasoning = (
        _field(message, "reasoning_content")
        or _field(message, "reasoning")
        or ""
    )
    return str(content or ""), str(reasoning or "")


def _field(obj, name: str):
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(name)
    extra = getattr(obj, "model_extra", None)
    if isinstance(extra, dict) and extra.get(name):
        return extra.get(name)
    return getattr(obj, name, None)


def _litellm_completion(kwargs: dict):
    attempts = [_with_thinking_body(kwargs, body) for body in _THINKING_OFF_BODIES]
    if kwargs.get("response_format"):
        attempts.append(_drop_thinking(kwargs))
    else:
        attempts = [kwargs]
    last_error: BaseException | None = None
    for index, attempt in enumerate(attempts):
        try:
            resp = litellm.completion(**attempt)
            try:
                setattr(resp, "_beacon_thinking_off", _thinking_off_label(attempt))
            except Exception:
                pass
            if index:
                print(
                    f"[llm_worker] thinking 被拒后改用 {_thinking_off_label(attempt)}",
                    flush=True,
                )
            return resp
        except BaseException as e:
            last_error = e
            if kwargs.get("response_format") and _thinking_kwarg_rejected(e):
                print(
                    f"[llm_worker] thinking 参数被拒，尝试下一写法: {e}",
                    flush=True,
                )
                continue
            raise
    assert last_error is not None
    raise last_error


def _serialize_error(e: BaseException) -> dict:
    """把异常序列化为安全 dict（不含 API key、prompt 等）。"""
    status_code = getattr(e, "status_code", None)
    retry_after = None
    # litellm/openai 的 RateLimitError 有 retry_after 属性
    ra = getattr(e, "retry_after", None)
    if ra is not None:
        try:
            retry_after = float(ra)
        except (TypeError, ValueError):
            retry_after = None
    return {
        "class": type(e).__name__,
        "msg": str(e)[:500],
        "status_code": int(status_code) if status_code is not None else None,
        "retry_after": retry_after,
    }


if __name__ == "__main__":
    # spawn 入口：conn 通过 stdio handle 传递
    import multiprocessing as mp
    from multiprocessing.spawn import spawn_main
    spawn_main()
