from __future__ import annotations

from pathlib import Path

import pytest

from mailcpu import (
    HeadlessOS,
    StreamError,
    StreamState,
    decode_stream_segment,
    encode_stream_segment,
)
from mailcpu.stream import STREAM_ACK, STREAM_DATA, encode_stream_segment


def _stream_network(establish: bool = True) -> tuple[HeadlessOS, int, int | None, int | None, int | None]:
    """Mathematics: construct endpoint pair `root/eth0↔guest/eth0`, optionally completing listener/connection setup."""

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
    if not establish:
        return os, pid, None, None, None
    listener = os.syscall(pid, "net_stream_listen", namespace="guest", interface="eth0", port=8000)
    client = os.syscall(
        pid,
        "net_stream_connect",
        source_namespace="root",
        source_interface="eth0",
        source_port=9000,
        destination_namespace="guest",
        destination_interface="eth0",
        destination_port=8000,
    )
    server = os.syscall(pid, "net_stream_accept", listener=listener)
    assert server != 0
    return os, pid, listener, client, int(server)


def test_stream_segment_round_trip_and_rejection() -> None:
    """Mathematics: `decode_stream_segment(encode_stream_segment(x))=x` and length corruption is refused."""

    wire = encode_stream_segment(7, STREAM_DATA, 3, 1, 9000, 8000, b"bytes")
    segment = decode_stream_segment(wire)
    assert segment.connection_id == 7
    assert segment.payload == b"bytes"
    with pytest.raises(StreamError, match="length"):
        decode_stream_segment(wire[:-1])
    with pytest.raises(StreamError, match="non-data"):
        encode_stream_segment(7, STREAM_ACK, 0, 0, 9000, 8000, b"bad")


def test_stream_send_receive_ack_window_and_close_eof() -> None:
    """Mathematics: byte stream preserves order, cumulative ACK clears pending bytes, and FIN yields EOF `b''`."""

    os, pid, listener, client, server = _stream_network()
    assert listener is not None and client is not None and server is not None
    assert os.syscall(pid, "net_stream_send", handle=client, payload=b"hello", logical_time=1) == 5
    assert os.syscall(pid, "net_stream_receive", handle=server, max_size=2) == b"he"
    assert os.syscall(pid, "net_stream_receive", handle=server) == b"llo"
    assert os.syscall(pid, "net_stream_receive", handle=client) is None
    info = os.syscall(pid, "net_stream_info")
    client_info = next(item for item in info["connections"] if item["handle"] == client)
    assert client_info["acknowledged"] == 5
    os.syscall(pid, "net_stream_close", handle=client, logical_time=2)
    assert os.syscall(pid, "net_stream_receive", handle=server) == b""
    server_info = next(item for item in os.syscall(pid, "net_stream_info")["connections"] if item["handle"] == server)
    assert server_info["state"] == StreamState.CLOSED.value
    assert os.syscall(pid, "net_stream_accept", listener=listener) == 0


def test_orphan_stream_segment_does_not_block_established_connection() -> None:
    r"""Mathematics: an unknown `(destination_port, connection_id)` segment is discarded before the next valid segment."""

    os, pid, _, client, server = _stream_network()
    assert client is not None and server is not None
    source = os.environment.streams.connection_binding(client)[0]
    destination = os.environment.streams.connection_binding(client)[2]
    os.environment.owned_network.send_routed(
        source,
        destination,
        encode_stream_segment(999999, STREAM_DATA, 0, 0, 9000, 8000, b"orphan"),
        1,
    )
    assert os.syscall(pid, "net_stream_send", handle=client, payload=b"valid", logical_time=2) == 5
    assert os.syscall(pid, "net_stream_receive", handle=server) == b"valid"


def test_stream_send_commits_partial_window_prefix_and_resumes_after_ack() -> None:
    """Mathematics: stream send returns `k=min(|B|,W-Σ|pending|,C_peer·chunk)` and later commits the suffix after cumulative ACK."""

    os, pid, _, client, server = _stream_network()
    assert client is not None and server is not None
    payload = b"s" * (os.environment.streams.window + 17)
    first = os.syscall(pid, "net_stream_send", handle=client, payload=payload, logical_time=1)
    assert first == os.environment.streams.window
    assert os.syscall(pid, "net_stream_receive", handle=server) == payload[:first]
    second = os.syscall(pid, "net_stream_send", handle=client, payload=payload[first:], logical_time=2)
    assert second == 17
    assert os.syscall(pid, "net_stream_receive", handle=server) == payload[first:]


def test_stream_send_respects_receiver_buffer_credit() -> None:
    r"""Mathematics: admitted bytes satisfy `|R_peer| + k ≤ W`, even after ACK clears sender pending state."""

    os, pid, _, client, server = _stream_network()
    assert client is not None and server is not None
    os.environment.streams.window = 8
    assert os.syscall(pid, "net_stream_send", handle=client, payload=b"12345678", logical_time=1) == 8
    assert os.environment.network_stream_peek(pid, server) == b"12345678"
    with pytest.raises(StreamError, match="receiver window"):
        os.environment.network_stream_send(pid, client, b"x", 2)
    assert os.environment.network_stream_receive(pid, server) == b"12345678"
    assert os.syscall(pid, "net_stream_send", handle=client, payload=b"x", logical_time=2) == 1

    # The second payload is still in flight; the receiver can never accumulate
    # more than the configured byte window.
    assert os.syscall(pid, "net_stream_receive", handle=server) == b"x"


def test_stream_checkpoint_restores_connection_and_raw_segments(tmp_path: Path) -> None:
    """Mathematics: `restore(snapshot(L,C,Q))` resumes a queued segment and preserves connection identity."""

    os, pid, _, client, server = _stream_network()
    assert client is not None and server is not None
    os.syscall(pid, "net_stream_send", handle=client, payload=b"checkpoint-stream", logical_time=4)
    checkpoint = tmp_path / "stream.mcpu.json"
    os.save_checkpoint(checkpoint)
    restored = HeadlessOS.restore_checkpoint(checkpoint)
    assert restored.syscall(restored.environment.init_pid, "net_stream_receive", handle=server) == b"checkpoint-stream"
    assert restored.environment.kernel.journal.verify()


def test_scheduled_program_transfers_stream_bytes_through_memory() -> None:
    """Mathematics: stream memory syscalls implement `send(memory[a:a+n])` and `receive→memory[a:a+n]`."""

    os, _, _, _, _ = _stream_network(False)
    program = os.run_source(
        "\n".join(
            (
                "SYSCALL r0 net_stream_listen namespace=guest interface=eth0 port=8000",
                "SYSCALL r1 net_stream_connect source_namespace=root source_interface=eth0 source_port=9000 destination_namespace=guest destination_interface=eth0 destination_port=8000",
                "SYSCALL r2 net_stream_accept listener=$r0",
                "SYSCALL r3 mmap length=4 writable=true",
                "SYSCALL r4 mem_write address=$r3 data=hex:7374726d",
                "SYSCALL r5 net_stream_send_from handle=$r1 address=$r3 size=4 logical_time=7",
                "SYSCALL r6 net_stream_receive_into handle=$r2 address=$r3 size=4",
                "SYSCALL r7 exit code=0",
            )
        ),
        name="stream-userland",
    )
    assert program.exit_code == 0
    address = os.process(program.pid).registers["r3"]
    assert os.vm.memories[program.pid].read(address, 4) == b"strm"
