"""Typed, confidence-aware decision primitives and the MailCPU classifier hypervisor."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Mapping, Protocol, Sequence

from .evidence import EvidenceTier, with_evidence_tier
from .intent_embedding import IntentPrediction, IntentPrototypeModel, VirtualCost, estimate_virtual_cost
from .journal import EventJournal


class ClassifierError(ValueError):
    """A typed question, probability distribution, or hypervisor request is invalid."""


class QuestionKind(str, Enum):
    """The three bounded decision primitives mirrored by the public Jev contract."""

    CHOICE = "choice"
    SCORE = "score"
    NOUL = "noul"


@dataclass(frozen=True)
class ChoiceQuestion:
    """A finite unordered choice question with at most 255 named options."""

    instructions: str
    criteria: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        """Mathematics: require `1 ≤ |criteria| ≤ 255` and unique non-empty option keys."""

        keys = [key for key, _ in self.criteria]
        if not self.instructions or not 1 <= len(keys) <= 255 or len(set(keys)) != len(keys) or any(not key for key in keys):
            raise ClassifierError("invalid Choice question")

    @classmethod
    def from_mapping(cls, instructions: str, criteria: Mapping[str, str]) -> "ChoiceQuestion":
        """Mathematics: canonicalize finite map `criteria` into lexicographically ordered option relation."""

        return cls(instructions, tuple(sorted((str(key), str(value)) for key, value in criteria.items())))


@dataclass(frozen=True)
class ScoreQuestion:
    """An ordered score question with two to ten descriptive levels."""

    instructions: str
    levels: tuple[str, ...]

    def __post_init__(self) -> None:
        """Mathematics: require ordered level domain `2 ≤ n = |levels| ≤ 10`."""

        if not self.instructions or not 2 <= len(self.levels) <= 10 or any(not level for level in self.levels):
            raise ClassifierError("invalid Score question")


@dataclass(frozen=True)
class NoulQuestion:
    """A yes/no question represented by probability `p ∈ [0,1]` that the proposition is true."""

    instructions: str
    true_criteria: str = ""
    false_criteria: str = ""

    def __post_init__(self) -> None:
        """Mathematics: require a non-empty proposition over binary outcome set `{false, true}`."""

        if not self.instructions:
            raise ClassifierError("invalid Noul question")


Question = ChoiceQuestion | ScoreQuestion | NoulQuestion


@dataclass(frozen=True)
class ChoiceAnswer:
    """Typed Choice result with a normalized distribution and derived confidence."""

    choice: str
    probabilities: dict[str, float]
    confidence: float

    @property
    def kind(self) -> QuestionKind:
        """Mathematics: identify answer type `kind(answer) = CHOICE`."""

        return QuestionKind.CHOICE


@dataclass(frozen=True)
class ScoreAnswer:
    """Typed Score result whose scalar is the probability-weighted level expectation."""

    score: float
    probabilities: tuple[float, ...]
    confidence: float

    @property
    def kind(self) -> QuestionKind:
        """Mathematics: identify answer type `kind(answer) = SCORE`."""

        return QuestionKind.SCORE


@dataclass(frozen=True)
class NoulAnswer:
    """Typed binary result with probability `p = P(proposition = true)`."""

    noul: float

    @property
    def kind(self) -> QuestionKind:
        """Mathematics: identify answer type `kind(answer) = NOUL`."""

        return QuestionKind.NOUL


Answer = ChoiceAnswer | ScoreAnswer | NoulAnswer


@dataclass(frozen=True)
class DecisionBatch:
    """One shared-state evaluation containing independently keyed typed answers."""

    answers: dict[str, Answer]
    model: str

    def to_dict(self) -> dict[str, object]:
        """Mathematics: serialize answer map `A : question_id ⇀ typed_answer` without losing distributions."""

        encoded: dict[str, object] = {}
        for key, answer in sorted(self.answers.items()):
            if isinstance(answer, ChoiceAnswer):
                encoded[key] = {
                    "type": answer.kind.value,
                    "choice": answer.choice,
                    "probabilities": dict(sorted(answer.probabilities.items())),
                    "confidence": answer.confidence,
                }
            elif isinstance(answer, ScoreAnswer):
                encoded[key] = {
                    "type": answer.kind.value,
                    "score": answer.score,
                    "probabilities": list(answer.probabilities),
                    "confidence": answer.confidence,
                }
            else:
                encoded[key] = {"type": answer.kind.value, "noul": answer.noul}
        return with_evidence_tier({"model": self.model, "answers": encoded}, EvidenceTier.E0)


class ClassifierModel(Protocol):
    """Model boundary: one state and many typed questions produce one decision batch."""

    def evaluate(self, state: Mapping[str, Any], questions: Mapping[str, Question]) -> DecisionBatch:
        """Mathematics: evaluate `f(state, {q_i}) = {answer_i}` with question independence under one shared state."""

        ...


class RevisionCandidate(Protocol):
    """Checkpointable candidate boundary shared by classifier and intent revisions."""

    def snapshot(self) -> Mapping[str, Any]:
        """Mathematics: expose candidate state `m'` as a finite canonical mapping `S(m')`."""

        ...


def choice_confidence(probabilities: Mapping[str, float]) -> float:
    """Mathematics: compute Jev-style Choice confidence `c=(p_max-1/n)/(1-1/n)` for `n ≥ 2`."""

    _validate_distribution(probabilities.values())
    count = len(probabilities)
    if count == 1:
        return 1.0
    return max(0.0, min(1.0, (max(probabilities.values()) - 1.0 / count) / (1.0 - 1.0 / count)))


def score_confidence(probabilities: tuple[float, ...]) -> float:
    """Mathematics: compute `max(0,1−Σ_i p_i|i−m|/MAD_uniform)` with `m=Σ_i i p_i`."""

    _validate_distribution(probabilities)
    count = len(probabilities)
    mean = sum(index * probability for index, probability in enumerate(probabilities))
    spread = sum(probability * abs(index - mean) for index, probability in enumerate(probabilities))
    uniform_mad = sum(abs(index - (count - 1) / 2) for index in range(count)) / count
    return 1.0 if uniform_mad == 0 else max(0.0, min(1.0, 1.0 - spread / uniform_mad))


class LexicalDecisionModel:
    """Deterministic E0 reference classifier using bounded lexical evidence and softmax probabilities."""

    def __init__(self, model: str = "mailcpu-lexical-e0") -> None:
        """Mathematics: fix model identity `m` so identical `(state, questions)` yield identical decisions."""

        self.model = model

    def evaluate(self, state: Mapping[str, Any], questions: Mapping[str, Question]) -> DecisionBatch:
        """Mathematics: evaluate all questions independently as `A_i = f(state, q_i)` and return one keyed batch."""

        state_tokens = canonical_tokens(state)
        answers: dict[str, Answer] = {}
        for key, question in sorted(questions.items()):
            if isinstance(question, ChoiceQuestion):
                scores = {option: _evidence_score(state_tokens, description) for option, description in question.criteria}
                probabilities = softmax(scores, ClassifierError)
                answers[key] = ChoiceAnswer(max(probabilities, key=lambda option: (probabilities[option], option)), probabilities, choice_confidence(probabilities))
            elif isinstance(question, ScoreQuestion):
                scores = [_evidence_score(state_tokens, level) for level in question.levels]
                probabilities = tuple(softmax({str(index): score for index, score in enumerate(scores)}, ClassifierError).values())
                answers[key] = ScoreAnswer(
                    sum(index * probability for index, probability in enumerate(probabilities)),
                    probabilities,
                    score_confidence(probabilities),
                )
            else:
                true_score = _evidence_score(state_tokens, question.true_criteria or question.instructions)
                false_score = _evidence_score(state_tokens, question.false_criteria)
                margin = true_score - false_score
                answers[key] = NoulAnswer(1.0 / (1.0 + math.exp(-margin)))
        return DecisionBatch(answers, self.model)


class HypervisorAction(str, Enum):
    """Control outcomes for classifier-gated execution requests."""

    ALLOW = "allow"
    REVIEW = "review"
    DENY = "deny"


class HypervisorDomain(str, Enum):
    """Execution domains selected by the classifier hypervisor."""

    CPU = "cpu"
    FILESYSTEM = "filesystem"
    NETWORK = "network"
    SERVICE = "service"
    REVIEW = "review"


@dataclass(frozen=True)
class HypervisorRequest:
    """A typed resource request presented to the classifier hypervisor."""

    operation: str
    resource: str
    payload: Mapping[str, Any]
    required_rights: frozenset[str] = frozenset()
    granted_rights: frozenset[str] = frozenset()
    destructive: bool = False
    temporal: Mapping[str, Any] | None = None

    def state(self) -> dict[str, object]:
        """Mathematics: form shared state `x=(operation,resource,payload,authority,risk,time)` for all advisory and exact gates."""

        state: dict[str, object] = {
            "operation": self.operation,
            "resource": self.resource,
            "payload": dict(self.payload),
            "required_rights": sorted(self.required_rights),
            "granted_rights": sorted(self.granted_rights),
            "destructive": self.destructive,
        }
        if self.temporal is not None:
            state["temporal"] = dict(self.temporal)
        return state

    @classmethod
    def from_state(cls, payload: Mapping[str, Any]) -> "HypervisorRequest":
        """Mathematics: invert request state `x` only when operation, resource, payload, rights, risk, and time retain their typed domains."""

        if not isinstance(payload, Mapping):
            raise ClassifierError("hypervisor request state must be a mapping")
        operation = payload.get("operation")
        resource = payload.get("resource")
        request_payload = payload.get("payload")
        required = payload.get("required_rights", ())
        granted = payload.get("granted_rights", ())
        temporal = payload.get("temporal")
        if (
            not isinstance(operation, str)
            or not operation
            or not isinstance(resource, str)
            or not resource
            or not isinstance(request_payload, Mapping)
            or not isinstance(required, (list, tuple))
            or not isinstance(granted, (list, tuple))
            or any(not isinstance(right, str) or not right for right in (*required, *granted))
            or not isinstance(payload.get("destructive", False), bool)
            or (temporal is not None and not isinstance(temporal, Mapping))
        ):
            raise ClassifierError("hypervisor request state has invalid fields")
        return cls(
            operation,
            resource,
            dict(request_payload),
            frozenset(required),
            frozenset(granted),
            bool(payload.get("destructive", False)),
            None if temporal is None else dict(temporal),
        )


@dataclass(frozen=True)
class HypervisorDecision:
    """Classifier result plus policy gate and journal receipt."""

    action: HypervisorAction
    domain: HypervisorDomain
    confidence: float
    danger_probability: float
    probabilities: dict[str, float]
    model: str
    receipt: str
    intent_domain: str = ""
    intent_confidence: float = 0.0
    intent_probabilities: dict[str, float] = field(default_factory=dict)
    intent_digest: str = ""
    virtual_cost: VirtualCost | None = None
    revision: int = 0

    def __post_init__(self) -> None:
        """Mathematics: require the producing classifier revision `r∈ℕ₀` to be explicit and finite."""

        if not isinstance(self.revision, int) or isinstance(self.revision, bool) or self.revision < 0:
            raise ClassifierError("decision revision must be a non-negative integer")

    def to_dict(self) -> dict[str, object]:
        """Mathematics: project decision `d` and advisory/time receipts into a stable control-plane record."""

        return with_evidence_tier(
            {
                "action": self.action.value,
                "domain": self.domain.value,
                "confidence": self.confidence,
                "danger_probability": self.danger_probability,
                "probabilities": dict(sorted(self.probabilities.items())),
                "model": self.model,
                "receipt": self.receipt,
                "revision": self.revision,
                "intent_embedding": {
                    "domain": self.intent_domain,
                    "confidence": self.intent_confidence,
                    "probabilities": dict(sorted(self.intent_probabilities.items())),
                    "digest": self.intent_digest,
                },
                "virtual_cost": self.virtual_cost.to_dict() if self.virtual_cost is not None else None,
            },
            EvidenceTier.E0,
        )


def _decision_semantics(decision: HypervisorDecision) -> dict[str, object]:
    """Mathematics: project policy semantics `π(D)` while quotienting receipt and model transport identity."""

    return {
        "action": decision.action.value,
        "domain": decision.domain.value,
        "confidence": decision.confidence,
        "danger_probability": decision.danger_probability,
        "probabilities": dict(sorted(decision.probabilities.items())),
        "intent_domain": decision.intent_domain,
        "intent_confidence": decision.intent_confidence,
        "intent_probabilities": dict(sorted(decision.intent_probabilities.items())),
        "virtual_cost": decision.virtual_cost.to_dict() if decision.virtual_cost is not None else None,
    }


def _canonical_json_bytes(value: Any) -> bytes:
    """Mathematics: encode finite value `x` as canonical bytes `J(x)=JSON(sort_keys,compact)(x)` or refuse it."""

    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ClassifierError("value is outside the canonical JSON domain") from exc


@dataclass(frozen=True)
class HypervisorRevisionWitness:
    """Immutable request/output pair that a candidate classifier must reproduce."""

    request: HypervisorRequest
    expected: Mapping[str, Any]

    def __post_init__(self) -> None:
        """Mathematics: require witness `w=(request,expected)` to be typed and canonically representable."""

        if not isinstance(self.request, HypervisorRequest) or not isinstance(self.expected, Mapping):
            raise ClassifierError("revision witness requires a request and mapping projection")
        _canonical_json_bytes(dict(self.expected))

    @classmethod
    def from_decision(cls, request: HypervisorRequest, decision: HypervisorDecision) -> "HypervisorRevisionWitness":
        """Mathematics: derive immutable witness `w=(r,π(D(r)))` from a known policy decision."""

        return cls(request, _decision_semantics(decision))

    def to_dict(self) -> dict[str, object]:
        """Mathematics: serialize witness relation `w` without including mutable journal receipt identity."""

        return {"request": self.request.state(), "expected": dict(self.expected)}

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "HypervisorRevisionWitness":
        """Mathematics: invert serialized witness `w=(request,expected)` while preserving its canonical semantic projection."""

        if not isinstance(payload, Mapping) or not isinstance(payload.get("request"), Mapping) or not isinstance(payload.get("expected"), Mapping):
            raise ClassifierError("revision witness snapshot has invalid fields")
        return cls(HypervisorRequest.from_state(payload["request"]), dict(payload["expected"]))


@dataclass(frozen=True)
class HypervisorIntentRevisionWitness:
    """Held-out intent prediction bound to the current authority action."""

    request: HypervisorRequest
    expected: Mapping[str, Any]
    baseline_action: HypervisorAction

    def __post_init__(self) -> None:
        """Mathematics: require witness `w=(x, M'(x), a)` to be typed and canonically representable."""

        if not isinstance(self.request, HypervisorRequest) or not isinstance(self.expected, Mapping):
            raise ClassifierError("intent revision witness requires a request and prediction mapping")
        if not isinstance(self.baseline_action, HypervisorAction):
            raise ClassifierError("intent revision witness baseline action is invalid")
        _canonical_json_bytes(dict(self.expected))

    @classmethod
    def from_prediction(
        cls,
        request: HypervisorRequest,
        prediction: IntentPrediction,
        baseline: HypervisorDecision,
    ) -> "HypervisorIntentRevisionWitness":
        """Mathematics: derive `w=(x,M'(x),a_current)` from a held-out prediction and current decision."""

        if not isinstance(prediction, IntentPrediction) or not isinstance(baseline, HypervisorDecision):
            raise ClassifierError("intent revision witness requires a prediction and baseline decision")
        return cls(request, prediction.to_dict(), baseline.action)

    def to_dict(self) -> dict[str, object]:
        """Mathematics: serialize the typed relation `w=(request,expected_prediction,baseline_action)`."""

        return {
            "request": self.request.state(),
            "expected": dict(self.expected),
            "baseline_action": self.baseline_action.value,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "HypervisorIntentRevisionWitness":
        """Mathematics: reconstruct `w` only when request, prediction, and baseline action retain their domains."""

        if (
            not isinstance(payload, Mapping)
            or not isinstance(payload.get("request"), Mapping)
            or not isinstance(payload.get("expected"), Mapping)
            or not isinstance(payload.get("baseline_action"), str)
        ):
            raise ClassifierError("intent revision witness snapshot has invalid fields")
        try:
            baseline = HypervisorAction(payload["baseline_action"])
        except ValueError as exc:
            raise ClassifierError("intent revision witness baseline action is invalid") from exc
        return cls(HypervisorRequest.from_state(payload["request"]), dict(payload["expected"]), baseline)


RevisionWitness = HypervisorRevisionWitness | HypervisorIntentRevisionWitness


@dataclass(frozen=True)
class HypervisorRevisionResult:
    """Outcome of one shadow-evaluated classifier revision proposal."""

    accepted: bool
    revision: int
    witness_digest: str
    candidate_model: str
    mismatch_index: int | None = None
    error: str | None = None
    target: str = "classifier"

    def __post_init__(self) -> None:
        """Mathematics: require revision `r≥0` and witness identity `d∈{0,1}^{256}`."""

        if self.revision < 0 or len(self.witness_digest) != 64 or any(
            character not in "0123456789abcdef" for character in self.witness_digest
        ):
            raise ClassifierError("invalid hypervisor revision result")
        if not self.candidate_model or self.target not in {"classifier", "intent"}:
            raise ClassifierError("revision result candidate model must be non-empty")

    def to_dict(self) -> dict[str, object]:
        """Mathematics: project revision result `R=(accepted,revision,digest,model,mismatch,error)` for audit."""

        return {
            "accepted": self.accepted,
            "revision": self.revision,
            "witness_digest": self.witness_digest,
            "candidate_model": self.candidate_model,
            "mismatch_index": self.mismatch_index,
            "error": self.error,
            "target": self.target,
        }


@dataclass(frozen=True)
class HypervisorRevisionProposal:
    """A checkpointable distributed envelope for one classifier revision proposal."""

    source: str
    channel: str
    sequence: int
    logical_time: int
    candidate_snapshot: Mapping[str, Any]
    witnesses: tuple[RevisionWitness, ...]
    target: str = "classifier"

    def __post_init__(self) -> None:
        """Mathematics: require `P=(I,m',W)` to have valid identity, canonical snapshot, and nonempty typed witness set."""

        if not isinstance(self.source, str) or not self.source:
            raise ClassifierError("revision proposal source must be non-empty")
        if not isinstance(self.channel, str) or not self.channel:
            raise ClassifierError("revision proposal channel must be non-empty")
        if not isinstance(self.sequence, int) or isinstance(self.sequence, bool) or self.sequence <= 0:
            raise ClassifierError("revision proposal sequence must be positive")
        if not isinstance(self.logical_time, int) or isinstance(self.logical_time, bool) or self.logical_time < 0:
            raise ClassifierError("revision proposal logical_time must be non-negative")
        if self.target not in {"classifier", "intent"}:
            raise ClassifierError("revision proposal target is invalid")
        if not isinstance(self.candidate_snapshot, Mapping) or not self.witnesses:
            raise ClassifierError("revision proposal requires a snapshot and witnesses")
        witness_type = HypervisorRevisionWitness if self.target == "classifier" else HypervisorIntentRevisionWitness
        if any(not isinstance(witness, witness_type) for witness in self.witnesses):
            raise ClassifierError("revision proposal witnesses have an invalid type")
        _canonical_json_bytes(self.to_dict())

    @property
    def identity(self) -> tuple[str, str, int]:
        """Mathematics: project proposal transport identity `I(P)=(source,channel,sequence)`."""

        return self.source, self.channel, self.sequence

    @classmethod
    def from_candidate(
        cls,
        source: str,
        channel: str,
        sequence: int,
        logical_time: int,
        candidate: RevisionCandidate,
        witnesses: Sequence[RevisionWitness],
        *,
        target: str = "classifier",
    ) -> "HypervisorRevisionProposal":
        """Mathematics: lift checkpointable model `m'` into typed envelope `P=(I,target,snapshot(m'),tuple(W))`."""

        snapshot = getattr(candidate, "snapshot", None)
        if not callable(snapshot):
            raise ClassifierError("revision proposal candidate must be checkpointable")
        candidate_snapshot = snapshot()
        if not isinstance(candidate_snapshot, Mapping):
            raise ClassifierError("revision proposal candidate snapshot must be a mapping")
        return cls(source, channel, sequence, logical_time, dict(candidate_snapshot), tuple(witnesses), target)

    def to_dict(self) -> dict[str, object]:
        """Mathematics: serialize proposal `P` into the canonical wire relation used by its fingerprint."""

        return {
            "source": self.source,
            "channel": self.channel,
            "sequence": self.sequence,
            "logical_time": self.logical_time,
            "target": self.target,
            "candidate_snapshot": dict(self.candidate_snapshot),
            "witnesses": [witness.to_dict() for witness in self.witnesses],
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "HypervisorRevisionProposal":
        """Mathematics: invert canonical proposal `P` only when identity, candidate snapshot, and every witness reconstruct exactly."""

        if not isinstance(payload, Mapping):
            raise ClassifierError("revision proposal snapshot must be a mapping")
        target = str(payload.get("target", "classifier"))
        raw_candidate = payload.get("candidate_snapshot")
        raw_witnesses = payload.get("witnesses")
        if not isinstance(raw_candidate, Mapping) or not isinstance(raw_witnesses, (list, tuple)):
            raise ClassifierError("revision proposal snapshot has invalid candidate or witnesses")
        witness_factory = HypervisorRevisionWitness.from_dict if target == "classifier" else HypervisorIntentRevisionWitness.from_dict
        return cls(
            payload.get("source"),
            payload.get("channel"),
            payload.get("sequence"),
            payload.get("logical_time"),
            dict(raw_candidate),
            tuple(witness_factory(raw) for raw in raw_witnesses),
            target,
        )


@dataclass(frozen=True)
class HypervisorRevisionArbitrationResult:
    """One first-seen or replayed distributed revision-proposal outcome."""

    source: str
    channel: str
    sequence: int
    logical_time: int
    fingerprint: str
    admission: HypervisorRevisionResult
    replayed: bool
    target: str = "classifier"

    def __post_init__(self) -> None:
        """Mathematics: require valid proposal identity, `f(P)∈{0,1}^{256}`, and typed admission result."""

        if not isinstance(self.source, str) or not self.source or not isinstance(self.channel, str) or not self.channel:
            raise ClassifierError("revision arbitration identity must be non-empty")
        if not isinstance(self.sequence, int) or isinstance(self.sequence, bool) or self.sequence <= 0:
            raise ClassifierError("revision arbitration sequence must be positive")
        if not isinstance(self.logical_time, int) or isinstance(self.logical_time, bool) or self.logical_time < 0:
            raise ClassifierError("revision arbitration logical_time must be non-negative")
        if len(self.fingerprint) != 64 or any(character not in "0123456789abcdef" for character in self.fingerprint):
            raise ClassifierError("revision proposal fingerprint must be lowercase SHA-256 hex")
        if not isinstance(self.admission, HypervisorRevisionResult):
            raise ClassifierError("revision arbitration requires a revision result")
        if self.target not in {"classifier", "intent"}:
            raise ClassifierError("revision arbitration target is invalid")
        if self.admission.target != self.target:
            raise ClassifierError("revision arbitration target does not match admission target")

    def to_dict(self) -> dict[str, object]:
        """Mathematics: project result `R=(I,f,admission,replayed)` for stable audit and checkpoint state."""

        return {
            "source": self.source,
            "channel": self.channel,
            "sequence": self.sequence,
            "logical_time": self.logical_time,
            "fingerprint": self.fingerprint,
            "admission": self.admission.to_dict(),
            "replayed": self.replayed,
            "target": self.target,
        }


@dataclass(frozen=True)
class HypervisorArbitrationEvent:
    """A distributed request envelope with a stable replay identity."""

    source: str
    channel: str
    sequence: int
    logical_time: int
    request: HypervisorRequest

    def __post_init__(self) -> None:
        """Mathematics: require event identity `e=(source,channel,s,t,r)` with nonempty labels, `s>0`, and `t≥0`."""

        if not isinstance(self.source, str) or not self.source:
            raise ClassifierError("arbitration source must be non-empty")
        if not isinstance(self.channel, str) or not self.channel:
            raise ClassifierError("arbitration channel must be non-empty")
        if not isinstance(self.sequence, int) or isinstance(self.sequence, bool) or self.sequence <= 0:
            raise ClassifierError("arbitration sequence must be positive")
        if not isinstance(self.logical_time, int) or isinstance(self.logical_time, bool) or self.logical_time < 0:
            raise ClassifierError("arbitration logical_time must be non-negative")
        if not isinstance(self.request, HypervisorRequest):
            raise ClassifierError("arbitration request must be a HypervisorRequest")

    @property
    def identity(self) -> tuple[str, str, int]:
        """Mathematics: project transport identity `I(e)=(source,channel,sequence)` independently of payload."""

        return self.source, self.channel, self.sequence

    def to_dict(self) -> dict[str, object]:
        """Mathematics: serialize the finite event relation `e` without changing request semantics."""

        return {
            "source": self.source,
            "channel": self.channel,
            "sequence": self.sequence,
            "logical_time": self.logical_time,
            "request": self.request.state(),
        }


@dataclass(frozen=True)
class HypervisorArbitrationResult:
    """One first-seen or replayed arbitration outcome."""

    source: str
    channel: str
    sequence: int
    logical_time: int
    fingerprint: str
    decision_receipt: str
    decision: HypervisorDecision | None
    replayed: bool
    decision_revision: int = 0

    def __post_init__(self) -> None:
        """Mathematics: require hash identities and revision `r∈ℕ₀` for the accepted or replayed decision."""

        for name, value in (("fingerprint", self.fingerprint), ("decision_receipt", self.decision_receipt)):
            if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
                raise ClassifierError(f"{name} must be lowercase SHA-256 hex")
        if not isinstance(self.decision_revision, int) or isinstance(self.decision_revision, bool) or self.decision_revision < 0:
            raise ClassifierError("decision revision must be a non-negative integer")
        if self.decision is not None and self.decision.revision != self.decision_revision:
            raise ClassifierError("arbitration result revision does not match decision revision")

    def to_dict(self) -> dict[str, object]:
        """Mathematics: project result `R=(I,f,H,r,decision,replayed)` into a stable audit record."""

        return {
            "source": self.source,
            "channel": self.channel,
            "sequence": self.sequence,
            "logical_time": self.logical_time,
            "fingerprint": self.fingerprint,
            "decision_receipt": self.decision_receipt,
            "decision_revision": self.decision_revision,
            "action": None if self.decision is None else self.decision.action.value,
            "domain": None if self.decision is None else self.decision.domain.value,
            "replayed": self.replayed,
        }


@dataclass(frozen=True)
class HypervisorPolicy:
    """Risk thresholds separating autonomous action, review, and authority denial."""

    review_confidence: float = 0.35
    automatic_confidence: float = 0.70
    destructive_confidence: float = 0.90
    danger_review_probability: float = 0.70
    embedding_review_confidence: float = 0.90

    def __post_init__(self) -> None:
        """Mathematics: require thresholds in unit interval `[0,1]` and `review ≤ automatic ≤ destructive`."""

        values = (
            self.review_confidence,
            self.automatic_confidence,
            self.destructive_confidence,
            self.danger_review_probability,
            self.embedding_review_confidence,
        )
        if any(value < 0 or value > 1 for value in values) or not self.review_confidence <= self.automatic_confidence <= self.destructive_confidence:
            raise ClassifierError("invalid hypervisor thresholds")


class HypervisorError(RuntimeError):
    """Exception for an unhandled or denied hypervisor dispatch."""


class ClassifierHypervisor:
    """Classifier-shaped hypervisor: typed questions choose a domain, policy code chooses whether to act."""

    def __init__(
        self,
        classifier: ClassifierModel | None = None,
        journal: EventJournal | None = None,
        policy: HypervisorPolicy | None = None,
        intent_model: IntentPrototypeModel | None = None,
        virtual_capacity: int = 64,
    ) -> None:
        """Mathematics: compose `H=(classifier, intent_model, policy, journal, C)` without granting proposals authority."""

        if classifier is None:
            from .procedural_model import ProceduralDecisionModel

            classifier = ProceduralDecisionModel()
        self.classifier = classifier
        self.journal = journal or EventJournal()
        self.policy = policy or HypervisorPolicy()
        if not isinstance(virtual_capacity, int) or isinstance(virtual_capacity, bool) or virtual_capacity < 1:
            raise ClassifierError("virtual capacity must be a positive integer")
        self.intent_model = intent_model or IntentPrototypeModel.default()
        self.virtual_capacity = virtual_capacity
        self._revision = 0

    def decide(self, request: HypervisorRequest) -> HypervisorDecision:
        """Mathematics: evaluate exact questions, advisory proposal, and policy gates, then append receipt `H_n`."""

        questions: dict[str, Question] = {
            "domain": ChoiceQuestion.from_mapping(
                "Which MailCPU execution domain owns this operation?",
                {
                    HypervisorDomain.CPU.value: "register arithmetic, instruction scheduling, program execution",
                    HypervisorDomain.FILESYSTEM.value: "file, inode, descriptor, path, read, write, storage operation",
                    HypervisorDomain.NETWORK.value: "packet, TCP, HTTP, socket, route, network operation",
                    HypervisorDomain.SERVICE.value: "service start, stop, restart, supervisor, process lifecycle",
                    HypervisorDomain.REVIEW.value: "unknown, ambiguous, or human-review operation",
                },
            ),
            "danger": NoulQuestion(
                "Is this operation destructive or externally consequential?",
                true_criteria="delete kill terminate overwrite public network destructive",
                false_criteria="read inspect list observe classify",
            ),
        }
        state = request.state()
        batch = self.classifier.evaluate(state, questions)
        intent_prediction = self.intent_model.predict(state)
        virtual_cost = estimate_virtual_cost(state, self.virtual_capacity)
        domain_answer = batch.answers["domain"]
        danger_answer = batch.answers["danger"]
        if not isinstance(domain_answer, ChoiceAnswer) or not isinstance(danger_answer, NoulAnswer):
            raise HypervisorError("classifier returned incompatible answer types")
        domain = HypervisorDomain(domain_answer.choice)
        missing = request.required_rights - request.granted_rights
        if missing:
            action = HypervisorAction.DENY
        elif domain is HypervisorDomain.REVIEW or domain_answer.confidence < self.policy.review_confidence:
            action = HypervisorAction.REVIEW
        elif request.destructive and (
            domain_answer.confidence < self.policy.destructive_confidence
            or danger_answer.noul >= self.policy.danger_review_probability
        ):
            action = HypervisorAction.REVIEW
        elif domain_answer.confidence < self.policy.automatic_confidence:
            action = HypervisorAction.REVIEW
        else:
            action = HypervisorAction.ALLOW
        disagreement = (
            action is HypervisorAction.ALLOW
            and intent_prediction.confidence >= self.policy.embedding_review_confidence
            and intent_prediction.domain != domain.value
        )
        if disagreement:
            action = HypervisorAction.REVIEW
        payload = {
            "request": state,
            "action": action.value,
            "domain": domain.value,
            "confidence": domain_answer.confidence,
            "danger_probability": danger_answer.noul,
            "probabilities": domain_answer.probabilities,
            "model": batch.model,
            "revision": self._revision,
            "intent_embedding": intent_prediction.to_dict(),
            "embedding_disagreement": disagreement,
            "virtual_cost": virtual_cost.to_dict(),
        }
        receipt = self.journal.append("hypervisor.decision", payload).digest
        return HypervisorDecision(
            action,
            domain,
            domain_answer.confidence,
            danger_answer.noul,
            domain_answer.probabilities,
            batch.model,
            receipt,
            intent_prediction.domain,
            intent_prediction.confidence,
            intent_prediction.probabilities,
            intent_prediction.digest,
            virtual_cost,
            self._revision,
        )

    @staticmethod
    def _candidate_identity(candidate: ClassifierModel) -> str:
        """Mathematics: project candidate identity `m` to a stable model label without granting it authority."""

        return str(getattr(candidate, "model", candidate.__class__.__name__))

    @staticmethod
    def _witness_digest(witnesses: Sequence[RevisionWitness]) -> str:
        """Mathematics: calculate witness identity `d(W)=SHA256(JSON_sort([w.to_dict()]))` over the immutable semantic corpus."""

        return hashlib.sha256(_canonical_json_bytes([witness.to_dict() for witness in witnesses])).hexdigest()

    def admit_classifier_revision(
        self,
        candidate: ClassifierModel,
        witnesses: Sequence[HypervisorRevisionWitness],
    ) -> HypervisorRevisionResult:
        """Mathematics: commit `H.classifier:=m'` iff `∀w∈W:π(H_{m'}(w))=w.expected`, otherwise preserve `H` exactly."""

        if not callable(getattr(candidate, "evaluate", None)):
            raise ClassifierError("candidate classifier must implement evaluate")
        witness_tuple = tuple(witnesses)
        if not witness_tuple:
            raise ClassifierError("classifier revision requires at least one witness")
        if any(not isinstance(witness, HypervisorRevisionWitness) for witness in witness_tuple):
            raise ClassifierError("classifier revision witnesses have an invalid type")
        witness_digest = self._witness_digest(witness_tuple)
        candidate_model = self._candidate_identity(candidate)
        shadow = ClassifierHypervisor(
            classifier=candidate,
            journal=EventJournal(),
            policy=self.policy,
            intent_model=self.intent_model,
            virtual_capacity=self.virtual_capacity,
        )
        for index, witness in enumerate(witness_tuple):
            try:
                observed = _decision_semantics(shadow.decide(witness.request))
            except Exception as exc:
                self.journal.append(
                    "hypervisor.revision.refuse",
                    {
                        "candidate_model": candidate_model,
                        "witness_digest": witness_digest,
                        "mismatch_index": index,
                        "error": f"{type(exc).__name__}: {exc}",
                    },
                )
                return HypervisorRevisionResult(
                    False,
                    self._revision,
                    witness_digest,
                    candidate_model,
                    index,
                    f"{type(exc).__name__}: {exc}",
                )
            expected = dict(witness.expected)
            if observed != expected:
                self.journal.append(
                    "hypervisor.revision.refuse",
                    {
                        "candidate_model": candidate_model,
                        "witness_digest": witness_digest,
                        "mismatch_index": index,
                        "expected": expected,
                        "observed": observed,
                    },
                )
                return HypervisorRevisionResult(
                    False,
                    self._revision,
                    witness_digest,
                    candidate_model,
                    index,
                    "semantic witness mismatch",
                )
        self.classifier = candidate
        self._revision += 1
        self.journal.append(
            "hypervisor.revision.admit",
            {
                "candidate_model": candidate_model,
                "witness_digest": witness_digest,
                "witness_count": len(witness_tuple),
                "revision": self._revision,
            },
        )
        return HypervisorRevisionResult(True, self._revision, witness_digest, candidate_model)

    @staticmethod
    def _action_rank(action: HypervisorAction) -> int:
        """Mathematics: order actions by permissiveness `rank(DENY)=0 < rank(REVIEW)=1 < rank(ALLOW)=2`."""

        return {
            HypervisorAction.DENY: 0,
            HypervisorAction.REVIEW: 1,
            HypervisorAction.ALLOW: 2,
        }[action]

    def _intent_revision_refusal(
        self,
        candidate_model: str,
        witness_digest: str,
        mismatch_index: int,
        error: str,
    ) -> HypervisorRevisionResult:
        """Mathematics: record `¬G(M',W)` while preserving `(classifier,intent,revision)` exactly."""

        self.journal.append(
            "hypervisor.revision.refuse",
            {
                "target": "intent",
                "candidate_model": candidate_model,
                "witness_digest": witness_digest,
                "mismatch_index": mismatch_index,
                "error": error,
            },
        )
        return HypervisorRevisionResult(
            False,
            self._revision,
            witness_digest,
            candidate_model,
            mismatch_index,
            error,
            "intent",
        )

    def admit_intent_revision(
        self,
        candidate: IntentPrototypeModel,
        witnesses: Sequence[HypervisorIntentRevisionWitness],
    ) -> HypervisorRevisionResult:
        """Mathematics: commit `H.intent_model:=M'` iff held-out predictions match and `rank(a')≤rank(a)` for every witness."""

        if not isinstance(candidate, IntentPrototypeModel):
            raise ClassifierError("intent revision candidate must be an IntentPrototypeModel")
        witness_tuple = tuple(witnesses)
        if not witness_tuple or any(not isinstance(witness, HypervisorIntentRevisionWitness) for witness in witness_tuple):
            raise ClassifierError("intent revision requires typed witnesses")
        witness_digest = self._witness_digest(witness_tuple)
        candidate_model = candidate.model
        current_shadow = ClassifierHypervisor(
            classifier=self.classifier,
            journal=EventJournal(),
            policy=self.policy,
            intent_model=self.intent_model,
            virtual_capacity=self.virtual_capacity,
        )
        candidate_shadow = ClassifierHypervisor(
            classifier=self.classifier,
            journal=EventJournal(),
            policy=self.policy,
            intent_model=candidate,
            virtual_capacity=self.virtual_capacity,
        )
        for index, witness in enumerate(witness_tuple):
            try:
                observed_prediction = candidate.predict(witness.request.state()).to_dict()
                current_decision = current_shadow.decide(witness.request)
                candidate_decision = candidate_shadow.decide(witness.request)
            except Exception as exc:
                return self._intent_revision_refusal(
                    candidate_model,
                    witness_digest,
                    index,
                    f"{type(exc).__name__}: {exc}",
                )
            if observed_prediction != dict(witness.expected):
                return self._intent_revision_refusal(
                    candidate_model,
                    witness_digest,
                    index,
                    "intent witness mismatch",
                )
            if current_decision.action is not witness.baseline_action:
                return self._intent_revision_refusal(
                    candidate_model,
                    witness_digest,
                    index,
                    "intent witness baseline is stale",
                )
            if self._action_rank(candidate_decision.action) > self._action_rank(current_decision.action):
                return self._intent_revision_refusal(
                    candidate_model,
                    witness_digest,
                    index,
                    "intent candidate expands authority",
                )
        self.intent_model = candidate
        self._revision += 1
        self.journal.append(
            "hypervisor.revision.admit",
            {
                "target": "intent",
                "candidate_model": candidate_model,
                "witness_digest": witness_digest,
                "witness_count": len(witness_tuple),
                "revision": self._revision,
            },
        )
        return HypervisorRevisionResult(True, self._revision, witness_digest, candidate_model, target="intent")

    def admit_classifier_revision_proposal(
        self,
        proposal: HypervisorRevisionProposal,
    ) -> HypervisorRevisionResult:
        """Mathematics: reconstruct the typed candidate in `P` and apply its target-specific witnessed admission law."""

        if not isinstance(proposal, HypervisorRevisionProposal):
            raise ClassifierError("classifier revision proposal has an invalid type")
        if proposal.target == "intent":
            candidate = self._intent_from_snapshot(proposal.candidate_snapshot)
            return self.admit_intent_revision(candidate, proposal.witnesses)
        candidate = self._classifier_from_snapshot(proposal.candidate_snapshot)
        return self.admit_classifier_revision(candidate, proposal.witnesses)

    def dispatch(
        self,
        request: HypervisorRequest,
        handlers: Mapping[HypervisorDomain | str, Callable[[], Any]],
    ) -> tuple[HypervisorDecision, Any | None]:
        """Mathematics: execute the handler when `decision.action = ALLOW`; otherwise return the decision without execution."""

        decision = self.decide(request)
        if decision.action is not HypervisorAction.ALLOW:
            return decision, None
        handler = handlers.get(decision.domain) or handlers.get(decision.domain.value)
        if handler is None:
            raise HypervisorError(f"no handler for domain: {decision.domain.value}")
        return decision, handler()

    def snapshot(self) -> dict[str, object]:
        """Mathematics: serialize exact classifier `m`, advisory model `M`, policy `π`, capacity `C`, and revision `r`."""

        model_snapshot = getattr(self.classifier, "snapshot", None)
        model = model_snapshot() if callable(model_snapshot) else {
            "kind": "lexical",
            "model": getattr(self.classifier, "model", self.classifier.__class__.__name__),
        }
        return {
            "model": model,
            "policy": {
                "review_confidence": self.policy.review_confidence,
                "automatic_confidence": self.policy.automatic_confidence,
                "destructive_confidence": self.policy.destructive_confidence,
                "danger_review_probability": self.policy.danger_review_probability,
                "embedding_review_confidence": self.policy.embedding_review_confidence,
            },
            "intent_model": self.intent_model.snapshot(),
            "virtual_capacity": self.virtual_capacity,
            "revision": self._revision,
        }

    @staticmethod
    def _classifier_from_snapshot(payload: Mapping[str, Any]) -> ClassifierModel:
        """Mathematics: invert checkpoint model relation `kind ↦ f_kind` only for admitted deterministic model kinds."""

        if not isinstance(payload, Mapping):
            raise ClassifierError("classifier snapshot must be a mapping")
        if payload.get("kind") == "procedural":
            from .procedural_model import ProceduralDecisionModel

            return ProceduralDecisionModel.from_snapshot(payload)
        if payload.get("kind") == "lexical":
            return LexicalDecisionModel(str(payload.get("model", "mailcpu-lexical-e0")))
        raise ClassifierError("unsupported classifier snapshot kind")

    @staticmethod
    def _intent_from_snapshot(payload: Mapping[str, Any]) -> IntentPrototypeModel:
        """Mathematics: invert target `intent` only through the checkpointed `IntentPrototypeModel` constructor."""

        if not isinstance(payload, Mapping) or payload.get("kind") != "intent-prototype":
            raise ClassifierError("unsupported intent model snapshot kind")
        return IntentPrototypeModel.from_snapshot(payload)

    @classmethod
    def from_snapshot(cls, payload: Mapping[str, Any], journal: EventJournal) -> "ClassifierHypervisor":
        """Mathematics: reconstruct `H'=(f_m,M,π,journal,C)` from finite checkpoint data."""

        policy_payload = dict(payload.get("policy", {}))
        policy = HypervisorPolicy(
            review_confidence=float(policy_payload.get("review_confidence", 0.35)),
            automatic_confidence=float(policy_payload.get("automatic_confidence", 0.70)),
            destructive_confidence=float(policy_payload.get("destructive_confidence", 0.90)),
            danger_review_probability=float(policy_payload.get("danger_review_probability", 0.70)),
            embedding_review_confidence=float(policy_payload.get("embedding_review_confidence", 0.90)),
        )
        model_payload = payload.get("model", {})
        model = cls._classifier_from_snapshot(model_payload if isinstance(model_payload, Mapping) else {})
        intent_payload = payload.get("intent_model", {})
        if isinstance(intent_payload, Mapping) and intent_payload.get("kind") == "intent-prototype":
            intent_model = IntentPrototypeModel.from_snapshot(intent_payload)
        else:
            intent_model = IntentPrototypeModel.default()
        hypervisor = cls(model, journal, policy, intent_model, int(payload.get("virtual_capacity", 64)))
        hypervisor._revision = int(payload.get("revision", 0))
        if hypervisor._revision < 0:
            raise ClassifierError("hypervisor revision must be non-negative")
        return hypervisor


class HypervisorArbitrationLoop:
    """Bounded Receive–Stabilize–Inspect loop around the authority-preserving hypervisor."""

    def __init__(self, hypervisor: ClassifierHypervisor) -> None:
        """Mathematics: initialize replay ledger `L=∅` and cycle counter `k=0` over one policy authority `H`."""

        if not isinstance(hypervisor, ClassifierHypervisor):
            raise ClassifierError("arbitration loop requires a ClassifierHypervisor")
        self.hypervisor = hypervisor
        self._seen: dict[tuple[str, str, int], tuple[str, str, int]] = {}
        self._revision_seen: dict[tuple[str, str, int], tuple[str, HypervisorRevisionResult]] = {}
        self._cycle = 0

    @staticmethod
    def _fingerprint(event: HypervisorArbitrationEvent) -> str:
        """Mathematics: calculate payload identity `f(e)=SHA256(JSON_sort(e))` independently of journal position."""

        try:
            canonical = json.dumps(
                event.to_dict(),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            ).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise ClassifierError("arbitration event is outside the canonical JSON domain") from exc
        return hashlib.sha256(canonical).hexdigest()

    @staticmethod
    def _revision_fingerprint(proposal: HypervisorRevisionProposal) -> str:
        """Mathematics: calculate proposal identity `f(P)=SHA256(JSON_sort(P))` independently of journal position."""

        try:
            canonical = json.dumps(
                proposal.to_dict(),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            ).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise ClassifierError("revision proposal is outside the canonical JSON domain") from exc
        return hashlib.sha256(canonical).hexdigest()

    def arbitrate(self, event: HypervisorArbitrationEvent) -> HypervisorArbitrationResult:
        """Mathematics: apply `L[I]` once, return `(receipt,r_original)` on exact replay, and refuse `I↦f'` when `f'≠f`."""

        if not isinstance(event, HypervisorArbitrationEvent):
            raise ClassifierError("arbitration requires a HypervisorArbitrationEvent")
        identity = event.identity
        fingerprint = self._fingerprint(event)
        previous = self._seen.get(identity)
        if previous is not None:
            previous_fingerprint, decision_receipt, decision_revision = previous
            if previous_fingerprint != fingerprint:
                raise HypervisorError("conflicting arbitration retransmission")
            self.hypervisor.journal.append(
                "hypervisor.arbitration.replay",
                {
                    "source": event.source,
                    "channel": event.channel,
                    "sequence": event.sequence,
                    "logical_time": event.logical_time,
                    "fingerprint": fingerprint,
                    "decision_receipt": decision_receipt,
                    "decision_revision": decision_revision,
                },
            )
            return HypervisorArbitrationResult(
                event.source,
                event.channel,
                event.sequence,
                event.logical_time,
                fingerprint,
                decision_receipt,
                None,
                True,
                decision_revision,
            )

        decision = self.hypervisor.decide(event.request)
        self._cycle += 1
        self._seen[identity] = (fingerprint, decision.receipt, decision.revision)
        self.hypervisor.journal.append(
            "hypervisor.arbitration.accept",
            {
                "source": event.source,
                "channel": event.channel,
                "sequence": event.sequence,
                "logical_time": event.logical_time,
                "fingerprint": fingerprint,
                "decision_receipt": decision.receipt,
                "decision_revision": decision.revision,
                "cycle": self._cycle,
            },
        )
        return HypervisorArbitrationResult(
            event.source,
            event.channel,
            event.sequence,
            event.logical_time,
            fingerprint,
            decision.receipt,
            decision,
            False,
            decision.revision,
        )

    def propose_revision(self, proposal: HypervisorRevisionProposal) -> HypervisorRevisionArbitrationResult:
        """Mathematics: apply revision ledger `L_r[I]` once, replay exact `P`, and refuse `I↦f(P')` conflicts."""

        if not isinstance(proposal, HypervisorRevisionProposal):
            raise ClassifierError("revision proposal arbitration requires a HypervisorRevisionProposal")
        identity = proposal.identity
        fingerprint = self._revision_fingerprint(proposal)
        previous = self._revision_seen.get(identity)
        if previous is not None:
            previous_fingerprint, admission = previous
            if previous_fingerprint != fingerprint:
                self.hypervisor.journal.append(
                    "hypervisor.revision.proposal.conflict",
                    {
                        "source": proposal.source,
                        "channel": proposal.channel,
                        "sequence": proposal.sequence,
                        "logical_time": proposal.logical_time,
                        "fingerprint": fingerprint,
                        "previous_fingerprint": previous_fingerprint,
                    },
                )
                raise HypervisorError("conflicting revision proposal")
            self.hypervisor.journal.append(
                "hypervisor.revision.proposal.replay",
                {
                    "source": proposal.source,
                    "channel": proposal.channel,
                    "sequence": proposal.sequence,
                    "logical_time": proposal.logical_time,
                    "fingerprint": fingerprint,
                    "revision": admission.revision,
                    "accepted": admission.accepted,
                },
            )
            return HypervisorRevisionArbitrationResult(
                proposal.source,
                proposal.channel,
                proposal.sequence,
                proposal.logical_time,
                fingerprint,
                admission,
                True,
                proposal.target,
            )

        try:
            admission = self.hypervisor.admit_classifier_revision_proposal(proposal)
        except Exception as exc:
            candidate_model = str(
                proposal.candidate_snapshot.get(
                    "model",
                    proposal.candidate_snapshot.get("kind", "unknown"),
                )
            )
            admission = HypervisorRevisionResult(
                False,
                int(self.hypervisor.snapshot()["revision"]),
                ClassifierHypervisor._witness_digest(proposal.witnesses),
                candidate_model,
                target=proposal.target,
                error=f"{type(exc).__name__}: {exc}",
            )
            self.hypervisor.journal.append(
                "hypervisor.revision.proposal.refuse",
                {
                    "source": proposal.source,
                    "channel": proposal.channel,
                    "sequence": proposal.sequence,
                    "logical_time": proposal.logical_time,
                    "fingerprint": fingerprint,
                    "error": admission.error,
                },
            )
        self._revision_seen[identity] = (fingerprint, admission)
        self.hypervisor.journal.append(
            "hypervisor.revision.proposal.result",
            {
                "source": proposal.source,
                "channel": proposal.channel,
                "sequence": proposal.sequence,
                "logical_time": proposal.logical_time,
                "fingerprint": fingerprint,
                "revision": admission.revision,
                "accepted": admission.accepted,
            },
        )
        return HypervisorRevisionArbitrationResult(
            proposal.source,
            proposal.channel,
            proposal.sequence,
            proposal.logical_time,
            fingerprint,
            admission,
            False,
            proposal.target,
        )

    def snapshot(self) -> dict[str, object]:
        """Mathematics: serialize decision ledger `L` and revision ledger `L_r` with cycle count `k` for exact duplicate recovery."""

        return {
            "version": 1,
            "cycle": self._cycle,
            "seen": [
                {
                    "source": source,
                    "channel": channel,
                    "sequence": sequence,
                    "fingerprint": fingerprint,
                    "decision_receipt": decision_receipt,
                    "decision_revision": decision_revision,
                }
                for (source, channel, sequence), (fingerprint, decision_receipt, decision_revision) in sorted(self._seen.items())
            ],
            "revision_proposals": [
                {
                    "source": source,
                    "channel": channel,
                    "sequence": sequence,
                    "logical_time": 0,
                    "fingerprint": fingerprint,
                    "admission": admission.to_dict(),
                    "target": admission.target,
                }
                for (source, channel, sequence), (fingerprint, admission) in sorted(self._revision_seen.items())
            ],
        }

    @classmethod
    def from_snapshot(
        cls,
        hypervisor: ClassifierHypervisor,
        payload: Mapping[str, Any],
    ) -> "HypervisorArbitrationLoop":
        """Mathematics: reconstruct `L` only when identities are unique, receipts are hashes, revisions are `ℕ₀`, and `k=|L|`."""

        if int(payload.get("version", 1)) != 1:
            raise ClassifierError("unsupported hypervisor arbitration snapshot")
        loop = cls(hypervisor)
        cycle = int(payload.get("cycle", 0))
        if cycle < 0:
            raise ClassifierError("arbitration cycle must be non-negative")
        for raw in payload.get("seen", ()):
            source = str(raw["source"])
            channel = str(raw["channel"])
            sequence = int(raw["sequence"])
            identity = (source, channel, sequence)
            if identity in loop._seen:
                raise ClassifierError("duplicate arbitration identity in snapshot")
            if not source or not channel or sequence <= 0:
                raise ClassifierError("invalid arbitration identity in snapshot")
            fingerprint = str(raw["fingerprint"])
            decision_receipt = str(raw["decision_receipt"])
            decision_revision = int(raw.get("decision_revision", 0))
            HypervisorArbitrationResult(
                source,
                channel,
                sequence,
                0,
                fingerprint,
                decision_receipt,
                None,
                True,
                decision_revision,
            )
            loop._seen[identity] = (fingerprint, decision_receipt, decision_revision)
        for raw in payload.get("revision_proposals", ()):
            source = str(raw["source"])
            channel = str(raw["channel"])
            sequence = int(raw["sequence"])
            identity = (source, channel, sequence)
            if identity in loop._revision_seen:
                raise ClassifierError("duplicate revision proposal identity in snapshot")
            if not source or not channel or sequence <= 0:
                raise ClassifierError("invalid revision proposal identity in snapshot")
            fingerprint = str(raw["fingerprint"])
            admission_payload = raw.get("admission")
            if not isinstance(admission_payload, Mapping):
                raise ClassifierError("revision proposal admission snapshot must be a mapping")
            admission = HypervisorRevisionResult(
                bool(admission_payload.get("accepted", False)),
                int(admission_payload.get("revision", 0)),
                str(admission_payload["witness_digest"]),
                str(admission_payload["candidate_model"]),
                None if admission_payload.get("mismatch_index") is None else int(admission_payload["mismatch_index"]),
                None if admission_payload.get("error") is None else str(admission_payload["error"]),
                str(admission_payload.get("target", raw.get("target", "classifier"))),
            )
            HypervisorRevisionArbitrationResult(
                source,
                channel,
                sequence,
                int(raw.get("logical_time", 0)),
                fingerprint,
                admission,
                False,
                admission.target,
            )
            loop._revision_seen[identity] = (fingerprint, admission)
        if cycle != len(loop._seen):
            raise ClassifierError("arbitration cycle does not equal admitted event count")
        loop._cycle = cycle
        return loop


def canonical_tokens(value: Any) -> set[str]:
    """Mathematics: tokenize canonical state `x` into the finite lexical set `T(x) = {t : t matches [a-z0-9_]+ in lower(canonical(x))}`."""

    text = json.dumps(value, sort_keys=True, default=str).lower()
    return set(re.findall(r"[a-z0-9_]+", text))


def _evidence_score(state_tokens: set[str], description: str) -> float:
    """Mathematics: score evidence as `1 + 8|T(state)∩T(description)|/max(1,|T(description)|)`."""

    criterion_tokens = canonical_tokens(description)
    overlap = len(state_tokens & criterion_tokens)
    return 1.0 + 8.0 * overlap / max(1, len(criterion_tokens))


def softmax(scores: Mapping[str, float], error: type[Exception], *, scale: float = 1.0) -> dict[str, float]:
    """Mathematics: normalize `p_i = e^{s_i/k − max(s)/k} / Σ_j e^{s_j/k − max(s)/k}` for `k > 0`, validating `Σ_i p_i = 1 ± 10^-9`."""

    if not scores:
        raise error("cannot normalize empty score map")
    scaled = {key: value / scale for key, value in scores.items()}
    maximum = max(scaled.values())
    exponentials = {key: math.exp(value - maximum) for key, value in scaled.items()}
    denominator = sum(exponentials.values())
    probabilities = {key: exponentials[key] / denominator for key in sorted(exponentials)}
    _validate_distribution(probabilities.values())
    return probabilities


def _validate_distribution(values: Any) -> None:
    """Mathematics: require finite nonnegative probabilities satisfying `Σ_i p_i = 1 ± 10^-9`."""

    numbers = tuple(float(value) for value in values)
    if not numbers or any(not math.isfinite(value) or value < 0 for value in numbers) or abs(sum(numbers) - 1.0) > 1e-9:
        raise ClassifierError("invalid probability distribution")
