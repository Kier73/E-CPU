"""Integration tests for full HeadlessOS state relations and trace witnesses."""

from __future__ import annotations

import copy

import pytest

from mailcpu.headless import HeadlessOS
from mailcpu.model import Instruction, Op, Program
from mailcpu.headless_relation import (
    HeadlessRelationError,
    capture_headless_os_trace,
    compare_headless_os_states,
    compare_headless_os_traces,
    observe_headless_os_state,
    verify_headless_trace_witness,
)


def _producer(cycles: int) -> Program:
    return Program((
        Instruction(Op.SET, ("remaining", cycles)),
        Instruction(Op.SET, ("minus_one", -1)),
        Instruction(Op.SET, ("value", 1)),
        Instruction(Op.SEND, ("proc:3", "value")),
        Instruction(Op.WAIT, ("proc:2", "ack")),
        Instruction(Op.ADD, ("remaining", "remaining", "minus_one")),
        Instruction(Op.BRANCH, ("remaining", 3)),
        Instruction(Op.HALT),
    ))


def _worker(cycles: int) -> Program:
    return Program((
        Instruction(Op.SET, ("remaining", cycles)),
        Instruction(Op.SET, ("acc", 0)),
        Instruction(Op.SET, ("minus_one", -1)),
        Instruction(Op.WAIT, ("proc:3", "incoming")),
        Instruction(Op.ADD, ("acc", "acc", "incoming")),
        Instruction(Op.COPY, ("out", "acc")),
        Instruction(Op.SEND, ("trace:worker", "out")),
        Instruction(Op.COPY, ("ack", "acc")),
        Instruction(Op.SEND, ("proc:2", "ack")),
        Instruction(Op.ADD, ("remaining", "remaining", "minus_one")),
        Instruction(Op.BRANCH, ("remaining", 3)),
        Instruction(Op.HALT),
    ))


def _make_system(cycles: int = 7) -> HeadlessOS:
    operating_system = HeadlessOS()
    producer = operating_system.spawn(_producer(cycles), "producer")
    worker = operating_system.spawn(_worker(cycles), "worker")
    assert (producer, worker) == (2, 3)
    return operating_system


def _clone(operating_system: HeadlessOS) -> HeadlessOS:
    return HeadlessOS.from_snapshot(copy.deepcopy(operating_system.snapshot()))


def test_full_headless_state_is_related_at_every_message_transition() -> None:
    left = _make_system(8)
    right = _clone(left)
    report = compare_headless_os_states(left, right)
    assert report.equivalent

    left_trace = capture_headless_os_trace(left, max_transitions=2_000)
    right_trace = capture_headless_os_trace(right, max_transitions=2_000)
    assert left_trace.transition_count > 8
    assert left_trace.transition_count == right_trace.transition_count
    assert verify_headless_trace_witness(left_trace)
    assert compare_headless_os_traces(left_trace, right_trace).equivalent
    assert left.environment.kernel.journal.verify()
    assert right.environment.kernel.journal.verify()
    assert left.process(2).status == "exited"
    assert left.process(3).status == "exited"
    assert left.environment.kernel.bus.pending("proc:2") == 0
    assert left.environment.kernel.bus.pending("proc:3") == 0
    assert left.environment.kernel.bus.pending("trace:worker") == 8


def test_memory_and_filesystem_are_part_of_the_full_system_relation() -> None:
    left = _make_system(3)
    right = _clone(left)
    assert compare_headless_os_states(left, right).equivalent

    right.vm.memories[2].write(0, b"changed")
    memory_relation = compare_headless_os_states(left, right)
    assert not memory_relation.equivalent
    assert any("memories" in path for path in memory_relation.difference_paths)

    right = _clone(left)
    right.environment.kernel.fs.create_file("/witness-probe", b"changed")
    filesystem_relation = compare_headless_os_states(left, right)
    assert not filesystem_relation.equivalent
    assert any("filesystem" in path for path in filesystem_relation.difference_paths)


def test_message_queue_and_capability_changes_break_full_system_relation() -> None:
    left = _make_system(4)
    right = _clone(left)
    right.environment.kernel.bus.send(
        "external-test", "proc:3", "DATA", {"value": 999}
    )
    bus_relation = compare_headless_os_states(left, right)
    assert not bus_relation.equivalent
    assert any("bus" in path for path in bus_relation.difference_paths)

    right = _clone(left)
    process = right.environment.kernel.processes[2]
    process.capabilities = ()
    capability_relation = compare_headless_os_states(left, right)
    assert not capability_relation.equivalent
    assert any("capabilities" in path for path in capability_relation.difference_paths)


def test_restore_from_full_snapshot_preserves_future_headless_execution() -> None:
    original = _make_system(10)
    prefix = original.run(max_ticks=19)
    assert prefix
    restored = _clone(original)

    assert compare_headless_os_states(original, restored).equivalent
    original_tail = capture_headless_os_trace(original, max_transitions=2_000)
    restored_tail = capture_headless_os_trace(restored, max_transitions=2_000)
    assert compare_headless_os_traces(original_tail, restored_tail).equivalent


def test_external_resources_and_nonstandard_callbacks_are_refused() -> None:
    operating_system = _make_system(2)
    operating_system.vm.trajectory = object()
    with pytest.raises(HeadlessRelationError, match="trajectory"):
        observe_headless_os_state(operating_system)

    operating_system = _make_system(2)
    operating_system.vm.page_backing = object()
    with pytest.raises(HeadlessRelationError, match="page backing"):
        observe_headless_os_state(operating_system)

    operating_system = _make_system(2)
    operating_system.vm.scheduler.post_step = lambda _pid: None
    with pytest.raises(HeadlessRelationError, match="post_step"):
        observe_headless_os_state(operating_system)

    operating_system = _make_system(2)
    operating_system.vm.host_syscall_handler = lambda _pid, _name, _args: 0
    with pytest.raises(HeadlessRelationError, match="host_syscall_handler"):
        observe_headless_os_state(operating_system)


def test_memory_backing_and_resident_callbacks_are_part_of_admission() -> None:
    operating_system = _make_system(2)
    operating_system.vm.memories[2]._page_backing = object()
    with pytest.raises(HeadlessRelationError, match="page backing"):
        observe_headless_os_state(operating_system)

    operating_system = _make_system(2)
    operating_system.vm.memories[2]._resident_admitter = lambda _count: None
    with pytest.raises(HeadlessRelationError, match="resident-page callback"):
        observe_headless_os_state(operating_system)


def test_tampered_full_system_journal_invalidates_observation() -> None:
    operating_system = _make_system(2)
    operating_system.environment.kernel.journal._records[-1].payload["name"] = "tampered"
    with pytest.raises(HeadlessRelationError, match="journal hash chain"):
        observe_headless_os_state(operating_system)
