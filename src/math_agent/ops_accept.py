"""分阶段人审登记 v0：写入 acceptance.json（paper sha256 + approved）。"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


def file_sha256(path: Path) -> str:
    """返回文件字节的 sha256 十六进制摘要。"""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def build_acceptance(
    *,
    problem_id: str,
    paper_path: str,
    paper_sha256: str,
    approved: bool,
    actor: str,
    notes: str = "",
    at: str | None = None,
) -> dict:
    """构造 acceptance.json 载荷。"""
    return {
        "version": 1,
        "problem_id": problem_id,
        "paper_path": paper_path,
        "paper_sha256": paper_sha256,
        "approved": approved,
        "actor": actor,
        "notes": notes,
        "at": at if at is not None else datetime.now(timezone.utc).isoformat(),
    }


def write_acceptance(payload: dict, dest: Path) -> Path:
    """写入 dest（UTF-8、indent=2、末尾换行）；自动创建父目录。"""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return dest


def load_acceptance(path: Path) -> dict:
    """读取 acceptance.json；失败时抛出中文 ValueError。"""
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"无法读取人审登记文件：{path}") from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"人审登记文件 JSON 无效：{path}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"人审登记文件根节点必须是对象：{path}")
    return data


def acceptance_approved(payload: dict) -> bool:
    """仅当 approved 为 JSON true（Python bool True）时视为通过。"""
    return payload.get("approved") is True


def accept(
    *,
    problem_dir: Path,
    paper: Path,
    approved: bool,
    actor: str,
    notes: str = "",
) -> dict:
    """登记人审结论到 problem_dir/acceptance.json 并返回载荷。"""
    paper = Path(paper)
    if not paper.is_file():
        raise ValueError(f"论文文件不存在：{paper}")

    problem_dir = Path(problem_dir)
    digest = file_sha256(paper)
    payload = build_acceptance(
        problem_id=problem_dir.name,
        paper_path=str(paper),
        paper_sha256=digest,
        approved=approved,
        actor=actor,
        notes=notes,
    )
    write_acceptance(payload, problem_dir / "acceptance.json")
    return payload
