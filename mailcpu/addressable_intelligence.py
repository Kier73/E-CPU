"""AIG-001: intention-specific executable Grounds from original hosted-model glances.

A host observes a previously acquired original pretrained BF16 slice Ground
(VL-64), compiles a requested pairwise Q-projection preference as an exact
dyadic direction, and realizes that behavior by certified partial-coordinate
navigation. The *model observation* is real pretrained checkpoint material;
the *new generated neural intelligence* is explicitly a bounded VLD model
constructed from observations, not an imitation of a full language model.

The original 5,760-byte capsule is supplied to the observer independently,
with its external pinned head. No network call or whole model load occurs.
A newly formed VL-I neural Ground can continue under existing E-CPU M3.
"""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
import base64
import hashlib
import json
import math
import re
import struct
from typing import Any, Mapping, Sequence

SCHEMA = "mailcpu.addressable-intelligence-ground.v1"
_RESULT_SCHEMA = "mailcpu.addressable-intelligence-observation.v1"
_HEX = re.compile(r"[0-9a-f]{64}\Z")


def _canonical(value: Any) -> bytes:
    """Canonical binary identity of one source-bound observation or new model."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def _hash(value: Any) -> str:
    """Identify an exact typed Ground without hiding its source structure."""
    return hashlib.sha256(_canonical(value)).hexdigest()


def _original_slice(source: Mapping[str, Any], *, expected_head: str):
    """Replay actual original VL-64 trained arithmetic, not a synthetic row fixture."""
    if (not isinstance(source, Mapping) or type(expected_head) is not str
        or _HEX.fullmatch(expected_head) is None
        or source.get("ground_digest") != expected_head):
        raise ValueError("original external model Ground identity unadmitted")
    from experiments.model_fabric.slice_ground import replay_slice_ground
    original = json.loads(_canonical(source))
    receipt = replay_slice_ground(original)
    if receipt["status"] != "VERIFIED_LOCAL_REPLAY_OF_PRETRAINED_TENSOR_SLICE":
        raise ValueError("original external pretrained Ground not numerically admitted")
    width = original["hidden_width"]
    nraw = base64.b64decode(original["norm_bf16_b64"], validate=True)
    qraw = base64.b64decode(original["q_bf16_b64"], validate=True)
    if len(nraw) != 2 * width or len(qraw) != 8 * width:
        raise ValueError("original BF16 physical tensor range differs")
    def bf16(raw):
        """Decode exact BF16 bytes to finite IEEE F32 numbers."""
        out = []
        for (bits,) in struct.iter_unpack("<H", raw):
            x = struct.unpack("<f", struct.pack("<I", bits << 16))[0]
            if not math.isfinite(x):
                raise ValueError("nonfinite original pretrained BF16 parameter")
            out.append(x)
        return tuple(out)
    norm, weights = bf16(nraw), bf16(qraw)
    return original, norm, weights, receipt


def _integerize(values: Sequence[float]) -> tuple[tuple[int, ...], int]:
    """Exact common binary denominator: finite floats are dyadic rationals."""
    if not values or any(type(v) not in (float, int) or not math.isfinite(v) for v in values):
        raise ValueError("intention requires a nonempty finite real vector")
    fractions = tuple(Fraction(v) for v in values)
    denominator = max(q.denominator for q in fractions)
    if denominator > 2**1074:
        raise ValueError("input coordinates exceed admitted double exponent")
    return tuple(v.numerator * (denominator // v.denominator) for v in fractions), denominator


@dataclass(frozen=True)
class CompiledModelIntention:
    """A source-attested trained pairwise model behavior, not a full decoder."""

    source_head: str
    source_model: str
    revision: str
    row_a: int
    row_b: int
    width: int
    coefficients: tuple[int, ...]
    denominator: int
    order: tuple[int, ...]
    model_observation_bytes: int
    relevant_source_bytes: int
    ground_digest: str

    def __post_init__(self) -> None:
        """Validate exact source identity, geometry, integers and executable head."""
        if (_HEX.fullmatch(self.source_head) is None
            or _HEX.fullmatch(self.ground_digest) is None
            or not isinstance(self.width, int) or not 1 <= self.width <= 2048
            or len(self.coefficients) != self.width
            or len(self.order) != self.width
            or sorted(self.order) != list(range(self.width))
            or self.denominator <= 0
            or not 0 <= self.row_a < 4 or not 0 <= self.row_b < 4
            or self.row_a == self.row_b):
            raise ValueError("compiled trained model intention malformed")
        if self.ground_digest != _hash(self.description):
            raise ValueError("trained model intention certificate differs")

    @property
    def description(self) -> dict[str, Any]:
        """Full self-contained executable direction under a typed original source."""
        return {
            "schema": SCHEMA,
            "source_head": self.source_head,
            "source_model": self.source_model,
            "revision": self.revision,
            "row_a": self.row_a, "row_b": self.row_b,
            "width": self.width, "coefficients": list(self.coefficients),
            "denominator": self.denominator,
            "order": list(self.order),
            "model_observation_bytes": self.model_observation_bytes,
            "relevant_source_bytes": self.relevant_source_bytes,
            "semantics": "sign_of_original_BF16_qrow_difference_after_RMS_norm_in_exact_reals",
        }

    @classmethod
    def restore(cls, description: Mapping[str, Any], expected_head: str) -> "CompiledModelIntention":
        """Reconstruct the exact compiled behavior from a portable description."""
        if not isinstance(description, Mapping) or _HEX.fullmatch(expected_head) is None:
            raise ValueError("compiled model description lacks an independent head")
        record = json.loads(_canonical(description))
        if set(record) != {
            "schema", "source_head", "source_model", "revision",
            "row_a", "row_b", "width", "coefficients", "denominator",
            "order", "model_observation_bytes", "relevant_source_bytes", "semantics",
        } or record["schema"] != SCHEMA or record["semantics"] != (
            "sign_of_original_BF16_qrow_difference_after_RMS_norm_in_exact_reals"
        )):
            raise ValueError("unqualified compiled model description")
        if _hash(record) != expected_head:
            raise ValueError("compiled model direction changed across observer hosts")
        if (type(record["width"]) is not int or type(record["denominator"]) is not int
            or type(record["coefficients"]) is not list
            or any(type(v) is not int for v in record["coefficients"])
            or type(record["order"]) is not list
            or any(type(v) is not int for v in record["order"])):
            raise ValueError("compiled numerical direction is not exact integerized source")
        return cls(
            source_head=record["source_head"], source_model=record["source_model"],
            revision=record["revision"], row_a=record["row_a"], row_b=record["row_b"],
            width=record["width"], coefficients=tuple(record["coefficients"]),
            denominator=record["denominator"], order=tuple(record["order"]),
            model_observation_bytes=record["model_observation_bytes"],
            relevant_source_bytes=record["relevant_source_bytes"],
            ground_digest=expected_head,
        )

    def observe(self, hidden: Sequence[float]) -> dict[str, Any]:
        """Certify a pretrained Q-row preference without a full four-row projection.

        For prefix S and remaining a,x, |tail| <= ||a_remaining||*||x_remaining||.
        When S*S > ||a_remaining||^2 ||x_remaining||^2, every compatible
        unseen contribution has the same sign. All products and comparisons
        here are exact integers: BF16 and IEEE double inputs are dyadics.
        """
        if type(hidden) not in (list, tuple) or len(hidden) != self.width:
            raise ValueError("observed input must match original model hidden width")
        xi, xden = _integerize(hidden)
        total_a2 = sum(a*a for a in self.coefficients)
        remaining_a2 = total_a2
        remaining_x2 = sum(x*x for x in xi)
        prefix = 0
        examined = 0
        certified_early = False
        for k in self.order:
            prefix += self.coefficients[k] * xi[k]
            remaining_a2 -= self.coefficients[k] ** 2
            remaining_x2 -= xi[k] ** 2
            examined += 1
            if prefix*prefix > remaining_a2*remaining_x2:
                certified_early = examined < self.width
                break
        winner = (1 if prefix > 0 else -1 if prefix < 0 else 0)
        result = {
            "schema": _RESULT_SCHEMA, "ground_digest": self.ground_digest,
            "source_head": self.source_head,
            "input_digest": _hash(list(hidden)), "row_a": self.row_a,
            "row_b": self.row_b, "sign": winner,
            "winner": "row_a" if winner > 0 else "row_b" if winner < 0 else "tie",
            "observed_coordinates": examined,
            "total_coordinates": self.width,
            "certified_early": certified_early,
            "partial_dot_integer": str(prefix),
            "remaining_bound_squared_integer": str(remaining_a2*remaining_x2),
            "partial_dot_squared_integer": str(prefix*prefix),
            "exact_dyadic_denominator": str(self.denominator * xden),
            "new_remote_weight_bytes": 0,
            "full_four_row_projection_performed": False,
            "scope": "exact_real_arithmetic_pairwise_Q_projection_preference",
        }
        result["observation_digest"] = _hash(result)
        return result

    def verify_observation(self, hidden: Sequence[float], reported: Mapping[str, Any]) -> bool:
        """Independent full re-navigation over the same signed compiled Ground."""
        if not isinstance(reported, Mapping) or dict(reported) != self.observe(hidden):
            raise ValueError("trained behavior observation cannot be reconstructed")
        return True


def compile_trained_model_intention(
    original_pretrained_slice: Mapping[str, Any], *,
    expected_source_head: str, row_a: int = 0, row_b: int = 1,
) -> CompiledModelIntention:
    """Compile exactly those original learned rows that settle the intention.

    Original VL-64 validates the entire historically retained 5760-byte
    source capsule. Only 2 Q rows and the common RMSNorm gain participate
    in this particular compiled question (3456 logical source bytes).
    """
    if (type(row_a) is not int or type(row_b) is not int or
        not 0 <= row_a < 4 or not 0 <= row_b < 4 or row_a == row_b):
        raise ValueError("requested trained readout rows are not in admitted slice")
    source, gain, q, original_receipt = _original_slice(
        original_pretrained_slice, expected_head=expected_source_head,
    )
    width = source["hidden_width"]
    rows = (q[row_a * width:(row_a+1)*width],
            q[row_b * width:(row_b+1)*width])
    direction = tuple(
        float((rows[0][i] - rows[1][i]) * gain[i])
        for i in range(width)
    )
    coefficients, denominator = _integerize(direction)
    order = tuple(sorted(range(width), key=lambda k: (-abs(coefficients[k]), k)))
    source_bytes = int(original_receipt["actual_model_weight_bytes"])
    body = {
        "schema": SCHEMA, "source_head": source["ground_digest"],
        "source_model": source["model"], "revision": source["revision"],
        "row_a": row_a, "row_b": row_b,
        "width": width, "coefficients": list(coefficients),
        "denominator": denominator, "order": list(order),
        "model_observation_bytes": source_bytes,
        "relevant_source_bytes": 3 * 2 * width,
        "semantics": "sign_of_original_BF16_qrow_difference_after_RMS_norm_in_exact_reals",
    }
    return CompiledModelIntention(
        source_head=source["ground_digest"],
        source_model=source["model"], revision=source["revision"],
        row_a=row_a, row_b=row_b, width=width, coefficients=coefficients,
        denominator=denominator, order=order,
        model_observation_bytes=source_bytes,
        relevant_source_bytes=3 * 2 * width,
        ground_digest=_hash(body),
    )


def original_full_four_row_projection(
    original_pretrained_slice: Mapping[str, Any], hidden: Sequence[float],
    *, expected_source_head: str,
) -> tuple[float, float, float, float]:
    """Independent dense numerical oracle: all 4 original trained BF16 Q rows."""
    source, gain, q, _ = _original_slice(
        original_pretrained_slice, expected_head=expected_source_head,
    )
    width = source["hidden_width"]
    if type(hidden) not in (list, tuple) or len(hidden) != width:
        raise ValueError("source model hidden width differs")
    if any(type(v) not in (int,float) or not math.isfinite(v) for v in hidden):
        raise ValueError("nonfinite source input")
    scale = 1.0 / math.sqrt(
        math.fsum(float(x)*x for x in hidden) / width + source["rms_eps"],
    )
    normalized = tuple(float(hidden[i])*gain[i]*scale for i in range(width))
    return tuple(
        math.fsum(q[r*width+i]*normalized[i] for i in range(width))
        for r in range(4)
    )


def generate_neural_ground_from_trained_observations(
    compiled: CompiledModelIntention,
    observations: Sequence[tuple[Sequence[float], Mapping[str, Any]]],
) -> tuple[bytes, dict[str, Any]]:
    """Form original VL-I/VLD neural weights from a finite observed behavior law.

    The new model captures a complete finite *observed input-coordinate*
    environment, with inspect and advance actions. This does not assert
    generalization of that neural FSM to unseen continuous hidden vectors;
    the trained pairwise compiler itself handles new vectors.
    """
    if not isinstance(compiled, CompiledModelIntention) or not 2 <= len(observations) <= 8:
        raise ValueError("neural formation requires 2..8 source-backed observations")
    events = []
    for i, (hidden, report) in enumerate(observations):
        compiled.verify_observation(hidden, report)
        events.append({
            "state": "observed_" + str(i),
            "sample_digest": report["input_digest"],
            "observation_digest": report["observation_digest"],
            "sign": report["sign"],
            "early": int(report["certified_early"]),
        })
    if len({e["sample_digest"] for e in events}) != len(events):
        raise ValueError("finite model cannot treat repeated inputs as independent states")
    labels = tuple(e["state"] for e in events)
    cells = []
    for i, event in enumerate(events):
        for action in ("inspect", "advance"):
            j = i if action == "inspect" else (i+1) % len(events)
            target = events[j]
            cells.append({
                "source": event["state"], "action": action,
                "outcomes": [{
                    "target": target["state"],
                    "output": [target["sign"] + 1, target["early"]],
                }],
                "support_count": 1,
                "evidence": [target["observation_digest"]],
            })
    description = {
        "format": "vld.transition-system.v1",
        "states": list(labels),
        "actions": ["inspect", "advance"],
        "channels": ["trained_q_preference", "early_certificate"],
        "initial_state": labels[0],
        "metadata": {
            "source": "original_pretrained_model_observations",
            "original_pretrained_ground_head": compiled.source_head,
            "compiled_behavior_head": compiled.ground_digest,
            "sample_observation_digests": [e["observation_digest"] for e in events],
            "scope": "observed_finite_environment_not_arbitrary_language_generation",
        },
        "observations": cells,
    }
    raw = _canonical(description)
    from vli.generative_response import GeneratedModelGround
    generated = GeneratedModelGround(raw)
    if not generated.verify():
        raise ValueError("original VLD-generated neural Ground failed verification")
    for cell in cells:
        next_state, output = generated.generated(cell["source"], cell["action"])
        if (next_state != cell["outcomes"][0]["target"]
            or list(output) != cell["outcomes"][0]["output"]):
            raise ValueError("original VL-I generated neural weights fail observed model behavior")
    return raw, {
        "description_digest": hashlib.sha256(raw).hexdigest(),
        "compiled_trained_behavior_head": compiled.ground_digest,
        "generated_model_ground_digest": generated.manifest["ground_digest"],
        "generated_neural_weights_digest": generated.weights_digest,
        "observed_cells_verified": len(cells),
        "generated_hidden_units": len(generated.neural.hidden_bias),
        "pretrained_weight_download_bytes_after_compilation": 0,
        "scope": "generated_neural_model_of_finite_trained_observation_environment",
    }
