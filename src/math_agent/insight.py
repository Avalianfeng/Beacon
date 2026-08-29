"""把 critic / 一致性 / 执行失败等机制正文落到 run 目录，供观察面读取。

不写入完整 prompt 或整份生成代码。写入失败不影响主流程。
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

INSIGHT_DIRNAME = "insights"
LATEST_JSON = "latest.json"
LATEST_MD = "latest.md"
_MAX_BODY = 6000
_CST = timezone(timedelta(hours=8))


def insight_dir(out: str | Path) -> Path:
    return Path(out) / INSIGHT_DIRNAME


def record_node_insight(out: str | Path | None, node: str, result: Any) -> None:
    """节点成功返回后 best-effort 落盘；无机制正文则跳过。"""
    if out is None or not node:
        return
    try:
        snapshot = extract_insight(node, result)
        if snapshot is None:
            return
        _write_snapshot(Path(out), node, snapshot)
    except Exception:
        return


def read_latest_meta(out: str | Path) -> dict[str, Any] | None:
    path = insight_dir(out) / LATEST_JSON
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError):
        return None
    return payload if isinstance(payload, dict) else None


def extract_insight(node: str, result: Any) -> dict[str, Any] | None:
    data = _plain(result)
    if not isinstance(data, dict) or not data:
        return None

    sections: list[str] = []
    headline_bits: list[str] = []

    reports = _as_list(data.get("critic_reports"))
    if reports:
        report = _plain(reports[-1]) or {}
        approved = bool(report.get("approved"))
        score = report.get("score")
        headline_bits.append(
            f"{node} · {'通过' if approved else '未通过'}"
            + (f" {score}/10" if score is not None else "")
        )
        sections.append(_format_critic(report))

    mc_reports = _as_list(data.get("model_code_reports"))
    if mc_reports:
        report = _plain(mc_reports[-1]) or {}
        approved = bool(report.get("approved"))
        score = report.get("score")
        headline_bits.append(
            f"{node} · 一致性{'通过' if approved else '未通过'}"
            + (f" {score}/10" if score is not None else "")
        )
        sections.append(_format_consistency(report))

    evaluation = _plain(data.get("evaluation"))
    if isinstance(evaluation, dict) and evaluation:
        overall = evaluation.get("overall")
        headline_bits.append(
            f"{node} · 综评 {overall}" if overall is not None else f"{node} · evaluation"
        )
        sections.append(_format_evaluation(evaluation))

    figure_critic = _plain(data.get("figure_current_critic"))
    if isinstance(figure_critic, dict) and figure_critic:
        score = figure_critic.get("quality_score", figure_critic.get("score"))
        headline_bits.append(
            f"{node} · 图评 {score}/10" if score is not None else f"{node} · 图评"
        )
        sections.append(_format_figure_critic(figure_critic))

    artifacts = _as_list(data.get("coder_work_artifacts"))
    queue = _as_list(data.get("coder_work_queue"))
    if artifacts or (queue and any(_plain(item) and (_plain(item) or {}).get("prev_err") for item in queue)):
        last = _plain(artifacts[-1]) if artifacts else {}
        item = _plain(queue[0]) if queue else {}
        success = bool(last.get("success")) if last else False
        err = str((item or {}).get("prev_err") or last.get("stderr") or "").strip()
        if last or err:
            headline_bits.append(
                f"{node} · {'执行成功' if success else '执行失败/回修'}"
            )
            sections.append(_format_execute(last or {}, item or {}, err))

    errors = data.get("errors")
    if isinstance(errors, list) and errors:
        headline_bits.append(f"{node} · errors={len(errors)}")
        sections.append("## errors\n" + "\n".join(f"- {_clip(str(item), 400)}" for item in errors[:12]))

    if not sections:
        return None
    headline = headline_bits[0] if headline_bits else node
    body = "\n\n".join(part for part in sections if part).strip()
    if not body:
        return None
    return {"headline": headline, "body": _clip(body, _MAX_BODY)}


def _write_snapshot(out: Path, node: str, snapshot: dict[str, Any]) -> None:
    folder = insight_dir(out)
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(_CST).strftime("%Y-%m-%d %H:%M:%S")
    text = f"# {node}\nupdated: {stamp}\nheadline: {snapshot['headline']}\n\n{snapshot['body']}\n"
    safe_node = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in node) or "node"
    node_path = folder / f"{safe_node}.md"
    latest_md = folder / LATEST_MD
    latest_json = folder / LATEST_JSON
    meta = {
        "node": node,
        "headline": snapshot["headline"],
        "path": f"{INSIGHT_DIRNAME}/{safe_node}.md",
        "updated_at": stamp,
        "ts": time.time(),
    }
    tmp_md = node_path.with_name(f"{node_path.name}.tmp-{os.getpid()}")
    tmp_latest = latest_md.with_name(f"{latest_md.name}.tmp-{os.getpid()}")
    tmp_json = latest_json.with_name(f"{latest_json.name}.tmp-{os.getpid()}")
    try:
        tmp_md.write_text(text, encoding="utf-8")
        os.replace(tmp_md, node_path)
        tmp_latest.write_text(text, encoding="utf-8")
        os.replace(tmp_latest, latest_md)
        tmp_json.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp_json, latest_json)
    finally:
        for tmp in (tmp_md, tmp_latest, tmp_json):
            tmp.unlink(missing_ok=True)


def _format_critic(report: dict[str, Any]) -> str:
    lines = [
        f"approved: {bool(report.get('approved'))}",
        f"score: {report.get('score', '?')}/10",
        f"target: {report.get('target', '')}",
        f"stage: {report.get('stage') or '-'}",
        f"critic_type: {report.get('critic_type') or '-'}",
    ]
    issues = _as_list(report.get("issues"))
    if issues:
        lines.append("\n## 问题")
        for issue in issues[:20]:
            payload = _plain(issue) or {}
            problem = payload.get("problem", issue)
            section = payload.get("section", "")
            prefix = f"[{section}] " if section else ""
            lines.append(f"- {prefix}{_clip(str(problem), 500)}")
    suggestions = _as_list(report.get("suggestions"))
    if suggestions:
        lines.append("\n## 建议")
        for item in suggestions[:20]:
            lines.append(f"- {_clip(str(item), 500)}")
    return "\n".join(lines)


def _format_consistency(report: dict[str, Any]) -> str:
    lines = [
        f"approved: {bool(report.get('approved'))}",
        f"score: {report.get('score', '?')}/10",
    ]
    for key, title in (
        ("missing_variables", "缺失变量"),
        ("missing_objectives", "缺失目标"),
        ("missing_constraints", "缺失约束"),
        ("issues", "问题"),
        ("suggestions", "建议"),
    ):
        items = _as_list(report.get(key))
        if items:
            lines.append(f"\n## {title}")
            for item in items[:20]:
                lines.append(f"- {_clip(str(item), 400)}")
    return "\n".join(lines)


def _format_evaluation(report: dict[str, Any]) -> str:
    lines = [f"overall: {report.get('overall', '?')}/10"]
    for key in (
        "assumption_reasonableness", "modeling_creativity",
        "result_correctness", "writing_clarity", "extra_depth",
    ):
        if key in report:
            lines.append(f"{key}: {report.get(key)}")
    issues = _as_list(report.get("issues"))
    if issues:
        lines.append("\n## 问题")
        for item in issues[:20]:
            lines.append(f"- {_clip(str(item), 400)}")
    suggestions = _as_list(report.get("suggestions"))
    if suggestions:
        lines.append("\n## 建议")
        for item in suggestions[:20]:
            lines.append(f"- {_clip(str(item), 400)}")
    return "\n".join(lines)


def _format_figure_critic(report: dict[str, Any]) -> str:
    lines = [
        f"quality_score: {report.get('quality_score', report.get('score', '?'))}",
        f"purpose: {_clip(str(report.get('purpose', '')), 200)}",
    ]
    issues = _as_list(report.get("quality_issues") or report.get("issues"))
    if issues:
        lines.append("\n## 问题")
        for item in issues[:20]:
            lines.append(f"- {_clip(str(item), 400)}")
    return "\n".join(lines)


def _format_execute(artifact: dict[str, Any], item: dict[str, Any], err: str) -> str:
    lines = [
        f"success: {bool(artifact.get('success'))}",
        f"purpose: {_clip(str(artifact.get('purpose') or item.get('kind') or ''), 200)}",
        f"evidence_role: {artifact.get('evidence_role', '-')}",
        f"attempt: {item.get('attempt', '-')}",
        f"kind: {item.get('kind') or artifact.get('category') or '-'}",
    ]
    if err:
        lines.append("\n## stderr / 校验")
        lines.append("```")
        lines.append(_clip(err, 3500))
        lines.append("```")
    stdout = str(artifact.get("stdout") or "").strip()
    if stdout:
        lines.append("\n## stdout 尾部")
        lines.append("```")
        lines.append(_clip(stdout[-1500:], 1500))
        lines.append("```")
    return "\n".join(lines)


def _plain(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, dict):
        return value
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        try:
            return dump()
        except Exception:
            return None
    if hasattr(value, "__dict__") and not isinstance(value, type):
        return {k: v for k, v in vars(value).items() if not k.startswith("_")}
    return None


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _clip(text: str, limit: int) -> str:
    text = text.replace("\x00", "")
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


STEPS_DIRNAME = "steps"
_MAX_JSON_CHARS = 120_000
_MAX_LLM_CONTENT = 80_000


def steps_dir(out: str | Path) -> Path:
    return Path(out) / STEPS_DIRNAME


def record_node_result(out: str | Path | None, node: str, result: Any, **meta: Any) -> None:
    """按节点顺序落盘本次返回值；重跑用时间戳分子目录。"""
    if out is None or not node:
        return
    try:
        payload = _jsonable(result)
        if payload in (None, {}, []):
            payload = {"_empty": True}
        headline = node
        snap = extract_insight(node, result)
        if snap:
            headline = str(snap.get("headline") or node)
        record_step(
            Path(out),
            kind="node",
            node=node,
            headline=headline,
            payload=payload,
            extra=meta,
        )
    except Exception:
        return


def record_llm_result(
    out: str | Path | None,
    *,
    node: str,
    model: str,
    content: str,
    parsed: Any = None,
    schema: str = "",
    prompt_chars: int = 0,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    status: str = "ok",
    reasoning_chars: int = 0,
    thinking_off: str = "",
) -> None:
    """记录一次 LLM 生成正文（不含完整 prompt）。"""
    if out is None:
        return
    try:
        body: dict[str, Any] = {
            "status": status,
            "schema": schema,
            "prompt_chars": int(prompt_chars),
            "content": _clip(str(content or ""), _MAX_LLM_CONTENT),
            "reasoning_chars": int(reasoning_chars or 0),
            "thinking_off": str(thinking_off or ""),
        }
        dumped = _jsonable(parsed)
        if dumped is not None:
            body["parsed"] = dumped
        record_step(
            Path(out),
            kind="llm",
            node=node or "llm",
            headline=f"{node or 'llm'} · {status} · {model}",
            payload=body,
            extra={
                "model": model,
                "prompt_tokens": int(prompt_tokens or 0),
                "completion_tokens": int(completion_tokens or 0),
                "reasoning_chars": int(reasoning_chars or 0),
                "thinking_off": str(thinking_off or ""),
            },
        )
    except Exception:
        return


def record_step(
    out: Path,
    *,
    kind: str,
    node: str,
    headline: str,
    payload: Any,
    extra: dict[str, Any] | None = None,
) -> Path | None:
    folder = steps_dir(out)
    folder.mkdir(parents=True, exist_ok=True)
    seq = _next_seq(folder)
    stamp = datetime.now(_CST).strftime("%Y%m%d-%H%M%S")
    safe_node = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in node) or "node"
    name = f"{seq:04d}_{safe_node}_{stamp}"
    dest = folder / name
    dest.mkdir(parents=True, exist_ok=True)
    meta = {
        "seq": seq,
        "kind": kind,
        "node": node,
        "headline": headline,
        "dir": f"{STEPS_DIRNAME}/{name}",
        "updated_at": datetime.now(_CST).strftime("%Y-%m-%d %H:%M:%S"),
        **(extra or {}),
    }
    _atomic_write(dest / "meta.json", json.dumps(meta, ensure_ascii=False, indent=2, default=str))
    text = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    if len(text) > _MAX_JSON_CHARS:
        text = text[: _MAX_JSON_CHARS - 1] + "…"
    _atomic_write(dest / "output.json", text)
    index_line = json.dumps(
        {k: meta[k] for k in ("seq", "kind", "node", "headline", "dir", "updated_at") if k in meta},
        ensure_ascii=False,
    )
    with (folder / "index.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(index_line + "\n")
    return dest


def read_recent_steps(out: str | Path, limit: int = 8) -> list[dict[str, Any]]:
    path = steps_dir(out) / "index.jsonl"
    if not path.is_file():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        return []
    rows: list[dict[str, Any]] = []
    for line in lines[-max(1, limit):]:
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            rows.append(item)
    return rows


def _next_seq(folder: Path) -> int:
    path = folder / "_seq"
    try:
        current = int(path.read_text(encoding="utf-8").strip() or "0")
    except (OSError, UnicodeError, ValueError):
        current = 0
    nxt = current + 1
    _atomic_write(path, str(nxt))
    return nxt


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_name(f"{path.name}.tmp-{os.getpid()}")
    try:
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return _clip(value, _MAX_LLM_CONTENT)
    dumped = _plain(value)
    if dumped is not None and dumped is not value:
        return _jsonable(dumped)
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return _clip(repr(value), 2000)
