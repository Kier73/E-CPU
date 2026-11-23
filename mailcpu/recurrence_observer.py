"""Observed integer/rational recurrence inference with explicitly finite-window evidence.

Berlekamp–Massey over Q produces a minimal linear recurrence fitting the
provided sequence. Only its observed equations are verified: finite samples
never authorize future states without an independent structural proof.
Companion-matrix and polynomial-reduction nth-term evaluators provide
independent computational cross-checks of the conditional recurrence.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from typing import Sequence

Scalar = int | Fraction


class RecurrenceObservationError(ValueError):
    """A recurrence observation or arithmetic request violates its exact domain."""


@dataclass(frozen=True)
class RecurrenceWindow:
    """A finite-window observation verdict, not a claim about unseen future terms."""

    verdict: str
    samples: tuple[Fraction, ...]
    coefficients: tuple[Fraction, ...]
    verified_equations: int
    margin: int
    reason: str = ""

    @property
    def order(self) -> int:
        """Mathematics: recurrence order is the coefficient-vector length."""

        return len(self.coefficients)


def _exact(value: Scalar) -> Fraction:
    """Mathematics: embed exactly representable integers and rationals in Q."""

    if isinstance(value, bool) or not isinstance(value, (int, Fraction)):
        raise RecurrenceObservationError("samples and coefficients must be exact rationals")
    return Fraction(value)


def _finite(samples: Sequence[Scalar]) -> tuple[Fraction, ...]:
    """Mathematics: freeze finite observed values as a canonical rational tuple."""

    if not isinstance(samples, (tuple, list)):
        raise RecurrenceObservationError("samples must be a finite sequence")
    return tuple(_exact(value) for value in samples)


def _berlekamp_massey(samples: tuple[Fraction, ...]) -> tuple[tuple[Fraction, ...], int]:
    """Mathematics: solve the shortest linear recurrence of the observed prefix over Q."""

    coefficients = [Fraction(1)]
    prior = [Fraction(1)]
    order, since_update, last_discrepancy = 0, 1, Fraction(1)
    for n in range(len(samples)):
        if len(coefficients) < order + 1:
            coefficients += [Fraction(0)] * (order + 1 - len(coefficients))
        discrepancy = sum(
            coefficients[i] * samples[n - i] for i in range(order + 1)
        )
        if not discrepancy:
            since_update += 1
            continue
        ratio = discrepancy / last_discrepancy
        saved = list(coefficients)
        if len(coefficients) < len(prior) + since_update:
            coefficients += [Fraction(0)] * (len(prior) + since_update - len(coefficients))
        for i, value in enumerate(prior):
            coefficients[i + since_update] -= ratio * value
        if 2 * order <= n:
            order, prior, last_discrepancy, since_update = n + 1 - order, saved, discrepancy, 1
        else:
            since_update += 1
    coefficients += [Fraction(0)] * (order + 1 - len(coefficients))
    return tuple(coefficients[:order + 1]), order


def infer_recurrence_window(
    samples: Sequence[Scalar], *, margin: int = 3
) -> RecurrenceWindow:
    """Mathematics: verify all available equations and require N >= 2L + margin.

    A WINDOW_VERIFIED label describes ONLY the supplied prefix. It is not a
    proof that the recurrence holds at the next term. Use an independently
    proved transition map, such as an affine orbit, to establish that.
    """

    values = _finite(samples)
    if not isinstance(margin, int) or isinstance(margin, bool) or margin < 1:
        raise RecurrenceObservationError("margin must be a positive integer")
    length = len(values)
    if not values:
        return RecurrenceWindow("UNRESOLVED", values, (), 0, margin, "no observations")
    if all(value == 0 for value in values):
        verdict = "WINDOW_VERIFIED" if length >= margin else "UNRESOLVED"
        return RecurrenceWindow(verdict, values, (), length, margin,
                                "" if verdict == "WINDOW_VERIFIED" else "insufficient zero samples")
    polynomial, order = _berlekamp_massey(values)
    coefficients = tuple(-polynomial[i] for i in range(1, order + 1))
    verified = 0
    for index in range(order, length):
        observed = values[index]
        predicted = sum(
            coefficients[i - 1] * values[index - i] for i in range(1, order + 1)
        )
        if observed != predicted:
            return RecurrenceWindow("UNRESOLVED", values, coefficients, verified, margin,
                                    f"recurrence fails at observed index {index}")
        verified += 1
    if length < 2 * order + margin:
        return RecurrenceWindow(
            "UNRESOLVED", values, coefficients, verified, margin,
            f"order {order} requires {2 * order + margin} observations; have {length}",
        )
    return RecurrenceWindow("WINDOW_VERIFIED", values, coefficients, verified, margin)


def _bit_cost(value: Fraction) -> int:
    """Mathematics: bound the binary representation of both rational numerator and denominator."""

    return max(value.numerator.bit_length(), value.denominator.bit_length())


def _checked(value: Fraction, max_bits: int) -> Fraction:
    """Mathematics: admit exact rational arithmetic only within a stated bit resource budget."""

    if _bit_cost(value) > max_bits:
        raise RecurrenceObservationError(f"recurrence arithmetic exceeds {max_bits}-bit admission")
    return value


def _checked_mul(
    left: list[list[Fraction]], right: list[list[Fraction]], max_bits: int
) -> list[list[Fraction]]:
    """Mathematics: multiply rational matrices with per-product and per-sum bit admission."""

    columns = list(zip(*right))
    result: list[list[Fraction]] = []
    for row in left:
        values: list[Fraction] = []
        for column in columns:
            total = Fraction(0)
            for a, b in zip(row, column):
                if _bit_cost(a) + _bit_cost(b) > max_bits:
                    raise RecurrenceObservationError("rational multiplication exceeds bit admission")
                total = _checked(total + _checked(a * b, max_bits), max_bits)
            values.append(total)
        result.append(values)
    return result


def _nth_inputs(
    coefficients: Sequence[Scalar], initial: Sequence[Scalar], index: int, max_bits: int
) -> tuple[tuple[Fraction, ...], tuple[Fraction, ...]]:
    """Mathematics: admit exact recurrence parameters, nonnegative target and finite cost."""

    rec, start = _finite(coefficients), _finite(initial)
    if len(rec) != len(start):
        raise RecurrenceObservationError("initial vector must match recurrence order")
    if not isinstance(index, int) or isinstance(index, bool) or index < 0:
        raise RecurrenceObservationError("target index must be a nonnegative integer")
    if not isinstance(max_bits, int) or isinstance(max_bits, bool) or max_bits < 4:
        raise RecurrenceObservationError("max_bits must be an integer of at least four")
    if any(_bit_cost(value) > max_bits for value in rec + start):
        raise RecurrenceObservationError("initial recurrence values exceed bit admission")
    return rec, start


def nth_recurrence_matrix(
    coefficients: Sequence[Scalar],
    initial: Sequence[Scalar],
    index: int,
    *,
    max_bits: int = 65536,
) -> Fraction:
    """Mathematics: evaluate a conditional recurrence through O(log index) companion powers."""

    rec, start = _nth_inputs(coefficients, initial, index, max_bits)
    order = len(rec)
    if not order:
        return Fraction(0)
    base = [[Fraction(0) for _ in range(order)] for _ in range(order)]
    for i in range(order - 1):
        base[i][i + 1] = Fraction(1)
    for i, value in enumerate(rec, 1):
        base[order - 1][order - i] = value
    power = [[Fraction(int(i == j)) for j in range(order)] for i in range(order)]
    exponent = index
    while exponent:
        if exponent & 1:
            power = _checked_mul(power, base, max_bits)
        exponent >>= 1
        if exponent:
            base = _checked_mul(base, base, max_bits)
    total = Fraction(0)
    for term, coefficient in zip(power[0], start):
        if _bit_cost(term) + _bit_cost(coefficient) > max_bits:
            raise RecurrenceObservationError("result multiplication exceeds bit admission")
        total = _checked(total + _checked(term * coefficient, max_bits), max_bits)
    return total


def _reduce_polynomial(
    polynomial: list[Fraction], coefficients: tuple[Fraction, ...], max_bits: int
) -> list[Fraction]:
    """Mathematics: reduce x^k modulo x^L - c_1*x^(L-1) - ... - c_L."""

    order = len(coefficients)
    result = list(polynomial)
    for k in range(len(result) - 1, order - 1, -1):
        lead = result[k]
        if lead:
            for i in range(1, order + 1):
                if _bit_cost(lead) + _bit_cost(coefficients[i - 1]) > max_bits:
                    raise RecurrenceObservationError("polynomial multiplication exceeds bit admission")
                result[k - i] = _checked(
                    result[k - i] + _checked(lead * coefficients[i - 1], max_bits), max_bits
                )
        result[k] = Fraction(0)
    return (result[:order] + [Fraction(0)] * order)[:order]


def _polynomial_multiply(
    left: list[Fraction], right: list[Fraction],
    coefficients: tuple[Fraction, ...], max_bits: int,
) -> list[Fraction]:
    """Mathematics: multiply two polynomials and project into the characteristic quotient ring."""

    order = len(coefficients)
    out = [Fraction(0)] * (2 * order - 1)
    for i, left_value in enumerate(left):
        if left_value:
            for j, right_value in enumerate(right):
                if right_value:
                    if _bit_cost(left_value) + _bit_cost(right_value) > max_bits:
                        raise RecurrenceObservationError("polynomial product exceeds bit admission")
                    out[i + j] = _checked(
                        out[i + j] + _checked(left_value * right_value, max_bits), max_bits
                    )
    return _reduce_polynomial(out, coefficients, max_bits)


def nth_recurrence_polynomial(
    coefficients: Sequence[Scalar],
    initial: Sequence[Scalar],
    index: int,
    *,
    max_bits: int = 65536,
) -> Fraction:
    """Mathematics: evaluate a conditional recurrence by Kitamasa-style x^n reduction."""

    rec, start = _nth_inputs(coefficients, initial, index, max_bits)
    order = len(rec)
    if not order:
        return Fraction(0)
    result = _reduce_polynomial([Fraction(1)], rec, max_bits)
    base = _reduce_polynomial([Fraction(0), Fraction(1)], rec, max_bits)
    exponent = index
    while exponent:
        if exponent & 1:
            result = _polynomial_multiply(result, base, rec, max_bits)
        exponent >>= 1
        if exponent:
            base = _polynomial_multiply(base, base, rec, max_bits)
    total = Fraction(0)
    for value, first in zip(result, start):
        if _bit_cost(value) + _bit_cost(first) > max_bits:
            raise RecurrenceObservationError("result product exceeds bit admission")
        total = _checked(total + _checked(value * first, max_bits), max_bits)
    return total
