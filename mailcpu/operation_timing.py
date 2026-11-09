"""Endpoint-local phase timing for computational operations.

Timing records use TemporalContext's process-local monotonic domain. Causal
stamps order observations within an actor; they do not synchronize clocks or
make cross-host timestamp subtraction valid.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import math
import re
import threading
from typing import Any, Callable, Iterator, Mapping

from .temporal import (
    CausalStamp,
    ClockDomain,
    MonotonicReading,
    TemporalContext,
    TemporalProfile,
)

_PHASE = re.compile(r"[a-z][a-z0-9_.-]{0,63}\Z")
_CORRELATION = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,511}\Z")


class OperationTimingError(ValueError):
    """A phase sample, endpoint clock, or timing correlation is malformed."""


@dataclass(frozen=True)
class OperationTimingToken:
    """An unfinished, actor-local timing interval."""

    phase: str
    correlation_id: str | None
    started: MonotonicReading
    causal_start: CausalStamp


@dataclass(frozen=True)
class OperationTimingSample:
    """One elapsed interval with endpoint and causal provenance."""

    phase: str
    actor_id: str
    segment: int
    correlation_id: str | None
    started: MonotonicReading
    ended: MonotonicReading
    causal_start: CausalStamp
    causal_end: CausalStamp

    def __post_init__(self) -> None:
        if not isinstance(self.phase, str) or _PHASE.fullmatch(self.phase) is None:
            raise OperationTimingError("phase name is invalid")
        if not isinstance(self.actor_id, str) or not self.actor_id:
            raise OperationTimingError("actor_id must be non-empty text")
        if type(self.segment) is not int or self.segment < 0:
            raise OperationTimingError("segment must be a non-negative strict integer")
        if self.correlation_id is not None and (
            not isinstance(self.correlation_id, str)
            or _CORRELATION.fullmatch(self.correlation_id) is None
        ):
            raise OperationTimingError("correlation_id is invalid")
        if not isinstance(self.started, MonotonicReading) or not isinstance(self.ended, MonotonicReading):
            raise OperationTimingError("sample requires typed monotonic readings")
        if (self.started.actor_id, self.started.segment) != (self.actor_id, self.segment):
            raise OperationTimingError("start reading belongs to a different actor or segment")
        if (self.ended.actor_id, self.ended.segment) != (self.actor_id, self.segment):
            raise OperationTimingError("end reading belongs to a different actor or segment")
        if not isinstance(self.causal_start, CausalStamp) or not isinstance(self.causal_end, CausalStamp):
            raise OperationTimingError("sample requires typed causal stamps")
        if self.causal_start.actor_id != self.actor_id or self.causal_end.actor_id != self.actor_id:
            raise OperationTimingError("causal stamps belong to a different actor")

    @property
    def elapsed_ns(self) -> int:
        """Return duration only inside this actor's monotonic segment."""
        return self.started.elapsed_until(self.ended)

    def to_dict(self) -> dict[str, Any]:
        return {
            "phase": self.phase,
            "actor_id": self.actor_id,
            "segment": self.segment,
            "correlation_id": self.correlation_id,
            "started": self.started.to_dict(),
            "ended": self.ended.to_dict(),
            "elapsed_ns": self.elapsed_ns,
            "causal_start": self.causal_start.to_dict(),
            "causal_end": self.causal_end.to_dict(),
        }


class OperationTimingProbe:
    """Thread-safe, endpoint-local recorder built on the existing TemporalContext.

    Use one probe per logical actor/endpoint. Never share one probe between
    independent endpoint identities: their monotonic domains are intentionally
    incomparable. Samples are side-band observations and are not added to
    workload, operator, DAG, or receipt digests.
    """

    def __init__(
        self,
        actor_id: str,
        *,
        monotonic_ns: Callable[[], int] | None = None,
        context: TemporalContext | None = None,
    ) -> None:
        if context is None:
            context = TemporalContext(
                actor_id,
                TemporalProfile(frozenset({ClockDomain.MONOTONIC, ClockDomain.CAUSAL})),
                monotonic_ns=monotonic_ns,
            )
        elif not isinstance(context, TemporalContext):
            raise OperationTimingError("context must be a TemporalContext")
        if context.actor_id != actor_id:
            raise OperationTimingError("context actor_id differs from probe actor_id")
        if not context.profile.uses(ClockDomain.MONOTONIC) or not context.profile.uses(ClockDomain.CAUSAL):
            raise OperationTimingError("timing probe context requires MONOTONIC and CAUSAL domains")
        self.actor_id = actor_id
        self.context = context
        self._samples: list[OperationTimingSample] = []
        self._lock = threading.RLock()

    def start(self, phase: str, *, correlation_id: str | None = None) -> OperationTimingToken:
        if not isinstance(phase, str) or _PHASE.fullmatch(phase) is None:
            raise OperationTimingError("phase name is invalid")
        if correlation_id is not None and (
            not isinstance(correlation_id, str)
            or _CORRELATION.fullmatch(correlation_id) is None
        ):
            raise OperationTimingError("correlation_id is invalid")
        with self._lock:
            causal_start = self.context.emit_causal_stamp()
            started = self.context.monotonic_reading()
        return OperationTimingToken(phase, correlation_id, started, causal_start)

    def finish(self, token: OperationTimingToken) -> OperationTimingSample:
        if not isinstance(token, OperationTimingToken):
            raise OperationTimingError("finish requires an OperationTimingToken")
        if token.started.actor_id != self.actor_id:
            raise OperationTimingError("timing token belongs to another actor")
        with self._lock:
            ended = self.context.monotonic_reading()
            causal_end = self.context.emit_causal_stamp()
            sample = OperationTimingSample(
                phase=token.phase,
                actor_id=self.actor_id,
                segment=token.started.segment,
                correlation_id=token.correlation_id,
                started=token.started,
                ended=ended,
                causal_start=token.causal_start,
                causal_end=causal_end,
            )
            self._samples.append(sample)
        return sample

    @contextmanager
    def measure(
        self,
        phase: str,
        *,
        correlation_id: str | None = None,
    ) -> Iterator[OperationTimingToken]:
        """Record a phase even when the measured operation raises."""
        token = self.start(phase, correlation_id=correlation_id)
        try:
            yield token
        finally:
            self.finish(token)

    def clear(self) -> None:
        """Clear samples without resetting the monotonic or causal clock state."""
        with self._lock:
            self._samples.clear()

    @property
    def samples(self) -> tuple[OperationTimingSample, ...]:
        with self._lock:
            return tuple(self._samples)

    def summary(self) -> dict[str, dict[str, int]]:
        """Summarize repeated same-actor phase durations without mixing endpoints."""
        grouped: dict[str, list[int]] = {}
        for sample in self.samples:
            grouped.setdefault(sample.phase, []).append(sample.elapsed_ns)
        output: dict[str, dict[str, int]] = {}
        for phase, values in sorted(grouped.items()):
            ordered = sorted(values)
            count = len(ordered)
            middle = count // 2
            median = (
                ordered[middle]
                if count % 2
                else (ordered[middle - 1] + ordered[middle]) // 2
            )
            p95 = ordered[math.ceil((count - 1) * 0.95)]
            output[phase] = {
                "count": count,
                "min_ns": ordered[0],
                "median_ns": median,
                "p95_ns": p95,
                "max_ns": ordered[-1],
                "total_ns": sum(ordered),
                "mean_ns": sum(ordered) // count,
            }
        return output

    def to_dict(self) -> dict[str, Any]:
        with self._lock:
            samples = tuple(self._samples)
        return {
            "schema": "mailcpu.operation-timing-probe.v1",
            "actor_id": self.actor_id,
            "clock_domain": "process-local-monotonic-nanoseconds",
            "causal_domain": "actor-local-lamport-vector",
            "samples": [sample.to_dict() for sample in samples],
            "summary": self.summary(),
            "comparison_rule": (
                "Durations are endpoint-local observations. Do not subtract monotonic "
                "readings across actors or infer one-way delay from unsynchronized clocks."
            ),
        }


__all__ = [
    "OperationTimingError",
    "OperationTimingProbe",
    "OperationTimingSample",
    "OperationTimingToken",
]
