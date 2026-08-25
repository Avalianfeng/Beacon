# -*- coding: utf-8 -*-
"""report_calibration_diff.py 测试（仓库内 fixture，不用 tmp_path）。"""

import json
import sys
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures" / "check_calib"
SCRIPT = Path(__file__).parent.parent / "scripts" / "report_calibration_diff.py"

from scripts.report_calibration_diff import hit_range, main  # noqa: E402


@pytest.fixture(scope="module", autouse=True)
def _fixtures():
    FIXTURES.mkdir(parents=True, exist_ok=True)
    (FIXTURES / "official_miss.json").write_text(json.dumps({
        "problem_id": "test-b",
        "obtained_at": "2026-08-24",
        "q1": {"range_s": [37000, 39500], "declared_s": 37280},
        "q2": {"declared_s": 142965, "range_s": None},
        "q3": {"range_s": [72500, 85000], "declared_s": 72860},
        "q4": {"range_s": [30750, 38500], "declared_s": 30755,
               "purchase": {"D": 3, "E": 3, "total": 7}},
        "ours_20260824": {
            "q1_s": 41600, "q2_s": 215303, "q3_s": 127085, "q4_s": 123844,
            "q4_spent_yuan": 155000,
            "q4_purchase": {"D": 1, "E": 1, "total": 2},
            "root_cause": "假设 9 口径收紧（测试）",
        },
    }), encoding="utf-8")
    (FIXTURES / "ours_hit.json").write_text(json.dumps({
        "q1_s": 38000, "q2_s": 142965, "q3_s": 75000, "q4_s": 32000,
        "q4_spent_yuan": 500000,
        "q4_purchase": {"D": 3, "E": 3, "total": 7},
    }), encoding="utf-8")
    yield


class TestHitRange:
    def test_hit(self):
        assert hit_range(38000, [37000, 39500]) is True

    def test_miss(self):
        assert hit_range(41600, [37000, 39500]) is False

    def test_none_range(self):
        assert hit_range(142965, None) is None


class TestMain:
    def test_miss_all_default_warn(self, capsys):
        code = main(["--official", str(FIXTURES / "official_miss.json")])
        out = capsys.readouterr().out
        assert code == 0  # 默认 WARN
        assert "未命中项 4 处" in out  # q1/q3/q4 区间 + q4_purchase（q2 无区间不判定）
        assert "❌" in out
        assert "根因提示：假设 9 口径收紧（测试）" in out

    def test_miss_all_strict(self, capsys):
        assert main(["--official", str(FIXTURES / "official_miss.json"), "--strict"]) == 1

    def test_hit_all(self, capsys):
        code = main(["--official", str(FIXTURES / "official_miss.json"),
                     "--ours", str(FIXTURES / "ours_hit.json")])
        out = capsys.readouterr().out
        assert code == 0
        assert "（全部命中）" in out
        assert "✅" in out

    def test_missing_file(self, capsys):
        assert main(["--official", str(FIXTURES / "不存在.json")]) == 2

    def test_no_ours_and_no_embedded(self, tmp_fixture, capsys):
        (tmp_fixture / "no_ours.json").write_text(
            json.dumps({"problem_id": "x", "q1": {"range_s": [1, 2]}}), encoding="utf-8")
        assert main(["--official", str(tmp_fixture / "no_ours.json")]) == 2

    def test_cli_subprocess_strict(self):
        import subprocess
        r = subprocess.run(
            [sys.executable, str(SCRIPT), "--official",
             str(FIXTURES / "official_miss.json"), "--strict"],
            capture_output=True, text=True)
        assert r.returncode == 1


@pytest.fixture(scope="module")
def tmp_fixture():
    FIXTURES.mkdir(parents=True, exist_ok=True)
    return FIXTURES
