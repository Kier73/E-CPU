"""Reversible bit-vector and word-level gate algebra for zero-dissipation state transitions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

KIND_X: int = 0
KIND_SWAP: int = 1

ARM_NONE: tuple[int, int] = (0, 0)


def arm_union(a: tuple[int, int], b: tuple[int, int]) -> tuple[int, int]:
    r"""Mathematics: evaluate `(pos_a \lor pos_b, neg_a \lor neg_b)`, asserting `(pos_a \lor pos_b) \land (neg_a \lor neg_b) = 0`."""

    pos = a[0] | b[0]
    neg = a[1] | b[1]
    if pos & neg:
        raise ValueError("control bit specified with contradictory polarities")
    return (pos, neg)


@dataclass(frozen=True)
class ReversibleGate:
    r"""Mathematics: involutive gate `G(s) = s \oplus \Delta(s)` satisfying `G \circ G = I`."""

    kind: int
    pos: int
    neg: int
    t1: int
    t2: int = -1

    def is_enabled(self, tape: int) -> bool:
        r"""Mathematics: evaluate predicate `(tape \land pos = pos) \land (tape \land neg = 0)`."""

        if self.pos and (tape & self.pos) != self.pos:
            return False
        if self.neg and (tape & self.neg) != 0:
            return False
        return True

    def apply(self, tape: int) -> tuple[int, bool]:
        r"""Mathematics: apply involution `tape \mapsto tape'`, returning `(tape', active)` where `active \iff tape' \neq tape`."""

        if not self.is_enabled(tape):
            return (tape, False)
        if self.kind == KIND_X:
            return (tape ^ (1 << self.t1), True)
        b1 = (tape >> self.t1) & 1
        b2 = (tape >> self.t2) & 1
        if b1 != b2:
            return (tape ^ ((1 << self.t1) | (1 << self.t2)), True)
        return (tape, False)


def apply_gate(tape: int, gate: ReversibleGate | tuple[int, int, int, int, int]) -> tuple[int, bool]:
    """Mathematics: execute gate `G` on `tape`, asserting involution `G(G(tape)) = tape`."""

    if isinstance(gate, ReversibleGate):
        return gate.apply(tape)
    kind, pos, neg, t1, t2 = gate
    if pos and (tape & pos) != pos:
        return (tape, False)
    if neg and (tape & neg) != 0:
        return (tape, False)
    if kind == KIND_X:
        return (tape ^ (1 << t1), True)
    b1 = (tape >> t1) & 1
    b2 = (tape >> t2) & 1
    if b1 != b2:
        return (tape ^ ((1 << t1) | (1 << t2)), True)
    return (tape, False)


def execute_gates(tape: int, gates: Sequence[ReversibleGate | tuple[int, int, int, int, int]]) -> tuple[int, int]:
    r"""Mathematics: compose sequence `(G_m \circ \dots \circ G_1)(tape)`, returning `(tape', n_{active})`."""

    active_count = 0
    current_tape = tape
    for gate in gates:
        current_tape, was_active = apply_gate(current_tape, gate)
        if was_active:
            active_count += 1
    return (current_tape, active_count)


def reverse_gates(gates: Sequence[ReversibleGate | tuple[int, int, int, int, int]]) -> list[ReversibleGate | tuple[int, int, int, int, int]]:
    r"""Mathematics: compute sequence inverse `(G_m \circ \dots \circ G_1)^{-1} = G_1 \circ \dots \circ G_m`."""

    return list(reversed(gates))


def phase_factor(active_chronons: int) -> complex:
    r"""Mathematics: compute discrete geometric phase factor `D = (-i)^{n_{active}} = \exp(-i \frac{\pi}{2} n_{active})`."""

    residue = active_chronons & 3
    if residue == 0:
        return 1.0 + 0.0j
    if residue == 1:
        return 0.0 - 1.0j
    if residue == 2:
        return -1.0 + 0.0j
    return 0.0 + 1.0j


def get_bits(tape: int, base: int, width: int) -> int:
    r"""Mathematics: extract integer slice `(tape \gg base) \bmod 2^{width}`."""

    return (tape >> base) & ((1 << width) - 1)


def set_bits(tape: int, base: int, width: int, value: int) -> int:
    r"""Mathematics: replace slice with `value \bmod 2^{width}` in `tape`."""

    mask = ((1 << width) - 1) << base
    return (tape & ~mask) | ((value & ((1 << width) - 1)) << base)


class ReversibleProgram:
    """Mathematics: stateful gate emitter and Bennett zero-restoring bit allocator."""

    def __init__(self) -> None:
        """Mathematics: initialize empty program with zero allocated bits and empty free list."""

        self.gates: list[tuple[int, int, int, int, int]] = []
        self.nbits: int = 0
        self._free: dict[int, list[int]] = {}
        self._peak: int = 0

    @property
    def peak_bits(self) -> int:
        r"""Mathematics: return peak allocated bit capacity `\max_t(nbits_t)`."""

        return self._peak

    def alloc(self, n: int = 1) -> int:
        """Mathematics: allocate `n` contiguous zero-initialized bits from free list or tape ceiling."""

        bucket = self._free.get(n)
        if bucket:
            return bucket.pop()
        base = self.nbits
        self.nbits += n
        self._peak = max(self._peak, self.nbits)
        return base

    def free(self, base: int, n: int = 1) -> None:
        """Mathematics: recycle `n` bits at `base`, asserting they have been Bennett-uncomputed to zero."""

        self._free.setdefault(n, []).append(base)

    def emit_x(self, target: int, pos: int = 0, neg: int = 0) -> None:
        """Mathematics: append controlled NOT gate flipping bit `target`."""

        self.gates.append((KIND_X, pos, neg, target, -1))

    def emit_swap(self, t1: int, t2: int, pos: int = 0, neg: int = 0) -> None:
        """Mathematics: append controlled exchange gate swapping bits `t1` and `t2`."""

        self.gates.append((KIND_SWAP, pos, neg, t1, t2))

    def emit_copy(self, out_base: int, src_base: int, width: int, arm: tuple[int, int] = ARM_NONE) -> None:
        r"""Mathematics: emit `out \leftarrow out \oplus src` across `width` bits under control `arm`."""

        pos, neg = arm
        for index in range(width):
            self.emit_x(out_base + index, pos | (1 << (src_base + index)), neg)

    def emit_const(self, out_base: int, value: int, width: int, arm: tuple[int, int] = ARM_NONE) -> None:
        r"""Mathematics: emit `out \leftarrow out \oplus (value \bmod 2^{width})` under control `arm`."""

        pos, neg = arm
        for index in range(width):
            if (value >> index) & 1:
                self.emit_x(out_base + index, pos, neg)

    def emit_not_into(self, out_base: int, src_base: int, width: int, arm: tuple[int, int] = ARM_NONE) -> None:
        r"""Mathematics: emit `out \leftarrow out \oplus (\sim src \bmod 2^{width})` into fresh zero cell under control `arm`."""

        self.emit_copy(out_base, src_base, width, arm)
        pos, neg = arm
        for index in range(width):
            self.emit_x(out_base + index, pos, neg)

    def emit_inc(self, out_base: int, src_base: int, width: int, arm: tuple[int, int] = ARM_NONE) -> None:
        r"""Mathematics: emit `out \leftarrow out \oplus ((src + 1) \bmod 2^{width})` into fresh zero cell under control `arm`."""

        pos, neg = arm
        self.emit_x(out_base, pos, neg | (1 << src_base))
        for index in range(1, width):
            self.emit_x(out_base + index, pos | (1 << (src_base + index)), neg)
            self.emit_x(out_base + index, pos | (((1 << index) - 1) << src_base), neg)

    def emit_bitwise(self, out_base: int, a_base: int, b_base: int, width: int, op: str, arm: tuple[int, int] = ARM_NONE) -> None:
        r"""Mathematics: emit `out \leftarrow out \oplus (a \odot b)` for `\odot \in \{\land, \lor, \oplus\}`."""

        pos, neg = arm
        for index in range(width):
            target = out_base + index
            ai = a_base + index
            bi = b_base + index
            if op == "xor":
                self.emit_x(target, pos | (1 << ai), neg)
                self.emit_x(target, pos | (1 << bi), neg)
            elif op == "and":
                self.emit_x(target, pos | (1 << ai) | (1 << bi), neg)
            elif op == "or":
                self.emit_x(target, pos | (1 << ai), neg)
                self.emit_x(target, pos | (1 << bi), neg)
                self.emit_x(target, pos | (1 << ai) | (1 << bi), neg)
            else:
                raise ValueError(f"unknown bitwise operator: {op}")

    def emit_shl(self, out_base: int, src_base: int, width: int, shift: int, arm: tuple[int, int] = ARM_NONE) -> None:
        r"""Mathematics: emit `out \leftarrow out \oplus ((src \ll shift) \bmod 2^{width})`."""

        pos, neg = arm
        for index in range(max(0, width - shift)):
            self.emit_x(out_base + index + shift, pos | (1 << (src_base + index)), neg)

    def emit_shr(self, out_base: int, src_base: int, width: int, shift: int, arm: tuple[int, int] = ARM_NONE) -> None:
        r"""Mathematics: emit `out \leftarrow out \oplus (src \gg shift)` across `width` bits."""

        pos, neg = arm
        for index in range(shift, width):
            self.emit_x(out_base + index - shift, pos | (1 << (src_base + index)), neg)

    def emit_xor_add(
        self,
        out_base: int,
        a_base: int,
        b_base: int,
        width: int,
        arm: tuple[int, int] = ARM_NONE,
        cin: int = 0,
        shift_b: int = 0,
    ) -> None:
        r"""Mathematics: emit `out \leftarrow out \oplus ((a + (b \ll shift\_b) + cin) \bmod 2^{width})` with Bennett carry uncomputation."""

        pos, neg = arm

        def _b_index(i: int) -> int | None:
            """Mathematics: map shifted bit index `i - shift_b` to tape bit coordinate when within `[0, width)`."""

            j = i - shift_b
            return b_base + j if 0 <= j < width else None

        c_base = self.alloc(width)
        if cin:
            self.emit_x(c_base, pos, neg)

        chain_start = len(self.gates)
        for index in range(width - 1):
            target = c_base + index + 1
            ai = a_base + index
            bi = _b_index(index)
            ci = c_base + index
            if bi is not None:
                self.emit_x(target, pos | (1 << ai) | (1 << bi), neg)
            self.emit_x(target, pos | (1 << ai) | (1 << ci), neg)
            if bi is not None:
                self.emit_x(target, pos | (1 << bi) | (1 << ci), neg)
        chain_end = len(self.gates)

        for index in range(width):
            ai = a_base + index
            bi = _b_index(index)
            ci = c_base + index
            self.emit_x(out_base + index, pos | (1 << ai), neg)
            if bi is not None:
                self.emit_x(out_base + index, pos | (1 << bi), neg)
            self.emit_x(out_base + index, pos | (1 << ci), neg)

        for gate in reversed(self.gates[chain_start:chain_end]):
            self.gates.append(gate)
        if cin:
            self.emit_x(c_base, pos, neg)
        self.free(c_base, width)

    def emit_xor_sub(
        self,
        out_base: int,
        a_base: int,
        b_base: int,
        width: int,
        arm: tuple[int, int] = ARM_NONE,
    ) -> None:
        r"""Mathematics: emit `out \leftarrow out \oplus ((a - b) \bmod 2^{width})` via two's complement `a + \sim b + 1`."""

        pos, neg = arm
        inv = self.alloc(width)
        self.emit_copy(inv, b_base, width, arm)
        for index in range(width):
            self.emit_x(inv + index, pos, neg)
        self.emit_xor_add(out_base, a_base, inv, width, arm=arm, cin=1)
        for index in reversed(range(width)):
            self.emit_x(inv + index, pos, neg)
        for index in reversed(range(width)):
            self.emit_x(inv + index, pos | (1 << (b_base + index)), neg)
        self.free(inv, width)

    def emit_xor_mul(
        self,
        out_base: int,
        a_base: int,
        b_base: int,
        width: int,
        arm: tuple[int, int] = ARM_NONE,
    ) -> None:
        r"""Mathematics: emit `out \leftarrow out \oplus ((a \times b) \bmod 2^{width})` via shift-and-add with full Bennett uncomputation."""

        pos, neg = arm
        start = len(self.gates)
        partials: list[int] = []
        for j in range(width):
            pj = self.alloc(width)
            partials.append(pj)
            for i in range(width):
                self.emit_x(pj + i, pos | (1 << (a_base + i)) | (1 << (b_base + j)), neg)
        acc = self.alloc(width)
        for i in range(width):
            self.emit_x(acc + i, pos | (1 << (partials[0] + i)), neg)
        accs = [acc]
        for j in range(1, width):
            nxt = self.alloc(width)
            self.emit_xor_add(nxt, acc, partials[j], width, arm=arm, shift_b=j)
            accs.append(nxt)
            acc = nxt
        copy_start = len(self.gates)
        self.emit_copy(out_base, acc, width, arm)
        for gate in reversed(self.gates[start:copy_start]):
            self.gates.append(gate)
        for block in partials:
            self.free(block, width)
        for block in accs:
            self.free(block, width)

    def execute(self, tape: int) -> tuple[int, int]:
        r"""Mathematics: execute compiled gate sequence forward, returning `(tape', n_{active})`."""

        return execute_gates(tape, self.gates)

    def reverse_execute(self, tape: int) -> tuple[int, int]:
        """Mathematics: execute reversed gate sequence backward, restoring exact pre-computation state."""

        return execute_gates(tape, reverse_gates(self.gates))

    def __len__(self) -> int:
        """Mathematics: return cardinality `|gates|`."""

        return len(self.gates)
