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


def random_communication_program(seed: int, length: int = 16) -> Program:
    """Mathematics: sample bounded-backtrack SEND/WAIT/MUL programs over shared FIFO mailboxes."""

    if length < 6:
        raise ValueError("communication program length must be at least 6")
    rng = random.Random(seed)
    registers = ("r0", "r1", "r2")
    mailboxes = ("shared-0", "shared-1")
    instructions: list[Instruction] = [
        Instruction(Op.SET, ("one", 1)),
        Instruction(Op.SET, ("two", 2)),
        Instruction(Op.SET, ("r0", rng.randint(-3, 3))),
    ]
    for index in range(3, length - 1):
        choice = rng.randrange(9)
        destination = rng.choice(registers)
        if choice == 0:
            instructions.append(Instruction(Op.SET, (destination, rng.randint(-5, 5))))
        elif choice == 1:
            instructions.append(Instruction(Op.COPY, (destination, rng.choice(registers))))
        elif choice == 2:
            instructions.append(Instruction(Op.ADD, (destination, rng.choice(registers), "one")))
        elif choice == 3:
            # Multiplication by a pinned factor bounds bit growth under a step budget.
            instructions.append(Instruction(Op.MUL, (destination, rng.choice(registers), "two")))
        elif choice == 4:
            instructions.append(Instruction(Op.COMPARE, (destination, rng.choice(registers), "one")))
        elif choice == 5:
            instructions.append(
                Instruction(Op.BRANCH, (rng.choice(registers), rng.randrange(3, length)))
            )
        elif choice in (6, 7):
            instructions.append(Instruction(Op.SEND, (rng.choice(mailboxes), rng.choice(registers))))
        else:
            instructions.append(Instruction(Op.WAIT, (rng.choice(mailboxes), destination)))
    instructions.append(Instruction(Op.HALT))
    return Program(tuple(instructions))
