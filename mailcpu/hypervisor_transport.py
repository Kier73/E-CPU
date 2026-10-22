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
        result = arbitration.execute(authorized, handlers, effect_encoder)
        received = self.channel.receive()
        if received is not None and received[0] != transport_sequence:
            raise HypervisorOperationTransportError("operation frame sequence changed after execution")
        return result

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
