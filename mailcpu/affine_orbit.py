"""Exact logarithmic navigation for the provably affine MailCPU loop fragment.

The proof decomposes one program into affine prefix P, repeated affine body B,
and affine suffix S. A BRANCH counter is admitted only when its body update is
c' = c + delta with delta invariant under B. The exact first zero of c
determines the number of loop iterations. This is deliberately separate from
empirical recurrence inference: no learned law authorizes a leap.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from .model import Instruction, Op, Program

_AFFINE = frozenset((Op.SET, Op.COPY, Op.ADD))


class AffineOrbitRefused(ValueError):
    """A program or requested calculation is outside the certified affine fragment."""


@dataclass(frozen=True)
class AffineLeapResult:
    """A checked terminal orbit, proven divergence, or explained refusal."""

    verdict: str
    reason: str = ""
    iterations: int | None = None
    registers: tuple[tuple[str, int], ...] = ()
    steps: int | None = None
    pc: int | None = None
    counter_initial: int | None = None
    counter_delta: int | None = None

    def register_map(self) -> dict[str, int]:
        """Mathematics: reconstruct the final finite register map without aliasing."""

        return dict(self.registers)


def _names_of(instructions: Sequence[Instruction]) -> set[str]:
    """Mathematics: enumerate every register read or written by the affine orbit."""

    names: set[str] = set()
    for instruction in instructions:
        args = instruction.args
        if instruction.op is Op.SET:
            names.add(args[0])
        elif instruction.op in (Op.COPY, Op.ADD):
            names.update(args)
        elif instruction.op is Op.BRANCH:
            names.add(args[0])
    return names


def _symbolic(instructions: Sequence[Instruction], names: tuple[str, ...]) -> list[list[int]]:
    """Mathematics: compose each assignment as one integer homogeneous affine matrix."""

    indices = {name: index for index, name in enumerate(names)}
    count = len(names)
    rows = [
        [1 if i == j else 0 for j in range(count + 1)]
        for i in range(count)
    ]
    for instruction in instructions:
        if instruction.op not in _AFFINE:
            raise AffineOrbitRefused(
                f"{instruction.op.value} is outside the SET/COPY/ADD fragment"
            )
        args = instruction.args
        if instruction.op is Op.SET:
            row = [0] * count + [args[1]]
        elif instruction.op is Op.COPY:
            row = list(rows[indices[args[1]]])
        else:
            row = [
                left + right
                for left, right in zip(rows[indices[args[1]]], rows[indices[args[2]]])
            ]
        rows[indices[args[0]]] = row
    return rows + [[0] * count + [1]]


def _matrix_multiply(
    left: list[list[int]], right: list[list[int]], *, max_bits: int
) -> list[list[int]]:
    """Mathematics: compute an exact integer matrix product with a prior bit-cost bound."""

    width = len(left)
    bound_a = max((abs(value).bit_length() for row in left for value in row), default=0)
    bound_b = max((abs(value).bit_length() for row in right for value in row), default=0)
    # Every output is the sum of width products. Reject before allocating a
    # potentially unbounded multiplication, even if cancellation could save it.
    predicted = bound_a + bound_b + (width - 1).bit_length()
    if predicted > max_bits:
        raise AffineOrbitRefused(
            f"matrix multiplication exceeds {max_bits}-bit coefficient admission"
        )
    columns = list(zip(*right))
    return [
        [sum(x * y for x, y in zip(row, column)) for column in columns]
        for row in left
    ]


def _matrix_power(matrix: list[list[int]], exponent: int, *, max_bits: int) -> list[list[int]]:
    """Mathematics: realize B^n with O(log n) exact bounded matrix products."""

    size = len(matrix)
    result = [[int(i == j) for j in range(size)] for i in range(size)]
    base = matrix
    while exponent:
        if exponent & 1:
            result = _matrix_multiply(result, base, max_bits=max_bits)
        exponent >>= 1
        if exponent:
            base = _matrix_multiply(base, base, max_bits=max_bits)
    return result


def _apply(matrix: list[list[int]], state: list[int], *, max_bits: int) -> list[int]:
    """Mathematics: apply one affine map with bounded exact integer arithmetic."""

    if not state:
        raise AffineOrbitRefused("an affine state must contain a homogeneous coordinate")
    upper = max((abs(value).bit_length() for value in state), default=0)
    matrix_upper = max((abs(value).bit_length() for row in matrix for value in row), default=0)
    if upper + matrix_upper + (len(state) - 1).bit_length() > max_bits:
        raise AffineOrbitRefused("affine state exceeds the configured integer-bit admission")
    return [sum(x * y for x, y in zip(row, state)) for row in matrix]


def leap_affine_loop(
    program: Program,
    initial_registers: Mapping[str, int] | None = None,
    *,
    max_registers: int = 32,
    max_bits: int = 65536,
) -> AffineLeapResult:
    """Mathematics: certify S(B^n(P(x))) or nontermination for one pure-counter loop.

    LEAP guarantees exact final registers, program counter, and semantic step
    count, but does not allocate the omitted interpreter trace. DIVERGES is
    a proof for the admitted pure-counter fragment. REFUSED gives no claim.
    The bit admission governs constructed numbers, not CPU execution time.
    """

    try:
        if not isinstance(program, Program):
            raise AffineOrbitRefused("requires a validated Program")
        if not isinstance(max_registers, int) or isinstance(max_registers, bool) or max_registers < 1:
            raise AffineOrbitRefused("max_registers must be a positive integer")
        if not isinstance(max_bits, int) or isinstance(max_bits, bool) or max_bits < 4:
            raise AffineOrbitRefused("max_bits must be an integer of at least four")
        if initial_registers is None:
            initial_registers = {}
        if not isinstance(initial_registers, Mapping) or any(
            not isinstance(name, str) or not name
            or not isinstance(value, int) or isinstance(value, bool)
            for name, value in initial_registers.items()
        ):
            raise AffineOrbitRefused("initial register valuation must map names to integers")
        if any(abs(value).bit_length() > max_bits for value in initial_registers.values()):
            raise AffineOrbitRefused("initial state exceeds integer-bit admission")
        ins = program.instructions
        branches = [pc for pc, instruction in enumerate(ins) if instruction.op is Op.BRANCH]
        if len(branches) != 1:
            raise AffineOrbitRefused(f"expected one BRANCH, found {len(branches)}")
        end = branches[0]
        start = ins[end].args[1]
        if start > end:
            raise AffineOrbitRefused("forward branch is not an orbit loop")
        prefix, body, suffix = ins[:start], ins[start:end], ins[end + 1:]
        if not suffix or suffix[-1].op is not Op.HALT:
            raise AffineOrbitRefused("loop must be followed by HALT")
        names = tuple(sorted(_names_of(ins) | set(initial_registers)))
        if len(names) > max_registers:
            raise AffineOrbitRefused("register dimension exceeds admission")
        prefix_matrix = _symbolic(prefix, names)
        body_matrix = _symbolic(body, names)
        suffix_matrix = _symbolic(suffix[:-1], names)
        homogeneous = len(names)
        vector = [initial_registers.get(name, 0) for name in names] + [1]
        after_prefix = _apply(prefix_matrix, vector, max_bits=max_bits)
        counter_index = names.index(ins[end].args[0])
        counter_initial = after_prefix[counter_index]
        counter_row = body_matrix[counter_index]
        invariants = {
            index for index in range(homogeneous)
            if body_matrix[index] == [int(column == index) for column in range(homogeneous + 1)]
        }
        if counter_row[counter_index] != 1 or any(
            counter_row[index] != 0
            for index in range(homogeneous)
            if index != counter_index and index not in invariants
        ):
            raise AffineOrbitRefused("branch register is not a pure counter")
        delta = counter_row[homogeneous] + sum(
            counter_row[index] * after_prefix[index]
            for index in invariants if index != counter_index
        )
        if delta == 0:
            raise AffineOrbitRefused("counter increment is zero; first exit requires a separate proof")
        quotient, remainder = divmod(-counter_initial, delta)
        if remainder != 0 or quotient < 1:
            return AffineLeapResult(
                "DIVERGES", "the counter never reaches zero after a positive body iteration",
                counter_initial=counter_initial, counter_delta=delta
            )
        final_vector = _apply(
            suffix_matrix,
            _apply(_matrix_power(body_matrix, quotient, max_bits=max_bits), after_prefix, max_bits=max_bits),
            max_bits=max_bits,
        )
        return AffineLeapResult(
            "LEAP", iterations=quotient,
            registers=tuple((name, final_vector[i]) for i, name in enumerate(names)),
            steps=len(prefix) + quotient * (len(body) + 1) + len(suffix),
            pc=end + len(suffix),
            counter_initial=counter_initial,
            counter_delta=delta,
        )
    except AffineOrbitRefused as refusal:
        return AffineLeapResult("REFUSED", str(refusal))
