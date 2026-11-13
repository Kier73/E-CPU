"""Tests for projecting canonical neural topology into MailCPU's dependency DAG."""

from __future__ import annotations

import copy

import pytest

from mailcpu.computation_dag import NavigableComputationDAG
from mailcpu.neural_graph_bridge import (
    NeuralGraphBridgeError,
    compile_neural_graph_dag,
)


REVISION = "607a30d783dfa663caf39e06633721c8d4cfcd7e"
HEADER_SHA = "a" * 64


def _port(name: str, dtype: str, shape: list) -> dict:
    return {"name": name, "dtype": dtype, "shape": shape}


def _operation(identifier: str, operator: str, inputs: list[dict], outputs: list[dict]) -> dict:
    return {
        "id": identifier,
        "operator": operator,
        "inputs": inputs,
        "outputs": outputs,
        "attributes": {},
        "provenance": {
            "operator_semantics": {
                "status": "family-interpreted",
                "basis": "synthetic adapter contract",
                "reference": "https://example.invalid/model-contract",
            },
            "port_shapes": {
                "status": "dimensionally-derived",
                "basis": "synthetic test dimensions",
            },
        },
    }


def make_graph() -> dict:
    return {
        "schema": "in-formation-space.neural-computation-graph.v0.1",
        "ir_version": "0.1.0",
        "source_observation": {
            "repository": "openai-community/gpt2",
            "revision": REVISION,
            "license_id": "mit",
            "nsd_schema": "in-formation-space.neural-structure-description.v0.1",
            "source_files": [
                {
                    "path": "model.safetensors",
                    "role": "safetensors-shard",
                    "sha256": HEADER_SHA,
                    "sha256_scope": "8-byte-prefix-and-header-only",
                    "size_bytes": 4096,
                }
            ],
        },
        "model_family_adapter": {
            "id": "test-adapter",
            "version": "0.1.0",
            "family": "test-family",
            "reference": "https://example.invalid/model-contract",
            "status": "family-interpreted",
        },
        "dimension_symbols": {
            "batch": {"kind": "runtime", "value": None, "minimum": 1},
            "feature": {"kind": "fixed", "value": 2},
        },
        "inputs": [
            {
                "name": "input.values",
                "dtype": "F32",
                "shape": ["batch", 2],
                "semantic_role": "test_input",
            }
        ],
        "outputs": [
            {
                "name": "output.values",
                "dtype": "F32",
                "shape": ["batch", 2],
                "semantic_role": "test_output",
            }
        ],
        "tensors": [
            {
                "name": "layer.weight",
                "dtype": "F32",
                "shape": [2, 2],
                "source": {
                    "file": "model.safetensors",
                    "data_offsets": [0, 16],
                    "data_bytes": 16,
                    "header_sha256": HEADER_SHA,
                    "header_hash_scope": "8-byte-prefix-and-header-only",
                },
                "classification": {
                    "role": "test.weight",
                    "status": "family-interpreted",
                    "evidence": ["synthetic tensor contract"],
                },
            }
        ],
        "operations": [
            _operation(
                "projection",
                "linear.affine",
                [
                    _port("data", "F32", ["batch", 2]),
                    _port("weight", "F32", [2, 2]),
                ],
                [_port("projected", "F32", ["batch", 2])],
            ),
            _operation(
                "normalization",
                "normalization.identity",
                [_port("value", "F32", ["batch", 2])],
                [_port("normalized", "F32", ["batch", 2])],
            ),
        ],
        "edges": [
            {
                "source": {"kind": "graph_input", "name": "input.values"},
                "target": {"kind": "operation_input", "operation": "projection", "port": "data"},
                "provenance": {"status": "inferred-connection", "basis": "test input contract"},
            },
            {
                "source": {"kind": "tensor", "name": "layer.weight"},
                "target": {"kind": "operation_input", "operation": "projection", "port": "weight"},
                "provenance": {"status": "inferred-connection", "basis": "test tensor binding"},
            },
            {
                "source": {"kind": "operation_output", "operation": "projection", "port": "projected"},
                "target": {"kind": "operation_input", "operation": "normalization", "port": "value"},
                "provenance": {"status": "inferred-connection", "basis": "test operation dependency"},
            },
            {
                "source": {"kind": "operation_output", "operation": "normalization", "port": "normalized"},
                "target": {"kind": "graph_output", "name": "output.values"},
                "provenance": {"status": "inferred-connection", "basis": "test output contract"},
            },
        ],
        "completeness": {
            "status": "complete-for-supported-family-template",
            "observed_tensor_count": 1,
            "classified_tensor_count": 1,
            "bound_tensor_count": 1,
            "unclassified_tensors": [],
            "unused_tensors": [],
            "unsupported_components": [],
            "missing_expected_components": [],
        },
        "verification": {
            "status": "passed",
            "passed_check_count": 12,
            "failed_check_count": 0,
            "operation_count": 2,
            "edge_count": 4,
            "input_port_count": 3,
            "output_port_count": 2,
            "checks": [],
        },
        "evidence_policy": {
            "tensor_metadata": "observed",
            "tensor_roles": "family-interpreted",
            "connections": "inferred",
            "payload_values": "not-observed",
        },
        "assumptions_and_unresolved": ["Synthetic test graph only."],
    }


def test_projects_typed_graph_into_content_addressed_mailcpu_dag() -> None:
    graph = make_graph()
    projection = compile_neural_graph_dag(graph)

    assert projection.source_repository == "openai-community/gpt2"
    assert projection.source_revision == REVISION
    assert projection.graph_edge_count == 4
    assert projection.dependency_edge_count == 1
    assert projection.tensor_binding_count == 1
    assert projection.graph_input_binding_count == 1
    assert projection.graph_output_binding_count == 1
    assert len(projection.dag.nodes) == 2
    assert [node.node_id for node in projection.dag.ready_nodes()] == ["projection"]

    manifest = projection.manifest()
    assert manifest["tensor_payload_bytes_included"] == 0
    assert manifest["execution_performed"] is False
    assert manifest["ready_frontier"] == ["projection"]

    projection_node = next(node for node in projection.dag.nodes if node.node_id == "projection")
    assert projection_node.dependencies == ()
    assert projection_node.payload["operation"]["operator"] == "linear.affine"
    assert projection_node.payload["input_bindings"][0]["source"]["kind"] == "graph_input"
    assert projection_node.payload["input_bindings"][1]["source"]["kind"] == "tensor"
    assert projection_node.payload["source_graph"]["revision"] == REVISION
    assert "weights" not in projection_node.payload
    assert "tensor_values" not in projection_node.payload


def test_operation_dependencies_become_dag_readiness_and_survive_checkpoint() -> None:
    projection = compile_neural_graph_dag(make_graph())
    dag = projection.dag
    assert tuple(node.node_id for node in dag.ready_nodes()) == ("projection",)

    dag.commit("projection", {"structural_status": "interpreted"})
    assert tuple(node.node_id for node in dag.ready_nodes()) == ("normalization",)
    snapshot = dag.snapshot()
    restored = NavigableComputationDAG.from_snapshot(snapshot)

    assert restored.digest == dag.digest
    assert restored.committed_nodes == ("projection",)
    assert restored.result("projection") == {"structural_status": "interpreted"}
    assert tuple(node.node_id for node in restored.ready_nodes()) == ("normalization",)

    restored.commit("normalization", {"structural_status": "complete"})
    assert restored.is_complete


def test_rejects_graph_without_passed_verification_or_completeness() -> None:
    graph = make_graph()
    graph["verification"]["status"] = "pending"
    with pytest.raises(NeuralGraphBridgeError, match="passed structural verification"):
        compile_neural_graph_dag(graph)

    graph = make_graph()
    graph["completeness"]["status"] = "incomplete"
    with pytest.raises(NeuralGraphBridgeError, match="complete for its declared"):
        compile_neural_graph_dag(graph)


def test_rejects_mutated_edge_shapes_and_missing_tensor_bindings() -> None:
    graph = make_graph()
    damaged = copy.deepcopy(graph)
    damaged["operations"][0]["inputs"][0]["shape"] = ["batch", 3]
    with pytest.raises(NeuralGraphBridgeError, match="edge type/shape mismatch"):
        compile_neural_graph_dag(damaged)

    graph = make_graph()
    graph["edges"] = [
        edge for edge in graph["edges"]
        if edge["source"].get("kind") != "tensor"
    ]
    with pytest.raises(NeuralGraphBridgeError, match="exactly one producer"):
        compile_neural_graph_dag(graph)


def test_rejects_unconnected_tensor_and_unsupported_edge_endpoints() -> None:
    graph = make_graph()
    graph["tensors"].append(
        {
            "name": "unused.weight",
            "dtype": "F32",
            "shape": [1],
            "source": {
                "file": "model.safetensors",
                "data_offsets": [16, 20],
                "data_bytes": 4,
                "header_sha256": HEADER_SHA,
                "header_hash_scope": "8-byte-prefix-and-header-only",
            },
            "classification": {
                "role": "test.unused",
                "status": "family-interpreted",
                "evidence": ["synthetic tensor contract"],
            },
        }
    )
    with pytest.raises(NeuralGraphBridgeError, match="not bound"):
        compile_neural_graph_dag(graph)

    graph = make_graph()
    graph["edges"][0]["source"] = {"kind": "missing", "name": "nowhere"}
    with pytest.raises(NeuralGraphBridgeError, match="unsupported operation input source kind"):
        compile_neural_graph_dag(graph)


def test_rejects_unpinned_revision_and_noncanonical_node_identifiers() -> None:
    graph = make_graph()
    graph["source_observation"]["revision"] = "main"
    with pytest.raises(NeuralGraphBridgeError, match="40-character"):
        compile_neural_graph_dag(graph)

    graph = make_graph()
    graph["operations"][0]["id"] = "bad/id"
    with pytest.raises(NeuralGraphBridgeError, match="valid MailCPU DAG node IDs"):
        compile_neural_graph_dag(graph)


def test_projection_digest_changes_when_graph_description_changes() -> None:
    first = compile_neural_graph_dag(make_graph())
    changed = make_graph()
    changed["operations"][0]["attributes"]["precision"] = "f32"
    second = compile_neural_graph_dag(changed)
    assert first.graph_digest != second.graph_digest
    assert first.dag.digest != second.dag.digest
