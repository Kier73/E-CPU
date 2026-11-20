"""IPS-002: intention-first inverse construction of communication architectures.

A receiver can describe a needed communication result and a finite palette of
existing evidence edges and hypothetical relations. This compiler explores
compositions, solves their phase constraints without iterating scheduler time,
and re-qualifies fully evidenced candidates through native E-CPU routing.

Offers are *not* EvidencePathEdges. No topology, periodic availability,
remote authorization, active service or physical realization is created here.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from .evidence_path_resolver import (
    EvidencePathCatalogue, EvidencePathEdge, EvidencePathRequest,
    EvidencePathResolver, EvidencePathStatus, RouteMetric,
)
from .headless import HeadlessOS
from .intention_phase_synthesis import (
    CommunicationIntention, PeriodicCommunicationWindow,
    PhaseSynthesisResult, _synthesize_math,
)
from .semantic_translation import RepresentationRef, canonical_value_digest

_SCHEMA = "mailcpu.inverse-architecture-synthesis.v1"
_MAX_EDGES = 256
_MAX_OFFERS = 64
_MAX_WINDOWS = 320
_MAX_HOPS = 8
_MAX_EXPANSIONS = 10_000
_MAX_CANDIDATES = 128


class ArchitectureSynthesisError(ValueError):
    """An inverse-architecture intention, palette or budget is invalid."""


@dataclass(frozen=True)
class ProposedRelation:
    """A proposed virtual relation, never a verified native route edge.

    The receiver supplies a stable ID, both representation identities, a
    Ground/context anchor, a local verification obligation and estimated
    costs. Neither the ID nor its digest authenticates a provider.
    """

    relation_id: str
    source: RepresentationRef
    target: RepresentationRef
    ground_digest: str
    context_digest: str
    verifier_digest: str
    estimated_costs: tuple[RouteMetric, ...]

    def __post_init__(self) -> None:
        """Validate a typed, finite hypothetical relation."""
        from .intention_phase_synthesis import _digest
        for label in ("relation_id", "ground_digest", "context_digest", "verifier_digest"):
            _digest(getattr(self, label), label)
        if (not isinstance(self.source, RepresentationRef)
                or not isinstance(self.target, RepresentationRef)
                or self.source == self.target):
            raise ArchitectureSynthesisError("offer needs distinct typed endpoints")
        if (type(self.estimated_costs) is not tuple
                or not 1 <= len(self.estimated_costs) <= 6
                or any(not isinstance(c, RouteMetric) for c in self.estimated_costs)
                or len({c.name for c in self.estimated_costs}) != len(self.estimated_costs)):
            raise ArchitectureSynthesisError("offer requires distinct typed cost dimensions")
        object.__setattr__(self, "estimated_costs", tuple(
            sorted(self.estimated_costs, key=lambda c: c.name)
        ))

    @property
    def digest(self) -> str:
        """Bind every offered fact, without treating it as authentication."""
        return canonical_value_digest(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        """Return an inert, auditable proposal without executable handlers."""
        return {
            "relation_id": self.relation_id, "source": self.source.to_dict(),
            "target": self.target.to_dict(), "ground_digest": self.ground_digest,
            "context_digest": self.context_digest, "verifier_digest": self.verifier_digest,
            "estimated_costs": [c.to_dict() for c in self.estimated_costs],
            "evidence_status": "hypothetical_not_admitted",
        }


@dataclass(frozen=True)
class ArchitectureCandidate:
    """One exact mathematical schedule and a route/qualification distinction."""

    relation_ids: tuple[str, ...]
    missing_relation_ids: tuple[str, ...]
    phase: PhaseSynthesisResult
    costs: tuple[RouteMetric, ...]
    qualification: str
    native_route_digest: str | None
    verification_obligations: tuple[tuple[str, str], ...]

    @property
    def authoritative(self) -> bool:
        """Neither candidate status can authorize execution."""
        return False

    def to_dict(self) -> dict[str, Any]:
        """Encode selected architecture, temporal coordinate and obligations."""
        return {
            "relation_ids": list(self.relation_ids),
            "missing_relation_ids": list(self.missing_relation_ids),
            "phase": self.phase.to_dict(),
            "costs": [c.to_dict() for c in self.costs],
            "qualification": self.qualification,
            "native_route_digest": self.native_route_digest,
            "verification_obligations": [
                {"relation_id": rid, "verifier_digest": vid}
                for rid, vid in self.verification_obligations
            ],
            "authoritative": False,
        }


@dataclass(frozen=True)
class ArchitectureSynthesisResult:
    """Bounded, replayable findings; absent candidates are never universal proof."""

    status: str
    intention_digest: str
    request_digest: str
    catalogue_digest: str
    palette_digest: str
    selected_qualified: ArchitectureCandidate | None
    selected_construction: ArchitectureCandidate | None
    inspected_paths: int
    impossible_paths: int
    undetermined_paths: int
    blocked_paths: int
    search_complete: bool
    max_expansions: int
    max_candidates: int
    max_classes: int

    @property
    def authoritative(self) -> bool:
        """Planning and architecture construction never grant authority."""
        return False

    @property
    def digest(self) -> str:
        """Bind the intention, evidence snapshot, finite policy and result."""
        return canonical_value_digest(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        """Serialize both qualified and hypothetical architectures independently."""
        return {
            "schema": _SCHEMA, "authoritative": False, "status": self.status,
            "intention_digest": self.intention_digest, "request_digest": self.request_digest,
            "catalogue_digest": self.catalogue_digest, "palette_digest": self.palette_digest,
            "selected_qualified": (
                None if self.selected_qualified is None else self.selected_qualified.to_dict()
            ),
            "selected_construction": (
                None if self.selected_construction is None else self.selected_construction.to_dict()
            ),
            "inspected_paths": self.inspected_paths,
            "impossible_paths": self.impossible_paths,
            "undetermined_paths": self.undetermined_paths,
            "blocked_paths": self.blocked_paths,
            "search_complete": self.search_complete,
            "max_expansions": self.max_expansions,
            "max_candidates": self.max_candidates,
            "max_classes": self.max_classes,
            "claim": "bounded mathematical possibility; no future capacity reservation or effect",
        }


def _score(candidate: ArchitectureCandidate, request: EvidencePathRequest) -> tuple:
    """Order candidates by requested arrival, typed costs, then stable path identity."""
    by_name = {c.name: c.amount for c in candidate.costs}
    return (
        candidate.phase.arrival_tick, candidate.phase.start_tick,
        *(by_name[k.name] for k in request.metric_order),
        len(candidate.relation_ids), candidate.relation_ids,
    )


def synthesize_architecture(
    intention: CommunicationIntention,
    architecture_ground_digest: str,
    catalogue: EvidencePathCatalogue,
    request: EvidencePathRequest,
    offers: Sequence[ProposedRelation],
    windows: Sequence[PeriodicCommunicationWindow],
    operating_system: HeadlessOS,
    pid: int,
    *,
    max_hops: int = 6,
    max_expansions: int = 1024,
    max_candidates: int = 64,
    max_classes: int = 512,
) -> ArchitectureSynthesisResult:
    """Compile a desired result into candidate path architecture and coordinate.

    Enumerates only finite, simple routes through an explicitly supplied
    palette; time coordinates are solved with IPS-001 generalized CRT rather
    than stepped. For a wholly existing route, re-invokes native
    EvidencePathResolver on a subset of the original evidence catalogue with
    the caller's *original* request and live HeadlessOS authority.

    An offered relation is never registered as an EvidencePathEdge. Even a
    native-qualified phase remains a schedule hypothesis, not a reservation.
    """

    from .intention_phase_synthesis import _digest
    _digest(architecture_ground_digest, "architecture Ground")
    if (not isinstance(intention, CommunicationIntention)
            or not isinstance(catalogue, EvidencePathCatalogue)
            or not isinstance(request, EvidencePathRequest)
            or not isinstance(operating_system, HeadlessOS)
            or type(pid) is not int or pid < 1):
        raise ArchitectureSynthesisError("native intention, evidence and receiver required")
    if intention.request_digest != request.digest:
        raise ArchitectureSynthesisError("intention and native request differ")
    limits = (
        (max_hops, _MAX_HOPS), (max_expansions, _MAX_EXPANSIONS),
        (max_candidates, _MAX_CANDIDATES), (max_classes, 4096),
    )
    if any(type(n) is not int or not 1 <= n <= upper for n, upper in limits):
        raise ArchitectureSynthesisError("invalid finite architecture search budget")
    if request.source == request.target:
        raise ArchitectureSynthesisError("architecture synthesis requires distinct endpoints")

    native_edges = catalogue.edges
    if len(native_edges) > _MAX_EDGES:
        raise ArchitectureSynthesisError("catalogue exceeds IPS-002 bounded research palette")
    if (len(offers) > _MAX_OFFERS or len(windows) > _MAX_WINDOWS
            or any(not isinstance(o, ProposedRelation) for o in offers)
            or any(not isinstance(w, PeriodicCommunicationWindow) for w in windows)):
        raise ArchitectureSynthesisError("untyped or oversized candidate palette")
    native_by_id = {e.edge_id: e for e in native_edges}
    offer_by_id = {o.relation_id: o for o in offers}
    if (len(offer_by_id) != len(offers)
            or set(offer_by_id) & set(native_by_id)
            or any(o.ground_digest != architecture_ground_digest for o in offers)):
        raise ArchitectureSynthesisError("duplicate, colliding or cross-Ground offer")
    if any(o.context_digest not in request.accepted_context_digests for o in offers):
        raise ArchitectureSynthesisError("offered relation has unaccepted native context")

    by_window = {w.edge_id: w for w in windows}
    if (len(by_window) != len(windows)
            or not set(by_window).issubset(set(native_by_id) | set(offer_by_id))):
        raise ArchitectureSynthesisError("duplicate or unattached schedule description")

    order = tuple(request.metric_order)
    expected = {(k.name, k.unit) for k in order}
    ceilings = {c.name: c.amount for c in request.resource_ceilings}
    adjacency: dict[RepresentationRef, list[tuple[str, RepresentationRef, tuple[RouteMetric, ...], bool]]] = {}
    skipped_cost = 0
    for relation_id, e in native_by_id.items():
        if {(c.name, c.unit) for c in e.costs} != expected:
            skipped_cost += 1
            continue
        adjacency.setdefault(e.source, []).append((relation_id, e.target, e.costs, False))
    for relation_id, o in offer_by_id.items():
        if {(c.name, c.unit) for c in o.estimated_costs} != expected:
            raise ArchitectureSynthesisError("offer cost units do not match native request")
        adjacency.setdefault(o.source, []).append(
            (relation_id, o.target, o.estimated_costs, True)
        )
    for choices in adjacency.values():
        choices.sort(key=lambda option: option[0])

    palette_digest = canonical_value_digest({
        "schema": _SCHEMA + ".palette",
        "architecture_ground_digest": architecture_ground_digest,
        "offers": [o.to_dict() for o in sorted(offers, key=lambda o: o.relation_id)],
        "windows": [w.to_dict() for w in sorted(windows, key=lambda w: w.edge_id)],
    })
    best_qualified: ArchitectureCandidate | None = None
    best_proposed: ArchitectureCandidate | None = None
    inspected = impossible = undetermined = blocked = 0
    expansions = 0
    truncated = False
    hop_ceiling = min(max_hops, request.max_hops)
    stack: list[tuple[RepresentationRef, tuple[RepresentationRef, ...],
                      tuple[str, ...], tuple[str, ...], tuple[int, ...]]] = [
        (request.source, (request.source,), (), (), (0,) * len(order))
    ]

    while stack:
        if expansions >= max_expansions:
            truncated = True
            break
        node, visited, ids, missing, total = stack.pop()
        expansions += 1

        if node == request.target and ids:
            if inspected >= max_candidates:
                truncated = True
                break
            inspected += 1
            phase_windows = [by_window[x] for x in ids if x in by_window]
            if len(phase_windows) != len(ids):
                undetermined += 1
                continue
            claim_digest = canonical_value_digest({
                "kind": "unqualified-inverse-architecture", "palette_digest": palette_digest,
                "relation_ids": ids,
            })
            phase = _synthesize_math(
                intention, ids, phase_windows, claim_digest, max_classes=max_classes
            )
            if phase.status == "impossible_under_description":
                impossible += 1
                continue
            if phase.status != "possible_under_description":
                undetermined += 1
                continue
            native_digest: str | None = None
            qualification = "construction_required"
            if not missing:
                # Only the native resolver can qualify an existing route. It
                # checks current evidence, contracts, budgets and kernel rights.
                subset = EvidencePathCatalogue(max_edges=len(ids))
                for relation_id in ids:
                    subset.register(native_by_id[relation_id])
                resolved = EvidencePathResolver().resolve(
                    subset, request, operating_system, pid
                )
                if (resolved.status is not EvidencePathStatus.FOUND
                        or resolved.edge_ids != ids):
                    blocked += 1
                    continue
                native_digest = resolved.digest
                qualification = "native_route_qualified_schedule_hypothesis"
                phase = _synthesize_math(
                    intention, ids, phase_windows, resolved.digest, max_classes=max_classes
                )
            costs = tuple(RouteMetric(k.name, k.unit, total[i])
                          for i, k in enumerate(order))
            obligations = tuple(
                (relation_id, offer_by_id[relation_id].verifier_digest)
                for relation_id in ids if relation_id in offer_by_id
            )
            candidate = ArchitectureCandidate(
                ids, missing, phase, costs, qualification, native_digest, obligations
            )
            if missing:
                if (best_proposed is None
                        or _score(candidate, request) < _score(best_proposed, request)):
                    best_proposed = candidate
            elif (best_qualified is None
                  or _score(candidate, request) < _score(best_qualified, request)):
                best_qualified = candidate
            continue

        if len(ids) >= hop_ceiling:
            continue
        # Reverse push yields deterministic ascending depth-first traversal.
        for relation_id, target, edge_costs, is_offer in reversed(adjacency.get(node, ())):
            if target in visited:
                continue
            amounts = {c.name: c.amount for c in edge_costs}
            new_total = tuple(total[i] + amounts[k.name] for i, k in enumerate(order))
            if any(new_total[i] > ceilings[k.name]
                   for i, k in enumerate(order) if k.name in ceilings):
                continue
            stack.append((
                target, visited + (target,), ids + (relation_id,),
                missing + ((relation_id,) if is_offer else ()), new_total,
            ))

    if best_qualified is not None:
        status = "qualified_route_with_hypothetical_schedule"
    elif best_proposed is not None:
        status = "construction_required"
    elif truncated:
        status = "budget_exhausted"
    elif undetermined:
        status = "undetermined"
    elif blocked:
        status = "unqualified_under_current_authority"
    else:
        status = "no_candidate_in_described_palette"

    return ArchitectureSynthesisResult(
        status, intention.digest, request.digest, catalogue.digest, palette_digest,
        best_qualified, best_proposed, inspected, impossible, undetermined,
        blocked + skipped_cost, not truncated, max_expansions, max_candidates, max_classes,
    )


def verify_architecture_synthesis(
    expected: ArchitectureSynthesisResult,
    intention: CommunicationIntention,
    architecture_ground_digest: str,
    catalogue: EvidencePathCatalogue,
    request: EvidencePathRequest,
    offers: Sequence[ProposedRelation],
    windows: Sequence[PeriodicCommunicationWindow],
    operating_system: HeadlessOS,
    pid: int,
    *,
    max_hops: int = 6,
    max_expansions: int = 1024,
    max_candidates: int = 64,
    max_classes: int = 512,
) -> bool:
    """Recompute from source inputs and live receiver authority, rejecting drift."""
    if not isinstance(expected, ArchitectureSynthesisResult):
        raise ArchitectureSynthesisError("expected typed architecture result")
    return expected == synthesize_architecture(
        intention, architecture_ground_digest, catalogue, request, offers, windows,
        operating_system, pid, max_hops=max_hops, max_expansions=max_expansions,
        max_candidates=max_candidates, max_classes=max_classes,
    )
