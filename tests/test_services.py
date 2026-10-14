from __future__ import annotations

from mailcpu import HeadlessOS, RestartPolicy, ServiceSpec


def test_service_supervisor_runs_mailbox_service_and_stops_it() -> None:
    """Mathematics: verify desired service state, `WAIT` blocking, mailbox delivery, and controlled shutdown."""

    os = HeadlessOS()
    os.install_source(
        "/etc/services/echo.mca",
        "set one 1\nloop:\nwait inbox value\nsend out value\nbranch one loop\n",
    )
    os.services.register(ServiceSpec("echo", "/etc/services/echo.mca"))
    started = os.services.start("echo")
    assert started.state == "runnable"
    os.services.tick(2)
    assert os.services.status("echo").state == "blocked"
    pid = os.services.status("echo").pid
    assert pid is not None
    os.inject(pid, "inbox", [41])
    os.services.tick(5)
    assert os.environment.kernel.bus.peek("out")[0].payload["value"] == 41
    stopped = os.services.stop("echo")
    assert stopped.state == "stopped"
    assert stopped.exit_code == 0


def test_service_supervisor_applies_bounded_restart_policy() -> None:
    """Mathematics: `restart_count < max_restarts` permits exactly the finite restart budget, then converges to exited."""

    os = HeadlessOS()
    os.install_source("/etc/services/oneshot.mca", "halt\n")
    os.services.register(ServiceSpec("oneshot", "/etc/services/oneshot.mca", RestartPolicy.ALWAYS, 1))
    first = os.services.start("oneshot")
    os.services.tick(1)
    after_restart = os.services.status("oneshot")
    assert after_restart.restart_count == 1
    assert after_restart.pid != first.pid
    assert first.pid not in os.environment.kernel.processes
    assert first.pid not in os.vm.memories
    os.services.tick(2)
    final = os.services.status("oneshot")
    assert final.state == "exited"
    assert final.restart_count == 1
    assert final.pid is None
    assert all(process.name != "service:oneshot" for process in os.environment.kernel.processes.values())
