"""Constructive ReLU realization of complete finite Boolean transition tables.

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
    """A transition table, neural architecture, snapshot, or intervention violates the finite-table contract."""


def _bit(value: Any, label: str) -> int:
    """Normalize a Boolean bit while rejecting values outside the finite domain."""
    if isinstance(value, bool):
        return int(value)
    if type(value) is int and value in (0, 1):
        return value
    raise TransitionSpaceError(f"{label} must be a Boolean bit (0 or 1)")


def _finite_number(value: Any, label: str) -> float:
    """Validate and normalize one finite scalar in a neural tensor."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TransitionSpaceError(f"{label} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise TransitionSpaceError(f"{label} must be finite")
    return result


def _names(values: Sequence[str], label: str) -> tuple[str, ...]:
    """Validate a nonempty ordered set of safe and unique field names."""
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
    """One complete Boolean input pattern and its corresponding output pattern."""

    inputs: tuple[int, ...]
    outputs: tuple[int, ...]

    def __post_init__(self) -> None:
        """Normalize both sides of a transition row to immutable Boolean tuples."""
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
        """Serialize the input and output bit patterns."""
        return {"inputs": list(self.inputs), "outputs": list(self.outputs)}


@dataclass(frozen=True, slots=True)
class FiniteTransitionTable:
    """A total deterministic Boolean function represented by its complete truth table."""

    name: str
    input_names: tuple[str, ...]
    output_names: tuple[str, ...]
    rows: tuple[TransitionRow, ...]

    def __post_init__(self) -> None:
        """Require every Boolean input pattern exactly once and sort rows canonically."""
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
        """Return the number of fully enumerated Boolean input patterns."""
        return len(self.rows)

    @property
    def digest(self) -> str:
        """Return the SHA-256 identity of the canonical transition-table payload."""
        encoded = json.dumps(
            self.to_dict(),
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def row_index(self, inputs: Sequence[int]) -> int:
        """Find the canonical row index for one validated input bit pattern."""
        pattern = tuple(_bit(value, "transition input") for value in inputs)
        if len(pattern) != len(self.input_names):
            raise TransitionSpaceError("input pattern width does not match the table")
        return pattern_to_index(pattern)

    def row_for(self, inputs: Sequence[int]) -> TransitionRow:
        """Return the declared transition for one exact Boolean input pattern."""
        return self.rows[self.row_index(inputs)]

    def with_output(
        self,
        inputs: Sequence[int],
        outputs: Sequence[int],
        *,
        name: str | None = None,
    ) -> "FiniteTransitionTable":
        """Return a new table with one selected row's output bits replaced."""
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
        """Serialize the table with deterministic field and row ordering."""
        return {
            "schema": "mailcpu.finite-transition-table.v1",
            "name": self.name,
            "input_names": list(self.input_names),
            "output_names": list(self.output_names),
            "rows": [row.to_dict() for row in self.rows],
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "FiniteTransitionTable":
        """Restore a transition table only from the exact declared schema."""
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
    """Interpret an ordered bit pattern as its stable binary row index."""
    result = 0
    for value in pattern:
        result = (result << 1) | _bit(value, "pattern bit")
    return result


def two_bit_counter_table() -> FiniteTransitionTable:
    """Enumerate the typed two-bit counter program into its complete truth table."""
    return two_bit_counter_program().to_table()


@dataclass(frozen=True, slots=True)
class TransitionWeightCoordinate:
    """Identify one output-major neural weight changed by a table intervention."""

    layer_index: int
    output_index: int
    input_index: int

    def to_dict(self) -> dict[str, int]:
        """Serialize the layer, output-neuron, and input-neuron coordinates."""
        return {
            "layer_index": self.layer_index,
            "output_index": self.output_index,
            "input_index": self.input_index,
        }


@dataclass(frozen=True, slots=True)
class TransitionWeightIntervention:
    """Bind a finite-table edit to the exact neural model parameters that changed."""

    source_table_digest: str
    target_table_digest: str
    source_model_digest: str
    target_model_digest: str
    changed_parameters: int
    coordinates: tuple[TransitionWeightCoordinate, ...]

    def to_dict(self) -> dict[str, Any]:
        """Serialize source/target identities and every modified weight coordinate."""
        return {
            "source_table_digest": self.source_table_digest,
            "target_table_digest": self.target_table_digest,
            "source_model_digest": self.source_model_digest,
            "target_model_digest": self.target_model_digest,
            "changed_parameters": self.changed_parameters,
            "coordinates": [item.to_dict() for item in self.coordinates],
        }


class TransitionReLUNetwork:
    """Dense ReLU model whose first hidden layer encodes one minterm per table row."""

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
        """Copy finite tensors and validate them against a complete-table architecture."""
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
        """Require one hidden unit per truth-table row and matching layer tensors."""
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
        """Return the exact layer-width tuple for this finite transition model."""
        return self._architecture

    @property
    def table_digest(self) -> str:
        """Return the digest of the truth table compiled into the current weights."""
        return self._table_digest

    @property
    def input_names(self) -> tuple[str, ...]:
        """Return the ordered transition input register names."""
        return self._input_names

    @property
    def output_names(self) -> tuple[str, ...]:
        """Return the ordered next-state output register names."""
        return self._output_names

    @property
    def weights(self) -> tuple[tuple[tuple[float, ...], ...], ...]:
        """Expose immutable output-major copies of the model weight matrices."""
        return tuple(tuple(tuple(row) for row in layer) for layer in self._weights)

    @property
    def biases(self) -> tuple[tuple[float, ...], ...]:
        """Expose immutable copies of the model bias vectors."""
        return tuple(tuple(layer) for layer in self._biases)

    @property
    def parameter_count(self) -> int:
        """Count all declared weights and biases, including zero-valued entries."""
        return sum(len(row) for layer in self._weights for row in layer) + sum(
            len(layer) for layer in self._biases
        )

    @property
    def active_parameter_count(self) -> int:
        """Count only nonzero weights and biases in the current network."""
        return sum(
            value != 0.0
            for layer in self._weights
            for row in layer
            for value in row
        ) + sum(value != 0.0 for layer in self._biases for value in layer)

    @property
    def digest(self) -> str:
        """Return a SHA-256 identity over architecture, source table, and all tensors."""
        encoded = json.dumps(
            self._payload(),
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def forward(self, inputs: Sequence[int | float]) -> tuple[float, ...]:
        """Evaluate the dense ReLU layers for one correctly sized finite input vector."""
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
        """Evaluate a Boolean transition row and require exact Boolean outputs."""
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
        """Build a detached canonical snapshot payload for content addressing."""
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
        """Return a detached digest-bound model snapshot."""
        payload = self._payload()
        payload["digest"] = self.digest
        return payload

    @classmethod
    def from_snapshot(cls, payload: Mapping[str, Any]) -> "TransitionReLUNetwork":
        """Restore a model only after checking schema, dimensions, counts, and digest."""
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
    """Validate one lowercase SHA-256 hexadecimal digest."""
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
    """Edit only output-layer weights corresponding to rows changed in a target table."""
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
    """Reference one named Boolean input in a compositional transition expression."""

    name: str

    def __post_init__(self) -> None:
        """Require an input identifier that cannot collide with compiler temporaries."""
        if (
            not isinstance(self.name, str)
            or _IDENTIFIER.fullmatch(self.name) is None
            or self.name.startswith(_INTERNAL_PREFIX)
        ):
            raise TransitionSpaceError("BooleanInput name must be a safe non-reserved identifier")


@dataclass(frozen=True, slots=True)
class BooleanConstant:
    """Represent one literal Boolean constant."""

    value: int

    def __post_init__(self) -> None:
        """Normalize the constant to an immutable bit."""
        object.__setattr__(self, "value", _bit(self.value, "Boolean constant"))


@dataclass(frozen=True, slots=True)
class BooleanNot:
    """Negate one Boolean expression."""

    value: "BooleanExpr"


@dataclass(frozen=True, slots=True)
class BooleanAnd:
    """Conjoin two Boolean expressions."""

    left: "BooleanExpr"
    right: "BooleanExpr"


@dataclass(frozen=True, slots=True)
class BooleanXor:
    """Exclusive-or two Boolean expressions."""

    left: "BooleanExpr"
    right: "BooleanExpr"


@dataclass(frozen=True, slots=True)
class BooleanSelect:
    """Select one expression when a condition is one and another when it is zero."""

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
    """Collect all input identifiers referenced by one typed Boolean expression."""
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
    """Evaluate one typed Boolean expression against a complete bit environment."""
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
    """Serialize one typed Boolean expression as its versioned algebra node."""
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
    """Restore one Boolean expression only from the exact fields of its node type."""
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
    """Compositional typed Boolean source program for a finite-state transition."""

    name: str
    input_names: tuple[str, ...]
    output_names: tuple[str, ...]
    output_expressions: tuple[BooleanExpr, ...]

    def __post_init__(self) -> None:
        """Validate output expressions, declared inputs, and the complete name interface."""
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
        """Return SHA-256 identity of the canonical typed transition program."""
        encoded = json.dumps(
            self.to_dict(),
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def evaluate(self, inputs: Sequence[int] | Mapping[str, int]) -> tuple[int, ...]:
        """Evaluate the transition expressions for one complete Boolean input vector."""
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
        """Compose a one-row override around the existing output expressions."""
        pattern = tuple(_bit(value, "transition input") for value in inputs)
        output_pattern = tuple(_bit(value, "transition output") for value in outputs)
        if len(pattern) != len(self.input_names):
            raise TransitionSpaceError("override input width does not match transition program")
        if len(output_pattern) != len(self.output_names):
            raise TransitionSpaceError("override output width does not match transition program")

        match: BooleanExpr = BooleanConstant(1)
        for input_name, expected_bit in zip(self.input_names, pattern):
            literal: BooleanExpr = BooleanInput(input_name)
            if not expected_bit:
                literal = BooleanNot(literal)
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
        """Enumerate the compositional program over every Boolean input pattern."""
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
        """Serialize the typed transition program and its ordered outputs."""
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
        """Restore a typed transition program from the exact versioned schema."""
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
