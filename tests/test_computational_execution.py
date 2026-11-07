from __future__ import annotations

from dataclasses import replace

import pytest

from mailcpu import (
    Capability,
    ComputationalAddress,
    ComputationalAddressResolver,
    ComputationalExecutionAdmissionCoordinator,
    ComputationalExecutionStatus,
    ComputationalHostCatalogue,
    ComputationalHostLocus,
    ComputationalResolutionStatus,
    HeadlessOS,
    OperatorRegistry,
    OperatorSpec,
    RouteMetric,
    RouteMetricKey,
    SystemIdentity,
    SystemSeed,
    SystemSeedEnvelope,
    VirtualBudget,
    VirtualLayerRuntime,
    VirtualLayerWorkload,
    VirtualGroundRef,
    VirtualOperatorRef,
)
from mailcpu.classifier import HypervisorAction, HypervisorDomain
from mailcpu.virtual_layer import VirtualLayerError

GROUND_FP = "a" * 64
PROGRAM_FP = "b" * 64
METRICS = (
    RouteMetricKey("latency", "ticks"),
    RouteMetricKey("energy", "units"),
    RouteMetricKey("bytes", "bytes"),
    RouteMetricKey("risk", "score"),
)


def _admitted(operating_system: HeadlessOS):
    identity = SystemIdentity("computational-execution-system", 1)
    seed = SystemSeed.from_system(operating_system)
    envelope = SystemSeedEnvelope(
        identity,
        "computational-execution",
        "computational-execution",
        seed,
    )
    result = operating_system.seed_admission.admit(envelope)
    assert result.accepted
    return identity, VirtualGroundRef.from_envelope(envelope)


def _spec() -> OperatorSpec:
    return OperatorSpec(
        operator_id="core.sum_pair",
        version=1,
        description="Add two integers from a JSON object",
        input_kind="object",
        output_kind="integer",
        substrates=("cpu", "gpu"),
        required_rights=frozenset({"compute"}),
        base_energy=8,
        energy_per_byte=1,
        max_input_bytes=4096,
        max_output_bytes=64,
        deterministic=True,
        effect_mode="pure",
    )


def _runtime(node_id: str, calls: list[str]) -> VirtualLayerRuntime:
    registry = OperatorRegistry()
    spec = _spec()

    def execute(value, workload):
        calls.append(workload.workload_id)
        return value["left"] + value["right"]

    registry.register(spec, execute)
    return VirtualLayerRuntime(registry, node_id, frozenset({"cpu"}))


def _costs(latency: int):
    return (
        RouteMetric("latency", "ticks", latency),
        RouteMetric("energy", "units", 20),
        RouteMetric("bytes", "bytes", 128),
        RouteMetric("risk", "score", 0),
    )


def _workload(identity, ground):
    return VirtualLayerWorkload(
        workload_id="computational-execution-workload",
        system=identity,
        ground=ground,
        intention={"goal": {"kind": "sum", "expected": 9}},
        operators=(VirtualOperatorRef("core.sum_pair", 1, "cpu"),),
        input_value={"left": 4, "right": 5},
        budget=VirtualBudget(10_000, 10_000, 1_000),
        logical_time=41,
        eligible_nodes=("node-a",),
        max_hops=1,
    )


def _fixture():
    operating_system = HeadlessOS()
    identity, ground = _admitted(operating_system)
    calls: list[str] = []
    runtime = _runtime("node-a", calls)
    pid = operating_system.environment.kernel.spawn(
        "computational-execution-host",
        capabilities=(Capability("/virtual-layer/operators", frozenset({"compute"})),),
        parent_pid=operating_system.environment.init_pid,
    )
    locus = ComputationalHostLocus.from_runtime(
        host_id="logical-host-a",
        runtime=runtime,
        authority_pid=pid,
        operator_id="core.sum_pair",
        computational_ground_fingerprints=(GROUND_FP,),
        program_fingerprints=(PROGRAM_FP,),
        costs=_costs(3),
        implementation_fingerprint="c" * 64,
    )
    catalogue = ComputationalHostCatalogue((locus,))
    address = ComputationalAddress.from_workload(
        _workload(identity, ground),
        "core.sum_pair",
        _spec(),
        GROUND_FP,
        program_fingerprint=PROGRAM_FP,
        metric_order=METRICS,
    )
    resolution = ComputationalAddressResolver().resolve(address, catalogue, operating_system)
    assert resolution.status is ComputationalResolutionStatus.FOUND
    assert resolution.witness is not None
    coordinator = ComputationalExecutionAdmissionCoordinator(operating_system)
    return operating_system, calls, runtime, catalogue, address, resolution.witness, coordinator


def test_execution_revalidates_witness_and_exact_replay_does_not_reenter_operator() -> None:
    (
        operating_system,
        calls,
        runtime,
        catalogue,
        address,
        witness,
        coordinator,
    ) = _fixture()

    first = coordinator.execute(
        address,
        witness,
        catalogue,
        runtime,
        source="semantic-client",
        channel="computational.execution",
        sequence=1,
    )
    replay = coordinator.execute(
        address,
        witness,
        catalogue,
        runtime,
        source="semantic-client",
        channel="computational.execution",
        sequence=1,
    )

    assert first.status is ComputationalExecutionStatus.EXECUTED
    assert first.accepted and first.executed and not first.replayed
    assert first.execution is not None
    assert first.execution.action is HypervisorAction.ALLOW
    assert first.execution.domain is HypervisorDomain.CPU
    assert first.execution.effect["result"] == 9
    assert first.execution.effect["kind"] == "virtual_layer.operator_result"
    assert replay.status is ComputationalExecutionStatus.REPLAYED
    assert replay.accepted and replay.executed and replay.replayed
    assert replay.execution is not None
    assert replay.execution.fingerprint == first.execution.fingerprint
    assert replay.admission_digest == first.admission_digest
    assert calls == ["computational-execution-workload"]
    assert first.admission_receipt
    assert operating_system.environment.kernel.journal.snapshot()


def test_execution_refuses_stale_witness_after_catalogue_change() -> None:
    (
        operating_system,
        calls,
        runtime,
        catalogue,
        address,
        witness,
        coordinator,
    ) = _fixture()
    second_runtime = _runtime("node-a", [])
    second_pid = operating_system.environment.kernel.spawn(
        "new-cheaper-computational-host",
        capabilities=(Capability("/virtual-layer/operators", frozenset({"compute"})),),
        parent_pid=operating_system.environment.init_pid,
    )
    catalogue.register(
        ComputationalHostLocus.from_runtime(
            host_id="logical-host-b",
            runtime=second_runtime,
            authority_pid=second_pid,
            operator_id="core.sum_pair",
            computational_ground_fingerprints=(GROUND_FP,),
            program_fingerprints=(PROGRAM_FP,),
            costs=_costs(1),
        )
    )

    result = coordinator.execute(
        address,
        witness,
        catalogue,
        runtime,
        source="semantic-client",
        channel="computational.execution",
        sequence=2,
    )

    assert result.status is ComputationalExecutionStatus.WITNESS_STALE
    assert not result.accepted
    assert result.execution is None
    assert calls == []


def test_execution_refuses_runtime_that_does_not_match_selected_locus() -> None:
    (
        _operating_system,
        calls,
        _runtime,
        catalogue,
        address,
        witness,
        coordinator,
    ) = _fixture()
    mismatched_runtime = _runtime("node-b", calls)

    result = coordinator.execute(
        address,
        witness,
        catalogue,
        mismatched_runtime,
        source="semantic-client",
        channel="computational.execution",
        sequence=3,
    )

    assert result.status is ComputationalExecutionStatus.HOST_MISMATCH
    assert not result.accepted
    assert result.execution is None
    assert calls == []


def test_execution_preserves_declared_substrate_preference_order() -> None:
    operating_system = HeadlessOS()
    identity, ground = _admitted(operating_system)
    calls: list[str] = []
    spec = OperatorSpec(
        operator_id="core.sum_pair",
        version=1,
        description="Add two integers from a JSON object",
        input_kind="object",
        output_kind="integer",
        substrates=("gpu", "cpu"),
        required_rights=frozenset({"compute"}),
        base_energy=8,
        energy_per_byte=1,
        max_input_bytes=4096,
        max_output_bytes=64,
        deterministic=True,
        effect_mode="pure",
    )
    registry = OperatorRegistry()

    def execute(value, workload):
        calls.append(workload.workload_id)
        return value["left"] + value["right"]

    registry.register(spec, execute)
    runtime = VirtualLayerRuntime(registry, "node-a", frozenset({"cpu", "gpu"}))
    pid = operating_system.environment.kernel.spawn(
        "computational-execution-dual-substrate-host",
        capabilities=(Capability("/virtual-layer/operators", frozenset({"compute"})),),
        parent_pid=operating_system.environment.init_pid,
    )
    locus = ComputationalHostLocus.from_runtime(
        host_id="dual-substrate-host",
        runtime=runtime,
        authority_pid=pid,
        operator_id="core.sum_pair",
        computational_ground_fingerprints=(GROUND_FP,),
        program_fingerprints=(PROGRAM_FP,),
        costs=_costs(3),
    )
    catalogue = ComputationalHostCatalogue((locus,))
    workload = replace(
        _workload(identity, ground),
        operators=(VirtualOperatorRef("core.sum_pair", 1),),
    )
    address = ComputationalAddress.from_workload(
        workload,
        "core.sum_pair",
        spec,
        GROUND_FP,
        program_fingerprint=PROGRAM_FP,
        metric_order=METRICS,
    )
    resolution = ComputationalAddressResolver().resolve(address, catalogue, operating_system)
    assert resolution.status is ComputationalResolutionStatus.FOUND
    assert resolution.witness is not None
    assert resolution.witness.substrate == "gpu"

    outcome = ComputationalExecutionAdmissionCoordinator(operating_system).execute(
        address,
        resolution.witness,
        catalogue,
        runtime,
        source="semantic-client",
        channel="computational.execution",
        sequence=8,
    )

    assert outcome.status is ComputationalExecutionStatus.EXECUTED
    assert outcome.execution is not None
    assert outcome.execution.effect["substrate"] == "gpu"
    assert calls == [workload.workload_id]


def test_virtual_layer_rejects_malformed_computational_admission_context() -> None:
    (
        operating_system,
        _calls,
        runtime,
        _catalogue,
        address,
        _witness,
        _coordinator,
    ) = _fixture()

    with pytest.raises(VirtualLayerError):
        runtime.build_event(
            "semantic-client",
            "computational.execution",
            4,
            address.workload.logical_time,
            address.workload,
            address.operator_id,
            computational_admission={"schema": "mailcpu.computational-execution-admission.v1"},
        )

    assert operating_system.environment.kernel.journal.snapshot()
