"""INTERNET-006: intention-directed, prospective Internet observation qualification.

Plans one *unobserved* receiver-approved probe only when existing, verified
EvidencePathResolver segments make its missing relation potentially decisive.
A hypothetical edge is NEVER registered. The local probe is an installed,
bounded handler, not executable content or an endpoint advertised by a website.
After a read, INTERNET-005's independent verifier gates the case and native
EvidencePathResolver checks the newly complete route under live capabilities.

This chooses where to observe, not which arbitrary remote code to execute.
A finite observation does not establish a universally valid Ground law.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Callable, Mapping

from .headless import HeadlessOS
from .kernel import ProcessStatus, Capability
from .internet_ground_routing import (
    InternetGroundRouter, InternetIntention, InternetObservationCase,
    InternetGroundRefused,
)
from .evidence_path_resolver import RouteMetric, EvidencePathStatus
from .semantic_translation import RepresentationRef, canonical_value_digest

_SCHEMA = "mailcpu.internet-prospective-qualification.v1"
_MAX_OFFERS = 32
_MAX_ATTEMPTS = 8
_MAX_RESPONSE_BYTES = 1_048_576


class ProspectiveRefused(InternetGroundRefused):
    """Unqualified observation, incorrect source, or invalid local probe policy."""


@dataclass(frozen=True)
class ProbeOffer:
    """Receiver-curated *possible* relation, explicitly NOT an observed edge.

    The endpoints and Ground are receiver hypotheses. Costs are estimates,
    never measured runtime or evidence. A probe implementation is installed
    out of band in the local handler registry, never serialized with an offer.
    """

    provider_id: str
    kind: str
    operation: str
    source: RepresentationRef
    target: RepresentationRef
    ground_digest: str
    context_digest: str
    available_at: int
    expires_at: int
    estimated_costs: tuple[RouteMetric, ...]
    max_response_bytes: int = 65536
    max_requests: int = 4

    def __post_init__(self) -> None:
        # The v5 case constructor enforces the same closed provider/operation
        # vocabulary. Unlike a case, we do NOT manufacture a successful
        # ObservationComparison to qualify a proposal.
        if not isinstance(self.source, RepresentationRef) or not isinstance(self.target, RepresentationRef):
            raise ProspectiveRefused("probe requires exact representation identities")
        if self.source == self.target:
            raise ProspectiveRefused("prospective relation must advance the state")
        from .internet_ground_routing import _KIND_OPS, _NAME, _DIGEST
        if (type(self.provider_id) is not str or _NAME.fullmatch(self.provider_id) is None
                or self.kind not in _KIND_OPS or self.operation not in _KIND_OPS[self.kind]):
            raise ProspectiveRefused("unknown provider operation or identity")
        if any(type(v) is not str or _DIGEST.fullmatch(v) is None
               for v in (self.ground_digest, self.context_digest)):
            raise ProspectiveRefused("unbound Ground or context")
        if (type(self.available_at) is not int or type(self.expires_at) is not int
                or not 0 <= self.available_at <= self.expires_at <= 2**63 - 1):
            raise ProspectiveRefused("invalid receiver-declared offer lease")
        if type(self.max_response_bytes) is not int or not 1 <= self.max_response_bytes <= _MAX_RESPONSE_BYTES:
            raise ProspectiveRefused("invalid maximum observation payload")
        if type(self.max_requests) is not int or not 1 <= self.max_requests <= 16:
            raise ProspectiveRefused("invalid maximum request count")
        if (type(self.estimated_costs) is not tuple or not 1 <= len(self.estimated_costs) <= 6
                or any(not isinstance(c, RouteMetric) for c in self.estimated_costs)
                or len({c.name for c in self.estimated_costs}) != len(self.estimated_costs)):
            raise ProspectiveRefused("invalid estimated typed cost vector")
        object.__setattr__(self, "estimated_costs", tuple(sorted(self.estimated_costs, key=lambda x: x.name)))

    @property
    def digest(self) -> str:
        return canonical_value_digest(self.to_dict())

    def to_dict(self) -> dict:
        return {"schema": _SCHEMA + ".offer", "provider_id": self.provider_id,
                "kind": self.kind, "operation": self.operation,
                "source": self.source.to_dict(), "target": self.target.to_dict(),
                "ground_digest": self.ground_digest, "context_digest": self.context_digest,
                "available_at": self.available_at, "expires_at": self.expires_at,
                "estimated_costs": [m.to_dict() for m in self.estimated_costs],
                "max_response_bytes": self.max_response_bytes, "max_requests": self.max_requests,
                "evidence_grade": "hypothetical-unobserved"}


@dataclass(frozen=True)
class ProbePolicy:
    """Local receiver policy; no authority is derived from offers or URL data."""

    allowed_providers: frozenset[str]
    max_attempts: int = 3
    total_response_budget: int = 131072

    def __post_init__(self) -> None:
        from .internet_ground_routing import _NAME
        if (type(self.allowed_providers) is not frozenset or len(self.allowed_providers) > _MAX_OFFERS
                or any(type(p) is not str or _NAME.fullmatch(p) is None for p in self.allowed_providers)):
            raise ProspectiveRefused("receiver provider allowlist invalid")
        if type(self.max_attempts) is not int or not 1 <= self.max_attempts <= _MAX_ATTEMPTS:
            raise ProspectiveRefused("probe attempt budget must be 1..8")
        if (type(self.total_response_budget) is not int
                or not 1 <= self.total_response_budget <= _MAX_RESPONSE_BYTES):
            raise ProspectiveRefused("invalid total observation byte budget")

    @property
    def digest(self) -> str:
        return canonical_value_digest({"providers": sorted(self.allowed_providers),
                                       "attempts": self.max_attempts,
                                       "response_bytes": self.total_response_budget})


@dataclass(frozen=True)
class ProbeCapture:
    """A receiver-installed handler's raw read accounting and typed candidate.

    `raw_response_bytes` is the count of actual response body bytes before
    projection; the handler is responsible for checking it against the passed
    bound *during* collection. A digest or count is not remote attestation.
    """

    case: InternetObservationCase
    raw_response_bytes: int
    request_count: int
    elapsed_ns: int
    raw_evidence_digest: str

    def __post_init__(self) -> None:
        from .internet_ground_routing import _DIGEST
        if (not isinstance(self.case, InternetObservationCase)
                or type(self.raw_response_bytes) is not int or self.raw_response_bytes < 0
                or type(self.request_count) is not int or not 1 <= self.request_count <= 16
                or type(self.elapsed_ns) is not int or self.elapsed_ns < 0
                or type(self.raw_evidence_digest) is not str or _DIGEST.fullmatch(self.raw_evidence_digest) is None):
            raise ProspectiveRefused("invalid receiver-observed capture accounting")


# Executable code exists only in a trusted LOCAL registry. It must enforce its
# own URL/redirect/timeout/request limits, independently of the postflight
# response-budget check. It receives a finite byte ceiling, not unrestricted
# source/scheme selection. Returning a case never grants authority.
ProbeHandler = Callable[[ProbeOffer, int], ProbeCapture]


@dataclass(frozen=True)
class ProbeDecision:
    """Deterministic proposal identifying a single missing verified relation."""
    status: str
    offer_digest: str | None
    provider_id: str | None
    estimated_total_costs: tuple[RouteMetric, ...]
    existing_route: dict
    considered: tuple[dict, ...]

    def to_dict(self) -> dict:
        return {"status": self.status, "offer_digest": self.offer_digest,
                "provider_id": self.provider_id,
                "estimated_total_costs": [c.to_dict() for c in self.estimated_total_costs],
                "existing_route": self.existing_route, "considered": list(self.considered),
                "claim": "possible-one-missing-relation-not-evidence"}


@dataclass(frozen=True)
class ProbeEvent:
    """Append-only attempt whose predecessor digest remains bound in history."""
    ordinal: int
    offer_digest: str
    status: str
    observed_case_digest: str | None
    captured_bytes: int
    request_count: int
    elapsed_ns: int
    raw_evidence_digest: str | None
    predecessor_digest: str
    detail: str

    @property
    def digest(self) -> str:
        return canonical_value_digest(self.to_dict())

    def to_dict(self) -> dict:
        return {"ordinal": self.ordinal, "offer_digest": self.offer_digest,
                "status": self.status, "observed_case_digest": self.observed_case_digest,
                "captured_bytes": self.captured_bytes, "request_count": self.request_count,
                "elapsed_ns": self.elapsed_ns, "raw_evidence_digest": self.raw_evidence_digest,
                "predecessor_digest": self.predecessor_digest,
                "detail": self.detail}


@dataclass
class ProspectiveQualifier:
    """Select, observe, qualify, and re-resolve without a shadow route graph."""

    router: InternetGroundRouter
    handlers: Mapping[str, ProbeHandler]
    policy: ProbePolicy
    offers: tuple[ProbeOffer, ...]
    history: list[ProbeEvent] = field(default_factory=list, init=False)

    def __post_init__(self) -> None:
        if (not isinstance(self.router, InternetGroundRouter) or not isinstance(self.policy, ProbePolicy)
                or not isinstance(self.handlers, Mapping) or len(self.offers) > _MAX_OFFERS):
            raise ProspectiveRefused("prospective qualifier requires native router and bounded policy")
        if len({offer.digest for offer in self.offers}) != len(self.offers):
            raise ProspectiveRefused("identical offers must not be repeated")
        if any(not isinstance(o, ProbeOffer) for o in self.offers):
            raise ProspectiveRefused("untyped offer")
        if any(type(key) is not str or not callable(fn) for key, fn in self.handlers.items()):
            raise ProspectiveRefused("probe registry must contain installed local callables")
        if not set(self.handlers).issubset(self.policy.allowed_providers):
            raise ProspectiveRefused("handler outside explicit receiver allowlist")
        # Enforce a *single* receiver-installed verifier binding per provider.
        # INTERNET-005 checks evidence with this verifier again at selection.
        if any(self.router._verifiers.get(provider) is None
               for provider in self.handlers):
            raise ProspectiveRefused("installed probe lacks native receiver verifier")

    @staticmethod
    def _authorized(os: HeadlessOS, pid: int, offer: ProbeOffer) -> bool:
        """Read HeadlessOS live process rights; an offer cannot create rights."""
        if not isinstance(os, HeadlessOS) or type(pid) is not int or pid < 1:
            raise ProspectiveRefused("live HeadlessOS process required")
        try:
            process = os.environment.kernel._process(pid)
        except Exception as exc:
            raise ProspectiveRefused("receiver process missing") from exc
        if process.status is ProcessStatus.EXITED:
            raise ProspectiveRefused("receiver process exited")
        resource = f"/internet/{offer.kind}/{offer.provider_id}"
        return any(isinstance(c, Capability) and c.allows(resource, "observe")
                   for c in process.capabilities)

    @staticmethod
    def _costs(route: dict, metric_order: tuple, missing: tuple[RouteMetric, ...],
               remainder: dict) -> tuple[RouteMetric, ...]:
        def vector(item):
            return {x["name"]: x["amount"] for x in item["route"]["total_costs"]}
        left, right = vector(route), vector(remainder)
        cost = {m.name: m.amount for m in missing}
        return tuple(RouteMetric(m.name, m.unit,
                                 left.get(m.name, 0) + cost[m.name] + right.get(m.name, 0))
                     for m in metric_order)

    def choose(self, intent: InternetIntention, os: HeadlessOS, pid: int) -> ProbeDecision:
        """Use the actual native resolver on qualified PREFIX and SUFFIX.

        A prospective edge is never supplied to EvidencePathCatalogue. One
        successful observation could close the remaining route; rank such
        opportunities by lexicographic cost (in the requested units). Unknown
        success probabilities are not invented as 'expected information gain'.
        """
        if not isinstance(intent, InternetIntention):
            raise ProspectiveRefused("typed native intention required")
        existing = self.router.resolve(intent, os, pid)
        if existing["status"] in (EvidencePathStatus.FOUND.value, EvidencePathStatus.ALREADY_AT_TARGET.value):
            return ProbeDecision("already_sufficient", None, None, (), existing, ())
        remaining = self.policy.total_response_budget - sum(x.captured_bytes for x in self.history)
        if len(self.history) >= self.policy.max_attempts or remaining <= 0:
            return ProbeDecision("budget_exhausted", None, None, (), existing, ())
        attempted = {x.offer_digest for x in self.history}
        considered: list[dict] = []
        eligible: list[tuple[tuple, str, ProbeOffer, tuple[RouteMetric, ...]]] = []
        units = {m.name: m.unit for m in intent.metric_order}
        ceilings = {m.name: m.amount for m in intent.resource_ceilings}
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
                continue
            # Current route graph must already justify reaching both sides of
            # the SINGLE proposed gap. No successful paired comparison is
            # fabricated for this hypothetical edge.
            prefix = self.router.resolve(replace(intent, target=offer.source), os, pid)
            suffix = self.router.resolve(replace(intent, source=offer.target), os, pid)
            if (prefix["status"] not in ("found", "already_at_target") or
                    suffix["status"] not in ("found", "already_at_target")):
                considered.append({"offer_digest": offer.digest, "reason": "not_a_single_verified_route_gap"})
                continue
            if (len(prefix["route"]["edge_ids"]) + 1 + len(suffix["route"]["edge_ids"]) > intent.max_hops):
                considered.append({"offer_digest": offer.digest, "reason": "hop_budget"})
                continue
            costs = self._costs(prefix, intent.metric_order, offer.estimated_costs, suffix)
            if any(m.amount > ceilings[m.name] for m in costs if m.name in ceilings):
                considered.append({"offer_digest": offer.digest, "reason": "estimated_route_budget"})
                continue
            score = tuple(m.amount for m in costs)
            eligible.append((score, offer.digest, offer, costs))
            considered.append({"offer_digest": offer.digest,
                               "reason": "eligible_single_missing_observation"})
        if not eligible:
            return ProbeDecision("no_eligible_probe", None, None, (), existing, tuple(considered))
        _, _, best, costs = min(eligible, key=lambda x: (x[0], x[1]))
        return ProbeDecision("probe_recommended", best.digest, best.provider_id,
                             costs, existing, tuple(considered))

    def step(self, intent: InternetIntention, os: HeadlessOS, pid: int) -> dict:
        """One receiver-approved network observation, then independent admission.

        If the probe fails, record refusal and permit the next candidate on
        a later explicit call; never interpret failure as a negative answer.
        """
        plan = self.choose(intent, os, pid)
        if plan.offer_digest is None:
            return {"schema": _SCHEMA + ".step", "status": plan.status,
                    "decision": plan.to_dict(), "event": None,
                    "result": plan.existing_route}
        offer = next(o for o in self.offers if o.digest == plan.offer_digest)
        remaining = self.policy.total_response_budget - sum(x.captured_bytes for x in self.history)
        allowed = min(offer.max_response_bytes, remaining)
        ordinal = len(self.history)
        previous = self.history[-1].digest if self.history else "0" * 64
        status = "probe_refused"
        details = "handler_failure_or_invalid_capture"
        captured_bytes = 0
        requests = 0
        elapsed_ns = 0
        case_digest = None
        raw_evidence_digest = None
        try:
            # A capability can be revoked after prospective route selection.
            # Re-evaluate the live receiver before issuing any network I/O.
            if not self._authorized(os, pid, offer):
                raise ProspectiveRefused("local probe capability revoked before dispatch")
            capture = self.handlers[offer.provider_id](offer, allowed)
            if not isinstance(capture, ProbeCapture):
                raise ProspectiveRefused("installed probe returned no typed capture")
            captured_bytes = capture.raw_response_bytes
            requests = capture.request_count
            elapsed_ns = capture.elapsed_ns
            raw_evidence_digest = capture.raw_evidence_digest
            if capture.raw_response_bytes > allowed or capture.request_count > offer.max_requests:
                raise ProspectiveRefused("capture exceeds declared byte or request policy")
            case = capture.case
            if ((case.provider_id, case.kind, case.operation, case.source, case.target,
                 case.ground_digest, case.context_digest) !=
                (offer.provider_id, offer.kind, offer.operation, offer.source, offer.target,
                 offer.ground_digest, offer.context_digest)):
                raise ProspectiveRefused("captured case changes the proposed Ground or identity")
            if not case.observed_at <= intent.now <= case.expires_at:
                raise ProspectiveRefused("observed case is not current")
            if {m.name: m.unit for m in case.costs} != {m.name: m.unit for m in intent.metric_order}:
                raise ProspectiveRefused("measured costs differ in unit or dimension")
            # Native receiver-installed verifier is the authority for exact
            # source/protocol evidence, not the capture or its supplied hashes.
            if self.router._verifiers[case.provider_id](case) is not True:
                raise ProspectiveRefused("native independent receiver verifier refused")
            # Reject a locally rehashed projection contradiction before
            # adding anything to the catalogue. Matching digests alone never
            # prove an observation relationship.
            self.router._edge(case)
            self.router.add(case)
            resolved = self.router.resolve(intent, os, pid)
            if case.case_digest not in {s["case_digest"] for s in resolved["selected"]}:
                status = "case_accepted_not_selected"
                details = "native_resolver_did_not_select_newly_qualified_case"
            else:
                status = "qualified_and_routed"
                details = "independent_case_accepted_and_native_route_found"
            case_digest = case.case_digest
        except Exception as exc:
            # An exception is a failed attempt, never an observed negative
            # Ground value. Do not leak arbitrary network exception content.
            details = type(exc).__name__
        event = ProbeEvent(ordinal, offer.digest, status, case_digest,
                           captured_bytes, requests, elapsed_ns, raw_evidence_digest,
                           previous, details)
        self.history.append(event)
        result = self.router.resolve(intent, os, pid)
        return {"schema": _SCHEMA + ".step", "status": status,
                "decision": plan.to_dict(), "event": event.to_dict(),
                "event_digest": event.digest, "result": result,
                "evidence_scope": "local-handler-capture-and-receiver-admission-not-external-attestation"}

    def run(self, intent: InternetIntention, os: HeadlessOS, pid: int) -> dict:
        """Try successive independent offers within the finite receiver quota."""
        steps = []
        while True:
            outcome = self.step(intent, os, pid)
            steps.append(outcome)
            if outcome["status"] in ("qualified_and_routed", "already_sufficient",
                                      "no_eligible_probe", "budget_exhausted"):
                break
            if len(self.history) >= self.policy.max_attempts:
                break
        return {"schema": _SCHEMA + ".run", "steps": steps,
                "attempts": len(self.history),
                "consumed_response_bytes": sum(e.captured_bytes for e in self.history),
                "last_status": steps[-1]["status"],
                "event_chain_tip": self.history[-1].digest if self.history else "0" * 64,
                "not": "not_a_self-authorizing_external_network_oracle"}
