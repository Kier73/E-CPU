"""Tests for evidence-indexed, resource-aware representation routing."""

from __future__ import annotations

import json
import pytest

from mailcpu import (
    Capability,
    CapabilityRequirement,
    EffectClass,
    HeadlessOS,
    HypervisorArbitrationEvent,
    HypervisorDomain,
    HypervisorPolicy,
    HypervisorRequest,
    ObservationContract,
    ReplayClass,
    RepresentationRef,
    ResourceBound,
    TransitComputeHost,
    TranslationContract,
    canonical_value_digest,
    compare_projected_observations,
    build_transit_translation_evidence,
)
from mailcpu.transit_oracles import build_transit_oracle_evidence
from mailcpu.evidence_path_resolver import (
    EvidencePathBlockerCode,
    EvidencePathCatalogue,
    EvidencePathEdge,
    EvidencePathRequest,
    EvidencePathResolver,
    EvidencePathStatus,
    EvidenceStrength,
    RouteMetric,
    RouteMetricKey,
)


_CONTEXT = {"tenant": "alpha", "partition": 3}
_CONTEXT_DIGEST = canonical_value_digest(_CONTEXT)
_METRIC_ORDER = (
    RouteMetricKey("latency_us", "us"),
    RouteMetricKey("energy_nj", "nJ"),
)


def _ref(name: str) -> RepresentationRef:
    """Mathematics: map a stable node label to a content-addressed representation identity."""
    return RepresentationRef.from_payload(
        "test.semantic.representation",
        1,
        {"node": name},
    )


def _os(*resources: str) -> tuple[HeadlessOS, int]:
    """Mathematics: create one receiver process whose live authority is exactly the supplied resource/right pairs."""
    operating_system = HeadlessOS()
    capabilities = tuple(
        Capability(resource, frozenset({"execute"}))
        for resource in resources
    )
    pid = operating_system.environment.kernel.spawn(
        "evidence-path-test",
        capabilities=capabilities,
        parent_pid=operating_system.environment.init_pid,
    )
    return operating_system, pid


def _edge(
    edge_name: str,
    source: RepresentationRef,
    target: RepresentationRef,
    *,
    latency: int,
    energy: int,
    resource: str = "/cpu/execute",
    context_digest: str = _CONTEXT_DIGEST,
    preconditions: tuple[str, ...] = (),
    invariants: tuple[str, ...] = (),
) -> EvidencePathEdge:
    """Build a finite paired-case translation edge with explicit resource/authority declarations."""
    contract = TranslationContract(
        contract_id=f"test.edge.{edge_name}",
        revision=1,
        source=source,
        target=target,
        mapping=RepresentationRef.from_payload(
            "test.semantic.mapping",
            1,
            {"edge": edge_name},
        ),
        observation=ObservationContract.from_definition(
            "test.route.observation",
            1,
            {"visible_fields": ["value"], "comparison": "exact"},
        ),
        context_digest=context_digest,
        precondition_digests=preconditions,
        invariant_digests=invariants,
        resource_bounds=(
            ResourceBound("energy_nj", 10_000, "nJ"),
            ResourceBound("latency_us", 10_000, "us"),
        ),
        authority_requirements=(
            CapabilityRequirement(resource, ("execute",)),
        ),
        effect_class=EffectClass.PURE,
        replay_class=ReplayClass.DETERMINISTIC,
    )
    comparison = compare_projected_observations(
        contract,
        case_payload={"case": edge_name},
        source_observation={"value": edge_name},
        target_observation={"value": edge_name},
    )
    return EvidencePathEdge(
        contract=contract,
        comparison=comparison,
        costs=(
            RouteMetric("latency_us", "us", latency),
            RouteMetric("energy_nj", "nJ", energy),
        ),
    )


def _request(
    source: RepresentationRef,
    target: RepresentationRef,
    *,
    energy_limit: int | None = None,
    context_digest: str = _CONTEXT_DIGEST,
    preconditions: tuple[str, ...] = (),
    invariants: tuple[str, ...] = (),
    minimum_evidence: EvidenceStrength = EvidenceStrength.PAIRED_CASE,
    metric_order: tuple[RouteMetricKey, ...] = _METRIC_ORDER,
    max_hops: int = 16,
    max_expansions: int = 128,
) -> EvidencePathRequest:
    """Build one deterministic route request with explicit metric priority and optional energy ceiling."""
    ceilings = (
        ()
        if energy_limit is None
        else (RouteMetric("energy_nj", "nJ", energy_limit),)
    )
    return EvidencePathRequest(
        source=source,
        target=target,
        context_digest=context_digest,
        metric_order=metric_order,
        resource_ceilings=ceilings,
        satisfied_preconditions=preconditions,
        satisfied_invariants=invariants,
        minimum_evidence=minimum_evidence,
        max_hops=max_hops,
        max_expansions=max_expansions,
    )


def test_resolver_uses_explicit_lexicographic_objective_not_mixed_units() -> None:
    """Mathematics: minimize total latency first, then energy, without adding unlike metric units."""
    source, via_fast, via_efficient, target = map(_ref, ("source", "fast", "efficient", "target"))
    catalogue = EvidencePathCatalogue()
    fast_path = (
        _edge("fast-1", source, via_fast, latency=1, energy=7),
        _edge("fast-2", via_fast, target, latency=1, energy=1),
    )
    efficient_path = (
        _edge("efficient-1", source, via_efficient, latency=2, energy=1, resource="/gpu/execute"),
        _edge("efficient-2", via_efficient, target, latency=2, energy=1, resource="/gpu/execute"),
    )
    for edge in (*fast_path, *efficient_path):
        catalogue.register(edge)
    operating_system, pid = _os("/cpu/execute", "/gpu/execute")

    result = EvidencePathResolver().resolve(
        catalogue,
        _request(source, target),
        operating_system,
        pid,
    )

    assert result.status is EvidencePathStatus.FOUND
    assert result.edge_ids == tuple(edge.edge_id for edge in fast_path)
    assert result.total_costs == (
        RouteMetric("energy_nj", "nJ", 8),
        RouteMetric("latency_us", "us", 2),
    )
    assert result.authoritative is False


def test_global_resource_ceiling_excludes_the_lexicographically_cheapest_path() -> None:
    """Mathematics: select the least-latency path among feasible paths after enforcing the aggregate energy ceiling."""
    source, via_fast, via_efficient, target = map(_ref, ("source", "fast", "efficient", "target"))
    fast_path = (
        _edge("fast-budget-1", source, via_fast, latency=1, energy=6),
        _edge("fast-budget-2", via_fast, target, latency=1, energy=1),
    )
    efficient_path = (
        _edge("efficient-budget-1", source, via_efficient, latency=2, energy=1, resource="/gpu/execute"),
        _edge("efficient-budget-2", via_efficient, target, latency=2, energy=1, resource="/gpu/execute"),
    )
    catalogue = EvidencePathCatalogue()
    for edge in (*fast_path, *efficient_path):
        catalogue.register(edge)
    operating_system, pid = _os("/cpu/execute", "/gpu/execute")

    result = EvidencePathResolver().resolve(
        catalogue,
        _request(source, target, energy_limit=5),
        operating_system,
        pid,
    )

    assert result.status is EvidencePathStatus.FOUND
    assert result.edge_ids == tuple(edge.edge_id for edge in efficient_path)
    assert dict((item.name, item.amount) for item in result.total_costs) == {
        "energy_nj": 2,
        "latency_us": 4,
    }
    assert any(item.code is EvidencePathBlockerCode.RESOURCE_LIMIT for item in result.blockers)


def test_live_receiver_capability_is_required_and_is_read_from_kernel_state() -> None:
    """Mathematics: a route edge is eligible iff every declared resource/right pair is present in the receiving process."""
    source, target = _ref("source"), _ref("target")
    edge = _edge(
        "gpu-only",
        source,
        target,
        latency=1,
        energy=1,
        resource="/gpu/execute",
    )
    catalogue = EvidencePathCatalogue()
    catalogue.register(edge)
    operating_system, pid = _os("/cpu/execute")

    denied = EvidencePathResolver().resolve(
        catalogue,
        _request(source, target),
        operating_system,
        pid,
    )
    assert denied.status is EvidencePathStatus.BLOCKED
    assert any(item.code is EvidencePathBlockerCode.AUTHORITY_MISSING for item in denied.blockers)

    gpu_pid = operating_system.environment.kernel.spawn(
        "gpu-capable-test",
        capabilities=(Capability("/gpu/execute", frozenset({"execute"})),),
        parent_pid=operating_system.environment.init_pid,
    )
    allowed = EvidencePathResolver().resolve(
        catalogue,
        _request(source, target),
        operating_system,
        gpu_pid,
    )
    assert allowed.status is EvidencePathStatus.FOUND
    assert allowed.edge_ids == (edge.edge_id,)
    assert allowed.authority_digest != denied.authority_digest


def test_context_preconditions_and_invariants_are_independent_route_filters() -> None:
    """Mathematics: an edge is eligible only when its exact context and all declared prerequisite digests are present."""
    source, target = _ref("source"), _ref("target")
    precondition = canonical_value_digest({"precondition": "memory-pinned"})
    invariant = canonical_value_digest({"invariant": "input-stable"})
    edge = _edge(
        "gated",
        source,
        target,
        latency=1,
        energy=1,
        preconditions=(precondition,),
        invariants=(invariant,),
    )
    catalogue = EvidencePathCatalogue()
    catalogue.register(edge)
    operating_system, pid = _os("/cpu/execute")

    missing = EvidencePathResolver().resolve(
        catalogue,
        _request(source, target, preconditions=(precondition,)),
        operating_system,
        pid,
    )
    assert missing.status is EvidencePathStatus.BLOCKED
    assert any(item.code is EvidencePathBlockerCode.INVARIANT_MISSING for item in missing.blockers)

    wrong_context = EvidencePathResolver().resolve(
        catalogue,
        _request(
            source,
            target,
            context_digest=canonical_value_digest({"tenant": "beta"}),
            preconditions=(precondition,),
            invariants=(invariant,),
        ),
        operating_system,
        pid,
    )
    assert wrong_context.status is EvidencePathStatus.BLOCKED
    assert any(item.code is EvidencePathBlockerCode.CONTEXT_MISMATCH for item in wrong_context.blockers)

    ready = EvidencePathResolver().resolve(
        catalogue,
        _request(
            source,
            target,
            preconditions=(precondition,),
            invariants=(invariant,),
        ),
        operating_system,
        pid,
    )
    assert ready.status is EvidencePathStatus.FOUND


def test_oracle_evidence_requirement_does_not_upgrade_a_paired_case_check() -> None:
    """Mathematics: PAIRED_CASE evidence is excluded whenever the request minimum is INDEPENDENT_ORACLE."""
    source, target = _ref("source"), _ref("target")
    edge = _edge("paired-only", source, target, latency=1, energy=1)
    catalogue = EvidencePathCatalogue()
    catalogue.register(edge)
    operating_system, pid = _os("/cpu/execute")

    result = EvidencePathResolver().resolve(
        catalogue,
        _request(
            source,
            target,
            minimum_evidence=EvidenceStrength.INDEPENDENT_ORACLE,
        ),
        operating_system,
        pid,
    )

    assert result.status is EvidencePathStatus.BLOCKED
    assert any(item.code is EvidencePathBlockerCode.EVIDENCE_INSUFFICIENT for item in result.blockers)


def test_catalogue_snapshot_round_trip_preserves_edge_identity_and_digest() -> None:
    """Mathematics: canonical catalogue serialization is a fixed point under strict edge reconstruction."""
    source, target = _ref("source"), _ref("target")
    edge = _edge("round-trip", source, target, latency=3, energy=2)
    catalogue = EvidencePathCatalogue(max_edges=8)
    first_id = catalogue.register(edge)
    assert catalogue.register(edge) == first_id

    restored = EvidencePathCatalogue.from_dict(catalogue.to_dict())

    assert restored.digest == catalogue.digest
    assert restored.edges == (edge,)
    assert restored.remove(first_id) is True
    assert restored.remove(first_id) is False


def test_exact_representation_content_identity_is_required_for_edge_chaining() -> None:
    """Mathematics: adjacent route steps compose only when target and next source RepresentationRefs are exactly equal."""
    source, intermediate_left, intermediate_right, target = map(
        _ref,
        ("source", "intermediate-left", "intermediate-right", "target"),
    )
    catalogue = EvidencePathCatalogue()
    catalogue.register(_edge("left", source, intermediate_left, latency=1, energy=1))
    catalogue.register(_edge("right", intermediate_right, target, latency=1, energy=1))
    operating_system, pid = _os("/cpu/execute")

    result = EvidencePathResolver().resolve(
        catalogue,
        _request(source, target),
        operating_system,
        pid,
    )

    assert result.status is EvidencePathStatus.UNREACHABLE
    assert not result.edge_ids


def test_hop_and_expansion_exhaustion_are_not_reported_as_unreachable() -> None:
    """Mathematics: finite resolver limits produce BUDGET_EXHAUSTED rather than a false unreachability claim."""
    source, middle, target = map(_ref, ("source", "middle", "target"))
    catalogue = EvidencePathCatalogue()
    catalogue.register(_edge("one", source, middle, latency=1, energy=1))
    catalogue.register(_edge("two", middle, target, latency=1, energy=1))
    operating_system, pid = _os("/cpu/execute")

    hop_limited = EvidencePathResolver().resolve(
        catalogue,
        _request(source, target, max_hops=1),
        operating_system,
        pid,
    )
    assert hop_limited.status is EvidencePathStatus.BUDGET_EXHAUSTED
    assert any(item.code is EvidencePathBlockerCode.HOP_LIMIT for item in hop_limited.blockers)

    expansion_limited = EvidencePathResolver().resolve(
        catalogue,
        _request(source, target, max_expansions=1),
        operating_system,
        pid,
    )
    assert expansion_limited.status is EvidencePathStatus.BUDGET_EXHAUSTED


def test_already_satisfied_target_needs_no_route_or_extra_capability() -> None:
    """Mathematics: source=target returns the empty route without inspecting graph edges or requesting an operation grant."""
    source = _ref("already-here")
    catalogue = EvidencePathCatalogue()
    operating_system, pid = _os()

    result = EvidencePathResolver().resolve(
        catalogue,
        _request(source, source),
        operating_system,
        pid,
    )

    assert result.status is EvidencePathStatus.ALREADY_AT_TARGET
    assert result.edge_ids == ()
    assert result.authoritative is False


def test_route_metric_unit_mismatch_is_a_blocker_not_a_silent_conversion() -> None:
    """Mathematics: the resolver never compares amounts whose metric names match but units differ."""
    source, target = _ref("source"), _ref("target")
    edge = _edge("units", source, target, latency=1, energy=1)
    catalogue = EvidencePathCatalogue()
    catalogue.register(edge)
    operating_system, pid = _os("/cpu/execute")
    request = _request(
        source,
        target,
        metric_order=(
            RouteMetricKey("latency_us", "ms"),
            RouteMetricKey("energy_nj", "nJ"),
        ),
    )

    result = EvidencePathResolver().resolve(catalogue, request, operating_system, pid)

    assert result.status is EvidencePathStatus.BLOCKED
    assert any(item.code is EvidencePathBlockerCode.METRIC_MISMATCH for item in result.blockers)


def test_route_evidence_and_cost_contract_mismatch_are_rejected_at_registration() -> None:
    """Mathematics: route registration rejects an observation pair bound to another contract and any cost above a declared contract ceiling."""
    source, target = _ref("source"), _ref("target")
    edge = _edge("first", source, target, latency=1, energy=1)
    other = _edge("other", source, target, latency=1, energy=1)

    with pytest.raises(ValueError, match="exact contract"):
        EvidencePathEdge(
            contract=edge.contract,
            comparison=other.comparison,
            costs=edge.costs,
        )


def test_route_result_digest_binds_request_and_receiver_authority_snapshot() -> None:
    """Mathematics: the same route and context under distinct live capability states produce distinct result digests."""
    source, target = _ref("source"), _ref("target")
    catalogue = EvidencePathCatalogue()
    catalogue.register(_edge("authority", source, target, latency=1, energy=1))
    cpu_os, cpu_pid = _os("/cpu/execute")
    gpu_pid = cpu_os.environment.kernel.spawn(
        "other-authority",
        capabilities=(
            Capability("/cpu/execute", frozenset({"execute"})),
            Capability("/gpu/execute", frozenset({"execute"})),
        ),
        parent_pid=cpu_os.environment.init_pid,
    )
    cpu_result = EvidencePathResolver().resolve(
        catalogue,
        _request(source, target),
        cpu_os,
        cpu_pid,
    )
    gpu_result = EvidencePathResolver().resolve(
        catalogue,
        _request(source, target),
        cpu_os,
        gpu_pid,
    )

    assert cpu_result.status is EvidencePathStatus.FOUND
    assert gpu_result.status is EvidencePathStatus.FOUND
    assert cpu_result.authority_digest != gpu_result.authority_digest
    assert cpu_result.digest != gpu_result.digest


def test_execution_result_ingestion_rejects_non_receiver_results() -> None:
    """Mathematics: only a typed committed hypervisor execution result can introduce a Transit oracle edge."""
    with pytest.raises(ValueError, match="HypervisorExecutionResult"):
        EvidencePathEdge.from_execution_result(
            {"effect": {"_semantic_translation": {}, "_semantic_oracle": {}}},
            (
                RouteMetric("latency_us", "us", 1),
                RouteMetric("energy_nj", "nJ", 1),
            ),
        )


def test_committed_oracle_checked_transit_result_becomes_a_routable_edge() -> None:
    """Mathematics: one ALLOW CPU effect yields an oracle-backed edge and a FOUND route only after live receiver authorization."""
    operation = "execute deterministic CPU arithmetic program"
    resource = "/cpu/compute"
    event = HypervisorArbitrationEvent(
        "route-client",
        "compute",
        1,
        501,
        HypervisorRequest(
            operation,
            resource,
            {
                "source": "\n".join((
                    "set left 19",
                    "set right 23",
                    "add total left right",
                    "set offset 6",
                    "add result total offset",
                    "halt",
                )),
                "initial_registers": {"seed": 7},
                "max_ticks": 64,
            },
            frozenset({"execute"}),
            frozenset(),
        ),
    )
    operating_system = HeadlessOS()
    pid = operating_system.environment.kernel.spawn(
        "evidence-route-cpu",
        capabilities=(Capability(resource, frozenset({"execute"})),),
        parent_pid=operating_system.environment.init_pid,
    )
    operating_system.hypervisor.policy = HypervisorPolicy(
        review_confidence=0.0,
        automatic_confidence=0.0,
        destructive_confidence=0.0,
        danger_review_probability=1.0,
        embedding_review_confidence=1.0,
    )
    authorized = operating_system.hypervisor_authorize_event(pid, event)
    host = TransitComputeHost()
    handler_calls = {"count": 0}

    def execute() -> dict[str, object]:
        """Mathematics: count and evaluate exactly one first-seen receiver-local CPU operation."""
        handler_calls["count"] += 1
        return host.handle(authorized)

    manifest = ((operation, resource),)

    def encode_effect(raw_effect: object) -> dict[str, object]:
        """Mathematics: bind the raw effect to the committed policy decision, canonical form, and independent reference observation."""
        assert isinstance(raw_effect, dict)
        decision = operating_system.hypervisor_arbitration.decision_projection_for(authorized.identity)
        assert decision is not None
        _action, domain, decision_receipt, _revision = decision
        canonical_effect = json.loads(json.dumps(
            raw_effect,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ))
        translation = build_transit_translation_evidence(
            authorized,
            raw_effect,
            canonical_effect,
            backend_manifest=manifest,
            decision_receipt=decision_receipt,
            domain=domain.value,
        )
        oracle = build_transit_oracle_evidence(
            authorized,
            canonical_effect,
            operating_system,
        )
        assert oracle is not None
        return {
            **canonical_effect,
            "_semantic_translation": translation.to_dict(),
            "_semantic_oracle": oracle.to_dict(),
        }

    result = operating_system.hypervisor_arbitration.execute(
        authorized,
        {HypervisorDomain.CPU: execute},
        encode_effect,
    )
    assert result.executed is True
    assert result.action.value == "allow"
    assert result.domain is HypervisorDomain.CPU
    assert handler_calls["count"] == 1

    costs = (
        RouteMetric("latency_us", "us", 18),
        RouteMetric("energy_nj", "nJ", 240),
    )
    edge = EvidencePathEdge.from_execution_result(result, costs)
    assert edge.evidence_strength is EvidenceStrength.INDEPENDENT_ORACLE
    assert edge.transit_evidence is not None
    assert edge.oracle_evidence is not None

    catalogue = EvidencePathCatalogue()
    edge_id = catalogue.register(edge)
    source = edge.source
    target = edge.target
    request = EvidencePathRequest(
        source=source,
        target=target,
        context_digest=edge.contract.context_digest,
        metric_order=(
            RouteMetricKey("latency_us", "us"),
            RouteMetricKey("energy_nj", "nJ"),
        ),
        satisfied_preconditions=edge.contract.precondition_digests,
        satisfied_invariants=edge.contract.invariant_digests,
        minimum_evidence=EvidenceStrength.INDEPENDENT_ORACLE,
    )
    route = EvidencePathResolver().resolve(
        catalogue,
        request,
        operating_system,
        pid,
    )
    assert route.status is EvidencePathStatus.FOUND
    assert route.edge_ids == (edge_id,)
    assert route.evidence_strength is EvidenceStrength.INDEPENDENT_ORACLE

    replay = operating_system.hypervisor_arbitration.execute(
        authorized,
        {HypervisorDomain.CPU: execute},
        encode_effect,
    )
    assert replay.replayed is True
    assert replay.effect == result.effect
    assert handler_calls["count"] == 1
    replay_edge = EvidencePathEdge.from_execution_result(replay, costs)
    assert replay_edge.edge_id == edge.edge_id



def test_route_request_binds_explicit_operation_context_scopes() -> None:
    """Mathematics: an edge context is eligible iff it is explicitly listed in the request's bounded context set."""
    source, target = _ref("context-source"), _ref("context-target")
    operation_context = canonical_value_digest({"operation": "structural-read"})
    edge = _edge(
        "scoped-context",
        source,
        target,
        latency=3,
        energy=5,
        context_digest=operation_context,
    )
    catalogue = EvidencePathCatalogue()
    catalogue.register(edge)
    operating_system, pid = _os("/cpu/execute")

    primary_only = _request(source, target)
    blocked = EvidencePathResolver().resolve(
        catalogue,
        primary_only,
        operating_system,
        pid,
    )
    assert blocked.status is EvidencePathStatus.BLOCKED
    assert any(
        item.code is EvidencePathBlockerCode.CONTEXT_MISMATCH
        for item in blocked.blockers
    )

    scoped = EvidencePathRequest(
        source=source,
        target=target,
        context_digest=_CONTEXT_DIGEST,
        accepted_context_digests=(operation_context,),
        metric_order=_METRIC_ORDER,
    )
    assert scoped.accepted_context_digests == tuple(
        sorted({_CONTEXT_DIGEST, operation_context})
    )
    assert scoped.to_dict()["schema"] == "mailcpu.evidence-path-request.v2"
    assert scoped.digest != primary_only.digest
    found = EvidencePathResolver().resolve(
        catalogue,
        scoped,
        operating_system,
        pid,
    )
    assert found.status is EvidencePathStatus.FOUND
    assert found.context_digest == _CONTEXT_DIGEST

    too_many = tuple(
        canonical_value_digest({"context_index": index})
        for index in range(65)
    )
    with pytest.raises(ValueError, match="64-context request limit"):
        EvidencePathRequest(
            source=source,
            target=target,
            context_digest=_CONTEXT_DIGEST,
            accepted_context_digests=too_many,
            metric_order=_METRIC_ORDER,
        )
