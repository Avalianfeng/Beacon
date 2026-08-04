#!/usr/bin/env python
"""对已上传的 PDF（题面或附件）执行视觉转写。

用法：python scripts/vision_transcribe_problem.py <pdf_path> [md_filename]
- stderr：PROGRESS {...} 进度行
- stdout：最终 JSON（与 extract_file_meta 字段兼容）
默认 md_filename=problem_parsed.md；附件请传 attachment_parsed.md。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> None:
    if len(sys.argv) < 2:
        print(json.dumps({
            "error": "usage: vision_transcribe_problem.py <pdf_path> [md_filename]",
        }))
        sys.exit(1)
    path = Path(sys.argv[1])
    md_filename = sys.argv[2] if len(sys.argv) > 2 else "problem_parsed.md"
    if not path.is_file():
        print(json.dumps({"error": f"file not found: {path}"}))
        sys.exit(1)
    if path.suffix.lower() != ".pdf":
        print(json.dumps({"error": "only PDF is supported for vision transcription"}))
        sys.exit(1)

    from math_agent.problem_ingest import apply_vision_transcription

    try:
        result = apply_vision_transcription(path, write_md=True, md_filename=md_filename)
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"error": f"vision transcription failed: {exc}"}))
        sys.exit(1)

    print(json.dumps({
        "file_type": "pdf",
        "filename": path.name,
        "summary": result.to_summary_dict(text_limit=5000),
        "parsed_md_path": (
            str(result.parsed_md_path).replace("\\", "/") if result.parsed_md_path else ""
        ),
        "parse_quality": result.quality.to_dict(),
        # 全文回填文本框；摘要仍用 summary.text_excerpt 截断
        "text": result.text,
    }, ensure_ascii=False))


if __name__ == "__main__":
    for s in (sys.stdout, sys.stderr):
        if hasattr(s, "reconfigure"):
            s.reconfigure(encoding="utf-8", errors="replace")
    main()
