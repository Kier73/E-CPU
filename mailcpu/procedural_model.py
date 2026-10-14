"""Deterministic procedural decision model for the MailCPU classifier hypervisor."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass
from typing import Any, Mapping

from .classifier import (
    Answer,
    ChoiceAnswer,
    ChoiceQuestion,
    ClassifierError,
    DecisionBatch,
    NoulAnswer,
    NoulQuestion,
    Question,
    ScoreAnswer,
    ScoreQuestion,
    canonical_tokens,
    choice_confidence,
    score_confidence,
    softmax,
)
from .vl_procedural_primitives import feistel_seal


@dataclass(frozen=True)
class ProceduralModelSpec:
    """Finite specification for an addressable, stateless model parameter field."""

    model: str = "mailcpu-procedural-e0"
    seed: int = 0x4D41494C435055
    tau: int = 0xB16B00B5CAFE
    feature_buckets: int = 256
    temperature: float = 1.0

    def __post_init__(self) -> None:
        """Mathematics: require `seed,tau∈[0,2^64)`, `D=2^k`, and finite `temperature>0`."""

        if not self.model or not 0 <= self.seed < 2**64 or not 0 <= self.tau < 2**64:
            raise ClassifierError("invalid procedural model identity")
        if self.feature_buckets < 32 or self.feature_buckets > 65_536 or self.feature_buckets & (self.feature_buckets - 1):
            raise ClassifierError("feature_buckets must be a power of two in [32, 65536]")
        if not math.isfinite(self.temperature) or self.temperature <= 0:
            raise ClassifierError("temperature must be finite and positive")


class ProceduralWeightField:
    """A stateless function that regenerates bounded parameters from an address."""

    def __init__(self, spec: ProceduralModelSpec) -> None:
        """Mathematics: bind field `W(a)=g(seed, a)` without allocating a weight tensor."""

        self.spec = spec

    def _digest(self, namespace: str, address: str) -> bytes:
        """Mathematics: derive `h=SHA256(model || namespace || address || seal(seed,tau))` as a canonical parameter address."""

        logical_address = int.from_bytes(
            hashlib.sha256(json.dumps([namespace, address], separators=(",", ":")).encode("utf-8")).digest()[:8],
            "big",
        )
        permuted_address = feistel_seal(logical_address, self.spec.tau, self.spec.seed)
        payload = json.dumps(
            [self.spec.seed, self.spec.tau, self.spec.model, namespace, address, permuted_address],
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(payload).digest()

    def weight(self, namespace: str, address: str) -> float:
        """Mathematics: generate bounded positive weight `w(a)=0.75+0.5·U(h(a))∈[0.75,1.25)`."""

        raw = int.from_bytes(self._digest(namespace, address)[:8], "big")
        uniform = raw / float(2**64)
        return 0.75 + 0.5 * uniform

    def bucket(self, token: str) -> tuple[int, int]:
        """Mathematics: map token `t` to signed feature `(b,s)` with `b=h(t) mod D` and `s∈{-1,+1}`."""

        digest = self._digest("feature", token)
        bucket = int.from_bytes(digest[:8], "big") & (self.spec.feature_buckets - 1)
        sign = 1 if digest[8] & 1 else -1
        return bucket, sign

    def feature_vector(self, state: Mapping[str, Any]) -> tuple[float, ...]:
        """Mathematics: construct normalized hashed vector `x_b=v_b/||v||₂` from canonical state tokens."""

        vector = [0.0] * self.spec.feature_buckets
        for token in sorted(canonical_tokens(state)):
            bucket, sign = self.bucket(token)
            vector[bucket] += float(sign)
        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0:
            return tuple(vector)
        return tuple(value / norm for value in vector)

    def snapshot(self) -> dict[str, object]:
        """Mathematics: serialize finite field parameters `F=(model,seed,tau,D,temperature)` without materializing weights."""

        return asdict(self.spec)


class ProceduralDecisionModel:
    """A from-scratch deterministic classifier whose parameters are generated on demand."""

    def __init__(self, spec: ProceduralModelSpec | None = None) -> None:
        """Mathematics: bind classifier `f_F(state, question)` to one immutable procedural field `F`."""

        self.spec = spec or ProceduralModelSpec()
        self.field = ProceduralWeightField(self.spec)
        self.model = self.spec.model

    def _evidence_score(self, state_tokens: set[str], namespace: str, description: str) -> float:
        """Mathematics: compute `s(q)=Σ_{t∈T(state)∩T(description)} w(namespace,t)`, preserving zero evidence."""

        criterion_tokens = canonical_tokens(description)
        overlap = sorted(state_tokens & criterion_tokens)
        return sum(self.field.weight(namespace, token) for token in overlap)

    def evaluate(self, state: Mapping[str, Any], questions: Mapping[str, Question]) -> DecisionBatch:
        """Mathematics: evaluate each `q_i` independently as `A_i=f_F(state,q_i)` and return a typed batch."""

        state_tokens = canonical_tokens(state)
        answers: dict[str, Answer] = {}
        for question_id, question in sorted(questions.items()):
            if isinstance(question, ChoiceQuestion):
                scores = {
                    option: self._evidence_score(
                        state_tokens,
                        f"choice:{question_id}:{option}",
                        description,
                    )
                    for option, description in question.criteria
                }
                probabilities = softmax(scores, ClassifierError, scale=self.spec.temperature)
                answers[question_id] = ChoiceAnswer(
                    max(probabilities, key=lambda option: (probabilities[option], option)),
                    probabilities,
                    choice_confidence(probabilities),
                )
            elif isinstance(question, ScoreQuestion):
                scores = {
                    str(index): self._evidence_score(
                        state_tokens,
                        f"score:{question_id}:{index}",
                        level,
                    )
                    for index, level in enumerate(question.levels)
                }
                probabilities = tuple(softmax(scores, ClassifierError, scale=self.spec.temperature).values())
                answers[question_id] = ScoreAnswer(
                    sum(index * probability for index, probability in enumerate(probabilities)),
                    probabilities,
                    score_confidence(probabilities),
                )
            else:
                true_score = self._evidence_score(
                    state_tokens,
                    f"noul:{question_id}:true",
                    question.true_criteria or question.instructions,
                )
                false_score = self._evidence_score(
                    state_tokens,
                    f"noul:{question_id}:false",
                    question.false_criteria,
                )
                answers[question_id] = NoulAnswer(_sigmoid(true_score - false_score))
        return DecisionBatch(answers, self.model)

    def snapshot(self) -> dict[str, object]:
        """Mathematics: serialize model identity and generator parameters `F` for exact restoration."""

        return {"kind": "procedural", **self.field.snapshot()}

    @classmethod
    def from_snapshot(cls, payload: Mapping[str, Any]) -> "ProceduralDecisionModel":
        """Mathematics: reconstruct `f_F` from finite parameters and reject invalid generator domains."""

        return cls(
            ProceduralModelSpec(
                model=str(payload.get("model", "mailcpu-procedural-e0")),
                seed=int(payload.get("seed", 0x4D41494C435055)),
                tau=int(payload.get("tau", 0xB16B00B5CAFE)),
                feature_buckets=int(payload.get("feature_buckets", 256)),
                temperature=float(payload.get("temperature", 1.0)),
            )
        )


def _sigmoid(value: float) -> float:
    """Mathematics: evaluate logistic map `σ(z)=1/(1+e^{-z})` with sign-stable branches."""

    if value >= 0:
        exponential = math.exp(-value)
        return 1.0 / (1.0 + exponential)
    exponential = math.exp(value)
    return exponential / (1.0 + exponential)
