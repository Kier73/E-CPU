"""Exact observational witnesses for a closed MailCPU scheduler execution.

This module never fast-forwards or mutates a scheduler. It commits to the
scheduler snapshot, live machine flags, task backend state, FIFO bus queues,
and verified event-journal head. External effects are rejected unless their
state is represented explicitly in the witness boundary.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any, Mapping

SCHEMA = "mailcpu.scheduler-state-relation/v1"
_ZERO = "0" * 64


class SchedulerRelationError(ValueError):
    """The requested state is outside the supported witness domain."""


def _plain(value: Any) -> Any:
    """Convert supported values to deterministic JSON-compatible values."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(item) for item in value]
    if hasattr(value, "value") and isinstance(value.value, (str, int, float, bool)):
        return value.value
    if hasattr(value, "__dataclass_fields__"):
        return {
            name: _plain(getattr(value, name))
            for name in value.__dataclass_fields__
        }
    raise SchedulerRelationError(
        f"non-JSON value in scheduler witness: {type(value).__name__}"
    )


def _bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            _plain(value),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise SchedulerRelationError(
            f"state is not canonical JSON: {exc}"
        ) from exc


def _digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _check_domain(scheduler: Any) -> None:
    """Reject effects whose state is not represented by this scheduler witness."""
    for name in ("syscall_handler", "wait_predicate", "post_step"):
        if getattr(scheduler, name, None) is not None:
            raise SchedulerRelationError(
                f"external {name} is outside the witness boundary"
            )
    tasks = getattr(scheduler, "tasks", None)
    if not isinstance(tasks, Mapping):
        raise SchedulerRelationError("scheduler must expose its task mapping")
    for pid, task in tasks.items():
        backend = getattr(task, "backend", None)
        if backend is None:
            raise SchedulerRelationError(f"task {pid} has no backend")
        if getattr(backend, "syscall_handler", None) is not None:
            raise SchedulerRelationError(
                f"task {pid} has an external syscall handler"
            )
        instructions = getattr(
            getattr(task, "program", None), "instructions", ()
        )
        for instruction in instructions:
            op = getattr(instruction, "op", None)
            if getattr(op, "value", op) == "SYSCALL":
                raise SchedulerRelationError(
                    f"task {pid} contains SYSCALL outside witness"
                )


def _journal_head(journal: Any) -> dict[str, Any]:
    """Verify the journal chain and return its count and terminal commitment."""
    if not callable(getattr(journal, "verify", None)) or not callable(
        getattr(journal, "snapshot", None)
    ):
        raise SchedulerRelationError(
            "journal must expose verify() and snapshot()"
        )
    if not journal.verify():
        raise SchedulerRelationError("event journal hash chain is invalid")
    records = journal.snapshot()
    if not isinstance(records, list):
        raise SchedulerRelationError("journal snapshot must be a list")
    return {
        "record_count": len(records),
        "head_digest": records[-1]["digest"] if records else _ZERO,
    }


@dataclass(frozen=True)
class SchedulerStateObservation:
    tick: int
    digest: str
    payload: Mapping[str, Any]
    canonical_size: int
    journal_records: int
    journal_head: str


def observe_scheduler_state(scheduler: Any) -> SchedulerStateObservation:
    """Observe one complete scheduler boundary and hash its canonical form."""
    _check_domain(scheduler)
    if not callable(getattr(getattr(scheduler, "bus", None), "snapshot", None)):
        raise SchedulerRelationError(
            "scheduler must expose a snapshot-capable bus"
        )
    if not callable(getattr(scheduler, "snapshot", None)):
        raise SchedulerRelationError("scheduler must expose snapshot()")
    snapshot = scheduler.snapshot()
    if not isinstance(snapshot, Mapping):
        raise SchedulerRelationError("scheduler snapshot must be a mapping")

    runtime: dict[str, Any] = {}
    for raw_pid, task in sorted(
        scheduler.tasks.items(), key=lambda item: int(item[0])
    ):
        state = getattr(task, "state", None)
        backend = getattr(task, "backend", None)
        if state is None or not callable(getattr(backend, "snapshot", None)):
            raise SchedulerRelationError(
                f"task {raw_pid} lacks state/backend snapshot"
            )
        runtime[str(raw_pid)] = {
            "pc": int(state.pc),
            "steps": int(state.steps),
            "halted": bool(state.halted),
            "blocked": bool(state.blocked),
            "registers": _plain(getattr(state, "registers", {})),
            "backend": _plain(backend.snapshot()),
            "status": str(
                getattr(
                    getattr(task, "status", None),
                    "value",
                    getattr(task, "status", ""),
                )
            ),
            "wait_request": _plain(getattr(task, "wait_request", None)),
            "wake_request": _plain(getattr(task, "wake_request", None)),
            "chemical_cost": float(getattr(task, "chemical_cost", 0.0)),
            "horizon_tracker": _plain(
                getattr(task, "horizon_tracker", None)
            ),
        }

    journal = _journal_head(scheduler.journal)
    payload = {
        "schema": SCHEMA,
        "scheduler": _plain(snapshot),
        "runtime": runtime,
        "bus": _plain(scheduler.bus.snapshot()),
        "journal": journal,
    }
    encoded = _bytes(payload)
    return SchedulerStateObservation(
        tick=int(scheduler.tick),
        digest=_digest(encoded),
        payload=payload,
        canonical_size=len(encoded),
        journal_records=int(journal["record_count"]),
        journal_head=str(journal["head_digest"]),
    )


def _diff(
    left: Any, right: Any, path: str = "$", limit: int = 16
) -> list[str]:
    if left == right:
        return []
    if limit <= 0:
        return [path + " (more differences omitted)"]
    if isinstance(left, Mapping) and isinstance(right, Mapping):
        result: list[str] = []
        for key in sorted(set(left) | set(right), key=str):
            child = f"{path}.{key}"
            if key not in left or key not in right:
                result.append(child)
            else:
                result.extend(
                    _diff(left[key], right[key], child, limit - len(result))
                )
            if len(result) >= limit:
                break
        return result or [path]
    if isinstance(left, list) and isinstance(right, list):
        result = [f"{path}.length"] if len(left) != len(right) else []
        for index, (a, b) in enumerate(zip(left, right)):
            result.extend(
                _diff(a, b, f"{path}[{index}]", limit - len(result))
            )
            if len(result) >= limit:
                break
        return result or [path]
    return [path]


@dataclass(frozen=True)
class SchedulerRelationReport:
    equivalent: bool
    left_digest: str
    right_digest: str
    difference_paths: tuple[str, ...] = ()


def compare_scheduler_states(
    left: Any, right: Any
) -> SchedulerRelationReport:
    """Compare two full observed scheduler boundaries and report changed paths."""
    left_obs = observe_scheduler_state(left)
    right_obs = observe_scheduler_state(right)
    equal = (
        left_obs.digest == right_obs.digest
        and left_obs.payload == right_obs.payload
    )
    differences = (
        ()
        if equal
        else tuple(_diff(left_obs.payload, right_obs.payload))
    )
    return SchedulerRelationReport(
        equal, left_obs.digest, right_obs.digest, differences
    )


def _event(event: Any) -> dict[str, Any]:
    names = (
        "tick", "pid", "name", "pc_before", "op", "pc_after",
        "status_after", "args", "registers", "output_delta",
    )
    if any(not hasattr(event, name) for name in names):
        raise SchedulerRelationError(
            "ScheduleEvent is missing required fields"
        )
    return {name: _plain(getattr(event, name)) for name in names}


@dataclass(frozen=True)
class SchedulerTraceWitness:
    """Per-boundary digest witness; not a reconstructable VM trace."""
    initial_tick: int
    final_tick: int
    boundary_digests: tuple[str, ...]
    event_digests: tuple[str, ...]
    receipt: str
    state_payload_bytes_observed: int
    event_payload_bytes_observed: int

    @property
    def transition_count(self) -> int:
        return len(self.event_digests)

    @property
    def witness_bytes_estimate(self) -> int:
        """Digest-only size estimate, excluding Python object overhead."""
        return (
            len(self.boundary_digests) + len(self.event_digests) + 1
        ) * 32


def _extend(
    previous: str, index: int, event_digest: str, state_digest: str
) -> str:
    row = {
        "index": index,
        "event_digest": event_digest,
        "state_digest": state_digest,
    }
    return _digest(bytes.fromhex(previous) + _bytes(row))


def verify_scheduler_trace_witness(
    witness: SchedulerTraceWitness,
) -> bool:
    """Verify digest formatting, witness shape, and ordered receipt chain."""
    if (
        len(witness.boundary_digests) != len(witness.event_digests) + 1
        or not witness.boundary_digests
    ):
        return False
    if (
        witness.initial_tick < 0
        or witness.final_tick < witness.initial_tick
        or witness.state_payload_bytes_observed < 0
        or witness.event_payload_bytes_observed < 0
    ):
        return False
    digests = (
        *witness.boundary_digests,
        *witness.event_digests,
        witness.receipt,
    )
    if any(not isinstance(item, str) or len(item) != 64 for item in digests):
        return False
    try:
        for item in digests:
            bytes.fromhex(item)
        previous = _ZERO
        for index, event_digest in enumerate(witness.event_digests):
            previous = _extend(
                previous,
                index,
                event_digest,
                witness.boundary_digests[index + 1],
            )
    except ValueError:
        return False
    return previous == witness.receipt


def capture_scheduler_trace(
    scheduler: Any, max_transitions: int = 100_000
) -> SchedulerTraceWitness:
    """Capture one accepted scheduler transition per call; never skip VM state."""
    if max_transitions < 0:
        raise ValueError("max_transitions must be non-negative")
    initial = observe_scheduler_state(scheduler)
    boundaries = [initial.digest]
    events: list[str] = []
    state_bytes = initial.canonical_size
    event_bytes = 0
    receipt = _ZERO

    while len(events) < max_transitions:
        before = int(scheduler.tick)
        batch = scheduler.run(max_ticks=before + 1)
        if not batch:
            break
        if (
            len(batch) != 1
            or int(batch[0].tick) != before
            or int(scheduler.tick) != before + 1
        ):
            raise SchedulerRelationError(
                "one-tick capture did not produce exactly one accepted event"
            )
        event_payload = _bytes(_event(batch[0]))
        event_digest = _digest(event_payload)
        after = observe_scheduler_state(scheduler)
        receipt = _extend(
            receipt, len(events), event_digest, after.digest
        )
        events.append(event_digest)
        boundaries.append(after.digest)
        event_bytes += len(event_payload)
        state_bytes += after.canonical_size

    final = observe_scheduler_state(scheduler)
    if final.digest != boundaries[-1]:
        raise SchedulerRelationError(
            "scheduler changed after final witnessed boundary"
        )
    witness = SchedulerTraceWitness(
        initial_tick=initial.tick,
        final_tick=final.tick,
        boundary_digests=tuple(boundaries),
        event_digests=tuple(events),
        receipt=receipt,
        state_payload_bytes_observed=state_bytes,
        event_payload_bytes_observed=event_bytes,
    )
    if not verify_scheduler_trace_witness(witness):
        raise SchedulerRelationError("trace receipt failed verification")
    return witness


@dataclass(frozen=True)
class SchedulerTraceRelationReport:
    equivalent: bool
    first_divergence: int | None
    reason: str | None
    left_receipt: str
    right_receipt: str


def compare_scheduler_traces(
    left: SchedulerTraceWitness,
    right: SchedulerTraceWitness,
) -> SchedulerTraceRelationReport:
    """Compare initial state, every event, and every post-transition state."""
    if (
        not verify_scheduler_trace_witness(left)
        or not verify_scheduler_trace_witness(right)
    ):
        return SchedulerTraceRelationReport(
            False, 0, "invalid witness receipt", left.receipt, right.receipt
        )
    if (
        left.initial_tick != right.initial_tick
        or left.boundary_digests[0] != right.boundary_digests[0]
    ):
        return SchedulerTraceRelationReport(
            False, 0, "initial states differ", left.receipt, right.receipt
        )
    shared = min(left.transition_count, right.transition_count)
    for index in range(shared):
        if left.event_digests[index] != right.event_digests[index]:
            return SchedulerTraceRelationReport(
                False, index + 1, "events differ", left.receipt, right.receipt
            )
        if left.boundary_digests[index + 1] != right.boundary_digests[index + 1]:
            return SchedulerTraceRelationReport(
                False, index + 1, "post-states differ", left.receipt, right.receipt
            )
    if left.transition_count != right.transition_count:
        return SchedulerTraceRelationReport(
            False, shared + 1, "transition counts differ",
            left.receipt, right.receipt
        )
    if left.final_tick != right.final_tick:
        return SchedulerTraceRelationReport(
            False, shared, "final ticks differ", left.receipt, right.receipt
        )
    return SchedulerTraceRelationReport(
        True, None, None, left.receipt, right.receipt
    )
