"""INTERNET-009: source-evidence-driven, append-only intention Ground revision.

INTERNET-005/006/007/008 can select a receiver-authorized Internet probe and
admit a verified exact observation into the native EvidencePathResolver. This
module closes the *mathematical* feedback loop: a qualified observation may
refine a receiver-provisioned finite Ground and cause exact sufficiency
re-planning. A VGI hypothetical scenario or model digest cannot substitute for
an actual native ProbeEvent or for the raw source verification callback.

A Ground revision is NOT a server-signed fact, proof that the original finite
model spans reality, generic inference authority, execution permission or an
effect receipt. A contradiction preserves evidence and makes the model
UNRESOLVED; it never fabricates a false measurement or a new operator.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from typing import Any, Callable, Mapping

from .internet_ground_routing import InternetIntention, InternetObservationCase
from .internet_prospective_qualification import (
    ProbeEvent, ProspectiveQualifier, ProspectiveRefused,
)
from .intention_sufficiency import (
    FiniteGround, MeasurementCapability, SufficiencyRefused,
    _bytes, _decode, plan_sufficiency,
)
from .semantic_translation import canonical_value_digest

SCHEMA = "mailcpu.internet-evidence-model-revision.v1"
MAX_REVISIONS = 16
MAX_ARCHIVE = 8 * 1024 * 1024
_ACCEPTED = frozenset(("case_accepted_not_selected", "qualified_and_routed"))


class GroundRevisionRefused(ValueError):
    """Missing source proof, changed reader policy, or incompatible revision."""


@dataclass(frozen=True)
class SourceFeatureReading:
    """One receiver-decoded typed feature; never supplied as an Internet offer.

    The decoder independently checks original source bytes and protocol
    meaning, then recomputes both the native capture digest and the exact
    admitted case's source evidence digest.
    """

    value: Any
    raw_evidence_digest: str
    case_evidence_digest: str

    def __post_init__(self) -> None:
        from .internet_ground_routing import _check_digest
        _bytes(self.value)
        _check_digest(self.raw_evidence_digest, "source capture")
        _check_digest(self.case_evidence_digest, "source case")


SourceDecoder = Callable[[InternetObservationCase, bytes], SourceFeatureReading]


@dataclass(frozen=True)
class ReceiverFeatureBinding:
    """Receiver-installed decoder is trusted code, NOT supplied by the website."""

    offer_digest: str
    provider_id: str
    feature_id: str
    decoder: SourceDecoder
    max_archive_bytes: int = MAX_ARCHIVE

    def __post_init__(self) -> None:
        from .internet_ground_routing import _check_digest, _NAME
        _check_digest(self.offer_digest, "bound offer")
        if (type(self.provider_id) is not str or _NAME.fullmatch(self.provider_id) is None
                or type(self.feature_id) is not str or _NAME.fullmatch(self.feature_id) is None
                or not callable(self.decoder)
                or type(self.max_archive_bytes) is not int
                or not 1 <= self.max_archive_bytes <= MAX_ARCHIVE):
            raise GroundRevisionRefused("invalid receiver-owned source decoder binding")


@dataclass
class EvidenceGroundRevision:
    """Finite hypothesis-space narrowing after ACTUAL native evidence admission.

    Revisions never mutate the original FiniteGround or its contracts.
    Source-level validity is rechecked on every admission through an installed
    independent decoder; when source evidence conflicts with the model, the
    model becomes contradicted instead of silently dropping that evidence.
    """

    base: FiniteGround
    public_value: Any
    offers: tuple[MeasurementCapability, ...]
    bindings: tuple[ReceiverFeatureBinding, ...]
    authority_digest: str
    receipts: list[dict] = field(default_factory=list, init=False)
    _readings: dict[str, bytes] = field(default_factory=dict, init=False, repr=False)
    _seen: dict[str, tuple[str, str]] = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self) -> None:
        from .internet_ground_routing import _check_digest
        if (not isinstance(self.base, FiniteGround)
                or type(self.offers) is not tuple
                or type(self.bindings) is not tuple):
            raise GroundRevisionRefused("pinned finite Ground and receiver bindings required")
        _check_digest(self.authority_digest, "original receiver authority")
        public = _bytes(self.public_value)
        if not any(row.public_json == public for row in self.base.states):
            raise GroundRevisionRefused("receiver public value absent from finite Ground")
        names = {name for name, _ in self.base.states[0].feature_json}
        offer_names = {x.feature_id for x in self.offers}
        if len(offer_names) != len(self.offers) or not offer_names.issubset(names):
            raise GroundRevisionRefused("feature capability catalogue is incomplete")
        if (not self.bindings or len(self.bindings) > 32
                or len({x.offer_digest for x in self.bindings}) != len(self.bindings)
                or len({x.feature_id for x in self.bindings}) != len(self.bindings)
                or any(x.feature_id not in offer_names for x in self.bindings)):
            raise GroundRevisionRefused("duplicate, missing or unknown decoder feature")
        plan_sufficiency(self.base, self.public_value, self.offers, self.authority_digest)

    @property
    def tip(self) -> str:
        return self.receipts[-1]["digest"] if self.receipts else "0" * 64

    def _candidates(self) -> tuple:
        public = _bytes(self.public_value)
        return tuple(
            row for row in self.base.states
            if row.public_json == public
            and all(row.features[name] == value for name, value in self._readings.items())
        )

    def current_ground(self) -> FiniteGround | None:
        """Rebuild an exact model subset, or return None on contradiction."""
        rows = self._candidates()
        if not rows:
            return None
        return FiniteGround(
            self.base.ground_digest,
            self.base.public_contract_digest,
            self.base.intention_contract_digest,
            self.base.context_digest,
            rows,
        )

    def snapshot(self) -> dict:
        """Recompute native exact sufficiency, never trust prior plan output."""
        subset = self.current_ground()
        measured = tuple(sorted(self._readings))
        offered = tuple(x for x in self.offers if x.feature_id not in self._readings)
        if subset is None:
            status, plan = "MODEL_CONTRADICTED", None
            target = None
        else:
            plan = plan_sufficiency(
                subset, self.public_value, offered, self.authority_digest,
            )
            status = "CONDITIONALLY_RESOLVED" if plan["status"] == "READY" else (
                "MODEL_UNRESOLVED" if plan["status"] == "REFUSE"
                else "MORE_SOURCE_EVIDENCE_REQUIRED"
            )
            target = plan["ready_result"] if status == "CONDITIONALLY_RESOLVED" else None
        body = {
            "schema": SCHEMA + ".snapshot",
            "base_model_digest": self.base.digest,
            "current_model_digest": subset.digest if subset is not None else None,
            "source_conditioned": bool(self.receipts),
            "model_status": status,
            "conditional_result": target,
            "candidate_count": len(self._candidates()),
            "measured_features": list(measured),
            "remaining_features": list(sorted(x.feature_id for x in offered)),
            "sufficiency_plan": plan,
            "source_event_digests": [r["source_event_digest"] for r in self.receipts],
            "revision_count": len(self.receipts),
            "revision_tip": self.tip,
            "not": "finite_hypothesis_result_not_a_remotely_attested_world_fact_or_execution_authority",
        }
        body["digest"] = canonical_value_digest(body)
        return body

    def admit(self, qualifier: ProspectiveQualifier, intent: InternetIntention,
              event: ProbeEvent, raw_archive: bytes) -> dict:
        """Admit one source-derived observation ONLY after native qualification.

        The original prospective Internet router owns *actual* case admission.
        This function does not insert a new route, invoke remote code, or
        decide whether a source may be contacted. It only rechecks the
        already-accepted case, independently parses original bytes with the
        receiver's decoder, and narrows the finite hypothesis table.
        """
        if (not isinstance(qualifier, ProspectiveQualifier)
                or not isinstance(intent, InternetIntention)
                or not isinstance(event, ProbeEvent)
                or type(raw_archive) is not bytes
                or not 1 <= len(raw_archive) <= MAX_ARCHIVE):
            raise GroundRevisionRefused("typed native Internet evidence and raw bytes required")
        if (intent.ground_digest != self.base.ground_digest
                or intent.context_digest != self.base.context_digest
                or not qualifier.history
                or event.status not in _ACCEPTED):
            raise GroundRevisionRefused("not a native-qualified source observation")
        expected_prev = "0" * 64
        found = False
        for i, recorded in enumerate(qualifier.history):
            if (recorded.ordinal != i or recorded.predecessor_digest != expected_prev):
                raise GroundRevisionRefused("native observation attempt chain changed")
            expected_prev = recorded.digest
            if recorded is event:
                found = True
        if not found:
            raise GroundRevisionRefused("event not present in original native observation history")
        offer = next((o for o in qualifier.offers if o.digest == event.offer_digest), None)
        binding = next((b for b in self.bindings if b.offer_digest == event.offer_digest), None)
        case = qualifier.router._cases.get(event.observed_case_digest or "")
        if (offer is None or binding is None or case is None
                or not isinstance(case, InternetObservationCase)
                or offer.provider_id != case.provider_id
                or binding.provider_id != case.provider_id
                or (case.kind, case.operation, case.source, case.target,
                    case.ground_digest, case.context_digest) !=
                   (offer.kind, offer.operation, offer.source, offer.target,
                    offer.ground_digest, offer.context_digest)
                or event.observed_case_digest != case.case_digest
                or not case.observed_at <= intent.now <= case.expires_at):
            raise GroundRevisionRefused("native event has no exact current receiver observation case")
        if not qualifier.router._verifiers[case.provider_id](case):
            raise GroundRevisionRefused("original native receiver refused source case")
        qualifier.router._edge(case)
        if len(raw_archive) > binding.max_archive_bytes:
            raise GroundRevisionRefused("raw source archive exceeds receiver policy")
        try:
            reading = binding.decoder(case, raw_archive)
        except (ValueError, TypeError, KeyError) as exc:
            raise GroundRevisionRefused("source-specific independent decoder refused bytes") from exc
        if (not isinstance(reading, SourceFeatureReading)
                or reading.raw_evidence_digest != event.raw_evidence_digest
                or reading.case_evidence_digest != case.evidence_digest):
            raise GroundRevisionRefused("decoded raw source and admitted case digests disagree")
        value = _bytes(reading.value)
        archive_sha = sha256(raw_archive).hexdigest()
        original = self._seen.get(binding.feature_id)
        if original is not None:
            if original == (event.digest, archive_sha):
                return next(x for x in self.receipts if x["source_event_digest"] == event.digest)
            raise GroundRevisionRefused("changing an observed feature requires a new context revision")
        if self.current_ground() is None:
            raise GroundRevisionRefused("contradicted model cannot promote more inferences")
        if len(self.receipts) >= MAX_REVISIONS:
            raise GroundRevisionRefused("bounded source observation revision quota exceeded")
        before = tuple(x.state_id for x in self._candidates())
        after = tuple(x.state_id for x in self._candidates()
                      if x.features[binding.feature_id] == value)
        body = {
            "schema": SCHEMA + ".receipt",
            "base_model_digest": self.base.digest,
            "original_authority_digest": self.authority_digest,
            "revision_index": len(self.receipts),
            "previous_revision": self.tip,
            "feature_id": binding.feature_id,
            "reading": _decode(value),
            "offer_digest": event.offer_digest,
            "source_event_digest": event.digest,
            "source_case_digest": case.case_digest,
            "case_evidence_digest": case.evidence_digest,
            "raw_capture_digest": event.raw_evidence_digest,
            "raw_archive_sha256": archive_sha,
            "previous_states": list(before),
            "remaining_states": list(after),
            "status": "MODEL_CONTRADICTION" if not after else "EVIDENCE_CONDITIONED",
            "evidence_scope": "native_verified_case_and_receiver_replayed_bytes_not_external_attestation",
        }
        body["digest"] = canonical_value_digest(body)
        self._readings[binding.feature_id] = value
        self._seen[binding.feature_id] = (event.digest, archive_sha)
        self.receipts.append(body)
        return dict(body)

    def replay(self, qualifier: ProspectiveQualifier, intent: InternetIntention,
               archives: tuple[tuple[ProbeEvent, bytes], ...]) -> dict:
        """An independent reader can reconstruct the same exact append-only Ground.

        Caller must independently supply receiver-authorized native cases,
        their source-specific verifiers and raw source archives. This does
        not claim signatures on the original remote observations.
        """
        if self.receipts:
            raise GroundRevisionRefused("replay requires a fresh original Ground")
        for event, archive in archives:
            self.admit(qualifier, intent, event, archive)
        return self.snapshot()
