"""SAB-002: bounded, permissioned discovery of navigable Grounds from host observations.

A code/data environment supplies an *observation callback*, not executable
source. A finite witness may ground a candidate law but never prove it for all
coordinates or grant authority. Only local policy may bind a trusted navigator
into SAB-001's observer-host graph.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
import subprocess
from typing import Any, Callable, Mapping

from .substrate_bootstrap import (
    BootstrapRefused, OperationOffer, RealizerBinding, ResourceObservation,
    digest, name, natural, sha,
)

PROBE_COORDINATES = (0, 1, 2, 3, 7, 11, 19, 7)
MAX_COORDINATE = 10**18


class DiscoveryRefused(BootstrapRefused):
    """A probe, witness, local admission or navigable law failed its contract."""


def _int(value: Any, what: str, *, floor: int = 0, ceiling: int = MAX_COORDINATE) -> int:
    """Reject booleans, signed overflows, and out-of-domain probe coordinates."""
    if type(value) is not int or not floor <= value <= ceiling:
        raise DiscoveryRefused(f"invalid {what}")
    return value


def _affine_pow(a: int, c: int, mod: int, x0: int, t: int) -> int:
    """Independent affine-map binary composition: F^t(x)=p*x+q (mod m)."""
    p, q = 1, 0
    mul, add = a, c
    while t:
        if t & 1:
            p, q = (mul * p) % mod, (mul * q + add) % mod
        add = (mul * add + add) % mod
        mul = (mul * mul) % mod
        t >>= 1
    return (p * x0 + q) % mod


@dataclass(frozen=True)
class ObservedCodeHost:
    """One explicitly reachable observer; labels do not qualify computation."""

    host_id: str
    substrate_hint: str
    modulus: int
    observer_id: str
    expires_at: int
    observe: Callable[[int], int]

    def __post_init__(self) -> None:
        """Require a bounded, callable observation interface and a finite domain."""
        for tag in ("host_id", "substrate_hint", "observer_id"):
            name(getattr(self, tag), tag)
        _int(self.modulus, "modulus", floor=2, ceiling=2**31 - 1)
        natural(self.expires_at, "expiry")
        if not callable(self.observe):
            raise DiscoveryRefused("observation callback must be locally installed")


@dataclass(frozen=True)
class ProbeAuthority:
    """Explicit local probe permissions and fixed quota; not remote consent."""

    allowed_hosts: frozenset[str]
    observer_id: str
    max_probes: int = len(PROBE_COORDINATES)
    max_coordinate: int = MAX_COORDINATE

    def __post_init__(self) -> None:
        """Check authority labels and safe resource ceilings before any observation."""
        name(self.observer_id, "observer identity")
        for host_id in self.allowed_hosts:
            name(host_id, "allowed host")
        _int(self.max_probes, "probe budget", floor=len(PROBE_COORDINATES), ceiling=32)
        _int(self.max_coordinate, "maximum coordinate", floor=19)


@dataclass(frozen=True)
class GroundCandidate:
    """A finite-witness affine law with exact host and transcript provenance."""

    host_id: str
    substrate_hint: str
    observer_id: str
    observed_at: int
    expires_at: int
    modulus: int
    x0: int
    a: int
    c: int
    witness: tuple[tuple[int, int], ...]
    transcript_digest: str
    verification: str = "finite_witness_only"

    def __post_init__(self) -> None:
        """Validate the witness, inferred law and finite empirical evidence grade."""
        for tag in ("host_id", "substrate_hint", "observer_id"):
            name(getattr(self, tag), tag)
        natural(self.observed_at, "observation time")
        natural(self.expires_at, "expiry")
        if self.expires_at < self.observed_at:
            raise DiscoveryRefused("expired candidate")
        _int(self.modulus, "modulus", floor=2, ceiling=2**31 - 1)
        for label in ("x0", "a", "c"):
            _int(getattr(self, label), label, ceiling=self.modulus - 1)
        sha(self.transcript_digest, "transcript")
        if self.verification != "finite_witness_only" or len(self.witness) != len(PROBE_COORDINATES):
            raise DiscoveryRefused("candidate must retain the complete finite witness")
        for (coordinate, value), expected in zip(self.witness, PROBE_COORDINATES):
            if coordinate != expected or _int(value, "witness value", ceiling=self.modulus - 1) != value:
                raise DiscoveryRefused("witness coordinate or value mismatch")
            if _affine_pow(self.a, self.c, self.modulus, self.x0, coordinate) != value:
                raise DiscoveryRefused("candidate law contradicts a witness")
        if self.transcript_digest != digest(self.transcript()):
            raise DiscoveryRefused("candidate transcript digest mismatch")

    def transcript(self) -> dict[str, Any]:
        """Serialize the exact host identity and ordered sample outcomes."""
        return {"host": self.host_id, "observer": self.observer_id,
                "observed_at": self.observed_at, "modulus": self.modulus,
                "samples": [list(x) for x in self.witness]}

    @property
    def ground_digest(self) -> str:
        """Identify the law independent of the host currently realizing it."""
        return digest({"family": "affine_mod", "modulus": self.modulus,
                       "x0": self.x0, "a": self.a, "c": self.c})

    def navigate(self, coordinate: int) -> int:
        """Navigate a candidate directly; this does not authorize execution."""
        _int(coordinate, "navigation coordinate")
        from .law_certifier import lcg_navigate
        return lcg_navigate(self.a, self.c, self.modulus, self.x0, coordinate)

    def to_resource(self, *, cost: int = 3) -> ResourceObservation:
        """Advertise the locally recognized transition as an untrusted offer."""
        natural(cost, "declared quanta", 1)
        return ResourceObservation(self.host_id, self.substrate_hint,
                                   self.observed_at, self.expires_at, self.observer_id,
                                   digest({"law": self.ground_digest, "transcript": self.transcript_digest}),
                                   (OperationOffer("navigate.affine_mod", "ground_query", "state_observation", cost),))


@dataclass(frozen=True)
class GroundAdmission:
    """Receiver-owned permission for a particular host and mathematical Ground."""

    allowed_host_grounds: frozenset[tuple[str, str]]
    authority_id: str

    def __post_init__(self) -> None:
        """Require explicit exact (host, law) tuples; wildcard admissions are absent."""
        name(self.authority_id, "authority")
        for host, ground in self.allowed_host_grounds:
            name(host, "admitted host")
            sha(ground, "admitted Ground")

    def bind(self, candidate: GroundCandidate, *, coordinate: int) -> RealizerBinding:
        """Bind trusted E-CPU navigation only for the locally admitted exact law."""
        natural(coordinate, "admission coordinate")
        if (candidate.host_id, candidate.ground_digest) not in self.allowed_host_grounds:
            raise DiscoveryRefused("candidate Ground lacks receiver admission")
        if not candidate.observed_at <= coordinate <= candidate.expires_at:
            raise DiscoveryRefused("candidate observation expired")

        def compute(value: Any) -> dict[str, int]:
            """Apply a locally trusted navigator to a content-pinned Ground query."""
            if not isinstance(value, Mapping) or set(value) != {"ground", "coordinate"}:
                raise DiscoveryRefused("navigation requires exact Ground and coordinate")
            if value["ground"] != candidate.ground_digest:
                raise DiscoveryRefused("navigation target Ground differs from admission")
            t = _int(value["coordinate"], "navigation coordinate")
            return {"coordinate": t, "value": candidate.navigate(t)}

        def check(value: Any, result: Any) -> bool:
            """Independently compose the affine law and compare the entire result."""
            if not isinstance(value, Mapping) or set(value) != {"ground", "coordinate"}:
                return False
            if value["ground"] != candidate.ground_digest:
                return False
            try:
                t = _int(value["coordinate"], "verification coordinate")
            except DiscoveryRefused:
                return False
            return result == {"coordinate": t, "value": _affine_pow(
                candidate.a, candidate.c, candidate.modulus, candidate.x0, t)}

        return RealizerBinding(candidate.host_id, "navigate.affine_mod", compute,
                               digest({"impl": "local-ecpu-lcg-navigator-v1",
                                       "ground": candidate.ground_digest}), check)


def discover(host: ObservedCodeHost, authority: ProbeAuthority, *, coordinate: int) -> GroundCandidate:
    """Run fixed active probes; derive affine law; reject ambiguous or contradicted fits.

    This witnesses an admissible *candidate* only; success is not a universal
    mathematical proof or a grant of remote execution rights.
    """
    natural(coordinate, "observation coordinate")
    if host.host_id not in authority.allowed_hosts or host.observer_id != authority.observer_id:
        raise DiscoveryRefused("host is not within local probe authorization")
    if coordinate > host.expires_at or authority.max_coordinate < max(PROBE_COORDINATES):
        raise DiscoveryRefused("observation expired or probe domain unavailable")
    if len(PROBE_COORDINATES) > authority.max_probes:
        raise DiscoveryRefused("probe budget exhausted")
    samples = []
    for index in PROBE_COORDINATES:
        try:
            observed = host.observe(index)
        except Exception as exc:
            raise DiscoveryRefused("observer failed a bounded coordinate query") from exc
        samples.append((index, _int(observed, "observed value", ceiling=host.modulus - 1)))
    x0, x1, x2 = (samples[i][1] for i in range(3))
    d0 = (x1 - x0) % host.modulus
    d1 = (x2 - x1) % host.modulus
    if math.gcd(d0, host.modulus) != 1:
        raise DiscoveryRefused("affine parameters cannot be uniquely inferred from this trace")
    a = (d1 * pow(d0, -1, host.modulus)) % host.modulus
    c = (x1 - a * x0) % host.modulus
    transcript = {"host": host.host_id, "observer": host.observer_id,
                  "observed_at": coordinate, "modulus": host.modulus,
                  "samples": [list(x) for x in samples]}
    return GroundCandidate(host.host_id, host.substrate_hint, host.observer_id,
                           coordinate, host.expires_at, host.modulus, x0, a, c,
                           tuple(samples), digest(transcript))


class SubprocessObserver:
    """Bounded JSON-line adapter to a locally permitted external interpreter."""

    def __init__(self, command: tuple[str, ...], host_id: str, *, timeout: float = 5.0) -> None:
        """Bind trusted launch configuration; the remote response is still checked."""
        if not command or any(type(x) is not str or not x for x in command):
            raise DiscoveryRefused("subprocess command must be a nonempty explicit argv")
        name(host_id, "worker host")
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 30:
            raise DiscoveryRefused("invalid subprocess timeout")
        self.command = command
        self.host_id = host_id
        self.timeout = timeout

    def observe(self, coordinate: int) -> int:
        """Read one isolated process observation with exact identity and request echo."""
        _int(coordinate, "worker coordinate")
        message = json.dumps({"kind": "sab002.observe", "host": self.host_id,
                              "coordinate": coordinate}, sort_keys=True) + "\n"
        try:
            result = subprocess.run(self.command, input=message, text=True, capture_output=True,
                                    timeout=self.timeout, check=False, shell=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise DiscoveryRefused("worker did not complete within its local execution contract") from exc
        if result.returncode or len(result.stdout) > 4096:
            raise DiscoveryRefused("worker did not return a bounded successful observation")
        try:
            envelope = json.loads(result.stdout)
        except (ValueError, TypeError) as exc:
            raise DiscoveryRefused("worker returned invalid JSON") from exc
        if (type(envelope) is not dict or set(envelope) != {"kind", "host", "coordinate", "value"}
                or envelope["kind"] != "sab002.observation" or envelope["host"] != self.host_id
                or envelope["coordinate"] != coordinate):
            raise DiscoveryRefused("worker observation identity or coordinate mismatch")
        return _int(envelope["value"], "worker observation")
