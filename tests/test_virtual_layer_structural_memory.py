from __future__ import annotations

from dataclasses import replace

import pytest

from mailcpu import (
    Capability,
    HeadlessOS,
    HypervisorAction,
    HypervisorPolicy,
    LexicalDecisionModel,
    OperatorRegistry,
    OperatorSpec,
    ReliabilityPolicy,
    ReliableChannel,
    SocketTransport,
    SystemIdentity,
    SystemSeed,
    SystemSeedEnvelope,
    VirtualBudget,
    VirtualGroundRef,
    VirtualLayerError,
    VirtualLayerRuntime,
    VirtualLayerWorkload,
    VirtualOperatorRef,
    VirtualStructuralMemoryRef,
    HypervisorOperationChannel,
)
from mailcpu.law_certifier import Law


_READ_RESOURCE = "/structural-memory/read"


def _ground(operating_system: HeadlessOS):
    identity = SystemIdentity("vl-structural-memory-system", 1)
    seed = SystemSeed.from_system(operating_system)
    envelope = SystemSeedEnvelope(identity, "test-origin", "virtual-layer", seed)
    assert operating_system.seed_admission.admit(envelope).accepted
    return identity, envelope, VirtualGroundRef.from_envelope(envelope)


def _admit_memory(operating_system: HeadlessOS, memory_id: str = "counter-memory"):
    law = Law(
        family="int",
        params={"x0": 11, "step": 7, "mod": 251},
        order=1,
        verdict="GROUND",
    )
    proposal = operating_system.structural_memory.propose(
        memory_id,
        law,
        {0: 11, 1: 18, 2: 25, 3: 32},
        domain="integer-orbit",
        context={"tenant": "alpha", "partition": 3},
    )
    return operating_system.structural_memory.admit(
        proposal.proposal_id,
        expected_revision=0,
    )


def _operator(calls: list[object]) -> OperatorSpec:
    return OperatorSpec(
        operator_id="core.add_structural",
        version=1,
        description="Add an offset to a receiver-resolved structural-memory value",
        input_kind="object",
        output_kind="integer",
        substrates=("cpu",),
        required_rights=frozenset({"compute"}),
        base_energy=8,
        energy_per_byte=1,
        max_input_bytes=20_000,
        max_output_bytes=64,
        deterministic=True,
        effect_mode="pure",
    )


def _registry(calls: list[object]) -> OperatorRegistry:
    registry = OperatorRegistry()
    registry.register(
        _operator(calls),
        lambda value, workload: (
            calls.append(workload.workload_id)
            or value["input"]["offset"]
            + value["structural_memory"]["counter"]["value"]
        ),
    )
    return registry


def _workload(identity, ground, memory_ref, *, workload_id="w-memory-1"):
    return VirtualLayerWorkload(
        workload_id=workload_id,
        system=identity,
        ground=ground,
        intention={"goal": {"equals": 84}},
        operators=(
            VirtualOperatorRef(
                "core.add_structural",
                1,
                "cpu",
                None,
                (memory_ref,),
            ),
        ),
        input_value={"offset": 3},
        budget=VirtualBudget(50_000, 20_000, 1_000),
        logical_time=9,
        eligible_nodes=("node-a",),
        max_hops=1,
        schema_version=2,
    )


def _worker_pid(operating_system: HeadlessOS, *, read: bool = True, compute: bool = True) -> int:
    capabilities = []
    if compute:
        capabilities.append(Capability("/virtual-layer/operators", frozenset({"compute"})))
    if read:
        capabilities.append(Capability(_READ_RESOURCE, frozenset({"read"})))
    return operating_system.environment.kernel.spawn(
        "virtual-layer-structural-memory-worker",
        capabilities=tuple(capabilities),
        parent_pid=operating_system.environment.init_pid,
    )


def _read_events(operating_system: HeadlessOS):
    return [
        record for record in operating_system.environment.kernel.journal.records()
        if record.kind == "structural_memory.read_revision"
    ]


def test_structural_memory_reference_round_trips_and_requires_schema_v2() -> None:
    operating_system = HeadlessOS(
        structural_memory_admission_policy=lambda proposal: proposal.spec.domain == "integer-orbit"
    )
    _, _, ground = _ground(operating_system)
    version = _admit_memory(operating_system)
    reference = VirtualStructuralMemoryRef.from_version("counter", version, 10)

    workload = _workload(SystemIdentity("vl-structural-memory-system", 1), ground, reference)
    restored = VirtualLayerWorkload.from_dict(workload.to_dict())
    assert restored.digest == workload.digest
    assert restored.to_dict() == workload.to_dict()
    assert restored.operators[0].structural_memory[0] == reference
    assert reference.to_dict()["spec_digest"] == version.spec.digest
    assert reference.to_dict()["certificate_digest"] == version.certificate.digest

    with pytest.raises(VirtualLayerError, match="schema version 2"):
        replace(workload, schema_version=1)

    corrupted = reference.to_dict() | {"spec_digest": "not-a-digest"}
    with pytest.raises(VirtualLayerError, match="SHA-256"):
        VirtualStructuralMemoryRef.from_dict(corrupted)


def test_local_operator_receives_pinned_value_and_receipt() -> None:
    operating_system = HeadlessOS(
        structural_memory_admission_policy=lambda proposal: proposal.spec.domain == "integer-orbit"
    )
    operating_system.hypervisor.classifier = LexicalDecisionModel()
    operating_system.hypervisor.policy = HypervisorPolicy(embedding_review_confidence=1.0)
    identity, _, ground = _ground(operating_system)
    version = _admit_memory(operating_system)
    reference = VirtualStructuralMemoryRef.from_version("counter", version, 10)
    workload = _workload(identity, ground, reference)
    calls: list[object] = []
    runtime = VirtualLayerRuntime(_registry(calls), "node-a", frozenset({"cpu"}))
    pid = _worker_pid(operating_system)

    first = runtime.execute_operator(
        operating_system, pid, "origin", "vl-memory", 1,
        workload.logical_time, workload, "core.add_structural",
    )
    assert first.action is HypervisorAction.ALLOW
    assert first.executed is True
    assert first.effect["result"] == 84
    assert first.effect["structural_memory_receipts"]["counter"]["memory_id"] == "counter-memory"
    assert first.effect["structural_memory_receipts"]["counter"]["revision"] == 1
    assert first.effect["structural_memory_receipts"]["counter"]["coordinate"] == 10
    assert first.effect["structural_memory_receipts"]["counter"]["spec_digest"] == version.spec.digest
    assert len(first.effect["resolved_input_digest"]) == 64
    assert len(calls) == 1
    assert len(_read_events(operating_system)) == 1

    replay = runtime.execute_operator(
        operating_system, pid, "origin", "vl-memory", 1,
        workload.logical_time, workload, "core.add_structural",
    )
    assert replay.replayed is True
    assert replay.effect == first.effect
    assert len(calls) == 1
    assert len(_read_events(operating_system)) == 1
    assert operating_system.environment.kernel.journal.verify()


def test_structural_memory_binding_refuses_missing_read_authority_and_digest_mismatch() -> None:
    operating_system = HeadlessOS(
        structural_memory_admission_policy=lambda proposal: proposal.spec.domain == "integer-orbit"
    )
    operating_system.hypervisor.classifier = LexicalDecisionModel()
    operating_system.hypervisor.policy = HypervisorPolicy(embedding_review_confidence=1.0)
    identity, _, ground = _ground(operating_system)
    version = _admit_memory(operating_system)
    reference = VirtualStructuralMemoryRef.from_version("counter", version, 10)
    calls: list[object] = []
    runtime = VirtualLayerRuntime(_registry(calls), "node-a", frozenset({"cpu"}))

    no_read_workload = _workload(identity, ground, reference)
    with pytest.raises(VirtualLayerError, match="lacks 'read'"):
        runtime.execute_operator(
            operating_system, _worker_pid(operating_system, read=False),
            "origin", "vl-memory", 1, 9, no_read_workload, "core.add_structural",
        )
    assert len(_read_events(operating_system)) == 0
    assert calls == []

    wrong_pin = replace(reference, spec_digest="0" * 64)
    wrong_workload = _workload(identity, ground, wrong_pin, workload_id="w-memory-bad-pin")
    with pytest.raises(VirtualLayerError, match="pinned reference"):
        runtime.execute_operator(
            operating_system, _worker_pid(operating_system),
            "origin", "vl-memory", 2, 9, wrong_workload, "core.add_structural",
        )
    assert calls == []
    assert len(_read_events(operating_system)) == 1


def _tcp_pair():
    listener = SocketTransport.listen("127.0.0.1", 0)
    port = listener.getsockname()[1]
    origin = SocketTransport.connect("127.0.0.1", port, "origin", "replica")
    replica = SocketTransport.accept(listener, "replica", "origin")
    listener.close()
    return origin, replica


def test_remote_virtual_layer_resolves_memory_only_at_receiver() -> None:
    origin_transport, receiver_transport = _tcp_pair()
    policy = ReliabilityPolicy(lease_ticks=1, max_attempts=3, window_size=4)
    origin_channel = HypervisorOperationChannel(
        ReliableChannel(origin_transport, "origin", "replica", "vl-memory", policy)
    )
    receiver_channel = HypervisorOperationChannel(
        ReliableChannel(receiver_transport, "replica", "replica", "vl-memory", policy, peer="origin")
    )

    origin_os = HeadlessOS()
    receiver_os = HeadlessOS(
        structural_memory_admission_policy=lambda proposal: proposal.spec.domain == "integer-orbit"
    )
    origin_os.hypervisor.classifier = LexicalDecisionModel()
    receiver_os.hypervisor.classifier = LexicalDecisionModel()
    identity, envelope, ground = _ground(origin_os)
    assert receiver_os.seed_admission.admit(envelope).accepted

    # The only structural-memory registry entry is on the receiving node.
    version = _admit_memory(receiver_os)
    reference = VirtualStructuralMemoryRef.from_version("counter", version, 10)
    workload = _workload(identity, ground, reference)
    calls: list[object] = []

    sender_catalog = OperatorRegistry()
    sender_catalog.declare(_operator([]))
    receiver_catalog = _registry(calls)
    sender_runtime = VirtualLayerRuntime(sender_catalog, "origin-node", frozenset({"cpu"}))
    receiver_runtime = VirtualLayerRuntime(receiver_catalog, "node-a", frozenset({"cpu"}))
    event = sender_runtime.build_event(
        "origin", "vl-memory", 1, workload.logical_time, workload, "core.add_structural"
    )
    worker_pid = _worker_pid(receiver_os)

    try:
        assert origin_channel.send(event) == 1
        origin_transport.service()
        result = receiver_runtime.receive_and_execute(receiver_channel, receiver_os, worker_pid)
        assert result is not None
        assert result.action is HypervisorAction.ALLOW
        assert result.executed is True
        assert result.effect["result"] == 84
        assert result.effect["node_id"] == "node-a"
        assert result.effect["structural_memory_receipts"]["counter"]["spec_digest"] == version.spec.digest
        assert len(calls) == 1
        assert len(_read_events(receiver_os)) == 1
        assert origin_os.structural_memory.active_version("counter-memory") is None
        assert receiver_os.environment.kernel.journal.verify()
    finally:
        for transport in (origin_transport, receiver_transport):
            if not transport.closed:
                transport.close()
