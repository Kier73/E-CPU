"""Contextual resolution and bounded navigation over declarative process state-spaces.

A process descriptor preserves a finite description of admissible states and
transition rules. A semantic address supplies a target condition, while a
process context supplies the current state, bindings, dependencies, and
resources. Navigation derives a finite path; it never executes that path.

Mathematics:
Let D=(S0,T,I) be a process descriptor, C a process context, and G a goal
predicate. The resolver searches the bounded graph induced by T from s0 for
s such that I(s) and G(s,C) hold. A returned witness is independently replayable.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping

from .temporal import ClockDomain, TemporalFrame


class NavigationError(ValueError):
    """Mathematics: a process description, context, path, or witness is invalid."""


class ContextResolutionError(NavigationError):
    """Mathematics: a contextual value reference cannot be resolved unambiguously."""


class ConditionOperator(str, Enum):
    """The closed comparison vocabulary for state predicates."""

    PRESENT = "present"
    ABSENT = "absent"
    EQ = "eq"
    NE = "ne"
    LT = "lt"
    LE = "le"
    GT = "gt"
    GE = "ge"
    IN = "in"


class UpdateOperation(str, Enum):
    """The closed update vocabulary admitted by declarative transition rules."""

    SET = "set"
    INCREMENT = "increment"
    APPEND = "append"
    COPY = "copy"
    DELETE = "delete"


class NavigationStatus(str, Enum):
    """Terminal disposition of one bounded state-space search."""

    FOUND = "found"
    ALREADY_SATISFIED = "already_satisfied"
    UNREACHABLE = "unreachable"
    RESOURCE_BLOCKED = "resource_blocked"
    BUDGET_EXHAUSTED = "budget_exhausted"


@dataclass(frozen=True)
class ContextRef:
    """A typed reference to one value supplied by the active process context."""

    name: str

    def __post_init__(self) -> None:
        """Mathematics: require a bounded context binding identifier."""
        _identifier(self.name, "context reference")

    def to_dict(self) -> dict[str, str]:
        """Mathematics: encode a reference as a tagged value, preserving literal-string identity."""
        return {"$context": self.name}


def _identifier(value: Any, label: str) -> str:
    """Mathematics: validate x against the finite identifier language [A-Za-z0-9][A-Za-z0-9._:-]{0,127}."""
    if not isinstance(value, str) or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", value) is None:
        raise NavigationError(f"{label} must be a safe 1-128 character identifier")
    return value


def _json_value(value: Any, label: str = "value", depth: int = 0) -> None:
    """Mathematics: require a finite JSON value with string object keys and nesting depth at most 64."""
    if depth > 64:
        raise NavigationError(f"{label} exceeds maximum nesting depth 64")
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise NavigationError(f"{label} contains a non-finite number")
        return
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise NavigationError(f"{label} object keys must be strings")
        for item in value.values():
            _json_value(item, label, depth + 1)
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            _json_value(item, label, depth + 1)
        return
    raise NavigationError(f"{label} contains a value outside the JSON domain")


def _operand_value(value: Any, label: str = "operand", depth: int = 0) -> None:
    """Mathematics: validate a JSON operand or a recursively nested ContextRef without executing code."""
    if depth > 64:
        raise NavigationError(f"{label} exceeds maximum nesting depth 64")
    if isinstance(value, ContextRef):
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise NavigationError(f"{label} object keys must be strings")
            _operand_value(item, label, depth + 1)
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            _operand_value(item, label, depth + 1)
        return
    _json_value(value, label, depth)


class _FrozenDict(dict):
    """JSON-compatible dictionary that rejects mutation after construction."""

    def _immutable(self, *args: Any, **kwargs: Any) -> None:
        """Mathematics: reject every mutating dictionary operation on a frozen value."""
        raise TypeError("navigation values are immutable")

    __setitem__ = _immutable
    __delitem__ = _immutable
    clear = _immutable
    pop = _immutable
    popitem = _immutable
    setdefault = _immutable
    update = _immutable
    __ior__ = _immutable


def _freeze_operand(value: Any) -> Any:
    """Mathematics: recursively detach and freeze JSON operands while retaining ContextRef tags."""
    if isinstance(value, ContextRef):
        return value
    if isinstance(value, Mapping):
        return _FrozenDict({key: _freeze_operand(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_operand(item) for item in value)
    return value


def _plain(value: Any) -> Any:
    """Mathematics: project frozen values and tagged references into detached JSON-compatible data."""
    if isinstance(value, ContextRef):
        return value.to_dict()
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


def _canonical_bytes(value: Any) -> bytes:
    """Mathematics: map a JSON-compatible value to its unique sorted compact UTF-8 encoding."""
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise NavigationError(f"value is not canonically serializable: {exc}") from exc


def _digest(value: Any) -> str:
    """Mathematics: calculate SHA-256 over the canonical JSON projection of value."""
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _path(value: Any, label: str = "path", *, optional: bool = False) -> tuple[str, ...] | None:
    """Mathematics: normalize a non-empty finite sequence of object-key path segments."""
    if value is None and optional:
        return None
    if not isinstance(value, (tuple, list)) or not value:
        raise NavigationError(f"{label} must be a non-empty sequence of object keys")
    if any(not isinstance(part, str) or not part for part in value):
        raise NavigationError(f"{label} segments must be non-empty strings")
    return tuple(value)


def _decode_operand(value: Any) -> Any:
    """Mathematics: decode only the exact tagged-object form reserved for ContextRef."""
    if isinstance(value, Mapping):
        if set(value) == {"$context"}:
            return ContextRef(value["$context"])
        return {key: _decode_operand(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_decode_operand(item) for item in value]
    return value


def _resolve_operand(value: Any, bindings: Mapping[str, Any]) -> Any:
    """Mathematics: substitute each ContextRef from bindings and reject unresolved names."""
    if isinstance(value, ContextRef):
        if value.name not in bindings:
            raise ContextResolutionError(f"missing context binding: {value.name}")
        return _plain(bindings[value.name])
    if isinstance(value, Mapping):
        return {key: _resolve_operand(item, bindings) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_resolve_operand(item, bindings) for item in value]
    return value


def _get_path(state: Mapping[str, Any], path: tuple[str, ...]) -> tuple[bool, Any]:
    """Mathematics: return (present,value) for a key path without mutating the state."""
    current: Any = state
    for part in path:
        if not isinstance(current, Mapping) or part not in current:
            return False, None
        current = current[part]
    return True, current


def _numeric(value: Any) -> bool:
    """Mathematics: test membership in R without treating Boolean values as numbers."""
    return isinstance(value, (int, float)) and not isinstance(value, bool) and (not isinstance(value, float) or math.isfinite(value))


def _typed_equal(left: Any, right: Any) -> bool:
    """Mathematics: compare JSON values recursively while preserving Boolean/numeric type distinctions."""
    if isinstance(left, bool) or isinstance(right, bool):
        return type(left) is type(right) and left == right
    if _numeric(left) and _numeric(right):
        return left == right
    if isinstance(left, Mapping) and isinstance(right, Mapping):
        return set(left) == set(right) and all(_typed_equal(left[key], right[key]) for key in left)
    if isinstance(left, (list, tuple)) and isinstance(right, (list, tuple)):
        return len(left) == len(right) and all(_typed_equal(a, b) for a, b in zip(left, right))
    if type(left) is not type(right):
        return False
    return left == right


@dataclass(frozen=True)
class StateCondition:
    """One typed comparison between a state path and a literal or contextual operand."""

    path: tuple[str, ...]
    operator: ConditionOperator
    value: Any = None

    def __post_init__(self) -> None:
        """Mathematics: validate a path, closed operator, and operand in the finite JSON/context language."""
        object.__setattr__(self, "path", _path(self.path))
        try:
            operator = self.operator if isinstance(self.operator, ConditionOperator) else ConditionOperator(self.operator)
        except (TypeError, ValueError) as exc:
            raise NavigationError("unknown state condition operator") from exc
        object.__setattr__(self, "operator", operator)
        if operator not in {ConditionOperator.PRESENT, ConditionOperator.ABSENT}:
            _operand_value(self.value)
            object.__setattr__(self, "value", _freeze_operand(self.value))

    def matches(self, state: Mapping[str, Any], bindings: Mapping[str, Any]) -> bool:
        """Mathematics: evaluate this predicate as a total Boolean over a validated JSON state."""
        present, actual = _get_path(state, self.path)
        if self.operator is ConditionOperator.PRESENT:
            return present
        if self.operator is ConditionOperator.ABSENT:
            return not present
        if not present:
            return False
        expected = _resolve_operand(self.value, bindings)
        if self.operator is ConditionOperator.EQ:
            return _typed_equal(actual, expected)
        if self.operator is ConditionOperator.NE:
            return not _typed_equal(actual, expected)
        if self.operator is ConditionOperator.IN:
            return isinstance(expected, (list, tuple)) and any(_typed_equal(actual, item) for item in expected)
        if self.operator in {ConditionOperator.LT, ConditionOperator.LE, ConditionOperator.GT, ConditionOperator.GE}:
            if not ((_numeric(actual) and _numeric(expected)) or (isinstance(actual, str) and isinstance(expected, str))):
                return False
            if self.operator is ConditionOperator.LT:
                return actual < expected
            if self.operator is ConditionOperator.LE:
                return actual <= expected
            if self.operator is ConditionOperator.GT:
                return actual > expected
            return actual >= expected
        return False

    def to_dict(self) -> dict[str, Any]:
        """Mathematics: serialize a predicate using stable path and operator labels."""
        result: dict[str, Any] = {"path": list(self.path), "operator": self.operator.value}
        if self.operator not in {ConditionOperator.PRESENT, ConditionOperator.ABSENT}:
            result["value"] = _plain(self.value)
        return result

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "StateCondition":
        """Mathematics: reconstruct a predicate only from its exact required field set."""
        if not isinstance(payload, Mapping):
            raise NavigationError("state condition must be an object")
        try:
            operator = ConditionOperator(payload.get("operator"))
        except (TypeError, ValueError) as exc:
            raise NavigationError("unknown state condition operator") from exc
        expected = {"path", "operator"} if operator in {ConditionOperator.PRESENT, ConditionOperator.ABSENT} else {"path", "operator", "value"}
        if set(payload) != expected:
            raise NavigationError("state condition fields are invalid")
        return cls(tuple(payload["path"]), operator, _decode_operand(payload.get("value")))


@dataclass(frozen=True)
class StatePattern:
    """A conjunction of state conditions; the empty conjunction matches every state."""

    conditions: tuple[StateCondition, ...] = ()

    def __post_init__(self) -> None:
        """Mathematics: require a finite ordered sequence of StateCondition predicates."""
        if not isinstance(self.conditions, (tuple, list)) or any(not isinstance(item, StateCondition) for item in self.conditions):
            raise NavigationError("state pattern conditions must be StateCondition values")
        object.__setattr__(self, "conditions", tuple(self.conditions))

    def matches(self, state: Mapping[str, Any], bindings: Mapping[str, Any]) -> bool:
        """Mathematics: return the conjunction of all member predicates over one state and binding set."""
        return all(condition.matches(state, bindings) for condition in self.conditions)

    def to_dict(self) -> dict[str, Any]:
        """Mathematics: serialize the ordered conjunction of condition records."""
        return {"conditions": [condition.to_dict() for condition in self.conditions]}

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "StatePattern":
        """Mathematics: reconstruct a conjunction from a finite list of condition records."""
        if not isinstance(payload, Mapping) or set(payload) != {"conditions"} or not isinstance(payload["conditions"], list):
            raise NavigationError("state pattern fields are invalid")
        return cls(tuple(StateCondition.from_dict(item) for item in payload["conditions"]))


@dataclass(frozen=True)
class StateUpdate:
    """A deterministic state mutation applied when one transition rule is enabled."""

    path: tuple[str, ...]
    operation: UpdateOperation
    value: Any = None
    source_path: tuple[str, ...] | None = None

    def __post_init__(self) -> None:
        """Mathematics: validate an update path, operation, value, and optional copy source."""
        object.__setattr__(self, "path", _path(self.path))
        try:
            operation = self.operation if isinstance(self.operation, UpdateOperation) else UpdateOperation(self.operation)
        except (TypeError, ValueError) as exc:
            raise NavigationError("unknown state update operation") from exc
        object.__setattr__(self, "operation", operation)
        source = _path(self.source_path, "source_path", optional=True)
        object.__setattr__(self, "source_path", source)
        if operation is UpdateOperation.COPY:
            if source is None:
                raise NavigationError("copy update requires source_path")
        elif source is not None:
            raise NavigationError("source_path is valid only for copy updates")
        if operation in {UpdateOperation.SET, UpdateOperation.INCREMENT, UpdateOperation.APPEND}:
            _operand_value(self.value)
            object.__setattr__(self, "value", _freeze_operand(self.value))

    def to_dict(self) -> dict[str, Any]:
        """Mathematics: serialize the update operation and only its applicable operands."""
        result: dict[str, Any] = {"path": list(self.path), "operation": self.operation.value}
        if self.operation in {UpdateOperation.SET, UpdateOperation.INCREMENT, UpdateOperation.APPEND}:
            result["value"] = _plain(self.value)
        if self.source_path is not None:
            result["source_path"] = list(self.source_path)
        return result

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "StateUpdate":
        """Mathematics: decode an update with an exact operation-specific key set."""
        if not isinstance(payload, Mapping):
            raise NavigationError("state update must be an object")
        try:
            operation = UpdateOperation(payload.get("operation"))
        except (TypeError, ValueError) as exc:
            raise NavigationError("unknown state update operation") from exc
        expected = {"path", "operation"}
        if operation in {UpdateOperation.SET, UpdateOperation.INCREMENT, UpdateOperation.APPEND}:
            expected.add("value")
        if operation is UpdateOperation.COPY:
            expected.add("source_path")
        if set(payload) != expected:
            raise NavigationError("state update fields are invalid")
        return cls(
            tuple(payload["path"]),
            operation,
            _decode_operand(payload.get("value")),
            None if "source_path" not in payload else tuple(payload["source_path"]),
        )

    def apply(self, state: dict[str, Any], bindings: Mapping[str, Any]) -> None:
        """Mathematics: apply one update in place after validating its target and contextual operand."""
        parent: Any = state
        for part in self.path[:-1]:
            if not isinstance(parent, dict) or part not in parent or not isinstance(parent[part], dict):
                raise NavigationError(f"update parent path does not exist: {'.'.join(self.path)}")
            parent = parent[part]
        if not isinstance(parent, dict):
            raise NavigationError("update target parent is not an object")
        leaf = self.path[-1]
        if self.operation is UpdateOperation.SET:
            parent[leaf] = _resolve_operand(self.value, bindings)
            return
        if self.operation is UpdateOperation.DELETE:
            if leaf not in parent:
                raise NavigationError(f"delete target does not exist: {'.'.join(self.path)}")
            del parent[leaf]
            return
        if self.operation is UpdateOperation.COPY:
            assert self.source_path is not None
            found, source = _get_path(state, self.source_path)
            if not found:
                raise NavigationError(f"copy source does not exist: {'.'.join(self.source_path)}")
            parent[leaf] = json.loads(_canonical_bytes(source).decode("utf-8"))
            return
        operand = _resolve_operand(self.value, bindings)
        if self.operation is UpdateOperation.INCREMENT:
            if leaf not in parent or not _numeric(parent[leaf]) or not _numeric(operand):
                raise NavigationError(f"increment requires numeric source and value: {'.'.join(self.path)}")
            parent[leaf] += operand
            if isinstance(parent[leaf], float) and not math.isfinite(parent[leaf]):
                raise NavigationError("increment produced a non-finite value")
            return
        if self.operation is UpdateOperation.APPEND:
            if leaf not in parent or not isinstance(parent[leaf], list):
                raise NavigationError(f"append requires an existing list: {'.'.join(self.path)}")
            _json_value(operand, "append value")
            parent[leaf].append(operand)
            return
        raise NavigationError("unsupported update operation")


@dataclass(frozen=True)
class TransitionRule:
    """A named guarded transition with deterministic updates and resource capacity needs."""

    transition_id: str
    guard: StatePattern = field(default_factory=StatePattern)
    updates: tuple[StateUpdate, ...] = ()
    resource_requirements: Mapping[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Mathematics: require a unique-safe rule ID, typed guard/update sequence, and non-negative capacities."""
        _identifier(self.transition_id, "transition_id")
        if not isinstance(self.guard, StatePattern):
            raise NavigationError("transition guard must be a StatePattern")
        if not isinstance(self.updates, (tuple, list)) or any(not isinstance(item, StateUpdate) for item in self.updates):
            raise NavigationError("transition updates must be StateUpdate values")
        object.__setattr__(self, "updates", tuple(self.updates))
        if not isinstance(self.resource_requirements, Mapping):
            raise NavigationError("resource_requirements must be a mapping")
        normalized: dict[str, int] = {}
        for name, amount in self.resource_requirements.items():
            _identifier(name, "resource name")
            if not isinstance(amount, int) or isinstance(amount, bool) or amount < 0:
                raise NavigationError("resource requirements must be non-negative integers")
            normalized[name] = amount
        object.__setattr__(self, "resource_requirements", _FrozenDict(dict(sorted(normalized.items()))))

    def to_dict(self) -> dict[str, Any]:
        """Mathematics: serialize a transition rule in a deterministic field order."""
        return {
            "transition_id": self.transition_id,
            "guard": self.guard.to_dict(),
            "updates": [update.to_dict() for update in self.updates],
            "resource_requirements": dict(self.resource_requirements),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "TransitionRule":
        """Mathematics: reconstruct a transition from its exact declared fields."""
        if not isinstance(payload, Mapping) or set(payload) != {"transition_id", "guard", "updates", "resource_requirements"}:
            raise NavigationError("transition rule fields are invalid")
        return cls(
            payload["transition_id"],
            StatePattern.from_dict(payload["guard"]),
            tuple(StateUpdate.from_dict(item) for item in payload["updates"]),
            payload["resource_requirements"],
        )

    def enabled(self, state: Mapping[str, Any], bindings: Mapping[str, Any]) -> bool:
        """Mathematics: decide whether the guard conjunction holds for the supplied state and context."""
        return self.guard.matches(state, bindings)

    def apply(self, state: Mapping[str, Any], bindings: Mapping[str, Any]) -> dict[str, Any]:
        """Mathematics: compute the successor state by applying updates in declared order to a detached copy."""
        candidate = json.loads(_canonical_bytes(state).decode("utf-8"))
        for update in self.updates:
            update.apply(candidate, bindings)
        _json_value(candidate, "transition result")
        return candidate


@dataclass(frozen=True)
class ReadinessResult:
    """Read-only evaluation of whether a process may begin under its current context."""

    ready: bool
    blockers: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """Mathematics: enforce ready iff and only if the blocker set is empty."""
        if not isinstance(self.ready, bool) or not isinstance(self.blockers, (tuple, list)):
            raise NavigationError("readiness result is malformed")
        normalized = tuple(self.blockers)
        if any(not isinstance(item, str) or not item for item in normalized):
            raise NavigationError("readiness blockers must be non-empty strings")
        if self.ready != (len(normalized) == 0):
            raise NavigationError("readiness flag and blocker set disagree")
        object.__setattr__(self, "blockers", normalized)


@dataclass(frozen=True)
class ReadinessContract:
    """Independent state, dependency, resource, authority, and clock-presence requirements."""

    preconditions: StatePattern = field(default_factory=StatePattern)
    dependency_ids: tuple[str, ...] = ()
    resource_requirements: Mapping[str, int] = field(default_factory=dict)
    required_capabilities: frozenset[str] = frozenset()
    required_temporal_domains: frozenset[ClockDomain] = frozenset()

    def __post_init__(self) -> None:
        """Mathematics: normalize finite requirement sets and reject duplicate or untyped requirements."""
        if not isinstance(self.preconditions, StatePattern):
            raise NavigationError("readiness preconditions must be a StatePattern")
        if not isinstance(self.dependency_ids, (tuple, list)):
            raise NavigationError("dependency_ids must be a finite sequence")
        deps = tuple(_identifier(item, "dependency id") for item in self.dependency_ids)
        if len(set(deps)) != len(deps):
            raise NavigationError("readiness dependency ids must be unique")
        object.__setattr__(self, "dependency_ids", deps)
        if not isinstance(self.resource_requirements, Mapping):
            raise NavigationError("readiness resource requirements must be a mapping")
        resources: dict[str, int] = {}
        for name, amount in self.resource_requirements.items():
            _identifier(name, "resource name")
            if not isinstance(amount, int) or isinstance(amount, bool) or amount < 0:
                raise NavigationError("readiness resource requirements must be non-negative integers")
            resources[name] = amount
        object.__setattr__(self, "resource_requirements", _FrozenDict(dict(sorted(resources.items()))))
        if not isinstance(self.required_capabilities, (tuple, list, set, frozenset)):
            raise NavigationError("required_capabilities must be a finite set or sequence")
        capabilities = frozenset(_identifier(item, "capability") for item in self.required_capabilities)
        object.__setattr__(self, "required_capabilities", capabilities)
        if not isinstance(self.required_temporal_domains, (tuple, list, set, frozenset)):
            raise NavigationError("required_temporal_domains must be a finite set or sequence")
        try:
            domains = frozenset(item if isinstance(item, ClockDomain) else ClockDomain(item) for item in self.required_temporal_domains)
        except (TypeError, ValueError) as exc:
            raise NavigationError("readiness contract contains an unknown temporal domain") from exc
        object.__setattr__(self, "required_temporal_domains", domains)

    def to_dict(self) -> dict[str, Any]:
        """Mathematics: serialize all readiness dimensions without converting their units."""
        return {
            "preconditions": self.preconditions.to_dict(),
            "dependency_ids": list(self.dependency_ids),
            "resource_requirements": dict(self.resource_requirements),
            "required_capabilities": sorted(self.required_capabilities),
            "required_temporal_domains": sorted(item.value for item in self.required_temporal_domains),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ReadinessContract":
        """Mathematics: reconstruct a readiness contract from its exact finite requirement record."""
        keys = {"preconditions", "dependency_ids", "resource_requirements", "required_capabilities", "required_temporal_domains"}
        if not isinstance(payload, Mapping) or set(payload) != keys:
            raise NavigationError("readiness contract fields are invalid")
        return cls(
            StatePattern.from_dict(payload["preconditions"]),
            tuple(payload["dependency_ids"]),
            payload["resource_requirements"],
            frozenset(payload["required_capabilities"]),
            frozenset(ClockDomain(item) for item in payload["required_temporal_domains"]),
        )

    def evaluate(self, context: "ProcessContext", state: Mapping[str, Any] | None) -> ReadinessResult:
        """Mathematics: return every unmet prerequisite as a stable blocker code, without scheduling or execution."""
        blockers: list[str] = []
        if state is None:
            if self.preconditions.conditions:
                blockers.append("state:unavailable")
        elif not self.preconditions.matches(state, context.bindings):
            blockers.append("state:preconditions")
        for dependency in self.dependency_ids:
            if dependency not in context.resolved_dependencies:
                blockers.append(f"dependency:{dependency}")
        for name, required in self.resource_requirements.items():
            if context.resource_capacity.get(name, 0) < required:
                blockers.append(f"resource:{name}")
        for capability in sorted(self.required_capabilities):
            if capability not in context.capabilities:
                blockers.append(f"capability:{capability}")
        present = _temporal_domains(context.temporal_frame)
        for domain in sorted(self.required_temporal_domains, key=lambda item: item.value):
            if domain not in present:
                blockers.append(f"clock:{domain.value}")
        return ReadinessResult(not blockers, tuple(blockers))


def _temporal_domains(frame: TemporalFrame | None) -> frozenset[ClockDomain]:
    """Mathematics: project present typed fields in one TemporalFrame onto their ClockDomain set."""
    if frame is None:
        return frozenset()
    result: set[ClockDomain] = set()
    for domain, present in (
        (ClockDomain.MONOTONIC, frame.monotonic is not None),
        (ClockDomain.WALL, frame.wall is not None),
        (ClockDomain.CAUSAL, frame.causal is not None),
        (ClockDomain.SCHEDULER, frame.scheduler is not None),
        (ClockDomain.EVENT, frame.event_lambda is not None),
        (ClockDomain.CHRONON, frame.chronon_phase is not None),
        (ClockDomain.CHEMICAL, frame.chemical_tau is not None),
    ):
        if present:
            result.add(domain)
    return frozenset(result)


@dataclass(frozen=True)
class ProcessDescriptor:
    """Versioned declarative logic defining a process's initial state, transitions, and invariants."""

    process_id: str
    version: str
    transitions: tuple[TransitionRule, ...]
    initial_state: Mapping[str, Any] | None = None
    invariants: tuple[StatePattern, ...] = ()
    readiness: ReadinessContract = field(default_factory=ReadinessContract)

    def __post_init__(self) -> None:
        """Mathematics: validate stable process identity and ensure the transition alphabet has unique IDs."""
        _identifier(self.process_id, "process_id")
        _identifier(self.version, "process version")
        if not isinstance(self.transitions, (tuple, list)) or any(not isinstance(item, TransitionRule) for item in self.transitions):
            raise NavigationError("transitions must be TransitionRule values")
        identifiers = [item.transition_id for item in self.transitions]
        if len(set(identifiers)) != len(identifiers):
            raise NavigationError("transition ids must be unique")
        object.__setattr__(self, "transitions", tuple(sorted(self.transitions, key=lambda item: item.transition_id)))
        if self.initial_state is not None:
            _json_value(self.initial_state, "initial_state")
            if not isinstance(self.initial_state, Mapping):
                raise NavigationError("initial_state must be an object")
            object.__setattr__(self, "initial_state", _freeze_operand(self.initial_state))
        if not isinstance(self.invariants, (tuple, list)) or any(not isinstance(item, StatePattern) for item in self.invariants):
            raise NavigationError("invariants must be StatePattern values")
        object.__setattr__(self, "invariants", tuple(self.invariants))
        if not isinstance(self.readiness, ReadinessContract):
            raise NavigationError("readiness must be a ReadinessContract")

    def to_dict(self) -> dict[str, Any]:
        """Mathematics: serialize the closed process definition into canonical JSON-compatible data."""
        return {
            "process_id": self.process_id,
            "version": self.version,
            "initial_state": None if self.initial_state is None else _plain(self.initial_state),
            "transitions": [item.to_dict() for item in self.transitions],
            "invariants": [item.to_dict() for item in self.invariants],
            "readiness": self.readiness.to_dict(),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ProcessDescriptor":
        """Mathematics: reconstruct a process descriptor only when its schema is exact and every component validates."""
        keys = {"process_id", "version", "initial_state", "transitions", "invariants", "readiness"}
        if not isinstance(payload, Mapping) or set(payload) != keys:
            raise NavigationError("process descriptor fields are invalid")
        if not isinstance(payload["transitions"], list) or not isinstance(payload["invariants"], list):
            raise NavigationError("process descriptor transitions and invariants must be lists")
        initial = payload["initial_state"]
        return cls(
            payload["process_id"],
            payload["version"],
            tuple(TransitionRule.from_dict(item) for item in payload["transitions"]),
            initial,
            tuple(StatePattern.from_dict(item) for item in payload["invariants"]),
            ReadinessContract.from_dict(payload["readiness"]),
        )

    @property
    def digest(self) -> str:
        """Mathematics: identify the exact versioned process law by SHA-256 of its canonical descriptor."""
        return _digest(self.to_dict())

    def admits(self, state: Mapping[str, Any], bindings: Mapping[str, Any]) -> bool:
        """Mathematics: return true exactly when every declared invariant holds for this state and context."""
        return all(invariant.matches(state, bindings) for invariant in self.invariants)


@dataclass(frozen=True)
class SemanticAddress:
    """A logical address naming a process version and the state condition to resolve."""

    process_id: str
    version: str
    goal: StatePattern

    def __post_init__(self) -> None:
        """Mathematics: validate process identity/version and the typed goal predicate."""
        _identifier(self.process_id, "process_id")
        _identifier(self.version, "process version")
        if not isinstance(self.goal, StatePattern):
            raise NavigationError("semantic address goal must be a StatePattern")

    def to_dict(self) -> dict[str, Any]:
        """Mathematics: serialize the semantic address without embedding executable code or authority."""
        return {"process_id": self.process_id, "version": self.version, "goal": self.goal.to_dict()}

    @property
    def digest(self) -> str:
        """Mathematics: calculate the stable identity of this semantic target request."""
        return _digest(self.to_dict())


@dataclass(frozen=True)
class ProcessContext:
    """Current observations and bounded resources used to resolve one semantic address."""

    process_id: str
    current_state: Mapping[str, Any] | None = None
    bindings: Mapping[str, Any] = field(default_factory=dict)
    resolved_dependencies: frozenset[str] = frozenset()
    resource_capacity: Mapping[str, int] = field(default_factory=dict)
    capabilities: frozenset[str] = frozenset()
    max_expansions: int = 10_000
    max_depth: int = 256
    temporal_frame: TemporalFrame | None = None

    def __post_init__(self) -> None:
        """Mathematics: freeze context inputs and enforce positive finite search budgets."""
        _identifier(self.process_id, "process_id")
        if self.current_state is not None:
            if not isinstance(self.current_state, Mapping):
                raise NavigationError("current_state must be an object")
            _json_value(self.current_state, "current_state")
            object.__setattr__(self, "current_state", _freeze_operand(self.current_state))
        if not isinstance(self.bindings, Mapping):
            raise NavigationError("bindings must be an object")
        _json_value(self.bindings, "bindings")
        object.__setattr__(self, "bindings", _freeze_operand(self.bindings))
        if not isinstance(self.resolved_dependencies, (tuple, list, set, frozenset)):
            raise NavigationError("resolved_dependencies must be a finite set or sequence")
        deps = frozenset(_identifier(item, "resolved dependency") for item in self.resolved_dependencies)
        object.__setattr__(self, "resolved_dependencies", deps)
        if not isinstance(self.resource_capacity, Mapping):
            raise NavigationError("resource_capacity must be an object")
        resources: dict[str, int] = {}
        for name, amount in self.resource_capacity.items():
            _identifier(name, "resource name")
            if not isinstance(amount, int) or isinstance(amount, bool) or amount < 0:
                raise NavigationError("resource capacities must be non-negative integers")
            resources[name] = amount
        object.__setattr__(self, "resource_capacity", _FrozenDict(dict(sorted(resources.items()))))
        if not isinstance(self.capabilities, (tuple, list, set, frozenset)):
            raise NavigationError("capabilities must be a finite set or sequence")
        caps = frozenset(_identifier(item, "capability") for item in self.capabilities)
        object.__setattr__(self, "capabilities", caps)
        for name, value in (("max_expansions", self.max_expansions), ("max_depth", self.max_depth)):
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise NavigationError(f"{name} must be a positive integer")
        if self.temporal_frame is not None and not isinstance(self.temporal_frame, TemporalFrame):
            raise NavigationError("temporal_frame must be a TemporalFrame")

    def resolution_digest(self) -> str:
        """Mathematics: identify all context fields that can affect the validity of a derived path."""
        return _digest({
            "process_id": self.process_id,
            "bindings": _plain(self.bindings),
            "resource_capacity": dict(self.resource_capacity),
        })


@dataclass(frozen=True)
class NavigationWitness:
    """Replay certificate binding one derived path to its descriptor, address, context, and endpoints."""

    descriptor_digest: str
    address_digest: str
    context_digest: str
    start_state_digest: str
    final_state_digest: str
    transition_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        """Mathematics: validate all SHA-256 identities and the finite transition sequence."""
        for name in ("descriptor_digest", "address_digest", "context_digest", "start_state_digest", "final_state_digest"):
            value = getattr(self, name)
            if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
                raise NavigationError(f"{name} must be a lowercase SHA-256 digest")
        if not isinstance(self.transition_ids, (tuple, list)):
            raise NavigationError("witness transition_ids must be a finite sequence")
        ids = tuple(_identifier(item, "witness transition id") for item in self.transition_ids)
        object.__setattr__(self, "transition_ids", ids)

    def to_dict(self) -> dict[str, Any]:
        """Mathematics: serialize the replay witness as its exact endpoint and rule identities."""
        return {
            "descriptor_digest": self.descriptor_digest,
            "address_digest": self.address_digest,
            "context_digest": self.context_digest,
            "start_state_digest": self.start_state_digest,
            "final_state_digest": self.final_state_digest,
            "transition_ids": list(self.transition_ids),
        }


@dataclass(frozen=True)
class NavigationResult:
    """The bounded resolver's result, including derived state and replay witness when successful."""

    status: NavigationStatus
    path: tuple[str, ...] = ()
    final_state: Mapping[str, Any] | None = None
    expanded_states: int = 0
    resource_envelope: Mapping[str, int] = field(default_factory=dict)
    witness: NavigationWitness | None = None

    def __post_init__(self) -> None:
        """Mathematics: enforce result typing, non-negative expansion count, and immutable result projections."""
        try:
            status = self.status if isinstance(self.status, NavigationStatus) else NavigationStatus(self.status)
        except (TypeError, ValueError) as exc:
            raise NavigationError("unknown navigation status") from exc
        object.__setattr__(self, "status", status)
        if not isinstance(self.path, (tuple, list)):
            raise NavigationError("navigation path must be a finite sequence")
        object.__setattr__(self, "path", tuple(_identifier(item, "transition id") for item in self.path))
        if not isinstance(self.expanded_states, int) or isinstance(self.expanded_states, bool) or self.expanded_states < 0:
            raise NavigationError("expanded_states must be a non-negative integer")
        if self.final_state is not None:
            if not isinstance(self.final_state, Mapping):
                raise NavigationError("final_state must be an object")
            _json_value(self.final_state, "final_state")
            object.__setattr__(self, "final_state", _freeze_operand(self.final_state))
        if not isinstance(self.resource_envelope, Mapping):
            raise NavigationError("resource_envelope must be an object")
        envelope: dict[str, int] = {}
        for key, value in self.resource_envelope.items():
            _identifier(key, "resource name")
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise NavigationError("resource envelope values must be non-negative integers")
            envelope[key] = value
        object.__setattr__(self, "resource_envelope", _FrozenDict(dict(sorted(envelope.items()))))
        if self.witness is not None and not isinstance(self.witness, NavigationWitness):
            raise NavigationError("witness must be a NavigationWitness")
        successful = status in {NavigationStatus.FOUND, NavigationStatus.ALREADY_SATISFIED}
        if successful != (self.final_state is not None and self.witness is not None):
            raise NavigationError("successful result requires final_state and witness; failure result must omit both")

    @property
    def reached(self) -> bool:
        """Mathematics: identify successful derivations without implying that their transitions were executed."""
        return self.status in {NavigationStatus.FOUND, NavigationStatus.ALREADY_SATISFIED}

    def to_dict(self) -> dict[str, Any]:
        """Mathematics: serialize the path result while keeping derived state distinct from execution receipts."""
        return {
            "status": self.status.value,
            "path": list(self.path),
            "final_state": None if self.final_state is None else _plain(self.final_state),
            "expanded_states": self.expanded_states,
            "resource_envelope": dict(self.resource_envelope),
            "witness": None if self.witness is None else self.witness.to_dict(),
        }


class ContextualNavigator:
    """Deterministic bounded breadth-first resolver for declarative process descriptors."""

    def navigate(self, descriptor: ProcessDescriptor, address: SemanticAddress, context: ProcessContext) -> NavigationResult:
        """Mathematics: derive a shortest transition-count path to the contextual goal within explicit expansion/depth bounds."""
        if not isinstance(descriptor, ProcessDescriptor) or not isinstance(address, SemanticAddress) or not isinstance(context, ProcessContext):
            raise NavigationError("navigate requires a descriptor, semantic address, and process context")
        if (descriptor.process_id, descriptor.version) != (address.process_id, address.version):
            raise NavigationError("semantic address does not identify this process descriptor version")
        if context.process_id != descriptor.process_id:
            raise NavigationError("process context belongs to another process")
        start_value = context.current_state if context.current_state is not None else descriptor.initial_state
        if start_value is None:
            raise NavigationError("no current or declared initial state is available")
        start = json.loads(_canonical_bytes(start_value).decode("utf-8"))
        if not descriptor.admits(start, context.bindings):
            raise NavigationError("starting state violates a declared process invariant")
        start_digest = _digest(start)
        if address.goal.matches(start, context.bindings):
            return self._success(
                NavigationStatus.ALREADY_SATISFIED, start, (), 0, {}, descriptor, address, context, start_digest
            )

        queue: deque[tuple[dict[str, Any], tuple[str, ...], dict[str, int]]] = deque([(start, (), {})])
        visited = {start_digest}
        expanded = 0
        resource_blocked = False
        depth_limited = False

        while queue:
            if expanded >= context.max_expansions:
                return NavigationResult(NavigationStatus.BUDGET_EXHAUSTED, expanded_states=expanded)
            state, path, envelope = queue.popleft()
            expanded += 1
            enabled = [rule for rule in descriptor.transitions if rule.enabled(state, context.bindings)]
            if len(path) >= context.max_depth:
                if enabled:
                    depth_limited = True
                continue
            for rule in enabled:
                if any(context.resource_capacity.get(name, 0) < required for name, required in rule.resource_requirements.items()):
                    resource_blocked = True
                    continue
                candidate = rule.apply(state, context.bindings)
                if not descriptor.admits(candidate, context.bindings):
                    continue
                state_digest = _digest(candidate)
                if state_digest in visited:
                    continue
                next_path = path + (rule.transition_id,)
                next_envelope = dict(envelope)
                for name, required in rule.resource_requirements.items():
                    next_envelope[name] = max(next_envelope.get(name, 0), required)
                if address.goal.matches(candidate, context.bindings):
                    return self._success(
                        NavigationStatus.FOUND, candidate, next_path, expanded, next_envelope,
                        descriptor, address, context, start_digest
                    )
                visited.add(state_digest)
                queue.append((candidate, next_path, next_envelope))

        if depth_limited:
            status = NavigationStatus.BUDGET_EXHAUSTED
        elif resource_blocked:
            status = NavigationStatus.RESOURCE_BLOCKED
        else:
            status = NavigationStatus.UNREACHABLE
        return NavigationResult(status, expanded_states=expanded)

    def _success(
        self,
        status: NavigationStatus,
        final_state: Mapping[str, Any],
        path: tuple[str, ...],
        expanded: int,
        envelope: Mapping[str, int],
        descriptor: ProcessDescriptor,
        address: SemanticAddress,
        context: ProcessContext,
        start_digest: str,
    ) -> NavigationResult:
        """Mathematics: bind a successful derivation to immutable descriptor, address, context, and state digests."""
        witness = NavigationWitness(
            descriptor.digest,
            address.digest,
            context.resolution_digest(),
            start_digest,
            _digest(final_state),
            path,
        )
        return NavigationResult(status, path, final_state, expanded, envelope, witness)


def verify_navigation_witness(
    descriptor: ProcessDescriptor,
    address: SemanticAddress,
    context: ProcessContext,
    result: NavigationResult,
) -> bool:
    """Mathematics: independently replay every declared transition and verify the witness endpoint and goal."""
    if not isinstance(result, NavigationResult) or not result.reached or result.witness is None or result.final_state is None:
        return False
    witness = result.witness
    if witness.descriptor_digest != descriptor.digest or witness.address_digest != address.digest:
        return False
    if witness.context_digest != context.resolution_digest():
        return False
    if (descriptor.process_id, descriptor.version, context.process_id) != (address.process_id, address.version, address.process_id):
        return False
    start_value = context.current_state if context.current_state is not None else descriptor.initial_state
    if start_value is None:
        return False
    state = json.loads(_canonical_bytes(start_value).decode("utf-8"))
    if _digest(state) != witness.start_state_digest or not descriptor.admits(state, context.bindings):
        return False
    rules = {rule.transition_id: rule for rule in descriptor.transitions}
    envelope: dict[str, int] = {}
    try:
        for transition_id in witness.transition_ids:
            rule = rules.get(transition_id)
            if rule is None or not rule.enabled(state, context.bindings):
                return False
            if any(context.resource_capacity.get(name, 0) < required for name, required in rule.resource_requirements.items()):
                return False
            state = rule.apply(state, context.bindings)
            if not descriptor.admits(state, context.bindings):
                return False
            for name, required in rule.resource_requirements.items():
                envelope[name] = max(envelope.get(name, 0), required)
    except (NavigationError, ContextResolutionError, TypeError, ValueError):
        return False
    if not address.goal.matches(state, context.bindings):
        return False
    return (
        _digest(state) == witness.final_state_digest
        and _typed_equal(state, result.final_state)
        and tuple(result.path) == witness.transition_ids
        and _typed_equal(envelope, result.resource_envelope)
        and result.status is (NavigationStatus.ALREADY_SATISFIED if not witness.transition_ids else NavigationStatus.FOUND)
    )


def evaluate_readiness(descriptor: ProcessDescriptor, context: ProcessContext) -> ReadinessResult:
    """Mathematics: evaluate a process's independent readiness contract against the current or initial state."""
    if not isinstance(descriptor, ProcessDescriptor) or not isinstance(context, ProcessContext):
        raise NavigationError("readiness evaluation requires a descriptor and process context")
    if descriptor.process_id != context.process_id:
        raise NavigationError("process context belongs to another process")
    state = context.current_state if context.current_state is not None else descriptor.initial_state
    if state is not None and not descriptor.admits(state, context.bindings):
        return ReadinessResult(False, ("state:invariant",))
    return descriptor.readiness.evaluate(context, state)
