"""Receiver-side worker for bounded MailCPU transit computations."""

from __future__ import annotations

from .classifier import HypervisorArbitrationEvent, HypervisorDomain, HypervisorExecutionResult
from .headless import HeadlessOS
from .hypervisor_transport import (
    HypervisorOperationChannel,
    HypervisorOperationResultChannel,
)
from .transit_compute import TransitComputeHost


class TransitComputeWorker:
    """Persistent receiver-side service for isolated, capability-gated compute jobs."""

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
