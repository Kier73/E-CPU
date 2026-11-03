"""Persistent path session for receiver-side MailCPU transit computation."""

from __future__ import annotations

from typing import Any, Mapping

from .hypervisor_transport import (
    HypervisorOperationChannel,
    HypervisorOperationResultChannel,
)
from .transit_worker import TransitComputeWorker


class TransitComputeSession:
    """One receiver-side computation path with state derived from its protocol and execution ledgers."""

    def __init__(
        self,
        worker: TransitComputeWorker,
        request: HypervisorOperationChannel,
        response: HypervisorOperationResultChannel,
    ) -> None:
        """Mathematics: compose path state Σ=Σ_request×Σ_worker×Σ_response without duplicating any authoritative ledger."""

        if not isinstance(worker, TransitComputeWorker):
            raise TypeError("transit compute session requires a TransitComputeWorker")
        if not isinstance(request, HypervisorOperationChannel):
            raise TypeError("transit compute session requires a HypervisorOperationChannel request")
        if not isinstance(response, HypervisorOperationResultChannel):
            raise TypeError("transit compute session requires a HypervisorOperationResultChannel response")

        inbound = request.channel
        outbound = response.channel
        if inbound.destination != inbound.source:
            raise ValueError("transit session request channel must be receiver-bound")
        if outbound.source != inbound.source or outbound.destination != inbound.peer:
            raise ValueError("transit session response channel must return to the request peer")
        if response.operation_source != inbound.peer or response.operation_channel != inbound.channel:
            raise ValueError("transit session response identity must match the request peer and channel")

        self.worker = worker
        self.request = request
        self.response = response

    @property
    def phase(self) -> str:
        """Mathematics: classify path phase from live protocol state, with no duplicate session-side state variable."""

        if self.request.channel.peek() is not None:
            return "request-ready"
        if self.response.channel.pending_sequences():
            return "response-unacknowledged"
        return "idle"

    def state(self) -> dict[str, object]:
        """Mathematics: expose a diagnostic projection of causal cursors and pending effects, not a second source of truth."""

        request_channel = self.request.channel
        response_channel = self.response.channel
        return {
            "phase": self.phase,
            "request": {
                "source": request_channel.source,
                "peer": request_channel.peer,
                "channel": request_channel.channel,
                "next_receive_sequence": request_channel.next_receive_sequence,
            },
            "response": {
                "source": response_channel.source,
                "peer": response_channel.peer,
                "channel": response_channel.channel,
                "pending_sequences": list(response_channel.pending_sequences()),
            },
        }

    def serve_once(self):
        """Mathematics: apply at most one receiver transition T_q and let the existing response-before-ACK rule preserve retryability."""

        return self.worker.serve_once(self.request, self.response)

    def snapshot(self) -> dict[str, object]:
        """Mathematics: checkpoint the complete path product only when request and response channels satisfy the worker's quiescence invariant."""

        return self.worker.snapshot(self.request, self.response)

    @classmethod
    def from_snapshot(
        cls,
        payload: Mapping[str, Any],
        request_transport: Any,
        response_transport: Any,
    ) -> "TransitComputeSession":
        """Mathematics: restore path product Σ from its worker/channel checkpoint and caller-rebound transports."""

        worker, request, response = TransitComputeWorker.from_snapshot(
            payload,
            request_transport,
            response_transport,
        )
        return cls(worker, request, response)
