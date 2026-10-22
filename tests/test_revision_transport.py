from __future__ import annotations

import socket

import pytest

from mailcpu import (
    HeadlessOS,
    HypervisorError,
    HypervisorRequest,
    HypervisorRevisionChannel,
    HypervisorRevisionProposal,
    HypervisorRevisionTransportError,
    HypervisorRevisionWitness,
    InMemoryTransport,
    Message,
    ProceduralDecisionModel,
    ReliabilityPolicy,
    ReliableChannel,
    SocketTransport,
)


def _proposal() -> HypervisorRevisionProposal:
    """Mathematics: construct one deterministic `P=(I,m',W)` from the current revision-0 hypervisor."""

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
        "origin",
        "revisions",
        1,
        17,
        candidate,
        (HypervisorRevisionWitness.from_decision(request, decision),),
    )


def test_revision_proposal_round_trips_and_admits_over_real_tcp_path() -> None:
    """Mathematics: `encode(P);decode(P)=P`, then reliable `RDATA(P);ACK` reaches one remote admission."""

    left, right = socket.socketpair()
    sender_transport = SocketTransport(left, "origin", "replica")
    receiver_transport = SocketTransport(right, "replica", "origin")
    policy = ReliabilityPolicy(lease_ticks=1, max_attempts=3)
    sender_channel = HypervisorRevisionChannel(
        ReliableChannel(sender_transport, "origin", "replica", "revisions", policy)
    )
    receiver_channel = HypervisorRevisionChannel(
        ReliableChannel(receiver_transport, "replica", "replica", "revisions", policy, peer="origin")
    )
    origin = HeadlessOS()
    replica = HeadlessOS()
    proposal = _proposal()
    try:
        assert HypervisorRevisionProposal.from_dict(proposal.to_dict()) == proposal
        transport_sequence = sender_channel.send(proposal)
        result = receiver_channel.receive_and_arbitrate(replica.hypervisor_arbitration)
        assert result is not None
        assert result.admission.accepted is True
        assert result.admission.revision == 1
        assert replica.hypervisor.snapshot()["revision"] == 1
        assert sender_channel.channel.process_ack() == (transport_sequence,)
        assert sender_channel.channel.pending_sequences() == ()
        assert replica.environment.kernel.journal.verify()
    finally:
        sender_transport.close()
        receiver_transport.close()


def test_revision_transport_refuses_malformed_payload_before_acknowledgement() -> None:
    """Mathematics: invalid `decode(P)` leaves `Q` and `ACK(Q)` unchanged, so malformed proposals cannot consume delivery."""

    transport = InMemoryTransport()
    channel = ReliableChannel(transport, "replica", "replica", "revisions", peer="origin")
    adapter = HypervisorRevisionChannel(channel)
    transport.send(
        "replica",
        Message(
            sender="origin",
            recipient="replica",
            addr="replica",
            op="RDATA",
            body=("revisions", 1, {"kind": "invalid"}),
        ),
    )

    with pytest.raises(HypervisorRevisionTransportError, match="payload"):
        adapter.receive()
    assert transport.pending("replica") == 1
    assert transport.pending(adapter.channel.ack_address) == 0


def test_revision_transport_keeps_conflicting_proposal_queued_before_ack() -> None:
    """Mathematics: if `I(P)=I(P')` and `f(P)≠f(P')`, arbitration refuses before `Q:=Q\\{F_s}` or `ACK(s)`."""

    transport = InMemoryTransport()
    sender = HypervisorRevisionChannel(
        ReliableChannel(transport, "origin", "replica", "revisions")
    )
    receiver = HypervisorRevisionChannel(
        ReliableChannel(transport, "replica", "replica", "revisions", peer="origin")
    )
    operating_system = HeadlessOS()
    proposal = _proposal()
    sender.send(proposal)
    first = receiver.receive_and_arbitrate(operating_system.hypervisor_arbitration)
    assert first is not None and first.admission.accepted is True
    assert sender.channel.process_ack() == (1,)

    changed_snapshot = dict(proposal.candidate_snapshot)
    changed_snapshot["model"] = "different-candidate"
    conflicting = HypervisorRevisionProposal(
        proposal.source,
        proposal.channel,
        proposal.sequence,
        proposal.logical_time,
        changed_snapshot,
        proposal.witnesses,
    )
    transport.send(
        "replica",
        Message(
            sender="origin",
            recipient="replica",
            addr="replica",
            op="RDATA",
            body=("revisions", 1, {"kind": "mailcpu.hypervisor.revision.proposal", "proposal": conflicting.to_dict()}),
        ),
    )

    with pytest.raises(HypervisorError, match="conflicting revision proposal"):
        receiver.receive_and_arbitrate(operating_system.hypervisor_arbitration)
    assert transport.pending("replica") == 1
    assert transport.pending(receiver.channel.ack_address) == 0

