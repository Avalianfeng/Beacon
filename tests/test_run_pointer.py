"""运行目录自动发现。"""
from __future__ import annotations

import json
from pathlib import Path

from math_agent.run_pointer import (
    find_recent_out,
    resolve_out_dir,
    write_active_run,
)


def test_write_and_resolve_pointer(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    out = tmp_path / "runs" / "demo"
    out.mkdir(parents=True)
    (out / "supervisor.json").write_text(
        json.dumps({"status": "blocked", "thread": "default"}), encoding="utf-8",
    )
    write_active_run(out, thread="default", status="blocked", cwd=tmp_path)

    resolved, how = resolve_out_dir(None, cwd=tmp_path)
    assert resolved == out.resolve()
    assert how in {"pointer", "recent"}


def test_explicit_out_wins(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    a = tmp_path / "runs" / "a"
    b = tmp_path / "runs" / "b"
    a.mkdir(parents=True)
    b.mkdir(parents=True)
    (a / "supervisor.json").write_text("{}", encoding="utf-8")
    write_active_run(a, cwd=tmp_path)
    resolved, how = resolve_out_dir(b, cwd=tmp_path)
    assert resolved == b.resolve()
    assert how == "explicit"


def test_placeholder_latest_falls_back(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    real = tmp_path / "runs" / "ui-latest"
    real.mkdir(parents=True)
    (real / "supervisor.json").write_text(
        json.dumps({"status": "completed"}), encoding="utf-8",
    )
    write_active_run(real, cwd=tmp_path)
    resolved, how = resolve_out_dir("runs/latest", cwd=tmp_path)
    assert resolved == real.resolve()
    assert how in {"pointer", "recent"}


def test_find_recent_out(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    older = tmp_path / "runs" / "old"
    newer = tmp_path / "runs" / "new"
    older.mkdir(parents=True)
    newer.mkdir(parents=True)
    (older / "supervisor.json").write_text("{}", encoding="utf-8")
    (newer / "supervisor.json").write_text("{}", encoding="utf-8")
    assert find_recent_out(tmp_path) == newer.resolve()
