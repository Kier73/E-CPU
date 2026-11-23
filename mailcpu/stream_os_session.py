"""Quorum-admitted HeadlessOS continuation from independently executed state bytes.

A remote observer-host proposes an OS successor using the existing M3
ComputationalSessionTransitionAdapter. This backend independently validates
the proposal against a closed, reference HeadlessOS execution before the
adapter publishes it through the existing M1/quorum CAS. Neither the remote
host nor a transport frame gains authority to choose the session high-water.
"""

from __future__ import annotations

import hashlib
import json
from typing import Callable, Mapping

from .computational_transition import (
    ComputationalTransitionContext,
    ComputationalTransitionError,
)
from .headless import HeadlessOS
from .headless_relation import HeadlessRelationError, compare_headless_os_states, observe_headless_os_state


OS_STATE_SCHEMA = "mailcpu.headless-snapshot.v1"
OS_STEP_INPUT_SCHEMA = "mailcpu.headless-pure-step.v1"
OS_TRANSITION_ID = "headless.os.continue.v1"
OS_BACKEND_FINGERPRINT = hashlib.sha256(
    b"mailcpu.headless-closed-state-reference-backend.v1"
).hexdigest()
OS_INTERPRETATION_FINGERPRINT = hashlib.sha256(
    b"mailcpu.headless-os-native-snapshot-and-scheduler-relation.v1"
).hexdigest()


def _canonical(value: object) -> bytes:
    """Encode an OS state or operation as canonical UTF-8 JSON without NaN."""
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ComputationalTransitionError("HeadlessOS state is outside canonical JSON") from exc


def _decode(data: bytes, description: str) -> Mapping[str, object]:
    """Reject duplicate keys, floats outside JSON, non-mappings and noncanonical bytes."""
    if not isinstance(data, bytes):
        raise ComputationalTransitionError(description + " must be exact bytes")
    def unique_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
        """Refuse ambiguous JSON duplicate field identities before interpretation."""
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON field")
            result[key] = value
        return result
    try:
        record = json.loads(
            data.decode("utf-8"),
            object_pairs_hook=unique_pairs,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError("non-finite JSON")),
        )
    except (UnicodeError, ValueError) as exc:
        raise ComputationalTransitionError(description + " cannot be decoded") from exc
    if not isinstance(record, dict) or _canonical(record) != data:
        raise ComputationalTransitionError(description + " must be a canonical JSON object")
    return record


def serialize_headless_state(operating_system: HeadlessOS) -> bytes:
    """Observe a closed native HeadlessOS and serialize its entire checkpoint."""
    if not isinstance(operating_system, HeadlessOS):
        raise TypeError("operating_system must be HeadlessOS")
    observed = observe_headless_os_state(operating_system)
    return _canonical(observed.payload["operating_system"])


def restore_headless_state(state_bytes: bytes) -> HeadlessOS:
    """Recreate an independently verified OS from canonical state bytes."""
    record = _decode(state_bytes, "HeadlessOS state")
    try:
        machine = HeadlessOS.from_snapshot(dict(record))
        observe_headless_os_state(machine)
    except (KeyError, ValueError, TypeError, HeadlessRelationError) as exc:
        raise ComputationalTransitionError("HeadlessOS state fails native reconstruction") from exc
    if serialize_headless_state(machine) != state_bytes:
        raise ComputationalTransitionError("reconstructed HeadlessOS state differs from input")
    return machine


def encode_headless_step(*, ticks: int, read_fd: int | None = None, read_size: int = 0) -> bytes:
    """Build a typed, bounded request for closed-state OS scheduler transitions."""
    if type(ticks) is not int or not 1 <= ticks <= 200:
        raise ComputationalTransitionError("ticks must be an integer in [1,200]")
    if read_fd is None:
        if read_size != 0:
            raise ComputationalTransitionError("read_size requires read_fd")
    elif type(read_fd) is not int or read_fd < 0:
        raise ComputationalTransitionError("read_fd must be a nonnegative integer")
    if type(read_size) is not int or not 0 <= read_size <= 4096:
        raise ComputationalTransitionError("read_size is outside the bounded virtual read range")
    return _canonical({
        "schema": OS_STEP_INPUT_SCHEMA,
        "ticks": ticks,
        "read_fd": read_fd,
        "read_size": read_size,
    })


def _step(machine: HeadlessOS, step_bytes: bytes) -> HeadlessOS:
    """Apply only snapshot-covered virtual I/O and an explicit scheduler budget."""
    record = _decode(step_bytes, "HeadlessOS operation")
    if set(record) != {"schema", "ticks", "read_fd", "read_size"}:
        raise ComputationalTransitionError("HeadlessOS operation has unknown or missing fields")
    if record["schema"] != OS_STEP_INPUT_SCHEMA:
        raise ComputationalTransitionError("HeadlessOS operation schema differs")
    ticks, fd, size = record["ticks"], record["read_fd"], record["read_size"]
    if type(ticks) is not int or not 1 <= ticks <= 200:
        raise ComputationalTransitionError("HeadlessOS scheduler budget is outside [1,200]")
    if fd is None:
        if size != 0:
            raise ComputationalTransitionError("virtual read_size requires read_fd")
    elif type(fd) is not int or fd < 0:
        raise ComputationalTransitionError("virtual file descriptor is invalid")
    if type(size) is not int or not 0 <= size <= 4096:
        raise ComputationalTransitionError("virtual read size is outside [0,4096]")
    if fd is not None:
        try:
            result = machine.syscall(machine.environment.init_pid, "read", fd=fd, size=size)
        except Exception as exc:
            raise ComputationalTransitionError("virtual read syscall refused") from exc
        if not isinstance(result, bytes):
            raise ComputationalTransitionError("virtual read did not produce byte evidence")
    machine.run(max_ticks=ticks)
    observe_headless_os_state(machine)
    return machine


class HeadlessOSQuorumTransitionBackend:
    """Verify a proposed remote OS successor before an M3 adapter may quorum-commit it."""

    backend_fingerprint = OS_BACKEND_FINGERPRINT

    def __init__(
        self,
        execute_remote: Callable[[bytes, bytes, ComputationalTransitionContext], bytes],
        *,
        max_state_bytes: int = 4_194_304,
    ) -> None:
        """Bind a preconfigured observer-host executor; admission remains at the M3 caller."""
        if not callable(execute_remote):
            raise TypeError("execute_remote must be callable")
        if type(max_state_bytes) is not int or max_state_bytes <= 0:
            raise ValueError("max_state_bytes must be a positive integer")
        self.execute_remote = execute_remote
        self.max_state_bytes = max_state_bytes
        self.remote_calls = 0
        self.last_verified_successor_digest: str | None = None

    def transition(
        self,
        state_bytes: bytes,
        input_bytes: bytes,
        context: ComputationalTransitionContext,
    ) -> bytes:
        """Require exact M3 input coordinates and native equivalence before publication."""
        if not isinstance(context, ComputationalTransitionContext):
            raise ComputationalTransitionError("HeadlessOS transition requires verified M3 context")
        if context.state_schema_id != OS_STATE_SCHEMA:
            raise ComputationalTransitionError("M3 HeadlessOS state schema differs")
        if context.execution_backend_fingerprint != self.backend_fingerprint:
            raise ComputationalTransitionError("HeadlessOS backend fingerprint differs")
        if context.interpretation_fingerprint != OS_INTERPRETATION_FINGERPRINT:
            raise ComputationalTransitionError("HeadlessOS interpretation fingerprint differs")
        if hashlib.sha256(state_bytes).hexdigest() != context.state_digest:
            raise ComputationalTransitionError("M3 state bytes differ from bound state digest")
        if len(state_bytes) > self.max_state_bytes:
            raise ComputationalTransitionError("OS state exceeds declared byte budget")
        # Verify the source before any remote work; the reference state is
        # reconstructed independently from the remote observer's implementation.
        reference = restore_headless_state(state_bytes)
        _decode(input_bytes, "HeadlessOS operation")
        self.remote_calls += 1
        candidate = self.execute_remote(state_bytes, input_bytes, context)
        if not isinstance(candidate, bytes) or len(candidate) > self.max_state_bytes:
            raise ComputationalTransitionError("remote OS proposal must be bounded state bytes")
        restored = restore_headless_state(candidate)
        _step(reference, input_bytes)
        relation = compare_headless_os_states(reference, restored)
        if not relation.equivalent:
            raise ComputationalTransitionError(
                "remote OS proposal disagrees with native reference transition: "
                + ",".join(relation.difference_paths[:4])
            )
        self.last_verified_successor_digest = hashlib.sha256(candidate).hexdigest()
        return candidate


def execute_headless_step(state_bytes: bytes, input_bytes: bytes) -> bytes:
    """Execute an isolated pure OS step for a separately bound observer-host."""
    machine = restore_headless_state(state_bytes)
    _step(machine, input_bytes)
    return serialize_headless_state(machine)
