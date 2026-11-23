"""ONP-001: observation itself constructs and realizes an intention-relative processor.

The observer supplies an intention, a hypothesis family, approved measurement
capabilities and a palette of executable primitives; it does *not* supply the
unknown source coefficients or a chosen processor program.

Existing E-CPU IOS-001 identifies the cheapest sufficient observations;
IPS-003 derives the least-cost primitive word; native NavigableComputationDAG
and SAB-008 execute and independently verify that generated computation.
All measurement authority remains with receiver-provisioned signing keys.
A measured finite family is not a proof about arbitrary unobserved behavior.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import json
import re
import secrets
import time
from typing import Any, Callable, Mapping, Sequence

from .generative_ground_construction import (
    AffineBehaviorIntention, AffinePrimitive, GroundConstructionError,
    GroundConstructionPlan, GroundConstructionReceipt, execute_ground_construction,
    synthesize_ground, verify_ground_construction, verify_ground_plan,
)
from .ground_native_realization import (
    RealizationPolicy, TwoPortArithmeticGate,
)
from .intention_sufficiency import (
    FiniteGround, FiniteState, MeasurementCapability, SufficiencyRefused,
    plan_sufficiency, resolve_sufficiency, verify_sufficiency_plan,
    verify_sufficiency_resolution,
)
from .inverse_architecture_synthesis import ProposedRelation
from .semantic_translation import canonical_value_digest
from .substrate_bootstrap import name, sha

_SCHEMA = "mailcpu.observation-formed-processor.v1"
_HEX32 = re.compile(r"[0-9a-f]{32}\Z")
_MAX_PROBES = 10
_MAX_MODULUS = 16  # IOS-001 supports at most 256 concrete candidate states.


class ObservationFormationRefused(ValueError):
    """An observation, inferred law, authorization or generated processor is invalid."""


def _wire(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def _key(secret: bytes) -> bytes:
    if type(secret) is not bytes or not 32 <= len(secret) <= 128:
        raise ObservationFormationRefused("a receiver-provisioned witness key is required")
    return secret


def _mac(value: Mapping[str, Any], secret: bytes) -> str:
    return hmac.new(_key(secret), (_SCHEMA + ".witness\0").encode() +
                    _wire(dict(value)), hashlib.sha256).hexdigest()


@dataclass(frozen=True)
class ObserverConstructionIntention:
    """A desired result and admitted relation, with no coefficients or program."""

    relation: ProposedRelation
    source_digest: str
    observer_id: str
    authority_digest: str
    modulus: int
    query_input: int

    def __post_init__(self) -> None:
        if not isinstance(self.relation, ProposedRelation):
            raise ObservationFormationRefused("a typed IPS-002 source/target relation is required")
        sha(self.source_digest, "source observation")
        sha(self.authority_digest, "measurement authority")
        name(self.observer_id, "observer")
        if (type(self.modulus) is not int
                or not 3 <= self.modulus <= _MAX_MODULUS
                or type(self.query_input) is not int
                or not 0 <= self.query_input < self.modulus):
            raise ObservationFormationRefused("invalid finite observation intention")

    @property
    def digest(self) -> str:
        return canonical_value_digest(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": _SCHEMA + ".intention", "relation": self.relation.to_dict(),
            "source_digest": self.source_digest, "observer_id": self.observer_id,
            "authority_digest": self.authority_digest,
            "family": "affine_mod", "modulus": self.modulus,
            "query_input": self.query_input,
        }


@dataclass(frozen=True)
class ProbeOffer:
    """Receiver-approved *capability offer*, not permission or executable code."""

    source_digest: str
    provider_id: str
    point: int
    cost_units: int

    def __post_init__(self) -> None:
        sha(self.source_digest, "source probe")
        name(self.provider_id, "probe provider")
        if (type(self.point) is not int or not 0 <= self.point < _MAX_MODULUS
                or type(self.cost_units) is not int or not 1 <= self.cost_units <= 10**6):
            raise ObservationFormationRefused("invalid bounded observation offer")

    @property
    def feature_id(self) -> str:
        return f"affine.point.{self.point:02d}"

    @property
    def contract_digest(self) -> str:
        return canonical_value_digest({
            "schema": _SCHEMA + ".probe-contract", "source": self.source_digest,
            "provider": self.provider_id, "point": self.point,
            "family": "affine_mod",
        })

    def capability(self) -> MeasurementCapability:
        return MeasurementCapability(
            self.feature_id, self.contract_digest,
            self.provider_id, self.cost_units,
        )


def sign_observation(intention: ObserverConstructionIntention,
                     offer: ProbeOffer, nonce: str, value: int,
                     *, issued_at: int, expires_at: int,
                     secret: bytes) -> dict[str, Any]:
    """Provider-side signed *observed* value; usable by an actual local sensor.

    Never manufactures an observation from a model description. The calling
    sensor must first perform its independent observation at the named point.
    """
    if (not isinstance(intention, ObserverConstructionIntention)
            or not isinstance(offer, ProbeOffer)
            or offer.source_digest != intention.source_digest
            or type(nonce) is not str or _HEX32.fullmatch(nonce) is None
            or type(value) is not int or not 0 <= value < intention.modulus
            or type(issued_at) is not int or type(expires_at) is not int
            or not 0 <= issued_at <= expires_at <= issued_at + 60):
        raise ObservationFormationRefused("invalid source observation signature request")
    record = {
        "schema": _SCHEMA + ".witness", "intention_digest": intention.digest,
        "source_digest": intention.source_digest,
        "provider_id": offer.provider_id, "point": offer.point,
        "feature_id": offer.feature_id,
        "contract_digest": offer.contract_digest,
        "nonce": nonce, "value": value, "issued_at": issued_at,
        "expires_at": expires_at,
    }
    return {**record, "signature": _mac(record, secret)}


def verify_observation(intention: ObserverConstructionIntention,
                       offer: ProbeOffer, witness: Mapping[str, Any],
                       trusted_keys: Mapping[str, bytes],
                       *, now: int, expected_nonce: str | None = None) -> int:
    """Validate complete signed provenance, freshness and exact source projection."""
    if (type(witness) is not dict
            or set(witness) != {
                "schema", "intention_digest", "source_digest", "provider_id",
                "point", "feature_id", "contract_digest", "nonce", "value",
                "issued_at", "expires_at", "signature",
            }
            or not isinstance(intention, ObserverConstructionIntention)
            or not isinstance(offer, ProbeOffer)
            or witness["schema"] != _SCHEMA + ".witness"
            or witness["intention_digest"] != intention.digest
            or witness["source_digest"] != intention.source_digest
            or witness["source_digest"] != offer.source_digest
            or witness["provider_id"] != offer.provider_id
            or witness["point"] != offer.point
            or witness["feature_id"] != offer.feature_id
            or witness["contract_digest"] != offer.contract_digest
            or type(witness["nonce"]) is not str
            or _HEX32.fullmatch(witness["nonce"]) is None
            or (expected_nonce is not None and witness["nonce"] != expected_nonce)
            or type(witness["value"]) is not int
            or not 0 <= witness["value"] < intention.modulus
            or type(now) is not int
            or type(witness["issued_at"]) is not int
            or type(witness["expires_at"]) is not int
            or not 0 <= witness["issued_at"] <= now <= witness["expires_at"]
            or witness["expires_at"] > witness["issued_at"] + 60
            or type(witness["signature"]) is not str
            or re.fullmatch(r"[0-9a-f]{64}\Z", witness["signature"]) is None):
        raise ObservationFormationRefused("unadmitted source observation witness")
    key = trusted_keys.get(offer.provider_id)
    unsigned = {k: v for k, v in witness.items() if k != "signature"}
    if key is None or not hmac.compare_digest(witness["signature"], _mac(unsigned, key)):
        raise ObservationFormationRefused("source observation authentication failed")
    return witness["value"]


def _catalogue(intention: ObserverConstructionIntention,
               offers: Sequence[ProbeOffer]) -> tuple[ProbeOffer, ...]:
    if (type(offers) not in (tuple, list) or not 3 <= len(offers) <= _MAX_PROBES
            or any(not isinstance(x, ProbeOffer) for x in offers)):
        raise ObservationFormationRefused("at least three bounded typed observation offers required")
    ordered = tuple(sorted(offers, key=lambda x: x.point))
    points = [offer.point for offer in ordered]
    if (len(set(points)) != len(points)
            or any(offer.source_digest != intention.source_digest
                   or offer.point >= intention.modulus for offer in ordered)
            or intention.query_input in points):
        raise ObservationFormationRefused("duplicate, wrong-source or direct-target probe")
    return ordered


def _hypotheses(intention: ObserverConstructionIntention,
                offers: tuple[ProbeOffer, ...]) -> FiniteGround:
    """Construct the finite space of possible laws without observing hidden a,c.

    The hypothesis family is a declared premise. Every affine law modulo m
    is included, and IOS-001 must prove the observed coordinates distinguish
    the intended coefficients among all m² possible laws.
    """
    modulus = intention.modulus
    states = tuple(
        FiniteState.create(
            f"a{a:02d}.c{c:02d}",
            {"family": "affine_mod", "modulus": modulus},
            {"multiplier": a, "offset": c},
            {offer.feature_id: (a * offer.point + c) % modulus
             for offer in offers},
        )
        for a in range(modulus) for c in range(modulus)
    )
    return FiniteGround(
        intention.relation.ground_digest,
        canonical_value_digest({
            "family": "affine_mod", "source": intention.source_digest,
            "modulus": modulus, "observer": intention.observer_id,
        }),
        intention.digest, intention.relation.context_digest, states,
    )


@dataclass(frozen=True)
class ObservedProcessorRealization:
    """Content-bound observation → sufficient Ground → native execution trace."""

    intention: ObserverConstructionIntention
    offers: tuple[ProbeOffer, ...]
    model_digest: str
    sufficiency_plan: dict[str, Any]
    measurement_witnesses: tuple[dict[str, Any], ...]
    sufficiency_resolution: dict[str, Any]
    validation_witness: dict[str, Any]
    synthesized_intention: AffineBehaviorIntention
    construction_plan: GroundConstructionPlan
    realization: GroundConstructionReceipt

    @property
    def digest(self) -> str:
        return canonical_value_digest(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": _SCHEMA + ".realization",
            "intention": self.intention.to_dict(),
            "offers": [
                {"source_digest": x.source_digest, "provider_id": x.provider_id,
                 "point": x.point, "cost_units": x.cost_units} for x in self.offers
            ],
            "model_digest": self.model_digest,
            "sufficiency_plan": self.sufficiency_plan,
            "measurement_witnesses": list(self.measurement_witnesses),
            "sufficiency_resolution": self.sufficiency_resolution,
            "validation_witness": self.validation_witness,
            "synthesized_intention": self.synthesized_intention.to_dict(),
            "construction_plan": self.construction_plan.to_dict(),
            "realization": self.realization.to_dict(),
        }


def _selected_offers(offers: tuple[ProbeOffer, ...],
                     plan: Mapping[str, Any]) -> tuple[ProbeOffer, ...]:
    by_feature = {offer.feature_id: offer for offer in offers}
    return tuple(by_feature[feature] for feature in plan["selected_features"])


def realize_observed_processor(
    intention: ObserverConstructionIntention,
    offers: Sequence[ProbeOffer],
    sensors: Mapping[str, Callable[[ObserverConstructionIntention, ProbeOffer, str, int], dict[str, Any]]],
    trusted_keys: Mapping[str, bytes],
    primitives: Sequence[AffinePrimitive],
    policy: RealizationPolicy,
    *,
    locus: str = "onp001-local",
    port_id: str = "observed-processor",
    clock: Callable[[], int] = lambda: int(time.time()),
    nonce_factory: Callable[[], str] = lambda: secrets.token_hex(16),
    max_states: int = 4096,
    max_depth: int = 12,
) -> ObservedProcessorRealization:
    """Observe the minimum sufficient data and *create* a new executing processor.

    All parameters describe the intended result, authorized observation and
    offered computational capacities. No coefficients or program are accepted.
    A held-out sensor challenge must agree before *any* port effect.
    """
    if not isinstance(intention, ObserverConstructionIntention):
        raise ObservationFormationRefused("typed intention required")
    ordered = _catalogue(intention, offers)
    if not isinstance(policy, RealizationPolicy):
        raise ObservationFormationRefused("receiver realization policy required")
    policy.permits(locus, "port", 1)
    if not isinstance(sensors, Mapping) or not isinstance(trusted_keys, Mapping):
        raise ObservationFormationRefused("locally admitted sensor bindings required")
    model = _hypotheses(intention, ordered)
    capabilities = tuple(x.capability() for x in ordered)
    public = {"family": "affine_mod", "modulus": intention.modulus}
    plan = plan_sufficiency(model, public, capabilities, intention.authority_digest)
    verify_sufficiency_plan(plan, model, public, capabilities, intention.authority_digest)
    if plan["status"] != "MEASURE":
        raise ObservationFormationRefused("permitted observations do not identify a unique law")
    selected = _selected_offers(ordered, plan)
    validation = next(
        (x for x in sorted(ordered, key=lambda x: (x.cost_units, x.point))
         if x.feature_id not in plan["selected_features"]),
        None,
    )
    if validation is None:
        raise ObservationFormationRefused("an independent held-out probe is required")
    values: dict[str, int] = {}
    witnesses: list[dict[str, Any]] = []
    observed_nonces: set[str] = set()

    def sample(offer: ProbeOffer) -> dict[str, Any]:
        provider = sensors.get(offer.provider_id)
        if not callable(provider) or offer.provider_id not in trusted_keys:
            raise ObservationFormationRefused("probe not bound to a receiver-authorized provider")
        nonce = nonce_factory()
        if (type(nonce) is not str or _HEX32.fullmatch(nonce) is None
                or nonce in observed_nonces):
            raise ObservationFormationRefused("unadmitted or repeated observation nonce")
        observed_nonces.add(nonce)
        now = clock()
        witness = provider(intention, offer, nonce, now)
        verify_observation(intention, offer, witness, trusted_keys,
                           now=now, expected_nonce=nonce)
        return witness

    for offer in selected:
        witness = sample(offer)
        witnesses.append(witness)
        values[offer.feature_id] = witness["value"]
    receipt_digest = canonical_value_digest(witnesses)
    resolution = resolve_sufficiency(
        model, public, capabilities, intention.authority_digest,
        plan, values, receipt_digest,
    )
    verify_sufficiency_resolution(
        resolution, model, public, capabilities, intention.authority_digest,
        plan, values, receipt_digest,
    )
    coefficients = resolution["result"]
    a, c = coefficients["multiplier"], coefficients["offset"]
    challenge = sample(validation)
    family = AffineBehaviorIntention(
        intention.relation, intention.modulus, c, (a + c) % intention.modulus,
        intention.query_input, ((validation.point, challenge["value"]),),
    )
    plan_ground = synthesize_ground(
        family, primitives, max_states=max_states, max_depth=max_depth,
    )
    if plan_ground.status != "constructed_exact_affine_ground":
        raise ObservationFormationRefused(
            "observed law cannot be constructed: " + plan_ground.status
        )
    gate = TwoPortArithmeticGate(port_id, intention.modulus)
    realization = execute_ground_construction(
        plan_ground, family, primitives, gate, policy, locus=locus,
        max_states=max_states, max_depth=max_depth,
    )
    report = ObservedProcessorRealization(
        intention, ordered, model.digest, plan, tuple(witnesses),
        resolution, challenge, family, plan_ground, realization,
    )
    verify_observed_processor(
        report, intention, ordered, primitives, policy, trusted_keys,
        now=clock(), locus=locus, max_states=max_states, max_depth=max_depth,
    )
    return report


def verify_observed_processor(
    report: ObservedProcessorRealization,
    intention: ObserverConstructionIntention,
    offers: Sequence[ProbeOffer],
    primitives: Sequence[AffinePrimitive],
    policy: RealizationPolicy,
    trusted_keys: Mapping[str, bytes],
    *,
    now: int,
    locus: str = "onp001-local",
    max_states: int = 4096,
    max_depth: int = 12,
) -> bool:
    """Reconstruct sufficiency, signed measurements, intended law and native DAG.

    Verification needs no sensor invocation and never repeats source execution.
    """
    try:
        ordered = _catalogue(intention, offers)
        if (not isinstance(report, ObservedProcessorRealization)
                or report.intention != intention or report.offers != ordered
                or report.realization.locus != locus):
            raise ObservationFormationRefused("wrong observation/realization lineage")
        model = _hypotheses(intention, ordered)
        if model.digest != report.model_digest:
            raise ObservationFormationRefused("altered candidate law family")
        capabilities = tuple(x.capability() for x in ordered)
        public = {"family": "affine_mod", "modulus": intention.modulus}
        verify_sufficiency_plan(report.sufficiency_plan, model, public,
                                capabilities, intention.authority_digest)
        selected = _selected_offers(ordered, report.sufficiency_plan)
        if (report.sufficiency_plan["status"] != "MEASURE"
                or len(report.measurement_witnesses) != len(selected)):
            raise ObservationFormationRefused("incomplete sufficient source observations")
        values = {}
        seen_nonces: set[str] = set()
        for offer, witness in zip(selected, report.measurement_witnesses):
            values[offer.feature_id] = verify_observation(
                intention, offer, witness, trusted_keys, now=now,
            )
            if witness["nonce"] in seen_nonces:
                raise ObservationFormationRefused("repeated source observation challenge")
            seen_nonces.add(witness["nonce"])
        evidence = canonical_value_digest(report.measurement_witnesses)
        verify_sufficiency_resolution(
            report.sufficiency_resolution, model, public, capabilities,
            intention.authority_digest, report.sufficiency_plan, values, evidence,
        )
        allowed_validation = next(
            (x for x in sorted(ordered, key=lambda x: (x.cost_units, x.point))
             if x.feature_id not in report.sufficiency_plan["selected_features"]),
            None,
        )
        if allowed_validation is None:
            raise ObservationFormationRefused("missing held-out observation")
        challenge = verify_observation(
            intention, allowed_validation, report.validation_witness,
            trusted_keys, now=now,
        )
        if report.validation_witness["nonce"] in seen_nonces:
            raise ObservationFormationRefused("held-out observation reused a nonce")
        coefficients = report.sufficiency_resolution["result"]
        a, c = coefficients["multiplier"], coefficients["offset"]
        expected_family = AffineBehaviorIntention(
            intention.relation, intention.modulus, c, (a + c) % intention.modulus,
            intention.query_input, ((allowed_validation.point, challenge),),
        )
        if expected_family != report.synthesized_intention:
            raise ObservationFormationRefused("observed processor has wrong inferred law")
        if not verify_ground_plan(
            report.construction_plan, expected_family, primitives,
            max_states=max_states, max_depth=max_depth,
        ) or report.construction_plan.status != "constructed_exact_affine_ground":
            raise ObservationFormationRefused("synthesized program differs from observed law")
        if not verify_ground_construction(
            report.realization, report.construction_plan, expected_family,
            primitives, policy, max_states=max_states, max_depth=max_depth,
        ):
            raise ObservationFormationRefused("native processor realization differs from Ground")
        if (report.realization.output !=
                (a * intention.query_input + c) % intention.modulus):
            raise ObservationFormationRefused("observed result differs from exact inferred law")
        return True
    except (GroundConstructionError, SufficiencyRefused, TypeError, KeyError,
            IndexError, ValueError, AttributeError) as exc:
        raise ObservationFormationRefused("observation-to-processor verification failed") from exc
