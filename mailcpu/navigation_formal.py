"""Formal symbolic reachability, representation equivalence, and causal dependencies.

This module extends contextual process navigation with three finite, typed
formal methods:
- interval abstract interpretation over integer linear expressions;
- greatest-fixed-point strong bisimulation for finite labelled transition systems;
- directed acyclic causal dependency graphs checked against vector-clock stamps.

The analyses are intentionally conservative. Abstract reachability reports
possibility, proof of unreachability, or inconclusive analysis; it does not
manufacture a concrete path witness.
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

from .temporal import CausalRelation, CausalStamp


class FormalNavigationError(ValueError):
    """Mathematics: a formal state-space, transition system, expression, or causal graph is malformed."""


def _identifier(value: Any, label: str) -> str:
    """Mathematics: require x in the bounded identifier language [A-Za-z0-9][A-Za-z0-9._:-]{0,127}."""
    if not isinstance(value, str) or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", value) is None:
        raise FormalNavigationError(f"{label} must be a safe 1-128 character identifier")
    return value


def _integer(value: Any, label: str) -> int:
    """Mathematics: require x in Z while excluding Boolean values from the integer domain."""
    if not isinstance(value, int) or isinstance(value, bool):
        raise FormalNavigationError(f"{label} must be an integer")
    return value


def _json_value(value: Any, label: str = "value", depth: int = 0) -> None:
    """Mathematics: accept finite JSON values with string keys and at most 64 nested container levels."""
    if depth > 64:
        raise FormalNavigationError(f"{label} exceeds maximum nesting depth 64")
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise FormalNavigationError(f"{label} contains a non-finite number")
        return
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise FormalNavigationError(f"{label} object keys must be strings")
        for item in value.values():
            _json_value(item, label, depth + 1)
        return
    if isinstance(value, (tuple, list)):
        for item in value:
            _json_value(item, label, depth + 1)
        return
    raise FormalNavigationError(f"{label} contains a value outside the finite JSON domain")


def _plain(value: Any) -> Any:
    """Mathematics: detach recursively frozen JSON values into ordinary serialization containers."""
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(item) for item in value]
    return value


def _canonical_bytes(value: Any) -> bytes:
    """Mathematics: map a finite JSON-compatible value to sorted compact UTF-8 bytes."""
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise FormalNavigationError(f"value is not canonically serializable: {exc}") from exc


def _digest(value: Any) -> str:
    """Mathematics: compute SHA-256 over the canonical JSON representation of a value."""
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


class _FrozenDict(dict):
    """JSON-compatible dictionary that rejects mutation after construction."""

    def _immutable(self, *args: Any, **kwargs: Any) -> None:
        """Mathematics: reject a mutating operation so a frozen model remains detached from caller state."""
        raise TypeError("formal navigation values are immutable")

    __setitem__ = _immutable
    __delitem__ = _immutable
    clear = _immutable
    pop = _immutable
    popitem = _immutable
    setdefault = _immutable
    update = _immutable
    __ior__ = _immutable


def _freeze(value: Any) -> Any:
    """Mathematics: recursively detach and freeze a validated JSON value."""
    if isinstance(value, Mapping):
        return _FrozenDict({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (tuple, list)):
        return tuple(_freeze(item) for item in value)
    return value


@dataclass(frozen=True)
class IntInterval:
    """Closed integer interval; None denotes an unbounded endpoint."""

    lower: int | None = None
    upper: int | None = None

    def __post_init__(self) -> None:
        """Mathematics: require integer endpoints and lower <= upper whenever both endpoints are finite."""
        if self.lower is not None:
            _integer(self.lower, "interval lower bound")
        if self.upper is not None:
            _integer(self.upper, "interval upper bound")
        if self.lower is not None and self.upper is not None and self.lower > self.upper:
            raise FormalNavigationError("interval lower bound exceeds upper bound")

    @classmethod
    def point(cls, value: int) -> "IntInterval":
        """Mathematics: construct the singleton interval [x,x] for integer x."""
        number = _integer(value, "point value")
        return cls(number, number)

    @property
    def is_singleton(self) -> bool:
        """Mathematics: return true exactly when both finite endpoints coincide."""
        return self.lower is not None and self.lower == self.upper

    def hull(self, other: "IntInterval") -> "IntInterval":
        """Mathematics: compute the least interval containing both operands, [min lower,max upper]."""
        if not isinstance(other, IntInterval):
            raise FormalNavigationError("interval hull requires another IntInterval")
        lower = None if self.lower is None or other.lower is None else min(self.lower, other.lower)
        upper = None if self.upper is None or other.upper is None else max(self.upper, other.upper)
        return IntInterval(lower, upper)

    def intersect(self, other: "IntInterval") -> "IntInterval | None":
        """Mathematics: compute interval intersection or None when the two closed intervals are disjoint."""
        if not isinstance(other, IntInterval):
            raise FormalNavigationError("interval intersection requires another IntInterval")
        if self.lower is None:
            lower = other.lower
        elif other.lower is None:
            lower = self.lower
        else:
            lower = max(self.lower, other.lower)
        if self.upper is None:
            upper = other.upper
        elif other.upper is None:
            upper = self.upper
        else:
            upper = min(self.upper, other.upper)
        if lower is not None and upper is not None and lower > upper:
            return None
        return IntInterval(lower, upper)

    def widen(self, candidate: "IntInterval") -> "IntInterval":
        """Mathematics: widen an ascending interval chain, replacing a strictly expanding endpoint by infinity."""
        if not isinstance(candidate, IntInterval):
            raise FormalNavigationError("interval widening requires another IntInterval")
        lower = self.lower
        upper = self.upper
        if self.lower is not None and (candidate.lower is None or candidate.lower < self.lower):
            lower = None
        if self.upper is not None and (candidate.upper is None or candidate.upper > self.upper):
            upper = None
        return IntInterval(lower, upper)

    def add(self, other: "IntInterval") -> "IntInterval":
        """Mathematics: add endpoint bounds, propagating unboundedness independently on each side."""
        if not isinstance(other, IntInterval):
            raise FormalNavigationError("interval addition requires another IntInterval")
        lower = None if self.lower is None or other.lower is None else self.lower + other.lower
        upper = None if self.upper is None or other.upper is None else self.upper + other.upper
        return IntInterval(lower, upper)

    def scale(self, coefficient: int) -> "IntInterval":
        """Mathematics: multiply an interval by integer c, reversing endpoints when c is negative."""
        factor = _integer(coefficient, "interval scale")
        if factor == 0:
            return IntInterval.point(0)
        if factor > 0:
            lower = None if self.lower is None else factor * self.lower
            upper = None if self.upper is None else factor * self.upper
        else:
            lower = None if self.upper is None else factor * self.upper
            upper = None if self.lower is None else factor * self.lower
        return IntInterval(lower, upper)

    def to_dict(self) -> dict[str, int | None]:
        """Mathematics: serialize an interval as its finite or unbounded endpoint pair."""
        return {"lower": self.lower, "upper": self.upper}


@dataclass(frozen=True)
class LinearExpression:
    """Integer affine expression c + sum(a_i*x_i), with canonical integer coefficients."""

    terms: tuple[tuple[str, int], ...] = ()
    constant: int = 0

    def __post_init__(self) -> None:
        """Mathematics: combine duplicate variable coefficients, remove zero terms, and sort the remaining basis."""
        _integer(self.constant, "linear expression constant")
        if not isinstance(self.terms, (tuple, list)):
            raise FormalNavigationError("linear expression terms must be a finite sequence")
        combined: dict[str, int] = {}
        for item in self.terms:
            if not isinstance(item, (tuple, list)) or len(item) != 2:
                raise FormalNavigationError("linear expression terms must be (variable, coefficient) pairs")
            name = _identifier(item[0], "linear variable")
            coefficient = _integer(item[1], "linear coefficient")
            combined[name] = combined.get(name, 0) + coefficient
        canonical = tuple(sorted((name, coefficient) for name, coefficient in combined.items() if coefficient))
        object.__setattr__(self, "terms", canonical)

    @classmethod
    def variable(cls, name: str) -> "LinearExpression":
        """Mathematics: construct the coordinate function x ↦ x_name."""
        return cls(((name, 1),), 0)

    @classmethod
    def literal(cls, value: int) -> "LinearExpression":
        """Mathematics: construct the constant affine expression f(x)=value."""
        return cls((), _integer(value, "linear literal"))

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "LinearExpression":
        """Mathematics: reconstruct an affine expression from its exact canonical field set."""
        if not isinstance(payload, Mapping) or set(payload) != {"terms", "constant"}:
            raise FormalNavigationError("linear expression fields are invalid")
        terms = payload["terms"]
        if not isinstance(terms, list):
            raise FormalNavigationError("linear expression terms must be a list")
        return cls(tuple((item[0], item[1]) for item in terms), payload["constant"])

    def to_dict(self) -> dict[str, Any]:
        """Mathematics: serialize the canonical integer coefficient vector and constant."""
        return {"terms": [[name, coefficient] for name, coefficient in self.terms], "constant": self.constant}

    def __add__(self, other: "LinearExpression | int") -> "LinearExpression":
        """Mathematics: add affine coefficient vectors and constants componentwise."""
        right = other if isinstance(other, LinearExpression) else LinearExpression.literal(other)
        return LinearExpression(self.terms + right.terms, self.constant + right.constant)

    def __sub__(self, other: "LinearExpression | int") -> "LinearExpression":
        """Mathematics: subtract affine coefficient vectors and constants componentwise."""
        right = other if isinstance(other, LinearExpression) else LinearExpression.literal(other)
        return self + right.scale(-1)

    def scale(self, coefficient: int) -> "LinearExpression":
        """Mathematics: multiply every coefficient and the constant by integer c."""
        factor = _integer(coefficient, "linear expression scale")
        return LinearExpression(tuple((name, factor * value) for name, value in self.terms), factor * self.constant)

    def evaluate(self, bounds: Mapping[str, IntInterval]) -> IntInterval:
        """Mathematics: compute a sound interval enclosure of an affine expression over interval variable bounds."""
        if not isinstance(bounds, Mapping):
            raise FormalNavigationError("linear bounds must be a mapping")
        result = IntInterval.point(self.constant)
        for name, coefficient in self.terms:
            interval = bounds.get(name, IntInterval())
            if not isinstance(interval, IntInterval):
                raise FormalNavigationError(f"bound for {name} must be an IntInterval")
            result = result.add(interval.scale(coefficient))
        return result

    def evaluate_exact(self, values: Mapping[str, int]) -> int:
        """Mathematics: evaluate the affine expression over a complete integer valuation."""
        if not isinstance(values, Mapping):
            raise FormalNavigationError("exact linear valuation must be a mapping")
        result = self.constant
        for name, coefficient in self.terms:
            if name not in values:
                raise FormalNavigationError(f"missing linear variable: {name}")
            result += coefficient * _integer(values[name], f"value for {name}")
        return result


class ConstraintRelation(str, Enum):
    """Relations interpreted between an integer linear expression and zero."""

    EQ = "eq"
    NE = "ne"
    LT = "lt"
    LE = "le"
    GT = "gt"
    GE = "ge"


class ConstraintDisposition(str, Enum):
    """Sound abstract truth classification of a linear constraint."""

    ENTAILED = "entailed"
    REFUTED = "refuted"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class LinearConstraint:
    """Integer linear predicate expression relation 0."""

    expression: LinearExpression
    relation: ConstraintRelation

    def __post_init__(self) -> None:
        """Mathematics: require an affine expression and a known comparison relation."""
        if not isinstance(self.expression, LinearExpression):
            raise FormalNavigationError("constraint expression must be a LinearExpression")
        try:
            relation = self.relation if isinstance(self.relation, ConstraintRelation) else ConstraintRelation(self.relation)
        except (TypeError, ValueError) as exc:
            raise FormalNavigationError("unknown linear constraint relation") from exc
        object.__setattr__(self, "relation", relation)

    def classify(self, bounds: Mapping[str, IntInterval]) -> ConstraintDisposition:
        """Mathematics: classify a predicate from an enclosing interval; unknown is retained, never treated as false."""
        interval = self.expression.evaluate(bounds)
        lo, hi = interval.lower, interval.upper
        relation = self.relation
        if relation is ConstraintRelation.EQ:
            if interval.is_singleton and lo == 0:
                return ConstraintDisposition.ENTAILED
            if (lo is not None and lo > 0) or (hi is not None and hi < 0):
                return ConstraintDisposition.REFUTED
            return ConstraintDisposition.UNKNOWN
        if relation is ConstraintRelation.NE:
            if (lo is not None and lo > 0) or (hi is not None and hi < 0):
                return ConstraintDisposition.ENTAILED
            if interval.is_singleton and lo == 0:
                return ConstraintDisposition.REFUTED
            return ConstraintDisposition.UNKNOWN
        if relation is ConstraintRelation.LT:
            if hi is not None and hi < 0:
                return ConstraintDisposition.ENTAILED
            if lo is not None and lo >= 0:
                return ConstraintDisposition.REFUTED
            return ConstraintDisposition.UNKNOWN
        if relation is ConstraintRelation.LE:
            if hi is not None and hi <= 0:
                return ConstraintDisposition.ENTAILED
            if lo is not None and lo > 0:
                return ConstraintDisposition.REFUTED
            return ConstraintDisposition.UNKNOWN
        if relation is ConstraintRelation.GT:
            if lo is not None and lo > 0:
                return ConstraintDisposition.ENTAILED
            if hi is not None and hi <= 0:
                return ConstraintDisposition.REFUTED
            return ConstraintDisposition.UNKNOWN
        if lo is not None and lo >= 0:
            return ConstraintDisposition.ENTAILED
        if hi is not None and hi < 0:
            return ConstraintDisposition.REFUTED
        return ConstraintDisposition.UNKNOWN

    def to_dict(self) -> dict[str, Any]:
        """Mathematics: serialize a constraint as one canonical affine expression and relation label."""
        return {"expression": self.expression.to_dict(), "relation": self.relation.value}


@dataclass(frozen=True)
class AbstractState:
    """Abstract program state mapping integer variables to closed intervals."""

    bounds: tuple[tuple[str, IntInterval], ...] = ()

    def __post_init__(self) -> None:
        """Mathematics: require unique variable names and canonical sorted interval bindings."""
        if not isinstance(self.bounds, (tuple, list)):
            raise FormalNavigationError("abstract state bounds must be a finite sequence")
        normalized: dict[str, IntInterval] = {}
        for item in self.bounds:
            if not isinstance(item, (tuple, list)) or len(item) != 2:
                raise FormalNavigationError("abstract state entries must be (variable, interval) pairs")
            name = _identifier(item[0], "abstract state variable")
            interval = item[1]
            if not isinstance(interval, IntInterval):
                raise FormalNavigationError("abstract state values must be IntInterval values")
            if name in normalized:
                raise FormalNavigationError("abstract state contains a duplicate variable")
            normalized[name] = interval
        object.__setattr__(self, "bounds", tuple(sorted(normalized.items())))

    @classmethod
    def from_mapping(cls, bounds: Mapping[str, IntInterval | int]) -> "AbstractState":
        """Mathematics: construct an abstract state from intervals or exact integer points."""
        if not isinstance(bounds, Mapping):
            raise FormalNavigationError("abstract state source must be a mapping")
        normalized: list[tuple[str, IntInterval]] = []
        for name, value in bounds.items():
            interval = IntInterval.point(value) if isinstance(value, int) and not isinstance(value, bool) else value
            if not isinstance(interval, IntInterval):
                raise FormalNavigationError("abstract state values must be intervals or integers")
            normalized.append((name, interval))
        return cls(tuple(normalized))

    def as_mapping(self) -> dict[str, IntInterval]:
        """Mathematics: return a detached finite mapping for interval evaluation."""
        return dict(self.bounds)

    def hull(self, other: "AbstractState") -> "AbstractState":
        """Mathematics: join two abstract valuations by componentwise interval hull."""
        if not isinstance(other, AbstractState):
            raise FormalNavigationError("abstract state join requires another AbstractState")
        left, right = self.as_mapping(), other.as_mapping()
        names = set(left) | set(right)
        joined = {
            name: left.get(name, IntInterval()).hull(right.get(name, IntInterval()))
            for name in names
        }
        return AbstractState.from_mapping(joined)

    def widen(self, candidate: "AbstractState") -> "AbstractState":
        """Mathematics: widen a joined abstract valuation against the previous one to force interval-chain convergence."""
        if not isinstance(candidate, AbstractState):
            raise FormalNavigationError("abstract state widening requires another AbstractState")
        old, new = self.as_mapping(), candidate.as_mapping()
        names = set(old) | set(new)
        return AbstractState.from_mapping({
            name: old.get(name, IntInterval()).widen(new.get(name, IntInterval()))
            for name in names
        })

    def assign(self, assignments: Mapping[str, LinearExpression]) -> "AbstractState":
        """Mathematics: apply simultaneous affine assignments evaluated over the pre-state interval valuation."""
        if not isinstance(assignments, Mapping):
            raise FormalNavigationError("abstract assignments must be a mapping")
        current = self.as_mapping()
        result = dict(current)
        evaluated: dict[str, IntInterval] = {}
        for name, expression in assignments.items():
            _identifier(name, "assignment target")
            if not isinstance(expression, LinearExpression):
                raise FormalNavigationError("abstract assignment values must be LinearExpression values")
            evaluated[name] = expression.evaluate(current)
        result.update(evaluated)
        return AbstractState.from_mapping(result)

    def to_dict(self) -> dict[str, Any]:
        """Mathematics: serialize the abstract valuation in sorted variable order."""
        return {name: interval.to_dict() for name, interval in self.bounds}


@dataclass(frozen=True)
class AbstractTransition:
    """A control-location edge guarded by linear predicates with simultaneous affine assignments."""

    transition_id: str
    source: str
    target: str
    guards: tuple[LinearConstraint, ...] = ()
    assignments: Mapping[str, LinearExpression] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Mathematics: validate edge identities, finite guards, and a canonical affine assignment map."""
        _identifier(self.transition_id, "abstract transition id")
        _identifier(self.source, "abstract source location")
        _identifier(self.target, "abstract target location")
        if not isinstance(self.guards, (tuple, list)) or any(not isinstance(item, LinearConstraint) for item in self.guards):
            raise FormalNavigationError("abstract guards must be LinearConstraint values")
        object.__setattr__(self, "guards", tuple(self.guards))
        if not isinstance(self.assignments, Mapping):
            raise FormalNavigationError("abstract assignments must be a mapping")
        normalized: dict[str, LinearExpression] = {}
        for name, expression in self.assignments.items():
            _identifier(name, "abstract assignment target")
            if not isinstance(expression, LinearExpression):
                raise FormalNavigationError("abstract assignments must be LinearExpression values")
            normalized[name] = expression
        object.__setattr__(self, "assignments", _FrozenDict(dict(sorted(normalized.items()))))

    def to_dict(self) -> dict[str, Any]:
        """Mathematics: serialize one abstract transition edge without executable callbacks."""
        return {
            "transition_id": self.transition_id,
            "source": self.source,
            "target": self.target,
            "guards": [item.to_dict() for item in self.guards],
            "assignments": {name: expression.to_dict() for name, expression in self.assignments.items()},
        }


@dataclass(frozen=True)
class AbstractProgram:
    """Finite control-flow graph with affine integer state, guards, invariants, and accepting locations."""

    program_id: str
    version: str
    initial_location: str
    initial_state: AbstractState
    transitions: tuple[AbstractTransition, ...]
    accepting_locations: tuple[str, ...]
    invariants: tuple[LinearConstraint, ...] = ()

    def __post_init__(self) -> None:
        """Mathematics: validate finite graph identities and ensure every edge endpoint is a declared location."""
        _identifier(self.program_id, "abstract program id")
        _identifier(self.version, "abstract program version")
        _identifier(self.initial_location, "initial location")
        if not isinstance(self.initial_state, AbstractState):
            raise FormalNavigationError("initial_state must be an AbstractState")
        if not isinstance(self.transitions, (tuple, list)) or any(not isinstance(item, AbstractTransition) for item in self.transitions):
            raise FormalNavigationError("abstract transitions must be AbstractTransition values")
        transition_ids = [item.transition_id for item in self.transitions]
        if len(set(transition_ids)) != len(transition_ids):
            raise FormalNavigationError("abstract transition identifiers must be unique")
        object.__setattr__(self, "transitions", tuple(sorted(self.transitions, key=lambda item: item.transition_id)))
        if not isinstance(self.accepting_locations, (tuple, list)):
            raise FormalNavigationError("accepting_locations must be a finite sequence")
        accepting = tuple(_identifier(item, "accepting location") for item in self.accepting_locations)
        if not accepting or len(set(accepting)) != len(accepting):
            raise FormalNavigationError("accepting locations must be non-empty and unique")
        object.__setattr__(self, "accepting_locations", tuple(sorted(accepting)))
        if not isinstance(self.invariants, (tuple, list)) or any(not isinstance(item, LinearConstraint) for item in self.invariants):
            raise FormalNavigationError("abstract invariants must be LinearConstraint values")
        object.__setattr__(self, "invariants", tuple(self.invariants))
        locations = {self.initial_location, *self.accepting_locations}
        for transition in self.transitions:
            locations.update((transition.source, transition.target))
        if any(item.source not in locations or item.target not in locations for item in self.transitions):
            raise FormalNavigationError("abstract transition references an undeclared location")

    def to_dict(self) -> dict[str, Any]:
        """Mathematics: serialize the finite abstract program into canonical JSON-compatible data."""
        return {
            "program_id": self.program_id,
            "version": self.version,
            "initial_location": self.initial_location,
            "initial_state": self.initial_state.to_dict(),
            "transitions": [item.to_dict() for item in self.transitions],
            "accepting_locations": list(self.accepting_locations),
            "invariants": [item.to_dict() for item in self.invariants],
        }

    @property
    def digest(self) -> str:
        """Mathematics: identify the exact abstract transition system by SHA-256 of its canonical form."""
        return _digest(self.to_dict())


class AbstractReachabilityStatus(str, Enum):
    """Conservative disposition of an abstract reachability analysis."""

    MAY_BE_REACHABLE = "may_be_reachable"
    PROVED_UNREACHABLE = "proved_unreachable"
    INCONCLUSIVE = "inconclusive"


@dataclass(frozen=True)
class AbstractReachabilityResult:
    """Abstract reachability summary; it intentionally carries no concrete execution path."""

    status: AbstractReachabilityStatus
    program_digest: str
    location_states: tuple[tuple[str, AbstractState], ...]
    goal_dispositions: tuple[tuple[str, tuple[ConstraintDisposition, ...]], ...]
    transition_updates: int
    reason: str

    def __post_init__(self) -> None:
        """Mathematics: validate result identity, sorted abstract locations, and the absence of concrete path claims."""
        try:
            status = self.status if isinstance(self.status, AbstractReachabilityStatus) else AbstractReachabilityStatus(self.status)
        except (TypeError, ValueError) as exc:
            raise FormalNavigationError("unknown abstract reachability status") from exc
        object.__setattr__(self, "status", status)
        if not isinstance(self.program_digest, str) or re.fullmatch(r"[0-9a-f]{64}", self.program_digest) is None:
            raise FormalNavigationError("program_digest must be a lowercase SHA-256 digest")
        if not isinstance(self.transition_updates, int) or isinstance(self.transition_updates, bool) or self.transition_updates < 0:
            raise FormalNavigationError("transition_updates must be non-negative")
        if not isinstance(self.reason, str) or not self.reason:
            raise FormalNavigationError("abstract result reason must be non-empty")
        if any(not isinstance(state, AbstractState) for _, state in self.location_states):
            raise FormalNavigationError("location states must contain AbstractState values")

    @property
    def may_reach_goal(self) -> bool:
        """Mathematics: report whether the over-approximation retains at least one accepting candidate."""
        return self.status is AbstractReachabilityStatus.MAY_BE_REACHABLE

    def to_dict(self) -> dict[str, Any]:
        """Mathematics: serialize abstract bounds and truth dispositions, never as an execution witness."""
        return {
            "status": self.status.value,
            "program_digest": self.program_digest,
            "location_states": {location: state.to_dict() for location, state in self.location_states},
            "goal_dispositions": {
                location: [item.value for item in dispositions]
                for location, dispositions in self.goal_dispositions
            },
            "transition_updates": self.transition_updates,
            "reason": self.reason,
        }


class AbstractReachabilityAnalyzer:
    """Worklist interval abstract interpreter with join and widening over a finite control graph."""

    def analyze(
        self,
        program: AbstractProgram,
        goal: tuple[LinearConstraint, ...] = (),
        *,
        max_updates: int = 10_000,
        widen_after: int = 3,
    ) -> AbstractReachabilityResult:
        """Mathematics: compute a sound interval over-approximation of reachable states until a fixed point or explicit cap."""
        if not isinstance(program, AbstractProgram):
            raise FormalNavigationError("analyze requires an AbstractProgram")
        if not isinstance(goal, (tuple, list)) or any(not isinstance(item, LinearConstraint) for item in goal):
            raise FormalNavigationError("goal must be a finite sequence of LinearConstraint values")
        for name, value in (("max_updates", max_updates), ("widen_after", widen_after)):
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise FormalNavigationError(f"{name} must be a positive integer")

        initial = program.initial_state
        if any(item.classify(initial.as_mapping()) is ConstraintDisposition.REFUTED for item in program.invariants):
            return AbstractReachabilityResult(
                AbstractReachabilityStatus.PROVED_UNREACHABLE,
                program.digest,
                ((program.initial_location, initial),),
                (),
                0,
                "initial abstract state contradicts a declared invariant",
            )

        outgoing: dict[str, list[AbstractTransition]] = {}
        for transition in program.transitions:
            outgoing.setdefault(transition.source, []).append(transition)

        states: dict[str, AbstractState] = {program.initial_location: initial}
        updates_at_location: dict[str, int] = {}
        queue: deque[str] = deque([program.initial_location])
        queued = {program.initial_location}
        updates = 0
        capped = False

        while queue:
            location = queue.popleft()
            queued.discard(location)
            state = states[location]
            for transition in outgoing.get(location, ()):
                if updates >= max_updates:
                    capped = True
                    break
                if any(
                    guard.classify(state.as_mapping()) is ConstraintDisposition.REFUTED
                    for guard in transition.guards
                ):
                    continue
                candidate = state.assign(transition.assignments)
                if any(
                    invariant.classify(candidate.as_mapping()) is ConstraintDisposition.REFUTED
                    for invariant in program.invariants
                ):
                    continue
                updates += 1
                previous = states.get(transition.target)
                if previous is None:
                    merged = candidate
                    updates_at_location[transition.target] = 0
                else:
                    joined = previous.hull(candidate)
                    count = updates_at_location.get(transition.target, 0) + 1
                    updates_at_location[transition.target] = count
                    merged = previous.widen(joined) if count >= widen_after else joined
                    if merged == previous:
                        continue
                states[transition.target] = merged
                if transition.target not in queued:
                    queue.append(transition.target)
                    queued.add(transition.target)
            if capped:
                break

        goal_dispositions: list[tuple[str, tuple[ConstraintDisposition, ...]]] = []
        retained_goal = False
        for location in program.accepting_locations:
            state = states.get(location)
            if state is None:
                continue
            dispositions = tuple(item.classify(state.as_mapping()) for item in goal)
            goal_dispositions.append((location, dispositions))
            if ConstraintDisposition.REFUTED not in dispositions:
                retained_goal = True

        if capped:
            status = AbstractReachabilityStatus.INCONCLUSIVE
            reason = "transition update limit reached before a fixed point"
        elif retained_goal:
            status = AbstractReachabilityStatus.MAY_BE_REACHABLE
            reason = "an accepting abstract state remains compatible with the goal"
        else:
            status = AbstractReachabilityStatus.PROVED_UNREACHABLE
            reason = "no accepting abstract state can satisfy the goal in the over-approximation"

        return AbstractReachabilityResult(
            status,
            program.digest,
            tuple(sorted(states.items())),
            tuple(goal_dispositions),
            updates,
            reason,
        )


@dataclass(frozen=True)
class LabeledTransition:
    """One labelled edge in a finite labelled transition system."""

    source: str
    action: str
    target: str

    def __post_init__(self) -> None:
        """Mathematics: require safe state identifiers and a non-empty finite action label."""
        _identifier(self.source, "LTS source")
        _identifier(self.target, "LTS target")
        if not isinstance(self.action, str) or not self.action or "\x00" in self.action:
            raise FormalNavigationError("LTS action must be non-empty text without NUL")

    def to_dict(self) -> dict[str, str]:
        """Mathematics: serialize a labelled edge as its ordered source/action/target triple."""
        return {"source": self.source, "action": self.action, "target": self.target}


@dataclass(frozen=True)
class FiniteTransitionSystem:
    """Finite labelled transition system whose observations define representation-visible behaviour."""

    system_id: str
    initial_state: str
    observations: Mapping[str, Any]
    transitions: tuple[LabeledTransition, ...]

    def __post_init__(self) -> None:
        """Mathematics: validate a finite state set, detach its JSON observations, and check every edge endpoint."""
        _identifier(self.system_id, "transition system id")
        _identifier(self.initial_state, "initial state")
        if not isinstance(self.observations, Mapping) or not self.observations:
            raise FormalNavigationError("LTS observations must be a non-empty state mapping")
        normalized: dict[str, Any] = {}
        for state, observation in self.observations.items():
            name = _identifier(state, "LTS state")
            _json_value(observation, f"observation for {name}")
            normalized[name] = _freeze(observation)
        if self.initial_state not in normalized:
            raise FormalNavigationError("LTS initial state is absent from observations")
        object.__setattr__(self, "observations", _FrozenDict(dict(sorted(normalized.items()))))
        if not isinstance(self.transitions, (tuple, list)) or any(not isinstance(item, LabeledTransition) for item in self.transitions):
            raise FormalNavigationError("LTS transitions must be LabeledTransition values")
        for transition in self.transitions:
            if transition.source not in normalized or transition.target not in normalized:
                raise FormalNavigationError("LTS transition references an unknown state")
        object.__setattr__(self, "transitions", tuple(sorted(
            self.transitions, key=lambda item: (item.source, item.action, item.target)
        )))

    def to_dict(self) -> dict[str, Any]:
        """Mathematics: serialize the finite observed transition system in deterministic order."""
        return {
            "system_id": self.system_id,
            "initial_state": self.initial_state,
            "observations": {name: _plain(value) for name, value in self.observations.items()},
            "transitions": [item.to_dict() for item in self.transitions],
        }

    @property
    def digest(self) -> str:
        """Mathematics: identify the exact finite transition system by canonical SHA-256."""
        return _digest(self.to_dict())

    def outgoing(self) -> dict[str, tuple[LabeledTransition, ...]]:
        """Mathematics: group outgoing labelled edges by source state in canonical edge order."""
        result: dict[str, list[LabeledTransition]] = {}
        for transition in self.transitions:
            result.setdefault(transition.source, []).append(transition)
        return {state: tuple(edges) for state, edges in result.items()}


@dataclass(frozen=True)
class BisimulationResult:
    """Greatest-fixed-point strong bisimulation relation for a pair of finite systems."""

    equivalent: bool
    relation: tuple[tuple[str, str], ...]
    left_digest: str
    right_digest: str
    iterations: int

    def __post_init__(self) -> None:
        """Mathematics: validate relation pairs, finite iteration count, and both system digests."""
        if not isinstance(self.equivalent, bool):
            raise FormalNavigationError("bisimulation equivalent flag must be Boolean")
        if not isinstance(self.relation, (tuple, list)):
            raise FormalNavigationError("bisimulation relation must be a finite sequence")
        pairs = tuple((_identifier(left, "left relation state"), _identifier(right, "right relation state")) for left, right in self.relation)
        if len(set(pairs)) != len(pairs):
            raise FormalNavigationError("bisimulation relation contains duplicate pairs")
        object.__setattr__(self, "relation", tuple(sorted(pairs)))
        for name in ("left_digest", "right_digest"):
            value = getattr(self, name)
            if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
                raise FormalNavigationError(f"{name} must be a lowercase SHA-256 digest")
        if not isinstance(self.iterations, int) or isinstance(self.iterations, bool) or self.iterations < 0:
            raise FormalNavigationError("bisimulation iterations must be non-negative")

    def relates(self, left_state: str, right_state: str) -> bool:
        """Mathematics: test membership of a state pair in the computed greatest bisimulation."""
        return (left_state, right_state) in set(self.relation)


def compute_bisimulation(
    left: FiniteTransitionSystem,
    right: FiniteTransitionSystem,
) -> BisimulationResult:
    """Mathematics: compute the greatest strong bisimulation by repeatedly removing pairs that fail either transition-matching direction."""
    if not isinstance(left, FiniteTransitionSystem) or not isinstance(right, FiniteTransitionSystem):
        raise FormalNavigationError("bisimulation requires two FiniteTransitionSystem values")
    relation = {
        (left_state, right_state)
        for left_state, left_observation in left.observations.items()
        for right_state, right_observation in right.observations.items()
        if _canonical_bytes(_plain(left_observation)) == _canonical_bytes(_plain(right_observation))
    }
    left_out, right_out = left.outgoing(), right.outgoing()
    iterations = 0
    while True:
        iterations += 1
        removed: set[tuple[str, str]] = set()
        for left_state, right_state in relation:
            left_edges = left_out.get(left_state, ())
            right_edges = right_out.get(right_state, ())
            left_matches = all(
                any(
                    other.action == edge.action and (edge.target, other.target) in relation
                    for other in right_edges
                )
                for edge in left_edges
            )
            right_matches = all(
                any(
                    other.action == edge.action and (other.target, edge.target) in relation
                    for other in left_edges
                )
                for edge in right_edges
            )
            if not left_matches or not right_matches:
                removed.add((left_state, right_state))
        if not removed:
            break
        relation.difference_update(removed)
    initial_pair = (left.initial_state, right.initial_state)
    return BisimulationResult(
        initial_pair in relation,
        tuple(sorted(relation)),
        left.digest,
        right.digest,
        iterations,
    )


def verify_bisimulation_relation(
    left: FiniteTransitionSystem,
    right: FiniteTransitionSystem,
    relation: tuple[tuple[str, str], ...],
) -> bool:
    """Mathematics: verify a proposed finite relation by observation equality and forth/back transition simulation."""
    if not isinstance(left, FiniteTransitionSystem) or not isinstance(right, FiniteTransitionSystem):
        return False
    try:
        pairs = set(relation)
        for left_state, right_state in pairs:
            if left_state not in left.observations or right_state not in right.observations:
                return False
            if _canonical_bytes(_plain(left.observations[left_state])) != _canonical_bytes(_plain(right.observations[right_state])):
                return False
        left_out, right_out = left.outgoing(), right.outgoing()
        for left_state, right_state in pairs:
            left_edges, right_edges = left_out.get(left_state, ()), right_out.get(right_state, ())
            for edge in left_edges:
                if not any(
                    other.action == edge.action and (edge.target, other.target) in pairs
                    for other in right_edges
                ):
                    return False
            for edge in right_edges:
                if not any(
                    other.action == edge.action and (other.target, edge.target) in pairs
                    for other in left_edges
                ):
                    return False
        return True
    except (TypeError, ValueError):
        return False


@dataclass(frozen=True)
class CausalDependencyResult:
    """Causal readiness outcome and deterministic topological event order."""

    ready: bool
    blockers: tuple[str, ...]
    topological_order: tuple[str, ...]

    def __post_init__(self) -> None:
        """Mathematics: enforce ready iff the blocker sequence is empty and freeze the topological order."""
        if not isinstance(self.ready, bool):
            raise FormalNavigationError("causal readiness flag must be Boolean")
        if not isinstance(self.blockers, (tuple, list)) or any(not isinstance(item, str) or not item for item in self.blockers):
            raise FormalNavigationError("causal blockers must be a finite sequence of non-empty strings")
        if self.ready != (len(self.blockers) == 0):
            raise FormalNavigationError("causal readiness flag and blockers disagree")
        if not isinstance(self.topological_order, (tuple, list)):
            raise FormalNavigationError("topological order must be a finite sequence")
        object.__setattr__(self, "blockers", tuple(self.blockers))
        object.__setattr__(self, "topological_order", tuple(self.topological_order))


@dataclass(frozen=True)
class CausalDependencyGraph:
    """A DAG of required event precedence, validated against distributed vector-clock stamps."""

    events: tuple[str, ...]
    edges: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        """Mathematics: validate unique event identities, known directed edges, and acyclicity by Kahn's algorithm."""
        if not isinstance(self.events, (tuple, list)):
            raise FormalNavigationError("causal graph events must be a finite sequence")
        events = tuple(_identifier(item, "causal event id") for item in self.events)
        if not events or len(set(events)) != len(events):
            raise FormalNavigationError("causal graph event ids must be non-empty and unique")
        if not isinstance(self.edges, (tuple, list)):
            raise FormalNavigationError("causal graph edges must be a finite sequence")
        normalized: set[tuple[str, str]] = set()
        for edge in self.edges:
            if not isinstance(edge, (tuple, list)) or len(edge) != 2:
                raise FormalNavigationError("causal graph edges must be (before, after) pairs")
            before, after = edge
            if before not in events or after not in events or before == after:
                raise FormalNavigationError("causal edge endpoints must be distinct declared events")
            normalized.add((before, after))
        object.__setattr__(self, "events", tuple(sorted(events)))
        object.__setattr__(self, "edges", tuple(sorted(normalized)))
        self.topological_order()

    def topological_order(self) -> tuple[str, ...]:
        """Mathematics: return a deterministic topological ordering or refuse a directed cycle."""
        outgoing: dict[str, list[str]] = {event: [] for event in self.events}
        indegree = {event: 0 for event in self.events}
        for before, after in self.edges:
            outgoing[before].append(after)
            indegree[after] += 1
        ready = sorted(event for event, degree in indegree.items() if degree == 0)
        order: list[str] = []
        while ready:
            current = ready.pop(0)
            order.append(current)
            for successor in sorted(outgoing[current]):
                indegree[successor] -= 1
                if indegree[successor] == 0:
                    ready.append(successor)
                    ready.sort()
        if len(order) != len(self.events):
            raise FormalNavigationError("causal dependency graph contains a cycle")
        return tuple(order)

    def evaluate(self, observed: Mapping[str, CausalStamp]) -> CausalDependencyResult:
        """Mathematics: require every graph event to be observed and every edge A→B to satisfy stamp(A) BEFORE stamp(B)."""
        if not isinstance(observed, Mapping):
            raise FormalNavigationError("observed causal stamps must be a mapping")
        unknown = set(observed) - set(self.events)
        if unknown:
            raise FormalNavigationError(f"observed causal stamps contain unknown events: {sorted(unknown)}")
        for event, stamp in observed.items():
            if not isinstance(stamp, CausalStamp):
                raise FormalNavigationError(f"causal stamp for {event} must be a CausalStamp")
        blockers = [f"event:missing:{event}" for event in self.events if event not in observed]
        for before, after in self.edges:
            if before not in observed or after not in observed:
                continue
            relation = observed[before].relation(observed[after])
            if relation is not CausalRelation.BEFORE:
                blockers.append(f"causality:{before}:{relation.value}:{after}")
        return CausalDependencyResult(not blockers, tuple(blockers), self.topological_order())

    def to_dict(self) -> dict[str, Any]:
        """Mathematics: serialize the DAG in sorted event and edge order."""
        return {"events": list(self.events), "edges": [list(edge) for edge in self.edges]}

    @property
    def digest(self) -> str:
        """Mathematics: identify the causal dependency structure by canonical SHA-256."""
        return _digest(self.to_dict())


def evaluate_causal_dependencies(
    graph: CausalDependencyGraph,
    observed: Mapping[str, CausalStamp],
) -> CausalDependencyResult:
    """Mathematics: expose the graph's causal readiness predicate as a standalone coordination operation."""
    if not isinstance(graph, CausalDependencyGraph):
        raise FormalNavigationError("causal dependency evaluation requires a CausalDependencyGraph")
    return graph.evaluate(observed)
