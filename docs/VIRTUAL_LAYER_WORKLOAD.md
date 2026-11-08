# Virtual Layer Workload and Operator Registry

This document specifies the first executable contract between Virtual Layer theory and the MailCPU hypervisor. It adds a portable workload description and a node-local operator registry without replacing the MailCPU instruction algebra, kernel, or existing hypervisor authority law.

## 1. Purpose

A Virtual Layer workload describes a desired transformation relative to an admitted Virtual Ground. It can travel through the existing reliable operation channel. A receiving host validates the system identity and ground, resolves an operator against its own registry, reconstructs process capabilities locally, and submits the work to the existing hypervisor arbitration and effect ledgers.

A workload carries references and data, never executable code or authority.

## 2. Workload contract

The schema identifier is `virtual_layer.workload`. Version 1 remains the legacy form; version 2 permits operator-scoped, digest-pinned structural-memory inputs while retaining version-1 decoding.

```text
W = (id, I, G, intention, operators, input, budget, time, placement)
```

- `id`: workload identity.
- `I`: hosted-system identity `SystemIdentity(system_id, incarnation)`.
- `G`: `VirtualGroundRef(origin_digest, state_digest, coordinate, frontier_digest)`.
- `intention`: finite JSON object containing a `goal` description and optional constraints.
- `operators`: ordered operator references containing ID, version, preferred substrate, optional target node, and optional structural-memory bindings.
- `input`: finite JSON value supplied to the selected operator.
- `budget`: ceilings for virtual energy, encoded bytes and virtual ticks.
- `time`: non-negative logical coordinate.
- `placement`: eligible node labels and a hop ceiling reserved for the Path-State scheduler.

The ground reference binds the origin digest, current state digest, coordinate and digest of the admitted external-input frontier. The receiver compares the complete reference and system incarnation with its locally admitted `SystemSeedEnvelope`. An unadmitted, stale or conflicting ground is refused before operator execution.

Workload data is restricted to finite canonical JSON. Object keys must be strings; non-finite floating-point values and arbitrary Python objects are rejected. Input and intention containers are detached and frozen after construction. The workload digest is SHA-256 over its canonical serialization.

## 3. Operator contracts

An `OperatorSpec` is declarative metadata:

```text
O = (id, version, input_kind, output_kind, substrates,
     required_rights, cost, bounds, deterministic, effect_mode)
```

Supported JSON kinds are `any`, `object`, `array`, `integer`, `number`, `string`, `boolean` and `null`. Substrate labels are `cpu`, `gpu`, `fpga`, `dpu`, `network`, `memory`, `sensor` and `delay-loop`.

The first distributed executor admits only contracts declaring:

```text
deterministic = true
effect_mode = pure
```

State-changing, idempotent and transactional operators remain on existing native adapters until their transaction and recovery contracts are explicitly connected. This is a contract and local trust boundary, not a Python sandbox or proof of purity: handlers are ordinary trusted local callables. The registry owner is responsible for ensuring a handler declared pure does not mutate external state.

`OperatorRegistry.declare(spec)` installs metadata only. `bind(id, version, handler)` attaches an explicitly trusted node-local implementation. Handler code is never serialized, imported or transmitted. A receiving node must bind its own implementation before execution.

Compatibility is bound to the selected operator's contract digest, not the entire node catalog. Nodes can host different additional operators while agreeing on the exact contract used by a workload. The catalog digest remains available for local inventory and checkpoint identity. By default an operator requires the `compute` right; a contract can require additional rights.


## 3.1 Structural-memory inputs (workload schema v2)

A schema-v2 `VirtualOperatorRef` may declare one or more `VirtualStructuralMemoryRef` values. Each reference contains:

```text
R = (binding, memory_id, revision, context, coordinate,
     spec_digest, certificate_digest)
```

The reference is an address, not a generator or executable description. Its specification and certificate digests pin the intended immutable revision more strongly than a revision number alone. The receiver must already possess that admitted revision in its local `HeadlessOS.structural_memory` registry.

After the workload has passed ground validation and the hypervisor has granted the operator request, the receiver requires its own process to hold `read` on `/structural-memory/read`. It resolves the exact revision and context through `read_revision`, then checks the returned receipt against the reference's memory identity, revision, coordinate, context digest, specification digest, and certificate digest.

The operator receives one object envelope:

```json
{
  "input": {"...": "original workload input"},
  "structural_memory": {
    "binding-name": {
      "value": 123,
      "receipt": {"...": "complete StructuralMemoryReadReceipt"}
    }
  }
}
```

Consequently, an operator using structural-memory bindings must declare `input_kind="object"` or `"any"`. Each binding name is unique within its operator reference. The result effect includes the resolved-input digest and every full structural-memory receipt. Since the references are part of the canonical workload digest, the existing hypervisor semantic ledger binds retries to the same pinned memory addresses and replays the original result without repeating the reads.

Sender-side preflight energy accounting includes the serialized input and reference descriptors. The receiver separately applies the declared input and workload byte limits to the fully resolved value-and-receipt envelope. These virtual estimates do not claim measured physical energy or include a hardware-specific generator cost.

A structural-memory binding is read-only. This integration does not replicate memory between hosts, transfer generator descriptions, permit context-to-parameter learning, or make an operator's handler code portable. Registry admission and witness provenance remain governed by the Structural Memory contract.


## 4. Hypervisor integration

`VirtualLayerRuntime.build_event()` converts a workload/operator reference into a `HypervisorArbitrationEvent`. This first adapter uses the existing `HypervisorDomain.CPU` route because the current domain algebra has no separate Virtual Layer domain. This is an adapter choice, not a claim that every operator physically executes on a CPU. The operator's substrate contract determines eligible local implementations.

For local execution, `execute_operator()` prepares the typed event, asks `HeadlessOS.hypervisor_authorize_event()` to reconstruct local grants, and calls `HypervisorArbitrationLoop.execute()`.

Before the event is submitted for arbitration, `VirtualLayerRuntime` builds a
compact `mailcpu.virtual-layer.intent.v1` projection. It binds the workload
identity/digest, E-CPU System and Ground coordinate, declared goal, selected
operator contract/reference, full input digest and byte extent, pinned
Structural Memory references, resource budget, logical time, placement and
recalculated virtual-cost claims. The projection has a 4 KiB canonical JSON
bound. The full workload and input remain in the event payload and its
fingerprint.

The receiver reconstructs the workload, resolves its local operator
contract, remeasures the input and cost, rebuilds the projection, and requires
exact equality before preparing the handler. `HeadlessOS` preserves this
projection while replacing sender grants with receiver-local rights. The
classifier sees the compact projection; the operator receives the complete
decoded input. A mismatched projection is rejected before the handler can run.

For remote execution, `receive_and_execute()` composes with `HypervisorOperationChannel.receive_and_execute()`. It validates the peer-bound frame while it remains pending, reconstructs the workload, checks the selected operator contract and Ground identity, resolves a local handler, replaces any sender-side grant claim with receiver-local process capabilities, and then submits the operation to the existing hypervisor. The reliable request is acknowledged only after a typed execution result exists. Exact retries return the cached effect; a changed payload under the same source/channel/sequence identity is refused by the existing arbitration/effect ledger.

The receiver checks that declared rights match its local operator contract. Sender-provided `granted_rights` are not trusted. Missing local rights produce `DENY` and no handler call. Classifier and intent-model outputs remain proposals; neither can grant authority.

## 5. Cost and placement

For input byte count `b`:

```text
E_op = base_energy + energy_per_byte * b
T_op = max(1, ceil(E_op / virtual_capacity))
```

Workload ceilings are intersected with node-local runtime ceilings and operator input/output bounds. Input size, estimated energy and virtual ticks are checked before dispatch. Output and combined input/output size are checked after the pure handler returns. These are virtual accounting units, not physical joules or measured network latency. The hypervisor independently records its existing representation cost and virtual-time receipt.

Eligible nodes, target node and preferred substrate are placement constraints, not capabilities. They cannot authorize a handler.

## 6. Result and goal semantics

A successful transformation returns a canonical effect containing workload and operator identities, operator-contract digest, receiving node, selected substrate, admitted ground, logical time, input and result digests, estimated energy/ticks, and JSON result.

The `goal` field is descriptive in this first stage. The executor does not yet interpret arbitrary goal predicates or prove that the result satisfies them. A later navigator/result-verifier must assign typed semantics to goals.

The existing hypervisor effect ledger binds the returned effect to the operation identity and decision receipt. Exact retransmission therefore returns the prior effect without invoking the handler again.

## 7. Boundaries and next stage

This milestone provides one pure operator per workload event. It does not yet implement multi-hop Path-State orchestration, goal-directed path search, automatic SIMD/SIMT partitioning, dynamic operator placement, public-Internet peer authentication, or a generalized algebraic Virtual Ground. Ordered operator references and `max_hops` reserve a future contract surface; they are not yet a scheduler.

The next stage is a Path-State machine that chains operator events while carrying the ground coordinate, input frontier, continuation, cumulative budget and receipt chain. A later Virtual Navigator can select compatible paths and certified state-space shortcuts. Algebraic shortcuts must preserve their law-certification horizon and verification obligations.

## 8. Verification

The acceptance witnesses cover canonical workload serialization (including legacy v1 and structural-memory v2), metadata-only catalog transfer, explicit local handler binding, hypervisor capability denial, receiver-local structural-memory reads with digest-pinned receipts, replay without duplicate handler or memory invocation, stale-ground and budget refusal, and real TCP loopback operations.

The TCP test is E1 loopback evidence, not evidence of public-Internet deployment.
