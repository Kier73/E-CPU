from __future__ import annotations

from mailcpu import (
    ClassifierHypervisor,
    HeadlessOS,
    HypervisorRequest,
    HypervisorRevisionProposal,
    HypervisorRevisionWitness,
    IntentExample,
    IntentPrototypeModel,
    ReliabilityPolicy,
    ReliableChannel,
    ReplicatedMailboxNode,
    ReplicatedMailboxStore,
    ReplicatedRevisionProposalRelay,
    SocketTransport,
    VirtualMemory,
)
from mailcpu.procedural_model import ProceduralDecisionModel
from mailcpu.remote_memory import RemotePageStore
from mailcpu.revision_transport import REVISION_PROPOSAL_KIND


MAILBOX = "external-hypervisor-revisions"


def _proposal(source: str) -> HypervisorRevisionProposal:
    """Mathematics: construct one live witnessed revision `P=(I,m',W)` for external transport."""

    operating_system = HeadlessOS()
    request = HypervisorRequest(
        "receive network packet socket connection",
        "/network/loopback",
        {"transport": "tcp", "encoding": "canonical"},
        frozenset({"receive"}),
        frozenset({"receive"}),
    )
    decision = operating_system.hypervisor_decide(request)
    candidate = ProceduralDecisionModel.from_snapshot(operating_system.hypervisor.classifier.snapshot())
    return HypervisorRevisionProposal.from_candidate(
        source,
        "external-revisions",
        1,
        31,
        candidate,
        (HypervisorRevisionWitness.from_decision(request, decision),),
    )


def _external_replicated_pair(tmp_path):
    """Mathematics: bind two durable nodes to an actual `AF_INET` stream with one reliable `P→R` replication channel."""

    listener = SocketTransport.listen("127.0.0.1", 0)
    port = listener.getsockname()[1]
    primary_transport = SocketTransport.connect("127.0.0.1", port, "P", "R")
    replica_transport = SocketTransport.accept(listener, "R", "P")
    listener.close()
    policy = ReliabilityPolicy(lease_ticks=1, max_attempts=4, window_size=16)
    primary_channel = ReliableChannel(primary_transport, "P", "R", "external", policy)
    replica_channel = ReliableChannel(replica_transport, "R", "R", "external", policy, peer="P")
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


def _external_page_pair(tmp_path, page_size: int = 8):
    """Mathematics: bind bidirectional replicated channels `A↔B` over one external TCP stream for remote CAS requests."""

    listener = SocketTransport.listen("127.0.0.1", 0)
    port = listener.getsockname()[1]
    transport_a = SocketTransport.connect("127.0.0.1", port, "A", "B")
    transport_b = SocketTransport.accept(listener, "B", "A")
    listener.close()
    policy = ReliabilityPolicy(lease_ticks=1, max_attempts=4, window_size=16)
    a_out = ReliableChannel(transport_a, "A", "B", "external-pages", policy)
    a_in = ReliableChannel(transport_a, "A", "A", "external-pages", policy, peer="B")
    b_out = ReliableChannel(transport_b, "B", "A", "external-pages", policy)
    b_in = ReliableChannel(transport_b, "B", "B", "external-pages", policy, peer="A")
    node_a = ReplicatedMailboxNode(
        ReplicatedMailboxStore(tmp_path / "a.mailbox.log", "A"),
        outbound={"B": a_out},
        inbound={"B": a_in},
        quorum=2,
    )
    node_b = ReplicatedMailboxNode(
        ReplicatedMailboxStore(tmp_path / "b.mailbox.log", "B"),
        outbound={"A": b_out},
        inbound={"A": b_in},
        quorum=2,
    )
    store_a = RemotePageStore(
        tmp_path / "pages-a",
        node_a,
        page_size=page_size,
        default_peer="B",
        pump=lambda: store_b.service(),
    )
    store_b = RemotePageStore(
        tmp_path / "pages-b",
        node_b,
        page_size=page_size,
        default_peer="A",
        pump=lambda: store_a.service(),
    )
    return transport_a, transport_b, store_a, store_b


def test_external_tcp_revision_encoding_and_hypervisor_admission(tmp_path) -> None:
    """Mathematics: `decode_mailbox(decode_wire(encode_wire(P)))=P`, then durable quorum and one remote admission hold."""

    primary, replica, primary_transport, replica_transport = _external_replicated_pair(tmp_path)
    sender = ReplicatedRevisionProposalRelay(primary, MAILBOX)
    remote = HeadlessOS()
    receiver = ReplicatedRevisionProposalRelay(replica, MAILBOX, remote.hypervisor_arbitration)
    proposal = _proposal("P")
    try:
        operation_id = sender.submit(proposal)
        assert replica.pending(MAILBOX) == 1
        queued = replica.store.list(MAILBOX)[0]
        assert queued.body == (REVISION_PROPOSAL_KIND, proposal.to_dict())
        assert sender.receipt(operation_id).committed is True
        result = receiver.receive_and_arbitrate()
        assert result is not None
        assert result.admission.accepted is True
        assert result.admission.revision == 1
        assert receiver.pending() == 0
        assert remote.environment.kernel.journal.verify()
    finally:
        primary_transport.close()
        replica_transport.close()


def test_external_tcp_remote_page_backing_drives_virtual_memory_fault(tmp_path) -> None:
    """Mathematics: `M[p]=h → reclaim → CAS_remote[h] → fault` restores the exact page over external TCP."""

    transport_a, transport_b, store_a, store_b = _external_page_pair(tmp_path)
    try:
        memory = VirtualMemory(page_size=8, page_backing=store_a)
        memory.map(0, 8)
        assert memory.write(0, b"tcp-page") == 8
        digest = memory.mapped_pages()[0].blob_id
        assert memory.reclaim(page_numbers=(0,)) == (0,)
        assert store_b.has_page(digest)
        store_a.drop_local_cache(digest)
        assert memory.read(0, 8) == b"tcp-page"
        assert store_a.has_page(digest)
    finally:
        transport_a.close()
        transport_b.close()


def test_external_operation_states_form_advisory_hypervisor_training_corpus() -> None:
    """Mathematics: `M_candidate=fit(X_observed)` classifies held-out states while `H.intent_model` remains unchanged until an intent witness gate exists."""

    examples = (
        IntentExample("network", {"operation": "receive network packet socket", "resource": "/network/loopback", "payload": {"transport": "tcp"}}),
        IntentExample("filesystem", {"operation": "read filesystem file descriptor", "resource": "/srv/data", "payload": {"path": "/srv/data"}}),
        IntentExample("service", {"operation": "restart service supervisor", "resource": "/service/worker", "payload": {"service": "worker"}}),
    )
    candidate = IntentPrototypeModel.fit(examples)
    held_out = {
        "network": {"operation": "receive network packet socket", "resource": "/network/remote", "payload": {"transport": "tcp"}},
        "filesystem": {"operation": "inspect filesystem file", "resource": "/srv/other", "payload": {"path": "/srv/other"}},
        "service": {"operation": "stop service supervisor", "resource": "/service/daemon", "payload": {"service": "daemon"}},
    }
    for expected, state in held_out.items():
        assert candidate.predict(state).domain == expected

    operating_system = HeadlessOS()
    before = operating_system.hypervisor.intent_model.snapshot()
    decision = operating_system.hypervisor_decide(
        HypervisorRequest(
            "receive network packet socket connection",
            "/network/remote",
            {"transport": "tcp"},
        )
    )
    assert decision.intent_domain == "network"
    assert operating_system.hypervisor.intent_model.snapshot() == before
    assert isinstance(ClassifierHypervisor(intent_model=candidate).intent_model, IntentPrototypeModel)
