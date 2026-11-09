# MailCPU

A deterministic, headless virtual machine whose state, time, and authority are
expressed as message transitions over a communication substrate.

MailCPU is a reference implementation and specification of a message-backed
virtual machine architecture.

## 1. Scope

This document states what MailCPU is, how to run it, and its architecture.
Normative detail is distributed across the specifications indexed in
`docs/README.md`.

Defined terms follow `docs/GLOSSARY.md`.

## 2. System definition

A **MailCPU machine** is a triple `(pc, R, Q, O)`:

| Component | Domain | Meaning |
|---|---|---|
| `pc` | `N` | Program counter |
| `R` | `A -> Z` | Register valuation |
| `Q` | product of mailbox queues | Pending messages per address |
| `O` | `(A, Z)*` | Ordered output log |

Execution applies exactly one **transition** per step:

```text
T : (pc, R, Q, O) -> (pc', R', Q', O')
```

`T` is total and deterministic. It is defined by the nine-instruction set in
`docs/ARCHITECTURE.md` clause 4.

Every implementation of `T` agrees with the reference interpreter on
`(status, state, trace, outputs)` for every program, where `status` is the
terminal disposition.

### 2.1 Instruction set

| Instruction | Transition |
|---|---|
| `SET d, v` | `R[d] := v` |
| `COPY d, s` | `R[d] := R[s]` |
| `ADD d, l, r` | `R[d] := R[l] + R[r]` |
| `COMPARE d, l, r` | `R[d] := sgn(R[l] - R[r])` |
| `BRANCH c, t` | `pc := t` if `R[c] != 0`, else `pc := pc + 1` |
| `SEND m, s` | append `(m, R[s])` to `O`; enqueue one data message on `Q_m` |
| `WAIT m, d` | dequeue the FIFO head of `Q_m` into `R[d]`; block if `Q_m` is empty |
| `SYSCALL d, n, k=v...` | invoke the kernel boundary; store the integer result in `R[d]` |
| `HALT` | set halted; do not advance `pc` |

Register reads are non-consuming observations. Register writes replace the
register's single cell. Each instruction execution emits one code-token
message; each successful non-`HALT` transition emits the next instruction token.
A blocked `WAIT` re-emits its own token, so the state is resumable.

The reference and pure mailbox interpreters do not handle `SYSCALL`;
system calls are dispatched through the composed scheduler.

## 3. Composition

The instruction algebra is one layer of a stack. Each layer is substitutable
only below the layer above it.

```text
instruction set T            <- defined algebra, no authority
  transition boundary delta  <- (K, request) -> (K', reply, emitted)
    kernel                  <- capabilities, descriptors, processes, IPC
      virtual environment   <- namespaces, content-addressed files, paging
        headless OS         <- scheduler, paged memory, checkpointing, services
          network           <- E0 captured frames, E1 owned fabric
            reliability     <- acknowledgement, windows, replay
              trajectory    <- indexed, receipt-verified capture
```

`K` is the **kernel state**. `delta : (K, request) -> (K', reply, emitted)`.

Transport substitutions preserve feature semantics above the transport boundary;
transport faults are observable in `Q`, `O`, and the journal.

## 4. Invocation

The package provides a `mailcpu` console script.

```sh
python -m mailcpu <command> [options]
```

| Command | Effect |
|---|---|
| `boot` | Print the boot namespace projection |
| `make-image PATH` | Write the deterministic demonstration image |
| `run-image PATH` | Execute an image under a tick budget |
| `demo` | Boot, install, schedule, and report the demonstration image |
| `run-source PATH` | Install an assembly source file and execute it |
| `restore-run PATH` | Restore a checkpoint and continue its processes |
| `os-demo` | Execute source already resident in the virtual filesystem |
| `memory-demo` | Exercise private and shared memory through the native ABI |
| `network-demo` | Exercise routed owned datagrams through the native ABI |
| `registry-publish ROOT IMAGE` | Publish an image into a digest-addressed registry |
| `registry-list ROOT` | List validated registry entries |
| `lift SEQUENCE [--horizon T]` | Certify algebraic recurrence law and compute orbit leap |
| `bench [--iterations N]` | Benchmark reversible gate cycles, delay loops, and lifter |
| `substrate [--rtt-ms MS] [--loss-rate P] [--cycles C]` | Simulate WAN delay-loop circulation under burst loss |
| `chronofold [--ticks N]` | Execute reversible trajectory ledger analysis and phase accounting |

`cli._COMMANDS` defines the declared command domain.

### 4.1 Development verification

```sh
python -m pytest                 # full suite
python scripts/record_golden.py  # regenerate the golden trace fixture
python scripts/verify_repo.py    # link, invariant, and integrity checks
```

If the transition algebra `T` changes, `tests/golden_traces.json` is regenerated
with `scripts/record_golden.py`.

### 4.2 Callable Python utilities

The command-line interface is one entry point; `mailcpu` is also an importable
Python package. The package root exports the tested public surface, including
the assembler, interpreters, virtual machine and headless OS, reliable
transports, Transit compute sessions, structural-memory providers, navigation
and evidence-path utilities, and checkpoint/recovery coordinators.

A small entry point is:

```python
from mailcpu import assemble

program = assemble(
    """
    SET left, 19
    SET right, 23
    ADD answer, left, right
    HALT
    """
)
```

The returned `Program` is the validated instruction representation. It can
then be supplied to the relevant interpreter or execution environment; the
runtime does not silently select an execution regime or grant capabilities.

For persistent Transit paths, the callable surface includes
`TransitComputeSession.save_checkpoint()` and
`TransitComputeSession.from_checkpoint()`. For jointly persisted requester
and receiver state, `RecoveryCheckpointBundleStore.seal()` and
`load_latest()` add an independent quorum admission step before restore.
The fixed-membership recovery authority can run across independent processes
using `RecoveryLineageProcessParticipant`, `RecoveryLineagePeerClient`, and
`DistributedRecoveryLineageCoordinator`. `RecoveryLineageAuthorityService`
adds a reconnectable remote service protected by mutual TLS, and the
`mailcpu-recovery-authority` command runs one non-owner member under an
external process supervisor. The owner can connect with
`RecoveryLineagePeerClient.connect_mutual_tls()`; both certificate-chain and
DNS-SAN identities are verified before the reliable channels are opened.
The `RecoveryLineageDeployment` model and `mailcpu-recovery-topology` command
validate exact membership coverage, unique declared placement-node/failure-domain/TLS
identities, unique authority endpoints, and node-local journal/TLS resource paths.
The validator can export the normalized membership file consumed by each
authority service; its placement declarations remain operator assertions, not
physical-host attestation. See
[`docs/RECOVERY_LINEAGE_DEPLOYMENT.md`](docs/RECOVERY_LINEAGE_DEPLOYMENT.md).
See [`docs/RECOVERY_LINEAGE_PROCESSES.md`](docs/RECOVERY_LINEAGE_PROCESSES.md)
and [`docs/RECOVERY_LINEAGE_SERVICE.md`](docs/RECOVERY_LINEAGE_SERVICE.md)
for the process protocol, deployment procedure, failure semantics, and proof
boundary. The complete checkpoint capture/restore protocol remains in
[`docs/RECOVERY_BUNDLE.md`](docs/RECOVERY_BUNDLE.md).

The public API is intentionally broader than the CLI command set. Most
subsystems are configured objects rather than standalone shell commands:
they require explicit state, capabilities, transports, backend registrations,
or a fixed authority membership. The detailed specifications and executable
tests are the usage contract for those components. The project remains Alpha;
the root export list is a declared API surface, not a promise that every
experimental subsystem has the same maturity or compatibility guarantees.

## 5. Determinism

Subsystems are deterministic given their input state.

Logical time advances by one per accepted event, independent of host wall-clock
time or thread scheduling.

Results are reportable with an evidence tier as defined in `docs/ARCHITECTURE.md`
clause 6. Every JSON result emitted by the native CLI includes `evidence_tier`;
local deterministic execution is `E0`, while `network-demo` is `E1` because its
route is exercised over the implementation-owned fabric.

Checkpointable components serialize deterministically, and checkpoint restore
verifies state digest integrity.

## 6. Control plane

The **hypervisor** mediates between structured request state and effectful
handlers.

```text
state -> typed questions -> model proposals -> policy gate -> one authorised handler -> journal receipt
```

Handlers execute based on explicit capability permissions. Decisions are
recorded in the hash-chained event journal.

The detailed operational profile is [`docs/HYPERVISOR_PROFILE.md`](docs/HYPERVISOR_PROFILE.md).

The first Virtual Layer workload and node-local operator contract is specified in [`docs/VIRTUAL_LAYER_WORKLOAD.md`](docs/VIRTUAL_LAYER_WORKLOAD.md).
The bounded transit execution path and deterministic multi-path orbit scheduler are specified in [`docs/TRANSIT_PATH_STATE.md`](docs/TRANSIT_PATH_STATE.md) and [`docs/TRANSIT_COMPUTE.md`](docs/TRANSIT_COMPUTE.md).

## 7. Repository layout

```text
mailcpu/     importable runtime package; VM, hypervisor, operator and substrate adapters
tests/       conformance, differential, protocol, runtime, and surface tests
scripts/     golden-trace recorder and repository verifiers
examples/    assembly source fixtures and reproducible benchmark scripts
docs/        specifications, architecture, invariants, glossary
```


The E-GPU is a composite logical host for navigable lane-wise methods. It routes vector addition and multiplication through the existing bounded SIMT reference interpreter, exposes a deterministic tree-reduction method, and now includes an explicit workgroup/shared-memory route with barrier-published visibility and Transit checkpoint/replay coverage. Register EGPUHost as an exact TransitBackendRouter backend; the receiver still authorizes /gpu/egpu through its local kernel capabilities. This is a reference operational structure, not physical GPU support or a speedup claim. See [COMMUNICATION_HOST_MODEL.md](docs/COMMUNICATION_HOST_MODEL.md) and [EGPU_NAVIGABLE_FABRIC.md](docs/EGPU_NAVIGABLE_FABRIC.md).


## Hosted VGI computational domain

E-CPU can host the independently versioned Virtual Ground Interpreter through the Virtual Layer operator `vgi.signal8.execute@1`. The adapter preserves the distinction between the admitted E-CPU system Ground and VGI's mathematical computational Ground, executes typed Signal8 tasks without semantic integer decoding, and returns signal-valued outputs, trace evidence, and a VGI checkpoint. Transit checkpoint schema v3 also binds the VGI route to its implementation source/profile fingerprint and refuses restore if that identity changes. Install the optional integration with `python -m pip install ".[vgi]"`. See [VGI_VIRTUAL_LAYER.md](docs/VGI_VIRTUAL_LAYER.md), [VGI_TRANSIT_SEMANTIC_CONTINUITY.md](docs/VGI_TRANSIT_SEMANTIC_CONTINUITY.md), and [COMPUTATIONAL_ADDRESSING.md](docs/COMPUTATIONAL_ADDRESSING.md) for the contract, recovery proof, and broader addressing model. The receiver-local `ComputationalAddressResolver` now maps a typed address to an eligible logical host and emits a non-authoritative route witness after checking Ground, operator/program identity, placement, budget, pinned state references, and live local capabilities. It does not evaluate a pinned Structural Memory coordinate, execute the request, or discover remote hosts. The `ComputationalExecutionAdmissionCoordinator` re-resolves that exact witness immediately before handoff, verifies the concrete local runtime against its selected locus, and places deterministic admission context in the ordinary Virtual Layer event fingerprint. The existing Hypervisor still performs capability reconstruction, policy arbitration, and effect/replay commit; the witness is never an execution grant. The `ComputationalFabricDirectory` and `ComputationalFabricResolver` exchange peer-owned host snapshots over direct mutual-TLS connections and plan bounded cost-aware multi-hop routes. The current `ComputationalFabricForwardingClient` and `ComputationalFabricForwardingServer` also execute bounded per-hop operations: each receiver revalidates its adjacent live leases, rebuilds local authority, and returns a typed hop receipt. Per-peer forwarding state can be quorum-anchored and restored against fresh TLS streams. The new `VGIFabricSessionOperator` composes an M7 VGI transfer bundle with this forwarding path: C imports its own M1 pages, verifies the original M3 proof, and advances the same session through M4 after local Hypervisor admission. The end-to-end A→B→C experiment checks descriptor, Ground, Program, artifact, revision, logical time, predecessor checkpoint, and replay identity while recording export, transfer, verification, persistence, and compute durations. These experiments establish selected deterministic process-recovery paths, not global atomic transactions or exactly-once arbitrary external effects. See [FABRIC_VGI_SESSION_COMPOSITION.md](docs/FABRIC_VGI_SESSION_COMPOSITION.md) for the full contract and measurement dimensions. The directory checkpoint retains revision anti-rollback state across reconstruction; `ComputationalFabricRecoveryStore` now persists and anchors that state under the existing strict-majority recovery lineage while requiring fresh direct-TLS observations to reactivate remote peers. See [COMPUTATIONAL_FABRIC.md](docs/COMPUTATIONAL_FABRIC.md) for the cross-codebase integration map.

Communication streams are typed carriers of computational state, not computation by themselves. A stream becomes part of a computational path when its receiver has a declared host identity, interpretation, transition, capability policy, resource bounds, and lineage. The receiver decodes and interprets a request, validates it against local state, performs an admitted transition, and emits a typed continuation or receipt. Large requests may carry a compact, receiver-recomputed intent projection for bounded interpretation while retaining the complete payload and digest in the event, replay ledger, transport and handler path; semantic interpretation cost and data-materialization cost are therefore distinct but neither is free. This is computation distributed across operational hosts; it does not bypass receiver processing or make physical network propagation equivalent to CPU or GPU instruction execution. See [COMMUNICATION_STREAM_COMPUTATION.md](docs/COMMUNICATION_STREAM_COMPUTATION.md) for the model and its finite-observer limits.


## Computational byte objects and time

E-CPU now has an initial content-addressed byte-object layer over the existing
page-backing contract. It separates immutable artifact identity from host
placement, temporal operation order, and domain-specific interpretation.
The M0 mathematical contract and M1 implementation boundaries are documented
in [COMPUTATIONAL_OBJECTS_AND_TIME.md](docs/COMPUTATIONAL_OBJECTS_AND_TIME.md)
and [TRANSIT_BYTE_OBJECTS.md](docs/TRANSIT_BYTE_OBJECTS.md). The first
implementation composes `ComputationalObjectStore` with existing local,
structural-memory, or remote page backings; it does not yet provide a universal
runtime, model-session transaction, or partitioned neural executor.


## General computational hosting

M2 adds a backend-neutral local computational host over the existing byte
object substrate. Composite artifact manifests bind multiple component files,
and backend profiles independently identify the trusted implementation,
runtime declarations, device profile, configuration, substrates, and resource
bounds. A local adapter exposes load, execute, and unload; the common core
does not import any specific model or accelerator framework.

Execution uses the existing Virtual Layer and Hypervisor authority path.
Deterministic result receipts are distinct from process-local duration
measurements and from durable Hypervisor commitment. See
[COMPUTATIONAL_HOSTING.md](docs/COMPUTATIONAL_HOSTING.md) for the mathematics,
adapter contract, tests, and current proof boundaries.


## Persistent computational sessions

M3 adds a general, domain-neutral state checkpoint and continuation layer.
Session identity is isolated by a fixed recovery membership; versioned state
payloads are stored in the existing M1 page/object substrate; and each
checkpoint is admitted as the quorum high-water through the existing recovery
lineage. Continuation uses compare-and-swap against both expected revision and
checkpoint digest. A portable checkpoint export can be restored by another
host when the same artifact/state schema, recovery membership, and M1 pages
are available; a changed backend profile requires explicit compatibility
approval. See
[COMPUTATIONAL_SESSIONS_AND_STATE.md](docs/COMPUTATIONAL_SESSIONS_AND_STATE.md).


## Stateful interpretation and compiled Ground plans

M4 adds a domain-neutral ComputationalSessionTransitionAdapter: it starts
from a verified M3 snapshot, invokes a declared deterministic pure backend
with a context bound to the exact checkpoint, quorum lineage, artifact,
backend, state schema, interpretation, input, and logical time, then publishes
candidate bytes through the existing session CAS and quorum seal. It does not
guess semantics from opaque state bytes and does not atomically commit
arbitrary external side effects.

For the optional VGI integration, typed tasks compile under the explicitly
declared Signal8 Computational Ground into immutable Program IR. A bounded
cache reuses only that compiled plan for matching Ground, compiler
implementation, and canonical task identities. Each execution constructs a
fresh mutable machine from its own inputs; M1 state and quorum-anchored
session checkpoints remain the authority. See
[COMPUTATIONAL_SESSION_INTERPRETATION.md](docs/COMPUTATIONAL_SESSION_INTERPRETATION.md)
and [VGI_VIRTUAL_LAYER.md](docs/VGI_VIRTUAL_LAYER.md).

## Persistent VGI sessions and transit

M5-M7 connect the VGI compiled interpretation to the persistent computational
session substrate. A descriptor binds Signal8 Ground, typed task, immutable
Program IR, implementation identity, and M2 artifact manifest. Machine state
is stored as canonical VGI checkpoints in M1 and becomes current only through
M3's quorum-anchored revisions.

Execution advances in bounded instruction quanta via the M4 pure transition
adapter. Each quantum uses revision/checkpoint compare-and-swap, preserves
logical-time progression, and supports exact immediate retry without
re-entering an already committed quantum. Cumulative step and state limits
bound the session independently from per-quantum limits.

A portable transfer package carries the descriptor, M3 proof, M1 manifest,
and bounded state bytes. A target re-admits state into its own M1 store,
requires matching page geometry, verifies the source quorum high-water, and
requires explicit compatibility approval for a changed execution backend
or VGI implementation. The current transfer format embeds bounded state
bytes in base64 JSON rather than streaming them. See
[VGI_PERSISTENT_SESSIONS_AND_TRANSIT.md](docs/VGI_PERSISTENT_SESSIONS_AND_TRANSIT.md).


## Operation-native computation and timing

E-CPU can compile the bounded straight-line MailCPU subset into register-definition DAGs and dispatch ready ADD, COMPARE, and MUL frontiers through the existing Virtual Layer and authenticated computational fabric. The portable operation contract is separate from its receiver-local CPU or E-GPU realization; typed receipts and predecessor lineage remain attached to the DAG. The fabric resolver exposes a bounded, deterministically ranked set of eligible host/route alternatives while preserving the original single-winner API; these proposals remain non-authoritative. Homogeneous binary frontiers can now be split into stable child requests, each addressed and routed independently to a distinct logical host. Every child uses the existing authenticated forwarding path and terminal Hypervisor / Virtual Layer admission. Typed child receipts are retained in one composite parent receipt, and the original DAG frontier commits only after aggregate scalar-oracle verification.

Start with [PROGRAM_DATAFLOW_COMPILATION.md](docs/PROGRAM_DATAFLOW_COMPILATION.md) for the assembly-to-DAG contract, [OPERATION_NATIVE_COMPUTATIONAL_FABRIC.md](docs/OPERATION_NATIVE_COMPUTATIONAL_FABRIC.md) for routing and receiver execution, and [CONTEXTUAL_ORBIT_FABRIC.md](docs/CONTEXTUAL_ORBIT_FABRIC.md) for state-space inverse navigation and typed predecessor evidence.

To compare local CPU, remote CPU and remote E-GPU placement with separate measurements for transport, receiver admission, provenance validation, backend execution, origin verification and total completion, run:

```sh
python examples/operation_frontier_benchmark.py --warmups 1 --iterations 5 --lanes 64 --multiplier-bits 2048 --output operation-frontier-timing.json
```

The benchmark uses a one-hop mutual-TLS loopback route and requires OpenSSL to create ephemeral test certificates. It checks each placement against the MailCPU reference interpreter. Its timings are endpoint-local observations, not a WAN latency or physical GPU speedup claim. [OPERATION_FRONTIER_TIMING.md](docs/OPERATION_FRONTIER_TIMING.md) explains the measurement phases, nested intervals, clock-domain rules and interpretation boundaries.

Every prepared ready frontier is now published through one atomic DAG commit boundary. Exact whole-frontier retries are idempotent; malformed, partial or conflicting batches refuse without publishing a sibling result. The operation-native executor performs this commit only after the complete frontier has passed receipt and scalar-oracle verification. See [NAVIGABLE_COMPUTATION_DAG.md](docs/NAVIGABLE_COMPUTATION_DAG.md).

[BINARY_FRONTIER_PARTITIONING.md](docs/BINARY_FRONTIER_PARTITIONING.md) describes the exact child partition model. [PARTITIONED_BINARY_FRONTIER_EXECUTION.md](docs/PARTITIONED_BINARY_FRONTIER_EXECUTION.md) documents authenticated per-child dispatch, composite receipts, resumable progress, stable origin-sequence windows and bounded concurrency across independent next-hop streams. Recovery skips verified children and retries incomplete children through their original route/sequence; ambiguous effects are not silently rehomed to another host because receiver-local ledgers do not yet establish cross-host exactly-once semantics.

[TRANSFERABLE_EXECUTION_CLAIMS.md](docs/TRANSFERABLE_EXECUTION_CLAIMS.md) specifies the quorum claim authority. [CLAIM_BOUND_FABRIC_ADMISSION.md](docs/CLAIM_BOUND_FABRIC_ADMISSION.md) documents its integration into actual partitioned computation: all child tickets are issued under one root, carried by forwarding envelope v2, checked by the terminal Host against live quorum and local OperatorSpec before Hypervisor admission, rechecked by the origin after response, and completed as one parent-level quorum transition. The composite preserves both the admission ticket and completion ticket. Automatic child rehoming remains the next orchestration step. The guarantee is single-winner semantic result acceptance for deterministic pure operations, not exactly-once physical execution or authorization for arbitrary external side effects.

The benchmark also emits immutable empirical placement profiles for local CPU, remote CPU and remote E-GPU. Each observation binds the exact compiled workload, origin-local total-completion sample, verification digest, and (for remote runs) the complete typed frontier receipt. Profiles are comparable only when their workload class, operator contract, Computational Ground and origin environment match. A ranking requires at least three observations per placement by default and remains advisory; it does not bypass live fabric resolution or receiver Hypervisor admission. See [PLACEMENT_PROFILES.md](docs/PLACEMENT_PROFILES.md).
