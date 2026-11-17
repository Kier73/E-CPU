"""INTERNET-008: VGI distinguishability + E-CPU intention sufficiency.

An advisory *receiver-installed* attention policy over already-eligible
first probes of INTERNET-007. Real VGI `score_partial_probe` provides
counterfactual, three-valued predictive-distinction counts; E-CPU's native
`plan_sufficiency` and `FiniteGround` identify intention-relevant features.

Neither a finite hypothetical model nor a VGI score is a real Internet
observation, source authentication, authority grant or edge in the native
EvidencePathCatalogue. Only INTERNET-006/007 dispatch, independent case
verification and EvidencePathResolver may advance the actual route.

The optional VGI package is an analysis dependency, not an E-CPU runtime
requirement for users of the existing frontier policy.
"""
from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from types import MappingProxyType
from typing import Any, Mapping

from .headless import HeadlessOS
from .internet_ground_routing import InternetIntention
from .internet_partial_frontier import PartialFrontierQualifier
from .internet_prospective_qualification import ProspectiveRefused
from .intention_sufficiency import (
    FiniteGround, MeasurementCapability, plan_sufficiency,
)
from .semantic_translation import canonical_value_digest

SCHEMA = "mailcpu.internet-distinguishability-attention.v1"
MAX_MODEL_STATES = 48
MAX_PROBES = 32
MAX_HORIZON = 5


def _vgi():
    """Load actual VGI implementation only for the optional attention policy."""
    try:
        from vgi.relational import ObserverContext
        from vgi.transitions import GroundTransitionSystem
        from vgi.partial_attention import TransitionProbe, score_partial_probe
    except ImportError as exc:
        raise ProspectiveRefused(
            "VGI distinguishability requires the installed pinned vgi package"
        ) from exc
    return ObserverContext, GroundTransitionSystem, TransitionProbe, score_partial_probe


@dataclass(frozen=True)
class DistinguishabilityGround:
    """Explicitly hypothetical VGI dynamics and E-CPU target-distinction model.

    The receiver supplies both models, the observation-to-feature binding and
    the exact permitted measurement catalogue; no fetched website can install
    a model, new capability, probe code, or executable ranking callback.
    """

    predictive_ground: Any
    observer: Any
    probes_by_offer: Mapping[str, Any]
    finite_ground: FiniteGround
    public_value: Any
    feature_by_offer: Mapping[str, str]
    measurement_offers: tuple[MeasurementCapability, ...]
    horizon: int

    def __post_init__(self) -> None:
        Observer, System, Probe, score = _vgi()
        if not isinstance(self.predictive_ground, System) or not isinstance(self.observer, Observer):
            raise ProspectiveRefused("attention must use actual VGI Ground and ObserverContext")
        if not isinstance(self.finite_ground, FiniteGround):
            raise ProspectiveRefused("attention requires native E-CPU finite intention Ground")
        if (type(self.horizon) is not int or not 1 <= self.horizon <= MAX_HORIZON
                or not 2 <= len(self.predictive_ground.states) <= MAX_MODEL_STATES
                or len(self.predictive_ground.actions) > 16):
            raise ProspectiveRefused("VGI model or horizon exceeds bounded attention profile")
        self.observer.validate(self.predictive_ground)
        if (not isinstance(self.probes_by_offer, Mapping)
                or not isinstance(self.feature_by_offer, Mapping)
                or not isinstance(self.measurement_offers, tuple)
                or not 1 <= len(self.probes_by_offer) <= MAX_PROBES
                or set(self.probes_by_offer) != set(self.feature_by_offer)):
            raise ProspectiveRefused("attention offer/probe/feature binding is incomplete")
        if any(type(k) is not str or len(k) != 64 or
               any(c not in "0123456789abcdef" for c in k)
               for k in self.probes_by_offer):
            raise ProspectiveRefused("attention requires exact offer SHA-256 identities")
        if any(not isinstance(p, Probe) for p in self.probes_by_offer.values()):
            raise ProspectiveRefused("attention inputs require actual VGI TransitionProbe values")
        for probe in self.probes_by_offer.values():
            # Actual VGI implementation refuses invalid sources, actions and
            # scenarios; a known cell is not an unobserved probe.
            score(self.predictive_ground, self.observer, probe, self.horizon)
        names = {m.feature_id for m in self.measurement_offers}
        if (len(names) != len(self.measurement_offers)
                or any(not isinstance(x, MeasurementCapability) for x in self.measurement_offers)
                or not set(self.feature_by_offer.values()).issubset(names)):
            raise ProspectiveRefused("attention feature is not in the receiver's measurement catalogue")
        # Freeze the maps so the policy is stable across a subsequent choose().
        object.__setattr__(self, "probes_by_offer", MappingProxyType(dict(self.probes_by_offer)))
        object.__setattr__(self, "feature_by_offer", MappingProxyType(dict(self.feature_by_offer)))
        # E-CPU's own exact plan rejects invalid public fibers and bad offers.
        plan_sufficiency(self.finite_ground, self.public_value,
                         self.measurement_offers, "0" * 64)

    @property
    def digest(self) -> str:
        """Identity of this model snapshot, not evidence that it is true."""
        return canonical_value_digest({
            "schema": SCHEMA, "vgi_ground": self.predictive_ground.fingerprint,
            "vgi_observer": {"actions": list(self.observer.actions),
                             "channels": list(self.observer.channels)},
            "horizon": self.horizon, "finite_ground": self.finite_ground.digest,
            "public": self.public_value,
            "features": dict(sorted(self.feature_by_offer.items())),
            "measurements": [c.to_dict() for c in self.measurement_offers],
            "scenario_probes": [
                {"offer_digest": key, "state": item.state, "action": item.action,
                 "cost": str(item.cost), "scenarios": [
                     {"target": s.outcome.target, "output": list(s.outcome.output),
                      "weight": None if s.weight is None else str(s.weight)}
                     for s in item.scenarios]}
                for key, item in sorted(self.probes_by_offer.items())
            ],
            "grade": "receiver-supplied-hypothetical-model",
        })

    def _target_pair_separations(self, feature: str) -> int:
        """Exact target-conflicting pairs split by one feature, model-relative."""
        from .intention_sufficiency import _bytes
        public = _bytes(self.public_value)
        rows = tuple(row for row in self.finite_ground.states if row.public_json == public)
        return sum(
            left.target_json != right.target_json and
            left.features[feature] != right.features[feature]
            for left, right in combinations(rows, 2)
        )

    def rank(self, *, intent: InternetIntention, authority_digest: str,
             candidates: tuple[str, ...], coverage: Mapping[str, int],
             route_costs: Mapping[str, tuple[int, ...]]) -> tuple[str, dict]:
        """Rank only native-reachable candidates, without inventing probabilities.

        Primary: whether a feature lies in E-CPU's exact minimal sufficient
        set for the supplied finite model. Secondary: target-distinguishing
        pairs in the observed public fiber. Tertiary: VGI's robust minimum and
        maximum pair-resolution *scenario bounds*. Only then use route
        coverage and typed estimated costs. All scores are advisory.
        """
        _, _, _, score_probe = _vgi()
        if (not isinstance(intent, InternetIntention) or
                intent.ground_digest != self.finite_ground.ground_digest or
                intent.context_digest != self.finite_ground.context_digest):
            raise ProspectiveRefused("attention model differs from exact requested Ground or context")
        if any(x not in self.probes_by_offer for x in candidates):
            raise ProspectiveRefused("eligible native frontier lacks a receiver-pinned VGI scenario")
        if (not candidates or len(candidates) > MAX_PROBES or
                set(candidates) != set(coverage) or set(candidates) != set(route_costs)):
            raise ProspectiveRefused("attention candidate/route scope is incomplete")
        plan = plan_sufficiency(self.finite_ground, self.public_value,
                                self.measurement_offers, authority_digest)
        required = set(plan["selected_features"]) if plan["status"] == "MEASURE" else set()
        scores = []
        for oid in sorted(candidates):
            feature = self.feature_by_offer[oid]
            vgi_score = score_probe(
                self.predictive_ground, self.observer,
                self.probes_by_offer[oid], self.horizon,
            )
            target_pairs = self._target_pair_separations(feature)
            vector = route_costs[oid]
            if not (type(vector) is tuple and len(vector) == len(intent.metric_order)
                    and all(type(v) is int and v >= 0 for v in vector)):
                raise ProspectiveRefused("attention was supplied an untyped or negative route-cost vector")
            if type(coverage[oid]) is not int or coverage[oid] < 1:
                raise ProspectiveRefused("attention was supplied a false coverage count")
            priority = (
                -(feature in required), -target_pairs,
                -vgi_score.minimum_resolved_pairs,
                -vgi_score.maximum_resolved_pairs,
                -coverage[oid], vector, oid,
            )
            scores.append((priority, oid, {
                "offer_digest": oid, "feature": feature,
                "in_minimal_sufficient_set": feature in required,
                "target_conflicting_pairs_separated": target_pairs,
                "vgi_min_resolved_pairs": vgi_score.minimum_resolved_pairs,
                "vgi_max_resolved_pairs": vgi_score.maximum_resolved_pairs,
                "vgi_expected_gain_per_cost": (
                    None if vgi_score.expected_gain_per_cost is None
                    else str(vgi_score.expected_gain_per_cost)),
                "vgi_expectation_used_for_ranking": False,
                "possible_route_coverage": coverage[oid],
                "estimated_route_costs": list(vector),
            }))
        scores.sort(key=lambda x: x[0])
        chosen = scores[0][1]
        return chosen, {
            "reason": "vgi_counterfactual_attention_model_only",
            "schema": SCHEMA + ".choice",
            "model_digest": self.digest,
            "finite_model_digest": self.finite_ground.digest,
            "vgi_system_fingerprint": self.predictive_ground.fingerprint,
            "intention_context_digest": intent.context_digest,
            "headless_authority_digest": authority_digest,
            "sufficiency_plan_digest": plan["plan_digest"],
            "sufficiency_status": plan["status"],
            "sufficiency_required_features": list(sorted(required)),
            "ranked_candidates": [entry for _, _, entry in scores],
            "selected_offer_digest": chosen,
            "not": "hypothetical_attention_not_service_evidence_or_authority",
        }


@dataclass
class DistinguishabilityFrontierQualifier(PartialFrontierQualifier):
    """Re-rank already-qualified first frontiers with actual VGI and E-CPU math."""

    attention: DistinguishabilityGround | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        if not isinstance(self.attention, DistinguishabilityGround):
            raise ProspectiveRefused("explicit receiver-supplied VGI attention Ground required")
        if not set(self.attention.probes_by_offer).issubset({item.digest for item in self.offers}):
            raise ProspectiveRefused("attention offers differ from receiver-curated probes")

    def _attention_order(self, intent: InternetIntention, os: HeadlessOS, pid: int,
                         candidates: tuple[str, ...], coverage: Mapping[str, int],
                         route_costs: Mapping[str, tuple[int, ...]]) -> tuple[str, dict]:
        # The native EvidencePathResolver already returned this authority
        # digest; receive it through the actual live process context rather
        # than trusting data from a proposed website.
        from .evidence_path_resolver import _local_capability_snapshot
        _, authority_digest = _local_capability_snapshot(os, pid)
        return self.attention.rank(
            intent=intent, authority_digest=authority_digest,
            candidates=candidates, coverage=coverage, route_costs=route_costs,
        )
