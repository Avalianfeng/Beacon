"""题面导入：文本抽取、乱码检测、视觉回退、Markdown 中间产物。"""
from __future__ import annotations

from math_agent.problem_ingest.garble import GarbleReport, assess_garble
from math_agent.problem_ingest.pdf_text import (
    extract_pdf_text,
    extract_tables_as_markdown,
    normalize_math_text,
    sanitize_text,
)
from math_agent.problem_ingest.pipeline import (
    ParseQuality,
    ProblemParseResult,
    apply_vision_transcription,
    parse_problem_file,
    write_problem_source_md,
)
from math_agent.problem_ingest.markdown_out import write_parsed_markdown

__all__ = [
    "GarbleReport",
    "ParseQuality",
    "ProblemParseResult",
    "apply_vision_transcription",
    "assess_garble",
    "extract_pdf_text",
    "extract_tables_as_markdown",
    "normalize_math_text",
    "parse_problem_file",
    "sanitize_text",
    "write_parsed_markdown",
    "write_problem_source_md",
]
