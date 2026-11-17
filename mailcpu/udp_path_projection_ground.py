"""PATH-GROUND-002: observe native IP/UDP peer selection and receive-queue retention.

The actual local OS network stack, not an E-CPU interpreter, performs the
connected-UDP source filtering and retains accepted datagrams before recv.
Source arithmetic is explicitly SOURCE-side stimulus generation.  Navigating
a recovered law later is a symbolic prediction; it does not assert that the
network evaluated the arithmetic or that a distant future state was measured.

Only owned 127.0.0.1 sockets are contacted.  Packet/source authentication,
public-internet routing, independent failure domains and optical computation
are NOT established by a connected UDP socket or a content digest.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from hashlib import sha256
import json
import select
import socket
import time
from typing import Any, Mapping, Sequence

from .law_certifier import Law, fit_affine, lcg_navigate
from .substrate_bootstrap import ChannelObservation

SCHEMA = "mailcpu.path-ground-002.native-udp-projection.v1"
_MAX_PROBES = 48
_MAX_MODULUS = 65521
_MAX_COORDINATE = 10**35
_FRAME_SIZE = 4


class NativePathGroundRefused(ValueError):
    """Mathematics: A candidate native-path operator, observation or Ground is unjustified."""


def _canonical(value: Any) -> bytes:
    """Mathematics: Provide the same canonical JSON byte representation as E-CPU evidence."""
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise NativePathGroundRefused("path evidence is outside canonical JSON") from exc


def _digest(value: Any) -> str:
    """Mathematics: Content identity; never authentication or physical-path attestation."""
    return sha256(_canonical(value)).hexdigest()


def _integer(value: Any, name: str, low: int, high: int) -> int:
    """Mathematics: constrain one exact integer to an explicitly bounded finite domain."""
    if type(value) is not int or not low <= value <= high:
        raise NativePathGroundRefused(f"{name} must be a strict integer in [{low}, {high}]")
    return value


def _hash(value: Any, name: str) -> str:
    """Mathematics: validate a canonical 256-bit content identity without assigning authority."""
    if type(value) is not str or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise NativePathGroundRefused(f"{name} must be lowercase SHA-256")
    return value


def _frame(value: int) -> bytes:
    """Mathematics: One exact unsigned integer payload, with no application-side source filter."""
    return value.to_bytes(_FRAME_SIZE, "big")


@dataclass(frozen=True)
class SourceAffineStimulus:
    """Mathematics: An explicitly SOURCE-generated deterministic probe, never path arithmetic."""

    a: int
    c: int
    modulus: int
    initial: int

    def __post_init__(self) -> None:
        _integer(self.modulus, "modulus", 3, _MAX_MODULUS)
        for name in ("a", "c", "initial"):
            _integer(getattr(self, name), name, 0, self.modulus - 1)

    def at(self, coordinate: int) -> int:
        """Mathematics: Use the existing E-CPU closed-form law to generate source stimuli."""
        _integer(coordinate, "source coordinate", 0, _MAX_COORDINATE)
        return lcg_navigate(self.a, self.c, self.modulus, self.initial, coordinate)


def _prepare(
    channel: ChannelObservation, observed_at: int, start: int, count: int,
    pause_seconds: float, timeout_seconds: float,
) -> None:
    """Mathematics: bound one socket probe by its native channel lease, coordinate and byte budget."""
    if not isinstance(channel, ChannelObservation):
        raise NativePathGroundRefused("native ChannelObservation required")
    if channel.source == channel.target or "bytes" not in channel.carries:
        raise NativePathGroundRefused("expected one directed native byte carrier")
    _integer(observed_at, "logical observation", channel.observed_at, channel.expires_at)
    _integer(start, "first projected coordinate", 0, 10**12)
    _integer(count, "probe count", 4, _MAX_PROBES)
    if count * 2 * _FRAME_SIZE > channel.max_payload_bytes:
        raise NativePathGroundRefused("packet payload budget exceeds observed channel")
    if (type(pause_seconds) not in (int, float) or not 0.001 <= pause_seconds <= 0.2
            or type(timeout_seconds) not in (int, float)
            or not 0.1 <= timeout_seconds <= 10):
        raise NativePathGroundRefused("controlled timing parameters are invalid")


@dataclass(frozen=True)
class KernelUdpProjectionObservation:
    """Mathematics: One measured kernel-connected UDP peer-filter/retention observation."""

    channel: ChannelObservation
    observed_at: int
    first_coordinate: int
    source_count: int
    result_values: tuple[int, ...]
    source_trace_digest: str
    received_frames_digest: str
    allowed_peer: tuple[str, int]
    unselected_peer: tuple[str, int]
    destination: tuple[str, int]
    pause_ns: int
    ready_before_receive: bool
    no_extra_datagrams: bool
    mechanism: str = "os_connected_ipv4_udp_source_filter"
    scope: str = "owned_local_kernel_stack_receive_queue_not_physical_path"

    def __post_init__(self) -> None:
        if not isinstance(self.channel, ChannelObservation):
            raise NativePathGroundRefused("native channel required")
        _integer(self.observed_at, "observed_at", self.channel.observed_at, self.channel.expires_at)
        _integer(self.first_coordinate, "first_coordinate", 0, 10**12)
        _integer(self.source_count, "source_count", 8, _MAX_PROBES * 2)
        values = tuple(self.result_values)
        if len(values) * 2 != self.source_count or not 4 <= len(values) <= _MAX_PROBES:
            raise NativePathGroundRefused("observed source/receiver cardinality mismatch")
        if any(type(v) is not int or not 0 <= v <= 0xFFFFFFFF for v in values):
            raise NativePathGroundRefused("noncanonical UDP numeric observation")
        _hash(self.source_trace_digest, "source trace")
        _hash(self.received_frames_digest, "receiver frames")
        for name in ("allowed_peer", "unselected_peer", "destination"):
            peer = getattr(self, name)
            if (not isinstance(peer, tuple) or len(peer) != 2
                    or peer[0] != "127.0.0.1"
                    or type(peer[1]) is not int or not 1 <= peer[1] <= 65535):
                raise NativePathGroundRefused(f"{name} must be an owned local IPv4 endpoint")
        if len({self.allowed_peer, self.unselected_peer, self.destination}) != 3:
            raise NativePathGroundRefused("sender and receiver sockets must be distinct")
        _integer(self.pause_ns, "pause_ns", 1, 10**11)
        if self.ready_before_receive is not True or self.no_extra_datagrams is not True:
            raise NativePathGroundRefused("kernel retention or selected-peer filter was not observed")
        if (self.mechanism != "os_connected_ipv4_udp_source_filter"
                or self.scope != "owned_local_kernel_stack_receive_queue_not_physical_path"):
            raise NativePathGroundRefused("unsupported or inflated physical-path claim")

    @property
    def digest(self) -> str:
        """Mathematics: Hash all declared evidence and ephemeral socket identity."""
        return _digest(self._identity())

    def _identity(self) -> dict[str, Any]:
        """Mathematics: project all immutable observation and mechanism fields into one identity record."""
        return {
            "channel": self.channel.to_dict(), "observed_at": self.observed_at,
            "first_coordinate": self.first_coordinate,
            "source_count": self.source_count, "result_values": list(self.result_values),
            "source_trace_digest": self.source_trace_digest,
            "received_frames_digest": self.received_frames_digest,
            "allowed_peer": list(self.allowed_peer),
            "unselected_peer": list(self.unselected_peer),
            "destination": list(self.destination),
            "pause_ns": self.pause_ns,
            "ready_before_receive": self.ready_before_receive,
            "no_extra_datagrams": self.no_extra_datagrams,
            "mechanism": self.mechanism, "scope": self.scope,
        }

    def to_dict(self) -> dict[str, Any]:
        """Mathematics: Typed, self-describing observation, not a remote signed receipt."""
        return {"schema": SCHEMA + ".observation", **self._identity(), "digest": self.digest}


def _trace_values(
    stimulus: SourceAffineStimulus, start: int, count: int,
) -> tuple[dict[str, Any], ...]:
    """Mathematics: Construct interleaved sender events; receiver never executes this generator."""
    trace: list[dict[str, Any]] = []
    for offset in range(count):
        coord = start + offset
        trace.append({"role": "selected", "value": stimulus.at(2 * coord)})
        trace.append({"role": "unselected", "value": stimulus.at(2 * coord + 1)})
    return tuple(trace)


def _exchange(
    stimulus: SourceAffineStimulus, *,
    start: int, count: int, pause_seconds: float,
    timeout_seconds: float, connected: bool,
) -> tuple[tuple[dict[str, Any], ...], tuple[bytes, ...],
           tuple[str, int], tuple[str, int], tuple[str, int], int, bool, bool]:
    """Mathematics: Exercise real OS datagram delivery; no Python receiver-side source filter."""
    trace = _trace_values(stimulus, start, count)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as receiver, \
         socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as selected, \
         socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as unselected:
        for sock in (receiver, selected, unselected):
            sock.bind(("127.0.0.1", 0))
            sock.settimeout(timeout_seconds)
        receiver.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1 << 20)
        allowed_peer = selected.getsockname()
        unselected_peer = unselected.getsockname()
        destination = receiver.getsockname()
        if connected:
            # The kernel, not a receiver Python filter, rejects other peers.
            receiver.connect(allowed_peer)
        for item in trace:
            src = selected if item["role"] == "selected" else unselected
            if src.sendto(_frame(item["value"]), destination) != _FRAME_SIZE:
                raise NativePathGroundRefused("short UDP datagram send")
        before_wait = time.monotonic_ns()
        time.sleep(pause_seconds)
        after_wait = time.monotonic_ns()
        readable = bool(select.select([receiver], [], [], timeout_seconds)[0])
        if not readable:
            raise NativePathGroundRefused("no kernel-readable datagram after idle period")
        expected = count if connected else 2 * count
        try:
            frames = tuple(receiver.recv(32) for _ in range(expected))
        except (socket.timeout, OSError) as exc:
            raise NativePathGroundRefused("UDP selection/queue delivery incomplete") from exc
        extra = bool(select.select([receiver], [], [], 0.025)[0])
    return trace, frames, allowed_peer, unselected_peer, destination, \
        after_wait - before_wait, readable, not extra


def probe_connected_udp_projection(
    stimulus: SourceAffineStimulus, *, channel: ChannelObservation,
    observed_at: int, first_coordinate: int, count: int = 16,
    pause_seconds: float = 0.015, timeout_seconds: float = 2.0,
) -> tuple[KernelUdpProjectionObservation, tuple[dict[str, Any], ...], tuple[bytes, ...]]:
    """Mathematics: Measure a real connected UDP socket filtering interleaved sources before recv.

    Return the source trace and actual receiver bytes separately, so a checker
    can re-evaluate the evidence rather than trusting the receipt's own digest.
    """
    if not isinstance(stimulus, SourceAffineStimulus):
        raise NativePathGroundRefused("typed SOURCE-side stimulus required")
    _prepare(channel, observed_at, first_coordinate, count, pause_seconds, timeout_seconds)
    try:
        trace, frames, allowed, unselected, destination, pause, ready, no_extra = _exchange(
            stimulus, start=first_coordinate, count=count,
            pause_seconds=pause_seconds, timeout_seconds=timeout_seconds,
            connected=True,
        )
    except OSError as exc:
        raise NativePathGroundRefused(f"owned local UDP experiment failed: {type(exc).__name__}") from exc
    if len(frames) != count or any(len(frame) != _FRAME_SIZE for frame in frames):
        raise NativePathGroundRefused("connected UDP output has missing or malformed frames")
    values = tuple(int.from_bytes(frame, "big") for frame in frames)
    observation = KernelUdpProjectionObservation(
        channel, observed_at, first_coordinate, len(trace), values,
        _digest(trace), _digest([frame.hex() for frame in frames]),
        allowed, unselected, destination, pause, ready, no_extra,
    )
    if not verify_kernel_udp_projection(observation, trace, frames, channel=channel):
        raise NativePathGroundRefused("observed kernel-selected stream contradicts sender trace")
    return observation, trace, frames


def probe_unconnected_udp_control(
    stimulus: SourceAffineStimulus, *, channel: ChannelObservation,
    observed_at: int, first_coordinate: int, count: int = 16,
    pause_seconds: float = 0.015,
) -> tuple[tuple[dict[str, Any], ...], tuple[bytes, ...]]:
    """Mathematics: Bypass control: without the kernel peer pin, both interleaved sources arrive.

    This is deliberately NOT a KernelUdpProjectionObservation: it does not
    satisfy the selected-source Ground and may expose different arrival order.
    """
    _prepare(channel, observed_at, first_coordinate, count, pause_seconds, 2.0)
    trace, frames, _a, _b, _dst, _pause, ready, no_extra = _exchange(
        stimulus, start=first_coordinate, count=count,
        pause_seconds=pause_seconds, timeout_seconds=2.0, connected=False,
    )
    if not ready or not no_extra or Counter(frames) != Counter(_frame(x["value"]) for x in trace):
        raise NativePathGroundRefused("unconnected bypass did not deliver both source streams")
    return trace, frames


def verify_kernel_udp_projection(
    observation: KernelUdpProjectionObservation,
    trace: Sequence[Mapping[str, Any]],
    received: Sequence[bytes], *, channel: ChannelObservation,
) -> bool:
    """Mathematics: Replay content identities, selection and exact frame order from supplied bytes.

    Physical provenance remains the executing probe's local trust boundary;
    a forged serialized report cannot remotely attest to kernel activity.
    """
    try:
        if (not isinstance(observation, KernelUdpProjectionObservation)
                or observation.channel != channel
                or not isinstance(trace, (list, tuple))
                or not isinstance(received, (list, tuple))
                or len(trace) != observation.source_count
                or len(received) != len(observation.result_values)
                or _digest(trace) != observation.source_trace_digest
                or _digest([frame.hex() for frame in received]) != observation.received_frames_digest):
            return False
        if any(type(frame) is not bytes or len(frame) != _FRAME_SIZE for frame in received):
            return False
        if any(not isinstance(item, Mapping) or set(item) != {"role", "value"}
               or item["role"] not in {"selected", "unselected"}
               or type(item["value"]) is not int
               or not 0 <= item["value"] <= 0xFFFFFFFF for item in trace):
            return False
        selected: list[bytes] = []
        for i in range(0, len(trace), 2):
            if trace[i]["role"] != "selected" or trace[i + 1]["role"] != "unselected":
                return False
            selected.append(_frame(trace[i]["value"]))
        return (tuple(selected) == tuple(received)
                and tuple(int.from_bytes(frame, "big") for frame in received)
                == observation.result_values)
    except (TypeError, ValueError, KeyError, AttributeError):
        return False


@dataclass(frozen=True)
class KernelProjectionGround:
    """Mathematics: Finite-witness-recovered affine law of kernel-selected observations."""

    a: int
    c: int
    modulus: int
    initial: int
    train_count: int
    holdout_count: int
    evidence_digest: str
    scope: str = "empirical_owned_kernel_peer_filter_not_future_network_proof"

    def __post_init__(self) -> None:
        _integer(self.modulus, "modulus", 3, _MAX_MODULUS)
        for name in ("a", "c", "initial"):
            _integer(getattr(self, name), name, 0, self.modulus - 1)
        _integer(self.train_count, "training count", 4, _MAX_PROBES)
        _integer(self.holdout_count, "heldout count", 4, _MAX_PROBES)
        _hash(self.evidence_digest, "evidence digest")
        if self.scope != "empirical_owned_kernel_peer_filter_not_future_network_proof":
            raise NativePathGroundRefused("a finite observation cannot claim universal network validity")

    @property
    def ground_digest(self) -> str:
        """Mathematics: Mathematical relation independent of particular socket IDs and path receipts."""
        return _digest({
            "schema": SCHEMA + ".mathematical-ground", "family": "lcg",
            "a": self.a, "c": self.c, "modulus": self.modulus,
            "initial": self.initial, "observer": "selected_udp_peer_u32",
            "source_pattern": "interleaved_two_peer_stream",
        })

    @property
    def law(self) -> Law:
        """Mathematics: Re-use E-CPU's existing law type; no second algebraic navigator."""
        return Law(
            family="lcg",
            params={"a": self.a, "c": self.c, "mod": self.modulus, "x0": self.initial},
            order=1, verdict="GROUND",
        )

    def navigate(self, coordinate: int) -> dict[str, Any]:
        """Mathematics: Predict the observation at an arbitrary symbolic coordinate in O(log t)."""
        _integer(coordinate, "requested coordinate", 0, _MAX_COORDINATE)
        return {
            "schema": SCHEMA + ".symbolic-navigation",
            "coordinate": coordinate, "value": self.law.navigate(coordinate),
            "ground_digest": self.ground_digest,
            "supporting_evidence_digest": self.evidence_digest,
            "method": "native_law_certifier_lcg_navigate",
            "scope": "symbolic_prediction_not_physical_replay_or_live_future_proof",
            "network_packets_sent_for_navigation": 0,
        }

    def propose_to_structural_memory(
        self, registry: Any, memory_id: str,
        train: KernelUdpProjectionObservation,
        holdout: KernelUdpProjectionObservation, *,
        train_trace: Sequence[Mapping[str, Any]],
        train_received: Sequence[bytes],
        holdout_trace: Sequence[Mapping[str, Any]],
        holdout_received: Sequence[bytes],
    ) -> Any:
        """Mathematics: Recheck RAW endpoint evidence before staging in the existing receiver registry.

        This method cannot substitute a self-hashed report for the original
        sender/receiver bytes, and it never grants its own admission rights.
        """
        from .structural_memory import StructuralMemoryRegistry
        if not isinstance(registry, StructuralMemoryRegistry):
            raise NativePathGroundRefused("trusted native StructuralMemoryRegistry required")
        if not verify_kernel_projection_ground(
            self, train, holdout, modulus=self.modulus,
            train_trace=train_trace, train_received=train_received,
            holdout_trace=holdout_trace, holdout_received=holdout_received,
        ):
            raise NativePathGroundRefused("unverified original native path evidence cannot be staged")
        witnesses = {
            **{i: x for i, x in enumerate(train.result_values)},
            **{self.train_count + i: x for i, x in enumerate(holdout.result_values)},
        }
        if any(self.law.navigate(i) != value for i, value in witnesses.items()):
            raise NativePathGroundRefused("Structural Memory witnesses contradict Ground")
        return registry.propose(
            memory_id, self.law, witnesses,
            domain="path-native-kernel-selection-observer",
            context={
                "experiment": SCHEMA, "mathematical_ground": self.ground_digest,
                "observation_evidence": self.evidence_digest,
                "scope": self.scope, "source_side_arithmetic": True,
                "kernel_contribution": "connected_udp_peer_filter_and_queue_retention",
            },
        )


def recognize_kernel_projection_ground(
    train: KernelUdpProjectionObservation,
    holdout: KernelUdpProjectionObservation, *,
    modulus: int, train_trace: Sequence[Mapping[str, Any]],
    train_received: Sequence[bytes], holdout_trace: Sequence[Mapping[str, Any]],
    holdout_received: Sequence[bytes],
) -> KernelProjectionGround:
    """Mathematics: Fit a law only from receiver-observed selected frames and independently checked holdouts.

    Source-side recurrence is not read by this certifier. Distinct native
    socket/channel observations support the same Ground on two placements,
    but do not establish independent hardware or future physical invariance.
    """
    _integer(modulus, "Ground modulus", 3, _MAX_MODULUS)
    if not isinstance(train, KernelUdpProjectionObservation) or not isinstance(holdout, KernelUdpProjectionObservation):
        raise NativePathGroundRefused("two typed kernel observations required")
    if (train.first_coordinate != 0
            or holdout.first_coordinate != len(train.result_values)
            or train.channel.channel_id == holdout.channel.channel_id
            or train.destination == holdout.destination
            or not verify_kernel_udp_projection(train, train_trace, train_received, channel=train.channel)
            or not verify_kernel_udp_projection(holdout, holdout_trace, holdout_received, channel=holdout.channel)):
        raise NativePathGroundRefused("topology witness, coordinate continuity, or endpoint bytes invalid")
    observed = train.result_values + holdout.result_values
    if any(value >= modulus for value in observed):
        raise NativePathGroundRefused("observed value outside declared Ground modulus")
    fit = fit_affine(train.result_values, modulus)
    if fit is None or set(fit) != {"a", "c", "M"} or fit["M"] != modulus:
        raise NativePathGroundRefused("selected output does not admit an exact affine law")
    law = Law(
        family="lcg",
        params={"a": fit["a"], "c": fit["c"], "mod": modulus,
                "x0": train.result_values[0]},
        order=1, verdict="GROUND",
    )
    if any(law.navigate(i) != v for i, v in enumerate(observed)):
        raise NativePathGroundRefused("independent held-out physical socket path contradicts the law")
    return KernelProjectionGround(
        fit["a"], fit["c"], modulus, train.result_values[0],
        len(train.result_values), len(holdout.result_values),
        _digest({"training": train.digest, "holdout": holdout.digest}),
    )


def verify_kernel_projection_ground(
    ground: KernelProjectionGround,
    train: KernelUdpProjectionObservation,
    holdout: KernelUdpProjectionObservation, **kwargs: Any,
) -> bool:
    """Mathematics: Refit and replay the complete measured evidence independently of serialized certificate."""
    try:
        return isinstance(ground, KernelProjectionGround) and ground == recognize_kernel_projection_ground(
            train, holdout, **kwargs,
        )
    except (NativePathGroundRefused, TypeError, ValueError):
        return False
