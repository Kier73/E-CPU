from __future__ import annotations

import socket

import pytest

from mailcpu import (
    HeadlessOS,
    HypervisorError,
    HypervisorRequest,
    HypervisorRevisionProposal,
    HypervisorRevisionRelayError,
    HypervisorRevisionWitness,
    Message,
    ProceduralDecisionModel,
    ReliabilityPolicy,
    ReliableChannel,
    ReplicatedMailboxNode,
    ReplicatedMailboxStore,
    ReplicatedRevisionProposalRelay,
    SocketTransport,
)
from mailcpu.replicated_mailbox import _message_to_record
from mailcpu.revision_transport import REVISION_PROPOSAL_KIND


MAILBOX = "hypervisor-revisions"


def _proposal(source: str, sequence: int, logical_time: int) -> HypervisorRevisionProposal:
    """Mathematics: construct `P=(source,channel,sequence,time,m',W)` from one live revision-0 policy witness."""

    operating_system = HeadlessOS()
    request = HypervisorRequest(
        "read filesystem file path descriptor",
        "/home/file",
        {"path": "/home/file"},
        frozenset({"read"}),
        frozenset({"read"}),
    )
    decision = operating_system.hypervisor_decide(request)
    candidate = ProceduralDecisionModel.from_snapshot(operating_system.hypervisor.classifier.snapshot())
    return HypervisorRevisionProposal.from_candidate(
        source,
        "revisions",
        sequence,
        logical_time,
        candidate,
        (HypervisorRevisionWitness.from_decision(request, decision),),
    )


def _replicated_pair(tmp_path):
    """Mathematics: construct two durable nodes `P↔R` over one framed reliable channel with quorum `q=2`."""

    left, right = socket.socketpair()
    primary_transport = SocketTransport(left, "P", "R")
    replica_transport = SocketTransport(right, "R", "P")
    policy = ReliabilityPolicy(lease_ticks=1, max_attempts=3)
    primary_channel = ReliableChannel(primary_transport, "P", "R", "revision-replication", policy)
    replica_channel = ReliableChannel(
        replica_transport,
        "R",
        "R",
        "revision-replication",
        policy,
        peer="P",
    )
    primary = ReplicatedMailboxNode(
        ReplicatedMailboxStore(tmp_path / "primary.log", "P"),
        outbound={"R": primary_channel},
        quorum=2,
    )
    replica = ReplicatedMailboxNode(
        ReplicatedMailboxStore(tmp_path / "replica.log", "R"),
        inbound={"P": replica_channel},
    )
    return primary, replica, primary_transport, replica_transport


def test_replicated_revision_relay_preserves_fifo_quorum_and_restart(tmp_path) -> None:
    """Mathematics: `ENQUEUE(P1);ENQUEUE(P2)` persists before ACK, restores, then `RSI(P1);CONSUME(P1);RSI(P2);CONSUME(P2)` in order."""

    primary, replica, primary_transport, replica_transport = _replicated_pair(tmp_path)
    primary_relay = ReplicatedRevisionProposalRelay(primary, MAILBOX)
    proposal_one = _proposal("P", 1, 11)
    proposal_two = _proposal("P", 2, 12)
    try:
        operation_one = primary_relay.submit(proposal_one)
        operation_two = primary_relay.submit(proposal_two)
        assert replica.pending(MAILBOX) == 2
        assert primary_relay.receipt(operation_one).committed is True
        assert primary_relay.receipt(operation_two).committed is True

        restored_store = ReplicatedMailboxStore(tmp_path / "replica.log", "R")
        restored_node = ReplicatedMailboxNode(restored_store)
        remote = HeadlessOS()
        restored_relay = ReplicatedRevisionProposalRelay(
            restored_node,
            MAILBOX,
            remote.hypervisor_arbitration,
        )
        first = restored_relay.receive_and_arbitrate()
        second = restored_relay.receive_and_arbitrate()
        assert first is not None and first.admission.accepted is True
        assert second is not None and second.admission.accepted is True
        assert first.admission.revision == 1
        assert second.admission.revision == 2
        assert restored_relay.pending() == 0
        assert restored_store.verify()
        assert remote.environment.kernel.journal.verify()
    finally:
        primary_transport.close()
        replica_transport.close()


def test_replicated_revision_relay_leaves_malformed_and_conflicting_messages_queued(tmp_path) -> None:
    """Mathematics: invalid `decode(P)` or conflicting `I↦f(P')` leaves durable `Q` unchanged and emits no semantic consume."""

    store = ReplicatedMailboxStore(tmp_path / "replica.log", "R")
    node = ReplicatedMailboxNode(store)
    operating_system = HeadlessOS()
    relay = ReplicatedRevisionProposalRelay(node, MAILBOX, operating_system.hypervisor_arbitration)
    valid = _proposal("P", 1, 11)
    store.apply_replica(
        "P:op:1",
        "enqueue",
        {
            "addr": MAILBOX,
            "message": _message_to_record(
                Message(
                    sender="P",
                    recipient=MAILBOX,
                    op="HREV",
                    addr=MAILBOX,
                    body=(REVISION_PROPOSAL_KIND, valid.to_dict()),
                    message_id="P:msg:1",
                )
            ),
        },
    )
    admitted = relay.receive_and_arbitrate()
    assert admitted is not None and admitted.admission.accepted is True

    changed_snapshot = dict(valid.candidate_snapshot)
    changed_snapshot["model"] = "different-candidate"
    conflicting = HypervisorRevisionProposal(
        valid.source,
        valid.channel,
        valid.sequence,
        valid.logical_time,
        changed_snapshot,
        valid.witnesses,
    )
    store.apply_replica(
        "P:op:2",
        "enqueue",
        {
            "addr": MAILBOX,
            "message": _message_to_record(
                Message(
                    sender="P",
                    recipient=MAILBOX,
                    op="HREV",
                    addr=MAILBOX,
                    body=(REVISION_PROPOSAL_KIND, conflicting.to_dict()),
                    message_id="P:msg:2",
                )
            ),
        },
    )
    with pytest.raises(HypervisorError, match="conflicting revision proposal"):
        relay.receive_and_arbitrate()
    assert relay.pending() == 1

    assert store.consume(store.list(MAILBOX)[0]) is True

    store.apply_replica(
        "P:op:3",
        "enqueue",
        {
            "addr": MAILBOX,
            "message": _message_to_record(
                Message(
                    sender="P",
                    recipient=MAILBOX,
                    op="HREV",
                    addr=MAILBOX,
                    body=("invalid-kind", {}),
                    message_id="P:msg:3",
                )
            ),
        },
    )
    with pytest.raises(HypervisorRevisionRelayError, match="malformed"):
        relay.receive_and_arbitrate()
    assert relay.pending() == 1


def test_replicated_revision_relay_binds_submission_to_node_identity(tmp_path) -> None:
    """Mathematics: reject `proposal.source≠node.id` before the durable enqueue transition mutates `Q`."""

    node = ReplicatedMailboxNode(ReplicatedMailboxStore(tmp_path / "primary.log", "P"))
    relay = ReplicatedRevisionProposalRelay(node, MAILBOX)
    with pytest.raises(HypervisorRevisionRelayError, match="node identity"):
        relay.submit(_proposal("other", 1, 11))
    assert node.pending(MAILBOX) == 0
