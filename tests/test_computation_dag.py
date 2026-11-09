"""Unit tests for the persistent, dependency-aware computation DAG."""

from __future__ import annotations

import copy

import pytest

from mailcpu.computation_dag import (
    ComputationDAGError,
    ComputationNode,
    NavigableComputationDAG,
)


_CONTEXT = "a" * 64


def _node(node_id: str, dependencies: tuple[str, ...] = (), revision: int = 1, payload=None):
    """Mathematics: construct a node with fixed context digest c and exact dependency predecessor set pred(v)."""

    return ComputationNode(
        node_id=node_id,
        revision=revision,
        operation="test operation",
        resource="/test/resource",
        context_digest=_CONTEXT,
        dependencies=dependencies,
        payload={} if payload is None else payload,
    )


def test_dag_frontier_commit_replay_and_snapshot_round_trip() -> None:
    """Mathematics: the ready frontier equals uncommitted nodes whose complete predecessor set is committed."""

    graph = NavigableComputationDAG((
        _node("root", payload={"seed": 7}),
        _node("left", ("root",), payload={"transform": "add"}),
        _node("right", ("root",), payload={"transform": "multiply"}),
        _node("join", ("left", "right"), payload={"transform": "sum"}),
    ))
    assert tuple(node.node_id for node in graph.ready_nodes()) == ("root",)
    with pytest.raises(ComputationDAGError, match="not ready"):
        graph.commit("left", {"value": 1})

    assert graph.commit("root", {"value": 7}) is False
    assert graph.commit("root", {"value": 7}) is True
    assert {node.node_id for node in graph.ready_nodes()} == {"left", "right"}
    graph.commit("left", {"value": 14})
    graph.commit("right", {"value": 49})
    assert tuple(node.node_id for node in graph.ready_nodes()) == ("join",)

    restored = NavigableComputationDAG.from_snapshot(graph.snapshot())
    assert restored.digest == graph.digest
    assert restored.committed_nodes == graph.committed_nodes
    assert restored.result("left") == {"value": 14}
    assert tuple(node.node_id for node in restored.ready_nodes()) == ("join",)
    restored.commit("join", {"value": 63})
    assert restored.is_complete
    assert set(restored.lineage("join")) == {"root", "left", "right"}


def test_dag_rejects_cycles_unknown_dependencies_and_conflicting_commits() -> None:
    """Mathematics: reject graphs without a topological ordering and reject non-functional commit maps C[v]."""

    with pytest.raises(ComputationDAGError, match="unknown dependencies"):
        NavigableComputationDAG((_node("root", ("missing",)),))
    with pytest.raises(ComputationDAGError, match="cycle"):
        NavigableComputationDAG((
            _node("first", ("second",)),
            _node("second", ("first",)),
        ))

    graph = NavigableComputationDAG((_node("root"),))
    graph.commit("root", {"value": 1})
    with pytest.raises(ComputationDAGError, match="conflicting result"):
        graph.commit("root", {"value": 2})


def test_pending_node_revision_is_monotonic_and_committed_nodes_are_immutable() -> None:
    """Mathematics: an uncommitted operation may advance v→v' only with a larger revision; a committed v is immutable."""

    graph = NavigableComputationDAG((
        _node("root"),
        _node("pending", ("root",), payload={"plan": "placeholder"}),
    ))
    graph.commit("root", {"receipt": "grounded"})
    revised = _node(
        "pending",
        ("root",),
        revision=2,
        payload={"plan": "materialized", "source": "HALT"},
    )
    assert graph.revise_node(revised) == revised.digest
    assert graph.ready_nodes() == (revised,)
    with pytest.raises(ComputationDAGError, match="increase monotonically"):
        graph.revise_node(_node("pending", ("root",), revision=2))
    graph.commit("pending", {"status": "done"})
    with pytest.raises(ComputationDAGError, match="cannot be revised"):
        graph.revise_node(_node("pending", ("root",), revision=3))


def test_dag_canonical_payload_is_detached_and_checkpoint_tampering_fails() -> None:
    """Mathematics: mutations to decoded projections do not change H(v), and any changed checkpoint state violates H(state)."""

    node = _node("root", payload={"nested": {"value": 1}, "items": [1, 2]})
    before = node.digest
    decoded = node.payload
    decoded["nested"]["value"] = 99
    decoded["items"].append(3)
    assert node.digest == before
    assert node.payload == {"nested": {"value": 1}, "items": [1, 2]}

    graph = NavigableComputationDAG((node,))
    checkpoint = graph.snapshot()
    tampered = copy.deepcopy(checkpoint)
    tampered["state"]["nodes"][0]["payload"]["nested"]["value"] = 100
    with pytest.raises(ComputationDAGError, match="digest mismatch"):
        NavigableComputationDAG.from_snapshot(tampered)


@pytest.mark.parametrize(
    "payload",
    (
        {1: "integer key"},
        {"not-json": object()},
        {"not-finite": float("nan")},
        {"tuple-is-not-a-json-array": (1, 2)},
    ),
)
def test_node_payload_rejects_values_outside_the_json_algebra(payload) -> None:
    """Mathematics: node payloads are restricted to the closed canonical JSON algebra, excluding ambiguous encodings."""

    with pytest.raises(ComputationDAGError):
        _node("root", payload=payload)

def test_frontier_commit_is_atomic_idempotent_and_snapshot_safe() -> None:
    """Mathematics: one exact ready frontier changes commit domain from C to C∪F in one transaction."""
    graph = NavigableComputationDAG((
        _node("a", payload={"source": "left"}),
        _node("b", payload={"source": "right"}),
        _node("join", ("a", "b"), payload={"operation": "join"}),
    ))
    frontier = ("a", "b")
    results = {
        "a": {"value": 11},
        "b": {"value": 31},
    }

    assert graph.commit_frontier(results, expected_node_ids=frontier) is False
    assert graph.committed_nodes == frontier
    assert tuple(node.node_id for node in graph.ready_nodes()) == ("join",)
    assert graph.commit_frontier(results, expected_node_ids=frontier) is True

    restored = NavigableComputationDAG.from_snapshot(graph.snapshot())
    assert restored.committed_nodes == frontier
    assert restored.result("a") == {"value": 11}
    assert restored.result("b") == {"value": 31}
    assert tuple(node.node_id for node in restored.ready_nodes()) == ("join",)

    with pytest.raises(ComputationDAGError, match="conflicting result"):
        graph.commit_frontier(
            {"a": {"value": 12}, "b": {"value": 31}},
            expected_node_ids=frontier,
        )
    assert graph.committed_nodes == frontier


def test_frontier_commit_refuses_partial_or_invalid_results_without_mutation() -> None:
    """Mathematics: failed validation leaves the prior commit map C unchanged for every submitted frontier."""
    graph = NavigableComputationDAG((
        _node("a"),
        _node("b"),
        _node("join", ("a", "b")),
    ))
    frontier = ("a", "b")

    with pytest.raises(ComputationDAGError, match="exact expected node identities"):
        graph.commit_frontier({"a": {"value": 1}}, expected_node_ids=frontier)
    assert graph.committed_nodes == ()

    with pytest.raises(ComputationDAGError, match="unsupported computation DAG value type"):
        graph.commit_frontier(
            {"a": {"value": 1}, "b": {"value": object()}},
            expected_node_ids=frontier,
        )
    assert graph.committed_nodes == ()
    assert tuple(node.node_id for node in graph.ready_nodes()) == frontier

    with pytest.raises(ComputationDAGError, match="stable order"):
        graph.commit_frontier(
            {"a": {"value": 1}, "b": {"value": 2}},
            expected_node_ids=("b", "a"),
        )
    assert graph.committed_nodes == ()


def test_frontier_commit_refuses_mixed_partial_retry() -> None:
    """Mathematics: a batch with only a strict subset already committed cannot complete a frontier transaction."""
    graph = NavigableComputationDAG((
        _node("a"),
        _node("b"),
        _node("join", ("a", "b")),
    ))
    graph.commit("a", {"value": 1})

    with pytest.raises(ComputationDAGError, match="partially committed frontier"):
        graph.commit_frontier(
            {"a": {"value": 1}, "b": {"value": 2}},
            expected_node_ids=("a", "b"),
        )

    assert graph.committed_nodes == ("a",)
    assert tuple(node.node_id for node in graph.ready_nodes()) == ("b",)

