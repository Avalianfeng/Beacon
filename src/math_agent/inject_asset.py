"""D-025：inject 资产检测与确定性 wrapper（无 sha256）。

主求解入口位于 ``data_dir/inject/``；敏感性脚本固定为 ``inject/sensitivity.py``。
T-19 冻结资产命中时完全不读取 inject。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

_ENTRY_NAMES = ("_entry.py", "main.py")
_SENSITIVITY_NAME = "sensitivity.py"


@dataclass(frozen=True)
class InjectAsset:
    """一次检测结果：inject 入口 + data_dir。"""

    entry_path: Path
    data_dir: Path


@dataclass(frozen=True)
class InjectDetectError:
    """多候选无入口等检测失败（失败闭环，不回退 LLM）。"""

    message: str


def detect_inject_asset(
    data_dir: str | Path | None,
) -> InjectAsset | InjectDetectError | None:
    """从 data_dir/inject/ 检测主求解入口。

    Returns:
        InjectAsset — 检测成功；
        InjectDetectError — 多候选无约定入口；
        None — 无 inject 目录或无可用入口。
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

    inject_dir = data_resolved / "inject"
    if not inject_dir.is_dir():
        return None

    for name in _ENTRY_NAMES:
        cand = inject_dir / name
        if cand.is_file():
            return InjectAsset(entry_path=cand.resolve(), data_dir=data_resolved)

    candidates = sorted(
        p for p in inject_dir.glob("*.py")
        if p.is_file() and p.name != _SENSITIVITY_NAME
    )
    if len(candidates) == 1:
        return InjectAsset(entry_path=candidates[0].resolve(), data_dir=data_resolved)
    if len(candidates) > 1:
        names = ", ".join(p.name for p in candidates)
        return InjectDetectError(
            f"inject 目录存在多个 Python 文件且无 _entry.py/main.py：{names}"
        )
    return None


def build_inject_wrapper(
    asset: InjectAsset,
    *,
    data_filenames: list[str] | None = None,
) -> str:
    """生成确定性 wrapper：exec inject 入口 + 调 main(data_dir, out_dir)；D-025，无哈希。"""
    data_dir_posix = asset.data_dir.as_posix()
    names = [n for n in (data_filenames or []) if n]
    data_files_literal = repr(names)
    named_hints = (
        "\n".join(f"# attachment: {n}" for n in names) if names else "# attachment: (none)"
    )
    entry_posix = asset.entry_path.as_posix()
    return f'''# D-025 inject wrapper — zero LLM, no hash
import matplotlib
matplotlib.use("Agg")
from pathlib import Path

DATA_FILES = {data_files_literal}
{named_hints}
data_dir = Path({data_dir_posix!r})
out_dir = Path.cwd()
_entry = Path({entry_posix!r})
_ns = {{"__name__": "inject_entry", "__file__": str(_entry)}}
exec(compile(_entry.read_text(encoding="utf-8"), str(_entry), "exec"), _ns)
_main = _ns.get("main")
if _main is None:
    raise RuntimeError("inject 入口缺少 main(data_dir, out_dir)")
_main(str(data_dir), str(out_dir))
'''


def read_inject_sensitivity(data_dir: str | Path | None) -> str | None:
    """读取 ``inject/sensitivity.py`` 全文；缺文件或空内容返回 None。"""
    if not data_dir:
        return None
    try:
        path = Path(data_dir).resolve() / "inject" / _SENSITIVITY_NAME
    except OSError:
        return None
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    return text if text.strip() else None
