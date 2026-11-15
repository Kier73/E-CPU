"""PATH-GROUND-001: communication path as distinct digital and measured Grounds.

A loopback TCP exchange gives live evidence for a kernel byte-stream transport
with an endpoint-to-endpoint monotonic time span. A separate finite impulse
response (FIR) calibration accepts measured input/output pairs but grants only
an evidence-scoped model hypothesis. The latter never executes on fiber here.

No path observation is an authority grant or a hardware attestation.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import math
import socket
import threading
import time
from typing import Any, Sequence

from .substrate_bootstrap import ChannelObservation

SCHEMA = "mailcpu.path-ground-probe.v1"
MAX_PAYLOAD_BYTES = 65536
MAX_STIMULUS_DIMENSION = 128
MAX_KERNEL_TAPS = 32


class PathGroundRefused(ValueError):
    """The claimed communication-path Ground lacks the specified evidence."""


def _bytes(value: Any) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (ValueError, TypeError) as exc:
        raise PathGroundRefused("noncanonical / nonfinite path evidence") from exc


def _hash(value: Any) -> str:
    return sha256(_bytes(value)).hexdigest()


def _hex(value: Any, what: str) -> str:
    if type(value) is not str or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise PathGroundRefused(f"{what} must be lowercase SHA-256")
    return value


def _int(value: Any, what: str, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise PathGroundRefused(f"{what} requires an integer >= {minimum}")
    return value


def _samples(value: Sequence[Any], what: str) -> tuple[float, ...]:
    if not isinstance(value, (list, tuple)) or not 1 <= len(value) <= MAX_STIMULUS_DIMENSION:
        raise PathGroundRefused(f"{what} has invalid bounded dimension")
    r: list[float] = []
    for v in value:
        if type(v) not in (int, float):
            raise PathGroundRefused(f"{what} contains invalid sample type")
        try:
            numeric = float(v)
        except (OverflowError, ValueError) as exc:
            raise PathGroundRefused(f"{what} contains unrepresentable sample") from exc
        if not math.isfinite(numeric) or abs(numeric) > 1e6:
            raise PathGroundRefused(f"{what} contains invalid finite sample")
        r.append(numeric)
    return tuple(r)


@dataclass(frozen=True)
class TcpPathObservation:
    """One real OS TCP loopback exchange; NOT evidence of optical processing."""

    channel: ChannelObservation
    logical_observed_at: int
    input_sha256: str
    output_sha256: str
    byte_count: int
    send_calls: int
    recv_calls: int
    elapsed_ns: int
    service: str = "os_tcp_loopback_byte_stream"
    clock_domain: str = "one_process_monotonic_ns"
    scope: str = "local_kernel_stack_including_endpoint_scheduling"

    def __post_init__(self) -> None:
        if not isinstance(self.channel, ChannelObservation):
            raise PathGroundRefused("TCP observation requires a native ChannelObservation")
        _hex(self.input_sha256, "input digest")
        _hex(self.output_sha256, "output digest")
        _int(self.logical_observed_at, "observation coordinate")
        _int(self.byte_count, "payload bytes", 1)
        _int(self.send_calls, "write operations", 1)
        _int(self.recv_calls, "receive operations", 1)
        _int(self.elapsed_ns, "measured elapsed ns", 1)
        if self.byte_count > MAX_PAYLOAD_BYTES or self.byte_count > self.channel.max_payload_bytes:
            raise PathGroundRefused("payload outside channel bound")
        if not self.channel.observed_at <= self.logical_observed_at <= self.channel.expires_at:
            raise PathGroundRefused("channel lease does not include observation")
        if "bytes" not in self.channel.carries:
            raise PathGroundRefused("channel has no byte-stream representation")
        if (self.service, self.clock_domain, self.scope) != (
            "os_tcp_loopback_byte_stream", "one_process_monotonic_ns",
            "local_kernel_stack_including_endpoint_scheduling"
        ):
            raise PathGroundRefused("unsupported or misleading path measurement scope")

    def to_dict(self) -> dict[str, Any]:
        return {"schema": SCHEMA + ".tcp", "channel": self.channel.to_dict(),
                "logical_observed_at": self.logical_observed_at,
                "input_sha256": self.input_sha256, "output_sha256": self.output_sha256,
                "byte_count": self.byte_count, "send_calls": self.send_calls,
                "recv_calls": self.recv_calls, "elapsed_ns": self.elapsed_ns,
                "service": self.service, "clock_domain": self.clock_domain,
                "scope": self.scope, "payload_equal": self.input_sha256 == self.output_sha256,
                "observation_digest": self.digest}

    @property
    def digest(self) -> str:
        return _hash({"channel": self.channel.to_dict(), "at": self.logical_observed_at,
                      "input": self.input_sha256, "output": self.output_sha256,
                      "size": self.byte_count, "send_calls": self.send_calls,
                      "recv_calls": self.recv_calls, "elapsed_ns": self.elapsed_ns,
                      "service": self.service, "clock": self.clock_domain,
                      "scope": self.scope})


def verify_tcp_path(observation: TcpPathObservation, *, sent: bytes, received: bytes,
                    channel: ChannelObservation, logical_observed_at: int) -> bool:
    """Check actual endpoint bytes against a receiver-selected channel snapshot."""
    try:
        return (type(sent) is bytes and type(received) is bytes
                and isinstance(observation, TcpPathObservation)
                and observation.channel == channel
                and observation.logical_observed_at == logical_observed_at
                and observation.byte_count == len(sent) == len(received)
                and observation.input_sha256 == sha256(sent).hexdigest()
                and observation.output_sha256 == sha256(received).hexdigest()
                and sent == received)
    except (TypeError, ValueError):
        return False


def probe_tcp_loopback(chunks: Sequence[bytes], *, channel: ChannelObservation,
                       logical_observed_at: int, timeout_seconds: float = 5.0,
                       ) -> tuple[TcpPathObservation, bytes]:
    """Send bounded chunks over a real local TCP stack, receiving one byte stream.

    The receiver writes into a preallocated bytearray. Sender-side chunk
    boundaries are NOT promised to survive TCP. Elapsed time includes Python,
    kernel, scheduling and all endpoint costs; it is not fiber flight-time.
    """
    if not isinstance(channel, ChannelObservation):
        raise PathGroundRefused("native observed channel required")
    if not isinstance(chunks, (list, tuple)) or not (2 <= len(chunks) <= 64):
        raise PathGroundRefused("require 2..64 explicitly bounded sender writes")
    if any(type(c) is not bytes or not c for c in chunks):
        raise PathGroundRefused("all sender writes must contain nonempty exact bytes")
    size = sum(len(c) for c in chunks)
    if size > min(MAX_PAYLOAD_BYTES, channel.max_payload_bytes):
        raise PathGroundRefused("channel payload bound exceeded before sending")
    if channel.source == channel.target or "bytes" not in channel.carries:
        raise PathGroundRefused("expected directed byte channel")
    if not channel.observed_at <= logical_observed_at <= channel.expires_at:
        raise PathGroundRefused("channel observation expired")
    if type(timeout_seconds) not in (int, float) or not 0 < timeout_seconds <= 20:
        raise PathGroundRefused("invalid local experiment deadline")
    expected = b"".join(chunks)
    buffer = bytearray(size)
    error: list[BaseException] = []
    stats = {"reads": 0, "received": 0}

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        listener.settimeout(timeout_seconds)
        with socket.create_connection(listener.getsockname(), timeout=timeout_seconds) as client:
            with listener.accept()[0] as receiver:
                receiver.settimeout(timeout_seconds)
                client.settimeout(timeout_seconds)

                def read_worker() -> None:
                    try:
                        view = memoryview(buffer)
                        while stats["received"] < size:
                            got = receiver.recv_into(view[stats["received"]:])
                            if got == 0:
                                raise PathGroundRefused("premature TCP stream end")
                            stats["reads"] += 1
                            stats["received"] += got
                    except BaseException as exc:  # surfaces thread failure to main thread
                        error.append(exc)

                worker = threading.Thread(target=read_worker, name="path-ground-tcp-reader", daemon=True)
                worker.start()
                start = time.monotonic_ns()
                try:
                    for chunk in chunks:
                        client.sendall(chunk)
                    client.shutdown(socket.SHUT_WR)
                    worker.join(timeout=timeout_seconds)
                except (OSError, TimeoutError) as exc:
                    raise PathGroundRefused(f"TCP loopback refused: {type(exc).__name__}") from exc
                end = time.monotonic_ns()
                if worker.is_alive():
                    raise PathGroundRefused("TCP loopback receiver timeout")
    if error:
        raise PathGroundRefused(f"TCP receiver refused: {type(error[0]).__name__}") from error[0]
    received = bytes(buffer)
    record = TcpPathObservation(channel=channel, logical_observed_at=logical_observed_at,
                                input_sha256=sha256(expected).hexdigest(),
                                output_sha256=sha256(received).hexdigest(),
                                byte_count=size, send_calls=len(chunks),
                                recv_calls=stats["reads"], elapsed_ns=end-start)
    return record, received


@dataclass(frozen=True)
class TransferObservation:
    """One bounded input/output transfer witness; mechanism is always explicit."""

    stimulus: tuple[float, ...]
    response: tuple[float, ...]
    mechanism: str
    environment_digest: str
    observation_id: str

    def __post_init__(self) -> None:
        x = _samples(self.stimulus, "stimulus")
        y = _samples(self.response, "response")
        if len(x) != len(y):
            raise PathGroundRefused("sample frames differ")
        if type(self.mechanism) is not str or self.mechanism not in {
            "software_fir_reference", "instrument_observation"
        }:
            raise PathGroundRefused("the path mechanism must identify software or instrument")
        _hex(self.environment_digest, "environment digest")
        if (type(self.observation_id) is not str or not self.observation_id
                or len(self.observation_id) > 128):
            raise PathGroundRefused("invalid observation ID")
        object.__setattr__(self, "stimulus", x)
        object.__setattr__(self, "response", y)

    def to_dict(self) -> dict[str, Any]:
        return {"stimulus": list(self.stimulus), "response": list(self.response),
                "mechanism": self.mechanism, "environment_digest": self.environment_digest,
                "observation_id": self.observation_id}


def fir_response(stimulus: Sequence[float], kernel: Sequence[float]) -> tuple[float, ...]:
    """Digital reference implementation ONLY; never a physical-path implementation."""
    x = _samples(stimulus, "stimulus")
    k = _samples(kernel, "FIR kernel")
    if len(k) > MAX_KERNEL_TAPS:
        raise PathGroundRefused("too many kernel taps")
    return tuple(sum(k[j] * x[i-j] for j in range(min(i+1,len(k)))) for i in range(len(x)))


@dataclass(frozen=True)
class TransferGroundCandidate:
    """Evidence-scoped LTI hypothesis inferred from actual supplied probe data."""

    kernel: tuple[float, ...]
    observed_dimension: int
    mechanism: str
    environment_digest: str
    evidence_digest: str
    tolerance: float
    worst_holdout_abs_error: float
    observation_count: int
    scope: str = "empirically_checked_probes_not_universal_law"

    def __post_init__(self) -> None:
        k = _samples(self.kernel, "kernel")
        if len(k) > MAX_KERNEL_TAPS:
            raise PathGroundRefused("kernel size exceeds bound")
        _int(self.observed_dimension, "dimension", 2)
        _int(self.observation_count, "observation count", 4)
        _hex(self.environment_digest, "environment digest")
        _hex(self.evidence_digest, "evidence digest")
        if self.mechanism not in ("software_fir_reference", "instrument_observation"):
            raise PathGroundRefused("invalid mechanism")
        for name in ("tolerance", "worst_holdout_abs_error"):
            val = getattr(self, name)
            if type(val) not in (int,float) or not math.isfinite(val) or val < 0:
                raise PathGroundRefused(f"invalid {name}")
        if self.worst_holdout_abs_error > self.tolerance:
            raise PathGroundRefused("holdout error exceeds declared tolerance")
        if self.scope != "empirically_checked_probes_not_universal_law":
            raise PathGroundRefused("transfer observation cannot claim universal proof")
        object.__setattr__(self, "kernel", k)

    def to_dict(self) -> dict[str, Any]:
        return {"schema": SCHEMA + ".transfer-ground", "kernel": list(self.kernel),
                "observed_dimension": self.observed_dimension, "mechanism": self.mechanism,
                "environment_digest": self.environment_digest,
                "evidence_digest": self.evidence_digest, "tolerance": self.tolerance,
                "worst_holdout_abs_error": self.worst_holdout_abs_error,
                "observation_count": self.observation_count, "scope": self.scope,
                "candidate_digest": self.digest}

    @property
    def digest(self) -> str:
        return _hash({"kernel": self.kernel, "observed_dimension": self.observed_dimension,
                      "mechanism": self.mechanism, "environment_digest": self.environment_digest,
                      "evidence_digest": self.evidence_digest,
                      "tolerance": self.tolerance, "worst_holdout_abs_error": self.worst_holdout_abs_error,
                      "observation_count": self.observation_count, "scope": self.scope})


def characterize_transfer(impulse: TransferObservation, shifted: TransferObservation,
                          holdouts: Sequence[TransferObservation], *,
                          taps: int, tolerance: float) -> TransferGroundCandidate:
    """Learn an FIR candidate from a full impulse, shift-check, and heldouts.

    A calibrated physical device may supply input/output measurements, but a
    measured finite dataset never proves the model outside these conditions.
    """
    if not isinstance(impulse, TransferObservation) or not isinstance(shifted, TransferObservation):
        raise PathGroundRefused("typed transfer calibration observations are required")
    n = len(impulse.stimulus)
    if not isinstance(holdouts, (list,tuple)) or len(holdouts)<2 or len(holdouts)>32:
        raise PathGroundRefused("two or more independently supplied held-out probes are required")
    _int(taps, "kernel taps", 1)
    if taps > min(n, MAX_KERNEL_TAPS):
        raise PathGroundRefused("kernel span invalid")
    if type(tolerance) not in (float,int) or not math.isfinite(tolerance) or not 0<=tolerance<=0.1:
        raise PathGroundRefused("invalid physical measurement tolerance")
    all_obs = (impulse, shifted, *holdouts)
    if any(not isinstance(o, TransferObservation) or len(o.stimulus)!=n for o in all_obs):
        raise PathGroundRefused("mixed or malformed transfer frames")
    if len({o.observation_id for o in all_obs}) != len(all_obs):
        raise PathGroundRefused("duplicate calibration receipt identity")
    if any(o.environment_digest != impulse.environment_digest or o.mechanism != impulse.mechanism
           for o in all_obs):
        raise PathGroundRefused("incompatible measurement environment or mechanism")
    if impulse.stimulus != (1.0,)+(0.0,)*(n-1):
        raise PathGroundRefused("first calibration probe is not an exact unit impulse")
    if shifted.stimulus != (0.0,1.0)+(0.0,)*(n-2):
        raise PathGroundRefused("second calibration probe is not an exact shifted impulse")
    kernel = impulse.response[:taps]
    if any(abs(x)>tolerance for x in impulse.response[taps:]):
        raise PathGroundRefused("impulse response outside declared finite kernel")
    errors=[]
    for obs in (shifted,*holdouts):
        predicted=fir_response(obs.stimulus,kernel)
        err=max(abs(p-q) for p,q in zip(predicted,obs.response))
        errors.append(err)
        if err>tolerance:
            raise PathGroundRefused("held-out or shifted observation contradicts FIR candidate")
    digest=_hash([o.to_dict() for o in all_obs])
    return TransferGroundCandidate(kernel,n,impulse.mechanism,impulse.environment_digest,
                                   digest,float(tolerance),max(errors),len(all_obs))


def verify_transfer_candidate(candidate: TransferGroundCandidate, impulse: TransferObservation,
                              shifted: TransferObservation, holdouts: Sequence[TransferObservation],
                              *, taps: int, tolerance: float) -> bool:
    """Rebuild from original probe values; a certificate cannot verify itself."""
    try:
        return candidate == characterize_transfer(impulse, shifted, holdouts,
                                                    taps=taps,tolerance=tolerance)
    except (PathGroundRefused, TypeError, ValueError):
        return False


def bind_tcp_carrier_witness(observation: TcpPathObservation, *, sent: bytes,
                             received: bytes, ground: Any,
                             context_digest: str, receiver_policy_digest: str) -> Any:
    """Adapt live TCP evidence into E-CPU's EXISTING VerifiedObserverPath.

    This deliberately produces a CARRIER stage, not a fabricated optical or
    computational TRANSFORM stage. Receiver-owned callback checks the bytes.
    The Ground is a caller-supplied *interpretation* of the carried content;
    its digest is not execution authority or proof of physical behavior.
    """
    from .semantic_translation import RepresentationRef
    from .observer_path_evidence import (
        ObserverPathStage, verify_observer_path, check_observer_path_receipt,
    )
    if not isinstance(ground, RepresentationRef):
        raise PathGroundRefused("native mathematical Ground identity required")
    _hex(context_digest, "context digest")
    _hex(receiver_policy_digest, "receiver policy digest")
    if not verify_tcp_path(observation, sent=sent, received=received,
                           channel=observation.channel,
                           logical_observed_at=observation.logical_observed_at):
        raise PathGroundRefused("TCP endpoint evidence did not verify")
    # Use the exact bytes in a content-addressed *representation*, not the
    # identity of the Python object holding them.
    byte_ref=RepresentationRef.from_payload('bytes',1,
                                            {"encoding":"hex","payload":sent.hex()})
    stage=ObserverPathStage(
        'carrier', observation.channel.source, observation.channel.target,
        byte_ref, byte_ref, channel=observation.channel, payload_bytes=len(sent),
    )
    def locally_verified_carrier(item: Any) -> bool:
        return (item is stage and verify_tcp_path(observation,sent=sent,received=received,
                                                  channel=observation.channel,
                                                  logical_observed_at=observation.logical_observed_at))
    def no_self_authorizing_observer(_: Any) -> bool:
        return False
    witness=verify_observer_path(
        (stage,), ground=ground, context_digest=context_digest,
        receiver_policy_digest=receiver_policy_digest,
        observed_at=observation.logical_observed_at,
        verify_carrier=locally_verified_carrier,
        verify_observer=no_self_authorizing_observer,
    )
    if not check_observer_path_receipt(witness,(stage,),
                                      verify_carrier=locally_verified_carrier,
                                      verify_observer=no_self_authorizing_observer):
        raise PathGroundRefused("native independent carrier witness reconstruction failed")
    return witness

@dataclass(frozen=True)
class TemporalGroundCandidate:
    """Finite, conditional endpoint-duration envelope; not pure path flight time."""

    nominal_elapsed_ns: int
    tolerance_ns: int
    worst_deviation_ns: int
    samples_checked: int
    channel_digest: str
    evidence_digest: str
    scope: str = "empirical_same_clock_endpoint_duration_only"

    def __post_init__(self) -> None:
        _int(self.nominal_elapsed_ns, "nominal endpoint duration", 1)
        _int(self.tolerance_ns, "duration tolerance")
        _int(self.worst_deviation_ns, "worst deviation")
        _int(self.samples_checked, "sample count", 6)
        _hex(self.channel_digest, "channel digest")
        _hex(self.evidence_digest, "evidence digest")
        if self.worst_deviation_ns > self.tolerance_ns:
            raise PathGroundRefused("observed duration exceeds the declared envelope")
        if self.scope != "empirical_same_clock_endpoint_duration_only":
            raise PathGroundRefused("time observation cannot assert pure propagation time")

    def to_dict(self) -> dict[str, Any]:
        return {"schema": SCHEMA + ".temporal", "nominal_elapsed_ns": self.nominal_elapsed_ns,
                "tolerance_ns": self.tolerance_ns, "worst_deviation_ns": self.worst_deviation_ns,
                "samples_checked": self.samples_checked, "channel_digest": self.channel_digest,
                "evidence_digest": self.evidence_digest, "scope": self.scope}


def characterize_temporal_span(calibration: Sequence[TcpPathObservation],
                               holdouts: Sequence[TcpPathObservation], *,
                               nominal_elapsed_ns: int, tolerance_ns: int) -> TemporalGroundCandidate:
    """Refuse a purported stable endpoint span unless all heldouts agree.

    Nominal and tolerance must be supplied by the receiving policy, not
    invented after looking at heldouts. This cannot certify a flight-time law.
    """
    if not isinstance(calibration, (list, tuple)) or not isinstance(holdouts, (list, tuple)):
        raise PathGroundRefused("timing evidence must be a bounded record sequence")
    if not 4 <= len(calibration) <= 64 or not 2 <= len(holdouts) <= 64:
        raise PathGroundRefused("need >=4 calibration and >=2 held-out timing observations")
    _int(nominal_elapsed_ns, "nominal endpoint duration", 1)
    _int(tolerance_ns, "allowed absolute timing error")
    all_samples = (*calibration, *holdouts)
    if any(not isinstance(s, TcpPathObservation) for s in all_samples):
        raise PathGroundRefused("invalid native TCP timing observation")
    first = all_samples[0]
    if any(s.channel != first.channel or s.input_sha256 != first.input_sha256
           or s.output_sha256 != s.input_sha256 or s.byte_count != first.byte_count
           for s in all_samples):
        raise PathGroundRefused("timing samples must share one exact channel and byte-frame")
    if len({s.logical_observed_at for s in all_samples}) != len(all_samples):
        raise PathGroundRefused("timing samples reuse an observation coordinate")
    # Prevent calling an arbitrary, uncalibrated duration a physical law.
    error = max(abs(s.elapsed_ns - nominal_elapsed_ns) for s in all_samples)
    if error > tolerance_ns:
        raise PathGroundRefused("held-out or calibration timing rejects declared duration envelope")
    return TemporalGroundCandidate(nominal_elapsed_ns,tolerance_ns,error,len(all_samples),
                                   _hash(first.channel.to_dict()),
                                   _hash([s.to_dict() for s in all_samples]))


def verify_temporal_candidate(candidate: TemporalGroundCandidate,
                              calibration: Sequence[TcpPathObservation],
                              holdouts: Sequence[TcpPathObservation], *,
                              nominal_elapsed_ns: int, tolerance_ns: int) -> bool:
    """Recompute every timing-evidence binding, including the held-out traces."""
    try:
        return (isinstance(candidate, TemporalGroundCandidate)
                and candidate == characterize_temporal_span(
                    calibration, holdouts, nominal_elapsed_ns=nominal_elapsed_ns,
                    tolerance_ns=tolerance_ns))
    except (PathGroundRefused, ValueError, TypeError):
        return False