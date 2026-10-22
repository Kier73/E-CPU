from __future__ import annotations

from dataclasses import replace

import pytest

from mailcpu import (
    CrossTransportRecoveryCoordinator,
    DEFAULT_CHECKPOINT_KIND,
    InMemoryTransport,
    RecoveryPolicyOffer,
    RecoveryPolicyAgreement,
    ReliabilityPolicy,
    ReliableChannel,
    SocketTransport,
    TransportMigrationCheckpoint,
    TransportMigrationError,
    advertise_recovery_policy,
    negotiate_recovery_policy,
)


def _tcp_pair() -> tuple[SocketTransport, SocketTransport]:
    """Mathematics: create reciprocal AF_INET streams `T_origin↔T_receiver` for source-state capture."""

    listener = SocketTransport.listen("127.0.0.1", 0)
    port = listener.getsockname()[1]
    origin = SocketTransport.connect("127.0.0.1", port, "origin", "receiver")
    receiver = SocketTransport.accept(listener, "receiver", "origin")
    listener.close()
    return origin, receiver


def _agreement() -> RecoveryPolicyAgreement:
    """Mathematics: construct `G=O∩A` for the socket-to-memory migration boundary."""

    policy = ReliabilityPolicy(lease_ticks=1, max_attempts=3, window_size=4)
    advertisement = advertise_recovery_policy(
        checkpoint_kinds=(DEFAULT_CHECKPOINT_KIND,),
        transport_kinds=("memory", "socket"),
        max_window_size=2,
        min_lease_ticks=2,
        max_attempts=2,
        allow_cross_transport=True,
        supports_effect_ledger=True,
    )
    offer = RecoveryPolicyOffer(1, DEFAULT_CHECKPOINT_KIND, "socket", "memory", policy, True)
    return negotiate_recovery_policy(offer, advertisement)


def test_socket_channel_migrates_to_shared_memory_and_completes_original_fifo() -> None:
    r"""Mathematics: `restore(R,Q_socket)→R_memory` preserves sequence `s=1`, payload, one delivery, and `P\{1}` after ACK."""

    origin_transport, receiver_transport = _tcp_pair()
    policy = ReliabilityPolicy(lease_ticks=1, max_attempts=3, window_size=4)
    sender = ReliableChannel(origin_transport, "origin", "receiver", "migration", policy)
    receiver = ReliableChannel(receiver_transport, "receiver", "receiver", "migration", policy, peer="origin")
    agreement = _agreement()
    try:
        assert sender.send({"value": "active", "energy": 7}) == 1
        assert receiver_transport.list("receiver")
        receiver_checkpoint = CrossTransportRecoveryCoordinator.checkpoint(
            receiver_transport,
            receiver,
            agreement,
        )
        sender_checkpoint = CrossTransportRecoveryCoordinator.checkpoint(
            origin_transport,
            sender,
            agreement,
        )
        assert TransportMigrationCheckpoint.from_snapshot(receiver_checkpoint.snapshot()).snapshot() == receiver_checkpoint.snapshot()
        assert TransportMigrationCheckpoint.from_snapshot(sender_checkpoint.snapshot()).snapshot() == sender_checkpoint.snapshot()
    finally:
        origin_transport.close()
        receiver_transport.close()

    target = InMemoryTransport()
    migrated_receiver = CrossTransportRecoveryCoordinator.migrate(receiver_checkpoint, agreement, target)
    migrated_sender = CrossTransportRecoveryCoordinator.migrate(sender_checkpoint, agreement, target)
    assert migrated_sender.pending_sequences() == (1,)
    assert migrated_receiver.next_receive_sequence == 1
    assert target.pending("receiver") == 1
    received = migrated_receiver.receive()
    assert received == (1, {"value": "active", "energy": 7})
    assert migrated_sender.process_ack() == (1,)
    assert migrated_sender.pending_sequences() == ()
    assert migrated_receiver.next_receive_sequence == 2
    assert target.pending("receiver") == 0


def test_cross_transport_migration_refuses_mismatched_agreement_without_target_mutation() -> None:
    """Mathematics: `fingerprint(A_checkpoint)≠fingerprint(A_supplied)` implies refusal and `Q_target'=Q_target`."""

    origin_transport, receiver_transport = _tcp_pair()
    policy = ReliabilityPolicy(window_size=2)
    sender = ReliableChannel(origin_transport, "origin", "receiver", "migration-refuse", policy)
    agreement = _agreement()
    try:
        sender.send({"value": "held"})
        checkpoint = CrossTransportRecoveryCoordinator.checkpoint(origin_transport, sender, agreement)
    finally:
        origin_transport.close()
        receiver_transport.close()
    target = InMemoryTransport()
    before = target.snapshot()
    mismatched = replace(agreement, target_transport="socket")
    with pytest.raises(TransportMigrationError, match="agreement"):
        CrossTransportRecoveryCoordinator.migrate(checkpoint, mismatched, target)
    assert target.snapshot() == before

def test_cross_transport_migration_refuses_target_substrate_before_import() -> None:
    """Mathematics: `kind(T_target)≠agreement.target_transport` implies refusal before `Q_target` changes."""

    origin_transport, receiver_transport = _tcp_pair()
    policy = ReliabilityPolicy(window_size=2)
    sender = ReliableChannel(origin_transport, "origin", "receiver", "migration-target", policy)
    agreement = _agreement()
    try:
        checkpoint = CrossTransportRecoveryCoordinator.checkpoint(origin_transport, sender, agreement)
    finally:
        origin_transport.close()
        receiver_transport.close()
    target_transport, target_peer = _tcp_pair()
    try:
        before = target_transport.snapshot()
        with pytest.raises(TransportMigrationError, match="target transport"):
            CrossTransportRecoveryCoordinator.migrate(checkpoint, agreement, target_transport)
        assert target_transport.snapshot() == before
    finally:
        target_transport.close()
        target_peer.close()


def test_cross_transport_migration_preflights_channel_before_import() -> None:
    """Mathematics: invalid `R_checkpoint` implies refusal before `Q_target` changes, even for an in-memory checkpoint object."""

    origin_transport, receiver_transport = _tcp_pair()
    policy = ReliabilityPolicy(window_size=2)
    sender = ReliableChannel(origin_transport, "origin", "receiver", "migration-preflight", policy)
    agreement = _agreement()
    try:
        sender.send({"value": "held"})
        checkpoint = CrossTransportRecoveryCoordinator.checkpoint(origin_transport, sender, agreement)
    finally:
        origin_transport.close()
        receiver_transport.close()

    target = InMemoryTransport()
    before = target.snapshot()
    invalid = TransportMigrationCheckpoint(
        checkpoint.source_transport_kind,
        checkpoint.target_transport_kind,
        {"version": 999},
        checkpoint.queued_messages,
        checkpoint.agreement,
    )
    with pytest.raises(TransportMigrationError, match="preflight"):
        CrossTransportRecoveryCoordinator.migrate(invalid, agreement, target)
    assert target.snapshot() == before

