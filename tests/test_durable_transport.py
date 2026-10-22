from __future__ import annotations

import json

import pytest

from mailcpu import DurableMailboxTransport, DurableTransportError, Message, ReliabilityPolicy, ReliableChannel


def test_durable_mailbox_replays_binary_messages_and_destructive_events(tmp_path) -> None:
    """Mathematics: durable `ENQUEUE`, `DEQUEUE`, and `CONSUME` replay to the same FIFO product `Q` and identity map `L` after reopen."""

    path = tmp_path / "mailbox.log"
    transport = DurableMailboxTransport(path)
    first = transport.send(
        "inbox",
        Message(sender="a", op="DATA", body=(b"\x00\xff", {"value": (1, 2)})),
    )
    second = transport.send("inbox", Message(sender="b", op="DATA", body=(b"second",)))
    assert transport.verify()
    restored = DurableMailboxTransport(path)
    assert restored.list("inbox") == (first, second)
    assert restored.consume(second) is True
    assert restored.poll("inbox") == first
    assert restored.pending("inbox") == 0
    assert DurableMailboxTransport(path).pending() == 0


def test_durable_mailbox_recovers_only_an_incomplete_final_append(tmp_path) -> None:
    """Mathematics: a torn suffix `R_partial` is truncated, while every complete prefix record remains hash-chain verified."""

    path = tmp_path / "recover.log"
    transport = DurableMailboxTransport(path)
    message = transport.send("inbox", Message(sender="a", op="DATA", value=7))
    with path.open("ab") as stream:
        stream.write(b'{"version":1,"sequence":999')
    recovered = DurableMailboxTransport(path)
    assert recovered.list("inbox") == (message,)
    assert recovered.verify()
    assert path.read_bytes().endswith(b"\n")


def test_durable_verify_does_not_repair_or_mutate_torn_log(tmp_path) -> None:
    r"""Mathematics: verification is a pure predicate `V(path)∈{True,False}` and never applies repair transition `R` to bytes."""

    path = tmp_path / "verify.log"
    transport = DurableMailboxTransport(path)
    transport.send("inbox", Message(sender="a", op="DATA", value=7))
    with path.open("ab") as stream:
        stream.write(b'{"version":1,"sequence":999')
    before = path.read_bytes()

    assert transport.verify() is False
    assert path.read_bytes() == before


def test_durable_lock_metadata_is_constant_size(tmp_path) -> None:
    r"""Mathematics: lock metadata size remains `|lock|=1` under repeated serialized commits."""

    path = tmp_path / "lock.log"
    transport = DurableMailboxTransport(path)
    for index in range(5):
        transport.send("inbox", Message(sender="a", op="DATA", value=index))
    assert path.with_name("lock.log.lock").stat().st_size == 1


def test_durable_mailbox_rejects_tampered_complete_records(tmp_path) -> None:
    """Mathematics: changing any complete record breaks `H_i=SHA256(H_{i-1}||R_i)` and must refuse replay."""

    path = tmp_path / "tamper.log"
    DurableMailboxTransport(path).send("inbox", Message(sender="a", op="DATA", value=7))
    record = json.loads(path.read_text(encoding="utf-8"))
    record["receipt"] = "00" * 32
    path.write_text(json.dumps(record, separators=(",", ":")) + "\n", encoding="utf-8")
    with pytest.raises(DurableTransportError, match="receipt"):
        DurableMailboxTransport(path)


def test_reliable_channel_continues_across_durable_transport_reopen(tmp_path) -> None:
    r"""Mathematics: durable delivery and acknowledgement preserve `P\{s}` after sender/receiver reconstruction across a transport reopen."""

    path = tmp_path / "reliable.log"
    sender_transport = DurableMailboxTransport(path)
    sender = ReliableChannel(sender_transport, "A", "B", "data", ReliabilityPolicy(3, 2))
    sequence = sender.send(b"payload")
    sender_snapshot = sender.snapshot()
    receiver_transport = DurableMailboxTransport(path)
    receiver = ReliableChannel(receiver_transport, "B", "B", "data", peer="A")
    assert receiver.receive() == (sequence, b"payload")
    sender_after_restore = ReliableChannel.from_snapshot(sender_snapshot, receiver_transport)
    assert sender_after_restore.process_ack() == (sequence,)
    assert sender_after_restore.pending_sequences() == ()


def test_reliable_channel_recovers_enqueue_committed_after_channel_snapshot(tmp_path) -> None:
    r"""Mathematics: when `enqueue(F_s)` precedes snapshot persistence, restore reconstructs `s∈P` and advances `next=max(next,s+1)`."""

    path = tmp_path / "crash-window.log"
    transport = DurableMailboxTransport(path)
    channel = ReliableChannel(transport, "A", "B", "data")
    snapshot = channel.snapshot()
    transport.send(
        "B",
        Message(
            sender="A",
            recipient="B",
            op="RDATA",
            addr="B",
            body=("data", 1, b"committed-before-snapshot"),
        ),
    )

    restored = ReliableChannel.from_snapshot(snapshot, DurableMailboxTransport(path))
    assert restored.pending_sequences() == (1,)
    assert restored.send(b"next") == 2


def test_reliable_channel_rejects_conflicting_queued_payload_on_restore(tmp_path) -> None:
    r"""Mathematics: equal sequence labels require equal protocol identity `I(F_1)`; a payload conflict violates single-valued state."""

    path = tmp_path / "conflict.log"
    transport = DurableMailboxTransport(path)
    channel = ReliableChannel(transport, "A", "B", "data")
    channel.send(b"expected")
    snapshot = channel.snapshot()
    assert transport.poll("B") is not None
    transport.send(
        "B",
        Message(
            sender="A",
            recipient="B",
            op="RDATA",
            addr="B",
            body=("data", 1, b"conflicting"),
        ),
    )

    with pytest.raises(ValueError, match="conflicts with restored pending state"):
        ReliableChannel.from_snapshot(snapshot, DurableMailboxTransport(path))


def test_reliable_channel_rejects_queued_frame_for_failed_sequence(tmp_path) -> None:
    r"""Mathematics: a sequence cannot be both queued and failed, so `s∈Q ∧ s∈F` is rejected as a contradiction."""

    path = tmp_path / "failed-contradiction.log"
    transport = DurableMailboxTransport(path)
    channel = ReliableChannel(
        transport,
        "A",
        "B",
        "data",
        ReliabilityPolicy(lease_ticks=1, max_attempts=1),
    )
    channel.send(b"not-deliverable")
    assert channel.tick() == (1,)
    snapshot = channel.snapshot()

    with pytest.raises(ValueError, match="contradicts delivered or failed state"):
        ReliableChannel.from_snapshot(snapshot, DurableMailboxTransport(path))


def test_reliable_channel_reconciliation_leaves_unrelated_mailbox_traffic_untouched(tmp_path) -> None:
    r"""Mathematics: reconciliation is a projection onto exact channel identity, so `Q_other` is invariant under restore."""

    path = tmp_path / "unrelated.log"
    transport = DurableMailboxTransport(path)
    channel = ReliableChannel(transport, "A", "B", "data")
    snapshot = channel.snapshot()
    unrelated = transport.send(
        "B",
        Message(
            sender="other",
            recipient="B",
            op="RDATA",
            addr="B",
            body=("other-channel", 1, b"keep"),
        ),
    )

    ReliableChannel.from_snapshot(snapshot, DurableMailboxTransport(path))
    assert DurableMailboxTransport(path).list("B") == (unrelated,)
