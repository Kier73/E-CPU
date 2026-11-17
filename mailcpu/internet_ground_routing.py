"""INTERNET-005: evidence-gated Internet observation routing using native E-CPU.

This module does NOT discover arbitrary services or create a shadow router. It
compiles already-observed, receiver-verified *exact cases* into the existing
EvidencePathCatalogue, lets the existing EvidencePathResolver select a route
under current HeadlessOS capabilities, and then validates the selected case
again before publishing a proposal. The remote service's protocol operation is
not performed by this route selection, and no returned digest is authority.

Generic Git, HTTP, DNS and RFC claims require distinct receiver-installed
verifiers. A finite-witness SAB-002 affine candidate may be admitted through
GroundAdmission, without turning its observations into a universal theorem.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Callable, Mapping
from types import MappingProxyType

from .active_ground_discovery import GroundAdmission, GroundCandidate, _affine_pow
from .evidence_path_resolver import (
    EvidencePathCatalogue, EvidencePathEdge, EvidencePathRequest,
    EvidencePathResolver, EvidencePathResult, EvidencePathStatus, RouteMetric,
    RouteMetricKey, EvidenceStrength,
)
from .headless import HeadlessOS
from .semantic_translation import (
    CapabilityRequirement, EffectClass, ObservationContract, ReplayClass,
    RepresentationRef, ResourceBound, TranslationContract,
    canonical_value_digest, compare_projected_observations,
)

_SCHEMA = "mailcpu.internet-ground-routing.v1"
_KIND_OPS = {
    "git": frozenset({"observe.graph", "observe.object"}),
    "http": frozenset({"observe.content", "observe.conditional", "observe.range"}),
    "dns": frozenset({"observe.rrset"}),
    "rfc": frozenset({"navigate.references"}),
    "law": frozenset({"navigate.affine"}),
}
_NAME = re.compile(r"[a-z][a-z0-9_.-]{0,47}\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_MAX_OFFERS = 48


class InternetGroundRefused(ValueError):
    """Candidate evidence, receiver policy or the selected path was refused."""


def _hash(value: object) -> str:
    return canonical_value_digest(value)


def _check_digest(value: object, label: str) -> None:
    if type(value) is not str or _DIGEST.fullmatch(value) is None:
        raise InternetGroundRefused(f"{label} must be a lowercase SHA-256")


def _json(value: object) -> object:
    """Detach a bounded finite JSON value, preventing later mutation of claims."""
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"),
                         allow_nan=False, ensure_ascii=False).encode("utf-8")
        if len(raw) > 8192:
            raise InternetGroundRefused("projected observation exceeds 8 KiB")
        return json.loads(raw)
    except (TypeError, ValueError) as exc:
        if isinstance(exc, InternetGroundRefused):
            raise
        raise InternetGroundRefused("observation is not canonical finite JSON") from exc


def _freeze(value: object) -> object:
    if isinstance(value, dict):
        return MappingProxyType({k: _freeze(v) for k, v in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(v) for v in value)
    return value


def _thaw(value: object) -> object:
    if isinstance(value, Mapping):
        return {k: _thaw(v) for k, v in value.items()}
    if isinstance(value, tuple):
        return [_thaw(v) for v in value]
    return value


@dataclass(frozen=True)
class InternetObservationCase:
    """One provider-specific, source-bound observation; NOT an advertisement.

    `expected_projection` comes from independent receiver policy, not from the
    remote response. `observed_projection` is the provider's sampled output.
    Their equality is checked separately from the receiver-installed verifier,
    which is responsible for checking real protocol evidence and source pins.
    A finite case is never silently upgraded to a universally valid law.
    """

    provider_id: str
    kind: str
    operation: str
    source: RepresentationRef
    target: RepresentationRef
    ground_digest: str
    context_digest: str
    observed_at: int
    expires_at: int
    evidence_digest: str
    expected_projection: object
    observed_projection: object
    costs: tuple[RouteMetric, ...]
    scope: str = "exact-observed-case-no-general-operator-proof"

    def __post_init__(self) -> None:
        if type(self.provider_id) is not str or _NAME.fullmatch(self.provider_id) is None:
            raise InternetGroundRefused("unbounded or unsafe provider identity")
        if self.kind not in _KIND_OPS or self.operation not in _KIND_OPS[self.kind]:
            raise InternetGroundRefused("unsupported provider kind or observation operation")
        if not isinstance(self.source, RepresentationRef) or not isinstance(self.target, RepresentationRef):
            raise InternetGroundRefused("provider requires native representation references")
        if self.source == self.target:
            raise InternetGroundRefused("an observation route must advance to a different representation")
        for field in ("ground_digest", "context_digest", "evidence_digest"):
            _check_digest(getattr(self, field), field)
        if (type(self.observed_at) is not int or type(self.expires_at) is not int
                or self.observed_at < 0 or self.expires_at < self.observed_at):
            raise InternetGroundRefused("observer lease must use bounded monotonic logical coordinates")
        if self.scope != "exact-observed-case-no-general-operator-proof":
            raise InternetGroundRefused("provider cannot expand the empirical claim scope")
        expected, observed = _json(self.expected_projection), _json(self.observed_projection)
        object.__setattr__(self, "expected_projection", _freeze(expected))
        object.__setattr__(self, "observed_projection", _freeze(observed))
        costs = tuple(self.costs)
        if (not 1 <= len(costs) <= 6 or not all(isinstance(x, RouteMetric) for x in costs)
                or len({x.name for x in costs}) != len(costs)):
            raise InternetGroundRefused("provider cost vector must be typed, bounded and unique")
        object.__setattr__(self, "costs", tuple(sorted(costs, key=lambda x: x.name)))

    @property
    def case_digest(self) -> str:
        return _hash(self.to_dict())

    def to_dict(self) -> dict:
        return {"schema": _SCHEMA + ".case", "provider_id": self.provider_id,
                "kind": self.kind, "operation": self.operation,
                "source": self.source.to_dict(), "target": self.target.to_dict(),
                "ground_digest": self.ground_digest, "context_digest": self.context_digest,
                "observed_at": self.observed_at, "expires_at": self.expires_at,
                "evidence_digest": self.evidence_digest,
                "expected_projection": _thaw(self.expected_projection),
                "observed_projection": _thaw(self.observed_projection),
                "costs": [x.to_dict() for x in self.costs], "scope": self.scope}


@dataclass(frozen=True)
class InternetIntention:
    """Bounded desired observation and route policy; does not grant authority."""

    source: RepresentationRef
    target: RepresentationRef
    ground_digest: str
    context_digest: str
    now: int
    metric_order: tuple[RouteMetricKey, ...]
    resource_ceilings: tuple[RouteMetric, ...] = ()
    allowed_kinds: frozenset[str] = frozenset(_KIND_OPS)
    max_hops: int = 5
    max_expansions: int = 96
    minimum_evidence: EvidenceStrength = EvidenceStrength.PAIRED_CASE

    def __post_init__(self) -> None:
        if not isinstance(self.source, RepresentationRef) or not isinstance(self.target, RepresentationRef):
            raise InternetGroundRefused("intention requires exact native input and desired output")
        _check_digest(self.ground_digest, "intention Ground")
        _check_digest(self.context_digest, "intention context")
        if type(self.now) is not int or not 0 <= self.now <= 2**63 - 1:
            raise InternetGroundRefused("invalid observation coordinate")
        if (not isinstance(self.metric_order, tuple) or not 1 <= len(self.metric_order) <= 6
                or not all(isinstance(x, RouteMetricKey) for x in self.metric_order)
                or len({x.name for x in self.metric_order}) != len(self.metric_order)):
            raise InternetGroundRefused("invalid route objective dimensions")
        if not isinstance(self.allowed_kinds, frozenset) or not self.allowed_kinds.issubset(_KIND_OPS):
            raise InternetGroundRefused("unrecognized allowed provider kind")
        if type(self.max_hops) is not int or not 1 <= self.max_hops <= 12:
            raise InternetGroundRefused("route hop count must be bounded")
        if type(self.max_expansions) is not int or not 1 <= self.max_expansions <= 256:
            raise InternetGroundRefused("route expansion ceiling exceeded")
        if not isinstance(self.resource_ceilings, tuple) or any(not isinstance(x, RouteMetric) for x in self.resource_ceilings):
            raise InternetGroundRefused("resource ceilings must be typed")
        if not isinstance(self.minimum_evidence, EvidenceStrength):
            raise InternetGroundRefused("minimum evidence tier must be native")


# A trusted local verifier MUST independently check the exact source bytes,
# protocol metadata, receipt, and expected projection. It may use a pinned
# standard service adapter (e.g. INTERNET-002 Git or INTERNET-004 RFC).
ReceiverVerifier = Callable[[InternetObservationCase], bool]


class InternetGroundRouter:
    """Compile receiver-verified observed cases into the existing native resolver."""

    def __init__(self, verified_by_provider: Mapping[str, ReceiverVerifier]) -> None:
        if not isinstance(verified_by_provider, Mapping) or len(verified_by_provider) > _MAX_OFFERS:
            raise InternetGroundRefused("bounded receiver-local verifier map required")
        for provider, verifier in verified_by_provider.items():
            if type(provider) is not str or _NAME.fullmatch(provider) is None or not callable(verifier):
                raise InternetGroundRefused("invalid receiver-installed provider verifier")
        self._verifiers = dict(verified_by_provider)
        self._cases: dict[str, InternetObservationCase] = {}

    def add(self, case: InternetObservationCase) -> str:
        """Add candidate evidence only; no network calls, execution or admission."""
        if not isinstance(case, InternetObservationCase):
            raise InternetGroundRefused("only typed observed Internet cases may be offered")
        if case.provider_id not in self._verifiers:
            raise InternetGroundRefused("provider has no receiver-installed verifier")
        if len(self._cases) >= _MAX_OFFERS and case.case_digest not in self._cases:
            raise InternetGroundRefused("candidate catalogue exceeds fixed maximum")
        self._cases[case.case_digest] = case
        return case.case_digest

    @staticmethod
    def _edge(case: InternetObservationCase) -> EvidencePathEdge:
        """Encode a *verified exact case* as native paired-case translation evidence.

        The translation itself is the local semantic step from an externally
        pinned intention/representation to the observed output description;
        it is NOT a claim that an Internet carrier has arbitrary execution.
        """
        contract = TranslationContract(
            contract_id=f"internet.{case.kind}.{case.operation}.{case.provider_id}",
            revision=1,
            source=case.source,
            target=case.target,
            mapping=RepresentationRef.from_payload("internet.qualified-relation", 1, {
                "provider": case.provider_id, "kind": case.kind,
                "operation": case.operation, "ground": case.ground_digest,
                "evidence": case.evidence_digest, "scope": case.scope,
                "observed_at": case.observed_at, "expires_at": case.expires_at,
            }),
            observation=ObservationContract.from_definition(
                "internet.verified-requested-projection", 1,
                {"ground": case.ground_digest, "source": case.source.to_dict(),
                 "target": case.target.to_dict(), "mode": "exact-case"}),
            context_digest=case.context_digest,
            precondition_digests=(case.ground_digest,),
            resource_bounds=tuple(ResourceBound(x.name, x.amount, x.unit) for x in case.costs),
            authority_requirements=(CapabilityRequirement(
                f"/internet/{case.kind}/{case.provider_id}", ("observe",)),),
            effect_class=EffectClass.PURE,
            replay_class=ReplayClass.DETERMINISTIC,
        )
        comparison = compare_projected_observations(
            contract, case_payload={"case_digest": case.case_digest},
            source_observation=_thaw(case.expected_projection),
            target_observation=_thaw(case.observed_projection),
        )
        if not comparison.equivalent:
            raise InternetGroundRefused("actual provider observation contradicts receiver expectation")
        return EvidencePathEdge(contract=contract, comparison=comparison, costs=case.costs)

    def resolve(self, intention: InternetIntention, operating_system: HeadlessOS,
                pid: int) -> dict:
        """Choose a verified, leased route using native EvidencePathResolver.

        The resolver consults *live* HeadlessOS process capabilities. This
        method does not perform the service's operation, or authorize future
        network access. Returning FOUND is a non-authoritative plan.
        """
        if not isinstance(intention, InternetIntention):
            raise InternetGroundRefused("exact typed navigation intention required")
        catalogue = EvidencePathCatalogue(max_edges=_MAX_OFFERS)
        accepted: dict[str, InternetObservationCase] = {}
        refused: list[dict[str, str]] = []
        metric_names = {x.name: x.unit for x in intention.metric_order}
        for case_id, case in sorted(self._cases.items()):
            if (case.kind not in intention.allowed_kinds or
                    case.ground_digest != intention.ground_digest or
                    case.context_digest != intention.context_digest):
                continue
            if not case.observed_at <= intention.now <= case.expires_at:
                refused.append({"case_digest": case_id, "reason": "expired_or_future_observation"})
                continue
            if {c.name: c.unit for c in case.costs} != metric_names:
                refused.append({"case_digest": case_id, "reason": "incomparable_metric_units"})
                continue
            verifier = self._verifiers.get(case.provider_id)
            try:
                # A callback is receiver-owned, not received from a service.
                valid = verifier is not None and verifier(case) is True
            except Exception:
                valid = False
            if not valid:
                refused.append({"case_digest": case_id, "reason": "receiver_evidence_refused"})
                continue
            try:
                edge = self._edge(case)
            except InternetGroundRefused:
                refused.append({"case_digest": case_id, "reason": "projection_mismatch"})
                continue
            catalogue.register(edge)
            accepted[edge.edge_id] = case
        request = EvidencePathRequest(
            source=intention.source, target=intention.target,
            context_digest=intention.context_digest,
            metric_order=intention.metric_order,
            resource_ceilings=intention.resource_ceilings,
            satisfied_preconditions=(intention.ground_digest,),
            max_hops=intention.max_hops,
            max_expansions=intention.max_expansions,
            minimum_evidence=intention.minimum_evidence,
        )
        result = EvidencePathResolver().resolve(catalogue, request, operating_system, pid)
        selected = [accepted[edge_id] for edge_id in result.edge_ids]
        # Catch changed or revoked evidence between route selection and
        # publication, even if the caller's verifier has side effects.
        for case in selected:
            if self._verifiers[case.provider_id](case) is not True:
                raise InternetGroundRefused("receiver rescinded selected path evidence")
        return {"schema": _SCHEMA + ".resolution", "status": result.status.value,
                "authoritative": False, "intention": {
                    "source": intention.source.to_dict(), "target": intention.target.to_dict(),
                    "ground_digest": intention.ground_digest, "context_digest": intention.context_digest,
                    "observed_at": intention.now},
                "selected": [{"provider": x.provider_id, "kind": x.kind,
                              "operation": x.operation, "case_digest": x.case_digest,
                              "evidence_digest": x.evidence_digest}
                             for x in selected],
                "route": result.to_dict(), "refusals": refused,
                "verification_scope": "receiver-checked-exact-cases-not-live-operator-attestation"}


def admitted_affine_observation(
    candidate: GroundCandidate, admission: GroundAdmission, *,
    source: RepresentationRef, target: RepresentationRef, context_digest: str,
    coordinate: int, observed_at: int, costs: tuple[RouteMetric, ...],
) -> InternetObservationCase:
    """Reuse SAB-002 finite-witness Ground discovery and exact receiver admission.

    The output is a receiver-local law navigation at a single coordinate.
    This is NOT evidence that the remote observed host physically executed
    all intermediate states, nor a universal certification of the law.
    """
    if not isinstance(candidate, GroundCandidate) or not isinstance(admission, GroundAdmission):
        raise InternetGroundRefused("native SAB-002 discovery and GroundAdmission required")
    if type(coordinate) is not int or coordinate < 0:
        raise InternetGroundRefused("invalid affine intention coordinate")
    binding = admission.bind(candidate, coordinate=observed_at)
    request = {"ground": candidate.ground_digest, "coordinate": coordinate}
    result = binding.handler(request)
    if binding.oracle is None or binding.oracle(request, result) is not True:
        raise InternetGroundRefused("native independent affine oracle rejected navigation")
    return InternetObservationCase(
        provider_id=candidate.host_id, kind="law", operation="navigate.affine",
        source=source, target=target, ground_digest=candidate.ground_digest,
        context_digest=context_digest, observed_at=candidate.observed_at,
        expires_at=candidate.expires_at, evidence_digest=candidate.transcript_digest,
        expected_projection={"coordinate": coordinate, "value": _affine_pow(
            candidate.a, candidate.c, candidate.modulus, candidate.x0, coordinate)},
        observed_projection=result, costs=costs,
    )


def admitted_rfc_observation(
    capsule: dict, policy: object, *, expected_capsule_digest: str,
    expected_path: tuple[str, ...], provider_id: str,
    source: RepresentationRef, target: RepresentationRef,
    context_digest: str, observed_at: int, expires_at: int,
    costs: tuple[RouteMetric, ...],
) -> tuple[InternetObservationCase, ReceiverVerifier]:
    """Connect INTERNET-004's actual captured HTTPS navigation to this router.

    A receiver supplies both the intended path and capsule pin. An RFC page
    cannot add arbitrary network destinations, instructions or authorities.
    The verifier closes over the independently retained raw HTML capsule and
    reruns INTERNET-004's full offline link/byte reconstruction at each plan.
    """
    from .public_internet_navigation import Policy, verify_capsule, rfc_url

    if not isinstance(policy, Policy):
        raise InternetGroundRefused("an INTERNET-004 bounded RFC policy is required")
    _check_digest(expected_capsule_digest, "RFC capsule independent pin")
    if type(expected_path) is not tuple or not expected_path:
        raise InternetGroundRefused("the receiver must declare its desired RFC path")
    if (expected_path[0] not in {rfc_url(n) for n in policy.seeds}
            or expected_path[-1] != rfc_url(policy.target)):
        raise InternetGroundRefused("declared path does not start and end at the intention")
    snapshot = _json(capsule)
    if not isinstance(snapshot, dict):
        raise InternetGroundRefused("captured RFC evidence must be a JSON object")

    def read_proof() -> dict:
        return verify_capsule(snapshot, policy, expected_capsule_digest=expected_capsule_digest)

    proof = read_proof()
    actual = {"status": proof["status"], "path": proof["path"]}
    expected = {"status": "reached_observed_target", "path": list(expected_path)}
    if actual != expected:
        raise InternetGroundRefused("observed RFC path does not satisfy receiver intention")
    case = InternetObservationCase(
        provider_id=provider_id, kind="rfc", operation="navigate.references",
        source=source, target=target, ground_digest=_hash(policy.as_dict()),
        context_digest=context_digest,
        observed_at=observed_at, expires_at=expires_at,
        evidence_digest=expected_capsule_digest,
        expected_projection=expected, observed_projection=actual, costs=costs,
    )
    pinned_case = case.case_digest

    def receiver_verify(candidate: InternetObservationCase) -> bool:
        if candidate.case_digest != pinned_case or candidate.evidence_digest != expected_capsule_digest:
            return False
        try:
            now = read_proof()
        except Exception:
            return False
        return {"status": now["status"], "path": now["path"]} == expected

    return case, receiver_verify
