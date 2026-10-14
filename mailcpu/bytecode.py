"""Validated binary executable format for native MailCPU programs."""

from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass

from .model import Instruction, Op, Program


class BytecodeError(ValueError):
    """A binary MailCPU executable is malformed, unsupported, or inconsistent."""


_MAGIC = b"MCPB"
_VERSION = 1
_HEADER = struct.Struct(">4sBI")
_U32 = struct.Struct(">I")
_MAX_INSTRUCTIONS = 1_000_000
_MAX_OPERAND_BYTES = 1_048_576
_OPCODES = {op: index for index, op in enumerate(Op, 1)}
_OPS_BY_CODE = {code: op for op, code in _OPCODES.items()}


@dataclass(frozen=True)
class BytecodeExecutable:
    """A self-validating binary encoding of one finite MailCPU instruction graph."""

    program: Program

    def to_bytes(self) -> bytes:
        """Mathematics: encode `P=(i_0,...,i_{n-1})` as `H || n || Π encode(i_k)` with injective tagged operands."""

        instructions = self.program.instructions
        if len(instructions) > _MAX_INSTRUCTIONS:
            raise BytecodeError("instruction count exceeds bytecode limit")
        output = bytearray(_HEADER.pack(_MAGIC, _VERSION, len(instructions)))
        for instruction in instructions:
            try:
                opcode = _OPCODES[instruction.op]
            except KeyError as exc:
                raise BytecodeError(f"unsupported opcode: {instruction.op}") from exc
            if len(instruction.args) > 0xFFFF:
                raise BytecodeError("operand count exceeds bytecode limit")
            output.extend(struct.pack(">BH", opcode, len(instruction.args)))
            for operand in instruction.args:
                if isinstance(operand, bool):
                    raise BytecodeError("boolean operands are not part of the native bytecode domain")
                if isinstance(operand, int):
                    tag = b"I"
                    encoded = str(operand).encode("ascii")
                elif isinstance(operand, str):
                    tag = b"S"
                    encoded = operand.encode("utf-8")
                else:
                    raise BytecodeError(f"unsupported operand type: {type(operand).__name__}")
                if len(encoded) > _MAX_OPERAND_BYTES:
                    raise BytecodeError("operand exceeds bytecode size limit")
                output.extend(tag)
                output.extend(_U32.pack(len(encoded)))
                output.extend(encoded)
        return bytes(output)

    @classmethod
    def from_bytes(cls, payload: bytes) -> "BytecodeExecutable":
        """Mathematics: invert `to_bytes` only when header, bounds, tags, EOF, and `Program` validation all hold."""

        data = bytes(payload)
        if len(data) < _HEADER.size:
            raise BytecodeError("bytecode is truncated before header")
        magic, version, instruction_count = _HEADER.unpack_from(data, 0)
        if magic != _MAGIC or version != _VERSION:
            raise BytecodeError("unsupported bytecode header")
        if instruction_count > _MAX_INSTRUCTIONS:
            raise BytecodeError("instruction count exceeds bytecode limit")
        cursor = _HEADER.size
        instructions: list[Instruction] = []
        for _ in range(instruction_count):
            if cursor + 3 > len(data):
                raise BytecodeError("bytecode is truncated before instruction")
            opcode_code, operand_count = struct.unpack_from(">BH", data, cursor)
            cursor += 3
            try:
                opcode = _OPS_BY_CODE[opcode_code]
            except KeyError as exc:
                raise BytecodeError(f"unknown bytecode opcode: {opcode_code}") from exc
            operands: list[int | str] = []
            for _ in range(operand_count):
                if cursor + 5 > len(data):
                    raise BytecodeError("bytecode is truncated before operand")
                tag = data[cursor : cursor + 1]
                size = _U32.unpack_from(data, cursor + 1)[0]
                cursor += 5
                if size > _MAX_OPERAND_BYTES or cursor + size > len(data):
                    raise BytecodeError("bytecode operand exceeds bounds")
                raw = data[cursor : cursor + size]
                cursor += size
                if tag == b"I":
                    try:
                        value = int(raw.decode("ascii"), 10)
                    except (UnicodeDecodeError, ValueError) as exc:
                        raise BytecodeError("invalid integer operand") from exc
                elif tag == b"S":
                    try:
                        value = raw.decode("utf-8")
                    except UnicodeDecodeError as exc:
                        raise BytecodeError("invalid UTF-8 string operand") from exc
                else:
                    raise BytecodeError(f"unknown operand tag: {tag!r}")
                operands.append(value)
            instructions.append(Instruction(opcode, tuple(operands)))
        if cursor != len(data):
            raise BytecodeError("trailing bytes after bytecode program")
        try:
            program = Program(tuple(instructions))
        except ValueError as exc:
            raise BytecodeError(str(exc)) from exc
        return cls(program)

    def digest(self) -> str:
        """Mathematics: identify executable bytes by `h=SHA256(to_bytes(P))`, independent of JSON presentation."""

        return hashlib.sha256(self.to_bytes()).hexdigest()
