"""Unit tests for canonicalization and receipt logic using a deterministic test double.

The real-scheduler integration contract is covered separately in
`test_scheduler_relation.py` and is intended to run in the complete repository.
"""

from __future__ import annotations

from collections import deque
from types import SimpleNamespace

import pytest

from mailcpu.scheduler_relation import (
    SchedulerRelationError,
    capture_scheduler_trace,
    compare_scheduler_states,
    compare_scheduler_traces,
    observe_scheduler_state,
    verify_scheduler_trace_witness,
)


class FakeJournal:
    def __init__(self):
        self._records = []

    def append(self, kind, payload):
        sequence = len(self._records) + 1
        self._records.append({"sequence": sequence, "kind": kind, "payload": dict(payload), "digest": f"{sequence:064x}"})

    def verify(self):
        return all(item["sequence"] == index for index, item in enumerate(self._records, 1))

    def snapshot(self):
        return [dict(item) for item in self._records]


class FakeBus:
    def __init__(self):
        self.queues = {}
        self.next_id = 1

    def send(self, destination, value):
        self.queues.setdefault(destination, []).append({"id": self.next_id, "value": value})
        self.next_id += 1

    def snapshot(self):
        return {"next_id": self.next_id, "queues": self.queues}


class FakeBackend:
    def __init__(self, endpoint):
        self.endpoint = endpoint
        self.registers = {"x": 0}
        self.inputs = {}
        self.outputs = []
        self.syscall_handler = None

    def snapshot(self):
        return {
            "endpoint": self.endpoint,
            "registers": dict(self.registers),
            "inputs": dict(self.inputs),
            "outputs": list(self.outputs),
        }


class FakeScheduler:
    def __init__(self):
        self.tick = 0
        self.bus = FakeBus()
        self.journal = FakeJournal()
        self.syscall_handler = None
        self.wait_predicate = None
        self.post_step = None
        self._ready = deque([1])
        self.tasks = {
            1: SimpleNamespace(
                state=SimpleNamespace(pc=0, steps=0, halted=False, blocked=False, registers={}),
                backend=FakeBackend("proc:1"),
                status=SimpleNamespace(value="runnable"),
                program=SimpleNamespace(instructions=()),
                name="fake",
            )
        }

    def snapshot(self):
        task = self.tasks[1]
        return {
            "tick": self.tick,
            "next_pid": 2,
            "ready": list(self._ready),
            "tasks": {
                "1": {
                    "pid": 1,
                    "name": task.name,
                    "pc": task.state.pc,
                    "steps": task.state.steps,
                    "halted": task.state.halted,
                    "status": task.status.value,
                    "registers": dict(task.backend.registers),
                    "outputs": list(task.backend.outputs),
                    "program": [],
                    "inputs": {},
                }
            },
            "system_epoch": {"event_lambda": self.tick, "chronon_real": 1.0, "chronon_imag": 0.0, "chemical_tau": 0.0},
        }

    def run(self, max_ticks):
        if self.tick >= max_ticks or not self._ready:
            return ()
        before = self.tick
        task = self.tasks[1]
        task.state.pc += 1
        task.state.steps += 1
        task.backend.registers["x"] += 1
        task.backend.outputs.append(("out", task.backend.registers["x"]))
        self.bus.send("out", task.backend.registers["x"])
        event = SimpleNamespace(
            tick=before,
            pid=1,
            name="fake",
            pc_before=before,
            op="ADD",
            pc_after=task.state.pc,
            status_after="runnable",
            args=("x", "x", "one"),
            registers=(("x", task.backend.registers["x"]),),
            output_delta=(("out", task.backend.registers["x"]),),
        )
        self.tick += 1
        task.state.status = "runnable"
        self.journal.append("scheduler.tick", {"tick": before, "pid": 1})
        return (event,)


def test_fake_scheduler_trace_receipts_and_state_relations() -> None:
    left = FakeScheduler()
    right = FakeScheduler()
    left_trace = capture_scheduler_trace(left, max_transitions=5)
    right_trace = capture_scheduler_trace(right, max_transitions=5)
    assert left_trace.transition_count == 5
    assert verify_scheduler_trace_witness(left_trace)
    assert compare_scheduler_traces(left_trace, right_trace).equivalent


def test_fake_bus_difference_breaks_relation() -> None:
    left = FakeScheduler()
    right = FakeScheduler()
    right.bus.send("proc:1", 99)
    report = compare_scheduler_states(left, right)
    assert not report.equivalent
    assert any("bus" in path for path in report.difference_paths)


def test_invalid_journal_is_refused() -> None:
    scheduler = FakeScheduler()
    scheduler.journal._records.append({"sequence": 3, "kind": "tamper", "payload": {}, "digest": "bad"})
    with pytest.raises(SchedulerRelationError, match="journal hash chain"):
        observe_scheduler_state(scheduler)
