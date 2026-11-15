"""Transit backend for receiver-pinned VGI similarity Ground navigation.

The receiver owns its trusted structural record catalogue, E-CPU's existing
hypervisor admission and persisted Transit effect ledger own execution/replay.
The network event contains only a typed workload and pinned content IDs.
"""
from __future__ import annotations

from typing import Any

from .classifier import HypervisorArbitrationEvent
from .transit_compute import TransitComputeHost
from .transit_router import TransitBackendRouter
from .virtual_layer import (
    OperatorRegistry, VirtualLayerRuntime, VirtualLayerWorkload,
    VIRTUAL_LAYER_OPERATOR_OPERATION, virtual_layer_operator_resource,
)
from .vgi_similarity_host import (
    PinnedSimilarityCatalogue, SIMILARITY_OPERATOR_ID,
    make_vgi_similarity_operator, vgi_similarity_implementation_fingerprint,
)

SIMILARITY_RESOURCE = virtual_layer_operator_resource(SIMILARITY_OPERATOR_ID, 1)


class TransitVGISimilarityHost(TransitComputeHost):
    """A pure admitted operator, executed by E-CPU's existing receiver ledger."""

    operation_name = VIRTUAL_LAYER_OPERATOR_OPERATION
    resource_name = SIMILARITY_RESOURCE

    def __init__(self, operating_system: Any, authority_pid: int,
                 catalogue: PinnedSimilarityCatalogue, *, node_id: str = "node-vgi") -> None:
        super().__init__()
        if not callable(getattr(operating_system, "hypervisor_authorize_event", None)):
            raise TypeError("similarity Transit host requires HeadlessOS hypervisor")
        if type(authority_pid) is not int:
            raise TypeError("receiver authority PID must be exact integer")
        operating_system.environment.kernel._process(authority_pid)
        self.operating_system = operating_system
        self.authority_pid = authority_pid
        self.node_id = node_id
        self.catalogue = catalogue
        self.registry = OperatorRegistry()
        spec, handler = make_vgi_similarity_operator(catalogue)
        self.registry.register(spec, handler)
        self.runtime = VirtualLayerRuntime(self.registry, node_id, frozenset({"cpu"}))
        self._implementation_fingerprint = vgi_similarity_implementation_fingerprint(type(self))

    @property
    def implementation_fingerprint(self) -> str:
        return self._implementation_fingerprint

    def handle(self, event: HypervisorArbitrationEvent) -> dict[str, object]:
        if not isinstance(event, HypervisorArbitrationEvent):
            raise TypeError("similarity Transit host requires a typed arbitration event")
        if (event.request.operation != self.operation_name
                or event.request.resource != self.resource_name
                or event.request.destructive):
            raise ValueError("event does not target the admitted similarity operator")
        result = self.runtime.execute_authorized_event(
            self.operating_system, self.authority_pid, event,
        )
        return {**dict(result), "backend_implementation_fingerprint": self.implementation_fingerprint}


def build_vgi_similarity_event(workload: VirtualLayerWorkload, source: str,
                               channel: str, sequence: int, logical_time: int,
                               *, node_id: str = "node-vgi") -> HypervisorArbitrationEvent:
    if not isinstance(workload, VirtualLayerWorkload):
        raise TypeError("similarity event requires VirtualLayerWorkload")
    registry = OperatorRegistry()
    # Contract only: sender never receives receiver implementation or authority.
    from .vgi_similarity_host import vgi_similarity_operator_spec
    spec = vgi_similarity_operator_spec()
    registry.declare(spec)
    runtime = VirtualLayerRuntime(registry, node_id, frozenset({"cpu"}))
    return runtime.build_event(source, channel, sequence, logical_time,
                               workload, SIMILARITY_OPERATOR_ID)


def make_transit_vgi_similarity_router(operating_system: Any, authority_pid: int,
                                       catalogue: PinnedSimilarityCatalogue,
                                       *, node_id: str = "node-vgi") -> TransitBackendRouter:
    router = TransitBackendRouter()
    router.register_backend(TransitVGISimilarityHost(
        operating_system, authority_pid, catalogue, node_id=node_id,
    ))
    return router