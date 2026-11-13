"""Projection from the framework-independent neural graph IR into MailCPU's DAG.

This adapter preserves graph structure, typed ports, tensor-header references,
and graph provenance inside content-addressed ComputationNode payloads. The
NavigableComputationDAG schedules operation dependencies only; it does not
perform neural arithmetic or fetch tensor data.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import hashlib
import json
import math
import re
from typing import Any, Mapping

from .computation_dag import (
    ComputationDAGError,
    ComputationNode,
    NavigableComputationDAG,
)

NEURAL_GRAPH_SCHEMA = "in-formation-space.neural-computation-graph.v0.1"
PROJECTION_SCHEMA = "mailcpu.neural-graph-dag-projection.v1"
OPERATION_PAYLOAD_SCHEMA = "mailcpu.neural-graph-operation-payload.v1"

_NODE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_REVISION_SHA = re.compile(r"^[0-9a-f]{40}$")


class NeuralGraphBridgeError(ValueError):
    """A canonical neural graph cannot be represented as a MailCPU dependency DAG."""


def _validate_json(value: Any, path: str = "$") -> None:
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise NeuralGraphBridgeError(f"{path} contains a non-finite number")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate_json(item, f"{path}[{index}]")
        return
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise NeuralGraphBridgeError(f"{path} has a non-string object key")
        for key, item in value.items():
            _validate_json(item, f"{path}.{key}")
        return
    raise NeuralGraphBridgeError(f"{path} contains non-JSON value {type(value).__name__}")


def _canonical(value: Any) -> bytes:
    _validate_json(value)
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise NeuralGraphBridgeError(f"graph must be canonical finite JSON: {exc}") from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _unique_named(items: Any, name: str, label: str) -> dict[str, dict[str, Any]]:
    if not isinstance(items, list):
        raise NeuralGraphBridgeError(f"{label} must be an array")
    result: dict[str, dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, Mapping):
            raise NeuralGraphBridgeError(f"{label} entries must be objects")
        identifier = item.get(name)
        if not isinstance(identifier, str) or not identifier:
            raise NeuralGraphBridgeError(f"{label} entries need a non-empty {name}")
        if identifier in result:
            raise NeuralGraphBridgeError(f"{label} contains duplicate {name}: {identifier}")
        result[identifier] = dict(item)
    return result


def _ports(operation: Mapping[str, Any], direction: str) -> dict[str, dict[str, Any]]:
    raw = operation.get(direction)
    if not isinstance(raw, list):
        raise NeuralGraphBridgeError(f"operation {operation.get('id')!r} {direction} must be an array")
    result: dict[str, dict[str, Any]] = {}
    for port in raw:
        if not isinstance(port, Mapping):
            raise NeuralGraphBridgeError(f"operation {operation.get('id')!r} has an invalid {direction} port")
        name = port.get("name")
        dtype = port.get("dtype")
        shape = port.get("shape")
        if (
            not isinstance(name, str)
            or not name
            or name in result
            or not isinstance(dtype, str)
            or not dtype
            or not isinstance(shape, list)
            or any(
                not (
                    (type(dimension) is int and dimension >= 0)
                    or (isinstance(dimension, str) and dimension)
                )
                for dimension in shape
            )
        ):
            raise NeuralGraphBridgeError(
                f"operation {operation.get('id')!r} has a malformed or duplicate {direction} port"
            )
        result[name] = dict(port)
    return result


@dataclass(frozen=True, slots=True)
class NeuralGraphDAGProjection:
    """A content-addressed MailCPU DAG plus the source graph identity and projection counts."""

    graph_digest: str
    source_repository: str
    source_revision: str
    dag: NavigableComputationDAG
    graph_edge_count: int
    dependency_edge_count: int
    tensor_binding_count: int
    graph_input_binding_count: int
    graph_output_binding_count: int

    def manifest(self) -> dict[str, Any]:
        return {
            "schema": PROJECTION_SCHEMA,
            "source_graph_schema": NEURAL_GRAPH_SCHEMA,
            "source_graph_digest": self.graph_digest,
            "source_repository": self.source_repository,
            "source_revision": self.source_revision,
            "dag_format": self.dag.FORMAT,
            "dag_digest": self.dag.digest,
            "operation_node_count": len(self.dag.nodes),
            "dependency_edge_count": self.dependency_edge_count,
            "source_graph_edge_count": self.graph_edge_count,
            "tensor_binding_count": self.tensor_binding_count,
            "graph_input_binding_count": self.graph_input_binding_count,
            "graph_output_binding_count": self.graph_output_binding_count,
            "ready_frontier": [node.node_id for node in self.dag.ready_nodes()],
            "tensor_payload_bytes_included": 0,
            "execution_performed": False,
        }

    def snapshot(self) -> dict[str, Any]:
        return {
            "projection": self.manifest(),
            "dag": self.dag.snapshot(),
        }


def compile_neural_graph_dag(graph: Mapping[str, Any]) -> NeuralGraphDAGProjection:
    """Project verified canonical graph operations into MailCPU's bounded DAG.

    Operation-to-operation edges become ComputationNode dependencies. Graph
    inputs and tensor references are retained as explicit typed bindings in
    each node's immutable payload. This is a scheduler/description projection,
    not a neural execution backend.
    """
    if not isinstance(graph, Mapping):
        raise NeuralGraphBridgeError("neural computation graph must be an object")
    _canonical(graph)
    if graph.get("schema") != NEURAL_GRAPH_SCHEMA:
        raise NeuralGraphBridgeError(f"unsupported graph schema: {graph.get('schema')!r}")

    verification = graph.get("verification")
    completeness = graph.get("completeness")
    source = graph.get("source_observation")
    if not isinstance(verification, Mapping) or verification.get("status") != "passed":
        raise NeuralGraphBridgeError("source graph must carry passed structural verification")
    if not isinstance(completeness, Mapping) or completeness.get("status") != "complete-for-supported-family-template":
        raise NeuralGraphBridgeError("source graph must be complete for its declared family template")
    if not isinstance(source, Mapping):
        raise NeuralGraphBridgeError("source observation provenance is required")

    repository = source.get("repository")
    revision = source.get("revision")
    if not isinstance(repository, str) or not repository:
        raise NeuralGraphBridgeError("source repository identity is required")
    if not isinstance(revision, str) or not _REVISION_SHA.fullmatch(revision):
        raise NeuralGraphBridgeError("source revision must be a pinned lowercase 40-character commit SHA")

    inputs = _unique_named(graph.get("inputs"), "name", "graph inputs")
    outputs = _unique_named(graph.get("outputs"), "name", "graph outputs")
    tensors = _unique_named(graph.get("tensors"), "name", "tensor catalog")
    operations = _unique_named(graph.get("operations"), "id", "operations")
    invalid_operation_ids = sorted(
        identifier for identifier in operations
        if not _NODE_ID.fullmatch(identifier)
    )
    if invalid_operation_ids:
        raise NeuralGraphBridgeError(
            f"operation identifiers are not valid MailCPU DAG node IDs: {invalid_operation_ids[:5]}"
        )
    for identifier, operation in operations.items():
        if not isinstance(operation.get("operator"), str) or not operation["operator"]:
            raise NeuralGraphBridgeError(f"operation {identifier!r} has no operator name")

    edges = graph.get("edges")
    if not isinstance(edges, list):
        raise NeuralGraphBridgeError("graph edges must be an array")

    input_ports = {
        (operation_id, port_name): port
        for operation_id, operation in operations.items()
        for port_name, port in _ports(operation, "inputs").items()
    }
    output_ports = {
        (operation_id, port_name): port
        for operation_id, operation in operations.items()
        for port_name, port in _ports(operation, "outputs").items()
    }

    incoming: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    output_consumers: dict[tuple[str, str], int] = defaultdict(int)
    tensor_uses: dict[str, int] = defaultdict(int)
    graph_input_uses: dict[str, int] = defaultdict(int)
    graph_output_uses: dict[str, int] = defaultdict(int)

    for edge in edges:
        if not isinstance(edge, Mapping):
            raise NeuralGraphBridgeError("graph edge entries must be objects")
        src = edge.get("source")
        dst = edge.get("target")
        if not isinstance(src, Mapping) or not isinstance(dst, Mapping):
            raise NeuralGraphBridgeError("graph edge endpoints must be objects")
        if dst.get("kind") == "operation_input":
            target_operation = dst.get("operation")
            target_port = dst.get("port")
            key = (target_operation, target_port)
            expected = input_ports.get(key)
            if expected is None:
                raise NeuralGraphBridgeError(f"edge targets unknown operation input {key!r}")

            source_kind = src.get("kind")
            source_descriptor: dict[str, Any] | None = None
            if source_kind == "graph_input":
                name = src.get("name")
                source_descriptor = inputs.get(name)
                if source_descriptor is not None:
                    graph_input_uses[name] += 1
            elif source_kind == "tensor":
                name = src.get("name")
                source_descriptor = tensors.get(name)
                if source_descriptor is not None:
                    tensor_uses[name] += 1
            elif source_kind == "operation_output":
                source_operation = src.get("operation")
                source_port = src.get("port")
                source_descriptor = output_ports.get((source_operation, source_port))
                if source_descriptor is not None:
                    output_consumers[(source_operation, source_port)] += 1
            else:
                raise NeuralGraphBridgeError(f"unsupported operation input source kind: {source_kind!r}")

            if source_descriptor is None:
                raise NeuralGraphBridgeError(f"edge references missing source endpoint: {dict(src)}")
            if (
                source_descriptor.get("dtype") != expected.get("dtype")
                or source_descriptor.get("shape") != expected.get("shape")
            ):
                raise NeuralGraphBridgeError(f"edge type/shape mismatch: {dict(src)} -> {dict(dst)}")
            incoming[key].append(
                {
                    "port": target_port,
                    "source": dict(src),
                    "dtype": expected["dtype"],
                    "shape": expected["shape"],
                }
            )
        elif dst.get("kind") == "graph_output":
            name = dst.get("name")
            expected = outputs.get(name)
            if expected is None:
                raise NeuralGraphBridgeError(f"edge targets unknown graph output {name!r}")
            if src.get("kind") != "operation_output":
                raise NeuralGraphBridgeError("graph outputs must be produced by operation outputs")
            source_operation = src.get("operation")
            source_port = src.get("port")
            actual = output_ports.get((source_operation, source_port))
            if actual is None:
                raise NeuralGraphBridgeError(f"graph output source is unknown: {dict(src)}")
            if actual.get("dtype") != expected.get("dtype") or actual.get("shape") != expected.get("shape"):
                raise NeuralGraphBridgeError(f"graph output type/shape mismatch for {name!r}")
            output_consumers[(source_operation, source_port)] += 1
            graph_output_uses[name] += 1
        else:
            raise NeuralGraphBridgeError(f"unsupported edge target kind: {dst.get('kind')!r}")

    for key in input_ports:
        if len(incoming.get(key, ())) != 1:
            raise NeuralGraphBridgeError(f"operation input {key!r} must have exactly one producer")
    for key in output_ports:
        if output_consumers.get(key, 0) < 1:
            raise NeuralGraphBridgeError(f"operation output {key!r} is disconnected")
    for name in tensors:
        if tensor_uses.get(name, 0) < 1:
            raise NeuralGraphBridgeError(f"tensor {name!r} is not bound to any operation")
    for name in inputs:
        if graph_input_uses.get(name, 0) < 1:
            raise NeuralGraphBridgeError(f"graph input {name!r} is not used")
    for name in outputs:
        if graph_output_uses.get(name, 0) != 1:
            raise NeuralGraphBridgeError(f"graph output {name!r} must have exactly one producer")

    graph_digest = _digest(dict(graph))
    context_digest = _digest(
        {
            "source_graph_digest": graph_digest,
            "source_repository": repository,
            "source_revision": revision,
            "ir_version": graph.get("ir_version"),
        }
    )

    nodes: list[ComputationNode] = []
    for operation_id, operation in sorted(operations.items()):
        bindings = [
            incoming[(operation_id, port_name)][0]
            for port_name in sorted(_ports(operation, "inputs"))
        ]
        dependencies = sorted(
            {
                binding["source"]["operation"]
                for binding in bindings
                if binding["source"]["kind"] == "operation_output"
            }
        )
        payload = {
            "schema": OPERATION_PAYLOAD_SCHEMA,
            "source_graph": {
                "schema": graph["schema"],
                "ir_version": graph.get("ir_version"),
                "digest": graph_digest,
                "repository": repository,
                "revision": revision,
                "license_id": source.get("license_id"),
            },
            "operation": {
                "id": operation_id,
                "operator": operation["operator"],
                "inputs": operation["inputs"],
                "outputs": operation["outputs"],
                "attributes": operation.get("attributes", {}),
                "provenance": operation.get("provenance", {}),
            },
            "input_bindings": bindings,
            "output_consumers": [
                {
                    "port": port_name,
                    "consumer_count": output_consumers.get((operation_id, port_name), 0),
                }
                for port_name in sorted(_ports(operation, "outputs"))
            ],
        }
        nodes.append(
            ComputationNode(
                node_id=operation_id,
                revision=1,
                operation=operation["operator"],
                resource="neural-graph.operation",
                context_digest=context_digest,
                dependencies=dependencies,
                payload=payload,
            )
        )

    if len(nodes) > NavigableComputationDAG.MAX_NODES:
        raise NeuralGraphBridgeError(
            f"graph has {len(nodes)} operation nodes; MailCPU DAG limit is {NavigableComputationDAG.MAX_NODES}"
        )
    try:
        dag = NavigableComputationDAG(nodes)
    except ComputationDAGError as exc:
        raise NeuralGraphBridgeError(f"MailCPU rejected the projected operation DAG: {exc}") from exc

    dependency_edge_count = sum(len(node.dependencies) for node in nodes)
    if dependency_edge_count > NavigableComputationDAG.MAX_EDGES:
        raise NeuralGraphBridgeError(
            f"projected dependency count exceeds MailCPU limit {NavigableComputationDAG.MAX_EDGES}"
        )

    return NeuralGraphDAGProjection(
        graph_digest=graph_digest,
        source_repository=repository,
        source_revision=revision,
        dag=dag,
        graph_edge_count=len(edges),
        dependency_edge_count=dependency_edge_count,
        tensor_binding_count=sum(tensor_uses.values()),
        graph_input_binding_count=sum(graph_input_uses.values()),
        graph_output_binding_count=sum(graph_output_uses.values()),
    )
