from __future__ import annotations

import json
import pytest

from mailcpu import (
    Capability,
    ContextualOrbitAddress,
    ComposedComponentAddress,
    ComposedVirtualGroundAddress,
    ObserverContract,
    ObserverReceipt,
    PredictiveGroundObservation,
    VirtualStructuralMemoryRef,
    canonical_value_digest,
    composed_component_context,
    CausalStamp,
    HeadlessOS,
    HypervisorAction,
    HypervisorPolicy,
    StructuralMemoryRegistry,
    LexicalDecisionModel,
    MonotonicReading,
    ObservationAuthorityPolicy,
    ObservationConsensus,
    SchedulerReading,
    TemporalFrame,
    TimingObservation,
    VirtualGroundRef,
    WallTimeReading,
)
from mailcpu.observed_orbit_pipeline import (
    GroundRealizationRefused,
    VerifiedComposedGroundRealizer,
    composed_ground_read_resource,
    select_composed_description,
    NavigationPlan,
    ObservationGroundBuilder,
    ObservationTraceBuilder,
    ObservedOrbitTrace,
    TemporalPathTrace,
    StateSpacePipelineError,
    VerifiedGroundRealizer,
    interpret_intention,
    virtual_ground_read_resource,
)
from mailcpu.semantic_translation import ObservationContract, RepresentationRef
from mailcpu.predictive_selection import predictive_experiment_digest
from mailcpu.law_certifier import Law
from mailcpu.seed import SystemIdentity


def _trace():
    sources = ("sensor-a", "sensor-b")
    consensus = ObservationConsensus(
        ObservationAuthorityPolicy("timing", sources, quorum=2, strict=True)
    )
    builder = ObservationTraceBuilder(
        consensus,
        stream_id="cadence-sensor-stream",
        value_register="symbol",
    )
    for index in range(50):
        logical_time = 100 + index * 2
        value = 30 + index * 3
        for source in sources:
            consensus.ingest(
                TimingObservation(
                    source=source,
                    logical_time=logical_time,
                    observed_us=1_000 + value,
                    symbol=value,
                    tracked_base_us=1_000,
                    quantum_us=10,
                    phase_error_us=0,
                    max_symbol=255,
                )
            )
        source_frame = TemporalFrame(
            actor_id="sensor-a",
            monotonic=MonotonicReading("sensor-a", 0, index * 500),
            wall=WallTimeReading("sensor-a", 1_700_000_000_000_000_000 + index * 500, index),
            causal=CausalStamp.create("sensor-a", index + 1, {"sensor-a": index + 1}),
            scheduler=SchedulerReading("sensor-scheduler", logical_time),
            event_lambda=index,
            chronon_phase=(1.0, 0.0),
            chemical_tau=float(index),
        )
        receiver_frame = TemporalFrame(
            actor_id="host-b",
            monotonic=MonotonicReading("host-b", 0, 9_000 + index * 900),
            wall=WallTimeReading("host-b", 1_800_000_000_000_000_000 + index * 900, index),
            causal=CausalStamp.create(
                "host-b",
                index + 2,
                {"sensor-a": index + 1, "host-b": index + 2},
            ),
            scheduler=SchedulerReading("sensor-scheduler", logical_time),
            event_lambda=index,
            chronon_phase=(1.0, 0.0),
            chemical_tau=float(index),
        )
        builder.capture_authorized(
            logical_time,
            source_frame=source_frame,
            receiver_frame=receiver_frame,
        )
    return builder.build()


def _bound_ground(operating_system: HeadlessOS):
    trace = _trace()
    registry = operating_system.structural_memory
    builder = ObservationGroundBuilder(registry)
    plan = builder.propose(
        trace,
        memory_id="cadence-symbol-ground",
        training_count=30,
        system_identity=SystemIdentity("cadence-system", 1),
        base_ground=VirtualGroundRef("a" * 64, "b" * 64, 100, "c" * 64),
        computational_ground=RepresentationRef.from_payload(
            "sensor.cadence-symbol",
            1,
            {"meaning": "observed cadence symbol", "unit": "symbol"},
        ),
        scheduler_id="sensor-scheduler",
        domain="observed-orbit",
    )
    assert plan.proposal.spec.family == "int"
    binding = builder.admit(
        plan,
        expected_revision=0,
        binding="cadence-symbol-generator",
        observer_id="cadence-orbit-observer",
    )
    return trace, binding


def test_observation_stream_builds_a_digest_bound_ground_and_round_trips_latency_provenance():
    trace = _trace()

    assert trace.samples[0].coordinate == 0
    assert trace.samples[-1].coordinate == 49
    assert trace.samples[0].logical_time == 100
    assert trace.samples[-1].logical_time == 198
    assert trace.values == tuple(30 + 3 * index for index in range(50))

    first_latency = trace.samples[0].latency
    assert first_latency is not None
    assert first_latency.monotonic_elapsed_ns is None
    assert first_latency.wall_elapsed_ns is None
    assert first_latency.causal_relation == "before"
    assert first_latency.scheduler_ticks == 0

    restored = ObservedOrbitTrace.from_dict(trace.to_dict())
    assert restored == trace
    assert restored.digest == trace.digest
    assert restored.context_binding["trace_digest"] == trace.digest
    assert restored.context_binding["temporal_evidence_digest"] == trace.temporal_evidence_digest


def test_temporal_path_trace_measures_local_latency_without_erasing_scheduler_time():
    start = TemporalFrame(
        actor_id="host-a",
        monotonic=MonotonicReading("host-a", 2, 100),
        scheduler=SchedulerReading("runtime", 40),
        event_lambda=8,
    )
    finish = TemporalFrame(
        actor_id="host-a",
        monotonic=MonotonicReading("host-a", 2, 175),
        scheduler=SchedulerReading("runtime", 43),
        event_lambda=10,
    )
    path = TemporalPathTrace("sensor-to-ground")
    path = path.append("observation", start, "1" * 64)
    path = path.append("ground", finish, "2" * 64)

    assert path.intervals[0][2].monotonic_elapsed_ns == 75
    assert path.intervals[0][2].scheduler_ticks == 3
    assert path.intervals[0][2].event_steps == 2
    assert path.to_dict()["digest"] == path.digest
    restored = TemporalPathTrace.from_dict(path.to_dict())
    assert restored == path
    assert restored.digest == path.digest


def test_verified_realization_runs_inside_receiver_hypervisor_and_checks_host_capability():
    operating_system = HeadlessOS(
        structural_memory_admission_policy=lambda proposal: proposal.spec.domain == "observed-orbit"
    )
    trace, binding = _bound_ground(operating_system)
    operating_system.hypervisor.classifier = LexicalDecisionModel()
    operating_system.hypervisor.policy = HypervisorPolicy(
        review_confidence=0.0,
        automatic_confidence=0.0,
        destructive_confidence=0.0,
        danger_review_probability=1.0,
        embedding_review_confidence=1.0,
    )

    resource = binding.read_resource
    authority_pid = operating_system.environment.kernel.spawn(
        "cadence-ground-reader",
        capabilities=(Capability(resource, frozenset({"read"})),),
        parent_pid=operating_system.environment.init_pid,
    )
    intent = interpret_intention(
        {
            "operation": "observe cadence symbol at logical coordinate",
            "goal": {"scheduler_tick": 140},
            "resource": resource,
        }
    )
    plan = NavigationPlan.direct(140, intent_digest=intent.digest)
    realization = VerifiedGroundRealizer(operating_system.structural_memory).realize(
        operating_system,
        authority_pid,
        binding.address,
        binding.observer_contract,
        plan,
        host_actor_id="host-b",
        intention=intent,
    )

    assert realization.verified is True
    assert realization.decision.action is HypervisorAction.ALLOW
    assert realization.navigation.projection.value == trace.values[20]
    assert realization.navigation.projection.orbit_offset == 20
    assert realization.navigation.observation.digest
    assert realization.navigation.projection.read_receipt.receipt_id
    assert realization.host_elapsed_ns >= 0
    assert realization.host_timing.monotonic_elapsed_ns == realization.host_elapsed_ns
    assert realization.receipt_digest == realization.to_dict()["receipt_digest"]
    assert resource == virtual_ground_read_resource(
        binding.version.spec.memory_id,
        revision=binding.version.spec.revision,
        context_digest=binding.address.context_digest,
    )
    assert resource != virtual_ground_read_resource(
        binding.version.spec.memory_id,
        revision=binding.version.spec.revision + 1,
        context_digest=binding.address.context_digest,
    )

    with pytest.raises(StateSpacePipelineError, match="receiver OS's own admitted Structural Memory registry"):
        VerifiedGroundRealizer(StructuralMemoryRegistry()).realize(
            operating_system,
            authority_pid,
            binding.address,
            binding.observer_contract,
            plan,
            host_actor_id="host-b",
            intention=intent,
        )

    inverse = VerifiedGroundRealizer(operating_system.structural_memory).realize(
        operating_system,
        authority_pid,
        binding.address,
        binding.observer_contract,
        NavigationPlan.inverse(trace.values[20], intent_digest=intent.digest),
        host_actor_id="host-b",
        intention=intent,
    )
    assert inverse.value_result is not None
    assert inverse.value_result.orbit_coordinate == 20
    assert inverse.navigation.projection.value == trace.values[20]

    denied_pid = operating_system.environment.kernel.spawn(
        "cadence-ground-reader-without-rights",
        capabilities=(Capability("/unrelated", frozenset({"read"})),),
        parent_pid=operating_system.environment.init_pid,
    )
    with pytest.raises(GroundRealizationRefused) as refused:
        VerifiedGroundRealizer(operating_system.structural_memory).realize(
            operating_system,
            denied_pid,
            binding.address,
            binding.observer_contract,
            plan,
            host_actor_id="host-b",
            intention=intent,
        )
    assert refused.value.decision.action is HypervisorAction.DENY


def test_composed_description_selection_flows_into_hypervisor_verified_realization():
    operating_system = HeadlessOS(
        structural_memory_admission_policy=lambda proposal: proposal.spec.domain == "composed-observed-orbit"
    )
    registry = operating_system.structural_memory
    system = SystemIdentity("observed-composed-system", 2)
    base_ground = VirtualGroundRef("a" * 64, "b" * 64, 500, "c" * 64)
    computational_ground = RepresentationRef.from_payload(
        "mailcpu.computational-ground",
        1,
        {"meaning": "composed observed system state"},
    )
    state_schema = RepresentationRef.from_payload(
        "mailcpu.composed-state-schema",
        1,
        {"cpu.pc": "instruction coordinate", "cpu.accumulator": "integer register"},
    )
    template = {"cpu": {"pc": 0, "accumulator": 0}}
    law_by_component = {
        "program-counter": Law("int", {"x0": 7, "step": 3, "mod": 101}, 1, "GROUND"),
        "accumulator": Law("int", {"x0": 13, "step": 5, "mod": 103}, 1, "GROUND"),
    }
    definitions = (
        (
            "program-counter",
            ("cpu", "pc"),
            RepresentationRef.from_payload("mailcpu.register.pc", 1, {"kind": "uint64"}),
        ),
        (
            "accumulator",
            ("cpu", "accumulator"),
            RepresentationRef.from_payload("mailcpu.register.accumulator", 1, {"kind": "uint32"}),
        ),
    )
    components = []
    initial_coordinate = 505
    for component_id, field_path, representation in definitions:
        value_kind = "integer"
        context = composed_component_context(
            system,
            base_ground,
            computational_ground,
            state_schema,
            template,
            scheduler_id="composed-scheduler",
            component_id=component_id,
            field_path=field_path,
            representation=representation,
            value_kind=value_kind,
        )
        law = law_by_component[component_id]
        proposal = registry.propose(
            f"observed-{component_id}",
            law,
            {coordinate: law.navigate(coordinate) for coordinate in range(16)},
            domain="composed-observed-orbit",
            context=context,
        )
        version = registry.admit(proposal.proposal_id, expected_revision=0)
        memory_ref = VirtualStructuralMemoryRef.from_version(
            f"binding-{component_id}",
            version,
            initial_coordinate - base_ground.coordinate,
        )
        orbit_address = ContextualOrbitAddress(
            system_identity=system,
            base_ground=base_ground,
            computational_ground=computational_ground,
            coordinate=SchedulerReading("composed-scheduler", initial_coordinate),
            structural_memory=memory_ref,
            context_extensions=context["extensions"],
        )
        components.append(
            ComposedComponentAddress(
                component_id=component_id,
                field_path=field_path,
                representation=representation,
                value_kind=value_kind,
                orbit_address=orbit_address,
            )
        )
    address = ComposedVirtualGroundAddress(
        system_identity=system,
        base_ground=base_ground,
        computational_ground=computational_ground,
        coordinate=SchedulerReading("composed-scheduler", initial_coordinate),
        state_schema=state_schema,
        template_json=json.dumps(template, sort_keys=True, separators=(",", ":")),
        components=tuple(components),
    )

    experiment_digest = predictive_experiment_digest(address)
    observer_contract = ObserverContract(
        observer_id="independent-composed-observer",
        revision=1,
        subject=state_schema,
        interpretation=computational_ground,
        observation=ObservationContract.from_definition(
            "mailcpu.composed-state.observation",
            1,
            {"meaning": "complete state projection"},
        ),
        context_digest=experiment_digest,
    )
    observations = []
    for tick in range(505, 513):
        state = address.template
        relative_coordinate = tick - base_ground.coordinate
        for component in address.components:
            current = state
            for part in component.field_path[:-1]:
                current = current[part]
            current[component.field_path[-1]] = law_by_component[
                component.component_id
            ].navigate(relative_coordinate)
        receipt = ObserverReceipt.issue(
            observer_contract,
            operation_id=f"composed-observe-{tick}",
            input_digest=canonical_value_digest({"scheduler_tick": tick}),
            projection_value=state,
            time_frame=TemporalFrame(
                actor_id=observer_contract.observer_id,
                scheduler=SchedulerReading("composed-scheduler", tick),
            ),
            subject_state_before_digest=canonical_value_digest(address.template),
            subject_state_after_digest=canonical_value_digest(state),
        )
        observations.append(
            PredictiveGroundObservation.capture(address, state, observer_contract, receipt)
        )

    selection = select_composed_description(
        registry,
        address,
        tuple(observations),
        development_through_tick=507,
        validation_through_tick=509,
    )
    assert selection.report.recommendation_authoritative is False
    assert selection.selected_candidate.address.digest

    intention = interpret_intention(
        {
            "operation": "observe composed virtual system state",
            "goal": {"scheduler_tick": 520},
            "resource": "selected-composed-ground",
        }
    )
    navigation_plan = NavigationPlan.direct(
        520,
        intent_digest=intention.digest,
        selection_report_digest=selection.report.digest,
    )
    resource = composed_ground_read_resource(selection.selected_candidate.address)
    operating_system.hypervisor.classifier = LexicalDecisionModel()
    operating_system.hypervisor.policy = HypervisorPolicy(
        review_confidence=0.0,
        automatic_confidence=0.0,
        destructive_confidence=0.0,
        danger_review_probability=1.0,
        embedding_review_confidence=1.0,
    )
    authority_pid = operating_system.environment.kernel.spawn(
        "composed-ground-reader",
        capabilities=(Capability(resource, frozenset({"read"})),),
        parent_pid=operating_system.environment.init_pid,
    )

    realized = VerifiedComposedGroundRealizer(registry).realize(
        operating_system,
        authority_pid,
        selection,
        intention,
        navigation_plan,
    )

    expected = address.template
    target_offset = 520 - base_ground.coordinate
    for component in address.components:
        current = expected
        for part in component.field_path[:-1]:
            current = current[part]
        current[component.field_path[-1]] = law_by_component[
            component.component_id
        ].navigate(target_offset)
    assert realized.verified is True
    assert realized.decision.action is HypervisorAction.ALLOW
    assert realized.navigation.projection.state == expected
    assert realized.navigation.projection.state_digest == canonical_value_digest(expected)
    assert len(realized.navigation.projection.components) == len(components)
    assert len(realized.identity_payload()["component_receipts"]) == len(components)
    assert realized.observer_receipt.digest
    assert realized.host_elapsed_ns >= 0
    assert realized.host_timing.monotonic_elapsed_ns == realized.host_elapsed_ns
    assert realized.receipt_digest == realized.to_dict()["receipt_digest"]
