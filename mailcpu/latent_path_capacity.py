"""CAPACITY-001: recognize pre-existing state transition capacity in opaque paths.

The observed path does not implement E-CPU or expose its constituent hosts.
A finite exhaustive observation may establish a declared modular affine law;
E-CPU's EXISTING law navigator then resolves logical coordinates without
replaying all previous traversals. This is a mathematical relation over one
observed snapshot, not source authentication, universal inference or permission.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import re
from typing import Any, Callable, Mapping

from .law_certifier import lcg_navigate

SCHEMA = "mailcpu.latent-path-capacity.v1"
_HEX = re.compile(r"[0-9a-f]{64}\Z")
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}\Z")
_MAX_MODULUS = 257


class CapacityRefused(ValueError):
    """A proposed path relation cannot be verified at the declared scope."""


def _canonical(obj: object) -> bytes:
    try:
        return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise CapacityRefused("noncanonical evidence") from exc


def _hash(obj: object) -> str:
    return sha256(_canonical(obj)).hexdigest()


def _name(v: object, what: str) -> str:
    if type(v) is not str or _NAME.fullmatch(v) is None:
        raise CapacityRefused(f"{what} is not a bounded identifier")
    return v


def _digest(v: object, what: str) -> str:
    if type(v) is not str or _HEX.fullmatch(v) is None:
        raise CapacityRefused(f"{what} is not a 256-bit hex digest")
    return v


def _number(v: object, what: str, *, minimum: int = 0) -> int:
    if type(v) is not int or v < minimum:
        raise CapacityRefused(f"{what} is not a permitted integer")
    return v


@dataclass(frozen=True)
class CapacityCertificate:
    """A verified whole-domain modular relation over one observer-scoped snapshot.

    Distinguishes the mathematical Ground from the path evidence identity.
    Checking a certificate rechecks all included values; attributing values
    to a real path additionally requires independent trusted observation.
    """

    path_id: str
    snapshot_id: str
    context_digest: str
    modulus: int
    multiplier: int
    increment: int
    outputs: tuple[int, ...]
    ground_digest: str
    evidence_digest: str

    def __post_init__(self) -> None:
        _name(self.path_id, "path_id")
        _name(self.snapshot_id, "snapshot_id")
        _digest(self.context_digest, "context_digest")
        m = _number(self.modulus, "modulus", minimum=2)
        if m > _MAX_MODULUS:
            raise CapacityRefused("capacity scan exceeds finite observation budget")
        a = _number(self.multiplier, "multiplier")
        b = _number(self.increment, "increment")
        if a >= m or b >= m:
            raise CapacityRefused("operator coefficients must be canonical")
        if type(self.outputs) is not tuple or len(self.outputs) != m:
            raise CapacityRefused("certificate lacks complete domain coverage")
        if any(type(z) is not int or z < 0 or z >= m for z in self.outputs):
            raise CapacityRefused("output outside the declared finite Ground")
        if any(self.outputs[x] != (a * x + b) % m for x in range(m)):
            raise CapacityRefused("finite path observations contradict the proposed law")
        if self.outputs[0] != b or self.outputs[1] != (a + b) % m:
            raise CapacityRefused("candidate inference is inconsistent")
        if self.ground_digest != self.expected_ground_digest:
            raise CapacityRefused("mathematical Ground identity is inconsistent")
        if self.evidence_digest != self.expected_evidence_digest:
            raise CapacityRefused("path observation identity is inconsistent")

    @property
    def expected_ground_digest(self) -> str:
        return _hash({"kind": "finite-affine-transit", "version": 1,
                      "modulus": self.modulus, "a": self.multiplier,
                      "b": self.increment})

    @property
    def expected_evidence_digest(self) -> str:
        return _hash({"schema": SCHEMA, "path_id": self.path_id,
                      "snapshot_id": self.snapshot_id,
                      "context_digest": self.context_digest,
                      "ground_digest": self.ground_digest,
                      "outputs": list(self.outputs)})

    @property
    def coverage(self) -> str:
        return "whole_declared_finite_domain_one_snapshot"

    def state_at(self, initial: int, tick: int) -> int:
        """Navigate a mathematically modeled orbit, not an unobserved live path."""
        x = _number(initial, "initial")
        _number(tick, "tick")
        if x >= self.modulus:
            raise CapacityRefused("initial lies outside the declared Ground")
        return lcg_navigate(self.multiplier, self.increment, self.modulus, x, tick)

    def to_dict(self) -> dict[str, Any]:
        return {"schema": SCHEMA, "path_id": self.path_id,
                "snapshot_id": self.snapshot_id,
                "context_digest": self.context_digest,
                "modulus": self.modulus,
                "multiplier": self.multiplier, "increment": self.increment,
                "outputs": list(self.outputs),
                "ground_digest": self.ground_digest,
                "evidence_digest": self.evidence_digest,
                "coverage": self.coverage}

    @classmethod
    def from_dict(cls, obj: Mapping[str, Any]) -> "CapacityCertificate":
        expected = {"schema", "path_id", "snapshot_id", "context_digest",
                    "modulus", "multiplier", "increment", "outputs",
                    "ground_digest", "evidence_digest", "coverage"}
        if not isinstance(obj, Mapping) or set(obj) != expected:
            raise CapacityRefused("capacity certificate has wrong fields")
        if obj["schema"] != SCHEMA or obj["coverage"] != "whole_declared_finite_domain_one_snapshot":
            raise CapacityRefused("wrong capacity certificate schema or scope")
        if type(obj["outputs"]) is not list:
            raise CapacityRefused("outputs must be a canonical array")
        return cls(path_id=obj["path_id"], snapshot_id=obj["snapshot_id"],
                   context_digest=obj["context_digest"], modulus=obj["modulus"],
                   multiplier=obj["multiplier"], increment=obj["increment"],
                   outputs=tuple(obj["outputs"]), ground_digest=obj["ground_digest"],
                   evidence_digest=obj["evidence_digest"])


def recognize_capacity(
    transmit: Callable[[int], int], *, path_id: str, snapshot_id: str,
    context_digest: str, modulus: int,
) -> CapacityCertificate:
    """Observe the complete finite input domain of an E-CPU-unaware path.

    Not every finite transition function is affine. A nonlinear path refuses,
    rather than extrapolating an affine hypothesis from probes 0 and 1.
    The supplied callback is an observer-owned test interface, not an E-CPU
    installation or a receiver authority. Callers must control its provenance.
    """
    _name(path_id, "path_id")
    _name(snapshot_id, "snapshot_id")
    _digest(context_digest, "context_digest")
    m = _number(modulus, "modulus", minimum=2)
    if m > _MAX_MODULUS:
        raise CapacityRefused("cannot exhaustively observe a larger finite Ground")
    if not callable(transmit):
        raise CapacityRefused("no observable path relation")
    outputs: list[int] = []
    for x in range(m):
        y = transmit(x)
        if type(y) is not int or not 0 <= y < m:
            raise CapacityRefused("path observation is outside the Ground")
        outputs.append(y)
    b = outputs[0]
    a = (outputs[1] - b) % m
    ground = _hash({"kind": "finite-affine-transit", "version": 1,
                    "modulus": m, "a": a, "b": b})
    evidence = _hash({"schema": SCHEMA, "path_id": path_id,
                      "snapshot_id": snapshot_id,
                      "context_digest": context_digest,
                      "ground_digest": ground, "outputs": outputs})
    return CapacityCertificate(path_id, snapshot_id, context_digest, m, a, b,
                               tuple(outputs), ground, evidence)


def verify_live_capacity(
    certificate: CapacityCertificate, transmit: Callable[[int], int], *,
    snapshot_id: str, context_digest: str,
) -> bool:
    """Reobserve the exact finite domain; refuse if context or snapshot changed."""
    if not isinstance(certificate, CapacityCertificate):
        raise CapacityRefused("requires a verified finite certificate")
    if snapshot_id != certificate.snapshot_id or context_digest != certificate.context_digest:
        raise CapacityRefused("observation snapshot or context has changed")
    if not callable(transmit):
        raise CapacityRefused("path is not presently observable")
    for x, y in enumerate(certificate.outputs):
        z = transmit(x)
        if type(z) is not int or z != y:
            raise CapacityRefused("current path no longer matches admitted relation")
    return True