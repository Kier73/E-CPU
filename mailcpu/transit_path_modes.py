"""One logical transit path that can retain, sense, and transform state."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from math import gcd
from typing import Any, Mapping, Sequence

from .delay_loop import DelayGroup, DelayLoopEngine, DelaySlot
from .rrns import legit_range, recover_rrns


_MODES = frozenset({"memory", "sensor", "processor"})
_FORMAT = "mailcpu-transit-path-state-v1"
_GROUP_KINDS = frozenset({"single", "noscrub", "scrub"})
_PROCESSOR_OPERATORS = frozenset({"identity", "add", "sub", "mul", "xor", "and", "or"})


class TransitPathStateError(ValueError):
    """A path-mode transition, sensor event, memory operation, or checkpoint is invalid."""


def _integer(value: Any, label: str, minimum: int | None = None) -> int:
    """Validate a non-Boolean integer and its optional lower bound."""
    if not isinstance(value, int) or isinstance(value, bool):
        raise TransitPathStateError(f"{label} must be an integer")
    if minimum is not None and value < minimum:
        raise TransitPathStateError(f"{label} must be at least {minimum}")
    return value


def _finite_number(value: Any, label: str, minimum: float | None = None) -> float:
    """Validate a finite numeric value and its optional lower bound."""
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
        raise TransitPathStateError(f"{label} must be finite")
    result = float(value)
    if minimum is not None and result < minimum:
        raise TransitPathStateError(f"{label} must be at least {minimum}")
    return result


def _canonical(value: Any) -> bytes:
    """Serialize a value as stable finite canonical JSON bytes."""
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise TransitPathStateError(f"path state is not canonical JSON: {exc}") from exc


def _digest(value: Any) -> str:
    """Compute the SHA-256 digest of canonical JSON state."""
    return hashlib.sha256(_canonical(value)).hexdigest()


def _path_id(value: Any) -> str:
    """Validate the stable logical path identifier."""
    if not isinstance(value, str) or not value.strip() or len(value) > 128 or "\x00" in value:
        raise TransitPathStateError("path_id must be a non-empty string of at most 128 characters")
    return value


def _validated_moduli(moduli: Sequence[int], k: int) -> tuple[tuple[int, ...], int]:
    """Validate the RRNS modulus set and return its information capacity."""
    if not isinstance(moduli, Sequence) or isinstance(moduli, (str, bytes)):
        raise TransitPathStateError("moduli must be a finite integer sequence")
    values = tuple(_integer(m, "modulus", 2) for m in moduli)
    if not 1 <= k <= len(values):
        raise TransitPathStateError("k must be between one and the number of moduli")
    if len(set(values)) != len(values):
        raise TransitPathStateError("moduli must be unique")
    for index, left in enumerate(values):
        if any(gcd(left, right) != 1 for right in values[index + 1 :]):
            raise TransitPathStateError("moduli must be pairwise coprime")
    return values, legit_range(values, k)


@dataclass(frozen=True)
class PathSensorSample:
    """One observed path event; latency is an RTT measured on one monotonic clock."""

    tick: int
    sequence: int
    observation_order: int
    latency_us: int | None
    delivered: bool
    duplicate: bool
    out_of_order: bool
    gap_before: int
    recovered: bool

    def to_dict(self) -> dict[str, Any]:
        """Return the immutable observation record as a JSON-compatible dictionary."""
        return asdict(self)


@dataclass(frozen=True)
class PathSensorSummary:
    """A finite summary of retained path observations, not an estimate of one-way delay."""

    sample_count: int
    delivered_count: int
    loss_count: int
    unresolved_loss_count: int
    recovered_count: int
    duplicate_count: int
    out_of_order_count: int
    gap_count: int
    minimum_latency_us: int | None
    maximum_latency_us: int | None
    mean_latency_us: int | None
    mean_absolute_jitter_us: int | None
    slot_interval_us: int

    def to_dict(self) -> dict[str, Any]:
        """Return the immutable observation record as a JSON-compatible dictionary."""
        return asdict(self)


class TransitPathState:
    """A stable logical path with three switchable roles backed by one retained state.

    Memory uses the existing RRNS DelayLoopEngine. Sensor mode records measured
    round-trip samples and explicit loss events. Processor mode applies a small
    deterministic integer algebra to retained RRNS values or sensor history.
    Logical ticks count local state transitions; RTT values remain physical-time
    measurements supplied by the caller.
    """

    def __init__(
        self,
        path_id: str,
        *,
        nominal_rtt_s: float = 0.05,
        slot_clamping_factor: float = 3.0,
        packet_len: int = 64,
        max_sensor_events: int = 4096,
    ) -> None:
        self.path_id = _path_id(path_id)
        self.nominal_rtt_s = _finite_number(nominal_rtt_s, "nominal_rtt_s", 0.000001)
        self.slot_clamping_factor = _finite_number(slot_clamping_factor, "slot_clamping_factor", 0.000001)
        self.packet_len = _integer(packet_len, "packet_len", 1)
        self.max_sensor_events = _integer(max_sensor_events, "max_sensor_events", 1)
        self.engine = DelayLoopEngine(self.nominal_rtt_s, self.slot_clamping_factor, self.packet_len)
        self.mode = "memory"
        self.logical_tick = 0
        self.mode_history: list[dict[str, Any]] = [{"tick": 0, "mode": "memory"}]
        self.sensor_samples: list[PathSensorSample] = []
        self.processor_outputs: list[dict[str, Any]] = []
        self._seen_delivered: set[int] = set()
        self._lost_sequences: set[int] = set()
        self._recovered_sequences: set[int] = set()
        self._highest_sequence: int | None = None

    def _advance(self) -> int:
        """Advance and return the path-local logical transition counter."""
        self.logical_tick += 1
        return self.logical_tick

    def _require_mode(self, expected: str) -> None:
        """Reject an operation unless the path currently has the required role."""
        if self.mode != expected:
            raise TransitPathStateError(f"operation requires {expected!r} mode, current mode is {self.mode!r}")

    def set_mode(self, mode: str) -> int:
        """Switch roles without replacing the path, its memory engine, or its history."""
        if not isinstance(mode, str) or mode not in _MODES:
            raise TransitPathStateError("mode must be one of: memory, sensor, processor")
        if mode == self.mode:
            return self.logical_tick
        tick = self._advance()
        self.mode = mode
        self.mode_history.append({"tick": tick, "mode": mode})
        return tick

    def store(self, value: int, *, k: int, moduli: Sequence[int], kind: str = "scrub") -> int:
        """Store one unsigned integer across redundant residue slots."""
        self._require_mode("memory")
        value = _integer(value, "value", 0)
        mods, capacity = _validated_moduli(moduli, _integer(k, "k", 1))
        if value >= capacity:
            raise TransitPathStateError(f"value exceeds RRNS information capacity {capacity}")
        if not isinstance(kind, str) or kind not in _GROUP_KINDS:
            raise TransitPathStateError("group kind must be single, noscrub, or scrub")
        group = self.engine.add_group(value=value, k=k, moduli=mods, kind=kind)
        self._advance()
        return group.group_id

    def read(self, group_id: int) -> int:
        """Read a stored value by CRT without modifying its residue slots."""
        self._require_mode("memory")
        group_id = _integer(group_id, "group_id", 0)
        value, ok = self.engine.read_group(group_id)
        if not ok or value is None:
            raise TransitPathStateError("memory group is unavailable or fails RRNS consistency")
        self._advance()
        return value

    def mark_slot_lost(self, group_id: int, position: int) -> None:
        """Record a simulated slot erasure in the delay-line memory."""
        self._require_mode("memory")
        group_id = _integer(group_id, "group_id", 0)
        position = _integer(position, "position", 0)
        group = self.engine.groups.get(group_id)
        if group is None or position >= len(group.slots):
            raise TransitPathStateError("unknown memory group or slot position")
        group.slots[position].alive = False
        self._advance()

    def repair(self, group_id: int) -> int:
        """Recover a value and regenerate erased residue slots when at least k survive."""
        self._require_mode("memory")
        group_id = _integer(group_id, "group_id", 0)
        value, ok = self.engine.scrub_group(group_id)
        self._advance()
        if not ok or value is None:
            raise TransitPathStateError("memory group cannot be repaired from its surviving residue slots")
        return value

    def record_sample(self, sequence: int, latency_us: int | None, *, delivered: bool = True) -> PathSensorSample:
        """Record an RTT observation or explicit loss notification in sensor mode."""
        self._require_mode("sensor")
        sequence = _integer(sequence, "sequence", 1)
        if not isinstance(delivered, bool):
            raise TransitPathStateError("delivered must be Boolean")
        if delivered:
            latency_us = _integer(latency_us, "latency_us", 0)
        elif latency_us is not None:
            raise TransitPathStateError("a loss event must use latency_us=None")
        if len(self.sensor_samples) >= self.max_sensor_events:
            raise TransitPathStateError("sensor event capacity is exhausted")
        if not delivered and sequence in self._seen_delivered:
            raise TransitPathStateError("cannot mark an already delivered sequence as lost")

        duplicate = sequence in (self._seen_delivered if delivered else self._lost_sequences)
        out_of_order = False
        gap_before = 0
        recovered = False
        if delivered and not duplicate:
            if self._highest_sequence is not None:
                out_of_order = sequence < self._highest_sequence
                if sequence > self._highest_sequence + 1:
                    gap_before = sequence - self._highest_sequence - 1
            recovered = sequence in self._lost_sequences and sequence not in self._recovered_sequences
        tick = self._advance()
        if delivered:
            self.engine.record_rtt(latency_us / 1_000_000.0)
            if not duplicate:
                self._seen_delivered.add(sequence)
                self._highest_sequence = sequence if self._highest_sequence is None else max(self._highest_sequence, sequence)
                if recovered:
                    self._recovered_sequences.add(sequence)
        else:
            self._lost_sequences.add(sequence)
        sample = PathSensorSample(
            tick=tick,
            sequence=sequence,
            observation_order=len(self.sensor_samples) + 1,
            latency_us=latency_us,
            delivered=delivered,
            duplicate=duplicate,
            out_of_order=out_of_order,
            gap_before=gap_before,
            recovered=recovered,
        )
        self.sensor_samples.append(sample)
        return sample

    def record_round_trip(self, sequence: int, started_ns: int, completed_ns: int) -> PathSensorSample:
        """Measure an RTT from two readings of the same local monotonic clock."""
        started_ns = _integer(started_ns, "started_ns", 0)
        completed_ns = _integer(completed_ns, "completed_ns", 0)
        if completed_ns < started_ns:
            raise TransitPathStateError("completed_ns cannot precede started_ns")
        return self.record_sample(sequence, round((completed_ns - started_ns) / 1000), delivered=True)

    def mark_lost(self, sequence: int) -> PathSensorSample:
        """Record a timeout/loss decision supplied by the transport observer."""
        return self.record_sample(sequence, None, delivered=False)

    def _build_summary(self) -> PathSensorSummary:
        """Derive sensor metrics from retained observations without mutating history."""
        delivered = [sample.latency_us for sample in self.sensor_samples if sample.delivered and not sample.duplicate]
        deltas = [abs(right - left) for left, right in zip(delivered, delivered[1:])]
        mean = None if not delivered else sum(delivered) // len(delivered)
        jitter = None if not deltas else round(sum(deltas) / len(deltas))
        unresolved = self._lost_sequences - self._recovered_sequences
        return PathSensorSummary(
            sample_count=len(delivered),
            delivered_count=len(self._seen_delivered),
            loss_count=len(self._lost_sequences),
            unresolved_loss_count=len(unresolved),
            recovered_count=len(self._recovered_sequences),
            duplicate_count=sum(sample.duplicate for sample in self.sensor_samples),
            out_of_order_count=sum(sample.out_of_order for sample in self.sensor_samples),
            gap_count=sum(sample.gap_before for sample in self.sensor_samples),
            minimum_latency_us=None if not delivered else min(delivered),
            maximum_latency_us=None if not delivered else max(delivered),
            mean_latency_us=mean,
            mean_absolute_jitter_us=jitter,
            slot_interval_us=round(self.engine.slot_interval_s * 1_000_000),
        )

    def summarize(self) -> PathSensorSummary:
        """Summarize retained sensor history and retain the result as a processor output."""
        self._require_mode("processor")
        summary = self._build_summary()
        tick = self._advance()
        self.processor_outputs.append({"tick": tick, "operation": "summarize", "value": summary.to_dict()})
        return summary

    def reduce_sensor_metric(self, metric: str) -> int:
        """Apply a named deterministic reduction to retained sensor history."""
        self._require_mode("processor")
        summary = self._build_summary()
        values = summary.to_dict()
        if metric not in values or not isinstance(values[metric], int) or isinstance(values[metric], bool):
            raise TransitPathStateError("metric is unknown or has no integer value in the current sensor history")
        value = values[metric]
        tick = self._advance()
        self.processor_outputs.append({"tick": tick, "operation": f"reduce:{metric}", "value": value})
        return value

    def transform_group(self, group_id: int, operator: str, operand: int = 0) -> int:
        """Transform an RRNS-retained integer and commit the result as a new memory group."""
        self._require_mode("processor")
        group_id = _integer(group_id, "group_id", 0)
        operand = _integer(operand, "operand", 0)
        if not isinstance(operator, str) or operator not in _PROCESSOR_OPERATORS:
            raise TransitPathStateError("unsupported processor operator")
        source = self.engine.groups.get(group_id)
        if source is None:
            raise TransitPathStateError("unknown source memory group")
        value, ok = self.engine.read_group(group_id)
        if not ok or value is None:
            raise TransitPathStateError("source memory group cannot be decoded")
        operations = {
            "identity": lambda x, y: x,
            "add": lambda x, y: x + y,
            "sub": lambda x, y: x - y,
            "mul": lambda x, y: x * y,
            "xor": lambda x, y: x ^ y,
            "and": lambda x, y: x & y,
            "or": lambda x, y: x | y,
        }
        result = operations[operator](value, operand)
        if result < 0 or result >= legit_range(source.moduli, source.k):
            raise TransitPathStateError("processor result exceeds source RRNS information capacity")
        group = self.engine.add_group(result, source.k, source.moduli, source.kind)
        tick = self._advance()
        self.processor_outputs.append({
            "tick": tick,
            "operation": f"transform:{operator}",
            "source_group_id": group_id,
            "result_group_id": group.group_id,
            "operand": operand,
            "value": result,
        })
        return group.group_id

    def _engine_state(self) -> dict[str, Any]:
        """Serialize the delay engine's groups, slots, timing estimate, and allocation cursors."""
        groups = []
        for group_id, group in sorted(self.engine.groups.items()):
            groups.append({
                "group_id": group_id,
                "kind": group.kind,
                "k": group.k,
                "moduli": list(group.moduli),
                "initial_value": group.initial_value,
                "is_lost": group.is_lost,
                "scrub_count": group.scrub_count,
                "bad_recon_count": group.bad_recon_count,
                "slots": [{
                    "slot_id": slot.slot_id,
                    "group_id": slot.group_id,
                    "pos": slot.pos,
                    "modulus": slot.modulus,
                    "version": slot.version,
                    "residue": slot.residue,
                    "alive": slot.alive,
                    "sent_time": slot.sent_time,
                    "arrival_times": list(slot.arrival_times),
                    "received_count": slot.received_count,
                } for slot in sorted(group.slots, key=lambda item: item.pos)],
            })
        return {
            "nominal_rtt_s": self.engine.nominal_rtt_s,
            "slot_clamping_factor": self.engine.slot_clamping_factor,
            "packet_len": self.engine.packet_len,
            "jitter_s": self.engine.jitter_s,
            "measured_rtts": list(self.engine.measured_rtts),
            "next_group_id": self.engine._next_group_id,
            "next_slot_id": self.engine._next_slot_id,
            "groups": groups,
        }

    def snapshot(self) -> dict[str, Any]:
        """Return a digest-checked finite snapshot of the full path-mode state."""
        state = {
            "path_id": self.path_id,
            "mode": self.mode,
            "logical_tick": self.logical_tick,
            "mode_history": list(self.mode_history),
            "max_sensor_events": self.max_sensor_events,
            "sensor_samples": [sample.to_dict() for sample in self.sensor_samples],
            "processor_outputs": list(self.processor_outputs),
            "engine": self._engine_state(),
        }
        return {"format": _FORMAT, "digest": _digest(state), "state": state}

    @staticmethod
    def _restore_engine(raw: Any) -> DelayLoopEngine:
        """Rebuild a delay engine only after validating its complete retained state."""
        if not isinstance(raw, Mapping) or set(raw) != {
            "nominal_rtt_s", "slot_clamping_factor", "packet_len", "jitter_s",
            "measured_rtts", "next_group_id", "next_slot_id", "groups",
        }:
            raise TransitPathStateError("path checkpoint engine fields are invalid")
        nominal = _finite_number(raw["nominal_rtt_s"], "nominal_rtt_s", 0.000001)
        factor = _finite_number(raw["slot_clamping_factor"], "slot_clamping_factor", 0.000001)
        packet_len = _integer(raw["packet_len"], "packet_len", 1)
        jitter = _finite_number(raw["jitter_s"], "jitter_s", 0.000001)
        rtts = raw["measured_rtts"]
        if not isinstance(rtts, list) or len(rtts) > 100:
            raise TransitPathStateError("engine RTT history is invalid")
        measured = [_finite_number(value, "measured RTT", 0.0) for value in rtts]
        engine = DelayLoopEngine(nominal, factor, packet_len)
        engine.jitter_s = jitter
        engine.measured_rtts = measured
        raw_groups = raw["groups"]
        if not isinstance(raw_groups, list):
            raise TransitPathStateError("engine groups must be a list")
        all_slot_ids: set[int] = set()
        for raw_group in raw_groups:
            if not isinstance(raw_group, Mapping) or set(raw_group) != {
                "group_id", "kind", "k", "moduli", "initial_value", "is_lost",
                "scrub_count", "bad_recon_count", "slots",
            }:
                raise TransitPathStateError("memory group fields are invalid")
            gid = _integer(raw_group["group_id"], "group_id", 0)
            if gid in engine.groups:
                raise TransitPathStateError("duplicate memory group ID")
            kind = raw_group["kind"]
            if not isinstance(kind, str) or kind not in _GROUP_KINDS:
                raise TransitPathStateError("memory group kind is invalid")
            mods_raw = raw_group["moduli"]
            if not isinstance(mods_raw, list):
                raise TransitPathStateError("memory group moduli must be a list")
            k = _integer(raw_group["k"], "group k", 1)
            mods, capacity = _validated_moduli(mods_raw, k)
            initial = _integer(raw_group["initial_value"], "initial_value", 0)
            if initial >= capacity:
                raise TransitPathStateError("memory initial value exceeds RRNS capacity")
            if not isinstance(raw_group["is_lost"], bool):
                raise TransitPathStateError("memory group lost flag must be Boolean")
            scrub_count = _integer(raw_group["scrub_count"], "scrub_count", 0)
            bad_recon_count = _integer(raw_group["bad_recon_count"], "bad_recon_count", 0)
            raw_slots = raw_group["slots"]
            if not isinstance(raw_slots, list) or len(raw_slots) != len(mods):
                raise TransitPathStateError("memory group slot count is inconsistent")
            slots = []
            for position, raw_slot in enumerate(raw_slots):
                if not isinstance(raw_slot, Mapping) or set(raw_slot) != {
                    "slot_id", "group_id", "pos", "modulus", "version", "residue",
                    "alive", "sent_time", "arrival_times", "received_count",
                }:
                    raise TransitPathStateError("memory slot fields are invalid")
                slot_id = _integer(raw_slot["slot_id"], "slot_id", 0)
                if slot_id in all_slot_ids:
                    raise TransitPathStateError("duplicate memory slot ID")
                all_slot_ids.add(slot_id)
                if _integer(raw_slot["group_id"], "slot group_id", 0) != gid:
                    raise TransitPathStateError("memory slot group identity mismatch")
                if _integer(raw_slot["pos"], "slot position", 0) != position:
                    raise TransitPathStateError("memory slot ordering mismatch")
                modulus = _integer(raw_slot["modulus"], "slot modulus", 2)
                if modulus != mods[position]:
                    raise TransitPathStateError("memory slot modulus mismatch")
                version = _integer(raw_slot["version"], "slot version", 0)
                residue = _integer(raw_slot["residue"], "slot residue", 0)
                if residue >= modulus:
                    raise TransitPathStateError("memory residue exceeds modulus")
                if not isinstance(raw_slot["alive"], bool):
                    raise TransitPathStateError("memory slot alive flag must be Boolean")
                sent_time = _finite_number(raw_slot["sent_time"], "slot sent_time", 0.0)
                arrivals_raw = raw_slot["arrival_times"]
                if not isinstance(arrivals_raw, list):
                    raise TransitPathStateError("slot arrival_times must be a list")
                arrivals = [_finite_number(value, "slot arrival time", 0.0) for value in arrivals_raw]
                received = _integer(raw_slot["received_count"], "received_count", 0)
                if received < len(arrivals):
                    raise TransitPathStateError("slot received_count is below retained arrivals")
                slot = DelaySlot(slot_id, gid, position, modulus, version, residue, raw_slot["alive"], sent_time, arrivals, received)
                slots.append(slot)
                engine.slots_by_id[slot_id] = slot
            group = DelayGroup(gid, kind, k, mods, initial, slots, raw_group["is_lost"], scrub_count, bad_recon_count)
            alive_pairs = [(slot.modulus, slot.residue) for slot in slots if slot.alive]
            if not group.is_lost and len(alive_pairs) >= k:
                recovered_value, consistent = recover_rrns(alive_pairs, k, mods)
                if not consistent or recovered_value != initial:
                    raise TransitPathStateError("retained RRNS residues do not reconstruct the memory value")
            engine.groups[gid] = group
        next_group = _integer(raw["next_group_id"], "next_group_id", 0)
        next_slot = _integer(raw["next_slot_id"], "next_slot_id", 0)
        if next_group <= max(engine.groups, default=-1) or next_slot <= max(all_slot_ids, default=999):
            raise TransitPathStateError("engine allocation cursors do not exceed retained identities")
        engine._next_group_id = next_group
        engine._next_slot_id = next_slot
        if len(measured) >= 2:
            mean = sum(measured) / len(measured)
            variance = sum((sample - mean) ** 2 for sample in measured) / (len(measured) - 1)
            expected_jitter = max(0.0005, math.sqrt(variance))
            if not math.isclose(jitter, expected_jitter, rel_tol=1e-9, abs_tol=1e-12):
                raise TransitPathStateError("engine jitter does not match retained RTT samples")
        return engine

    @classmethod
    def from_snapshot(cls, payload: Mapping[str, Any]) -> "TransitPathState":
        """Restore a path only after digest, memory, timing, and role-history validation."""
        if not isinstance(payload, Mapping) or set(payload) != {"format", "digest", "state"}:
            raise TransitPathStateError("path checkpoint envelope is invalid")
        if payload.get("format") != _FORMAT:
            raise TransitPathStateError("unsupported transit path checkpoint format")
        state = payload.get("state")
        if not isinstance(state, Mapping) or _digest(state) != payload.get("digest"):
            raise TransitPathStateError("path checkpoint digest mismatch")
        fields = {
            "path_id", "mode", "logical_tick", "mode_history", "max_sensor_events",
            "sensor_samples", "processor_outputs", "engine",
        }
        if set(state) != fields:
            raise TransitPathStateError("path checkpoint state fields are invalid")
        mode = state["mode"]
        if not isinstance(mode, str) or mode not in _MODES:
            raise TransitPathStateError("path checkpoint mode is invalid")
        engine = cls._restore_engine(state["engine"])
        path = cls(
            state["path_id"],
            nominal_rtt_s=engine.nominal_rtt_s,
            slot_clamping_factor=engine.slot_clamping_factor,
            packet_len=engine.packet_len,
            max_sensor_events=_integer(state["max_sensor_events"], "max_sensor_events", 1),
        )
        path.engine = engine
        path.mode = mode
        path.logical_tick = _integer(state["logical_tick"], "logical_tick", 0)
        raw_history = state["mode_history"]
        if not isinstance(raw_history, list) or not raw_history:
            raise TransitPathStateError("path mode history must be non-empty")
        history = []
        last_tick = -1
        for item in raw_history:
            if not isinstance(item, Mapping) or set(item) != {"tick", "mode"}:
                raise TransitPathStateError("path mode history item is invalid")
            tick = _integer(item["tick"], "mode history tick", 0)
            item_mode = item["mode"]
            if (
                not isinstance(item_mode, str)
                or item_mode not in _MODES
                or tick <= last_tick
                or tick > path.logical_tick
                or (history and item_mode == history[-1]["mode"])
            ):
                raise TransitPathStateError("path mode history order is invalid")
            history.append({"tick": tick, "mode": item_mode})
            last_tick = tick
        if history[0] != {"tick": 0, "mode": "memory"} or history[-1]["mode"] != mode:
            raise TransitPathStateError("path mode history does not anchor the current role")
        path.mode_history = history

        raw_samples = state["sensor_samples"]
        if not isinstance(raw_samples, list) or len(raw_samples) > path.max_sensor_events:
            raise TransitPathStateError("sensor history exceeds its configured bound")
        seen: set[int] = set()
        lost: set[int] = set()
        recovered: set[int] = set()
        highest: int | None = None
        samples: list[PathSensorSample] = []
        previous_tick = 0
        for order, raw_sample in enumerate(raw_samples, start=1):
            if not isinstance(raw_sample, Mapping) or set(raw_sample) != {
                "tick", "sequence", "observation_order", "latency_us", "delivered",
                "duplicate", "out_of_order", "gap_before", "recovered",
            }:
                raise TransitPathStateError("sensor sample fields are invalid")
            tick = _integer(raw_sample["tick"], "sample tick", 1)
            sequence = _integer(raw_sample["sequence"], "sequence", 1)
            if tick <= previous_tick or tick > path.logical_tick:
                raise TransitPathStateError("sensor sample ticks are not strictly increasing")
            if _integer(raw_sample["observation_order"], "observation_order", 1) != order:
                raise TransitPathStateError("sensor observation order is inconsistent")
            delivered = raw_sample["delivered"]
            if not isinstance(delivered, bool):
                raise TransitPathStateError("sensor delivered flag must be Boolean")
            latency = raw_sample["latency_us"]
            if delivered:
                latency = _integer(latency, "latency_us", 0)
                duplicate = sequence in seen
                out_of_order = False if duplicate or highest is None else sequence < highest
                gap_before = 0 if duplicate or highest is None or sequence <= highest + 1 else sequence - highest - 1
                was_recovered = sequence in lost and sequence not in recovered
                if not duplicate:
                    seen.add(sequence)
                    highest = sequence if highest is None else max(highest, sequence)
                    if was_recovered:
                        recovered.add(sequence)
            else:
                if latency is not None or sequence in seen:
                    raise TransitPathStateError("loss sample conflicts with a delivered sample")
                duplicate = sequence in lost
                out_of_order = False
                gap_before = 0
                was_recovered = False
                lost.add(sequence)
            expected_flags = (duplicate, out_of_order, gap_before, was_recovered)
            actual_flags = (
                raw_sample["duplicate"], raw_sample["out_of_order"],
                _integer(raw_sample["gap_before"], "gap_before", 0), raw_sample["recovered"],
            )
            if any(not isinstance(flag, bool) for flag in (raw_sample["duplicate"], raw_sample["out_of_order"], raw_sample["recovered"])) or actual_flags != expected_flags:
                raise TransitPathStateError("sensor sample derived flags are inconsistent")
            samples.append(PathSensorSample(tick, sequence, order, latency, delivered, duplicate, out_of_order, gap_before, was_recovered))
            previous_tick = tick

        def role_at(tick: int) -> str:
            """Resolve the role active at a path-local logical transition."""
            current_role = history[0]["mode"]
            for transition in history[1:]:
                if transition["tick"] > tick:
                    break
                current_role = transition["mode"]
            return current_role

        if any(role_at(sample.tick) != "sensor" for sample in samples):
            raise TransitPathStateError("sensor sample occurred outside sensor mode")
        path.sensor_samples = samples
        path._seen_delivered = seen
        path._lost_sequences = lost
        path._recovered_sequences = recovered
        path._highest_sequence = highest

        raw_outputs = state["processor_outputs"]
        if not isinstance(raw_outputs, list):
            raise TransitPathStateError("processor outputs must be a list")
        outputs = []
        previous_tick = 0
        for item in raw_outputs:
            if not isinstance(item, Mapping) or "tick" not in item or "operation" not in item or "value" not in item:
                raise TransitPathStateError("processor output record is invalid")
            tick = _integer(item["tick"], "processor output tick", 1)
            if (
                tick <= previous_tick
                or tick > path.logical_tick
                or not isinstance(item["operation"], str)
                or role_at(tick) != "processor"
            ):
                raise TransitPathStateError("processor output order is invalid")
            _canonical(item)
            outputs.append(dict(item))
            previous_tick = tick
        path.processor_outputs = outputs

        expected_rtts = [sample.latency_us / 1_000_000.0 for sample in samples if sample.delivered][-100:]
        if len(expected_rtts) != len(engine.measured_rtts) or any(
            not math.isclose(left, right, rel_tol=1e-12, abs_tol=1e-12)
            for left, right in zip(expected_rtts, engine.measured_rtts)
        ):
            raise TransitPathStateError("sensor RTT history differs from delay-engine timing state")
        return path
