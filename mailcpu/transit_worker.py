"""Receiver-side worker for bounded MailCPU transit computations."""

from __future__ import annotations

from typing import Any, Mapping

from .classifier import HypervisorArbitrationEvent, HypervisorDomain, HypervisorExecutionResult
from .headless import HeadlessOS
from .hypervisor_transport import (
    HypervisorOperationChannel,
    HypervisorOperationResultChannel,
)
from .reliability import ReliableChannel
from .transit_compute import TransitComputeHost


class TransitComputeWorker:
    """Receiver-side service for isolated, capability-gated compute jobs."""

    def __init__(
        self,
        operating_system: HeadlessOS,
        authority_pid: int,
        compute_host: TransitComputeHost | None = None,
    ) -> None:
        """Mathematics: bind worker W to receiver state S and authority a, so each request is reauthorized by G_S(a, resource)."""

        if not isinstance(operating_system, HeadlessOS):
            raise TypeError("transit worker requires a HeadlessOS receiver")
        if not isinstance(authority_pid, int) or isinstance(authority_pid, bool):
            raise TypeError("transit worker authority pid must be an integer")
        operating_system.environment.kernel._process(authority_pid)
        if compute_host is not None and not isinstance(compute_host, TransitComputeHost):
            raise TypeError("transit worker compute_host must be a TransitComputeHost")
        self.operating_system = operating_system
        self.authority_pid = authority_pid
        self.compute_host = compute_host or TransitComputeHost()

    def _authorize(self, event: HypervisorArbitrationEvent) -> HypervisorArbitrationEvent:
        """Mathematics: replace all peer-supplied grants with receiver-local capability projection G_S(a, event)."""

        return self.operating_system.hypervisor_authorize_event(self.authority_pid, event)

    def serve_once(
        self,
        request: HypervisorOperationChannel,
        response: HypervisorOperationResultChannel,
    ) -> HypervisorExecutionResult | None:
        """Mathematics: consume at most one authorized request, commit its effect to response R, then acknowledge its request frame."""

        if not isinstance(request, HypervisorOperationChannel):
            raise TypeError("transit worker request must be a HypervisorOperationChannel")
        if not isinstance(response, HypervisorOperationResultChannel):
            raise TypeError("transit worker response must be a HypervisorOperationResultChannel")
        return request.receive_and_reply_event(
            self.operating_system.hypervisor_arbitration,
            self._authorize,
            {HypervisorDomain.CPU: self.compute_host.handle},
            response,
        )

    def snapshot(
        self,
        request: HypervisorOperationChannel,
        response: HypervisorOperationResultChannel,
    ) -> dict[str, object]:
        """Mathematics: checkpoint OS state and channel ledgers only at a quiescent boundary Q=0 with no unacknowledged result."""

        if not isinstance(request, HypervisorOperationChannel):
            raise TypeError("worker checkpoint requires a HypervisorOperationChannel")
        if not isinstance(response, HypervisorOperationResultChannel):
            raise TypeError("worker checkpoint requires a HypervisorOperationResultChannel")
        if request.channel.pending_sequences() or request.channel.peek() is not None or request.channel.transport.pending() != 0:
            raise ValueError("cannot checkpoint transit worker with pending request transport data")
        if response.channel.pending_sequences() or response.channel.transport.pending() != 0:
            raise ValueError("cannot checkpoint transit worker with unacknowledged response data")
        return {
            "version": 1,
            "authority_pid": self.authority_pid,
            "compute_bounds": {
                "max_source_bytes": self.compute_host.max_source_bytes,
                "max_instructions": self.compute_host.max_instructions,
                "max_ticks": self.compute_host.max_ticks,
                "max_registers": self.compute_host.max_registers,
            },
            "receiver": self.operating_system.snapshot(),
            "request_channel": request.channel.snapshot(),
            "response_channel": response.snapshot(),
        }

    @classmethod
    def from_snapshot(
        cls,
        payload: Mapping[str, Any],
        request_transport: Any,
        response_transport: Any,
    ) -> tuple[
        "TransitComputeWorker",
        HypervisorOperationChannel,
        HypervisorOperationResultChannel,
    ]:
        """Mathematics: restore W and its reliable channel cursors from checkpoint C, reusing caller-restored transports T_req,T_res."""

        if not isinstance(payload, Mapping) or int(payload.get("version", -1)) != 1:
            raise ValueError("unsupported transit worker checkpoint")
        raw_receiver = payload.get("receiver")
        raw_bounds = payload.get("compute_bounds")
        raw_request = payload.get("request_channel")
        raw_response = payload.get("response_channel")
        if not all(isinstance(item, Mapping) for item in (raw_receiver, raw_bounds, raw_request, raw_response)):
            raise ValueError("transit worker checkpoint is incomplete")
        expected_bounds = {
            "max_source_bytes",
            "max_instructions",
            "max_ticks",
            "max_registers",
        }
        if set(raw_bounds) != expected_bounds:
            raise ValueError("transit worker compute bounds are invalid")
        if any(
            not isinstance(raw_bounds[key], int) or isinstance(raw_bounds[key], bool)
            for key in expected_bounds
        ):
            raise ValueError("transit worker compute bounds must be integers")
        authority_pid = payload.get("authority_pid")
        if not isinstance(authority_pid, int) or isinstance(authority_pid, bool):
            raise ValueError("transit worker authority pid must be an integer")
        host = TransitComputeHost(
            max_source_bytes=raw_bounds["max_source_bytes"],
            max_instructions=raw_bounds["max_instructions"],
            max_ticks=raw_bounds["max_ticks"],
            max_registers=raw_bounds["max_registers"],
        )
        operating_system = HeadlessOS.from_snapshot(dict(raw_receiver))
        worker = cls(operating_system, authority_pid, host)
        request_channel = HypervisorOperationChannel(
            ReliableChannel.from_snapshot(dict(raw_request), request_transport)
        )
        response_channel = HypervisorOperationResultChannel.from_snapshot(
            raw_response,
            response_transport,
        )
        return worker, request_channel, response_channel
