# E-GPU Navigable Operational Fabric

## Purpose and current methods

The E-GPU is a composite logical host. It resolves a method through a directed graph of operational loci, executes a bounded reference method, verifies its observable result, and returns a route receipt.

| Method | Path | Semantics |
|---|---|---|
| vector.add | dispatch → SIMT → verify | Lane-wise integer addition |
| vector.multiply | dispatch → SIMT → verify | Lane-wise integer multiplication |
| simt.kernel | dispatch → SIMT → verify | Existing bounded SIMT instruction algebra |
| vector.sum | dispatch → tree reduction → verify | Pairwise reduction with odd-lane carry |

The first three use TransitSIMTHost. The reduction method records a tree-shaped level trace but the current Python evaluator is sequential; no GPU parallel speedup is claimed.

## Host graph

The default graph has four logical loci:

| Identity | Role | Capability | Successors |
|---|---|---|---|
| egpu.default.dispatch | Dispatch | egpu.dispatch | SIMT, reduction |
| egpu.default.simt | Execution | simt.execute | Verification |
| egpu.default.reduce | Reduction | reduce.tree | Verification |
| egpu.default.verify | Verification | result.verify | None |

These are logical host identities, not machine or placement-node names. A method maps to one required capability. Breadth-first search resolves a minimum-hop directed path from dispatch to the unique locus with that capability, then from that locus to verification. Successors are visited lexically, making ties deterministic. Missing, ambiguous, or unreachable paths fail closed.

## Request contract

The external request uses operation execute navigable E-GPU method, resource /gpu/egpu, exact required/granted rights {execute}, and destructive=false. The receiver hypervisor must reconstruct execute authority from local kernel capabilities. Internal graph capabilities select a method locus; they do not grant OS or kernel privileges.

Exact payload shapes:

~~~python
{"method": "vector.add", "left": [1, 2], "right": [3, 4], "max_steps": 16}
{"method": "vector.multiply", "left": [2, 3], "right": [4, 5], "max_steps": 16}
{"method": "vector.sum", "values": [1, 2, 3, 4], "max_steps": 16}
{"method": "simt.kernel", "lanes": 2, "inputs": {"x": [1, 2]}, "program": [...], "max_steps": 16}
~~~

Vector methods compile into a five-instruction SIMT program. The general kernel retains the existing instruction grammar, lane and register bounds, structured divergence/reconvergence, and converged barrier rule.

## Verification and receipts

Vector addition and multiplication are checked against independent scalar integer operations. Tree reduction is checked against scalar sum and its canonical state digest is recomputed. An arbitrary SIMT kernel receives a complete state-digest integrity check, not an independent semantic oracle.

The response contains the composite host identity, selected method and capability, traversed logical locus IDs, backend result, backend result digest, and a receipt digest binding those fields. The receipt is unsigned: it is deterministic provenance, not external cryptographic attestation. The Transit worker may bind the effect to its existing semantic-translation evidence and execution journal.

## Router integration

EGPUHost follows the operation_name/resource_name/handle(event) contract of TransitBackendRouter and can be registered as an exact backend:

~~~python
from mailcpu.egpu import EGPUHost
from mailcpu.transit_router import TransitBackendRouter

router = TransitBackendRouter()
router.register_backend(EGPUHost())
~~~

Place that router inside TransitComputeWorker. The receiver authority process must hold execute on /gpu/egpu. The E-GPU graph is not a second hypervisor and cannot bypass the outer contract.

## Limits and next gates

This implementation does not provide physical GPU discovery, a driver, GPU ISA execution, vendor scheduling, occupancy, GPU memory semantics, asynchronous streams, concurrent workgroups, atomics, shared-memory visibility, or CPU/accelerator address-space transfer. It makes no measured energy, latency, bandwidth, or speedup claim.

Next gates: explicit local/shared buffer ownership and visibility; workgroup barriers and memory ordering; typed transfer and completion receipts; independent reduction oracle; a hardware or faithful emulator adapter; and persistent Transit session/checkpoint/replay tests for E-GPU.
