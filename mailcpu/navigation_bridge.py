"""Conservative compiler from concrete navigation descriptions to affine analysis.

The bridge deliberately supports only a closed integer-affine projection.
Unsupported state constructs are refused rather than silently omitted.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Mapping

from .navigation import (
    ConditionOperator,
    ContextRef,
    NavigationError,
    ProcessContext,
    ProcessDescriptor,
    SemanticAddress,
    StateCondition,
    StatePattern,
    StateUpdate,
    UpdateOperation,
)
from .navigation_formal import (
    AbstractProgram,
    AbstractReachabilityAnalyzer,
    AbstractReachabilityResult,
    AbstractState,
    AbstractTransition,
    ConstraintRelation,
    IntInterval,
    LinearConstraint,
    LinearExpression,
)


class NavigationCompilationError(ValueError):
    """A concrete process description cannot be represented by the supported abstract subset."""


def _canonical_bytes(value: Any) -> bytes:
    """Mathematics: encode JSON data with a unique sorted compact UTF-8 projection."""
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise NavigationCompilationError(f"value is not canonically serializable: {exc}") from exc


def _plain(value: Any) -> Any:
    """Mathematics: detach immutable mappings and tuples into canonical JSON-shaped values."""
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(item) for item in value]
    return value


def _digest(value: Any) -> str:
    """Mathematics: calculate SHA-256 over the canonical JSON projection of value."""
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _resolve_integer(value: Any, context: ProcessContext, label: str) -> int:
    """Mathematics: resolve a literal or ContextRef to one exact integer, excluding Boolean values."""
    if isinstance(value, ContextRef):
        if value.name not in context.bindings:
            raise NavigationCompilationError(f"missing context binding: {value.name}")
        value = context.bindings[value.name]
    if not isinstance(value, int) or isinstance(value, bool):
        raise NavigationCompilationError(f"{label} must resolve to an integer")
    return value


def _variable(path: tuple[str, ...], label: str) -> str:
    """Mathematics: project a concrete state path onto the flat integer variable basis."""
    if len(path) != 1:
        raise NavigationCompilationError(f"{label} requires a single-level state path")
    return path[0]


_RELATIONS = {
    ConditionOperator.EQ: ConstraintRelation.EQ,
    ConditionOperator.NE: ConstraintRelation.NE,
    ConditionOperator.LT: ConstraintRelation.LT,
    ConditionOperator.LE: ConstraintRelation.LE,
    ConditionOperator.GT: ConstraintRelation.GT,
    ConditionOperator.GE: ConstraintRelation.GE,
}


def _condition(
    condition: StateCondition,
    context: ProcessContext,
    label: str,
) -> LinearConstraint:
    """Mathematics: translate an integer comparison x op k into the affine relation (x-k) op 0."""
    variable = _variable(condition.path, label)
    relation = _RELATIONS.get(condition.operator)
    if relation is None:
        raise NavigationCompilationError(
            f"{label} operator {condition.operator.value!r} is outside the integer-affine subset"
        )
    value = _resolve_integer(condition.value, context, label)
    return LinearConstraint(LinearExpression.variable(variable) - value, relation)


def _pattern(
    pattern: StatePattern,
    context: ProcessContext,
    label: str,
) -> tuple[LinearConstraint, ...]:
    """Mathematics: translate a conjunction while preserving every predicate or refusing the whole pattern."""
    return tuple(_condition(item, context, label) for item in pattern.conditions)


def _assignments(
    updates: tuple[StateUpdate, ...],
    context: ProcessContext,
) -> Mapping[str, LinearExpression]:
    """Mathematics: fold ordered SET/INCREMENT updates into simultaneous pre-state affine assignments."""
    expressions: dict[str, LinearExpression] = {}
    for update in updates:
        target = _variable(update.path, "transition update")
        if update.operation is UpdateOperation.SET:
            expressions[target] = LinearExpression.literal(
                _resolve_integer(update.value, context, f"SET value for {target}")
            )
        elif update.operation is UpdateOperation.INCREMENT:
            amount = _resolve_integer(update.value, context, f"INCREMENT value for {target}")
            previous = expressions.get(target, LinearExpression.variable(target))
            expressions[target] = previous + amount
        else:
            raise NavigationCompilationError(
                f"transition update {update.operation.value!r} is outside the integer-affine subset"
            )
    return expressions


@dataclass(frozen=True)
class CompiledNavigation:
    """Source-bound abstract program and goal produced by the restricted navigation compiler."""

    descriptor_digest: str
    address_digest: str
    context_digest: str
    start_state_digest: str
    program: AbstractProgram
    goal: tuple[LinearConstraint, ...]

    def __post_init__(self) -> None:
        """Mathematics: require four SHA-256 source identities and a typed abstract program/goal."""
        for name in ("descriptor_digest", "address_digest", "context_digest", "start_state_digest"):
            value = getattr(self, name)
            if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
                raise NavigationCompilationError(f"{name} must be a lowercase SHA-256 digest")
        if not isinstance(self.program, AbstractProgram):
            raise NavigationCompilationError("program must be an AbstractProgram")
        if not isinstance(self.goal, (tuple, list)) or any(
            not isinstance(item, LinearConstraint) for item in self.goal
        ):
            raise NavigationCompilationError("goal must be a finite sequence of LinearConstraint values")
        object.__setattr__(self, "goal", tuple(self.goal))

    @property
    def digest(self) -> str:
        """Mathematics: bind source identities, abstract program, and goal under one canonical digest."""
        return _digest(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        """Mathematics: serialize the compilation without claiming a concrete path or execution effect."""
        return {
            "schema": "mailcpu.abstract-navigation-compilation.v1",
            "descriptor_digest": self.descriptor_digest,
            "address_digest": self.address_digest,
            "context_digest": self.context_digest,
            "start_state_digest": self.start_state_digest,
            "program": self.program.to_dict(),
            "goal": [item.to_dict() for item in self.goal],
        }


class AbstractNavigationCompiler:
    """Compile the supported integer-affine projection of a concrete navigation request."""

    def compile(
        self,
        descriptor: ProcessDescriptor,
        address: SemanticAddress,
        context: ProcessContext,
    ) -> CompiledNavigation:
        """Mathematics: compile a validated process request into a sound over-approximation of its integer state projection."""
        if not isinstance(descriptor, ProcessDescriptor):
            raise NavigationCompilationError("descriptor must be a ProcessDescriptor")
        if not isinstance(address, SemanticAddress):
            raise NavigationCompilationError("address must be a SemanticAddress")
        if not isinstance(context, ProcessContext):
            raise NavigationCompilationError("context must be a ProcessContext")
        if (descriptor.process_id, descriptor.version) != (address.process_id, address.version):
            raise NavigationCompilationError("semantic address does not identify this process descriptor version")
        if context.process_id != descriptor.process_id:
            raise NavigationCompilationError("process context belongs to another process")

        start_value = context.current_state if context.current_state is not None else descriptor.initial_state
        if start_value is None:
            raise NavigationCompilationError("no current or declared initial state is available")
        if not descriptor.admits(start_value, context.bindings):
            raise NavigationCompilationError("starting state violates a declared process invariant")

        # Only integer coordinates are represented. Unprojected fields are safe to
        # omit only because every guard, invariant, goal, and update is compiled
        # in full or causes an explicit refusal below.
        integer_state = {
            name: IntInterval.point(value)
            for name, value in start_value.items()
            if isinstance(value, int) and not isinstance(value, bool)
        }
        abstract_initial = AbstractState.from_mapping(integer_state)

        invariants = tuple(
            LinearConstraint(
                item.expression,
                item.relation,
            )
            for pattern in descriptor.invariants
            for item in _pattern(pattern, context, "process invariant")
        )
        transitions = tuple(
            AbstractTransition(
                rule.transition_id,
                "process",
                "process",
                _pattern(rule.guard, context, f"guard for {rule.transition_id}"),
                _assignments(rule.updates, context),
            )
            for rule in descriptor.transitions
        )
        goal = _pattern(address.goal, context, "semantic goal")
        program = AbstractProgram(
            descriptor.process_id,
            descriptor.version,
            "process",
            abstract_initial,
            transitions,
            ("process",),
            invariants,
        )
        return CompiledNavigation(
            descriptor.digest,
            address.digest,
            context.resolution_digest(),
            _digest(_plain(start_value)),
            program,
            goal,
        )


def analyze_compiled_navigation(
    compilation: CompiledNavigation,
    *,
    analyzer: AbstractReachabilityAnalyzer | None = None,
    max_updates: int = 10_000,
    widen_after: int = 3,
) -> AbstractReachabilityResult:
    """Mathematics: analyze the compiled over-approximation without manufacturing a concrete navigation witness."""
    if not isinstance(compilation, CompiledNavigation):
        raise NavigationCompilationError("compilation must be a CompiledNavigation")
    engine = analyzer if analyzer is not None else AbstractReachabilityAnalyzer()
    if not isinstance(engine, AbstractReachabilityAnalyzer):
        raise NavigationCompilationError("analyzer must be an AbstractReachabilityAnalyzer")
    return engine.analyze(
        compilation.program,
        compilation.goal,
        max_updates=max_updates,
        widen_after=widen_after,
    )


def verify_abstract_compilation(
    descriptor: ProcessDescriptor,
    address: SemanticAddress,
    context: ProcessContext,
    compilation: CompiledNavigation,
) -> bool:
    """Mathematics: recompile the exact source request and compare the canonical compilation digest."""
    if not isinstance(compilation, CompiledNavigation):
        return False
    try:
        rebuilt = AbstractNavigationCompiler().compile(descriptor, address, context)
    except (NavigationError, NavigationCompilationError, TypeError, ValueError):
        return False
    return rebuilt.digest == compilation.digest
