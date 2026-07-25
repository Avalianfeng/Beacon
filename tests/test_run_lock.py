import pytest

from math_agent.run_lock import RunLock, RunLockedError, is_locked


def test_only_one_worker_can_hold_output_directory_lock(workdir):
    first = RunLock(workdir)
    second = RunLock(workdir)

    with first:
        with pytest.raises(RunLockedError):
            second.acquire()

    second.acquire()
    second.release()


def test_is_locked_reports_holder(workdir):
    assert is_locked(workdir) is False
    with RunLock(workdir):
        assert is_locked(workdir) is True
    assert is_locked(workdir) is False

