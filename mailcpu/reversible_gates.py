"""Reversible bit-vector and word-level gate algebra for zero-dissipation state transitions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

KIND_X: int = 0
KIND_SWAP: int = 1

ARM_NONE: tuple[int, int] = (0, 0)


def _validate_controls(pos: int, neg: int) -> None:
    r"""Mathematics: enforce the Boolean control invariant `pos \land neg = 0` and `pos, neg \ge 0`."""

    if pos < 0 or neg < 0:
        raise ValueError("control masks must be non-negative")
    if pos & neg:
        raise ValueError("control bit specified with contradictory polarities")


def _validate_slice(base: int, width: int, label: str = "slice") -> None:
    r"""Mathematics: validate interval `[base, base + width)` with `base \ge 0` and `width \ge 0`."""

    if base < 0 or width < 0:
        raise ValueError(f"{label} base and width must be non-negative")


def _ranges_overlap(base_a: int, width_a: int, base_b: int, width_b: int) -> bool:
    r"""Mathematics: test interval intersection `[a_0,a_1) \cap [b_0,b_1) \ne \varnothing`."""

    return max(base_a, base_b) < min(base_a + width_a, base_b + width_b)


def _validate_gate_geometry(kind: int, pos: int, neg: int, t1: int, t2: int) -> None:
    r"""Mathematics: validate an involution's disjoint target/control supports and kind domain."""

    _validate_controls(pos, neg)
    if kind not in (KIND_X, KIND_SWAP):
        raise ValueError(f"unknown reversible gate kind: {kind}")
    if t1 < 0 or (kind == KIND_SWAP and t2 < 0):
        raise ValueError("gate target indices must be non-negative")
    if kind == KIND_X:
        if pos & (1 << t1) or neg & (1 << t1):
            raise ValueError("gate target cannot also be a control")
    elif t1 == t2:
        raise ValueError("swap targets must be distinct")
    elif (pos | neg) & ((1 << t1) | (1 << t2)):
        raise ValueError("swap targets cannot also be controls")


def arm_union(a: tuple[int, int], b: tuple[int, int]) -> tuple[int, int]:
    r"""Mathematics: evaluate `(pos_a \lor pos_b, neg_a \lor neg_b)`, asserting `(pos_a \lor pos_b) \land (neg_a \lor neg_b) = 0`."""

    _validate_controls(*a)
    _validate_controls(*b)
    pos = a[0] | b[0]
    neg = a[1] | b[1]
    _validate_controls(pos, neg)
    return (pos, neg)


@dataclass(frozen=True)
class ReversibleGate:
    r"""Mathematics: involutive gate `G(s) = s \oplus \Delta(s)` satisfying `G \circ G = I`."""

    kind: int
    pos: int
    neg: int
    t1: int
    t2: int = -1

    def __post_init__(self) -> None:
        r"""Mathematics: enforce the gate support invariant required for `G \circ G = I`."""

        _validate_gate_geometry(self.kind, self.pos, self.neg, self.t1, self.t2)

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
    return ReversibleGate(kind, pos, neg, t1, t2).apply(tape)


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

    _validate_slice(base, width)
    return (tape >> base) & ((1 << width) - 1)


def set_bits(tape: int, base: int, width: int, value: int) -> int:
    r"""Mathematics: replace slice with `value \bmod 2^{width}` in `tape`."""

    _validate_slice(base, width)
    mask = ((1 << width) - 1) << base
    return (tape & ~mask) | ((value & ((1 << width) - 1)) << base)


class ReversibleProgram:
    """Mathematics: stateful gate emitter and Bennett zero-restoring bit allocator."""

    def __init__(self) -> None:
        """Mathematics: initialize empty program with zero allocated bits and empty free list."""

        self.gates: list[tuple[int, int, int, int, int]] = []
        self.nbits: int = 0
        self._free: dict[int, list[int]] = {}
        self._live: dict[int, int] = {}
        self._peak: int = 0

    @property
    def peak_bits(self) -> int:
        r"""Mathematics: return peak allocated bit capacity `\max_t(nbits_t)`."""

        return self._peak

    def alloc(self, n: int = 1) -> int:
        """Mathematics: allocate `n > 0` contiguous bits, reusing a free interval when available."""

        if n <= 0:
            raise ValueError("allocation width must be positive")
        bucket = self._free.get(n)
        if bucket:
            base = bucket.pop()
            self._live[base] = n
            return base
        base = self.nbits
        self.nbits += n
        self._peak = max(self._peak, self.nbits)
        self._live[base] = n
        return base

    def free(self, base: int, n: int = 1) -> None:
        """Mathematics: recycle exactly an owned interval after the caller proves its Bennett state is zero."""

        _validate_slice(base, n, "free interval")
        if self._live.get(base) != n:
            raise ValueError("free interval is not an owned live allocation")
        del self._live[base]
        self._free.setdefault(n, []).append(base)

    def emit_x(self, target: int, pos: int = 0, neg: int = 0) -> None:
        r"""Mathematics: append controlled NOT `t \mapsto t \oplus 2^{target}` with target outside controls."""

        _validate_gate_geometry(KIND_X, pos, neg, target, -1)
        self.gates.append((KIND_X, pos, neg, target, -1))

    def emit_swap(self, t1: int, t2: int, pos: int = 0, neg: int = 0) -> None:
        r"""Mathematics: append controlled exchange `t_1 \leftrightarrow t_2` with disjoint supports."""

        _validate_gate_geometry(KIND_SWAP, pos, neg, t1, t2)
        self.gates.append((KIND_SWAP, pos, neg, t1, t2))

    def emit_copy(self, out_base: int, src_base: int, width: int, arm: tuple[int, int] = ARM_NONE) -> None:
        r"""Mathematics: emit `out \leftarrow out \oplus src` across `width` bits under control `arm`."""

        _validate_slice(out_base, width, "output")
        _validate_slice(src_base, width, "source")
        if _ranges_overlap(out_base, width, src_base, width):
            raise ValueError("copy source and output ranges must be disjoint")
        pos, neg = arm
        _validate_controls(pos, neg)
        if (pos | neg) & sum(1 << (out_base + index) for index in range(width)):
            raise ValueError("copy output cannot also be a control")
        for index in range(width):
            self.emit_x(out_base + index, pos | (1 << (src_base + index)), neg)

    def emit_const(self, out_base: int, value: int, width: int, arm: tuple[int, int] = ARM_NONE) -> None:
        r"""Mathematics: emit `out \leftarrow out \oplus (value \bmod 2^{width})` under control `arm`."""

        _validate_slice(out_base, width, "output")
        pos, neg = arm
        _validate_controls(pos, neg)
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

        _validate_slice(out_base, width, "output")
        _validate_slice(src_base, width, "source")
        if _ranges_overlap(out_base, width, src_base, width):
            raise ValueError("increment source and output ranges must be disjoint")
        pos, neg = arm
        _validate_controls(pos, neg)
        self.emit_x(out_base, pos, neg | (1 << src_base))
        for index in range(1, width):
            self.emit_x(out_base + index, pos | (1 << (src_base + index)), neg)
            self.emit_x(out_base + index, pos | (((1 << index) - 1) << src_base), neg)

    def emit_bitwise(self, out_base: int, a_base: int, b_base: int, width: int, op: str, arm: tuple[int, int] = ARM_NONE) -> None:
        r"""Mathematics: emit `out \leftarrow out \oplus (a \odot b)` for `\odot \in \{\land, \lor, \oplus\}`."""

        _validate_slice(out_base, width, "output")
        _validate_slice(a_base, width, "left input")
        _validate_slice(b_base, width, "right input")
        if _ranges_overlap(out_base, width, a_base, width) or _ranges_overlap(out_base, width, b_base, width):
            raise ValueError("bitwise output and input ranges must be disjoint")
        pos, neg = arm
        _validate_controls(pos, neg)
        if op not in {"xor", "and", "or"}:
            raise ValueError(f"unknown bitwise operator: {op}")
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

    def emit_shl(self, out_base: int, src_base: int, width: int, shift: int, arm: tuple[int, int] = ARM_NONE) -> None:
        r"""Mathematics: emit `out \leftarrow out \oplus ((src \ll shift) \bmod 2^{width})`."""

        _validate_slice(out_base, width, "output")
        _validate_slice(src_base, width, "source")
        if shift < 0:
            raise ValueError("shift must be non-negative")
        if _ranges_overlap(out_base, width, src_base, width):
            raise ValueError("shift source and output ranges must be disjoint")
        pos, neg = arm
        _validate_controls(pos, neg)
        for index in range(max(0, width - shift)):
            self.emit_x(out_base + index + shift, pos | (1 << (src_base + index)), neg)

    def emit_shr(self, out_base: int, src_base: int, width: int, shift: int, arm: tuple[int, int] = ARM_NONE) -> None:
        r"""Mathematics: emit `out \leftarrow out \oplus (src \gg shift)` across `width` bits."""

        _validate_slice(out_base, width, "output")
        _validate_slice(src_base, width, "source")
        if shift < 0:
            raise ValueError("shift must be non-negative")
        if _ranges_overlap(out_base, width, src_base, width):
            raise ValueError("shift source and output ranges must be disjoint")
        pos, neg = arm
        _validate_controls(pos, neg)
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

        if width <= 0:
            raise ValueError("addition width must be positive")
        _validate_slice(out_base, width, "output")
        _validate_slice(a_base, width, "left input")
        _validate_slice(b_base, width, "right input")
        if _ranges_overlap(out_base, width, a_base, width) or _ranges_overlap(out_base, width, b_base, width):
            raise ValueError("addition output and input ranges must be disjoint")
        if shift_b < 0:
            raise ValueError("shift_b must be non-negative")
        pos, neg = arm
        _validate_controls(pos, neg)

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

        if width <= 0:
            raise ValueError("subtraction width must be positive")
        _validate_slice(out_base, width, "output")
        _validate_slice(a_base, width, "left input")
        _validate_slice(b_base, width, "right input")
        if _ranges_overlap(out_base, width, a_base, width) or _ranges_overlap(out_base, width, b_base, width):
            raise ValueError("subtraction output and input ranges must be disjoint")
        pos, neg = arm
        _validate_controls(pos, neg)
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

        if width <= 0:
            raise ValueError("multiplication width must be positive")
        _validate_slice(out_base, width, "output")
        _validate_slice(a_base, width, "left input")
        _validate_slice(b_base, width, "right input")
        if _ranges_overlap(out_base, width, a_base, width) or _ranges_overlap(out_base, width, b_base, width):
            raise ValueError("multiplication output and input ranges must be disjoint")
        pos, neg = arm
        _validate_controls(pos, neg)
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
