from __future__ import annotations

import pytest

from mailcpu.reversible_gates import (
    ARM_NONE,
    KIND_SWAP,
    KIND_X,
    ReversibleGate,
    ReversibleProgram,
    apply_gate,
    arm_union,
    execute_gates,
    get_bits,
    phase_factor,
    reverse_gates,
    set_bits,
)
from mailcpu.chronofold import AllocatorSnapshot, ChronoFold


def test_gate_involution_identity() -> None:
    r"""Mathematics: every gate `G` satisfies `G(G(s)) = s` for all states `s \in \mathbb{N}`."""

    tape = 0b101100101
    gx = ReversibleGate(kind=KIND_X, pos=0, neg=0, t1=3)
    t1, act1 = gx.apply(tape)
    assert act1 is True
    t2, act2 = gx.apply(t1)
    assert act2 is True
    assert t2 == tape

    gswap = ReversibleGate(kind=KIND_SWAP, pos=0, neg=0, t1=0, t2=1)
    t3, act3 = gswap.apply(tape)
    assert act3 is True
    t4, act4 = gswap.apply(t3)
    assert act4 is True
    assert t4 == tape


def test_controlled_gate_predication() -> None:
    r"""Mathematics: gate activation condition `(s \land pos = pos) \land (s \land neg = 0)` gates execution without branch jumps."""

    gate = ReversibleGate(kind=KIND_X, pos=0b01, neg=0b10, t1=4)
    res, act = gate.apply(0b01)
    assert act is True
    assert res == 0b10001

    res_blocked_pos, act_bp = gate.apply(0b00)
    assert act_bp is False
    assert res_blocked_pos == 0b00

    res_blocked_neg, act_bn = gate.apply(0b11)
    assert act_bn is False
    assert res_blocked_neg == 0b11


def test_contradictory_controls_raise() -> None:
    r"""Mathematics: asserting disjointness `pos \land neg = 0` rejects contradictory control assignments."""

    with pytest.raises(ValueError, match="contradictory polarities"):
        arm_union((0b01, 0), (0, 0b01))


def test_invalid_reversible_geometry_is_rejected() -> None:
    r"""Mathematics: an involution requires disjoint target and control supports."""

    with pytest.raises(ValueError, match="target cannot also be a control"):
        ReversibleGate(kind=KIND_X, pos=0b1, neg=0, t1=0)

    with pytest.raises(ValueError, match="source and output ranges"):
        ReversibleProgram().emit_copy(out_base=2, src_base=3, width=2)

    with pytest.raises(ValueError, match="non-negative"):
        ReversibleProgram().emit_shl(out_base=0, src_base=4, width=2, shift=-1)

    with pytest.raises(ValueError, match="unknown reversible gate kind"):
        apply_gate(0, (99, 0, 0, 0, -1))


def test_allocator_rejects_double_free_and_unknown_intervals() -> None:
    r"""Mathematics: allocator ownership is a partial bijection between live and free intervals."""

    program = ReversibleProgram()
    base = program.alloc(3)
    program.free(base, 3)

    with pytest.raises(ValueError, match="owned live allocation"):
        program.free(base, 3)

    with pytest.raises(ValueError, match="owned live allocation"):
        program.free(99, 1)


def test_reversible_adder_and_ancilla_cleanup() -> None:
    r"""Mathematics: adder computes `(a + b) \bmod 2^w` with Bennett carry uncomputation, leaving carry ancillas strictly at 0."""

    p = ReversibleProgram()
    w = 8
    a_base = p.alloc(w)
    b_base = p.alloc(w)
    out_base = p.alloc(w)

    p.emit_xor_add(out_base, a_base, b_base, w)

    initial_tape = 0
    initial_tape = set_bits(initial_tape, a_base, w, 45)
    initial_tape = set_bits(initial_tape, b_base, w, 78)

    final_tape, active_count = p.execute(initial_tape)
    assert get_bits(final_tape, out_base, w) == (45 + 78) & 0xFF
    assert active_count > 0

    restored_tape, rev_active = p.reverse_execute(final_tape)
    assert restored_tape == initial_tape
    assert rev_active == active_count


def test_reversible_subtractor_and_multiplier() -> None:
    r"""Mathematics: subtraction and multiplication evaluate modular rings with complete reversal `(P^{-1} \circ P)(s) = s`."""

    p = ReversibleProgram()
    w = 8
    a_base = p.alloc(w)
    b_base = p.alloc(w)
    sub_base = p.alloc(w)
    mul_base = p.alloc(w)

    p.emit_xor_sub(sub_base, a_base, b_base, w)
    p.emit_xor_mul(mul_base, a_base, b_base, w)

    tape = 0
    tape = set_bits(tape, a_base, w, 15)
    tape = set_bits(tape, b_base, w, 6)

    out_tape, active_count = p.execute(tape)
    assert get_bits(out_tape, sub_base, w) == (15 - 6) & 0xFF
    assert get_bits(out_tape, mul_base, w) == (15 * 6) & 0xFF

    inv_tape, rev_count = p.reverse_execute(out_tape)
    assert inv_tape == tape
    assert rev_count == active_count


def test_discrete_geometric_phase_ledger() -> None:
    """Mathematics: discrete geometric phase `D = (-i)^{n_{active}}` cycles on modular period 4."""

    assert phase_factor(0) == 1.0 + 0.0j
    assert phase_factor(1) == 0.0 - 1.0j
    assert phase_factor(2) == -1.0 + 0.0j
    assert phase_factor(3) == 0.0 + 1.0j
    assert phase_factor(4) == 1.0 + 0.0j
    assert phase_factor(100) == 1.0 + 0.0j


def test_chronofold_periodic_trace_compression() -> None:
    r"""Mathematics: repeated loop strides `t_{i+P} = t_i + S` are detected and stored as `\mathcal{O}(1)` descriptors."""

    fold = ChronoFold(initial_tape=0x1234)
    pattern = [10, 20, 30]
    stride = 5
    for iteration in range(6):
        for val in pattern:
            fold.record_step(val + iteration * stride, active_delta=2, read_delta=1)

    assert fold.detect_periodicity(min_period=3, max_period=5) is True
    assert fold.period_length == 3
    assert fold.period_stride == stride
    assert fold.active_chronons == 6 * 3 * 2
    assert fold.sector_reads == 6 * 3 * 1


def test_chronofold_bennett_constant_space_replay_and_reversal() -> None:
    """Mathematics: Bennett replay `recompute_final_tape` and `reverse_tape` verify `(T^N)^{-1}(T^N(s_0)) = s_0` without storing intermediate tapes."""

    fold = ChronoFold(initial_tape=0)
    for code in [1, 2, 3, 2, 1]:
        fold.record_step(code)

    def gate_generator(code: int) -> list[ReversibleGate]:
        return [ReversibleGate(kind=KIND_X, pos=0, neg=0, t1=code)]

    final_tape, active_fwd = fold.recompute_final_tape(gate_generator)
    expected_tape = (1 << 1) ^ (1 << 2) ^ (1 << 3) ^ (1 << 2) ^ (1 << 1)
    assert final_tape == expected_tape
    assert final_tape == (1 << 3)

    restored_tape, active_rev = fold.reverse_tape(final_tape, gate_generator)
    assert restored_tape == fold.initial_tape
    assert restored_tape == 0
    assert active_rev == active_fwd


def test_chronofold_serialization_roundtrip() -> None:
    r"""Mathematics: `from_json(to_json(\mathcal{F})) = \mathcal{F}` preserves initial state, trace, phase, and period headers."""

    fold = ChronoFold(
        initial_tape=0xDEADBEEF,
        trace=[1, 2, 4, 8, 16],
        period_header=2,
        period_length=1,
        period_stride=1,
        active_chronons=12,
        sector_reads=5,
    )
    payload = fold.to_json()
    deserialized = ChronoFold.from_json(payload)

    assert deserialized.initial_tape == fold.initial_tape
    assert deserialized.trace == fold.trace
    assert deserialized.period_header == fold.period_header
    assert deserialized.period_length == fold.period_length
    assert deserialized.period_stride == fold.period_stride
    assert deserialized.active_chronons == fold.active_chronons
    assert deserialized.sector_reads == fold.sector_reads
    assert deserialized.phase == fold.phase


def test_chronofold_rejects_period_metadata_outside_trace() -> None:
    r"""Mathematics: a period witness requires `h + 2P <= |trace|`; malformed witnesses are rejected."""

    with pytest.raises(ValueError, match="retained trace"):
        ChronoFold.from_dict(
            {
                "format": "mailcpu-chronofold/1",
                "initial_tape": "0x0",
                "trace": [1, 2],
                "period_header": 1,
                "period_length": 1,
            }
        )


def test_scheduler_chronofold_integration() -> None:
    r"""Mathematics: scheduler trace projection `\tau \mapsto \mathcal{F}` records executed micro-steps and phase `D = (-i)^{n_{active}}` across snapshots."""

    from mailcpu.assembler import assemble
    from mailcpu.bus import MailboxBus
    from mailcpu.journal import EventJournal
    from mailcpu.scheduler import DeterministicScheduler

    source = "set a 10\nset b 20\nadd c a b\nhalt\n"
    program = assemble(source)

    bus = MailboxBus()
    journal = EventJournal()
    scheduler = DeterministicScheduler(bus=bus, journal=journal)

    pid = scheduler.add(program, name="adder", enable_chronofold=True)
    events = scheduler.run(10)
    assert len(events) == 4

    task = scheduler.tasks[pid]
    assert task.chronofold is not None
    assert len(task.chronofold.trace) == 4
    assert task.chronofold.active_chronons == 4
    assert task.chronofold.phase == phase_factor(4)

    snapshot_payload = scheduler.snapshot()
    restored_scheduler = DeterministicScheduler.from_snapshot(snapshot_payload, bus=bus, journal=journal)
    restored_task = restored_scheduler.tasks[pid]
    assert restored_task.chronofold is not None
    assert restored_task.chronofold.trace == task.chronofold.trace
    assert restored_task.chronofold.active_chronons == task.chronofold.active_chronons
    assert restored_task.chronofold.phase == task.chronofold.phase
    assert scheduler.system_epoch.chronon_phase == phase_factor(4)
    assert restored_scheduler.system_epoch.chronon_phase == phase_factor(4)

