from __future__ import annotations

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

        primary_transport_snapshot = primary_transport.snapshot()
        primary_channel_snapshot = primary_channel.snapshot()
        primary_node_snapshot = primary.snapshot()
        replica_transport_snapshot = replica_transport.snapshot()
        replica_channel_snapshot = replica_channel.snapshot()
        replica_node_snapshot = replica.snapshot()
        replica_transport.close()

        rebound_primary, rebound_replica = _tcp_pair()
        restored_primary_transport = SocketTransport.from_snapshot(rebound_primary.socket, primary_transport_snapshot)
        restored_replica_transport = SocketTransport.from_snapshot(rebound_replica.socket, replica_transport_snapshot)
        restored_primary_channel = ReliableChannel.from_snapshot(primary_channel_snapshot, restored_primary_transport)
        restored_replica_channel = ReliableChannel.from_snapshot(replica_channel_snapshot, restored_replica_transport)
        restored_primary = ReplicatedMailboxNode.from_snapshot(
            primary_node_snapshot,
            ReplicatedMailboxStore(tmp_path / "primary.log", "P"),
            outbound={"R": restored_primary_channel},
        )
        restored_replica = ReplicatedMailboxNode.from_snapshot(
            replica_node_snapshot,
            ReplicatedMailboxStore(tmp_path / "replica.log", "R"),
            inbound={"P": restored_replica_channel},
        )
        try:
            assert restored_primary.tick() == ()
            assert restored_replica.service() == 0
            assert restored_primary.receipt(operation_id).committed is True
            assert restored_primary_channel.pending_sequences() == ()
            assert restored_replica.store.list(MAILBOX) == restored_primary.store.list(MAILBOX)
            assert len(restored_replica.store.list(MAILBOX)) == 1

            receiver = ReplicatedRevisionProposalRelay(
                restored_replica,
                MAILBOX,
                remote.hypervisor_arbitration,
            )
            result = receiver.receive_and_arbitrate()
            assert result is not None
            assert result.target == "intent"
            assert result.admission.accepted is True
            assert remote.hypervisor.snapshot()["revision"] == 1
            assert receiver.receive_and_arbitrate() is None
            assert remote.environment.kernel.journal.verify()
            assert restored_replica.store.verify()
        finally:
            restored_primary_transport.close()
            restored_replica_transport.close()
    finally:
        if not primary_transport.closed:
            primary_transport.close()
        if not replica_transport.closed:
            replica_transport.close()
