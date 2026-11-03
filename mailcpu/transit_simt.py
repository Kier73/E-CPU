"""Bounded lockstep SIMT reference interpreter for transit computation queries."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Mapping

from .classifier import HypervisorArbitrationEvent


_OPERATION = "execute deterministic CPU SIMT reference program"
_RESOURCE = "/gpu/simt"
_EXECUTE_RIGHT = frozenset({"execute"})
_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}")
_ARITY = {
    "const": 2,
    "lane_id": 1,
    "load": 2,
    "copy": 2,
    "add": 3,
    "sub": 3,
    "mul": 3,
    "lt": 3,
    "if": 1,
    "else": 0,
    "endif": 0,
    "barrier": 0,
    "store": 2,
    "halt": 0,
}


class TransitSIMTError(ValueError):
    """Mathematics: reject a SIMT request unless typed program, lane masks, barriers, and resource bounds preserve the reference execution relation."""


class TransitSIMTHost:
    """Mathematics: evaluate a bounded lockstep transition relation over lane valuations, active masks, structured reconvergence, and converged barriers."""

    def __init__(
        self,
        *,
        max_lanes: int = 64,
        max_instructions: int = 512,
        max_steps: int = 512,
        max_registers: int = 64,
        max_input_elements: int = 4096,
        max_integer_bits: int = 4096,
    ) -> None:
        """Mathematics: fix finite execution bounds B=(lanes,instructions,steps,registers,elements,integer_bits)."""

        bounds = (
            max_lanes,
            max_instructions,
            max_steps,
            max_registers,
            max_input_elements,
            max_integer_bits,
        )
        if any(not isinstance(value, int) or isinstance(value, bool) or value <= 0 for value in bounds):
            raise ValueError("SIMT execution bounds must be positive integers")
        self.max_lanes = max_lanes
        self.max_instructions = max_instructions
        self.max_steps = max_steps
        self.max_registers = max_registers
        self.max_input_elements = max_input_elements
        self.max_integer_bits = max_integer_bits

    def handle(self, event: HypervisorArbitrationEvent) -> dict[str, Any]:
        """Mathematics: evaluate bounded lockstep program P over lanes L and return outputs plus a canonical state receipt."""

        if not isinstance(event, HypervisorArbitrationEvent):
            raise TransitSIMTError("SIMT host requires a typed arbitration event")
        request = event.request
        if request.operation != _OPERATION or request.resource != _RESOURCE:
            raise TransitSIMTError("operation identity is not a SIMT reference request")
        if request.required_rights != _EXECUTE_RIGHT or request.granted_rights != _EXECUTE_RIGHT:
            raise TransitSIMTError("exact receiver-local execute authority is required")
        if request.destructive:
            raise TransitSIMTError("SIMT reference requests cannot be marked destructive")

        payload = request.payload
        if not isinstance(payload, Mapping):
            raise TransitSIMTError("SIMT payload must be a mapping")
        if set(payload) != {"lanes", "inputs", "program", "max_steps"}:
            raise TransitSIMTError("SIMT payload fields are invalid")

        lanes = payload.get("lanes")
        if (
            not isinstance(lanes, int)
            or isinstance(lanes, bool)
            or lanes <= 0
            or lanes > self.max_lanes
        ):
            raise TransitSIMTError("lane count is outside configured bounds")

        raw_inputs = payload.get("inputs")
        if not isinstance(raw_inputs, Mapping):
            raise TransitSIMTError("SIMT inputs must be a mapping of names to lane arrays")
        inputs: dict[str, tuple[int, ...]] = {}
        input_elements = 0
        for name, raw_values in raw_inputs.items():
            self._require_name(name, "input array")
            if not isinstance(raw_values, (list, tuple)) or len(raw_values) != lanes:
                raise TransitSIMTError(f"input array {name!r} must contain exactly {lanes} lane values")
            values: list[int] = []
            for value in raw_values:
                self._require_integer(value, "input value")
                self._require_integer_bound(value)
                values.append(value)
            inputs[name] = tuple(values)
            input_elements += len(values)
        if input_elements > self.max_input_elements:
            raise TransitSIMTError("SIMT input element count exceeds configured bound")

        raw_program = payload.get("program")
        if not isinstance(raw_program, (list, tuple)) or not raw_program:
            raise TransitSIMTError("SIMT program must be a non-empty instruction sequence")
        if len(raw_program) > self.max_instructions:
            raise TransitSIMTError("SIMT instruction count exceeds configured bound")
        program, register_names, output_names = self._validate_program(raw_program, inputs)
        if len(register_names) > self.max_registers:
            raise TransitSIMTError("SIMT register count exceeds configured bound")
        budget = payload.get("max_steps")
        if (
            not isinstance(budget, int)
            or isinstance(budget, bool)
            or budget <= 0
            or budget > self.max_steps
            or len(program) > budget
        ):
            raise TransitSIMTError("SIMT step budget is outside configured bounds")

        registers: dict[str, list[int | bool | None]] = {
            name: [None] * lanes for name in register_names
        }
        outputs: dict[str, list[int | None]] = {
            name: [None] * lanes for name in output_names
        }
        active = [True] * lanes
        stack: list[dict[str, Any]] = []
        mask_trace: list[dict[str, object]] = []
        barrier_trace: list[dict[str, int]] = []

        for pc, (opcode, args) in enumerate(program):
            if opcode == "const":
                destination, value = args
                self._require_integer_bound(value)
                self._write_active(registers[destination], value, active)
            elif opcode == "lane_id":
                (destination,) = args
                self._write_active(registers[destination], None, active, lane_ids=True)
            elif opcode == "load":
                destination, input_name = args
                for lane, enabled in enumerate(active):
                    if enabled:
                        registers[destination][lane] = inputs[input_name][lane]
            elif opcode == "copy":
                destination, source = args
                for lane, enabled in enumerate(active):
                    if enabled:
                        value = self._read(registers[source][lane], source, lane)
                        registers[destination][lane] = value
            elif opcode in {"add", "sub", "mul"}:
                destination, left, right = args
                for lane, enabled in enumerate(active):
                    if enabled:
                        a = self._read_integer(registers[left][lane], left, lane)
                        b = self._read_integer(registers[right][lane], right, lane)
                        value = a + b if opcode == "add" else a - b if opcode == "sub" else a * b
                        self._require_integer_bound(value)
                        registers[destination][lane] = value
            elif opcode == "lt":
                destination, left, right = args
                for lane, enabled in enumerate(active):
                    if enabled:
                        a = self._read_integer(registers[left][lane], left, lane)
                        b = self._read_integer(registers[right][lane], right, lane)
                        registers[destination][lane] = a < b
            elif opcode == "if":
                (predicate_name,) = args
                parent = list(active)
                condition = [
                    parent[lane]
                    and self._read_predicate(registers[predicate_name][lane], predicate_name, lane)
                    for lane in range(lanes)
                ]
                stack.append(
                    {
                        "parent": parent,
                        "condition": condition,
                        "else_seen": False,
                    }
                )
                active = [parent[lane] and condition[lane] for lane in range(lanes)]
                mask_trace.append(self._mask_event(pc, "if", active))
            elif opcode == "else":
                if not stack:
                    raise TransitSIMTError("ELSE has no active IF")
                frame = stack[-1]
                if frame["else_seen"]:
                    raise TransitSIMTError("SIMT IF may contain only one ELSE")
                frame["else_seen"] = True
                active = [
                    frame["parent"][lane] and not frame["condition"][lane]
                    for lane in range(lanes)
                ]
                mask_trace.append(self._mask_event(pc, "else", active))
            elif opcode == "endif":
                if not stack:
                    raise TransitSIMTError("ENDIF has no active IF")
                frame = stack.pop()
                active = list(frame["parent"])
                mask_trace.append(self._mask_event(pc, "endif", active))
            elif opcode == "barrier":
                if stack or not all(active):
                    raise TransitSIMTError(
                        "barrier requires a converged workgroup with every lane active"
                    )
                epoch = len(barrier_trace) + 1
                barrier_trace.append(
                    {"epoch": epoch, "pc": pc, "arrivals": lanes}
                )
            elif opcode == "store":
                output_name, source = args
                for lane, enabled in enumerate(active):
                    if enabled:
                        value = self._read_integer(registers[source][lane], source, lane)
                        outputs[output_name][lane] = value
            elif opcode == "halt":
                if stack or not all(active):
                    raise TransitSIMTError("HALT requires all lanes to reconverge")
            else:
                raise TransitSIMTError(f"unsupported SIMT opcode: {opcode}")

        incomplete = [
            name
            for name, values in outputs.items()
            if any(value is None for value in values)
        ]
        if incomplete:
            raise TransitSIMTError(
                "SIMT output arrays were not written by every lane: " + ", ".join(sorted(incomplete))
            )

        materialized_outputs = {
            name: [int(value) for value in values]
            for name, values in sorted(outputs.items())
        }
        materialized_registers = {
            name: list(values)
            for name, values in sorted(registers.items())
        }
        state = {
            "lanes": lanes,
            "steps": len(program),
            "registers": materialized_registers,
            "outputs": materialized_outputs,
            "mask_trace": mask_trace,
            "barriers": barrier_trace,
        }
        canonical = json.dumps(
            state,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        return {
            **state,
            "state_digest": hashlib.sha256(canonical).hexdigest(),
        }

    def _validate_program(
        self,
        raw_program: list[Any] | tuple[Any, ...],
        inputs: Mapping[str, tuple[int, ...]],
    ) -> tuple[list[tuple[str, tuple[Any, ...]]], set[str], set[str]]:
        """Mathematics: validate instruction typing and structured IF/ELSE/ENDIF nesting before executing program P."""

        program: list[tuple[str, tuple[Any, ...]]] = []
        registers: set[str] = set()
        outputs: set[str] = set()
        stack: list[bool] = []
        halted = False

        for pc, raw in enumerate(raw_program):
            if halted:
                raise TransitSIMTError("no instruction may follow HALT")
            if not isinstance(raw, (list, tuple)) or not raw or not isinstance(raw[0], str):
                raise TransitSIMTError(f"SIMT instruction {pc} must be a non-empty sequence")
            opcode = raw[0].lower()
            if opcode not in _ARITY:
                raise TransitSIMTError(f"unknown SIMT opcode at pc {pc}: {opcode!r}")
            args = tuple(raw[1:])
            if len(args) != _ARITY[opcode]:
                raise TransitSIMTError(
                    f"SIMT {opcode.upper()} at pc {pc} expects {_ARITY[opcode]} operands"
                )

            if opcode == "const":
                destination, value = args
                self._require_name(destination, "register")
                self._require_integer(value, "constant")
                registers.add(destination)
            elif opcode in {"lane_id"}:
                (destination,) = args
                self._require_name(destination, "register")
                registers.add(destination)
            elif opcode == "load":
                destination, input_name = args
                self._require_name(destination, "register")
                self._require_name(input_name, "input array")
                if input_name not in inputs:
                    raise TransitSIMTError(f"unknown SIMT input array: {input_name}")
                registers.add(destination)
            elif opcode == "copy":
                destination, source = args
                self._require_name(destination, "register")
                self._require_name(source, "register")
                registers.update((destination, source))
            elif opcode in {"add", "sub", "mul", "lt"}:
                destination, left, right = args
                for name in args:
                    self._require_name(name, "register")
                registers.update((destination, left, right))
            elif opcode == "if":
                (predicate_name,) = args
                self._require_name(predicate_name, "predicate register")
                registers.add(predicate_name)
                stack.append(False)
            elif opcode == "else":
                if not stack:
                    raise TransitSIMTError("ELSE has no matching IF")
                if stack[-1]:
                    raise TransitSIMTError("SIMT IF may contain only one ELSE")
                stack[-1] = True
            elif opcode == "endif":
                if not stack:
                    raise TransitSIMTError("ENDIF has no matching IF")
                stack.pop()
            elif opcode == "barrier":
                if stack:
                    raise TransitSIMTError("BARRIER must appear after explicit reconvergence (ENDIF)")
            elif opcode == "store":
                output_name, source = args
                self._require_name(output_name, "output array")
                self._require_name(source, "register")
                outputs.add(output_name)
                registers.add(source)
            elif opcode == "halt":
                if stack:
                    raise TransitSIMTError("HALT cannot occur inside a divergent control region")
                if pc != len(raw_program) - 1:
                    raise TransitSIMTError("HALT must be the final SIMT instruction")
                halted = True

            program.append((opcode, args))

        if stack:
            raise TransitSIMTError("SIMT program has an unterminated IF region")
        if not halted:
            raise TransitSIMTError("SIMT program must terminate with HALT")
        return program, registers, outputs

    @staticmethod
    def _require_name(value: Any, label: str) -> None:
        """Mathematics: require symbolic name n to belong to the finite register/address grammar NAME."""

        if not isinstance(value, str) or _NAME.fullmatch(value) is None:
            raise TransitSIMTError(f"{label} name is invalid")

    @staticmethod
    def _require_integer(value: Any, label: str) -> None:
        """Mathematics: restrict integer operands to Z while excluding Boolean values from Python's integer subtype."""

        if not isinstance(value, int) or isinstance(value, bool):
            raise TransitSIMTError(f"{label} must be an integer")

    def _require_integer_bound(self, value: int) -> None:
        """Mathematics: require integer magnitude to fit the configured finite bit domain."""

        if value.bit_length() > self.max_integer_bits:
            raise TransitSIMTError("SIMT integer exceeds configured bit bound")

    @staticmethod
    def _read(value: int | bool | None, register: str, lane: int) -> int | bool:
        """Mathematics: require register cell R[register,lane] to be defined before reading it."""

        if value is None:
            raise TransitSIMTError(f"register {register!r} is undefined for lane {lane}")
        return value

    @classmethod
    def _read_integer(cls, value: int | bool | None, register: str, lane: int) -> int:
        """Mathematics: project a defined register cell onto the integer domain Z, excluding predicates."""

        result = cls._read(value, register, lane)
        if not isinstance(result, int) or isinstance(result, bool):
            raise TransitSIMTError(f"register {register!r} is not an integer for lane {lane}")
        return result

    @classmethod
    def _read_predicate(cls, value: int | bool | None, register: str, lane: int) -> bool:
        """Mathematics: project a defined register cell onto the Boolean lane-mask domain."""

        result = cls._read(value, register, lane)
        if not isinstance(result, bool):
            raise TransitSIMTError(f"register {register!r} is not a predicate for lane {lane}")
        return result

    @staticmethod
    def _write_active(
        destination: list[int | bool | None],
        value: int | None,
        active: list[bool],
        *,
        lane_ids: bool = False,
    ) -> None:
        """Mathematics: assign destination register only on active lanes, preserving inactive lane values."""

        for lane, enabled in enumerate(active):
            if enabled:
                destination[lane] = lane if lane_ids else value

    @staticmethod
    def _mask_event(pc: int, opcode: str, active: list[bool]) -> dict[str, object]:
        """Mathematics: expose the active-lane set M_pc={i | active[i]=1} at a structured branch boundary."""

        return {
            "pc": pc,
            "opcode": opcode,
            "active_lanes": [lane for lane, enabled in enumerate(active) if enabled],
        }
