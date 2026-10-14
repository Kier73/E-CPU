"""Text assembler and disassembler for the native MailCPU instruction set."""

from __future__ import annotations

import shlex

from .model import OPCODE_ARITY, Instruction, Op, Program


class AssemblyError(ValueError):
    """A source file is not a member of the MailCPU assembly grammar."""


def _tokens(line: str, line_number: int) -> list[str]:
    """Mathematics: tokenize a source line as the finite word sequence `w_1 ... w_n` under shell quoting."""

    try:
        return shlex.split(line.replace(",", " "), comments=True, posix=True)
    except ValueError as exc:
        raise AssemblyError(f"line {line_number}: {exc}") from exc


def _parse_integer(token: str, line_number: int) -> int:
    """Mathematics: parse an operand in `Z` using Python's base-0 numeral homomorphism `parse : token -> integer`."""

    try:
        return int(token, 0)
    except ValueError as exc:
        raise AssemblyError(f"line {line_number}: expected integer, got {token!r}") from exc


def _branch_target(token: str, labels: dict[str, int], line_number: int) -> int:
    """Mathematics: resolve `target = labels[token]` when defined, otherwise evaluate `target = parse(token)`."""

    if token in labels:
        return labels[token]
    return _parse_integer(token, line_number)


def assemble(source: str) -> Program:
    """Mathematics: compile source `S` into `P = validate([decode(line_i)])`, with labels as pc-valued symbols."""

    if not isinstance(source, str):
        raise AssemblyError("source must be text")
    parsed: list[tuple[int, list[str]]] = []
    labels: dict[str, int] = {}
    for line_number, raw_line in enumerate(source.splitlines(), 1):
        line = raw_line.strip()
        if not line:
            continue
        tokens = _tokens(line, line_number)
        if not tokens:
            continue
        while tokens and tokens[0].endswith(":"):
            label = tokens.pop(0)[:-1]
            if not label or not label.replace("_", "a").isalnum() or label[0].isdigit():
                raise AssemblyError(f"line {line_number}: invalid label {label!r}")
            if label in labels:
                raise AssemblyError(f"line {line_number}: duplicate label {label!r}")
            labels[label] = len(parsed)
        if tokens:
            parsed.append((line_number, tokens))

    instructions: list[Instruction] = []
    for line_number, tokens in parsed:
        opcode_text, *operands = tokens
        try:
            opcode = Op(opcode_text.upper())
        except ValueError as exc:
            raise AssemblyError(f"line {line_number}: unknown opcode {opcode_text!r}") from exc
        expected = OPCODE_ARITY[opcode]
        if expected is None:
            if len(operands) < 2:
                raise AssemblyError(f"line {line_number}: SYSCALL expects destination and syscall name")
        elif len(operands) != expected:
            raise AssemblyError(
                f"line {line_number}: {opcode.value} expects {expected} operands, got {len(operands)}"
            )
        if opcode is Op.SET:
            args = (operands[0], _parse_integer(operands[1], line_number))
        elif opcode is Op.COPY:
            args = tuple(operands)
        elif opcode in (Op.ADD, Op.COMPARE):
            args = tuple(operands)
        elif opcode is Op.BRANCH:
            args = (operands[0], _branch_target(operands[1], labels, line_number))
        elif opcode is Op.SEND:
            args = (operands[0], operands[1])
        elif opcode is Op.WAIT:
            args = (operands[0], operands[1])
        elif opcode is Op.SYSCALL:
            args = tuple(operands)
        else:
            args = ()
        instructions.append(Instruction(opcode, args))
    try:
        return Program(tuple(instructions))
    except ValueError as exc:
        raise AssemblyError(str(exc)) from exc


def _format_operand(value: object) -> str:
    """Mathematics: serialize each operand under the injective textual encoding `encode : A -> tokens`."""

    return str(value)


def disassemble(program: Program) -> str:
    """Mathematics: emit `decode(disassemble(P)) = P` for every validated finite program `P`."""

    lines: list[str] = []
    for instruction in program.instructions:
        operands = " ".join(_format_operand(value) for value in instruction.args)
        lines.append(instruction.op.value + ((" " + operands) if operands else ""))
    return "\n".join(lines) + "\n"
