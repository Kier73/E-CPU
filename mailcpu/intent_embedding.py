r"""Deterministic structural intent embeddings and virtual-time accounting.

The module makes the Hypervisor's request boundary explicit without importing a
neural runtime.  A request is represented by typed paths, values, and sequence
positions, then projected into a signed hashed vector.  Prototype similarity is
an advisory routing signal only; the classifier, capabilities, and policy remain
the authority boundary.

Mathematics:
For structural token multiset $T(x)$ and embedding dimension $D$,
\[
 v_b(x)=\sum_{t\in T(x):h(t)\bmod D=b}\operatorname{sign}(h(t)),
 \qquad \phi(x)=\frac{v(x)}{\lVert v(x)\rVert_2}.
\]
For label prototype $d$ built from examples $X_d$,
\[
 \mu_d=\frac{\sum_{x\in X_d}\phi(x)}{\left\lVert\sum_{x\in X_d}\phi(x)\right\rVert_2},
 \quad s_d=\mu_d\cdot\phi(x),
 \quad p_d=\frac{e^{s_d/\theta}}{\sum_j e^{s_j/\theta}}.
\]
Virtual time is the system's declared energy-to-time translation for active
representation and communication:
\[
 E_v=\max\left(1,8|J(x)|+8|T(x)|+\lceil16\tau_{chem}(J(x))\rceil+1\right),
 \qquad \tau_v=\left\lceil\frac{E_v}{C}\right\rceil,
\]
where $J(x)$ is canonical JSON and $C$ is the declared virtual capacity of the
current processing path.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .chemical_time import compute_chemical_difficulty
from .evidence import EvidenceTier, with_evidence_tier


class IntentEmbeddingError(ValueError):
    """A structural request cannot be represented within the declared finite bounds."""


_WORD_PATTERN = re.compile(r"[a-z0-9_]+")


def _canonical_json(value: Any) -> str:
    """Mathematics: serialize JSON-domain value `x` as the unique ordered string `J(x)` or refuse it."""

    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as error:
        raise IntentEmbeddingError(f"value is outside the deterministic JSON domain: {error}") from error


def _path_text(path: tuple[str, ...]) -> str:
    """Mathematics: map path tuple `p=(p_1,...,p_n)` to the canonical ordered label `$.p_1...p_n`."""

    return "$" if not path else "$." + ".".join(path)


def _append_token(tokens: list[str], token: str, maximum: int) -> None:
    """Mathematics: maintain the finite invariant `0 ≤ |tokens| < maximum`, refusing overflow instead of truncating."""

    if len(tokens) >= maximum:
        raise IntentEmbeddingError(f"structural token budget exceeded: {maximum}")
    tokens.append(token)


def _string_tokens(value: str, path: tuple[str, ...], tokens: list[str], maximum: int) -> None:
    """Mathematics: emit path/type/value features `F(s,p)` while preserving lexical terms `W(s)`."""

    location = _path_text(path)
    lowered = value.lower()
    _append_token(tokens, f"type:{location}:string", maximum)
    _append_token(tokens, f"length:{location}:{len(value)}", maximum)
    words = _WORD_PATTERN.findall(lowered)
    for word in words:
        _append_token(tokens, f"value:{location}:{word}", maximum)
        _append_token(tokens, f"lex:{word}", maximum)
    if not words:
        _append_token(tokens, f"empty:{location}", maximum)


def _walk_structural(value: Any, path: tuple[str, ...], tokens: list[str], maximum: int, depth: int) -> None:
    """Mathematics: recursively emit typed tree features `F(x,p)=F(type,p)∪⋃F(child,p·i)` with bounded depth."""

    if depth > 32:
        raise IntentEmbeddingError("structural nesting exceeds depth 32")
    location = _path_text(path)
    _append_token(tokens, f"path:{location}", maximum)
    if isinstance(value, Mapping):
        _append_token(tokens, f"type:{location}:mapping", maximum)
        keys = sorted((str(key), key) for key in value)
        _append_token(tokens, f"length:{location}:{len(keys)}", maximum)
        for key_text, key in keys:
            child_path = path + (f"field[{key_text}]",)
            _append_token(tokens, f"field:{location}:{key_text}", maximum)
            _walk_structural(value[key], child_path, tokens, maximum, depth + 1)
        return
    if isinstance(value, (list, tuple)):
        _append_token(tokens, f"type:{location}:sequence", maximum)
        _append_token(tokens, f"length:{location}:{len(value)}", maximum)
        for index, child in enumerate(value):
            _walk_structural(child, path + (f"index[{index}]",), tokens, maximum, depth + 1)
        return
    if isinstance(value, (set, frozenset)):
        ordered = sorted(value, key=lambda item: _canonical_json(item))
        _append_token(tokens, f"type:{location}:set", maximum)
        _append_token(tokens, f"length:{location}:{len(ordered)}", maximum)
        for index, child in enumerate(ordered):
            _walk_structural(child, path + (f"member[{index}]",), tokens, maximum, depth + 1)
        return
    if isinstance(value, str):
        _string_tokens(value, path, tokens, maximum)
        return
    if value is None:
        _append_token(tokens, f"type:{location}:null", maximum)
        return
    if isinstance(value, bool):
        _append_token(tokens, f"type:{location}:boolean", maximum)
        _append_token(tokens, f"value:{location}:{str(value).lower()}", maximum)
        return
    if isinstance(value, int) and not isinstance(value, bool):
        _append_token(tokens, f"type:{location}:integer", maximum)
        _append_token(tokens, f"value:{location}:{value}", maximum)
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise IntentEmbeddingError("non-finite float cannot be embedded")
        _append_token(tokens, f"type:{location}:real", maximum)
        _append_token(tokens, f"value:{location}:{value.hex()}", maximum)
        return
    raise IntentEmbeddingError(f"unsupported structural value type: {type(value).__name__}")


def structural_tokens(value: Any, *, max_tokens: int = 4096) -> tuple[str, ...]:
    """Mathematics: calculate ordered structural feature sequence `T(x)` without silently losing information."""

    if not isinstance(max_tokens, int) or isinstance(max_tokens, bool) or max_tokens < 16 or max_tokens > 1_000_000:
        raise IntentEmbeddingError("max_tokens must be an integer in [16, 1000000]")
    _canonical_json(value)
    tokens: list[str] = []
    _walk_structural(value, (), tokens, max_tokens, 0)
    return tuple(tokens)


def _normalize(vector: Sequence[float]) -> tuple[float, ...]:
    """Mathematics: return `u/||u||₂` and reject the zero vector required for cosine geometry."""

    norm = math.sqrt(sum(float(value) * float(value) for value in vector))
    if not math.isfinite(norm) or norm <= 0.0:
        raise IntentEmbeddingError("cannot normalize a zero or non-finite vector")
    return tuple(float(value) / norm for value in vector)


@dataclass(frozen=True)
class IntentEncoding:
    """A bounded structural embedding with a reproducible identity digest."""

    dimension: int
    digest: str
    token_count: int
    vector: tuple[float, ...]

    def __post_init__(self) -> None:
        """Mathematics: require `|vector|=D`, `||vector||₂=1`, and a 256-bit hexadecimal digest."""

        if self.dimension != len(self.vector) or self.dimension < 32:
            raise IntentEmbeddingError("embedding dimension does not match vector")
        if not self.digest or len(self.digest) != 64 or any(character not in "0123456789abcdef" for character in self.digest):
            raise IntentEmbeddingError("embedding digest must be lowercase SHA-256 hex")
        if self.token_count <= 0 or any(not math.isfinite(value) for value in self.vector):
            raise IntentEmbeddingError("embedding contains invalid finite data")
        if abs(sum(value * value for value in self.vector) - 1.0) > 1e-9:
            raise IntentEmbeddingError("embedding vector is not L2-normalized")

    def to_dict(self) -> dict[str, object]:
        """Mathematics: project encoding metadata `e=(D,d,|T|)` without expanding the private vector."""

        return {
            "dimension": self.dimension,
            "digest": self.digest,
            "token_count": self.token_count,
            "norm_l2": math.sqrt(sum(value * value for value in self.vector)),
        }


@dataclass(frozen=True)
class IntentEmbedding:
    """A deterministic signed-hash encoder for typed request structure."""

    dimension: int = 128
    namespace: str = "mailcpu-intent-e0"
    max_tokens: int = 4096

    def __post_init__(self) -> None:
        """Mathematics: require `D=2^k`, `32≤D≤4096`, nonempty namespace, and finite token budget."""

        if self.dimension < 32 or self.dimension > 4096 or self.dimension & (self.dimension - 1):
            raise IntentEmbeddingError("dimension must be a power of two in [32, 4096]")
        if not self.namespace:
            raise IntentEmbeddingError("embedding namespace cannot be empty")
        structural_tokens({}, max_tokens=self.max_tokens)

    def encode(self, value: Any) -> IntentEncoding:
        """Mathematics: calculate `φ(x)=v(x)/||v(x)||₂` with SHA-256 bucket/sign features and digest `d(x)`."""

        serialized = _canonical_json(value)
        tokens = structural_tokens(value, max_tokens=self.max_tokens)
        vector = [0.0] * self.dimension
        for token in tokens:
            digest = hashlib.sha256(f"{self.namespace}\0{token}".encode("utf-8")).digest()
            bucket = int.from_bytes(digest[:8], "big") % self.dimension
            vector[bucket] += 1.0 if digest[8] & 1 else -1.0
        normalized = _normalize(vector)
        identity = hashlib.sha256(
            f"{self.namespace}\0{self.dimension}\0{serialized}".encode("utf-8")
        ).hexdigest()
        return IntentEncoding(self.dimension, identity, len(tokens), normalized)

    def snapshot(self) -> dict[str, object]:
        """Mathematics: serialize finite encoder state `E=(D,namespace,max_tokens)` for exact regeneration."""

        return {"kind": "structural-hash", "dimension": self.dimension, "namespace": self.namespace, "max_tokens": self.max_tokens}

    @classmethod
    def from_snapshot(cls, payload: Mapping[str, Any]) -> "IntentEmbedding":
        """Mathematics: reconstruct encoder `E` from finite parameters and reapply its domain constraints."""

        return cls(
            dimension=int(payload.get("dimension", 128)),
            namespace=str(payload.get("namespace", "mailcpu-intent-e0")),
            max_tokens=int(payload.get("max_tokens", 4096)),
        )


@dataclass(frozen=True)
class IntentExample:
    """One labeled request state used to form an advisory domain prototype."""

    label: str
    state: Mapping[str, Any]

    def __post_init__(self) -> None:
        """Mathematics: require a nonempty label in finite prototype domain `D` and a mapping-valued state."""

        if not self.label or not isinstance(self.state, Mapping):
            raise IntentEmbeddingError("intent examples require a label and mapping state")


@dataclass(frozen=True)
class IntentPrediction:
    """Advisory prototype result; it is a proposal and never an authority decision."""

    domain: str
    confidence: float
    probabilities: dict[str, float]
    digest: str
    token_count: int
    model: str

    def __post_init__(self) -> None:
        """Mathematics: require `0≤confidence≤1`, `Σ_d p_d=1`, and prediction identity metadata."""

        if not self.domain or not 0.0 <= self.confidence <= 1.0:
            raise IntentEmbeddingError("invalid intent prediction confidence")
        if not self.probabilities or abs(sum(self.probabilities.values()) - 1.0) > 1e-9:
            raise IntentEmbeddingError("intent probabilities are not normalized")
        if self.token_count <= 0 or not self.model:
            raise IntentEmbeddingError("invalid intent prediction metadata")

    def to_dict(self) -> dict[str, object]:
        """Mathematics: project proposal `P=(d,p,confidence,digest)` with explicit E0 provenance."""

        return with_evidence_tier(
            {
                "domain": self.domain,
                "confidence": self.confidence,
                "probabilities": dict(sorted(self.probabilities.items())),
                "digest": self.digest,
                "token_count": self.token_count,
                "model": self.model,
            },
            EvidenceTier.E0,
        )


def _stable_softmax(scores: Mapping[str, float], temperature: float) -> dict[str, float]:
    """Mathematics: normalize prototype scores as `p_d=e^{s_d/θ−m}/Σ_j e^{s_j/θ−m}` for `θ>0`."""

    scaled = {label: float(score) / temperature for label, score in scores.items()}
    maximum = max(scaled.values())
    values = {label: math.exp(score - maximum) for label, score in scaled.items()}
    total = sum(values.values())
    probabilities = {label: values[label] / total for label in sorted(values)}
    if abs(sum(probabilities.values()) - 1.0) > 1e-9:
        raise IntentEmbeddingError("prototype probabilities are not normalized")
    return probabilities


class IntentPrototypeModel:
    """Checkpointable advisory classifier formed by normalized structural prototypes."""

    def __init__(self, encoder: IntentEmbedding, prototypes: Mapping[str, Sequence[float]], temperature: float = 0.25) -> None:
        """Mathematics: bind `M=(E,{μ_d},θ)` and validate every prototype in the same cosine space."""

        if not math.isfinite(temperature) or temperature <= 0.0 or not prototypes:
            raise IntentEmbeddingError("prototype model requires finite positive temperature and labels")
        self.encoder = encoder
        self.temperature = float(temperature)
        normalized: dict[str, tuple[float, ...]] = {}
        for label, vector in sorted(prototypes.items()):
            raw = tuple(float(value) for value in vector)
            norm = math.sqrt(sum(value * value for value in raw))
            if abs(norm - 1.0) <= 1e-12:
                normalized[str(label)] = raw
            else:
                normalized[str(label)] = _normalize(raw)
        self.prototypes = normalized
        if any(len(vector) != encoder.dimension for vector in self.prototypes.values()):
            raise IntentEmbeddingError("prototype dimension does not match encoder")
        self.model = "mailcpu-intent-prototype-e0"

    @classmethod
    def fit(
        cls,
        examples: Sequence[IntentExample],
        encoder: IntentEmbedding | None = None,
        temperature: float = 0.25,
    ) -> "IntentPrototypeModel":
        """Mathematics: fit `μ_d=normalize(Σ_{x∈X_d}φ(x))` independently for every observed label `d`."""

        if not examples:
            raise IntentEmbeddingError("cannot fit an empty prototype model")
        selected_encoder = encoder or IntentEmbedding()
        accumulators: dict[str, list[float]] = {}
        for example in examples:
            encoded = selected_encoder.encode(example.state)
            accumulator = accumulators.setdefault(example.label, [0.0] * selected_encoder.dimension)
            for index, value in enumerate(encoded.vector):
                accumulator[index] += value
        return cls(selected_encoder, accumulators, temperature)

    @staticmethod
    def default_examples() -> tuple[IntentExample, ...]:
        """Mathematics: provide a finite typed training set `X_d` spanning each Hypervisor execution domain."""

        return (
            IntentExample("cpu", {"operation": "execute instruction arithmetic register scheduler", "resource": "/cpu", "payload": {"program": "register"}}),
            IntentExample("cpu", {"operation": "run program instruction process", "resource": "/cpu/0", "payload": {"register": "accumulator"}}),
            IntentExample("filesystem", {"operation": "read filesystem file path descriptor storage", "resource": "/home/example", "payload": {"path": "/home/example", "size": 128}}),
            IntentExample("filesystem", {"operation": "write file inode descriptor storage", "resource": "/var/data", "payload": {"path": "/var/data", "bytes": "contents"}}),
            IntentExample("network", {"operation": "ingest network packet tcp http socket route", "resource": "/network/0", "payload": {"packet": "tcp http"}}),
            IntentExample("network", {"operation": "send network datagram socket connection", "resource": "/network/1", "payload": {"route": "remote"}}),
            IntentExample("process", {"operation": "spawn process executable child image launch", "resource": "/bin/example", "payload": {"path": "/bin/example", "argv": ["example"]}}),
            IntentExample("process", {"operation": "exec process child image replacement", "resource": "/bin/worker", "payload": {"path": "/bin/worker", "argv": ["worker"]}}),
            IntentExample("package", {"operation": "install package registry image digest deployment", "resource": "/package/example", "payload": {"digest": "verified-image"}}),
            IntentExample("package", {"operation": "stage package artifact registry verified", "resource": "/package/staged", "payload": {"artifact": "image"}}),
            IntentExample("service", {"operation": "start service supervisor process lifecycle", "resource": "/service/example", "payload": {"service": "example"}}),
            IntentExample("service", {"operation": "restart service process supervisor", "resource": "/service/demo", "payload": {"service": "demo"}}),
            IntentExample("service", {"operation": "resume seed commit after durable quorum decision before host publication", "resource": "/service/seed-commit/recovery", "payload": {"recovery_phase": "committed_unpublished", "ledger_slot": 1, "journal_operations": 0}}),
            IntentExample("service", {"operation": "replay durable client result after publication before request fifo acknowledgement", "resource": "/service/seed-commit/recovery", "payload": {"recovery_phase": "published_unacknowledged", "result_durable": True, "request_acknowledged": False}}),
            IntentExample("service", {"operation": "reconcile seed commit after lost client response and retry the same request identity", "resource": "/service/seed-commit/recovery", "payload": {"recovery_phase": "result_replay", "duplicate": True, "host_effect_count": 1}}),
            IntentExample("review", {"operation": "unknown ambiguous human review", "resource": "/unknown", "payload": {}}),
            IntentExample("review", {"operation": "unclassified uncertain manual approval", "resource": "/review", "payload": {"reason": "unclear"}}),
        )

    @classmethod
    def default(cls) -> "IntentPrototypeModel":
        """Mathematics: construct the deterministic finite model `M_0=fit(X_default,E_0,θ=.25)`."""

        return cls.fit(cls.default_examples())

    def predict(self, state: Mapping[str, Any]) -> IntentPrediction:
        """Mathematics: calculate `d*=argmax_d μ_d·φ(x)` and calibrated softmax proposal probabilities."""

        encoding = self.encoder.encode(state)
        scores = {
            label: sum(left * right for left, right in zip(vector, encoding.vector))
            for label, vector in self.prototypes.items()
        }
        probabilities = _stable_softmax(scores, self.temperature)
        domain = max(probabilities, key=lambda label: (probabilities[label], label))
        return IntentPrediction(domain, probabilities[domain], probabilities, encoding.digest, encoding.token_count, self.model)

    def snapshot(self) -> dict[str, object]:
        """Mathematics: serialize `M` as finite encoder, temperature, and normalized prototype vectors."""

        return {
            "kind": "intent-prototype",
            "encoder": self.encoder.snapshot(),
            "temperature": self.temperature,
            "prototypes": {label: list(vector) for label, vector in sorted(self.prototypes.items())},
        }

    @classmethod
    def from_snapshot(cls, payload: Mapping[str, Any]) -> "IntentPrototypeModel":
        """Mathematics: reconstruct `M` from checkpointed vectors and preserve its exact prediction function."""

        encoder_payload = payload.get("encoder", {})
        encoder = IntentEmbedding.from_snapshot(encoder_payload if isinstance(encoder_payload, Mapping) else {})
        prototypes_payload = payload.get("prototypes", {})
        if not isinstance(prototypes_payload, Mapping):
            raise IntentEmbeddingError("prototype snapshot must contain a mapping")
        prototypes = {str(label): tuple(float(value) for value in vector) for label, vector in prototypes_payload.items()}
        return cls(encoder, prototypes, float(payload.get("temperature", 0.25)))


@dataclass(frozen=True)
class VirtualCost:
    """E0 virtual energy and time receipt for representing one Hypervisor request."""

    semantic_bits: int
    token_count: int
    chemical_tau: float
    virtual_energy: int
    virtual_ticks: int
    capacity: int

    def __post_init__(self) -> None:
        """Mathematics: enforce `E_v≥1`, `C≥1`, `τ_v=ceil(E_v/C)`, and finite `τ_chem≥0`."""

        if self.semantic_bits < 0 or self.token_count <= 0 or self.virtual_energy < 1 or self.capacity < 1 or self.virtual_ticks < 1:
            raise IntentEmbeddingError("invalid virtual cost receipt")
        if not math.isfinite(self.chemical_tau) or self.chemical_tau < 0.0:
            raise IntentEmbeddingError("chemical time must be finite and non-negative")
        if self.virtual_ticks != math.ceil(self.virtual_energy / self.capacity):
            raise IntentEmbeddingError("virtual tick quotient is not ceiling-divided")

    def to_dict(self) -> dict[str, object]:
        """Mathematics: project cost `C=(8|J|,|T|,τ_chem,E_v,τ_v,C)` with E0 accounting provenance."""

        return with_evidence_tier(
            {
                "semantic_bits": self.semantic_bits,
                "token_count": self.token_count,
                "chemical_tau": self.chemical_tau,
                "virtual_energy": self.virtual_energy,
                "virtual_ticks": self.virtual_ticks,
                "capacity": self.capacity,
            },
            EvidenceTier.E0,
        )


def estimate_virtual_cost(value: Mapping[str, Any], capacity: int = 64) -> VirtualCost:
    """Mathematics: evaluate `E_v=max(1,8|J|+8|T|+ceil(16τ_chem)+1)` and `τ_v=ceil(E_v/C)`."""

    if not isinstance(value, Mapping) or not isinstance(capacity, int) or isinstance(capacity, bool) or capacity < 1:
        raise IntentEmbeddingError("virtual cost requires mapping state and positive integer capacity")
    serialized = _canonical_json(value).encode("utf-8")
    tokens = structural_tokens(value)
    chemical_tau = compute_chemical_difficulty(tuple(serialized))
    semantic_bits = 8 * len(serialized)
    virtual_energy = max(1, semantic_bits + 8 * len(tokens) + math.ceil(16.0 * chemical_tau) + 1)
    virtual_ticks = math.ceil(virtual_energy / capacity)
    return VirtualCost(semantic_bits, len(tokens), chemical_tau, virtual_energy, virtual_ticks, capacity)
