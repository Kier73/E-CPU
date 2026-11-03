"""Conformance tests for snapshot-covered HeadlessOS-managed operations."""

from __future__ import annotations

import copy

from mailcpu import HeadlessOS, ServiceSpec
from mailcpu.model import Instruction, Op, Program
from mailcpu.headless_relation import (
    capture_headless_os_trace,
    compare_headless_os_states,
    compare_headless_os_traces,
)


def _clone(machine: HeadlessOS) -> HeadlessOS:
    return HeadlessOS.from_snapshot(copy.deepcopy(machine.snapshot()))


def test_standard_memory_syscalls_remain_inside_the_headless_relation() -> None:
    left = HeadlessOS()
    pid = left.spawn(
        Program((
            Instruction(Op.SYSCALL, ("address", "mmap", "length=8", "writable=true")),
            Instruction(
                Op.SYSCALL,
                ("written", "mem_write", "address=$address", "data=hex:434f4d50555445"),
            ),
            Instruction(Op.SYSCALL, ("exit_code", "exit", "code=0")),
        )),
        "syscall-memory-probe",
    )
    right = _clone(left)

    left_trace = capture_headless_os_trace(left, max_transitions=50)
    right_trace = capture_headless_os_trace(right, max_transitions=50)
    assert left_trace.transition_count == 3
    assert compare_headless_os_traces(left_trace, right_trace).equivalent

    address = left.vm.scheduler.tasks[pid].backend.read_register("address")
    assert left.vm.memories[pid].read(address, 7) == b"COMPUTE"
    assert compare_headless_os_states(left, right).equivalent


def _configure_service(machine: HeadlessOS) -> None:
    path = "/etc/services/echo.mca"
    machine.install_source(
        path,
        "set one 1\nloop:\nwait inbox value\nsend out value\nbranch one loop\n",
    )
    machine.services.register(ServiceSpec("echo", path))


def _advance_service(machine: HeadlessOS) -> None:
    started = machine.services.start("echo")
    assert started.pid is not None
    machine.services.tick(2)
    status = machine.services.status("echo")
    assert status.pid == started.pid
    assert status.state == "blocked"
    machine.inject(started.pid, "inbox", [41])
    machine.services.tick(5)
    assert machine.environment.kernel.bus.peek("out")[0].payload["value"] == 41
    stopped = machine.services.stop("echo")
    assert stopped.state == "stopped"


def test_service_supervisor_state_and_lifecycle_are_relational() -> None:
    left = HeadlessOS()
    _configure_service(left)
    right = _clone(left)

    _advance_service(left)
    _advance_service(right)

    relation = compare_headless_os_states(left, right)
    assert relation.equivalent
    assert left.environment.kernel.journal.verify()
    assert right.environment.kernel.journal.verify()


def _configure_network_descriptors(machine: HeadlessOS) -> tuple[int, int, int]:
    pid = machine.environment.init_pid
    assert pid is not None
    machine.syscall(pid, "net_namespace_create", name="guest")
    machine.syscall(pid, "net_interface_create", namespace="root", interface="eth0")
    machine.syscall(pid, "net_interface_create", namespace="guest", interface="eth0")
    machine.syscall(
        pid,
        "net_connect",
        link="root-guest",
        left_namespace="root",
        left_interface="eth0",
        right_namespace="guest",
        right_interface="eth0",
    )
    listener = machine.syscall(
        pid, "net_stream_listen_fd",
        namespace="guest", interface="eth0", port=8000
    )
    client = machine.syscall(
        pid,
        "net_stream_connect_fd",
        source_namespace="root",
        source_interface="eth0",
        source_port=9000,
        destination_namespace="guest",
        destination_interface="eth0",
        destination_port=8000,
    )
    accepted = machine.syscall(pid, "net_stream_accept_fd", fd=listener)
    return pid, client, accepted


def test_network_descriptor_queue_state_is_part_of_the_headless_relation() -> None:
    left = HeadlessOS()
    right = _clone(left)

    left_pid, left_client, left_accepted = _configure_network_descriptors(left)
    right_pid, right_client, right_accepted = _configure_network_descriptors(right)
    assert (left_pid, left_client, left_accepted) == (
        right_pid, right_client, right_accepted
    )
    assert left.syscall(left_pid, "write", fd=left_client, data=b"queued") == 6
    assert right.syscall(right_pid, "write", fd=right_client, data=b"queued") == 6
    assert compare_headless_os_states(left, right).equivalent

    assert left.syscall(left_pid, "read", fd=left_accepted, size=6) == b"queued"
    assert right.syscall(right_pid, "read", fd=right_accepted, size=6) == b"queued"
    assert compare_headless_os_states(left, right).equivalent
