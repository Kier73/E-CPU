"""Observation-driven construction and verified navigation of E-CPU state-space Grounds.

The module joins existing observation consensus, Structural Memory certification,
contextual orbit addressing, intent prototypes, predictive description selection,
and receiver-local Hypervisor dispatch. It deliberately does not add a second
Ground certifier or a second execution authority.

An observed stream has two distinct coordinates:
- event time: the source-provided logical time retained as provenance;
- orbit coordinate: the zero-based position in the explicitly ordered sample
  sequence supplied to Structural Memory trace recovery.

Neither event time nor wall-clock time is silently converted into the other.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
import hashlib
import json
import re
import time
from typing import Any, Mapping, Sequence

from .classifier import HypervisorAction, HypervisorDecision, HypervisorDomain
from .composed_ground import (\n    ComposedGroundNavigationResult,\n    ComposedVirtualGroundAddress,\n    ComposedVirtualGroundNavigator,\n)
from .headless import HeadlessOS
from .intent_embedding import IntentPrediction, IntentPrototypeModel
from .observation import ObservationConsensus
from .observer_orbit import (
    ContextualOrbitAddress,
    ContextualOrbitNavigator,
    ObserverContract,
    ObserverReceipt,
    OrbitNavigationResult,
    OrbitValueResult,
    contextual_orbit_context,
    verify_observer_receipt,
)
from .predictive_selection import (
    PredictiveCandidatePool,
    PredictiveCandidatePoolBuilder,
    PredictiveDescriptionCandidate,
    PredictiveDescriptionSelector,
    PredictiveGroundObservation,
    PredictiveSelectionReport,
)
from .seed import SystemIdentity
from .semantic_translation import (
    ObservationContract,
    RepresentationRef,
    canonical_value_digest,
    structural_memory_spec_representation_ref,
)
from .structural_memory import (
    StructuralMemoryProposal,
    StructuralMemoryRegistry,
    StructuralMemoryVersion,
)
from .temporal import (
    CausalStamp,
    MonotonicReading,
    SchedulerReading,
    TemporalFrame,
    WallTimeReading,
)
from .virtual_layer import VirtualGroundRef, VirtualStructuralMemoryRef


_SCHEMA = "mailcpu.observed-orbit-pipeline.v1"
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_MAX_TRACE_SAMPLES = 65_536
_VIRTUAL_GROUND_RESOURCE_PREFIX = "/virtual-ground/"


class StateSpacePipelineError(ValueError):
    """Invalid observation trace, Ground construction, intent, or navigation request."""


def _canonical_json(value: Any, label: str) -> str:
    """Encode a finite JSON value in canonical sorted-key form."""
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise StateSpacePipelineError(f"{label} is not finite canonical JSON") from exc


def _digest(value: Any, label: str = "value") -> str:
    """Identify a canonical JSON value by SHA-256."""
    return hashlib.sha256(_canonical_json(value, label).encode("utf-8")).hexdigest()


def _require_digest(value: Any, label: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise StateSpacePipelineError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _require_identifier(value: Any, label: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise StateSpacePipelineError(f"{label} must be a safe 1-128 character identifier")
    return value


def virtual_ground_read_resource(
    memory_id: str,
    *,
    revision: int,
    context_digest: str,
) -> str:
    """Return a capability resource scoped to one admitted revision and exact Ground context."""
    if not isinstance(memory_id, str) or not memory_id.strip() or len(memory_id) > 256:
        raise StateSpacePipelineError("memory_id must be non-empty text of at most 256 characters")
    if type(revision) is not int or revision < 1:
        raise StateSpacePipelineError("revision must be a positive integer")
    _require_digest(context_digest, "context_digest")
    return _VIRTUAL_GROUND_RESOURCE_PREFIX + _digest(
        {"memory_id": memory_id, "revision": revision, "context_digest": context_digest},
        "Virtual Ground read identity",
    )


def _frame_from_dict(payload: Mapping[str, Any]) -> TemporalFrame:
    """Reconstruct a temporal frame without collapsing its independent clock domains."""
    expected = {
        "actor_id", "monotonic", "wall", "causal", "scheduler",
        "event_lambda", "chronon_phase", "chemical_tau",
    }
    if not isinstance(payload, Mapping) or set(payload) != expected:
        raise StateSpacePipelineError("temporal frame fields are invalid")
    monotonic_raw = payload["monotonic"]
    wall_raw = payload["wall"]
    causal_raw = payload["causal"]
    scheduler_raw = payload["scheduler"]
    monotonic = None if monotonic_raw is None else MonotonicReading(**monotonic_raw)
    wall = None if wall_raw is None else WallTimeReading(**wall_raw)
    causal = None if causal_raw is None else CausalStamp.from_dict(causal_raw)
    scheduler = None if scheduler_raw is None else SchedulerReading(**scheduler_raw)
    phase = payload["chronon_phase"]
    return TemporalFrame(
        actor_id=payload["actor_id"],
        monotonic=monotonic,
        wall=wall,
        causal=causal,
        scheduler=scheduler,
        event_lambda=payload["event_lambda"],
        chronon_phase=None if phase is None else tuple(phase),
        chemical_tau=payload["chemical_tau"],
    )


@dataclass(frozen=True)
class TemporalDelta:
    """A multi-domain temporal relation; absent values mean incomparable or unobserved."""

    start_actor_id: str
    end_actor_id: str
    monotonic_elapsed_ns: int | None = None
    monotonic_regressed: bool = False
    wall_elapsed_ns: int | None = None
    causal_relation: str | None = None
    scheduler_ticks: int | None = None
    event_steps: int | None = None
    chemical_tau_delta: float | None = None
    chronon_phase_from: tuple[float, float] | None = None
    chronon_phase_to: tuple[float, float] | None = None

    @classmethod
    def between(cls, earlier: TemporalFrame, later: TemporalFrame) -> "TemporalDelta":
        """Compare only clock coordinates whose scopes make comparison meaningful."""
        if not isinstance(earlier, TemporalFrame) or not isinstance(later, TemporalFrame):
            raise StateSpacePipelineError("TemporalDelta requires two TemporalFrame values")
        mono = None
        mono_regressed = False
        if earlier.monotonic is not None and later.monotonic is not None:
            if (
                earlier.monotonic.actor_id == later.monotonic.actor_id
                and earlier.monotonic.segment == later.monotonic.segment
            ):
                try:
                    mono = earlier.monotonic.elapsed_until(later.monotonic)
                except ValueError:
                    mono_regressed = True
        wall = None
        if earlier.wall is not None and later.wall is not None:
            if earlier.wall.actor_id == later.wall.actor_id:
                wall = later.wall.utc_ns - earlier.wall.utc_ns
        causal = None
        if earlier.causal is not None and later.causal is not None:
            causal = earlier.causal.relation(later.causal).value
        scheduler = None
        if earlier.scheduler is not None and later.scheduler is not None:
            if (
                earlier.scheduler.scheduler_id == later.scheduler.scheduler_id
                and later.scheduler.tick >= earlier.scheduler.tick
            ):
                scheduler = later.scheduler.tick - earlier.scheduler.tick
        event_steps = None
        if (
            earlier.actor_id == later.actor_id
            and earlier.event_lambda is not None
            and later.event_lambda is not None
            and later.event_lambda >= earlier.event_lambda
        ):
            event_steps = later.event_lambda - earlier.event_lambda
        chemical = None
        if (
            earlier.actor_id == later.actor_id
            and earlier.chemical_tau is not None
            and later.chemical_tau is not None
        ):
            chemical = later.chemical_tau - earlier.chemical_tau
        return cls(
            start_actor_id=earlier.actor_id,
            end_actor_id=later.actor_id,
            monotonic_elapsed_ns=mono,
            monotonic_regressed=mono_regressed,
            wall_elapsed_ns=wall,
            causal_relation=causal,
            scheduler_ticks=scheduler,
            event_steps=event_steps,
            chemical_tau_delta=chemical,
            chronon_phase_from=earlier.chronon_phase,
            chronon_phase_to=later.chronon_phase,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "start_actor_id": self.start_actor_id,
            "end_actor_id": self.end_actor_id,
            "monotonic_elapsed_ns": self.monotonic_elapsed_ns,
            "monotonic_regressed": self.monotonic_regressed,
            "wall_elapsed_ns": self.wall_elapsed_ns,
            "causal_relation": self.causal_relation,
            "scheduler_ticks": self.scheduler_ticks,
            "event_steps": self.event_steps,
            "chemical_tau_delta": self.chemical_tau_delta,
            "chronon_phase_from": None if self.chronon_phase_from is None else list(self.chronon_phase_from),
            "chronon_phase_to": None if self.chronon_phase_to is None else list(self.chronon_phase_to),
        }


@dataclass(frozen=True)
class TemporalPathEvent:
    """One named processing stage observed by one actor at one typed temporal frame."""

    stage: str
    frame: TemporalFrame
    evidence_digest: str

    def __post_init__(self) -> None:
        _require_identifier(self.stage, "temporal path stage")
        if not isinstance(self.frame, TemporalFrame):
            raise StateSpacePipelineError("temporal path event requires a TemporalFrame")
        _require_digest(self.evidence_digest, "temporal path evidence_digest")

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "frame": self.frame.to_dict(),
            "evidence_digest": self.evidence_digest,
        }


@dataclass(frozen=True)
class TemporalPathTrace:
    """Append-only value object preserving per-stage clock frames across a communication path."""

    path_id: str
    events: tuple[TemporalPathEvent, ...] = ()

    def __post_init__(self) -> None:
        _require_identifier(self.path_id, "path_id")
        events = tuple(self.events)
        if any(not isinstance(item, TemporalPathEvent) for item in events):
            raise StateSpacePipelineError("temporal path events must be typed")
        object.__setattr__(self, "events", events)

    def append(self, stage: str, frame: TemporalFrame, evidence_digest: str) -> "TemporalPathTrace":
        """Return a new trace with one event; previous frames remain unchanged."""
        return TemporalPathTrace(
            self.path_id,
            self.events + (TemporalPathEvent(stage, frame, evidence_digest),),
        )

    @property
    def intervals(self) -> tuple[tuple[str, str, TemporalDelta], ...]:
        return tuple(
            (
                self.events[index].stage,
                self.events[index + 1].stage,
                TemporalDelta.between(self.events[index].frame, self.events[index + 1].frame),
            )
            for index in range(len(self.events) - 1)
        )

    @property
    def digest(self) -> str:
        return _digest(self.to_dict(include_digest=False), "temporal path trace")

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "TemporalPathTrace":
        """Restore a path trace and recompute every temporal interval and its identity."""
        expected = {"schema", "path_id", "events", "intervals", "digest"}
        if not isinstance(payload, Mapping) or set(payload) != expected:
            raise StateSpacePipelineError("temporal path trace fields are invalid")
        if payload["schema"] != "mailcpu.temporal-path-trace.v1" or not isinstance(payload["events"], list):
            raise StateSpacePipelineError("unsupported temporal path trace schema")
        events = []
        for item in payload["events"]:
            if not isinstance(item, Mapping) or set(item) != {"stage", "frame", "evidence_digest"}:
                raise StateSpacePipelineError("temporal path event fields are invalid")
            events.append(TemporalPathEvent(
                stage=item["stage"],
                frame=_frame_from_dict(item["frame"]),
                evidence_digest=item["evidence_digest"],
            ))
        trace = cls(payload["path_id"], tuple(events))
        expected_intervals = [
            {"from_stage": left, "to_stage": right, "delta": delta.to_dict()}
            for left, right, delta in trace.intervals
        ]
        if payload["intervals"] != expected_intervals or payload["digest"] != trace.digest:
            raise StateSpacePipelineError("temporal path trace intervals or digest failed verification")
        return trace

    def to_dict(self, *, include_digest: bool = True) -> dict[str, Any]:
        payload = {
            "schema": "mailcpu.temporal-path-trace.v1",
            "path_id": self.path_id,
            "events": [item.to_dict() for item in self.events],
            "intervals": [
                {"from_stage": left, "to_stage": right, "delta": delta.to_dict()}
                for left, right, delta in self.intervals
            ],
        }
        if include_digest:
            payload["digest"] = self.digest
        return payload


@dataclass(frozen=True)
class ObservedOrbitSample:
    """One quorum-authorized sensor/event sample at an explicit sequence coordinate."""

    coordinate: int
    logical_time: int
    value: int
    observation_kind: str
    value_register: str
    representative_source: str
    observed_sources: tuple[str, ...]
    dissenting_sources: tuple[str, ...]
    missing_sources: tuple[str, ...]
    observation_payload_json: str
    consensus_decision_digest: str
    source_frame: TemporalFrame | None = None
    receiver_frame: TemporalFrame | None = None

    def __post_init__(self) -> None:
        if type(self.coordinate) is not int or self.coordinate < 0:
            raise StateSpacePipelineError("sample coordinate must be a non-negative integer")
        if type(self.logical_time) is not int or self.logical_time < 0:
            raise StateSpacePipelineError("sample logical_time must be a non-negative integer")
        if type(self.value) is not int:
            raise StateSpacePipelineError("observed orbit values must be strict integers")
        for name, value in (
            ("observation_kind", self.observation_kind),
            ("value_register", self.value_register),
            ("representative_source", self.representative_source),
        ):
            _require_identifier(value, name)
        for name in ("observed_sources", "dissenting_sources", "missing_sources"):
            values = tuple(getattr(self, name))
            if any(not isinstance(item, str) or not item for item in values):
                raise StateSpacePipelineError(f"{name} must contain non-empty source identities")
            if tuple(sorted(set(values))) != values:
                raise StateSpacePipelineError(f"{name} must be sorted and unique")
            object.__setattr__(self, name, values)
        if self.representative_source not in self.observed_sources:
            raise StateSpacePipelineError("representative source is not included in observed_sources")
        if self.representative_source in self.dissenting_sources:
            raise StateSpacePipelineError("representative source must belong to the authorized consensus group")
        if not set(self.dissenting_sources).issubset(self.observed_sources):
            raise StateSpacePipelineError("dissenting sources must be among observed sources")
        try:
            payload = json.loads(self.observation_payload_json)
        except (TypeError, json.JSONDecodeError) as exc:
            raise StateSpacePipelineError("observation payload JSON is malformed") from exc
        if not isinstance(payload, list) or _canonical_json(payload, "observation payload") != self.observation_payload_json:
            raise StateSpacePipelineError("observation payload must be a canonical JSON array")
        _require_digest(self.consensus_decision_digest, "consensus decision digest")
        if self.source_frame is not None:
            if not isinstance(self.source_frame, TemporalFrame):
                raise StateSpacePipelineError("source_frame must be a TemporalFrame")
            if self.source_frame.actor_id != self.representative_source:
                raise StateSpacePipelineError("source_frame actor must identify the representative observation source")
        if self.receiver_frame is not None and not isinstance(self.receiver_frame, TemporalFrame):
            raise StateSpacePipelineError("receiver_frame must be a TemporalFrame")

    @property
    def latency(self) -> TemporalDelta | None:
        if self.source_frame is None or self.receiver_frame is None:
            return None
        return TemporalDelta.between(self.source_frame, self.receiver_frame)

    @property
    def digest(self) -> str:
        return _digest(self.to_dict(), "observed orbit sample")

    def to_dict(self) -> dict[str, Any]:
        return {
            "coordinate": self.coordinate,
            "logical_time": self.logical_time,
            "value": self.value,
            "observation_kind": self.observation_kind,
            "value_register": self.value_register,
            "representative_source": self.representative_source,
            "observed_sources": list(self.observed_sources),
            "dissenting_sources": list(self.dissenting_sources),
            "missing_sources": list(self.missing_sources),
            "observation_payload_json": self.observation_payload_json,
            "consensus_decision_digest": self.consensus_decision_digest,
            "source_frame": None if self.source_frame is None else self.source_frame.to_dict(),
            "receiver_frame": None if self.receiver_frame is None else self.receiver_frame.to_dict(),
            "latency": None if self.latency is None else self.latency.to_dict(),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ObservedOrbitSample":
        expected = {
            "coordinate", "logical_time", "value", "observation_kind", "value_register",
            "representative_source", "observed_sources", "dissenting_sources", "missing_sources",
            "observation_payload_json", "consensus_decision_digest", "source_frame",
            "receiver_frame", "latency",
        }
        if not isinstance(payload, Mapping) or set(payload) != expected:
            raise StateSpacePipelineError("observed orbit sample fields are invalid")
        result = cls(
            coordinate=payload["coordinate"],
            logical_time=payload["logical_time"],
            value=payload["value"],
            observation_kind=payload["observation_kind"],
            value_register=payload["value_register"],
            representative_source=payload["representative_source"],
            observed_sources=tuple(payload["observed_sources"]),
            dissenting_sources=tuple(payload["dissenting_sources"]),
            missing_sources=tuple(payload["missing_sources"]),
            observation_payload_json=payload["observation_payload_json"],
            consensus_decision_digest=payload["consensus_decision_digest"],
            source_frame=None if payload["source_frame"] is None else _frame_from_dict(payload["source_frame"]),
            receiver_frame=None if payload["receiver_frame"] is None else _frame_from_dict(payload["receiver_frame"]),
        )
        expected_latency = None if result.latency is None else result.latency.to_dict()
        if payload["latency"] != expected_latency:
            raise StateSpacePipelineError("stored latency vector differs from its source and receiver frames")
        return result


@dataclass(frozen=True)
class ObservedOrbitTrace:
    """Immutable ordered observation stream with quorum and per-sample temporal provenance."""

    stream_id: str
    observation_kind: str
    value_register: str
    allowed_sources: tuple[str, ...]
    quorum: int
    strict: bool
    samples: tuple[ObservedOrbitSample, ...]

    def __post_init__(self) -> None:
        _require_identifier(self.stream_id, "stream_id")
        _require_identifier(self.observation_kind, "observation_kind")
        _require_identifier(self.value_register, "value_register")
        sources = tuple(self.allowed_sources)
        if not sources or tuple(sorted(set(sources))) != sources:
            raise StateSpacePipelineError("allowed_sources must be sorted and unique")
        if any(not isinstance(item, str) or not item for item in sources):
            raise StateSpacePipelineError("allowed_sources must contain non-empty identities")
        object.__setattr__(self, "allowed_sources", sources)
        if type(self.quorum) is not int or not 1 <= self.quorum <= len(sources):
            raise StateSpacePipelineError("quorum must satisfy 1 <= quorum <= source count")
        if type(self.strict) is not bool:
            raise StateSpacePipelineError("strict must be Boolean")
        samples = tuple(self.samples)
        if not samples or len(samples) > _MAX_TRACE_SAMPLES:
            raise StateSpacePipelineError("trace sample count must be between 1 and the configured hard maximum")
        previous_time = -1
        for index, sample in enumerate(samples):
            if not isinstance(sample, ObservedOrbitSample) or sample.coordinate != index:
                raise StateSpacePipelineError("trace coordinates must be contiguous and zero-based")
            if sample.logical_time <= previous_time:
                raise StateSpacePipelineError("trace event logical times must be strictly increasing")
            if sample.observation_kind != self.observation_kind or sample.value_register != self.value_register:
                raise StateSpacePipelineError("trace samples disagree on observation kind or value register")
            if not set(sample.observed_sources).issubset(sources):
                raise StateSpacePipelineError("sample contains a source outside the trace authority policy")
            if len(set(sample.observed_sources) - set(sample.dissenting_sources)) < self.quorum:
                raise StateSpacePipelineError("sample does not retain an authorized quorum")
            previous_time = sample.logical_time
        object.__setattr__(self, "samples", samples)

    @property
    def values(self) -> tuple[int, ...]:
        return tuple(item.value for item in self.samples)

    @property
    def temporal_evidence_digest(self) -> str:
        return _digest(
            [
                {
                    "coordinate": item.coordinate,
                    "source_frame": None if item.source_frame is None else item.source_frame.to_dict(),
                    "receiver_frame": None if item.receiver_frame is None else item.receiver_frame.to_dict(),
                    "latency": None if item.latency is None else item.latency.to_dict(),
                }
                for item in self.samples
            ],
            "trace temporal evidence",
        )

    @property
    def context_binding(self) -> dict[str, Any]:
        """Compact identity for binding this exact stream interpretation into Ground context."""
        return {
            "schema": "mailcpu.observed-orbit-binding.v1",
            "trace_digest": self.digest,
            "stream_id": self.stream_id,
            "observation_kind": self.observation_kind,
            "value_register": self.value_register,
            "sample_count": len(self.samples),
            "first_logical_time": self.samples[0].logical_time,
            "last_logical_time": self.samples[-1].logical_time,
            "allowed_sources": list(self.allowed_sources),
            "quorum": self.quorum,
            "strict": self.strict,
            "temporal_evidence_digest": self.temporal_evidence_digest,
        }

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": _SCHEMA,
            "stream_id": self.stream_id,
            "observation_kind": self.observation_kind,
            "value_register": self.value_register,
            "allowed_sources": list(self.allowed_sources),
            "quorum": self.quorum,
            "strict": self.strict,
            "samples": [item.to_dict() for item in self.samples],
        }

    @property
    def digest(self) -> str:
        return _digest(self.identity_payload(), "observed orbit trace")

    def to_dict(self) -> dict[str, Any]:
        payload = self.identity_payload()
        payload["digest"] = self.digest
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ObservedOrbitTrace":
        expected = {
            "schema", "stream_id", "observation_kind", "value_register",
            "allowed_sources", "quorum", "strict", "samples", "digest",
        }
        if not isinstance(payload, Mapping) or set(payload) != expected or payload["schema"] != _SCHEMA:
            raise StateSpacePipelineError("observed orbit trace schema or fields are invalid")
        result = cls(
            stream_id=payload["stream_id"],
            observation_kind=payload["observation_kind"],
            value_register=payload["value_register"],
            allowed_sources=tuple(payload["allowed_sources"]),
            quorum=payload["quorum"],
            strict=payload["strict"],
            samples=tuple(ObservedOrbitSample.from_dict(item) for item in payload["samples"]),
        )
        if payload["digest"] != result.digest:
            raise StateSpacePipelineError("observed orbit trace digest mismatch")
        return result


class ObservationTraceBuilder:
    """Lift explicitly authorized consensus events into an ordered orbit sample stream."""

    def __init__(
        self,
        consensus: ObservationConsensus,
        *,
        stream_id: str,
        value_register: str,
    ) -> None:
        if not isinstance(consensus, ObservationConsensus):
            raise StateSpacePipelineError("trace builder requires ObservationConsensus")
        self.consensus = consensus
        self.stream_id = _require_identifier(stream_id, "stream_id")
        self.value_register = _require_identifier(value_register, "value_register")
        self._samples: list[ObservedOrbitSample] = []
        self._last_logical_time = -1

    def capture_authorized(
        self,
        logical_time: int,
        *,
        source_frame: TemporalFrame | None = None,
        receiver_frame: TemporalFrame | None = None,
    ) -> ObservedOrbitSample:
        """Finalize one quorum-ready event and retain its typed value plus evidence provenance."""
        if type(logical_time) is not int or logical_time < 0:
            raise StateSpacePipelineError("logical_time must be a non-negative integer")
        if logical_time <= self._last_logical_time:
            raise StateSpacePipelineError("trace events must be captured in strictly increasing logical time")
        current = self.consensus.status(self.consensus.policy.kind, logical_time)
        if current.status == "QUORUM":
            decision = self.consensus.finalize(self.consensus.policy.kind, logical_time)
        elif current.status == "AUTHORIZED":
            decision = current
        else:
            raise StateSpacePipelineError(
                f"observation event is not quorum-ready: {current.status}"
            )
        if decision.status != "AUTHORIZED":
            raise StateSpacePipelineError(
                f"observation event was not authorized after finalization: {decision.status}"
            )
        observation = self.consensus.authorized_observation(
            self.consensus.policy.kind,
            logical_time,
        )
        if observation is None:
            raise StateSpacePipelineError("authorized consensus event has no representative observation")
        values = observation.register_values(prefix=observation.kind)
        register = self.value_register
        if register not in values and not register.startswith(f"{observation.kind}_"):
            register = f"{observation.kind}_{register}"
        if register not in values:
            raise StateSpacePipelineError(
                f"observation does not expose the requested integer register {self.value_register!r}"
            )
        value = values[register]
        if type(value) is not int:
            raise StateSpacePipelineError("selected observation register is not a strict integer")
        decision_payload = {
            "kind": decision.kind,
            "logical_time": decision.logical_time,
            "status": decision.status,
            "quorum": decision.quorum,
            "observed_sources": list(decision.observed_sources),
            "dissenting_sources": list(decision.dissenting_sources),
            "missing_sources": list(decision.missing_sources),
            "canonical_payload": None if decision.canonical_payload is None else list(decision.canonical_payload),
            "strict": decision.strict,
        }
        sample = ObservedOrbitSample(
            coordinate=len(self._samples),
            logical_time=logical_time,
            value=value,
            observation_kind=observation.kind,
            value_register=register,
            representative_source=observation.source,
            observed_sources=tuple(sorted(decision.observed_sources)),
            dissenting_sources=tuple(sorted(decision.dissenting_sources)),
            missing_sources=tuple(sorted(decision.missing_sources)),
            observation_payload_json=_canonical_json(list(observation.to_payload()), "observation payload"),
            consensus_decision_digest=_digest(decision_payload, "consensus decision"),
            source_frame=source_frame,
            receiver_frame=receiver_frame,
        )
        self._samples.append(sample)
        self._last_logical_time = logical_time
        return sample

    def build(self) -> ObservedOrbitTrace:
        if not self._samples:
            raise StateSpacePipelineError("cannot build an empty observed orbit trace")
        policy = self.consensus.policy
        return ObservedOrbitTrace(
            stream_id=self.stream_id,
            observation_kind=policy.kind,
            value_register=self._samples[0].value_register if self._samples else self.value_register,
            allowed_sources=tuple(sorted(policy.allowed_sources)),
            quorum=policy.quorum,
            strict=policy.strict,
            samples=tuple(self._samples),
        )


@dataclass(frozen=True)
class GroundConstructionPlan:
    """A staged, witness-certified Ground proposal bound to one observed stream."""

    proposal: StructuralMemoryProposal
    trace: ObservedOrbitTrace
    system_identity: SystemIdentity
    base_ground: VirtualGroundRef
    computational_ground: RepresentationRef
    scheduler_id: str
    context_extensions_json: str
    context_json: str

    def __post_init__(self) -> None:
        if not isinstance(self.proposal, StructuralMemoryProposal):
            raise StateSpacePipelineError("Ground plan requires a StructuralMemoryProposal")
        if not isinstance(self.trace, ObservedOrbitTrace):
            raise StateSpacePipelineError("Ground plan requires an ObservedOrbitTrace")
        if not isinstance(self.system_identity, SystemIdentity):
            raise StateSpacePipelineError("Ground plan requires a SystemIdentity")
        if not isinstance(self.base_ground, VirtualGroundRef):
            raise StateSpacePipelineError("Ground plan requires a VirtualGroundRef")
        if not isinstance(self.computational_ground, RepresentationRef):
            raise StateSpacePipelineError("Ground plan requires a Computational Ground representation")
        _require_identifier(self.scheduler_id, "scheduler_id")
        for field_name in ("context_extensions_json", "context_json"):
            raw = getattr(self, field_name)
            try:
                parsed = json.loads(raw)
            except (TypeError, json.JSONDecodeError) as exc:
                raise StateSpacePipelineError(f"{field_name} is malformed") from exc
            if _canonical_json(parsed, field_name) != raw:
                raise StateSpacePipelineError(f"{field_name} must be canonical JSON")

    @property
    def context_extensions(self) -> dict[str, Any]:
        return json.loads(self.context_extensions_json)

    @property
    def digest(self) -> str:
        return _digest(self.to_dict(include_digest=False), "Ground construction plan")

    def to_dict(self, *, include_digest: bool = True) -> dict[str, Any]:
        payload = {
            "schema": "mailcpu.observed-ground-construction-plan.v1",
            "proposal_id": self.proposal.proposal_id,
            "memory_id": self.proposal.spec.memory_id,
            "spec_digest": self.proposal.spec.digest,
            "certificate_digest": self.proposal.certificate.digest,
            "trace": self.trace.to_dict(),
            "system_identity": self.system_identity.snapshot(),
            "base_ground": self.base_ground.to_dict(),
            "computational_ground": self.computational_ground.to_dict(),
            "scheduler_id": self.scheduler_id,
            "context_extensions": self.context_extensions,
            "context": json.loads(self.context_json),
            "training_witness_count": len(self.proposal.witnesses),
        }
        if include_digest:
            payload["digest"] = self.digest
        return payload


@dataclass(frozen=True)
class GroundBinding:
    """Admitted Structural Memory revision bound to a contextual Virtual Ground and observer."""

    version: StructuralMemoryVersion
    trace: ObservedOrbitTrace
    address: ContextualOrbitAddress
    observer_contract: ObserverContract

    def __post_init__(self) -> None:
        if not isinstance(self.version, StructuralMemoryVersion):
            raise StateSpacePipelineError("Ground binding requires an admitted StructuralMemoryVersion")
        if not isinstance(self.trace, ObservedOrbitTrace):
            raise StateSpacePipelineError("Ground binding requires the original ObservedOrbitTrace")
        if not isinstance(self.address, ContextualOrbitAddress):
            raise StateSpacePipelineError("Ground binding requires a ContextualOrbitAddress")
        if not isinstance(self.observer_contract, ObserverContract):
            raise StateSpacePipelineError("Ground binding requires an ObserverContract")
        memory_ref = self.address.structural_memory
        if (
            memory_ref.memory_id != self.version.spec.memory_id
            or memory_ref.revision != self.version.spec.revision
            or memory_ref.spec_digest != self.version.spec.digest
            or memory_ref.certificate_digest != self.version.certificate.digest
        ):
            raise StateSpacePipelineError("Ground binding address does not pin the admitted Structural Memory revision")
        if self.observer_contract.context_digest != self.address.context_digest:
            raise StateSpacePipelineError("Ground observer context differs from the pinned address")

    @property
    def read_resource(self) -> str:
        return virtual_ground_read_resource(
            self.version.spec.memory_id,
            revision=self.version.spec.revision,
            context_digest=self.address.context_digest,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "mailcpu.observed-ground-binding.v1",
            "version": {
                "memory_id": self.version.spec.memory_id,
                "revision": self.version.spec.revision,
                "spec_digest": self.version.spec.digest,
                "certificate_digest": self.version.certificate.digest,
            },
            "trace": self.trace.to_dict(),
            "address": self.address.to_dict(),
            "observer_contract": self.observer_contract.to_dict(),
            "read_resource": self.read_resource,
        }


class ObservationGroundBuilder:
    """Build and bind Structural Memory only from finalized, receiver-authorized orbit traces."""

    def __init__(self, registry: StructuralMemoryRegistry) -> None:
        if not isinstance(registry, StructuralMemoryRegistry):
            raise StateSpacePipelineError("ObservationGroundBuilder requires StructuralMemoryRegistry")
        self.registry = registry

    def propose(
        self,
        trace: ObservedOrbitTrace,
        *,
        memory_id: str,
        training_count: int,
        system_identity: SystemIdentity,
        base_ground: VirtualGroundRef,
        computational_ground: RepresentationRef,
        scheduler_id: str,
        domain: str = "observed-orbit",
        context_extensions: Mapping[str, Any] | None = None,
    ) -> GroundConstructionPlan:
        """Recover a deterministic law from training samples and withheld stream samples."""
        if not isinstance(trace, ObservedOrbitTrace):
            raise StateSpacePipelineError("propose requires an ObservedOrbitTrace")
        if type(training_count) is not int or training_count < 2:
            raise StateSpacePipelineError("training_count must be an integer of at least two")
        if training_count > len(trace.samples) - 2:
            raise StateSpacePipelineError("at least two withheld samples are required for independent verification")
        if not isinstance(system_identity, SystemIdentity):
            raise StateSpacePipelineError("system_identity must be a SystemIdentity")
        if not isinstance(base_ground, VirtualGroundRef):
            raise StateSpacePipelineError("base_ground must be a VirtualGroundRef")
        if not isinstance(computational_ground, RepresentationRef):
            raise StateSpacePipelineError("computational_ground must be a RepresentationRef")
        _require_identifier(scheduler_id, "scheduler_id")
        if not isinstance(domain, str) or not domain.strip():
            raise StateSpacePipelineError("Ground domain must be non-empty text")
        extras = {} if context_extensions is None else dict(context_extensions)
        if "observed_orbit" in extras:
            raise StateSpacePipelineError("observed_orbit context is reserved for the exact trace binding")
        extensions = {
            **extras,
            "observed_orbit": trace.context_binding,
        }
        context = contextual_orbit_context(
            system_identity,
            base_ground,
            computational_ground,
            scheduler_id=scheduler_id,
            extensions=extensions,
        )
        proposal = self.registry.propose_trace(
            memory_id,
            trace.values[:training_count],
            trace.values[training_count:],
            domain=domain,
            context=context,
        )
        return GroundConstructionPlan(
            proposal=proposal,
            trace=trace,
            system_identity=system_identity,
            base_ground=base_ground,
            computational_ground=computational_ground,
            scheduler_id=scheduler_id,
            context_extensions_json=_canonical_json(extensions, "Ground context extensions"),
            context_json=_canonical_json(context, "Ground context"),
        )

    def admit(
        self,
        plan: GroundConstructionPlan,
        *,
        expected_revision: int,
        binding: str = "observed-orbit",
        observer_id: str = "observed-orbit-observer",
        observer_revision: int = 1,
        observation_contract: ObservationContract | None = None,
    ) -> GroundBinding:
        """Request trusted registry admission, then pin the admitted revision into a contextual address."""
        if not isinstance(plan, GroundConstructionPlan):
            raise StateSpacePipelineError("admit requires a GroundConstructionPlan")
        _require_identifier(binding, "Structural Memory binding")
        _require_identifier(observer_id, "observer_id")
        version = self.registry.admit(plan.proposal.proposal_id, expected_revision=expected_revision)
        memory_ref = VirtualStructuralMemoryRef.from_version(binding, version, 0)
        address = ContextualOrbitAddress(
            system_identity=plan.system_identity,
            base_ground=plan.base_ground,
            computational_ground=plan.computational_ground,
            coordinate=SchedulerReading(plan.scheduler_id, plan.base_ground.coordinate),
            structural_memory=memory_ref,
            context_extensions=plan.context_extensions,
        )
        contract = observation_contract or ObservationContract.from_definition(
            "mailcpu.observed-orbit-projection",
            1,
            {
                "fields": [
                    "coordinate",
                    "orbit_offset",
                    "value",
                    "value_digest",
                    "virtual_ground_projection_digest",
                ],
                "trace_digest": plan.trace.digest,
            },
        )
        observer = ObserverContract(
            observer_id=observer_id,
            revision=observer_revision,
            subject=structural_memory_spec_representation_ref(version.spec),
            interpretation=plan.computational_ground,
            observation=contract,
            context_digest=canonical_value_digest(json.loads(plan.context_json)),
        )
        return GroundBinding(version, plan.trace, address, observer)


@dataclass(frozen=True)
class IntentionInterpretation:
    """Digest-bound advisory interpretation of a structured intention."""

    intent_json: str
    prediction: IntentPrediction

    def __post_init__(self) -> None:
        try:
            payload = json.loads(self.intent_json)
        except (TypeError, json.JSONDecodeError) as exc:
            raise StateSpacePipelineError("intent JSON is malformed") from exc
        if not isinstance(payload, Mapping) or _canonical_json(payload, "intent") != self.intent_json:
            raise StateSpacePipelineError("intent must be a canonical JSON object")
        if not isinstance(self.prediction, IntentPrediction):
            raise StateSpacePipelineError("intention interpretation requires IntentPrediction")

    @property
    def digest(self) -> str:
        return _digest(self.to_dict(include_digest=False), "intention interpretation")

    def to_dict(self, *, include_digest: bool = True) -> dict[str, Any]:
        payload = {
            "schema": "mailcpu.intention-interpretation.v1",
            "intent_json": self.intent_json,
            "intent_digest": _digest(json.loads(self.intent_json), "structured intent"),
            "prediction": self.prediction.to_dict(),
            "authority": "advisory-only",
        }
        if include_digest:
            payload["digest"] = self.digest
        return payload


def interpret_intention(
    intention: Mapping[str, Any],
    model: IntentPrototypeModel | None = None,
) -> IntentionInterpretation:
    """Interpret a finite structured intent without granting it execution authority."""
    if not isinstance(intention, Mapping):
        raise StateSpacePipelineError("intention must be a structured mapping")
    detached = json.loads(_canonical_json(dict(intention), "structured intention"))
    if not detached:
        raise StateSpacePipelineError("structured intention must not be empty")
    selected_model = model or IntentPrototypeModel.default()
    if not isinstance(selected_model, IntentPrototypeModel):
        raise StateSpacePipelineError("model must be an IntentPrototypeModel")
    return IntentionInterpretation(
        intent_json=_canonical_json(detached, "structured intention"),
        prediction=selected_model.predict(detached),
    )


@dataclass(frozen=True)
class DescriptionSelectionStage:
    """Existing one-factor pool and Pareto selection result for a composed Ground."""

    pool: PredictiveCandidatePool
    report: PredictiveSelectionReport
    selected_candidate: PredictiveDescriptionCandidate

    def __post_init__(self) -> None:
        if not isinstance(self.pool, PredictiveCandidatePool):
            raise StateSpacePipelineError("selection stage requires a PredictiveCandidatePool")
        if not isinstance(self.report, PredictiveSelectionReport):
            raise StateSpacePipelineError("selection stage requires a PredictiveSelectionReport")
        if not isinstance(self.selected_candidate, PredictiveDescriptionCandidate):
            raise StateSpacePipelineError("selection stage requires the selected candidate")
        if self.report.selected_candidate_id != self.selected_candidate.candidate_id:
            raise StateSpacePipelineError("selected candidate differs from the report recommendation")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "mailcpu.description-selection-stage.v1",
            "pool": self.pool.to_dict(),
            "report": self.report.to_dict(),
            "selected_candidate": self.selected_candidate.to_dict(),
            "authoritative": False,
        }


def select_composed_description(
    registry: StructuralMemoryRegistry,
    address: ComposedVirtualGroundAddress,
    observations: Sequence[PredictiveGroundObservation],
    *,
    development_through_tick: int,
    validation_through_tick: int,
    max_candidates: int = 64,
) -> DescriptionSelectionStage:
    """Reuse existing admitted-version candidate generation and independent validation/test selection."""
    pool = PredictiveCandidatePoolBuilder(registry).build_one_factor(
        address,
        max_candidates=max_candidates,
    )
    report = PredictiveDescriptionSelector(registry).evaluate_pool(
        pool,
        observations,
        development_through_tick=development_through_tick,
        validation_through_tick=validation_through_tick,
    )
    selected = next(
        (item for item in pool.candidates if item.candidate_id == report.selected_candidate_id),
        None,
    )
    if selected is None:
        raise StateSpacePipelineError("selector recommended a candidate outside its explicit candidate pool")
    return DescriptionSelectionStage(pool, report, selected)


class NavigationStrategy(str, Enum):
    DIRECT_COORDINATE = "direct_coordinate"
    INVERSE_VALUE = "inverse_value"


@dataclass(frozen=True)
class NavigationPlan:
    """A non-executing strategy choice bound to the intention and optional selection report."""

    strategy: NavigationStrategy
    target_coordinate: int | None = None
    target_value: int | None = None
    operation_id: str = "mailcpu.observed-orbit.realize"
    intent_digest: str | None = None
    selection_report_digest: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.strategy, NavigationStrategy):
            try:
                object.__setattr__(self, "strategy", NavigationStrategy(self.strategy))
            except (TypeError, ValueError) as exc:
                raise StateSpacePipelineError("unsupported navigation strategy") from exc
        _require_identifier(self.operation_id, "operation_id")
        if self.strategy is NavigationStrategy.DIRECT_COORDINATE:
            if type(self.target_coordinate) is not int or self.target_coordinate < 0 or self.target_value is not None:
                raise StateSpacePipelineError("direct navigation requires only a non-negative absolute target_coordinate")
        else:
            if type(self.target_value) is not int or self.target_coordinate is not None:
                raise StateSpacePipelineError("inverse navigation requires only a strict integer target_value")
        if self.intent_digest is not None:
            _require_digest(self.intent_digest, "intent_digest")
        if self.selection_report_digest is not None:
            _require_digest(self.selection_report_digest, "selection_report_digest")

    @classmethod
    def direct(
        cls,
        target_coordinate: int,
        *,
        intent_digest: str | None = None,
        selection_report_digest: str | None = None,
        operation_id: str = "mailcpu.observed-orbit.realize",
    ) -> "NavigationPlan":
        return cls(
            NavigationStrategy.DIRECT_COORDINATE,
            target_coordinate=target_coordinate,
            operation_id=operation_id,
            intent_digest=intent_digest,
            selection_report_digest=selection_report_digest,
        )

    @classmethod
    def inverse(
        cls,
        target_value: int,
        *,
        intent_digest: str | None = None,
        selection_report_digest: str | None = None,
        operation_id: str = "mailcpu.observed-orbit.realize",
    ) -> "NavigationPlan":
        return cls(
            NavigationStrategy.INVERSE_VALUE,
            target_value=target_value,
            operation_id=operation_id,
            intent_digest=intent_digest,
            selection_report_digest=selection_report_digest,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "mailcpu.navigation-plan.v1",
            "strategy": self.strategy.value,
            "target_coordinate": self.target_coordinate,
            "target_value": self.target_value,
            "operation_id": self.operation_id,
            "intent_digest": self.intent_digest,
            "selection_report_digest": self.selection_report_digest,
            "authoritative": False,
        }

    @property
    def digest(self) -> str:
        return _digest(self.to_dict(), "navigation plan")


class GroundRealizationRefused(StateSpacePipelineError):
    """The local Hypervisor returned REVIEW or DENY, so no Ground read was realized."""

    def __init__(self, decision: HypervisorDecision) -> None:
        self.decision = decision
        super().__init__(f"Ground realization was not authorized: {decision.action.value}")


@dataclass(frozen=True)
class VerifiedGroundRealization:
    """A receiver-Hypervisor-authorized Ground observation with independently verifiable receipts."""

    decision: HypervisorDecision
    observer_contract: ObserverContract
    navigation: OrbitNavigationResult
    value_result: OrbitValueResult | None
    plan: NavigationPlan
    requested_address_digest: str
    host_pid: int
    resource: str
    host_elapsed_ns: int
    host_timing: TemporalDelta

    def __post_init__(self) -> None:
        if not isinstance(self.decision, HypervisorDecision) or self.decision.action is not HypervisorAction.ALLOW:
            raise StateSpacePipelineError("verified realization requires a receiver Hypervisor ALLOW decision")
        if not isinstance(self.observer_contract, ObserverContract):
            raise StateSpacePipelineError("verified realization requires the exact ObserverContract")
        if not isinstance(self.navigation, OrbitNavigationResult):
            raise StateSpacePipelineError("verified realization requires OrbitNavigationResult")
        if self.value_result is not None and not isinstance(self.value_result, OrbitValueResult):
            raise StateSpacePipelineError("value_result must be OrbitValueResult or None")
        if not isinstance(self.plan, NavigationPlan):
            raise StateSpacePipelineError("verified realization requires NavigationPlan")
        _require_digest(self.requested_address_digest, "requested_address_digest")
        if type(self.host_pid) is not int or self.host_pid < 0:
            raise StateSpacePipelineError("host_pid must be a non-negative integer")
        if (not isinstance(self.resource, str) or not self.resource.startswith(_VIRTUAL_GROUND_RESOURCE_PREFIX) or _SHA256.fullmatch(self.resource[len(_VIRTUAL_GROUND_RESOURCE_PREFIX):]) is None):
            raise StateSpacePipelineError("host resource is not the opaque Virtual Ground read resource")
        if type(self.host_elapsed_ns) is not int or self.host_elapsed_ns < 0:
            raise StateSpacePipelineError("host_elapsed_ns must be a non-negative integer")
        if not isinstance(self.host_timing, TemporalDelta):
            raise StateSpacePipelineError("host_timing must be a TemporalDelta")
        if not verify_observer_receipt(self.observer_contract, self.navigation.observation):
            raise StateSpacePipelineError("observer receipt failed independent contract verification")
        if self.navigation.expanded_states != 0:
            raise StateSpacePipelineError("verified direct Ground realization unexpectedly expanded intermediate states")
        if self.plan.strategy is NavigationStrategy.INVERSE_VALUE:
            if self.value_result is None or self.value_result.navigation != self.navigation:
                raise StateSpacePipelineError("inverse realization lost its verified inverse result")
            if self.value_result.target_value != self.plan.target_value:
                raise StateSpacePipelineError("inverse target value differs from the plan")
        elif self.value_result is not None:
            raise StateSpacePipelineError("direct realization cannot carry an inverse result")

    @property
    def verified(self) -> bool:
        return True

    def identity_payload(self) -> dict[str, Any]:
        read_receipt = self.navigation.projection.read_receipt
        return {
            "schema": "mailcpu.verified-ground-realization.v1",
            "hypervisor": {
                "action": self.decision.action.value,
                "domain": self.decision.domain.value,
                "decision_receipt": self.decision.receipt,
                "revision": self.decision.revision,
            },
            "observer_contract_digest": self.observer_contract.digest,
            "observer_receipt_digest": self.navigation.observation.digest,
            "projection_digest": self.navigation.projection.projection_digest,
            "structural_memory_receipt_digest": read_receipt.receipt_id,
            "requested_address_digest": self.requested_address_digest,
            "navigation_plan": self.plan.to_dict(),
            "host_pid": self.host_pid,
            "resource": self.resource,
            "host_elapsed_ns": self.host_elapsed_ns,
            "host_timing": self.host_timing.to_dict(),
            "value": self.navigation.projection.value,
            "scheduler": self.navigation.projection.coordinate.to_dict(),
            "orbit_offset": self.navigation.projection.orbit_offset,
            "inverse_result": None if self.value_result is None else self.value_result.to_dict(),
        }

    @property
    def receipt_digest(self) -> str:
        return _digest(self.identity_payload(), "verified Ground realization")

    def to_dict(self) -> dict[str, Any]:
        payload = self.identity_payload()
        payload["navigation"] = self.navigation.to_dict()
        payload["observer_contract"] = self.observer_contract.to_dict()
        payload["receipt_digest"] = self.receipt_digest
        payload["verified"] = True
        return payload


class VerifiedGroundRealizer:
    """Perform Ground navigation only inside the receiver-local Hypervisor ALLOW handler."""

    def __init__(self, registry: StructuralMemoryRegistry) -> None:
        if not isinstance(registry, StructuralMemoryRegistry):
            raise StateSpacePipelineError("VerifiedGroundRealizer requires StructuralMemoryRegistry")
        self.registry = registry
        self.navigator = ContextualOrbitNavigator(registry)

    def realize(
        self,
        operating_system: HeadlessOS,
        authority_pid: int,
        address: ContextualOrbitAddress,
        observer: ObserverContract,
        plan: NavigationPlan,
        *,
        observer_time_frame: TemporalFrame | None = None,
        host_actor_id: str = "local-host",
        host_start_frame: TemporalFrame | None = None,
        host_end_frame: TemporalFrame | None = None,
        intention: IntentionInterpretation | None = None,
    ) -> VerifiedGroundRealization:
        """Run direct or inverse navigation on the host only after actual local capability and policy checks."""
        if not isinstance(operating_system, HeadlessOS):
            raise StateSpacePipelineError("realization requires a HeadlessOS receiver")
        if type(authority_pid) is not int or authority_pid < 0:
            raise StateSpacePipelineError("authority_pid must be a non-negative integer")
        if not isinstance(address, ContextualOrbitAddress):
            raise StateSpacePipelineError("realization requires a ContextualOrbitAddress")
        if not isinstance(observer, ObserverContract):
            raise StateSpacePipelineError("realization requires an ObserverContract")
        if not isinstance(plan, NavigationPlan):
            raise StateSpacePipelineError("realization requires a NavigationPlan")
        _require_identifier(host_actor_id, "host_actor_id")
        if plan.intent_digest is not None:
            if intention is None or intention.digest != plan.intent_digest:
                raise StateSpacePipelineError("navigation plan intent digest does not match the supplied interpretation")
        elif intention is not None:
            raise StateSpacePipelineError("an intention was supplied but the navigation plan does not bind it")
        if plan.selection_report_digest is not None:
            raise StateSpacePipelineError("single-Ground realization cannot consume a composed description-selection report")
        if operating_system.structural_memory is not self.registry:
            raise StateSpacePipelineError("Ground registry must be the receiver OS's own admitted Structural Memory registry")
        resource = virtual_ground_read_resource(
            address.structural_memory.memory_id,
            revision=address.structural_memory.revision,
            context_digest=address.context_digest,
        )
        started_ns = time.monotonic_ns()

        def navigate() -> tuple[OrbitNavigationResult, OrbitValueResult | None]:
            if plan.strategy is NavigationStrategy.DIRECT_COORDINATE:
                target_tick = plan.target_coordinate
                if target_tick is None or target_tick < address.base_ground.coordinate:
                    raise StateSpacePipelineError("direct target precedes the pinned base Virtual Ground")
                offset = target_tick - address.base_ground.coordinate
                target_ref = replace(address.structural_memory, coordinate=offset)
                target_address = replace(
                    address,
                    coordinate=SchedulerReading(address.coordinate.scheduler_id, target_tick),
                    structural_memory=target_ref,
                )
                result = self.navigator.locate(
                    target_address,
                    observer,
                    operation_id=plan.operation_id,
                    time_frame=observer_time_frame,
                )
                return result, None
            inverse = self.navigator.locate_value(
                address,
                observer,
                plan.target_value,
                operation_id=plan.operation_id,
                time_frame=observer_time_frame,
            )
            return inverse.navigation, inverse

        def invoke() -> tuple[OrbitNavigationResult, OrbitValueResult | None]:
            return navigate()

        handlers = {
            domain: invoke
            for domain in HypervisorDomain
            if domain is not HypervisorDomain.REVIEW
        }
        decision, result = operating_system.hypervisor_dispatch(
            authority_pid,
            "cpu register arithmetic instruction scheduling program execution observe virtual ground state",
            resource,
            {
                "address_digest": address.digest,
                "observer_contract_digest": observer.digest,
                "navigation_plan": plan.to_dict(),
                "structural_memory_revision": address.structural_memory.revision,
            },
            handlers,
            frozenset({"read"}),
            destructive=False,
        )
        completed_ns = time.monotonic_ns()
        if decision.action is not HypervisorAction.ALLOW:
            if result is not None:
                raise StateSpacePipelineError("Hypervisor returned an effect for a non-ALLOW decision")
            raise GroundRealizationRefused(decision)
        if (
            not isinstance(result, tuple)
            or len(result) != 2
            or not isinstance(result[0], OrbitNavigationResult)
            or (result[1] is not None and not isinstance(result[1], OrbitValueResult))
        ):
            raise StateSpacePipelineError("authorized Ground handler returned an invalid navigation result")
        navigation, value_result = result
        if not verify_observer_receipt(observer, navigation.observation):
            raise StateSpacePipelineError("host navigation returned an invalid observer receipt")
        projection = navigation.projection
        pinned = address.structural_memory
        read = projection.read_receipt
        if (
            read.memory_id != pinned.memory_id
            or read.revision != pinned.revision
            or read.spec_digest != pinned.spec_digest
            or read.certificate_digest != pinned.certificate_digest
            or read.context_digest != address.context_digest
            or projection.system_identity != address.system_identity
            or projection.computational_ground != address.computational_ground
        ):
            raise StateSpacePipelineError("host observation differs from the requested pinned Ground identity")
        if value_result is not None and value_result.orbit_coordinate != projection.orbit_offset:
            raise StateSpacePipelineError("inverse coordinate differs from the realized orbit projection")
        automatic_start = TemporalFrame(
            actor_id=host_actor_id,
            monotonic=MonotonicReading(host_actor_id, 0, started_ns),
        )
        automatic_end = TemporalFrame(
            actor_id=host_actor_id,
            monotonic=MonotonicReading(host_actor_id, 0, completed_ns),
        )
        if (host_start_frame is None) != (host_end_frame is None):
            raise StateSpacePipelineError("host_start_frame and host_end_frame must be supplied together")
        if host_start_frame is None:
            host_timing = TemporalDelta.between(automatic_start, automatic_end)
        else:
            if host_start_frame.actor_id != host_actor_id or host_end_frame.actor_id != host_actor_id:
                raise StateSpacePipelineError("host timing frames must belong to host_actor_id")
            host_timing = TemporalDelta.between(host_start_frame, host_end_frame)
        return VerifiedGroundRealization(
            decision=decision,
            observer_contract=observer,
            navigation=navigation,
            value_result=value_result,
            plan=plan,
            requested_address_digest=address.digest,
            host_pid=authority_pid,
            resource=resource,
            host_elapsed_ns=completed_ns - started_ns,
            host_timing=host_timing,
        )


_COMPOSED_VIRTUAL_GROUND_RESOURCE_PREFIX = "/virtual-ground/composed/"


def composed_ground_read_resource(address: ComposedVirtualGroundAddress) -> str:
    """Return a read capability scoped to one composition, its pinned revisions, and context.

    The target coordinate is intentionally omitted: authorization grants read
    access to this exact admitted Ground composition at its navigable coordinates,
    not to a different set of component laws or a different schema/context.
    """
    if not isinstance(address, ComposedVirtualGroundAddress):
        raise StateSpacePipelineError("composed read resource requires a ComposedVirtualGroundAddress")
    identity = {
        "system_identity": address.system_identity.snapshot(),
        "base_ground": address.base_ground.to_dict(),
        "computational_ground": address.computational_ground.to_dict(),
        "state_schema": address.state_schema.to_dict(),
        "template": address.template,
        "scheduler_id": address.coordinate.scheduler_id,
        "extensions": address.to_dict()["extensions"],
        "components": [
            {
                "component_id": item.component_id,
                "field_path": list(item.field_path),
                "representation": item.representation.to_dict(),
                "value_kind": item.value_kind,
                "memory_id": item.orbit_address.structural_memory.memory_id,
                "revision": item.orbit_address.structural_memory.revision,
                "spec_digest": item.orbit_address.structural_memory.spec_digest,
                "certificate_digest": item.orbit_address.structural_memory.certificate_digest,
                "context_digest": item.orbit_address.context_digest,
            }
            for item in address.components
        ],
    }
    return _COMPOSED_VIRTUAL_GROUND_RESOURCE_PREFIX + _digest(identity, "composed Ground read identity")


def _composed_address_at_tick(
    address: ComposedVirtualGroundAddress,
    target_tick: int,
) -> ComposedVirtualGroundAddress:
    """Move one selected composition to a common absolute scheduler coordinate."""
    if type(target_tick) is not int or target_tick < address.base_ground.coordinate:
        raise StateSpacePipelineError("composed target tick must not precede the base Virtual Ground")
    coordinate = SchedulerReading(address.coordinate.scheduler_id, target_tick)
    offset = target_tick - address.base_ground.coordinate
    components = tuple(
        replace(
            component,
            orbit_address=replace(
                component.orbit_address,
                coordinate=coordinate,
                structural_memory=replace(
                    component.orbit_address.structural_memory,
                    coordinate=offset,
                ),
            ),
        )
        for component in address.components
    )
    return replace(address, coordinate=coordinate, components=components)


@dataclass(frozen=True)
class VerifiedComposedGroundRealization:
    """Hypervisor-authorized observation of one selected composed Ground at one shared coordinate."""

    decision: HypervisorDecision
    selection: DescriptionSelectionStage
    intention: IntentionInterpretation
    plan: NavigationPlan
    address: ComposedVirtualGroundAddress
    navigation: ComposedGroundNavigationResult
    observer_contract: ObserverContract
    observer_receipt: ObserverReceipt
    host_pid: int
    resource: str
    host_elapsed_ns: int
    host_actor_id: str
    host_timing: TemporalDelta

    def __post_init__(self) -> None:
        if not isinstance(self.decision, HypervisorDecision) or self.decision.action is not HypervisorAction.ALLOW:
            raise StateSpacePipelineError("composed realization requires a receiver Hypervisor ALLOW decision")
        if not isinstance(self.selection, DescriptionSelectionStage):
            raise StateSpacePipelineError("composed realization requires a description-selection stage")
        if not isinstance(self.intention, IntentionInterpretation):
            raise StateSpacePipelineError("composed realization requires an interpreted intention")
        if not isinstance(self.plan, NavigationPlan) or self.plan.strategy is not NavigationStrategy.DIRECT_COORDINATE:
            raise StateSpacePipelineError("composed realization currently requires a direct-coordinate navigation plan")
        if self.plan.intent_digest != self.intention.digest:
            raise StateSpacePipelineError("composed navigation plan is not bound to its intention")
        if self.plan.selection_report_digest != self.selection.report.digest:
            raise StateSpacePipelineError("composed navigation plan is not bound to its selection report")
        if self.plan.target_coordinate != self.address.coordinate.tick:
            raise StateSpacePipelineError("composed address coordinate differs from the navigation plan")
        if not isinstance(self.navigation, ComposedGroundNavigationResult):
            raise StateSpacePipelineError("composed realization requires ComposedGroundNavigationResult")
        if self.navigation.expanded_states != 0:
            raise StateSpacePipelineError("composed direct navigation unexpectedly expanded intermediate states")
        if self.navigation.projection.address_digest != self.address.digest:
            raise StateSpacePipelineError("composed projection does not match the realized address")
        if self.selection.selected_candidate.address.digest == self.address.digest:
            pass
        elif self.selection.selected_candidate.address.digest != _composed_address_at_tick(
            self.address,
            self.selection.selected_candidate.address.coordinate.tick,
        ).digest:
            raise StateSpacePipelineError("selected description identity differs from realized composition")
        if not isinstance(self.observer_contract, ObserverContract):
            raise StateSpacePipelineError("composed realization requires an ObserverContract")
        if not isinstance(self.observer_receipt, ObserverReceipt) or not verify_observer_receipt(
            self.observer_contract,
            self.observer_receipt,
        ):
            raise StateSpacePipelineError("composed ObserverReceipt failed independent verification")
        if self.observer_receipt.projection_digest != canonical_value_digest(self.navigation.projection.to_dict()):
            raise StateSpacePipelineError("composed ObserverReceipt does not bind the returned projection")
        if self.observer_contract.subject != self.address.state_schema:
            raise StateSpacePipelineError("composed observer subject differs from the selected state schema")
        if self.observer_contract.interpretation != self.address.computational_ground:
            raise StateSpacePipelineError("composed observer interpretation differs from the selected Computational Ground")
        if self.observer_contract.context_digest != canonical_value_digest(self.address.to_dict()):
            raise StateSpacePipelineError("composed observer context differs from the realized address")
        if type(self.host_pid) is not int or self.host_pid < 0:
            raise StateSpacePipelineError("host_pid must be a non-negative integer")
        if self.resource != composed_ground_read_resource(self.address):
            raise StateSpacePipelineError("composed host capability resource differs from the Ground composition")
        if type(self.host_elapsed_ns) is not int or self.host_elapsed_ns < 0:
            raise StateSpacePipelineError("host_elapsed_ns must be non-negative")
        _require_identifier(self.host_actor_id, "host_actor_id")
        if not isinstance(self.host_timing, TemporalDelta):
            raise StateSpacePipelineError("composed host_timing must be a TemporalDelta")
        if self.host_timing.monotonic_elapsed_ns != self.host_elapsed_ns:
            raise StateSpacePipelineError("composed host timing must match the receiver's local monotonic measurement")

    @property
    def verified(self) -> bool:
        return True

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": "mailcpu.verified-composed-ground-realization.v1",
            "hypervisor": {
                "action": self.decision.action.value,
                "domain": self.decision.domain.value,
                "decision_receipt": self.decision.receipt,
                "revision": self.decision.revision,
            },
            "selected_candidate_digest": self.selection.selected_candidate.digest,
            "selection_report_digest": self.selection.report.digest,
            "intention_digest": self.intention.digest,
            "navigation_plan_digest": self.plan.digest,
            "address_digest": self.address.digest,
            "projection_digest": self.navigation.projection.projection_digest,
            "composed_evidence_digest": self.navigation.projection.evidence_digest,
            "observer_contract_digest": self.observer_contract.digest,
            "observer_receipt_digest": self.observer_receipt.digest,
            "host_pid": self.host_pid,
            "resource": self.resource,
            "host_elapsed_ns": self.host_elapsed_ns,
            "host_actor_id": self.host_actor_id,
            "host_timing": self.host_timing.to_dict(),
            "state_digest": self.navigation.projection.state_digest,
            "scheduler": self.address.coordinate.to_dict(),
            "component_receipts": [
                item.projection.read_receipt.to_dict()
                for item in self.navigation.projection.components
            ],
        }

    @property
    def receipt_digest(self) -> str:
        return _digest(self.identity_payload(), "verified composed Ground realization")

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.identity_payload(),
            "navigation": self.navigation.to_dict(),
            "observer_contract": self.observer_contract.to_dict(),
            "observer_receipt": self.observer_receipt.to_dict(),
            "receipt_digest": self.receipt_digest,
            "verified": True,
        }


class VerifiedComposedGroundRealizer:
    """Realize a selected composed description only inside its receiver-local Hypervisor ALLOW handler."""

    def __init__(self, registry: StructuralMemoryRegistry) -> None:
        if not isinstance(registry, StructuralMemoryRegistry):
            raise StateSpacePipelineError("VerifiedComposedGroundRealizer requires StructuralMemoryRegistry")
        self.registry = registry
        self.navigator = ComposedVirtualGroundNavigator(registry)

    def realize(
        self,
        operating_system: HeadlessOS,
        authority_pid: int,
        selection: DescriptionSelectionStage,
        intention: IntentionInterpretation,
        plan: NavigationPlan,
        *,
        observer_id: str = "composed-ground-observer",
        observer_revision: int = 1,
        observer_time_frame: TemporalFrame | None = None,
        host_actor_id: str = "local-host",
    ) -> VerifiedComposedGroundRealization:
        if not isinstance(operating_system, HeadlessOS):
            raise StateSpacePipelineError("composed realization requires a HeadlessOS receiver")
        if operating_system.structural_memory is not self.registry:
            raise StateSpacePipelineError("Ground registry must be the receiver OS's own admitted Structural Memory registry")
        if type(authority_pid) is not int or authority_pid < 0:
            raise StateSpacePipelineError("authority_pid must be a non-negative integer")
        if not isinstance(selection, DescriptionSelectionStage):
            raise StateSpacePipelineError("realization requires the explicit selected-description stage")
        if not isinstance(intention, IntentionInterpretation):
            raise StateSpacePipelineError("realization requires an IntentionInterpretation")
        if not isinstance(plan, NavigationPlan) or plan.strategy is not NavigationStrategy.DIRECT_COORDINATE:
            raise StateSpacePipelineError("composed realization supports direct-coordinate navigation only")
        if plan.intent_digest != intention.digest:
            raise StateSpacePipelineError("navigation plan intent digest differs from the supplied intention")
        if plan.selection_report_digest != selection.report.digest:
            raise StateSpacePipelineError("navigation plan selection digest differs from the supplied report")
        _require_identifier(observer_id, "observer_id")
        _require_identifier(host_actor_id, "host_actor_id")
        if type(observer_revision) is not int or observer_revision < 1:
            raise StateSpacePipelineError("observer_revision must be positive")
        if plan.target_coordinate is None:
            raise StateSpacePipelineError("composed direct navigation requires a target coordinate")
        address = _composed_address_at_tick(selection.selected_candidate.address, plan.target_coordinate)
        resource = composed_ground_read_resource(address)
        observer_context = canonical_value_digest(address.to_dict())
        contract = ObserverContract(
            observer_id=observer_id,
            revision=observer_revision,
            subject=address.state_schema,
            interpretation=address.computational_ground,
            observation=ObservationContract.from_definition(
                "mailcpu.composed-ground.state-observation",
                1,
                {
                    "projection": "complete composed state",
                    "state_schema_digest": address.state_schema.content_digest,
                    "component_ids": [item.component_id for item in address.components],
                    "component_read_receipts": True,
                },
            ),
            context_digest=observer_context,
        )
        time_frame = observer_time_frame or TemporalFrame(
            actor_id=observer_id,
            scheduler=address.coordinate,
        )
        if time_frame.actor_id != observer_id:
            raise StateSpacePipelineError("observer time frame belongs to another observer")
        if time_frame.scheduler is not None and time_frame.scheduler != address.coordinate:
            raise StateSpacePipelineError("observer scheduler coordinate differs from composed address")
        started_ns = time.monotonic_ns()

        def observe_composed_state() -> tuple[ComposedGroundNavigationResult, ObserverContract, ObserverReceipt]:
            navigation = self.navigator.locate(address)
            projection_value = navigation.projection.to_dict()
            evidence_refs = tuple(
                item.projection.transition
                for item in navigation.projection.components
            )
            receipt = ObserverReceipt.issue(
                contract,
                operation_id=plan.operation_id,
                input_digest=canonical_value_digest({
                    "address_digest": address.digest,
                    "plan_digest": plan.digest,
                }),
                projection_value=projection_value,
                time_frame=time_frame,
                evidence=evidence_refs,
            )
            return navigation, contract, receipt

        handlers = {
            domain: observe_composed_state
            for domain in HypervisorDomain
            if domain is not HypervisorDomain.REVIEW
        }
        decision, result = operating_system.hypervisor_dispatch(
            authority_pid,
            "observe inspect read composed virtual ground state and structural memory",
            resource,
            {
                "address_digest": address.digest,
                "selection_report_digest": selection.report.digest,
                "selected_candidate_digest": selection.selected_candidate.digest,
                "intention_digest": intention.digest,
                "navigation_plan": plan.to_dict(),
                "component_count": len(address.components),
            },
            handlers,
            frozenset({"read"}),
            destructive=False,
        )
        completed_ns = time.monotonic_ns()
        if decision.action is not HypervisorAction.ALLOW:
            if result is not None:
                raise StateSpacePipelineError("Hypervisor returned a composed effect for a non-ALLOW decision")
            raise GroundRealizationRefused(decision)
        if (
            not isinstance(result, tuple)
            or len(result) != 3
            or not isinstance(result[0], ComposedGroundNavigationResult)
            or not isinstance(result[1], ObserverContract)
            or not isinstance(result[2], ObserverReceipt)
        ):
            raise StateSpacePipelineError("authorized composed handler returned an invalid result")
        navigation, actual_contract, receipt = result
        if actual_contract != contract or not verify_observer_receipt(contract, receipt):
            raise StateSpacePipelineError("composed observer contract or receipt failed verification")
        if receipt.projection_digest != canonical_value_digest(navigation.projection.to_dict()):
            raise StateSpacePipelineError("composed observer receipt does not bind the returned projection")
        if navigation.projection.address_digest != address.digest:
            raise StateSpacePipelineError("composed navigation returned a different address")
        expected_component_refs = {
            (item.component_id, item.orbit_address.structural_memory.memory_id,
             item.orbit_address.structural_memory.revision,
             item.orbit_address.structural_memory.spec_digest,
             item.orbit_address.structural_memory.certificate_digest)
            for item in address.components
        }
        actual_component_refs = {
            (item.address.component_id, item.projection.read_receipt.memory_id,
             item.projection.read_receipt.revision,
             item.projection.read_receipt.spec_digest,
             item.projection.read_receipt.certificate_digest)
            for item in navigation.projection.components
        }
        if actual_component_refs != expected_component_refs:
            raise StateSpacePipelineError("composed realization receipts do not match all selected component revisions")
        return VerifiedComposedGroundRealization(
            decision=decision,
            selection=selection,
            intention=intention,
            plan=plan,
            address=address,
            navigation=navigation,
            observer_contract=contract,
            observer_receipt=receipt,
            host_pid=authority_pid,
            resource=resource,
            host_elapsed_ns=completed_ns - started_ns,
            host_actor_id=host_actor_id,
            host_timing=TemporalDelta.between(
                TemporalFrame(
                    actor_id=host_actor_id,
                    monotonic=MonotonicReading(host_actor_id, 0, started_ns),
                ),
                TemporalFrame(
                    actor_id=host_actor_id,
                    monotonic=MonotonicReading(host_actor_id, 0, completed_ns),
                ),
            ),
        )
