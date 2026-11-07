# E-GPU Navigable Operational Fabric

## Purpose and current methods

The E-GPU is a composite logical host. It resolves a method through a directed graph of operational loci, executes a bounded reference method, verifies its observable result, and returns a route receipt.

| Method | Path | Semantics |
|---|---|---|
| vector.add | dispatch → SIMT → verify | Lane-wise integer addition |
| vector.multiply | dispatch → SIMT → verify | Lane-wise integer multiplication |
| simt.kernel | dispatch → SIMT → verify | Existing bounded SIMT instruction algebra |
| vector.sum | dispatch → tree reduction → verify | Pairwise reduction with odd-lane carry |
| workgroup.shared_kernel | dispatch → workgroup → shared memory → verify | A bounded lane program with invocation-scoped shared buffers and barrier-published visibility |

The first three use TransitSIMTHost. The reduction method records a tree-shaped level trace but the current Python evaluator is sequential; no GPU parallel speedup is claimed. The workgroup method extends the existing SIMT reference interpreter with bounded shared buffers, single-writer epochs, and converged barrier publication.

## Host graph

The default graph has four logical loci:

| Identity | Role | Capability | Successors |
|---|---|---|---|
| egpu.default.dispatch | Dispatch | egpu.dispatch | SIMT, reduction |
| egpu.default.simt | Execution | simt.execute | Verification |
| egpu.default.reduce | Reduction | reduce.tree | Verification |
| egpu.default.workgroup | Workgroup execution | workgroup.execute | Shared memory |
| egpu.default.shared | Workgroup shared memory | shared.memory | Verification |
| egpu.default.verify | Verification | result.verify | None |

These are logical host identities, not machine or placement-node names. Each method maps to an ordered capability sequence. Breadth-first search resolves a minimum-hop directed path through each required locus in sequence, then to verification. The shared-workgroup method therefore explicitly traverses both the workgroup executor and its shared-memory host. Successors are visited lexically, making ties deterministic. Missing, ambiguous, or unreachable paths fail closed.

## Request contract

The external request uses operation execute navigable E-GPU method, resource /gpu/egpu, exact required/granted rights {execute}, and destructive=false. The receiver hypervisor must reconstruct execute authority from local kernel capabilities. Internal graph capabilities select a method locus; they do not grant OS or kernel privileges.

Exact payload shapes:

~~~python
{"method": "vector.add", "left": [1, 2], "right": [3, 4], "max_steps": 16}
{"method": "vector.multiply", "left": [2, 3], "right": [4, 5], "max_steps": 16}
{"method": "vector.sum", "values": [1, 2, 3, 4], "max_steps": 16}
{"method": "simt.kernel", "lanes": 2, "inputs": {"x": [1, 2]}, "program": [...], "max_steps": 16}
{"method": "workgroup.shared_kernel", "lanes": 4, "inputs": {"x": [73, 11, 29, 47]}, "shared_buffers": {"scratch": 1}, "program": [...], "max_steps": 16}
~~~

Vector methods compile into a five-instruction SIMT program. The general kernel retains the existing instruction grammar, lane and register bounds, structured divergence/reconvergence, and converged barrier rule. Workgroup kernels additionally use SHARED_STORE and SHARED_LOAD and must declare bounded shared_buffers. A write is private to the invocation until every lane arrives at a converged BARRIER.

## Verification and receipts

Vector addition and multiplication are checked against independent scalar integer operations. Tree reduction is checked against scalar sum and its canonical state digest is recomputed. An arbitrary SIMT kernel receives a complete state-digest integrity check, not an independent semantic oracle.

The response contains the composite host identity, selected method and capability, traversed logical locus IDs, backend result, backend result digest, and a receipt digest binding those fields. The receipt is unsigned: it is deterministic provenance, not external cryptographic attestation. The Transit worker may bind the effect to its existing semantic-translation evidence and execution journal.

## Shared workgroup and Transit recovery

The shared-workgroup method is a concrete multi-host route. Lane zero can write one declared shared cell, then all lanes cross a converged barrier and load the published cell. The interpreter returns the visible shared-memory projection and the barrier epochs that published writes. The operational rules are specified in [WORKGROUP_SHARED_MEMORY.md](WORKGROUP_SHARED_MEMORY.md).

An end-to-end Transit test sends this operation through receiver-local authorization, records semantic-translation evidence, saves a quiescent session checkpoint, restores it over replacement TCP transports, and retransmits the same semantic event in a new reliable frame. The restored hypervisor ledger returns the committed result as a replay; the E-GPU backend call count remains one. This is checkpoint/restore within the test process, not a hard process-termination or physical-host experiment.

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

Next gates: cross-workgroup coordination; typed memory transfer and completion receipts; an independent workgroup semantic oracle; a hardware or faithful emulator adapter; and hard-process-termination tests using the new shared-workgroup backend.
