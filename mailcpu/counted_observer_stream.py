"""COUNTED-004: exact event-count navigation through feedback-driven finite Grounds.

This is a pure mathematical observation utility over E-CPU's admitted
FiniteObserverLaw. A selected observation quotient preserves the outputs used
by an event transducer under every source action. An exact reachable quotient
orbit yields a preperiod and a (possibly nontrivial) cycle, with ordered,
variable-rate emissions for each source action.

The stream's kth event is addressed by division into counted cycle periods
without computing its preceding k events. Receipts bind the source,
observer quotient, action word, rule order, ordinal, and selected event, and
are independently reconstructed from the original source. No SEND is
physically enqueued, acknowledged, or committed by this utility.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Any, Mapping

from .intention_formed_fabric import (
    FiniteObserverLaw, form_observer_machine, verify_formed_machine,
)
from .substrate_bootstrap import BootstrapRefused

_SCHEMA = "mailcpu.counted-feedback-stream.v1"
_REQUEST_SCHEMA = "mailcpu.counted-feedback-request.v1"
_MAX_COORDINATE_BITS = 4096
Scalar = str | int | bool | None


def _valid_scalar(value: object) -> bool:
    """Mathematics: define the finite exact scalar observation domain."""

    return type(value) in (str, int, bool, type(None))


def _canonical(value: object) -> bytes:
    """Mathematics: encode source-bound claims with deterministic, finite JSON."""

    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False,
    ).encode("ascii")


def _hex(value: int) -> str:
    """Mathematics: unique signed hexadecimal representation for an integer."""

    return hex(value)


def _decode_hex(value: object, *, min_value: int = 0) -> int:
    """Mathematics: refuse unbounded and noncanonical external integer spellings."""

    if type(value) is not str or len(value) > 2 + (_MAX_COORDINATE_BITS + 3) // 4:
        raise BootstrapRefused("counted stream coordinate is not bounded hexadecimal")
    try:
        decoded = int(value, 16)
    except ValueError as exc:
        raise BootstrapRefused("counted stream coordinate is malformed") from exc
    if _hex(decoded) != value or decoded < min_value or decoded.bit_length() > _MAX_COORDINATE_BITS:
        raise BootstrapRefused("counted stream coordinate is not canonical and admitted")
    return decoded


def _coordinate(value: int) -> int:
    """Mathematics: admit a nonnegative logical time or emission ordinal."""

    if type(value) is not int or value < 0 or value.bit_length() > _MAX_COORDINATE_BITS:
        raise BootstrapRefused("counted stream coordinate exceeds 4096-bit admission")
    return value


def _digest(value: object) -> str:
    """Mathematics: bind a canonical observation or request to its exact contents."""

    return sha256(_canonical(value)).hexdigest()


@dataclass(frozen=True, slots=True)
class EmitRule:
    """Ordered post-action emission of one declared observer field."""

    mailbox: str
    value_field: str
    when_field: str | None = None
    when_equals: Scalar = None
    on_action: str | None = None

    def __post_init__(self) -> None:
        """Mathematics: refuse ambiguous event predicates and uncontrolled labels."""

        if (type(self.mailbox) is not str or not 0 < len(self.mailbox) <= 128
                or type(self.value_field) is not str or not self.value_field
                or (self.when_field is not None
                    and (type(self.when_field) is not str or not self.when_field))
                or (self.on_action is not None
                    and (type(self.on_action) is not str or not self.on_action))):
            raise BootstrapRefused("counted emission rule names are invalid")
        if not _valid_scalar(self.when_equals):
            raise BootstrapRefused("counted emission condition is not a finite scalar")
        if self.when_field is None and self.when_equals is not None:
            raise BootstrapRefused("unconditional emission cannot declare a gate comparison")

    def to_dict(self) -> dict[str, Any]:
        """Mathematics: serialize a uniquely ordered typed emission predicate."""

        return {
            "mailbox": self.mailbox,
            "value_field": self.value_field,
            "when_field": self.when_field,
            "when_equals": self.when_equals,
            "on_action": self.on_action,
        }

    @classmethod
    def from_dict(cls, value: object) -> "EmitRule":
        """Mathematics: reject missing, extra, or mistyped rule fields."""

        if type(value) is not dict or set(value) != {
            "mailbox", "value_field", "when_field", "when_equals", "on_action",
        }:
            raise BootstrapRefused("counted emission rule envelope is invalid")
        return cls(**value)


@dataclass(frozen=True, slots=True)
class CountedEvent:
    """One semantic emission with event index and exact source-action coordinate."""

    index: int
    word_iteration: int
    action_offset: int
    mailbox: str
    value: Scalar

    def to_dict(self) -> dict[str, Any]:
        """Mathematics: retain both emission and logical-time coordinates."""

        return {
            "index": _hex(self.index),
            "word_iteration": _hex(self.word_iteration),
            "action_offset": self.action_offset,
            "mailbox": self.mailbox,
            "value": self.value,
        }

    @classmethod
    def from_dict(cls, raw: object) -> "CountedEvent":
        """Mathematics: decode only one bounded exact observer event."""

        if type(raw) is not dict or set(raw) != {
            "index", "word_iteration", "action_offset", "mailbox", "value",
        } or type(raw["action_offset"]) is not int or raw["action_offset"] < 0:
            raise BootstrapRefused("counted event envelope is invalid")
        if type(raw["mailbox"]) is not str or not 0 < len(raw["mailbox"]) <= 128:
            raise BootstrapRefused("counted event mailbox is invalid")
        if not _valid_scalar(raw["value"]):
            raise BootstrapRefused("counted event value is not a finite scalar")
        return cls(
            _decode_hex(raw["index"]),
            _decode_hex(raw["word_iteration"], min_value=1),
            raw["action_offset"],
            raw["mailbox"], raw["value"],
        )


@dataclass(frozen=True, slots=True)
class CountedStreamRequest:
    """Original observer intention, including the exact output index."""

    initial_state: str
    word: tuple[str, ...]
    rules: tuple[EmitRule, ...]
    index: int

    def to_dict(self) -> dict[str, Any]:
        """Mathematics: construct a canonical identity of the intended observation."""

        return {
            "schema": _REQUEST_SCHEMA,
            "initial_state": self.initial_state,
            "word": list(self.word),
            "rules": [rule.to_dict() for rule in self.rules],
            "index": _hex(self.index),
        }


@dataclass(frozen=True, slots=True)
class CountedStreamReceipt:
    """Receiver-reconstructable source and observer-quotient event certificate."""

    source_digest: str
    quotient_digest: str
    request: CountedStreamRequest
    event: CountedEvent

    def _payload(self) -> dict[str, Any]:
        """Mathematics: bind source, intended query, and exact event result."""

        return {
            "schema": _SCHEMA,
            "source_digest": self.source_digest,
            "quotient_digest": self.quotient_digest,
            "request": self.request.to_dict(),
            "event": self.event.to_dict(),
        }

    @property
    def digest(self) -> str:
        """Mathematics: content-address the selected stream observation."""

        return _digest(self._payload())

    def snapshot(self) -> dict[str, Any]:
        """Mathematics: export versioned typed receipt plus canonical SHA256."""

        return {**self._payload(), "digest": self.digest}

    def to_bytes(self) -> bytes:
        """Mathematics: transmit one bounded, canonical mathematical result."""

        return _canonical(self.snapshot())

    @classmethod
    def from_snapshot(cls, raw: object) -> "CountedStreamReceipt":
        """Mathematics: reject all fields not in the declared receipt schema."""

        if type(raw) is not dict or set(raw) != {
            "schema", "source_digest", "quotient_digest", "request", "event", "digest",
        } or raw["schema"] != _SCHEMA:
            raise BootstrapRefused("counted stream receipt schema is invalid")
        for field in ("source_digest", "quotient_digest", "digest"):
            value = raw[field]
            if (type(value) is not str or len(value) != 64
                    or any(ch not in "0123456789abcdef" for ch in value)):
                raise BootstrapRefused("counted stream digest is not canonical SHA256")
        request = raw["request"]
        if type(request) is not dict or set(request) != {
            "schema", "initial_state", "word", "rules", "index",
        } or request["schema"] != _REQUEST_SCHEMA:
            raise BootstrapRefused("counted stream request is malformed")
        word, rules = request["word"], request["rules"]
        if (type(request["initial_state"]) is not str
                or type(word) is not list or not 1 <= len(word) <= 32
                or any(type(action) is not str for action in word)
                or type(rules) is not list or not 1 <= len(rules) <= 16):
            raise BootstrapRefused("counted stream request fields are malformed")
        decoded = cls(
            raw["source_digest"], raw["quotient_digest"],
            CountedStreamRequest(
                request["initial_state"], tuple(word),
                tuple(EmitRule.from_dict(rule) for rule in rules),
                _decode_hex(request["index"]),
            ),
            CountedEvent.from_dict(raw["event"]),
        )
        if decoded.snapshot() != raw:
            raise BootstrapRefused("counted stream receipt identity or canonical form differs")
        return decoded

    @classmethod
    def from_bytes(cls, raw: bytes) -> "CountedStreamReceipt":
        """Mathematics: reject duplicate JSON keys, noncanonical bytes, and nonfinite values."""

        if type(raw) is not bytes or not 0 < len(raw) <= 32_768:
            raise BootstrapRefused("counted stream receipt bytes exceed admission")
        def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
            """Mathematics: reject duplicate field identities at every JSON level."""

            result: dict[str, Any] = {}
            for key, value in pairs:
                if key in result:
                    raise BootstrapRefused("duplicate JSON key in counted stream receipt")
                result[key] = value
            return result
        def reject_nonfinite(name: str) -> object:
            """Mathematics: refuse nonfinite numeric constants outright."""

            raise BootstrapRefused(f"unadmitted JSON numeric constant: {name}")
        try:
            decoded = json.loads(
                raw.decode("ascii"),
                object_pairs_hook=unique, parse_constant=reject_nonfinite,
            )
        except (ValueError, UnicodeError, TypeError) as exc:
            raise BootstrapRefused("counted stream receipt JSON is malformed") from exc
        if _canonical(decoded) != raw:
            raise BootstrapRefused("counted stream receipt bytes are noncanonical")
        return cls.from_snapshot(decoded)


@dataclass(frozen=True, slots=True)
class _EventTemplate:
    """One event within a bounded orbit prefix or one observed period."""

    iteration: int
    offset: int
    mailbox: str
    value: Scalar


@dataclass(frozen=True, slots=True)
class CountedCycleSummary:
    """Exact finite-quotient event-count composition and proof coordinates."""

    source_digest: str
    quotient_digest: str
    preperiod: int
    period: int
    prefix_emissions: int
    period_emissions: int
    quotient_states: int

    @property
    def infinite(self) -> bool:
        """Mathematics: a positive emission count per persistent cycle implies infinite stream."""

        return self.period_emissions > 0


class CountedObserverStream:
    """Index variable-rate semantic emissions on a persistent finite feedback Ground."""

    def __init__(
        self,
        source: FiniteObserverLaw,
        *,
        initial_state: str,
        word: tuple[str, ...],
        rules: tuple[EmitRule, ...],
    ) -> None:
        """Mathematics: quotient selected observations and certify their reachable cycle."""

        if not isinstance(source, FiniteObserverLaw):
            raise BootstrapRefused("counted stream requires an exact finite observer law")
        # Preserve content identity against a mutable nested source representation.
        if any(type(getattr(source, name)) is not tuple for name in (
            "states", "actions", "fields", "transitions", "observations",
        )) or any(type(row) is not tuple for row in (*source.transitions, *source.observations)):
            raise BootstrapRefused("counted stream source must be an immutable tuple Ground")
        if type(initial_state) is not str or initial_state not in source.states:
            raise BootstrapRefused("counted stream initial state is not declared")
        if (type(word) is not tuple or not 1 <= len(word) <= 32
                or any(type(action) is not str or action not in source.actions for action in word)):
            raise BootstrapRefused("counted stream action word is not declared")
        if (type(rules) is not tuple or not 1 <= len(rules) <= 16
                or any(type(rule) is not EmitRule for rule in rules)):
            raise BootstrapRefused("counted stream requires ordered, typed emission rules")
        for rule in rules:
            if (rule.value_field not in source.fields
                    or (rule.when_field is not None and rule.when_field not in source.fields)
                    or (rule.on_action is not None and rule.on_action not in source.actions)):
                raise BootstrapRefused("emission rule refers to an undeclared action or observation")
        selected_fields = tuple(dict.fromkeys(
            field for rule in rules for field in (rule.value_field, rule.when_field)
            if field is not None
        ))
        machine = form_observer_machine(source, selected_fields)
        if not verify_formed_machine(source, machine):
            raise BootstrapRefused("requested quotient failed receiver-owned source recheck")
        field_positions = {field: machine.fields.index(field) for field in selected_fields}
        action_positions = {action: machine.actions.index(action) for action in word}
        start = machine.state_groups[source.states.index(initial_state)]
        groups = len(machine.groups)
        seen: dict[int, int] = {}
        states: list[int] = []
        steps: list[tuple[_EventTemplate, ...]] = []
        state = start
        tick = 0
        while state not in seen:
            if tick > groups:
                raise BootstrapRefused("finite quotient failed deterministic cycle bound")
            seen[state] = tick
            states.append(state)
            events: list[_EventTemplate] = []
            for action_offset, action in enumerate(word):
                state = machine.transitions[state][action_positions[action]]
                observations = machine.outputs[state]
                for rule in rules:
                    if rule.on_action is not None and rule.on_action != action:
                        continue
                    if rule.when_field is not None:
                        observed = observations[field_positions[rule.when_field]]
                        if type(observed) is not type(rule.when_equals) or observed != rule.when_equals:
                            continue
                    events.append(_EventTemplate(
                        tick + 1, action_offset, rule.mailbox,
                        observations[field_positions[rule.value_field]],
                    ))
            steps.append(tuple(events))
            tick += 1
        mu = seen[state]
        lam = tick - mu
        if not 1 <= lam <= groups:
            raise BootstrapRefused("counted stream orbit period is malformed")
        self.source = source
        self.machine = machine
        self.initial_state = initial_state
        self.word = word
        self.rules = rules
        self._states = tuple(states)
        self._steps = tuple(steps)
        self._prefix = tuple(event for step in steps[:mu] for event in step)
        self._cycle = tuple(event for step in steps[mu:] for event in step)
        self._prefix_counts = [0]
        for step in steps:
            self._prefix_counts.append(self._prefix_counts[-1] + len(step))
        self.summary = CountedCycleSummary(
            source.fingerprint, machine.fingerprint, mu, lam,
            len(self._prefix), len(self._cycle), groups,
        )

    def length(self) -> int | None:
        """Mathematics: return finite count or None for a positive-emission period."""

        return None if self.summary.infinite else self.summary.prefix_emissions

    def count_after(self, iterations: int) -> int:
        """Mathematics: count all output events through n complete source action words."""

        n = _coordinate(iterations)
        mu, lam = self.summary.preperiod, self.summary.period
        if n <= mu:
            return self._prefix_counts[n]
        repetitions, remainder = divmod(n - mu, lam)
        return (
            self.summary.prefix_emissions
            + repetitions * self.summary.period_emissions
            + self._prefix_counts[mu + remainder] - self._prefix_counts[mu]
        )

    def quotient_state_after(self, iterations: int) -> int:
        """Mathematics: seek the same observed state after n words via its exact orbit period."""

        n = _coordinate(iterations)
        mu, lam = self.summary.preperiod, self.summary.period
        coordinate = n if n < mu else mu + (n - mu) % lam
        return self._states[coordinate]

    def event(self, index: int) -> CountedEvent:
        """Mathematics: invert the exact cumulative count of the recurring transducer."""

        k = _coordinate(index)
        if k < len(self._prefix):
            item = self._prefix[k]
            iteration = item.iteration
        elif self._cycle:
            repeats, offset = divmod(k - len(self._prefix), len(self._cycle))
            item = self._cycle[offset]
            iteration = item.iteration + repeats * self.summary.period
        else:
            raise IndexError("requested event is absent from finite output stream")
        if iteration.bit_length() > _MAX_COORDINATE_BITS:
            raise BootstrapRefused("selected source logical time exceeds the admitted bit width")
        return CountedEvent(k, iteration, item.offset, item.mailbox, item.value)

    def request(self, index: int) -> CountedStreamRequest:
        """Mathematics: retain observer intention including the exact output ordinal."""

        return CountedStreamRequest(
            self.initial_state, self.word, self.rules, _coordinate(index)
        )

    def issue_receipt(self, index: int) -> CountedStreamReceipt:
        """Mathematics: bind selected event and its source-checked quotient Ground."""

        event = self.event(index)
        return CountedStreamReceipt(
            self.summary.source_digest, self.summary.quotient_digest,
            self.request(index), event,
        )


def verify_counted_stream_receipt(
    receipt: CountedStreamReceipt,
    source: FiniteObserverLaw,
    *,
    expected_request: CountedStreamRequest | None = None,
) -> bool:
    """Mathematics: independently compile source quotient and verify selected event.

    A caller may require mathematical validity alone or additionally pin the
    original request. Receipt digests alone convey no trust or execution grant.
    """

    if not isinstance(receipt, CountedStreamReceipt):
        return False
    try:
        if (receipt.source_digest != source.fingerprint
                or expected_request is not None and (
                    type(expected_request) is not CountedStreamRequest
                    or _canonical(expected_request.to_dict()) != _canonical(receipt.request.to_dict())
                )):
            return False
        stream = CountedObserverStream(
            source, initial_state=receipt.request.initial_state,
            word=receipt.request.word, rules=receipt.request.rules,
        )
        expected = stream.issue_receipt(receipt.request.index)
        return expected.to_bytes() == receipt.to_bytes()
    except (BootstrapRefused, IndexError, ValueError, TypeError, OverflowError):
        return False
