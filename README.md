# MailCPU

A deterministic, headless virtual machine whose state, time, and authority are
expressed as message transitions over a communication substrate.

MailCPU is a reference implementation and specification. It is not a Linux
distribution, a container runtime, or a hypervisor for foreign CPU
architectures. Section 8 enumerates the non-goals that fix this boundary.

## 1. Scope

This document states what MailCPU is, how to run it, and what it does not
claim. Normative detail is distributed across the specifications indexed in
`docs/README.md`.

Defined terms follow `docs/GLOSSARY.md`. Writing conventions follow
`docs/STYLE.md`.

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

**REQUIRED** Every implementation of `T` MUST agree with the **reference
interpreter** on `(status, state, trace, outputs)` for every program, where
`status` is the terminal disposition.

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

**REQUIRED** The reference and pure mailbox interpreters MUST refuse `SYSCALL`.
Neither possesses kernel authority. `SYSCALL` is reachable only from the
composed scheduler.

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

**REQUIRED** A transport substitution MUST NOT alter the semantics of any
feature above the transport boundary. Transport faults are observable as
distinctness in `Q`, `O`, and the journal, never as altered feature semantics.

## 4. Invocation

**REQUIRED** The package MUST install a `mailcpu` console script.

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

`cli._COMMANDS` is the declared command domain. `tests/test_cli_surface.py`
MUST assert that the parser's registered domain equals it exactly.

### 4.1 Development verification

```sh
python -m pytest                 # full suite
python scripts/record_golden.py  # regenerate the golden trace fixture
python scripts/verify_repo.py    # boundary, link, and style conformance
```

`scripts/record_golden.py` MUST NOT be run with a modified transition algebra.
Where `T` changes, `tests/golden_traces.json` MUST be regenerated and the
change MUST be justified in the commit message.

## 5. Determinism

**REQUIRED** Every subsystem MUST be deterministic given its input state.

**REQUIRED** Logical time MUST advance by exactly one per accepted event, and
MUST NOT be derived from wall-clock time, host scheduler time, or thread
identity.

**REQUIRED** Every result MUST be reportable with an **evidence tier** as
defined in `docs/ARCHITECTURE.md` clause 6.

**REQUIRED** Every state component admitted into a checkpoint MUST be
**check pointable**. Checkpoint restore MUST reject a state whose digest does
not match its content.

## 6. Control plane

The **hypervisor** mediates between structured request state and effectful
handlers.

```text
state -> typed questions -> model proposals -> policy gate -> one authorised handler -> journal receipt
```

**REQUIRED** Model output MUST NOT constitute authority. A handler is invoked
only on an explicit `allow` decision derived from the caller's kernel
capabilities.

**REQUIRED** Every decision MUST be recorded in the hash-chained journal.

Refusal rules, confidence arithmetic, and the external-model boundary are
specified in `docs/BOUNDARY_JEV.md`.

## 7. Explicit refusals

The following are specified as refusals, not as unimplemented work. They are
not obligations to be discharged.

| Surface | Refusal |
|---|---|
| `SYSCALL` in reference and mailbox interpreters | Refused; no kernel authority |
| Execution regimes other than `MAILCPU` | Refused; fail closed |
| Unsupported `O_*` / `F_*` bits | Refused with a typed failure |
| Non-zero blocking `poll` timeouts | Refused until wakeup ordering is provable |
| Descriptor transfer to a foreign creator | Refused |
| Reaping a child across parents | Refused |
| Journal records failing chain verification | Refused; the checkpoint is rejected |
| Capability-missing classifier requests | Denied, never reviewed |

## 8. Non-goals

MailCPU does not implement, and does not claim:

1. **Linux compatibility or distribution packaging.** No package manager, no
   `init` system integration, no host namespace sharing.
2. **Foreign instruction execution.** `parse_elf` validates and stages ELF32 and
   ELF64 images into process memory. It performs no relocation, no dynamic
   linking, no `libc` binding, and no CPU emulation.
3. **Public or host networking.** No host socket is opened. No relay, provider,
   or public infrastructure is contacted. All network evidence is tier `E0` or
   `E1`.
4. **Multi-host durability.** `DurableMailboxTransport` is a local, single-writer
   hash chain. Replicated commit and cross-host acknowledgement are not
   provided.
5. **Congestion control or receiver-advertised windows.** `ReliableChannel`
   implements a sender-side flow-control window only.
6. **Reproduction of any undisclosed third-party internals.** See
   `docs/BOUNDARY_JEV.md` and `docs/BOUNDARY_PROCEDURAL_MODEL.md`.
7. **Cryptographic primitives.** The vendored address permutation in
   `mailcpu/vl_procedural_primitives.py` provides no confidentiality, integrity,
   or compression.

## 9. Repository layout

```text
mailcpu/     importable package; 37 modules
tests/       conformance, differential, protocol, runtime, and surface tests
scripts/     golden-trace recorder and repository verifiers
examples/    assembly source fixtures
docs/        specifications, boundaries, style standard, glossary
```

## 10. Related documents

| Document | Subject |
|---|---|
| `docs/ARCHITECTURE.md` | State model, lifting table, capability model, evidence tiers |
| `docs/REPLACEMENT_SPEC.md` | Acceptance criteria for the replacement claim |
| `docs/INTEGRATION_SPEC.md` | Adopted mechanisms, integration boundaries, verification obligations |
| `docs/BOUNDARY_JEV.md` | External-model contract and refusal rules |
| `docs/BOUNDARY_PROCEDURAL_MODEL.md` | Procedural model and non-copying boundary |
| `docs/PLAN.md` | Research plan, hypotheses, and evidence procedure |
| `docs/STYLE.md` | Writing standard |
| `docs/GLOSSARY.md` | Defined terms |
| `docs/INVARIANTS.md` | Machine-checkable invariant registry |
| `AGENTS.md` | Operating procedure for automated contributors |
