"""Typed, confidence-aware decision primitives and the MailCPU classifier hypervisor."""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Mapping, Protocol

from .evidence import EvidenceTier, with_evidence_tier
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

    def state(self) -> dict[str, object]:
        """Mathematics: form shared classifier state `x = (operation, resource, payload, authority, risk)`."""

        return {
            "operation": self.operation,
            "resource": self.resource,
            "payload": dict(self.payload),
            "required_rights": sorted(self.required_rights),
            "granted_rights": sorted(self.granted_rights),
            "destructive": self.destructive,
        }


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

    def to_dict(self) -> dict[str, object]:
        """Mathematics: project decision `d` into a stable control-plane record."""

        return with_evidence_tier(
            {
                "action": self.action.value,
                "domain": self.domain.value,
                "confidence": self.confidence,
                "danger_probability": self.danger_probability,
                "probabilities": dict(sorted(self.probabilities.items())),
                "model": self.model,
                "receipt": self.receipt,
            },
            EvidenceTier.E0,
        )


@dataclass(frozen=True)
class HypervisorPolicy:
    """Risk thresholds separating autonomous action, review, and authority denial."""

    review_confidence: float = 0.35
    automatic_confidence: float = 0.70
    destructive_confidence: float = 0.90
    danger_review_probability: float = 0.70

    def __post_init__(self) -> None:
        """Mathematics: require thresholds in unit interval `[0,1]` and `review ≤ automatic ≤ destructive`."""

        values = (self.review_confidence, self.automatic_confidence, self.destructive_confidence, self.danger_review_probability)
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
    ) -> None:
        """Mathematics: compose `H = (classifier, policy, journal)` without granting model output direct authority."""

        if classifier is None:
            from .procedural_model import ProceduralDecisionModel

            classifier = ProceduralDecisionModel()
        self.classifier = classifier
        self.journal = journal or EventJournal()
        self.policy = policy or HypervisorPolicy()

    def decide(self, request: HypervisorRequest) -> HypervisorDecision:
        """Mathematics: evaluate typed questions, apply authority/risk gates, and append receipt `H_n`."""

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
        batch = self.classifier.evaluate(request.state(), questions)
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
        payload = {
            "request": request.state(),
            "action": action.value,
            "domain": domain.value,
            "confidence": domain_answer.confidence,
            "danger_probability": danger_answer.noul,
            "probabilities": domain_answer.probabilities,
            "model": batch.model,
        }
        receipt = self.journal.append("hypervisor.decision", payload).digest
        return HypervisorDecision(action, domain, domain_answer.confidence, danger_answer.noul, domain_answer.probabilities, batch.model, receipt)

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
        """Mathematics: serialize policy `π` and generator/model identity `m` while journal state remains in the OS graph."""

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
            },
        }

    @classmethod
    def from_snapshot(cls, payload: Mapping[str, Any], journal: EventJournal) -> "ClassifierHypervisor":
        """Mathematics: reconstruct `H'=(f_m,π,journal)` from serialized model/generator identity and thresholds."""

        policy_payload = dict(payload.get("policy", {}))
        policy = HypervisorPolicy(
            review_confidence=float(policy_payload.get("review_confidence", 0.35)),
            automatic_confidence=float(policy_payload.get("automatic_confidence", 0.70)),
            destructive_confidence=float(policy_payload.get("destructive_confidence", 0.90)),
            danger_review_probability=float(policy_payload.get("danger_review_probability", 0.70)),
        )
        model_payload = payload.get("model", {})
        if isinstance(model_payload, Mapping) and model_payload.get("kind") == "procedural":
            from .procedural_model import ProceduralDecisionModel

            model = ProceduralDecisionModel.from_snapshot(model_payload)
        elif isinstance(model_payload, Mapping):
            model = LexicalDecisionModel(str(model_payload.get("model", "mailcpu-lexical-e0")))
        else:
            model = LexicalDecisionModel(str(model_payload or "mailcpu-lexical-e0"))
        return cls(model, journal, policy)


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
