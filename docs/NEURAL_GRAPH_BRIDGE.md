# Neural graph projection into MailCPU

## Purpose

The [In-Formation-Space HFR-002 graph IR](https://github.com/Kier73/In-Formation-Space/blob/main/experiments/external_neural_structure_reading/neural-computation-graph.schema.json) describes a neural computation as typed operations, ports, tensor references and directed dataflow edges.

MailCPU already has a bounded, content-addressed dependency DAG. This bridge projects the *operation dependency relation* into that DAG while retaining the richer typed graph detail inside immutable node payloads.

It deliberately does not execute neural operators, import model code, download tensors, or turn a dependency DAG into a tensor engine.

## Mapping

| HFR graph | MailCPU representation |
| --- | --- |
| Operation | `ComputationNode` |
| Operation identifier | Stable DAG node identifier |
| Operator name | Node `operation` label |
| Operation-output to operation-input edge | Dependency in `ComputationNode.dependencies` |
| Typed operation ports | Preserved in node payload |
| Tensor-to-operation-input edge | Explicit tensor binding in node payload |
| Graph-input-to-operation-input edge | Explicit input binding in node payload |
| Source revision and graph identity | Context digest and source provenance in node payload |
| Graph output | Explicit output-consumer record in producer node payload |

An operation node is ready when every predecessor operation has a committed result, using the existing `NavigableComputationDAG.ready_nodes()` rule. A graph with multiple independent operation branches can expose those nodes together as a frontier.

Tensor ports are not collapsed into dependency edges. Their names, dtypes, shapes, tensor identity, shard path, header hash and offsets remain available as node payload evidence. This preserves information that the current dependency-only scheduler does not model directly.

## Usage

Given an HFR-002 graph JSON document:

```python
import json
from pathlib import Path

from mailcpu import compile_neural_graph_dag

graph = json.loads(Path("gpt2-typed-topology.json").read_text())
projection = compile_neural_graph_dag(graph)

print(projection.manifest())
print([node.node_id for node in projection.dag.ready_nodes()])
checkpoint = projection.snapshot()
```

The bridge requires:
- the exact supported HFR-002 graph schema;
- a pinned 40-character source commit SHA;
- structural verification marked `passed`;
- completeness marked `complete-for-supported-family-template`;
- unique typed operation and tensor identities;
- one producer per operation input;
- dtype/shape compatibility on every retained edge;
- all graph tensors and inputs used, and all operation outputs connected;
- an acyclic operation dependency relation admitted by MailCPU's existing DAG bounds.

## Resource and execution boundary

The current `NavigableComputationDAG` is bounded at 256 operation nodes and 1,024 operation dependencies. The GPT-2 HFR-002 graph has 150 operations, so its operation-level projection fits this first bound. A larger model may exceed it; the bridge fails closed rather than silently pruning or partitioning operations.

The initial projection retains zero tensor payload bytes and sets `execution_performed=false`. The DAG is a description/readiness object. A later executor must separately define:
- operator implementations and numerical dtypes;
- tensor materialization or remote tensor access;
- shape and layout semantics at runtime;
- activation/memory lifetime and placement;
- numerical comparison and tolerances;
- operation receipts, authority requirements and replay behavior.

No model weights are copied into this projection. The graph's tensor references remain references to the original pinned observation and Safetensors header metadata only.

## Evidence boundary

A successful projection establishes that the canonical graph's operation dependencies can be represented by MailCPU's content-addressed DAG without dropping the typed port/tensor bindings. It does not establish that MailCPU can run the operations or reproduce the source neural model's outputs.

This is a bridge from *description to navigable dependency structure*, not yet a neural runtime.
