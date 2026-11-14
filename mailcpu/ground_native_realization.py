"""SAB-008: one Ground-native observation across multiple substrate realizers.

The semantics are defined by a Ground and observer predicate, not by a machine
architecture. Every realizer has a receiver-owned binding and explicit policy.
Content digests check integrity, never the identity or honesty of remote hosts.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Mapping

from .runtime_qualification import (
    REQUEST_KIND, QualificationEndpoint, QualificationPolicy, QualificationRefused,
    _check_response, affine_expected, canonical, digest, verify_report,
)

SCHEMA = "mailcpu.sab008.ground-native-realization.v1"
MAX_COORDINATE = 10**18


class RealizationRefused(ValueError):
    """A resource, observation, authority, frame, or evidence is inadmissible."""


def _integer(value: Any, name: str, minimum: int = 0, maximum: int = MAX_COORDINATE) -> int:
    """Require a strict bounded integer; Boolean values are not coordinates."""
    if type(value) is not int or not minimum <= value <= maximum:
        raise RealizationRefused(f"invalid {name}")
    return value


def _name(value: Any, name: str) -> str:
    """Accept only short explicit host or request identifiers."""
    if (type(value) is not str or not 1 <= len(value) <= 100
            or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._:-" for c in value)):
        raise RealizationRefused(f"invalid {name}")
    return value


@dataclass(frozen=True)
class AffineGround:
    """Host-independent finite law: x(t+1) = (a*x(t)+c) mod modulus."""

    a: int
    c: int
    modulus: int
    seed: int

    def __post_init__(self) -> None:
        """Validate every parameter inside the bounded integer Ground."""
        _integer(self.modulus, "modulus", 2, 2**31 - 1)
        for field in ("a", "c", "seed"):
            _integer(getattr(self, field), field, 0, self.modulus - 1)

    @property
    def fingerprint(self) -> str:
        """Identify mathematical meaning without naming a realizer or substrate."""
        return digest({"schema": SCHEMA + ".ground", "family": "affine_mod",
                       "a": self.a, "c": self.c, "mod": self.modulus, "seed": self.seed})

    def input(self, coordinate: int) -> dict[str, int]:
        """Construct a canonical, host-independent evaluation input."""
        _integer(coordinate, "coordinate")
        return {"a": self.a, "c": self.c, "mod": self.modulus,
                "x0": self.seed, "coordinate": coordinate}


@dataclass(frozen=True)
class GroundIntention:
    """A single requested observer projection at a coordinate in a Ground."""

    request_id: str
    ground: AffineGround
    coordinate: int
    observation: str = "value"

    def __post_init__(self) -> None:
        """Exclude physical placement from semantic identity."""
        _name(self.request_id, "request identity")
        if not isinstance(self.ground, AffineGround):
            raise RealizationRefused("intention requires a typed Ground")
        _integer(self.coordinate, "coordinate")
        if self.observation != "value":
            raise RealizationRefused("unsupported observer projection")

    @property
    def fingerprint(self) -> str:
        """Bind exact law, observation, logical coordinate, and request identity."""
        return digest({"schema": SCHEMA + ".intention", "request": self.request_id,
                       "ground": self.ground.fingerprint, "coordinate": self.coordinate,
                       "observation": self.observation})


def independent_observation(intention: GroundIntention) -> int:
    """Verify by binary affine composition independently of the chosen realizer."""
    p, q, mul, add, n = 1, 0, intention.ground.a, intention.ground.c, intention.coordinate
    modulus = intention.ground.modulus
    while n:
        if n & 1:
            p, q = (p * mul) % modulus, (q * mul + add) % modulus
        mul, add = (mul * mul) % modulus, (add * (mul + 1)) % modulus
        n >>= 1
    value = (p * intention.ground.seed + q) % modulus
    other = affine_expected(intention.ground.a, intention.ground.c,
                            modulus, intention.ground.seed, intention.coordinate)
    if value != other:
        raise RealizationRefused("Ground evaluators disagree")
    return value


@dataclass(frozen=True)
class RealizationPolicy:
    """Local permission to request an operation; not remote Hypervisor authority."""

    allowed: frozenset[tuple[str, str]]
    expires_at: int
    max_events: int = 256
    max_bytes: int = 4096

    def __post_init__(self) -> None:
        """Ensure permits are exact and observations are bounded."""
        _integer(self.expires_at, "permission expiry")
        _integer(self.max_events, "event budget", 1, 2048)
        _integer(self.max_bytes, "frame budget", 256, 8192)
        if not isinstance(self.allowed, frozenset) or not self.allowed:
            raise RealizationRefused("local permission set is empty")
        for pair in self.allowed:
            if (not isinstance(pair, tuple) or len(pair) != 2
                    or _name(pair[0], "locus") != pair[0]
                    or pair[1] not in {"port", "interpreter", "federated"}):
                raise RealizationRefused("invalid local realizer permission")

    def permits(self, locus: str, method: str, coordinate: int) -> None:
        """Refuse missing or expired exact local permission before touching a host."""
        if (locus, method) not in self.allowed or coordinate > self.expires_at:
            raise RealizationRefused("realizer is not permitted at requested coordinate")

    @property
    def fingerprint(self) -> str:
        """Bind the local grant independently of host-supplied advertisements."""
        return digest({"allowed": [list(p) for p in sorted(self.allowed)],
                       "expiry": self.expires_at, "max_events": self.max_events,
                       "max_bytes": self.max_bytes})


@dataclass(frozen=True)
class RealizationReceipt:
    """One internally consistent observation, not a cryptographically signed claim."""

    payload: dict[str, Any]

    @property
    def fingerprint(self) -> str:
        """Return the digest of this complete realization record."""
        return str(self.payload["receipt_digest"])

