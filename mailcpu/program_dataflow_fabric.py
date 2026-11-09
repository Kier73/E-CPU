"""Operation-native execution of compiled MailCPU dataflow frontiers over the E-CPU fabric.

The compiler's dependency DAG remains independent of the communication topology.
This module binds one ready ADD frontier to one semantic vector-add request,
dispatches that request through the existing Computational Fabric, and maps
its typed result lanes back to the original DAG node identities.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

from .computation_dag import ComputationDAGError, NavigableComputationDAG
from .computational_fabric import (
    ComputationalFabricResolver,
)
from .computational_fabric_forwarding import (
    ComputationalFabricForwardingClient,
    ComputationalFabricForwardingEnvelope,
    ComputationalFabricHopReceipt,
)
from .computational_resolver import ComputationalAddress
from .evidence_path_resolver import RouteMetricKey
from .interpreter import compare_values
from .model import Op, RunStatus
from .program_dataflow import (
    CompiledMailCPUDataflow,
    DataflowExecutionReport,
)
from .orbit_fabric import ContextualOrbitDataflowInput
from .seed import SystemIdentity
from .structural_memory import StructuralMemoryReadReceipt
from .semantic_translation import canonical_value_digest
from .virtual_layer import (
    OperatorSpec,
    VirtualBudget,
    VirtualGroundRef,
    VirtualLayerWorkload,
    VirtualOperatorRef,
    VirtualStructuralMemoryRef,
)


class OperationNativeDataflowError(ValueError):
    """A dataflow operation could not be safely dispatched, verified, or committed."""


_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_NODE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_HOST_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_PEER_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_REGISTER = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}\Z")
_LANE_MEMORY_BINDING = re.compile(r"pc-[0-9]{6}\.(?:left|right)\Z")
_MAX_ADD_LANES = 64
_MAX_CONTEXTUAL_ORBIT_INPUTS = 64
_MAX_ADD_INTEGER_BITS = 4096


def _bounded_add_integer(value: Any, label: str) -> int:
    """Mathematics: enforce the shared CPU/E-GPU ADD domain of strict integers with at most 4096 bits."""
    result = _strict_integer(value, label)
    if result.bit_length() > _MAX_ADD_INTEGER_BITS:
        raise OperationNativeDataflowError(f"{label} exceeds the common {_MAX_ADD_INTEGER_BITS}-bit ADD domain")
    return result


def _memory_reference_with_binding(
    reference: VirtualStructuralMemoryRef,
    binding: str,
) -> VirtualStructuralMemoryRef:
    """Mathematics: rebind one immutable revision-pinned memory address to a unique lane-side name."""
    return VirtualStructuralMemoryRef(
        binding=binding,
        memory_id=reference.memory_id,
        revision=reference.revision,
        context=reference.context,
        coordinate=reference.coordinate,
        spec_digest=reference.spec_digest,
        certificate_digest=reference.certificate_digest,
    )




def _digest(value: Any, label: str) -> str:
    """Mathematics: admit only a lowercase 256-bit content identity."""
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise OperationNativeDataflowError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _strict_integer(value: Any, label: str) -> int:
    """Mathematics: distinguish ℤ from booleans and machine-specific coercions."""
    if type(value) is not int:
        raise OperationNativeDataflowError(f"{label} must be a strict integer")
    return value


@dataclass(frozen=True)
class DataflowAddLane:
    """One stable binary DAG node with two scalar operands and optional typed orbit provenance."""

    node_id: str
    node_digest: str
    destination: str
    left: int | None
    right: int | None
    left_register: str | None = None
    right_register: str | None = None
    left_reference: VirtualStructuralMemoryRef | None = None
    right_reference: VirtualStructuralMemoryRef | None = None
    left_orbit_inputs: tuple[ContextualOrbitDataflowInput, ...] = ()
    right_orbit_inputs: tuple[ContextualOrbitDataflowInput, ...] = ()

    def __post_init__(self) -> None:
        """Mathematics: validate each scalar operand, optional pinned memory address, and typed orbit provenance."""
        if not isinstance(self.node_id, str) or _NODE_ID.fullmatch(self.node_id) is None:
            raise OperationNativeDataflowError("lane node_id is invalid")
        _digest(self.node_digest, "lane node_digest")
        if not isinstance(self.destination, str) or _REGISTER.fullmatch(self.destination) is None:
            raise OperationNativeDataflowError("lane destination register is invalid")
        for side in ("left", "right"):
            value = getattr(self, side)
            register = getattr(self, f"{side}_register")
            reference = getattr(self, f"{side}_reference")
            orbit_inputs = tuple(getattr(self, f"{side}_orbit_inputs"))
            if value is not None:
                _bounded_add_integer(value, f"lane {side} operand")
                if reference is not None:
                    raise OperationNativeDataflowError(f"lane {side} cannot contain both a value and memory reference")
            elif not isinstance(reference, VirtualStructuralMemoryRef):
                raise OperationNativeDataflowError(f"lane {side} requires a value or VirtualStructuralMemoryRef")
            if orbit_inputs:
                if reference is not None or value is None:
                    raise OperationNativeDataflowError(f"lane {side} cannot combine contextual-orbit provenance with unresolved Structural Memory")
                if len(orbit_inputs) > _MAX_CONTEXTUAL_ORBIT_INPUTS:
                    raise OperationNativeDataflowError(f"lane {side} contextual-orbit provenance exceeds {_MAX_CONTEXTUAL_ORBIT_INPUTS} inputs")
                if any(not isinstance(item, ContextualOrbitDataflowInput) for item in orbit_inputs):
                    raise OperationNativeDataflowError(f"lane {side} contextual-orbit provenance must contain typed inputs")
                if orbit_inputs != tuple(sorted(orbit_inputs, key=lambda item: item.digest)):
                    raise OperationNativeDataflowError(f"lane {side} contextual-orbit provenance must be sorted by digest")
                if len({item.digest for item in orbit_inputs}) != len(orbit_inputs):
                    raise OperationNativeDataflowError(f"lane {side} contextual-orbit provenance must be unique")
            object.__setattr__(self, f"{side}_orbit_inputs", orbit_inputs)
            if reference is not None:
                if not isinstance(register, str) or _REGISTER.fullmatch(register) is None:
                    raise OperationNativeDataflowError(f"lane {side} memory operand requires its source register")
                if reference.binding != f"{self.node_id}.{side}":
                    raise OperationNativeDataflowError(f"lane {side} memory binding must be unique to its DAG node side")
            elif register is not None and (not isinstance(register, str) or _REGISTER.fullmatch(register) is None):
                raise OperationNativeDataflowError(f"lane {side} source register is invalid")

    def to_dict(self) -> dict[str, Any]:
        """Mathematics: serialize the exact typed operation identity and its inline or symbolic operand sides."""
        return {
            "node_id": self.node_id,
            "node_digest": self.node_digest,
            "destination": self.destination,
            "left": self.left,
            "right": self.right,
            "left_register": self.left_register,
            "right_register": self.right_register,
            "left_reference": None if self.left_reference is None else self.left_reference.to_dict(),
            "right_reference": None if self.right_reference is None else self.right_reference.to_dict(),
            "left_orbit_inputs": [item.to_dict() for item in self.left_orbit_inputs],
            "right_orbit_inputs": [item.to_dict() for item in self.right_orbit_inputs],
        }


DataflowBinaryLane = DataflowAddLane


@dataclass(frozen=True)
class DataflowAddFrontierRequest:
    """A content-bound batch of independent ADD nodes from one exact DAG frontier."""

    plan_digest: str
    context_digest: str
    frontier_index: int
    lanes: tuple[DataflowAddLane, ...]

    def __post_init__(self) -> None:
        _digest(self.plan_digest, "plan_digest")
        _digest(self.context_digest, "context_digest")
        if type(self.frontier_index) is not int or self.frontier_index < 0:
            raise OperationNativeDataflowError("frontier_index must be a non-negative strict integer")
        lanes = tuple(self.lanes)
        if not lanes or len(lanes) > _MAX_ADD_LANES or any(not isinstance(item, DataflowAddLane) for item in lanes):
            raise OperationNativeDataflowError(f"ADD frontier request requires 1..{_MAX_ADD_LANES} typed lanes")
        if lanes != tuple(sorted(lanes, key=lambda item: item.node_id)):
            raise OperationNativeDataflowError("ADD frontier lanes must be sorted by stable node identity")
        if len({item.node_id for item in lanes}) != len(lanes):
            raise OperationNativeDataflowError("ADD frontier node identities must be unique")
        object.__setattr__(self, "lanes", lanes)

    @property
    def digest(self) -> str:
        """Mathematics: identify the canonical ordered frontier request or remote result."""
        return canonical_value_digest(self.to_dict())

    @property
    def left_values(self) -> tuple[int, ...]:
        """Mathematics: project aligned inline left values; refuse unresolved receiver-side references."""
        if any(item.left is None for item in self.lanes):
            raise OperationNativeDataflowError("left operand vector contains receiver-resolved Structural Memory references")
        return tuple(item.left for item in self.lanes if item.left is not None)

    @property
    def right_values(self) -> tuple[int, ...]:
        """Mathematics: project aligned inline right values; refuse unresolved receiver-side references."""
        if any(item.right is None for item in self.lanes):
            raise OperationNativeDataflowError("right operand vector contains receiver-resolved Structural Memory references")
        return tuple(item.right for item in self.lanes if item.right is not None)

    def to_dict(self) -> dict[str, Any]:
        """Mathematics: serialize the exact typed operation identity and its bound fields."""
        return {
            "schema": "mailcpu.dataflow.add-frontier-request.v3",
            "plan_digest": self.plan_digest,
            "context_digest": self.context_digest,
            "frontier_index": self.frontier_index,
            "lanes": [item.to_dict() for item in self.lanes],
        }


class DataflowCompareFrontierRequest(DataflowAddFrontierRequest):
    """A content-bound batch of independent COMPARE nodes from one exact DAG frontier."""

    def to_dict(self) -> dict[str, Any]:
        """Mathematics: serialize the exact typed comparison frontier and its bound operands."""
        return {
            "schema": "mailcpu.dataflow.compare-frontier-request.v1",
            "plan_digest": self.plan_digest,
            "context_digest": self.context_digest,
            "frontier_index": self.frontier_index,
            "lanes": [item.to_dict() for item in self.lanes],
        }


@dataclass(frozen=True)
class DataflowAddFrontierReceipt:
    """Verified transport result retaining lane-to-node and route identities."""

    request_digest: str
    results: tuple[tuple[str, int], ...]
    host_id: str
    peer_id: str
    peer_path: tuple[str, ...]
    route_witness_digest: str
    forwarding_receipt_digest: str
    operator_effect_digest: str
    implementation_fingerprint: str
    backend_receipt_digest: str
    structural_memory_receipts: tuple[tuple[str, StructuralMemoryReadReceipt], ...] = ()

    def __post_init__(self) -> None:
        _digest(self.request_digest, "request_digest")
        results = tuple(self.results)
        if not results:
            raise OperationNativeDataflowError("frontier receipt requires at least one result lane")
        for node_id, value in results:
            if not isinstance(node_id, str) or _NODE_ID.fullmatch(node_id) is None:
                raise OperationNativeDataflowError("frontier result node identity is invalid")
            _bounded_add_integer(value, "frontier result value")
        if results != tuple(sorted(results, key=lambda item: item[0])):
            raise OperationNativeDataflowError("frontier result lanes must be sorted by node identity")
        if len({item[0] for item in results}) != len(results):
            raise OperationNativeDataflowError("frontier result node identities must be unique")
        object.__setattr__(self, "results", results)
        if not isinstance(self.host_id, str) or _HOST_ID.fullmatch(self.host_id) is None:
            raise OperationNativeDataflowError("target logical host identity is invalid")
        if not isinstance(self.peer_id, str) or _PEER_ID.fullmatch(self.peer_id) is None:
            raise OperationNativeDataflowError("target peer identity is invalid")
        path = tuple(self.peer_path)
        if len(path) < 2 or any(not isinstance(item, str) or _PEER_ID.fullmatch(item) is None for item in path):
            raise OperationNativeDataflowError("operation-native receipt must describe a remote peer path")
        if len(set(path)) != len(path) or path[-1] != self.peer_id:
            raise OperationNativeDataflowError("receipt peer path is cyclic or does not terminate at its target")
        object.__setattr__(self, "peer_path", path)
        for name in (
            "route_witness_digest",
            "forwarding_receipt_digest",
            "operator_effect_digest",
            "implementation_fingerprint",
            "backend_receipt_digest",
        ):
            _digest(getattr(self, name), name)
        memory_receipts = tuple(self.structural_memory_receipts)
        if memory_receipts != tuple(sorted(memory_receipts, key=lambda item: item[0])):
            raise OperationNativeDataflowError("Structural Memory receipts must be sorted by binding")
        if len({binding for binding, _ in memory_receipts}) != len(memory_receipts):
            raise OperationNativeDataflowError("Structural Memory receipt bindings must be unique")
        for binding, receipt in memory_receipts:
            if not isinstance(binding, str) or _LANE_MEMORY_BINDING.fullmatch(binding) is None:
                raise OperationNativeDataflowError("Structural Memory receipt binding is invalid")
            if not isinstance(receipt, StructuralMemoryReadReceipt):
                raise OperationNativeDataflowError("Structural Memory receipt must be a typed read receipt")
            expected_value_digest = canonical_value_digest({"type": "integer", "value": receipt.value})
            if receipt.value_digest != expected_value_digest:
                raise OperationNativeDataflowError("Structural Memory receipt value digest is inconsistent")
        object.__setattr__(self, "structural_memory_receipts", memory_receipts)

    @property
    def digest(self) -> str:
        """Mathematics: identify the canonical ordered frontier request or remote result."""
        return canonical_value_digest(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        """Mathematics: serialize the exact typed operation identity and its bound fields."""
        return {
            "schema": "mailcpu.dataflow.add-frontier-receipt.v3",
            "request_digest": self.request_digest,
            "results": [[node_id, value] for node_id, value in self.results],
            "host_id": self.host_id,
            "peer_id": self.peer_id,
            "peer_path": list(self.peer_path),
            "route_witness_digest": self.route_witness_digest,
            "forwarding_receipt_digest": self.forwarding_receipt_digest,
            "operator_effect_digest": self.operator_effect_digest,
            "implementation_fingerprint": self.implementation_fingerprint,
            "backend_receipt_digest": self.backend_receipt_digest,
            "structural_memory_receipts": [
                [binding, receipt.to_dict()]
                for binding, receipt in self.structural_memory_receipts
            ],
        }


class DataflowCompareFrontierReceipt(DataflowAddFrontierReceipt):
    """Verified transport result for a COMPARE frontier, retaining lane and route identities."""

    def to_dict(self) -> dict[str, Any]:
        """Mathematics: serialize comparison execution evidence under its distinct operation schema."""
        payload = super().to_dict()
        payload["schema"] = "mailcpu.dataflow.compare-frontier-receipt.v1"
        return payload


@dataclass(frozen=True)
class OperationNativeDataflowReport:
    """Local DAG result plus independently retained remote operation receipts."""

    execution: DataflowExecutionReport
    frontier_receipts: tuple[DataflowAddFrontierReceipt, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.execution, DataflowExecutionReport):
            raise OperationNativeDataflowError("execution must be a DataflowExecutionReport")
        receipts = tuple(self.frontier_receipts)
        if any(not isinstance(item, DataflowAddFrontierReceipt) for item in receipts):
            raise OperationNativeDataflowError("frontier_receipts must contain typed receipts")
        if len({item.request_digest for item in receipts}) != len(receipts):
            raise OperationNativeDataflowError("one execution cannot repeat an ADD frontier request identity")
        object.__setattr__(self, "frontier_receipts", receipts)

    def _payload(self) -> dict[str, Any]:
        """Mathematics: project the report fields that participate in its content digest."""
        return {
            "schema": "mailcpu.operation-native-dataflow-execution.v2",
            "execution": self.execution.to_dict(),
            "frontier_receipts": [item.to_dict() for item in self.frontier_receipts],
        }

    @property
    def digest(self) -> str:
        """Mathematics: bind the local execution and all route-bound remote frontier receipts."""
        return canonical_value_digest(self._payload())

    def to_dict(self) -> dict[str, Any]:
        """Mathematics: serialize the exact typed operation identity and its bound fields."""
        return {**self._payload(), "digest": self.digest}


def _contextual_orbit_predecessors(
    graph: NavigableComputationDAG,
    operand: Mapping[str, Any],
    node_id: str,
) -> tuple[ContextualOrbitDataflowInput, ...]:
    """Mathematics: collect compact, verified orbit provenance from the dependency's DAG ancestry."""
    if operand.get("kind") != "dependency":
        return ()
    dependency_id = operand.get("node_id")
    if not isinstance(dependency_id, str):
        raise OperationNativeDataflowError(f"node {node_id!r} has a malformed dependency operand")
    ancestor_ids = set(graph.lineage(dependency_id)) | {dependency_id}
    collected: dict[str, ContextualOrbitDataflowInput] = {}
    for ancestor_id in sorted(ancestor_ids):
        result = graph.result(ancestor_id)
        raw = result.get("contextual_orbit_input")
        if raw is None:
            continue
        if not isinstance(raw, Mapping):
            raise OperationNativeDataflowError(f"node {node_id!r} has malformed contextual-orbit predecessor evidence")
        try:
            predecessor = ContextualOrbitDataflowInput.from_dict(raw)
        except (TypeError, ValueError, KeyError) as exc:
            raise OperationNativeDataflowError(f"node {node_id!r} contextual-orbit predecessor failed verification: {exc}") from exc
        if (
            result.get("predecessor_digest") != predecessor.digest
            or result.get("value") != predecessor.value
            or result.get("selected_coordinate") != predecessor.selected_coordinate
            or result.get("selected_value") != predecessor.selected_value
            or result.get("receipt_digest") != predecessor.receipt.digest
        ):
            raise OperationNativeDataflowError(f"node {node_id!r} contextual-orbit predecessor result was altered")
        collected[predecessor.digest] = predecessor
    return tuple(collected[key] for key in sorted(collected))


def _operand_value(
    graph: NavigableComputationDAG,
    operand: Mapping[str, Any],
    node_id: str,
) -> int | VirtualStructuralMemoryRef:
    """Mathematics: resolve a literal/value/predecessor or preserve a pinned symbolic memory address without reading it."""
    kind = operand.get("kind")
    if kind in {"literal", "initial"}:
        value = operand.get("value")
    elif kind == "dependency":
        dependency_id = operand.get("node_id")
        if not isinstance(dependency_id, str):
            raise OperationNativeDataflowError(f"node {node_id!r} has a malformed dependency operand")
        dependency = graph.result(dependency_id)
        value = dependency.get("value")
    elif kind == "structural_memory":
        raw_reference = operand.get("reference")
        if not isinstance(raw_reference, Mapping):
            raise OperationNativeDataflowError(f"node {node_id!r} has a malformed symbolic Structural Memory operand")
        reference = VirtualStructuralMemoryRef.from_dict(raw_reference)
        if reference.binding != operand.get("register"):
            raise OperationNativeDataflowError(f"node {node_id!r} Structural Memory binding differs from its source register")
        return reference
    else:
        raise OperationNativeDataflowError(f"node {node_id!r} has an unsupported operand source")
    return _bounded_add_integer(value, f"operand for node {node_id}")


def _lane_operand(
    value: int | VirtualStructuralMemoryRef,
    *,
    node_id: str,
    side: str,
    source_register: Any,
) -> tuple[int | None, str | None, VirtualStructuralMemoryRef | None]:
    """Mathematics: map one compiled register operand into a stable inline or lane-bound symbolic reference."""
    if isinstance(value, VirtualStructuralMemoryRef):
        if not isinstance(source_register, str) or _REGISTER.fullmatch(source_register) is None:
            raise OperationNativeDataflowError("symbolic ADD operand is missing its source register")
        return None, source_register, _memory_reference_with_binding(value, f"{node_id}.{side}")
    return _bounded_add_integer(value, f"{side} ADD operand"), (
        source_register if isinstance(source_register, str) else None
    ), None


def _validate_memory_receipt_for_reference(
    reference: VirtualStructuralMemoryRef,
    receipt: StructuralMemoryReadReceipt,
) -> None:
    """Mathematics: require a receiver read receipt to match every pinned memory coordinate and evidence identity."""
    if (
        receipt.memory_id != reference.memory_id
        or receipt.revision != reference.revision
        or receipt.coordinate != reference.coordinate
        or receipt.spec_digest != reference.spec_digest
        or receipt.certificate_digest != reference.certificate_digest
        or receipt.context_digest != canonical_value_digest(dict(reference.context))
        or receipt.value_digest != canonical_value_digest({"type": "integer", "value": receipt.value})
    ):
        raise OperationNativeDataflowError("receiver Structural Memory receipt differs from the exact pinned reference")


def _materialize_frontier_operands(
    value: Mapping[str, Any],
) -> tuple[list[int], list[int], int]:
    """Mathematics: realize aligned lane operands from inline literals or receiver-authorized Structural Memory bindings."""
    if not isinstance(value, Mapping):
        raise OperationNativeDataflowError("ADD frontier input must be an object")
    if set(value) == {"input", "structural_memory"}:
        raw = value["input"]
        memory = value["structural_memory"]
    else:
        raw = value
        memory = {}
    if not isinstance(raw, Mapping) or set(raw) != {"lanes", "max_steps"}:
        raise OperationNativeDataflowError("ADD frontier input fields are invalid")
    if not isinstance(memory, Mapping):
        raise OperationNativeDataflowError("resolved Structural Memory input must be an object")
    lanes = raw["lanes"]
    if not isinstance(lanes, (list, tuple)) or not 1 <= len(lanes) <= _MAX_ADD_LANES:
        raise OperationNativeDataflowError(f"ADD frontier must contain 1..{_MAX_ADD_LANES} lanes")
    max_steps = raw["max_steps"]
    if type(max_steps) is not int or not 1 <= max_steps <= 10_000:
        raise OperationNativeDataflowError("ADD frontier max_steps is outside its bounded profile")

    left_values: list[int] = []
    right_values: list[int] = []
    used_memory_bindings: set[str] = set()
    for index, lane in enumerate(lanes):
        if not isinstance(lane, Mapping) or set(lane) != {"node_id", "left", "right"}:
            raise OperationNativeDataflowError(f"ADD frontier lane {index} has invalid fields")
        if not isinstance(lane["node_id"], str) or _NODE_ID.fullmatch(lane["node_id"]) is None:
            raise OperationNativeDataflowError(f"ADD frontier lane {index} has an invalid node identity")
        for side in ("left", "right"):
            operand = lane[side]
            if not isinstance(operand, Mapping):
                raise OperationNativeDataflowError(f"ADD frontier lane {index} {side} operand must be typed")
            if set(operand) == {"kind", "value"} and operand["kind"] == "inline":
                resolved = _bounded_add_integer(operand["value"], f"lane {index} {side} value")
            elif set(operand) == {"kind", "binding"} and operand["kind"] == "structural_memory":
                binding = operand["binding"]
                if not isinstance(binding, str) or not binding:
                    raise OperationNativeDataflowError(f"ADD frontier lane {index} {side} memory binding is invalid")
                used_memory_bindings.add(binding)
                entry = memory.get(binding)
                if not isinstance(entry, Mapping) or set(entry) != {"value", "receipt"}:
                    raise OperationNativeDataflowError(f"receiver did not resolve Structural Memory binding {binding!r}")
                receipt_payload = entry["receipt"]
                if not isinstance(receipt_payload, Mapping):
                    raise OperationNativeDataflowError(f"Structural Memory binding {binding!r} has no typed receipt")
                receipt = StructuralMemoryReadReceipt.from_dict(receipt_payload)
                resolved = _bounded_add_integer(entry["value"], f"Structural Memory value {binding}")
                if receipt.value != resolved:
                    raise OperationNativeDataflowError(f"Structural Memory binding {binding!r} value differs from its receipt")
            elif set(operand) == {"kind", "value", "inputs"} and operand["kind"] == "contextual_orbit":
                raw_inputs = operand["inputs"]
                if (
                    not isinstance(raw_inputs, (list, tuple))
                    or not raw_inputs
                    or len(raw_inputs) > _MAX_CONTEXTUAL_ORBIT_INPUTS
                ):
                    raise OperationNativeDataflowError(
                        f"ADD frontier lane {index} {side} contextual-orbit provenance is empty, malformed, or exceeds {_MAX_CONTEXTUAL_ORBIT_INPUTS} inputs"
                    )
                try:
                    predecessors = tuple(
                        ContextualOrbitDataflowInput.from_dict(item)
                        for item in raw_inputs
                        if isinstance(item, Mapping)
                    )
                except (TypeError, ValueError, KeyError) as exc:
                    raise OperationNativeDataflowError(f"ADD frontier lane {index} {side} contextual-orbit evidence failed verification: {exc}") from exc
                if len(predecessors) != len(raw_inputs) or predecessors != tuple(sorted(predecessors, key=lambda item: item.digest)):
                    raise OperationNativeDataflowError(f"ADD frontier lane {index} {side} contextual-orbit provenance ordering or shape is invalid")
                if len({item.digest for item in predecessors}) != len(predecessors):
                    raise OperationNativeDataflowError(f"ADD frontier lane {index} {side} contextual-orbit provenance is duplicated")
                resolved = _bounded_add_integer(operand["value"], f"contextual-orbit-derived value lane {index} {side}")
            else:
                raise OperationNativeDataflowError(f"ADD frontier lane {index} {side} operand descriptor is unsupported")
            (left_values if side == "left" else right_values).append(resolved)
    if used_memory_bindings != set(memory):
        raise OperationNativeDataflowError("resolved Structural Memory bindings differ from the lane operand descriptors")
    return left_values, right_values, max_steps


def execute_dataflow_operation_native(
    plan: CompiledMailCPUDataflow,
    dispatcher: Callable[[DataflowAddFrontierRequest], DataflowAddFrontierReceipt] | None = None,
    *,
    operation_dispatchers: Mapping[str, Callable[[Any], Any]] | None = None,
    max_work_units: int | None = None,
) -> OperationNativeDataflowReport:
    """Mathematics: evaluate a DAG while dispatching each ready ADD frontier as one semantic operation.

    SET, COPY, COMPARE, and HALT are evaluated locally in this first profile.
    ADD nodes in the same frontier are packed into ordered lanes. The returned
    values are checked against an independent scalar definition before any
    node in that frontier is committed.
    """
    if not isinstance(plan, CompiledMailCPUDataflow):
        raise OperationNativeDataflowError("plan must be a CompiledMailCPUDataflow")
    dispatchers: dict[str, Callable[[Any], Any]] = {}
    if dispatcher is not None:
        if not callable(dispatcher):
            raise OperationNativeDataflowError("dispatcher must be callable")
        dispatchers["ADD"] = dispatcher
    if operation_dispatchers is not None:
        if not isinstance(operation_dispatchers, Mapping):
            raise OperationNativeDataflowError("operation_dispatchers must be a mapping")
        for operation, operation_dispatcher in operation_dispatchers.items():
            if operation not in {"ADD", "COMPARE"} or not callable(operation_dispatcher):
                raise OperationNativeDataflowError("operation_dispatchers keys must be ADD or COMPARE with callable dispatchers")
            dispatchers[operation] = operation_dispatcher
    if not dispatchers:
        raise OperationNativeDataflowError("at least one operation-native dispatcher is required")
    limit = len(plan.nodes) if max_work_units is None else max_work_units
    if type(limit) is not int or limit < 1 or len(plan.nodes) > limit:
        raise OperationNativeDataflowError("compiled graph exceeds max_work_units")

    graph = plan.graph()
    node_by_id = {node.node_id: node for node in plan.nodes}
    receipts: list[DataflowAddFrontierReceipt] = []
    resolved_initial_registers: dict[str, int] = {}
    executed_frontiers: list[tuple[str, ...]] = []
    committed: list[str] = []

    for frontier_index, expected_frontier in enumerate(plan.frontiers):
        ready = tuple(node.node_id for node in graph.ready_nodes())
        if ready != expected_frontier:
            raise OperationNativeDataflowError("live DAG readiness differs from the compiled frontier")

        pending: dict[str, dict[str, Any]] = {}
        operation_lanes: dict[str, list[DataflowAddLane]] = {"ADD": [], "COMPARE": []}
        for node_id in expected_frontier:
            node = node_by_id[node_id]
            payload = node.payload
            opcode = payload.get("opcode")
            destination = payload.get("destination")
            if payload.get("kind") == "mailcpu.register-dataflow.contextual-orbit-input":
                register = payload.get("register")
                predecessor = dict(plan.contextual_orbit_inputs).get(register)
                if (
                    not isinstance(register, str)
                    or predecessor is None
                    or payload.get("source_digest") != predecessor.digest
                    or payload.get("field") != predecessor.field
                    or payload.get("request_digest") != predecessor.request.digest
                    or payload.get("receipt_digest") != predecessor.receipt.digest
                ):
                    raise OperationNativeDataflowError("contextual-orbit predecessor node differs from the compiled typed input")
                resolved_initial_registers[register] = predecessor.value
                pending[node_id] = {
                    "register": register,
                    "value": predecessor.value,
                    "contextual_orbit_input": predecessor.to_dict(),
                    "predecessor_digest": predecessor.digest,
                    "selected_coordinate": predecessor.selected_coordinate,
                    "selected_value": predecessor.selected_value,
                    "receipt_digest": predecessor.receipt.digest,
                }
                continue
            if opcode == Op.HALT.value:
                pending[node_id] = {
                    "status": RunStatus.HALTED.value,
                    "pc": payload["pc"],
                    "steps": payload["instruction_count"],
                    "halted": True,
                    "blocked": False,
                }
                continue

            operands = payload.get("operands")
            if not isinstance(operands, list):
                raise OperationNativeDataflowError(f"node {node_id!r} has no typed operand list")
            if opcode in {Op.ADD.value, Op.COMPARE.value}:
                operation = opcode
                if len(operands) != 2:
                    raise OperationNativeDataflowError(f"{operation} node {node_id!r} must have two operands")
                left_value = _operand_value(graph, operands[0], node_id)
                right_value = _operand_value(graph, operands[1], node_id)
                left_orbit_inputs = _contextual_orbit_predecessors(graph, operands[0], node_id)
                right_orbit_inputs = _contextual_orbit_predecessors(graph, operands[1], node_id)
                left, left_register, left_reference = _lane_operand(
                    left_value,
                    node_id=node_id,
                    side="left",
                    source_register=operands[0].get("register"),
                )
                right, right_register, right_reference = _lane_operand(
                    right_value,
                    node_id=node_id,
                    side="right",
                    source_register=operands[1].get("register"),
                )
                operation_lanes[operation].append(DataflowAddLane(
                    node_id=node_id,
                    node_digest=node.digest,
                    destination=destination,
                    left=left,
                    right=right,
                    left_register=left_register,
                    right_register=right_register,
                    left_reference=left_reference,
                    right_reference=right_reference,
                    left_orbit_inputs=left_orbit_inputs,
                    right_orbit_inputs=right_orbit_inputs,
                ))
                continue

            values = [_operand_value(graph, item, node_id) for item in operands]
            if any(isinstance(item, VirtualStructuralMemoryRef) for item in values):
                raise OperationNativeDataflowError(
                    f"symbolic Structural Memory operands are only admitted by ADD in this execution profile (node {node_id!r})"
                )
            if opcode in {Op.SET.value, Op.COPY.value}:
                if len(values) != 1:
                    raise OperationNativeDataflowError(f"{opcode} node {node_id!r} must have one operand")
                result_value = values[0]
            elif opcode == Op.COMPARE.value:
                if len(values) != 2:
                    raise OperationNativeDataflowError("COMPARE node must have two operands")
                result_value = compare_values(values[0], values[1])
            else:
                raise OperationNativeDataflowError(f"compiled opcode {opcode!r} is unsupported")

            if not isinstance(destination, str):
                raise OperationNativeDataflowError(f"node {node_id!r} has no destination register")
            pending[node_id] = {
                "register": destination,
                "value": _strict_integer(result_value, f"result for node {node_id}"),
            }

        for operation in ("ADD", "COMPARE"):
            lanes = operation_lanes[operation]
            if not lanes:
                continue
            operation_dispatcher = dispatchers.get(operation)
            if operation_dispatcher is None:
                raise OperationNativeDataflowError(f"no operation-native dispatcher is configured for {operation}")
            request_type = DataflowAddFrontierRequest if operation == "ADD" else DataflowCompareFrontierRequest
            receipt_type = DataflowAddFrontierReceipt if operation == "ADD" else DataflowCompareFrontierReceipt
            request = request_type(
                plan_digest=plan.digest,
                context_digest=plan.context_digest,
                frontier_index=frontier_index,
                lanes=tuple(sorted(lanes, key=lambda item: item.node_id)),
            )
            receipt = operation_dispatcher(request)
            if not isinstance(receipt, receipt_type):
                raise OperationNativeDataflowError(f"dispatcher did not return a typed {operation} frontier receipt")
            if receipt.request_digest != request.digest:
                raise OperationNativeDataflowError("remote receipt belongs to a different frontier request")
            expected_ids = tuple(item.node_id for item in request.lanes)
            actual_ids = tuple(item[0] for item in receipt.results)
            if actual_ids != expected_ids:
                raise OperationNativeDataflowError("remote result lane identities differ from the exact request ordering")

            returned = dict(receipt.results)
            expected_memory_references = {
                reference.binding: reference
                for lane in request.lanes
                for reference in (lane.left_reference, lane.right_reference)
                if reference is not None
            }
            received_memory_receipts = dict(receipt.structural_memory_receipts)
            if set(received_memory_receipts) != set(expected_memory_references):
                raise OperationNativeDataflowError(
                    "receiver Structural Memory receipt bindings differ from the exact frontier request"
                )
            for binding, reference in expected_memory_references.items():
                memory_receipt = received_memory_receipts[binding]
                _validate_memory_receipt_for_reference(reference, memory_receipt)
                matching_registers = {
                    lane.left_register
                    for lane in request.lanes
                    if lane.left_reference is not None and lane.left_reference.binding == binding
                } | {
                    lane.right_register
                    for lane in request.lanes
                    if lane.right_reference is not None and lane.right_reference.binding == binding
                }
                if len(matching_registers) != 1:
                    raise OperationNativeDataflowError("Structural Memory binding does not identify exactly one source register")
                source_register = next(iter(matching_registers))
                previous_value = resolved_initial_registers.get(source_register)
                if previous_value is not None and previous_value != memory_receipt.value:
                    raise OperationNativeDataflowError("one symbolic Structural Memory register resolved inconsistently across frontiers")
                resolved_initial_registers[source_register] = memory_receipt.value

            for lane in request.lanes:
                # The independent scalar oracle consumes receiver-resolved values
                # only after checking their exact pinned memory identities.
                left_value = lane.left
                if lane.left_reference is not None:
                    left_value = received_memory_receipts[lane.left_reference.binding].value
                right_value = lane.right
                if lane.right_reference is not None:
                    right_value = received_memory_receipts[lane.right_reference.binding].value
                left_integer = _bounded_add_integer(left_value, f"left operand for {lane.node_id}")
                right_integer = _bounded_add_integer(right_value, f"right operand for {lane.node_id}")
                expected_value = (
                    _bounded_add_integer(left_integer + right_integer, f"ADD result for {lane.node_id}")
                    if operation == "ADD"
                    else compare_values(left_integer, right_integer)
                )
                if returned[lane.node_id] != expected_value:
                    raise OperationNativeDataflowError(
                        f"remote {operation} result for {lane.node_id!r} failed the independent scalar oracle"
                    )
                pending[lane.node_id] = {
                    "register": lane.destination,
                    "value": expected_value,
                    "operation": operation,
                    "operator_id": receipt.to_dict().get("operator_id", f"mailcpu.dataflow.{operation.lower()}_frontier"),
                    "frontier_request_digest": request.digest,
                    "operation_receipt": receipt.to_dict(),
                    "operation_receipt_digest": receipt.digest,
                }
            receipts.append(receipt)

        # The frontier is published only after every remote lane has passed
        # identity, cardinality, type and independent semantic checks.
        for node_id in expected_frontier:
            result = pending.get(node_id)
            if result is None:
                raise OperationNativeDataflowError(f"frontier node {node_id!r} has no prepared result")
            try:
                graph.commit(node_id, result)
            except ComputationDAGError as exc:
                raise OperationNativeDataflowError(f"could not commit verified node {node_id!r}: {exc}") from exc
            committed.append(node_id)
        executed_frontiers.append(expected_frontier)

    halt_nodes = [item for item in plan.nodes if item.payload.get("opcode") == Op.HALT.value]
    if len(halt_nodes) != 1:
        raise OperationNativeDataflowError("compiled plan must have exactly one terminal HALT node")
    halt = graph.result(halt_nodes[0].node_id)
    if halt.get("status") != RunStatus.HALTED.value:
        raise OperationNativeDataflowError("terminal node did not commit a HALTED result")

    registers: dict[str, int] = {}
    for source in plan.final_register_sources:
        if source.kind == "initial":
            value = source.value
        elif source.kind == "structural_memory":
            value = resolved_initial_registers.get(source.register)
        else:
            value = graph.result(source.node_id or "").get("value")
        registers[source.register] = _strict_integer(value, f"final register {source.register}")

    snapshot_json = __import__("json").dumps(
        graph.snapshot(),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    report = DataflowExecutionReport(
        plan_digest=plan.digest,
        status=RunStatus.HALTED.value,
        pc=halt["pc"],
        steps=halt["steps"],
        halted=True,
        blocked=False,
        registers=tuple(sorted(registers.items())),
        committed_node_ids=tuple(committed),
        executed_frontiers=tuple(executed_frontiers),
        _dag_snapshot_json=snapshot_json,
        resolved_initial_registers=tuple(sorted(resolved_initial_registers.items())),
    )
    return OperationNativeDataflowReport(report, tuple(receipts))


def dataflow_compare_operator_spec() -> OperatorSpec:
    """Mathematics: define a strict integer sign-comparison contract for CPU and E-GPU realizations."""
    return OperatorSpec(
        operator_id="mailcpu.dataflow.compare_frontier",
        version=1,
        description="Apply sign(left-right) to 1..64 aligned strict-integer lanes bounded to 4096 bits; verify typed contextual-orbit predecessors at the receiver",
        input_kind="object",
        output_kind="object",
        substrates=("cpu", "gpu"),
        required_rights=frozenset({"compute"}),
        base_energy=16,
        energy_per_byte=2,
        max_input_bytes=262_144,
        max_output_bytes=262_144,
        deterministic=True,
        effect_mode="pure",
    )


def make_cpu_dataflow_compare_handler() -> Callable[[Mapping[str, Any], VirtualLayerWorkload], dict[str, Any]]:
    """Mathematics: construct the CPU realization of the common sign-comparison Ground."""
    def execute(value: Mapping[str, Any], _workload: VirtualLayerWorkload) -> dict[str, Any]:
        """Mathematics: map aligned strict integer pairs through MailCPU compare_values."""
        left, right, _max_steps = _materialize_frontier_operands(value)
        outputs = [compare_values(a, b) for a, b in zip(left, right)]
        backend = {
            "implementation": "mailcpu.cpu.strict-integer-vector-compare.v1",
            "values": outputs,
        }
        return {
            "values": outputs,
            "backend_method": "cpu.vector.compare",
            "backend_receipt_digest": canonical_value_digest(backend),
        }
    return execute


def make_egpu_dataflow_compare_handler(egpu_host: Any) -> Callable[[Mapping[str, Any], VirtualLayerWorkload], dict[str, Any]]:
    """Mathematics: bind the sign-comparison Ground to a bounded receiver-local E-GPU SIMT kernel."""
    from .egpu import EGPUHost

    if not isinstance(egpu_host, EGPUHost):
        raise OperationNativeDataflowError("E-GPU COMPARE handler requires an EGPUHost instance")
    if (
        egpu_host.simt_host.max_lanes < _MAX_ADD_LANES
        or egpu_host.simt_host.max_integer_bits < _MAX_ADD_INTEGER_BITS
    ):
        raise OperationNativeDataflowError(
            "E-GPU host does not implement the full shared 64-lane/4096-bit COMPARE domain"
        )

    program = [
        ["load", "a", "left"],
        ["load", "b", "right"],
        ["lt", "less", "a", "b"],
        ["lt", "greater", "b", "a"],
        ["const", "zero", 0],
        ["const", "negative", -1],
        ["const", "positive", 1],
        ["copy", "result", "zero"],
        ["if", "less"],
        ["copy", "result", "negative"],
        ["endif"],
        ["if", "greater"],
        ["copy", "result", "positive"],
        ["endif"],
        ["store", "result", "result"],
        ["halt"],
    ]

    def execute(value: Mapping[str, Any], _workload: VirtualLayerWorkload) -> dict[str, Any]:
        """Mathematics: compute sign(a-b) through the existing E-GPU SIMT kernel and check its scalar projection."""
        left, right, _max_steps = _materialize_frontier_operands(value)
        result = egpu_host.execute_authorized_method(
            "simt.kernel",
            {
                "method": "simt.kernel",
                "lanes": len(left),
                "inputs": {"left": left, "right": right},
                "program": program,
                "max_steps": 32,
            },
        )
        values = result["result"]["outputs"]["result"]
        expected = [compare_values(a, b) for a, b in zip(left, right)]
        if not isinstance(values, list) or values != expected:
            raise OperationNativeDataflowError("E-GPU COMPARE kernel failed its independent scalar reference check")
        backend = {
            "values": values,
            "egpu_host_id": result["host_id"],
            "egpu_receipt_digest": result["receipt_digest"],
        }
        return {
            "values": values,
            "backend_method": "egpu.simt.compare",
            "backend_receipt_digest": result["receipt_digest"],
            "backend_host_id": result["host_id"],
        }
    return execute


def dataflow_add_operator_spec() -> OperatorSpec:
    """Mathematics: define one strict integer vector-add contract for CPU and E-GPU realizations."""
    return OperatorSpec(
        operator_id="mailcpu.dataflow.add_frontier",
        version=3,
        description="Apply strict integer addition to 1..64 aligned lanes with signed operands and results bounded to 4096 bits; resolve pinned Structural Memory operands and verify contextual-orbit predecessor inputs at the receiver",
        input_kind="object",
        output_kind="object",
        substrates=("cpu", "gpu"),
        required_rights=frozenset({"compute"}),
        base_energy=16,
        energy_per_byte=2,
        max_input_bytes=262_144,
        max_output_bytes=262_144,
        deterministic=True,
        effect_mode="pure",
    )


def make_cpu_dataflow_add_handler() -> Callable[[Mapping[str, Any], VirtualLayerWorkload], dict[str, Any]]:
    """Mathematics: construct the CPU realization of the common vector-add Ground."""
    def execute(value: Mapping[str, Any], _workload: VirtualLayerWorkload) -> dict[str, Any]:
        """Mathematics: map aligned strict integer pairs through the local CPU addition law."""
        left, right, _max_steps = _materialize_frontier_operands(value)
        outputs = []
        for index, (a, b) in enumerate(zip(left, right)):
            outputs.append(_bounded_add_integer(a + b, f"CPU ADD result[{index}]"))
        backend = {
            "implementation": "mailcpu.cpu.strict-integer-vector-add.v1",
            "values": outputs,
        }
        return {
            "values": outputs,
            "backend_method": "cpu.vector.add",
            "backend_receipt_digest": canonical_value_digest(backend),
        }
    return execute


def make_egpu_dataflow_add_handler(egpu_host: Any) -> Callable[[Mapping[str, Any], VirtualLayerWorkload], dict[str, Any]]:
    """Mathematics: bind the common vector-add Ground to one trusted local EGPUHost instance."""
    from .egpu import EGPUHost

    if not isinstance(egpu_host, EGPUHost):
        raise OperationNativeDataflowError("E-GPU ADD handler requires an EGPUHost instance")
    if (
        egpu_host.simt_host.max_lanes < _MAX_ADD_LANES
        or egpu_host.simt_host.max_integer_bits < _MAX_ADD_INTEGER_BITS
    ):
        raise OperationNativeDataflowError(
            "E-GPU host does not implement the full shared 64-lane/4096-bit ADD domain"
        )

    def execute(value: Mapping[str, Any], _workload: VirtualLayerWorkload) -> dict[str, Any]:
        """Mathematics: realize the ordered vector-add observation through the local E-GPU method graph."""
        left, right, max_steps = _materialize_frontier_operands(value)
        result = egpu_host.execute_authorized_method(
            "vector.add",
            {
                "method": "vector.add",
                "left": left,
                "right": right,
                "max_steps": max_steps,
            },
        )
        values = result["result"]["outputs"]["result"]
        if not isinstance(values, list) or len(values) != len(left):
            raise OperationNativeDataflowError("E-GPU returned a result vector outside the shared ADD shape")
        values = [
            _bounded_add_integer(item, f"E-GPU ADD result[{index}]")
            for index, item in enumerate(values)
        ]
        backend = {
            "values": values,
            "egpu_host_id": result["host_id"],
            "egpu_receipt_digest": result["receipt_digest"],
        }
        return {
            "values": values,
            "backend_method": "egpu.vector.add",
            "backend_receipt_digest": result["receipt_digest"],
            "backend_host_id": result["host_id"],
        }
    return execute


class ComputationalFabricDataflowAddDispatcher:
    """Turn one ADD frontier into a typed Virtual Layer workload and a multi-hop operation request."""

    def __init__(
        self,
        *,
        origin_peer_id: str,
        directory: Any,
        forwarding_clients: Mapping[str, ComputationalFabricForwardingClient],
        system: SystemIdentity,
        ground: VirtualGroundRef,
        operator_spec: OperatorSpec,
        computational_ground_fingerprint: str,
        budget: VirtualBudget,
        eligible_nodes_by_frontier: Mapping[int, Sequence[str]] | Callable[[DataflowAddFrontierRequest], Sequence[str]],
        origin_channel: str,
        first_sequence: int,
        logical_time: int = 0,
        max_hops: int = 8,
        metric_order: Sequence[RouteMetricKey],
        max_steps: int = 64,
    ) -> None:
        from .computational_fabric import ComputationalFabricDirectory

        if not isinstance(directory, ComputationalFabricDirectory):
            raise OperationNativeDataflowError("dispatcher requires a ComputationalFabricDirectory")
        if directory.local_peer_id != origin_peer_id:
            raise OperationNativeDataflowError("origin peer must own the supplied fabric directory")
        if not forwarding_clients:
            raise OperationNativeDataflowError("dispatcher requires at least one authenticated next-hop client")
        clients = dict(forwarding_clients)
        if any(
            not isinstance(client, ComputationalFabricForwardingClient)
            or peer_id != client.remote_endpoint.peer_id
            or client.local_peer_id != origin_peer_id
            or client.origin_channel != origin_channel
            for peer_id, client in clients.items()
        ):
            raise OperationNativeDataflowError("forwarding clients are not bound to this origin/channel")
        if not isinstance(system, SystemIdentity) or not isinstance(ground, VirtualGroundRef):
            raise OperationNativeDataflowError("dispatcher requires typed System and Virtual Grounds")
        if not isinstance(operator_spec, OperatorSpec) or not operator_spec.replay_safe:
            raise OperationNativeDataflowError("dispatcher requires a deterministic pure OperatorSpec")
        if operator_spec.operator_id != "mailcpu.dataflow.add_frontier" or operator_spec.version != 3:
            raise OperationNativeDataflowError("dispatcher operator contract is not the dataflow ADD frontier contract")
        _digest(computational_ground_fingerprint, "computational_ground_fingerprint")
        if not isinstance(budget, VirtualBudget):
            raise OperationNativeDataflowError("dispatcher requires a VirtualBudget")
        if not isinstance(origin_channel, str) or not origin_channel.strip():
            raise OperationNativeDataflowError("origin_channel must be non-empty")
        if type(first_sequence) is not int or first_sequence < 1:
            raise OperationNativeDataflowError("first_sequence must be a positive strict integer")
        if type(logical_time) is not int or logical_time < 0:
            raise OperationNativeDataflowError("logical_time must be a non-negative strict integer")
        if type(max_hops) is not int or max_hops < 1:
            raise OperationNativeDataflowError("max_hops must be a positive strict integer")
        if type(max_steps) is not int or not 1 <= max_steps <= 10_000:
            raise OperationNativeDataflowError("max_steps is outside the bounded E-GPU method range")
        metrics = tuple(metric_order)
        if not metrics or any(not isinstance(item, RouteMetricKey) for item in metrics):
            raise OperationNativeDataflowError("metric_order must contain RouteMetricKey values")
        self.origin_peer_id = origin_peer_id
        self.directory = directory
        self.forwarding_clients = clients
        self.system = system
        self.ground = ground
        self.operator_spec = operator_spec
        self.computational_ground_fingerprint = computational_ground_fingerprint
        self.budget = budget
        self.eligible_nodes_by_frontier = eligible_nodes_by_frontier
        self.origin_channel = origin_channel
        self.first_sequence = first_sequence
        self.logical_time = logical_time
        self.max_hops = max_hops
        self.metric_order = metrics
        self.max_steps = max_steps

    def __call__(self, request: DataflowAddFrontierRequest) -> DataflowAddFrontierReceipt:
        from .computational_fabric import ComputationalFabricStatus
        from .virtual_layer import VirtualOperatorRef

        if not isinstance(request, DataflowAddFrontierRequest):
            raise OperationNativeDataflowError("dispatcher requires a DataflowAddFrontierRequest")
        if callable(self.eligible_nodes_by_frontier):
            eligible_nodes = tuple(self.eligible_nodes_by_frontier(request))
        else:
            eligible_nodes = tuple(self.eligible_nodes_by_frontier.get(request.frontier_index, ()))
        if not eligible_nodes or any(not isinstance(item, str) or not item for item in eligible_nodes):
            raise OperationNativeDataflowError("frontier has no declared eligible execution node")

        structural_references: dict[str, VirtualStructuralMemoryRef] = {}
        wire_lanes: list[dict[str, Any]] = []
        for lane in request.lanes:
            wire_lane: dict[str, Any] = {"node_id": lane.node_id}
            for side in ("left", "right"):
                reference = getattr(lane, f"{side}_reference")
                operand_value = getattr(lane, side)
                if reference is not None:
                    if reference.binding in structural_references:
                        raise OperationNativeDataflowError("frontier Structural Memory binding identities must be unique")
                    structural_references[reference.binding] = reference
                    wire_lane[side] = {"kind": "structural_memory", "binding": reference.binding}
                else:
                    orbit_inputs = getattr(lane, f"{side}_orbit_inputs")
                    if orbit_inputs:
                        wire_lane[side] = {
                            "kind": "contextual_orbit",
                            "value": _bounded_add_integer(operand_value, f"{lane.node_id} {side} operand"),
                            "inputs": [item.to_dict() for item in orbit_inputs],
                        }
                    else:
                        wire_lane[side] = {"kind": "inline", "value": _bounded_add_integer(operand_value, f"{lane.node_id} {side} operand")}
            wire_lanes.append(wire_lane)
        input_value = {"lanes": wire_lanes, "max_steps": self.max_steps}
        operator_reference = VirtualOperatorRef(
            self.operator_spec.operator_id,
            self.operator_spec.version,
            structural_memory=tuple(structural_references[key] for key in sorted(structural_references)),
        )
        workload_id = f"dataflow-add-{request.plan_digest[:12]}-{request.frontier_index:04d}"
        workload = VirtualLayerWorkload(
            workload_id=workload_id,
            system=self.system,
            ground=self.ground,
            intention={
                "goal": {
                    "kind": "mailcpu.dataflow.add_frontier",
                    "plan_digest": request.plan_digest,
                    "context_digest": request.context_digest,
                    "request_digest": request.digest,
                    "frontier_index": request.frontier_index,
                    "lanes": [item.to_dict() for item in request.lanes],
                }
            },
            operators=(operator_reference,),
            input_value=input_value,
            budget=self.budget,
            logical_time=self.logical_time + request.frontier_index,
            eligible_nodes=eligible_nodes,
            max_hops=self.max_hops,
            schema_version=2 if structural_references else 1,
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
            raise OperationNativeDataflowError(
                f"fabric could not resolve ADD frontier to an eligible host: {planned.status.value}: {details}"
            )
        route = planned.witness
        if len(route.peer_path) < 2:
            raise OperationNativeDataflowError("operation-native dispatcher expected a remote host, not local execution")
        if route.target_host.implementation_fingerprint is None:
            raise OperationNativeDataflowError("target host has no pinned implementation fingerprint")
        next_peer = route.peer_path[1]
        client = self.forwarding_clients.get(next_peer)
        if client is None:
            raise OperationNativeDataflowError(f"no authenticated forwarding client is configured for first hop {next_peer!r}")

        envelope = ComputationalFabricForwardingEnvelope.begin(
            address,
            route,
            origin_channel=self.origin_channel,
            origin_sequence=self.first_sequence + request.frontier_index,
        )
        hop_receipt = client.forward(envelope, self.directory)
        if not isinstance(hop_receipt, ComputationalFabricHopReceipt) or not hop_receipt.succeeded:
            raise OperationNativeDataflowError("fabric forwarding did not commit a successful terminal execution")
        if hop_receipt.operation_digest != envelope.operation_digest:
            raise OperationNativeDataflowError("forwarding receipt belongs to a different semantic operation")
        terminal = hop_receipt
        while terminal.next_peer_id is not None:
            if terminal.downstream is None:
                raise OperationNativeDataflowError("forwarding receipt has an incomplete downstream chain")
            terminal = terminal.downstream
        if terminal.peer_id != route.peer_path[-1] or not isinstance(terminal.terminal_execution, Mapping):
            raise OperationNativeDataflowError("forwarding receipt does not terminate at the selected host peer")

        terminal_execution = terminal.terminal_execution
        if (
            terminal_execution.get("accepted") is not True
            or terminal_execution.get("executed") is not True
            or terminal_execution.get("status") not in {"executed", "replayed"}
            or not isinstance(terminal_execution.get("execution"), Mapping)
        ):
            raise OperationNativeDataflowError("terminal peer did not return an accepted Hypervisor execution")
        execution = terminal_execution["execution"]
        if execution.get("action") != "allow" or not isinstance(execution.get("effect"), Mapping):
            raise OperationNativeDataflowError("terminal operation is missing its local Hypervisor ALLOW effect")
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
            raise OperationNativeDataflowError("terminal operator effect does not bind the addressed workload and contract")
        operator_result = effect["result"]
        if canonical_value_digest(operator_result) != effect.get("result_digest"):
            raise OperationNativeDataflowError("terminal operator result digest is inconsistent")
        values = operator_result.get("values")
        if not isinstance(values, list) or len(values) != len(request.lanes):
            raise OperationNativeDataflowError("terminal operator returned the wrong number of ADD lanes")
        results = tuple(
            (lane.node_id, _strict_integer(value, f"remote result for {lane.node_id}"))
            for lane, value in zip(request.lanes, values)
        )
        backend_receipt = operator_result.get("backend_receipt_digest")
        _digest(backend_receipt, "backend_receipt_digest")
        raw_memory_receipts = effect.get("structural_memory_receipts", {})
        if not isinstance(raw_memory_receipts, Mapping):
            raise OperationNativeDataflowError("terminal Structural Memory receipts must be an object")
        expected_bindings = set(structural_references)
        if set(raw_memory_receipts) != expected_bindings:
            raise OperationNativeDataflowError("terminal Structural Memory receipt bindings differ from requested references")
        memory_receipts: list[tuple[str, StructuralMemoryReadReceipt]] = []
        for binding in sorted(expected_bindings):
            payload = raw_memory_receipts[binding]
            if not isinstance(payload, Mapping):
                raise OperationNativeDataflowError(f"terminal Structural Memory receipt {binding!r} is malformed")
            memory_receipt = StructuralMemoryReadReceipt.from_dict(payload)
            _validate_memory_receipt_for_reference(structural_references[binding], memory_receipt)
            memory_receipts.append((binding, memory_receipt))

        return DataflowAddFrontierReceipt(
            request_digest=request.digest,
            results=results,
            host_id=route.target_host.host_id,
            peer_id=route.target_host.peer_id,
            peer_path=route.peer_path,
            route_witness_digest=route.digest,
            forwarding_receipt_digest=hop_receipt.digest,
            operator_effect_digest=effect["result_digest"],
            implementation_fingerprint=route.target_host.implementation_fingerprint,
            backend_receipt_digest=backend_receipt,
            structural_memory_receipts=tuple(memory_receipts),
        )


__all__ = [
    "ComputationalFabricDataflowAddDispatcher",
    "DataflowAddFrontierReceipt",
    "DataflowAddFrontierRequest",
    "DataflowAddLane",
    "OperationNativeDataflowError",
    "OperationNativeDataflowReport",
    "dataflow_add_operator_spec",
    "execute_dataflow_operation_native",
    "make_cpu_dataflow_add_handler",
    "make_egpu_dataflow_add_handler",
]
