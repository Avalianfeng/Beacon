"""PDF 分页渲染 + 视觉模型转写为 Markdown。"""
from __future__ import annotations

import base64
import json
import re
import sys
import tempfile
from pathlib import Path
from typing import Callable

# 超过该页数时改为每批多页，控制 vision 调用次数
_BATCH_PAGE_THRESHOLD = 12
_PAGES_PER_BATCH_LONG = 3

_VISION_SYSTEM = (
    "你是竞赛题面转写助手。请把页面图像中的中文与数学公式忠实地转写为 Markdown。"
    "行内公式用 $...$，独立公式用 $$...$$。"
    "保留原有章节结构与列表；不要解释、不要补全题面未给出的内容。"
    "只输出 Markdown 正文，不要前言或后记。"
)

ProgressCb = Callable[[dict], None]


def emit_progress(event: dict, progress_cb: ProgressCb | None = None) -> None:
    """向 stderr 输出 PROGRESS 行，并可选回调（供同进程 UI/测试）。"""
    if progress_cb is not None:
        progress_cb(event)
    print("PROGRESS " + json.dumps(event, ensure_ascii=False), file=sys.stderr, flush=True)


def _page_batches(total_pages: int) -> list[tuple[int, int]]:
    """返回 0-based [start, end) 页区间列表。"""
    if total_pages <= 0:
        return []
    size = 1 if total_pages <= _BATCH_PAGE_THRESHOLD else _PAGES_PER_BATCH_LONG
    batches = []
    start = 0
    while start < total_pages:
        end = min(start + size, total_pages)
        batches.append((start, end))
        start = end
    return batches


def render_pdf_pages_to_pngs(pdf_path: Path, out_dir: Path, *, dpi: int = 144) -> list[Path]:
    """将 PDF 每页渲染为 PNG，返回按页序的路径列表。"""
    import fitz

    out_dir.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(str(pdf_path))
    paths: list[Path] = []
    zoom = dpi / 72.0
    matrix = fitz.Matrix(zoom, zoom)
    try:
        for i, page in enumerate(doc):
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            dest = out_dir / f"page-{i + 1:03d}.png"
            pix.save(str(dest))
            paths.append(dest)
    finally:
        doc.close()
    return paths


def _encode_png(path: Path) -> str:
    raw = path.read_bytes()
    return "data:image/png;base64," + base64.b64encode(raw).decode("ascii")


def _strip_fences(text: str) -> str:
    text = text.strip()
    fence = re.match(r"^```(?:markdown|md)?\s*\n([\s\S]*?)\n```\s*$", text, re.I)
    if fence:
        return fence.group(1).strip()
    return text


def transcribe_pdf_with_vision(
    pdf_path: Path,
    *,
    model: str | None = None,
    complete_fn=None,
    progress_cb: ProgressCb | None = None,
) -> str:
    """分页（或分批）视觉转写 PDF，合并为 Markdown。

    ``complete_fn`` 可注入以便测试；默认使用 ``math_agent.llm.complete``。
    进度通过 stderr ``PROGRESS {...}`` 与可选 ``progress_cb`` 输出。
    """
    from math_agent.config import FIGURE_MODEL

    if complete_fn is None:
        from math_agent.llm import complete as complete_fn

    model = model or FIGURE_MODEL
    pdf_path = Path(pdf_path)

    emit_progress(
        {"stage": "render", "message": "正在渲染 PDF 页面为图像…"},
        progress_cb,
    )
    with tempfile.TemporaryDirectory(prefix="beacon-pdf-vision-") as tmp:
        page_pngs = render_pdf_pages_to_pngs(pdf_path, Path(tmp))
        if not page_pngs:
            raise ValueError("PDF has no pages to render")

        total = len(page_pngs)
        batches = _page_batches(total)
        emit_progress(
            {
                "stage": "vision_start",
                "message": f"开始视觉转写，共 {total} 页、{len(batches)} 批",
                "pages": total,
                "batches": len(batches),
                "batch": 0,
            },
            progress_cb,
        )
        sections: list[str] = []
        for batch_idx, (start, end) in enumerate(batches, start=1):
            images = [_encode_png(p) for p in page_pngs[start:end]]
            if start + 1 == end:
                page_label = f"第 {start + 1} 页"
            else:
                page_label = f"第 {start + 1}-{end} 页"
            emit_progress(
                {
                    "stage": "vision_batch",
                    "message": f"正在视觉转写 {page_label}（{batch_idx}/{len(batches)}）…",
                    "pages": total,
                    "batches": len(batches),
                    "batch": batch_idx,
                    "pageStart": start + 1,
                    "pageEnd": end,
                },
                progress_cb,
            )
            prompt = (
                f"请转写下列题面图像（{page_label}，共 {total} 页中的一部分）。"
                "输出纯 Markdown。"
            )
            raw = complete_fn(
                prompt,
                system=_VISION_SYSTEM,
                model=model,
                images=images,
                profile="vision",
                temperature=0.1,
            )
            if not isinstance(raw, str):
                raw = str(raw)
            body = _strip_fences(raw)
            header = f"<!-- pages {start + 1}-{end} -->\n\n"
            sections.append(header + body)

    emit_progress(
        {"stage": "done", "message": "视觉转写完成", "pages": total, "batches": len(batches)},
        progress_cb,
    )
    return "\n\n".join(sections).strip() + "\n"
