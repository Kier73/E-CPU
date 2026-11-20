"""IPS-001: exact inverse timing and live native route qualification."""
from __future__ import annotations

import random
import pytest
from mailcpu import (
    Capability, CapabilityRequirement, EffectClass, HeadlessOS, ObservationContract,
    ReplayClass, RepresentationRef, ResourceBound, TranslationContract,
    canonical_value_digest, compare_projected_observations,
)
from mailcpu.evidence_path_resolver import (
    EvidencePathCatalogue, EvidencePathEdge, EvidencePathRequest,
    RouteMetric, RouteMetricKey,
)
from mailcpu.intention_phase_synthesis import (
    CommunicationIntention, PeriodicCommunicationWindow, PhaseSynthesisError,
    _synthesize_math, synthesize_communication_state,
    verify_communication_synthesis,
)

CLOCK = "a" * 64
GROUND = "b" * 64
CONTEXT = canonical_value_digest({"room": "observer-test"})


def _window(edge: str, period: int, phases: tuple[int, ...], *, delay: int = 1,
            capacity: int = 10, begin: int = 0, end: int = (1 << 63) - 1,
            clock: str = CLOCK) -> PeriodicCommunicationWindow:
    """Construct one isolated mathematical candidate schedule."""
    return PeriodicCommunicationWindow(edge, clock, GROUND, period, phases,
                                       delay, capacity, begin, end)


def _intent(early: int, deadline: int, *, payload: int = 5,
            max_ticks: int = 10, request: str = "c" * 64) -> CommunicationIntention:
    """Construct an exact intended delivery deadline and payload."""
    return CommunicationIntention(request, CLOCK, early, deadline, payload, max_ticks)


def test_trillion_tick_inverse_jump_and_non_coprime_crt() -> None:
    """Intersect a two-hop schedule at 10^15 without enumerating its history."""
    early = 10**15
    ids = ("1" * 64, "2" * 64)
    windows = (_window(ids[0], 4, (1,), delay=2),
               _window(ids[1], 6, (3,), delay=3))
    result = _synthesize_math(_intent(early, early + 50), ids, windows, "d" * 64)
    expected = early + ((1 - early) % 12)
    assert result.status == "possible_under_description"
    assert result.start_tick == expected
    assert result.arrival_tick == expected + 5
    assert result.edge_entry_ticks == ((ids[0], expected), (ids[1], expected + 2))
    assert (result.solution_residue, result.solution_period) == (1, 12)
    assert result.authoritative is False


def test_incompatible_phases_and_missing_window_have_distinct_outcomes() -> None:
    """An impossible declared schedule is not an absence of evidence."""
    ids = ("1" * 64, "2" * 64)
    one = _window(ids[0], 4, (1,), delay=2)
    two = _window(ids[1], 6, (0,), delay=3)
    impossible = _synthesize_math(_intent(0, 40), ids, (one, two), "d" * 64)
    assert impossible.status == "impossible_under_description"
    assert "phases" in impossible.detail
    missing = _synthesize_math(_intent(0, 40), ids, (one,), "d" * 64)
    assert missing.status == "undetermined"


def test_capacity_lease_arrival_and_unequal_clock_refuse() -> None:
    """Never convert stale, unaffordable or incommensurate offers into permission."""
    eid = "1" * 64
    intent = _intent(5, 25, payload=9, max_ticks=3)
    assert _synthesize_math(intent, (eid,), (_window(eid, 2, (0,), capacity=8),), "d" * 64).status == "impossible_under_description"
    assert _synthesize_math(intent, (eid,), (_window(eid, 2, (0,), delay=4),), "d" * 64).status == "impossible_under_description"
    assert _synthesize_math(intent, (eid,), (_window(eid, 2, (0,), begin=30, end=40),), "d" * 64).status == "impossible_under_description"
    assert _synthesize_math(intent, (eid,), (_window(eid, 2, (0,), clock="f" * 64),), "d" * 64).status == "undetermined"
    assert _synthesize_math(intent, (eid,), (_window(eid, 2, (0,), begin=6, end=6),), "d" * 64).start_tick == 6


def test_class_budget_explicitly_exhausts() -> None:
    """Refuse combinatorial class blowup rather than misreport impossibility."""
    eid = "1" * 64
    result = _synthesize_math(_intent(0, 100), (eid,),
                              (_window(eid, 9, tuple(range(9))),),
                              "d" * 64, max_classes=3)
    assert result.status == "budget_exhausted"


def test_random_small_oracle_for_earliest_coordinate() -> None:
    """Compare exact inverse navigation to independent stepwise enumeration."""
    rng = random.Random(173)
    ids = ("1" * 64, "2" * 64, "3" * 64)
    for _ in range(120):
        windows = tuple(_window(eid, p, tuple(sorted(rng.sample(range(p), rng.randint(1, p)))),
                                delay=rng.randint(1, 3), begin=rng.randint(0, 5), end=rng.randint(25, 50))
                        for eid, p in zip(ids, (rng.randint(2, 7) for _ in ids)))
        intention = _intent(rng.randint(0, 12), 60)
        out = _synthesize_math(intention, ids, windows, "d" * 64)
        brute = None
        for start in range(intention.not_before, intention.arrive_by + 1):
            offset = 0
            feasible = True
            for window in windows:
                entry = start + offset
                if (entry % window.period not in window.phases
                        or entry < window.valid_from
                        or entry + window.transit_ticks - 1 > window.valid_through
                        or window.capacity_bytes < intention.payload_bytes):
                    feasible = False
                    break
                offset += window.transit_ticks
            if feasible and offset <= intention.max_transit_ticks and start + offset <= intention.arrive_by:
                brute = start
                break
        assert out.start_tick == brute
        assert (out.status == "possible_under_description") == (brute is not None)


def _native() -> tuple[EvidencePathCatalogue, EvidencePathRequest, HeadlessOS, int, str]:
    """Build one receiver-qualified path using E-CPU's actual native types."""
    source = RepresentationRef.from_payload("ips.node", 1, {"id": "source"})
    target = RepresentationRef.from_payload("ips.node", 1, {"id": "target"})
    contract = TranslationContract(
        contract_id="ips.one", revision=1, source=source, target=target,
        mapping=RepresentationRef.from_payload("ips.map", 1, {"id": "edge"}),
        observation=ObservationContract.from_definition("ips.observer", 1, {"check": "equality"}),
        context_digest=CONTEXT,
        resource_bounds=(ResourceBound("latency_us", 999, "us"),),
        authority_requirements=(CapabilityRequirement("/ips/execute", ("execute",)),),
        effect_class=EffectClass.PURE, replay_class=ReplayClass.DETERMINISTIC)
    comparison = compare_projected_observations(
        contract, case_payload={"id": "one"},
        source_observation={"value": 1}, target_observation={"value": 1})
    edge = EvidencePathEdge(contract, comparison, (RouteMetric("latency_us", "us", 1),))
    catalogue = EvidencePathCatalogue()
    catalogue.register(edge)
    request = EvidencePathRequest(source=source, target=target,
                                  context_digest=CONTEXT,
                                  metric_order=(RouteMetricKey("latency_us", "us"),))
    os = HeadlessOS()
    pid = os.environment.kernel.spawn(
        "ips-test", capabilities=(Capability("/ips/execute", frozenset({"execute"})),),
        parent_pid=os.environment.init_pid)
    return catalogue, request, os, pid, edge.edge_id


def test_native_route_permission_and_independent_reverification() -> None:
    """Every candidate must derive from live native qualified evidence."""
    catalogue, request, os, pid, edge = _native()
    intention = _intent(10, 100, request=request.digest)
    windows = (_window(edge, 5, (2,)),)
    result = synthesize_communication_state(intention, windows, catalogue, request, os, pid)
    assert result.status == "possible_under_description"
    assert result.start_tick == 12
    assert verify_communication_synthesis(result, intention, windows, catalogue, request, os, pid)
    assert not verify_communication_synthesis(result, intention, (_window(edge, 5, (3,)),),
                                              catalogue, request, os, pid)
    with pytest.raises(PhaseSynthesisError):
        synthesize_communication_state(_intent(10, 100), windows, catalogue, request, os, pid)
    # Remove route evidence without changing the request: no invented route.
    catalogue.remove(edge)
    rejected = synthesize_communication_state(intention, windows, catalogue, request, os, pid)
    assert rejected.status == "unqualified"
    assert not verify_communication_synthesis(result, intention, windows, catalogue, request, os, pid)
