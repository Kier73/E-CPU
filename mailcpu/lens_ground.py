"""LENS-001: typed, reversible 64-bit observation frames over E-CPU affine laws.

A lens is a finite value-coordinate representation P. The original observed
orbit is x(t) = P^-1(F(t)), where F is an existing 64-bit affine generator.
This module does not grant authority, claim universal inductive proof, or
replace Structural Memory's witness/admission/receipt machinery.
"""
from __future__ import annotations

from itertools import product
from typing import Any, Mapping, Sequence

from .law_certifier import (
    Law, Refused, find_coordinate_int, find_coordinate_lcg_adic,
    fit_affine, lcg_navigate,
)

WIDTH = 64
MODULUS = 1 << WIDTH
MASK = MODULUS - 1
FRAMES = (
    "gray.decode", "gray.encode", "bits.reverse", "bytes.reverse",
    "rotate.left.1", "rotate.right.1",
    "rotate.left.7", "rotate.right.7",
    "rotate.left.13", "rotate.right.13",
)
INVERSE = {
    "gray.decode": "gray.encode",
    "gray.encode": "gray.decode",
    "bits.reverse": "bits.reverse",
    "bytes.reverse": "bytes.reverse",
    **{f"rotate.left.{n}": f"rotate.right.{n}" for n in (1, 7, 13)},
    **{f"rotate.right.{n}": f"rotate.left.{n}" for n in (1, 7, 13)},
}


def _word(value: int, label: str) -> int:
    if type(value) is not int or not 0 <= value < MODULUS:
        raise ValueError(f"{label} must be an unsigned 64-bit integer")
    return value


def transform(value: int, frame: str) -> int:
    """Apply an explicitly whitelisted bijection to one unsigned word."""
    v = _word(value, "lens value")
    if frame not in INVERSE:
        raise ValueError(f"unsupported lens frame {frame!r}")
    if frame == "gray.encode":
        return v ^ (v >> 1)
    if frame == "gray.decode":
        for shift in (1, 2, 4, 8, 16, 32):
            v ^= v >> shift
        return v
    if frame == "bits.reverse":
        return int(f"{v:064b}"[::-1], 2)
    if frame == "bytes.reverse":
        return int.from_bytes(v.to_bytes(8, "little"), "big")
    direction, _, distance = frame.partition(".")[2].partition(".")
    amount = int(distance)
    if direction == "left":
        return ((v << amount) | (v >> (WIDTH - amount))) & MASK
    return ((v >> amount) | (v << (WIDTH - amount))) & MASK


def forward_frames(value: int, frames: Sequence[str]) -> int:
    """Observed value -> affine-law value."""
    for frame in frames:
        value = transform(value, frame)
    return value


def backward_frames(value: int, frames: Sequence[str]) -> int:
    """Affine-law value -> observed value."""
    for frame in reversed(frames):
        value = transform(value, INVERSE[frame])
    return value


def validate_lens_parameters(params: Mapping[str, Any], order: int = 1) -> None:
    """Validate the exact serializable ABI before Ground reconstruction."""
    if not isinstance(params, Mapping) or set(params) != {"width", "frames", "a", "c", "x0"}:
        raise ValueError("lens64 requires exactly width, frames, a, c, x0")
    if type(params["width"]) is not int or params["width"] != WIDTH or order != 1:
        raise ValueError("lens64 requires width 64 and order 1")
    frames = params["frames"]
    if not isinstance(frames, list) or not 1 <= len(frames) <= 2:
        raise ValueError("lens64 requires one or two whitelisted frame names")
    for frame in frames:
        if type(frame) is not str or frame not in INVERSE:
            raise ValueError("lens64 frame is not whitelisted")
    if len(frames) == 2 and INVERSE[frames[0]] == frames[1]:
        raise ValueError("lens64 adjacent cancelling frames are noncanonical")
    for field in ("a", "c", "x0"):
        _word(params[field], f"lens64.{field}")


def navigate_lens(params: Mapping[str, Any], coordinate: int) -> int:
    """Evaluate P^-1(F(t)) without materializing intermediate orbit states."""
    validate_lens_parameters(params)
    if type(coordinate) is not int or coordinate < 0:
        raise Refused("lens64 coordinate must be a non-negative integer")
    inner = lcg_navigate(params["a"], params["c"], MODULUS, params["x0"], coordinate)
    return backward_frames(inner, params["frames"])


def find_lens(params: Mapping[str, Any], target: int) -> int | None:
    """Bounded inverse: modular increment or full-period 2-adic affine only."""
    validate_lens_parameters(params)
    if type(target) is not int or not 0 <= target < MODULUS:
        return None
    inner = forward_frames(target, params["frames"])
    a, c, x0 = params["a"], params["c"], params["x0"]
    if a == 1:
        return find_coordinate_int(c, MODULUS, x0, inner)
    if a % 4 == 1 and c % 2 == 1:
        return find_coordinate_lcg_adic(a, c, MODULUS, x0, inner)
    raise Refused("lens64 direct inverse requires a modular increment or full-period 2-adic affine law")


def recover_lens_law(
    window: Sequence[int], truth: Sequence[int], *, max_depth: int = 2,
) -> Law:
    """Infer a framed affine law from training, then check each reserved probe.

    Models are constructed exclusively from the training window. The withheld
    suffix is used to select a fully agreeing model, not to fit coefficients.
    GROUND is a finite-witness verdict, not an all-coordinate mathematical proof.
    """
    if (
        type(max_depth) is not int or not 1 <= max_depth <= 2
        or len(window) < 16 or len(truth) < 8
        or any(type(v) is not int or not 0 <= v < MODULUS for v in (*window, *truth))
    ):
        return Law(family="tape", verdict="TAPE", residual=1.0)
    for depth in range(1, max_depth + 1):
        for frames in product(FRAMES, repeat=depth):
            if depth == 2 and INVERSE[frames[0]] == frames[1]:
                continue
            transformed = [forward_frames(v, frames) for v in window]
            fit = fit_affine(transformed, MODULUS)
            if fit is None:
                continue
            params = {
                "width": WIDTH, "frames": list(frames),
                "a": fit["a"], "c": fit["c"], "x0": transformed[0],
            }
            if all(navigate_lens(params, len(window) + i) == value for i, value in enumerate(truth)):
                return Law(family="lens64", params=params, order=1, verdict="GROUND")
    return Law(family="tape", verdict="TAPE", residual=1.0)
