from __future__ import annotations

import random
import pytest

from mailcpu.delay_loop import DelayGroup, DelayLoopEngine, DelaySlot
from mailcpu.rrns import (
    affine_orbit_jump,
    crt,
    encode_rrns,
    legit_range,
    primes_below,
    recover_rrns,
)


def test_primes_below_sieve() -> None:
    """Mathematics: sieve yields monotonically descending prime numbers strictly below ceiling."""

    primes = primes_below(30, 5)
    assert primes == [29, 23, 19, 17, 13]


def test_crt_exact_reconstruction() -> None:
    r"""Mathematics: Chinese Remainder Theorem uniquely evaluates `x \equiv r_i \pmod{m_i}` in `[0, \prod m_i)`."""

    moduli = [11, 13, 17]
    value = 1842
    residues = [value % m for m in moduli]

    reconstructed = crt(residues, moduli)
    assert reconstructed == value
    for r, m in zip(residues, moduli):
        assert reconstructed % m == r


def test_rrns_encoding_and_erasure_recovery() -> None:
    r"""Mathematics: `k`-of-`n` RRNS recovers original state `V` from any subset of size `k \le n` surviving residue packets."""

    moduli = [101, 103, 107, 109, 113]
    k = 3
    max_range = legit_range(moduli, k)
    value = 987654
    assert value < max_range

    residues = encode_rrns(value, moduli)
    pairs = list(zip(moduli, residues))

    # Drop 2 out of 5 packets (e.g. retain indices 0, 2, 4)
    surviving = [pairs[0], pairs[2], pairs[4]]
    recovered, ok = recover_rrns(surviving, k, moduli)
    assert ok is True
    assert recovered == value


def test_rrns_corruption_detection() -> None:
    r"""Mathematics: corrupted residue vectors falling into `[M, M_T)` or violating consistency are rejected."""

    moduli = [101, 103, 107, 109, 113]
    k = 3
    value = 543210
    residues = encode_rrns(value, moduli)
    pairs = list(zip(moduli, residues))

    # Corrupt one residue packet
    pairs[3] = (pairs[3][0], (pairs[3][1] + 1) % pairs[3][0])

    # With k=3 and 4 pairs provided, consistency check against the 4th pair should fail
    recovered, ok = recover_rrns(pairs[:4], k, moduli)
    assert ok is False


def test_affine_orbit_jump_equivalence() -> None:
    r"""Mathematics: `\mathcal{O}(\log n)` matrix exponentiation matches iterative affine recurrence `x_{k+1} = a x_k + b \pmod m`."""

    a = 1664525
    b = 1013904223
    m = 2**32
    steps = 1000

    # Iterative step-by-step
    x = 42
    for _ in range(steps):
        x = (a * x + b) % m

    # Logarithmic orbit jump
    big_a, big_b = affine_orbit_jump(a, b, m, steps)
    jumped_x = (big_a * 42 + big_b) % m

    assert jumped_x == x


def test_delay_loop_engine_scrub_and_regeneration() -> None:
    r"""Mathematics: delay-line engine restores in-flight memory slots and increments version on packet loss."""

    engine = DelayLoopEngine(nominal_rtt_s=0.04)
    moduli = primes_below(200, 5)  # 5 coprime moduli
    k = 3
    value = 50000

    group = engine.add_group(value=value, k=k, moduli=moduli, kind="scrub")
    assert len(group.slots) == 5

    # Simulate arrival of all 5 slots
    for slot in group.slots:
        payload = slot.encode_payload()
        success = engine.process_arrival(slot.slot_id, payload, arrival_time=0.04)
        assert success is True

    # Check read
    read_val, read_ok = engine.read_group(group.group_id)
    assert read_ok is True
    assert read_val == value

    # Simulate 2 dropped slots (erasure)
    group.slots[1].alive = False
    group.slots[3].alive = False

    # Scrub: reconstructs from 3 surviving slots and revives dropped slots
    recovered, scrub_ok = engine.scrub_group(group.group_id)
    assert scrub_ok is True
    assert recovered == value
    assert group.scrub_count == 1
    assert group.slots[1].alive is True
    assert group.slots[1].version == 1
    assert group.slots[1].residue == value % group.slots[1].modulus
    assert group.slots[3].alive is True
    assert group.slots[3].version == 1
    assert group.slots[3].residue == value % group.slots[3].modulus


def test_delay_loop_unrecoverable_loss() -> None:
    r"""Mathematics: when surviving slots `< k`, the group is marked as irreversibly lost."""

    engine = DelayLoopEngine()
    moduli = primes_below(150, 4)
    k = 3
    group = engine.add_group(value=1234, k=k, moduli=moduli, kind="scrub")

    # Drop 2 out of 4 slots (only 2 survive, < k=3)
    group.slots[0].alive = False
    group.slots[1].alive = False

    recovered, scrub_ok = engine.scrub_group(group.group_id)
    assert scrub_ok is False
    assert recovered is None
    assert group.is_lost is True


def test_dynamic_slot_clamping() -> None:
    r"""Mathematics: dynamic slot spacing scales with measured jitter `\Delta_{\text{slot}} \ge 3 \sigma_{\text{jitter}}`."""

    engine = DelayLoopEngine(slot_clamping_factor=3.0)
    # Feed varying RTTs
    rtts = [0.048, 0.052, 0.045, 0.055, 0.050, 0.060, 0.040]
    for rtt in rtts:
        engine.record_rtt(rtt)

    assert engine.jitter_s > 0.002
    assert engine.slot_interval_s >= 3.0 * engine.jitter_s
