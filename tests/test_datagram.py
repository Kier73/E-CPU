from __future__ import annotations

from pathlib import Path

import pytest

from mailcpu import DatagramError, HeadlessOS, NetworkAddress, decode_datagram, encode_datagram
from mailcpu.kernel import KernelError


def _network(bind_sockets: bool = True) -> tuple[HeadlessOS, int, int | None, int | None]:
    """Mathematics: construct routed topology `root/eth0 ↔ guest/eth0`, optionally binding its ports."""

    os = HeadlessOS()
    pid = os.environment.init_pid
    os.syscall(pid, "net_namespace_create", name="guest")
    os.syscall(pid, "net_interface_create", namespace="root", interface="eth0")
    os.syscall(pid, "net_interface_create", namespace="guest", interface="eth0")
    os.syscall(
        pid,
        "net_connect",
        link="root-guest",
        left_namespace="root",
        left_interface="eth0",
        right_namespace="guest",
        right_interface="eth0",
    )
    source_socket = None
    destination_socket = None
    if bind_sockets:
        source_socket = os.syscall(
            pid,
            "net_dgram_bind",
            namespace="root",
            interface="eth0",
            port=6000,
        )
        destination_socket = os.syscall(
            pid,
            "net_dgram_bind",
            namespace="guest",
            interface="eth0",
            port=7000,
        )
    return os, pid, source_socket, destination_socket


def test_datagram_wire_encoding_is_injective_and_bounded() -> None:
    """Mathematics: `decode(encode(p_s,p_d,b))=(p_s,p_d,b)` and malformed lengths are rejected."""

    wire = encode_datagram(6000, 7000, b"mailcpu")
    assert decode_datagram(wire) == (6000, 7000, b"mailcpu")
    with pytest.raises(DatagramError, match="length"):
        decode_datagram(wire[:-1])
    with pytest.raises(DatagramError, match="port"):
        encode_datagram(0, 7000, b"")


def test_datagram_stack_binds_demultiplexes_and_preserves_small_buffer_failure() -> None:
    """Mathematics: port demultiplexing maps envelope destination `p_d` to `Q_socket[p_d]` and failed size checks preserve the raw head."""

    os, pid, source_socket, destination_socket = _network()
    assert source_socket is not None and destination_socket is not None
    second_socket = os.syscall(
        pid,
        "net_dgram_bind",
        namespace="guest",
        interface="eth0",
        port=7001,
    )
    os.syscall(
        pid,
        "net_dgram_send",
        socket_id=source_socket,
        destination_namespace="guest",
        destination_interface="eth0",
        destination_port=7001,
        payload=b"second",
        logical_time=1,
    )
    os.syscall(
        pid,
        "net_dgram_send",
        socket_id=source_socket,
        destination_namespace="guest",
        destination_interface="eth0",
        destination_port=7000,
        payload=b"first",
        logical_time=2,
    )
    first = os.syscall(pid, "net_dgram_receive", socket_id=destination_socket)
    second = os.syscall(pid, "net_dgram_receive", socket_id=second_socket)
    assert first.payload == b"first"
    assert second.payload == b"second"

    os.syscall(
        pid,
        "net_dgram_send",
        socket_id=source_socket,
        destination_namespace="guest",
        destination_interface="eth0",
        destination_port=7000,
        payload=b"wide",
        logical_time=3,
    )
    with pytest.raises(DatagramError, match="smaller"):
        os.syscall(pid, "net_dgram_receive", socket_id=destination_socket, max_size=2)
    assert os.environment.owned_network.peek(NetworkAddress("guest", "eth0")) is not None


def test_unbound_datagram_does_not_block_later_bound_frame() -> None:
    r"""Mathematics: demultiplexing drops `p_d ∉ dom(B)` and continues to the next FIFO frame."""

    os, pid, source_socket, destination_socket = _network()
    assert source_socket is not None and destination_socket is not None
    os.syscall(
        pid,
        "net_dgram_send",
        socket_id=source_socket,
        destination_namespace="guest",
        destination_interface="eth0",
        destination_port=7999,
        payload=b"orphan",
        logical_time=1,
    )
    os.syscall(
        pid,
        "net_dgram_send",
        socket_id=source_socket,
        destination_namespace="guest",
        destination_interface="eth0",
        destination_port=7000,
        payload=b"bound",
        logical_time=2,
    )

    datagram = os.syscall(pid, "net_dgram_receive", socket_id=destination_socket)
    assert datagram.payload == b"bound"


def test_datagram_checkpoint_restores_raw_and_socket_queues(tmp_path: Path) -> None:
    """Mathematics: `restore(snapshot(F,B,Q))` preserves a queued wire datagram and binding identity."""

    os, pid, source_socket, destination_socket = _network()
    assert source_socket is not None and destination_socket is not None
    os.syscall(
        pid,
        "net_dgram_send",
        socket_id=source_socket,
        destination_namespace="guest",
        destination_interface="eth0",
        destination_port=7000,
        payload=b"checkpoint-datagram",
        logical_time=8,
    )
    os.environment.network_datagram_peek(pid, destination_socket)
    os.syscall(
        pid,
        "net_dgram_send",
        socket_id=source_socket,
        destination_namespace="guest",
        destination_interface="eth0",
        destination_port=7000,
        payload=b"raw-queue",
        logical_time=9,
    )
    checkpoint = tmp_path / "datagram.mcpu.json"
    os.save_checkpoint(checkpoint)
    restored = HeadlessOS.restore_checkpoint(checkpoint)
    received = restored.syscall(restored.environment.init_pid, "net_dgram_receive", socket_id=destination_socket)
    second = restored.syscall(restored.environment.init_pid, "net_dgram_receive", socket_id=destination_socket)
    assert received is not None and second is not None
    assert received.payload == b"checkpoint-datagram"
    assert second.payload == b"raw-queue"
    assert restored.environment.kernel.journal.verify()


def test_scheduled_program_transfers_datagram_through_virtual_memory() -> None:
    """Mathematics: `net_dgram_send_from` and `net_dgram_receive_into` implement `Q_socket := Q_socket || memory[a:a+n]` and its inverse."""

    os, pid, source_socket, destination_socket = _network(False)
    sender = os.run_source(
        "\n".join(
            (
                "SYSCALL r0 net_dgram_bind namespace=root interface=eth0 port=6000",
                "SYSCALL r1 mmap length=4 writable=true",
                "SYSCALL r2 mem_write address=$r1 data=hex:64617461",
                "SYSCALL r3 net_dgram_send_from socket_id=$r0 destination_namespace=guest destination_interface=eth0 destination_port=7000 address=$r1 size=4 logical_time=14",
                "SYSCALL r4 exit code=0",
            )
        ),
        name="datagram-sender",
    )
    assert sender.exit_code == 0
    receiver = os.launch_source(
        "\n".join(
            (
                "SYSCALL r0 net_dgram_bind namespace=guest interface=eth0 port=7000",
                "SYSCALL r1 mmap length=4 writable=true",
                "SYSCALL r2 net_dgram_receive_into socket_id=$r0 address=$r1 size=4",
                "SYSCALL r3 exit code=0",
            )
        ),
        name="datagram-receiver",
    )
    os.run()
    address = os.process(receiver).registers["r1"]
    assert os.vm.memories[receiver].read(address, 4) == b"data"


def test_network_handles_are_process_owned_and_checkpointed() -> None:
    """Mathematics: handle authority is a partial function `Owner(h)=pid`; `Owner(h)≠caller` is denied."""

    os, pid, _, destination_socket = _network()
    assert destination_socket is not None
    other = os.launch_source("halt\n", name="other-process")
    with pytest.raises(KernelError, match="belongs to process"):
        os.syscall(other, "net_dgram_receive", socket_id=destination_socket)
    snapshot = os.snapshot()
    restored = HeadlessOS.from_snapshot(snapshot)
    with pytest.raises(KernelError, match="belongs to process"):
        restored.syscall(other, "net_dgram_receive", socket_id=destination_socket)


def test_reaping_process_releases_owned_datagram_handles() -> None:
    """Mathematics: exact reaping applies `Owner^{-1}(pid):=∅` and removes every owned socket resource."""

    os, _, _, _ = _network(False)
    report = os.run_source(
        "\n".join(
            (
                "SYSCALL r0 net_dgram_bind namespace=root interface=eth0 port=6100",
                "SYSCALL r1 exit code=0",
            )
        ),
        name="socket-owner",
    )
    assert os.environment.datagrams.sockets()
    os.reap_process(report.pid)
    assert os.environment.datagrams.sockets() == ()
