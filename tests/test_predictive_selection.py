from __future__ import annotations

from dataclasses import replace

import pytest

from mailcpu import (
    ComposedComponentAddress,
    ComposedVirtualGroundAddress,
    ObserverContract,
    ObserverReceipt,
    PredictiveCandidatePoolBuilder,
    RepresentationRef,
    StructuralMemoryRegistry,
    VirtualGroundRef,
    VirtualStructuralMemoryRef,
    canonical_value_digest,
    composed_component_context,
)
from mailcpu.classifier import HypervisorAction, HypervisorDomain, HypervisorExecutionResult
from mailcpu.computational_fabric import (
    ComputationalFabricRouteWitness,
    ComputationalHostAdvertisement,
    ComputationalPeerEndpoint,
)
from mailcpu.evidence_path_resolver import RouteMetric
from mailcpu.law_certifier import Law
from mailcpu.observer_orbit import ContextualOrbitAddress
from mailcpu.predictive_selection import (
    PredictiveDescriptionCandidate,
    PredictiveDescriptionSelector,
    PredictiveExecutionEvidence,
    PredictiveGroundObservation,
    PredictiveSelectionError,
    predictive_experiment_digest,
)
from mailcpu.semantic_translation import ObservationContract
from mailcpu.seed import SystemIdentity
from mailcpu.temporal import SchedulerReading, TemporalFrame
from mailcpu.virtual_layer import OperatorSpec

from test_composed_ground import _canonical, _fixture


def _laws_map(laws):
    """Project the fixture component tuples into a component-ID to Law mapping."""
    return {item[0]: item[4] for item in laws}


def _candidate_address(
    registry: StructuralMemoryRegistry,
    base: ComposedVirtualGroundAddress,
    candidate_id: str,
    laws_by_component: dict[str, Law],
) -> ComposedVirtualGroundAddress:
    components: list[ComposedComponentAddress] = []
    for component in base.components:
        law = laws_by_component[component.component_id]
        context = composed_component_context(
            base.system_identity,
            base.base_ground,
            base.computational_ground,
            base.state_schema,
            base.template,
            scheduler_id=base.coordinate.scheduler_id,
            component_id=component.component_id,
            field_path=component.field_path,
            representation=component.representation,
            value_kind=component.value_kind,
            extensions=dict(base.extensions),
        )
        memory_id = f"{candidate_id}-{component.component_id}"
        proposal = registry.propose(
            memory_id,
            law,
            {coordinate: law.navigate(coordinate) for coordinate in range(8)},
            domain="predictive-selection-test",
            context=context,
        )
        version = registry.admit(proposal.proposal_id, expected_revision=0)
        memory_ref = VirtualStructuralMemoryRef.from_version(
            f"{candidate_id}-{component.component_id}",
            version,
            base.orbit_offset,
        )
        orbit_address = ContextualOrbitAddress(
            system_identity=base.system_identity,
            base_ground=base.base_ground,
            computational_ground=base.computational_ground,
            coordinate=base.coordinate,
            structural_memory=memory_ref,
            context_extensions=context["extensions"],
        )
        components.append(
            ComposedComponentAddress(
                component_id=component.component_id,
                field_path=component.field_path,
                representation=component.representation,
                value_kind=component.value_kind,
                orbit_address=orbit_address,
            )
        )
    return replace(base, components=tuple(components))


def _make_observations(
    address: ComposedVirtualGroundAddress,
    laws_by_component: dict[str, Law],
    ticks: tuple[int, ...],
    *,
    mutate_state=None,
) -> tuple[PredictiveGroundObservation, ...]:
    experiment = predictive_experiment_digest(address)
    contract = ObserverContract(
        observer_id="independent-state-observer",
        revision=1,
        subject=address.state_schema,
        interpretation=address.computational_ground,
        observation=ObservationContract.from_definition(
            "mailcpu.test.full-state-observation",
            1,
            {"meaning": "complete canonical composed state"},
        ),
        context_digest=experiment,
    )
    observations = []
    for tick in ticks:
        state = address.template
        offset = tick - address.base_ground.coordinate
        for component in address.components:
            current = state
            for part in component.field_path[:-1]:
                current = current[part]
            current[component.field_path[-1]] = laws_by_component[component.component_id].navigate(offset)
        if mutate_state is not None:
            state = mutate_state(tick, state)
        receipt = ObserverReceipt.issue(
            contract,
            operation_id=f"observe-{tick}",
            input_digest=canonical_value_digest({"scheduler_tick": tick}),
            projection_value=state,
            time_frame=TemporalFrame(
                actor_id=contract.observer_id,
                scheduler=SchedulerReading(address.coordinate.scheduler_id, tick),
            ),
            subject_state_before_digest=canonical_value_digest(address.template),
            subject_state_after_digest=canonical_value_digest(state),
        )
        observations.append(
            PredictiveGroundObservation.capture(address, state, contract, receipt)
        )
    return tuple(observations)


def _route_witness() -> ComputationalFabricRouteWitness:
    operator = OperatorSpec(
        operator_id="predictive.test.operator",
        version=1,
        description="test operator",
        input_kind="object",
        output_kind="object",
        substrates=("cpu",),
        base_energy=2,
        energy_per_byte=1,
    )
    host = ComputationalHostAdvertisement(
        host_id="test-host-b",
        node_id="node-b",
        peer_id="peer-b",
        operator_spec=operator,
        substrates=("cpu",),
        computational_ground_fingerprints=("a" * 64,),
        program_fingerprints=(),
        supports_ground_program_compilation=True,
        supports_structural_memory=True,
        implementation_fingerprint="b" * 64,
        costs=(RouteMetric("latency", "ms", 2),),
        virtual_capacity=8,
        max_energy=10000,
        max_bytes=100000,
        max_virtual_ticks=10000,
    )
    return ComputationalFabricRouteWitness(
        address_digest="c" * 64,
        directory_digest="d" * 64,
        topology_digest="e" * 64,
        origin_peer_id="peer-a",
        peer_path=("peer-a", "peer-b"),
        link_ids=("f" * 64,),
        peer_endpoints=(
            ComputationalPeerEndpoint("peer-a", "peer-a.test", "127.0.0.1", 7001),
            ComputationalPeerEndpoint("peer-b", "peer-b.test", "127.0.0.2", 7002),
        ),
        target_host=host,
        network_costs=(RouteMetric("latency", "ms", 3),),
        host_costs=(RouteMetric("latency", "ms", 2),),
        total_costs=(RouteMetric("latency", "ms", 5),),
    )


def test_selector_ranks_composed_descriptions_on_chronological_holdouts():
    registry, address, original_laws = _fixture()
    alternative_laws = _laws_map(original_laws)
    alternative_laws["program-counter"] = Law(
        "int",
        {"x0": 7, "step": 4, "mod": 101},
        1,
        "GROUND",
    )
    alternative_address = _candidate_address(
        registry,
        address,
        "alternative",
        alternative_laws,
    )
    candidates = (
        PredictiveDescriptionCandidate("grounded", address),
        PredictiveDescriptionCandidate("alternative", alternative_address),
    )
    observations = _make_observations(
        address,
        _laws_map(original_laws),
        (511, 512, 513, 514, 515, 516),
    )

    report = PredictiveDescriptionSelector(registry).evaluate(
        candidates,
        observations,
        development_through_tick=512,
        validation_through_tick=514,
    )

    assert report.selected_candidate_id == "grounded"
    assert report.ranking[0] == "grounded"
    assert "grounded" in report.pareto_frontier
    grounded = next(item for item in report.evaluations if item.candidate_id == "grounded")
    alternative = next(item for item in report.evaluations if item.candidate_id == "alternative")
    assert grounded.partition("development").sample_count == 2
    assert grounded.partition("validation").sample_count == 2
    assert grounded.partition("test").sample_count == 2
    assert grounded.partition("validation").coverage_ratio == 1.0
    assert grounded.partition("validation").component_accuracy == 1.0
    assert grounded.partition("validation").predictive_yield == 1.0
    assert grounded.partition("validation").full_state_match_rate == 1.0
    assert grounded.partition("validation").distinct_observed_component_states == 2
    assert grounded.partition("validation").distinct_matched_component_states == 2
    assert grounded.partition("validation").component_state_space_coverage == 1.0
    assert alternative.partition("validation").component_accuracy < 1.0
    assert alternative.partition("validation").predictive_yield < 1.0
    assert grounded.partition("validation").navigation_work_units > 0
    assert len(grounded.partition("validation").navigation_evidence_digest) == 64
    assert grounded.description_bytes > 0
    assert grounded.verification_witness_units >= 6
    assert report.recommendation_authoritative is False
    assert report.to_dict()["report_digest"] == report.digest


def test_test_partition_changes_do_not_change_validation_selection():
    registry, address, laws = _fixture()

    def alter_test_state(tick, state):
        if tick > 514:
            state["cpu"]["pc"] = (state["cpu"]["pc"] + 37) % 101
            state["scheduler"]["tick"] = tick
        return state

    observations = _make_observations(
        address,
        _laws_map(laws),
        (511, 512, 513, 514, 515, 516),
        mutate_state=alter_test_state,
    )
    report = PredictiveDescriptionSelector(registry).evaluate(
        (PredictiveDescriptionCandidate("grounded", address),),
        observations,
        development_through_tick=512,
        validation_through_tick=514,
    )
    evaluation = report.evaluations[0]
    assert report.selected_candidate_id == "grounded"
    assert evaluation.partition("validation").component_accuracy == 1.0
    assert evaluation.partition("test").component_accuracy < 1.0
    assert evaluation.partition("test").unmodeled_changed_leaf_count > 0
    assert evaluation.partition("test").full_state_match_rate == 0.0


def test_observer_receipt_must_bind_the_exact_experiment_and_scheduler():
    _, address, laws = _fixture()
    valid = _make_observations(address, _laws_map(laws), (511, 512))[0]
    wrong_contract = replace(
        valid.observer_contract,
        context_digest="9" * 64,
    )
    with pytest.raises(PredictiveSelectionError, match="experiment"):
        replace(valid, observer_contract=wrong_contract)

    wrong_frame = replace(
        valid.observer_receipt,
        time_frame=TemporalFrame(
            actor_id=valid.observer_contract.observer_id,
            scheduler=SchedulerReading("different-scheduler", valid.tick),
        ),
    )
    with pytest.raises(PredictiveSelectionError):
        PredictiveGroundObservation.capture(
            address,
            valid.observed_state,
            valid.observer_contract,
            wrong_frame,
        )


def test_hypervisor_and_fabric_evidence_keep_estimates_separate_from_execution():
    result = HypervisorExecutionResult(
        source="predictive-test",
        channel="operator",
        sequence=1,
        logical_time=511,
        fingerprint="1" * 64,
        decision_receipt="2" * 64,
        action=HypervisorAction.ALLOW,
        domain=HypervisorDomain.CPU,
        effect={
            "kind": "virtual_layer.operator_result",
            "estimated_energy": 17,
            "estimated_virtual_ticks": 3,
            "node_id": "node-b",
            "substrate": "cpu",
            "measurement": {
                "handler_total_ms": 1.25,
                "transfer_bundle_bytes": 512,
            },
        },
        replayed=False,
        executed=True,
    )
    route = _route_witness()
    evidence = PredictiveExecutionEvidence.from_hypervisor_result(
        result,
        route_witness=route,
    )

    assert evidence.estimated_energy == 17
    assert evidence.estimated_virtual_ticks == 3
    assert evidence.measured_metrics["handler_total_ms"] == 1.25
    assert evidence.route_witness_digest == route.digest
    assert evidence.to_dict()["route_authoritative"] is False
    restored = PredictiveExecutionEvidence.from_dict(evidence.to_dict())
    assert restored == evidence
    tampered_execution = evidence.to_dict()
    tampered_execution["hypervisor_result"]["effect"]["estimated_energy"] += 1
    with pytest.raises(PredictiveSelectionError, match="hypervisor result content"):
        PredictiveExecutionEvidence.from_dict(tampered_execution)
    tampered = evidence.to_dict()
    tampered["route_witness"]["total_costs"][0]["amount"] += 1
    with pytest.raises(PredictiveSelectionError, match="route witness"):
        PredictiveExecutionEvidence.from_dict(tampered)
    mismatched_route = replace(
        route,
        target_host=replace(route.target_host, node_id="other-node"),
    )
    with pytest.raises(PredictiveSelectionError, match="target node"):
        PredictiveExecutionEvidence.from_hypervisor_result(
            result,
            route_witness=mismatched_route,
        )

    registry, address, laws = _fixture()
    observations = list(_make_observations(address, _laws_map(laws), (511, 512)))
    observations[0] = replace(observations[0], execution_evidence=evidence)
    replay_result = replace(result, sequence=2, logical_time=512, replayed=True)
    replay_evidence = PredictiveExecutionEvidence.from_hypervisor_result(
        replay_result,
        route_witness=route,
    )
    observations[1] = replace(observations[1], execution_evidence=replay_evidence)
    report = PredictiveDescriptionSelector(registry).evaluate(
        (PredictiveDescriptionCandidate("grounded", address),),
        tuple(observations),
        development_through_tick=511,
        validation_through_tick=512,
    )
    operational = report.identity_payload()["operational_profile"]
    assert operational["hypervisor_result_samples"] == 2
    assert operational["hypervisor_executed_samples"] == 1
    assert operational["hypervisor_replayed_samples"] == 1
    assert operational["estimated_energy_sum"] == 17
    assert operational["fabric_route_witness_samples"] == 1
    assert operational["fabric_route_cost_sums"] == [
        {"cost_scope": "host", "name": "latency", "unit": "ms", "amount": 2},
        {"cost_scope": "network", "name": "latency", "unit": "ms", "amount": 3},
        {"cost_scope": "total", "name": "latency", "unit": "ms", "amount": 5},
    ]


def test_hypervisor_adapter_refuses_denied_or_unexecuted_results():
    denied = HypervisorExecutionResult(
        source="predictive-test",
        channel="operator",
        sequence=1,
        logical_time=511,
        fingerprint="1" * 64,
        decision_receipt="2" * 64,
        action=HypervisorAction.DENY,
        domain=HypervisorDomain.CPU,
        effect=None,
        replayed=False,
        executed=False,
    )
    with pytest.raises(PredictiveSelectionError, match="executed ALLOW"):
        PredictiveExecutionEvidence.from_hypervisor_result(denied)


def test_observation_round_trip_revalidates_receipt_and_state_digest():
    registry, address, laws = _fixture()
    observation = _make_observations(address, _laws_map(laws), (511,))[0]

    restored = PredictiveGroundObservation.from_dict(observation.to_dict())

    assert restored == observation
    assert restored.digest == observation.digest


def test_selector_refuses_an_empty_validation_window():
    registry, address, laws = _fixture()
    observations = _make_observations(address, _laws_map(laws), (511, 512))

    with pytest.raises(PredictiveSelectionError, match="validation partition"):
        PredictiveDescriptionSelector(registry).evaluate(
            (PredictiveDescriptionCandidate("grounded", address),),
            observations,
            development_through_tick=512,
            validation_through_tick=513,
        )


def test_admitted_versions_lists_only_admitted_revisions_in_stable_order():
    registry, address, laws = _fixture()
    baseline_versions = registry.admitted_versions()
    assert len(baseline_versions) == len(address.components)
    assert tuple(
        (item.spec.memory_id, item.spec.revision, item.spec.digest)
        for item in baseline_versions
    ) == tuple(sorted(
        (item.spec.memory_id, item.spec.revision, item.spec.digest)
        for item in baseline_versions
    ))

    component = address.components[0]
    laws_by_id = _laws_map(laws)
    context = composed_component_context(
        address.system_identity,
        address.base_ground,
        address.computational_ground,
        address.state_schema,
        address.template,
        scheduler_id=address.coordinate.scheduler_id,
        component_id=component.component_id,
        field_path=component.field_path,
        representation=component.representation,
        value_kind=component.value_kind,
        extensions=dict(address.extensions),
    )
    staged = registry.propose(
        "not-admitted-" + component.component_id,
        laws_by_id[component.component_id],
        {coordinate: laws_by_id[component.component_id].navigate(coordinate) for coordinate in range(8)},
        domain="candidate-pool-test",
        context=context,
    )
    assert registry.admitted_versions(staged.spec.memory_id) == ()
    assert all(item.spec.memory_id != staged.spec.memory_id for item in registry.admitted_versions())


def test_candidate_pool_builder_emits_only_bounded_one_factor_admitted_variants():
    registry, address, laws = _fixture()
    alternative_laws = _laws_map(laws)
    alternative_laws["program-counter"] = Law(
        "int",
        {"x0": 7, "step": 4, "mod": 101},
        1,
        "GROUND",
    )
    _candidate_address(registry, address, "pool-alternative", alternative_laws)

    builder = PredictiveCandidatePoolBuilder(registry)
    complete = builder.build_one_factor(address, max_candidates=8)
    bounded = builder.build_one_factor(address, max_candidates=2)
    repeated = builder.build_one_factor(address, max_candidates=2)

    assert len(complete.candidates) == 4
    assert complete.discovered_candidate_count == 4
    assert complete.omitted_candidate_count == 0
    assert complete.candidates[0].candidate_id == "baseline"
    assert bounded.candidates[0] == complete.candidates[0]
    assert len(bounded.candidates) == 2
    assert bounded.max_candidates == 2
    assert bounded.discovered_candidate_count == 4
    assert bounded.omitted_candidate_count == 2
    assert bounded.digest == repeated.digest
    assert bounded.candidates == repeated.candidates

    baseline_by_id = {
        item.component_id: item.orbit_address.structural_memory.spec_digest
        for item in address.components
    }
    for candidate in complete.candidates[1:]:
        changed = [
            item.component_id
            for item in candidate.address.components
            if item.orbit_address.structural_memory.spec_digest
            != baseline_by_id[item.component_id]
        ]
        assert len(changed) == 1
        assert candidate.experiment_digest == complete.experiment_digest

    too_small = builder.build_one_factor(address, max_candidates=1)
    assert too_small.candidates == (complete.candidates[0],)
    assert too_small.omitted_candidate_count == 3
    assert too_small.to_dict()["pool_digest"] == too_small.digest
    observations = _make_observations(address, _laws_map(laws), (511, 512, 513, 514))
    report = PredictiveDescriptionSelector(registry).evaluate_pool(
        bounded,
        observations,
        development_through_tick=511,
        validation_through_tick=513,
    )
    pool_record = report.identity_payload()["candidate_pool"]
    assert pool_record["pool_digest"] == bounded.digest
    assert pool_record["max_candidates"] == 2
    assert pool_record["discovered_candidate_count"] == 4
    assert pool_record["included_candidate_count"] == 2
    assert pool_record["omitted_candidate_count"] == 2
    assert report.to_dict()["report_digest"] == report.digest


def test_predictive_selector_advises_page_access_trace_from_independent_held_out_ticks():
    """Use admitted page-access descriptions to forecast an independently observed cache workload."""
    registry = StructuralMemoryRegistry(admission_policy=lambda proposal: True)
    system = SystemIdentity("predictive-page-cache", 1)
    base_ground = VirtualGroundRef("a" * 64, "b" * 64, 1000, "c" * 64)
    computational_ground = RepresentationRef.from_payload(
        "mailcpu.computational-ground",
        1,
        {"meaning": "page-cache-access-trace", "domain": "integer page identifiers"},
    )
    state_schema = RepresentationRef.from_payload(
        "mailcpu.page-cache-access-schema",
        1,
        {"cache.requested_page": "bounded integer page identifier"},
    )
    template = {
        "cache": {"requested_page": 0},
        "scheduler": {"tick": 0},
    }
    representation = RepresentationRef.from_payload(
        "mailcpu.cache.page-index",
        1,
        {"kind": "integer", "meaning": "requested backing page index"},
    )
    component_context = composed_component_context(
        system,
        base_ground,
        computational_ground,
        state_schema,
        template,
        scheduler_id="cache-scheduler",
        component_id="requested-page",
        field_path=("cache", "requested_page"),
        representation=representation,
        value_kind="integer",
        extensions={"experiment": "predictive-page-reuse-v1"},
    )

    # Baseline is a simple round-robin page sweep. Revision 2 describes the
    # cache workload observed by the independent scheduler/observer.
    baseline_law = Law(
        "fgraph",
        {"orbit": [0, 1, 2, 3], "mu": 0, "lam": 4},
        4,
        "GROUND",
    )
    memory_id = "page-access-description"
    baseline_proposal = registry.propose(
        memory_id,
        baseline_law,
        {coordinate: baseline_law.navigate(coordinate) for coordinate in range(8)},
        domain="page-access-trace",
        context=component_context,
    )
    baseline_version = registry.admit(
        baseline_proposal.proposal_id,
        expected_revision=0,
    )
    baseline_reference = VirtualStructuralMemoryRef.from_version(
        "requested-page-binding",
        baseline_version,
        0,
    )
    baseline_orbit = ContextualOrbitAddress(
        system_identity=system,
        base_ground=base_ground,
        computational_ground=computational_ground,
        coordinate=SchedulerReading("cache-scheduler", base_ground.coordinate),
        structural_memory=baseline_reference,
        context_extensions=component_context["extensions"],
    )
    component = ComposedComponentAddress(
        component_id="requested-page",
        field_path=("cache", "requested_page"),
        representation=representation,
        value_kind="integer",
        orbit_address=baseline_orbit,
    )
    address = ComposedVirtualGroundAddress(
        system_identity=system,
        base_ground=base_ground,
        computational_ground=computational_ground,
        coordinate=SchedulerReading("cache-scheduler", base_ground.coordinate),
        state_schema=state_schema,
        template_json=_canonical(template),
        components=(component,),
        extensions={"experiment": "predictive-page-reuse-v1"},
    )

    observed_access_trace = (0, 1, 0, 2, 0, 3, 0, 1, 0, 2, 0, 3)
    observed_law = Law(
        "fgraph",
        {
            "orbit": list(observed_access_trace),
            "mu": 0,
            "lam": len(observed_access_trace),
        },
        len(observed_access_trace),
        "GROUND",
    )
    alternative_memory_id = "page-access-description-forecast"
    observed_proposal = registry.propose(
        alternative_memory_id,
        observed_law,
        {coordinate: observed_law.navigate(coordinate) for coordinate in range(8)},
        domain="page-access-trace",
        context=component_context,
    )
    registry.admit(observed_proposal.proposal_id, expected_revision=0)
    baseline_active_before = registry.active_version(memory_id)

    pool = PredictiveCandidatePoolBuilder(registry).build_one_factor(
        address,
        max_candidates=4,
    )
    assert len(pool.candidates) == 2
    assert pool.discovered_candidate_count == 2
    assert pool.candidates[0].candidate_id == "baseline"

    experiment = predictive_experiment_digest(address)
    observer_contract = ObserverContract(
        observer_id="independent-page-access-observer",
        revision=1,
        subject=state_schema,
        interpretation=computational_ground,
        observation=ObservationContract.from_definition(
            "mailcpu.page-cache-access-observation",
            1,
            {"meaning": "observed requested page index at scheduler tick"},
        ),
        context_digest=experiment,
    )
    observations = []
    for offset, requested_page in enumerate(observed_access_trace):
        tick = base_ground.coordinate + offset
        observed_state = {
            "cache": {"requested_page": requested_page},
            "scheduler": {"tick": 0},
        }
        receipt = ObserverReceipt.issue(
            observer_contract,
            operation_id=f"page-access-{offset}",
            input_digest=canonical_value_digest({"scheduler_tick": tick}),
            projection_value=observed_state,
            time_frame=TemporalFrame(
                actor_id=observer_contract.observer_id,
                scheduler=SchedulerReading("cache-scheduler", tick),
            ),
            subject_state_before_digest=canonical_value_digest(template),
            subject_state_after_digest=canonical_value_digest(observed_state),
        )
        observations.append(
            PredictiveGroundObservation.capture(
                address,
                observed_state,
                observer_contract,
                receipt,
            )
        )

    report = PredictiveDescriptionSelector(registry).evaluate_pool(
        pool,
        tuple(observations),
        development_through_tick=base_ground.coordinate + 3,
        validation_through_tick=base_ground.coordinate + 7,
    )
    selected = next(
        candidate for candidate in pool.candidates
        if candidate.candidate_id == report.selected_candidate_id
    )
    selected_evaluation = next(
        item for item in report.evaluations
        if item.candidate_id == selected.candidate_id
    )
    baseline_evaluation = next(
        item for item in report.evaluations
        if item.candidate_id == "baseline"
    )

    assert selected.candidate_id != "baseline"
    assert selected_evaluation.partition("validation").predictive_yield == 1.0
    assert selected_evaluation.partition("test").predictive_yield == 1.0
    assert baseline_evaluation.partition("validation").predictive_yield < 1.0
    assert baseline_evaluation.partition("test").predictive_yield < 1.0
    assert report.recommendation_authoritative is False
    assert registry.active_version(memory_id) == baseline_active_before
    assert report.identity_payload()["candidate_pool"]["pool_digest"] == pool.digest
    assert report.to_dict()["report_digest"] == report.digest


def test_candidate_pool_rejects_non_positive_and_oversized_budgets():
    registry, address, _ = _fixture()
    builder = PredictiveCandidatePoolBuilder(registry)
    with pytest.raises(PredictiveSelectionError, match="max_candidates"):
        builder.build_one_factor(address, max_candidates=0)
    with pytest.raises(PredictiveSelectionError, match="hard pool bound"):
        builder.build_one_factor(address, max_candidates=4097)
