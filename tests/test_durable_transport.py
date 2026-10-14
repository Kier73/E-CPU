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
    receiver = ReliableChannel(receiver_transport, "B", "B", "data")
    assert receiver.receive() == (sequence, b"payload")
    sender_after_restore = ReliableChannel.from_snapshot(sender_snapshot, receiver_transport)
    assert sender_after_restore.process_ack() == (sequence,)
    assert sender_after_restore.pending_sequences() == ()
