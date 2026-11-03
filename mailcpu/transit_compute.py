"""Bounded, side-effect-free arithmetic jobs executed on a MailCPU virtual CPU."""

from __future__ import annotations

import re
from typing import Any, Mapping

from .assembler import AssemblyError, assemble
from .classifier import HypervisorArbitrationEvent
from .headless import HeadlessOS
from .headless_relation import HeadlessRelationError, observe_headless_os_state
from .model import Op


class TransitComputeError(ValueError):
    """A transit computation request is malformed, unsafe, or exceeds its execution budget."""


_SAFE_OPS = frozenset({Op.SET, Op.COPY, Op.ADD, Op.COMPARE, Op.BRANCH, Op.HALT})
_REGISTER_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}")
_OPERATION = "execute deterministic CPU arithmetic program"
_RESOURCE = "/cpu/compute"
_EXECUTE_RIGHT = frozenset({"execute"})


class TransitComputeHost:
    """Execute a peer-supplied pure arithmetic program in an isolated MailCPU VM."""

    def __init__(
        self,
        *,
        max_source_bytes: int = 16_384,
        max_instructions: int = 512,
        max_ticks: int = 10_000,
        max_registers: int = 32,
    ) -> None:
        """Mathematics: establish finite admission bounds B=(source_bytes,instructions,ticks,registers) over each isolated job."""

        bounds = (max_source_bytes, max_instructions, max_ticks, max_registers)
        if any(not isinstance(value, int) or isinstance(value, bool) or value <= 0 for value in bounds):
            raise ValueError("transit compute bounds must be positive integers")
        self.max_source_bytes = max_source_bytes
        self.max_instructions = max_instructions
        self.max_ticks = max_ticks
        self.max_registers = max_registers

    def handle(self, event: HypervisorArbitrationEvent) -> dict[str, Any]:
        """Mathematics: admit only pure opcode program P, then return its bounded E-CPU terminal state and digest."""

        if not isinstance(event, HypervisorArbitrationEvent):
            raise TransitComputeError("transit compute requires a typed arbitration event")
        request = event.request
        if request.operation != _OPERATION or request.resource != _RESOURCE:
            raise TransitComputeError("operation identity is not a MailCPU compute request")
        if request.required_rights != _EXECUTE_RIGHT or request.granted_rights != _EXECUTE_RIGHT:
            raise TransitComputeError("exact receiver-local execute authority is required")
        if request.destructive:
            raise TransitComputeError("pure compute requests cannot be marked destructive")

        payload = request.payload
        if not isinstance(payload, Mapping):
            raise TransitComputeError("compute payload must be a mapping")
        if set(payload) != {"source", "initial_registers", "max_ticks"}:
            raise TransitComputeError("compute payload fields are invalid")
        source = payload.get("source")
        if not isinstance(source, str) or not source.strip():
            raise TransitComputeError("compute source must be non-empty text")
        if len(source.encode("utf-8")) > self.max_source_bytes:
            raise TransitComputeError("compute source exceeds configured byte bound")

        raw_registers = payload.get("initial_registers")
        if not isinstance(raw_registers, Mapping) or len(raw_registers) > self.max_registers:
            raise TransitComputeError("initial register map is outside configured bounds")
        initial_registers: dict[str, int] = {}
        for name, value in raw_registers.items():
            if not isinstance(name, str) or _REGISTER_NAME.fullmatch(name) is None:
                raise TransitComputeError("initial register name is invalid")
            if not isinstance(value, int) or isinstance(value, bool):
                raise TransitComputeError("initial register values must be integers")
            initial_registers[name] = value

        budget = payload.get("max_ticks")
        if (
            not isinstance(budget, int)
            or isinstance(budget, bool)
            or budget <= 0
            or budget > self.max_ticks
        ):
            raise TransitComputeError("requested tick budget is outside configured bounds")

        try:
            program = assemble(source)
        except (AssemblyError, TypeError, ValueError) as exc:
            raise TransitComputeError(f"compute program failed to assemble: {exc}") from exc
        if not program.instructions or len(program.instructions) > self.max_instructions:
            raise TransitComputeError("instruction count is outside configured bounds")
        forbidden = sorted({
            instruction.op.value
            for instruction in program.instructions
            if instruction.op not in _SAFE_OPS
        })
        if forbidden:
            raise TransitComputeError(
                "program contains non-compute operations: " + ", ".join(forbidden)
            )

        machine = HeadlessOS()
        parent_pid = machine.environment.init_pid
        if parent_pid is None:
            raise TransitComputeError("isolated MailCPU host has no init process")
        pid = machine.spawn(
            program,
            name=f"transit-compute-{event.sequence}",
            initial_registers=initial_registers,
            parent_pid=parent_pid,
        )
        events = machine.run(max_ticks=budget)
        report = machine.process(pid)
        if report.status != "exited":
            raise TransitComputeError(
                f"compute program did not halt within {budget} scheduler ticks"
            )
        try:
            witness = observe_headless_os_state(machine)
        except HeadlessRelationError as exc:
            raise TransitComputeError(f"compute state witness failed: {exc}") from exc

        return {
            "pid": pid,
            "status": report.status,
            "exit_code": report.exit_code,
            "pc": report.pc,
            "steps": report.steps,
            "scheduler_events": len(events),
            "registers": dict(sorted(report.registers.items())),
            "state_digest": witness.digest,
        }
