"""Reusable inverse indexes for finite, path-dependent process trajectories.

The index in this module does not discover an unknown state-space. It compiles
an explicitly supplied, already observed transition path after validating every
guard, update, invariant, and resource requirement. Exact state lookup is then
expected O(1), and the returned prefix remains independently replay-verifiable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import re
from typing import Any, Mapping, Sequence

from .navigation import (
    NavigationError,
    NavigationResult,
    NavigationStatus,
    NavigationWitness,
    ProcessContext,
    ProcessDescriptor,
    SemanticAddress,
)


class ProcessPathIndexError(NavigationError):
    """Mathematics: a supplied process trace or inverse state index is malformed or incompatible."""


_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")


def _canonical_json(value: Any, label: str) -> str:
    """Mathematics: encode finite JSON state using deterministic sorted compact bytes."""
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ProcessPathIndexError(f"{label} must be finite canonical JSON") from exc


def _state_digest(state: Mapping[str, Any]) -> str:
    """Mathematics: identify one process state as SHA256(canonical_json(state))."""
    return hashlib.sha256(_canonical_json(state, "process state").encode("utf-8")).hexdigest()


def _is_digest(value: Any) -> bool:
    """Mathematics: recognize one lowercase 256-bit hexadecimal digest."""
    return isinstance(value, str) and _DIGEST.fullmatch(value) is not None


def _frozen_envelope(value: Mapping[str, int]) -> tuple[tuple[str, int], ...]:
    """Mathematics: convert a resource envelope to a stable sorted finite vector."""
    if not isinstance(value, Mapping):
        raise ProcessPathIndexError("resource envelope must be an object")
    items: list[tuple[str, int]] = []
    for name, amount in value.items():
        if not isinstance(name, str) or _IDENTIFIER.fullmatch(name) is None:
            raise ProcessPathIndexError("resource envelope names must be safe identifiers")
        if type(amount) is not int or amount < 0:
            raise ProcessPathIndexError("resource envelope values must be non-negative integers")
        items.append((name, amount))
    return tuple(sorted(items))


@dataclass(frozen=True)
class ProcessPathIndex:
    """Content-addressed inverse index over one validated declarative transition path.

    Mathematics:
    For path states s_0,...,s_n, store I[H(s)] = min{i | H(s_i)=H(s)}.
    The trace is verified once at build time; exact-state lookup thereafter is
    expected O(1), independent of the path length.
    """

    descriptor_digest: str
    context_digest: str
    start_state_digest: str
    transition_ids: tuple[str, ...]
    state_digests: tuple[str, ...]
    resource_envelopes: tuple[tuple[tuple[str, int], ...], ...]
    _first_coordinates: dict[str, int] = field(init=False, repr=False, compare=False)
    _verified: bool = field(init=False, repr=False, compare=False, default=False)

    def __post_init__(self) -> None:
        """Mathematics: enforce path, endpoint, digest, and prefix-envelope dimensions."""
        for name in ("descriptor_digest", "context_digest", "start_state_digest"):
            if not _is_digest(getattr(self, name)):
                raise ProcessPathIndexError(f"{name} must be a lowercase SHA-256 digest")
        if not isinstance(self.transition_ids, (tuple, list)):
            raise ProcessPathIndexError("transition_ids must be a finite sequence")
        transitions = tuple(self.transition_ids)
        if any(not isinstance(item, str) or _IDENTIFIER.fullmatch(item) is None for item in transitions):
            raise ProcessPathIndexError("transition_ids contain an invalid identifier")
        if not isinstance(self.state_digests, (tuple, list)):
            raise ProcessPathIndexError("state_digests must be a finite sequence")
        states = tuple(self.state_digests)
        if len(states) != len(transitions) + 1:
            raise ProcessPathIndexError("a path index must have exactly one more state than transition")
        if any(not _is_digest(item) for item in states):
            raise ProcessPathIndexError("state_digests contain an invalid SHA-256 digest")
        if states[0] != self.start_state_digest:
            raise ProcessPathIndexError("first indexed state does not match start_state_digest")
        if not isinstance(self.resource_envelopes, (tuple, list)) or len(self.resource_envelopes) != len(states):
            raise ProcessPathIndexError("resource_envelopes must align with every indexed state")
        envelopes = tuple(_frozen_envelope(dict(item)) for item in self.resource_envelopes)
        first: dict[str, int] = {}
        for coordinate, digest in enumerate(states):
            first.setdefault(digest, coordinate)
        object.__setattr__(self, "transition_ids", transitions)
        object.__setattr__(self, "state_digests", states)
        object.__setattr__(self, "resource_envelopes", envelopes)
        object.__setattr__(self, "_first_coordinates", first)
        object.__setattr__(self, "_verified", False)

    @classmethod
    def build(
        cls,
        descriptor: ProcessDescriptor,
        context: ProcessContext,
        transition_ids: Sequence[str],
    ) -> "ProcessPathIndex":
        """Compile a caller-supplied observed path after validating every declared transition.

        Mathematics:
        Evaluates the exact path recurrence s_{i+1}=T_i(s_i) for the supplied
        rule sequence only. It does not expand alternative branches or perform
        breadth-first search. Work is O(path length × transition application).
        """
        if not isinstance(descriptor, ProcessDescriptor) or not isinstance(context, ProcessContext):
            raise ProcessPathIndexError("build requires a ProcessDescriptor and ProcessContext")
        if descriptor.process_id != context.process_id:
            raise ProcessPathIndexError("process context belongs to another descriptor")
        if not isinstance(transition_ids, (tuple, list)):
            raise ProcessPathIndexError("transition_ids must be a finite sequence")
        identifiers = tuple(transition_ids)
        if len(identifiers) > context.max_depth or len(identifiers) > context.max_expansions:
            raise ProcessPathIndexError("supplied trace exceeds the ProcessContext path budget")
        state_value = context.current_state if context.current_state is not None else descriptor.initial_state
        if state_value is None or not isinstance(state_value, Mapping):
            raise ProcessPathIndexError("no current or declared initial process state is available")
        state = json.loads(_canonical_json(state_value, "starting state"))
        if not descriptor.admits(state, context.bindings):
            raise ProcessPathIndexError("starting state violates a process invariant")

        rules = {rule.transition_id: rule for rule in descriptor.transitions}
        state_digests = [_state_digest(state)]
        resource_envelopes: list[tuple[tuple[str, int], ...]] = [()]
        envelope: dict[str, int] = {}
        for coordinate, transition_id in enumerate(identifiers):
            if not isinstance(transition_id, str) or _IDENTIFIER.fullmatch(transition_id) is None:
                raise ProcessPathIndexError(f"invalid transition identifier at coordinate {coordinate}")
            rule = rules.get(transition_id)
            if rule is None:
                raise ProcessPathIndexError(f"transition {transition_id!r} is not declared by the descriptor")
            try:
                enabled = rule.enabled(state, context.bindings)
            except Exception as exc:
                raise ProcessPathIndexError(f"transition guard failed at coordinate {coordinate}") from exc
            if not enabled:
                raise ProcessPathIndexError(f"transition {transition_id!r} is not enabled at coordinate {coordinate}")
            if any(context.resource_capacity.get(name, 0) < required for name, required in rule.resource_requirements.items()):
                raise ProcessPathIndexError(f"transition {transition_id!r} exceeds available resources")
            try:
                candidate = rule.apply(state, context.bindings)
            except Exception as exc:
                raise ProcessPathIndexError(f"transition {transition_id!r} could not be applied") from exc
            if not descriptor.admits(candidate, context.bindings):
                raise ProcessPathIndexError(f"transition {transition_id!r} violates a process invariant")
            state = candidate
            for name, required in rule.resource_requirements.items():
                envelope[name] = max(envelope.get(name, 0), required)
            state_digests.append(_state_digest(state))
            resource_envelopes.append(_frozen_envelope(envelope))

        index = cls(
            descriptor_digest=descriptor.digest,
            context_digest=context.resolution_digest(),
            start_state_digest=state_digests[0],
            transition_ids=identifiers,
            state_digests=tuple(state_digests),
            resource_envelopes=tuple(resource_envelopes),
        )
        object.__setattr__(index, "_verified", True)
        return index

    def coordinate_of(self, state: Mapping[str, Any]) -> int | None:
        """Mathematics: resolve the first indexed coordinate by exact state digest in expected O(1)."""
        if not isinstance(state, Mapping):
            raise ProcessPathIndexError("target state must be an object")
        return self._first_coordinates.get(_state_digest(state))

    def locate_state(
        self,
        descriptor: ProcessDescriptor,
        address: SemanticAddress,
        context: ProcessContext,
        target_state: Mapping[str, Any],
    ) -> NavigationResult:
        """Return a replayable path witness for an exact state already present in the index.

        Mathematics:
        Lookup uses I[H(target_state)] and does not expand intermediate or
        alternative states. Absence is not interpreted as unreachability because
        this index covers one supplied path, not the complete branching state graph.
        """
        if not isinstance(descriptor, ProcessDescriptor) or not isinstance(address, SemanticAddress) or not isinstance(context, ProcessContext):
            raise ProcessPathIndexError("locate_state requires a descriptor, address, and process context")
        if (descriptor.process_id, descriptor.version) != (address.process_id, address.version):
            raise ProcessPathIndexError("semantic address does not identify the descriptor")
        if context.process_id != descriptor.process_id:
            raise ProcessPathIndexError("process context belongs to another descriptor")
        if not self._verified:
            raise ProcessPathIndexError("portable path index must be verified against its descriptor and context before lookup")
        if descriptor.digest != self.descriptor_digest:
            raise ProcessPathIndexError("process descriptor differs from the indexed transition law")
        if context.resolution_digest() != self.context_digest:
            raise ProcessPathIndexError("process context differs from the indexed bindings or resources")
        start_value = context.current_state if context.current_state is not None else descriptor.initial_state
        if start_value is None or _state_digest(start_value) != self.start_state_digest:
            raise ProcessPathIndexError("current starting state differs from the indexed path origin")
        if not isinstance(target_state, Mapping):
            raise ProcessPathIndexError("target_state must be an object")
        target_digest = _state_digest(target_state)
        coordinate = self._first_coordinates.get(target_digest)
        if coordinate is None:
            raise ProcessPathIndexError(
                "target state is absent from this path index; absence is not proof of global unreachability"
            )
        if not descriptor.admits(target_state, context.bindings):
            raise ProcessPathIndexError("target state violates the process descriptor invariants")
        if not address.goal.matches(target_state, context.bindings):
            raise ProcessPathIndexError("target state does not satisfy the semantic address")
        path = self.transition_ids[:coordinate]
        witness = NavigationWitness(
            descriptor.digest,
            address.digest,
            context.resolution_digest(),
            self.start_state_digest,
            target_digest,
            path,
        )
        status = NavigationStatus.ALREADY_SATISFIED if coordinate == 0 else NavigationStatus.FOUND
        envelope = dict(self.resource_envelopes[coordinate])
        return NavigationResult(
            status=status,
            path=path,
            final_state=target_state,
            expanded_states=0,
            resource_envelope=envelope,
            witness=witness,
        )

    def verify(self, descriptor: ProcessDescriptor, context: ProcessContext) -> bool:
        """Mathematics: independently rebuild the indexed supplied path and compare its content identity."""
        if not isinstance(descriptor, ProcessDescriptor) or not isinstance(context, ProcessContext):
            return False
        try:
            rebuilt = ProcessPathIndex.build(descriptor, context, self.transition_ids)
        except (NavigationError, TypeError, ValueError):
            return False
        valid = rebuilt.digest == self.digest
        if valid:
            object.__setattr__(self, "_verified", True)
        return valid

    def _payload(self) -> dict[str, Any]:
        """Mathematics: serialize the non-self-referential process-path index fields."""
        return {
            "schema": "mailcpu.process-path-index.v1",
            "descriptor_digest": self.descriptor_digest,
            "context_digest": self.context_digest,
            "start_state_digest": self.start_state_digest,
            "transition_ids": list(self.transition_ids),
            "state_digests": list(self.state_digests),
            "resource_envelopes": [dict(item) for item in self.resource_envelopes],
        }

    @property
    def digest(self) -> str:
        """Mathematics: hash the complete canonical process-path index payload."""
        return hashlib.sha256(_canonical_json(self._payload(), "process path index").encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        """Mathematics: serialize the path index together with its content digest."""
        return self._payload() | {"index_digest": self.digest}

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ProcessPathIndex":
        """Mathematics: reconstruct a portable path index and reject inconsistent digests or dimensions."""
        expected = {
            "schema", "descriptor_digest", "context_digest", "start_state_digest",
            "transition_ids", "state_digests", "resource_envelopes", "index_digest",
        }
        if not isinstance(payload, Mapping) or set(payload) != expected:
            raise ProcessPathIndexError("process path index fields are invalid")
        if payload["schema"] != "mailcpu.process-path-index.v1":
            raise ProcessPathIndexError("unsupported process path index schema")
        if not isinstance(payload["transition_ids"], list):
            raise ProcessPathIndexError("transition_ids must be an array")
        if not isinstance(payload["state_digests"], list):
            raise ProcessPathIndexError("state_digests must be an array")
        if not isinstance(payload["resource_envelopes"], list):
            raise ProcessPathIndexError("resource_envelopes must be an array")
        index = cls(
            descriptor_digest=payload["descriptor_digest"],
            context_digest=payload["context_digest"],
            start_state_digest=payload["start_state_digest"],
            transition_ids=tuple(payload["transition_ids"]),
            state_digests=tuple(payload["state_digests"]),
            resource_envelopes=tuple(_frozen_envelope(item) for item in payload["resource_envelopes"]),
        )
        if payload["index_digest"] != index.digest:
            raise ProcessPathIndexError("process path index digest does not match its content")
        return index
