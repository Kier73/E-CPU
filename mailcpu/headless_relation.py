"""Exact observational relation for a closed, checkpointable HeadlessOS state.

Unlike a scheduler-only witness, this layer commits to the complete HeadlessOS
snapshot: VM, scheduler, process/kernel state, filesystem, descriptors,
capabilities, devices, network stacks, memory images, services, hypervisor
state, seed-admission state and journal. It is observational only.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .scheduler_relation import (
    SchedulerRelationError,
    _bytes,
    _digest,
    _event,
    _extend,
)

SCHEMA = "mailcpu.headless-state-relation/v1"
_ZERO = "0" * 64


class HeadlessRelationError(ValueError):
    """The requested HeadlessOS state is outside the supported witness domain."""


def _is_bound(method: Any, owner: Any, name: str) -> bool:
    return (
        getattr(method, "__self__", None) is owner
        and getattr(method, "__func__", None) is getattr(type(owner), name, None)
    )


def _check_closed_domain(operating_system: Any) -> None:
    """Admit only the standard, snapshot-covered HeadlessOS continuation path."""
    vm = getattr(operating_system, "vm", None)
    environment = getattr(operating_system, "environment", None)
    if vm is None or environment is None:
        raise HeadlessRelationError("HeadlessOS must expose VM and environment")
    kernel = getattr(environment, "kernel", None)
    scheduler = getattr(vm, "scheduler", None)
    if kernel is None or scheduler is None:
        raise HeadlessRelationError("HeadlessOS must expose kernel and scheduler")

    # These resources are intentionally outside HeadlessOS.snapshot().
    if getattr(vm, "trajectory", None) is not None:
        raise HeadlessRelationError("external trajectory writer is outside witness")
    if getattr(vm, "page_backing", None) is not None:
        raise HeadlessRelationError("external page backing is outside witness")

    if getattr(operating_system, "_pending_exec", None):
        raise HeadlessRelationError("uncommitted exec transition is outside witness")
    if getattr(operating_system, "_pending_fork", None):
        raise HeadlessRelationError("uncommitted fork transition is outside witness")

    # Permit only the built-in OS/VM callbacks whose target state is included
    # in HeadlessOS.snapshot() and whose implementations are reconstructed by
    # HeadlessOS.from_snapshot().
    required = (
        (getattr(vm, "host_syscall_handler", None), operating_system, "_dispatch_program_syscall"),
        (getattr(scheduler, "syscall_handler", None), vm, "_dispatch_program_syscall"),
        (getattr(scheduler, "wait_predicate", None), operating_system, "_scheduler_wait_ready"),
        (getattr(scheduler, "post_step", None), operating_system, "_apply_deferred_exec"),
        (getattr(kernel, "terminal_signal_handler", None), operating_system, "_handle_terminal_signal"),
    )
    for callback, owner, name in required:
        if not _is_bound(callback, owner, name):
            raise HeadlessRelationError(
                f"non-standard or external callback {name} is outside witness"
            )

    if scheduler.bus is not kernel.bus:
        raise HeadlessRelationError("scheduler and kernel do not share one message bus")
    if scheduler.journal is not kernel.journal:
        raise HeadlessRelationError("scheduler and kernel do not share one event journal")

    for pid, task in scheduler.tasks.items():
        backend = getattr(task, "backend", None)
        if backend is None or getattr(backend, "syscall_handler", None) != scheduler.syscall_handler:
            raise HeadlessRelationError(
                f"task {pid} has a non-standard syscall dispatch path"
            )

    for pid, memory in vm.memories.items():
        if getattr(memory, "_page_backing", None) is not None:
            raise HeadlessRelationError(
                f"task {pid} memory has external page backing"
            )
        if not _is_bound(
            getattr(memory, "_resident_admitter", None),
            vm,
            "_admit_resident_pages",
        ):
            raise HeadlessRelationError(
                f"task {pid} memory has a non-standard resident-page callback"
            )


@dataclass(frozen=True)
class HeadlessStateObservation:
    tick: int
    digest: str
    payload: Mapping[str, Any]
    canonical_size: int
    journal_records: int
    journal_head: str


def observe_headless_os_state(operating_system: Any) -> HeadlessStateObservation:
    """Capture the canonical full-system snapshot and verify its journal head."""
    _check_closed_domain(operating_system)
    snapshot = operating_system.snapshot()
    if not isinstance(snapshot, Mapping):
        raise HeadlessRelationError("HeadlessOS snapshot must be a mapping")

    journal = operating_system.environment.kernel.journal
    if not journal.verify():
        raise HeadlessRelationError("HeadlessOS event journal hash chain is invalid")
    records = journal.snapshot()
    journal_head = records[-1]["digest"] if records else _ZERO
    payload = {
        "schema": SCHEMA,
        "operating_system": snapshot,
        "journal": {
            "record_count": len(records),
            "head_digest": journal_head,
        },
    }
    try:
        encoded = _bytes(payload)
    except SchedulerRelationError as exc:
        raise HeadlessRelationError(str(exc)) from exc
    return HeadlessStateObservation(
        tick=int(operating_system.vm.scheduler.tick),
        digest=_digest(encoded),
        payload=payload,
        canonical_size=len(encoded),
        journal_records=len(records),
        journal_head=str(journal_head),
    )


def _diff(
    left: Any, right: Any, path: str = "$", limit: int = 24
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
                result.extend(_diff(left[key], right[key], child, limit - len(result)))
            if len(result) >= limit:
                break
        return result or [path]
    if isinstance(left, list) and isinstance(right, list):
        result = [f"{path}.length"] if len(left) != len(right) else []
        for index, (a, b) in enumerate(zip(left, right)):
            result.extend(_diff(a, b, f"{path}[{index}]", limit - len(result)))
            if len(result) >= limit:
                break
        return result or [path]
    return [path]


@dataclass(frozen=True)
class HeadlessRelationReport:
    equivalent: bool
    left_digest: str
    right_digest: str
    difference_paths: tuple[str, ...] = ()


def compare_headless_os_states(left: Any, right: Any) -> HeadlessRelationReport:
    """Compare complete, supported HeadlessOS snapshots with path-level diagnostics."""
    a = observe_headless_os_state(left)
    b = observe_headless_os_state(right)
    equal = a.digest == b.digest and a.payload == b.payload
    paths = () if equal else tuple(_diff(a.payload, b.payload))
    return HeadlessRelationReport(equal, a.digest, b.digest, paths)


@dataclass(frozen=True)
class HeadlessTraceWitness:
    """Full-system boundary/event digest index; it is not a reconstructable trace."""
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
        return (
            len(self.boundary_digests) + len(self.event_digests) + 1
        ) * 32


def verify_headless_trace_witness(witness: HeadlessTraceWitness) -> bool:
    if len(witness.boundary_digests) != len(witness.event_digests) + 1:
        return False
    if not witness.boundary_digests:
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
    try:
        for item in digests:
            if not isinstance(item, str) or len(item) != 64:
                return False
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


def capture_headless_os_trace(
    operating_system: Any,
    max_transitions: int = 100_000,
) -> HeadlessTraceWitness:
    """Capture the HeadlessOS orbit one accepted instruction transition at a time."""
    if max_transitions < 0:
        raise ValueError("max_transitions must be non-negative")
    initial = observe_headless_os_state(operating_system)
    boundaries = [initial.digest]
    event_digests: list[str] = []
    state_bytes = initial.canonical_size
    event_bytes = 0
    receipt = _ZERO
    scheduler = operating_system.vm.scheduler

    while len(event_digests) < max_transitions:
        before_tick = int(scheduler.tick)
        events = operating_system.run(max_ticks=before_tick + 1)
        if not events:
            break
        if (
            len(events) != 1
            or int(events[0].tick) != before_tick
            or int(scheduler.tick) != before_tick + 1
        ):
            raise HeadlessRelationError(
                "one-tick HeadlessOS capture did not produce exactly one accepted instruction"
            )
        event_payload = _bytes(_event(events[0]))
        event_digest = _digest(event_payload)
        after = observe_headless_os_state(operating_system)
        receipt = _extend(
            receipt, len(event_digests), event_digest, after.digest
        )
        event_digests.append(event_digest)
        boundaries.append(after.digest)
        event_bytes += len(event_payload)
        state_bytes += after.canonical_size

    final = observe_headless_os_state(operating_system)
    if final.digest != boundaries[-1]:
        raise HeadlessRelationError(
            "HeadlessOS changed after final witnessed boundary"
        )
    witness = HeadlessTraceWitness(
        initial_tick=initial.tick,
        final_tick=final.tick,
        boundary_digests=tuple(boundaries),
        event_digests=tuple(event_digests),
        receipt=receipt,
        state_payload_bytes_observed=state_bytes,
        event_payload_bytes_observed=event_bytes,
    )
    if not verify_headless_trace_witness(witness):
        raise HeadlessRelationError("HeadlessOS trace receipt failed verification")
    return witness


@dataclass(frozen=True)
class HeadlessTraceRelationReport:
    equivalent: bool
    first_divergence: int | None
    reason: str | None
    left_receipt: str
    right_receipt: str


def compare_headless_os_traces(
    left: HeadlessTraceWitness,
    right: HeadlessTraceWitness,
) -> HeadlessTraceRelationReport:
    """Compare initial state, all accepted events and all full-system boundaries."""
    if not verify_headless_trace_witness(left) or not verify_headless_trace_witness(right):
        return HeadlessTraceRelationReport(
            False, 0, "invalid witness receipt", left.receipt, right.receipt
        )
    if (
        left.initial_tick != right.initial_tick
        or left.boundary_digests[0] != right.boundary_digests[0]
    ):
        return HeadlessTraceRelationReport(
            False, 0, "initial HeadlessOS states differ",
            left.receipt, right.receipt
        )
    shared = min(left.transition_count, right.transition_count)
    for index in range(shared):
        if left.event_digests[index] != right.event_digests[index]:
            return HeadlessTraceRelationReport(
                False, index + 1, "scheduler events differ",
                left.receipt, right.receipt
            )
        if left.boundary_digests[index + 1] != right.boundary_digests[index + 1]:
            return HeadlessTraceRelationReport(
                False, index + 1, "full HeadlessOS states differ",
                left.receipt, right.receipt
            )
    if left.transition_count != right.transition_count:
        return HeadlessTraceRelationReport(
            False, shared + 1, "transition counts differ",
            left.receipt, right.receipt
        )
    if left.final_tick != right.final_tick:
        return HeadlessTraceRelationReport(
            False, shared, "final ticks differ", left.receipt, right.receipt
        )
    return HeadlessTraceRelationReport(
        True, None, None, left.receipt, right.receipt
    )
