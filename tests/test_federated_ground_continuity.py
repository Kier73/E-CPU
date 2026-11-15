"""SAB-007: real native fabric object contracts and durable recovery quorum tests.

Forwarder replacement in these tests is a controlled fake: the repository's
separate native mTLS multi-hop tests run in CI to test actual wire behavior.
"""
from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

import pytest

from mailcpu.adaptive_placement import CompositeIntent, expected_result
from mailcpu.computational_fabric import (
    ComputationalFabricDirectory, ComputationalFabricResolver,
    ComputationalPeerEndpoint, ComputationalPeerSnapshot,
    ComputationalNetworkLink, ComputationalHostAdvertisement,
)
from mailcpu.computational_fabric_forwarding import (
    ComputationalFabricForwardingClient, ComputationalFabricHopReceipt,
)
from mailcpu.computational_resolver import ComputationalAddress, ComputationalHostLocus
from mailcpu.evidence_path_resolver import RouteMetric, RouteMetricKey
from mailcpu.federated_ground_continuity import (
    AtomicGroundEvidenceStore, GroundContinuityRefused, NativeGroundDispatcher,
    SCHEMA, recheck_evidence, recover_native_result, seal_native_result,
    validate_native_result,
)
from mailcpu.recovery_lineage import (
    RecoveryLineageAuthority, RecoveryLineageCoordinator, RecoveryLineageError,
)
from mailcpu.seed_commit_quorum import SeedCommitMembership
from mailcpu.seed import SystemIdentity
from mailcpu.virtual_layer import (
    OperatorRegistry, OperatorSpec, VirtualBudget, VirtualGroundRef,
    VirtualLayerRuntime, VirtualLayerWorkload, VirtualOperatorRef,
)
from mailcpu.runtime_qualification import digest


METRICS = (
    RouteMetricKey("latency", "ticks"), RouteMetricKey("energy", "units"),
    RouteMetricKey("bytes", "bytes"), RouteMetricKey("risk", "score"),
)


def costs(delay: int) -> tuple[RouteMetric, ...]:
    """Construct a common finite metric basis for all routes and native operators."""
    return (RouteMetric("latency", "ticks", delay),
            RouteMetric("energy", "units", 5),
            RouteMetric("bytes", "bytes", 64),
            RouteMetric("risk", "score", 0))


def endpoint(peer: str) -> ComputationalPeerEndpoint:
    """Create a named synthetic directory peer with an exact TLS DNS pin."""
    return ComputationalPeerEndpoint(peer, f"{peer}.sab007.test", "127.0.0.1", 44002)


def spec() -> OperatorSpec:
    """Describe only pure affine navigation; no new source execution is allowed."""
    return OperatorSpec("sab007.affine_mod", 1, "Navigate a pinned affine Ground",
                        "object", "object", ("cpu",), frozenset({"compute"}),
                        8, 1, 4096, 256, True, "pure")


def intent() -> CompositeIntent:
    """One stable intention whose coordinate is prohibitively large for iteration."""
    return CompositeIntent("sab007-intent", 5, 7, 65521, 19, 10**15 + 137)


def address_for(target: CompositeIntent, *, mismatched_input: bool = False) -> ComputationalAddress:
    """Construct a native typed semantic address matching the SAB-004 intention."""
    payload = dict(target.input())
    if mismatched_input:
        payload["x0"] += 1
    workload = VirtualLayerWorkload(
        workload_id="sab007-" + target.request_id,
        system=SystemIdentity("sab007-system", 1),
        ground=VirtualGroundRef("a" * 64, "b" * 64, 0, "c" * 64),
        intention={"goal": {"kind": "sab007.affine", "intention": target.fingerprint,
                            "ground": target.ground}},
        operators=(VirtualOperatorRef("sab007.affine_mod", 1, "cpu"),),
        input_value=payload,
        budget=VirtualBudget(100000, 100000, 10000),
        logical_time=29,
        eligible_nodes=("node-c", "node-d"),
        max_hops=4,
    )
    return ComputationalAddress.from_workload(workload, "sab007.affine_mod", spec(),
                                              target.ground, metric_order=METRICS)


def advertisement(peer: str, latency: int) -> ComputationalHostAdvertisement:
    """Project a receiver-local native locus to portable, non-authoritative metadata."""
    registry = OperatorRegistry()
    registry.register(spec(), lambda value, workload: {"value": 1})
    runtime = VirtualLayerRuntime(registry, "node-" + peer[-1], frozenset({"cpu"}))
    locus = ComputationalHostLocus.from_runtime(
        host_id="host-" + peer, runtime=runtime, authority_pid=17,
        operator_id="sab007.affine_mod", computational_ground_fingerprints=(intent().ground,),
        supports_ground_program_compilation=True, costs=costs(latency),
        implementation_fingerprint=digest("local-" + peer),
    )
    return ComputationalHostAdvertisement.from_locus(locus, peer)


def snapshot(peer: str, *, outgoing: tuple[str, ...] = (), with_host: bool = False,
             latency: int = 2, revision: int = 1) -> ComputationalPeerSnapshot:
    """Fabric-native advertisement with only peer-owned outgoing link claims."""
    hosts = (advertisement(peer, latency),) if with_host else ()
    links = tuple(ComputationalNetworkLink(peer, nxt, costs(1)) for nxt in outgoing)
    return ComputationalPeerSnapshot(endpoint(peer), revision, 60, hosts, links)


def native_directory() -> ComputationalFabricDirectory:
    """Build deterministic synthetic authenticated snapshots using native verifier ingress.

    This calls the internal post-authentication seam **only inside tests**;
    production code must use merge_authenticated_snapshot over real mTLS.
    """
    now = [0.0]
    d = ComputationalFabricDirectory("peer-a", {
        "peer-b": "peer-b.sab007.test", "peer-c": "peer-c.sab007.test",
        "peer-d": "peer-d.sab007.test"}, monotonic=lambda: now[0])
    d.register_local_snapshot(snapshot("peer-a", outgoing=("peer-b",)))
    for s in (snapshot("peer-b", outgoing=("peer-c", "peer-d")),
              snapshot("peer-c", with_host=True, latency=2),
              snapshot("peer-d", with_host=True, latency=8)):
        assert d._merge_verified_peer_snapshot(s, authenticated_peer_id=s.peer_id,
                        authenticated_server_name=s.endpoint.tls_server_name)
    d._test_clock = now  # Synthetic clock belongs exclusively to this test fixture.
    return d


def fake_client() -> ComputationalFabricForwardingClient:
    """Allocate a native client shell; tests replace only its network I/O method."""
    client = object.__new__(ComputationalFabricForwardingClient)
    client.local_peer_id = "peer-a"
    client.origin_peer_id = "peer-a"
    client.origin_channel = "sab007.native"
    client.remote_endpoint = endpoint("peer-b")
    return client


def native_receipt(envelope, *, corrupt: bool = False, refuse: bool = False):
    """Produce a typed synthetic hop tree matching the actual native serialization ABI."""
    child = envelope.advance()
    terminal_env = child.advance()
    result = expected_result(intent())["value"] + (1 if corrupt else 0)
    terminal_exec = {
        "status": "executed" if not refuse else "hypervisor_refused",
        "accepted": not refuse, "executed": not refuse, "replayed": False,
        "address_digest": envelope.address.digest,
        "admission_receipt": "7" * 64,
        "execution": {"effect": {
            "kind": "virtual_layer.operator_result",
            "operator_contract_digest": envelope.address.operator_contract_digest,
            "ground": envelope.address.workload.ground.to_dict(),
            "result": {"value": result}}},
    }
    terminal = ComputationalFabricHopReceipt(
        peer_id=terminal_env.current_peer_id,
        previous_peer_id=terminal_env.previous_peer_id,
        next_peer_id=None, hop_index=2,
        operation_digest=terminal_env.operation_digest,
        envelope_digest=terminal_env.digest,
        next_envelope_digest=None, decision_receipt="5" * 64,
        status="refused" if refuse else "executed",
        terminal_execution=terminal_exec,
    )
    return ComputationalFabricHopReceipt(
        peer_id=child.current_peer_id, previous_peer_id=child.previous_peer_id,
        next_peer_id=terminal_env.current_peer_id,
        hop_index=1, operation_digest=child.operation_digest,
        envelope_digest=child.digest,
        next_envelope_digest=terminal_env.digest,
        decision_receipt="4" * 64,
        status="refused" if refuse else "forwarded", downstream=terminal,
    )


def dispatcher():
    """Configure a bounded receiver-local allowlist for the two target hosts."""
    directory = native_directory()
    client = fake_client()
    source = NativeGroundDispatcher(directory, client, allowed_hosts=frozenset({
        ("peer-c", "host-peer-c"), ("peer-d", "host-peer-d")}))
    client.forward = lambda envelope, directory: native_receipt(envelope)
    return source, client


def quorum(root: Path):
    """Use three separate fsynced native anchor journals on one test machine."""
    membership = SeedCommitMembership(
        "sab007-machine", 1, ("owner", "anchor-b", "anchor-c"),
        "owner", 1, "f" * 64)
    authorities = {m: RecoveryLineageAuthority(membership, m, root / (m + ".jsonl"))
                   for m in membership.member_ids}
    return membership, authorities


def test_native_route_forward_and_quorum_recovery(tmp_path: Path) -> None:
    """A verified three-peer native route is sealed by a real durable quorum."""
    bridge, _client = dispatcher()
    target, address = intent(), address_for(intent())
    selected = bridge.prepare(target, address, origin_sequence=1)
    assert selected.envelope.route.peer_path == ("peer-a", "peer-b", "peer-c")
    evidence = bridge.execute(selected)
    assert recheck_evidence(target, address, evidence) == evidence
    assert evidence["observed"] == expected_result(target)

    member, journals = quorum(tmp_path)
    coordinator = RecoveryLineageCoordinator(member, journals)
    storage = AtomicGroundEvidenceStore(tmp_path / "evidence")
    manifest, proof = seal_native_result(target, address, evidence,
                 coordinator=coordinator, storage=storage,
                 generation=1, predecessor_digest=member.genesis_state_digest)
    assert len(proof.decisions) >= member.quorum
    assert coordinator.high_water() == (1, manifest.digest)
    recovered = recover_native_result(target, address, manifest=manifest,
                                      proof=proof, coordinator=coordinator, storage=storage)
    assert recovered["observed"] == expected_result(target)
    assert recovered["reexecuted_computation"] is False
    assert storage.get(manifest.state_digest) == canonical_json(evidence)


def canonical_json(evidence):
    """Encode only finite canonical data as needed by the native immutable evidence store."""
    return json.dumps(evidence, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode()


def test_rehome_changes_native_route_not_intention_and_fences_stale_lineage(tmp_path: Path):
    """A new assignment carries the same Ground but advances the quorum state root."""
    bridge, _ = dispatcher()
    target = intent()
    addr = address_for(target)
    first = bridge.prepare(target, addr, origin_sequence=1)
    ev1 = bridge.execute(first)
    membership, journals = quorum(tmp_path)
    coordinator = RecoveryLineageCoordinator(membership, journals)
    storage = AtomicGroundEvidenceStore(tmp_path / "states")
    m1, p1 = seal_native_result(target, addr, ev1, coordinator=coordinator,
                               storage=storage, generation=1,
                               predecessor_digest=membership.genesis_state_digest)
    other = bridge.prepare(target, addr, origin_sequence=2,
                           excluded_hosts=frozenset({("peer-c", "host-peer-c")}))
    assert other.envelope.route.peer_path == ("peer-a", "peer-b", "peer-d")
    ev2 = bridge.execute(other)
    assert ev1["observed"] == ev2["observed"]
    assert ev1["ground_digest"] == ev2["ground_digest"]
    assert ev1["route_digest"] != ev2["route_digest"]
    m2, p2 = seal_native_result(target, addr, ev2, coordinator=coordinator,
                               storage=storage, generation=2, predecessor_digest=m1.digest)
    assert recover_native_result(target, addr, manifest=m2, proof=p2,
                                 coordinator=coordinator, storage=storage)["reexecuted_computation"] is False
    with pytest.raises(RecoveryLineageError, match="stale"):
        recover_native_result(target, addr, manifest=m1, proof=p1,
                              coordinator=coordinator, storage=storage)


def test_wrong_input_or_unapproved_remote_host_refuses_before_network():
    """An address cannot smuggle a different mathematical input or host selection."""
    bridge, client = dispatcher()
    client.forward = lambda *_: pytest.fail("forward must not run")
    with pytest.raises(GroundContinuityRefused, match="input differs"):
        bridge.prepare(intent(), address_for(intent(), mismatched_input=True), origin_sequence=1)
    with pytest.raises(GroundContinuityRefused, match="sequence"):
        bridge.prepare(intent(), address_for(intent()), origin_sequence=True)
    bridge.allowed_hosts = frozenset({("peer-unknown", "host")})
    with pytest.raises(GroundContinuityRefused, match="no locally admitted route"):
        bridge.prepare(intent(), address_for(intent()), origin_sequence=2)


def test_changed_directory_rejects_stale_plan_before_forwarding():
    """Peer revision updates make old route plans unusable without any receiver call."""
    bridge, client = dispatcher()
    selected = bridge.prepare(intent(), address_for(intent()), origin_sequence=1)
    client.forward = lambda *_: pytest.fail("forward must not run")
    snap = snapshot("peer-b", outgoing=("peer-c", "peer-d"), revision=2)
    bridge.directory._merge_verified_peer_snapshot(
        snap, authenticated_peer_id="peer-b", authenticated_server_name=snap.endpoint.tls_server_name)
    with pytest.raises(GroundContinuityRefused, match="changed before"):
        bridge.execute(selected)


def test_midflight_directory_change_refuses_success_ack():
    """An accepted remote effect cannot become a current-plan success after topology moves."""
    bridge, client = dispatcher()
    selected = bridge.prepare(intent(), address_for(intent()), origin_sequence=1)
    def mutate(envelope, directory):
        """Simulate a revision change during native dispatch, then provide an old receipt."""
        snap = snapshot("peer-b", outgoing=("peer-c", "peer-d"), revision=2)
        directory._merge_verified_peer_snapshot(snap, authenticated_peer_id="peer-b",
                         authenticated_server_name=snap.endpoint.tls_server_name)
        return native_receipt(envelope)
    client.forward = mutate
    with pytest.raises(GroundContinuityRefused, match="changed during"):
        bridge.execute(selected)


def test_corrupt_or_refused_terminal_cannot_be_sealed(tmp_path: Path):
    """Receipt chain alone never supplies semantic authorization or exact output."""
    bridge, client = dispatcher()
    selected = bridge.prepare(intent(), address_for(intent()), origin_sequence=1)
    client.forward = lambda envelope, directory: native_receipt(envelope, corrupt=True)
    with pytest.raises(GroundContinuityRefused, match="terminal result"):
        bridge.execute(selected)
    client.forward = lambda envelope, directory: native_receipt(envelope, refuse=True)
    with pytest.raises(GroundContinuityRefused, match="did not commit"):
        bridge.execute(selected)
    storage = AtomicGroundEvidenceStore(tmp_path / "evidence")
    membership, journals = quorum(tmp_path)
    with pytest.raises(GroundContinuityRefused, match="schema"):
        seal_native_result(intent(), address_for(intent()), {"schema": "fake"},
                           coordinator=RecoveryLineageCoordinator(membership, journals),
                           storage=storage, generation=1,
                           predecessor_digest=membership.genesis_state_digest)


def test_missing_quorum_does_not_create_accepted_result_and_can_retry(tmp_path: Path):
    """Prepared bytes do not become committed evidence until a durable majority signs."""
    bridge, _ = dispatcher()
    target, addr = intent(), address_for(intent())
    ev = bridge.execute(bridge.prepare(target, addr, origin_sequence=1))
    membership, journals = quorum(tmp_path)
    storage = AtomicGroundEvidenceStore(tmp_path / "evidence")
    only_owner = RecoveryLineageCoordinator(membership, {"owner": journals["owner"]})
    with pytest.raises(RecoveryLineageError, match="prepare quorum"):
        seal_native_result(target, addr, ev, coordinator=only_owner,
                           storage=storage, generation=1,
                           predecessor_digest=membership.genesis_state_digest)
    assert list((tmp_path / "evidence").glob("*.json")), "prepared bytes are durable"
    full = RecoveryLineageCoordinator(membership, journals)
    manifest, proof = seal_native_result(target, addr, ev, coordinator=full,
                                        storage=storage, generation=1,
                                        predecessor_digest=membership.genesis_state_digest)
    assert recover_native_result(target, addr, manifest=manifest, proof=proof,
                                 coordinator=full, storage=storage)["observed"] == expected_result(target)


def test_tampered_payload_and_duplicate_generation_rejected(tmp_path: Path):
    """State bytes and quorum generation both independently reject conflicting recovery."""
    bridge, _ = dispatcher()
    target, addr = intent(), address_for(intent())
    evidence = bridge.execute(bridge.prepare(target, addr, origin_sequence=1))
    membership, journals = quorum(tmp_path)
    coordinator = RecoveryLineageCoordinator(membership, journals)
    storage = AtomicGroundEvidenceStore(tmp_path / "states")
    manifest, proof = seal_native_result(target, addr, evidence,
                       coordinator=coordinator, storage=storage, generation=1,
                       predecessor_digest=membership.genesis_state_digest)
    with pytest.raises(GroundContinuityRefused, match="contradictory"):
        changed = dict(evidence)
        changed["origin_sequence"] += 1
        # `recheck_evidence` refuses an altered native envelope *before* quorum.
        seal_native_result(target, addr, changed, coordinator=coordinator,
                          storage=storage, generation=1,
                          predecessor_digest=membership.genesis_state_digest)
    path = storage.directory / f"{manifest.state_digest}.json"
    path.write_bytes(b"corrupted")
    with pytest.raises(GroundContinuityRefused, match="no longer match"):
        recover_native_result(target, addr, manifest=manifest, proof=proof,
                              coordinator=coordinator, storage=storage)


def test_changed_ground_cannot_recover_same_receipt(tmp_path: Path):
    """A different mathematical description is incompatible with the stored state root."""
    bridge, _ = dispatcher()
    target, addr = intent(), address_for(intent())
    evidence = bridge.execute(bridge.prepare(target, addr, origin_sequence=1))
    membership, journals = quorum(tmp_path)
    coordinator = RecoveryLineageCoordinator(membership, journals)
    storage = AtomicGroundEvidenceStore(tmp_path / "states")
    manifest, proof = seal_native_result(target, addr, evidence,
                       coordinator=coordinator, storage=storage, generation=1,
                       predecessor_digest=membership.genesis_state_digest)
    different = CompositeIntent("sab007-intent", 5, 7, 65521, 20, 10**15 + 137)
    with pytest.raises(GroundContinuityRefused):
        recover_native_result(different, addr, manifest=manifest, proof=proof,
                              coordinator=coordinator, storage=storage)