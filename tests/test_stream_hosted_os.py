"""OS-state-in-a-real-stream process-boundary experiment for HeadlessOS.

The TCP carrier carries an entire canonical OS checkpoint between fresh Python
interpreters. Each receiver executes real HeadlessOS transitions and returns the
successor checkpoint. This experiment does not confer authenticated authority
or replicate the M3 quorum lineage; those remain separate E-CPU contracts.
"""

from __future__ import annotations

import copy
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import socket
import struct
import subprocess
import sys

import pytest

from mailcpu import HeadlessOS
from mailcpu.headless_relation import compare_headless_os_states, observe_headless_os_state
from mailcpu.model import Instruction, Op, Program

SCHEMA = "mailcpu.stream-hosted-headlessos.experiment.v1"
MAX_FRAME = 32 * 1024 * 1024


def _canonical(value: object) -> bytes:
    """Encode a state envelope without depending on sender JSON field order."""
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False, ensure_ascii=False
    ).encode("utf-8")


def _frame(value: object) -> bytes:
    """Encode one bounded, checksummed payload for an actual TCP byte stream."""
    body = _canonical(value)
    if not body or len(body) > MAX_FRAME:
        raise ValueError("stream OS envelope exceeds its admitted byte bound")
    return struct.pack(">I", len(body)) + hashlib.sha256(body).digest() + body


def _read_exact(connection: socket.socket, size: int) -> bytes:
    """Reassemble exact bytes across arbitrarily fragmented TCP receives."""
    parts: list[bytes] = []
    remaining = size
    while remaining:
        piece = connection.recv(min(remaining, 65536))
        if not piece:
            raise ValueError("truncated stream OS envelope")
        parts.append(piece)
        remaining -= len(piece)
    return b"".join(parts)


def _receive(connection: socket.socket) -> dict[str, object]:
    """Reject truncation, overlong payloads and altered bytes before interpretation."""
    header = _read_exact(connection, 36)
    length = struct.unpack(">I", header[:4])[0]
    if not 0 < length <= MAX_FRAME:
        raise ValueError("stream OS length is outside admitted bounds")
    body = _read_exact(connection, length)
    if hashlib.sha256(body).digest() != header[4:]:
        raise ValueError("stream OS payload checksum differs")
    payload = json.loads(body)
    if not isinstance(payload, dict):
        raise ValueError("stream OS payload must be an object")
    return payload


def _worker(port: int) -> None:
    """Receive one OS state, execute its scheduled transitions, return its successor."""
    with socket.create_connection(("127.0.0.1", port), timeout=20) as connection:
        connection.settimeout(20)
        request = _receive(connection)
        if request.get("schema") != SCHEMA:
            raise ValueError("stream OS schema mismatch")
        if type(request.get("revision")) is not int or request["revision"] < 0:
            raise ValueError("invalid OS revision")
        if type(request.get("ticks")) is not int or not 0 < request["ticks"] <= 200:
            raise ValueError("invalid OS execution budget")
        if not isinstance(request.get("state"), dict):
            raise ValueError("missing OS state")
        if not isinstance(request.get("identity"), str):
            raise ValueError("missing OS identity")

        machine = HeadlessOS.from_snapshot(request["state"])
        observe_headless_os_state(machine)
        received = None
        if request.get("consume_fd") is not None:
            if type(request["consume_fd"]) is not int:
                raise ValueError("invalid virtual stream descriptor")
            received = machine.syscall(
                machine.environment.init_pid, "read", fd=request["consume_fd"], size=6
            )
            if not isinstance(received, bytes):
                raise ValueError("virtual socket read did not yield bytes")
        machine.run(max_ticks=request["ticks"])
        observe_headless_os_state(machine)
        connection.sendall(_frame({
            "schema": SCHEMA,
            "identity": request["identity"],
            "parent_revision": request["revision"],
            "revision": request["revision"] + 1,
            "worker_pid": os.getpid(),
            "virtual_io_hex": None if received is None else received.hex(),
            "state": machine.snapshot(),
        }))


def _remote_step(
    snapshot: dict[str, object],
    *,
    identity: str,
    revision: int,
    ticks: int,
    consume_fd: int | None = None,
) -> dict[str, object]:
    """Rehost one OS continuation in a newly spawned, independently living process."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        listener.settimeout(20)
        port = listener.getsockname()[1]
        worker = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "--worker", str(port)],
            cwd=Path(__file__).resolve().parents[1],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            with listener.accept()[0] as connection:
                connection.settimeout(20)
                connection.sendall(_frame({
                    "schema": SCHEMA,
                    "identity": identity,
                    "revision": revision,
                    "ticks": ticks,
                    "consume_fd": consume_fd,
                    "state": snapshot,
                }))
                result = _receive(connection)
            stdout, stderr = worker.communicate(timeout=30)
            assert worker.returncode == 0, (stdout, stderr)
        finally:
            if worker.poll() is None:
                worker.kill()
                worker.communicate(timeout=10)
    assert result["schema"] == SCHEMA
    assert result["identity"] == identity
    assert result["parent_revision"] == revision
    assert result["revision"] == revision + 1
    assert result["worker_pid"] != os.getpid()
    return result


def _virtual_stream(machine: HeadlessOS) -> int:
    """Create a queued virtual TCP stream wholly inside the snapshot-covered OS."""
    init = machine.environment.init_pid
    machine.syscall(init, "net_namespace_create", name="guest")
    machine.syscall(init, "net_interface_create", namespace="root", interface="eth0")
    machine.syscall(init, "net_interface_create", namespace="guest", interface="eth0")
    machine.syscall(
        init, "net_connect", link="root-guest",
        left_namespace="root", left_interface="eth0",
        right_namespace="guest", right_interface="eth0",
    )
    listener = machine.syscall(
        init, "net_stream_listen_fd", namespace="guest", interface="eth0", port=8000
    )
    client = machine.syscall(
        init, "net_stream_connect_fd",
        source_namespace="root", source_interface="eth0", source_port=9000,
        destination_namespace="guest", destination_interface="eth0",
        destination_port=8000,
    )
    accepted = machine.syscall(init, "net_stream_accept_fd", fd=listener)
    assert machine.syscall(init, "write", fd=client, data=b"queued") == 6
    return accepted


def test_full_os_continues_through_two_fresh_tcp_process_hosts() -> None:
    """A runnable process and queued virtual socket survive two host-process moves."""
    machine = HeadlessOS()
    pid = machine.spawn(
        Program((
            Instruction(Op.SET, ("remaining", 50)),
            Instruction(Op.SET, ("minus_one", -1)),
            Instruction(Op.ADD, ("remaining", "remaining", "minus_one")),
            Instruction(Op.BRANCH, ("remaining", 2)),
            Instruction(Op.HALT),
        )),
        "rehosted-process",
    )
    fd = _virtual_stream(machine)
    machine.run(max_ticks=5)
    assert machine.process(pid).status == "runnable"
    observe_headless_os_state(machine)
    start_state = machine.snapshot()
    identity = hashlib.sha256(_canonical(start_state)).hexdigest()

    # Independent reference performs the same state transitions without TCP.
    reference = HeadlessOS.from_snapshot(copy.deepcopy(start_state))
    assert reference.syscall(reference.environment.init_pid, "read", fd=fd, size=6) == b"queued"
    reference.run(max_ticks=8)
    reference.run(max_ticks=200)
    assert reference.process(pid).status == "exited"

    hop1 = _remote_step(start_state, identity=identity, revision=0, ticks=8, consume_fd=fd)
    assert hop1["virtual_io_hex"] == b"queued".hex()
    middle = HeadlessOS.from_snapshot(hop1["state"])
    assert middle.process(pid).status == "runnable"
    hop2 = _remote_step(hop1["state"], identity=identity, revision=1, ticks=200)
    assert hop1["worker_pid"] != hop2["worker_pid"]

    continuation = HeadlessOS.from_snapshot(hop2["state"])
    assert continuation.process(pid).status == "exited"
    assert continuation.process(pid).registers["remaining"] == 0
    assert continuation.environment.kernel.journal.verify()
    assert compare_headless_os_states(reference, continuation).equivalent


def test_stream_checksum_refuses_changed_payload_before_os_interpretation() -> None:
    """A mutated carrier payload cannot be interpreted as the transferred OS state."""
    valid = _frame({"schema": SCHEMA, "state": {"vm": {}}})
    corrupt = bytearray(valid)
    corrupt[-1] ^= 1
    with ExitStack() as stack:
        left, right = socket.socketpair()
        stack.enter_context(left)
        stack.enter_context(right)
        left.sendall(corrupt)
        with pytest.raises(ValueError, match="checksum"):
            _receive(right)


def test_stream_rejects_truncation_and_unbounded_envelopes() -> None:
    """Carrier fragmentation is allowed; missing and oversized bytes are not."""
    with ExitStack() as stack:
        left, right = socket.socketpair()
        stack.enter_context(left)
        stack.enter_context(right)
        left.sendall(struct.pack(">I", 5) + b"\0" * 32 + b"ab")
        left.shutdown(socket.SHUT_WR)
        with pytest.raises(ValueError, match="truncated"):
            _receive(right)
    with ExitStack() as stack:
        left, right = socket.socketpair()
        stack.enter_context(left)
        stack.enter_context(right)
        left.sendall(struct.pack(">I", MAX_FRAME + 1) + b"\0" * 32)
        with pytest.raises(ValueError, match="length"):
            _receive(right)


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] != "--worker":
        raise SystemExit("usage: test_stream_hosted_os.py --worker PORT")
    _worker(int(sys.argv[2]))
