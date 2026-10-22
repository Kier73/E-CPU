from __future__ import annotations

import pytest

from mailcpu import (
    HeadlessOS,
    HypervisorIntentRevisionWitness,
    HypervisorRequest,
    HypervisorRevisionProposal,
    IntentExample,
    IntentPrototypeModel,
    ReliabilityPolicy,
    ReliableChannel,
    ReplicatedMailboxNode,
    ReplicatedMailboxStore,
    ReplicatedRevisionProposalRelay,
    CrossHostRecoveryCoordinator,
    RecoveryCheckpoint,
    RecoveryCoordinatorError,
    SocketTransport,
)


MAILBOX = "recovery-intent-revisions"


def _proposal(source: str, operating_system: HeadlessOS) -> HypervisorRevisionProposal:
    """Mathematics: construct target-aware `P=(I,intent,M',W)` from held-out candidate predictions and current actions."""

    candidate = IntentPrototypeModel.fit(
        (
            IntentExample("network", {"operation": "receive network packet socket", "resource": "/network/remote"}),
            IntentExample("filesystem", {"operation": "read filesystem file", "resource": "/srv/data"}),
            IntentExample("service", {"operation": "restart service supervisor", "resource": "/service/worker"}),
        )
    )
    requests = (
        HypervisorRequest("receive network packet socket", "/network/remote", {"transport": "tcp"}),
        HypervisorRequest("read filesystem file", "/srv/data", {"path": "/srv/data"}),
    )
    witnesses = tuple(
        HypervisorIntentRevisionWitness.from_prediction(
            request,
            candidate.predict(request.state()),
            operating_system.hypervisor_decide(request),
        )
        for request in requests
    )
    return HypervisorRevisionProposal.from_candidate(
        source,
        "recovery-intent",
        1,
        44,
        candidate,
        witnesses,
        target="intent",
    )


def _tcp_pair() -> tuple[SocketTransport, SocketTransport]:
    """Mathematics: create one externally connected `P↔R` stream with distinct endpoint identities."""

    listener = SocketTransport.listen("127.0.0.1", 0)
    port = listener.getsockname()[1]
    primary = SocketTransport.connect("127.0.0.1", port, "P", "R")
    replica = SocketTransport.accept(listener, "R", "P")
    listener.close()
    return primary, replica


def test_external_recovery_reconnects_lost_ack_and_admits_one_intent_revision(tmp_path) -> None:
    """Mathematics: `apply_R(o,m)` and `deliver_R(s)` are idempotent after reconnect, while `admit(I)=1` remains single-valued."""

    primary_transport, replica_transport = _tcp_pair()
    policy = ReliabilityPolicy(lease_ticks=1, max_attempts=4, window_size=8)
    primary_channel = ReliableChannel(primary_transport, "P", "R", "recovery", policy)
    replica_channel = ReliableChannel(replica_transport, "R", "R", "recovery", policy, peer="P")
    primary = ReplicatedMailboxNode(
        ReplicatedMailboxStore(tmp_path / "primary.log", "P"),
        outbound={"R": primary_channel},
        quorum=2,
    )
    replica = ReplicatedMailboxNode(
        ReplicatedMailboxStore(tmp_path / "replica.log", "R"),
        inbound={"P": replica_channel},
    )
    remote = HeadlessOS()
    sender = ReplicatedRevisionProposalRelay(primary, MAILBOX)
    proposal = _proposal("P", remote)
    operation_id = sender.submit(proposal)
    try:
        assert replica.pending(MAILBOX) == 1
        assert primary_channel.pending_sequences() == (1,)
        primary_transport.close()

        primary_checkpoint = CrossHostRecoveryCoordinator.checkpoint(primary_transport, primary_channel, primary)
        replica_checkpoint = CrossHostRecoveryCoordinator.checkpoint(replica_transport, replica_channel, replica)
        replica_transport.close()

        rebound_primary, rebound_replica = _tcp_pair()
        restored_primary = CrossHostRecoveryCoordinator.rebind(
            primary_checkpoint,
            rebound_primary.socket,
            ReplicatedMailboxStore(tmp_path / "primary.log", "P"),
            direction="outbound",
            peer="R",
        )
        restored_replica = CrossHostRecoveryCoordinator.rebind(
            replica_checkpoint,
            rebound_replica.socket,
            ReplicatedMailboxStore(tmp_path / "replica.log", "R"),
            direction="inbound",
            peer="P",
            arbitration=remote.hypervisor_arbitration,
            mailbox=MAILBOX,
        )
        try:
            assert restored_primary.retry() == ()
            assert restored_replica.service() == 0
            primary_status = restored_primary.status(operation_id, mailbox=MAILBOX)
            assert primary_status.committed is True
            assert primary_status.pending_sequences == ()
            assert restored_replica.node.store.list(MAILBOX) == restored_primary.node.store.list(MAILBOX)
            assert len(restored_replica.node.store.list(MAILBOX)) == 1

            result = restored_replica.admit_next()
            assert result is not None
            assert result.target == "intent"
            assert result.admission.accepted is True
            assert remote.hypervisor.snapshot()["revision"] == 1
            replica_status = restored_replica.status(mailbox=MAILBOX)
            assert replica_status.semantic_admitted is True
            assert replica_status.mailbox_pending == 0
            assert restored_replica.admit_next() is None
            assert remote.environment.kernel.journal.verify()
            assert restored_replica.node.store.verify()
        finally:
            restored_primary.transport.close()
            restored_replica.transport.close()
    finally:
        if not primary_transport.closed:
            primary_transport.close()
        if not replica_transport.closed:
            replica_transport.close()


def test_recovery_checkpoint_roundtrip_and_direction_mismatch_fail_closed(tmp_path) -> None:
    """Mathematics: `decode(encode(C))=C`, while `direction ≠ direction(C)` is rejected before binding."""

    primary_transport, replica_transport = _tcp_pair()
    policy = ReliabilityPolicy(lease_ticks=1, max_attempts=2, window_size=2)
    primary_channel = ReliableChannel(primary_transport, "P", "R", "recovery-check", policy)
    primary = ReplicatedMailboxNode(
        ReplicatedMailboxStore(tmp_path / "primary.log", "P"),
        outbound={"R": primary_channel},
        quorum=2,
    )
    checkpoint = CrossHostRecoveryCoordinator.checkpoint(primary_transport, primary_channel, primary)
    assert RecoveryCheckpoint.from_snapshot(checkpoint.snapshot()).snapshot() == checkpoint.snapshot()
    primary_transport.close()
    replica_transport.close()

    rebound_primary, rebound_replica = _tcp_pair()
    try:
        with pytest.raises(RecoveryCoordinatorError, match="inbound channel identity"):
            CrossHostRecoveryCoordinator.rebind(
                checkpoint,
                rebound_primary.socket,
                ReplicatedMailboxStore(tmp_path / "primary.log", "P"),
                direction="inbound",
                peer="R",
            )
    finally:
        rebound_primary.close()
        rebound_replica.close()
