"""Crash-loop bounds and real child-process readiness supervision."""

from __future__ import annotations

from pathlib import Path
import sys

import pytest

from mailcpu import RestartPolicy
from mailcpu.subprocess_service import (
    SubprocessServiceError,
    SubprocessServiceSpec,
    SubprocessServiceSupervisor,
)


def _worker_command() -> tuple[str, ...]:
    source = (
        "import time; "
        "from mailcpu.subprocess_service import publish_service_ready; "
        "publish_service_ready({'role': 'test-worker'}); "
        "time.sleep(60)"
    )
    return (sys.executable, "-c", source)


def test_subprocess_supervisor_restarts_hard_killed_child_within_finite_budget(
    tmp_path: Path,
) -> None:
    """A fresh PID must prove readiness, and repeated failure must exhaust the declared budget."""

    supervisor = SubprocessServiceSupervisor()
    supervisor.register(
        SubprocessServiceSpec(
            name="worker",
            command=_worker_command(),
            readiness_directory=tmp_path / "ready",
            restart=RestartPolicy.ON_FAILURE,
            max_restarts=1,
            readiness_timeout=5.0,
            restart_delay=0.01,
            cwd=Path(__file__).resolve().parents[1],
        )
    )
    try:
        first = supervisor.start("worker")
        assert first.state == "running"
        assert first.pid is not None
        assert first.ready == {"role": "test-worker"}
        first_pid = first.pid

        supervisor.kill("worker")
        restarted = supervisor.reconcile()[0]
        assert restarted.state == "running"
        assert restarted.pid is not None and restarted.pid != first_pid
        assert restarted.restart_count == 1
        assert restarted.ready == {"role": "test-worker"}

        supervisor.kill("worker")
        exhausted = supervisor.reconcile()[0]
        assert exhausted.state == "restart_exhausted"
        assert exhausted.pid is None
        assert exhausted.restart_count == 1
        assert exhausted.exit_code not in (None, 0)
    finally:
        supervisor.close()


def test_explicit_stop_clears_desired_state_and_suppresses_restart(
    tmp_path: Path,
) -> None:
    supervisor = SubprocessServiceSupervisor()
    supervisor.register(
        SubprocessServiceSpec(
            name="worker",
            command=_worker_command(),
            readiness_directory=tmp_path / "ready",
            restart=RestartPolicy.ALWAYS,
            max_restarts=5,
            readiness_timeout=5.0,
            cwd=Path(__file__).resolve().parents[1],
        )
    )
    started = supervisor.start("worker")
    assert started.pid is not None

    stopped = supervisor.stop("worker")
    assert stopped.state == "stopped"
    assert stopped.pid is None
    reports = supervisor.reconcile()
    assert reports[0].state == "stopped"
    assert reports[0].restart_count == 0
    supervisor.close()


def test_never_restart_policy_survives_failed_initial_readiness(tmp_path: Path) -> None:
    """A failed first spawn remains terminal when the declared restart policy is NEVER."""

    marker = tmp_path / "spawn-count.txt"
    source = (
        "from pathlib import Path; "
        f"Path({str(marker)!r}).open('a', encoding='utf-8').write('x'); "
        "raise SystemExit(17)"
    )
    supervisor = SubprocessServiceSupervisor()
    supervisor.register(
        SubprocessServiceSpec(
            name="never-worker",
            command=(sys.executable, "-c", source),
            readiness_directory=tmp_path / "ready",
            restart=RestartPolicy.NEVER,
            max_restarts=5,
            readiness_timeout=2.0,
            cwd=tmp_path,
        )
    )
    try:
        with pytest.raises(SubprocessServiceError, match="exited before readiness"):
            supervisor.start("never-worker")

        failed = supervisor.status("never-worker")
        assert failed.state == "failed"
        assert failed.restart_count == 0
        assert marker.read_text(encoding="utf-8") == "x"

        for _ in range(3):
            reconciled = supervisor.reconcile()[0]
            assert reconciled.state == "failed"
            assert reconciled.restart_count == 0

        assert marker.read_text(encoding="utf-8") == "x"
    finally:
        supervisor.close()
