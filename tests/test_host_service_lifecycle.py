from __future__ import annotations

from pathlib import Path
import sys

import pytest

from mailcpu import (
    Capability,
    HeadlessOS,
    HostServiceAction,
    HostServiceCommand,
    HostServiceLifecycleAdapter,
    HostServiceLifecycleError,
    HypervisorAction,
    HypervisorPolicy,
    RestartPolicy,
    SubprocessServiceSpec,
)


def _worker_command() -> tuple[str, ...]:
    source = (
        "import time; "
        "from mailcpu.subprocess_service import publish_service_ready; "
        "publish_service_ready({'role': 'host-service-test'}); "
        "time.sleep(60)"
    )
    return (sys.executable, "-c", source)


def _adapter(tmp_path: Path) -> HostServiceLifecycleAdapter:
    adapter = HostServiceLifecycleAdapter()
    adapter.register(
        SubprocessServiceSpec(
            name="worker",
            command=_worker_command(),
            readiness_directory=tmp_path / "ready",
            restart=RestartPolicy.NEVER,
            max_restarts=0,
            readiness_timeout=5.0,
            cwd=Path(__file__).resolve().parents[1],
        )
    )
    return adapter


def _permissive_hypervisor(operating_system: HeadlessOS) -> None:
    """Keep this integration witness focused on routing and capability enforcement."""

    operating_system.hypervisor.policy = HypervisorPolicy(
        review_confidence=0.0,
        automatic_confidence=0.0,
        destructive_confidence=0.0,
        danger_review_probability=1.0,
        embedding_review_confidence=1.0,
    )


def test_host_service_event_is_capability_gated_and_checkpoint_replay_safe(tmp_path: Path) -> None:
    operating_system = HeadlessOS()
    _permissive_hypervisor(operating_system)
    init_pid = operating_system.environment.init_pid
    manager_pid = operating_system.environment.kernel.spawn(
        "host-service-manager",
        capabilities=(Capability("/host-service/worker", frozenset({"execute", "control", "read"})),),
        parent_pid=init_pid,
    )
    adapter = _adapter(tmp_path)
    start = HostServiceCommand(HostServiceAction.START, "worker")

    try:
        first = operating_system.hypervisor_host_service_event(
            manager_pid, "node-a", "host-service", 1, 7, start, adapter
        )
        assert first.action is HypervisorAction.ALLOW
        assert first.executed is True
        assert first.replayed is False
        assert first.effect["state"] == "running"
        first_pid = first.effect["pid"]
        assert isinstance(first_pid, int)

        duplicate = operating_system.hypervisor_host_service_event(
            manager_pid, "node-a", "host-service", 1, 7, start, adapter
        )
        assert duplicate.replayed is True
        assert duplicate.effect == first.effect
        assert adapter.supervisor.status("worker").pid == first_pid

        restored = HeadlessOS.from_snapshot(operating_system.snapshot())
        restored_duplicate = restored.hypervisor_host_service_event(
            manager_pid, "node-a", "host-service", 1, 7, start, adapter
        )
        assert restored_duplicate.replayed is True
        assert restored_duplicate.effect == first.effect
        assert adapter.supervisor.status("worker").pid == first_pid

        inspected = operating_system.hypervisor_host_service_event(
            manager_pid,
            "node-a",
            "host-service",
            2,
            8,
            HostServiceCommand(HostServiceAction.INSPECT, "worker"),
            adapter,
        )
        assert inspected.action is HypervisorAction.ALLOW
        assert inspected.executed is True
        assert inspected.effect["pid"] == first_pid
        assert inspected.effect["state"] == "running"

        stopped = operating_system.hypervisor_host_service_event(
            manager_pid,
            "node-a",
            "host-service",
            3,
            9,
            HostServiceCommand(HostServiceAction.STOP, "worker"),
            adapter,
        )
        assert stopped.action is HypervisorAction.ALLOW
        assert stopped.executed is True
        assert stopped.effect["state"] == "stopped"
        assert stopped.effect["pid"] is None
        assert operating_system.environment.kernel.journal.verify()
    finally:
        adapter.close()


def test_host_service_event_cannot_exceed_virtual_process_capabilities(tmp_path: Path) -> None:
    operating_system = HeadlessOS()
    init_pid = operating_system.environment.init_pid
    limited_pid = operating_system.environment.kernel.spawn(
        "unprivileged-host-service-client",
        capabilities=(Capability("/host-service/other", frozenset({"execute"})),),
        parent_pid=init_pid,
    )
    adapter = _adapter(tmp_path)
    try:
        denied = operating_system.hypervisor_host_service_event(
            limited_pid,
            "node-a",
            "host-service",
            1,
            7,
            HostServiceCommand(HostServiceAction.START, "worker"),
            adapter,
        )
        assert denied.action is HypervisorAction.DENY
        assert denied.executed is False
        assert denied.effect is None
        assert adapter.supervisor.status("worker").state == "stopped"
    finally:
        adapter.close()


def test_host_service_adapter_refuses_unregistered_or_nonportable_commands(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    try:
        with pytest.raises(HostServiceLifecycleError, match="not registered"):
            adapter.validate(HostServiceCommand(HostServiceAction.START, "other"))

        with pytest.raises(HostServiceLifecycleError, match="identifier"):
            HostServiceCommand(HostServiceAction.START, "../worker")

        with pytest.raises(HostServiceLifecycleError, match="start, stop, or inspect"):
            HostServiceCommand("restart", "worker")
    finally:
        adapter.close()
