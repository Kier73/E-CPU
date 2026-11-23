"""Small independently verified nonlinear MailCPU lift: integer triangular polynomial dynamics.

The native loop contains MUL, so AffineSendStream must refuse it. Its selected
SEND nevertheless admits a finite exact Koopman feature closure that is
verified here in the integer polynomial ring, then navigated by M^n.
"""

from __future__ import annotations

from mailcpu.affine_orbit import AffineOrbitRefused, _apply, _matrix_power
from mailcpu.affine_stream import AffineSendStream
from mailcpu.interpreter import ReferenceInterpreter
from mailcpu.model import Instruction, Op, Program, RunStatus


def _add(left: dict[tuple[int, int], int], right: dict[tuple[int, int], int]) -> dict[tuple[int, int], int]:
    """Mathematics: exact coefficient-wise addition in Z[x,y]."""

    out = dict(left)
    for key, value in right.items():
        out[key] = out.get(key, 0) + value
        if out[key] == 0:
            del out[key]
    return out


def _mul(left: dict[tuple[int, int], int], right: dict[tuple[int, int], int]) -> dict[tuple[int, int], int]:
    """Mathematics: exact polynomial convolution without finite interpolation."""

    result: dict[tuple[int, int], int] = {}
    for (ax, ay), av in left.items():
        for (bx, by), bv in right.items():
            exponent = (ax + bx, ay + by)
            result[exponent] = result.get(exponent, 0) + av * bv
            if result[exponent] == 0:
                del result[exponent]
    return result


def _scale(polynomial: dict[tuple[int, int], int], coefficient: int) -> dict[tuple[int, int], int]:
    """Mathematics: scale a symbolic polynomial by an integer coefficient."""

    return {monomial: coefficient * value for monomial, value in polynomial.items() if coefficient * value}


# Features are [1, y, y*y, x]. Their pullbacks close exactly under
# T(x,y)=(x+y*y, y+1), a nonlinear update.
MATRIX = [
    [1, 0, 0, 0],
    [1, 1, 0, 0],
    [1, 2, 1, 0],
    [0, 0, 1, 1],
]


def _program(iterations: int) -> Program:
    """Mathematics: emit the updated nonlinear x coordinate at each loop iteration."""

    return Program((
        Instruction(Op.SET, ("x", 2)),
        Instruction(Op.SET, ("y", 3)),
        Instruction(Op.SET, ("counter", iterations)),
        Instruction(Op.SET, ("one", 1)),
        Instruction(Op.SET, ("minus_one", -1)),
        Instruction(Op.MUL, ("square", "y", "y")),
        Instruction(Op.ADD, ("x", "x", "square")),
        Instruction(Op.ADD, ("y", "y", "one")),
        Instruction(Op.SEND, ("nonlinear", "x")),
        Instruction(Op.ADD, ("counter", "counter", "minus_one")),
        Instruction(Op.BRANCH, ("counter", 5)),
        Instruction(Op.HALT),
    ))


def _lifted_x(iterations: int) -> int:
    """Mathematics: navigate selected nonlinear output through a four-dimensional exact lift."""

    phi_initial = [1, 3, 9, 2]
    phi_now = _apply(
        _matrix_power(MATRIX, iterations, max_bits=256),
        phi_initial,
        max_bits=256,
    )
    assert phi_now[2] == phi_now[1] ** 2
    return phi_now[3]


def test_nonlinear_lift_is_an_exact_polynomial_identity_for_all_integer_states() -> None:
    """Mathematics: verify phi(T(x,y))=M*phi(x,y) by comparing symbolic coefficients."""

    one = {(0, 0): 1}
    x = {(1, 0): 1}
    y = {(0, 1): 1}
    phi = [one, y, _mul(y, y), x]
    y_after = _add(y, one)
    x_after = _add(x, _mul(y, y))
    transformed = [one, y_after, _mul(y_after, y_after), x_after]
    for claimed_row, truth in zip(MATRIX, transformed):
        expected: dict[tuple[int, int], int] = {}
        for coefficient, observable in zip(claimed_row, phi):
            expected = _add(expected, _scale(observable, coefficient))
        assert expected == truth


def test_nonlinear_native_mul_and_send_match_lifted_index_outputs() -> None:
    """Mathematics: a native MUL loop matches nonlinear lifted SEND values exactly."""

    for n in (1, 2, 10, 30):
        program = _program(n)
        try:
            AffineSendStream(program)
        except AffineOrbitRefused:
            pass
        else:
            raise AssertionError("affine oracle must not interpret nonlinear MUL")
        run = ReferenceInterpreter(program).run(max_steps=8 * n + 12)
        assert run.status is RunStatus.HALTED
        assert len(run.outputs) == n
        for index, (mailbox, value) in enumerate(run.outputs):
            assert mailbox == "nonlinear"
            assert value == _lifted_x(index + 1)


def test_distant_nonlinear_output_matches_independent_closed_form() -> None:
    """Mathematics: exact 10^12-step selected output without executing earlier SENDs."""

    n = 10**12
    via_lift = _lifted_x(n)
    independent = 2 + 9 * n + 3 * n * (n - 1) + n * (n - 1) * (2 * n - 1) // 6
    assert via_lift == independent
    assert via_lift == 333333333335833333333339500000000002
