r"""Unit tests for Omega-5 law certification, vantage transforms, and mixture decomposition.

Mathematics:
Verifies formal invariants across the 8-rung algebraic ladder:
- $O(1)$ and $O(\log t)$ orbit navigation
- 2-adic bit-lifting and BSGS inversion
- Vantage-point transforms and difference invariants
- Interleaved multi-tenant stream mixture decomposition
- Horizon guard enforcement ($t < t_{\text{horizon}}$)
"""

from __future__ import annotations

import pytest

from mailcpu.law_certifier import (
    HorizonExceeded,
    Law,
    Refused,
    brent_cycle,
    detect_eventual_period,
    find_coordinate_lcg,
    find_coordinate_lcg_adic,
    find_guarded,
    geom_sum_mod,
    lcg_navigate,
    lfsr_jump,
    navigate_guarded,
    orbit_leap,
    recover_law,
)
from mailcpu.mixture_decomposition import decompose_mixture, recover_mixture
from mailcpu.vantage_transform import (
    apply_vantage,
    vp_difference,
    vp_fold,
    vp_integrate,
    vp_modulus,
    vp_origin,
    vp_stride,
)


def test_geometric_series_sum() -> None:
    r"""Test O(log t) geometric series summation modulo M.

    Mathematics:
    \[
    S(t) = \sum_{i=0}^{t-1} a^i \pmod M
    \]
    """
    a = 5
    m = 10007
    for t in (0, 1, 2, 5, 17, 64):
        expected = sum(pow(a, i, m) for i in range(t)) % m
        assert geom_sum_mod(a, t, m) == expected


def test_int_law_certification_and_leap() -> None:
    r"""Test integer arithmetic progression certification and O(1) leap.

    Mathematics:
    \[
    x_t \equiv (x_0 + \text{step} \cdot t) \pmod M
    \]
    """
    x0 = 65500
    step = 17
    m = 65536
    lane = [(x0 + step * t) % m for t in range(50)]
    window = lane[:30]
    truth = lane[30:]

    law = recover_law(window, truth)
    assert law.verdict == "GROUND"
    assert law.family == "int"
    assert law.params["step"] == step
    assert law.params["mod"] == m

    # Leap to distant coordinate
    for t in (35, 45, 1000):
        expected = (x0 + step * t) % m
        assert orbit_leap(law, t) == expected

    # Invert
    target = lane[25]
    coord = find_guarded(law, target)
    assert coord == 25


def test_lcg_power_of_two_and_adic_inversion() -> None:
    r"""Test power-of-two affine recurrence with 2-adic bit-lifting inversion.

    Mathematics:
    \[
    x_{t+1} \equiv (5 x_t + 1) \pmod{256}
    \]
    """
    a = 5
    c = 1
    m = 256
    x0 = 13
    lane = []
    cur = x0
    for _ in range(60):
        lane.append(cur)
        cur = (a * cur + c) % m

    window = lane[:40]
    truth = lane[40:]
    law = recover_law(window, truth)
    assert law.verdict == "GROUND"
    assert law.family == "lcg"
    assert law.params["a"] == a
    assert law.params["c"] == c
    assert law.params["mod"] == m

    # 2-adic bit lifting inversion
    target = lane[19]
    t_found = find_coordinate_lcg_adic(a, c, m, x0, target)
    assert t_found == 19

    # Guarded find
    coord = find_guarded(law, target)
    assert coord == 19


def test_lcg_wide_prime_modulus_bsgs() -> None:
    r"""Test wide prime modulus affine recurrence and BSGS inversion.

    Mathematics:
    \[
    x_{t+1} \equiv (16807 x_t + 3) \pmod{2147483647}
    \]
    """
    p = 2147483647
    a = 16807
    c = 3
    x0 = 123456
    lane = []
    cur = x0
    for _ in range(40):
        lane.append(cur)
        cur = (a * cur + c) % p

    window = lane[:25]
    truth = lane[25:]
    law = recover_law(window, truth)
    assert law.verdict == "GROUND"
    assert law.family == "lcg"
    assert law.params["mod"] == p

    # BSGS inversion
    target = lane[14]
    t_found = find_coordinate_lcg(a, c, p, x0, target, max_order=100)
    assert t_found == 14


def test_gf2_berlekamp_massey_and_jump() -> None:
    r"""Test GF(2) linear feedback shift register jump.

    Mathematics:
    Fibonacci recurrence $s_n = s_{n-1} \oplus s_{n-2} \pmod 2$.
    """
    s = [1, 1]
    for _ in range(40):
        s.append(s[-1] ^ s[-2])

    window = s[:25]
    truth = s[25:]
    law = recover_law(window, truth)
    assert law.verdict == "GROUND"
    assert law.family == "gf2"
    assert law.order == 2

    # Orbit leap forward
    for t in (10, 20, 30, 38):
        assert orbit_leap(law, t) == s[t]


def test_fgraph_brent_cycle_and_orbit() -> None:
    r"""Test functional graph Brent cycle discovery and orbit navigation.

    Mathematics:
    Quadratic map $x_{k+1} = (x_k^2 + 1) \pmod{101}$.
    """
    step = lambda x: (x * x + 1) % 101
    mu, lam = brent_cycle(step, 2)
    assert mu >= 0
    assert lam >= 1

    # In-window periodic detection
    lane = [10, 20, 30, 40, 50, 40, 50, 40, 50, 40, 50]
    period = detect_eventual_period(lane)
    assert period is not None
    assert period == (3, 2)

    law = recover_law(lane[:7], lane[7:])
    assert law.verdict == "GROUND"
    assert law.family == "fgraph"
    assert orbit_leap(law, 8) == 50
    assert orbit_leap(law, 9) == 40


def test_kreg_regular_sequence() -> None:
    r"""Test 2-regular sequence certification.

    Mathematics:
    Popcount / Thue-Morse style relations: $x_{2t} = x_t$, $x_{2t+1} = x_t + 1$.
    """
    lane = [0] * 32
    for t in range(16):
        lane[2 * t] = lane[t]
        if 2 * t + 1 < 32:
            lane[2 * t + 1] = lane[t] + 1

    window = lane[:24]
    truth = lane[24:]
    law = recover_law(window, truth)
    assert law.verdict == "GROUND"
    assert law.family == "kreg"
    assert orbit_leap(law, 27) == lane[27]


def test_guarded_navigation_horizon() -> None:
    r"""Test that navigate_guarded strictly raises HorizonExceeded past first_bad."""
    # Prefix-ground law: holds for prefix, then diverges
    lane = [10, 20, 30, 40, 50, 60, 70, 80, 999, 999]
    window = lane[:6]
    truth = lane[6:]
    law = recover_law(window, truth)
    assert law.verdict == "PREFIX-GROUND"
    assert law.first_bad == 8

    # Valid before horizon
    assert navigate_guarded(law, 6) == 70
    assert navigate_guarded(law, 7) == 80

    # Refused at or past horizon
    with pytest.raises(HorizonExceeded):
        navigate_guarded(law, 8)

    with pytest.raises(HorizonExceeded):
        navigate_guarded(law, 9)

    # TAPE refusal
    tape_law = Law(family="tape", verdict="TAPE", residual=1.0)
    with pytest.raises(Refused):
        navigate_guarded(tape_law, 0)


def test_vantage_transforms() -> None:
    r"""Test vantage point transforms and algebraic relations."""
    seq = [10, 15, 20, 25, 30, 35, 40]

    # Stride
    assert vp_stride(seq, k=2) == [10, 20, 30, 40]

    # Difference
    assert vp_difference(seq) == [5, 5, 5, 5, 5, 5]

    # Integration
    diffs = [5, 5, 5]
    assert vp_integrate(diffs, seed=10) == [15, 20, 25]

    # Origin
    assert vp_origin(seq) == [0, 5, 10, 15, 20, 25, 30]

    # Modulus
    assert vp_modulus(seq, m=16) == [10, 15, 4, 9, 14, 3, 8]

    # Fold
    folded = vp_fold(seq, k_bins=10)
    assert folded[0] == 0
    assert folded[-1] == 10

    # Pipeline wrapper
    assert apply_vantage("difference", seq) == [5, 5, 5, 5, 5, 5]
    assert apply_vantage("stride", seq, k=3) == [10, 25, 40]


def test_mixture_decomposition_interleaved_streams() -> None:
    r"""Test mixture decomposition of interleaved execution threads.

    Mathematics:
    Interleaves two independent streams:
    Stream 0: $y^{(0)}_{t+1} \equiv (5 y^{(0)}_t + 1) \pmod{256}$
    Stream 1: $y^{(1)}_t = 100 + 7 t \pmod{256}$
    """
    m = 256
    s0 = []
    cur0 = 11
    for _ in range(40):
        s0.append(cur0)
        cur0 = (5 * cur0 + 1) % m

    s1 = [(100 + 7 * t) % m for t in range(40)]

    interleaved = []
    for a, b in zip(s0, s1):
        interleaved.append(a)
        interleaved.append(b)

    # Plain law certifier must refuse composite interleaved stream as TAPE
    plain_law = recover_law(interleaved[:40], interleaved[40:])
    assert plain_law.verdict == "TAPE"

    # Mixture decomposition detects stride 2 and recovers both components
    mix = decompose_mixture(interleaved, max_stride=4, require_refused=True)
    assert mix.is_mixture
    assert mix.stride == 2
    assert len(mix.components) == 2

    # Recover mixture law and leap
    mix_law, recovered_mix = recover_mixture(interleaved[:50], interleaved[50:])
    assert mix_law.is_ground
    assert mix_law.family.startswith("mixture")

    # Verify orbit leap reproduces held out interleaved stream
    for t in (52, 53, 60, 61):
        assert orbit_leap(mix_law, t) == interleaved[t]
