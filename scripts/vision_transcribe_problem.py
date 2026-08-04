#!/usr/bin/env python
"""对已上传的题面 PDF 执行视觉转写。

用法：python scripts/vision_transcribe_problem.py <pdf_path>
- stderr：PROGRESS {...} 进度行
- stdout：最终 JSON（与 extract_file_meta 题面字段兼容）
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> None:
    if len(sys.argv) < 2:
        print(json.dumps({"error": "usage: vision_transcribe_problem.py <pdf_path>"}))
        sys.exit(1)
    path = Path(sys.argv[1])
    if not path.is_file():
        print(json.dumps({"error": f"file not found: {path}"}))
        sys.exit(1)
    if path.suffix.lower() != ".pdf":
        print(json.dumps({"error": "only PDF is supported for vision transcription"}))
        sys.exit(1)

    from math_agent.problem_ingest import apply_vision_transcription

    try:
        result = apply_vision_transcription(path, write_md=True)
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
        "text": result.text[:5000],
    }, ensure_ascii=False))


if __name__ == "__main__":
    for s in (sys.stdout, sys.stderr):
        if hasattr(s, "reconfigure"):
            s.reconfigure(encoding="utf-8", errors="replace")
    main()
