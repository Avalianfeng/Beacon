# -*- coding: utf-8 -*-
"""Beacon 文档只读审计 wrapper（2026-08-26 治理阶段 4）。

调用全局 doc-compact 的 audit.py，再按 Beacon 口径过滤：
  1. 排除虚拟环境/依赖缓存噪音（.venv、.uv-cache、node_modules、.git）
  2. archive/ 下孤儿豁免（设计内冻结区，见 docs/文档治理约定.md §一）
  3. 根 CLAUDE.md「非单行 @*.md」豁免（Beacon 范式：CLAUDE.md 为自包含规则集）

用法: python scripts/audit_docs.py
退出码: 0 = 无非豁免缺陷；1 = 存在非豁免缺陷。
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

AUDIT_PY = Path.home() / ".agents" / "skills" / "doc-compact" / "scripts" / "audit.py"
PROJ = Path(__file__).resolve().parent.parent

NOISE = (".venv", ".uv-cache", "node_modules", ".probe_tmp", ".codegraph")
ARCHIVE_ORPHAN = re.compile(r"孤儿:\s*(docs[/\\]archive)", re.IGNORECASE)
ROOT_CLAUDE_CMDLINE = re.compile(r"非单行 @\*\.md:\s*CLAUDE\.md\s*$", re.IGNORECASE)


def is_noise(line: str) -> bool:
    # 子串匹配：虚拟环境/缓存/临时目录路径（如 .venv\Lib\... 或 .uv-cache\archive-v0\...）
    return any(d in line for d in NOISE)


def main() -> int:
    if not AUDIT_PY.exists():
        print(f"[FATAL] 找不到 audit.py: {AUDIT_PY}", file=sys.stderr)
        return 2

    proc = subprocess.run(
        [sys.executable, str(AUDIT_PY), str(PROJ)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    raw = (proc.stdout or "") + (proc.stderr or "")
    kept, exempt_noise, exempt_archive, exempt_claude = [], 0, 0, 0

    for line in raw.splitlines():
        if not line.strip():
            continue
        if is_noise(line):
            exempt_noise += 1
            continue
        if ARCHIVE_ORPHAN.search(line):
            exempt_archive += 1
            continue
        if ROOT_CLAUDE_CMDLINE.search(line):
            exempt_claude += 1
            continue
        kept.append(line)

    print("\n".join(kept))
    print("=" * 60)
    print(
        f"Beacon 口径豁免: 噪音 {exempt_noise} 行 | archive 孤儿 {exempt_archive} 行 | "
        f"根 CLAUDE.md 范式 {exempt_claude} 行"
    )
    # 判缺陷：保留行里是否还有 ❌
    defects = [ln for ln in kept if "❌" in ln]
    print(f"非豁免缺陷: {len(defects)} 项")
    for ln in defects:
        print(" ", ln)
    return 0 if not defects else 1


if __name__ == "__main__":
    sys.exit(main())
