"""Deterministic multi-task scheduler executing MailCPU programs over the virtual bus."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Sequence

from .bus import MailboxBus
from .interpreter import ExecutionBackend, Transition, apply_instruction
from .journal import EventJournal
from .model import DEFAULT_MAX_TICKS, Instruction, MachineState, Op, Program, RunStatus


class TaskStatus(str, Enum):
    """Lifecycle states of a scheduled MailCPU program."""

    RUNNABLE = "runnable"
    BLOCKED = "blocked"
    SUSPENDED = "suspended"
    HALTED = "halted"


class SyscallBlocked(Exception):
    """A scheduler-owned syscall suspension carrying its checkpointable wake predicate."""

    def __init__(self, wait_request: dict[str, Any]) -> None:
        """Mathematics: preserve wait state `W := wait_request` while refusing to advance the blocked instruction."""

        self.wait_request = dict(wait_request)
        super().__init__(f"syscall blocked on {self.wait_request}")


class SchedulerBackend:
    """Persistent task-local registers plus bus-backed input/output channels."""

    def __init__(
        self,
        bus: MailboxBus,
        endpoint: str,
        initial_registers: dict[str, int],
        syscall_handler: Callable[[int, str, dict[str, Any]], int] | None = None,
    ) -> None:
        """Mathematics: initialize task valuation `R=R0`, local input queues, output sequence `O=[]`, and native trap map `H`.

        The handler is injected by the composed VM; the scheduler itself
        retains no host authority beyond this explicit state-transition hook.
        """

        self.bus = bus
        self.endpoint = endpoint
        self.registers = dict(initial_registers)
        self.inputs: dict[str, deque[int]] = {}
        self.outputs: list[tuple[str, int]] = []
        self.pid = int(endpoint.rsplit(":", 1)[-1])
        self.syscall_handler = syscall_handler

    def read_register(self, name: str) -> int:
        """Mathematics: evaluate totalized valuation `R[name]`, with `0` for `name ∉ dom(R)`."""

        return self.registers.get(name, 0)

    def write_register(self, name: str, value: int) -> None:
        """Mathematics: apply finite-map override `R := R[name ↦ value]`."""

        self.registers[name] = value

    def receive(self, mailbox: str) -> int | None:
        """Mathematics: consume local FIFO input first, then decode the bus head payload `{'value': v}`."""

        local = self.inputs.get(mailbox)
        if local:
            return local.popleft()
        message = self.bus.receive(mailbox)
        if message is None:
            return None
        value = message.payload.get("value")
        if not isinstance(value, int):
            raise RuntimeError("scheduler received a non-integer DATA payload")
        return value

    def send(self, mailbox: str, value: int) -> None:
        """Mathematics: emit `(mailbox, value)` to `O` and append `{value}` to the destination bus queue."""

        self.outputs.append((mailbox, value))
        self.bus.send(self.endpoint, mailbox, "DATA", {"value": value})

    def snapshot_registers(self) -> dict[str, int]:
        """Mathematics: expose the finite valuation domain `dom(R)` in sorted order."""

        return dict(sorted(self.registers.items()))

    def output_log(self) -> list[tuple[str, int]]:
        """Mathematics: expose the ordered output sequence `O` without permitting mutation."""

        return list(self.outputs)

    def syscall(self, name: str, arguments: tuple[str, ...]) -> tuple[int, bool]:
        """Mathematics: parse `key=value` operands into `A`, then return `(H(pid,name,A), name='exit')` with integer result validation."""

        if self.syscall_handler is None:
            raise RuntimeError(f"SYSCALL requires an OS execution backend: {name}")
        decoded: dict[str, Any] = {}
        for token in arguments:
            key, raw_value = token.split("=", 1)
            decoded[key] = self._decode_syscall_value(raw_value)
        result = self.syscall_handler(self.pid, name, decoded)
        if isinstance(result, bool):
            result = int(result)
        if not isinstance(result, int):
            raise RuntimeError(f"syscall {name} returned non-integer result")
        return result, name == "exit"

    def _decode_syscall_value(self, raw_value: str) -> Any:
        """Mathematics: decode `D('$r')=R[r]`, `D('hex:b')=bytes(b)`, `D(n)=n`, else `D(s)=s`."""

        if raw_value.startswith("$"):
            return self.read_register(raw_value[1:])
        if raw_value.startswith("hex:"):
            return bytes.fromhex(raw_value[4:])
        if raw_value.lower() in {"true", "false"}:
            return raw_value.lower() == "true"
        try:
            return int(raw_value, 0)
        except ValueError:
            return raw_value

    def snapshot(self) -> dict[str, Any]:
        """Mathematics: serialize backend valuation `R`, queues `I`, and output sequence `O` for exact continuation."""

        return {
            "endpoint": self.endpoint,
            "registers": self.snapshot_registers(),
            "inputs": {mailbox: list(values) for mailbox, values in sorted(self.inputs.items())},
            "outputs": [list(item) for item in self.outputs],
        }

    def inject(self, mailbox: str, values: Sequence[int]) -> None:
        """Mathematics: extend local input sequence `I_mailbox := I_mailbox || values` for deterministic tests."""

        self.inputs.setdefault(mailbox, deque()).extend(values)


@dataclass
class ScheduledTask:
    """Scheduler state for one program and its persistent execution backend."""

    pid: int
    name: str
    program: Program
    state: MachineState
    backend: SchedulerBackend
    status: TaskStatus = TaskStatus.RUNNABLE
    wait_request: dict[str, Any] | None = None
    wake_request: dict[str, Any] | None = None


@dataclass(frozen=True)
class ScheduleEvent:
    """One scheduler decision and optional instruction transition."""

    tick: int
    pid: int
    name: str
    pc_before: int
    op: str
    pc_after: int
    status_after: str


class DeterministicScheduler:
    """Round-robin scheduler with one instruction transition per logical tick."""

    def __init__(
        self,
        bus: MailboxBus | None = None,
        journal: EventJournal | None = None,
        syscall_handler: Callable[[int, str, dict[str, Any]], int] | None = None,
    ) -> None:
        """Mathematics: initialize ready queue `R=[]`, task map `T=∅`, logical tick `τ=0`, shared bus, and trap map `H`."""

        self.bus = bus or MailboxBus()
        self.journal = journal or EventJournal()
        self.tasks: dict[int, ScheduledTask] = {}
        self._ready: deque[int] = deque()
        self._next_pid = 1
        self.tick = 0
        self.syscall_handler = syscall_handler
        self.wait_predicate: Callable[[int, dict[str, Any]], bool] | None = None
        self.post_step: Callable[[int], None] | None = None

    def add(
        self,
        program: Program,
        name: str,
        initial_registers: dict[str, int] | None = None,
        pid: int | None = None,
    ) -> int:
        """Mathematics: insert task `T[pid]` and append `pid` to ready queue, preserving unique task identity."""

        task_pid = self._next_pid if pid is None else pid
        if task_pid in self.tasks:
            raise ValueError(f"task already exists: {task_pid}")
        self._next_pid = max(self._next_pid, task_pid + 1)
        backend = SchedulerBackend(self.bus, f"proc:{task_pid}", initial_registers or {}, self.syscall_handler)
        task = ScheduledTask(task_pid, name, program, MachineState(), backend)
        self.tasks[task_pid] = task
        self._ready.append(task_pid)
        self.journal.append("scheduler.add", {"pid": task_pid, "name": name})
        return task_pid

    def fork_task(
        self,
        parent_pid: int,
        child_pid: int,
        registers: dict[str, int],
        pc: int,
        steps: int,
    ) -> int:
        """Mathematics: create child task `T_c=(P_p,pc,R_c,Q_c,O_c)` with `R_c` supplied by fork semantics and `Q_c,O_c` copied from parent."""

        parent = self._task(parent_pid)
        if child_pid in self.tasks:
            raise ValueError(f"task already exists: {child_pid}")
        if pc < 0 or pc > len(parent.program.instructions):
            raise ValueError("fork child program counter is out of range")
        if steps < 0:
            raise ValueError("fork child step count must be non-negative")
        backend = SchedulerBackend(self.bus, f"proc:{child_pid}", registers, self.syscall_handler)
        backend.inputs = {
            mailbox: deque(values)
            for mailbox, values in parent.backend.inputs.items()
        }
        backend.outputs = parent.backend.output_log()
        child = ScheduledTask(
            child_pid,
            parent.name,
            parent.program,
            MachineState(pc=pc, steps=steps),
            backend,
        )
        self.tasks[child_pid] = child
        self._next_pid = max(self._next_pid, child_pid + 1)
        self._ready.append(child_pid)
        self.journal.append(
            "scheduler.fork",
            {"parent_pid": parent_pid, "child_pid": child_pid, "pc": pc, "steps": steps},
        )
        return child_pid

    def inject(self, pid: int, mailbox: str, values: Sequence[int]) -> None:
        """Mathematics: append input tokens and apply wake rule `BLOCKED ∧ input_available -> RUNNABLE`."""

        task = self._task(pid)
        task.backend.inject(mailbox, values)
        if task.status is TaskStatus.BLOCKED and task.wait_request is None:
            task.status = TaskStatus.RUNNABLE
            task.state.blocked = False
            self._ready.append(pid)

    def terminate(self, pid: int) -> None:
        """Mathematics: apply the control transition `T[pid].status := HALTED` and make future scheduling a no-op."""

        task = self._task(pid)
        if task.status is TaskStatus.HALTED:
            return
        task.status = TaskStatus.HALTED
        task.state.halted = True
        task.state.blocked = False
        task.wait_request = None
        task.wake_request = None
        self.journal.append("scheduler.terminate", {"pid": pid, "tick": self.tick})

    def exec(self, pid: int, program: Program, name: str | None = None) -> None:
        """Mathematics: replace task image `T[pid]=(P,R,pc)` with `(program,0,0)` and enqueue exactly one runnable token."""

        task = self._task(pid)
        self._ready = deque(item for item in self._ready if item != pid)
        task.program = program
        task.name = task.name if name is None else name
        task.state = MachineState()
        task.backend = SchedulerBackend(self.bus, f"proc:{pid}", {}, self.syscall_handler)
        task.status = TaskStatus.RUNNABLE
        task.state.blocked = False
        task.wait_request = None
        task.wake_request = None
        self._ready.append(pid)
        self.journal.append("scheduler.exec", {"pid": pid, "name": task.name})

    def reap(self, pid: int) -> None:
        """Mathematics: remove terminal task `T[pid]` from the scheduler relation after its kernel wait transition."""

        task = self._task(pid)
        if task.status is not TaskStatus.HALTED:
            raise ValueError("task is not halted")
        self._ready = deque(item for item in self._ready if item != pid)
        del self.tasks[pid]
        self.journal.append("scheduler.reap", {"pid": pid})

    def suspend(self, pid: int) -> None:
        """Mathematics: remove task from the runnable transition relation by setting `status := SUSPENDED`."""

        task = self._task(pid)
        if task.status is not TaskStatus.HALTED:
            task.status = TaskStatus.SUSPENDED
            self._ready = deque(item for item in self._ready if item != pid)
            self.journal.append("scheduler.suspend", {"pid": pid, "tick": self.tick})

    def resume(self, pid: int) -> None:
        """Mathematics: apply wake transition `SUSPENDED -> RUNNABLE` and enqueue exactly one future scheduling token."""

        task = self._task(pid)
        if task.status is TaskStatus.SUSPENDED:
            if task.wait_request is None:
                task.status = TaskStatus.RUNNABLE
                task.state.blocked = False
                self._ready.append(pid)
            else:
                task.status = TaskStatus.BLOCKED
                task.state.blocked = True
            self.journal.append("scheduler.resume", {"pid": pid, "tick": self.tick})

    def run(self, max_ticks: int = DEFAULT_MAX_TICKS) -> tuple[ScheduleEvent, ...]:
        """Mathematics: iterate round-robin transitions `τ := τ + 1`, interleaving deadline jumps when `R=∅`, until `τ=max_ticks` or no wakeable task remains."""

        if max_ticks < 0:
            raise ValueError("max_ticks must be non-negative")
        events: list[ScheduleEvent] = []
        while self.tick < max_ticks:
            self._wake_tasks()
            if not self._ready:
                if not self._advance_to_deadline(max_ticks):
                    break
                self._wake_tasks()
                if not self._ready:
                    break
            pid = self._ready.popleft()
            task = self._task(pid)
            if task.status is not TaskStatus.RUNNABLE:
                continue
            event = self._step(task)
            events.append(event)
            self.tick += 1
            self.journal.append(
                "scheduler.tick",
                {
                    "tick": event.tick,
                    "pid": event.pid,
                    "pc_before": event.pc_before,
                    "op": event.op,
                    "pc_after": event.pc_after,
                    "status_after": event.status_after,
                },
            )
            self._wake_tasks()
            if task.status is TaskStatus.RUNNABLE and pid not in self._ready:
                self._ready.append(pid)
        return tuple(events)

    def _advance_to_deadline(self, max_ticks: int) -> bool:
        """Mathematics: when `R=∅`, advance virtual time to `min{d : τ<d<max_ticks}` without inventing an instruction transition."""

        deadlines: list[int] = []
        for task in self.tasks.values():
            if task.status is not TaskStatus.BLOCKED or task.wait_request is None:
                continue
            raw_deadline = task.wait_request.get("deadline")
            if raw_deadline is None:
                continue
            deadline = int(raw_deadline)
            if self.tick < deadline < max_ticks:
                deadlines.append(deadline)
        if not deadlines:
            return False
        target = min(deadlines)
        previous = self.tick
        self.tick = target
        self.journal.append(
            "scheduler.time_advance",
            {"from": previous, "to": target, "reason": "wait-deadline"},
        )
        return True

    def _step(self, task: ScheduledTask) -> ScheduleEvent:
        """Mathematics: apply exactly one `T_task` transition and classify its terminal status."""

        pc_before = task.state.pc
        instruction = task.program.instructions[pc_before]
        try:
            transition = apply_instruction(instruction, pc_before, task.backend)
        except SyscallBlocked as blocked:
            transition = Transition(pc_before, blocked=True)
            task.wait_request = blocked.wait_request
        else:
            task.wait_request = None
        finally:
            task.wake_request = None
        if transition.blocked:
            task.status = TaskStatus.BLOCKED
            task.state.blocked = True
        else:
            task.state.pc = transition.next_pc
            task.state.steps += 1
            task.state.blocked = False
            if transition.halted:
                task.state.halted = True
                task.status = TaskStatus.HALTED
            if self.post_step is not None:
                self.post_step(task.pid)
        return ScheduleEvent(
            tick=self.tick,
            pid=task.pid,
            name=task.name,
            pc_before=pc_before,
            op=instruction.op.value,
            pc_after=task.state.pc,
            status_after=task.status.value,
        )

    def _wake_tasks(self) -> None:
        """Mathematics: apply `blocked ∧ (W=⊥ ∧ |Q_pid|>0 ∨ W≠⊥ ∧ P(W)) -> runnable` without duplicating ready tokens."""

        for task in self.tasks.values():
            if task.status is not TaskStatus.BLOCKED:
                continue
            ready = (
                self.bus.pending(task.backend.endpoint)
                if task.wait_request is None
                else self.wait_predicate is not None and self.wait_predicate(task.pid, task.wait_request)
            )
            if ready:
                task.status = TaskStatus.RUNNABLE
                task.state.blocked = False
                task.wake_request = None if task.wait_request is None else dict(task.wait_request)
                task.wait_request = None
                self._ready.append(task.pid)

    def _task(self, pid: int) -> ScheduledTask:
        """Mathematics: perform the partial lookup `T[pid]`, rejecting unknown task identities."""

        try:
            return self.tasks[pid]
        except KeyError as exc:
            raise KeyError(f"unknown task: {pid}") from exc

    def snapshot(self) -> dict[str, object]:
        """Mathematics: serialize scheduler state `(T, ready, tick)` and each task's machine valuation."""

        return {
            "tick": self.tick,
            "next_pid": self._next_pid,
            "ready": list(self._ready),
            "tasks": {
                str(pid): {
                    "pid": task.pid,
                    "name": task.name,
                    "pc": task.state.pc,
                    "steps": task.state.steps,
                    "halted": task.state.halted,
                    "status": task.status.value,
                    "wait_request": None if task.wait_request is None else dict(task.wait_request),
                    "wake_request": None if task.wake_request is None else dict(task.wake_request),
                    "registers": task.backend.snapshot_registers(),
                    "outputs": list(task.backend.output_log()),
                    "program": [
                        {"op": instruction.op.value, "args": list(instruction.args)}
                        for instruction in task.program.instructions
                    ],
                    "inputs": {
                        mailbox: list(values)
                        for mailbox, values in sorted(task.backend.inputs.items())
                    },
                }
                for pid, task in sorted(self.tasks.items())
            },
        }

    @classmethod
    def from_snapshot(
        cls,
        payload: dict[str, Any],
        bus: MailboxBus,
        journal: EventJournal,
        syscall_handler: Callable[[int, str, dict[str, Any]], int] | None = None,
    ) -> "DeterministicScheduler":
        """Mathematics: reconstruct scheduler state `(T, ready, tick)` and validate every embedded program graph."""

        scheduler = cls(bus=bus, journal=journal, syscall_handler=syscall_handler)
        scheduler.tick = int(payload["tick"])
        scheduler._next_pid = int(payload["next_pid"])
        scheduler._ready = deque(int(pid) for pid in payload.get("ready", ()))
        for raw in payload.get("tasks", {}).values():
            pid = int(raw["pid"])
            program = Program(
                tuple(
                    Instruction(Op(item["op"]), tuple(item.get("args", ())))
                    for item in raw["program"]
                )
            )
            backend = SchedulerBackend(bus, f"proc:{pid}", dict(raw.get("registers", {})), syscall_handler)
            backend.inputs = {
                str(mailbox): deque(int(value) for value in values)
                for mailbox, values in raw.get("inputs", {}).items()
            }
            backend.outputs = [
                (str(item[0]), int(item[1]))
                for item in raw.get("outputs", ())
            ]
            state = MachineState(
                pc=int(raw["pc"]),
                halted=bool(raw["halted"]),
                blocked=raw["status"] == TaskStatus.BLOCKED.value,
                steps=int(raw["steps"]),
            )
            raw_wait = raw.get("wait_request")
            if raw_wait is not None and not isinstance(raw_wait, dict):
                raise ValueError("scheduler wait_request must be a mapping or null")
            wait_request = None if raw_wait is None else dict(raw_wait)
            raw_wake = raw.get("wake_request")
            if raw_wake is not None and not isinstance(raw_wake, dict):
                raise ValueError("scheduler wake_request must be a mapping or null")
            wake_request = None if raw_wake is None else dict(raw_wake)
            if wake_request is not None and TaskStatus(raw["status"]) not in {
                TaskStatus.RUNNABLE,
                TaskStatus.SUSPENDED,
            }:
                raise ValueError("only runnable or suspended scheduler tasks may carry a wake_request")
            if wait_request is not None and TaskStatus(raw["status"]) not in {
                TaskStatus.BLOCKED,
                TaskStatus.SUSPENDED,
            }:
                raise ValueError("only blocked or stopped scheduler tasks may carry a wait_request")
            task = ScheduledTask(
                pid,
                str(raw["name"]),
                program,
                state,
                backend,
                TaskStatus(raw["status"]),
                wait_request,
                wake_request,
            )
            scheduler.tasks[pid] = task
        return scheduler
