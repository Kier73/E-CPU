from __future__ import annotations

import pytest

from mailcpu.faults import FaultInjectingTransport, FaultProfile
from mailcpu.reliability import ReliabilityPolicy, ReliableChannel, ReliableChannelWouldBlock
from mailcpu.transport import InMemoryTransport


def test_reliable_channel_retries_a_dropped_frame_and_deduplicates() -> None:
    """Mathematics: verify at-least-once delivery `send(v)` reaches the receiver despite first-send loss and yields one payload."""

    transport = FaultInjectingTransport(FaultProfile(drop_indices=frozenset({1})))
    sender = ReliableChannel(
        transport,
        "sender",
        "receiver",
        "data",
        ReliabilityPolicy(lease_ticks=1, max_attempts=3),
    )
    receiver = ReliableChannel(
        transport,
        "receiver",
        "receiver",
        "data",
        ReliabilityPolicy(lease_ticks=1, max_attempts=3),
    )
    assert sender.send({"value": 9}) == 1
    assert receiver.receive() is None
    sender.tick()
    delivered = receiver.receive()
    assert delivered == (1, {"value": 9})
    assert sender.process_ack() == (1,)
    assert sender.pending_sequences() == ()


def test_reliable_channel_reports_bounded_failure() -> None:
    """Mathematics: after `max_attempts` erased transmissions, the pending sequence enters explicit failure set `F`."""

    transport = FaultInjectingTransport(
        FaultProfile(drop_indices=frozenset({1, 2, 3, 4, 5}))
    )
    sender = ReliableChannel(
        transport,
        "sender",
        "receiver",
        "data",
        ReliabilityPolicy(lease_ticks=1, max_attempts=3),
    )
    sender.send(123)
    assert sender.tick() == ()
    assert sender.tick() == ()
    assert sender.tick() == (1,)
    assert sender.failed_sequences == [1]
    assert sender.pending_sequences() == ()


def test_reliable_channel_deduplicates_duplicate_delivery() -> None:
    """Mathematics: duplicate frames share sequence `s`, so receiver delivery cardinality remains `|deliver(s)| = 1`."""

    transport = FaultInjectingTransport(FaultProfile(duplicate_indices=frozenset({1})))
    sender = ReliableChannel(transport, "sender", "receiver", "data")
    receiver = ReliableChannel(transport, "receiver", "receiver", "data")
    sender.send("once")
    assert receiver.receive() == (1, "once")
    assert receiver.receive() is None


def test_reliable_channel_snapshot_restores_pending_binary_state() -> None:
    """Mathematics: restoring `(P,D,F,t,next)` preserves acknowledgement continuation and binary payload identity."""

    transport = InMemoryTransport()
    sender = ReliableChannel(transport, "sender", "receiver", "data", ReliabilityPolicy(2, 3))
    assert sender.send({"blob": b"mailcpu"}) == 1
    snapshot = sender.snapshot()
    restored = ReliableChannel.from_snapshot(snapshot, transport)
    receiver = ReliableChannel(transport, "receiver", "receiver", "data", ReliabilityPolicy(2, 3))

    assert receiver.receive() == (1, {"blob": b"mailcpu"})
    assert restored.process_ack() == (1,)
    assert restored.pending_sequences() == ()
    assert restored.send("next") == 2

    invalid = dict(snapshot)
    invalid["next_sequence"] = 1
    try:
        ReliableChannel.from_snapshot(invalid, transport)
    except ValueError as exc:
        assert "next sequence" in str(exc)
    else:
        raise AssertionError("invalid next sequence was accepted")


def test_reliable_channel_and_fault_transport_resume_as_one_state() -> None:
    """Mathematics: restoring `(channel_state, transport_state)` preserves retry transition `tick;receive;ack` after a dropped first frame."""

    transport = FaultInjectingTransport(FaultProfile(drop_indices=frozenset({1})))
    sender = ReliableChannel(transport, "sender", "receiver", "data", ReliabilityPolicy(1, 3))
    sender.send({"value": 9})
    restored_transport = FaultInjectingTransport.from_snapshot(transport.snapshot())
    restored_sender = ReliableChannel.from_snapshot(sender.snapshot(), restored_transport)
    receiver = ReliableChannel(restored_transport, "receiver", "receiver", "data", ReliabilityPolicy(1, 3))

    assert restored_sender.tick() == ()
    assert receiver.receive() == (1, {"value": 9})
    assert restored_sender.process_ack() == (1,)
    assert restored_sender.pending_sequences() == ()


def test_reliable_channel_enforces_bounded_inflight_window_and_reopens_after_ack() -> None:
    """Mathematics: sender admission is `|P|<W`; an acknowledgement removes one `s∈P` and restores exactly one capacity slot."""

    transport = InMemoryTransport()
    sender = ReliableChannel(transport, "sender", "receiver", "data", ReliabilityPolicy(3, 2, 2))
    receiver = ReliableChannel(transport, "receiver", "receiver", "data")
    assert sender.send("first") == 1
    assert sender.send("second") == 2
    assert sender.available_window == 0
    with pytest.raises(ReliableChannelWouldBlock, match="window is full"):
        sender.send("third")
    assert receiver.receive() == (1, "first")
    assert receiver.receive() == (2, "second")
    assert sender.process_ack() == (1, 2)
    assert sender.available_window == 2
    assert sender.send("third") == 3


def test_reliable_channel_failed_sequence_releases_window_slot() -> None:
    """Mathematics: when retry budget classifies `s` as failed, `P:=P\\{s}` and the bounded window admits the next sequence."""

    transport = FaultInjectingTransport(FaultProfile(drop_indices=frozenset({1, 2})))
    sender = ReliableChannel(transport, "sender", "receiver", "data", ReliabilityPolicy(1, 1, 1))
    assert sender.send("lost") == 1
    with pytest.raises(ReliableChannelWouldBlock):
        sender.send("blocked")
    assert sender.tick() == (1,)
    assert sender.available_window == 1
    assert sender.send("next") == 2


def test_reliable_channel_snapshot_preserves_window_admission() -> None:
    """Mathematics: checkpoint preserves `W` and `|P|`, so restored admission equals the pre-checkpoint residual capacity."""

    transport = InMemoryTransport()
    sender = ReliableChannel(transport, "sender", "receiver", "data", ReliabilityPolicy(2, 3, 2))
    sender.send(b"one")
    sender.send(b"two")
    restored = ReliableChannel.from_snapshot(sender.snapshot(), transport)
    assert restored.available_window == 0
    with pytest.raises(ReliableChannelWouldBlock):
        restored.send(b"three")
    invalid = sender.snapshot()
    invalid["policy"]["window_size"] = 1
    with pytest.raises(ValueError, match="exceed reliable channel window"):
        ReliableChannel.from_snapshot(invalid, transport)
