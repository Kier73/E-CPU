"""Exact small-domain compilation of Boolean gates into dense ReLU weights.

This is a deliberately bounded constructive realization, not a trainer and not
an arbitrary-network synthesizer. It compiles two-input XOR/AND specifications
into a fixed 2-85-112-1 MLP and exposes a two-weight semantic intervention.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .model import Instruction, Op, Program

ARCHITECTURE = (2, 85, 112, 1)
ACTIVATION = "relu-hidden-linear-output"
SCHEMA = "mailcpu.weight-space-model.v1"
_GATE_OUTPUTS = {"xor": (1.0, -2.0), "and": (0.0, 1.0)}


class WeightSpaceError(ValueError):
    """A model, gate specification, input, or intervention is outside this prototype's contract."""


def _finite_number(value: Any, label: str) -> float:
    """Validate and normalize one finite real-valued model scalar."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise WeightSpaceError(f"{label} must be a real number")
    result = float(value)
    if not math.isfinite(result):
        raise WeightSpaceError(f"{label} must be finite")
    return result


def _binary(value: Any, label: str) -> int:
    """Validate a Boolean-domain input while excluding non-binary integers."""
    if isinstance(value, bool):
        return int(value)
    if type(value) is int and value in (0, 1):
        return value
    raise WeightSpaceError(f"{label} must be a Boolean bit (0 or 1)")


class DenseReLUNetwork:
    """Explicit dense 2-85-112-1 ReLU parameterization for a Boolean gate."""
    """Dense MLP whose matrices are stored output-major and include explicit biases."""

    def __init__(
        self,
        weights: Sequence[Sequence[Sequence[float]]],
        biases: Sequence[Sequence[float]],
        *,
        compiled_gate: str,
    ) -> None:
        if compiled_gate not in _GATE_OUTPUTS:
            raise WeightSpaceError("compiled_gate must be 'xor' or 'and'")
        self._weights = [
            [[_finite_number(value, "weight") for value in row] for row in layer]
            for layer in weights
        ]
        self._biases = [
            [_finite_number(value, "bias") for value in layer]
            for layer in biases
        ]
        self._compiled_gate = compiled_gate
        self._validate_shape()

    def _validate_shape(self) -> None:
        """Reject tensors whose dimensions differ from the declared architecture."""
        if len(self._weights) != 3 or len(self._biases) != 3:
            raise WeightSpaceError("the prototype requires exactly three dense layers")
        expected = tuple(zip(ARCHITECTURE[:-1], ARCHITECTURE[1:]))
        for layer_index, ((input_width, output_width), matrix, bias) in enumerate(
            zip(expected, self._weights, self._biases)
        ):
            if len(matrix) != output_width or len(bias) != output_width:
                raise WeightSpaceError(f"layer {layer_index} output shape is invalid")
            if any(len(row) != input_width for row in matrix):
                raise WeightSpaceError(f"layer {layer_index} input shape is invalid")

    @property
    def architecture(self) -> tuple[int, ...]:
        """Return the fixed layer-width tuple represented by this network."""
        return ARCHITECTURE

    @property
    def compiled_gate(self) -> str:
        """Return the gate identity used by the deterministic compiler template."""
        return self._compiled_gate

    @property
    def weights(self) -> tuple[tuple[tuple[float, ...], ...], ...]:
        """Expose an immutable output-major copy of all weight matrices."""
        return tuple(tuple(tuple(row) for row in layer) for layer in self._weights)

    @property
    def biases(self) -> tuple[tuple[float, ...], ...]:
        """Expose an immutable copy of the layer bias vectors."""
        return tuple(tuple(layer) for layer in self._biases)

    @property
    def parameter_count(self) -> int:
        """Count every declared weight and bias, including zero-valued entries."""
        return sum(len(row) for layer in self._weights for row in layer) + sum(
            len(layer) for layer in self._biases
        )

    @property
    def active_parameter_count(self) -> int:
        """Count nonzero weights and biases in the current parameterization."""
        return sum(
            value != 0.0
            for layer in self._weights
            for row in layer
            for value in row
        ) + sum(value != 0.0 for layer in self._biases for value in layer)

    def forward(self, inputs: Sequence[int | float]) -> tuple[float, ...]:
        """Evaluate the declared dense layers with ReLU hidden activations."""
        if len(inputs) != ARCHITECTURE[0]:
            raise WeightSpaceError("input must contain exactly two values")
        values = [_finite_number(value, "input") for value in inputs]
        for layer_index, (matrix, bias) in enumerate(zip(self._weights, self._biases)):
            next_values = [
                offset + sum(weight * value for weight, value in zip(row, values))
                for row, offset in zip(matrix, bias)
            ]
            # The architecture is ReLU on hidden layers and linear at the output.
            values = (
                [max(0.0, value) for value in next_values]
                if layer_index < 2
                else next_values
            )
        return tuple(values)

    def predict(self, left: int, right: int) -> int:
        """Evaluate the declared Boolean domain {0,1}² and return one exact bit."""
        left_bit, right_bit = _binary(left, "left input"), _binary(right, "right input")
        output = self.forward((left_bit, right_bit))[0]
        nearest = round(output)
        if (
            not math.isclose(output, nearest, rel_tol=0.0, abs_tol=1e-12)
            or nearest not in (0, 1)
        ):
            raise WeightSpaceError(
                "network output left the exact Boolean output set {0,1}"
            )
        return int(nearest)

    def _payload(self) -> dict[str, Any]:
        """Build a detached canonical-JSON-compatible model snapshot payload."""
        # Snapshots must not alias mutable internal tensors.
        return {
            "schema": SCHEMA,
            "architecture": list(ARCHITECTURE),
            "activation": ACTIVATION,
            "compiled_gate": self._compiled_gate,
            "weights": [[list(row) for row in layer] for layer in self._weights],
            "biases": [list(layer) for layer in self._biases],
            "parameter_count": self.parameter_count,
        }

    @property
    def digest(self) -> str:
        """Return SHA-256 identity of the canonical model snapshot payload."""
        encoded = json.dumps(
            self._payload(),
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def snapshot(self) -> dict[str, Any]:
        """Return a detached, digest-bound serialization of the model."""
        payload = self._payload()
        payload["digest"] = self.digest
        return payload

    @classmethod
    def from_snapshot(cls, payload: Mapping[str, Any]) -> "DenseReLUNetwork":
        """Restore a model only after checking its schema, shape, count, and digest."""
        if not isinstance(payload, Mapping):
            raise WeightSpaceError("snapshot must be a mapping")
        required = {
            "schema",
            "architecture",
            "activation",
            "compiled_gate",
            "weights",
            "biases",
            "parameter_count",
            "digest",
        }
        if set(payload) != required:
            raise WeightSpaceError("snapshot fields do not match the v1 schema")
        if (
            payload["schema"] != SCHEMA
            or tuple(payload["architecture"]) != ARCHITECTURE
        ):
            raise WeightSpaceError("snapshot schema or architecture is unsupported")
        if payload["activation"] != ACTIVATION:
            raise WeightSpaceError("snapshot activation contract is unsupported")
        restored = cls(
            payload["weights"],
            payload["biases"],
            compiled_gate=payload["compiled_gate"],
        )
        if (
            type(payload["parameter_count"]) is not int
            or payload["parameter_count"] != restored.parameter_count
        ):
            raise WeightSpaceError("snapshot parameter count does not match its tensors")
        if payload["digest"] != restored.digest:
            raise WeightSpaceError("snapshot digest mismatch")
        return restored


def compile_boolean_gate(gate: str = "xor") -> DenseReLUNetwork:
    """Construct a 10,000-parameter 2-85-112-1 MLP without an optimizer or dataset.

    Hidden unit 0 computes ReLU(a+b); hidden unit 1 computes ReLU(a+b-1).
    The second hidden layer copies those two non-negative features. The final
    linear weights are (1,-2) for XOR and (0,1) for AND.
    """
    if gate not in _GATE_OUTPUTS:
        raise WeightSpaceError("gate must be 'xor' or 'and'")

    w1 = [[0.0, 0.0] for _ in range(85)]
    b1 = [0.0] * 85
    w1[0] = [1.0, 1.0]
    w1[1] = [1.0, 1.0]
    b1[1] = -1.0

    w2 = [[0.0] * 85 for _ in range(112)]
    b2 = [0.0] * 112
    w2[0][0] = 1.0
    w2[1][1] = 1.0

    w3 = [[0.0] * 112]
    b3 = [0.0]
    w3[0][0], w3[0][1] = _GATE_OUTPUTS[gate]

    return DenseReLUNetwork(
        (w1, w2, w3),
        (b1, b2, b3),
        compiled_gate=gate,
    )


@dataclass(frozen=True)
class ParameterCoordinate:
    """Identify one output-major weight coordinate in a layer matrix."""
    layer_index: int
    output_index: int
    input_index: int

    def to_dict(self) -> dict[str, int]:
        """Serialize the three integer indices of this parameter coordinate."""
        return {
            "layer_index": self.layer_index,
            "output_index": self.output_index,
            "input_index": self.input_index,
        }


@dataclass(frozen=True)
class ParameterIntervention:
    """Record the content identities and coordinates of one parameter edit."""
    source_digest: str
    target_digest: str
    changed_parameters: int
    coordinates: tuple[ParameterCoordinate, ...]

    def to_dict(self) -> dict[str, Any]:
        """Serialize the intervention identity and its changed coordinates."""
        return {
            "source_digest": self.source_digest,
            "target_digest": self.target_digest,
            "changed_parameters": self.changed_parameters,
            "coordinates": [item.to_dict() for item in self.coordinates],
        }


def edit_boolean_gate(
    model: DenseReLUNetwork,
    target_gate: str,
) -> ParameterIntervention:
    """Change XOR↔AND by editing exactly two output coefficients in the final layer."""
    if not isinstance(model, DenseReLUNetwork):
        raise WeightSpaceError("model must be a DenseReLUNetwork")
    if target_gate not in _GATE_OUTPUTS:
        raise WeightSpaceError("target_gate must be 'xor' or 'and'")

    # Refuse to apply the surgical edit to an arbitrary or externally mutated network.
    canonical = compile_boolean_gate(model.compiled_gate)
    if model.weights != canonical.weights or model.biases != canonical.biases:
        raise WeightSpaceError("model no longer matches its declared compiled template")

    source_digest = model.digest
    if model.compiled_gate == target_gate:
        return ParameterIntervention(source_digest, source_digest, 0, ())

    desired = _GATE_OUTPUTS[target_gate]
    coordinates: list[ParameterCoordinate] = []
    for input_index, value in enumerate(desired):
        if model._weights[2][0][input_index] != value:
            model._weights[2][0][input_index] = value
            coordinates.append(ParameterCoordinate(2, 0, input_index))
    model._compiled_gate = target_gate

    if len(coordinates) != 2:
        raise WeightSpaceError(
            "expected the semantic edit to change exactly two parameters"
        )
    return ParameterIntervention(
        source_digest=source_digest,
        target_digest=model.digest,
        changed_parameters=len(coordinates),
        coordinates=tuple(coordinates),
    )


def boolean_gate_program(gate: str) -> Program:
    """Build a MailCPU instruction program for the same two-input Boolean function."""
    if gate == "and":
        return Program(
            (
                Instruction(Op.MUL, ("result", "a", "b")),
                Instruction(Op.HALT),
            )
        )
    if gate == "xor":
        return Program(
            (
                Instruction(Op.COMPARE, ("different", "a", "b")),
                Instruction(Op.BRANCH, ("different", 4)),
                Instruction(Op.SET, ("result", 0)),
                Instruction(Op.HALT),
                Instruction(Op.SET, ("result", 1)),
                Instruction(Op.HALT),
            )
        )
    raise WeightSpaceError("gate must be 'xor' or 'and'")


def evaluate_boolean_gate(gate: str, left: int, right: int) -> int:
    """Independent, explicit specification oracle on the declared binary domain."""
    left_bit, right_bit = _binary(left, "left input"), _binary(right, "right input")
    if gate == "xor":
        return left_bit ^ right_bit
    if gate == "and":
        return left_bit & right_bit
    raise WeightSpaceError("gate must be 'xor' or 'and'")


def encode_boolean_signal(bit: int) -> int:
    """Embed the Boolean group in Z/8Z: 0↦0 and 1↦4; addition then realizes XOR."""
    return 4 * _binary(bit, "signal input")


def decode_boolean_signal(symbol: int) -> int:
    """Decode one value from the embedded Boolean subgroup {0, 4} of Z/8Z."""
    if symbol == 0:
        return 0
    if symbol == 4:
        return 1
    raise WeightSpaceError(
        "signal symbol is not in the embedded Boolean subgroup {0,4}"
    )
