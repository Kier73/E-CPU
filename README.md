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

`cli._COMMANDS` defines the declared command domain.

### 4.1 Development verification

```sh
python -m pytest                 # full suite
python scripts/record_golden.py  # regenerate the golden trace fixture
python scripts/verify_repo.py    # link, invariant, and integrity checks
```

If the transition algebra `T` changes, `tests/golden_traces.json` is regenerated
with `scripts/record_golden.py`.

## 5. Determinism

Subsystems are deterministic given their input state.

Logical time advances by one per accepted event, independent of host wall-clock
time or thread scheduling.

Results are reportable with an evidence tier as defined in `docs/ARCHITECTURE.md`
clause 6.

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

## 7. Repository layout

```text
mailcpu/     importable package; 37 modules
tests/       conformance, differential, protocol, runtime, and surface tests
scripts/     golden-trace recorder and repository verifiers
examples/    assembly source fixtures
docs/        specifications, architecture, invariants, glossary
```
