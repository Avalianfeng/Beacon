"""离线 ingest：扫描语料目录 → 切块 → 嵌入 → 入库。

支持后缀：.md, .txt, .pdf
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from math_agent.problem_ingest.pdf_text import (
    extract_pdf_text as _extract_pdf_text_impl,
    normalize_math_text,
    sanitize_text,
)
from math_agent.rag.chunking import chunk_text
from math_agent.rag.embeddings import embed_texts
from math_agent.rag.store import VectorStore


SUPPORTED_SUFFIXES = {".md", ".txt", ".pdf"}


@dataclass
class IngestReport:
    files_processed: int
    chunks_added: int
    skipped: list[str]


# 测试与旧导入兼容
_sanitize_text = sanitize_text
_normalize_math_text = normalize_math_text


def _extract_pdf_text(path: Path) -> str:
    text, _pages = _extract_pdf_text_impl(path, include_tables=False)
    return text


def _read_file(path: Path) -> str:
    if path.suffix.lower() == ".pdf":
        return _extract_pdf_text(path)
    return sanitize_text(path.read_text(encoding="utf-8", errors="ignore"))


# 路径含 papers/论文 → paper（写作风格）；其余 → model_lib（建模参考）。
_PAPER_DIR_HINTS = {"papers", "论文"}


def _derive_source_type(path: Path) -> str:
    parts = {p.lower() for p in path.parts}
    return "paper" if (parts & _PAPER_DIR_HINTS) else "model_lib"


def ingest_directory(
    *,
    src_dir: str | Path,
    db_path: str | Path,
    embedding_model: str,
    dim: int,
    max_chars: int = 1200,
    overlap: int = 200,
) -> IngestReport:
    src_dir = Path(src_dir)
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    store = VectorStore.open(db_path, dim=dim)
    files_processed = 0
    chunks_added = 0
    skipped: list[str] = []
    try:
        for p in sorted(src_dir.rglob("*")):
            if not p.is_file() or p.suffix.lower() not in SUPPORTED_SUFFIXES:
                continue
            try:
                text = _read_file(p)
            except Exception as e:
                skipped.append(f"{p}: {e}")
                continue
            chunks = chunk_text(text, max_chars=max_chars, overlap=overlap,
                                source=str(p), source_type=_derive_source_type(p))
            if not chunks:
                continue
            new_chunks = store.missing_chunks(chunks)
            if new_chunks:
                embeddings = embed_texts([c.text for c in new_chunks], model=embedding_model)
                added = store.add(chunks=new_chunks, embeddings=embeddings)
            else:
                added = 0
            files_processed += 1
            chunks_added += added
    finally:
        store.close()
    return IngestReport(files_processed=files_processed,
                        chunks_added=chunks_added, skipped=skipped)
