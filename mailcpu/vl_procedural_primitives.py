"""Four-round Feistel address permutation used by MailCPU procedural addressing.

The construction is used only as a reversible address permutation over
non-cryptographic domains. It provides no confidentiality, no integrity, and no
compression. Its provenance, its non-copying boundary, and the conditions under
which it may be substituted are specified in `docs/BOUNDARY_PROCEDURAL_MODEL.md`.
"""

from __future__ import annotations

M32 = (1 << 32) - 1
M64 = (1 << 64) - 1
PHI32 = 0x9E3779B9
PHI64 = 0x9E3779B97F4A7C15


def _rotl32(value: int, shift: int) -> int:
    """Mathematics: rotate 32-bit word `v` by `s`, `ρ_s(v)=((v≪s)∨(v≫(32−s))) mod 2^32`."""

    shift &= 31
    value &= M32
    return value if shift == 0 else ((value << shift) | (value >> (32 - shift))) & M32


def _subkey(tau: int, seed: int, round_index: int) -> int:
    """Mathematics: derive round key `k_i=low32(finalizer(tau ⊕ (seed+i·φ64)))`."""

    value = (tau ^ (seed + round_index * PHI64)) & M64
    value ^= value >> 33
    value = (value * 0xFF51AFD7ED558CCD) & M64
    value ^= value >> 33
    return value & M32


def _round(right: int, key: int) -> int:
    """Mathematics: evaluate Feistel round function `F(r,k)=rotl13((r⊕k)·φ32)·c mod 2^32`."""

    value = ((right ^ key) * PHI32) & M32
    return (_rotl32(value, 13) * 0x517CC1B7) & M32


def feistel_seal(value: int, tau: int, seed: int) -> int:
    """Mathematics: apply four Feistel bijections `(L,R)↦(R,L⊕F(R,k_i))` over 64 bits."""

    left = (value >> 32) & M32
    right = value & M32
    for round_index in range(4):
        left, right = right, left ^ _round(right, _subkey(tau, seed, round_index))
    return ((right << 32) | left) & M64


def feistel_open(value: int, tau: int, seed: int) -> int:
    """Mathematics: invert `feistel_seal` in reverse key order, satisfying `open(seal(x))=x`."""

    right = (value >> 32) & M32
    left = value & M32
    for round_index in range(3, -1, -1):
        right, left = left, right ^ _round(left, _subkey(tau, seed, round_index))
    return ((left << 32) | right) & M64


def feistel_stream_byte(position: int, tau: int, seed: int) -> int:
    """Mathematics: expose byte `b_p = byte_{p mod 8}(seal(⌊p/8⌋))` for procedural storage."""

    if position < 0:
        raise ValueError("position must be non-negative")
    word = feistel_seal(position // 8, tau, seed)
    return (word >> (8 * (position % 8))) & 0xFF
