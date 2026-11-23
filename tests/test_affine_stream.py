"""Peer SEND oracle regressions: exact indexed observations from source-ground loops."""

from __future__ import annotations

from dataclasses import replace
import json
import random

import pytest

from mailcpu.affine_orbit import AffineOrbitRefused
from mailcpu.affine_stream import (
    AffineSendStream,
    StreamObservationReceipt,
    verify_stream_receipt,
)
from mailcpu.interpreter import QueueInterpreter, ReferenceInterpreter
from mailcpu.model import Instruction, Op, Program, RunStatus


def _s(reg: str, value: int) -> Instruction:
    """Mathematics: construct one exact constant assignment."""

    return Instruction(Op.SET, (reg, value))


def _peer_random_loop(rng: random.Random) -> Program:
    """Mathematics: reproduce the peer's heterogeneous SEND/affine-loop generator."""

    data = ["d0", "d1", "d2"]
    pool = data + ["c", "k"]
    delta = rng.choice([-1, -1, -2, -3, 1])
    n0 = rng.randint(1, 30)
    c0 = n0 * -delta if rng.random() < 0.8 else rng.randint(-40, 40)
    hostile = rng.random() < 0.3
    src = pool if hostile else data
    mailboxes = ["o0", "o1"]

    def send() -> Instruction:
        """Mathematics: choose one source register and one external output mailbox."""

        return Instruction(Op.SEND, (rng.choice(mailboxes), rng.choice(src)))

    prefix = [_s("c", c0), _s("k", delta)]
    prefix += [_s(d, rng.randint(-4, 4)) for d in data]
    for _ in range(rng.choice([0, 0, 1, 2])):
        prefix.insert(rng.randint(2, len(prefix)), send())
    body: list[Instruction] = []
    for _ in range(rng.randint(1, 5)):
        op = rng.choice(["SET", "COPY", "ADD", "ADD", "SEND"])
        dst = rng.choice(pool if hostile else data)
        if op == "SET":
            body.append(_s(dst, rng.randint(-3, 3)))
        elif op == "COPY":
            body.append(Instruction(Op.COPY, (dst, rng.choice(src))))
        elif op == "ADD":
            body.append(Instruction(Op.ADD, (dst, rng.choice(src), rng.choice(src))))
        else:
            body.append(send())
    body.append(Instruction(Op.ADD, ("c", "c", "k")))
    if rng.random() < 0.5:
        body.insert(rng.randint(0, len(body) - 1), send())
    suffix = [send() for _ in range(rng.choice([0, 0, 1, 2]))] + [Instruction(Op.HALT)]
    return Program(tuple(prefix + body + [Instruction(Op.BRANCH, ("c", len(prefix)))] + suffix))


def test_peer_3000_generated_streams_match_reference() -> None:
    """Mathematics: all admitted output coordinates agree with native SEND traces."""

    rng = random.Random(23)
    categories = {"FINITE": 0, "INFINITE": 0, "REFUSED": 0}
    for _ in range(3000):
        program = _peer_random_loop(rng)
        try:
            oracle = AffineSendStream(program)
        except AffineOrbitRefused:
            categories["REFUSED"] += 1
            continue
        if oracle.iterations is None:
            categories["INFINITE"] += 1
            observed = ReferenceInterpreter(program).run(max_steps=300)
            assert observed.status is RunStatus.STEP_LIMIT
            assert all(oracle.out(i) == value for i, value in enumerate(observed.outputs))
            if oracle.length() is not None:
                assert oracle.length() == len(observed.outputs)
        else:
            categories["FINITE"] += 1
            maximum = 12 + oracle.iterations * (len(program.instructions) + 1)
            observed = ReferenceInterpreter(program).run(max_steps=maximum)
            assert observed.status is RunStatus.HALTED
            assert oracle.length() == len(observed.outputs)
            assert all(oracle.out(i) == value for i, value in enumerate(observed.outputs))
            with pytest.raises(IndexError):
                oracle.out(len(observed.outputs))
    assert categories["FINITE"] > 2000
    assert categories["INFINITE"] > 200
    assert categories["REFUSED"] > 200


def test_stream_matches_queue_backend_for_multi_send_interleaved_updates() -> None:
    """Mathematics: SEND reads register state at its own instruction position."""

    program = Program((
        _s("x", 2), _s("c", 5), _s("k", -1),
        Instruction(Op.SEND, ("prefix", "x")),
        Instruction(Op.ADD, ("x", "x", "x")),
        Instruction(Op.SEND, ("first", "x")),
        Instruction(Op.ADD, ("x", "x", "x")),
        Instruction(Op.SEND, ("second", "x")),
        Instruction(Op.ADD, ("c", "c", "k")),
        Instruction(Op.BRANCH, ("c", 4)),
        Instruction(Op.SEND, ("suffix", "x")),
        Instruction(Op.HALT),
    ))
    oracle = AffineSendStream(program)
    ref = ReferenceInterpreter(program).run()
    queue = QueueInterpreter(program).run()
    assert ref.status is RunStatus.HALTED
    assert ref.outputs == queue.outputs
    assert oracle.termination == "HALTS"
    assert oracle.length() == len(ref.outputs) == 12
    assert tuple(oracle.out(i) for i in range(oracle.length())) == ref.outputs
    assert oracle.out(0) == ("prefix", 2)
    assert oracle.out(1) == ("first", 4)
    assert oracle.out(2) == ("second", 8)
    assert oracle.out(11) == ("suffix", 2 * 4**5)


def test_distant_early_stream_observation_never_materializes_final_orbit() -> None:
    """Mathematics: prefix and bounded-index reads do not calculate a huge final Fibonacci."""

    billion = 10**9
    program = Program((
        _s("a", 0), _s("b", 1), _s("counter", billion), _s("k", -1),
        Instruction(Op.SEND, ("prefix", "b")),
        Instruction(Op.ADD, ("t", "a", "b")),
        Instruction(Op.COPY, ("a", "b")),
        Instruction(Op.COPY, ("b", "t")),
        Instruction(Op.SEND, ("fib", "a")),
        Instruction(Op.ADD, ("counter", "counter", "k")),
        Instruction(Op.BRANCH, ("counter", 5)),
        Instruction(Op.HALT),
    ))
    oracle = AffineSendStream(program, max_bits=1024)
    assert oracle.length() == billion + 1
    assert oracle.out(0) == ("prefix", 1)
    assert oracle.out(1) == ("fib", 1)
    assert oracle.out(11) == ("fib", 89)
    # F(200) is exact and comfortably within budget; the far future F(1e9)
    # exceeds the admitted bit budget and never needs to be constructed.
    with pytest.raises(AffineOrbitRefused, match="bit"):
        oracle.out(billion)


def test_nonterminating_orbit_has_unbounded_selectively_addressed_stream() -> None:
    """Mathematics: output exists for every finite index even if HALT is unreachable."""

    program = Program((
        _s("x", 1), _s("c", 7), _s("k", -2),
        Instruction(Op.ADD, ("x", "x", "x")),
        Instruction(Op.SEND, ("powers", "x")),
        Instruction(Op.ADD, ("c", "c", "k")),
        Instruction(Op.BRANCH, ("c", 3)),
        Instruction(Op.HALT),
    ))
    oracle = AffineSendStream(program)
    assert oracle.termination == "DIVERGES"
    assert oracle.length() is None
    assert oracle.out(100) == ("powers", 2**101)
    assert oracle.out(1000) == ("powers", 2**1001)


def test_zero_step_counter_is_decidable_after_first_body_pass() -> None:
    """Mathematics: pure zero counter exits after one iteration, nonzero stays forever."""

    def program(counter: int) -> Program:
        """Mathematics: form a counter-preserving SEND loop."""

        return Program((
            _s("c", counter), _s("x", 9), Instruction(Op.SEND, ("stream", "x")),
            Instruction(Op.BRANCH, ("c", 2)), Instruction(Op.HALT),
        ))

    exiting = AffineSendStream(program(0))
    assert exiting.iterations == 1 and exiting.length() == 1
    assert exiting.out(0) == ("stream", 9)
    repeating = AffineSendStream(program(1))
    assert repeating.iterations is None and repeating.length() is None
    assert repeating.out(120) == ("stream", 9)


def test_infinite_program_without_loop_emissions_has_finite_observation_log() -> None:
    """Mathematics: nonterminating execution need not emit an infinite stream."""

    program = Program((
        _s("x", 3), _s("c", 1),
        Instruction(Op.SEND, ("once", "x")),
        Instruction(Op.BRANCH, ("c", 3)), Instruction(Op.HALT),
    ))
    oracle = AffineSendStream(program)
    assert oracle.termination == "DIVERGES"
    assert oracle.length() == 1
    assert oracle.out(0) == ("once", 3)
    with pytest.raises(IndexError):
        oracle.out(1)


def test_stream_receipts_require_original_program_and_initial_state() -> None:
    """Mathematics: independently reconstruct one output instead of trusting received bytes."""

    program = Program((
        _s("c", 4), _s("k", -1),
        Instruction(Op.ADD, ("value", "value", "k")),
        Instruction(Op.SEND, ("m", "value")),
        Instruction(Op.ADD, ("c", "c", "k")),
        Instruction(Op.BRANCH, ("c", 2)), Instruction(Op.HALT),
    ))
    oracle = AffineSendStream(program, {"value": 17})
    receipt = oracle.issue_receipt(3)
    assert oracle.observe(3).value == 13
    assert verify_stream_receipt(receipt, program, {"value": 17})
    restored = StreamObservationReceipt.from_snapshot(
        json.loads(json.dumps(receipt.snapshot()))
    )
    assert restored == receipt
    assert not verify_stream_receipt(restored, program, {"value": 18})
    assert not verify_stream_receipt(
        replace(restored, value=99), program, {"value": 17}
    )
    payload = restored.snapshot()
    payload["value"] = "0x000d"
    with pytest.raises(AffineOrbitRefused, match="noncanonical"):
        StreamObservationReceipt.from_snapshot(payload)
    payload = restored.snapshot()
    payload["mailbox"] = "wrong"
    with pytest.raises(AffineOrbitRefused, match="digest"):
        StreamObservationReceipt.from_snapshot(payload)


@pytest.mark.parametrize("opcode", (Op.WAIT, Op.MUL, Op.SYSCALL, Op.COMPARE))
def test_stream_refuses_operations_outside_pure_output_fragment(opcode: Op) -> None:
    """Mathematics: input consumption, nonlinear effects and trap actions need distinct laws."""

    instruction = {
        Op.WAIT: Instruction(Op.WAIT, ("inbox", "x")),
        Op.MUL: Instruction(Op.MUL, ("x", "x", "x")),
        Op.SYSCALL: Instruction(Op.SYSCALL, ("x", "noop")),
        Op.COMPARE: Instruction(Op.COMPARE, ("x", "x", "x")),
    }[opcode]
    program = Program((
        _s("c", 2), _s("k", -1), instruction,
        Instruction(Op.ADD, ("c", "c", "k")),
        Instruction(Op.BRANCH, ("c", 2)),
        Instruction(Op.HALT),
    ))
    with pytest.raises(AffineOrbitRefused):
        AffineSendStream(program)


def test_stream_applies_resource_admission_per_requested_output() -> None:
    """Mathematics: bit growth is bounded only when a distant value is requested."""

    program = Program((
        _s("c", 1000), _s("k", -1), _s("x", 2),
        Instruction(Op.SEND, ("m", "x")),
        Instruction(Op.ADD, ("x", "x", "x")),
        Instruction(Op.ADD, ("c", "c", "k")),
        Instruction(Op.BRANCH, ("c", 3)), Instruction(Op.HALT),
    ))
    oracle = AffineSendStream(program, max_bits=64)
    assert oracle.out(0) == ("m", 2)
    assert oracle.out(10) == ("m", 2048)
    with pytest.raises(AffineOrbitRefused, match="bit"):
        oracle.out(999)
