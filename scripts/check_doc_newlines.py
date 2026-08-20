"""文档行尾健康检查：检测 \\r\\r\\n、\\r\\r\\r\\n、裸 \\r 等历史工具双重转换遗留。

用法:
  python scripts/check_doc_newlines.py [--root docs]

退出码: 0 = 全部干净；1 = 存在行尾问题。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def check_file(path: Path) -> list[str]:
    b = path.read_bytes()
    issues: list[str] = []
    if b"\r\r\n" in b:
        issues.append("CRCRLF")
    if b"\r\r\r\n" in b:
        issues.append("CRCRCRLF")
    cr = b.count(b"\r")
    crlf = b.count(b"\r\n")
    if cr != crlf:
        issues.append(f"bare CR (CR={cr} CRLF={crlf})")
    return issues


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", type=Path, default=ROOT / "docs", help="扫描根目录")
    args = ap.parse_args()
    root: Path = args.root.resolve()
    bad = 0
    for p in sorted(root.rglob("*.md")):
        issues = check_file(p)
        if issues:
            bad += 1
            print(f"[BAD] {p.relative_to(ROOT)}: {', '.join(issues)}")
    if bad:
        print(f"{bad} file(s) with newline issues")
        return 1
    print("ALL DOC NEWLINES CLEAN")
    return 0


if __name__ == "__main__":
    sys.exit(main())
