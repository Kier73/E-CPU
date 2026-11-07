"""Transit backend adapter for typed VGI Signal8 Virtual Layer workloads.

The VGI interpreter remains a separately versioned computational Ground. This
module binds its existing Virtual Layer contract to the receiver's Transit
backend relation so the interpreter result and execution ledger share one
recoverable receiver checkpoint.
"""

from __future__ import annotations

from typing import Any

from .classifier import HypervisorArbitrationEvent
from .transit_compute import TransitComputeHost
from .transit_router import TransitBackendRouter
from .vgi_host import (
    VGI_SIGNAL8_OPERATOR_ID,
    make_vgi_signal8_operator,
    vgi_signal8_implementation_fingerprint,
)
from .virtual_layer import (
    OperatorRegistry,
    VirtualLayerRuntime,
    VirtualLayerWorkload,
    VIRTUAL_LAYER_OPERATOR_OPERATION,
    virtual_layer_operator_resource,
)

VGI_SIGNAL8_RESOURCE = virtual_layer_operator_resource(VGI_SIGNAL8_OPERATOR_ID, 1)


class TransitVGIHost(TransitComputeHost):
    """Receiver-local VGI Signal8 backend bound to one admitted HeadlessOS authority."""

    operation_name = VIRTUAL_LAYER_OPERATOR_OPERATION
    resource_name = VGI_SIGNAL8_RESOURCE

    def __init__(
        self,
        operating_system: Any,
        authority_pid: int,
        *,
        node_id: str = "node-vgi",
        max_steps: int = 10_000,
    ) -> None:
        """Mathematics: bind VGI's pure operator relation to receiver-local Ground, process authority, and finite execution budget."""
        super().__init__()
        if not callable(getattr(operating_system, "hypervisor_authorize_event", None)):
            raise TypeError("TransitVGIHost requires a HeadlessOS-compatible receiver")
        if not isinstance(authority_pid, int) or isinstance(authority_pid, bool):
            raise TypeError("TransitVGIHost authority_pid must be an integer")
        operating_system.environment.kernel._process(authority_pid)
        self.operating_system = operating_system
        self.authority_pid = authority_pid
        self.node_id = node_id
        self.registry = OperatorRegistry()
        spec, handler = make_vgi_signal8_operator(max_steps=max_steps)
        self.registry.register(spec, handler)
        self.runtime = VirtualLayerRuntime(
            self.registry,
            node_id,
            frozenset({"cpu"}),
        )

        self._implementation_fingerprint = vgi_signal8_implementation_fingerprint(
            type(self),
            max_configured_steps=max_steps,
        )

    @property
    def implementation_fingerprint(self) -> str:
        """Mathematics: Return the source identity of this concrete hosted VGI backend class."""
        return self._implementation_fingerprint

    def handle(self, event: HypervisorArbitrationEvent) -> dict[str, object]:
        """Mathematics: refine one authorized Transit event into the same typed Virtual Layer effect used by local execution."""
        if not isinstance(event, HypervisorArbitrationEvent):
            raise TypeError("TransitVGIHost requires a HypervisorArbitrationEvent")
        if (
            event.request.operation != self.operation_name
            or event.request.resource != self.resource_name
            or event.request.destructive
        ):
            raise ValueError("Transit event does not match the VGI Signal8 backend identity")
        effect = self.runtime.execute_authorized_event(
            self.operating_system,
            self.authority_pid,
            event,
        )
        bound_effect = dict(effect)
        bound_effect["backend_implementation_fingerprint"] = self.implementation_fingerprint
        return bound_effect


def build_vgi_signal8_event(
    workload: VirtualLayerWorkload,
    source: str,
    channel: str,
    sequence: int,
    logical_time: int,
    *,
    node_id: str = "node-vgi",
) -> HypervisorArbitrationEvent:
    """Mathematics: compile a portable VGI workload reference into the exact event identity consumed by TransitVGIHost."""
    if not isinstance(workload, VirtualLayerWorkload):
        raise TypeError("VGI event construction requires a VirtualLayerWorkload")
    registry = OperatorRegistry()
    spec, _handler = make_vgi_signal8_operator()
    registry.declare(spec)
    runtime = VirtualLayerRuntime(registry, node_id, frozenset({"cpu"}))
    return runtime.build_event(
        source,
        channel,
        sequence,
        logical_time,
        workload,
        VGI_SIGNAL8_OPERATOR_ID,
    )


def make_transit_vgi_router(
    operating_system: Any,
    authority_pid: int,
    *,
    node_id: str = "node-vgi",
    max_steps: int = 10_000,
) -> TransitBackendRouter:
    """Mathematics: extend the standard Transit backend map with the exact VGI Signal8 operation/resource pair."""
    router = TransitBackendRouter()
    router.register_backend(
        TransitVGIHost(
            operating_system,
            authority_pid,
            node_id=node_id,
            max_steps=max_steps,
        )
    )
    return router
