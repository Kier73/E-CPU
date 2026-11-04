"""Integration tests for exact state relations over the real MailCPU scheduler."""

from __future__ import annotations

import copy

import pytest

from mailcpu.bus import MailboxBus
from mailcpu.journal import EventJournal
from mailcpu.model import Instruction, Op, Program
from mailcpu.scheduler import DeterministicScheduler
from mailcpu.scheduler_relation import (
    SchedulerRelationError,
    capture_scheduler_trace,
    compare_scheduler_states,
    compare_scheduler_traces,
    observe_scheduler_state,
    verify_scheduler_trace_witness,
)


def _producer_program(cycles: int) -> Program:
    return Program((
        Instruction(Op.SET, ("remaining", cycles)),
        Instruction(Op.SET, ("minus_one", -1)),
        Instruction(Op.SET, ("value", 1)),
        Instruction(Op.SEND, ("proc:2", "value")),
        Instruction(Op.WAIT, ("proc:1", "ack")),
        Instruction(Op.ADD, ("remaining", "remaining", "minus_one")),
        Instruction(Op.BRANCH, ("remaining", 3)),
        Instruction(Op.HALT),
    ))


def _worker_program(cycles: int) -> Program:
    return Program((
        Instruction(Op.SET, ("remaining", cycles)),
        Instruction(Op.SET, ("acc", 0)),
        Instruction(Op.SET, ("minus_one", -1)),
        Instruction(Op.WAIT, ("proc:2", "incoming")),
        Instruction(Op.ADD, ("acc", "acc", "incoming")),
        Instruction(Op.COPY, ("out", "acc")),
        Instruction(Op.SEND, ("trace:worker", "out")),
        Instruction(Op.COPY, ("ack", "acc")),
        Instruction(Op.SEND, ("proc:1", "ack")),
        Instruction(Op.ADD, ("remaining", "remaining", "minus_one")),
        Instruction(Op.BRANCH, ("remaining", 3)),
        Instruction(Op.HALT),
    ))


def _make_pair(cycles: int = 7) -> DeterministicScheduler:
    scheduler = DeterministicScheduler()
    producer = scheduler.add(_producer_program(cycles), "producer", pid=1)
    worker = scheduler.add(_worker_program(cycles), "worker", pid=2)
    assert (producer, worker) == (1, 2)
    return scheduler


def _clone_at_boundary(scheduler: DeterministicScheduler) -> DeterministicScheduler:
    return DeterministicScheduler.from_snapshot(
        scheduler.snapshot(),
        bus=MailboxBus.from_snapshot(scheduler.bus.snapshot()),
        journal=EventJournal.from_snapshot(scheduler.journal.snapshot()),
    )


def _advance_one(scheduler: DeterministicScheduler) -> bool:
    events = scheduler.run(max_ticks=scheduler.tick + 1)
    assert len(events) <= 1
    return bool(events)


def test_identical_two_process_replays_are_related_at_every_boundary() -> None:
    left = _make_pair(9)
    right = _make_pair(9)
    left_trace = capture_scheduler_trace(left, max_transitions=1_000)
    right_trace = capture_scheduler_trace(right, max_transitions=1_000)

    report = compare_scheduler_traces(left_trace, right_trace)
    assert report.equivalent
    assert report.first_divergence is None
    assert left_trace.transition_count == right_trace.transition_count
    assert left_trace.transition_count > 9
    assert verify_scheduler_trace_witness(left_trace)
    assert left.journal.verify()
    assert right.journal.verify()


def test_checkpoint_restore_preserves_relation_and_future_execution() -> None:
    original = _make_pair(11)
    for _ in range(23):
        if not _advance_one(original):
            break
    restored = _clone_at_boundary(original)

    assert compare_scheduler_states(original, restored).equivalent
    original_tail = capture_scheduler_trace(original, max_transitions=1_000)
    restored_tail = capture_scheduler_trace(restored, max_transitions=1_000)
    assert compare_scheduler_traces(original_tail, restored_tail).equivalent


def test_pending_mailbox_difference_is_not_hidden_by_equal_worker_registers() -> None:
    left = _make_pair(4)
    right = _make_pair(4)
    for _ in range(5):
        assert _advance_one(left)
        assert _advance_one(right)

    assert left.tasks[2].backend.snapshot_registers() == right.tasks[2].backend.snapshot_registers()
    right.bus.send("test", "proc:2", "DATA", {"value": 999})
    relation = compare_scheduler_states(left, right)
    assert not relation.equivalent
    assert any("bus" in path for path in relation.difference_paths)


def test_ready_queue_order_is_part_of_scheduler_relation() -> None:
    left = _make_pair(5)
    right = _make_pair(5)
    right._ready.reverse()
    relation = compare_scheduler_states(left, right)
    assert not relation.equivalent
    assert any("ready" in path for path in relation.difference_paths)


def test_external_callbacks_and_syscalls_are_rejected() -> None:
    scheduler = _make_pair(2)
    scheduler.post_step = lambda _pid: None
    with pytest.raises(SchedulerRelationError, match="post_step"):
        observe_scheduler_state(scheduler)

    scheduler = DeterministicScheduler()
    syscall_program = Program((Instruction(Op.SYSCALL, ("result", "clock")), Instruction(Op.HALT)))
    scheduler.add(syscall_program, "effectful")
    with pytest.raises(SchedulerRelationError, match="SYSCALL"):
        observe_scheduler_state(scheduler)


def test_journal_tampering_invalidates_the_state_witness() -> None:
    scheduler = _make_pair(2)
    scheduler.journal._records[-1].payload["name"] = "tampered"
    with pytest.raises(SchedulerRelationError, match="journal hash chain"):
        observe_scheduler_state(scheduler)
