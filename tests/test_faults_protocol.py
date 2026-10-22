from __future__ import annotations

import pytest

from mailcpu.bus import MailboxBus
from mailcpu.faults import FaultInjectingTransport, FaultProfile
from mailcpu.headless import HeadlessOS
from mailcpu.kernel import VirtualKernel
from mailcpu.model import Message
from mailcpu.protocol import SyscallClient, SyscallServer
from mailcpu.transport import InMemoryTransport


def test_fault_transport_exposes_drop_duplicate_delay_and_reorder() -> None:
    """Mathematics: verify the observed queue reflects the configured fault function over send indices."""

    transport = FaultInjectingTransport(
        FaultProfile(
            drop_indices=frozenset({2}),
            duplicate_indices=frozenset({1}),
            delays=((3, 3),),
            reorder_ready_messages=True,
        )
    )
    transport.send("mailbox", Message(value=1))
    transport.send("mailbox", Message(value=2))
    transport.send("mailbox", Message(value=3))
    transport.advance(2)
    values = [message.value for message in transport.list("mailbox")]
    assert values == [1, 1]
    transport.advance(1)
    assert [message.value for message in transport.list("mailbox")] == [1, 1, 3]
    assert [item.action for item in transport.observations] == ["deliver", "drop", "deliver"]


def test_transport_and_bus_restore_reject_counter_collisions_and_route_mismatch() -> None:
    r"""Mathematics: restored identity counters must exceed `max(id)` and every queued message must inhabit its declared mailbox."""

    transport = InMemoryTransport()
    transport.send("mailbox", Message(sender="a", recipient="mailbox"))
    invalid_transport = transport.snapshot()
    invalid_transport["next_id"] = 1
    with pytest.raises(ValueError, match="next_id"):
        InMemoryTransport.from_snapshot(invalid_transport)

    bus = MailboxBus()
    bus.send("a", "b", "data", {"value": 1})
    invalid_bus = bus.snapshot()
    invalid_bus["queues"]["b"][0]["destination"] = "other"
    with pytest.raises(ValueError, match="identity or route"):
        MailboxBus.from_snapshot(invalid_bus)


def test_structured_syscall_request_reply_crosses_bus() -> None:
    """Mathematics: verify request/reply composition `client.submit; server.serve; client.receive = Ok(result)`."""

    bus = MailboxBus()
    kernel = VirtualKernel(bus=bus)
    pid = kernel.spawn("client")
    client = SyscallClient(bus, pid)
    server = SyscallServer(bus, kernel)
    request_id = client.submit("getpid")
    response = server.serve_once()
    assert response is not None
    assert response.request_id == request_id
    assert client.receive().result == pid


def test_structured_syscall_failure_is_a_wire_level_result() -> None:
    """Mathematics: verify failed transitions remain observable as `Err(error)` instead of being fabricated as success."""

    bus = MailboxBus()
    kernel = VirtualKernel(bus=bus)
    pid = kernel.spawn("client")
    client = SyscallClient(bus, pid)
    server = SyscallServer(bus, kernel)
    client.submit("unknown_syscall")
    server.serve_once()
    response = client.receive()
    assert response is not None
    assert response.ok is False
    assert "unknown syscall" in (response.error or "")


def test_syscall_server_rejects_payload_pid_spoofing() -> None:
    r"""Mathematics: request authority requires `message.source = proc(request.pid)`."""

    bus = MailboxBus()
    kernel = VirtualKernel(bus=bus)
    victim = kernel.spawn("victim")
    attacker = kernel.spawn("attacker")
    bus.send(
        f"proc:{attacker}",
        "kernel",
        "syscall.request",
        {"request_id": "req-spoof", "pid": victim, "name": "getpid", "args": {}},
        reply_to=f"proc:{attacker}",
    )

    with pytest.raises(ValueError, match="identity mismatch"):
        SyscallServer(bus, kernel).serve_once()
    assert bus.peek(f"proc:{victim}") == ()


def test_syscall_client_rejects_forged_response_source() -> None:
    r"""Mathematics: client response acceptance requires `source = server_endpoint` and `destination = proc(pid)`."""

    bus = MailboxBus()
    client = SyscallClient(bus, 7)
    bus.send(
        "attacker",
        "proc:7",
        "syscall.response",
        {"request_id": "req-00000001", "ok": True, "result": 99, "error": None},
    )

    with pytest.raises(ValueError, match="identity mismatch"):
        client.receive()


def test_headless_memory_syscalls_cross_bus_with_lossless_bytes() -> None:
    """Mathematics: wire composition `client → kernel → client` preserves `bytes` and explicit success/failure partitions."""

    operating_system = HeadlessOS()
    pid = operating_system.launch_source("halt\n", "bus-memory", max_pages=3)
    client = SyscallClient(operating_system.environment.kernel.bus, pid)
    server = operating_system.syscall_server()

    request_id = client.submit("mmap", length=4096)
    response = server.serve_once()
    assert response is not None and response.request_id == request_id and response.ok
    first_reply = client.receive()
    assert first_reply is not None and first_reply.result == 8192

    client.submit("mem_write", address=8192, data=b"over-the-bus")
    write_reply = server.serve_once()
    assert write_reply is not None and write_reply.ok
    write_result = client.receive()
    assert write_result is not None and write_result.result == 12

    client.submit("mem_read", address=8192, size=12)
    read_reply = server.serve_once()
    assert read_reply is not None and read_reply.ok
    read_result = client.receive()
    assert read_result is not None and read_result.result == b"over-the-bus"

    client.submit("mem_read", address=16384, size=1)
    failure_reply = server.serve_once()
    assert failure_reply is not None and failure_reply.ok is False
    failure = client.receive()
    assert failure is not None and failure.ok is False and "unmapped page" in (failure.error or "")


def test_transport_snapshots_preserve_binary_fifo_identity() -> None:
    """Mathematics: transport restore preserves `Q`, message identity, and `bytes` body projection exactly."""

    transport = InMemoryTransport()
    transport.send("mailbox", Message(body=(b"payload", {"n": 2})))
    restored = InMemoryTransport.from_snapshot(transport.snapshot())
    message = restored.poll("mailbox")
    assert message is not None
    assert message.body == (b"payload", {"n": 2})
    assert message.message_id == "m00000001"


def test_fault_transport_snapshot_preserves_staged_delivery() -> None:
    """Mathematics: restoring staged set `S` and clock `t` yields the same delivery when `t≥ready_time` later holds."""

    transport = FaultInjectingTransport(FaultProfile(delays=((1, 3),)))
    transport.send("mailbox", Message(body=(b"delayed",)))
    restored = FaultInjectingTransport.from_snapshot(transport.snapshot())
    assert restored.pending_staged() == 1
    restored.advance(2)
    assert restored.list("mailbox") == ()
    restored.advance(1)
    delivered = restored.poll("mailbox")
    assert delivered is not None and delivered.body == (b"delayed",)


def test_syscall_server_deduplicates_side_effects_and_restores_cache() -> None:
    """Mathematics: repeated request `r` yields cached `C[r]` without a second transition, while altered `r` is rejected."""

    bus = MailboxBus()
    kernel = VirtualKernel(bus=bus)
    pid = kernel.spawn("client")
    client = SyscallClient(bus, pid)
    server = SyscallServer(bus, kernel)
    request_id = client.submit("pipe")
    original = bus.peek("kernel")[0]
    first = server.serve_once()
    assert first is not None and first.ok
    first_result = client.receive()
    assert first_result is not None and len(first_result.result) == 2
    assert len(kernel.pipes) == 1

    bus.send(f"proc:{pid}", "kernel", "syscall.request", dict(original.payload), reply_to=f"proc:{pid}")
    duplicate = server.serve_once()
    assert duplicate is not None and duplicate.request_id == request_id and duplicate.ok
    duplicate_result = client.receive()
    assert duplicate_result is not None and duplicate_result.result == first_result.result
    assert len(kernel.pipes) == 1

    restored_server = SyscallServer.from_snapshot(bus, kernel, server.snapshot())
    bus.send(f"proc:{pid}", "kernel", "syscall.request", dict(original.payload), reply_to=f"proc:{pid}")
    restored_duplicate = restored_server.serve_once()
    assert restored_duplicate is not None and restored_duplicate.ok
    assert client.receive().result == first_result.result
    assert len(kernel.pipes) == 1

    altered = dict(original.payload)
    altered["name"] = "getpid"
    bus.send(f"proc:{pid}", "kernel", "syscall.request", altered, reply_to=f"proc:{pid}")
    conflict = restored_server.serve_once()
    assert conflict is not None and conflict.ok is False
    assert "reused" in (client.receive().error or "")


def test_headless_exec_is_available_through_the_bus() -> None:
    """Mathematics: remote `exec(path)` preserves PID and makes the replacement orbit `T^k(new_program)` executable."""

    operating_system = HeadlessOS()
    pid = operating_system.launch_source("halt\n", "old")
    operating_system.install_source("/home/new.mca", "set answer 42\nhalt\n")
    client = SyscallClient(operating_system.environment.kernel.bus, pid)
    server = operating_system.syscall_server()
    client.submit("exec", path="/home/new.mca", argv=["new"])
    response = server.serve_once()
    assert response is not None and response.ok
    reply = client.receive()
    assert reply is not None and reply.result == 0
    assert operating_system.process(pid).argv == ("new",)
    operating_system.run(10)
    assert operating_system.process(pid).registers["answer"] == 42
