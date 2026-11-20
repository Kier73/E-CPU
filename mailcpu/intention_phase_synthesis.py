"""IPS-001: intention-first future communication-slot synthesis.

A declared periodic window is a *hypothesis*, not evidence. This module uses
exact modular constraints to construct an earliest feasible coordinate without
stepping through time. A native EvidencePathResolver must first qualify the
route under the receiver's live permissions. Neither result executes packets,
reserves slots, nor verifies physical future availability.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import gcd
import re
from typing import Any, Sequence

from .evidence_path_resolver import (
    EvidencePathCatalogue, EvidencePathRequest, EvidencePathResolver,
    EvidencePathStatus,
)
from .headless import HeadlessOS
from .semantic_translation import canonical_value_digest

_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_MAX_TICK = (1 << 63) - 1
_MAX_HOPS = 32
_MAX_PHASES = 64
_MAX_PERIOD = 1_000_000_000
_MAX_CLASSES = 4096


class PhaseSynthesisError(ValueError):
    """The finite intention, clock, proposed window, or proof is invalid."""


def _digest(value: Any, label: str) -> None:
    """Check an exact lowercase SHA-256 identifier, not its authenticity."""
    if type(value) is not str or _DIGEST.fullmatch(value) is None:
        raise PhaseSynthesisError(f"invalid {label} digest")


def _tick(value: Any, label: str, *, minimum: int = 0) -> None:
    """Require a bounded non-boolean logical scheduler coordinate."""
    if type(value) is not int or not minimum <= value <= _MAX_TICK:
        raise PhaseSynthesisError(f"invalid {label}")


@dataclass(frozen=True)
class CommunicationIntention:
    """Desired payload and arrival condition, tied to a route query and clock."""

    request_digest: str
    clock_digest: str
    not_before: int
    arrive_by: int
    payload_bytes: int
    max_transit_ticks: int

    def __post_init__(self) -> None:
        """Keep the requested feasible interval and semantics unambiguous."""
        _digest(self.request_digest, "route request")
        _digest(self.clock_digest, "scheduler clock")
        _tick(self.not_before, "earliest start")
        _tick(self.arrive_by, "arrival deadline", minimum=self.not_before)
        _tick(self.payload_bytes, "payload bytes", minimum=1)
        _tick(self.max_transit_ticks, "transit ceiling", minimum=1)

    @property
    def digest(self) -> str:
        """Identify every aspect of the receiver's requested virtual state."""
        return canonical_value_digest(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        """Serialize the intention independently of any candidate schedule."""
        return {"request_digest": self.request_digest, "clock_digest": self.clock_digest,
                "not_before": self.not_before, "arrive_by": self.arrive_by,
                "payload_bytes": self.payload_bytes, "max_transit_ticks": self.max_transit_ticks}


@dataclass(frozen=True)
class PeriodicCommunicationWindow:
    """Receiver-supplied schedule hypothesis for one qualified path edge.

    Edge accepts an entry at scheduler tick t iff t % period is in phases.
    The complete transfer occupies [t,t+transit_ticks), in one common logical
    clock. The declared lease covers that whole interval. Capacity is a
    declared per-transfer bound, NOT observed throughput or reservation.
    """

    edge_id: str
    clock_digest: str
    schedule_ground_digest: str
    period: int
    phases: tuple[int, ...]
    transit_ticks: int
    capacity_bytes: int
    valid_from: int
    valid_through: int

    def __post_init__(self) -> None:
        """Reject ambiguous phases, clockless schedules and invalid leases."""
        for label in ("edge_id", "clock_digest", "schedule_ground_digest"):
            _digest(getattr(self, label), label)
        _tick(self.period, "period", minimum=1)
        if self.period > _MAX_PERIOD:
            raise PhaseSynthesisError("period exceeds exact finite policy")
        _tick(self.transit_ticks, "transfer duration", minimum=1)
        _tick(self.capacity_bytes, "transfer capacity", minimum=1)
        _tick(self.valid_from, "lease start")
        _tick(self.valid_through, "lease end", minimum=self.valid_from)
        if (type(self.phases) is not tuple or not 1 <= len(self.phases) <= _MAX_PHASES
                or len(set(self.phases)) != len(self.phases)
                or any(type(p) is not int or not 0 <= p < self.period for p in self.phases)
                or tuple(sorted(self.phases)) != self.phases):
            raise PhaseSynthesisError("phases must be unique sorted residues")

    @property
    def digest(self) -> str:
        """Identify the supplied schedule hypothesis, not a measured path."""
        return canonical_value_digest(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        """Preserve window identity and its qualification-independent values."""
        return {"edge_id": self.edge_id, "clock_digest": self.clock_digest,
                "schedule_ground_digest": self.schedule_ground_digest,
                "period": self.period, "phases": list(self.phases),
                "transit_ticks": self.transit_ticks, "capacity_bytes": self.capacity_bytes,
                "valid_from": self.valid_from, "valid_through": self.valid_through}


@dataclass(frozen=True)
class PhaseSynthesisResult:
    """Replayable, non-authoritative possibility witness or explicit refusal."""

    status: str
    intention_digest: str
    route_digest: str | None
    window_digests: tuple[str, ...]
    start_tick: int | None = None
    arrival_tick: int | None = None
    edge_entry_ticks: tuple[tuple[str, int], ...] = ()
    solution_residue: int | None = None
    solution_period: int | None = None
    detail: str = ""

    @property
    def authoritative(self) -> bool:
        """A mathematical proposal never grants network execution authority."""
        return False

    @property
    def digest(self) -> str:
        """Bind the result to the intention, route, hypotheses and witness."""
        return canonical_value_digest(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        """Serialize an exact, reproducible proposal without implied authority."""
        return {"schema": "mailcpu.intention-phase-synthesis.v1", "authoritative": False,
                "status": self.status, "intention_digest": self.intention_digest,
                "route_digest": self.route_digest, "window_digests": list(self.window_digests),
                "start_tick": self.start_tick, "arrival_tick": self.arrival_tick,
                "edge_entry_ticks": [[k, v] for k, v in self.edge_entry_ticks],
                "solution_residue": self.solution_residue,
                "solution_period": self.solution_period, "detail": self.detail}


def _crt(a: int, m: int, b: int, n: int) -> tuple[int, int] | None:
    """Construct exact intersection of two possibly non-coprime congruences."""
    g = gcd(m, n)
    if (b - a) % g:
        return None
    q = n // g
    k = ((b - a) // g * pow(m // g, -1, q)) % q if q != 1 else 0
    modulus = m * q
    return (a + m * k) % modulus, modulus


def _synthesize_math(
    intention: CommunicationIntention,
    edge_ids: tuple[str, ...],
    windows: Sequence[PeriodicCommunicationWindow],
    route_digest: str,
    *,
    max_classes: int = _MAX_CLASSES,
) -> PhaseSynthesisResult:
    """Solve the inverse slot constraints without enumerating intermediate ticks.

    This internal function assumes a route has already been qualified by the
    native resolver; only `synthesize_communication_state` should expose it.
    """
    if type(max_classes) is not int or not 1 <= max_classes <= _MAX_CLASSES:
        raise PhaseSynthesisError("invalid class budget")
    _digest(route_digest, "route result")
    if not 1 <= len(edge_ids) <= _MAX_HOPS or len(set(edge_ids)) != len(edge_ids):
        raise PhaseSynthesisError("expected 1..32 unique qualified route edges")
    for edge_id in edge_ids:
        _digest(edge_id, "edge")
    if any(not isinstance(w, PeriodicCommunicationWindow) for w in windows):
        raise PhaseSynthesisError("untyped schedule window")
    if len(windows) != len(edge_ids) or {w.edge_id for w in windows} != set(edge_ids):
        return PhaseSynthesisResult("undetermined", intention.digest, route_digest, (),
                                    detail="missing, extra, or duplicate route schedule")
    mapped = {w.edge_id: w for w in windows}
    ordered = tuple(mapped[edge_id] for edge_id in edge_ids)
    digests = tuple(w.digest for w in ordered)
    if (any(w.clock_digest != intention.clock_digest for w in ordered)
            or len({w.schedule_ground_digest for w in ordered}) != 1):
        return PhaseSynthesisResult("undetermined", intention.digest, route_digest, digests,
                                    detail="incommensurate logical clocks or schedule Grounds")
    def result(status: str, detail: str = "") -> PhaseSynthesisResult:
        """Construct a refusal with the exact hypotheses that produced it."""
        return PhaseSynthesisResult(status, intention.digest, route_digest, digests, detail=detail)

    if any(w.capacity_bytes < intention.payload_bytes for w in ordered):
        return result("impossible_under_description", "declared capacity below requested payload")
    duration = sum(w.transit_ticks for w in ordered)
    if duration > intention.max_transit_ticks:
        return result("impossible_under_description", "declared path exceeds transit ceiling")
    low = intention.not_before
    high = intention.arrive_by - duration
    offsets: list[int] = []
    offset = 0
    for w in ordered:
        offsets.append(offset)
        low = max(low, w.valid_from - offset)
        high = min(high, w.valid_through - offset - w.transit_ticks + 1)
        offset += w.transit_ticks
    if low > high:
        return result("impossible_under_description", "no common leased arrival interval")

    classes: set[tuple[int, int]] = {(0, 1)}
    for w, offset in zip(ordered, offsets):
        next_classes: set[tuple[int, int]] = set()
        for residue, modulus in sorted(classes):
            for phase in w.phases:
                merged = _crt(residue, modulus, (phase - offset) % w.period, w.period)
                if merged is not None:
                    next_classes.add(merged)
                    if len(next_classes) > max_classes:
                        return result("budget_exhausted", "residue-class budget exceeded")
        if not next_classes:
            return result("impossible_under_description", "incompatible schedule phases")
        classes = next_classes

    choices = []
    for residue, modulus in classes:
        tick = residue + max(0, (low - residue + modulus - 1) // modulus) * modulus
        if tick <= high:
            choices.append((tick, residue, modulus))
    if not choices:
        return result("impossible_under_description", "no acceptable future coordinate")
    start, residue, period = min(choices)
    entries = tuple((edge_id, start + offset) for edge_id, offset in zip(edge_ids, offsets))
    return PhaseSynthesisResult(
        "possible_under_description", intention.digest, route_digest, digests,
        start, start + duration, entries, residue, period,
        "exact schedule coordinates; admission and future observation remain required")


def synthesize_communication_state(
    intention: CommunicationIntention,
    windows: Sequence[PeriodicCommunicationWindow],
    catalogue: EvidencePathCatalogue,
    request: EvidencePathRequest,
    operating_system: HeadlessOS,
    pid: int,
    *,
    max_classes: int = _MAX_CLASSES,
) -> PhaseSynthesisResult:
    """Qualify the route through native EvidencePathResolver before synthesis.

    Never accept caller-forged route results or capability flags. Native
    authority is checked *at planning time* and must be rechecked at dispatch.
    A successful result describes possible windows, not observed availability.
    """
    if not isinstance(intention, CommunicationIntention) or not isinstance(request, EvidencePathRequest):
        raise PhaseSynthesisError("typed intention and native route request required")
    if intention.request_digest != request.digest:
        raise PhaseSynthesisError("intention targets a different route request")
    native = EvidencePathResolver().resolve(catalogue, request, operating_system, pid)
    if native.status is not EvidencePathStatus.FOUND:
        return PhaseSynthesisResult("unqualified", intention.digest, native.digest, (),
                                    detail=f"native route status: {native.status.value}")
    return _synthesize_math(intention, native.edge_ids, windows, native.digest,
                            max_classes=max_classes)


def verify_communication_synthesis(
    expected: PhaseSynthesisResult,
    intention: CommunicationIntention,
    windows: Sequence[PeriodicCommunicationWindow],
    catalogue: EvidencePathCatalogue,
    request: EvidencePathRequest,
    operating_system: HeadlessOS,
    pid: int,
    *,
    max_classes: int = _MAX_CLASSES,
) -> bool:
    """Recompute under current native evidence and live rights; reject stale plans."""
    if not isinstance(expected, PhaseSynthesisResult):
        raise PhaseSynthesisError("expected typed synthesis result")
    return expected == synthesize_communication_state(
        intention, windows, catalogue, request, operating_system, pid,
        max_classes=max_classes)
