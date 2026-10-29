"""One job at a time (Oct 23 review, finding 6)."""

import threading

import pytest

from chimera.jobs import JobRegistry, JobRunning


def test_a_second_job_cannot_start_while_one_runs():
    jobs = JobRegistry()
    release, started = threading.Event(), threading.Event()

    def slow(job):
        started.set()
        release.wait(5)
        return {"ok": True}

    first = jobs.run_function("analyze", slow)
    assert started.wait(2)
    with pytest.raises(JobRunning) as info:
        jobs.run_command("run", ["python", "-c", "pass"])
    assert info.value.job is first and "already running" in str(info.value)
    assert jobs.running() is first and len(jobs._jobs) == 1          # the refused job was never registered
    release.set()
    for _ in range(50):
        if first.status != "running":
            break
        threading.Event().wait(0.05)
    assert first.status == "done" and jobs.running() is None
    second = jobs.run_function("analyze", lambda job: {"ok": True})  # free again
    assert second.id != first.id
