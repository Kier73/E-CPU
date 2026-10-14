"""Small deterministic programs and the bounded random corpus generator."""

from __future__ import annotations

import random

from .model import Instruction, Op, Program


def addition_program(left: int, right: int) -> Program:
    """Mathematics: construct a program whose final result satisfies `result = left + right`."""

    return Program(
        (
            Instruction(Op.SET, ("left", left)),
            Instruction(Op.SET, ("right", right)),
            Instruction(Op.ADD, ("result", "left", "right")),
            Instruction(Op.HALT),
        )
    )


def branch_program(condition: int) -> Program:
    """Mathematics: realize `result = 1` iff `condition ≠ 0`, otherwise `result = 0`, using the branch predicate."""

    return Program(
        (
            Instruction(Op.SET, ("condition", condition)),
            Instruction(Op.BRANCH, ("condition", 4)),
            Instruction(Op.SET, ("result", 0)),
            Instruction(Op.HALT),
            Instruction(Op.SET, ("result", 1)),
            Instruction(Op.HALT),
        )
    )


def countdown_program(start: int) -> Program:
    """Mathematics: for `start ≥ 0`, iterate `n := n - 1` while `sgn(n - 0) = 1`, then halt at `n = 0`."""

    if start < 0:
        raise ValueError("countdown start must be non-negative")
    return Program(
        (
            Instruction(Op.SET, ("n", start)),
            Instruction(Op.SET, ("one", 1)),
            Instruction(Op.SET, ("minus_one", -1)),
            Instruction(Op.SET, ("zero", 0)),
            Instruction(Op.COMPARE, ("positive", "n", "zero")),
            Instruction(Op.BRANCH, ("positive", 7)),
            Instruction(Op.HALT),
            Instruction(Op.ADD, ("n", "n", "minus_one")),
            Instruction(Op.BRANCH, ("one", 4)),
        )
    )


def wait_send_program() -> Program:
    """Mathematics: implement the input/output identity `out := in` when one input token exists."""

    return Program(
        (
            Instruction(Op.WAIT, ("inbox", "received")),
            Instruction(Op.SEND, ("outbox", "received")),
            Instruction(Op.HALT),
        )
    )


def random_program(seed: int, length: int = 12) -> Program:
    """Mathematics: sample a deterministic program from a finite product space, with only forward branches so termination is guaranteed."""

    if length < 2:
        raise ValueError("random program length must be at least 2")
    rng = random.Random(seed)
    registers = ("r0", "r1", "r2", "r3")
    instructions: list[Instruction] = []
    for index in range(length - 1):
        choice = rng.randrange(6)
        destination = rng.choice(registers)
        if choice == 0:
            instructions.append(Instruction(Op.SET, (destination, rng.randint(-5, 5))))
        elif choice == 1:
            instructions.append(Instruction(Op.COPY, (destination, rng.choice(registers))))
        elif choice == 2:
            instructions.append(
                Instruction(Op.ADD, (destination, rng.choice(registers), rng.choice(registers)))
            )
        elif choice == 3:
            instructions.append(
                Instruction(
                    Op.COMPARE,
                    (destination, rng.choice(registers), rng.choice(registers)),
                )
            )
        elif choice == 4:
            target = rng.randint(index + 1, length - 1)
            instructions.append(Instruction(Op.BRANCH, (rng.choice(registers), target)))
        else:
            instructions.append(Instruction(Op.SEND, ("random-out", rng.choice(registers))))
    instructions.append(Instruction(Op.HALT))
    return Program(tuple(instructions))
