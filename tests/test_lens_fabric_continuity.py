"""LENS-003: real terminal Hypervisors with native Fabric route and quorum contracts.

The first-hop wire is a controlled forwarding stub so topology failures can be
injected. Route/envelope/hop objects, receiver-local Structural Memory reads,
Virtual Layer Hypervisors and durable recovery quorum are the real E-CPU APIs.
Live mutual-TLS is tested separately by LENS-002 and existing Fabric tests.
"""
from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

import pytest

from mailcpu import (
    Capability, HeadlessOS, HypervisorAction, HypervisorPolicy, LexicalDecisionModel,
    OperatorRegistry, SystemIdentity, SystemSeed, SystemSeedEnvelope,
    VirtualGroundRef, VirtualLayerRuntime,
)
from mailcpu.computational_fabric import (
    ComputationalFabricDirectory, ComputationalHostAdvertisement,
    ComputationalNetworkLink, ComputationalPeerEndpoint, ComputationalPeerSnapshot,
)
from mailcpu.computational_fabric_forwarding import (
    ComputationalFabricForwardingClient, ComputationalFabricForwardingServer,
    ComputationalFabricHopReceipt, ComputationalFabricForwardingError,
)
from mailcpu.computational_resolver import ComputationalAddress, ComputationalHostLocus, ComputationalHostCatalogue
from mailcpu.evidence_path_resolver import RouteMetric
from mailcpu.federated_ground_continuity import (
    AtomicGroundEvidenceStore, GroundContinuityRefused, NativeGroundDispatcher,
)
from mailcpu.law_certifier import Law
from mailcpu.lens_ground import recover_lens_law, transform
from mailcpu.lens_fabric_continuity import (
    LensFabricDispatcher, LensFabricIntent, LensFabricRefused,
    lens_fabric_address, lens_fabric_handler, lens_fabric_spec,
    recheck_lens_evidence, recover_lens_fabric_result, seal_lens_fabric_result,
)
from mailcpu.recovery_lineage import (
    RecoveryLineageAuthority, RecoveryLineageCoordinator, RecoveryLineageError,
)
from mailcpu.runtime_qualification import canonical, digest
from mailcpu.seed_commit_quorum import SeedCommitMembership
from mailcpu.structural_memory import StructuralMemoryRegistry


COORDINATE = (1 << 50) + 103
BASE = (1 << 41) + 27
HOSTS = ("peer-c", "peer-d")


def _proposal():
    """Use the actual LENS-001 discovery and independent finite witness certifier."""
    samples = [transform((BASE + t) % (1 << 64), "gray.encode") for t in range(112)]
    law = recover_lens_law(samples[:64], samples[64:])
    assert law.family == "lens64" and law.verdict == "GROUND"
    origin = StructuralMemoryRegistry(admission_policy=lambda _: True)
    return origin.propose(
        "lens003-orbit", law,
        {t: samples[t] for t in (0, 1, 2, 5, 11, 37, 63, 79, 111)},
        context={"research": "lens003", "observer": "gray"},
    )


def _cost(delay):
    """Build the exact shared native multi-metric route basis."""
    return (
        RouteMetric("latency", "ticks", delay),
        RouteMetric("energy", "units", 5),
        RouteMetric("bytes", "bytes", 128),
        RouteMetric("risk", "score", 0),
    )


def _endpoint(peer):
    """Construct a finite identity-pinned peer advertisement."""
    return ComputationalPeerEndpoint(peer, peer + ".lens003.test", "127.0.0.1", 45018)


def _snapshot(peer, *, outgoing=(), host=None, revision=1, latency=1):
    """Construct native peer-owned route descriptions with typed local host contracts."""
    hosts = () if host is None else (host,)
    links = tuple(ComputationalNetworkLink(peer, next_peer, _cost(1)) for next_peer in outgoing)
    return ComputationalPeerSnapshot(_endpoint(peer), revision, 60, hosts, links)


def _receiver(proposal, envelope, peer, *, allow_read=True, admit_memory=True):
    """Install and admit the same Ground into a separate native HeadlessOS receiver."""
    os = HeadlessOS(structural_memory_admission_policy=lambda item: item.spec.digest == proposal.spec.digest)
    os.hypervisor.classifier = LexicalDecisionModel()
    os.hypervisor.policy = HypervisorPolicy(embedding_review_confidence=1.0)
    assert os.seed_admission.admit(envelope).accepted
    p = proposal.spec
    if admit_memory:
        law = Law(p.family, p.parameters, p.order, p.law_verdict, first_bad=p.first_bad)
        staged = os.structural_memory.propose(
            p.memory_id, law, dict(proposal.witnesses), domain=p.domain, context=p.context,
        )
        assert staged.proposal_id == proposal.proposal_id
        version = os.structural_memory.admit(staged.proposal_id, expected_revision=0)
        assert version.spec.digest == p.digest
    registry = OperatorRegistry()
    registry.register(lens_fabric_spec(), lens_fabric_handler)
    runtime = VirtualLayerRuntime(registry, "node-" + peer[-1], frozenset({"cpu"}))
    caps = [Capability("/virtual-layer/operators", frozenset({"compute"}))]
    if allow_read:
        caps.append(Capability("/structural-memory/read", frozenset({"read"})))
    pid = os.environment.kernel.spawn(
        "lens003-worker", capabilities=tuple(caps), parent_pid=os.environment.init_pid,
    )
    locus = ComputationalHostLocus.from_runtime(
        host_id="host-" + peer, runtime=runtime, authority_pid=pid,
        operator_id=lens_fabric_spec().operator_id,
        computational_ground_fingerprints=(p.digest,),
        supports_ground_program_compilation=True,
        supports_structural_memory=True,
        costs=_cost(1 if peer == "peer-c" else 8),
        implementation_fingerprint=digest("lens-implementation-" + peer),
    )
    return os, runtime, pid, ComputationalHostAdvertisement.from_locus(locus, peer), ComputationalHostCatalogue((locus,))


class _TerminalWire:
    """Controlled forwarding seam that calls actual independent terminal Hypervisors."""

    def __init__(self, receivers):
        """Bind the test's explicit peer-to-receiver table; never claim a physical relay."""
        self.receivers = receivers
        self.calls = 0
        self.mutate = False
        self.before_reply = None

    def __call__(self, envelope, directory):
        """Build native typed hop receipts around a genuinely executed terminal effect."""
        self.calls += 1
        target = envelope.route.peer_path[-1]
        os, _runtime, _pid, _advertisement, catalogue = self.receivers[target]
        first = envelope.advance()
        last = first.advance()
        # Call the production terminal method: it compares the live local
        # catalogue to the advertised host, resolves the address under receiver
        # authority, then performs real Hypervisor/Structural Memory execution.
        terminal_server = object.__new__(ComputationalFabricForwardingServer)
        terminal_server.catalogue = catalogue
        terminal_server.local_peer_id = target
        terminal_server.operating_system = os
        terminal_server.claim_coordinator = None
        terminal_server.timing_probe = None
        terminal_server.claim_status_clients = {}
        executed = terminal_server._execute_terminal(last)
        assert executed["kind"] == "terminal"
        terminal_execution = executed["terminal_execution"]
        assert terminal_execution["accepted"] and terminal_execution["executed"]
        if self.mutate:
            terminal_execution = json.loads(canonical(terminal_execution))
            terminal_execution["execution"]["effect"]["structural_memory_receipts"]["lens"]["value"] ^= 1
        terminal = ComputationalFabricHopReceipt(
            peer_id=last.current_peer_id, previous_peer_id=last.previous_peer_id,
            next_peer_id=None, hop_index=2, operation_digest=last.operation_digest,
            envelope_digest=last.digest, next_envelope_digest=None,
            decision_receipt="7" * 64, status="executed",
            terminal_execution=terminal_execution,
        )
        receipt = ComputationalFabricHopReceipt(
            peer_id=first.current_peer_id, previous_peer_id=first.previous_peer_id,
            next_peer_id=last.current_peer_id, hop_index=1,
            operation_digest=first.operation_digest, envelope_digest=first.digest,
            next_envelope_digest=last.digest, decision_receipt="b" * 64,
            status="forwarded", downstream=terminal,
        )
        if self.before_reply is not None:
            self.before_reply(directory)
        return receipt


def _fabric(*, denied_read=frozenset(), missing_revision=frozenset()):
    """Create two native receiver runtimes and authenticated-ingress test snapshots."""
    proposal = _proposal()
    origin = HeadlessOS()
    identity = SystemIdentity("lens003-system", 1)
    seed_envelope = SystemSeedEnvelope(
        identity, "test-origin", "lens003", SystemSeed.from_system(origin),
    )
    assert origin.seed_admission.admit(seed_envelope).accepted
    system_ground = VirtualGroundRef.from_envelope(seed_envelope)
    receivers = {
        peer: _receiver(
            proposal, seed_envelope, peer,
            allow_read=peer not in denied_read,
            admit_memory=peer not in missing_revision,
        )
        for peer in HOSTS
    }
    directory = ComputationalFabricDirectory(
        "peer-a", {peer: peer + ".lens003.test" for peer in ("peer-b",) + HOSTS},
        monotonic=lambda: 0.0,
    )
    directory.register_local_snapshot(_snapshot("peer-a", outgoing=("peer-b",)))
    for snap in (
        _snapshot("peer-b", outgoing=HOSTS),
        _snapshot("peer-c", host=receivers["peer-c"][3]),
        _snapshot("peer-d", host=receivers["peer-d"][3], latency=8),
    ):
        assert directory._merge_verified_peer_snapshot(
            snap, authenticated_peer_id=snap.peer_id,
            authenticated_server_name=snap.endpoint.tls_server_name,
        )
    # Native client object with network I/O swapped for this controlled experiment.
    client = object.__new__(ComputationalFabricForwardingClient)
    client.local_peer_id = client.origin_peer_id = "peer-a"
    client.origin_channel = "lens003.native"
    client.remote_endpoint = _endpoint("peer-b")
    wire = _TerminalWire(receivers)
    client.forward = wire
    native = NativeGroundDispatcher(
        directory, client,
        allowed_hosts=frozenset({
            ("peer-c", "host-peer-c"), ("peer-d", "host-peer-d"),
        }),
    )
    intent = LensFabricIntent(proposal, COORDINATE, "one-intention")
    address = lens_fabric_address(
        intent, system=identity, ground=system_ground,
        eligible_nodes=("node-c", "node-d"),
    )
    return LensFabricDispatcher(native), intent, address, wire, receivers


def _quorum(root: Path):
    """Provision actual 3-member fsynced E-CPU quorum journals on the test machine."""
    members = SeedCommitMembership(
        "lens003-machine", 1, ("owner", "anchor-b", "anchor-c"),
        "owner", 1, "f" * 64,
    )
    authorities = {
        m: RecoveryLineageAuthority(members, m, root / (m + ".jsonl"))
        for m in members.member_ids
    }
    return members, RecoveryLineageCoordinator(members, authorities)


def test_real_terminal_lens_ground_survives_native_rehome_and_quorum_recovery(tmp_path):
    """Same revision and distant value survive peer-c -> peer-d and stale root is fenced."""
    fabric, intent, address, wire, receivers = _fabric()
    first = fabric.prepare(intent, address, origin_sequence=1)
    assert first.route.envelope.route.peer_path == ("peer-a", "peer-b", "peer-c")
    evidence_a = fabric.execute(first)
    assert recheck_lens_evidence(intent, address, evidence_a) == evidence_a
    assert evidence_a["observed"] == {"value": intent.expected_value}
    assert evidence_a["structural_memory_read"]["spec_digest"] == intent.proposal.spec.digest
    assert evidence_a["structural_memory_read"]["coordinate"] == COORDINATE
    members, coordinator = _quorum(tmp_path)
    storage = AtomicGroundEvidenceStore(tmp_path / "ground-states")
    m1, p1 = seal_lens_fabric_result(
        intent, address, evidence_a, coordinator=coordinator, storage=storage,
        generation=1, predecessor_digest=members.genesis_state_digest,
    )

    other = fabric.prepare(
        intent, address, origin_sequence=1,
        excluded_hosts=frozenset({("peer-c", "host-peer-c")}),
    )
    assert other.route.envelope.route.peer_path == ("peer-a", "peer-b", "peer-d")
    evidence_b = fabric.execute(other)
    assert wire.calls == 2
    assert evidence_b["intention_digest"] == evidence_a["intention_digest"]
    assert evidence_b["spec_digest"] == evidence_a["spec_digest"]
    assert evidence_b["certificate_digest"] == evidence_a["certificate_digest"]
    assert evidence_b["observed"] == evidence_a["observed"]
    assert evidence_b["route_digest"] != evidence_a["route_digest"]
    assert evidence_b["terminal_peer_id"] == "peer-d"

    m2, p2 = seal_lens_fabric_result(
        intent, address, evidence_b, coordinator=coordinator, storage=storage,
        generation=2, predecessor_digest=m1.digest,
    )
    recovered = recover_lens_fabric_result(
        intent, address, manifest=m2, proof=p2, coordinator=coordinator, storage=storage,
    )
    assert recovered["observed"] == {"value": intent.expected_value}
    assert recovered["reexecuted_computation"] is False
    assert wire.calls == 2  # recovery never calls the executor
    with pytest.raises(RecoveryLineageError, match="stale"):
        recover_lens_fabric_result(
            intent, address, manifest=m1, proof=p1, coordinator=coordinator, storage=storage,
        )
    for peer in HOSTS:
        os = receivers[peer][0]
        assert any(event.kind == "structural_memory.read_revision"
                   for event in os.environment.kernel.journal.records())


def test_stale_topology_refuses_before_dispatch():
    """A verified plan becomes inadmissible on authenticated directory revision advance."""
    fabric, intent, address, wire, _ = _fabric()
    plan = fabric.prepare(intent, address, origin_sequence=1)
    snapshot = _snapshot("peer-b", outgoing=HOSTS, revision=2)
    directory = fabric.native.directory
    assert directory._merge_verified_peer_snapshot(
        snapshot, authenticated_peer_id="peer-b",
        authenticated_server_name=snapshot.endpoint.tls_server_name,
    )
    with pytest.raises(GroundContinuityRefused, match="changed before"):
        fabric.execute(plan)
    assert wire.calls == 0


def test_midflight_topology_change_refuses_success_ack():
    """A valid terminal result cannot upgrade a changed route into an accepted result."""
    fabric, intent, address, wire, _ = _fabric()
    plan = fabric.prepare(intent, address, origin_sequence=1)
    def change(directory):
        """Model one verified upstream peer epoch change before the response arrives."""
        snapshot = _snapshot("peer-b", outgoing=HOSTS, revision=2)
        assert directory._merge_verified_peer_snapshot(
            snapshot, authenticated_peer_id="peer-b",
            authenticated_server_name=snapshot.endpoint.tls_server_name,
        )
    wire.before_reply = change
    with pytest.raises(GroundContinuityRefused, match="changed during"):
        fabric.execute(plan)
    assert wire.calls == 1


def test_terminal_value_receipt_mismatch_is_rejected():
    """Even after real Hypervisor authorization, mutated observer evidence is refused."""
    fabric, intent, address, wire, _ = _fabric()
    plan = fabric.prepare(intent, address, origin_sequence=1)
    wire.mutate = True
    with pytest.raises(LensFabricRefused, match="terminal read receipt"):
        fabric.execute(plan)


def test_changed_ground_or_coordinate_refuses_before_network():
    """No remote offer can change the mathematical intention or requested revision."""
    fabric, intent, address, wire, _ = _fabric()
    with pytest.raises(LensFabricRefused, match="semantic address"):
        fabric.prepare(replace(intent, coordinate=COORDINATE + 1), address, origin_sequence=1)
    with pytest.raises(LensFabricRefused, match="semantic address"):
        fabric.prepare(
            replace(intent, request_id="different-intention"), address, origin_sequence=2,
        )
    assert wire.calls == 0


def test_recovered_evidence_cannot_be_retargeted_or_corrupted(tmp_path):
    """Quorum high-water and exact Ground bind every recovered semantic observation."""
    fabric, intent, address, wire, _ = _fabric()
    evidence = fabric.execute(fabric.prepare(intent, address, origin_sequence=1))
    members, coordinator = _quorum(tmp_path)
    storage = AtomicGroundEvidenceStore(tmp_path / "store")
    manifest, proof = seal_lens_fabric_result(
        intent, address, evidence, coordinator=coordinator, storage=storage,
        generation=1, predecessor_digest=members.genesis_state_digest,
    )
    with pytest.raises(LensFabricRefused, match="semantic address"):
        recover_lens_fabric_result(
            replace(intent, coordinate=COORDINATE + 1), address, manifest=manifest,
            proof=proof, coordinator=coordinator, storage=storage,
        )
    encoded = storage.directory / (manifest.state_digest + ".json")
    encoded.write_bytes(encoded.read_bytes() + b" ")
    with pytest.raises(GroundContinuityRefused, match="content address"):
        recover_lens_fabric_result(
            intent, address, manifest=manifest, proof=proof,
            coordinator=coordinator, storage=storage,
        )


def test_receiver_cannot_use_a_remote_read_capability(tmp_path):
    """Receiver-owned Structural Memory authority refuses a routed but ungranted read."""
    fabric, intent, address, wire, receivers = _fabric(denied_read=frozenset({"peer-c"}))
    plan = fabric.prepare(intent, address, origin_sequence=1)
    with pytest.raises(ComputationalFabricForwardingError, match="fresh terminal semantic resolution"):
        fabric.execute(plan)
    assert wire.calls == 1
    assert not any(event.kind == "structural_memory.read_revision"
                   for event in receivers["peer-c"][0].environment.kernel.journal.records())


def test_pinned_certificate_substitution_refused_before_forwarding():
    """One valid route and output type cannot authorize a different witness certificate."""
    fabric, intent, address, wire, _ = _fabric()
    original = address.workload.operators[0]
    reference = replace(original.structural_memory[0], certificate_digest="0" * 64)
    substituted = replace(original, structural_memory=(reference,))
    workload = replace(address.workload, operators=(substituted,))
    new_address = ComputationalAddress.from_workload(
        workload, lens_fabric_spec().operator_id, lens_fabric_spec(),
        intent.proposal.spec.digest,
    )
    with pytest.raises(LensFabricRefused, match="semantic address"):
        fabric.prepare(intent, new_address, origin_sequence=1)
    assert wire.calls == 0


def test_receiver_rejects_inline_coordinate_drift():
    """A local Hypervisor operator will not reinterpret the pinned memory address."""
    fabric, intent, address, _wire, receivers = _fabric()
    os, runtime, pid, _ = receivers["peer-c"]
    changed_workload = replace(
        address.workload, input_value={"coordinate": COORDINATE + 1},
    )
    with pytest.raises(LensFabricRefused, match="receiver coordinate"):
        runtime.execute_operator(
            os, pid, "lens003.remote", "lens003.coordinatedrift",
            1, changed_workload.logical_time,
            changed_workload, lens_fabric_spec().operator_id,
        )


def test_native_address_transports_only_revision_not_law_or_witness_tape():
    """The native route contains no remote generator, synthetic tape or admission grant."""
    _fabric_runtime, intent, address, _wire, _receivers = _fabric()
    encoded = canonical(address.to_dict())
    assert b'"parameters"' not in encoded
    assert b'"witnesses"' not in encoded
    assert b'"frames"' not in encoded
    assert b'"admission_policy"' not in encoded
    reference = address.workload.operators[0].structural_memory[0]
    assert reference.to_dict() == intent.memory_ref.to_dict()
    assert reference.coordinate == COORDINATE
    assert address.workload.schema_version == 2


def test_terminal_rejects_stale_implementation_advertisement():
    """Native terminal rechecks its live host implementation, never trusting old directory bytes."""
    fabric, intent, address, wire, receivers = _fabric()
    plan = fabric.prepare(intent, address, origin_sequence=1)
    os, runtime, pid, advertised, catalogue = receivers["peer-c"]
    shifted_locus = replace(
        catalogue.loci[0],
        implementation_fingerprint=digest("new-receiver-build"),
    )
    receivers["peer-c"] = (
        os, runtime, pid, advertised, ComputationalHostCatalogue((shifted_locus,)),
    )
    with pytest.raises(ComputationalFabricForwardingError, match="differs from the live local locus"):
        fabric.execute(plan)
    assert wire.calls == 1
    assert not any(event.kind == "structural_memory.read_revision"
                   for event in os.environment.kernel.journal.records())
