from math_agent.ops_help import ROOT_HELP, STAGE_HELP_MARKERS


def test_root_help_contains_stage_markers():
    for marker in STAGE_HELP_MARKERS:
        assert marker in ROOT_HELP


def test_root_help_contains_key_commands():
    assert "problem" in ROOT_HELP
    assert "review-check" in ROOT_HELP
    assert "recertify" in ROOT_HELP
    assert "accept" in ROOT_HELP
    assert "做题主路径" in ROOT_HELP
    assert "可选遗留执行器" in ROOT_HELP
    assert "supervise" in ROOT_HELP
    assert "非做题路径" in ROOT_HELP
    assert "ingest" in ROOT_HELP
    assert "bench" in ROOT_HELP
    # 默认标记不含 S9；S9 只在降权段出现
    assert "S9" not in STAGE_HELP_MARKERS
    assert "S9" in ROOT_HELP
