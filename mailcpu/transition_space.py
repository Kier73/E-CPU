"""Constructive ReLU realization of complete finite Boolean transition tables.
Mathematics: this callable implements the deterministic mapping or invariant stated in its contract, over the explicitly validated input domain.

A table row is compiled into one hidden minterm unit. The unit is exactly one
on its declared input row and zero on every other Boolean input. A linear
output layer then selects the specified next-state bits. This is a bounded
exact compiler for finite Boolean transition systems, not a learned model.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .model import Instruction, Op, Program

SCHEMA = "mailcpu.finite-transition-relu.v1"
_IDENTIFIER = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
_INTERNAL_PREFIX = "transition_"


class TransitionSpaceError(ValueError):
    """A transition table, neural architecture, snapshot, or intervention violates the finite-table contract.
Mathematics: this callable implements the deterministic mapping or invariant stated in its contract, over the explicitly validated input domain.
"""


def _bit(value: Any, label: str) -> int:
    """Normalize a Boolean bit while rejecting values outside the finite domain.
Mathematics: this callable implements the deterministic mapping or invariant stated in its contract, over the explicitly validated input domain.
"""
    if isinstance(value, bool):
        return int(value)
    if type(value) is int and value in (0, 1):
        return value
    raise TransitionSpaceError(f"{label} must be a Boolean bit (0 or 1)")


def _finite_number(value: Any, label: str) -> float:
    """Validate and normalize one finite scalar in a neural tensor.
Mathematics: this callable implements the deterministic mapping or invariant stated in its contract, over the explicitly validated input domain.
"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TransitionSpaceError(f"{label} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise TransitionSpaceError(f"{label} must be finite")
    return result


def _names(values: Sequence[str], label: str) -> tuple[str, ...]:
    """Validate a nonempty ordered set of safe and unique field names.
Mathematics: this callable implements the deterministic mapping or invariant stated in its contract, over the explicitly validated input domain.
"""
    result = tuple(values)
    if not result or any(
        not isinstance(value, str)
        or _IDENTIFIER.fullmatch(value) is None
        or value.startswith(_INTERNAL_PREFIX)
        for value in result
    ):
        raise TransitionSpaceError(f"{label} must contain safe non-reserved identifiers")
    if len(set(result)) != len(result):
        raise TransitionSpaceError(f"{label} must be unique")
    return result


@dataclass(frozen=True, slots=True)
class TransitionRow:
    """One complete Boolean input pattern and its corresponding output pattern.
Mathematics: this callable implements the deterministic mapping or invariant stated in its contract, over the explicitly validated input domain.
"""

    inputs: tuple[int, ...]
    outputs: tuple[int, ...]

    def __post_init__(self) -> None:
        """Normalize both sides of a transition row to immutable Boolean tuples.
Mathematics: this callable implements the deterministic mapping or invariant stated in its contract, over the explicitly validated input domain.
"""
        normalized_inputs = tuple(
            _bit(value, "transition input") for value in self.inputs
        )
        normalized_outputs = tuple(
            _bit(value, "transition output") for value in self.outputs
        )
        if not normalized_inputs or not normalized_outputs:
            raise TransitionSpaceError("transition rows require nonempty input and output patterns")
        object.__setattr__(self, "inputs", normalized_inputs)
        object.__setattr__(self, "outputs", normalized_outputs)

    def to_dict(self) -> dict[str, list[int]]:
        """Serialize the input and output bit patterns.
Mathematics: this callable implements the deterministic mapping or invariant stated in its contract, over the explicitly validated input domain.
"""
        return {"inputs": list(self.inputs), "outputs": list(self.outputs)}


@dataclass(frozen=True, slots=True)
class FiniteTransitionTable:
    """A total deterministic Boolean function represented by its complete truth table.
Mathematics: this callable implements the deterministic mapping or invariant stated in its contract, over the explicitly validated input domain.
"""

    name: str
    input_names: tuple[str, ...]
    output_names: tuple[str, ...]
    rows: tuple[TransitionRow, ...]

    def __post_init__(self) -> None:
        """Require every Boolean input pattern exactly once and sort rows canonically.
Mathematics: this callable implements the deterministic mapping or invariant stated in its contract, over the explicitly validated input domain.
"""
        if not isinstance(self.name, str) or not self.name.strip():
            raise TransitionSpaceError("transition table name must be nonempty")
        input_names = _names(self.input_names, "input_names")
        output_names = _names(self.output_names, "output_names")
        if set(input_names) & set(output_names):
            raise TransitionSpaceError("input and output names must be disjoint")
        if len(input_names) > 8:
            raise TransitionSpaceError("transition tables are bounded to at most eight input bits")
        rows = tuple(self.rows)
        if any(not isinstance(row, TransitionRow) for row in rows):
            raise TransitionSpaceError("rows must contain TransitionRow values")
        if any(
            len(row.inputs) != len(input_names)
            or len(row.outputs) != len(output_names)
            for row in rows
        ):
            raise TransitionSpaceError("row dimensions do not match declared names")
        ordered = tuple(sorted(rows, key=lambda row: row.inputs))
        patterns = tuple(row.inputs for row in ordered)
        expected = tuple(itertools.product((0, 1), repeat=len(input_names)))
        if patterns != expected:
            raise TransitionSpaceError(
                "rows must cover every Boolean input pattern exactly once"
            )
        object.__setattr__(self, "input_names", input_names)
        object.__setattr__(self, "output_names", output_names)
        object.__setattr__(self, "rows", ordered)

    @property
    def row_count(self) -> int:
        """Return the number of fully enumerated Boolean input patterns.
Mathematics: this callable implements the deterministic mapping or invariant stated in its contract, over the explicitly validated input domain.
"""
        return len(self.rows)

    @property
    def digest(self) -> str:
        """Return the SHA-256 identity of the canonical transition-table payload.
Mathematics: this callable implements the deterministic mapping or invariant stated in its contract, over the explicitly validated input domain.
"""
        encoded = json.dumps(
            self.to_dict(),
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def row_index(self, inputs: Sequence[int]) -> int:
        """Find the canonical row index for one validated input bit pattern.
Mathematics: this callable implements the deterministic mapping or invariant stated in its contract, over the explicitly validated input domain.
"""
        pattern = tuple(_bit(value, "transition input") for value in inputs)
        if len(pattern) != len(self.input_names):
            raise TransitionSpaceError("input pattern width does not match the table")
        return pattern_to_index(pattern)

    def row_for(self, inputs: Sequence[int]) -> TransitionRow:
        """Return the declared transition for one exact Boolean input pattern.
Mathematics: this callable implements the deterministic mapping or invariant stated in its contract, over the explicitly validated input domain.
"""
        return self.rows[self.row_index(inputs)]

    def with_output(
        self,
        inputs: Sequence[int],
        outputs: Sequence[int],
        *,
        name: str | None = None,
    ) -> "FiniteTransitionTable":
        """Return a new table with one selected row's output bits replaced.
Mathematics: this callable implements the deterministic mapping or invariant stated in its contract, over the explicitly validated input domain.
"""
        row_index = self.row_index(inputs)
        output_pattern = tuple(
            _bit(value, "transition output") for value in outputs
        )
        if len(output_pattern) != len(self.output_names):
            raise TransitionSpaceError("output pattern width does not match the table")
        rows = list(self.rows)
        rows[row_index] = TransitionRow(rows[row_index].inputs, output_pattern)
        return FiniteTransitionTable(
            name or self.name,
            self.input_names,
            self.output_names,
            tuple(rows),
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize the table with deterministic field and row ordering.
Mathematics: this callable implements the deterministic mapping or invariant stated in its contract, over the explicitly validated input domain.
"""
        return {
            "schema": "mailcpu.finite-transition-table.v1",
            "name": self.name,
            "input_names": list(self.input_names),
            "output_names": list(self.output_names),
            "rows": [row.to_dict() for row in self.rows],
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "FiniteTransitionTable":
        """Restore a transition table only from the exact declared schema.
Mathematics: this callable implements the deterministic mapping or invariant stated in its contract, over the explicitly validated input domain.
"""
        required = {"schema", "name", "input_names", "output_names", "rows"}
        if not isinstance(payload, Mapping) or set(payload) != required:
            raise TransitionSpaceError("transition table fields do not match the schema")
        if payload["schema"] != "mailcpu.finite-transition-table.v1":
            raise TransitionSpaceError("unsupported transition table schema")
        rows = payload["rows"]
        if not isinstance(rows, list):
            raise TransitionSpaceError("transition table rows must be an array")
        restored_rows = []
        for item in rows:
            if not isinstance(item, Mapping) or set(item) != {"inputs", "outputs"}:
                raise TransitionSpaceError("transition row fields are invalid")
            restored_rows.append(TransitionRow(tuple(item["inputs"]), tuple(item["outputs"])))
        return cls(
            payload["name"],
            tuple(payload["input_names"]),
            tuple(payload["output_names"]),
            tuple(restored_rows),
        )


def pattern_to_index(pattern: Sequence[int]) -> int:
    """Interpret an ordered bit pattern as its stable binary row index.
Mathematics: this callable implements the deterministic mapping or invariant stated in its contract, over the explicitly validated input domain.
"""
    result = 0
    for value in pattern:
        result = (result << 1) | _bit(value, "pattern bit")
    return result


def two_bit_counter_table() -> FiniteTransitionTable:
    """Enumerate the typed two-bit counter program into its complete truth table.
Mathematics: this callable implements the deterministic mapping or invariant stated in its contract, over the explicitly validated input domain.
"""
    return two_bit_counter_program().to_table()


@dataclass(frozen=True, slots=True)
class TransitionWeightCoordinate:
    """Identify one output-major neural weight changed by a table intervention.
Mathematics: this callable implements the deterministic mapping or invariant stated in its contract, over the explicitly validated input domain.
"""

    layer_index: int
    output_index: int
    input_index: int

    def to_dict(self) -> dict[str, int]:
        """Serialize the layer, output-neuron, and input-neuron coordinates.
Mathematics: this callable implements the deterministic mapping or invariant stated in its contract, over the explicitly validated input domain.
"""
        return {
            "layer_index": self.layer_index,
            "output_index": self.output_index,
            "input_index": self.input_index,
        }


@dataclass(frozen=True, slots=True)
class TransitionWeightIntervention:
    """Bind a finite-table edit to the exact neural model parameters that changed.
Mathematics: this callable implements the deterministic mapping or invariant stated in its contract, over the explicitly validated input domain.
"""

    source_table_digest: str
    target_table_digest: str
    source_model_digest: str
    target_model_digest: str
    changed_parameters: int
    coordinates: tuple[TransitionWeightCoordinate, ...]

    def to_dict(self) -> dict[str, Any]:
        """Serialize source/target identities and every modified weight coordinate.
Mathematics: this callable implements the deterministic mapping or invariant stated in its contract, over the explicitly validated input domain.
"""
        return {
            "source_table_digest": self.source_table_digest,
            "target_table_digest": self.target_table_digest,
            "source_model_digest": self.source_model_digest,
            "target_model_digest": self.target_model_digest,
            "changed_parameters": self.changed_parameters,
            "coordinates": [item.to_dict() for item in self.coordinates],
        }


class TransitionReLUNetwork:
    """Dense ReLU model whose first hidden layer encodes one minterm per table row.
Mathematics: this callable implements the deterministic mapping or invariant stated in its contract, over the explicitly validated input domain.
"""

    def __init__(
        self,
        weights: Sequence[Sequence[Sequence[float]]],
        biases: Sequence[Sequence[float]],
        *,
        table_digest: str,
        input_names: Sequence[str],
        output_names: Sequence[str],
        architecture: Sequence[int],
    ) -> None:
        """Copy finite tensors and validate them against a complete-table architecture.
Mathematics: this callable implements the deterministic mapping or invariant stated in its contract, over the explicitly validated input domain.
"""
        self._weights = [
            [[_finite_number(value, "weight") for value in row] for row in layer]
            for layer in weights
        ]
        self._biases = [
            [_finite_number(value, "bias") for value in layer]
            for layer in biases
        ]
        self._table_digest = _validate_digest(table_digest, "table_digest")
        self._input_names = _names(input_names, "input_names")
        self._output_names = _names(output_names, "output_names")
        self._architecture = tuple(architecture)
        self._row_count = 2 ** len(self._input_names)
        self._validate_shape()

    def _validate_shape(self) -> None:
        """Require one hidden unit per truth-table row and matching layer tensors.
Mathematics: this callable implements the deterministic mapping or invariant stated in its contract, over the explicitly validated input domain.
"""
        if (
            len(self._architecture) < 3
            or self._architecture[0] != len(self._input_names)
            or self._architecture[-1] != len(self._output_names)
            or any(width != self._row_count for width in self._architecture[1:-1])
            or len(self._weights) != len(self._architecture) - 1
            or len(self._biases) != len(self._architecture) - 1
        ):
            raise TransitionSpaceError("architecture must preserve one hidden unit per table row")
        expected = tuple(zip(self._architecture[:-1], self._architecture[1:]))
        for layer_index, ((input_width, output_width), matrix, bias) in enumerate(
            zip(expected, self._weights, self._biases)
        ):
            if len(matrix) != output_width or len(bias) != output_width:
                raise TransitionSpaceError(f"layer {layer_index} output shape is invalid")
            if any(len(row) != input_width for row in matrix):
                raise TransitionSpaceError(f"layer {layer_index} input shape is invalid")

    @property
    def architecture(self) -> tuple[int, ...]:
        """Return the exact layer-width tuple for this finite transition model.
Mathematics: this callable implements the deterministic mapping or invariant stated in its contract, over the explicitly validated input domain.
"""
        return self._architecture

    @property
    def table_digest(self) -> str:
        """Return the digest of the truth table compiled into the current weights.
Mathematics: this callable implements the deterministic mapping or invariant stated in its contract, over the explicitly validated input domain.
"""
        return self._table_digest

    @property
    def input_names(self) -> tuple[str, ...]:
        """Return the ordered transition input register names.
Mathematics: this callable implements the deterministic mapping or invariant stated in its contract, over the explicitly validated input domain.
"""
        return self._input_names

    @property
    def output_names(self) -> tuple[str, ...]:
        """Return the ordered next-state output register names.
Mathematics: this callable implements the deterministic mapping or invariant stated in its contract, over the explicitly validated input domain.
"""
        return self._output_names

    @property
    def weights(self) -> tuple[tuple[tuple[float, ...], ...], ...]:
        """Expose immutable output-major copies of the model weight matrices.
Mathematics: this callable implements the deterministic mapping or invariant stated in its contract, over the explicitly validated input domain.
"""
        return tuple(tuple(tuple(row) for row in layer) for layer in self._weights)

    @property
    def biases(self) -> tuple[tuple[float, ...], ...]:
        """Expose immutable copies of the model bias vectors.
Mathematics: this callable implements the deterministic mapping or invariant stated in its contract, over the explicitly validated input domain.
"""
        return tuple(tuple(layer) for layer in self._biases)

    @property
    def parameter_count(self) -> int:
        """Count all declared weights and biases, including zero-valued entries.
Mathematics: this callable implements the deterministic mapping or invariant stated in its contract, over the explicitly validated input domain.
"""
        return sum(len(row) for layer in self._weights for row in layer) + sum(
            len(layer) for layer in self._biases
        )

    @property
    def active_parameter_count(self) -> int:
        """Count only nonzero weights and biases in the current network.
Mathematics: this callable implements the deterministic mapping or invariant stated in its contract, over the explicitly validated input domain.
"""
        return sum(
            value != 0.0
            for layer in self._weights
            for row in layer
            for value in row
        ) + sum(value != 0.0 for layer in self._biases for value in layer)

    @property
    def digest(self) -> str:
        """Return a SHA-256 identity over architecture, source table, and all tensors.
Mathematics: this callable implements the deterministic mapping or invariant stated in its contract, over the explicitly validated input domain.
"""
        encoded = json.dumps(
            self._payload(),
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def forward(self, inputs: Sequence[int | float]) -> tuple[float, ...]:
        """Evaluate the dense ReLU layers for one correctly sized finite input vector.
Mathematics: this callable implements the deterministic mapping or invariant stated in its contract, over the explicitly validated input domain.
"""
        if len(inputs) != len(self._input_names):
            raise TransitionSpaceError("input vector width does not match the transition table")
        values = [_finite_number(value, "input") for value in inputs]
        for layer_index, (matrix, bias) in enumerate(zip(self._weights, self._biases)):
            next_values = [
                offset + sum(weight * value for weight, value in zip(row, values))
                for row, offset in zip(matrix, bias)
            ]
            values = (
                [max(0.0, value) for value in next_values]
                if layer_index < len(self._weights) - 1
                else next_values
            )
        return tuple(values)

    def predict(self, inputs: Sequence[int]) -> tuple[int, ...]:
        """Evaluate a Boolean transition row and require exact Boolean outputs.
Mathematics: this callable implements the deterministic mapping or invariant stated in its contract, over the explicitly validated input domain.
"""
        normalized = tuple(_bit(value, "transition input") for value in inputs)
        values = self.forward(normalized)
        rounded = tuple(round(value) for value in values)
        if any(
            nearest not in (0, 1)
            or not math.isclose(value, nearest, rel_tol=0.0, abs_tol=1e-12)
            for value, nearest in zip(values, rounded)
        ):
            raise TransitionSpaceError("network output left the exact Boolean set")
        return tuple(int(value) for value in rounded)

    def _payload(self) -> dict[str, Any]:
        """Build a detached canonical snapshot payload for content addressing.
Mathematics: this callable implements the deterministic mapping or invariant stated in its contract, over the explicitly validated input domain.
"""
        return {
            "schema": SCHEMA,
            "table_digest": self._table_digest,
            "input_names": list(self._input_names),
            "output_names": list(self._output_names),
            "row_count": self._row_count,
            "architecture": list(self._architecture),
            "weights": [[list(row) for row in layer] for layer in self._weights],
            "biases": [list(layer) for layer in self._biases],
            "parameter_count": self.parameter_count,
        }

    def snapshot(self) -> dict[str, Any]:
        """Return a detached digest-bound model snapshot.
Mathematics: this callable implements the deterministic mapping or invariant stated in its contract, over the explicitly validated input domain.
"""
        payload = self._payload()
        payload["digest"] = self.digest
        return payload

    @classmethod
    def from_snapshot(cls, payload: Mapping[str, Any]) -> "TransitionReLUNetwork":
        """Restore a model only after checking schema, dimensions, counts, and digest.
Mathematics: this callable implements the deterministic mapping or invariant stated in its contract, over the explicitly validated input domain.
"""
        required = {
            "schema",
            "table_digest",
            "input_names",
            "output_names",
            "row_count",
            "architecture",
            "weights",
            "biases",
            "parameter_count",
            "digest",
        }
        if not isinstance(payload, Mapping) or set(payload) != required:
            raise TransitionSpaceError("model snapshot fields do not match the schema")
        if payload["schema"] != SCHEMA:
            raise TransitionSpaceError("unsupported transition model schema")
        model = cls(
            payload["weights"],
            payload["biases"],
            table_digest=payload["table_digest"],
            input_names=payload["input_names"],
            output_names=payload["output_names"],
            architecture=payload["architecture"],
        )
        if (
            payload["row_count"] != model._row_count
            or type(payload["parameter_count"]) is not int
            or payload["parameter_count"] != model.parameter_count
            or payload["digest"] != model.digest
        ):
            raise TransitionSpaceError("model snapshot count, row count, or digest mismatch")
        return model


def _validate_digest(value: Any, label: str) -> str:
    """Validate one lowercase SHA-256 hexadecimal digest.
Mathematics: this callable implements the deterministic mapping or invariant stated in its contract, over the explicitly validated input domain.
"""
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise TransitionSpaceError(f"{label} must be a lowercase SHA-256 digest")
    return value


def compile_transition_table(
    table: FiniteTransitionTable,
    *,
    architecture: Sequence[int] | None = None,
) -> TransitionReLUNetwork:
    """Compile a total Boolean transition table into exact ReLU minterm weights.
Mathematics: this callable implements the deterministic mapping or invariant stated in its contract, over the explicitly validated input domain.

    For table row r, its hidden unit is:
        h_r(x) = ReLU(sum_i (x_i if r_i=1 else 1-x_i) - (n-1)).
    This equals one on row r and zero on every other Boolean row. The output
    layer sums the minterms whose table output bit is one.
    """
    if not isinstance(table, FiniteTransitionTable):
        raise TransitionSpaceError("table must be a FiniteTransitionTable")
    input_width = len(table.input_names)
    output_width = len(table.output_names)
    row_count = table.row_count
    selected = tuple(architecture) if architecture is not None else (
        input_width,
        row_count,
        output_width,
    )
    if (
        len(selected) < 3
        or selected[0] != input_width
        or selected[-1] != output_width
        or any(width != row_count for width in selected[1:-1])
    ):
        raise TransitionSpaceError(
            "architecture must use one hidden neuron per table row in every hidden layer"
        )

    weights: list[list[list[float]]] = []
    biases: list[list[float]] = []

    first_matrix = []
    first_bias = []
    for row in table.rows:
        first_matrix.append([1.0 if bit else -1.0 for bit in row.inputs])
        first_bias.append(float(1 - sum(row.inputs)))
    weights.append(first_matrix)
    biases.append(first_bias)

    for _ in range(len(selected) - 3):
        identity = [
            [1.0 if output_index == input_index else 0.0 for input_index in range(row_count)]
            for output_index in range(row_count)
        ]
        weights.append(identity)
        biases.append([0.0] * row_count)

    output_matrix = [
        [float(row.outputs[output_index]) for row in table.rows]
        for output_index in range(output_width)
    ]
    weights.append(output_matrix)
    biases.append([0.0] * output_width)

    model = TransitionReLUNetwork(
        weights,
        biases,
        table_digest=table.digest,
        input_names=table.input_names,
        output_names=table.output_names,
        architecture=selected,
    )
    for row in table.rows:
        if model.predict(row.inputs) != row.outputs:
            raise TransitionSpaceError("compiled model failed its table construction invariant")
    return model


def apply_table_intervention(
    model: TransitionReLUNetwork,
    source_table: FiniteTransitionTable,
    target_table: FiniteTransitionTable,
) -> TransitionWeightIntervention:
    """Edit only output-layer weights corresponding to rows changed in a target table.
Mathematics: this callable implements the deterministic mapping or invariant stated in its contract, over the explicitly validated input domain.
"""
    if not isinstance(model, TransitionReLUNetwork):
        raise TransitionSpaceError("model must be a TransitionReLUNetwork")
    if not isinstance(source_table, FiniteTransitionTable) or not isinstance(
        target_table, FiniteTransitionTable
    ):
        raise TransitionSpaceError("source and target must be finite transition tables")
    if model.table_digest != source_table.digest:
        raise TransitionSpaceError("model is not compiled from the supplied source table")
    if (
        source_table.input_names != target_table.input_names
        or source_table.output_names != target_table.output_names
        or tuple(row.inputs for row in source_table.rows)
        != tuple(row.inputs for row in target_table.rows)
    ):
        raise TransitionSpaceError("table intervention must preserve the input/output interface")
    canonical = compile_transition_table(
        source_table,
        architecture=model.architecture,
    )
    if model.weights != canonical.weights or model.biases != canonical.biases:
        raise TransitionSpaceError("model tensors no longer match their source table")

    source_model_digest = model.digest
    output_layer_index = len(model._weights) - 1
    coordinates: list[TransitionWeightCoordinate] = []
    for row_index, (source_row, target_row) in enumerate(
        zip(source_table.rows, target_table.rows)
    ):
        for output_index, target_bit in enumerate(target_row.outputs):
            if source_row.outputs[output_index] == target_bit:
                continue
            model._weights[output_layer_index][output_index][row_index] = float(target_bit)
            coordinates.append(
                TransitionWeightCoordinate(
                    output_layer_index,
                    output_index,
                    row_index,
                )
            )
    model._table_digest = target_table.digest
    return TransitionWeightIntervention(
        source_table_digest=source_table.digest,
        target_table_digest=target_table.digest,
        source_model_digest=source_model_digest,
        target_model_digest=model.digest,
        changed_parameters=len(coordinates),
        coordinates=tuple(coordinates),
    )


def compile_transition_program(table: FiniteTransitionTable) -> Program:
    """Compile a finite table to a MailCPU program using Boolean minterm branches.
Mathematics: this callable implements the deterministic mapping or invariant stated in its contract, over the explicitly validated input domain.

    Each input row gets one conjunction of literals. Exactly one conjunction is
    true on each valid Boolean input, so its branch selects the row's output block.
    """
    if not isinstance(table, FiniteTransitionTable):
        raise TransitionSpaceError("table must be a FiniteTransitionTable")
    instructions: list[Instruction] = [
        Instruction(Op.SET, ("transition_one", 1)),
        Instruction(Op.SET, ("transition_minus_one", -1)),
    ]
    complements: dict[str, str] = {}
    for name in table.input_names:
        negative = f"transition_negative_{name}"
        complement = f"transition_not_{name}"
        complements[name] = complement
        instructions.append(
            Instruction(Op.MUL, (negative, name, "transition_minus_one"))
        )
        instructions.append(
            Instruction(Op.ADD, (complement, negative, "transition_one"))
        )

    branch_positions: list[tuple[int, str]] = []
    for row_index, row in enumerate(table.rows):
        literals = [
            name if bit else complements[name]
            for name, bit in zip(table.input_names, row.inputs)
        ]
        match_register = f"transition_match_{row_index}"
        instructions.append(Instruction(Op.COPY, (match_register, literals[0])))
        for literal in literals[1:]:
            instructions.append(
                Instruction(Op.MUL, (match_register, match_register, literal))
            )
        branch_positions.append((len(instructions), match_register))
        instructions.append(Instruction(Op.BRANCH, (match_register, -1)))

    default_target = len(instructions)
    for name in table.output_names:
        instructions.append(Instruction(Op.SET, (name, 0)))
    instructions.append(Instruction(Op.HALT))

    row_targets: list[int] = []
    for row in table.rows:
        row_targets.append(len(instructions))
        for name, bit in zip(table.output_names, row.outputs):
            instructions.append(Instruction(Op.SET, (name, bit)))
        instructions.append(Instruction(Op.HALT))

    for (branch_position, match_register), target in zip(branch_positions, row_targets):
        instructions[branch_position] = Instruction(
            Op.BRANCH,
            (match_register, target),
        )
    if default_target >= len(instructions):
        raise TransitionSpaceError("internal compiler error: missing default output block")
    return Program(tuple(instructions))


@dataclass(frozen=True, slots=True)
class BooleanInput:
    """Reference one named Boolean input in a compositional transition expression.
Mathematics: this callable implements the deterministic mapping or invariant stated in its contract, over the explicitly validated input domain.
"""

    name: str

    def __post_init__(self) -> None:
        """Require an input identifier that cannot collide with compiler temporaries.
Mathematics: this callable implements the deterministic mapping or invariant stated in its contract, over the explicitly validated input domain.
"""
        if (
            not isinstance(self.name, str)
            or _IDENTIFIER.fullmatch(self.name) is None
            or self.name.startswith(_INTERNAL_PREFIX)
        ):
            raise TransitionSpaceError("BooleanInput name must be a safe non-reserved identifier")


@dataclass(frozen=True, slots=True)
class BooleanConstant:
    """Represent one literal Boolean constant.
Mathematics: this callable implements the deterministic mapping or invariant stated in its contract, over the explicitly validated input domain.
"""

    value: int

    def __post_init__(self) -> None:
        """Normalize the constant to an immutable bit.
Mathematics: this callable implements the deterministic mapping or invariant stated in its contract, over the explicitly validated input domain.
"""
        object.__setattr__(self, "value", _bit(self.value, "Boolean constant"))


@dataclass(frozen=True, slots=True)
class BooleanNot:
    """Negate one Boolean expression.
Mathematics: this callable implements the deterministic mapping or invariant stated in its contract, over the explicitly validated input domain.
"""

    value: "BooleanExpr"


@dataclass(frozen=True, slots=True)
class BooleanAnd:
    """Conjoin two Boolean expressions.
Mathematics: this callable implements the deterministic mapping or invariant stated in its contract, over the explicitly validated input domain.
"""

    left: "BooleanExpr"
    right: "BooleanExpr"


@dataclass(frozen=True, slots=True)
class BooleanXor:
    """Exclusive-or two Boolean expressions.
Mathematics: this callable implements the deterministic mapping or invariant stated in its contract, over the explicitly validated input domain.
"""

    left: "BooleanExpr"
    right: "BooleanExpr"


@dataclass(frozen=True, slots=True)
class BooleanSelect:
    """Select one expression when a condition is one and another when it is zero.
Mathematics: this callable implements the deterministic mapping or invariant stated in its contract, over the explicitly validated input domain.
"""

    condition: "BooleanExpr"
    when_one: "BooleanExpr"
    when_zero: "BooleanExpr"


BooleanExpr = (
    BooleanInput
    | BooleanConstant
    | BooleanNot
    | BooleanAnd
    | BooleanXor
    | BooleanSelect
)


def _boolean_expression_inputs(expression: BooleanExpr) -> set[str]:
    """Collect all input identifiers referenced by one typed Boolean expression.
Mathematics: this callable implements the deterministic mapping or invariant stated in its contract, over the explicitly validated input domain.
"""
    if isinstance(expression, BooleanInput):
        return {expression.name}
    if isinstance(expression, BooleanConstant):
        return set()
    if isinstance(expression, BooleanNot):
        return _boolean_expression_inputs(expression.value)
    if isinstance(expression, (BooleanAnd, BooleanXor)):
        return (
            _boolean_expression_inputs(expression.left)
            | _boolean_expression_inputs(expression.right)
        )
    if isinstance(expression, BooleanSelect):
        return (
            _boolean_expression_inputs(expression.condition)
            | _boolean_expression_inputs(expression.when_one)
            | _boolean_expression_inputs(expression.when_zero)
        )
    raise TransitionSpaceError(
        f"unsupported Boolean expression type: {type(expression).__name__}"
    )


def _evaluate_boolean_expression(
    expression: BooleanExpr,
    environment: Mapping[str, int],
) -> int:
    """Evaluate one typed Boolean expression against a complete bit environment.
Mathematics: this callable implements the deterministic mapping or invariant stated in its contract, over the explicitly validated input domain.
"""
    if isinstance(expression, BooleanInput):
        return environment[expression.name]
    if isinstance(expression, BooleanConstant):
        return expression.value
    if isinstance(expression, BooleanNot):
        return 1 - _evaluate_boolean_expression(expression.value, environment)
    if isinstance(expression, BooleanAnd):
        return (
            _evaluate_boolean_expression(expression.left, environment)
            & _evaluate_boolean_expression(expression.right, environment)
        )
    if isinstance(expression, BooleanXor):
        return (
            _evaluate_boolean_expression(expression.left, environment)
            ^ _evaluate_boolean_expression(expression.right, environment)
        )
    if isinstance(expression, BooleanSelect):
        condition = _evaluate_boolean_expression(expression.condition, environment)
        selected = expression.when_one if condition else expression.when_zero
        return _evaluate_boolean_expression(selected, environment)
    raise TransitionSpaceError(
        f"unsupported Boolean expression type: {type(expression).__name__}"
    )


def _boolean_expression_to_dict(expression: BooleanExpr) -> dict[str, Any]:
    """Serialize one typed Boolean expression as its versioned algebra node.
Mathematics: this callable implements the deterministic mapping or invariant stated in its contract, over the explicitly validated input domain.
"""
    if isinstance(expression, BooleanInput):
        return {"type": "input", "name": expression.name}
    if isinstance(expression, BooleanConstant):
        return {"type": "constant", "value": expression.value}
    if isinstance(expression, BooleanNot):
        return {
            "type": "not",
            "value": _boolean_expression_to_dict(expression.value),
        }
    if isinstance(expression, BooleanAnd):
        return {
            "type": "and",
            "left": _boolean_expression_to_dict(expression.left),
            "right": _boolean_expression_to_dict(expression.right),
        }
    if isinstance(expression, BooleanXor):
        return {
            "type": "xor",
            "left": _boolean_expression_to_dict(expression.left),
            "right": _boolean_expression_to_dict(expression.right),
        }
    if isinstance(expression, BooleanSelect):
        return {
            "type": "select",
            "condition": _boolean_expression_to_dict(expression.condition),
            "when_one": _boolean_expression_to_dict(expression.when_one),
            "when_zero": _boolean_expression_to_dict(expression.when_zero),
        }
    raise TransitionSpaceError(
        f"unsupported Boolean expression type: {type(expression).__name__}"
    )


def _boolean_expression_from_dict(payload: Any) -> BooleanExpr:
    """Restore one Boolean expression only from the exact fields of its node type.
Mathematics: this callable implements the deterministic mapping or invariant stated in its contract, over the explicitly validated input domain.
"""
    if not isinstance(payload, Mapping) or "type" not in payload:
        raise TransitionSpaceError("Boolean expression nodes must be typed objects")
    kind = payload["type"]
    if kind == "input":
        if set(payload) != {"type", "name"}:
            raise TransitionSpaceError("Boolean input node fields are invalid")
        return BooleanInput(payload["name"])
    if kind == "constant":
        if set(payload) != {"type", "value"}:
            raise TransitionSpaceError("Boolean constant node fields are invalid")
        return BooleanConstant(payload["value"])
    if kind == "not":
        if set(payload) != {"type", "value"}:
            raise TransitionSpaceError("Boolean not node fields are invalid")
        return BooleanNot(_boolean_expression_from_dict(payload["value"]))
    if kind in ("and", "xor"):
        if set(payload) != {"type", "left", "right"}:
            raise TransitionSpaceError("Boolean binary node fields are invalid")
        node = BooleanAnd if kind == "and" else BooleanXor
        return node(
            _boolean_expression_from_dict(payload["left"]),
            _boolean_expression_from_dict(payload["right"]),
        )
    if kind == "select":
        if set(payload) != {"type", "condition", "when_one", "when_zero"}:
            raise TransitionSpaceError("Boolean select node fields are invalid")
        return BooleanSelect(
            _boolean_expression_from_dict(payload["condition"]),
            _boolean_expression_from_dict(payload["when_one"]),
            _boolean_expression_from_dict(payload["when_zero"]),
        )
    raise TransitionSpaceError(f"unknown Boolean expression type: {kind!r}")


@dataclass(frozen=True, slots=True)
class FiniteTransitionProgram:
    """Compositional typed Boolean source program for a finite-state transition.
Mathematics: this callable implements the deterministic mapping or invariant stated in its contract, over the explicitly validated input domain.
"""

    name: str
    input_names: tuple[str, ...]
    output_names: tuple[str, ...]
    output_expressions: tuple[BooleanExpr, ...]

    def __post_init__(self) -> None:
        """Validate output expressions, declared inputs, and the complete name interface.
Mathematics: this callable implements the deterministic mapping or invariant stated in its contract, over the explicitly validated input domain.
"""
        if not isinstance(self.name, str) or not self.name.strip():
            raise TransitionSpaceError("transition program name must be nonempty")
        input_names = _names(self.input_names, "input_names")
        output_names = _names(self.output_names, "output_names")
        if set(input_names) & set(output_names):
            raise TransitionSpaceError("input and output names must be disjoint")
        if len(input_names) > 8:
            raise TransitionSpaceError("transition programs are bounded to at most eight input bits")
        expressions = tuple(self.output_expressions)
        if len(expressions) != len(output_names):
            raise TransitionSpaceError("output expression count must match output names")
        referenced: set[str] = set()
        for expression in expressions:
            referenced.update(_boolean_expression_inputs(expression))
        missing = referenced - set(input_names)
        if missing:
            raise TransitionSpaceError(
                f"transition expressions reference undeclared inputs: {sorted(missing)}"
            )
        object.__setattr__(self, "input_names", input_names)
        object.__setattr__(self, "output_names", output_names)
        object.__setattr__(self, "output_expressions", expressions)

    @property
    def digest(self) -> str:
        """Return SHA-256 identity of the canonical typed transition program.
Mathematics: this callable implements the deterministic mapping or invariant stated in its contract, over the explicitly validated input domain.
"""
        encoded = json.dumps(
            self.to_dict(),
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def evaluate(self, inputs: Sequence[int] | Mapping[str, int]) -> tuple[int, ...]:
        """Evaluate the transition expressions for one complete Boolean input vector.
Mathematics: this callable implements the deterministic mapping or invariant stated in its contract, over the explicitly validated input domain.
"""
        if isinstance(inputs, Mapping):
            if set(inputs) != set(self.input_names):
                raise TransitionSpaceError("input mapping must match the declared input names")
            values = {
                name: _bit(inputs[name], f"input {name}")
                for name in self.input_names
            }
        else:
            pattern = tuple(_bit(value, "transition input") for value in inputs)
            if len(pattern) != len(self.input_names):
                raise TransitionSpaceError("input vector width does not match transition program")
            values = dict(zip(self.input_names, pattern))
        return tuple(
            _evaluate_boolean_expression(expression, values)
            for expression in self.output_expressions
        )

    def with_row_output(
        self,
        inputs: Sequence[int],
        outputs: Sequence[int],
        *,
        name: str | None = None,
    ) -> "FiniteTransitionProgram":
        """Compose a one-row override around the existing output expressions.
Mathematics: this callable implements the deterministic mapping or invariant stated in its contract, over the explicitly validated input domain.
"""
        pattern = tuple(_bit(value, "transition input") for value in inputs)
        output_pattern = tuple(_bit(value, "transition output") for value in outputs)
        if len(pattern) != len(self.input_names):
            raise TransitionSpaceError("override input width does not match transition program")
        if len(output_pattern) != len(self.output_names):
            raise TransitionSpaceError("override output width does not match transition program")

        literals: list[BooleanExpr] = []
        for input_name, expected_bit in zip(self.input_names, pattern):
            literal: BooleanExpr = BooleanInput(input_name)
            if not expected_bit:
                literal = BooleanNot(literal)
            literals.append(literal)
        match = literals[0]
        for literal in literals[1:]:
            match = BooleanAnd(match, literal)

        current_outputs = self.evaluate(pattern)
        expressions = tuple(
            expression
            if current_bit == target_bit
            else BooleanSelect(match, BooleanConstant(target_bit), expression)
            for expression, current_bit, target_bit in zip(
                self.output_expressions,
                current_outputs,
                output_pattern,
            )
        )
        return FiniteTransitionProgram(
            name or f"{self.name}.row-override",
            self.input_names,
            self.output_names,
            expressions,
        )

    def to_table(self) -> FiniteTransitionTable:
        """Enumerate the compositional program over every Boolean input pattern.
Mathematics: this callable implements the deterministic mapping or invariant stated in its contract, over the explicitly validated input domain.
"""
        rows = tuple(
            TransitionRow(pattern, self.evaluate(pattern))
            for pattern in itertools.product((0, 1), repeat=len(self.input_names))
        )
        return FiniteTransitionTable(
            self.name,
            self.input_names,
            self.output_names,
            rows,
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize the typed transition program and its ordered outputs.
Mathematics: this callable implements the deterministic mapping or invariant stated in its contract, over the explicitly validated input domain.
"""
        return {
            "schema": "mailcpu.finite-transition-program.v1",
            "name": self.name,
            "input_names": list(self.input_names),
            "output_names": list(self.output_names),
            "outputs": [
                {
                    "name": name,
                    "expression": _boolean_expression_to_dict(expression),
                }
                for name, expression in zip(self.output_names, self.output_expressions)
            ],
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "FiniteTransitionProgram":
        """Restore a typed transition program from the exact versioned schema.
Mathematics: this callable implements the deterministic mapping or invariant stated in its contract, over the explicitly validated input domain.
"""
        required = {"schema", "name", "input_names", "output_names", "outputs"}
        if not isinstance(payload, Mapping) or set(payload) != required:
            raise TransitionSpaceError("transition program fields do not match the schema")
        if payload["schema"] != "mailcpu.finite-transition-program.v1":
            raise TransitionSpaceError("unsupported transition program schema")
        outputs = payload["outputs"]
        output_names = tuple(payload["output_names"])
        if not isinstance(outputs, list) or len(outputs) != len(output_names):
            raise TransitionSpaceError("transition program output entries are invalid")
        expressions = []
        for expected_name, item in zip(output_names, outputs):
            if (
                not isinstance(item, Mapping)
                or set(item) != {"name", "expression"}
                or item["name"] != expected_name
            ):
                raise TransitionSpaceError("transition program output name/order is invalid")
            expressions.append(_boolean_expression_from_dict(item["expression"]))
        return cls(
            payload["name"],
            tuple(payload["input_names"]),
            output_names,
            tuple(expressions),
        )


def two_bit_counter_program() -> FiniteTransitionProgram:
    """Declare the reset-dominant two-bit counter compositionally, without row enumeration.
Mathematics: this callable implements the deterministic mapping or invariant stated in its contract, over the explicitly validated input domain.

    The next high bit is state_1 XOR state_0 when advancing; the next low bit
    is NOT state_0. Reset dominates advance, and the no-action path holds.
    """
    state_1 = BooleanInput("state_1")
    state_0 = BooleanInput("state_0")
    advance = BooleanInput("advance")
    reset = BooleanInput("reset")
    zero = BooleanConstant(0)
    next_state_1 = BooleanSelect(
        reset,
        zero,
        BooleanSelect(advance, BooleanXor(state_1, state_0), state_1),
    )
    next_state_0 = BooleanSelect(
        reset,
        zero,
        BooleanSelect(advance, BooleanNot(state_0), state_0),
    )
    return FiniteTransitionProgram(
        "two-bit-counter.reset-dominant.v1",
        ("state_1", "state_0", "advance", "reset"),
        ("next_state_1", "next_state_0"),
        (next_state_1, next_state_0),
    )


def _boolean_expression_children(expression: BooleanExpr) -> tuple[BooleanExpr, ...]:
    """Return the ordered child expressions of one non-leaf Boolean AST node.
Mathematics: this callable implements the deterministic mapping or invariant stated in its contract, over the explicitly validated input domain.
"""
    if isinstance(expression, (BooleanInput, BooleanConstant)):
        return ()
    if isinstance(expression, BooleanNot):
        return (expression.value,)
    if isinstance(expression, (BooleanAnd, BooleanXor)):
        return (expression.left, expression.right)
    if isinstance(expression, BooleanSelect):
        return (expression.condition, expression.when_one, expression.when_zero)
    raise TransitionSpaceError(
        f"unsupported Boolean expression type: {type(expression).__name__}"
    )


def _boolean_expression_key(expression: BooleanExpr) -> str:
    """Return the canonical structural key used to hash-cons repeated AST nodes.
Mathematics: this callable implements the deterministic mapping or invariant stated in its contract, over the explicitly validated input domain.
"""
    return json.dumps(
        _boolean_expression_to_dict(expression),
        sort_keys=True,
        separators=(",", ":"),
    )


def _literal_conjunction(
    expression: BooleanExpr,
) -> tuple[tuple[str, int], ...] | None:
    """Flatten an AND tree only when every leaf is a named input or its negation.
Mathematics: this callable implements the deterministic mapping or invariant stated in its contract, over the explicitly validated input domain.
"""
    if isinstance(expression, BooleanInput):
        return ((expression.name, 1),)
    if isinstance(expression, BooleanNot) and isinstance(expression.value, BooleanInput):
        return ((expression.value.name, 0),)
    if not isinstance(expression, BooleanAnd):
        return None
    left = _literal_conjunction(expression.left)
    right = _literal_conjunction(expression.right)
    if left is None or right is None:
        return None
    names = [name for name, _ in (*left, *right)]
    if len(set(names)) != len(names):
        return None
    return left + right


class CompositionalTransitionReLUNetwork:
    """ReLU network compiled from shared Boolean expression nodes rather than truth-table rows.
Mathematics: this callable implements the deterministic mapping or invariant stated in its contract, over the explicitly validated input domain.
"""

    def __init__(
        self,
        weights: Sequence[Sequence[Sequence[float]]],
        biases: Sequence[Sequence[float]],
        *,
        program_digest: str,
        input_names: Sequence[str],
        output_names: Sequence[str],
        architecture: Sequence[int],
    ) -> None:
        """Copy tensors and validate their exact dimensions and source-program identity.
Mathematics: this callable implements the deterministic mapping or invariant stated in its contract, over the explicitly validated input domain.
"""
        self._weights = [
            [[_finite_number(value, "weight") for value in row] for row in layer]
            for layer in weights
        ]
        self._biases = [
            [_finite_number(value, "bias") for value in layer]
            for layer in biases
        ]
        self._program_digest = _validate_digest(program_digest, "program_digest")
        self._input_names = _names(input_names, "input_names")
        self._output_names = _names(output_names, "output_names")
        self._architecture = tuple(architecture)
        self._validate_shape()

    def _validate_shape(self) -> None:
        """Require one dense tensor pair for every transition between declared layers.
Mathematics: this callable implements the deterministic mapping or invariant stated in its contract, over the explicitly validated input domain.
"""
        if (
            len(self._architecture) < 3
            or self._architecture[0] != len(self._input_names)
            or self._architecture[-1] != len(self._output_names)
            or any(type(width) is not int or width < 1 for width in self._architecture)
            or len(self._weights) != len(self._architecture) - 1
            or len(self._biases) != len(self._architecture) - 1
        ):
            raise TransitionSpaceError("compositional model architecture is invalid")
        expected = tuple(zip(self._architecture[:-1], self._architecture[1:]))
        for layer_index, ((input_width, output_width), matrix, bias) in enumerate(
            zip(expected, self._weights, self._biases)
        ):
            if len(matrix) != output_width or len(bias) != output_width:
                raise TransitionSpaceError(f"layer {layer_index} output shape is invalid")
            if any(len(row) != input_width for row in matrix):
                raise TransitionSpaceError(f"layer {layer_index} input shape is invalid")

    @property
    def architecture(self) -> tuple[int, ...]:
        """Return the input, hidden, and output widths of the compositional network.
Mathematics: this callable implements the deterministic mapping or invariant stated in its contract, over the explicitly validated input domain.
"""
        return self._architecture

    @property
    def program_digest(self) -> str:
        """Return the digest of the typed transition program compiled into the weights.
Mathematics: this callable implements the deterministic mapping or invariant stated in its contract, over the explicitly validated input domain.
"""
        return self._program_digest

    @property
    def input_names(self) -> tuple[str, ...]:
        """Return the ordered Boolean input register names.

        Mathematics: input_names is the ordered coordinate basis of the
        transition program's finite Boolean domain.
        """
        return self._input_names

    @property
    def output_names(self) -> tuple[str, ...]:
        """Return the ordered next-state output register names.

        Mathematics: output_names is the ordered coordinate basis of the
        transition program's Boolean result.
        """
        return self._output_names

    @property
    def weights(self) -> tuple[tuple[tuple[float, ...], ...], ...]:
        """Expose immutable output-major copies of the neural weight matrices.
Mathematics: this callable implements the deterministic mapping or invariant stated in its contract, over the explicitly validated input domain.
"""
        return tuple(tuple(tuple(row) for row in layer) for layer in self._weights)

    @property
    def biases(self) -> tuple[tuple[float, ...], ...]:
        """Expose immutable copies of the neural bias vectors.
Mathematics: this callable implements the deterministic mapping or invariant stated in its contract, over the explicitly validated input domain.
"""
        return tuple(tuple(layer) for layer in self._biases)

    @property
    def parameter_count(self) -> int:
        """Count all declared weights and biases, including zero-valued entries.
Mathematics: this callable implements the deterministic mapping or invariant stated in its contract, over the explicitly validated input domain.
"""
        return sum(len(row) for layer in self._weights for row in layer) + sum(
            len(layer) for layer in self._biases
        )

    @property
    def active_parameter_count(self) -> int:
        """Count only nonzero weights and biases in the compositional model.
Mathematics: this callable implements the deterministic mapping or invariant stated in its contract, over the explicitly validated input domain.
"""
        return sum(
            value != 0.0
            for layer in self._weights
            for row in layer
            for value in row
        ) + sum(value != 0.0 for layer in self._biases for value in layer)

    @property
    def digest(self) -> str:
        """Return a content identity over the typed source, architecture, and all parameters.
Mathematics: this callable implements the deterministic mapping or invariant stated in its contract, over the explicitly validated input domain.
"""
        encoded = json.dumps(
            self._payload(),
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def forward(self, inputs: Sequence[int | float]) -> tuple[float, ...]:
        """Evaluate the ReLU hidden layers and linear output for one finite input vector.
Mathematics: this callable implements the deterministic mapping or invariant stated in its contract, over the explicitly validated input domain.
"""
        if len(inputs) != len(self._input_names):
            raise TransitionSpaceError("input vector width does not match the transition program")
        values = [_finite_number(value, "input") for value in inputs]
        for layer_index, (matrix, bias) in enumerate(zip(self._weights, self._biases)):
            next_values = [
                offset + sum(weight * value for weight, value in zip(row, values))
                for row, offset in zip(matrix, bias)
            ]
            values = (
                [max(0.0, value) for value in next_values]
                if layer_index < len(self._weights) - 1
                else next_values
            )
        return tuple(values)

    def predict(self, inputs: Sequence[int]) -> tuple[int, ...]:
        """Evaluate a Boolean transition input and require exact Boolean output bits.
Mathematics: this callable implements the deterministic mapping or invariant stated in its contract, over the explicitly validated input domain.
"""
        pattern = tuple(_bit(value, "transition input") for value in inputs)
        values = self.forward(pattern)
        rounded = tuple(round(value) for value in values)
        if any(
            nearest not in (0, 1)
            or not math.isclose(value, nearest, rel_tol=0.0, abs_tol=1e-12)
            for value, nearest in zip(values, rounded)
        ):
            raise TransitionSpaceError("compositional network output left the Boolean set")
        return tuple(int(value) for value in rounded)

    def _payload(self) -> dict[str, Any]:
        """Build a detached canonical snapshot payload for model provenance.
Mathematics: this callable implements the deterministic mapping or invariant stated in its contract, over the explicitly validated input domain.
"""
        return {
            "schema": "mailcpu.compositional-transition-relu.v1",
            "program_digest": self._program_digest,
            "input_names": list(self._input_names),
            "output_names": list(self._output_names),
            "architecture": list(self._architecture),
            "weights": [[list(row) for row in layer] for layer in self._weights],
            "biases": [list(layer) for layer in self._biases],
            "parameter_count": self.parameter_count,
        }

    def snapshot(self) -> dict[str, Any]:
        """Return a detached model snapshot with its canonical SHA-256 digest.
Mathematics: this callable implements the deterministic mapping or invariant stated in its contract, over the explicitly validated input domain.
"""
        payload = self._payload()
        payload["digest"] = self.digest
        return payload

    @classmethod
    def from_snapshot(
        cls,
        payload: Mapping[str, Any],
    ) -> "CompositionalTransitionReLUNetwork":
        """Restore a compositional network only after strict schema and digest checks.
Mathematics: this callable implements the deterministic mapping or invariant stated in its contract, over the explicitly validated input domain.
"""
        required = {
            "schema",
            "program_digest",
            "input_names",
            "output_names",
            "architecture",
            "weights",
            "biases",
            "parameter_count",
            "digest",
        }
        if not isinstance(payload, Mapping) or set(payload) != required:
            raise TransitionSpaceError("compositional snapshot fields do not match the schema")
        if payload["schema"] != "mailcpu.compositional-transition-relu.v1":
            raise TransitionSpaceError("unsupported compositional network schema")
        model = cls(
            payload["weights"],
            payload["biases"],
            program_digest=payload["program_digest"],
            input_names=payload["input_names"],
            output_names=payload["output_names"],
            architecture=payload["architecture"],
        )
        if (
            type(payload["parameter_count"]) is not int
            or payload["parameter_count"] != model.parameter_count
            or payload["digest"] != model.digest
        ):
            raise TransitionSpaceError("compositional snapshot parameter count or digest mismatch")
        return model


def compile_compositional_transition_program(
    program: FiniteTransitionProgram,
) -> CompositionalTransitionReLUNetwork:
    """Compile the typed Boolean expression DAG directly into layered ReLU weights.
Mathematics: this callable implements the deterministic mapping or invariant stated in its contract, over the explicitly validated input domain.

    Input and prior feature activations are copied forward through each hidden
    layer. NOT, AND, XOR, and SELECT nodes add only the ReLU features needed by
    their own truth conditions. Structurally identical AST nodes are shared.
    This compilation does not allocate one hidden unit per complete input row.
    """
    if not isinstance(program, FiniteTransitionProgram):
        raise TransitionSpaceError("program must be a FiniteTransitionProgram")

    nodes_by_depth: dict[int, set[BooleanExpr]] = {}
    depths: dict[BooleanExpr, int] = {}

    def visit(expression: BooleanExpr) -> int:
        """Collect one shared expression node and return its compositional depth.
Mathematics: this callable implements the deterministic mapping or invariant stated in its contract, over the explicitly validated input domain.
"""
        if isinstance(expression, (BooleanInput, BooleanConstant)):
            return 0
        if expression in depths:
            return depths[expression]
        if isinstance(expression, BooleanAnd) and _literal_conjunction(expression) is not None:
            depth = 1
        else:
            child_depths = tuple(
                visit(child) for child in _boolean_expression_children(expression)
            )
            depth = 1 + max(child_depths, default=0)
        depths[expression] = depth
        nodes_by_depth.setdefault(depth, set()).add(expression)
        return depth

    for expression in program.output_expressions:
        visit(expression)

    input_width = len(program.input_names)
    output_width = len(program.output_names)
    input_indices = {name: index for index, name in enumerate(program.input_names)}
    references: dict[BooleanExpr, tuple[tuple[float, ...], float]] = {}
    weights: list[list[list[float]]] = []
    biases: list[list[float]] = []
    hidden_widths: list[int] = []
    feature_count = 0

    def reference(
        expression: BooleanExpr,
        width: int,
    ) -> tuple[list[float], float]:
        """Return an expression's affine feature representation at the current layer.
Mathematics: this callable implements the deterministic mapping or invariant stated in its contract, over the explicitly validated input domain.
"""
        if isinstance(expression, BooleanInput):
            vector = [0.0] * width
            vector[input_indices[expression.name]] = 1.0
            return vector, 0.0
        if isinstance(expression, BooleanConstant):
            return [0.0] * width, float(expression.value)
        if expression not in references:
            raise TransitionSpaceError("typed expression dependency is not in an earlier layer")
        coefficients, offset = references[expression]
        if len(coefficients) > width:
            raise TransitionSpaceError("internal feature representation exceeds layer width")
        return list(coefficients) + [0.0] * (width - len(coefficients)), offset

    if not nodes_by_depth:
        # A source made only of inputs/constants still gets one identity ReLU layer.
        matrix = [
            [1.0 if row == column else 0.0 for column in range(input_width)]
            for row in range(input_width)
        ]
        weights.append(matrix)
        biases.append([0.0] * input_width)
        hidden_widths.append(input_width)

    for depth in sorted(nodes_by_depth):
        previous_width = input_width + feature_count
        layer_matrix = [
            [1.0 if row == column else 0.0 for column in range(previous_width)]
            for row in range(previous_width)
        ]
        layer_bias = [0.0] * previous_width
        node_references: list[tuple[BooleanExpr, tuple[int, ...]]] = []

        def add_unit(coefficients: Sequence[float], offset: float) -> int:
            """Append one ReLU feature row and return its output coordinate.
Mathematics: this callable implements the deterministic mapping or invariant stated in its contract, over the explicitly validated input domain.
"""
            if len(coefficients) != previous_width:
                raise TransitionSpaceError("internal feature row has the wrong width")
            layer_matrix.append([float(value) for value in coefficients])
            layer_bias.append(float(offset))
            return len(layer_matrix) - 1

        level_nodes = sorted(
            nodes_by_depth[depth],
            key=_boolean_expression_key,
        )
        for expression in level_nodes:
            if isinstance(expression, BooleanNot):
                child, child_bias = reference(expression.value, previous_width)
                index = add_unit([-value for value in child], 1.0 - child_bias)
                node_references.append((expression, (index,)))
                continue

            if isinstance(expression, BooleanAnd):
                literals = _literal_conjunction(expression)
                if literals is not None:
                    coefficients = [0.0] * previous_width
                    positive_count = 0
                    for input_name, expected_bit in literals:
                        input_index = input_indices[input_name]
                        coefficients[input_index] = 1.0 if expected_bit else -1.0
                        positive_count += expected_bit
                    index = add_unit(
                        coefficients,
                        1.0 - positive_count,
                    )
                else:
                    left, left_bias = reference(expression.left, previous_width)
                    right, right_bias = reference(expression.right, previous_width)
                    coefficients = [a + b for a, b in zip(left, right)]
                    index = add_unit(
                        coefficients,
                        left_bias + right_bias - 1.0,
                    )
                node_references.append((expression, (index,)))
                continue

            if isinstance(expression, BooleanXor):
                left, left_bias = reference(expression.left, previous_width)
                right, right_bias = reference(expression.right, previous_width)
                coefficients = [a + b for a, b in zip(left, right)]
                total_bias = left_bias + right_bias
                first = add_unit(coefficients, total_bias)
                second = add_unit(coefficients, total_bias - 1.0)
                node_references.append((expression, (first, second)))
                continue

            if isinstance(expression, BooleanSelect):
                condition, condition_bias = reference(
                    expression.condition,
                    previous_width,
                )
                when_one, when_one_bias = reference(
                    expression.when_one,
                    previous_width,
                )
                when_zero, when_zero_bias = reference(
                    expression.when_zero,
                    previous_width,
                )
                first_coefficients = [
                    a + b for a, b in zip(condition, when_one)
                ]
                second_coefficients = [
                    a - b for a, b in zip(when_zero, condition)
                ]
                first = add_unit(
                    first_coefficients,
                    condition_bias + when_one_bias - 1.0,
                )
                second = add_unit(
                    second_coefficients,
                    when_zero_bias - condition_bias,
                )
                node_references.append((expression, (first, second)))
                continue

            raise TransitionSpaceError(
                f"unsupported computed expression: {type(expression).__name__}"
            )

        current_width = len(layer_matrix)
        for expression, feature_indices in node_references:
            coefficients = [0.0] * current_width
            if isinstance(expression, BooleanXor):
                coefficients[feature_indices[0]] = 1.0
                coefficients[feature_indices[1]] = -2.0
            else:
                for index in feature_indices:
                    coefficients[index] = 1.0
            references[expression] = (tuple(coefficients), 0.0)

        weights.append(layer_matrix)
        biases.append(layer_bias)
        hidden_widths.append(current_width)
        feature_count = current_width - input_width

    final_width = input_width + feature_count
    output_matrix: list[list[float]] = []
    output_bias: list[float] = []
    for expression in program.output_expressions:
        coefficients, offset = reference(expression, final_width)
        output_matrix.append(coefficients)
        output_bias.append(offset)
    weights.append(output_matrix)
    biases.append(output_bias)

    architecture = (input_width, *hidden_widths, output_width)
    model = CompositionalTransitionReLUNetwork(
        weights,
        biases,
        program_digest=program.digest,
        input_names=program.input_names,
        output_names=program.output_names,
        architecture=architecture,
    )
    for pattern in itertools.product((0, 1), repeat=input_width):
        if model.predict(pattern) != program.evaluate(pattern):
            raise TransitionSpaceError("compositional neural compilation failed its finite verification")
    return model


def compile_live_compositional_transition_program(
    program: FiniteTransitionProgram,
) -> CompositionalTransitionReLUNetwork:
    """Compile a Boolean expression DAG with layer-by-layer feature liveness projection.
Mathematics: this callable implements the deterministic mapping or invariant stated in its contract, over the explicitly validated input domain.

    Unlike the dense carry compiler, each hidden layer projects away input values
    and computed features that no future expression or output needs. A feature
    survives only while it is a direct dependency of a later AST node or output.
    """
    if not isinstance(program, FiniteTransitionProgram):
        raise TransitionSpaceError("program must be a FiniteTransitionProgram")

    nodes_by_depth: dict[int, set[BooleanExpr]] = {}
    depths: dict[BooleanExpr, int] = {}

    def visit(expression: BooleanExpr) -> int:
        """Collect computed AST nodes and their topological expression depth.
Mathematics: this callable implements the deterministic mapping or invariant stated in its contract, over the explicitly validated input domain.
"""
        if isinstance(expression, (BooleanInput, BooleanConstant)):
            return 0
        if expression in depths:
            return depths[expression]
        if isinstance(expression, BooleanAnd) and _literal_conjunction(expression) is not None:
            depth = 1
        else:
            child_depths = tuple(
                visit(child) for child in _boolean_expression_children(expression)
            )
            depth = 1 + max(child_depths, default=0)
        depths[expression] = depth
        nodes_by_depth.setdefault(depth, set()).add(expression)
        return depth

    for output in program.output_expressions:
        visit(output)

    input_width = len(program.input_names)
    output_width = len(program.output_names)
    input_names = set(program.input_names)
    input_refs = {name: index for index, name in enumerate(program.input_names)}
    active_refs: dict[BooleanExpr, tuple[tuple[float, ...], float]] = {}
    weights: list[list[list[float]]] = []
    biases: list[list[float]] = []
    hidden_widths: list[int] = []

    def direct_required_inputs(expression: BooleanExpr) -> set[str]:
        """Return raw input names consumed directly by this node's affine construction.
Mathematics: this callable implements the deterministic mapping or invariant stated in its contract, over the explicitly validated input domain.
"""
        literals = _literal_conjunction(expression)
        if literals is not None:
            return {name for name, _ in literals}
        return {
            child.name
            for child in _boolean_expression_children(expression)
            if isinstance(child, BooleanInput)
        }

    def requirements_after(
        depth: int,
    ) -> tuple[set[str], set[BooleanExpr]]:
        """Find raw inputs and computed expressions still needed after this depth.
Mathematics: this callable implements the deterministic mapping or invariant stated in its contract, over the explicitly validated input domain.
"""
        needed_inputs: set[str] = set()
        needed_expressions: set[BooleanExpr] = set()

        for parent_depth, parents in nodes_by_depth.items():
            if parent_depth <= depth:
                continue
            for parent in parents:
                needed_inputs.update(direct_required_inputs(parent))
                for child in _boolean_expression_children(parent):
                    if child in depths and depths[child] <= depth:
                        needed_expressions.add(child)

        for output in program.output_expressions:
            if isinstance(output, BooleanInput):
                needed_inputs.add(output.name)
            elif output in depths and depths[output] <= depth:
                needed_expressions.add(output)

        return needed_inputs, needed_expressions

    def previous_reference(
        expression: BooleanExpr,
        width: int,
    ) -> tuple[list[float], float]:
        """Resolve one expression into affine coordinates of the previous hidden output.
Mathematics: this callable implements the deterministic mapping or invariant stated in its contract, over the explicitly validated input domain.
"""
        if isinstance(expression, BooleanInput):
            if expression.name not in input_refs:
                raise TransitionSpaceError(
                    f"input {expression.name!r} expired before its final use"
                )
            vector = [0.0] * width
            vector[input_refs[expression.name]] = 1.0
            return vector, 0.0
        if isinstance(expression, BooleanConstant):
            return [0.0] * width, float(expression.value)
        if expression not in active_refs:
            raise TransitionSpaceError(
                "computed expression expired before its final dependency"
            )
        coefficients, offset = active_refs[expression]
        if len(coefficients) != width:
            raise TransitionSpaceError("live feature reference has an invalid layer width")
        return list(coefficients), offset

    if not nodes_by_depth:
        # Preserve the minimal input basis for programs whose outputs are only leaves.
        identity = [
            [1.0 if row == column else 0.0 for column in range(input_width)]
            for row in range(input_width)
        ]
        weights.append(identity)
        biases.append([0.0] * input_width)
        hidden_widths.append(input_width)
        current_refs: dict[BooleanExpr, tuple[tuple[float, ...], float]] = {}
        for name, index in input_refs.items():
            vector = [0.0] * input_width
            vector[index] = 1.0
            # Raw inputs are addressed through input_refs, not active_refs.
    else:
        for depth in sorted(nodes_by_depth):
            live_input_names, live_expressions = requirements_after(depth)
            carry_indices: set[int] = set()

            for name in live_input_names:
                if name not in input_refs:
                    raise TransitionSpaceError(
                        f"input {name!r} is not live at the required layer"
                    )
                carry_indices.add(input_refs[name])

            for expression in live_expressions:
                if depths[expression] >= depth:
                    continue
                if expression not in active_refs:
                    raise TransitionSpaceError(
                        "a live expression is missing from the preceding layer"
                    )
                coefficients, _ = active_refs[expression]
                carry_indices.update(
                    index
                    for index, coefficient in enumerate(coefficients)
                    if coefficient != 0.0
                )

            previous_width = (
                hidden_widths[-1] if hidden_widths else input_width
            )
            # Include all needed indices but discard every dead input/feature coordinate.
            ordered_carry = sorted(carry_indices)
            old_to_new = {
                old_index: new_index
                for new_index, old_index in enumerate(ordered_carry)
            }
            layer_matrix = [
                [
                    1.0 if input_index == old_index else 0.0
                    for input_index in range(previous_width)
                ]
                for old_index in ordered_carry
            ]
            layer_bias = [0.0] * len(ordered_carry)
            base_width = len(layer_matrix)

            def add_unit(coefficients: Sequence[float], offset: float) -> int:
                """Append one ReLU feature row over the previous compact layer.
Mathematics: this callable implements the deterministic mapping or invariant stated in its contract, over the explicitly validated input domain.
"""
                if len(coefficients) != previous_width:
                    raise TransitionSpaceError("live feature row has an invalid input width")
                layer_matrix.append([float(value) for value in coefficients])
                layer_bias.append(float(offset))
                return len(layer_matrix) - 1

            node_representations: list[
                tuple[BooleanExpr, tuple[tuple[int, float], ...]]
            ] = []
            level_nodes = sorted(
                nodes_by_depth[depth],
                key=_boolean_expression_key,
            )
            for expression in level_nodes:
                if isinstance(expression, BooleanNot):
                    child, child_bias = previous_reference(
                        expression.value,
                        previous_width,
                    )
                    index = add_unit(
                        [-value for value in child],
                        1.0 - child_bias,
                    )
                    node_representations.append((expression, ((index, 1.0),)))
                    continue

                if isinstance(expression, BooleanAnd):
                    literals = _literal_conjunction(expression)
                    if literals is not None:
                        coefficients = [0.0] * previous_width
                        positive_count = 0
                        for input_name, expected_bit in literals:
                            if input_name not in input_refs:
                                raise TransitionSpaceError(
                                    f"minterm input {input_name!r} is not live"
                                )
                            coefficients[input_refs[input_name]] = (
                                1.0 if expected_bit else -1.0
                            )
                            positive_count += expected_bit
                        index = add_unit(coefficients, 1.0 - positive_count)
                    else:
                        left, left_bias = previous_reference(
                            expression.left,
                            previous_width,
                        )
                        right, right_bias = previous_reference(
                            expression.right,
                            previous_width,
                        )
                        coefficients = [
                            a + b for a, b in zip(left, right)
                        ]
                        index = add_unit(
                            coefficients,
                            left_bias + right_bias - 1.0,
                        )
                    node_representations.append((expression, ((index, 1.0),)))
                    continue

                if isinstance(expression, BooleanXor):
                    left, left_bias = previous_reference(
                        expression.left,
                        previous_width,
                    )
                    right, right_bias = previous_reference(
                        expression.right,
                        previous_width,
                    )
                    coefficients = [
                        a + b for a, b in zip(left, right)
                    ]
                    offset = left_bias + right_bias
                    first = add_unit(coefficients, offset)
                    second = add_unit(coefficients, offset - 1.0)
                    node_representations.append(
                        (expression, ((first, 1.0), (second, -2.0)))
                    )
                    continue

                if isinstance(expression, BooleanSelect):
                    condition, condition_bias = previous_reference(
                        expression.condition,
                        previous_width,
                    )
                    when_one, when_one_bias = previous_reference(
                        expression.when_one,
                        previous_width,
                    )
                    when_zero, when_zero_bias = previous_reference(
                        expression.when_zero,
                        previous_width,
                    )
                    first_coefficients = [
                        a + b for a, b in zip(condition, when_one)
                    ]
                    second_coefficients = [
                        a - b for a, b in zip(when_zero, condition)
                    ]
                    first = add_unit(
                        first_coefficients,
                        condition_bias + when_one_bias - 1.0,
                    )
                    second = add_unit(
                        second_coefficients,
                        when_zero_bias - condition_bias,
                    )
                    node_representations.append(
                        (expression, ((first, 1.0), (second, 1.0)))
                    )
                    continue

                raise TransitionSpaceError(
                    f"unsupported computed expression: {type(expression).__name__}"
                )

            current_width = len(layer_matrix)
            current_refs: dict[BooleanExpr, tuple[tuple[float, ...], float]] = {}

            # Move still-live prior expressions through the selected identity coordinates.
            for expression in live_expressions:
                if depths[expression] >= depth:
                    continue
                coefficients, offset = active_refs[expression]
                compacted = [0.0] * current_width
                for old_index, new_index in old_to_new.items():
                    compacted[new_index] = coefficients[old_index]
                current_refs[expression] = (tuple(compacted), offset)

            # Add the expression nodes produced at the current depth.
            for expression, terms in node_representations:
                coefficients = [0.0] * current_width
                for index, value in terms:
                    coefficients[index] += value
                current_refs[expression] = (tuple(coefficients), 0.0)

            # A newly computed node is retained only if a later expression or output uses it.
            active_refs = {
                expression: current_refs[expression]
                for expression in live_expressions
                if expression in current_refs
            }
            missing_live = live_expressions - set(active_refs)
            if missing_live:
                raise TransitionSpaceError(
                    "feature-liveness pass discarded a required expression"
                )

            input_refs = {
                name: old_to_new[input_refs[name]]
                for name in live_input_names
            }
            weights.append(layer_matrix)
            biases.append(layer_bias)
            hidden_widths.append(current_width)

    final_width = hidden_widths[-1]
    output_matrix: list[list[float]] = []
    output_bias: list[float] = []
    for expression in program.output_expressions:
        if isinstance(expression, BooleanInput):
            if expression.name not in input_refs:
                raise TransitionSpaceError("an input output was not kept live")
            coefficients = [0.0] * final_width
            coefficients[input_refs[expression.name]] = 1.0
            offset = 0.0
        elif isinstance(expression, BooleanConstant):
            coefficients = [0.0] * final_width
            offset = float(expression.value)
        else:
            if expression not in active_refs:
                raise TransitionSpaceError("an output expression was not kept live")
            coefficients_tuple, offset = active_refs[expression]
            coefficients = list(coefficients_tuple)
        output_matrix.append(coefficients)
        output_bias.append(offset)

    weights.append(output_matrix)
    biases.append(output_bias)
    architecture = (input_width, *hidden_widths, output_width)
    model = CompositionalTransitionReLUNetwork(
        weights,
        biases,
        program_digest=program.digest,
        input_names=program.input_names,
        output_names=program.output_names,
        architecture=architecture,
    )
    for pattern in itertools.product((0, 1), repeat=input_width):
        if model.predict(pattern) != program.evaluate(pattern):
            raise TransitionSpaceError(
                "live-feature neural compilation failed its finite verification"
            )
    return model


class SparseTransitionReLUNetwork:
    """Sparse execution realization of an existing exact finite Boolean ReLU model.

    The dense source remains the semantic reference. This representation stores
    only nonzero weights and biases, executes only stored weight products, and
    retains the source Ground digest and dense model digest. It is intended for
    exact finite Boolean transition programs; no continuous-domain or hardware
    performance claim follows from this representation alone.
    """

    SCHEMA = "mailcpu.sparse-transition-relu.v1"

    def __init__(
        self,
        weight_rows: Sequence[Sequence[Sequence[Sequence[int | float]]]],
        bias_entries: Sequence[Sequence[Sequence[int | float]]],
        *,
        source_kind: str,
        source_digest: str,
        source_model_digest: str,
        input_names: Sequence[str],
        output_names: Sequence[str],
        architecture: Sequence[int],
    ) -> None:
        """Mathematics: normalize a sparse output-major tensor and validate its finite layer graph.

        Every stored coordinate is unique, ordered, nonzero, and in range. The
        represented affine map is reconstructed from these sparse coordinates.
        """
        self._source_kind = source_kind
        self._source_digest = _validate_digest(source_digest, "source_digest")
        self._source_model_digest = _validate_digest(
            source_model_digest,
            "source_model_digest",
        )
        self._input_names = _names(input_names, "input_names")
        self._output_names = _names(output_names, "output_names")
        self._architecture = tuple(architecture)

        normalized_rows: list[tuple[tuple[tuple[int, float], ...], ...]] = []
        for layer_index, layer in enumerate(weight_rows):
            normalized_layer: list[tuple[tuple[int, float], ...]] = []
            for output_index, row in enumerate(layer):
                if not isinstance(row, Sequence) or isinstance(row, (str, bytes)):
                    raise TransitionSpaceError(
                        f"sparse weight row {layer_index}:{output_index} must be a sequence"
                    )
                normalized_row: list[tuple[int, float]] = []
                previous_index = -1
                for pair_index, pair in enumerate(row):
                    if (
                        not isinstance(pair, Sequence)
                        or isinstance(pair, (str, bytes))
                        or len(pair) != 2
                    ):
                        raise TransitionSpaceError(
                            f"sparse weight entry {layer_index}:{output_index}:{pair_index} must be an index/value pair"
                        )
                    source_index, raw_weight = pair
                    if type(source_index) is not int or source_index <= previous_index:
                        raise TransitionSpaceError(
                            "sparse weight indices must be strictly increasing integers"
                        )
                    weight = _finite_number(raw_weight, "sparse weight")
                    if weight == 0.0:
                        raise TransitionSpaceError(
                            "sparse weight entries must not store zero coefficients"
                        )
                    normalized_row.append((source_index, weight))
                    previous_index = source_index
                normalized_layer.append(tuple(normalized_row))
            normalized_rows.append(tuple(normalized_layer))

        normalized_biases: list[tuple[tuple[int, float], ...]] = []
        for layer_index, layer in enumerate(bias_entries):
            if not isinstance(layer, Sequence) or isinstance(layer, (str, bytes)):
                raise TransitionSpaceError(
                    f"sparse bias layer {layer_index} must be a sequence"
                )
            normalized_layer: list[tuple[int, float]] = []
            previous_index = -1
            for pair_index, pair in enumerate(layer):
                if (
                    not isinstance(pair, Sequence)
                    or isinstance(pair, (str, bytes))
                    or len(pair) != 2
                ):
                    raise TransitionSpaceError(
                        f"sparse bias entry {layer_index}:{pair_index} must be an index/value pair"
                    )
                output_index, raw_bias = pair
                if type(output_index) is not int or output_index <= previous_index:
                    raise TransitionSpaceError(
                        "sparse bias indices must be strictly increasing integers"
                    )
                bias = _finite_number(raw_bias, "sparse bias")
                if bias == 0.0:
                    raise TransitionSpaceError(
                        "sparse bias entries must not store zero coefficients"
                    )
                normalized_layer.append((output_index, bias))
                previous_index = output_index
            normalized_biases.append(tuple(normalized_layer))

        self._weight_rows = tuple(normalized_rows)
        self._bias_entries = tuple(normalized_biases)
        self._validate_shape()
        self._bias_maps = tuple(dict(layer) for layer in self._bias_entries)

    @classmethod
    def from_dense(
        cls,
        model: TransitionReLUNetwork | CompositionalTransitionReLUNetwork,
    ) -> "SparseTransitionReLUNetwork":
        """Mathematics: convert a dense model into its exact nonzero-coordinate representation.

        The source Ground digest and dense model digest are retained so the
        sparse model remains tied to the exact model from which it was derived.
        """
        if isinstance(model, TransitionReLUNetwork):
            source_kind = "transition_table"
            source_digest = model.table_digest
        elif isinstance(model, CompositionalTransitionReLUNetwork):
            source_kind = "transition_program"
            source_digest = model.program_digest
        else:
            raise TransitionSpaceError(
                "sparse conversion requires a supported dense transition ReLU model"
            )

        weight_rows = [
            [
                [
                    (source_index, weight)
                    for source_index, weight in enumerate(row)
                    if weight != 0.0
                ]
                for row in layer
            ]
            for layer in model.weights
        ]
        bias_entries = [
            [
                (output_index, bias)
                for output_index, bias in enumerate(layer)
                if bias != 0.0
            ]
            for layer in model.biases
        ]
        return cls(
            weight_rows,
            bias_entries,
            source_kind=source_kind,
            source_digest=source_digest,
            source_model_digest=model.digest,
            input_names=model.input_names,
            output_names=model.output_names,
            architecture=model.architecture,
        )

    def _validate_shape(self) -> None:
        """Mathematics: validate that every sparse row index is in [0, layer_input_width).

        Each layer also has exactly one sparse output row and at most one
        nonzero bias entry per declared output coordinate.
        """
        if self._source_kind not in {"transition_table", "transition_program"}:
            raise TransitionSpaceError("sparse source_kind is unsupported")
        if (
            len(self._architecture) < 3
            or any(type(width) is not int or width < 1 for width in self._architecture)
            or self._architecture[0] != len(self._input_names)
            or self._architecture[-1] != len(self._output_names)
            or len(self._weight_rows) != len(self._architecture) - 1
            or len(self._bias_entries) != len(self._architecture) - 1
        ):
            raise TransitionSpaceError("sparse model architecture is invalid")

        for layer_index, (input_width, output_width) in enumerate(
            zip(self._architecture[:-1], self._architecture[1:])
        ):
            rows = self._weight_rows[layer_index]
            biases = self._bias_entries[layer_index]
            if len(rows) != output_width:
                raise TransitionSpaceError(
                    f"sparse layer {layer_index} output row count is invalid"
                )
            for output_index, row in enumerate(rows):
                if any(source_index >= input_width for source_index, _ in row):
                    raise TransitionSpaceError(
                        f"sparse layer {layer_index} row {output_index} references an out-of-range input"
                    )
            if any(output_index >= output_width for output_index, _ in biases):
                raise TransitionSpaceError(
                    f"sparse layer {layer_index} contains an out-of-range bias index"
                )

    @property
    def source_kind(self) -> str:
        """Mathematics: source_kind ∈ {transition_table, transition_program}.

        Return which declared Ground representation supplies the sparse model.
        """
        return self._source_kind

    @property
    def source_digest(self) -> str:
        """Mathematics: source_digest = SHA256(canonical(source Ground)).

        Return the identity of the exact finite transition description.
        """
        return self._source_digest

    @property
    def source_model_digest(self) -> str:
        """Mathematics: source_model_digest = SHA256(canonical(dense model)).

        Return the identity of the dense realization from which this sparse
        representation was derived.
        """
        return self._source_model_digest

    @property
    def input_names(self) -> tuple[str, ...]:
        """Mathematics: input_names is the ordered coordinate basis of {0,1}^n.

        Return the transition input register names.
        """
        return self._input_names

    @property
    def output_names(self) -> tuple[str, ...]:
        """Mathematics: output_names is the ordered coordinate basis of {0,1}^m.

        Return the next-state output register names.
        """
        return self._output_names

    @property
    def architecture(self) -> tuple[int, ...]:
        """Mathematics: architecture = (n_0, n_1, ..., n_L).

        Return every dense-equivalent layer width, including input and output.
        """
        return self._architecture

    @property
    def sparse_weights(self) -> tuple[tuple[tuple[tuple[int, float], ...], ...], ...]:
        """Mathematics: E_j contains the ordered nonzero (i,w) coordinates for output j.

        Return immutable output-major sparse weight rows.
        """
        return self._weight_rows

    @property
    def sparse_biases(self) -> tuple[tuple[tuple[int, float], ...], ...]:
        """Mathematics: B_l is the ordered set of nonzero (j,b_j) bias coordinates.

        Return immutable sparse bias entries by layer.
        """
        return self._bias_entries

    @property
    def stored_weight_count(self) -> int:
        """Mathematics: stored_weight_count = Σ_l Σ_j |E_j^(l)|.

        Count the nonzero weight coordinates stored in all layers.
        """
        return sum(
            len(row)
            for layer in self._weight_rows
            for row in layer
        )

    @property
    def stored_bias_count(self) -> int:
        """Mathematics: stored_bias_count = Σ_l |B_l|.

        Count the nonzero bias coordinates stored in all layers.
        """
        return sum(len(layer) for layer in self._bias_entries)

    @property
    def stored_parameter_count(self) -> int:
        """Mathematics: stored_parameter_count = stored_weight_count + stored_bias_count.

        Only explicitly serialized nonzero scalar parameters are counted.
        """
        return self.stored_weight_count + self.stored_bias_count

    @property
    def parameter_count(self) -> int:
        """Mathematics: parameter_count is the stored sparse scalar parameter count.

        This deliberately differs from dense-equivalent parameter slots.
        """
        return self.stored_parameter_count

    @property
    def dense_weight_slot_count(self) -> int:
        """Mathematics: dense_weight_slot_count = Σ_l n_(l-1) * n_l.

        Count every weight position in the equivalent dense layer matrices.
        """
        return sum(
            input_width * output_width
            for input_width, output_width in zip(
                self._architecture[:-1],
                self._architecture[1:],
            )
        )

    @property
    def dense_equivalent_parameter_count(self) -> int:
        """Mathematics: dense_equivalent_parameter_count = dense_weight_slots + Σ_l n_l.

        Count all dense weight and bias positions, including implicit zeros.
        """
        return self.dense_weight_slot_count + sum(self._architecture[1:])

    @property
    def active_parameter_count(self) -> int:
        """Mathematics: active_parameter_count = stored_weight_count + stored_bias_count.

        Return the number of stored nonzero weights and biases.
        """
        return self.stored_parameter_count

    @property
    def digest(self) -> str:
        """Mathematics: digest = SHA256(canonical(_payload())).

        Return a SHA-256 identity over source provenance and sparse tensors.
        """
        encoded = json.dumps(
            self._payload(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @property
    def operation_profile(self) -> dict[str, int]:
        """Mathematics: D_mul = N_dense_weights and S_mul = N_nonzero_weights.

        Dense and sparse additions follow the current Python sum plus bias
        combination: each nonempty sparse row uses one addition per stored
        coefficient, while an empty row still combines bias with zero.

        The current dense forward performs one multiplication and one sum
        accumulation per dense weight slot. The sparse forward skips zero
        weights. For each output neuron it still combines its bias with the
        sparse sum, so an all-zero row requires one addition.
        """
        dense_multiply_count = self.dense_weight_slot_count
        sparse_multiply_count = self.stored_weight_count
        dense_addition_count = dense_multiply_count
        sparse_addition_count = sum(
            max(1, len(row))
            for layer in self._weight_rows
            for row in layer
        )
        relu_count = sum(self._architecture[1:-1])
        return {
            "dense_weight_multiply_count": dense_multiply_count,
            "sparse_weight_multiply_count": sparse_multiply_count,
            "dense_accumulator_addition_count": dense_addition_count,
            "sparse_accumulator_addition_count": sparse_addition_count,
            "dense_relu_count": relu_count,
            "sparse_relu_count": relu_count,
        }

    def forward(self, inputs: Sequence[int | float]) -> tuple[float, ...]:
        """Mathematics: z_j = b_j + sum_(i,w in E_j)(w*a_i), skipping zero edges.

        Evaluate each hidden ReLU layer and leave the final layer linear.
        """
        if len(inputs) != len(self._input_names):
            raise TransitionSpaceError(
                "input vector width does not match the sparse transition model"
            )
        values = [_finite_number(value, "input") for value in inputs]
        for layer_index, rows in enumerate(self._weight_rows):
            bias_map = self._bias_maps[layer_index]
            next_values = [
                bias_map.get(output_index, 0.0)
                + sum(weight * values[source_index] for source_index, weight in row)
                for output_index, row in enumerate(rows)
            ]
            values = (
                [max(0.0, value) for value in next_values]
                if layer_index < len(self._weight_rows) - 1
                else next_values
            )
        return tuple(values)

    def predict(self, inputs: Sequence[int]) -> tuple[int, ...]:
        """Mathematics: predict(x) is defined only for x in {0,1}^n and requires y in {0,1}^m.

        Reject outputs that are not within the exact Boolean set.
        """
        pattern = tuple(_bit(value, "transition input") for value in inputs)
        values = self.forward(pattern)
        rounded = tuple(round(value) for value in values)
        if any(
            nearest not in (0, 1)
            or not math.isclose(value, nearest, rel_tol=0.0, abs_tol=1e-12)
            for value, nearest in zip(values, rounded)
        ):
            raise TransitionSpaceError(
                "sparse network output left the exact Boolean set"
            )
        return tuple(int(value) for value in rounded)

    def _payload(self) -> dict[str, Any]:
        """Mathematics: _payload is the canonical sparse representation excluding digest.

        Build the canonical sparse schema payload without its digest field.
        """
        return {
            "schema": self.SCHEMA,
            "source_kind": self._source_kind,
            "source_digest": self._source_digest,
            "source_model_digest": self._source_model_digest,
            "input_names": list(self._input_names),
            "output_names": list(self._output_names),
            "architecture": list(self._architecture),
            "layers": [
                {
                    "weight_rows": [
                        [[source_index, weight] for source_index, weight in row]
                        for row in layer
                    ],
                    "bias_entries": [
                        [output_index, bias]
                        for output_index, bias in biases
                    ],
                }
                for layer, biases in zip(self._weight_rows, self._bias_entries)
            ],
            "dense_equivalent_parameter_count": self.dense_equivalent_parameter_count,
            "stored_parameter_count": self.stored_parameter_count,
        }

    def snapshot(self) -> dict[str, Any]:
        """Mathematics: snapshot = _payload() ∪ {digest: SHA256(canonical(_payload()))}.

        Return a detached sparse snapshot with canonical digest and count fields.
        """
        payload = self._payload()
        payload["digest"] = self.digest
        return payload

    @classmethod
    def from_snapshot(
        cls,
        payload: Mapping[str, Any],
    ) -> "SparseTransitionReLUNetwork":
        """Mathematics: restore(payload) is defined only when its digest and counts recompute exactly.

        Restore after checking sparse coordinates, source identity, counts, and digest.
        """
        required = {
            "schema",
            "source_kind",
            "source_digest",
            "source_model_digest",
            "input_names",
            "output_names",
            "architecture",
            "layers",
            "dense_equivalent_parameter_count",
            "stored_parameter_count",
            "digest",
        }
        if not isinstance(payload, Mapping) or set(payload) != required:
            raise TransitionSpaceError(
                "sparse snapshot fields do not match the schema"
            )
        if payload["schema"] != cls.SCHEMA:
            raise TransitionSpaceError("unsupported sparse transition schema")
        layers = payload["layers"]
        if not isinstance(layers, Sequence) or isinstance(layers, (str, bytes)):
            raise TransitionSpaceError("sparse snapshot layers must be a sequence")
        if any(
            not isinstance(layer, Mapping) or set(layer) != {"weight_rows", "bias_entries"}
            for layer in layers
        ):
            raise TransitionSpaceError("sparse snapshot layer fields do not match the schema")
        model = cls(
            [layer["weight_rows"] for layer in layers],
            [layer["bias_entries"] for layer in layers],
            source_kind=payload["source_kind"],
            source_digest=payload["source_digest"],
            source_model_digest=payload["source_model_digest"],
            input_names=payload["input_names"],
            output_names=payload["output_names"],
            architecture=payload["architecture"],
        )
        if (
            type(payload["dense_equivalent_parameter_count"]) is not int
            or payload["dense_equivalent_parameter_count"]
            != model.dense_equivalent_parameter_count
            or type(payload["stored_parameter_count"]) is not int
            or payload["stored_parameter_count"] != model.stored_parameter_count
            or payload["digest"] != model.digest
        ):
            raise TransitionSpaceError(
                "sparse snapshot parameter counts or digest mismatch"
            )
        return model

