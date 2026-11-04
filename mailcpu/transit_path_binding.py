"""Live observational binding between a transit session and its three-mode path state."""

from __future__ import annotations

import hashlib
import json
import time
from collections import defaultdict, deque
from dataclasses import asdict, dataclass
from typing import Any, Callable, Mapping

from .classifier import HypervisorArbitrationEvent, HypervisorExecutionResult
from .hypervisor_transport import (
    HypervisorOperationChannel,
    HypervisorOperationResultChannel,
)
from .transit_path_modes import TransitPathState, TransitPathStateError
from .transit_session import TransitComputeSession


_FORMAT = "mailcpu-transit-path-binding-v1"


class TransitPathBindingError(ValueError):
    """A live path binding, telemetry correlation, or binding checkpoint is invalid."""


def _canonical(value: Any) -> bytes:
    """Mathematics: Encode finite JSON-compatible state with deterministic key and separator ordering."""
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise TransitPathBindingError(f"path binding state is not canonical JSON: {exc}") from exc


def _digest(value: Any) -> str:
    """Mathematics: Compute SHA-256 over the canonical JSON representation of a binding state."""
    return hashlib.sha256(_canonical(value)).hexdigest()


def _clock_value(clock_ns: Callable[[], int]) -> int:
    """Mathematics: Require one non-negative integer reading from the binding's local monotonic clock."""
    value = clock_ns()
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise TransitPathBindingError("clock_ns must return a non-negative integer")
    return value


def _session_contract(session: TransitComputeSession) -> dict[str, Any]:
    """Mathematics: Project the receiver's logical request/result channels without binding physical transport objects."""
    request = session.request.channel
    response = session.response.channel
    return {
        "request": {
            "source": request.source,
            "destination": request.destination,
            "peer": request.peer,
            "channel": request.channel,
        },
        "response": {
            "source": response.source,
            "destination": response.destination,
            "peer": response.peer,
            "channel": response.channel,
            "operation_source": session.response.operation_source,
            "operation_channel": session.response.operation_channel,
        },
    }


@dataclass(frozen=True)
class TransitPathQueueObservation:
    """A diagnostic snapshot of queue readiness and reliable-window occupancy at one observation boundary."""

    tick: int
    cause: str
    session_phase: str
    request_ready: bool
    response_client_ready: bool
    request_receive_cursor: int
    request_sender_available_window: int
    request_sender_pending: tuple[int, ...]
    response_sender_available_window: int
    response_sender_pending: tuple[int, ...]

    def to_dict(self) -> dict[str, Any]:
        """Mathematics: Project the immutable queue observation into a JSON-compatible record."""
        value = asdict(self)
        value["request_sender_pending"] = list(self.request_sender_pending)
        value["response_sender_pending"] = list(self.response_sender_pending)
        return value


@dataclass(frozen=True)
class TransitPathServiceSample:
    """Receiver-local elapsed service time for one semantic operation, distinct from end-to-end RTT."""

    tick: int
    operation_sequence: int
    service_us: int

    def to_dict(self) -> dict[str, int]:
        """Mathematics: Project service timing into a finite integer record."""
        return asdict(self)


class TransitPathSessionBinding:
    """Observe a live TransitComputeSession while preserving its execution and reliable-channel authorities.

    This reference binding holds both the receiver session and its paired
    requester-side channels. Its RTT uses a single local clock around request
    send and result receive. A later distributed adapter can split these
    endpoint hooks while preserving the same telemetry record contract.
    """

    def __init__(
        self,
        path_id: str,
        session: TransitComputeSession,
        request_sender: HypervisorOperationChannel,
        result_receiver: HypervisorOperationResultChannel,
        *,
        state: TransitPathState | None = None,
        clock_ns: Callable[[], int] = time.monotonic_ns,
        max_observations: int = 4096,
    ) -> None:
        """Mathematics: bind one stable path ID to its receiver session, opposite endpoint channels, and retained path state."""
        if not isinstance(session, TransitComputeSession):
            raise TransitPathBindingError("binding requires a TransitComputeSession")
        if not isinstance(request_sender, HypervisorOperationChannel):
            raise TransitPathBindingError("binding requires an origin-side HypervisorOperationChannel")
        if not isinstance(result_receiver, HypervisorOperationResultChannel):
            raise TransitPathBindingError("binding requires an origin-side HypervisorOperationResultChannel")
        if not callable(clock_ns):
            raise TransitPathBindingError("clock_ns must be callable")
        if (
            not isinstance(max_observations, int)
            or isinstance(max_observations, bool)
            or max_observations <= 0
        ):
            raise TransitPathBindingError("max_observations must be a positive integer")

        self.path_id = path_id
        self.session = session
        self.request_sender = request_sender
        self.result_receiver = result_receiver
        self.clock_ns = clock_ns
        self.max_observations = max_observations
        self.state = state or TransitPathState(path_id)
        if not isinstance(self.state, TransitPathState):
            raise TransitPathBindingError("state must be a TransitPathState")
        if self.state.path_id != path_id:
            raise TransitPathBindingError("path state identifier does not match binding path_id")

        self._validate_endpoint_pair()
        self._contract_digest = _digest(_session_contract(session))
        self._observation_tick = 0
        self._queue_observations: list[TransitPathQueueObservation] = []
        self._service_samples: list[TransitPathServiceSample] = []
        self._protocol_events: list[dict[str, Any]] = []
        self._dropped_observations = {"queue": 0, "service": 0, "protocol": 0}
        self._pending_started: dict[int, deque[tuple[int, int]]] = defaultdict(deque)
        self._request_frame_semantics: dict[int, int] = {}
        self._response_frame_semantics: dict[int, int] = {}
        self._last_clock_ns: int | None = None

    def _now(self) -> int:
        """Mathematics: Read the configured monotonic clock and reject a backwards movement within this binding lifetime."""
        value = _clock_value(self.clock_ns)
        if self._last_clock_ns is not None and value < self._last_clock_ns:
            raise TransitPathBindingError("configured monotonic clock moved backwards")
        self._last_clock_ns = value
        return value

    def _validate_endpoint_pair(self) -> None:
        """Mathematics: Require client-side channel identities to be the exact reverse endpoints of the receiver session."""
        receiver_request = self.session.request.channel
        receiver_response = self.session.response.channel
        client_request = self.request_sender.channel
        client_result = self.result_receiver.channel

        valid = (
            client_request.source == receiver_request.peer
            and client_request.destination == receiver_request.source
            and client_request.peer == receiver_request.source
            and client_request.channel == receiver_request.channel
            and client_result.source == receiver_request.peer
            and client_result.destination == receiver_response.destination
            and client_result.peer == receiver_request.source
            and client_result.channel == receiver_response.channel
            and self.result_receiver.operation_source == receiver_request.peer
            and self.result_receiver.operation_channel == receiver_request.channel
        )
        if not valid:
            raise TransitPathBindingError(
                "request sender and result receiver do not match the receiver session's logical path"
            )

    @property
    def queue_observations(self) -> tuple[TransitPathQueueObservation, ...]:
        """Mathematics: Expose the bounded immutable projection of observed queue and reliable-window states."""
        return tuple(self._queue_observations)

    @property
    def service_samples(self) -> tuple[TransitPathServiceSample, ...]:
        """Mathematics: Expose receiver-local service durations without conflating them with network round-trip time."""
        return tuple(self._service_samples)

    @property
    def protocol_events(self) -> tuple[dict[str, Any], ...]:
        """Mathematics: Expose copied ACK and retry evidence without granting it execution authority."""
        return tuple(dict(item) for item in self._protocol_events)

    def _check_capacity(self, collection: list[Any], label: str) -> None:
        """Mathematics: Keep telemetry bounded by evicting the oldest record, never by blocking a protocol transition."""
        if len(collection) >= self.max_observations:
            del collection[0]
            self._dropped_observations[label] += 1

    def _capture_queue(self, cause: str) -> TransitPathQueueObservation:
        """Mathematics: Observe readiness and sender windows as a diagnostic projection without consuming or acknowledging frames."""
        self._check_capacity(self._queue_observations, "queue")
        request_receiver = self.session.request.channel
        response_sender = self.session.response.channel
        request_sender = self.request_sender.channel
        result_receiver = self.result_receiver.channel

        observation = TransitPathQueueObservation(
            tick=self._observation_tick + 1,
            cause=cause,
            session_phase=self.session.phase,
            request_ready=request_receiver.peek() is not None,
            response_client_ready=result_receiver.peek() is not None,
            request_receive_cursor=request_receiver.next_receive_sequence,
            request_sender_available_window=request_sender.available_window,
            request_sender_pending=request_sender.pending_sequences(),
            response_sender_available_window=response_sender.available_window,
            response_sender_pending=response_sender.pending_sequences(),
        )
        self._observation_tick += 1
        self._queue_observations.append(observation)
        return observation

    def _append_protocol_event(self, event: Mapping[str, Any]) -> None:
        """Mathematics: Append one finite protocol observation while respecting the shared telemetry capacity."""
        self._check_capacity(self._protocol_events, "protocol")
        payload = dict(event)
        payload["tick"] = self._observation_tick + 1
        _canonical(payload)
        self._observation_tick += 1
        self._protocol_events.append(payload)

    def _record_sensor_round_trip(self, sequence: int, started_ns: int, completed_ns: int) -> None:
        """Mathematics: Record RTT from two readings of the same requester-side monotonic clock, restoring the prior path role afterward."""
        previous_mode = self.state.mode
        if previous_mode != "sensor":
            self.state.set_mode("sensor")
        try:
            self.state.record_round_trip(sequence, started_ns, completed_ns)
        except TransitPathStateError as exc:
            self._append_protocol_event({
                "kind": "sensor-observation-rejected",
                "observation": "round-trip",
                "operation_sequence": sequence,
                "reason": str(exc),
            })
        finally:
            if previous_mode != "sensor":
                self.state.set_mode(previous_mode)

    def _record_sensor_timeout(self, sequence: int) -> None:
        """Mathematics: Record an explicit operation-level timeout as loss evidence, without inferring loss from an unacknowledged frame."""
        previous_mode = self.state.mode
        if previous_mode != "sensor":
            self.state.set_mode("sensor")
        try:
            self.state.mark_lost(sequence)
        except TransitPathStateError as exc:
            raise TransitPathBindingError(f"timeout observation rejected: {exc}") from exc
        finally:
            if previous_mode != "sensor":
                self.state.set_mode(previous_mode)

    def send_request(self, event: HypervisorArbitrationEvent) -> int:
        """Mathematics: Send one typed semantic operation, bind its reliable frame sequence to a local monotonic start, and observe queue state."""
        if not isinstance(event, HypervisorArbitrationEvent):
            raise TransitPathBindingError("send_request requires a HypervisorArbitrationEvent")
        started_ns = self._now()
        try:
            transport_sequence = self.request_sender.send(event)
        except Exception:
            self._capture_queue("request-send-rejected")
            raise
        self._pending_started[event.sequence].append((transport_sequence, started_ns))
        self._request_frame_semantics[transport_sequence] = event.sequence
        self._capture_queue("request-sent")
        return transport_sequence

    def serve_once(self) -> HypervisorExecutionResult | None:
        """Mathematics: Measure one receiver-local service transition while delegating all admission, execution, replay, and ACK rules to the session worker."""
        before = set(self.session.response.channel.pending_sequences())
        started_ns = self._now()
        result: HypervisorExecutionResult | None = None
        try:
            result = self.session.serve_once()
            return result
        finally:
            completed_ns = self._now()
            if completed_ns < started_ns:
                raise TransitPathBindingError("service clock completed before it started")
            if result is not None:
                self._check_capacity(self._service_samples, "service")
                service_us = (completed_ns - started_ns + 500) // 1000
                self._service_samples.append(
                    TransitPathServiceSample(
                        tick=self._observation_tick + 1,
                        operation_sequence=result.sequence,
                        service_us=service_us,
                    )
                )
                current = set(self.session.response.channel.pending_sequences())
                for response_sequence in sorted(current - before):
                    self._response_frame_semantics[response_sequence] = result.sequence
            self._capture_queue("service-completed" if result is not None else "service-idle")

    def receive_result(self) -> HypervisorExecutionResult | None:
        """Mathematics: Receive and ACK one typed result, then correlate its semantic sequence to the oldest pending requester-side send for RTT measurement."""
        result = self.result_receiver.receive()
        if result is None:
            self._capture_queue("result-not-ready")
            return None

        completed_ns = self._now()
        pending = self._pending_started.get(result.sequence)
        if pending:
            _request_transport_sequence, started_ns = pending.popleft()
            if not pending:
                del self._pending_started[result.sequence]
            self._record_sensor_round_trip(result.sequence, started_ns, completed_ns)
        else:
            self._append_protocol_event({
                "kind": "result-without-local-start",
                "operation_sequence": result.sequence,
                "replayed": bool(result.replayed),
            })
        self._capture_queue("result-received")
        return result

    def record_request_timeout(self, operation_sequence: int) -> None:
        """Mathematics: Admit an explicit caller-observed operation timeout as a sensor loss event, correlated by semantic operation sequence."""
        operation_sequence = self._positive_sequence(operation_sequence, "operation_sequence")
        self._record_sensor_timeout(operation_sequence)
        self._append_protocol_event({
            "kind": "operation-timeout",
            "operation_sequence": operation_sequence,
        })
        self._capture_queue("operation-timeout")

    @staticmethod
    def _positive_sequence(value: Any, label: str) -> int:
        """Mathematics: Validate one positive integer semantic or transport sequence while excluding Boolean values."""
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise TransitPathBindingError(f"{label} must be a positive integer")
        return value

    def process_acknowledgements(self) -> dict[str, tuple[int, ...]]:
        """Mathematics: Drain requester ACKs and receiver response ACKs, retaining semantic correlations while leaving both reliable ledgers authoritative."""
        request_acks = self.request_sender.channel.process_ack()
        response_acks = self.session.response.channel.process_ack()
        request_operations = tuple(
            self._request_frame_semantics.pop(sequence)
            for sequence in request_acks
            if sequence in self._request_frame_semantics
        )
        response_operations = tuple(
            self._response_frame_semantics.pop(sequence)
            for sequence in response_acks
            if sequence in self._response_frame_semantics
        )
        self._append_protocol_event({
            "kind": "acknowledgements",
            "request_transport_sequences": list(request_acks),
            "request_operations": list(request_operations),
            "response_transport_sequences": list(response_acks),
            "response_operations": list(response_operations),
        })
        self._capture_queue("acknowledgements-processed")
        return {
            "request_transport_sequences": request_acks,
            "request_operations": request_operations,
            "response_transport_sequences": response_acks,
            "response_operations": response_operations,
        }

    def tick_reliability(self) -> dict[str, tuple[int, ...]]:
        """Mathematics: Advance both endpoint retry clocks once and report exhausted transport sequences without equating ACK failure with semantic operation loss."""
        request_failed = self.request_sender.channel.tick()
        response_failed = self.session.response.channel.tick()
        request_operations = tuple(
            self._request_frame_semantics.get(sequence)
            for sequence in request_failed
            if sequence in self._request_frame_semantics
        )
        response_operations = tuple(
            self._response_frame_semantics.get(sequence)
            for sequence in response_failed
            if sequence in self._response_frame_semantics
        )
        self._append_protocol_event({
            "kind": "retry-exhaustion",
            "request_transport_sequences": list(request_failed),
            "request_operations": list(request_operations),
            "response_transport_sequences": list(response_failed),
            "response_operations": list(response_operations),
        })
        self._capture_queue("retry-clock-advanced")
        return {
            "request_transport_sequences": request_failed,
            "request_operations": request_operations,
            "response_transport_sequences": response_failed,
            "response_operations": response_operations,
        }

    def state(self) -> dict[str, Any]:
        """Mathematics: Record one fresh queue observation and expose the combined path-state and telemetry projection."""
        queue = self._capture_queue("state-observed")
        return {
            "path_id": self.path_id,
            "mode": self.state.mode,
            "path_logical_tick": self.state.logical_tick,
            "observation_tick": self._observation_tick,
            "session_phase": self.session.phase,
            "queue": queue.to_dict(),
            "service_sample_count": len(self._service_samples),
            "protocol_event_count": len(self._protocol_events),
            "pending_round_trip_sequences": sorted(self._pending_started),
        }

    def snapshot(self) -> dict[str, Any]:
        """Mathematics: Checkpoint telemetry only at a quiescent boundary and bind it to the current session and requester-channel digests."""
        if self._pending_started:
            raise TransitPathBindingError("cannot checkpoint with an unmeasured operation round trip")
        if self._request_frame_semantics or self._response_frame_semantics:
            raise TransitPathBindingError("cannot checkpoint with unresolved ACK correlations")
        if self.session.phase != "idle":
            raise TransitPathBindingError("cannot checkpoint while the receiver session is not idle")
        if self.session.request.channel.peek() is not None or self.result_receiver.channel.peek() is not None:
            raise TransitPathBindingError("cannot checkpoint while a request or result frame is queued")
        if self.request_sender.channel.pending_sequences():
            raise TransitPathBindingError("cannot checkpoint with requester-side request frames awaiting ACK")
        if self.session.response.channel.pending_sequences():
            raise TransitPathBindingError("cannot checkpoint with receiver-side response frames awaiting ACK")

        session_snapshot = self.session.snapshot()
        client_request_snapshot = self.request_sender.channel.snapshot()
        client_result_snapshot = self.result_receiver.snapshot()
        state = {
            "version": 1,
            "path_id": self.path_id,
            "contract_digest": self._contract_digest,
            "session_checkpoint_digest": session_snapshot.get("digest"),
            "client_request_digest": _digest(client_request_snapshot),
            "client_result_digest": _digest(client_result_snapshot),
            "path_state": self.state.snapshot(),
            "observation_tick": self._observation_tick,
            "queue_observations": [item.to_dict() for item in self._queue_observations],
            "service_samples": [item.to_dict() for item in self._service_samples],
            "protocol_events": list(self._protocol_events),
            "dropped_observations": dict(self._dropped_observations),
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
        session: TransitComputeSession,
        request_sender: HypervisorOperationChannel,
        result_receiver: HypervisorOperationResultChannel,
        *,
        clock_ns: Callable[[], int] = time.monotonic_ns,
        max_observations: int = 4096,
    ) -> "TransitPathSessionBinding":
        """Mathematics: Restore telemetry only when the canonical digest, logical path, session checkpoint, and both client-channel states match exactly."""
        if not isinstance(payload, Mapping) or set(payload) != {"format", "digest", "state"}:
            raise TransitPathBindingError("path binding checkpoint envelope is invalid")
        if payload.get("format") != _FORMAT:
            raise TransitPathBindingError("unsupported path binding checkpoint format")
        raw_state = payload.get("state")
        if not isinstance(raw_state, Mapping) or _digest(raw_state) != payload.get("digest"):
            raise TransitPathBindingError("path binding checkpoint digest mismatch")
        expected_fields = {
            "version", "path_id", "contract_digest", "session_checkpoint_digest",
            "client_request_digest", "client_result_digest", "path_state",
            "observation_tick", "queue_observations", "service_samples", "protocol_events",
            "dropped_observations",
        }
        if set(raw_state) != expected_fields or raw_state.get("version") != 1:
            raise TransitPathBindingError("path binding checkpoint state fields are invalid")

        path_state = TransitPathState.from_snapshot(raw_state["path_state"])
        binding = cls(
            raw_state["path_id"],
            session,
            request_sender,
            result_receiver,
            state=path_state,
            clock_ns=clock_ns,
            max_observations=max_observations,
        )
        session_snapshot = session.snapshot()
        if binding._contract_digest != raw_state["contract_digest"]:
            raise TransitPathBindingError("restored session changes the logical path contract")
        if session_snapshot.get("digest") != raw_state["session_checkpoint_digest"]:
            raise TransitPathBindingError("restored session checkpoint does not match binding checkpoint")
        if _digest(request_sender.channel.snapshot()) != raw_state["client_request_digest"]:
            raise TransitPathBindingError("restored requester channel does not match binding checkpoint")
        if _digest(result_receiver.snapshot()) != raw_state["client_result_digest"]:
            raise TransitPathBindingError("restored result channel does not match binding checkpoint")

        observation_tick = raw_state["observation_tick"]
        if not isinstance(observation_tick, int) or isinstance(observation_tick, bool) or observation_tick < 0:
            raise TransitPathBindingError("binding observation_tick must be a non-negative integer")
        binding._observation_tick = observation_tick
        raw_dropped = raw_state["dropped_observations"]
        if not isinstance(raw_dropped, Mapping) or set(raw_dropped) != {"queue", "service", "protocol"}:
            raise TransitPathBindingError("dropped observation counters are invalid")
        for label, value in raw_dropped.items():
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise TransitPathBindingError("dropped observation counters must be non-negative integers")
            binding._dropped_observations[label] = value

        queue_items = raw_state["queue_observations"]
        service_items = raw_state["service_samples"]
        protocol_items = raw_state["protocol_events"]
        if (
            not isinstance(queue_items, list)
            or not isinstance(service_items, list)
            or not isinstance(protocol_items, list)
            or max(len(queue_items), len(service_items), len(protocol_items)) > max_observations
        ):
            raise TransitPathBindingError("binding telemetry collections are invalid or exceed capacity")

        try:
            for item in queue_items:
                if not isinstance(item, Mapping) or set(item) != {
                    "tick", "cause", "session_phase", "request_ready", "response_client_ready",
                    "request_receive_cursor", "request_sender_available_window",
                    "request_sender_pending", "response_sender_available_window",
                    "response_sender_pending",
                }:
                    raise TransitPathBindingError("queue observation fields are invalid")
                if not isinstance(item["cause"], str) or not isinstance(item["session_phase"], str):
                    raise TransitPathBindingError("queue observation labels are invalid")
                for flag in ("request_ready", "response_client_ready"):
                    if not isinstance(item[flag], bool):
                        raise TransitPathBindingError("queue observation flags must be Boolean")
                for number in ("tick", "request_receive_cursor"):
                    cls._positive_sequence(item[number], number)
                for number in ("request_sender_available_window", "response_sender_available_window"):
                    value = item[number]
                    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                        raise TransitPathBindingError(f"{number} must be a non-negative integer")
                for numbers in ("request_sender_pending", "response_sender_pending"):
                    if not isinstance(item[numbers], list):
                        raise TransitPathBindingError("queue pending sequences must be lists")
                    for value in item[numbers]:
                        cls._positive_sequence(value, "pending sequence")
                binding._queue_observations.append(TransitPathQueueObservation(
                    item["tick"], item["cause"], item["session_phase"],
                    item["request_ready"], item["response_client_ready"],
                    item["request_receive_cursor"], item["request_sender_available_window"],
                    tuple(item["request_sender_pending"]), item["response_sender_available_window"],
                    tuple(item["response_sender_pending"]),
                ))

            previous_service_tick = 0
            for item in service_items:
                if not isinstance(item, Mapping) or set(item) != {"tick", "operation_sequence", "service_us"}:
                    raise TransitPathBindingError("service sample fields are invalid")
                tick = cls._positive_sequence(item["tick"], "service tick")
                operation_sequence = cls._positive_sequence(item["operation_sequence"], "operation_sequence")
                service_us = item["service_us"]
                if not isinstance(service_us, int) or isinstance(service_us, bool) or service_us < 0 or tick <= previous_service_tick:
                    raise TransitPathBindingError("service sample timing or order is invalid")
                binding._service_samples.append(TransitPathServiceSample(tick, operation_sequence, service_us))
                previous_service_tick = tick

            previous_protocol_tick = 0
            for item in protocol_items:
                if not isinstance(item, Mapping) or "tick" not in item or "kind" not in item:
                    raise TransitPathBindingError("protocol event fields are invalid")
                tick = cls._positive_sequence(item["tick"], "protocol event tick")
                if tick <= previous_protocol_tick or not isinstance(item["kind"], str):
                    raise TransitPathBindingError("protocol event order or kind is invalid")
                _canonical(item)
                binding._protocol_events.append(dict(item))
                previous_protocol_tick = tick
        except (TypeError, KeyError) as exc:
            raise TransitPathBindingError(f"binding checkpoint telemetry is malformed: {exc}") from exc

        if max(
            len(binding._queue_observations),
            len(binding._service_samples),
            len(binding._protocol_events),
        ) > binding.max_observations:
            raise TransitPathBindingError("restored telemetry exceeds configured capacity")
        return binding
