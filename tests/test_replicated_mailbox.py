from __future__ import annotations

import socket
from pathlib import Path
import subprocess
import sys

import pytest

from mailcpu import (
    Message,
    ReliabilityPolicy,
    ReliableChannel,
    ReplicatedMailboxError,
    ReplicatedMailboxNode,
    ReplicatedMailboxStore,
    SocketTransport,
)
from mailcpu.replicated_mailbox import _message_to_record


def test_replicated_store_replays_typed_fifo_and_allocates_after_restart(tmp_path) -> None:
    """Mathematics: verify journal replay preserves `Q_addr` and chooses fresh `m_{n+1}` after reopen."""

    path = tmp_path / "node-a.log"
    store = ReplicatedMailboxStore(path, "A")
    first = store.send("inbox", Message(sender="A", op="DATA", body=(b"bytes", (1, 2))))
    assert store.list("inbox") == (first,)
    restored = ReplicatedMailboxStore(path, "A")
    assert restored.verify()
    assert restored.list("inbox") == (first,)
    second = restored.send("inbox", Message(sender="A", op="DATA", body=(b"second",)))
    assert second.message_id == "A:msg:2"
    assert restored.list("inbox") == (first, second)


def test_replicated_store_repairs_only_torn_final_suffix(tmp_path) -> None:
    """Mathematics: truncate only incomplete `R_partial` while preserving every complete hash-chain prefix record."""

    path = tmp_path / "repair.log"
    store = ReplicatedMailboxStore(path, "A")
    message = store.send("inbox", Message(sender="A", op="DATA", value=7))
    with path.open("ab") as stream:
        stream.write(b'{"version":1,"sequence":999')
    recovered = ReplicatedMailboxStore(path, "A")
    assert recovered.list("inbox") == (message,)
    assert recovered.verify()
    assert path.read_bytes().endswith(b"\n")


def test_replicated_store_rejects_operation_identity_conflict(tmp_path) -> None:
    """Mathematics: require operation identity to be single-valued, so `I(o)=x ∧ I(o)=y ∧ x≠y` refuses."""

    store = ReplicatedMailboxStore(tmp_path / "conflict.log", "B")
    first = {"addr": "inbox", "message": _message_to_record(Message(sender="A", recipient="inbox", op="DATA", body=(1,), message_id="A:msg:1"))}
    store.apply_replica("A:op:1", "enqueue", first)
    conflicting = {"addr": "inbox", "message": _message_to_record(Message(sender="A", recipient="inbox", op="DATA", body=(2,), message_id="A:msg:2"))}
    with pytest.raises(ReplicatedMailboxError, match="conflict"):
        store.apply_replica("A:op:1", "enqueue", conflicting)
    assert len(store.list("inbox")) == 1


def test_replication_reaches_quorum_and_replays_dequeue_over_tcp(tmp_path) -> None:
    """Mathematics: verify local commit plus one durable peer ACK satisfies `1+|A(o)|≥q=2` and FIFO removal converges."""

    left, right = socket.socketpair()
    primary_transport = SocketTransport(left, "P", "R")
    replica_transport = SocketTransport(right, "R", "P")
    primary_channel = ReliableChannel(primary_transport, "P", "R", "replication", ReliabilityPolicy(1, 3))
    replica_channel = ReliableChannel(replica_transport, "R", "R", "replication", ReliabilityPolicy(1, 3), peer="P")
    primary = ReplicatedMailboxNode(
        ReplicatedMailboxStore(tmp_path / "primary.log", "P"),
        outbound={"R": primary_channel},
        quorum=2,
    )
    replica = ReplicatedMailboxNode(
        ReplicatedMailboxStore(tmp_path / "replica.log", "R"),
        inbound={"P": replica_channel},
    )
    try:
        message = primary.send("inbox", Message(sender="P", op="DATA", body=(b"remote", {"x": (1, 2)})))
        operation = primary.operation_ids()[0]
        assert primary.receipt(operation).committed is False
        assert replica.list("inbox") == (message,)
        assert primary.receipt(operation).committed is True
        assert primary.store.list("inbox") == replica.store.list("inbox")
        assert primary.poll("inbox") == message
        dequeue_operation = primary.operation_ids()[-1]
        assert replica.list("inbox") == ()
        assert primary.receipt(dequeue_operation).committed is True
    finally:
        primary_transport.close()
        replica_transport.close()


def test_lost_ack_retransmission_is_idempotent_at_replica(tmp_path) -> None:
    """Mathematics: lost `ACK(s)` causes retransmission, while equal operation identity leaves replica state single-valued."""

    left, right = socket.socketpair()
    primary_transport = SocketTransport(left, "P", "R")
    replica_transport = SocketTransport(right, "R", "P")
    primary_channel = ReliableChannel(primary_transport, "P", "R", "replication", ReliabilityPolicy(1, 3))
    replica_channel = ReliableChannel(replica_transport, "R", "R", "replication", ReliabilityPolicy(1, 3), peer="P")
    primary = ReplicatedMailboxNode(ReplicatedMailboxStore(tmp_path / "p.log", "P"), outbound={"R": primary_channel}, quorum=2)
    replica = ReplicatedMailboxNode(ReplicatedMailboxStore(tmp_path / "r.log", "R"), inbound={"P": replica_channel})
    try:
        message = primary.send("inbox", Message(sender="P", op="DATA", value=9))
        operation = primary.operation_ids()[0]
        assert replica.list("inbox") == (message,)
        assert primary.tick() == ()
        assert replica.list("inbox") == (message,)
        assert primary.receipt(operation).committed is True
        assert len(replica.store.list("inbox")) == 1
    finally:
        primary_transport.close()
        replica_transport.close()


def test_replica_process_loss_after_durable_apply_replays_one_operation(tmp_path) -> None:
    """Mathematics: after replica `fsync(ENQUEUE(o,m))` and before ACK, restart preserves `Q=[m]` and replay is idempotent."""

    journal_path = tmp_path / "replica-crash.log"
    child = r'''# Mathematics: durably apply one replicated FIFO event, then stop before any ACK or interpreter cleanup.
import os
import sys
from pathlib import Path
from mailcpu import Message, ReplicatedMailboxStore
from mailcpu.replicated_mailbox import _message_to_record

store = ReplicatedMailboxStore(Path(sys.argv[1]), "R")
message = Message(
    sender="P", recipient="inbox", op="DATA", value=9, message_id="P:msg:1"
)
store.apply_replica(
    "P:op:1",
    "enqueue",
    {"addr": "inbox", "message": _message_to_record(message)},
)
os._exit(29)
'''
    process = subprocess.run(
        [sys.executable, "-c", child, str(journal_path)],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert process.returncode == 29, process.stderr

    recovered = ReplicatedMailboxStore(journal_path, "R")
    message = Message(sender="P", recipient="inbox", op="DATA", value=9, message_id="P:msg:1")
    payload = {"addr": "inbox", "message": _message_to_record(message)}
    assert recovered.list("inbox") == (message,)
    assert recovered.apply_replica("P:op:1", "enqueue", payload) is False
    assert recovered.list("inbox") == (message,)
    assert recovered.verify()


def test_reliable_commit_callback_runs_before_dequeue_and_ack() -> None:
    """Mathematics: for new `s`, `commit(s)` precedes `Q:=Q\\{F_s}` and `ACK(s)` in the receive transition."""

    from mailcpu import InMemoryTransport

    transport = InMemoryTransport()
    channel = ReliableChannel(transport, "B", "B", "data", peer="A")
    frame = transport.send("B", Message(sender="A", recipient="B", addr="B", op="RDATA", body=("data", 1, b"x")))
    observations: list[tuple[int, bool, bool]] = []

    def commit(sequence: int, payload: object) -> None:
        """Mathematics: observe pre-commit state `F_s∈Q` and absent acknowledgement `ACK(s)∉Q_ack`."""

        del payload
        observations.append((sequence, frame in transport.list("B"), not transport.list(channel.ack_address)))

    assert channel.receive(commit=commit) == (1, b"x")
    assert observations == [(1, True, True)]
