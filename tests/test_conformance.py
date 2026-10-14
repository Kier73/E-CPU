from __future__ import annotations

import pytest

from mailcpu import QueueInterpreter, ReferenceInterpreter, RunStatus, canonical_result
from mailcpu.interpreter import QueueBackend
from mailcpu.model import Instruction, Op, Program
from mailcpu.transport import InMemoryTransport
from mailcpu.programs import (
    addition_program,
    branch_program,
    countdown_program,
    random_program,
    wait_send_program,
)


def assert_equivalent(
    program: Program,
    initial_registers: dict[str, int] | None = None,
    inputs: dict[str, list[int]] | None = None,
    max_steps: int = 10_000,
) -> None:
    """Mathematics: assert observational equivalence `π(T_ref^k(s)) = π(T_queue^k(s))` for the bounded run."""

    reference = ReferenceInterpreter(program).run(initial_registers, inputs, max_steps)
    queue = QueueInterpreter(program).run(initial_registers, inputs, max_steps)
    assert canonical_result(queue) == canonical_result(reference)


def test_addition_and_halt() -> None:
    """Mathematics: verify the integer identity `1 + 1 = 2` and terminal HALT semantics."""

    result = ReferenceInterpreter(addition_program(1, 1)).run()
    assert result.status is RunStatus.HALTED
    assert result.state.registers["result"] == 2
    assert_equivalent(addition_program(1, 1))


@pytest.mark.parametrize("condition, expected", [(1, 1), (0, 0)])
def test_branch_taken_and_not_taken(condition: int, expected: int) -> None:
    """Mathematics: verify the predicate `condition ≠ 0` selects the taken branch and `condition = 0` falls through."""

    program = branch_program(condition)
    result = ReferenceInterpreter(program).run()
    assert result.state.registers["result"] == expected
    assert_equivalent(program)


def test_countdown_loop() -> None:
    """Mathematics: verify the loop invariant `0 ≤ n ≤ start` and termination at the fixed point `n = 0`."""

    program = countdown_program(5)
    result = ReferenceInterpreter(program).run()
    assert result.status is RunStatus.HALTED
    assert result.state.registers["n"] == 0
    assert_equivalent(program)


def test_wait_send_and_blocking() -> None:
    """Mathematics: verify `WAIT` is blocking on empty input and realizes `out = in` on one token."""

    program = wait_send_program()
    blocked_reference = ReferenceInterpreter(program).run()
    blocked_queue = QueueInterpreter(program).run()
    assert blocked_reference.status is RunStatus.BLOCKED
    assert canonical_result(blocked_queue) == canonical_result(blocked_reference)

    assert_equivalent(program, inputs={"inbox": [42]})
    result = ReferenceInterpreter(program).run(inputs={"inbox": [42]})
    assert result.outputs == (("outbox", 42),)


def test_differential_random_program_corpus() -> None:
    """Mathematics: compare both implementations over a finite sampled corpus `P(seed, length)` with the same initial valuation."""

    initial = {"r0": 0, "r1": 1, "r2": -2, "r3": 3}
    for seed in range(100):
        assert_equivalent(random_program(seed, length=14), initial_registers=initial)


def test_step_budget_exhaustion_reports_step_limit_not_halt() -> None:
    """Mathematics: on an unbounded orbit, `T^{max_steps}(s)` satisfies `status = step_limit ∧ halted = false ∧ steps = max_steps`, so budget exhaustion is never reported as success."""

    program = Program(
        (
            Instruction(Op.SET, ("one", 1)),
            Instruction(Op.BRANCH, ("one", 1)),
        )
    )
    result = ReferenceInterpreter(program).run(max_steps=7)
    assert result.status is RunStatus.STEP_LIMIT
    assert result.state.halted is False
    assert result.state.steps == 7
    assert len(result.trace) == 7
    assert_equivalent(program, max_steps=7)


def test_queue_register_read_is_non_consuming() -> None:
    """Mathematics: `read_register` projects `Q_reg:name` with `list`, so the observed cell is never dequeued and repeated reads agree."""

    backend = QueueBackend(InMemoryTransport(), {"total": 41}, {})
    assert backend.read_register("total") == 41
    assert backend.read_register("total") == 41
    cells = backend.transport.list(QueueBackend.register_address("total"))
    assert len(cells) == 1
    assert cells[0].value == 41


def test_invalid_branch_target_is_exposed() -> None:
    """Mathematics: reject any static target outside the finite program domain `[0, n)`."""

    with pytest.raises(ValueError, match="outside"):
        Program(
            (
                Instruction(Op.BRANCH, ("flag", 2)),
                Instruction(Op.HALT),
            )
        )
