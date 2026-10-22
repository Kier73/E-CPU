from __future__ import annotations

from dataclasses import replace

import pytest

from mailcpu import (
    CrossHostMultiPeerRecoveryCoordinator,
    CrossHostRecoveryCoordinator,
    Message,
    MultiPeerRecoveryCheckpoint,
    RecoveryCoordinatorError,
    ReliabilityPolicy,
    ReliableChannel,
    ReplicatedMailboxNode,
    ReplicatedMailboxStore,
    SocketTransport,
)


MAILBOX = "multi-peer-recovery"


def _tcp_pair(peer: str) -> tuple[SocketTransport, SocketTransport]:
    """Mathematics: create one actual AF_INET stream pair with `P→peer` and `peer→P` endpoint identities."""

    listener = SocketTransport.listen("127.0.0.1", 0)
    port = listener.getsockname()[1]
    primary = SocketTransport.connect("127.0.0.1", port, "P", peer)
    replica = SocketTransport.accept(listener, peer, "P")
    listener.close()
    return primary, replica


def _close(*transports: SocketTransport) -> None:
    """Mathematics: apply the idempotent terminal transition `closed:=True` to every supplied stream."""

    for transport in transports:
        transport.close()


def test_multi_peer_recovery_rebinds_lost_ack_and_preserves_quorum_state(tmp_path) -> None:
    """Mathematics: with `q=3`, one checkpointed ACK gives `1+|A|=2<3`, then duplicate replay of the lost peer gives `1+|A|=3` once."""

    primary_b, replica_b = _tcp_pair("B")
    primary_c, replica_c = _tcp_pair("C")
    policy = ReliabilityPolicy(lease_ticks=1, max_attempts=4, window_size=4)
    channel_b = ReliableChannel(primary_b, "P", "B", "multi-recovery", policy)
    channel_c = ReliableChannel(primary_c, "P", "C", "multi-recovery", policy)
    replica_channel_b = ReliableChannel(replica_b, "B", "B", "multi-recovery", policy, peer="P")
    replica_channel_c = ReliableChannel(replica_c, "C", "C", "multi-recovery", policy, peer="P")
    primary = ReplicatedMailboxNode(
        ReplicatedMailboxStore(tmp_path / "primary.log", "P"),
        outbound={"B": channel_b, "C": channel_c},
        quorum=3,
    )
    node_b = ReplicatedMailboxNode(
        ReplicatedMailboxStore(tmp_path / "b.log", "B"),
        inbound={"P": replica_channel_b},
    )
    node_c = ReplicatedMailboxNode(
        ReplicatedMailboxStore(tmp_path / "c.log", "C"),
        inbound={"P": replica_channel_c},
    )
    restored_primary: CrossHostMultiPeerRecoveryCoordinator | None = None
    restored_b: CrossHostRecoveryCoordinator | None = None
    restored_c: CrossHostRecoveryCoordinator | None = None
    new_primary_b: SocketTransport | None = None
    new_primary_c: SocketTransport | None = None
    new_replica_b: SocketTransport | None = None
    new_replica_c: SocketTransport | None = None
    try:
        message = primary.send(MAILBOX, Message(sender="P", recipient=MAILBOX, op="DATA", body=("payload",)))
        operation_id = primary.operation_ids()[0]
        assert primary.receipt(operation_id).committed is False
        assert node_b.list(MAILBOX) == (message,)
        assert node_c.list(MAILBOX) == (message,)

        primary_b.close()
        primary_checkpoint = CrossHostMultiPeerRecoveryCoordinator.checkpoint(
            {"B": primary_b, "C": primary_c},
            {"B": channel_b, "C": channel_c},
            primary,
            {"B": "outbound", "C": "outbound"},
        )
        checkpoint_roundtrip = MultiPeerRecoveryCheckpoint.from_snapshot(primary_checkpoint.snapshot())
        assert checkpoint_roundtrip.snapshot() == primary_checkpoint.snapshot()
        checkpoint_b = CrossHostRecoveryCoordinator.checkpoint(replica_b, replica_channel_b, node_b)
        checkpoint_c = CrossHostRecoveryCoordinator.checkpoint(replica_c, replica_channel_c, node_c)
        _close(primary_c, replica_b, replica_c)

        new_primary_b, new_replica_b = _tcp_pair("B")
        new_primary_c, new_replica_c = _tcp_pair("C")
        restored_primary = CrossHostMultiPeerRecoveryCoordinator.rebind(
            primary_checkpoint,
            {"B": new_primary_b.socket, "C": new_primary_c.socket},
            ReplicatedMailboxStore(tmp_path / "primary.log", "P"),
        )
        restored_b = CrossHostRecoveryCoordinator.rebind(
            checkpoint_b,
            new_replica_b.socket,
            ReplicatedMailboxStore(tmp_path / "b.log", "B"),
            direction="inbound",
            peer="P",
        )
        restored_c = CrossHostRecoveryCoordinator.rebind(
            checkpoint_c,
            new_replica_c.socket,
            ReplicatedMailboxStore(tmp_path / "c.log", "C"),
            direction="inbound",
            peer="P",
        )

        partial = restored_primary.status(operation_id)
        assert partial.acknowledged_peers == ("C",)
        assert partial.pending_sequences == {"B": (1,), "C": ()}
        assert partial.committed is False

        assert restored_primary.retry() == ()
        assert restored_b.service() == 0
        assert restored_c.service() == 0
        final = restored_primary.status(operation_id)
        assert final.acknowledged_peers == ("B", "C")
        assert final.pending_sequences == {"B": (), "C": ()}
        assert final.committed is True
        assert restored_b.node.store.list(MAILBOX) == (message,)
        assert restored_c.node.store.list(MAILBOX) == (message,)
        assert restored_b.node.store.verify()
        assert restored_c.node.store.verify()
    finally:
        if restored_primary is not None:
            restored_primary.transports["B"].close()
            restored_primary.transports["C"].close()
        if restored_b is not None:
            restored_b.transport.close()
        if restored_c is not None:
            restored_c.transport.close()
        _close(primary_b, primary_c, replica_b, replica_c)
        if new_primary_b is not None:
            new_primary_b.close()
        if new_primary_c is not None:
            new_primary_c.close()
        if new_replica_b is not None:
            new_replica_b.close()
        if new_replica_c is not None:
            new_replica_c.close()


def test_multi_peer_recovery_rejects_direction_mismatch_before_binding(tmp_path) -> None:
    """Mathematics: replacing `d_peer=outbound` with `inbound` violates the channel identity relation and yields no binding."""

    primary_b, replica_b = _tcp_pair("B")
    policy = ReliabilityPolicy(lease_ticks=1, max_attempts=2, window_size=2)
    channel_b = ReliableChannel(primary_b, "P", "B", "multi-check", policy)
    primary = ReplicatedMailboxNode(
        ReplicatedMailboxStore(tmp_path / "primary.log", "P"),
        outbound={"B": channel_b},
        quorum=2,
    )
    checkpoint = CrossHostMultiPeerRecoveryCoordinator.checkpoint(
        {"B": primary_b},
        {"B": channel_b},
        primary,
        {"B": "outbound"},
    )
    bad_factor = replace(checkpoint.peers[0], direction="inbound")
    bad_checkpoint = MultiPeerRecoveryCheckpoint(checkpoint.node, (bad_factor,))
    rebound_primary, rebound_replica = _tcp_pair("B")
    try:
        with pytest.raises(RecoveryCoordinatorError, match="channel identity mismatch"):
            CrossHostMultiPeerRecoveryCoordinator.rebind(
                bad_checkpoint,
                {"B": rebound_primary.socket},
                ReplicatedMailboxStore(tmp_path / "primary.log", "P"),
            )
    finally:
        _close(primary_b, replica_b, rebound_primary, rebound_replica)
