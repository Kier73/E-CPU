"""Receiver-executed inverse navigation as a typed Computational Fabric operation.

The request carries a contextual base address and observer contract. The
receiver validates its local Structural Memory authority, then invokes the
existing ContextualOrbitNavigator. The base coordinate is never read merely
to authorize navigation; the result contains the actual located-coordinate
read receipt and a symbolic Virtual Ground projection.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import re
import threading
from typing import Any, Mapping, Sequence

from .computational_fabric import (
    ComputationalFabricDirectory,
    ComputationalFabricResolver,
    ComputationalFabricStatus,
)
from .computational_fabric_forwarding import (
    ComputationalFabricForwardingClient,
    ComputationalFabricForwardingEnvelope,
    ComputationalFabricHopReceipt,
)
from .computational_resolver import ComputationalAddress
from .evidence_path_resolver import RouteMetricKey
from .observer_orbit import (
    ContextualOrbitAddress,
    ContextualOrbitNavigator,
    ObserverContract,
    ObserverOrbitError,
    OrbitValueResult,
)
from .seed import SystemIdentity
from .semantic_translation import canonical_value_digest
from .structural_memory import StructuralMemoryRegistry
from .temporal import SchedulerReading
from .virtual_layer import (
    OperatorSpec,
    VirtualBudget,
    VirtualLayerWorkload,
    VirtualOperatorRef,
)


CONTEXTUAL_ORBIT_LOCATE_VALUE_OPERATOR_ID = "mailcpu.contextual_orbit.locate_value"
CONTEXTUAL_ORBIT_LOCATE_VALUE_OPERATOR_VERSION = 1
_CONTEXTUAL_ORBIT_OPERATION_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_PEER_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")


class ContextualOrbitFabricError(ValueError):
    """A routed inverse-navigation query could not be admitted or verified."""


def _digest(value: Any, label: str) -> str:
    """Mathematics: require a lowercase SHA-256 identity for one canonical value."""
    result = value if isinstance(value, str) else ""
    if _SHA256.fullmatch(result) is None:
        raise ContextualOrbitFabricError(f"{label} must be a lowercase SHA-256 digest")
    return result


def _peer(value: Any, label: str) -> str:
    """Mathematics: restrict peer identities to the stable bounded identifier alphabet."""
    if not isinstance(value, str) or _PEER_ID.fullmatch(value) is None:
        raise ContextualOrbitFabricError(f"{label} is not a valid peer identity")
    return value


@dataclass(frozen=True)
class ContextualOrbitLocateValueRequest:
    """One exact inverse query under a base Virtual Ground and observer contract."""

    address: ContextualOrbitAddress
    observer: ObserverContract
    target_value: int
    operation_id: str = "mailcpu.orbit.locate-value"

    def __post_init__(self) -> None:
        if not isinstance(self.address, ContextualOrbitAddress):
            raise ContextualOrbitFabricError("request address must be a ContextualOrbitAddress")
        if not isinstance(self.observer, ObserverContract):
            raise ContextualOrbitFabricError("request observer must be an ObserverContract")
        if type(self.target_value) is not int:
            raise ContextualOrbitFabricError("target_value must be a strict integer")
        if not isinstance(self.operation_id, str) or _CONTEXTUAL_ORBIT_OPERATION_ID.fullmatch(self.operation_id) is None:
            raise ContextualOrbitFabricError("operation_id must be a safe 1-128 character identifier")
        if self.address.orbit_offset != 0:
            raise ContextualOrbitFabricError("inverse query must be pinned at its base Virtual Ground coordinate")
        if self.observer.context_digest != self.address.context_digest:
            raise ContextualOrbitFabricError("observer context differs from the contextual orbit address")
        if self.address.structural_memory.coordinate != 0:
            raise ContextualOrbitFabricError("inverse query must carry the exact zero-offset Structural Memory reference")

    def to_dict(self) -> dict[str, Any]:
        """Mathematics: serialize the complete query, keeping intent separate from host authority."""
        return {
            "schema": "mailcpu.contextual-orbit.locate-value-request.v1",
            "address": self.address.to_dict(),
            "observer": self.observer.to_dict(),
            "target_value": self.target_value,
            "operation_id": self.operation_id,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ContextualOrbitLocateValueRequest":
        """Mathematics: reconstruct a typed query and re-run every address and observer invariant."""
        expected = {"schema", "address", "observer", "target_value", "operation_id"}
        if not isinstance(payload, Mapping) or set(payload) != expected:
            raise ContextualOrbitFabricError("inverse query fields are invalid")
        if payload["schema"] != "mailcpu.contextual-orbit.locate-value-request.v1":
            raise ContextualOrbitFabricError("unsupported inverse query schema")
        if not isinstance(payload["address"], Mapping) or not isinstance(payload["observer"], Mapping):
            raise ContextualOrbitFabricError("inverse query address and observer must be objects")
        try:
            return cls(
                address=ContextualOrbitAddress.from_dict(payload["address"]),
                observer=ObserverContract.from_dict(payload["observer"]),
                target_value=payload["target_value"],
                operation_id=payload["operation_id"],
            )
        except (KeyError, TypeError, ValueError) as exc:
            if isinstance(exc, ContextualOrbitFabricError):
                raise
            raise ContextualOrbitFabricError(f"inverse query contains invalid typed fields: {exc}") from exc

    @property
    def digest(self) -> str:
        """Mathematics: content-address the exact base Ground, memory revision, observer and target predicate."""
        return canonical_value_digest(self.to_dict())


@dataclass(frozen=True)
class ContextualOrbitLocateValueReceipt:
    """Origin-verifiable route and navigation result identity, without claiming a signature."""

    request_digest: str
    result: OrbitValueResult
    host_id: str
    peer_id: str
    peer_path: tuple[str, ...]
    route_witness_digest: str
    forwarding_receipt_digest: str
    operator_effect_digest: str
    implementation_fingerprint: str

    def __post_init__(self) -> None:
        _digest(self.request_digest, "request_digest")
        if not isinstance(self.result, OrbitValueResult):
            raise ContextualOrbitFabricError("receipt result must be an OrbitValueResult")
        if not isinstance(self.host_id, str) or not self.host_id:
            raise ContextualOrbitFabricError("host_id must be non-empty")
        peer_id = _peer(self.peer_id, "peer_id")
        path = tuple(self.peer_path)
        if len(path) < 2 or any(not isinstance(item, str) for item in path):
            raise ContextualOrbitFabricError("peer_path must contain an origin and remote peer")
        for item in path:
            _peer(item, "peer_path entry")
        if len(path) != len(set(path)) or path[-1] != peer_id:
            raise ContextualOrbitFabricError("peer_path must be simple and terminate at peer_id")
        object.__setattr__(self, "peer_path", path)
        for name in ("route_witness_digest", "forwarding_receipt_digest", "operator_effect_digest", "implementation_fingerprint"):
            _digest(getattr(self, name), name)

    def to_dict(self) -> dict[str, Any]:
        """Mathematics: serialize the routed result and its path/effect commitments."""
        return {
            "schema": "mailcpu.contextual-orbit.locate-value-receipt.v1",
            "request_digest": self.request_digest,
            "result": self.result.to_dict(),
            "host_id": self.host_id,
            "peer_id": self.peer_id,
            "peer_path": list(self.peer_path),
            "route_witness_digest": self.route_witness_digest,
            "forwarding_receipt_digest": self.forwarding_receipt_digest,
            "operator_effect_digest": self.operator_effect_digest,
            "implementation_fingerprint": self.implementation_fingerprint,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ContextualOrbitLocateValueReceipt":
        """Mathematics: rebuild the typed result and verify the route receipt envelope."""
        expected = {
            "schema", "request_digest", "result", "host_id", "peer_id", "peer_path",
            "route_witness_digest", "forwarding_receipt_digest", "operator_effect_digest",
            "implementation_fingerprint",
        }
        if not isinstance(payload, Mapping) or set(payload) != expected:
            raise ContextualOrbitFabricError("inverse navigation receipt fields are invalid")
        if payload["schema"] != "mailcpu.contextual-orbit.locate-value-receipt.v1":
            raise ContextualOrbitFabricError("unsupported inverse navigation receipt schema")
        if not isinstance(payload["result"], Mapping) or not isinstance(payload["peer_path"], list):
            raise ContextualOrbitFabricError("inverse navigation receipt result/path is malformed")
        return cls(
            request_digest=payload["request_digest"],
            result=OrbitValueResult.from_dict(payload["result"]),
            host_id=payload["host_id"],
            peer_id=payload["peer_id"],
            peer_path=tuple(payload["peer_path"]),
            route_witness_digest=payload["route_witness_digest"],
            forwarding_receipt_digest=payload["forwarding_receipt_digest"],
            operator_effect_digest=payload["operator_effect_digest"],
            implementation_fingerprint=payload["implementation_fingerprint"],
        )


def contextual_orbit_locate_value_operator_spec() -> OperatorSpec:
    """Declare the deterministic, pure operation contract for receiver-side inverse navigation."""
    return OperatorSpec(
        operator_id=CONTEXTUAL_ORBIT_LOCATE_VALUE_OPERATOR_ID,
        version=CONTEXTUAL_ORBIT_LOCATE_VALUE_OPERATOR_VERSION,
        description=(
            "Locate the first coordinate matching an integer target under a pinned contextual "
            "Structural Memory law using only an explicitly supported direct inverse and forward verification"
        ),
        input_kind="object",
        output_kind="object",
        substrates=("cpu",),
        required_rights=frozenset({"compute"}),
        base_energy=128,
        energy_per_byte=1,
        max_input_bytes=262_144,
        max_output_bytes=262_144,
        deterministic=True,
        effect_mode="pure",
    )


def make_contextual_orbit_locate_value_handler(
    registry: StructuralMemoryRegistry,
):
    """Bind the trusted operator to one receiver-local Structural Memory registry and reusable navigator."""
    if not isinstance(registry, StructuralMemoryRegistry):
        raise ContextualOrbitFabricError("navigation handler requires a receiver-local StructuralMemoryRegistry")
    navigator = ContextualOrbitNavigator(registry)

    def execute(value: Mapping[str, Any], workload: VirtualLayerWorkload) -> dict[str, Any]:
        """Invert on the receiver and return the exact forward-verified projection/read receipt."""
        if not isinstance(value, Mapping) or not isinstance(workload, VirtualLayerWorkload):
            raise ContextualOrbitFabricError("navigation handler requires an object input and typed workload")
        request = ContextualOrbitLocateValueRequest.from_dict(value)
        if workload.system != request.address.system_identity or workload.ground != request.address.base_ground:
            raise ContextualOrbitFabricError("workload System or Virtual Ground differs from the contextual orbit address")
        reference = workload.operator_ref(CONTEXTUAL_ORBIT_LOCATE_VALUE_OPERATOR_ID)
        if reference.structural_memory_access != "navigate":
            raise ContextualOrbitFabricError("receiver workload did not declare authority-only navigation access")
        if len(reference.structural_memory) != 1 or reference.structural_memory[0] != request.address.structural_memory:
            raise ContextualOrbitFabricError("receiver workload memory authority differs from the contextual base address")
        goal = workload.intention.get("goal")
        expected_goal = {
            "kind": CONTEXTUAL_ORBIT_LOCATE_VALUE_OPERATOR_ID,
            "request_digest": request.digest,
            "address_digest": request.address.digest,
            "observer_digest": request.observer.digest,
            "target_value": request.target_value,
        }
        if not isinstance(goal, Mapping) or dict(goal) != expected_goal:
            raise ContextualOrbitFabricError("Virtual Layer goal differs from the typed inverse query")
        result = navigator.locate_value(
            request.address,
            request.observer,
            request.target_value,
            operation_id=request.operation_id,
        )
        return {
            "request_digest": request.digest,
            "result": result.to_dict(),
        }

    return execute


def _validate_navigation_result(
    request: ContextualOrbitLocateValueRequest,
    result: OrbitValueResult,
) -> None:
    """Verify the result is exactly the requested contextual projection and its receiver read evidence."""
    if result.target_value != request.target_value:
        raise ContextualOrbitFabricError("receiver located a value other than the requested target")
    address = request.address
    projection = result.navigation.projection
    coordinate = result.orbit_coordinate
    expected_read_ref = address.structural_memory
    located_reference = replace(expected_read_ref, coordinate=coordinate)
    located_address = ContextualOrbitAddress(
        system_identity=address.system_identity,
        base_ground=address.base_ground,
        computational_ground=address.computational_ground,
        coordinate=SchedulerReading(
            address.coordinate.scheduler_id,
            address.base_ground.coordinate + coordinate,
        ),
        structural_memory=located_reference,
        context_extensions=address.context_extensions,
    )
    if (
        projection.system_identity != address.system_identity
        or projection.base_ground != address.base_ground
        or projection.computational_ground != address.computational_ground
        or projection.transition != request.observer.subject
        or projection.coordinate != located_address.coordinate
        or projection.orbit_offset != coordinate
        or projection.structural_memory != located_reference
        or projection.value != request.target_value
    ):
        raise ContextualOrbitFabricError("receiver projection does not match the requested Ground, observer, and memory address")

    read_receipt = projection.read_receipt
    expected_context_digest = canonical_value_digest(dict(address.structural_memory.context))
    if (
        read_receipt.memory_id != expected_read_ref.memory_id
        or read_receipt.revision != expected_read_ref.revision
        or read_receipt.spec_digest != expected_read_ref.spec_digest
        or read_receipt.certificate_digest != expected_read_ref.certificate_digest
        or read_receipt.coordinate != coordinate
        or read_receipt.context_digest != expected_context_digest
        or read_receipt.value != request.target_value
        or read_receipt.value_digest != projection.value_digest
    ):
        raise ContextualOrbitFabricError("receiver read receipt does not match the located Structural Memory coordinate")

    observation = result.navigation.observation
    expected_observation = {
        "schema": "mailcpu.orbit.observation.v1",
        "coordinate": located_address.coordinate.to_dict(),
        "orbit_offset": coordinate,
        "value": request.target_value,
        "value_digest": read_receipt.value_digest,
        "virtual_ground_projection_digest": projection.projection_digest,
    }
    evidence_read_receipts = [
        item for item in observation.evidence
        if item.type_id == "mailcpu.structural-memory.read-receipt"
    ]
    evidence_projections = [
        item for item in observation.evidence
        if item.type_id == "mailcpu.virtual-ground.projection"
    ]
    if (
        observation.observer_id != request.observer.observer_id
        or observation.revision != request.observer.revision
        or observation.contract_digest != request.observer.digest
        or observation.subject != request.observer.subject
        or observation.interpretation != request.observer.interpretation
        or observation.observation != request.observer.observation
        or observation.operation_id != request.operation_id
        or observation.input_digest != located_address.digest
        or observation.context_digest != request.observer.context_digest
        or observation.projection != expected_observation
        or len(evidence_read_receipts) != 1
        or evidence_read_receipts[0].content_digest != canonical_value_digest(read_receipt.to_dict())
        or len(evidence_projections) != 1
        or evidence_projections[0].content_digest != canonical_value_digest(projection.identity_payload())
    ):
        raise ContextualOrbitFabricError("observer receipt does not bind the requested located coordinate and read evidence")


class ContextualOrbitLocateValueDispatcher:
    """Resolve and route one inverse query, then verify its typed terminal result at the origin."""

    def __init__(
        self,
        *,
        origin_peer_id: str,
        directory: ComputationalFabricDirectory,
        forwarding_clients: Mapping[str, ComputationalFabricForwardingClient],
        operator_spec: OperatorSpec,
        computational_ground_fingerprint: str,
        budget: VirtualBudget,
        eligible_nodes: Sequence[str],
        origin_channel: str,
        first_sequence: int,
        logical_time: int = 0,
        max_hops: int = 8,
        metric_order: Sequence[RouteMetricKey],
    ) -> None:
        if not isinstance(directory, ComputationalFabricDirectory) or directory.local_peer_id != origin_peer_id:
            raise ContextualOrbitFabricError("dispatcher directory must belong to the origin peer")
        clients = dict(forwarding_clients)
        if not clients or any(
            not isinstance(client, ComputationalFabricForwardingClient)
            or peer_id != client.remote_endpoint.peer_id
            or client.local_peer_id != origin_peer_id
            or client.origin_channel != origin_channel
            for peer_id, client in clients.items()
        ):
            raise ContextualOrbitFabricError("forwarding clients must be authenticated adjacent peers owned by the origin")
        if (
            not isinstance(operator_spec, OperatorSpec)
            or operator_spec.operator_id != CONTEXTUAL_ORBIT_LOCATE_VALUE_OPERATOR_ID
            or operator_spec.version != CONTEXTUAL_ORBIT_LOCATE_VALUE_OPERATOR_VERSION
            or not operator_spec.replay_safe
        ):
            raise ContextualOrbitFabricError("dispatcher requires the contextual orbit locate_value operator contract")
        _digest(computational_ground_fingerprint, "computational_ground_fingerprint")
        if not isinstance(budget, VirtualBudget):
            raise ContextualOrbitFabricError("dispatcher requires a VirtualBudget")
        nodes = tuple(eligible_nodes)
        if not nodes or any(not isinstance(item, str) or not item for item in nodes) or len(nodes) != len(set(nodes)):
            raise ContextualOrbitFabricError("eligible_nodes must contain unique declared logical nodes")
        if not isinstance(origin_channel, str) or not origin_channel.strip():
            raise ContextualOrbitFabricError("origin_channel must be non-empty")
        if type(first_sequence) is not int or first_sequence < 1:
            raise ContextualOrbitFabricError("first_sequence must be a positive strict integer")
        if type(logical_time) is not int or logical_time < 0:
            raise ContextualOrbitFabricError("logical_time must be a non-negative strict integer")
        if type(max_hops) is not int or max_hops < 1:
            raise ContextualOrbitFabricError("max_hops must be a positive strict integer")
        metrics = tuple(metric_order)
        if not metrics or any(not isinstance(item, RouteMetricKey) for item in metrics):
            raise ContextualOrbitFabricError("metric_order must contain RouteMetricKey values")
        self.origin_peer_id = _peer(origin_peer_id, "origin_peer_id")
        self.directory = directory
        self.forwarding_clients = clients
        self.operator_spec = operator_spec
        self.computational_ground_fingerprint = computational_ground_fingerprint
        self.budget = budget
        self.eligible_nodes = nodes
        self.origin_channel = origin_channel
        self.first_sequence = first_sequence
        self.logical_time = logical_time
        self.max_hops = max_hops
        self.metric_order = metrics
        self._next_sequence = first_sequence
        self._sequence_lock = threading.Lock()

    def __call__(self, request: ContextualOrbitLocateValueRequest) -> ContextualOrbitLocateValueReceipt:
        """Route one operation and return only after the destination's Hypervisor effect is verified."""
        if not isinstance(request, ContextualOrbitLocateValueRequest):
            raise ContextualOrbitFabricError("dispatcher requires a ContextualOrbitLocateValueRequest")
        with self._sequence_lock:
            sequence = self._next_sequence
            self._next_sequence += 1
        logical_time = self.logical_time + sequence - self.first_sequence
        memory_reference = request.address.structural_memory
        operator_reference = VirtualOperatorRef(
            self.operator_spec.operator_id,
            self.operator_spec.version,
            structural_memory=(memory_reference,),
            structural_memory_access="navigate",
        )
        workload = VirtualLayerWorkload(
            workload_id=f"orbit-locate-{request.digest[:16]}-{sequence:08d}",
            system=request.address.system_identity,
            ground=request.address.base_ground,
            intention={
                "goal": {
                    "kind": CONTEXTUAL_ORBIT_LOCATE_VALUE_OPERATOR_ID,
                    "request_digest": request.digest,
                    "address_digest": request.address.digest,
                    "observer_digest": request.observer.digest,
                    "target_value": request.target_value,
                }
            },
            operators=(operator_reference,),
            input_value=request.to_dict(),
            budget=self.budget,
            logical_time=logical_time,
            eligible_nodes=self.eligible_nodes,
            max_hops=self.max_hops,
            schema_version=3,
        )
        address = ComputationalAddress.from_workload(
            workload,
            self.operator_spec.operator_id,
            self.operator_spec,
            self.computational_ground_fingerprint,
            program_fingerprint=None,
            metric_order=self.metric_order,
        )
        planned = ComputationalFabricResolver().resolve(
            address,
            self.directory,
            origin_peer_id=self.origin_peer_id,
            max_hops=self.max_hops,
        )
        if planned.status is not ComputationalFabricStatus.FOUND or planned.witness is None:
            details = "; ".join(item.detail for item in planned.blockers[:4])
            raise ContextualOrbitFabricError(
                f"fabric could not resolve inverse navigation to an eligible receiver: {planned.status.value}: {details}"
            )
        route = planned.witness
        if len(route.peer_path) < 2:
            raise ContextualOrbitFabricError("inverse-navigation dispatcher requires a remote receiver")
        if route.target_host.implementation_fingerprint is None:
            raise ContextualOrbitFabricError("inverse-navigation receiver has no pinned implementation fingerprint")
        next_peer = route.peer_path[1]
        client = self.forwarding_clients.get(next_peer)
        if client is None:
            raise ContextualOrbitFabricError(f"no authenticated forwarding client is configured for first hop {next_peer!r}")

        envelope = ComputationalFabricForwardingEnvelope.begin(
            address,
            route,
            origin_channel=self.origin_channel,
            origin_sequence=sequence,
        )
        hop_receipt = client.forward(envelope, self.directory)
        if not isinstance(hop_receipt, ComputationalFabricHopReceipt) or not hop_receipt.succeeded:
            raise ContextualOrbitFabricError("fabric forwarding did not commit a successful terminal execution")
        if hop_receipt.operation_digest != envelope.operation_digest:
            raise ContextualOrbitFabricError("forwarding receipt belongs to a different inverse-navigation operation")
        terminal = hop_receipt
        while terminal.next_peer_id is not None:
            if terminal.downstream is None:
                raise ContextualOrbitFabricError("forwarding receipt has an incomplete downstream chain")
            terminal = terminal.downstream
        if terminal.peer_id != route.peer_path[-1] or not isinstance(terminal.terminal_execution, Mapping):
            raise ContextualOrbitFabricError("forwarding receipt does not terminate at the selected receiver")
        terminal_execution = terminal.terminal_execution
        if (
            terminal_execution.get("accepted") is not True
            or terminal_execution.get("executed") is not True
            or terminal_execution.get("status") not in {"executed", "replayed"}
            or not isinstance(terminal_execution.get("execution"), Mapping)
        ):
            raise ContextualOrbitFabricError("terminal peer did not return an accepted Hypervisor execution")
        execution = terminal_execution["execution"]
        if execution.get("action") != "allow" or not isinstance(execution.get("effect"), Mapping):
            raise ContextualOrbitFabricError("terminal inverse-navigation operation lacks a local Hypervisor ALLOW effect")
        effect = execution["effect"]
        if (
            effect.get("kind") != "virtual_layer.operator_result"
            or effect.get("workload_id") != workload.workload_id
            or effect.get("workload_digest") != workload.digest
            or effect.get("operator_id") != self.operator_spec.operator_id
            or effect.get("operator_version") != self.operator_spec.version
            or effect.get("operator_contract_digest") != self.operator_spec.digest
            or effect.get("input_digest") != address.input_digest
            or not isinstance(effect.get("result"), Mapping)
        ):
            raise ContextualOrbitFabricError("terminal effect does not bind the addressed inverse-navigation workload")
        operator_result = effect["result"]
        if canonical_value_digest(operator_result) != effect.get("result_digest"):
            raise ContextualOrbitFabricError("terminal inverse-navigation result digest is inconsistent")
        if operator_result.get("request_digest") != request.digest or not isinstance(operator_result.get("result"), Mapping):
            raise ContextualOrbitFabricError("terminal result does not bind the exact inverse query")
        try:
            result = OrbitValueResult.from_dict(operator_result["result"])
            _validate_navigation_result(request, result)
        except (ObserverOrbitError, ValueError, TypeError, KeyError) as exc:
            if isinstance(exc, ContextualOrbitFabricError):
                raise
            raise ContextualOrbitFabricError(f"terminal inverse-navigation evidence failed origin verification: {exc}") from exc

        return ContextualOrbitLocateValueReceipt(
            request_digest=request.digest,
            result=result,
            host_id=route.target_host.host_id,
            peer_id=route.target_host.peer_id,
            peer_path=route.peer_path,
            route_witness_digest=route.digest,
            forwarding_receipt_digest=hop_receipt.digest,
            operator_effect_digest=effect["result_digest"],
            implementation_fingerprint=route.target_host.implementation_fingerprint,
        )


__all__ = [
    "CONTEXTUAL_ORBIT_LOCATE_VALUE_OPERATOR_ID",
    "CONTEXTUAL_ORBIT_LOCATE_VALUE_OPERATOR_VERSION",
    "ContextualOrbitFabricError",
    "ContextualOrbitLocateValueDispatcher",
    "ContextualOrbitLocateValueReceipt",
    "ContextualOrbitLocateValueRequest",
    "contextual_orbit_locate_value_operator_spec",
    "make_contextual_orbit_locate_value_handler",
]
