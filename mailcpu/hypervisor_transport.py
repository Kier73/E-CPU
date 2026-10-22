"""Reliable transport adapter for checkpointable hypervisor operation events."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Callable

from .classifier import (
    ClassifierError,
    HypervisorArbitrationEvent,
    HypervisorArbitrationLoop,
    HypervisorExecutionResult,
    HypervisorDomain,
)
from .reliability import ReliableChannel


OPERATION_EVENT_KIND = "mailcpu.hypervisor.operation"
OPERATION_RESULT_KIND = "mailcpu.hypervisor.operation.result"


class HypervisorOperationTransportError(ValueError):
    """A hypervisor operation event is malformed, misbound, or unsafe to acknowledge."""


class HypervisorOperationChannel:
    """Carry peer-bound hypervisor operation events through one reliable channel."""

    def __init__(self, channel: ReliableChannel) -> None:
        """Mathematics: bind operation stream `S` to `(source,peer,channel)` without introducing a second delivery identity."""

        if not isinstance(channel, ReliableChannel):
            raise HypervisorOperationTransportError("operation transport requires a ReliableChannel")
        self.channel = channel

    def send(self, event: HypervisorArbitrationEvent) -> int:
        """Mathematics: encode `e` as reliable payload `RDATA(kind_operation,e)` and return its transport sequence."""

        if not isinstance(event, HypervisorArbitrationEvent):
            raise HypervisorOperationTransportError("operation transport requires a HypervisorArbitrationEvent")
        if event.source != self.channel.source or event.channel != self.channel.channel:
            raise HypervisorOperationTransportError("operation identity does not match reliable channel source or channel")
        return self.channel.send({"kind": OPERATION_EVENT_KIND, "event": event.to_dict()})

    def receive(self) -> HypervisorArbitrationEvent | None:
        """Mathematics: decode and peer-bind `e` while peeked, then consume and acknowledge only after typed reconstruction."""

        peeked = self.channel.peek()
        if peeked is None:
            return None
        transport_sequence, payload = peeked
        event = self._decode_payload(payload)
        received = self.channel.receive()
        if received is not None and received[0] != transport_sequence:
            raise HypervisorOperationTransportError("operation receive sequence changed during validation")
        return event if received is not None else None

    def receive_and_execute(
        self,
        arbitration: HypervisorArbitrationLoop,
        authorize: Callable[[HypervisorArbitrationEvent], HypervisorArbitrationEvent],
        handlers: Mapping[HypervisorDomain | str, Callable[[], Any]],
        effect_encoder: Callable[[Any], Any] | None = None,
    ) -> HypervisorExecutionResult | None:
        """Mathematics: compute `E[authorize(e)]` before `ACK`, with local authority reconstruction and duplicate-safe consumption."""

        prepared = self._prepare_execution(arbitration, authorize)
        if prepared is None:
            return None
        transport_sequence, authorized = prepared
        result = arbitration.execute(authorized, handlers, effect_encoder)
        self._consume_after_execution(transport_sequence)
        return result

    def receive_and_reply(
        self,
        arbitration: HypervisorArbitrationLoop,
        authorize: Callable[[HypervisorArbitrationEvent], HypervisorArbitrationEvent],
        handlers: Mapping[HypervisorDomain | str, Callable[[], Any]],
        response: "HypervisorOperationResultChannel",
        effect_encoder: Callable[[Any], Any] | None = None,
    ) -> HypervisorExecutionResult | None:
        """Mathematics: commit `result` to the reverse channel before request `ACK`, preserving retryability when response delivery fails."""

        prepared = self._prepare_execution(arbitration, authorize)
        if prepared is None:
            return None
        transport_sequence, authorized = prepared
        result = arbitration.execute(authorized, handlers, effect_encoder)
        if not isinstance(response, HypervisorOperationResultChannel):
            raise HypervisorOperationTransportError("operation reply requires a HypervisorOperationResultChannel")
        response.send(result)
        self._consume_after_execution(transport_sequence)
        return result

    def _prepare_execution(
        self,
        arbitration: HypervisorArbitrationLoop,
        authorize: Callable[[HypervisorArbitrationEvent], HypervisorArbitrationEvent],
    ) -> tuple[int, HypervisorArbitrationEvent] | None:
        """Mathematics: project `peek(Q)` to authorized event `e'` while preserving `I(e')=I(e)` before any effect transition."""

        if not isinstance(arbitration, HypervisorArbitrationLoop):
            raise HypervisorOperationTransportError("operation transport requires a HypervisorArbitrationLoop")
        if not callable(authorize):
            raise HypervisorOperationTransportError("operation transport requires a receiver authority function")
        peeked = self.channel.peek()
        if peeked is None:
            return None
        transport_sequence, payload = peeked
        event = self._decode_payload(payload)
        try:
            authorized = authorize(event)
        except Exception as exc:
            raise HypervisorOperationTransportError(f"receiver authority rejected operation: {exc}") from exc
        if not isinstance(authorized, HypervisorArbitrationEvent) or authorized.identity != event.identity:
            raise HypervisorOperationTransportError("receiver authority changed operation identity")
        return transport_sequence, authorized

    def _consume_after_execution(self, transport_sequence: int) -> None:
        """Mathematics: consume `F_s` and emit `ACK(s)` only after effect or response commit reaches a typed result."""

        received = self.channel.receive()
        if received is not None and received[0] != transport_sequence:
            raise HypervisorOperationTransportError("operation frame sequence changed after execution")

    def _decode_payload(self, payload: Any) -> HypervisorArbitrationEvent:
        """Mathematics: invert wire relation `W=(kind,event)` only for expected kind and peer-bound source/channel identity."""

        if not isinstance(payload, Mapping) or payload.get("kind") != OPERATION_EVENT_KIND:
            raise HypervisorOperationTransportError("operation payload kind is invalid")
        raw_event = payload.get("event")
        if not isinstance(raw_event, Mapping):
            raise HypervisorOperationTransportError("operation payload event is not a mapping")
        try:
            event = HypervisorArbitrationEvent.from_dict(raw_event)
        except (ClassifierError, TypeError, ValueError, OverflowError) as exc:
            raise HypervisorOperationTransportError(f"operation payload is invalid: {exc}") from exc
        if event.source != self.channel.peer or event.channel != self.channel.channel:
            raise HypervisorOperationTransportError("operation payload source or channel is not peer-bound")
        return event


class HypervisorOperationResultChannel:
    """Carry typed operation effects back to the initiating host with semantic duplicate suppression."""

    def __init__(self, channel: ReliableChannel, operation_source: str, operation_channel: str) -> None:
        """Mathematics: bind result FIFO `R` and initialize semantic ledger `S=∅` for requester and operation channel."""

        if not isinstance(channel, ReliableChannel):
            raise HypervisorOperationTransportError("result transport requires a ReliableChannel")
        if not operation_source or not operation_channel:
            raise HypervisorOperationTransportError("result transport requires non-empty operation identity labels")
        self.channel = channel
        self.operation_source = operation_source
        self.operation_channel = operation_channel
        self._seen: dict[tuple[str, str, int], tuple[str, HypervisorExecutionResult]] = {}

    def send(self, result: HypervisorExecutionResult) -> int:
        """Mathematics: emit `RDATA(kind_result,result)` while retaining response frame until its ACK."""

        self._validate_result(result)
        return self.channel.send({"kind": OPERATION_RESULT_KIND, "result": result.to_dict()})

    def receive(self) -> HypervisorExecutionResult | None:
        """Mathematics: apply semantic result law `S[I]` before consuming and acknowledging the reliable response frame."""

        peeked = self.channel.peek()
        if peeked is None:
            return None
        transport_sequence, payload = peeked
        incoming = self._decode_payload(payload)
        identity = (incoming.source, incoming.channel, incoming.sequence)
        previous = self._seen.get(identity)
        if previous is not None:
            previous_fingerprint, stored = previous
            if previous_fingerprint != incoming.fingerprint:
                raise HypervisorOperationTransportError("conflicting operation result")
            result = HypervisorExecutionResult(
                stored.source,
                stored.channel,
                stored.sequence,
                stored.logical_time,
                stored.fingerprint,
                stored.decision_receipt,
                stored.action,
                stored.domain,
                stored.effect,
                True,
                stored.executed,
            )
        else:
            result = HypervisorExecutionResult(
                incoming.source,
                incoming.channel,
                incoming.sequence,
                incoming.logical_time,
                incoming.fingerprint,
                incoming.decision_receipt,
                incoming.action,
                incoming.domain,
                incoming.effect,
                False,
                incoming.executed,
            )
        received = self.channel.receive()
        if received is not None and received[0] != transport_sequence:
            raise HypervisorOperationTransportError("operation result sequence changed during validation")
        self._seen.setdefault(identity, (incoming.fingerprint, result if not result.replayed else stored))
        return result

    def snapshot(self) -> dict[str, object]:
        """Mathematics: serialize result transport `R`, operation binding, and semantic ledger `S` for response replay."""

        return {
            "version": 1,
            "channel": self.channel.snapshot(),
            "operation_source": self.operation_source,
            "operation_channel": self.operation_channel,
            "seen": [result.to_dict() for _, result in sorted(self._seen.values(), key=self._sort_key)],
        }

    @classmethod
    def from_snapshot(cls, payload: Mapping[str, Any], transport: Any) -> "HypervisorOperationResultChannel":
        """Mathematics: reconstruct result FIFO and `S` only when every response identity is unique and peer-bound."""

        if int(payload.get("version", 1)) != 1:
            raise HypervisorOperationTransportError("unsupported operation result snapshot version")
        raw_channel = payload.get("channel")
        if not isinstance(raw_channel, Mapping):
            raise HypervisorOperationTransportError("operation result snapshot channel is invalid")
        adapter = cls(
            ReliableChannel.from_snapshot(dict(raw_channel), transport),
            str(payload.get("operation_source", "")),
            str(payload.get("operation_channel", "")),
        )
        for raw_result in payload.get("seen", ()):
            result = HypervisorExecutionResult.from_dict(raw_result, replayed=False)
            adapter._validate_result(result)
            identity = (result.source, result.channel, result.sequence)
            if identity in adapter._seen:
                raise HypervisorOperationTransportError("duplicate operation result identity in snapshot")
            adapter._seen[identity] = (result.fingerprint, result)
        return adapter

    @staticmethod
    def _sort_key(item: tuple[str, HypervisorExecutionResult]) -> tuple[str, str, int]:
        """Mathematics: order semantic results by operation identity `(source,channel,sequence)` for deterministic snapshots."""

        result = item[1]
        return result.source, result.channel, result.sequence

    def _validate_result(self, result: HypervisorExecutionResult) -> None:
        """Mathematics: require result identity `I=(operation_source,operation_channel,sequence)` and canonical effect type."""

        if not isinstance(result, HypervisorExecutionResult):
            raise HypervisorOperationTransportError("operation result requires a HypervisorExecutionResult")
        if result.source != self.operation_source or result.channel != self.operation_channel:
            raise HypervisorOperationTransportError("operation result identity is not bound to requester or operation channel")

    def _decode_payload(self, payload: Any) -> HypervisorExecutionResult:
        """Mathematics: invert result wire relation `W=(kind,result)` only for typed requester-bound results."""

        if not isinstance(payload, Mapping) or payload.get("kind") != OPERATION_RESULT_KIND:
            raise HypervisorOperationTransportError("operation result payload kind is invalid")
        raw_result = payload.get("result")
        if not isinstance(raw_result, Mapping):
            raise HypervisorOperationTransportError("operation result payload is not a mapping")
        try:
            result = HypervisorExecutionResult.from_dict(raw_result, replayed=False)
            self._validate_result(result)
        except (ClassifierError, TypeError, ValueError, OverflowError) as exc:
            raise HypervisorOperationTransportError(f"operation result payload is invalid: {exc}") from exc
        return result
