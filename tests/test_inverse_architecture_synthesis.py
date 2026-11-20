"""IPS-002: intention-driven route architecture search and phase synthesis."""
from __future__ import annotations

from dataclasses import replace

import pytest

from mailcpu import (
    Capability, CapabilityRequirement, EffectClass, HeadlessOS,
    ObservationContract, ReplayClass, RepresentationRef, ResourceBound,
    TranslationContract, canonical_value_digest, compare_projected_observations,
)
from mailcpu.evidence_path_resolver import (
    EvidencePathCatalogue, EvidencePathEdge, EvidencePathRequest,
    EvidencePathResolver, EvidencePathStatus, RouteMetric, RouteMetricKey,
)
from mailcpu.intention_phase_synthesis import (
    CommunicationIntention, PeriodicCommunicationWindow,
)
from mailcpu.inverse_architecture_synthesis import (
    ArchitectureSynthesisError, ProposedRelation, synthesize_architecture,
    verify_architecture_synthesis,
)

CLOCK = "a" * 64
GROUND = "b" * 64
VERIFIER = "f" * 64
CONTEXT = canonical_value_digest({"system": "ips-002", "revision": 1})


def _ref(name: str) -> RepresentationRef:
    """Construct one exact finite representation identity."""
    return RepresentationRef.from_payload("ips002.representation", 1, {"node": name})


def _edge(name: str, source: RepresentationRef, target: RepresentationRef,
          latency: int, resource: str = "/ips/execute") -> EvidencePathEdge:
    """Build an independently checked exact-case native translation."""
    contract = TranslationContract(
        contract_id="ips002." + name, revision=1, source=source, target=target,
        mapping=RepresentationRef.from_payload("ips002.mapping", 1, {"edge": name}),
        observation=ObservationContract.from_definition(
            "ips002.observer", 1, {"projection": "same-typed-value"}
        ),
        context_digest=CONTEXT,
        resource_bounds=(ResourceBound("latency_us", 999, "us"),),
        authority_requirements=(CapabilityRequirement(resource, ("execute",)),),
        effect_class=EffectClass.PURE, replay_class=ReplayClass.DETERMINISTIC,
    )
    comparison = compare_projected_observations(
        contract, case_payload={"id": name},
        source_observation={"value": name}, target_observation={"value": name},
    )
    return EvidencePathEdge(
        contract, comparison, (RouteMetric("latency_us", "us", latency),)
    )


def _os(*resources: str) -> tuple[HeadlessOS, int]:
    """Issue live receiver process capabilities for the test."""
    operating_system = HeadlessOS()
    pid = operating_system.environment.kernel.spawn(
        "ips002-test",
        capabilities=tuple(Capability(x, frozenset({"execute"})) for x in resources),
        parent_pid=operating_system.environment.init_pid,
    )
    return operating_system, pid


def _window(edge_id: str, period: int, phases: tuple[int, ...],
            delay: int = 1, capacity: int = 100,
            *, clock: str = CLOCK) -> PeriodicCommunicationWindow:
    """Describe a hypothetical periodic transfer window in one logical clock."""
    return PeriodicCommunicationWindow(
        edge_id, clock, GROUND, period, phases, delay, capacity,
        0, (1 << 63) - 1,
    )


def _fixture():
    """Create two alternative native routes; the cheapest has no feasible phase."""
    s, a, b, t = map(_ref, ("source", "cheap", "feasible", "target"))
    edges = (
        _edge("cheap1", s, a, 1), _edge("cheap2", a, t, 1),
        _edge("alternative1", s, b, 4), _edge("alternative2", b, t, 4),
    )
    catalogue = EvidencePathCatalogue()
    for edge in edges:
        catalogue.register(edge)
    request = EvidencePathRequest(
        source=s, target=t, context_digest=CONTEXT,
        metric_order=(RouteMetricKey("latency_us", "us"),),
    )
    os, pid = _os("/ips/execute")
    early = 10**15
    intention = CommunicationIntention(request.digest, CLOCK, early, early + 100, 8, 8)
    windows = (
        _window(edges[0].edge_id, 4, (0,), delay=1),
        _window(edges[1].edge_id, 6, (0,), delay=1),  # t even, t+1 == 0 (mod 6): impossible
        _window(edges[2].edge_id, 4, (1,), delay=2),
        _window(edges[3].edge_id, 6, (3,), delay=3),
    )
    return catalogue, request, os, pid, intention, edges, windows


def test_find_alternative_architecture_when_cheapest_native_route_has_no_phase() -> None:
    """Joint route-and-time synthesis succeeds where single-route IPS-001 cannot."""
    catalogue, request, os, pid, intention, edges, windows = _fixture()
    cheapest = EvidencePathResolver().resolve(catalogue, request, os, pid)
    assert cheapest.status is EvidencePathStatus.FOUND
    assert cheapest.edge_ids == (edges[0].edge_id, edges[1].edge_id)

    result = synthesize_architecture(
        intention, GROUND, catalogue, request, (), windows, os, pid
    )
    assert result.status == "qualified_route_with_hypothetical_schedule"
    assert result.selected_qualified is not None
    candidate = result.selected_qualified
    assert candidate.relation_ids == (edges[2].edge_id, edges[3].edge_id)
    assert candidate.missing_relation_ids == ()
    assert candidate.phase.start_tick == 10**15 + ((1 - 10**15) % 12)
    assert candidate.phase.arrival_tick == candidate.phase.start_tick + 5
    assert candidate.native_route_digest is not None
    assert candidate.authoritative is False
    assert result.impossible_paths == 1
    assert result.search_complete
    assert verify_architecture_synthesis(
        result, intention, GROUND, catalogue, request, (), windows, os, pid
    )


def test_imposed_missing_relation_returns_construction_obligation_not_authority() -> None:
    """A mathematical shortcut cannot silently manufacture a qualified edge."""
    catalogue, request, os, pid, intention, edges, windows = _fixture()
    offer = ProposedRelation(
        "9" * 64, request.source, request.target, GROUND,
        CONTEXT, VERIFIER, (RouteMetric("latency_us", "us", 1),),
    )
    result = synthesize_architecture(
        intention, GROUND, catalogue, request, (offer,),
        windows + (_window(offer.relation_id, 1, (0,), delay=1),),
        os, pid,
    )
    assert result.selected_qualified is not None
    assert result.selected_construction is not None
    construction = result.selected_construction
    assert construction.phase.start_tick == intention.not_before
    assert construction.missing_relation_ids == (offer.relation_id,)
    assert construction.verification_obligations == ((offer.relation_id, VERIFIER),)
    assert construction.native_route_digest is None
    assert construction.qualification == "construction_required"
    assert construction.authoritative is False
    assert len(catalogue.edges) == 4
    assert all(e.edge_id != offer.relation_id for e in catalogue.edges)


def test_only_missing_architecture_is_explicitly_not_yet_qualified() -> None:
    """Even an exactly navigable design is only a proposal until independently admitted."""
    cat, request, os, pid, intent, _, _ = _fixture()
    cat = EvidencePathCatalogue()
    offer = ProposedRelation(
        "8" * 64, request.source, request.target, GROUND, CONTEXT,
        VERIFIER, (RouteMetric("latency_us", "us", 1),),
    )
    w = _window(offer.relation_id, 3, (0,), delay=1)
    result = synthesize_architecture(
        intent, GROUND, cat, request, (offer,), (w,), os, pid
    )
    assert result.status == "construction_required"
    assert result.selected_qualified is None
    assert result.selected_construction is not None
    assert result.selected_construction.phase.start_tick % 3 == 0
    assert result.selected_construction.native_route_digest is None


def test_live_receiver_rights_and_removed_evidence_reject_native_candidate() -> None:
    """No old candidate is promoted when its native route loses evidence/authority."""
    cat, request, os, pid, intent, edges, windows = _fixture()
    expected = synthesize_architecture(
        intent, GROUND, cat, request, (), windows, os, pid
    )
    no_rights, no_rights_pid = _os()
    refused = synthesize_architecture(
        intent, GROUND, cat, request, (), windows, no_rights, no_rights_pid
    )
    assert refused.selected_qualified is None
    assert refused.blocked_paths > 0
    assert not verify_architecture_synthesis(
        expected, intent, GROUND, cat, request, (), windows,
        no_rights, no_rights_pid,
    )
    cat.remove(edges[3].edge_id)
    # A now-orphaned schedule is rejected as stale input rather than silently
    # retained as admissible route evidence.
    with pytest.raises(ArchitectureSynthesisError):
        synthesize_architecture(
            intent, GROUND, cat, request, (), windows, os, pid
        )
    remaining_windows = tuple(
        w for w in windows if w.edge_id != edges[3].edge_id
    )
    no_edge = synthesize_architecture(
        intent, GROUND, cat, request, (), remaining_windows, os, pid
    )
    assert no_edge.selected_qualified is None
    assert not verify_architecture_synthesis(
        expected, intent, GROUND, cat, request, (), remaining_windows, os, pid
    )


def test_missing_window_and_bounded_search_are_not_impossibility_proofs() -> None:
    """Search exhaustion and missing descriptions are three-valued, not false."""
    cat, request, os, pid, intent, edges, windows = _fixture()
    partial = synthesize_architecture(
        intent, GROUND, cat, request, (), windows[:2], os, pid
    )
    assert partial.selected_qualified is None
    assert partial.status == "undetermined"
    assert partial.undetermined_paths
    exhausted = synthesize_architecture(
        intent, GROUND, cat, request, (), windows, os, pid,
        max_expansions=1,
    )
    assert not exhausted.search_complete
    assert exhausted.status == "budget_exhausted"
    assert exhausted.selected_qualified is None


def test_typed_offer_rejections_and_description_drift() -> None:
    """Wrong context/Ground, unknown windows, and changed proposals cannot pass."""
    cat, request, os, pid, intent, edges, windows = _fixture()
    offer = ProposedRelation(
        "7" * 64, request.source, request.target, GROUND,
        CONTEXT, VERIFIER, (RouteMetric("latency_us", "us", 1),),
    )
    with pytest.raises(ArchitectureSynthesisError):
        synthesize_architecture(
            intent, GROUND, cat, request,
            (replace(offer, ground_digest="0"*64),), windows, os, pid
        )
    with pytest.raises(ArchitectureSynthesisError):
        synthesize_architecture(
            intent, GROUND, cat, request, (replace(offer, context_digest="0"*64),),
            windows, os, pid
        )
    with pytest.raises(ArchitectureSynthesisError):
        synthesize_architecture(
            intent, GROUND, cat, request, (offer, offer), windows, os, pid
        )
    with pytest.raises(ArchitectureSynthesisError):
        synthesize_architecture(
            intent, GROUND, cat, request, (),
            windows + (_window("6" * 64, 2, (0,)),), os, pid
        )
    with pytest.raises(ArchitectureSynthesisError):
        synthesize_architecture(
            intent, GROUND, cat, request, (),
            (replace(windows[0], schedule_ground_digest="0" * 64),) + windows[1:],
            os, pid,
        )
    original = synthesize_architecture(
        intent, GROUND, cat, request, (offer,),
        windows + (_window(offer.relation_id, 2, (0,)),), os, pid
    )
    changed = replace(offer, verifier_digest="e" * 64)
    assert not verify_architecture_synthesis(
        original, intent, GROUND, cat, request, (changed,),
        windows + (_window(offer.relation_id, 2, (0,)),), os, pid
    )


def test_global_route_cost_ceiling_prunes_advisory_offers() -> None:
    """Even hypothetical architecture choices cannot evade the request budget."""
    cat, req, os, pid, _, _, windows = _fixture()
    constrained = EvidencePathRequest(
        source=req.source, target=req.target, context_digest=CONTEXT,
        metric_order=req.metric_order,
        resource_ceilings=(RouteMetric("latency_us", "us", 1),),
    )
    intent = CommunicationIntention(constrained.digest, CLOCK, 0, 50, 8, 8)
    offer = ProposedRelation(
        "5" * 64, req.source, req.target, GROUND, CONTEXT,
        VERIFIER, (RouteMetric("latency_us", "us", 5),),
    )
    result = synthesize_architecture(
        intent, GROUND, cat, constrained, (offer,),
        windows + (_window(offer.relation_id, 1, (0,)),), os, pid
    )
    assert result.selected_construction is None
    assert result.selected_qualified is None
    assert result.status == "no_candidate_in_described_palette"
