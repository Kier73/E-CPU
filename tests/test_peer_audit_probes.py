"""Adversarial peer audit probes retained as executable regression targets.

Previously repaired SEND/WAIT, mailbox, validation and assembly defects are
covered by test_conformance.py and test_assembler.py. Remaining journal and
resource findings are explicitly expected failures, not successful proofs.
"""

from __future__ import annotations

import pytest

from mailcpu.interpreter import ReferenceInterpreter
from mailcpu.journal import EventJournal
from mailcpu.model import Instruction, Op, Program


def _digest(payload: dict[object, object]) -> str:
    """Mathematics: compute the current event journal digest for one source payload."""

    return EventJournal().append("peer-audit", payload).digest


@pytest.mark.xfail(strict=True, reason="To Do: versioned injective EventJournal payload algebra")
def test_generic_journal_must_distinguish_integer_and_string_keys() -> None:
    """Mathematics: distinct typed maps must never share one event identity."""

    assert _digest({1: "a"}) != _digest({"1": "a"})


@pytest.mark.xfail(strict=True, reason="To Do: versioned injective EventJournal payload algebra")
def test_generic_journal_must_distinguish_list_and_tuple() -> None:
    """Mathematics: list and tuple values need distinct canonical identities."""

    assert _digest({"value": (1, 2)}) != _digest({"value": [1, 2]})


@pytest.mark.xfail(strict=True, reason="To Do: reject noncanonical journal snapshot coercion")
def test_event_journal_snapshot_sequence_must_not_coerce_string() -> None:
    """Mathematics: a journal sequence identity cannot change type on restore."""

    journal = EventJournal()
    journal.append("peer-audit", {"n": 1})
    snapshot = journal.snapshot()
    snapshot[0]["sequence"] = "1"
    with pytest.raises(ValueError):
        EventJournal.from_snapshot(snapshot)


@pytest.mark.xfail(strict=True, reason="To Do: reject non-finite payload tokens")
def test_event_journal_must_reject_nonfinite_json_numbers() -> None:
    """Mathematics: journal canonical bytes must reside in an admitted finite algebra."""

    with pytest.raises((TypeError, ValueError)):
        EventJournal().append("peer-audit", {"n": float("nan")})


@pytest.mark.xfail(strict=True, reason="To Do: admit register-bit and trace-byte budgets")
def test_instruction_step_budget_alone_must_bound_integer_growth() -> None:
    """Mathematics: 18 transition steps should refuse uncontrolled superlinear bit growth."""

    program = Program((
        Instruction(Op.SET, ("a", 3)),
        Instruction(Op.MUL, ("a", "a", "a")),
        Instruction(Op.BRANCH, ("a", 1)),
    ))
    result = ReferenceInterpreter(program).run(max_steps=18)
    assert result.state.registers["a"].bit_length() <= 64
