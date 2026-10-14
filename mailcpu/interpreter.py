"""Reference and message-transport interpreters sharing one transition function."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Protocol, Sequence

from .model import (
    DEFAULT_MAX_STEPS,
    Instruction,
    MachineState,
    Message,
    Op,
    Program,
    RunResult,
    RunStatus,
    TraceEvent,
    instruction_message,
)
from .transport import InMemoryTransport, Transport


class ExecutionBackend(Protocol):
    """The state operations required by the shared MailCPU transition algebra."""

    def read_register(self, name: str) -> int:
        """Mathematics: return the register valuation `R[name]`, using the zero default for an uninitialized cell."""

        ...

    def write_register(self, name: str, value: int) -> None:
        """Mathematics: update the valuation by function override `R' = R[name ↦ value]`."""

        ...

    def receive(self, mailbox: str) -> int | None:
        """Mathematics: consume the least message in `Q_mailbox`, or return `⊥` when `Q_mailbox = []`."""

        ...

    def send(self, mailbox: str, value: int) -> None:
        """Mathematics: append an emitted value to the output sequence `O' = O || [(mailbox, value)]`."""

        ...

    def snapshot_registers(self) -> dict[str, int]:
        """Mathematics: expose a finite projection of the register valuation over all names touched so far."""

        ...

    def output_log(self) -> list[tuple[str, int]]:
        """Mathematics: return the ordered output sequence `O` used for trace deltas and final comparison."""

        ...

    def syscall(self, name: str, arguments: tuple[str, ...]) -> tuple[int, bool]:
        """Mathematics: evaluate native trap `δ_syscall(name,args)=(integer_result,halt_after)` or refuse unsupported backends."""

        ...


class ReferenceBackend:
    """A transport-free finite-state backend used as the ground truth."""

    def __init__(self, initial_registers: dict[str, int], inputs: dict[str, Sequence[int]]) -> None:
        """Mathematics: initialize `R = R0`, `I_mailbox = deque(inputs[mailbox])`, and `O = []`."""

        self._registers = dict(initial_registers)
        self._known_registers = set(initial_registers)
        self._inputs = {mailbox: deque(values) for mailbox, values in inputs.items()}
        self._outputs: list[tuple[str, int]] = []

    def read_register(self, name: str) -> int:
        """Mathematics: evaluate `R[name]` with totalization `R[name] = 0` when `name ∉ dom(R)`."""

        self._known_registers.add(name)
        return self._registers.get(name, 0)

    def write_register(self, name: str, value: int) -> None:
        """Mathematics: perform the finite-map assignment `R := R[name ↦ value]`."""

        self._known_registers.add(name)
        self._registers[name] = value

    def receive(self, mailbox: str) -> int | None:
        """Mathematics: implement destructive read `I_mailbox := tail(I_mailbox)` and return its head."""

        queue = self._inputs.get(mailbox)
        if not queue:
            return None
        return queue.popleft()

    def send(self, mailbox: str, value: int) -> None:
        """Mathematics: append one event to the output trace, `O := O || [(mailbox, value)]`."""

        self._outputs.append((mailbox, value))

    def snapshot_registers(self) -> dict[str, int]:
        """Mathematics: project the valuation onto the finite touched-name set `K`, yielding `{k: R[k] | k ∈ K}`."""

        return {name: self._registers.get(name, 0) for name in sorted(self._known_registers)}

    def output_log(self) -> list[tuple[str, int]]:
        """Mathematics: expose the ordered sequence `O` as a copy, preserving observational immutability."""

        return list(self._outputs)

    def syscall(self, name: str, arguments: tuple[str, ...]) -> tuple[int, bool]:
        """Mathematics: the transport-free reference has no OS authority, so `SYSCALL` is an explicit undefined transition."""

        raise RuntimeError(f"SYSCALL requires an OS execution backend: {name}")


class QueueBackend:
    """A backend whose register and input state is represented by transport messages."""

    def __init__(
        self,
        transport: Transport,
        initial_registers: dict[str, int],
        inputs: dict[str, Sequence[int]],
    ) -> None:
        """Mathematics: establish the single-cell invariant `|Q_reg:name| ≤ 1` and seed each input queue in order."""

        self.transport = transport
        self._known_registers = set(initial_registers)
        self._outputs: list[tuple[str, int]] = []
        for name, value in initial_registers.items():
            self.write_register(name, value)
        for mailbox, values in inputs.items():
            for value in values:
                if not isinstance(value, int):
                    raise ValueError("input values must be integers")
                self.transport.send(
                    mailbox,
                    Message(sender="host", op="INPUT", addr=mailbox, value=value),
                )

    @staticmethod
    def register_address(name: str) -> str:
        """Mathematics: inject symbolic register names into the mailbox namespace via `f(name) = 'reg:' || name`."""

        return f"reg:{name}"

    def read_register(self, name: str) -> int:
        """Mathematics: read the unique cell in `Q_reg:name`, with empty-cell default `0`."""

        self._known_registers.add(name)
        cells = self.transport.list(self.register_address(name))
        if len(cells) > 1:
            raise RuntimeError(f"register mailbox {name!r} violates the single-cell invariant")
        return 0 if not cells else cells[0].value or 0

    def write_register(self, name: str, value: int) -> None:
        """Mathematics: realize `R[name ↦ value]` by replacing the sole message in `Q_reg:name`."""

        self._known_registers.add(name)
        address = self.register_address(name)
        cells = self.transport.list(address)
        if len(cells) > 1:
            raise RuntimeError(f"register mailbox {name!r} violates the single-cell invariant")
        if cells and not self.transport.consume(cells[0]):
            raise RuntimeError(f"register mailbox {name!r} lost its cell during consume")
        self.transport.send(address, Message(sender="cpu", op="VALUE", addr=name, value=value))

    def receive(self, mailbox: str) -> int | None:
        """Mathematics: apply FIFO destructive read to `Q_mailbox`, returning `⊥` for an empty queue."""

        message = self.transport.poll(mailbox)
        if message is None:
            return None
        if message.value is None:
            raise RuntimeError(f"received non-numeric message {message.message_id}")
        return message.value

    def send(self, mailbox: str, value: int) -> None:
        """Mathematics: append `Message(value)` to `Q_mailbox` and the same pair to ordered output sequence `O`."""

        self.transport.send(mailbox, Message(sender="cpu", op="DATA", addr=mailbox, value=value))
        self._outputs.append((mailbox, value))

    def snapshot_registers(self) -> dict[str, int]:
        """Mathematics: decode the finite register projection from one message per `reg:name` mailbox."""

        return {name: self.read_register(name) for name in sorted(self._known_registers)}

    def output_log(self) -> list[tuple[str, int]]:
        """Mathematics: expose a copy of `O`, leaving transport queues untouched."""

        return list(self._outputs)

    def syscall(self, name: str, arguments: tuple[str, ...]) -> tuple[int, bool]:
        """Mathematics: the pure mailbox backend refuses kernel effects rather than fabricating a syscall result."""

        raise RuntimeError(f"SYSCALL requires an OS execution backend: {name}")


@dataclass(frozen=True)
class Transition:
    """The result of one application of the algebraic transition function."""

    next_pc: int
    halted: bool = False
    blocked: bool = False


def compare_values(left: int, right: int) -> int:
    """Mathematics: return `sgn(left - right) ∈ {-1, 0, 1}`, the total order comparison identity."""

    return (left > right) - (left < right)


def apply_instruction(
    instruction: Instruction,
    pc: int,
    backend: ExecutionBackend,
) -> Transition:
    """Mathematics: apply one deterministic relation `T(pc, R, Q, O) -> (pc', R', Q', O')` from the eight-opcode algebra."""

    op = instruction.op
    args = instruction.args
    if op is Op.SET:
        backend.write_register(args[0], args[1])
        return Transition(pc + 1)
    if op is Op.COPY:
        backend.write_register(args[0], backend.read_register(args[1]))
        return Transition(pc + 1)
    if op is Op.ADD:
        backend.write_register(
            args[0], backend.read_register(args[1]) + backend.read_register(args[2])
        )
        return Transition(pc + 1)
    if op is Op.COMPARE:
        backend.write_register(
            args[0], compare_values(backend.read_register(args[1]), backend.read_register(args[2]))
        )
        return Transition(pc + 1)
    if op is Op.BRANCH:
        condition = backend.read_register(args[0])
        return Transition(args[1] if condition != 0 else pc + 1)
    if op is Op.SEND:
        backend.send(args[0], backend.read_register(args[1]))
        return Transition(pc + 1)
    if op is Op.WAIT:
        value = backend.receive(args[0])
        if value is None:
            return Transition(pc, blocked=True)
        backend.write_register(args[1], value)
        return Transition(pc + 1)
    if op is Op.SYSCALL:
        result, halt_after = backend.syscall(args[1], tuple(args[2:]))
        backend.write_register(args[0], result)
        return Transition(pc + 1, halted=halt_after)
    if op is Op.HALT:
        return Transition(pc, halted=True)
    raise ValueError(f"unsupported opcode: {op}")


def code_address(pc: int) -> str:
    """Mathematics: map each program counter `pc ∈ N` injectively to the code mailbox `code:pc`."""

    return f"code:{pc}"


def _trace_event(
    step: int,
    pc_before: int,
    instruction: Instruction,
    transition: Transition,
    backend: ExecutionBackend,
    output_start: int,
) -> TraceEvent:
    """Mathematics: record the observable projection `π(state_after)` after one successful transition."""

    output_delta = tuple(backend.output_log()[output_start:])
    registers = tuple(sorted(backend.snapshot_registers().items()))
    return TraceEvent(
        step=step,
        pc_before=pc_before,
        op=instruction.op.value,
        args=instruction.args,
        pc_after=transition.next_pc,
        registers=registers,
        output_delta=output_delta,
    )


class ReferenceInterpreter:
    """Transport-free interpreter whose transitions define the conformance oracle."""

    def __init__(self, program: Program) -> None:
        """Mathematics: fix a finite transition table `P : pc -> instruction` for this interpreter instance."""

        self.program = program

    def run(
        self,
        initial_registers: dict[str, int] | None = None,
        inputs: dict[str, Sequence[int]] | None = None,
        max_steps: int = DEFAULT_MAX_STEPS,
    ) -> RunResult:
        """Mathematics: execute the bounded orbit `s_k = T^k(s_0)` until `HALT`, `WAIT` with `⊥`, or `k = max_steps`."""

        if max_steps < 0:
            raise ValueError("max_steps must be non-negative")
        backend = ReferenceBackend(initial_registers or {}, inputs or {})
        state = MachineState(registers={}, pc=0)
        trace: list[TraceEvent] = []
        status = RunStatus.STEP_LIMIT
        for step in range(max_steps):
            instruction = self.program.instructions[state.pc]
            output_start = len(backend.output_log())
            transition = apply_instruction(instruction, state.pc, backend)
            if transition.blocked:
                state.blocked = True
                status = RunStatus.BLOCKED
                break
            state.steps += 1
            trace.append(
                _trace_event(
                    step,
                    state.pc,
                    instruction,
                    transition,
                    backend,
                    output_start,
                )
            )
            state.pc = transition.next_pc
            state.halted = transition.halted
            if state.halted:
                status = RunStatus.HALTED
                break
        state.registers = backend.snapshot_registers()
        return RunResult(status, state, tuple(trace), tuple(backend.output_log()))


class QueueInterpreter:
    """Interpreter whose execution token, registers, inputs, and outputs are transport messages."""

    def __init__(self, program: Program) -> None:
        """Mathematics: fix the same finite transition table `P` used by the reference interpreter."""

        self.program = program
        self.transport: InMemoryTransport | None = None

    def run(
        self,
        initial_registers: dict[str, int] | None = None,
        inputs: dict[str, Sequence[int]] | None = None,
        max_steps: int = DEFAULT_MAX_STEPS,
    ) -> RunResult:
        """Mathematics: preserve the token invariant `Q_code:pc = [instruction(pc)]` at every runnable boundary."""

        if max_steps < 0:
            raise ValueError("max_steps must be non-negative")
        transport = InMemoryTransport()
        self.transport = transport
        backend = QueueBackend(transport, initial_registers or {}, inputs or {})
        transport.send(code_address(0), instruction_message(self.program.instructions[0]))
        state = MachineState(registers={}, pc=0)
        trace: list[TraceEvent] = []
        status = RunStatus.STEP_LIMIT
        for step in range(max_steps):
            address = code_address(state.pc)
            token = transport.poll(address)
            if token is None:
                state.blocked = True
                status = RunStatus.BLOCKED
                break
            instruction = self.program.instructions[state.pc]
            output_start = len(backend.output_log())
            transition = apply_instruction(instruction, state.pc, backend)
            if transition.blocked:
                transport.send(address, instruction_message(instruction))
                state.blocked = True
                status = RunStatus.BLOCKED
                break
            state.steps += 1
            trace.append(
                _trace_event(
                    step,
                    state.pc,
                    instruction,
                    transition,
                    backend,
                    output_start,
                )
            )
            state.pc = transition.next_pc
            state.halted = transition.halted
            if state.halted:
                status = RunStatus.HALTED
                break
            transport.send(code_address(state.pc), instruction_message(self.program.instructions[state.pc]))
        state.registers = backend.snapshot_registers()
        return RunResult(status, state, tuple(trace), tuple(backend.output_log()))
