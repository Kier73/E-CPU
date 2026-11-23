from __future__ import annotations

import pytest

from mailcpu import AssemblyError, assemble, disassemble
from mailcpu.model import OPCODE_ARITY, Instruction, Op, Program


_EXACT_ARITY_OPERANDS = {
    Op.SET: ("value", "7"),
    Op.COPY: ("target", "value"),
    Op.ADD: ("target", "left", "right"),
    Op.MUL: ("target", "left", "right"),
    Op.COMPARE: ("target", "left", "right"),
    Op.BRANCH: ("flag", "1"),
    Op.SEND: ("mailbox", "value"),
    Op.WAIT: ("mailbox", "value"),
    Op.HALT: (),
}


def test_opcode_arity_is_single_sourced_for_assembler_and_validator() -> None:
    """Mathematics: one table `OPCODE_ARITY` fixes `|args| = OPCODE_ARITY[op]` for both the assembler and `validate_instruction`, so any second copy would have to agree on every width."""

    assert set(OPCODE_ARITY) == set(Op)
    for op, operands in _EXACT_ARITY_OPERANDS.items():
        arity = OPCODE_ARITY[op]
        assert arity is not None
        assert len(operands) == arity
        source = f"{op.value.lower()} {' '.join(operands)}\nhalt\n"
        assert assemble(source).instructions[0].op is op
        if arity > 0:
            with pytest.raises(AssemblyError, match="expects"):
                assemble(f"{op.value.lower()} {' '.join(operands + ('surplus',))}\nhalt\n")
            with pytest.raises(AssemblyError, match="expects"):
                assemble(f"{op.value.lower()}\nhalt\n")
    assert OPCODE_ARITY[Op.SYSCALL] is None
    with pytest.raises(AssemblyError, match="SYSCALL expects destination and syscall name"):
        assemble("syscall\nhalt\n")


def test_label_assembly_and_disassembly_round_trip() -> None:
    """Mathematics: verify `assemble(disassemble(P)) = P` for a labelled control-flow program."""

    source = """
        set n, 3
        set one, 1
        set zero, 0
        set minus_one, -1
    loop:
        compare positive, n, zero
        branch positive, decrement
        halt
    decrement:
        add n, n, minus_one
        branch one, loop
    """
    program = assemble(source)
    assert assemble(disassemble(program)) == program
    assert program.instructions[5].args[1] == 7
    assert program.instructions[8].args[1] == 4


def test_assembly_reports_invalid_source_instead_of_lowering_it() -> None:
    """Mathematics: a malformed source has no defined image under the partial compiler `assemble : S ⇀ P`."""

    with pytest.raises(AssemblyError, match="unknown opcode"):
        assemble("nonsense r0")
    with pytest.raises(AssemblyError, match="expected integer"):
        assemble("set r0 missing")
    with pytest.raises(AssemblyError, match="outside"):
        assemble("branch r0 4\nhalt")


@pytest.mark.parametrize(
    "register",
    ("name with spaces", "name#comment", "a,b", "quote'and\\\"double",
     "x\\\\y", "new\\nline", "tab\\tvalue", "@u:literal", "λ-cpu"),
)
def test_disassembly_round_trips_every_validated_register_name(register: str) -> None:
    """Mathematics: encoded lexical operands preserve symbolic name identity over UTF-8."""

    program = Program((
        Instruction(Op.SET, (register, 19)),
        Instruction(Op.COPY, ("receiver", register)),
        Instruction(Op.SEND, ("mailbox", register)),
        Instruction(Op.HALT),
    ))
    assert assemble(disassemble(program)) == program


def test_quoted_commas_are_data_not_delimiters() -> None:
    """Mathematics: shell-quoted commas remain inside a single mailbox token."""

    program = assemble('SET "x,y" 3\\nSEND "message,queue" "x,y"\\nHALT\\n')
    assert program.instructions[0].args == ("x,y", 3)
    assert program.instructions[1].args == ("message,queue", "x,y")
    assert assemble(disassemble(program)) == program


def test_unicode_numerals_do_not_enter_canonical_assembly() -> None:
    """Mathematics: numerals are ASCII tokens and cannot depend on Unicode digit aliases."""

    with pytest.raises(AssemblyError, match="expected integer"):
        assemble("SET a ١٢٣\\nHALT\\n")
