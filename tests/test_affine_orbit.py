"""Independent interpreter comparisons for peer-derived exact affine orbit navigation."""

from __future__ import annotations

import random

from mailcpu.affine_orbit import leap_affine_loop
from mailcpu.interpreter import QueueInterpreter, ReferenceInterpreter
from mailcpu.model import Instruction, Op, Program, RunStatus


def _fib_program(n: int) -> Program:
    """Mathematics: materialize F_n as the orbit of the two-dimensional Fibonacci affine map."""

    return Program((
        Instruction(Op.SET, ("a", 0)),
        Instruction(Op.SET, ("b", 1)),
        Instruction(Op.SET, ("c", n)),
        Instruction(Op.SET, ("k", -1)),
        Instruction(Op.ADD, ("t", "a", "b")),
        Instruction(Op.COPY, ("a", "b")),
        Instruction(Op.COPY, ("b", "t")),
        Instruction(Op.ADD, ("c", "c", "k")),
        Instruction(Op.BRANCH, ("c", 4)),
        Instruction(Op.HALT),
    ))


def _random_loop(rng: random.Random) -> Program:
    """Mathematics: generate mixed affine assignments with optional counter mutations."""

    data = ("d0", "d1", "d2")
    delta = rng.choice((-3, -2, -1, -1, 1))
    starting = rng.randint(1, 40) * -delta if rng.random() < 0.8 else rng.randint(-50, 50)
    instructions = [
        Instruction(Op.SET, ("c", starting)), Instruction(Op.SET, ("k", delta))
    ]
    instructions.extend(Instruction(Op.SET, (name, rng.randint(-4, 4))) for name in data)
    start = len(instructions)
    hostile = rng.random() < 0.35
    pool = data + ("c", "k") if hostile else data
    for _ in range(rng.randint(1, 5)):
        dst = rng.choice(pool)
        action = rng.choice(("SET", "COPY", "ADD", "ADD"))
        if action == "SET":
            instructions.append(Instruction(Op.SET, (dst, rng.randint(-3, 3))))
        elif action == "COPY":
            instructions.append(Instruction(Op.COPY, (dst, rng.choice(pool))))
        else:
            instructions.append(Instruction(Op.ADD, (dst, rng.choice(pool), rng.choice(pool))))
    instructions.append(Instruction(Op.ADD, ("c", "c", "k")))
    instructions.append(Instruction(Op.BRANCH, ("c", start)))
    if rng.random() < 0.5:
        instructions.append(Instruction(Op.ADD, ("d0", "d1", "d2")))
    instructions.append(Instruction(Op.HALT))
    return Program(tuple(instructions))


def test_affine_fibonacci_matches_both_backends() -> None:
    """Mathematics: leap is equal to repeated transition application at four orbit lengths."""

    for n in (1, 2, 12, 100):
        program = _fib_program(n)
        leap = leap_affine_loop(program)
        assert leap.verdict == "LEAP"
        assert leap.iterations == n
        for backend in (ReferenceInterpreter, QueueInterpreter):
            result = backend(program).run(max_steps=leap.steps + 1)
            assert result.status is RunStatus.HALTED
            assert result.state.registers == leap.register_map()
            assert result.state.pc == leap.pc
            assert result.state.steps == leap.steps


def test_affine_randomized_independent_differential_corpus() -> None:
    """Mathematics: every admitted leap agrees with the ordinary interpreter state trace."""

    rng = random.Random(7)
    tallies = {"LEAP": 0, "DIVERGES": 0, "REFUSED": 0}
    for _ in range(400):
        program = _random_loop(rng)
        leap = leap_affine_loop(program)
        tallies[leap.verdict] += 1
        if leap.verdict == "LEAP":
            result = ReferenceInterpreter(program).run(max_steps=leap.steps + 1)
            assert result.status is RunStatus.HALTED
            assert result.state.registers == leap.register_map()
            assert result.state.steps == leap.steps
            assert result.state.pc == leap.pc
        elif leap.verdict == "DIVERGES":
            assert ReferenceInterpreter(program).run(max_steps=300).status is RunStatus.STEP_LIMIT
        else:
            assert leap.reason
    assert tallies["LEAP"] > 100
    assert tallies["DIVERGES"] > 20
    assert tallies["REFUSED"] > 20


def test_affine_algebraic_divergence_is_not_confused_with_refusal() -> None:
    """Mathematics: a counter 5-2n never reaches zero at positive integer n."""

    program = Program((
        Instruction(Op.SET, ("c", 5)),
        Instruction(Op.SET, ("k", -2)),
        Instruction(Op.ADD, ("c", "c", "k")),
        Instruction(Op.BRANCH, ("c", 2)),
        Instruction(Op.HALT),
    ))
    leap = leap_affine_loop(program)
    assert leap.verdict == "DIVERGES"
    assert leap.counter_initial == 5
    assert leap.counter_delta == -2


def test_affine_zero_increment_is_conservatively_refused() -> None:
    """Mathematics: a zero-step counter can exit on the first body pass; refuse ambiguous law."""

    program = Program((
        Instruction(Op.SET, ("c", 0)),
        Instruction(Op.SET, ("k", 0)),
        Instruction(Op.ADD, ("c", "c", "k")),
        Instruction(Op.BRANCH, ("c", 2)),
        Instruction(Op.HALT),
    ))
    assert leap_affine_loop(program).verdict == "REFUSED"
    assert ReferenceInterpreter(program).run().status is RunStatus.HALTED


def test_affine_refuses_nonaffine_or_data_driven_counter() -> None:
    """Mathematics: no symbolic leap is published for MUL or non-invariant counter changes."""

    multiplication = Program((
        Instruction(Op.SET, ("c", 2)),
        Instruction(Op.SET, ("k", -1)),
        Instruction(Op.MUL, ("c", "c", "c")),
        Instruction(Op.BRANCH, ("c", 2)),
        Instruction(Op.HALT),
    ))
    assert leap_affine_loop(multiplication).verdict == "REFUSED"

    noninvariant = Program((
        Instruction(Op.SET, ("c", 5)),
        Instruction(Op.SET, ("a", 1)),
        Instruction(Op.ADD, ("a", "a", "a")),
        Instruction(Op.ADD, ("c", "c", "a")),
        Instruction(Op.BRANCH, ("c", 2)),
        Instruction(Op.HALT),
    ))
    assert leap_affine_loop(noninvariant).verdict == "REFUSED"


def test_affine_resource_admission_blocks_exponential_bit_growth() -> None:
    """Mathematics: the cost gate refuses matrix growth before unbounded allocation."""

    program = Program((
        Instruction(Op.SET, ("a", 1)),
        Instruction(Op.SET, ("c", 300)),
        Instruction(Op.SET, ("k", -1)),
        Instruction(Op.ADD, ("a", "a", "a")),
        Instruction(Op.ADD, ("c", "c", "k")),
        Instruction(Op.BRANCH, ("c", 3)),
        Instruction(Op.HALT),
    ))
    refused = leap_affine_loop(program, max_bits=32)
    assert refused.verdict == "REFUSED"
    assert "bit" in refused.reason


def test_affine_large_identity_orbit_navigates_without_step_by_step_execution() -> None:
    """Mathematics: ten billion iterations have a compact exact proof coordinate."""

    n = 10**10
    program = Program((
        Instruction(Op.SET, ("c", n)),
        Instruction(Op.SET, ("k", -1)),
        Instruction(Op.SET, ("v", 7)),
        Instruction(Op.ADD, ("c", "c", "k")),
        Instruction(Op.BRANCH, ("c", 3)),
        Instruction(Op.HALT),
    ))
    result = leap_affine_loop(program, max_bits=256)
    assert result.verdict == "LEAP"
    assert result.iterations == n
    assert result.register_map()["c"] == 0
    assert result.register_map()["v"] == 7
    assert result.steps == 3 + 2 * n + 1
