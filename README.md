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
examples/    assembly source fixtures
docs/        specifications, architecture, invariants, glossary
```


The E-GPU is a composite logical host for navigable lane-wise methods. It routes vector addition and multiplication through the existing bounded SIMT reference interpreter, exposes a deterministic tree-reduction method, and now includes an explicit workgroup/shared-memory route with barrier-published visibility and Transit checkpoint/replay coverage. Register EGPUHost as an exact TransitBackendRouter backend; the receiver still authorizes /gpu/egpu through its local kernel capabilities. This is a reference operational structure, not physical GPU support or a speedup claim. See [COMMUNICATION_HOST_MODEL.md](docs/COMMUNICATION_HOST_MODEL.md) and [EGPU_NAVIGABLE_FABRIC.md](docs/EGPU_NAVIGABLE_FABRIC.md).


## Hosted VGI computational domain

E-CPU can host the independently versioned Virtual Ground Interpreter through the Virtual Layer operator `vgi.signal8.execute@1`. The adapter preserves the distinction between the admitted E-CPU system Ground and VGI's mathematical computational Ground, executes typed Signal8 tasks without semantic integer decoding, and returns signal-valued outputs, trace evidence, and a VGI checkpoint. Transit checkpoint schema v3 also binds the VGI route to its implementation source/profile fingerprint and refuses restore if that identity changes. Install the optional integration with `python -m pip install ".[vgi]"`. See [VGI_VIRTUAL_LAYER.md](docs/VGI_VIRTUAL_LAYER.md), [VGI_TRANSIT_SEMANTIC_CONTINUITY.md](docs/VGI_TRANSIT_SEMANTIC_CONTINUITY.md), and [COMPUTATIONAL_ADDRESSING.md](docs/COMPUTATIONAL_ADDRESSING.md) for the contract, recovery proof, and broader addressing model.
