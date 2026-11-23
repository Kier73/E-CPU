"""Peer-derived BM inference has bounded, finite-window evidence, never future authority."""

from __future__ import annotations

from fractions import Fraction
import math
import random

import pytest

from mailcpu.affine_orbit import leap_affine_loop
from mailcpu.interpreter import ReferenceInterpreter
from mailcpu.model import Instruction, Op, Program
from mailcpu.recurrence_observer import (
    RecurrenceObservationError,
    infer_recurrence_window,
    nth_recurrence_matrix,
    nth_recurrence_polynomial,
)


def _naive(coefficients: list[int], initial: list[int], length: int) -> list[int]:
    """Mathematics: independently enumerate s_n=sum(c_i*s_(n-i)) for small n."""

    samples = list(initial)
    while len(samples) < length:
        samples.append(sum(
            coefficient * samples[-index]
            for index, coefficient in enumerate(coefficients, 1)
        ))
    return samples[:length]


def _fib_program(n: int) -> Program:
    """Mathematics: derive a Fibonacci orbit from native SET/COPY/ADD transitions."""

    return Program((
        Instruction(Op.SET, ("a", 0)),
        Instruction(Op.SET, ("b", 1)),
        Instruction(Op.SET, ("c", n)),
        Instruction(Op.SET, ("k", -1)),
        Instruction(Op.ADD, ("tmp", "a", "b")),
        Instruction(Op.COPY, ("a", "b")),
        Instruction(Op.COPY, ("b", "tmp")),
        Instruction(Op.ADD, ("c", "c", "k")),
        Instruction(Op.BRANCH, ("c", 4)),
        Instruction(Op.HALT),
    ))


def test_fibonacci_observation_has_exact_verified_window_but_no_future_proof() -> None:
    """Mathematics: the inferred second-order law matches 23 independent observations."""

    fib = _naive([1, 1], [0, 1], 24)
    result = infer_recurrence_window(fib)
    assert result.verdict == "WINDOW_VERIFIED"
    assert result.order == 2
    assert result.coefficients == (1, 1)
    assert result.verified_equations == 22
    assert nth_recurrence_matrix(result.coefficients, fib[:2], 40) == _naive([1, 1], [0, 1], 41)[40]
    assert nth_recurrence_polynomial(result.coefficients, fib[:2], 40) == _naive([1, 1], [0, 1], 41)[40]


def test_adversarial_tail_breaks_finite_observation_extrapolation() -> None:
    """Mathematics: a perfectly fitting Fibonacci prefix need not constrain its next sample."""

    fib = _naive([1, 1], [0, 1], 24)
    observed = infer_recurrence_window(fib)
    predicted = nth_recurrence_matrix(observed.coefficients, fib[:2], 24)
    assert predicted == fib[-1] + fib[-2]
    adversarial = infer_recurrence_window(fib + [predicted + 1])
    assert adversarial.verdict == "UNRESOLVED"


def test_random_exact_recurrences_crosscheck_two_independent_lifters() -> None:
    """Mathematics: both companion matrix and quotient-ring algorithms match direct recurrence."""

    rng = random.Random(11)
    for _ in range(120):
        order = rng.randint(1, 5)
        rec = [rng.randint(-2, 2) for _ in range(order)]
        rec[-1] = rec[-1] or 1
        initial = [rng.randint(-3, 3) for _ in range(order)]
        values = _naive(rec, initial, 50)
        observed = infer_recurrence_window(values[:2 * order + 7])
        assert observed.verdict == "WINDOW_VERIFIED"
        start = observed.samples[:observed.order]
        for target in (5, 19, 49):
            assert nth_recurrence_matrix(observed.coefficients, start, target) == values[target]
            assert nth_recurrence_polynomial(observed.coefficients, start, target) == values[target]


def test_unstructured_sequences_remain_unresolved() -> None:
    """Mathematics: the finite-window margin refuses high-degree interpolation of noise."""

    rng = random.Random(17)
    noise = [rng.randint(-1000, 1000) for _ in range(30)]
    primes = [
        n for n in range(2, 220)
        if all(n % p for p in range(2, math.isqrt(n) + 1))
    ][:30]
    catalan = [math.comb(2 * n, n) // (n + 1) for n in range(30)]
    for data in (noise, primes, catalan, [math.factorial(i) for i in range(30)]):
        assert infer_recurrence_window(data).verdict == "UNRESOLVED"


def test_observed_fibonacci_and_static_program_proof_agree() -> None:
    """Mathematics: observed recurrence is independently corroborated by exact affine program structure."""

    program = _fib_program(60)
    # Observe 30 branch boundaries rather than asserting any unobserved recurrence.
    observed_run = ReferenceInterpreter(program).run(max_steps=4 + 5 * 30)
    samples = [dict(event.registers)["a"] for event in observed_run.trace if event.op == "BRANCH"]
    assert len(samples) == 30
    window = infer_recurrence_window(samples)
    assert window.verdict == "WINDOW_VERIFIED"
    assert window.coefficients == (1, 1)
    # Samples begin at the end of the first body iteration: index n-1.
    conditional = nth_recurrence_polynomial(window.coefficients, samples[:2], 59)
    static = leap_affine_loop(program)
    assert static.verdict == "LEAP"
    assert static.register_map()["a"] == conditional


def test_fractional_recurrence_has_exact_evidence_and_bounded_arithmetic() -> None:
    """Mathematics: Q is retained without float approximation and big rationals are refused."""

    coefficients = [Fraction(1, 2), Fraction(1, 2)]
    initial = [Fraction(1), Fraction(2)]
    samples = list(initial)
    for _ in range(20):
        samples.append(coefficients[0] * samples[-1] + coefficients[1] * samples[-2])
    window = infer_recurrence_window(samples)
    assert window.verdict == "WINDOW_VERIFIED"
    assert nth_recurrence_matrix(coefficients, initial, 20) == samples[20]
    assert nth_recurrence_polynomial(coefficients, initial, 20) == samples[20]
    with pytest.raises(RecurrenceObservationError, match="bit admission"):
        nth_recurrence_matrix([2], [1], 1000, max_bits=32)
    with pytest.raises(RecurrenceObservationError, match="bit admission"):
        nth_recurrence_polynomial([2], [1], 1000, max_bits=32)


@pytest.mark.parametrize("bad", (1.25, float("nan"), True, "3", None))
def test_inference_rejects_inexact_or_untyped_samples(bad: object) -> None:
    """Mathematics: observed data are finite exact rational values, never coerced floats."""

    with pytest.raises(RecurrenceObservationError, match="exact rationals"):
        infer_recurrence_window([1, bad])


def test_zero_sample_window_does_not_prove_future_zero() -> None:
    """Mathematics: an all-zero finite prefix gives only its local zero observation."""

    window = infer_recurrence_window([0] * 12)
    assert window.verdict == "WINDOW_VERIFIED"
    assert window.order == 0
    assert nth_recurrence_matrix([], [], 10) == 0
    assert nth_recurrence_polynomial([], [], 10) == 0
