"""USM-001: a trained model uses E-CPU as an observation/ground operating service.

This is a deliberately small, real inference-and-execution loop, not an LLM,
a new trusted certifier, or a new hypervisor. The trained controller spends
observation/ground-construction work; receiver-owned StructuralMemoryRegistry
alone determines whether a proposed Ground can be admitted and read.

Run: python -m examples.model_ground_os
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from mailcpu.law_certifier import recover_law
from mailcpu.neural_lifter import extract_lifter_features
from mailcpu.structural_memory import StructuralMemoryError, StructuralMemoryRegistry

FEATURE_NAMES = (
    "entropy", "distinct_ratio", "is_binary", "diff_constant_ratio",
    "gcd_diff_unit", "det_gcd_nonzero", "max_bit_length", "has_cycle",
)
MODEL_SCHEMA = "mailcpu.use-system.model-ground-policy.v1"
EPISODE_SCHEMA = "mailcpu.use-system.ground-operation.v1"


def _digest(value: Any) -> str:
    """Hash an exact canonical JSON projection, not a host-specific object ID."""
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()


def _features(window: Sequence[int]) -> tuple[float, ...]:
    """Use the existing E-CPU neural-lifter observation features."""
    if len(window) < 4 or any(type(value) is not int for value in window):
        raise ValueError("a training/operating window needs at least four integer observations")
    observed = extract_lifter_features(window)
    return tuple(float(observed[name]) for name in FEATURE_NAMES)


def _sigmoid(value: float) -> float:
    """Stable binary logistic inference."""
    if value >= 0:
        return 1.0 / (1.0 + math.exp(-value))
    e = math.exp(value)
    return e / (1.0 + e)


@dataclass
class GroundPolicyModel:
    """Eight-feature trainable binary model; it is never an execution authority."""

    weights: tuple[float, ...] = (0.0,) * len(FEATURE_NAMES)
    bias: float = 0.0

    def __post_init__(self) -> None:
        if len(self.weights) != len(FEATURE_NAMES) or any(
            type(w) not in (int, float) or not math.isfinite(w) for w in self.weights
        ):
            raise ValueError("model weights must be finite and match the feature ABI")
        if type(self.bias) not in (int, float) or not math.isfinite(self.bias):
            raise ValueError("model bias must be finite")

    def predict(self, window: Sequence[int]) -> float:
        """Predict whether requesting expensive Ground construction is worthwhile."""
        x = _features(window)
        return _sigmoid(sum(w * v for w, v in zip(self.weights, x)) + self.bias)

    def fit(
        self,
        cases: Iterable[tuple[Sequence[int], bool]],
        *,
        epochs: int = 120,
        learning_rate: float = 0.35,
    ) -> dict[str, Any]:
        """Train with verified E-CPU labels; no optimizer or tensor framework needed."""
        if type(epochs) is not int or not 1 <= epochs <= 2000:
            raise ValueError("invalid epoch budget")
        if type(learning_rate) not in (int, float) or not 0 < learning_rate <= 1:
            raise ValueError("invalid learning rate")
        examples = [(_features(window), label) for window, label in cases]
        if not examples or any(type(label) is not bool for _, label in examples):
            raise ValueError("training requires exact boolean evidence labels")
        weights = list(self.weights)
        bias = float(self.bias)
        for _ in range(epochs):
            for features, accepted in examples:
                score = sum(w * x for w, x in zip(weights, features)) + bias
                error = float(accepted) - _sigmoid(score)
                weights = [w + learning_rate * (error * x - 0.0001 * w)
                           for w, x in zip(weights, features)]
                bias += learning_rate * error
        self.weights, self.bias = tuple(weights), bias
        scores = [_sigmoid(sum(w * x for w, x in zip(weights, features)) + bias)
                  for features, _ in examples]
        accuracy = sum((score >= 0.5) == label
                       for score, (_, label) in zip(scores, examples)) / len(examples)
        return {"examples": len(examples), "epochs": epochs,
                "training_accuracy": accuracy, "model_digest": self.digest}

    def snapshot(self) -> dict[str, Any]:
        """Portable model artifact; no runtime object or host identity is required."""
        data = {"schema": MODEL_SCHEMA, "features": list(FEATURE_NAMES),
                "weights": list(self.weights), "bias": self.bias}
        return {**data, "digest": _digest(data)}

    @property
    def digest(self) -> str:
        return self.snapshot()["digest"]

    @classmethod
    def from_snapshot(cls, artifact: Mapping[str, Any]) -> GroundPolicyModel:
        """Reject mutated artifacts before allowing inference."""
        expected = {"schema", "features", "weights", "bias", "digest"}
        if not isinstance(artifact, Mapping) or set(artifact) != expected:
            raise ValueError("invalid model artifact fields")
        if artifact["schema"] != MODEL_SCHEMA or artifact["features"] != list(FEATURE_NAMES):
            raise ValueError("model feature/schema mismatch")
        payload = {key: artifact[key] for key in expected - {"digest"}}
        if artifact["digest"] != _digest(payload):
            raise ValueError("model artifact digest mismatch")
        if type(artifact["weights"]) is not list:
            raise ValueError("model weights must be a list")
        return cls(tuple(artifact["weights"]), artifact["bias"])


def evidence_label(samples: Sequence[int], *, training_count: int = 24) -> bool:
    """Teacher label comes from E-CPU law recovery, never from model predictions."""
    if not 4 <= training_count < len(samples):
        raise ValueError("invalid witness split")
    law = recover_law(samples[:training_count], samples[training_count:])
    return law.verdict == "GROUND" and law.family in {"int", "lcg", "gf2", "fgraph"}


def operate_ground(
    model: GroundPolicyModel,
    registry: StructuralMemoryRegistry,
    stream_id: str,
    samples: Sequence[int],
    *,
    coordinate: int,
    training_count: int = 24,
    context: Mapping[str, Any] | None = None,
    threshold: float = 0.5,
    force: bool = False,
) -> dict[str, Any]:
    """Use model inference to request actual E-CPU Ground admission and navigation.

    Caller 'force' permits explicit service requests despite a model false
    negative. It does not bypass the registry's witness or admission policy.
    """
    if not isinstance(stream_id, str) or not stream_id:
        raise ValueError("stream_id is required")
    if type(coordinate) is not int or coordinate < 0:
        raise ValueError("coordinate must be a non-negative integer")
    if not 4 <= training_count < len(samples):
        raise ValueError("invalid observation split")
    if type(threshold) not in (int, float) or not 0 < threshold < 1:
        raise ValueError("invalid model threshold")
    if type(force) is not bool:
        raise ValueError("force must be boolean")
    probability = model.predict(samples[:training_count])
    result: dict[str, Any] = {
        "schema": EPISODE_SCHEMA,
        "stream_id": stream_id,
        "model_digest": model.digest,
        "observation_digest": _digest(list(samples)),
        "training_count": training_count,
        "requested_coordinate": coordinate,
        "ground_probability": round(probability, 9),
        "model_recommended": probability >= threshold,
        "caller_override": force,
    }
    if probability < threshold and not force:
        result["status"] = "deferred_by_model"
    else:
        try:
            proposal = registry.propose_trace(
                stream_id,
                samples[:training_count],
                samples[training_count:],
                domain="model-operated-observed-orbit",
                context=context,
            )
            version = registry.admit(proposal.proposal_id, expected_revision=0)
            read = registry.read(stream_id, coordinate, context=context)
            result.update(
                status="ground_read",
                ground_digest=version.spec.digest,
                certificate_digest=version.certificate.digest,
                read_receipt_id=read.receipt_id,
                value=read.value,
                verification_class=read.verification_class.value,
            )
        except StructuralMemoryError as exc:
            result.update(status="refused_by_ecpu", refusal=type(exc).__name__)
    return {**result, "episode_digest": _digest(result)}


def sample_stream(kind: str, seed: int, *, count: int = 40) -> tuple[int, ...]:
    """Reproducible workload data; use independent seeds across train/evaluation."""
    if type(seed) is not int or seed < 0 or type(count) is not int or count < 32:
        raise ValueError("invalid stream parameters")
    if kind == "affine":
        return tuple((7 + seed + 5 * t) % 97 for t in range(count))
    if kind == "nonlinear":
        return tuple(((t + seed) ** 3 + 17 * t * t + 3) % 97 for t in range(count))
    raise ValueError("unknown stream kind")


def train_example_model() -> tuple[GroundPolicyModel, dict[str, Any]]:
    """Train on E-CPU's actual accept/refuse decisions, with distinct eval seeds."""
    cases = []
    labels = {"ground": 0, "not_ground": 0}
    for seed in range(12):
        for kind in ("affine", "nonlinear"):
            stream = sample_stream(kind, seed)
            accepted = evidence_label(stream)
            labels["ground" if accepted else "not_ground"] += 1
            cases.append((stream[:24], accepted))
    model = GroundPolicyModel()
    report = model.fit(cases)
    return model, {**report, "teacher_label_counts": labels}


def run_demo() -> dict[str, Any]:
    """Operate an actual receiver-owned Ground registry, including long navigation."""
    model, training = train_example_model()
    restored = GroundPolicyModel.from_snapshot(model.snapshot())
    context = {"tenant": "use-system", "purpose": "observed-computation"}
    # Host policy is supplied independently: the model cannot grant this right.
    registry = StructuralMemoryRegistry(
        admission_policy=lambda proposal: (
            proposal.spec.domain == "model-operated-observed-orbit"
            and proposal.spec.context == context
        )
    )
    coordinate = 10**12 + 137
    episodes = [
        operate_ground(restored, registry, "affine-evaluation",
                       sample_stream("affine", 201), coordinate=coordinate,
                       context=context, force=True),
        operate_ground(restored, registry, "nonlinear-evaluation",
                       sample_stream("nonlinear", 207), coordinate=coordinate,
                       context=context, force=True),
    ]
    expected = (7 + 201 + 5 * coordinate) % 97
    comparison = {
        "affine_source_oracle_match": (
            episodes[0]["status"] == "ground_read"
            and episodes[0]["value"] == expected
        ),
        "nonlinear_admitted": episodes[1]["status"] == "ground_read",
    }
    # Independent evaluation: these requests are NOT forced. The trained
    # model actually decides which E-CPU Ground requests are performed.
    # Reference labels are evaluated afterward and never fed to the controller.
    evaluation = []
    for seed in range(301, 305):
        for kind in ("affine", "nonlinear"):
            stream = sample_stream(kind, seed)
            executed = operate_ground(
                restored, registry, f"eval-{kind}-{seed}", stream,
                coordinate=coordinate, context=context,
            )
            evaluation.append({
                "kind": kind,
                "stream_id": executed["stream_id"],
                "evidence_eligible": evidence_label(stream),
                "model_recommended": executed["model_recommended"],
                "ground_probability": executed["ground_probability"],
                "status": executed["status"],
                "episode_digest": executed["episode_digest"],
            })
    correct = sum(item["evidence_eligible"] == item["model_recommended"]
                  for item in evaluation)
    evaluation_summary = {
        "cases": len(evaluation),
        "selection_accuracy": correct / len(evaluation),
        "ground_reads": sum(x["status"] == "ground_read" for x in evaluation),
        "deferrals": sum(x["status"] == "deferred_by_model" for x in evaluation),
        "ecpu_refusals": sum(x["status"] == "refused_by_ecpu" for x in evaluation),
        "model_false_negatives": sum(
            x["evidence_eligible"] and not x["model_recommended"] for x in evaluation
        ),
    }
    report = {"schema": "mailcpu.use-system.demo.v1", "training": training,
              "model": restored.snapshot(), "episodes": episodes,
              "external_comparison": comparison,
              "unforced_evaluation": evaluation,
              "evaluation_summary": evaluation_summary}
    return {**report, "report_digest": _digest(report)}


if __name__ == "__main__":
    print(json.dumps(run_demo(), sort_keys=True, indent=2))
