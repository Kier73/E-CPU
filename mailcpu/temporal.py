"""Typed temporal coordinates for local processes and distributed causal paths.

The module keeps physical wall time, process-local monotonic time, distributed
causal time, virtual scheduler ticks, and MailCPU's existing SystemEpoch
coordinates separate. It deliberately defines no conversion between them.
"""

from __future__ import annotations

import hashlib
import json
import math
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Mapping

from .chemical_time import SystemEpoch


_FORMAT = "mailcpu-temporal-context-v1"


class TemporalError(ValueError):
    """A temporal coordinate, clock profile, causal update, or checkpoint is invalid."""


class ClockUnavailableError(TemporalError):
    """A process attempted to use a clock domain not declared in its profile."""


class ClockRegressionError(TemporalError):
    """A process-local monotonic clock returned a value lower than its previous sample."""


class CausalClockError(TemporalError):
    """A causal stamp is malformed or cannot be merged into this process clock."""


class ClockDomain(str, Enum):
    """Independent temporal coordinate families exposed to a process."""

    MONOTONIC = "monotonic"
    WALL = "wall"
    CAUSAL = "causal"
    SCHEDULER = "scheduler"
    EVENT = "event"
    CHRONON = "chronon"
    CHEMICAL = "chemical"


class CausalRelation(str, Enum):
    """Partial-order relation between two vector-clock observations."""

    BEFORE = "before"
    AFTER = "after"
    EQUAL = "equal"
    CONCURRENT = "concurrent"


def _text(value: Any, label: str) -> str:
    """Mathematics: require a non-empty identity string x in the finite text domain."""
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise TemporalError(f"{label} must be non-empty text without NUL")
    return value


def _integer(value: Any, label: str, minimum: int = 0) -> int:
    """Mathematics: enforce x in Z and x >= minimum, excluding Boolean values."""
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        raise TemporalError(f"{label} must be an integer >= {minimum}")
    return value


def _finite(value: Any, label: str) -> float:
    """Mathematics: require a finite real coordinate x in R with |x| < infinity."""
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise TemporalError(f"{label} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise TemporalError(f"{label} must be finite")
    return result


def _canonical_bytes(value: Any) -> bytes:
    """Mathematics: map finite JSON-compatible state x to canonical bytes J(x)."""
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise TemporalError(f"temporal state is not canonical JSON: {exc}") from exc


def _digest(value: Any) -> str:
    """Mathematics: compute H(x) = SHA256(J(x)) over canonical JSON bytes."""
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


@dataclass(frozen=True)
class TemporalProfile:
    """The clock domains a process is permitted and expected to observe."""

    domains: frozenset[ClockDomain]

    def __post_init__(self) -> None:
        """Mathematics: require D to be a subset of the finite ClockDomain alphabet."""
        try:
            normalized = frozenset(
                item if isinstance(item, ClockDomain) else ClockDomain(item)
                for item in self.domains
            )
        except (TypeError, ValueError) as exc:
            raise TemporalError("profile contains an unknown clock domain") from exc
        object.__setattr__(self, "domains", normalized)

    def uses(self, domain: ClockDomain) -> bool:
        """Mathematics: return 1 iff domain is a member of the process domain set D."""
        return domain in self.domains

    def to_dict(self) -> dict[str, object]:
        """Mathematics: serialize D as a deterministic sorted finite string set."""
        return {"domains": sorted(domain.value for domain in self.domains)}

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "TemporalProfile":
        """Mathematics: reconstruct D only from a finite sequence of known domain labels."""
        if not isinstance(payload, Mapping) or set(payload) != {"domains"}:
            raise TemporalError("temporal profile fields are invalid")
        raw = payload.get("domains")
        if not isinstance(raw, (list, tuple)):
            raise TemporalError("temporal profile domains must be a sequence")
        if any(not isinstance(item, str) for item in raw):
            raise TemporalError("temporal profile domain labels must be strings")
        if len(set(raw)) != len(raw):
            raise TemporalError("temporal profile contains duplicate domains")
        try:
            return cls(frozenset(ClockDomain(item) for item in raw))
        except ValueError as exc:
            raise TemporalError("temporal profile contains an unknown domain") from exc


@dataclass(frozen=True)
class MonotonicReading:
    """A process-local elapsed-time reading, scoped to one monotonic segment."""

    actor_id: str
    segment: int
    elapsed_ns: int

    def __post_init__(self) -> None:
        """Mathematics: validate reading identity (actor, segment) and elapsed coordinate e >= 0."""
        _text(self.actor_id, "actor_id")
        _integer(self.segment, "segment")
        _integer(self.elapsed_ns, "elapsed_ns")

    def elapsed_until(self, later: "MonotonicReading") -> int:
        """Mathematics: compute later.e - self.e only when actor and segment identities are equal and the difference is non-negative."""
        if not isinstance(later, MonotonicReading):
            raise TemporalError("later reading must be a MonotonicReading")
        if (self.actor_id, self.segment) != (later.actor_id, later.segment):
            raise TemporalError("monotonic readings from different actors or segments are incomparable")
        if later.elapsed_ns < self.elapsed_ns:
            raise ClockRegressionError("later monotonic reading precedes the starting reading")
        return later.elapsed_ns - self.elapsed_ns

    def to_dict(self) -> dict[str, object]:
        """Mathematics: project the scoped elapsed coordinate into a finite record."""
        return {
            "actor_id": self.actor_id,
            "segment": self.segment,
            "elapsed_ns": self.elapsed_ns,
        }


@dataclass(frozen=True)
class WallTimeReading:
    """A local UTC wall-clock sample; it is a calendar estimate, not causal proof."""

    actor_id: str
    utc_ns: int
    sample_index: int

    def __post_init__(self) -> None:
        """Mathematics: validate actor identity, signed UTC nanoseconds, and sample index n >= 0."""
        _text(self.actor_id, "actor_id")
        if not isinstance(self.utc_ns, int) or isinstance(self.utc_ns, bool):
            raise TemporalError("utc_ns must be an integer")
        _integer(self.sample_index, "sample_index")

    def to_dict(self) -> dict[str, object]:
        """Mathematics: project the wall-clock sample into a finite record."""
        return {
            "actor_id": self.actor_id,
            "utc_ns": self.utc_ns,
            "sample_index": self.sample_index,
        }


@dataclass(frozen=True)
class CausalStamp:
    """A Lamport scalar paired with a vector clock for distributed event ordering."""

    actor_id: str
    lamport: int
    vector: tuple[tuple[str, int], ...]

    def __post_init__(self) -> None:
        """Mathematics: require sorted unique actor counters v_i >= 0 and max(v_i) <= L."""
        _text(self.actor_id, "actor_id")
        _integer(self.lamport, "lamport")
        if not isinstance(self.vector, (tuple, list)):
            raise CausalClockError("vector must be a finite sequence of actor counters")
        normalized: list[tuple[str, int]] = []
        seen: set[str] = set()
        for item in self.vector:
            if not isinstance(item, (tuple, list)) or len(item) != 2:
                raise CausalClockError("vector entries must be (actor_id, counter) pairs")
            actor = _text(item[0], "vector actor_id")
            counter = _integer(item[1], "vector counter")
            if actor in seen:
                raise CausalClockError("vector contains a duplicate actor")
            seen.add(actor)
            normalized.append((actor, counter))
        normalized.sort(key=lambda item: item[0])
        if self.actor_id not in seen:
            raise CausalClockError("vector must include the stamp's own actor")
        if any(counter > self.lamport for _, counter in normalized):
            raise CausalClockError("vector counter cannot exceed the Lamport scalar")
        object.__setattr__(self, "vector", tuple(normalized))

    @classmethod
    def create(
        cls,
        actor_id: str,
        lamport: int,
        vector: Mapping[str, int],
    ) -> "CausalStamp":
        """Mathematics: construct C=(actor,L,V) from a finite vector map with unique keys."""
        if not isinstance(vector, Mapping):
            raise CausalClockError("vector must be a mapping")
        return cls(
            actor_id,
            lamport,
            tuple((key, value) for key, value in vector.items()),
        )

    def vector_map(self) -> dict[str, int]:
        """Mathematics: expose the finite vector relation V as a detached mapping."""
        return dict(self.vector)

    def relation(self, other: "CausalStamp") -> CausalRelation:
        """Mathematics: compare V1 and V2 componentwise, returning before, after, equal, or concurrent."""
        if not isinstance(other, CausalStamp):
            raise CausalClockError("causal comparison requires another CausalStamp")
        left = self.vector_map()
        right = other.vector_map()
        actors = set(left) | set(right)
        less = any(left.get(actor, 0) < right.get(actor, 0) for actor in actors)
        greater = any(left.get(actor, 0) > right.get(actor, 0) for actor in actors)
        if less and greater:
            return CausalRelation.CONCURRENT
        if less:
            return CausalRelation.BEFORE
        if greater:
            return CausalRelation.AFTER
        return CausalRelation.EQUAL

    def to_dict(self) -> dict[str, object]:
        """Mathematics: serialize C=(actor,L,V) with vector actors in canonical sorted order."""
        return {
            "actor_id": self.actor_id,
            "lamport": self.lamport,
            "vector": {actor: counter for actor, counter in self.vector},
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "CausalStamp":
        """Mathematics: invert the causal-stamp projection only when actor, scalar, and vector domains validate."""
        if not isinstance(payload, Mapping) or set(payload) != {
            "actor_id",
            "lamport",
            "vector",
        }:
            raise CausalClockError("causal stamp fields are invalid")
        vector = payload.get("vector")
        if not isinstance(vector, Mapping):
            raise CausalClockError("causal stamp vector must be a mapping")
        return cls.create(
            payload.get("actor_id"),
            payload.get("lamport"),
            vector,
        )


@dataclass(frozen=True)
class SchedulerReading:
    """A logical tick in one named virtual scheduler, not elapsed physical time."""

    scheduler_id: str
    tick: int

    def __post_init__(self) -> None:
        """Mathematics: require scheduler identity s and logical tick t in Z>=0."""
        _text(self.scheduler_id, "scheduler_id")
        _integer(self.tick, "tick")

    def to_dict(self) -> dict[str, object]:
        """Mathematics: serialize the scheduler-scoped coordinate (s,t)."""
        return {"scheduler_id": self.scheduler_id, "tick": self.tick}


@dataclass(frozen=True)
class TemporalFrame:
    """A typed bundle of only the temporal coordinates selected by one process."""

    actor_id: str
    monotonic: MonotonicReading | None = None
    wall: WallTimeReading | None = None
    causal: CausalStamp | None = None
    scheduler: SchedulerReading | None = None
    event_lambda: int | None = None
    chronon_phase: tuple[float, float] | None = None
    chemical_tau: float | None = None

    def __post_init__(self) -> None:
        """Mathematics: require every present coordinate to be typed and scoped to the frame actor where applicable."""
        _text(self.actor_id, "actor_id")
        if self.monotonic is not None and self.monotonic.actor_id != self.actor_id:
            raise TemporalError("monotonic reading belongs to another actor")
        if self.wall is not None and self.wall.actor_id != self.actor_id:
            raise TemporalError("wall reading belongs to another actor")
        if self.causal is not None and self.causal.actor_id != self.actor_id:
            raise TemporalError("causal stamp belongs to another actor")
        if self.scheduler is not None and not isinstance(self.scheduler, SchedulerReading):
            raise TemporalError("scheduler coordinate is not typed")
        if self.event_lambda is not None:
            _integer(self.event_lambda, "event_lambda")
        if self.chronon_phase is not None:
            if not isinstance(self.chronon_phase, tuple) or len(self.chronon_phase) != 2:
                raise TemporalError("chronon_phase must be a real/imaginary pair")
            _finite(self.chronon_phase[0], "chronon real phase")
            _finite(self.chronon_phase[1], "chronon imaginary phase")
        if self.chemical_tau is not None and _finite(self.chemical_tau, "chemical_tau") < 0:
            raise TemporalError("chemical_tau must be non-negative")

    def to_dict(self) -> dict[str, object]:
        """Mathematics: project the selected temporal coordinate product without converting between domains."""
        return {
            "actor_id": self.actor_id,
            "monotonic": None if self.monotonic is None else self.monotonic.to_dict(),
            "wall": None if self.wall is None else self.wall.to_dict(),
            "causal": None if self.causal is None else self.causal.to_dict(),
            "scheduler": None if self.scheduler is None else self.scheduler.to_dict(),
            "event_lambda": self.event_lambda,
            "chronon_phase": None if self.chronon_phase is None else list(self.chronon_phase),
            "chemical_tau": self.chemical_tau,
        }


class TemporalContext:
    """Process-local temporal interface with profile-selected clocks and causal merge."""

    def __init__(
        self,
        actor_id: str,
        profile: TemporalProfile,
        *,
        monotonic_ns: Callable[[], int] | None = None,
        wall_time_ns: Callable[[], int] | None = None,
        segment: int = 0,
        elapsed_ns: int = 0,
        lamport: int = 0,
        vector: Mapping[str, int] | None = None,
        wall_sample_index: int = 0,
    ) -> None:
        """Mathematics: initialize process clock state (actor, D, segment, elapsed, L, V) using independent local physical sources."""
        self.actor_id = _text(actor_id, "actor_id")
        if not isinstance(profile, TemporalProfile):
            raise TemporalError("profile must be a TemporalProfile")
        self.profile = profile
        self._monotonic_ns = monotonic_ns or time.monotonic_ns
        self._wall_time_ns = wall_time_ns or time.time_ns
        if not callable(self._monotonic_ns) or not callable(self._wall_time_ns):
            raise TemporalError("clock sources must be callable")
        self._segment = _integer(segment, "segment")
        self._elapsed_ns = _integer(elapsed_ns, "elapsed_ns")
        self._wall_sample_index = _integer(wall_sample_index, "wall_sample_index")
        self._lamport = _integer(lamport, "lamport")
        if vector is not None and not isinstance(vector, Mapping):
            raise CausalClockError("vector must be a mapping")
        raw_vector = {} if vector is None else dict(vector)
        if any(not isinstance(key, str) for key in raw_vector):
            raise CausalClockError("vector actor identities must be strings")
        self._vector: dict[str, int] = {
            _text(key, "vector actor_id"): _integer(value, "vector counter")
            for key, value in raw_vector.items()
        }
        if ClockDomain.CAUSAL in self.profile.domains:
            self._vector.setdefault(self.actor_id, 0)
            if any(value > self._lamport for value in self._vector.values()):
                raise CausalClockError("vector counter cannot exceed Lamport scalar")
        elif self._lamport != 0 or self._vector:
            raise TemporalError("causal state supplied to a profile without the causal domain")

        self._monotonic_origin_ns: int | None = None
        self._last_monotonic_ns: int | None = None
        if ClockDomain.MONOTONIC in self.profile.domains:
            origin = self._read_source(self._monotonic_ns, "monotonic_ns", nonnegative=True)
            self._monotonic_origin_ns = origin
            self._last_monotonic_ns = origin

    @staticmethod
    def _read_source(
        source: Callable[[], int],
        label: str,
        *,
        nonnegative: bool,
    ) -> int:
        """Mathematics: sample an integer clock source x and reject Boolean or out-of-domain readings."""
        try:
            value = source()
        except Exception as exc:
            raise TemporalError(f"{label} source failed: {exc}") from exc
        minimum = 0 if nonnegative else -(2**63)
        return _integer(value, label, minimum)

    def _require(self, domain: ClockDomain) -> None:
        """Mathematics: enforce domain in profile D before exposing a coordinate."""
        if not self.profile.uses(domain):
            raise ClockUnavailableError(
                f"clock domain {domain.value} is not enabled for actor {self.actor_id}"
            )

    def monotonic_reading(self) -> MonotonicReading:
        """Mathematics: return E = E_saved + (m_now - m_segment_start), requiring m_now >= m_last."""
        self._require(ClockDomain.MONOTONIC)
        current = self._read_source(self._monotonic_ns, "monotonic_ns", nonnegative=True)
        assert self._monotonic_origin_ns is not None
        assert self._last_monotonic_ns is not None
        if current < self._last_monotonic_ns:
            raise ClockRegressionError(
                f"monotonic source regressed for actor {self.actor_id}"
            )
        self._last_monotonic_ns = current
        return MonotonicReading(
            self.actor_id,
            self._segment,
            self._elapsed_ns + current - self._monotonic_origin_ns,
        )

    def wall_reading(self) -> WallTimeReading:
        """Mathematics: sample the local calendar coordinate U=wall_time_ns without imposing monotonic ordering."""
        self._require(ClockDomain.WALL)
        current = self._read_source(
            self._wall_time_ns,
            "wall_time_ns",
            nonnegative=False,
        )
        self._wall_sample_index += 1
        return WallTimeReading(self.actor_id, current, self._wall_sample_index)

    def current_causal_stamp(self) -> CausalStamp:
        """Mathematics: expose the current pair (L,V) without advancing either causal coordinate."""
        self._require(ClockDomain.CAUSAL)
        return CausalStamp.create(self.actor_id, self._lamport, self._vector)

    def emit_causal_stamp(self) -> CausalStamp:
        """Mathematics: advance local event time L:=L+1 and V_actor:=V_actor+1, then emit C=(actor,L,V)."""
        self._require(ClockDomain.CAUSAL)
        self._lamport += 1
        self._vector[self.actor_id] = self._vector.get(self.actor_id, 0) + 1
        return self.current_causal_stamp()

    def receive_causal_stamp(self, remote: CausalStamp) -> CausalStamp:
        """Mathematics: merge V:=max(V, V_remote), then set L:=max(L,L_remote)+1 and V_actor:=V_actor+1."""
        self._require(ClockDomain.CAUSAL)
        if not isinstance(remote, CausalStamp):
            raise CausalClockError("remote causal input must be a CausalStamp")
        if remote.actor_id == self.actor_id:
            raise CausalClockError("a process cannot receive its own causal stamp")
        for actor, counter in remote.vector:
            self._vector[actor] = max(self._vector.get(actor, 0), counter)
        self._lamport = max(self._lamport, remote.lamport) + 1
        self._vector[self.actor_id] = self._vector.get(self.actor_id, 0) + 1
        if any(value > self._lamport for value in self._vector.values()):
            raise CausalClockError("merged vector counter exceeds Lamport scalar")
        return self.current_causal_stamp()

    def observe(
        self,
        *,
        scheduler_id: str | None = None,
        scheduler_tick: int | None = None,
        system_epoch: SystemEpoch | None = None,
    ) -> TemporalFrame:
        """Mathematics: prevalidate selected external coordinates, then assemble only domains D without partial sampling on refusal."""
        scheduler = None
        if self.profile.uses(ClockDomain.SCHEDULER):
            if scheduler_id is None or scheduler_tick is None:
                raise ClockUnavailableError(
                    "scheduler_id and scheduler_tick are required by this profile"
                )
            scheduler = SchedulerReading(
                _text(scheduler_id, "scheduler_id"),
                _integer(scheduler_tick, "scheduler_tick"),
            )

        event_lambda = None
        chronon_phase = None
        chemical_tau = None
        needs_epoch = any(
            self.profile.uses(domain)
            for domain in (
                ClockDomain.EVENT,
                ClockDomain.CHRONON,
                ClockDomain.CHEMICAL,
            )
        )
        if needs_epoch:
            if not isinstance(system_epoch, SystemEpoch):
                raise ClockUnavailableError(
                    "SystemEpoch is required by this process temporal profile"
                )
            if self.profile.uses(ClockDomain.EVENT):
                event_lambda = _integer(
                    system_epoch.event_lambda,
                    "SystemEpoch.event_lambda",
                )
            if self.profile.uses(ClockDomain.CHRONON):
                real = _finite(system_epoch.chronon_phase.real, "chronon real phase")
                imag = _finite(system_epoch.chronon_phase.imag, "chronon imaginary phase")
                if not math.isclose(math.hypot(real, imag), 1.0, rel_tol=1e-9, abs_tol=1e-9):
                    raise TemporalError("chronon phase must remain on the unit circle")
                chronon_phase = (real, imag)
            if self.profile.uses(ClockDomain.CHEMICAL):
                chemical_tau = _finite(system_epoch.chemical_tau, "chemical_tau")
                if chemical_tau < 0:
                    raise TemporalError("chemical_tau must be non-negative")

        # Local physical reads occur only after every supplied virtual coordinate
        # has been checked, so an invalid observation has no partial clock effects.
        monotonic = (
            self.monotonic_reading()
            if self.profile.uses(ClockDomain.MONOTONIC)
            else None
        )
        wall = (
            self.wall_reading()
            if self.profile.uses(ClockDomain.WALL)
            else None
        )
        causal = (
            self.current_causal_stamp()
            if self.profile.uses(ClockDomain.CAUSAL)
            else None
        )
        return TemporalFrame(
            actor_id=self.actor_id,
            monotonic=monotonic,
            wall=wall,
            causal=causal,
            scheduler=scheduler,
            event_lambda=event_lambda,
            chronon_phase=chronon_phase,
            chemical_tau=chemical_tau,
        )

    def snapshot(self) -> dict[str, object]:
        """Mathematics: serialize K=(actor,D,segment,elapsed,L,V,sample_index) under canonical digest H(K)."""
        if ClockDomain.MONOTONIC in self.profile.domains:
            elapsed = self.monotonic_reading().elapsed_ns
        else:
            elapsed = self._elapsed_ns
        state = {
            "version": 1,
            "actor_id": self.actor_id,
            "profile": self.profile.to_dict(),
            "segment": self._segment,
            "elapsed_ns": elapsed,
            "lamport": self._lamport,
            "vector": dict(sorted(self._vector.items())),
            "wall_sample_index": self._wall_sample_index,
        }
        return {
            "format": _FORMAT,
            "digest": _digest(state),
            "state": state,
        }

    @classmethod
    def from_snapshot(
        cls,
        payload: Mapping[str, Any],
        *,
        monotonic_ns: Callable[[], int] | None = None,
        wall_time_ns: Callable[[], int] | None = None,
    ) -> "TemporalContext":
        """Mathematics: restore K only when format, schema and H(K) verify; start a new monotonic segment without counting downtime."""
        if not isinstance(payload, Mapping) or set(payload) != {
            "format",
            "digest",
            "state",
        }:
            raise TemporalError("temporal checkpoint envelope fields are invalid")
        if payload.get("format") != _FORMAT:
            raise TemporalError("unsupported temporal checkpoint format")
        state = payload.get("state")
        expected = {
            "version",
            "actor_id",
            "profile",
            "segment",
            "elapsed_ns",
            "lamport",
            "vector",
            "wall_sample_index",
        }
        if not isinstance(state, Mapping) or set(state) != expected:
            raise TemporalError("temporal checkpoint state fields are invalid")
        version = state.get("version")
        if not isinstance(version, int) or isinstance(version, bool) or version != 1:
            raise TemporalError("unsupported temporal checkpoint version")
        if _digest(dict(state)) != payload.get("digest"):
            raise TemporalError("temporal checkpoint digest mismatch")
        profile = TemporalProfile.from_dict(state.get("profile"))
        segment = _integer(state.get("segment"), "segment")
        if ClockDomain.MONOTONIC in profile.domains:
            segment += 1
        return cls(
            state.get("actor_id"),
            profile,
            monotonic_ns=monotonic_ns,
            wall_time_ns=wall_time_ns,
            segment=segment,
            elapsed_ns=_integer(state.get("elapsed_ns"), "elapsed_ns"),
            lamport=_integer(state.get("lamport"), "lamport"),
            vector=state.get("vector"),
            wall_sample_index=_integer(
                state.get("wall_sample_index"),
                "wall_sample_index",
            ),
        )
