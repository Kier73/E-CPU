"""Redundant Residue Number System (RRNS) Chinese Remainder Theorem coder and orbit leap generator."""

from __future__ import annotations

from math import prod
from typing import Sequence


def primes_below(limit: int, count: int) -> list[int]:
    """Mathematics: compute the `count` largest prime numbers strictly below `limit` using an incremental sieve."""

    if limit < 3:
        return []
    sieve = bytearray([1]) * limit
    sieve[:2] = b"\0\0"
    for i in range(2, int(limit**0.5) + 1):
        if sieve[i]:
            sieve[i * i :: i] = bytearray(len(sieve[i * i :: i]))
    primes = [i for i in range(limit - 1, 1, -1) if sieve[i]]
    return primes[:count]


def crt(residues: Sequence[int], moduli: Sequence[int]) -> int:
    r"""Mathematics: Garner-free incremental Chinese Remainder Theorem evaluating `X \in [0, \prod m_i)` satisfying `X \equiv r_i \pmod{m_i}`."""

    if len(residues) != len(moduli):
        raise ValueError("residues and moduli sequences must have equal length")
    if not residues:
        return 0

    x = 0
    m_accum = 1
    for r, m in zip(residues, moduli):
        t = ((r - x) * pow(m_accum, -1, m)) % m
        x += m_accum * t
        m_accum *= m
    return x


def legit_range(moduli: Sequence[int], k: int) -> int:
    r"""Mathematics: calculate non-redundant information capacity `M = \prod_{i=1}^k m_i` over the `k` smallest moduli."""

    sorted_mods = sorted(moduli)
    return prod(sorted_mods[:k])


def encode_rrns(value: int, moduli: Sequence[int]) -> list[int]:
    r"""Mathematics: project integer `V \in [0, M)` onto residue vector `r_i = V \bmod m_i`."""

    return [value % m for m in moduli]


def recover_rrns(
    pairs: Sequence[tuple[int, int]],
    k: int,
    moduli_all: Sequence[int] | None = None,
) -> tuple[int | None, bool]:
    r"""Mathematics: reconstruct `V = \text{CRT}(\{r_i, m_i\}_{i=1}^k)` and verify consistency across all redundant pairs."""

    if len(pairs) < k:
        return (None, False)

    use = pairs[:k]
    mods_used = [m for m, _ in use]
    res_used = [r for _, r in use]

    v = crt(res_used, mods_used)

    consistent = True
    for m, r in pairs[k:]:
        if v % m != r:
            consistent = False
            break

    if moduli_all is not None and consistent:
        max_legit = legit_range(moduli_all, k)
        if v >= max_legit:
            consistent = False

    return (v, consistent)


def affine_orbit_jump(a: int, b: int, m: int, n: int) -> tuple[int, int]:
    r"""Mathematics: evaluate matrix exponentiation `\begin{pmatrix} a & b \\ 0 & 1 \end{pmatrix}^n` in `\mathcal{O}(\log n)` time, returning `(A, B)` such that `x_n = A x_0 + B \pmod m`."""

    big_a = 1
    big_b = 0
    pa = a % m
    pb = b % m

    exp = n
    while exp > 0:
        if exp & 1:
            big_a = (pa * big_a) % m
            big_b = (pa * big_b + pb) % m
        pa, pb = (pa * pa) % m, (pa * pb + pb) % m
        exp >>= 1

    return (big_a, big_b)
