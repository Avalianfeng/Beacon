"""Dry-run 启动前预检（从 CLI 抽出，供 run --dry-run 与流程阶段复用）。"""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path

OPTIONAL_ML_LIBS = [
    "sklearn",
    "ruptures",
    "statsmodels",
    "xgboost",
    "lightgbm",
    "pywt",
    "shap",
]


def run_preflight(
    *,
    problem_path: Path,
    spec: dict,
    brief_path: Path | None,
    out: Path,
    force: bool,
) -> dict:
    """执行预检；不打印、不抛 typer.Exit。"""
    problems: list[str] = []
    blockers: list = []
    raw: dict | None = None

    try:
        raw = json.loads(problem_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        problems.append(f"题目文件不可读：{exc}")

    if raw is not None:
        blockers = raw.get("feasibility", {}).get("blockers") or []
        if not isinstance(blockers, list):
            blockers = []
        if blockers:
            problems.append(f"feasibility.blockers 非空（能力不可达）：{blockers}")

    data_dir = spec.get("data_dir") or ""
    for df in spec.get("data_files", []):
        rel = (df.get("path") or "").strip()
        if not rel:
            continue
        fp = Path(rel) if os.path.isabs(rel) else Path(data_dir) / rel
        if not fp.is_file():
            problems.append(f"附件缺失：{fp}（data_files 的 {df.get('filename', rel)}）")

    if (out / "checkpoints.sqlite").is_file() and not force:
        problems.append(f"输出目录已有 checkpoint（{out}）：换 --out 或 --force")

    warns: list[str] = []
    ok_libs: list[str] = []
    if not problems:
        for lib in OPTIONAL_ML_LIBS:
            if importlib.util.find_spec(lib) is not None:
                ok_libs.append(lib)
            else:
                warns.append(
                    f"缺库 {lib}——求解/敏感性代码只能用 numpy/scipy 替代（方向阶段勿选依赖它的方法）"
                )

    return {
        "ok": not problems,
        "problems": problems,
        "warns": warns,
        "blockers": blockers,
        "brief_path": str(brief_path) if brief_path is not None else None,
        "ok_libs": ok_libs,
    }


def write_preflight_json(payload: dict, out: Path) -> Path:
    """写入 ``out/preflight.json``（UTF-8、indent=2、末尾换行）。"""
    out.mkdir(parents=True, exist_ok=True)
    path = out / "preflight.json"
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path
