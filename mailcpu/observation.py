"""Typed observations carried from communication substrates into VM state."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, ClassVar, Mapping, Protocol, TYPE_CHECKING

from .chemical_time import HorizonTracker, SystemEpoch
from .chronofold import ChronoFold
from .delay_loop import DelayLoopEngine
from .reliability import ReliableChannel
from .timing_channel import CadenceDemodulator, TimingChannelConfig

if TYPE_CHECKING:
    from .transport import Transport
    from .vm import MailCPUVirtualMachine


class ObservationError(ValueError):
    """A substrate observation or substrate-to-VM bridge invariant failed."""


class SubstrateObservation(Protocol):
    """Structural contract shared by every typed substrate observation."""

    kind: ClassVar[str]
    source: str
    logical_time: int

    def to_payload(self) -> tuple[Any, ...]:
        """Mathematics: encode an observation as a finite product tuple `E(O)`."""

    def register_values(self, prefix: str = "substrate") -> dict[str, int]:
        """Mathematics: project an observation into an integer VM valuation `π(O) : R ⇀ Z`."""


_STATUS_CODES = {"NOERROR": 0, "NXDOMAIN": 1, "REFUSED": 2}
_RESOLVER_PAYLOAD_TAG = "RESOLVER_OBSERVATION"
_TIMING_PAYLOAD_TAG = "TIMING_OBSERVATION"
_DELAY_PAYLOAD_TAG = "DELAY_OBSERVATION"
_TEMPORAL_PAYLOAD_TAG = "TEMPORAL_OBSERVATION"
_PHASE_PAYLOAD_TAG = "PHASE_OBSERVATION"
_PAYLOAD_VERSION = 1
_CHEMICAL_FIXED_SCALE = 1_000_000


def _validate_identifier(name: str, value: Any) -> None:
    """Mathematics: require `value ∈ Σ⁺` with NUL excluded from the identifier alphabet."""

    if not isinstance(value, str) or not value or "\x00" in value:
        raise ObservationError(f"observation {name} must be a non-empty string without NUL")


def _validate_logical_time(value: Any) -> None:
    """Mathematics: require logical coordinate `t ∈ Z_{≥0}` and reject Boolean subtyping."""

    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ObservationError("observation logical_time must be a non-negative integer")


def _validate_register_prefix(prefix: Any) -> None:
    """Mathematics: require register namespace `r ∈ Σ⁺` with no whitespace or NUL separators."""

    if not isinstance(prefix, str) or not prefix or any(
        character.isspace() or character == "\x00" for character in prefix
    ):
        raise ObservationError("observation register prefix must be non-empty and whitespace-free")


def _validate_integer(name: str, value: Any, minimum: int | None = None) -> None:
    """Mathematics: require `value ∈ Z` and, when supplied, `value ≥ minimum`."""

    if not isinstance(value, int) or isinstance(value, bool):
        raise ObservationError(f"observation {name} must be an integer")
    if minimum is not None and value < minimum:
        raise ObservationError(f"observation {name} must be at least {minimum}")


def _validate_timing_config(config: TimingChannelConfig) -> None:
    """Mathematics: admit cadence parameters only in `base,quantum>0`, `1≤B≤31`, and `0≤α≤1`."""

    if not isinstance(config, TimingChannelConfig):
        raise ObservationError("timing demodulator must expose TimingChannelConfig")
    for name, value in (("base_delay_ms", config.base_delay_ms), ("quantum_ms", config.quantum_ms)):
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value) or value <= 0:
            raise ObservationError(f"timing {name} must be finite and positive")
    _validate_integer("bits_per_symbol", config.bits_per_symbol, 1)
    if config.bits_per_symbol > 31:
        raise ObservationError("timing bits_per_symbol must be at most 31")
    if (
        not isinstance(config.pll_alpha, (int, float))
        or isinstance(config.pll_alpha, bool)
        or not math.isfinite(config.pll_alpha)
        or not 0 <= config.pll_alpha <= 1
    ):
        raise ObservationError("timing pll_alpha must be finite in [0, 1]")


def _phase_quadrant(phase: complex) -> int:
    """Mathematics: decode `D∈{1,-i,-1,i}` as `q∈Z₄`, rejecting non-unit or off-axis phases."""

    if not isinstance(phase, complex) or not math.isfinite(phase.real) or not math.isfinite(phase.imag):
        raise ObservationError("chronon phase must be finite complex")
    candidates = (1 + 0j, 0 - 1j, -1 + 0j, 0 + 1j)
    distances = [abs(phase - candidate) for candidate in candidates]
    quadrant = min(range(4), key=distances.__getitem__)
    if distances[quadrant] > 1e-9 or not math.isclose(abs(phase), 1.0, rel_tol=1e-9, abs_tol=1e-9):
        raise ObservationError("chronon phase is not an exact quarter-turn unit phase")
    return quadrant


def _validate_quadrant(value: Any, name: str = "phase_quadrant") -> None:
    """Mathematics: require quarter-turn coordinate `q∈{0,1,2,3}=Z₄`."""

    _validate_integer(name, value, 0)
    if value > 3:
        raise ObservationError(f"{name} must be in [0, 3]")


def _quantize_chemical_tau(value: Any) -> int:
    """Mathematics: encode nonnegative chemical coordinate `τ` as fixed point `τ_fixed=round(Sτ)`."""

    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value) or value < 0:
        raise ObservationError("chemical_tau must be finite and non-negative")
    return round(value * _CHEMICAL_FIXED_SCALE)


@dataclass(frozen=True)
class ResolverObservation:
    """Typed resolver result with a discrete logical-time coordinate."""

    kind: ClassVar[str] = "resolver"

    source: str
    domain: str
    record_type: str
    logical_time: int
    status: str
    hit: bool
    ttl: int
    value: str

    def __post_init__(self) -> None:
        """Mathematics: admit `O` only when identifiers are nonempty, `t,ttl∈Z_{≥0}`, `hit∈{0,1}`, and `status∈dom(code)`."""

        for name, value in (
            ("source", self.source),
            ("domain", self.domain),
            ("record_type", self.record_type),
        ):
            _validate_identifier(name, value)
        _validate_logical_time(self.logical_time)
        if self.status not in _STATUS_CODES:
            raise ObservationError(f"unknown resolver observation status: {self.status}")
        if not isinstance(self.hit, bool):
            raise ObservationError("observation hit must be boolean")
        _validate_integer("ttl", self.ttl, 0)
        if not isinstance(self.value, str) or "\x00" in self.value:
            raise ObservationError("observation value must be a string without NUL")

    @classmethod
    def from_query(
        cls,
        source: str,
        domain: str,
        record_type: str,
        logical_time: int,
        result: Mapping[str, Any],
    ) -> "ResolverObservation":
        """Mathematics: lift query result `q` into `O=(source,domain,type,t,q.status,q.hit,q.ttl,q.value)`."""

        if not isinstance(result, Mapping):
            raise ObservationError("resolver query result must be a mapping")
        if "status" not in result or "hit" not in result or "ttl" not in result:
            raise ObservationError("resolver query result lacks typed observation fields")
        return cls(
            source=source,
            domain=domain,
            record_type=record_type,
            logical_time=logical_time,
            status=result["status"],
            hit=result["hit"],
            ttl=result["ttl"],
            value=result.get("value", ""),
        )

    def to_payload(self) -> tuple[Any, ...]:
        """Mathematics: encode `O` injectively as tagged tuple `E(O)` with fixed arity and version."""

        return (
            _RESOLVER_PAYLOAD_TAG,
            _PAYLOAD_VERSION,
            self.source,
            self.domain,
            self.record_type,
            self.logical_time,
            self.status,
            int(self.hit),
            self.ttl,
            self.value,
        )

    @classmethod
    def from_payload(cls, payload: Any) -> "ResolverObservation":
        """Mathematics: invert `E` only on the exact tagged resolver product domain."""

        if not isinstance(payload, tuple) or len(payload) != 10:
            raise ObservationError("resolver observation payload shape mismatch")
        if payload[0] != _RESOLVER_PAYLOAD_TAG or payload[1] != _PAYLOAD_VERSION:
            raise ObservationError("unsupported resolver observation payload version")
        if payload[7] not in (0, 1) or isinstance(payload[7], bool):
            raise ObservationError("resolver observation hit flag must be 0 or 1")
        return cls(
            source=payload[2],
            domain=payload[3],
            record_type=payload[4],
            logical_time=payload[5],
            status=payload[6],
            hit=bool(payload[7]),
            ttl=payload[8],
            value=payload[9],
        )

    def register_values(self, prefix: str = "resolver") -> dict[str, int]:
        """Mathematics: project `O` into integer VM valuation `R[p_time,t_hit,t_ttl,t_status]`."""

        _validate_register_prefix(prefix)
        return {
            f"{prefix}_time": self.logical_time,
            f"{prefix}_hit": int(self.hit),
            f"{prefix}_ttl": self.ttl,
            f"{prefix}_status": _STATUS_CODES[self.status],
        }


@dataclass(frozen=True)
class TimingObservation:
    """Typed result of one cadence demodulation step and its PLL state."""

    kind: ClassVar[str] = "timing"

    source: str
    logical_time: int
    observed_us: int
    symbol: int
    tracked_base_us: int
    quantum_us: int
    phase_error_us: int
    max_symbol: int = 255

    def __post_init__(self) -> None:
        """Mathematics: admit `T` when `y,b,q∈Z_{>0}`, `0≤d≤D`, and `e∈Z` are well-typed."""

        _validate_identifier("source", self.source)
        _validate_logical_time(self.logical_time)
        _validate_integer("observed_us", self.observed_us, 0)
        _validate_integer("tracked_base_us", self.tracked_base_us, 1)
        _validate_integer("quantum_us", self.quantum_us, 1)
        _validate_integer("phase_error_us", self.phase_error_us)
        _validate_integer("max_symbol", self.max_symbol, 0)
        _validate_integer("symbol", self.symbol, 0)
        if self.symbol > self.max_symbol:
            raise ObservationError("timing symbol exceeds configured maximum")

    @classmethod
    def from_demodulator(
        cls,
        source: str,
        logical_time: int,
        observed_delay_ms: float,
        demodulator: CadenceDemodulator,
    ) -> "TimingObservation":
        """Mathematics: apply `d=clamp(round((y-b)/q))`, `e=y-(b+dq)`, then capture post-step PLL baseline."""

        _validate_identifier("source", source)
        _validate_logical_time(logical_time)
        _validate_timing_config(demodulator.config)
        if (
            not isinstance(observed_delay_ms, (int, float))
            or isinstance(observed_delay_ms, bool)
            or not math.isfinite(observed_delay_ms)
            or observed_delay_ms < 0
        ):
            raise ObservationError("timing observed delay must be finite and non-negative")
        base_before_ms = demodulator.tracked_base_ms
        symbol = demodulator.decode_interval(observed_delay_ms)
        phase_error_ms = observed_delay_ms - (
            base_before_ms + symbol * demodulator.config.quantum_ms
        )
        return cls(
            source=source,
            logical_time=logical_time,
            observed_us=round(observed_delay_ms * 1000),
            symbol=symbol,
            tracked_base_us=round(demodulator.tracked_base_ms * 1000),
            quantum_us=round(demodulator.config.quantum_ms * 1000),
            phase_error_us=round(phase_error_ms * 1000),
            max_symbol=demodulator.config.max_symbol,
        )

    def to_payload(self) -> tuple[Any, ...]:
        """Mathematics: encode `T` as a fixed-arity integer tuple without floating-point transport state."""

        return (
            _TIMING_PAYLOAD_TAG,
            _PAYLOAD_VERSION,
            self.source,
            self.logical_time,
            self.observed_us,
            self.symbol,
            self.tracked_base_us,
            self.quantum_us,
            self.phase_error_us,
            self.max_symbol,
        )

    @classmethod
    def from_payload(cls, payload: Any) -> "TimingObservation":
        """Mathematics: invert the timing codec only on its tagged integer product domain."""

        if not isinstance(payload, tuple) or len(payload) != 10:
            raise ObservationError("timing observation payload shape mismatch")
        if payload[0] != _TIMING_PAYLOAD_TAG or payload[1] != _PAYLOAD_VERSION:
            raise ObservationError("unsupported timing observation payload version")
        return cls(
            source=payload[2],
            logical_time=payload[3],
            observed_us=payload[4],
            symbol=payload[5],
            tracked_base_us=payload[6],
            quantum_us=payload[7],
            phase_error_us=payload[8],
            max_symbol=payload[9],
        )

    def register_values(self, prefix: str = "timing") -> dict[str, int]:
        """Mathematics: project `T` into integer registers for time, decision, interval, PLL, and phase error."""

        _validate_register_prefix(prefix)
        return {
            f"{prefix}_time": self.logical_time,
            f"{prefix}_symbol": self.symbol,
            f"{prefix}_delay_us": self.observed_us,
            f"{prefix}_base_us": self.tracked_base_us,
            f"{prefix}_quantum_us": self.quantum_us,
            f"{prefix}_error_us": self.phase_error_us,
        }


class TimingObservationProducer:
    """Stateful adapter that turns cadence intervals into durable timing observations."""

    def __init__(self, source: str, demodulator: CadenceDemodulator | None = None) -> None:
        """Mathematics: bind source `s` to demodulator state `D₀` while preserving its PLL recurrence."""

        _validate_identifier("source", source)
        self.source = source
        self.demodulator = demodulator or CadenceDemodulator()
        _validate_timing_config(self.demodulator.config)
        if (
            not isinstance(self.demodulator.tracked_base_ms, (int, float))
            or not math.isfinite(self.demodulator.tracked_base_ms)
            or self.demodulator.tracked_base_ms <= 0
        ):
            raise ObservationError("timing demodulator tracked base must be finite and positive")

    def observe_interval(self, logical_time: int, observed_delay_ms: float) -> TimingObservation:
        """Mathematics: emit `T_k` from one transition `D_k → D_{k+1}` under the demodulator's PLL rule."""

        return TimingObservation.from_demodulator(
            self.source,
            logical_time,
            observed_delay_ms,
            self.demodulator,
        )

    def snapshot(self) -> dict[str, Any]:
        """Mathematics: serialize source and all recurrence parameters needed to resume `D_{k+1}` exactly."""

        config = self.demodulator.config
        return {
            "version": 1,
            "source": self.source,
            "config": {
                "base_delay_ms": config.base_delay_ms,
                "quantum_ms": config.quantum_ms,
                "bits_per_symbol": config.bits_per_symbol,
                "pll_alpha": config.pll_alpha,
            },
            "tracked_base_ms": self.demodulator.tracked_base_ms,
        }

    @classmethod
    def from_snapshot(cls, payload: Mapping[str, Any]) -> "TimingObservationProducer":
        """Mathematics: reconstruct producer state `P'` so future PLL updates are continuation-equivalent."""

        if not isinstance(payload, Mapping) or int(payload.get("version", 1)) != 1:
            raise ObservationError("unsupported timing producer snapshot version")
        raw_config = payload.get("config")
        if not isinstance(raw_config, Mapping):
            raise ObservationError("timing producer snapshot lacks config")
        try:
            config = TimingChannelConfig(
                base_delay_ms=raw_config.get("base_delay_ms"),
                quantum_ms=raw_config.get("quantum_ms"),
                bits_per_symbol=raw_config.get("bits_per_symbol"),
                pll_alpha=raw_config.get("pll_alpha"),
            )
        except (TypeError, ValueError) as exc:
            raise ObservationError("timing producer snapshot contains invalid config") from exc
        demodulator = CadenceDemodulator(config)
        tracked_base_ms = payload.get("tracked_base_ms")
        if (
            not isinstance(tracked_base_ms, (int, float))
            or isinstance(tracked_base_ms, bool)
            or not math.isfinite(tracked_base_ms)
            or tracked_base_ms <= 0
        ):
            raise ObservationError("timing producer snapshot tracked base must be finite and positive")
        demodulator.tracked_base_ms = tracked_base_ms
        source = payload.get("source")
        _validate_identifier("source", source)
        return cls(source, demodulator)


@dataclass(frozen=True)
class DelayObservation:
    """Typed RRNS delay-loop read or scrub result, including explicit failure state."""

    kind: ClassVar[str] = "delay"

    source: str
    logical_time: int
    group_id: int
    value: int | None
    ok: bool
    surviving_slots: int
    required_slots: int
    scrub_count: int
    lost: bool
    slot_interval_us: int

    def __post_init__(self) -> None:
        """Mathematics: admit `D` with `ok⇔value∈Z`, survivor counts in `Z_{≥0}`, and `lost∈{0,1}`."""

        _validate_identifier("source", self.source)
        _validate_logical_time(self.logical_time)
        _validate_integer("group_id", self.group_id, 0)
        if not isinstance(self.ok, bool) or not isinstance(self.lost, bool):
            raise ObservationError("delay observation flags must be boolean")
        if self.ok:
            _validate_integer("value", self.value)
        elif self.value is not None:
            raise ObservationError("failed delay observation must have value=None")
        _validate_integer("surviving_slots", self.surviving_slots, 0)
        _validate_integer("required_slots", self.required_slots, 1)
        _validate_integer("scrub_count", self.scrub_count, 0)
        _validate_integer("slot_interval_us", self.slot_interval_us, 1)

    @classmethod
    def from_engine(
        cls,
        source: str,
        logical_time: int,
        engine: DelayLoopEngine,
        group_id: int,
        operation: str = "read",
    ) -> "DelayObservation":
        """Mathematics: observe `D=(V,ok)` after `read` or `scrub`, preserving `None` when CRT consistency fails."""

        _validate_identifier("source", source)
        _validate_logical_time(logical_time)
        _validate_integer("group_id", group_id, 0)
        if operation not in {"read", "scrub"}:
            raise ObservationError("delay observation operation must be read or scrub")
        group = engine.groups.get(group_id)
        if group is None:
            raise ObservationError(f"unknown delay group: {group_id}")
        surviving_slots = sum(1 for slot in group.slots if slot.alive)
        if operation == "read":
            value, ok = engine.read_group(group_id)
        else:
            value, ok = engine.scrub_group(group_id)
        if not ok:
            value = None
        interval_us = round(engine.slot_interval_s * 1_000_000)
        if interval_us <= 0:
            raise ObservationError("delay engine slot interval must quantize to positive microseconds")
        return cls(
            source=source,
            logical_time=logical_time,
            group_id=group_id,
            value=value,
            ok=ok,
            surviving_slots=surviving_slots,
            required_slots=group.k,
            scrub_count=group.scrub_count,
            lost=group.is_lost,
            slot_interval_us=interval_us,
        )

    def to_payload(self) -> tuple[Any, ...]:
        """Mathematics: encode `D` as a fixed-arity tuple with `None` as the explicit failed-recovery value."""

        return (
            _DELAY_PAYLOAD_TAG,
            _PAYLOAD_VERSION,
            self.source,
            self.logical_time,
            self.group_id,
            self.value,
            int(self.ok),
            self.surviving_slots,
            self.required_slots,
            self.scrub_count,
            int(self.lost),
            self.slot_interval_us,
        )

    @classmethod
    def from_payload(cls, payload: Any) -> "DelayObservation":
        """Mathematics: invert the delay codec only on its tagged product domain."""

        if not isinstance(payload, tuple) or len(payload) != 12:
            raise ObservationError("delay observation payload shape mismatch")
        if payload[0] != _DELAY_PAYLOAD_TAG or payload[1] != _PAYLOAD_VERSION:
            raise ObservationError("unsupported delay observation payload version")
        for index, name in ((6, "ok"), (10, "lost")):
            if payload[index] not in (0, 1) or isinstance(payload[index], bool):
                raise ObservationError(f"delay observation {name} flag must be 0 or 1")
        return cls(
            source=payload[2],
            logical_time=payload[3],
            group_id=payload[4],
            value=payload[5],
            ok=bool(payload[6]),
            surviving_slots=payload[7],
            required_slots=payload[8],
            scrub_count=payload[9],
            lost=bool(payload[10]),
            slot_interval_us=payload[11],
        )

    def register_values(self, prefix: str = "delay") -> dict[str, int]:
        """Mathematics: project `D` to integer registers with `-1` as the explicit `value=None` sentinel."""

        _validate_register_prefix(prefix)
        return {
            f"{prefix}_time": self.logical_time,
            f"{prefix}_group": self.group_id,
            f"{prefix}_value": -1 if self.value is None else self.value,
            f"{prefix}_ok": int(self.ok),
            f"{prefix}_survivors": self.surviving_slots,
            f"{prefix}_required": self.required_slots,
            f"{prefix}_scrubs": self.scrub_count,
            f"{prefix}_lost": int(self.lost),
            f"{prefix}_slot_us": self.slot_interval_us,
        }


@dataclass(frozen=True)
class TemporalObservation:
    """Typed fixed-point observation of scheduler event, chronon phase, and chemical time."""

    kind: ClassVar[str] = "temporal"

    source: str
    logical_time: int
    event_lambda: int
    phase_quadrant: int
    chemical_tau_micro: int
    horizon: int | None
    horizon_remaining: int
    horizon_valid: bool

    def __post_init__(self) -> None:
        """Mathematics: enforce `q∈Z₄`, `τ_fixed∈Z_{≥0}`, and `valid⇔(h=None∨t<h)`."""

        _validate_identifier("source", self.source)
        _validate_logical_time(self.logical_time)
        _validate_integer("event_lambda", self.event_lambda, 0)
        _validate_quadrant(self.phase_quadrant)
        _validate_integer("chemical_tau_micro", self.chemical_tau_micro, 0)
        if self.horizon is not None:
            _validate_integer("horizon", self.horizon, 0)
            expected_remaining = self.horizon - self.logical_time
            expected_valid = self.logical_time < self.horizon
        else:
            expected_remaining = -1
            expected_valid = True
        if self.horizon_remaining != expected_remaining:
            raise ObservationError("temporal horizon remaining coordinate is inconsistent")
        if self.horizon_valid != expected_valid or not isinstance(self.horizon_valid, bool):
            raise ObservationError("temporal horizon validity is inconsistent")

    @classmethod
    def from_epoch(
        cls,
        source: str,
        logical_time: int,
        epoch: SystemEpoch,
        horizon_tracker: HorizonTracker | None = None,
    ) -> "TemporalObservation":
        """Mathematics: project `E=(λ,D,τ,h)` into discrete `T=(λ,q(D),round(Sτ),h,h-t,valid)`."""

        _validate_identifier("source", source)
        _validate_logical_time(logical_time)
        if not isinstance(epoch, SystemEpoch):
            raise ObservationError("temporal observation requires SystemEpoch")
        if horizon_tracker is not None and not isinstance(horizon_tracker, HorizonTracker):
            raise ObservationError("temporal horizon must be HorizonTracker or None")
        horizon = None if horizon_tracker is None else horizon_tracker.t_horizon
        return cls(
            source=source,
            logical_time=logical_time,
            event_lambda=epoch.event_lambda,
            phase_quadrant=_phase_quadrant(epoch.chronon_phase),
            chemical_tau_micro=_quantize_chemical_tau(epoch.chemical_tau),
            horizon=horizon,
            horizon_remaining=-1 if horizon is None else horizon - logical_time,
            horizon_valid=True if horizon is None else logical_time < horizon,
        )

    @classmethod
    def from_scheduler(
        cls,
        source: str,
        logical_time: int,
        scheduler: Any,
        task_id: int,
    ) -> "TemporalObservation":
        """Mathematics: observe scheduler state `S=(system_epoch,tasks[task_id].horizon_tracker)` without mutating `S`."""

        if not hasattr(scheduler, "system_epoch") or not hasattr(scheduler, "tasks"):
            raise ObservationError("temporal observation requires scheduler state")
        task = scheduler.tasks.get(task_id)
        if task is None:
            raise ObservationError(f"unknown temporal observation task: {task_id}")
        return cls.from_epoch(source, logical_time, scheduler.system_epoch, task.horizon_tracker)

    def to_payload(self) -> tuple[Any, ...]:
        """Mathematics: encode fixed-point temporal state `T` as a tagged tuple with no floating fields."""

        return (
            _TEMPORAL_PAYLOAD_TAG,
            _PAYLOAD_VERSION,
            self.source,
            self.logical_time,
            self.event_lambda,
            self.phase_quadrant,
            self.chemical_tau_micro,
            self.horizon,
            self.horizon_remaining,
            int(self.horizon_valid),
        )

    @classmethod
    def from_payload(cls, payload: Any) -> "TemporalObservation":
        """Mathematics: invert the temporal codec only on its tagged fixed-point product domain."""

        if not isinstance(payload, tuple) or len(payload) != 10:
            raise ObservationError("temporal observation payload shape mismatch")
        if payload[0] != _TEMPORAL_PAYLOAD_TAG or payload[1] != _PAYLOAD_VERSION:
            raise ObservationError("unsupported temporal observation payload version")
        if payload[9] not in (0, 1) or isinstance(payload[9], bool):
            raise ObservationError("temporal horizon validity flag must be 0 or 1")
        return cls(
            source=payload[2],
            logical_time=payload[3],
            event_lambda=payload[4],
            phase_quadrant=payload[5],
            chemical_tau_micro=payload[6],
            horizon=payload[7],
            horizon_remaining=payload[8],
            horizon_valid=bool(payload[9]),
        )

    def register_values(self, prefix: str = "temporal") -> dict[str, int]:
        """Mathematics: project `T` into integer event, phase, chemical, and horizon registers."""

        _validate_register_prefix(prefix)
        return {
            f"{prefix}_time": self.logical_time,
            f"{prefix}_event": self.event_lambda,
            f"{prefix}_phase": self.phase_quadrant,
            f"{prefix}_chemical_micro": self.chemical_tau_micro,
            f"{prefix}_horizon": -1 if self.horizon is None else self.horizon,
            f"{prefix}_remaining": self.horizon_remaining,
            f"{prefix}_valid": int(self.horizon_valid),
        }


@dataclass(frozen=True)
class PhaseObservation:
    """Typed reversible chronofold metadata observation with exact quarter-turn phase."""

    kind: ClassVar[str] = "phase"

    source: str
    logical_time: int
    active_chronons: int
    sector_reads: int
    trace_length: int
    phase_quadrant: int
    period_header: int
    period_length: int
    period_stride: int

    def __post_init__(self) -> None:
        """Mathematics: enforce `q=active_chronons mod 4`, nonnegative counters, and bounded period metadata."""

        _validate_identifier("source", self.source)
        _validate_logical_time(self.logical_time)
        for name, value in (
            ("active_chronons", self.active_chronons),
            ("sector_reads", self.sector_reads),
            ("trace_length", self.trace_length),
            ("period_header", self.period_header),
        ):
            _validate_integer(name, value, 0)
        _validate_quadrant(self.phase_quadrant)
        _validate_integer("period_length", self.period_length, 1)
        _validate_integer("period_stride", self.period_stride)
        if self.phase_quadrant != self.active_chronons % 4:
            raise ObservationError("phase quadrant disagrees with active chronon count")
        if self.period_header and self.period_header + 2 * self.period_length > self.trace_length:
            raise ObservationError("phase period metadata exceeds retained trace")

    @classmethod
    def from_chronofold(
        cls,
        source: str,
        logical_time: int,
        fold: ChronoFold,
    ) -> "PhaseObservation":
        """Mathematics: project `F` into counters and `q(F.phase)=active_chronons mod 4` without replay claims."""

        if not isinstance(fold, ChronoFold):
            raise ObservationError("phase observation requires ChronoFold")
        return cls(
            source=source,
            logical_time=logical_time,
            active_chronons=fold.active_chronons,
            sector_reads=fold.sector_reads,
            trace_length=len(fold.trace),
            phase_quadrant=fold.active_chronons % 4,
            period_header=fold.period_header,
            period_length=fold.period_length,
            period_stride=fold.period_stride,
        )

    def to_payload(self) -> tuple[Any, ...]:
        """Mathematics: encode reversible metadata `P` as a fixed-arity integer tuple."""

        return (
            _PHASE_PAYLOAD_TAG,
            _PAYLOAD_VERSION,
            self.source,
            self.logical_time,
            self.active_chronons,
            self.sector_reads,
            self.trace_length,
            self.phase_quadrant,
            self.period_header,
            self.period_length,
            self.period_stride,
        )

    @classmethod
    def from_payload(cls, payload: Any) -> "PhaseObservation":
        """Mathematics: invert the phase codec only on its tagged integer product domain."""

        if not isinstance(payload, tuple) or len(payload) != 11:
            raise ObservationError("phase observation payload shape mismatch")
        if payload[0] != _PHASE_PAYLOAD_TAG or payload[1] != _PAYLOAD_VERSION:
            raise ObservationError("unsupported phase observation payload version")
        return cls(
            source=payload[2],
            logical_time=payload[3],
            active_chronons=payload[4],
            sector_reads=payload[5],
            trace_length=payload[6],
            phase_quadrant=payload[7],
            period_header=payload[8],
            period_length=payload[9],
            period_stride=payload[10],
        )

    def register_values(self, prefix: str = "phase") -> dict[str, int]:
        """Mathematics: project `P` into integer chronon, trace, phase, and periodicity registers."""

        _validate_register_prefix(prefix)
        return {
            f"{prefix}_time": self.logical_time,
            f"{prefix}_active": self.active_chronons,
            f"{prefix}_reads": self.sector_reads,
            f"{prefix}_trace": self.trace_length,
            f"{prefix}_quadrant": self.phase_quadrant,
            f"{prefix}_header": self.period_header,
            f"{prefix}_length": self.period_length,
            f"{prefix}_stride": self.period_stride,
        }


_OBSERVATION_DECODERS = {
    _RESOLVER_PAYLOAD_TAG: ResolverObservation.from_payload,
    _TIMING_PAYLOAD_TAG: TimingObservation.from_payload,
    _DELAY_PAYLOAD_TAG: DelayObservation.from_payload,
    _TEMPORAL_PAYLOAD_TAG: TemporalObservation.from_payload,
    _PHASE_PAYLOAD_TAG: PhaseObservation.from_payload,
}
_OBSERVATION_KINDS = {"resolver", "timing", "delay", "temporal", "phase"}


def decode_substrate_observation(payload: Any) -> SubstrateObservation:
    """Mathematics: compute `E⁻¹(payload)` by tagged dispatch, or return the typed error `⊥`."""

    if not isinstance(payload, tuple) or not payload or not isinstance(payload[0], str):
        raise ObservationError("substrate observation payload lacks a tag")
    decoder = _OBSERVATION_DECODERS.get(payload[0])
    if decoder is None:
        raise ObservationError("substrate observation payload shape or tag mismatch")
    return decoder(payload)


def _validate_observation_kind(kind: Any) -> None:
    """Mathematics: restrict codec selector to finite set `K={resolver,timing,delay,temporal,phase}`."""

    if kind not in _OBSERVATION_KINDS:
        raise ObservationError(f"unsupported observation kind: {kind}")


class ObservationConflictError(ObservationError):
    """A single source attempted to provide two payloads for one logical event."""


@dataclass(frozen=True)
class ObservationAuthorityPolicy:
    """Immutable source/quorum policy governing one observation kind."""

    kind: str
    allowed_sources: tuple[str, ...]
    quorum: int
    strict: bool = True

    def __post_init__(self) -> None:
        """Mathematics: enforce `1≤q≤|A|`, unique `A⊂Σ⁺`, and `kind∈K`."""

        _validate_observation_kind(self.kind)
        if not isinstance(self.allowed_sources, (tuple, list)):
            raise ObservationError("authority allowed_sources must be a sequence")
        sources = tuple(self.allowed_sources)
        if not sources or len(set(sources)) != len(sources):
            raise ObservationError("authority allowed_sources must be non-empty and unique")
        for source in sources:
            _validate_identifier("authority source", source)
        object.__setattr__(self, "allowed_sources", tuple(sorted(sources)))
        _validate_integer("authority quorum", self.quorum, 1)
        if self.quorum > len(sources):
            raise ObservationError("authority quorum cannot exceed allowed source count")
        if not isinstance(self.strict, bool):
            raise ObservationError("authority strict flag must be boolean")


@dataclass(frozen=True)
class ObservationDecision:
    """Deterministic authority result for one `(kind,logical_time)` evidence set."""

    kind: str
    logical_time: int
    status: str
    quorum: int
    observed_sources: tuple[str, ...]
    dissenting_sources: tuple[str, ...]
    missing_sources: tuple[str, ...]
    canonical_payload: tuple[Any, ...] | None
    strict: bool

    def __post_init__(self) -> None:
        """Mathematics: admit decision status in `{PENDING,QUORUM,AUTHORIZED,CONFLICT,REFUSED}` with typed coordinates."""

        _validate_observation_kind(self.kind)
        _validate_logical_time(self.logical_time)
        if self.status not in {"PENDING", "QUORUM", "AUTHORIZED", "CONFLICT", "REFUSED"}:
            raise ObservationError(f"unknown observation decision status: {self.status}")
        _validate_integer("decision quorum", self.quorum, 1)
        if not isinstance(self.strict, bool):
            raise ObservationError("decision strict flag must be boolean")
        if any(not isinstance(source, str) for source in self.observed_sources + self.dissenting_sources + self.missing_sources):
            raise ObservationError("decision source lists must contain strings")


def _canonical_observation_payload(observation: SubstrateObservation) -> tuple[Any, ...]:
    """Mathematics: form source-free evidence signature `C(O)=E(O)[:2]+E(O)[3:]` after strict decode."""

    payload = observation.to_payload()
    decoded = decode_substrate_observation(payload)
    if decoded.kind != observation.kind or decoded.source != observation.source:
        raise ObservationError("observation payload does not match observation identity")
    return payload[:2] + payload[3:]


def _event_key(kind: str, logical_time: int) -> tuple[str, int]:
    """Mathematics: identify one evidence event by `e=(kind,logical_time)`."""

    _validate_observation_kind(kind)
    _validate_logical_time(logical_time)
    return kind, logical_time


class ObservationConsensus:
    """Snapshotable, non-authoritative quorum state for typed substrate evidence."""

    def __init__(self, policy: ObservationAuthorityPolicy) -> None:
        """Mathematics: initialize evidence relation `E_e[source]=payload` over policy event domain."""

        if not isinstance(policy, ObservationAuthorityPolicy):
            raise ObservationError("consensus requires ObservationAuthorityPolicy")
        self.policy = policy
        self._evidence: dict[tuple[str, int], dict[str, tuple[Any, ...]]] = {}
        self._conflicts: dict[tuple[str, int], set[str]] = {}
        self._finalized: dict[tuple[str, int], str] = {}

    def _validate_observation(self, observation: SubstrateObservation) -> tuple[tuple[str, int], tuple[Any, ...]]:
        """Mathematics: admit observation `O` iff `kind(O)=K` and `source(O)∈A`, returning `(e,C(O))`."""

        if not hasattr(observation, "kind") or not hasattr(observation, "source") or not hasattr(observation, "logical_time"):
            raise ObservationError("consensus requires a typed substrate observation")
        if observation.kind != self.policy.kind:
            raise ObservationError("observation kind does not match authority policy")
        if observation.source not in self.policy.allowed_sources:
            raise ObservationError("observation source is not authorized by policy")
        return (
            _event_key(observation.kind, observation.logical_time),
            _canonical_observation_payload(observation),
        )

    def ingest(self, observation: SubstrateObservation) -> ObservationDecision:
        """Mathematics: insert source evidence idempotently, rejecting `E_e[s]≠payload` as a typed conflict."""

        event, canonical = self._validate_observation(observation)
        full_payload = observation.to_payload()
        source = observation.source
        evidence = self._evidence.setdefault(event, {})
        previous = evidence.get(source)
        if event in self._finalized:
            if previous == full_payload:
                return self.status(*event)
            raise ObservationError("observation event is already finalized")
        if previous is not None:
            if previous == full_payload:
                return self.status(*event)
            self._conflicts.setdefault(event, set()).add(source)
            raise ObservationConflictError("source provided conflicting payload for one logical event")
        evidence[source] = full_payload
        return self.status(*event)

    def _groups(self, event: tuple[str, int]) -> dict[tuple[Any, ...], tuple[str, ...]]:
        """Mathematics: partition `E_e` into equivalence classes under source-free payload equality."""

        grouped: dict[tuple[Any, ...], list[str]] = {}
        for source, payload in self._evidence.get(event, {}).items():
            signature = payload[:2] + payload[3:]
            grouped.setdefault(signature, []).append(source)
        return {signature: tuple(sorted(sources)) for signature, sources in grouped.items()}

    def _decision(self, event: tuple[str, int]) -> ObservationDecision:
        """Mathematics: calculate deterministic state-machine output from evidence partition and policy."""

        kind, logical_time = event
        evidence = self._evidence.get(event, {})
        groups = self._groups(event)
        winner: tuple[Any, ...] | None = None
        winner_sources: tuple[str, ...] = ()
        if groups:
            winner, winner_sources = min(
                groups.items(),
                key=lambda item: (-len(item[1]), tuple(repr(value) for value in item[0])),
            )
        observed_sources = tuple(sorted(evidence))
        dissenting = tuple(sorted(source for source in observed_sources if source not in winner_sources))
        missing = tuple(sorted(set(self.policy.allowed_sources) - set(observed_sources)))
        if event in self._finalized:
            status = self._finalized[event]
        elif event in self._conflicts:
            status = "CONFLICT"
        elif self.policy.strict and dissenting:
            status = "CONFLICT"
        elif winner is None or len(winner_sources) < self.policy.quorum:
            status = "PENDING"
        elif self.policy.strict and missing:
            status = "PENDING"
        else:
            status = "QUORUM"
        return ObservationDecision(
            kind=kind,
            logical_time=logical_time,
            status=status,
            quorum=self.policy.quorum,
            observed_sources=observed_sources,
            dissenting_sources=dissenting,
            missing_sources=missing,
            canonical_payload=winner,
            strict=self.policy.strict,
        )

    def status(self, kind: str, logical_time: int) -> ObservationDecision:
        """Mathematics: inspect event state `δ(e)` without mutating evidence or VM state."""

        return self._decision(_event_key(kind, logical_time))

    def finalize(self, kind: str, logical_time: int) -> ObservationDecision:
        """Mathematics: close event `e`, mapping quorum success to `AUTHORIZED` and all other states to `REFUSED`."""

        event = _event_key(kind, logical_time)
        if event in self._finalized:
            return self._decision(event)
        decision = self._decision(event)
        if decision.status == "QUORUM":
            final_status = "AUTHORIZED"
        elif decision.status == "CONFLICT":
            final_status = "CONFLICT"
        else:
            final_status = "REFUSED"
        self._finalized[event] = final_status
        return self._decision(event)

    def authorized_observation(self, kind: str, logical_time: int) -> SubstrateObservation | None:
        """Mathematics: return representative `O*` iff explicit finalization yields `AUTHORIZED`; otherwise return `None`."""

        event = _event_key(kind, logical_time)
        decision = self._decision(event)
        if decision.status != "AUTHORIZED" or decision.canonical_payload is None:
            return None
        group = self._groups(event).get(decision.canonical_payload, ())
        if not group:
            raise ObservationError("authorized decision lost its representative evidence")
        representative = self._evidence[event][group[0]]
        return decode_substrate_observation(representative)

    def snapshot(self) -> dict[str, Any]:
        """Mathematics: serialize policy, evidence relation, conflict markers, and finalization map for exact continuation."""

        return {
            "version": 1,
            "policy": {
                "kind": self.policy.kind,
                "allowed_sources": list(self.policy.allowed_sources),
                "quorum": self.policy.quorum,
                "strict": self.policy.strict,
            },
            "events": [
                {
                    "kind": kind,
                    "logical_time": logical_time,
                    "evidence": [
                        {"source": source, "payload": list(payload)}
                        for source, payload in sorted(evidence.items())
                    ],
                }
                for (kind, logical_time), evidence in sorted(self._evidence.items())
            ],
            "conflicts": [
                {"kind": kind, "logical_time": logical_time, "sources": sorted(sources)}
                for (kind, logical_time), sources in sorted(self._conflicts.items())
            ],
            "finalized": [
                {"kind": kind, "logical_time": logical_time, "status": status}
                for (kind, logical_time), status in sorted(self._finalized.items())
            ],
        }

    @classmethod
    def from_snapshot(cls, payload: Mapping[str, Any]) -> "ObservationConsensus":
        """Mathematics: restore consensus state only when every payload, identity, conflict, and final status validates."""

        if not isinstance(payload, Mapping) or int(payload.get("version", 1)) != 1:
            raise ObservationError("unsupported observation consensus snapshot version")
        raw_policy = payload.get("policy")
        if not isinstance(raw_policy, Mapping):
            raise ObservationError("consensus snapshot lacks policy")
        policy = ObservationAuthorityPolicy(
            kind=raw_policy.get("kind"),
            allowed_sources=tuple(raw_policy.get("allowed_sources", ())),
            quorum=raw_policy.get("quorum"),
            strict=raw_policy.get("strict"),
        )
        consensus = cls(policy)
        raw_events = payload.get("events", ())
        if not isinstance(raw_events, (list, tuple)):
            raise ObservationError("consensus snapshot events must be a sequence")
        for raw_event in raw_events:
            if not isinstance(raw_event, Mapping):
                raise ObservationError("consensus snapshot event must be a mapping")
            event = _event_key(str(raw_event.get("kind")), int(raw_event.get("logical_time")))
            if event[0] != policy.kind:
                raise ObservationError("consensus snapshot event kind does not match policy")
            raw_evidence = raw_event.get("evidence", ())
            if not isinstance(raw_evidence, (list, tuple)):
                raise ObservationError("consensus snapshot evidence must be a sequence")
            seen_sources: set[str] = set()
            for raw_item in raw_evidence:
                if not isinstance(raw_item, Mapping):
                    raise ObservationError("consensus snapshot evidence item must be a mapping")
                raw_payload = raw_item.get("payload")
                if not isinstance(raw_payload, (list, tuple)):
                    raise ObservationError("consensus snapshot evidence payload must be a sequence")
                observation = decode_substrate_observation(tuple(raw_payload))
                if observation.kind != event[0] or observation.logical_time != event[1]:
                    raise ObservationError("consensus snapshot evidence event mismatch")
                if observation.source != raw_item.get("source"):
                    raise ObservationError("consensus snapshot evidence source mismatch")
                if observation.source in seen_sources:
                    raise ObservationError("duplicate consensus evidence source")
                seen_sources.add(observation.source)
                consensus.ingest(observation)
        raw_conflicts = payload.get("conflicts", ())
        if not isinstance(raw_conflicts, (list, tuple)):
            raise ObservationError("consensus snapshot conflicts must be a sequence")
        for raw_conflict in raw_conflicts:
            if not isinstance(raw_conflict, Mapping):
                raise ObservationError("consensus snapshot conflict must be a mapping")
            event = _event_key(str(raw_conflict.get("kind")), int(raw_conflict.get("logical_time")))
            if event not in consensus._evidence:
                raise ObservationError("consensus conflict references unknown event")
            sources = tuple(raw_conflict.get("sources", ()))
            if len(set(sources)) != len(sources):
                raise ObservationError("duplicate consensus conflict source")
            if any(source not in policy.allowed_sources for source in sources):
                raise ObservationError("consensus conflict source is not authorized")
            consensus._conflicts[event] = set(sources)
        raw_finalized = payload.get("finalized", ())
        if not isinstance(raw_finalized, (list, tuple)):
            raise ObservationError("consensus snapshot finalized entries must be a sequence")
        seen_finalized: set[tuple[str, int]] = set()
        for raw_final in raw_finalized:
            if not isinstance(raw_final, Mapping):
                raise ObservationError("consensus finalized entry must be a mapping")
            event = _event_key(str(raw_final.get("kind")), int(raw_final.get("logical_time")))
            status = raw_final.get("status")
            if status not in {"AUTHORIZED", "CONFLICT", "REFUSED"}:
                raise ObservationError("invalid consensus finalized status")
            if event in seen_finalized:
                raise ObservationError("duplicate consensus finalized event")
            seen_finalized.add(event)
            computed = consensus._decision(event)
            if status == "AUTHORIZED" and computed.status != "QUORUM":
                raise ObservationError("authorized consensus snapshot lacks quorum")
            if status == "CONFLICT" and computed.status != "CONFLICT":
                raise ObservationError("conflict consensus snapshot lacks conflict evidence")
            if status == "REFUSED" and computed.status != "PENDING":
                raise ObservationError("refused consensus snapshot is not pending")
            consensus._finalized[event] = status
        return consensus


class SubstrateObservationEndpoint:
    """Reliable producer/consumer endpoint for any typed substrate observation."""

    def __init__(
        self,
        channel: ReliableChannel,
        target_pid: int | None = None,
        register_prefix: str = "substrate",
        observation_kind: str = "resolver",
    ) -> None:
        """Mathematics: bind reliable channel `C` to target `p`, projection namespace `r`, and codec `K`."""

        if target_pid is not None and (
            not isinstance(target_pid, int) or isinstance(target_pid, bool) or target_pid <= 0
        ):
            raise ObservationError("observation target pid must be positive")
        _validate_register_prefix(register_prefix)
        _validate_observation_kind(observation_kind)
        self.channel = channel
        self.target_pid = target_pid
        self.register_prefix = register_prefix
        self.observation_kind = observation_kind

    def publish(self, observation: SubstrateObservation) -> int:
        """Mathematics: emit `E(O)` only when `source(O)=source(C)` and `kind(O)=K`."""

        if observation.source != self.channel.source:
            raise ObservationError("observation source does not own reliable channel")
        if observation.kind != self.observation_kind:
            raise ObservationError("observation kind does not match endpoint codec")
        return self.channel.send(observation.to_payload())

    def receive(self, vm: "MailCPUVirtualMachine") -> tuple[int, SubstrateObservation] | None:
        """Mathematics: apply `peek→idempotent_apply→consume/ACK` exactly once per reliable sequence."""

        if self.target_pid is None:
            raise ObservationError("observation endpoint has no VM target")
        peeked = self.channel.peek()
        if peeked is None:
            return None
        sequence, payload = peeked
        observation = decode_substrate_observation(payload)
        if observation.kind != self.observation_kind:
            raise ObservationError("observation payload kind does not match endpoint codec")
        if observation.source != self.channel.peer:
            raise ObservationError("observation source does not match reliable peer")
        if self.target_pid not in vm.scheduler.tasks:
            raise ObservationError(f"unknown observation target pid: {self.target_pid}")
        vm.apply_substrate_observation(
            self.target_pid,
            observation,
            sequence,
            self.register_prefix,
        )
        received = self.channel.receive()
        if received is None:
            return None
        if received != (sequence, payload):
            raise ObservationError("reliable observation changed between validation and consume")
        return sequence, observation

    def process_ack(self) -> tuple[int, ...]:
        r"""Mathematics: delegate sender transition `P := P \ ACKS` to the reliable channel."""

        return self.channel.process_ack()

    def snapshot(self) -> dict[str, Any]:
        """Mathematics: serialize endpoint binding `E=(C,target,prefix,K)` for continuation."""

        return {
            "version": 1,
            "target_pid": self.target_pid,
            "register_prefix": self.register_prefix,
            "observation_kind": self.observation_kind,
            "channel": self.channel.snapshot(),
        }

    @classmethod
    def from_snapshot(
        cls,
        payload: Mapping[str, Any],
        transport: "Transport",
    ) -> "SubstrateObservationEndpoint":
        """Mathematics: reconstruct `E'` only when version, target, prefix, codec, and channel state validate."""

        if not isinstance(payload, Mapping) or int(payload.get("version", 1)) != 1:
            raise ObservationError("unsupported observation endpoint snapshot version")
        target = payload.get("target_pid")
        target_pid = None if target is None else int(target)
        channel = ReliableChannel.from_snapshot(dict(payload["channel"]), transport)
        return SubstrateObservationEndpoint(
            channel,
            target_pid,
            str(payload.get("register_prefix", "substrate")),
            str(payload.get("observation_kind", "resolver")),
        )


class ResolverObservationEndpoint(SubstrateObservationEndpoint):
    """Compatibility endpoint retaining the resolver-specific public constructor and snapshot contract."""

    def __init__(
        self,
        channel: ReliableChannel,
        target_pid: int | None = None,
        register_prefix: str = "resolver",
    ) -> None:
        """Mathematics: specialize generic endpoint codec `K` to resolver observations."""

        super().__init__(channel, target_pid, register_prefix, "resolver")

    @classmethod
    def from_snapshot(
        cls,
        payload: Mapping[str, Any],
        transport: "Transport",
    ) -> "ResolverObservationEndpoint":
        """Mathematics: restore only snapshots whose codec selector is `K=resolver`."""

        endpoint = SubstrateObservationEndpoint.from_snapshot(payload, transport)
        if endpoint.observation_kind != "resolver":
            raise ObservationError("resolver endpoint snapshot contains a non-resolver codec")
        return cls(endpoint.channel, endpoint.target_pid, endpoint.register_prefix)
