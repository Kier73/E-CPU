"""Real E-CPU registry/provenance integration for portable similarity memories.

Requires the GEOMETRY-FIRST-008 version of VGI, installed in the optional CI
workflow; these tests do not silently fall back to the default older VGI extra.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

pytest.importorskip("vgi.structural_memory")

from mailcpu import (
    Capability, HeadlessOS, HypervisorAction, HypervisorPolicy,
    LexicalDecisionModel, OperatorRegistry, SystemIdentity, SystemSeed,
    SystemSeedEnvelope, VirtualBudget, VirtualGroundRef, VirtualLayerRuntime,
    VirtualLayerWorkload, VirtualOperatorRef,
)
from mailcpu.structural_memory import (
    StructuralMemoryAuthorizationError, StructuralMemoryConflict,
    StructuralMemoryRegistry, StructuralMemoryRefused,
)
from mailcpu.journal import EventJournal
from mailcpu.vgi_similarity_host import (
    SimilarityHostError, SIMILARITY_OPERATOR_ID, SIMILARITY_REQUEST_SCHEMA,
    make_vgi_similarity_operator,
)
from mailcpu.vgi_similarity_native_memory import (
    NATIVE_DOMAIN, NativeSimilarityCatalogue, NativeSimilarityPin,
    admit_native_similarity_revision,
)
from mailcpu.transit_vgi_similarity import (
    TransitVGISimilarityHost, build_vgi_similarity_event,
)
from vgi.structural_memory import (
    admit_similarity_memory, export_similarity_memory,
)
from vgi.typed_operator_navigation import (
    DenseMap, OperatorChain, PreparedTemporalOperator, TypedVector,
)
from examples.vgi_similarity_transfer_process import build_lab_ground


def _source():
    graph, _cert, payload = build_lab_ground()
    memory = admit_similarity_memory(payload, expected_graph_fingerprint=graph.fingerprint)
    return graph, payload, memory


def _admit(registry, record, memory, *, expected_revision=0, memory_id="similarity-ground",
           provenance_label="trusted-research-authority"):
    return admit_native_similarity_revision(
        registry, record, memory_id=memory_id, expected_revision=expected_revision,
        expected_memory_sha256=memory.memory_sha256,
        expected_graph_fingerprint=memory.graph_fingerprint,
        provenance_label=provenance_label,
    )


def _host():
    host = HeadlessOS(structural_memory_admission_policy=lambda proposal:
        proposal.spec.domain == NATIVE_DOMAIN
        and proposal.spec.context.get("provenance_label") == "trusted-research-authority"
    )
    host.hypervisor.classifier = LexicalDecisionModel()
    host.hypervisor.policy = HypervisorPolicy(embedding_review_confidence=1.0)
    identity = SystemIdentity("native-similarity-system", 1)
    seed = SystemSeedEnvelope(
        identity, "receiver", "native-math-memory", SystemSeed.from_system(host),
    )
    assert host.seed_admission.admit(seed).accepted
    good = host.environment.kernel.spawn(
        "native-similarity-worker",
        capabilities=(
            Capability("/virtual-layer/operators", frozenset({"compute"})),
            Capability("/structural-memory/read", frozenset({"read"})),
        ),
        parent_pid=host.environment.init_pid,
    )
    bad = host.environment.kernel.spawn(
        "native-no-read-worker",
        capabilities=(Capability("/virtual-layer/operators", frozenset({"compute"})),),
        parent_pid=host.environment.init_pid,
    )
    return host, identity, seed, good, bad


def _workload(identity, seed, memory, *, tick=10**30 + 11):
    initial = TypedVector(memory.graph.domain, (2, 4, 8, 16, 32, 64))
    req = {
        "schema": SIMILARITY_REQUEST_SCHEMA,
        "memory_sha256": memory.memory_sha256,
        "graph_fingerprint": memory.graph_fingerprint,
        "initial": initial.to_dict(),
        "logical_tick": tick,
    }
    workload = VirtualLayerWorkload(
        workload_id="native-similarity-001",
        system=identity,
        ground=VirtualGroundRef.from_envelope(seed),
        intention={"goal": {"kind": "navigate-revision-pinned-similarity-ground"}},
        operators=(VirtualOperatorRef(SIMILARITY_OPERATOR_ID, 1, "cpu"),),
        input_value=req,
        budget=VirtualBudget(100_000, 1_000_000, 1_000),
        logical_time=7,
        eligible_nodes=("node-vgi",),
        max_hops=2,
    )
    return workload, initial


def test_native_revision_operator_requires_both_rights_and_binds_provenance():
    graph, payload, memory = _source()
    host, identity, seed, good, bad = _host()
    pin = _admit(host.structural_memory, payload, memory)
    catalogue = NativeSimilarityCatalogue(host, good, pin)
    workload, initial = _workload(identity, seed, memory)
    spec, handler = make_vgi_similarity_operator(catalogue)
    registry = OperatorRegistry()
    calls = []
    registry.register(spec, lambda value, task: (calls.append(task.workload_id) or handler(value, task)))
    runtime = VirtualLayerRuntime(registry, "node-vgi", frozenset({"cpu"}))
    first = runtime.execute_operator(host, good, "peer", "native", 1,
                                     workload.logical_time, workload, SIMILARITY_OPERATOR_ID)
    assert first.action is HypervisorAction.ALLOW
    assert first.executed is True
    effect = first.effect["result"]
    assert effect["native_structural_memory"]["revision"] == 1
    assert effect["native_structural_memory"]["spec_digest"] == pin.spec_digest
    assert effect["native_structural_memory"]["certificate_digest"] == pin.certificate_digest
    assert effect["computation_ground"]["memory_sha256"] == pin.memory_sha256
    assert effect["navigation"]["inner"]["result"]["values"] == list(
        PreparedTemporalOperator.from_chain(graph).state_at(initial, workload.input_value["logical_tick"]).result.values
    )
    replay = runtime.execute_operator(host, good, "peer", "native", 1,
                                      workload.logical_time, workload, SIMILARITY_OPERATOR_ID)
    assert replay.replayed is True
    assert replay.effect == first.effect
    assert calls == [workload.workload_id]
    assert host.environment.kernel.journal.verify()
    no_read = NativeSimilarityCatalogue(host, bad, pin)
    with pytest.raises(SimilarityHostError, match="read capability"):
        make_vgi_similarity_operator(no_read)[1](workload.input_value, workload)


def test_native_version_is_cas_guarded_and_its_parent_identity_is_preserved():
    graph, payload, memory = _source()
    host, identity, seed, good, bad = _host()
    first = _admit(host.structural_memory, payload, memory)
    with pytest.raises(StructuralMemoryConflict):
        _admit(host.structural_memory, payload, memory, expected_revision=0,
               provenance_label="different-authorization-context")
    # New version is allowed only by explicit native admission and CAS; the
    # original version can still be addressed historically by its exact pin.
    graph2 = OperatorChain((DenseMap(
        graph.factors[0].identity + "-changed", graph.domain, graph.domain,
        tuple(tuple((2 * value) % graph.domain.modulus for value in row)
              for row in graph.factors[0].rows),
    ),) + graph.factors[1:])
    renewed = memory.rebind(graph2)
    payload2 = export_similarity_memory(renewed.certificate)
    second = _admit(host.structural_memory, payload2, renewed, expected_revision=1)
    latest = host.structural_memory.version_for_revision(first.memory_id, 2)
    older = host.structural_memory.version_for_revision(first.memory_id, 1)
    assert second.revision == 2
    assert latest.spec.parent_digest == older.spec.digest
    assert second.spec_digest != first.spec_digest
    old = NativeSimilarityCatalogue(host, good, first)
    new = NativeSimilarityCatalogue(host, good, second)
    assert old.resolve(first.memory_sha256, first.graph_fingerprint).memory_sha256 == first.memory_sha256
    assert new.resolve(second.memory_sha256, second.graph_fingerprint).memory_sha256 == second.memory_sha256
    with pytest.raises(SimilarityHostError, match="pinned native Ground"):
        new.resolve(first.memory_sha256, first.graph_fingerprint)
    with pytest.raises(SimilarityHostError, match="superseded"):
        NativeSimilarityCatalogue(host, good, first, require_active=True)


def test_explicit_host_policy_can_refuse_native_mathematical_admission():
    graph, record, memory = _source()
    registry = StructuralMemoryRegistry(admission_policy=lambda proposal: False)
    with pytest.raises(StructuralMemoryAuthorizationError):
        _admit(registry, record, memory)
    assert registry.active_version("similarity-ground") is None


def test_wrong_provenance_pin_refuses_even_when_mathematics_is_self_consistent():
    graph, record, memory = _source()
    registry = StructuralMemoryRegistry(admission_policy=lambda proposal: True)
    with pytest.raises(SimilarityHostError):
        admit_native_similarity_revision(registry, record,
            memory_id="similarity-ground", expected_revision=0,
            expected_memory_sha256="0" * 64,
            expected_graph_fingerprint=memory.graph_fingerprint,
            provenance_label="trusted-research-authority")
    assert registry.active_version("similarity-ground") is None
    pin = _admit(registry, record, memory)
    with pytest.raises(SimilarityHostError):
        NativeSimilarityPin(pin.memory_id, pin.revision, "not-hash", pin.certificate_digest,
                            pin.memory_sha256, pin.graph_fingerprint)


def test_native_journal_checkpoint_reconstructs_a_fresh_receiver_without_discovery(tmp_path):
    graph, record, memory = _source()
    journal = EventJournal()
    registry = StructuralMemoryRegistry(
        admission_policy=lambda proposal: proposal.spec.domain == NATIVE_DOMAIN,
        journal=journal,
    )
    pin = _admit(registry, record, memory)
    snapshot = registry.snapshot()
    durable = {"registry": snapshot, "journal": journal.snapshot(), "pin": pin.to_dict()}
    location = tmp_path / "native-similarity-checkpoint.json"
    location.write_text(json.dumps(durable, sort_keys=True))
    loaded = json.loads(location.read_text())
    recovered = StructuralMemoryRegistry.from_snapshot(
        loaded["registry"], admission_policy=lambda proposal: proposal.spec.domain == NATIVE_DOMAIN,
        journal=EventJournal.from_snapshot(loaded["journal"]),
    )
    receiver = SimpleNamespace(
        structural_memory=recovered,
        environment=SimpleNamespace(kernel=SimpleNamespace(
            _process=lambda pid: SimpleNamespace(capabilities=(
                Capability("/structural-memory/read", frozenset({"read"})),
            )),
        )),
    )
    from vgi.similarity_blocks import CertifiedSimilarityBlocks
    original = CertifiedSimilarityBlocks.__dict__["discover"]
    try:
        CertifiedSimilarityBlocks.discover = classmethod(
            lambda cls, *args, **kwargs: (_ for _ in ()).throw(
                AssertionError("a recovered observer must not search for a basis")))
        catalogue = NativeSimilarityCatalogue(receiver, 19, NativeSimilarityPin(**loaded["pin"]))
        admitted = catalogue.resolve(memory.memory_sha256, memory.graph_fingerprint)
        initial = TypedVector(admitted.graph.domain, (2, 4, 8, 16, 32, 64))
        expected = memory.state_at(initial, 10**30 + 11)
        assert admitted.state_at(initial, 10**30 + 11) == expected
        assert recovered.journal.verify()
    finally:
        CertifiedSimilarityBlocks.discover = original
    loaded["registry"]["journal_anchor"]["digest"] = "0" * 64
    with pytest.raises(Exception):
        StructuralMemoryRegistry.from_snapshot(
            loaded["registry"], journal=EventJournal.from_snapshot(loaded["journal"]))


def test_native_catalogue_is_compatible_with_existing_transit_backend_contract():
    graph, record, memory = _source()
    host, identity, seed, good, bad = _host()
    pin = _admit(host.structural_memory, record, memory)
    native = NativeSimilarityCatalogue(host, good, pin)
    node = TransitVGISimilarityHost(host, good, native, node_id="node-vgi")
    workload, _ = _workload(identity, seed, memory)
    event = build_vgi_similarity_event(workload, "peer", "native", 1, workload.logical_time)
    assert node.registry.contract(SIMILARITY_OPERATOR_ID, 1).digest == \
        make_vgi_similarity_operator(native)[0].digest
    assert event.request.resource == node.resource_name
    assert len(node.implementation_fingerprint) == 64


def test_recovered_native_registry_on_independent_interpreter_process(tmp_path):
    """Real second interpreter loads checkpoint, verifies journal, never rediscovering."""
    graph, record, memory = _source()
    journal = EventJournal()
    registry = StructuralMemoryRegistry(
        admission_policy=lambda proposal: proposal.spec.domain == NATIVE_DOMAIN,
        journal=journal,
    )
    pin = _admit(registry, record, memory)
    document = {"registry": registry.snapshot(), "journal": journal.snapshot(),
                "pin": pin.to_dict()}
    path = tmp_path / "sealed-native-revision.json"
    path.write_text(json.dumps(document, sort_keys=True), encoding="utf-8")
    pbytes = json.dumps(pin.to_dict(), sort_keys=True, separators=(",", ":")).encode()
    pin_sha = hashlib.sha256(pbytes).hexdigest()
    source = TypedVector(graph.domain, (2, 4, 8, 16, 32, 64))
    target_tick = 10**30 + 11
    repo_root = Path(__file__).resolve().parents[1]
    output = subprocess.run(
        [sys.executable, "-m", "examples.verify_native_similarity_revision",
         str(path), pin_sha, json.dumps(list(source.values)), str(target_tick)],
        cwd=repo_root, capture_output=True, text=True, timeout=35, check=True,
    )
    received = json.loads(output.stdout)
    assert received["process_id"] != os.getpid()
    assert received["native_pin"] == pin.to_dict()
    assert received["rediscovery"] is False
    assert received["navigation"] == memory.state_at(source, target_tick).to_dict()
    assert received["transit_execution_ledger_replay"] == "not_tested_here"
    document["registry"]["journal_anchor"]["digest"] = "0" * 64
    path.write_text(json.dumps(document, sort_keys=True), encoding="utf-8")
    refused = subprocess.run(
        [sys.executable, "-m", "examples.verify_native_similarity_revision",
         str(path), pin_sha, json.dumps(list(source.values)), str(target_tick)],
        cwd=repo_root, capture_output=True, text=True, timeout=35,
    )
    assert refused.returncode != 0