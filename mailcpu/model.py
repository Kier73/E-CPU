"""Core MailCPU data types and validation rules."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable, Mapping, Sequence


class Op(str, Enum):
    """The nine operations in the native MailCPU instruction set."""

    SET = "SET"
    COPY = "COPY"
    ADD = "ADD"
    COMPARE = "COMPARE"
    BRANCH = "BRANCH"
    SEND = "SEND"
    WAIT = "WAIT"
    SYSCALL = "SYSCALL"
    HALT = "HALT"


@dataclass(frozen=True)
class Instruction:
    """An immutable opcode plus its body operands."""

    op: Op
    args: tuple[Any, ...] = ()


@dataclass(frozen=True)
class Program:
    """A finite instruction sequence with validated branch targets."""

    instructions: tuple[Instruction, ...]

    def __post_init__(self) -> None:
        """Mathematics: validate that every transition target lies in `[0, n)` for program length `n`."""

        validate_program(self.instructions)


@dataclass(frozen=True)
class Message:
    """The transport-neutral envelope described by the plan."""

    sender: str = ""
    recipient: str = ""
    op: str = ""
    addr: str = ""
    value: int | None = None
    seq: int = 0
    body: tuple[Any, ...] = ()
    message_id: str = ""


@dataclass
class MachineState:
    """Observable machine state at a transition boundary."""

    registers: dict[str, int] = field(default_factory=dict)
    pc: int = 0
    halted: bool = False
    blocked: bool = False
    steps: int = 0


class RunStatus(str, Enum):
    """The terminal result of a bounded execution attempt."""

    HALTED = "halted"
    BLOCKED = "blocked"
    STEP_LIMIT = "step_limit"


@dataclass(frozen=True)
class TraceEvent:
    """A canonical machine-level event, independent of transport message IDs."""

    step: int
    pc_before: int
    op: str
    args: tuple[Any, ...]
    pc_after: int
    registers: tuple[tuple[str, int], ...]
    output_delta: tuple[tuple[str, int], ...] = ()


@dataclass(frozen=True)
class RunResult:
    """Execution result used by conformance and differential tests."""

    status: RunStatus
    state: MachineState
    trace: tuple[TraceEvent, ...]
    outputs: tuple[tuple[str, int], ...]


def _is_int(value: Any) -> bool:
    """Mathematics: accept the integer domain `Z` while excluding Boolean values, whose Python subtype relation would otherwise admit `True = 1`."""

    return isinstance(value, int) and not isinstance(value, bool)


DEFAULT_MAX_STEPS = 10_000
DEFAULT_MAX_TICKS = 10_000

OPCODE_ARITY = {
    Op.SET: 2,
    Op.COPY: 2,
    Op.ADD: 3,
    Op.COMPARE: 3,
    Op.BRANCH: 2,
    Op.SEND: 2,
    Op.WAIT: 2,
    Op.SYSCALL: None,
    Op.HALT: 0,
}


def _expect_register(value: Any, position: str) -> None:
    """Mathematics: register names are elements of a symbolic address set `A`, represented as non-empty strings."""

    if not isinstance(value, str) or not value:
        raise ValueError(f"{position} must be a non-empty register name")


def _expect_arity(op: Op, args: Sequence[Any], arity: int) -> None:
    """Mathematics: an instruction is a partial function only on its declared operand domain, so `|args| = arity` is required."""

    if len(args) != arity:
        raise ValueError(f"{op.value} expects {arity} operands, got {len(args)}")


def validate_instruction(instruction: Instruction) -> None:
    """Mathematics: enforce the typed domain of each opcode before applying the transition function `T`."""

    op = instruction.op
    args = instruction.args
    arity = OPCODE_ARITY[op]
    if arity is not None:
        _expect_arity(op, args, arity)

    if op is Op.SET:
        _expect_register(args[0], "SET destination")
        if not _is_int(args[1]):
            raise ValueError("SET value must be an integer")
    elif op is Op.COPY:
        _expect_register(args[0], "COPY destination")
        _expect_register(args[1], "COPY source")
    elif op in (Op.ADD, Op.COMPARE):
        _expect_register(args[0], f"{op.value} destination")
        _expect_register(args[1], f"{op.value} left operand")
        _expect_register(args[2], f"{op.value} right operand")
    elif op is Op.BRANCH:
        _expect_register(args[0], "BRANCH condition")
        if not _is_int(args[1]):
            raise ValueError("BRANCH target must be an integer")
    elif op is Op.SEND:
        _expect_register(args[1], "SEND source")
        if not isinstance(args[0], str) or not args[0]:
            raise ValueError("SEND mailbox must be a non-empty address")
    elif op is Op.WAIT:
        if not isinstance(args[0], str) or not args[0]:
            raise ValueError("WAIT mailbox must be a non-empty address")
        _expect_register(args[1], "WAIT destination")
    elif op is Op.SYSCALL:
        if len(args) < 2:
            raise ValueError("SYSCALL expects destination and syscall name")
        _expect_register(args[0], "SYSCALL destination")
        if not isinstance(args[1], str) or not args[1]:
            raise ValueError("SYSCALL name must be a non-empty string")
        if any(
            not isinstance(argument, str) or not argument or "=" not in argument
            for argument in args[2:]
        ):
            raise ValueError("SYSCALL arguments must be non-empty key=value strings")


def validate_program(instructions: Sequence[Instruction]) -> None:
    """Mathematics: for `n = len(program)`, require every static branch target `j` to satisfy `0 <= j < n`."""

    if not instructions:
        raise ValueError("a program must contain at least one instruction")
    for index, instruction in enumerate(instructions):
        validate_instruction(instruction)
        if instruction.op is Op.BRANCH:
            target = instruction.args[1]
            if target < 0 or target >= len(instructions):
                raise ValueError(
                    f"BRANCH at pc {index} targets {target}, outside [0, {len(instructions)})"
                )


def instruction_message(instruction: Instruction) -> Message:
    """Mathematics: encode an instruction as a message `m = (OP, BODY)` without changing its operands."""

    return Message(op=instruction.op.value, body=instruction.args, sender="program")


def canonical_trace(trace: Iterable[TraceEvent]) -> list[dict[str, Any]]:
    """Mathematics: map each trace event to a transport-invariant normal form, removing IDs and queue metadata."""

    return [
        {
            "step": event.step,
            "pc_before": event.pc_before,
            "op": event.op,
            "args": list(event.args),
            "pc_after": event.pc_after,
            "registers": [list(item) for item in event.registers],
            "output_delta": [list(item) for item in event.output_delta],
        }
        for event in trace
    ]


def canonical_result(result: RunResult) -> dict[str, Any]:
    """Mathematics: compare executions by the observable tuple `(status, state, trace, outputs)`, not implementation details."""

    return {
        "status": result.status.value,
        "state": {
            "registers": dict(sorted(result.state.registers.items())),
            "pc": result.state.pc,
            "halted": result.state.halted,
            "blocked": result.state.blocked,
            "steps": result.state.steps,
        },
        "trace": canonical_trace(result.trace),
        "outputs": [list(item) for item in result.outputs],
    }
