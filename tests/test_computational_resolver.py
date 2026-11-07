from __future__ import annotations

from dataclasses import replace

import pytest

from mailcpu import (
    Capability,
    ComputationalAddress,
    ComputationalAddressResolver,
    ComputationalBlockerCode,
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
    VirtualGroundRef,
    VirtualLayerWorkload,
    VirtualOperatorRef,
    VirtualStructuralMemoryRef,
    VirtualLayerRuntime,
)

GROUND_FP = "a" * 64
PROGRAM_FP = "b" * 64
METRICS = (
    RouteMetricKey("latency", "ticks"),
    RouteMetricKey("energy", "units"),
    RouteMetricKey("bytes", "bytes"),
    RouteMetricKey("risk", "score"),
)


def _admitted(operating_system: HeadlessOS):
    identity = SystemIdentity("computational-resolver-system", 1)
    seed = SystemSeed.from_system(operating_system)
    envelope = SystemSeedEnvelope(identity, "resolver-executor", "computational-resolver", seed)
    admission = operating_system.seed_admission.admit(envelope)
    assert admission.accepted
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


def _workload(identity, ground, *, budget=None, eligible_nodes=("node-a",), operator_id="core.sum_pair"):
    return VirtualLayerWorkload(
        workload_id="resolver-workload",
        system=identity,
        ground=ground,
        intention={"goal": {"kind": "sum", "expected": 9}},
        operators=(VirtualOperatorRef(operator_id, 1, "cpu"),),
        input_value={"left": 4, "right": 5},
        budget=budget or VirtualBudget(10_000, 10_000, 1_000),
        logical_time=23,
        eligible_nodes=eligible_nodes,
        max_hops=4,
    )


def _runtime(
    node_id: str,
    calls: list[str] | None = None,
    substrates: tuple[str, ...] = ("cpu",),
) -> VirtualLayerRuntime:
    registry = OperatorRegistry()
    spec = _spec()

    def execute(value, workload):
        if calls is not None:
            calls.append(workload.workload_id)
        return value["left"] + value["right"]

    registry.register(spec, execute)
    return VirtualLayerRuntime(registry, node_id, frozenset(substrates))


def _costs(latency: int, energy: int = 20, byte_count: int = 128, risk: int = 0):
    return (
        RouteMetric("latency", "ticks", latency),
        RouteMetric("energy", "units", energy),
        RouteMetric("bytes", "bytes", byte_count),
        RouteMetric("risk", "score", risk),
    )


def _locus(
    host_id: str,
    operating_system: HeadlessOS,
    runtime: VirtualLayerRuntime,
    *,
    authority_pid: int,
    costs,
    ground: str = GROUND_FP,
    programs=(PROGRAM_FP,),
    dynamic_programs: bool = False,
    implementation: str | None = None,
):
    return ComputationalHostLocus.from_runtime(
        host_id=host_id,
        runtime=runtime,
        authority_pid=authority_pid,
        operator_id="core.sum_pair",
        computational_ground_fingerprints=(ground,),
        costs=costs,
        program_fingerprints=programs,
        supports_ground_program_compilation=dynamic_programs,
        implementation_fingerprint=implementation,
    )


def _address(workload, spec=None, *, ground: str = GROUND_FP, program: str | None = PROGRAM_FP, ceilings=()):
    return ComputationalAddress.from_workload(
        workload,
        "core.sum_pair",
        spec or _spec(),
        ground,
        program_fingerprint=program,
        metric_order=METRICS,
        resource_ceilings=ceilings,
    )


def _worker_pid(operating_system: HeadlessOS, *, granted: bool = True) -> int:
    capabilities = (
        (Capability("/virtual-layer/operators", frozenset({"compute"})),)
        if granted else
        (Capability("/unrelated", frozenset({"read"})),)
    )
    return operating_system.environment.kernel.spawn(
        "semantic-resolver-host",
        capabilities=capabilities,
        parent_pid=operating_system.environment.init_pid,
    )


def test_computational_address_round_trip_binds_workload_ground_program_and_state() -> None:
    operating_system = HeadlessOS()
    identity, ground = _admitted(operating_system)
    workload = _workload(identity, ground)
    address = _address(workload)

    restored = ComputationalAddress.from_dict(address.to_dict())

    assert restored == address
    assert restored.digest == address.digest
    assert restored.workload.digest == workload.digest
    assert restored.state_digest == address.state_digest
    assert restored.input_digest
    assert restored.workload.logical_time == 23


def test_resolver_selects_least_cost_live_host_and_returns_non_authoritative_witness() -> None:
    operating_system = HeadlessOS()
    identity, ground = _admitted(operating_system)
    calls: list[str] = []
    runtime_a = _runtime("node-a", calls)
    runtime_b = _runtime("node-a", calls)
    denied_pid = _worker_pid(operating_system, granted=False)
    allowed_pid = _worker_pid(operating_system)
    catalogue = ComputationalHostCatalogue((
        _locus("host-a-denied", operating_system, runtime_a, authority_pid=denied_pid, costs=_costs(1)),
        _locus("host-b-live", operating_system, runtime_b, authority_pid=allowed_pid, costs=_costs(8)),
    ))
    address = _address(_workload(identity, ground))
    before_journal = operating_system.environment.kernel.journal.snapshot()

    result = ComputationalAddressResolver().resolve(address, catalogue, operating_system)

    assert result.status is ComputationalResolutionStatus.FOUND
    assert result.authoritative is False
    assert result.witness is not None
    assert result.witness.authoritative is False
    assert result.witness.host_id == "host-b-live"
    assert result.witness.node_id == "node-a"
    assert result.witness.operator_contract_digest == _spec().digest
    assert result.witness.computational_ground_fingerprint == GROUND_FP
    assert result.witness.program_fingerprint == PROGRAM_FP
    assert result.witness.state_digest == address.state_digest
    assert result.witness.state_sources == ("inline-input",)
    assert any(item.code is ComputationalBlockerCode.AUTHORITY_MISSING for item in result.blockers)
    assert calls == []
    assert operating_system.environment.kernel.journal.snapshot() == before_journal


def test_resolver_uses_deterministic_host_id_tie_break_after_cost_vector() -> None:
    operating_system = HeadlessOS()
    identity, ground = _admitted(operating_system)
    runtime = _runtime("node-a")
    pid_a = _worker_pid(operating_system)
    pid_b = _worker_pid(operating_system)
    equal_costs = _costs(3, 30, 100, 1)
    catalogue = ComputationalHostCatalogue((
        _locus("host-z", operating_system, runtime, authority_pid=pid_b, costs=equal_costs),
        _locus("host-a", operating_system, runtime, authority_pid=pid_a, costs=equal_costs),
    ))

    result = ComputationalAddressResolver().resolve(
        _address(_workload(identity, ground)), catalogue, operating_system
    )

    assert result.status is ComputationalResolutionStatus.FOUND
    assert result.witness is not None
    assert result.witness.host_id == "host-a"


@pytest.mark.parametrize(
    ("ground", "program", "expected_code"),
    (
        ("c" * 64, (PROGRAM_FP,), ComputationalBlockerCode.GROUND_MISMATCH),
        (GROUND_FP, ("d" * 64,), ComputationalBlockerCode.PROGRAM_MISMATCH),
    ),
)
def test_resolver_refuses_incompatible_computational_ground_or_program(
    ground: str,
    program: tuple[str, ...],
    expected_code: ComputationalBlockerCode,
) -> None:
    operating_system = HeadlessOS()
    identity, system_ground = _admitted(operating_system)
    runtime = _runtime("node-a")
    pid = _worker_pid(operating_system)
    catalogue = ComputationalHostCatalogue((
        _locus(
            "host-a",
            operating_system,
            runtime,
            authority_pid=pid,
            costs=_costs(1),
            ground=ground,
            programs=program,
        ),
    ))

    result = ComputationalAddressResolver().resolve(
        _address(_workload(identity, system_ground)), catalogue, operating_system
    )

    assert result.status is ComputationalResolutionStatus.BLOCKED
    assert result.witness is None
    assert any(item.code is expected_code for item in result.blockers)


def test_resolver_refuses_wrong_node_substrate_and_stale_system_ground() -> None:
    operating_system = HeadlessOS()
    identity, ground = _admitted(operating_system)
    runtime = _runtime("node-b")
    pid = _worker_pid(operating_system)
    catalogue = ComputationalHostCatalogue((
        _locus("host-b", operating_system, runtime, authority_pid=pid, costs=_costs(1)),
    ))
    workload = _workload(identity, ground, eligible_nodes=("node-a",))

    placement = ComputationalAddressResolver().resolve(
        _address(workload), catalogue, operating_system
    )
    assert placement.status is ComputationalResolutionStatus.BLOCKED
    assert any(item.code is ComputationalBlockerCode.PLACEMENT_MISMATCH for item in placement.blockers)

    stale = replace(
        workload,
        ground=VirtualGroundRef(
            ground.origin_digest,
            ground.state_digest,
            ground.coordinate,
            "f" * 64,
        ),
    )
    stale_result = ComputationalAddressResolver().resolve(
        _address(stale), catalogue, operating_system
    )
    assert stale_result.status is ComputationalResolutionStatus.BLOCKED
    assert stale_result.blockers[0].host_id == "system-ground"
    assert stale_result.blockers[0].code is ComputationalBlockerCode.GROUND_MISMATCH

    gpu_runtime = _runtime("node-a", substrates=("gpu",))
    gpu_pid = _worker_pid(operating_system)
    gpu_catalogue = ComputationalHostCatalogue((
        _locus("gpu-only-host", operating_system, gpu_runtime, authority_pid=gpu_pid, costs=_costs(1)),
    ))
    substrate_result = ComputationalAddressResolver().resolve(
        _address(_workload(identity, ground)), gpu_catalogue, operating_system
    )
    assert substrate_result.status is ComputationalResolutionStatus.BLOCKED
    assert any(item.code is ComputationalBlockerCode.SUBSTRATE_MISMATCH for item in substrate_result.blockers)


def test_resolver_applies_address_cost_ceilings_and_workload_budgets() -> None:
    operating_system = HeadlessOS()
    identity, ground = _admitted(operating_system)
    runtime = _runtime("node-a")
    pid = _worker_pid(operating_system)
    catalogue = ComputationalHostCatalogue((
        _locus("host-a", operating_system, runtime, authority_pid=pid, costs=_costs(10, 20, 128, 1)),
    ))
    workload = _workload(identity, ground)
    address = _address(
        workload,
        ceilings=(RouteMetric("latency", "ticks", 5),),
    )

    route_limited = ComputationalAddressResolver().resolve(address, catalogue, operating_system)
    assert route_limited.status is ComputationalResolutionStatus.BUDGET_EXHAUSTED
    assert any(item.code is ComputationalBlockerCode.RESOURCE_LIMIT for item in route_limited.blockers)

    small_budget = replace(workload, budget=VirtualBudget(1, 10_000, 1_000))
    energy_limited = ComputationalAddressResolver().resolve(
        _address(small_budget), catalogue, operating_system
    )
    assert energy_limited.status is ComputationalResolutionStatus.BUDGET_EXHAUSTED


def test_resolver_reports_unreachable_operator_without_claiming_host_discovery() -> None:
    operating_system = HeadlessOS()
    identity, ground = _admitted(operating_system)
    workload = _workload(identity, ground)
    catalogue = ComputationalHostCatalogue()

    result = ComputationalAddressResolver().resolve(
        _address(workload), catalogue, operating_system
    )

    assert result.status is ComputationalResolutionStatus.UNREACHABLE
    assert result.candidate_count == 0
    assert result.witness is None


def test_resolver_refuses_missing_pinned_structural_memory_state() -> None:
    operating_system = HeadlessOS()
    identity, ground = _admitted(operating_system)
    memory_ref = VirtualStructuralMemoryRef(
        binding="left-state",
        memory_id="missing-memory",
        revision=1,
        context={"domain": "test"},
        coordinate=0,
        spec_digest="c" * 64,
        certificate_digest="d" * 64,
    )
    workload = VirtualLayerWorkload(
        workload_id="resolver-structural-memory",
        system=identity,
        ground=ground,
        intention={"goal": {"kind": "sum"}},
        operators=(
            VirtualOperatorRef(
                "core.sum_pair",
                1,
                "cpu",
                structural_memory=(memory_ref,),
            ),
        ),
        input_value={"right": 5},
        budget=VirtualBudget(10_000, 10_000, 1_000),
        logical_time=24,
        eligible_nodes=("node-a",),
        max_hops=4,
        schema_version=2,
    )
    runtime = _runtime("node-a")
    authority_pid = operating_system.environment.kernel.spawn(
        "structural-resolver-host",
        capabilities=(
            Capability("/virtual-layer/operators", frozenset({"compute"})),
            Capability("/structural-memory/read", frozenset({"read"})),
        ),
        parent_pid=operating_system.environment.init_pid,
    )
    locus = ComputationalHostLocus.from_runtime(
        host_id="host-memory",
        runtime=runtime,
        authority_pid=authority_pid,
        operator_id="core.sum_pair",
        computational_ground_fingerprints=(GROUND_FP,),
        costs=_costs(1),
        program_fingerprints=(PROGRAM_FP,),
        supports_structural_memory=True,
    )
    catalogue = ComputationalHostCatalogue((locus,))

    result = ComputationalAddressResolver().resolve(
        _address(workload), catalogue, operating_system
    )

    assert result.status is ComputationalResolutionStatus.BLOCKED
    assert any(item.code is ComputationalBlockerCode.STATE_UNAVAILABLE for item in result.blockers)


def test_resolver_requires_exact_program_pin_or_ground_bounded_compilation_policy() -> None:
    operating_system = HeadlessOS()
    identity, ground = _admitted(operating_system)
    runtime = _runtime("node-a")
    pid_exact = _worker_pid(operating_system)
    exact_catalogue = ComputationalHostCatalogue((
        _locus("exact-host", operating_system, runtime, authority_pid=pid_exact, costs=_costs(1)),
    ))
    unpinned = _address(_workload(identity, ground), program=None)

    exact_only = ComputationalAddressResolver().resolve(unpinned, exact_catalogue, operating_system)
    assert exact_only.status is ComputationalResolutionStatus.BLOCKED
    assert any(item.code is ComputationalBlockerCode.PROGRAM_MISMATCH for item in exact_only.blockers)

    pid_dynamic = _worker_pid(operating_system)
    dynamic_catalogue = ComputationalHostCatalogue((
        _locus(
            "dynamic-host",
            operating_system,
            runtime,
            authority_pid=pid_dynamic,
            costs=_costs(2),
            programs=(),
            dynamic_programs=True,
        ),
    ))
    dynamic_result = ComputationalAddressResolver().resolve(
        unpinned, dynamic_catalogue, operating_system
    )
    assert dynamic_result.status is ComputationalResolutionStatus.FOUND
    assert dynamic_result.witness is not None
    assert dynamic_result.witness.program_fingerprint is None
