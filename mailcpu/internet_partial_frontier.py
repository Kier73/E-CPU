"""INTERNET-007: VGI-inspired partial-frontier attention over E-CPU Ground relations.

Only independently verified InternetObservationCase values enter the existing
InternetGroundRouter / EvidencePathResolver. Hypothetical ProbeOffers remain
outside all routing catalogues. A bounded search over offers finds *possible*
completion sequences, while each intervening known segment is resolved by the
existing receiver-authorized native route planner. This policy does not issue
execution rights, infer probe-success probabilities, or claim that an unobserved
relation is a verified Ground.

The inherited ProspectiveQualifier.step / run own probe dispatch, bounded raw
capture, receiver verifier, native case admission, and append-only failure
records. This subclass changes only where attention is directed next.
"""
from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace
from typing import Any

from .evidence_path_resolver import EvidencePathStatus, RouteMetric
from .internet_prospective_qualification import (
    ProbeDecision, ProbeOffer, ProspectiveQualifier, ProspectiveRefused,
)
from .internet_ground_routing import InternetIntention
from .headless import HeadlessOS
from .semantic_translation import RepresentationRef, canonical_value_digest

_MAX_MISSING = 4
_MAX_EXPLORATIONS = 2048
_MAX_PLANS = 256
_MAX_NATIVE_QUERIES = 1200


@dataclass(frozen=True)
class _HypotheticalPlan:
    """One *not admitted* completion hypothesis, never a native route."""

    offer_digests: tuple[str, ...]
    total_costs: tuple[RouteMetric, ...]
    known_edge_ids: tuple[str, ...]
    total_hops: int

    @property
    def digest(self) -> str:
        return canonical_value_digest({
            "offers": list(self.offer_digests),
            "costs": [x.to_dict() for x in self.total_costs],
            "known_edges": list(self.known_edge_ids),
            "hops": self.total_hops,
        })


class _FrontierBudgetExceeded(RuntimeError):
    """No extrapolation from a partially enumerated candidate space."""


class PartialFrontierQualifier(ProspectiveQualifier):
    """Choose only an *accessible first missing edge* on a bounded frontier.

    Preference: an already-qualified route; a decisive single missing edge;
    otherwise minimum missing-edge count among possible completions. With
    equal minimum gaps, first probes that appear in more qualified-prefix
    completion paths get attention, then lower estimated total route cost.
    Coverage counts are structural hypothesis counts, NOT probabilities.
    """

    def choose(self, intent: InternetIntention, os: HeadlessOS, pid: int) -> ProbeDecision:
        first = super().choose(intent, os, pid)
        if first.status != "no_eligible_probe":
            return first

        # Authority, source identity and permitted operation filters are the
        # same as in INTERNET-006. No handler is dispatched during attention.
        attempted = {event.offer_digest for event in self.history}
        units = {m.name: m.unit for m in intent.metric_order}
        ceilings = {m.name: m.amount for m in intent.resource_ceilings}
        allowed: list[ProbeOffer] = []
        considered = list(first.considered)
        for offer in sorted(self.offers, key=lambda o: o.digest):
            reason = None
            if offer.digest in attempted:
                reason = "previously_attempted"
            elif offer.provider_id not in self.policy.allowed_providers or offer.provider_id not in self.handlers:
                reason = "no_receiver_installed_probe"
            elif offer.kind not in intent.allowed_kinds:
                reason = "kind_not_requested"
            elif offer.ground_digest != intent.ground_digest or offer.context_digest != intent.context_digest:
                reason = "ground_or_context_mismatch"
            elif not offer.available_at <= intent.now <= offer.expires_at:
                reason = "expired_or_future"
            elif {m.name: m.unit for m in offer.estimated_costs} != units:
                reason = "incomparable_costs"
            elif intent.minimum_evidence.value == "independent_oracle":
                reason = "unsupported_native_evidence_tier"
            elif not self._authorized(os, pid, offer):
                reason = "local_probe_authority_missing"
            if reason is not None:
                considered.append({"offer_digest": offer.digest, "reason": reason})
            else:
                allowed.append(offer)

        if len(allowed) < 2 or intent.max_hops < 2:
            return ProbeDecision("no_eligible_probe", None, None, (), first.existing_route,
                                 tuple(considered))
        # Cache only results of the *actual*, live-capability-aware native
        # router. Never approximate verified transitions with an inferred edge.
        checked: dict[tuple[RepresentationRef, RepresentationRef], dict] = {}
        known_cases = {case.case_digest: case for case in self.router._cases.values()}
        queries = 0
        explorations = 0
        metric_names = tuple(m.name for m in intent.metric_order)
        zero = tuple(0 for _ in metric_names)

        def route(source: RepresentationRef, target: RepresentationRef) -> dict | None:
            nonlocal queries
            key = (source, target)
            if key not in checked:
                if queries >= _MAX_NATIVE_QUERIES:
                    raise _FrontierBudgetExceeded("native routing query budget")
                queries += 1
                outcome = self.router.resolve(replace(intent, source=source, target=target), os, pid)
                checked[key] = outcome
            result = checked[key]
            if result["status"] not in (
                EvidencePathStatus.FOUND.value, EvidencePathStatus.ALREADY_AT_TARGET.value
            ):
                return None
            return result

        def route_trace(result: dict, source: RepresentationRef,
                        visited: frozenset[RepresentationRef]) -> tuple[frozenset[RepresentationRef], tuple[str, ...]] | None:
            """Check that a native segment does not revisit prospective states."""
            current = source
            next_visited = visited
            edges: list[str] = []
            for step in result["selected"]:
                case = known_cases.get(step["case_digest"])
                if case is None or case.source != current or case.target in next_visited:
                    return None
                current = case.target
                next_visited = next_visited | {current}
                edges.append(step["case_digest"])
            return next_visited, tuple(edges)

        def route_costs(result: dict) -> tuple[int, ...]:
            values = {m["name"]: m["amount"] for m in result["route"]["total_costs"]}
            return tuple(values.get(name, 0) for name in metric_names)

        def add_costs(*vectors: tuple[int, ...]) -> tuple[int, ...]:
            return tuple(sum(column) for column in zip(*vectors))

        def fits(costs: tuple[int, ...]) -> bool:
            return all(cost <= ceilings[name] for name, cost in zip(metric_names, costs)
                       if name in ceilings)

        offers = tuple(allowed)
        plans: list[_HypotheticalPlan] = []
        # Iterative deepening limits the number of unknown relations. A path
        # with k-1 unknowns is examined in full before considering k.
        try:
            for desired_gaps in range(2, min(_MAX_MISSING, len(offers), intent.max_hops) + 1):
                plans.clear()
                explorations = 0

                def walk(current: RepresentationRef, previous: tuple[str, ...],
                         visited: frozenset[RepresentationRef],
                         costs: tuple[int, ...], hops: int,
                         known: tuple[str, ...]) -> None:
                    nonlocal explorations
                    if explorations >= _MAX_EXPLORATIONS:
                        raise _FrontierBudgetExceeded("hypothetical expansion budget")
                    explorations += 1
                    if len(previous) == desired_gaps:
                        tail = route(current, intent.target)
                        if tail is None:
                            return
                        traversed = route_trace(tail, current, visited)
                        if traversed is None:
                            return
                        tail_costs = route_costs(tail)
                        total_hops = hops + len(tail["route"]["edge_ids"])
                        combined = add_costs(costs, tail_costs)
                        if total_hops > intent.max_hops or not fits(combined):
                            return
                        if len(plans) >= _MAX_PLANS:
                            raise _FrontierBudgetExceeded("hypothetical plan budget")
                        plans.append(_HypotheticalPlan(
                            previous,
                            tuple(RouteMetric(m.name, m.unit, amount)
                                  for m, amount in zip(intent.metric_order, combined)),
                            known + traversed[1], total_hops,
                        ))
                        return
                    for offer in offers:
                        if offer.digest in previous or offer.target in visited:
                            continue
                        segment = route(current, offer.source)
                        if segment is None:
                            continue
                        traversed = route_trace(segment, current, visited)
                        if traversed is None or offer.target in traversed[0]:
                            continue
                        step_hops = hops + len(segment["route"]["edge_ids"]) + 1
                        if step_hops > intent.max_hops:
                            continue
                        estimated = tuple(next(m.amount for m in offer.estimated_costs if m.name == name)
                                          for name in metric_names)
                        aggregate = add_costs(costs, route_costs(segment), estimated)
                        if not fits(aggregate):
                            continue
                        walk(offer.target, previous + (offer.digest,),
                             traversed[0] | {offer.target}, aggregate, step_hops,
                             known + traversed[1])

                walk(intent.source, (), frozenset({intent.source}), zero, 0, ())
                if plans:
                    break
        except _FrontierBudgetExceeded:
            return ProbeDecision("budget_exhausted", None, None, (), first.existing_route,
                                 tuple(considered + [{"reason": "bounded_search_incomplete",
                                                     "native_queries": queries}]))

        if not plans:
            return ProbeDecision("no_eligible_probe", None, None, (), first.existing_route,
                                 tuple(considered + [{"reason": "no_bounded_multi_gap_completion",
                                                     "native_queries": queries}]))
        # Only the FIRST unverified relation has a verified reachable prefix.
        # Later gaps must not be probed as if their hypothetical predecessors
        # had already been realized. Coverage is a count of finite alternatives.
        counts: dict[str, int] = {}
        best_route: dict[str, _HypotheticalPlan] = {}
        for plan in plans:
            first_digest = plan.offer_digests[0]
            counts[first_digest] = counts.get(first_digest, 0) + 1
            if (first_digest not in best_route or
                    tuple(m.amount for m in plan.total_costs) <
                    tuple(m.amount for m in best_route[first_digest].total_costs)):
                best_route[first_digest] = plan

        def priority(digest: str) -> tuple:
            best = best_route[digest]
            first_offer = next(o for o in offers if o.digest == digest)
            return (-counts[digest],
                    tuple(m.amount for m in best.total_costs),
                    tuple(next(m.amount for m in first_offer.estimated_costs if m.name == name)
                          for name in metric_names), digest)

        selected_digest = min(counts, key=priority)
        selected_offer = next(o for o in offers if o.digest == selected_digest)
        best = best_route[selected_digest]
        considered.append({
            "reason": "multi_gap_hypothesis_only",
            "minimum_missing_relations": len(best.offer_digests),
            "candidate_completions": len(plans),
            "first_probe_coverage": counts[selected_digest],
            "native_queries": queries,
            "selected_possible_completion": list(best.offer_digests),
            "known_case_digests": list(best.known_edge_ids),
            "not": "hypothetical_offers_are_never_native_evidence_or_authority",
        })
        return ProbeDecision("probe_recommended", selected_offer.digest,
                             selected_offer.provider_id, best.total_costs,
                             first.existing_route, tuple(considered))
