from math_agent.ops_help import ROOT_HELP, STAGE_HELP_MARKERS


def test_root_help_contains_stage_markers():
    for marker in STAGE_HELP_MARKERS:
        assert marker in ROOT_HELP


def test_root_help_contains_key_commands():
    assert "problem" in ROOT_HELP
    assert "review-check" in ROOT_HELP
    assert "supervise" in ROOT_HELP
