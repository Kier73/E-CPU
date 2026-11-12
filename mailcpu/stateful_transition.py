"""Stateful verified transition execution with revision continuity and hash-chained events."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .transition_space import (
    FiniteTransitionProgram,
    compile_live_compositional_transition_program,
)


SCHEMA = "mailcpu.stateful-transition-runtime.v1"
COMPILER_ID = "mailcpu.transition_space.compile_live_compositional_transition_program"
_GENESIS_DOMAIN = "mailcpu.stateful-transition-runtime.genesis.v1"


class StatefulTransitionError(ValueError):
    """A runtime input, revision, snapshot, or event chain violates its contract."""


@dataclass(frozen=True, slots=True)
class TransitionStep:
    """The committed result of one logical transition tick."""

    tick: int
    revision: int
    state: tuple[int, ...]
    program_digest: str
    model_digest: str
    event_digest: str


def _bit(value: Any, label: str) -> int:
    """Accept only strict Boolean bits, excluding numeric values such as 0.0."""
    if isinstance(value, bool):
        return int(value)
    if type(value) is int and value in (0, 1):
        return value
    raise StatefulTransitionError(f"{label} must be a Boolean bit (0 or 1)")


def _canonical_json(value: Any) -> str:
    """Encode a JSON-compatible value deterministically and reject non-finite numbers."""
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise StatefulTransitionError("runtime payload is not canonical JSON data") from exc


def _digest(value: Any) -> str:
    """Return the SHA-256 digest of one canonical JSON value."""
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _copy_json(value: Any) -> Any:
    """Create a detached JSON-compatible copy of an event or snapshot value."""
    return json.loads(_canonical_json(value))


class StatefulTransitionRuntime:
    """Own a live Boolean state, verified ReLU model, logical tick, and event chain.

    The runtime is generic over a typed finite Boolean transition program. A
    subset of program inputs is designated as state registers; all remaining
    input names are controls supplied on each tick. Program outputs replace the
    state registers in their declared order.

    Revisions are accepted only when they preserve the input/output interface
    and compile successfully to a liveness-compacted ReLU model. Applying a
    revision preserves the current state and logical tick while incrementing
    a separate model-revision counter.
    """

    def __init__(
        self,
        program: FiniteTransitionProgram,
        initial_state: Sequence[int],
        *,
        state_input_names: Sequence[str] = ("state_1", "state_0"),
    ) -> None:
        """Construct a runtime and verify the initial program/model pairing."""
        if not isinstance(program, FiniteTransitionProgram):
            raise StatefulTransitionError("program must be a FiniteTransitionProgram")
        state_names = tuple(state_input_names)
        if not state_names or len(set(state_names)) != len(state_names):
            raise StatefulTransitionError("state_input_names must be nonempty and unique")
        if any(name not in program.input_names for name in state_names):
            raise StatefulTransitionError("every state input name must exist in the program")
        if len(program.output_names) != len(state_names):
            raise StatefulTransitionError(
                "the program must produce one next-state output per state register"
            )
        state = tuple(_bit(value, "initial state") for value in initial_state)
        if len(state) != len(state_names):
            raise StatefulTransitionError("initial state width does not match state registers")

        self._initial_program = _copy_json(program.to_dict())
        self._program = program
        self._model = compile_live_compositional_transition_program(program)
        self._initial_state = state
        self._state = state
        self._state_input_names = state_names
        self._control_names = tuple(
            name for name in program.input_names if name not in set(state_names)
        )
        self._tick = 0
        self._revision = 0
        self._events: list[dict[str, Any]] = []
        self._genesis_digest = _digest(
            {
                "domain": _GENESIS_DOMAIN,
                "schema": SCHEMA,
                "initial_state": list(state),
                "state_input_names": list(state_names),
                "initial_program_digest": program.digest,
                "initial_model_digest": self._model.digest,
                "compiler_id": COMPILER_ID,
            }
        )
        self._chain_head_digest = self._genesis_digest

    @property
    def state(self) -> tuple[int, ...]:
        """Return the current immutable state-register vector."""
        return self._state

    @property
    def tick(self) -> int:
        """Return the number of committed transition steps."""
        return self._tick

    @property
    def revision(self) -> int:
        """Return the number of accepted model/program revisions."""
        return self._revision

    @property
    def program(self) -> FiniteTransitionProgram:
        """Return the current immutable typed transition program."""
        return self._program

    @property
    def program_digest(self) -> str:
        """Return the content digest of the current typed transition program."""
        return self._program.digest

    @property
    def model_digest(self) -> str:
        """Return the content digest of the current compiled ReLU realization."""
        return self._model.digest

    @property
    def model_parameter_count(self) -> int:
        """Return the dense parameter count of the currently active ReLU model."""
        return self._model.parameter_count

    @property
    def model_active_parameter_count(self) -> int:
        """Return the number of nonzero weights and biases in the active model."""
        return self._model.active_parameter_count

    @property
    def state_input_names(self) -> tuple[str, ...]:
        """Return the ordered names that carry the live state vector."""
        return self._state_input_names

    @property
    def control_names(self) -> tuple[str, ...]:
        """Return the ordered input names supplied externally on each transition."""
        return self._control_names

    @property
    def event_count(self) -> int:
        """Return the number of committed step and revision events."""
        return len(self._events)

    @property
    def chain_head_digest(self) -> str:
        """Return the digest of the latest event, or the initial genesis record."""
        return self._chain_head_digest

    @property
    def events(self) -> tuple[dict[str, Any], ...]:
        """Return detached event records in append order."""
        return tuple(_copy_json(event) for event in self._events)

    def _append_event(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Bind a payload to the prior chain head and append its content digest."""
        event_payload = {
            "sequence": len(self._events) + 1,
            "previous_event_digest": self._chain_head_digest,
            **dict(payload),
        }
        event_digest = _digest(event_payload)
        event = {**event_payload, "event_digest": event_digest}
        self._events.append(event)
        self._chain_head_digest = event_digest
        return event

    def step(self, controls: Mapping[str, int]) -> TransitionStep:
        """Execute one transition, verify the neural result, and commit a hashed event."""
        if not isinstance(controls, Mapping):
            raise StatefulTransitionError("controls must be a mapping of declared input names")
        if set(controls) != set(self._control_names):
            missing = sorted(set(self._control_names) - set(controls))
            extra = sorted(set(controls) - set(self._control_names))
            raise StatefulTransitionError(
                f"controls do not match the declared interface (missing={missing}, extra={extra})"
            )

        control_values = {
            name: _bit(controls[name], f"control {name}")
            for name in self._control_names
        }
        input_values: dict[str, int] = dict(zip(self._state_input_names, self._state))
        input_values.update(control_values)
        ordered_inputs = tuple(input_values[name] for name in self._program.input_names)
        expected_outputs = self._program.evaluate(input_values)
        neural_outputs = self._model.predict(ordered_inputs)
        if neural_outputs != expected_outputs:
            raise StatefulTransitionError(
                "the active neural model diverged from its typed transition program"
            )

        next_state = tuple(neural_outputs)
        tick_before = self._tick
        event = self._append_event(
            {
                "kind": "step",
                "tick_before": tick_before,
                "tick_after": tick_before + 1,
                "revision": self._revision,
                "state_before": list(self._state),
                "state_after": list(next_state),
                "controls": {
                    name: control_values[name] for name in self._control_names
                },
                "input_values": {
                    name: input_values[name] for name in self._program.input_names
                },
                "outputs": list(neural_outputs),
                "program_digest": self._program.digest,
                "model_digest": self._model.digest,
            }
        )
        self._state = next_state
        self._tick = tick_before + 1
        return TransitionStep(
            tick=self._tick,
            revision=self._revision,
            state=self._state,
            program_digest=self._program.digest,
            model_digest=self._model.digest,
            event_digest=event["event_digest"],
        )

    def revise(self, target_program: FiniteTransitionProgram) -> dict[str, Any]:
        """Install a fully compiled compatible program without changing live state or tick."""
        if not isinstance(target_program, FiniteTransitionProgram):
            raise StatefulTransitionError("target_program must be a FiniteTransitionProgram")
        if (
            target_program.input_names != self._program.input_names
            or target_program.output_names != self._program.output_names
        ):
            raise StatefulTransitionError("a model revision must preserve the exact interface")
        if target_program.digest == self._program.digest:
            raise StatefulTransitionError("a no-op program revision is not a new model revision")

        target_model = compile_live_compositional_transition_program(target_program)
        source_program_digest = self._program.digest
        source_model_digest = self._model.digest
        revision_before = self._revision
        revision_after = revision_before + 1
        event = self._append_event(
            {
                "kind": "revision",
                "tick": self._tick,
                "revision_before": revision_before,
                "revision_after": revision_after,
                "state_preserved": list(self._state),
                "source_program_digest": source_program_digest,
                "target_program_digest": target_program.digest,
                "source_model_digest": source_model_digest,
                "target_model_digest": target_model.digest,
                "target_program": target_program.to_dict(),
            }
        )
        self._program = target_program
        self._model = target_model
        self._revision = revision_after
        return _copy_json(event)

    def snapshot(self) -> dict[str, Any]:
        """Return a replayable snapshot with program, model, state, counters, and hash chain."""
        return {
            "schema": SCHEMA,
            "compiler_id": COMPILER_ID,
            "initial_state": list(self._initial_state),
            "state_input_names": list(self._state_input_names),
            "initial_program": self._initial_program_payload(),
            "current_program": self._program.to_dict(),
            "current_model": self._model.snapshot(),
            "state": list(self._state),
            "tick": self._tick,
            "revision": self._revision,
            "events": list(self.events),
            "genesis_digest": self._genesis_digest,
            "chain_head_digest": self._chain_head_digest,
        }

    def _initial_program_payload(self) -> dict[str, Any]:
        """Return the detached initial source program retained from construction."""
        return _copy_json(self._initial_program)

    @classmethod
    def from_snapshot(cls, payload: Mapping[str, Any]) -> "StatefulTransitionRuntime":
        """Restore a runtime only after replaying and validating every chained event."""
        required = {
            "schema",
            "compiler_id",
            "initial_state",
            "state_input_names",
            "initial_program",
            "current_program",
            "current_model",
            "state",
            "tick",
            "revision",
            "events",
            "genesis_digest",
            "chain_head_digest",
        }
        if not isinstance(payload, Mapping) or set(payload) != required:
            raise StatefulTransitionError("runtime snapshot fields do not match the schema")
        if payload["schema"] != SCHEMA or payload["compiler_id"] != COMPILER_ID:
            raise StatefulTransitionError("unsupported runtime or compiler schema")
        if not isinstance(payload["events"], list):
            raise StatefulTransitionError("runtime events must be an ordered array")

        initial_program = FiniteTransitionProgram.from_dict(payload["initial_program"])
        runtime = cls(
            initial_program,
            payload["initial_state"],
            state_input_names=payload["state_input_names"],
        )
        if payload["genesis_digest"] != runtime._genesis_digest:
            raise StatefulTransitionError("runtime genesis digest mismatch")
        for stored_event in payload["events"]:
            if not isinstance(stored_event, Mapping) or stored_event.get("kind") not in (
                "step",
                "revision",
            ):
                raise StatefulTransitionError("runtime event has an unknown event type")
            if stored_event["kind"] == "step":
                generated = runtime.step(stored_event.get("controls", {}))
            else:
                target_payload = stored_event.get("target_program")
                target_program = FiniteTransitionProgram.from_dict(target_payload)
                generated = runtime.revise(target_program)
            generated_event = (
                runtime._events[-1]
                if stored_event["kind"] == "step"
                else generated
            )
            if _canonical_json(generated_event) != _canonical_json(stored_event):
                raise StatefulTransitionError(
                    f"event {stored_event.get('sequence')} failed replay or digest verification"
                )

        current_program = FiniteTransitionProgram.from_dict(payload["current_program"])
        if current_program.digest != runtime.program_digest:
            raise StatefulTransitionError("current program does not match replayed revisions")
        if _canonical_json(runtime._model.snapshot()) != _canonical_json(payload["current_model"]):
            raise StatefulTransitionError("current model snapshot does not match replayed program")
        if (
            tuple(payload["state"]) != runtime.state
            or type(payload["tick"]) is not int
            or payload["tick"] != runtime.tick
            or type(payload["revision"]) is not int
            or payload["revision"] != runtime.revision
            or payload["chain_head_digest"] != runtime.chain_head_digest
        ):
            raise StatefulTransitionError("runtime terminal state or counters do not match replay")
        runtime._assert_runtime_invariants()
        return runtime

    def _assert_runtime_invariants(self) -> None:
        """Recheck interface, model/source identity, and chain linkage after replay."""
        if self._model.program_digest != self._program.digest:
            raise StatefulTransitionError("active model is not bound to the active program")
        if len(self._state) != len(self._state_input_names):
            raise StatefulTransitionError("runtime state width changed unexpectedly")
        previous = self._genesis_digest
        for sequence, event in enumerate(self._events, start=1):
            if event.get("sequence") != sequence:
                raise StatefulTransitionError("event sequence is not contiguous")
            if event.get("previous_event_digest") != previous:
                raise StatefulTransitionError("event chain predecessor digest mismatch")
            event_payload = {
                key: value for key, value in event.items() if key != "event_digest"
            }
            expected = _digest(event_payload)
            if event.get("event_digest") != expected:
                raise StatefulTransitionError("event digest mismatch")
            previous = expected
        if previous != self._chain_head_digest:
            raise StatefulTransitionError("event chain head digest mismatch")
