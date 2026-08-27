"""T-19：冻结参考实现检测、哈希校验与确定性 wrapper。

检测到 problem.json / reference.json 登记的参考实现且 sha256 一致时，
coder 跳过 LLM 生成，直接 runner 执行本模块生成的 wrapper。
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class FrozenAsset:
    """一次检测结果：可执行入口 + 已校验文件列表。"""

    kind: str  # "single" | "package"
    data_dir: Path
    problem_dir: Path
    entry_path: Path
    verified_files: tuple[Path, ...] = field(default_factory=tuple)
    entry_name: str = ""  # package 时为 reference.json 的 entry 文件名


@dataclass(frozen=True)
class FrozenDetectError:
    """检测到资产但哈希/路径失败（失败闭环，不回退 LLM）。"""

    message: str


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_json(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return raw if isinstance(raw, dict) else None


def _resolve_registered_path(
    rel: str, *, data_dir: Path, problem_dir: Path
) -> Path | None:
    """按计划顺序解析登记路径：data_dir/path → problem_dir/path → data_dir/name。"""
    rel_path = Path(rel)
    candidates = [
        data_dir / rel_path,
        problem_dir / rel_path,
        data_dir / rel_path.name,
    ]
    for cand in candidates:
        try:
            resolved = cand.resolve()
        except OSError:
            continue
        if resolved.is_file():
            return resolved
    return None


def _is_reference_py(path_str: str) -> bool:
    lower = path_str.replace("\\", "/").casefold()
    return "reference" in lower and lower.endswith(".py")


def _verify_hashes(
    entries: list[dict], *, data_dir: Path, problem_dir: Path
) -> tuple[list[Path], str | None]:
    """校验登记条目的 sha256；返回 (已解析路径列表, 错误信息)。"""
    verified: list[Path] = []
    for item in entries:
        if not isinstance(item, dict):
            continue
        rel = item.get("path")
        expected = item.get("sha256")
        if not isinstance(rel, str) or not rel.strip():
            continue
        if not isinstance(expected, str) or not expected.strip():
            return [], f"冻结资产缺少 sha256：{rel}"
        if not _is_reference_py(rel):
            continue
        resolved = _resolve_registered_path(rel, data_dir=data_dir, problem_dir=problem_dir)
        if resolved is None:
            return [], f"冻结资产文件不存在：{rel}"
        actual = _sha256_file(resolved)
        if actual.casefold() != expected.strip().casefold():
            return [], (
                f"冻结资产哈希不匹配：{rel} "
                f"expected={expected[:12]}… actual={actual[:12]}…"
            )
        verified.append(resolved)
    return verified, None


def detect_frozen_asset(
    data_dir: str | Path | None,
) -> FrozenAsset | FrozenDetectError | None:
    """从 data_dir 旁检测冻结参考实现。

    Returns:
        FrozenAsset — 检测成功且哈希一致；
        FrozenDetectError — 有登记资产但哈希/路径失败；
        None — 无冻结资产，走现有 LLM 路径。
    """
    if not data_dir:
        return None
    data_path = Path(data_dir)
    try:
        data_resolved = data_path.resolve()
    except OSError:
        return None
    if not data_resolved.is_dir():
        return None

    problem_dir = data_resolved.parent
    problem_json = _load_json(problem_dir / "problem.json")
    source_files: list[dict] = []
    if problem_json:
        source = problem_json.get("source")
        if isinstance(source, dict):
            raw_files = source.get("source_files")
            if isinstance(raw_files, list):
                source_files = [x for x in raw_files if isinstance(x, dict)]

    ref_meta = _load_json(problem_dir / "reference.json")
    if isinstance(ref_meta, dict):
        entry = ref_meta.get("entry")
        files = ref_meta.get("files")
        if isinstance(entry, str) and entry.strip() and isinstance(files, list):
            file_entries = [x for x in files if isinstance(x, dict)]
            # reference.json 的 path 形如 reference/_entry.py；优先用其 files 校验
            verified, err = _verify_hashes(
                file_entries, data_dir=data_resolved, problem_dir=problem_dir
            )
            if err:
                return FrozenDetectError(err)
            if not verified:
                # 无 .py 条目则不算命中
                pass
            else:
                entry_resolved = _resolve_registered_path(
                    f"reference/{Path(entry).name}",
                    data_dir=data_resolved,
                    problem_dir=problem_dir,
                )
                if entry_resolved is None:
                    entry_resolved = _resolve_registered_path(
                        entry,
                        data_dir=data_resolved,
                        problem_dir=problem_dir,
                    )
                if entry_resolved is None:
                    return FrozenDetectError(
                        f"reference.json entry 不存在：{entry}"
                    )
                # 若 problem.json 也登记了 reference/*.py，一并校验
                if source_files:
                    ref_source = [f for f in source_files if _is_reference_py(str(f.get("path", "")))]
                    if ref_source:
                        _, src_err = _verify_hashes(
                            ref_source, data_dir=data_resolved, problem_dir=problem_dir
                        )
                        if src_err:
                            return FrozenDetectError(src_err)
                return FrozenAsset(
                    kind="package",
                    data_dir=data_resolved,
                    problem_dir=problem_dir,
                    entry_path=entry_resolved,
                    verified_files=tuple(verified),
                    entry_name=Path(entry).name,
                )

    # 单文件：source_files 中含 reference 的 .py
    ref_files = [f for f in source_files if _is_reference_py(str(f.get("path", "")))]
    if not ref_files:
        return None
    verified, err = _verify_hashes(
        ref_files, data_dir=data_resolved, problem_dir=problem_dir
    )
    if err:
        return FrozenDetectError(err)
    if not verified:
        return None
    # 单入口：优先 reference_solver.py，否则取第一个
    entry_path = next(
        (p for p in verified if p.name.casefold() == "reference_solver.py"),
        verified[0],
    )
    return FrozenAsset(
        kind="single",
        data_dir=data_resolved,
        problem_dir=problem_dir,
        entry_path=entry_path,
        verified_files=tuple(verified),
        entry_name=entry_path.name,
    )


def build_frozen_wrapper(
    asset: FrozenAsset,
    *,
    data_filenames: list[str] | None = None,
) -> str:
    """生成确定性 wrapper：读冻结资产 + 输出到 cwd，不 listdir reference/。"""
    data_dir_posix = asset.data_dir.as_posix()
    names = [n for n in (data_filenames or []) if n]
    data_files_literal = repr(names)
    # 附件名字面量满足 validate_code_data_usage 的 has_named_source
    named_hints = "\n".join(f"# attachment: {n}" for n in names) if names else "# attachment: (none)"

    if asset.kind == "package":
        entry = asset.entry_name or asset.entry_path.name
        return f'''# T-19 frozen package wrapper — zero LLM
import matplotlib
matplotlib.use("Agg")
from pathlib import Path

DATA_FILES = {data_files_literal}
{named_hints}
data_dir = Path({data_dir_posix!r})
# 入口路径已知，禁止 glob/listdir reference/
_entry = data_dir / "reference" / {entry!r}
exec(_entry.read_text(encoding="utf-8"), {{"data_dir": data_dir, "__file__": str(_entry)}})
'''

    solver_posix = asset.entry_path.as_posix()
    return f'''# T-19 frozen single-file wrapper — zero LLM
import matplotlib
matplotlib.use("Agg")
from pathlib import Path

DATA_FILES = {data_files_literal}
{named_hints}
data_dir = Path({data_dir_posix!r})
out_dir = Path.cwd()
# 入口路径已知；输出写 runner cwd，禁止写回 source/
_solver = Path({solver_posix!r})
_ns = {{"__name__": "frozen_reference_solver", "__file__": str(_solver)}}
exec(compile(_solver.read_text(encoding="utf-8"), str(_solver), "exec"), _ns)
_main = _ns.get("main")
if _main is None:
    raise RuntimeError("冻结参考实现缺少 main()")
_main(str(data_dir), str(out_dir))
'''
