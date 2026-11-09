"""Deterministic, evidence-bound partition descriptions for binary DAG frontiers.

This module describes how one homogeneous binary operation frontier can be
split into child requests and proposed to distinct fabric destinations. It
does not dispatch work or grant execution authority.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from typing import Any, Mapping, Sequence

from .computational_fabric import ComputationalFabricRouteWitness
from .orbit_fabric import ContextualOrbitDataflowInput
from .program_dataflow_fabric import (
    DataflowAddFrontierRequest,
    DataflowBinaryLane,
    DataflowCompareFrontierRequest,
    DataflowMultiplyFrontierRequest,
    dataflow_add_operator_spec,
    dataflow_compare_operator_spec,
    dataflow_multiply_operator_spec,
)
from .virtual_layer import VirtualStructuralMemoryRef

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_MAX_PARTITIONS = 64
_REQUEST_TYPES = {
    "mailcpu.dataflow.add-frontier-request.v3": (DataflowAddFrontierRequest, "ADD"),
    "mailcpu.dataflow.compare-frontier-request.v1": (DataflowCompareFrontierRequest, "COMPARE"),
    "mailcpu.dataflow.multiply-frontier-request.v1": (DataflowMultiplyFrontierRequest, "MUL"),
}
_REQUEST_SCHEMAS = {
    DataflowAddFrontierRequest: "mailcpu.dataflow.add-frontier-request.v3",
    DataflowCompareFrontierRequest: "mailcpu.dataflow.compare-frontier-request.v1",
    DataflowMultiplyFrontierRequest: "mailcpu.dataflow.multiply-frontier-request.v1",
}
_OPERATOR_SPECS = {
    "ADD": dataflow_add_operator_spec,
    "COMPARE": dataflow_compare_operator_spec,
    "MUL": dataflow_multiply_operator_spec,
}


class FrontierPartitionError(ValueError):
    """A frontier partition, child request, or proposed route is malformed or inconsistent."""


def _digest(value: Any, label: str) -> str:
    """Mathematics: admit only one lowercase SHA-256 content identity."""
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise FrontierPartitionError(f"{label} must be lowercase SHA-256 hex")
    return value


def _canonical(value: Any) -> bytes:
    """Mathematics: define canonical partition encoding J(x)=UTF8(JSON_sort_keys(x))."""
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise FrontierPartitionError("partition description is not canonical finite JSON") from exc


def _canonical_digest(value: Any) -> str:
    """Mathematics: identify canonical JSON content by SHA256(J(x))."""
    return hashlib.sha256(_canonical(value)).hexdigest()


def _lane_from_dict(payload: Mapping[str, Any]) -> DataflowBinaryLane:
    """Mathematics: restore one scalar/symbolic lane and all typed predecessor evidence."""
    expected = {
        "node_id", "node_digest", "destination", "left", "right",
        "left_register", "right_register", "left_reference", "right_reference",
        "left_orbit_inputs", "right_orbit_inputs",
    }
    if not isinstance(payload, Mapping) or set(payload) != expected:
        raise FrontierPartitionError("binary lane fields are malformed")
    for side in ("left", "right"):
        raw_reference = payload[f"{side}_reference"]
        if raw_reference is not None and not isinstance(raw_reference, Mapping):
            raise FrontierPartitionError(f"binary lane {side} reference is malformed")
        raw_orbit = payload[f"{side}_orbit_inputs"]
        if not isinstance(raw_orbit, list):
            raise FrontierPartitionError(f"binary lane {side} orbit inputs are malformed")
    try:
        return DataflowBinaryLane(
            node_id=payload["node_id"],
            node_digest=payload["node_digest"],
            destination=payload["destination"],
            left=payload["left"],
            right=payload["right"],
            left_register=payload["left_register"],
            right_register=payload["right_register"],
            left_reference=(
                None if payload["left_reference"] is None
                else VirtualStructuralMemoryRef.from_dict(payload["left_reference"])
            ),
            right_reference=(
                None if payload["right_reference"] is None
                else VirtualStructuralMemoryRef.from_dict(payload["right_reference"])
            ),
            left_orbit_inputs=tuple(
                ContextualOrbitDataflowInput.from_dict(item)
                for item in payload["left_orbit_inputs"]
            ),
            right_orbit_inputs=tuple(
                ContextualOrbitDataflowInput.from_dict(item)
                for item in payload["right_orbit_inputs"]
            ),
        )
    except (KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, FrontierPartitionError):
            raise
        raise FrontierPartitionError("binary lane contains invalid typed operands or provenance") from exc


def _request_from_dict(payload: Mapping[str, Any]) -> DataflowAddFrontierRequest:
    """Mathematics: restore one exact typed ADD/COMPARE/MUL child request and its ordered lane identities."""
    expected = {"schema", "plan_digest", "context_digest", "frontier_index", "lanes"}
    if not isinstance(payload, Mapping) or set(payload) != expected:
        raise FrontierPartitionError("partition child request fields are malformed")
    entry = _REQUEST_TYPES.get(payload["schema"])
    if entry is None:
        raise FrontierPartitionError("partition child request schema is unsupported")
    request_type, _operation = entry
    if not isinstance(payload["lanes"], list):
        raise FrontierPartitionError("partition child request lanes must be a list")
    try:
        return request_type(
            plan_digest=payload["plan_digest"],
            context_digest=payload["context_digest"],
            frontier_index=payload["frontier_index"],
            lanes=tuple(_lane_from_dict(item) for item in payload["lanes"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, FrontierPartitionError):
            raise
        raise FrontierPartitionError("partition child request contains invalid lane values") from exc


@dataclass(frozen=True)
class BinaryFrontierPartition:
    """One homogeneous child request paired with one exact non-authoritative fabric route proposal."""

    request: DataflowAddFrontierRequest
    route_witness: ComputationalFabricRouteWitness

    def __post_init__(self) -> None:
        """Mathematics: bind one typed request to a remote route advertising the exact operator and implementation."""
        operation = next(
            (name for request_type, name in (
                (DataflowAddFrontierRequest, "ADD"),
                (DataflowCompareFrontierRequest, "COMPARE"),
                (DataflowMultiplyFrontierRequest, "MUL"),
            ) if type(self.request) is request_type),
            None,
        )
        if operation is None:
            raise FrontierPartitionError("partition request must be an exact typed ADD, COMPARE, or MUL request")
        if not isinstance(self.route_witness, ComputationalFabricRouteWitness):
            raise FrontierPartitionError("partition requires a typed ComputationalFabricRouteWitness")
        if len(self.route_witness.peer_path) < 2:
            raise FrontierPartitionError("partition route must identify a remote execution path")
        expected_spec = _OPERATOR_SPECS[operation]()
        host = self.route_witness.target_host
        if host.operator_spec.digest != expected_spec.digest:
            raise FrontierPartitionError("partition route host does not advertise the exact operation contract")
        if host.implementation_fingerprint is None:
            raise FrontierPartitionError("partition route host has no pinned implementation fingerprint")
        if not host.computational_ground_fingerprints:
            raise FrontierPartitionError("partition route host has no declared Computational Ground support")

    @property
    def operation(self) -> str:
        """Mathematics: derive the semantic operator family from the exact typed child-request class."""
        for request_type, operation in (
            (DataflowAddFrontierRequest, "ADD"),
            (DataflowCompareFrontierRequest, "COMPARE"),
            (DataflowMultiplyFrontierRequest, "MUL"),
        ):
            if type(self.request) is request_type:
                return operation
        raise FrontierPartitionError("partition request type is unsupported")

    @property
    def node_ids(self) -> tuple[str, ...]:
        """Mathematics: project the stable sorted original DAG node identities assigned to this child."""
        return tuple(item.node_id for item in self.request.lanes)

    @property
    def digest(self) -> str:
        """Mathematics: identify the exact child request and route proposal pair."""
        return _canonical_digest(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        """Mathematics: serialize full child lane/provenance and the complete non-authoritative route witness."""
        return {
            "schema": "mailcpu.binary-frontier-partition.v1",
            "operation": self.operation,
            "request": self.request.to_dict(),
            "route_witness": self.route_witness.to_dict(),
            "digest": self.digest,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "BinaryFrontierPartition":
        """Mathematics: restore a child partition only when its typed request, route and enclosing digest agree."""
        expected = {"schema", "operation", "request", "route_witness", "digest"}
        if not isinstance(payload, Mapping) or set(payload) != expected:
            raise FrontierPartitionError("binary frontier partition fields are malformed")
        if (
            payload["schema"] != "mailcpu.binary-frontier-partition.v1"
            or not isinstance(payload["request"], Mapping)
            or not isinstance(payload["route_witness"], Mapping)
        ):
            raise FrontierPartitionError("binary frontier partition schema or nested values are invalid")
        try:
            partition = cls(
                request=_request_from_dict(payload["request"]),
                route_witness=ComputationalFabricRouteWitness.from_dict(payload["route_witness"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            if isinstance(exc, FrontierPartitionError):
                raise
            raise FrontierPartitionError("binary frontier partition contains invalid nested values") from exc
        if payload["operation"] != partition.operation or payload["digest"] != partition.digest:
            raise FrontierPartitionError("binary frontier partition operation or digest differs from its contents")
        return partition


@dataclass(frozen=True)
class BinaryFrontierPartitionPlan:
    """Complete deterministic split of one homogeneous binary frontier across multiple proposed hosts."""

    plan_digest: str
    context_digest: str
    frontier_index: int
    operation: str
    computational_ground_fingerprint: str
    origin_peer_id: str
    directory_digest: str
    topology_digest: str
    frontier_node_ids: tuple[str, ...]
    partitions: tuple[BinaryFrontierPartition, ...]

    def __post_init__(self) -> None:
        """Mathematics: require a disjoint exact cover of one operation frontier across at least two remote logical hosts."""
        for name in (
            "plan_digest", "context_digest", "computational_ground_fingerprint",
            "directory_digest", "topology_digest",
        ):
            _digest(getattr(self, name), name)
        if type(self.frontier_index) is not int or self.frontier_index < 0:
            raise FrontierPartitionError("frontier_index must be a non-negative strict integer")
        if self.operation not in _OPERATOR_SPECS:
            raise FrontierPartitionError("partition plan operation must be ADD, COMPARE, or MUL")
        if not isinstance(self.origin_peer_id, str) or not self.origin_peer_id:
            raise FrontierPartitionError("origin_peer_id must be non-empty")
        node_ids = tuple(self.frontier_node_ids)
        if (
            not node_ids
            or any(not isinstance(item, str) or not item for item in node_ids)
            or len(node_ids) != len(set(node_ids))
            or node_ids != tuple(sorted(node_ids))
        ):
            raise FrontierPartitionError("frontier_node_ids must be non-empty, unique and stably sorted")
        partitions = tuple(self.partitions)
        if not 2 <= len(partitions) <= _MAX_PARTITIONS or any(
            not isinstance(item, BinaryFrontierPartition) for item in partitions
        ):
            raise FrontierPartitionError(f"partition plan requires 2..{_MAX_PARTITIONS} typed child partitions")
        if partitions != tuple(sorted(
            partitions,
            key=lambda item: (item.node_ids[0], item.route_witness.target_host.peer_id,
                              item.route_witness.target_host.host_id, item.request.digest),
        )):
            raise FrontierPartitionError("child partitions are not in canonical node/host/request order")
        assigned: list[str] = []
        hosts: set[tuple[str, str]] = set()
        for partition in partitions:
            request = partition.request
            route = partition.route_witness
            if (
                partition.operation != self.operation
                or request.plan_digest != self.plan_digest
                or request.context_digest != self.context_digest
                or request.frontier_index != self.frontier_index
            ):
                raise FrontierPartitionError("child request differs from its parent plan identity or operation")
            if (
                route.origin_peer_id != self.origin_peer_id
                or route.directory_digest != self.directory_digest
                or route.topology_digest != self.topology_digest
            ):
                raise FrontierPartitionError("partition route differs from the plan's origin/directory/topology view")
            if self.computational_ground_fingerprint not in route.target_host.computational_ground_fingerprints:
                raise FrontierPartitionError("partition host does not advertise the plan's Computational Ground")
            assigned.extend(partition.node_ids)
            hosts.add((route.target_host.peer_id, route.target_host.host_id))
        if len(assigned) != len(set(assigned)) or tuple(sorted(assigned)) != node_ids:
            raise FrontierPartitionError("child partitions must cover every frontier node exactly once")
        if len(hosts) < 2:
            raise FrontierPartitionError("partition plan must span at least two distinct logical hosts")
        object.__setattr__(self, "frontier_node_ids", node_ids)
        object.__setattr__(self, "partitions", partitions)

    @property
    def authoritative(self) -> bool:
        """Mathematics: a partition plan is a proposal; every receiver must independently resolve and admit its child."""
        return False

    @property
    def digest(self) -> str:
        """Mathematics: identify the complete partition proposal, including every child and route witness."""
        return _canonical_digest(self._payload())

    def _payload(self) -> dict[str, Any]:
        """Mathematics: project the exact parent frontier identity and ordered child assignments."""
        return {
            "schema": "mailcpu.binary-frontier-partition-plan.v1",
            "plan_digest": self.plan_digest,
            "context_digest": self.context_digest,
            "frontier_index": self.frontier_index,
            "operation": self.operation,
            "computational_ground_fingerprint": self.computational_ground_fingerprint,
            "origin_peer_id": self.origin_peer_id,
            "directory_digest": self.directory_digest,
            "topology_digest": self.topology_digest,
            "frontier_node_ids": list(self.frontier_node_ids),
            "partitions": [item.to_dict() for item in self.partitions],
        }

    def to_dict(self) -> dict[str, Any]:
        """Mathematics: serialize the complete child assignment with a canonical plan digest and advisory marker."""
        return {**self._payload(), "digest": self.digest, "authoritative": False}

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "BinaryFrontierPartitionPlan":
        """Mathematics: restore a plan only when child requests, route witnesses, coverage and content digest recompute."""
        expected = {
            "schema", "plan_digest", "context_digest", "frontier_index",
            "operation", "computational_ground_fingerprint", "origin_peer_id",
            "directory_digest", "topology_digest", "frontier_node_ids",
            "partitions", "digest", "authoritative",
        }
        if not isinstance(payload, Mapping) or set(payload) != expected:
            raise FrontierPartitionError("binary frontier partition plan fields are malformed")
        if (
            payload["schema"] != "mailcpu.binary-frontier-partition-plan.v1"
            or payload["authoritative"] is not False
            or not isinstance(payload["frontier_node_ids"], list)
            or not isinstance(payload["partitions"], list)
        ):
            raise FrontierPartitionError("binary frontier partition plan schema or authority marker is invalid")
        try:
            plan = cls(
                plan_digest=payload["plan_digest"],
                context_digest=payload["context_digest"],
                frontier_index=payload["frontier_index"],
                operation=payload["operation"],
                computational_ground_fingerprint=payload["computational_ground_fingerprint"],
                origin_peer_id=payload["origin_peer_id"],
                directory_digest=payload["directory_digest"],
                topology_digest=payload["topology_digest"],
                frontier_node_ids=tuple(payload["frontier_node_ids"]),
                partitions=tuple(BinaryFrontierPartition.from_dict(item) for item in payload["partitions"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            if isinstance(exc, FrontierPartitionError):
                raise
            raise FrontierPartitionError("binary frontier partition plan contains invalid nested values") from exc
        if payload["digest"] != plan.digest:
            raise FrontierPartitionError("binary frontier partition plan digest mismatch")
        return plan


def split_binary_frontier_request(
    request: DataflowAddFrontierRequest,
    partitions: Sequence[Sequence[str]],
) -> tuple[DataflowAddFrontierRequest, ...]:
    """Mathematics: partition one ordered request into disjoint child requests whose lane union equals the parent lanes."""
    if type(request) not in _REQUEST_SCHEMAS:
        raise FrontierPartitionError("split requires an exact typed ADD, COMPARE, or MUL request")
    if not isinstance(partitions, (tuple, list)) or not 2 <= len(partitions) <= _MAX_PARTITIONS:
        raise FrontierPartitionError(f"split requires 2..{_MAX_PARTITIONS} child node groups")
    normalized: list[tuple[str, ...]] = []
    for group in partitions:
        if not isinstance(group, (tuple, list)) or not group:
            raise FrontierPartitionError("child node groups must be non-empty sequences")
        node_ids = tuple(group)
        if (
            any(not isinstance(item, str) or not item for item in node_ids)
            or len(node_ids) != len(set(node_ids))
            or node_ids != tuple(sorted(node_ids))
            or len(node_ids) > 64
        ):
            raise FrontierPartitionError("child node groups must contain 1..64 unique node IDs in stable order")
        normalized.append(node_ids)
    if normalized != sorted(normalized, key=lambda item: item[0]):
        raise FrontierPartitionError("child node groups must be in canonical first-node order")
    assigned = [node_id for group in normalized for node_id in group]
    original = tuple(item.node_id for item in request.lanes)
    if len(assigned) != len(set(assigned)) or tuple(sorted(assigned)) != original:
        raise FrontierPartitionError("child node groups must cover the exact parent request lane identities once")
    lanes = {item.node_id: item for item in request.lanes}
    request_type = type(request)
    return tuple(
        request_type(
            plan_digest=request.plan_digest,
            context_digest=request.context_digest,
            frontier_index=request.frontier_index,
            lanes=tuple(lanes[node_id] for node_id in group),
        )
        for group in normalized
    )


__all__ = [
    "BinaryFrontierPartition",
    "BinaryFrontierPartitionPlan",
    "FrontierPartitionError",
    "split_binary_frontier_request",
]
