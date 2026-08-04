"""题面 Markdown 中间产物落盘。"""
from __future__ import annotations

from pathlib import Path
from typing import Any


def _yaml_escape(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{text}"'


def _format_warnings(warnings: list[str]) -> str:
    if not warnings:
        return "[]"
    items = ", ".join(_yaml_escape(w) for w in warnings)
    return f"[{items}]"


def build_parsed_markdown(
    body: str,
    *,
    source: str,
    method: str,
    garble_score: float,
    pages: int,
    warnings: list[str] | None = None,
) -> str:
    """生成带 YAML front matter 的题面 Markdown。"""
    warnings = warnings or []
    fm = "\n".join([
        "---",
        f"source: {_yaml_escape(source)}",
        f"method: {_yaml_escape(method)}",
        f"garble_score: {garble_score}",
        f"pages: {pages}",
        f"warnings: {_format_warnings(warnings)}",
        "---",
        "",
    ])
    return fm + (body or "").rstrip() + "\n"


def write_parsed_markdown(
    path: Path | str,
    body: str,
    *,
    source: str,
    method: str,
    garble_score: float = 0.0,
    pages: int = 0,
    warnings: list[str] | None = None,
) -> Path:
    """写入 problem_parsed.md（或任意目标路径）。"""
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    content = build_parsed_markdown(
        body,
        source=source,
        method=method,
        garble_score=garble_score,
        pages=pages,
        warnings=warnings,
    )
    out.write_text(content, encoding="utf-8")
    return out
