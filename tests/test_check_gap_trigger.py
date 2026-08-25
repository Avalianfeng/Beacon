# -*- coding: utf-8 -*-
"""check_gap_trigger.py 测试（仓库内 fixture，不用 tmp_path）。"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures" / "check_gap"
SCRIPT = Path(__file__).parent.parent / "scripts" / "check_gap_trigger.py"

from scripts.check_gap_trigger import find_gap_candidates, main  # noqa: E402


@pytest.fixture(scope="module")
def big_gap_json(tmp_fixture_dir):
    return tmp_fixture_dir / "big_gap.json"


@pytest.fixture(scope="module")
def small_gap_json(tmp_fixture_dir):
    return tmp_fixture_dir / "small_gap.json"


@pytest.fixture(scope="module")
def no_pair_json(tmp_fixture_dir):
    return tmp_fixture_dir / "no_pair.json"


@pytest.fixture(scope="module")
def tmp_fixture_dir():
    FIXTURES.mkdir(parents=True, exist_ok=True)
    return FIXTURES


@pytest.fixture(scope="module", autouse=True)
def _write_fixtures(tmp_fixture_dir):
    (tmp_fixture_dir / "big_gap.json").write_text(
        json.dumps({
            "cpm_lower_bounds": {
                "Q1": {"lb_pure_duration": 41400, "makespan": 41600,
                       "gap_s_pure": 200, "gap_pct_pure": 0.4831},
                "Q2": {"lb": 123614, "makespan": 215303, "gap_s": 91689,
                       "gap_pct": 74.1736},
                "Q3": {"lb": 123614, "makespan": 127085, "gap_s": 3471,
                       "gap_pct": 2.8079},
            }
        }), encoding="utf-8")
    (tmp_fixture_dir / "small_gap.json").write_text(
        json.dumps({"bound": {"lb": 1000, "makespan": 1050}}), encoding="utf-8")
    (tmp_fixture_dir / "no_pair.json").write_text(
        json.dumps({"only": {"makespan": 41600}}), encoding="utf-8")
    yield


class TestFindGapCandidates:
    def test_pairs_big_gap(self, big_gap_json):
        data = json.loads(big_gap_json.read_text(encoding="utf-8"))
        rows = find_gap_candidates(data)
        # Q1 命中 lb_pure_duration=41400（lb 取第一个匹配键）
        # Q2 命中 lb=123614；Q3 命中 lb=123614
        lbs = sorted(r[1] for r in rows)
        assert lbs == [41400, 123614, 123614]
        mss = sorted(r[2] for r in rows)
        assert mss == [41600, 127085, 215303]

    def test_no_pair(self, no_pair_json):
        data = json.loads(no_pair_json.read_text(encoding="utf-8"))
        assert find_gap_candidates(data) == []


class TestMain:
    def test_default_warn_big_gap(self, big_gap_json, capsys):
        code = main(["--json", str(big_gap_json)])
        out = capsys.readouterr().out
        assert code == 0  # 默认 WARN
        assert "⚠ 触发" in out
        assert "74.17%" in out
        assert "Q2" in out

    def test_strict_big_gap(self, big_gap_json, capsys):
        code = main(["--json", str(big_gap_json), "--strict"])
        assert code == 1

    def test_small_gap_no_trigger(self, small_gap_json, capsys):
        code = main(["--json", str(small_gap_json)])
        out = capsys.readouterr().out
        assert code == 0
        assert "触发 0 处" in out

    def test_no_pair(self, no_pair_json, capsys):
        code = main(["--json", str(no_pair_json)])
        assert code == 0

    def test_no_input(self, capsys):
        assert main([]) == 2

    def test_missing_file(self, capsys):
        assert main(["--json", str(FIXTURES / "不存在.json")]) == 2

    def test_threshold_override(self, small_gap_json, capsys):
        # 5% 差距 < 默认 15，但若阈值降到 4 则触发
        code = main(["--json", str(small_gap_json), "--threshold", "4"])
        assert code == 0  # 默认 WARN
        assert "⚠ 触发" in capsys.readouterr().out
        code = main(["--json", str(small_gap_json), "--threshold", "4", "--strict"])
        assert code == 1

    def test_cli_subprocess_strict_exit(self, big_gap_json):
        r = subprocess.run(
            [sys.executable, str(SCRIPT), "--json", str(big_gap_json), "--strict"],
            capture_output=True, text=True)
        assert r.returncode == 1
        assert "74.17%" in r.stdout
