"""Bounded, content-addressed dependency DAGs for persistent Transit computation."""

from __future__ import annotations

import hashlib
import heapq
import json
import math
import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping


_HEX_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_NODE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")


class ComputationDAGError(ValueError):
    """A computation graph is malformed, cyclic, over budget, or inconsistently committed."""


def _validate_json_value(value: Any) -> None:
    """Mathematics: admit only JSON algebra J={null,bool,int,finite-float,string,list,object[string→J]}."""

    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ComputationDAGError("non-finite numbers are outside the computation DAG value algebra")
        return
    if isinstance(value, list):
        for item in value:
            _validate_json_value(item)
        return
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise ComputationDAGError("JSON object keys must be strings")
        for item in value.values():
            _validate_json_value(item)
        return
    raise ComputationDAGError(f"unsupported computation DAG value type: {type(value).__name__}")


def _canonical(value: Any) -> bytes:
    """Mathematics: define canonical encoding J(x)=UTF8(JSON_sort_keys(x)) for stable digest identity."""

    _validate_json_value(value)
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ComputationDAGError("computation DAG values must be canonical JSON") from exc


def _digest(value: Any) -> str:
    """Mathematics: map canonical state x to its content identity H(x)=SHA256(J(x))."""

    return hashlib.sha256(_canonical(value)).hexdigest()


def _label(value: Any, name: str) -> str:
    """Mathematics: admit label ℓ iff ℓ is non-empty text of at most 256 UTF-8 bytes."""

    if not isinstance(value, str) or not value or len(value.encode("utf-8")) > 256:
        raise ComputationDAGError(f"{name} must be non-empty text of at most 256 UTF-8 bytes")
    return value


@dataclass(frozen=True, init=False)
class ComputationNode:
    """Immutable content-addressed description of one operation in a dependency DAG."""

    node_id: str
    revision: int
    operation: str
    resource: str
    context_digest: str
    dependencies: tuple[str, ...]
    _payload_json: str = field(repr=False)
    digest: str

    def __init__(
        self,
        node_id: str,
        revision: int,
        operation: str,
        resource: str,
        context_digest: str,
        dependencies: Iterable[str],
        payload: Mapping[str, Any],
    ) -> None:
        """Mathematics: identify node v by H(id,rev,op,res,ctx,deps,J(payload)); payload is a bounded JSON object."""

        if not isinstance(node_id, str) or _NODE_ID.fullmatch(node_id) is None:
            raise ComputationDAGError("node_id must be a 1-128 character stable identifier")
        if not isinstance(revision, int) or isinstance(revision, bool) or revision <= 0:
            raise ComputationDAGError("node revision must be a positive integer")
        operation = _label(operation, "operation")
        resource = _label(resource, "resource")
        if not isinstance(context_digest, str) or _HEX_DIGEST.fullmatch(context_digest) is None:
            raise ComputationDAGError("context_digest must be a lowercase SHA-256 digest")
        if isinstance(dependencies, (str, bytes)):
            raise ComputationDAGError("dependencies must be an iterable of node identifiers")
        try:
            deps = tuple(dependencies)
        except TypeError as exc:
            raise ComputationDAGError("dependencies must be iterable") from exc
        if (
            any(not isinstance(dep, str) or _NODE_ID.fullmatch(dep) is None for dep in deps)
            or len(deps) != len(set(deps))
            or node_id in deps
        ):
            raise ComputationDAGError("dependencies must be unique valid node identifiers and cannot include self")
        if not isinstance(payload, Mapping):
            raise ComputationDAGError("node payload must be a JSON object")
        payload_json = _canonical(dict(payload)).decode("utf-8")
        if len(payload_json.encode("utf-8")) > 1_000_000:
            raise ComputationDAGError("node payload exceeds the 1 MB bound")
        record = {
            "node_id": node_id,
            "revision": revision,
            "operation": operation,
            "resource": resource,
            "context_digest": context_digest,
            "dependencies": list(deps),
            "payload": json.loads(payload_json),
        }
        object.__setattr__(self, "node_id", node_id)
        object.__setattr__(self, "revision", revision)
        object.__setattr__(self, "operation", operation)
        object.__setattr__(self, "resource", resource)
        object.__setattr__(self, "context_digest", context_digest)
        object.__setattr__(self, "dependencies", deps)
        object.__setattr__(self, "_payload_json", payload_json)
        object.__setattr__(self, "digest", _digest(record))

    @property
    def payload(self) -> dict[str, Any]:
        """Mathematics: decode a fresh value P from immutable canonical bytes J(P), preventing caller mutation."""

        return json.loads(self._payload_json)

    def to_dict(self) -> dict[str, Any]:
        """Mathematics: project node v to its schema record plus H(v), preserving content identity."""

        return {
            "node_id": self.node_id,
            "revision": self.revision,
            "operation": self.operation,
            "resource": self.resource,
            "context_digest": self.context_digest,
            "dependencies": list(self.dependencies),
            "payload": self.payload,
            "digest": self.digest,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ComputationNode":
        """Mathematics: invert a node record iff exact schema and recomputed H(v) equal its supplied digest."""

        fields = {
            "node_id", "revision", "operation", "resource",
            "context_digest", "dependencies", "payload", "digest",
        }
        if not isinstance(payload, Mapping) or set(payload) != fields:
            raise ComputationDAGError("computation node schema or fields are invalid")
        node = cls(
            payload["node_id"],
            payload["revision"],
            payload["operation"],
            payload["resource"],
            payload["context_digest"],
            payload["dependencies"],
            payload["payload"],
        )
        if payload["digest"] != node.digest:
            raise ComputationDAGError("computation node digest mismatch")
        return node


@dataclass(frozen=True)
class CommittedComputationResult:
    """Immutable semantic result bound to one exact computation node revision."""

    node_id: str
    node_digest: str
    result_digest: str
    _result_json: str = field(repr=False)

    @property
    def result(self) -> dict[str, Any]:
        """Mathematics: decode a fresh result R from immutable canonical bytes J(R)."""

        return json.loads(self._result_json)

    def to_dict(self) -> dict[str, Any]:
        """Mathematics: project commit c to its node and result content identities plus exact result."""

        return {
            "node_id": self.node_id,
            "node_digest": self.node_digest,
            "result_digest": self.result_digest,
            "result": self.result,
        }


class NavigableComputationDAG:
    """Bounded dependency graph with readiness, exact result commits, and checkpoint reconstruction."""

    FORMAT = "mailcpu-navigable-computation-dag-v1"
    MAX_NODES = 256
    MAX_EDGES = 1024

    def __init__(self, nodes: Iterable[ComputationNode], *, max_nodes: int = MAX_NODES) -> None:
        """Mathematics: construct finite DAG G=(V,E), requiring |V|≤N, |E|≤M, known endpoints, and acyclicity."""

        if not isinstance(max_nodes, int) or isinstance(max_nodes, bool) or not 1 <= max_nodes <= self.MAX_NODES:
            raise ComputationDAGError(f"max_nodes must be in [1, {self.MAX_NODES}]")
        try:
            supplied = tuple(nodes)
        except TypeError as exc:
            raise ComputationDAGError("nodes must be iterable") from exc
        if not supplied or len(supplied) > max_nodes:
            raise ComputationDAGError("computation DAG node count is empty or exceeds its bound")
        if any(not isinstance(node, ComputationNode) for node in supplied):
            raise ComputationDAGError("computation DAG contains a non-ComputationNode value")
        mapping = {node.node_id: node for node in supplied}
        if len(mapping) != len(supplied):
            raise ComputationDAGError("computation DAG node identifiers must be unique")
        edge_count = sum(len(node.dependencies) for node in supplied)
        if edge_count > self.MAX_EDGES:
            raise ComputationDAGError("computation DAG edge count exceeds its bound")
        for node in supplied:
            missing = set(node.dependencies) - set(mapping)
            if missing:
                raise ComputationDAGError(
                    f"node {node.node_id} names unknown dependencies: {', '.join(sorted(missing))}"
                )
        self._nodes = mapping
        self.max_nodes = max_nodes
        self._topological = self._topological_order()
        self._committed: dict[str, CommittedComputationResult] = {}

    @property
    def digest(self) -> str:
        """Mathematics: identify graph structure by H(sorted({v.to_dict():v∈V}),max_nodes), excluding mutable commits."""

        return _digest({
            "max_nodes": self.max_nodes,
            "nodes": [self._nodes[node_id].to_dict() for node_id in sorted(self._nodes)],
        })

    @property
    def nodes(self) -> tuple[ComputationNode, ...]:
        """Mathematics: expose immutable node sequence sorted by stable identity id."""

        return tuple(self._nodes[node_id] for node_id in sorted(self._nodes))

    @property
    def committed_nodes(self) -> tuple[str, ...]:
        """Mathematics: expose sorted set dom(C) of nodes with a validated result commit."""

        return tuple(sorted(self._committed))

    @property
    def is_complete(self) -> bool:
        """Mathematics: report true exactly when dom(C)=V."""

        return len(self._committed) == len(self._nodes)

    def ready_nodes(self) -> tuple[ComputationNode, ...]:
        """Mathematics: return frontier F={v∈V\dom(C): pred(v)⊆dom(C)} in stable node-id order."""

        return tuple(
            self._nodes[node_id]
            for node_id in sorted(self._nodes)
            if node_id not in self._committed
            and all(dep in self._committed for dep in self._nodes[node_id].dependencies)
        )

    def revise_node(self, node: ComputationNode) -> str:
        """Mathematics: replace uncommitted v by revision v' iff id(v')=id(v), rev(v')>rev(v), and G remains acyclic."""

        if not isinstance(node, ComputationNode):
            raise ComputationDAGError("node revision requires a ComputationNode")
        current = self._nodes.get(node.node_id)
        if current is None:
            raise ComputationDAGError("cannot revise an unknown computation node")
        if node.node_id in self._committed:
            raise ComputationDAGError("a committed computation node cannot be revised")
        if node.revision <= current.revision:
            raise ComputationDAGError("node revision must increase monotonically")
        if node.node_id in node.dependencies:
            raise ComputationDAGError("revised node cannot depend on itself")
        missing = set(node.dependencies) - set(self._nodes)
        if missing:
            raise ComputationDAGError("revised node names unknown dependencies")
        edge_count = (
            sum(len(item.dependencies) for item in self._nodes.values())
            - len(current.dependencies)
            + len(node.dependencies)
        )
        if edge_count > self.MAX_EDGES:
            raise ComputationDAGError("revised computation DAG exceeds its edge bound")
        previous = self._nodes[node.node_id]
        self._nodes[node.node_id] = node
        try:
            self._topological = self._topological_order()
        except Exception:
            self._nodes[node.node_id] = previous
            self._topological = self._topological_order()
            raise
        return node.digest

    def commit(self, node_id: str, result: Mapping[str, Any]) -> bool:
        """Mathematics: commit R_v once when pred(v)⊆dom(C); return replay=true only for exact H(R_v) repetition."""

        if not isinstance(node_id, str) or node_id not in self._nodes:
            raise ComputationDAGError("cannot commit an unknown computation node")
        if not isinstance(result, Mapping):
            raise ComputationDAGError("computation result must be a JSON object")
        result_json = _canonical(dict(result)).decode("utf-8")
        result_digest = hashlib.sha256(result_json.encode("utf-8")).hexdigest()
        node = self._nodes[node_id]
        previous = self._committed.get(node_id)
        if previous is not None:
            if previous.node_digest != node.digest or previous.result_digest != result_digest:
                raise ComputationDAGError("conflicting result commit for an existing node identity")
            return True
        if not all(dep in self._committed for dep in node.dependencies):
            raise ComputationDAGError("computation node is not ready; dependencies remain uncommitted")
        self._committed[node_id] = CommittedComputationResult(
            node_id,
            node.digest,
            result_digest,
            result_json,
        )
        return False

    def commit_frontier(
        self,
        results: Mapping[str, Mapping[str, Any]],
        *,
        expected_node_ids: Iterable[str] | None = None,
    ) -> bool:
        """Mathematics: atomically publish every result in one exact ready frontier; exact whole-frontier replay is idempotent."""
        if not isinstance(results, Mapping) or not results:
            raise ComputationDAGError("frontier results must be a non-empty node-to-result mapping")
        entries = tuple(results.items())
        node_ids = tuple(sorted(key for key, _ in entries if isinstance(key, str)))
        if len(node_ids) != len(entries) or len(set(node_ids)) != len(node_ids):
            raise ComputationDAGError("frontier result keys must be unique string node identifiers")
        unknown = set(node_ids) - set(self._nodes)
        if unknown:
            raise ComputationDAGError(
                f"frontier results name unknown nodes: {', '.join(sorted(unknown))}"
            )

        if expected_node_ids is not None:
            if isinstance(expected_node_ids, (str, bytes)):
                raise ComputationDAGError("expected_node_ids must be an iterable of node identifiers")
            try:
                expected = tuple(expected_node_ids)
            except TypeError as exc:
                raise ComputationDAGError("expected_node_ids must be iterable") from exc
            if (
                any(not isinstance(item, str) or item not in self._nodes for item in expected)
                or len(expected) != len(set(expected))
                or expected != tuple(sorted(expected))
            ):
                raise ComputationDAGError("expected frontier node identities must be unique known IDs in stable order")
            if expected != node_ids:
                raise ComputationDAGError("frontier results do not match the exact expected node identities")

        prepared: dict[str, CommittedComputationResult] = {}
        for node_id, result in entries:
            if not isinstance(result, Mapping):
                raise ComputationDAGError(f"frontier result for {node_id!r} must be a JSON object")
            result_json = _canonical(dict(result)).decode("utf-8")
            result_digest = hashlib.sha256(result_json.encode("utf-8")).hexdigest()
            prepared[node_id] = CommittedComputationResult(
                node_id=node_id,
                node_digest=self._nodes[node_id].digest,
                result_digest=result_digest,
                _result_json=result_json,
            )

        committed = set(node_ids) & set(self._committed)
        if committed:
            if committed != set(node_ids):
                raise ComputationDAGError("frontier retry conflicts with a partially committed frontier")
            for node_id, candidate in prepared.items():
                previous = self._committed[node_id]
                if (
                    previous.node_digest != candidate.node_digest
                    or previous.result_digest != candidate.result_digest
                ):
                    raise ComputationDAGError("conflicting result commit for an existing frontier identity")
            return True

        ready = tuple(node.node_id for node in self.ready_nodes())
        if node_ids != ready:
            raise ComputationDAGError("frontier results do not cover the exact current ready frontier")
        if any(
            not all(dependency in self._committed for dependency in self._nodes[node_id].dependencies)
            for node_id in node_ids
        ):
            raise ComputationDAGError("frontier contains a node whose dependencies remain uncommitted")

        # All canonical JSON, node identities, dependency checks, and retry
        # checks have succeeded. Publish the complete commit map in one update.
        self._committed.update(prepared)
        return False

    def result(self, node_id: str) -> dict[str, Any]:
        """Mathematics: retrieve R_v only for v∈dom(C), returning a detached JSON projection."""

        commit = self._committed.get(node_id)
        if commit is None:
            raise ComputationDAGError("computation node has no committed result")
        return commit.result

    def lineage(self, node_id: str) -> tuple[str, ...]:
        """Mathematics: return transitive ancestor closure pred*(v) in topological order, excluding v."""

        if node_id not in self._nodes:
            raise ComputationDAGError("unknown computation node")
        ancestors: set[str] = set()
        pending = list(self._nodes[node_id].dependencies)
        while pending:
            current = pending.pop()
            if current in ancestors:
                continue
            ancestors.add(current)
            pending.extend(self._nodes[current].dependencies)
        return tuple(item for item in self._topological if item in ancestors)

    def snapshot(self) -> dict[str, Any]:
        """Mathematics: serialize graph G and committed prefix C in deterministic topological order under digest H(state)."""

        state = {
            "version": 1,
            "max_nodes": self.max_nodes,
            "nodes": [self._nodes[node_id].to_dict() for node_id in sorted(self._nodes)],
            "commits": [
                self._committed[node_id].to_dict()
                for node_id in self._topological
                if node_id in self._committed
            ],
        }
        return {
            "format": self.FORMAT,
            "digest": _digest(state),
            "state": state,
        }

    @classmethod
    def from_snapshot(cls, payload: Mapping[str, Any]) -> "NavigableComputationDAG":
        """Mathematics: reconstruct (G,C) iff envelope digest, node DAG, commit order, and all result digests verify."""

        if (
            not isinstance(payload, Mapping)
            or set(payload) != {"format", "digest", "state"}
            or payload.get("format") != cls.FORMAT
        ):
            raise ComputationDAGError("computation DAG checkpoint envelope is invalid")
        state = payload.get("state")
        if (
            not isinstance(state, Mapping)
            or set(state) != {"version", "max_nodes", "nodes", "commits"}
            or type(state.get("version")) is not int
            or state.get("version") != 1
            or not isinstance(state.get("nodes"), list)
            or not isinstance(state.get("commits"), list)
        ):
            raise ComputationDAGError("computation DAG checkpoint schema is invalid")
        if not isinstance(payload.get("digest"), str) or not _HEX_DIGEST.fullmatch(payload["digest"]):
            raise ComputationDAGError("computation DAG checkpoint digest encoding is invalid")
        if _digest(state) != payload["digest"]:
            raise ComputationDAGError("computation DAG checkpoint digest mismatch")
        nodes = tuple(ComputationNode.from_dict(item) for item in state["nodes"])
        graph = cls(nodes, max_nodes=state["max_nodes"])
        for raw in state["commits"]:
            if not isinstance(raw, Mapping) or set(raw) != {
                "node_id", "node_digest", "result_digest", "result"
            }:
                raise ComputationDAGError("computation DAG commit schema is invalid")
            node_id = raw["node_id"]
            if not isinstance(node_id, str) or node_id not in graph._nodes:
                raise ComputationDAGError("computation DAG commit names an unknown node")
            node = graph._nodes[node_id]
            if raw["node_digest"] != node.digest:
                raise ComputationDAGError("computation DAG commit node digest mismatch")
            result = raw["result"]
            if not isinstance(result, Mapping):
                raise ComputationDAGError("computation DAG commit result must be an object")
            result_json = _canonical(dict(result)).decode("utf-8")
            expected_result_digest = hashlib.sha256(result_json.encode("utf-8")).hexdigest()
            if raw["result_digest"] != expected_result_digest:
                raise ComputationDAGError("computation DAG commit result digest mismatch")
            replayed = graph.commit(node_id, result)
            if replayed:
                raise ComputationDAGError("duplicate computation DAG commit")
        return graph

    def _topological_order(self) -> tuple[str, ...]:
        """Mathematics: Kahn's algorithm emits a total order iff every cycle-free vertex is removed once."""

        indegree = {node_id: len(node.dependencies) for node_id, node in self._nodes.items()}
        outgoing = {node_id: [] for node_id in self._nodes}
        for node in self._nodes.values():
            for dependency in node.dependencies:
                outgoing[dependency].append(node.node_id)
        ready = [node_id for node_id, degree in indegree.items() if degree == 0]
        heapq.heapify(ready)
        order: list[str] = []
        while ready:
            node_id = heapq.heappop(ready)
            order.append(node_id)
            for dependent in sorted(outgoing[node_id]):
                indegree[dependent] -= 1
                if indegree[dependent] == 0:
                    heapq.heappush(ready, dependent)
        if len(order) != len(self._nodes):
            raise ComputationDAGError("computation graph contains a dependency cycle")
        return tuple(order)
