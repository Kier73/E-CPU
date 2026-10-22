# MailCPU Replacement Specification

Normative specification of the MailCPU replacement system, the criteria by which
its operation is evaluated, and the surfaces its transition algebra covers.

Defined terms follow `docs/GLOSSARY.md`.

## 1. Purpose

MailCPU is a native, portable, replayable virtual environment whose underlying
machine is communication infrastructure. It provides the workflows in clause 3
through its own state, authority, memory, time, and communication algebra.

Linux implementation internals are not the organizing model.

## 2. System boundary

The system defined under this document is bounded by:

1. the acceptance criteria in clause 3;
2. the **evidence tier** of every result reported, per
   `docs/ARCHITECTURE.md` clause 6;
3. the staged obligations in clause 9;
4. the governing rule in clause 10.

Future substrate stages extend these same boundaries through explicit builds.

## 3. Acceptance criteria

MailCPU satisfies the replacement system when all seven criteria hold.

**AC-1** A project can boot a reproducible environment on the host without a
Linux kernel.

**AC-2** A project can install an executable image and its files as
content-addressed artifacts.

**AC-3** A project can run multiple programs with independent memory, processes,
IPC, files, devices, and capabilities.

**AC-4** A project can persist, snapshot, replay, and inspect all state
transitions.

**AC-5** A project can move selected channels from local queues to real
communication paths without changing the feature-level ABI.

**AC-6** A project has a practical native CLI and developer workflow.

**AC-7** Failures are explicit and recoverable rather than hidden behind
compatibility shims.

**REQUIRED** Each criterion MUST be discharged by at least one test. A criterion
discharged by assertion alone does not satisfy this clause.

## 4. Native path

```text
image
  -> booted root namespace and capabilities
  -> content-addressed files and paged memory
  -> round-robin scheduled programs
  -> bus IPC and typed syscall protocol
  -> fault model and reliable channel
  -> replayable journal and checkpoint
```

## 5. Command surface

```sh
python -m mailcpu demo
python -m mailcpu boot
python -m mailcpu make-image work/demo.mcp.json
python -m mailcpu run-image work/demo.mcp.json
python -m mailcpu os-demo
python -m mailcpu memory-demo
python -m mailcpu run-source examples/countdown.mca --trajectory-dir work/trajectory
python -m mailcpu run-source examples/countdown.mca --max-ticks 5 --checkpoint-out work/partial.mcpu.json
python -m mailcpu restore-run work/partial.mcpu.json --max-ticks 100
python -m mailcpu registry-publish work/registry work/demo.mcp.json
python -m mailcpu registry-list work/registry
```

`work/` is a generated-artifact path and is excluded from version control.

## 6. Conformance

**REQUIRED** A workload MUST pass against the reference semantics before its
compatibility stage is admitted, per clause 10.

**REQUIRED** The result MUST be replayable from the recorded communication
trajectory.

**REQUIRED** Differential conformance MUST cover programs with blocking `WAIT`
both preceded and followed by `SEND`, message FIFO ordering, and
identity-consuming reads.

## 7. Specified surfaces

The following surfaces are specified. Each entry states its contract; the
governing rules are `docs/ARCHITECTURE.md` clauses 3 and 5.

### 7.1 Execution

Assembly source is stored in the virtual filesystem, compiled into the validated
instruction graph, launched as a kernel process, scheduled by the deterministic
scheduler, and inspected through process reports or the shell surface.

Portable image v2 carries a bounded tagged binary executable payload. Loading
reconstructs the program from bytes, checks it against the readable graph, and
refuses corruption or disagreement before scheduling. v1 graph-only images
remain migration-readable.

**REQUIRED** A bounded run reaching its tick budget MUST remain explicitly
`runnable`. An empty `WAIT` MUST remain `blocked`. Neither disposition is
converted into a success.

Mailbox injection wakes a blocked task through the scheduler. Explicit
termination records a caller-selected exit code. Long-lived services have
declarative restart budgets. Checkpoint and restore continue a saved scheduler
orbit with integrity verification. Executable loading crosses kernel
descriptors. Suspension and resumption are explicit virtual states.

### 7.2 Control plane

The control plane carries scoped process environments and typed
`TERM/KILL/STOP/CONT/INT/QUIT/HUP` signals.

```text
request state
  -> Choice(domain) and Noul(danger)
  -> capability, confidence, and destructive policy
  -> ALLOW | REVIEW | DENY, with a journal receipt
```

Model output does not possess authority over the host.

External classifier internals are not imported as the system's architecture.

### 7.3 Network

Native image artifacts are stored by SHA-256 in a local registry.

The network boundary comprises an E0 captured-frame driver with journaled TCP
state, HTTP semantic events, malformed-frame rejection, and deterministic HDC
projection; and an E1 owned namespace, interface, and link fabric with
deterministic multi-hop forwarding, bounded byte queues, route and MTU evidence,
capability-gated memory transfers, process-owned typed datagram and bounded
stream and port layers, exact-reap cleanup, and shared descriptor-backed socket
I/O.

**REQUIRED** Controlled external networking enters through the framed
`SocketTransport` boundary. Public infrastructure is a later E2 stage; semantic
network state remains independent of host socket details.

### 7.4 Processes

The process boundary carries argument vectors, parent, group, and session
identity, inherited environments and capabilities, and optional inherited
descriptors. `setsid`, `setpgid`, `getpgid`, and `getsid` enforce explicit
session membership rules. `signal-group` provides deterministic PID-ordered
fan-out. The complete ABI state is included in checkpoints. Descriptor-backed
pipes provide bounded FIFO IPC with explicit would-block, broken-pipe, capacity,
and restore behaviour.

Process context is addressable from scheduled userland. Exact size queries and
atomic memory transfers expose NUL-packed `argv`, sorted `KEY=VALUE`
environment records, and the working directory.

**REQUIRED** The kernel MUST reject embedded NULs so the representation remains
injective.

**REQUIRED** An undersized destination MUST return `-ERANGE` before mutation.

Context-transfer receipts survive checkpoint continuation.

### 7.5 Terminals

Dynamic pseudo-terminals are communication resources. `pty_open` and
`pty_open_into` create connected master/slave descriptors. The slave applies
session, foreground-group, canonical, raw, and echo rules. Both queues and peer
identities participate in checkpoint and restore, and in last-alias
reclamation.

With `ISIG`, `Ctrl-C`, `Ctrl-Z`, and `Ctrl-\\` produce foreground-group `INT`,
`STOP`, and `QUIT` events, updating scheduled and kernel-only process state
through one journaled path.

Canonical input implements checkpointable `VERASE`, `VKILL`, and `VEOF`. Edit
controls alter only the current line. Echo projects the edit back to the master.
EOF is an explicit readiness event, not an incidental empty read. Raw mode
preserves control bytes.

A last-master close marks the surviving slave as hung up, preserves queued bytes
followed by EOF, reports `POLLHUP`, and emits one foreground-group `SIGHUP`.
Terminal liveness and the scheduler bridge survive checkpoint restore.

Signal disposition is an explicit process relation with integer-safe
`signal_set_ignored` and `signal_is_ignored` calls. Default and ignore state are
inherited and checkpointed.

**REQUIRED** `SIGKILL` and `SIGSTOP` are non-ignorable.

### 7.6 Executable lifecycle

`execve` loads an execute-mode virtual file through kernel descriptors,
assembles it before mutation, and replaces program, registers, scheduler orbit,
and private memory while preserving PID, descriptors, authority, environment,
and lineage. The same transition is available through the typed bus syscall
server.

`exec` validates the replacement image and commits it after the trap, so the
prior instruction stream cannot continue.

The executable boundary parses and stages ELF32 and ELF64 program headers.
`PT_LOAD` segments are bounds-, alignment-, and overlap-checked. File bytes are
copied into virtual pages, BSS remains zero-filled, writable protections are
applied, and entry, interpreter, and dynamic metadata are journaled.

**REQUIRED** Unsupported foreign instruction execution MUST fail closed.
Relocation, dynamic linking, stack and auxiliary-vector construction, and CPU
emulation are not provided.

### 7.7 Instruction plane

The instruction plane provides a native `SYSCALL` trap. A scheduled program
supplies a syscall name and typed `key=value` operands, including `$register`
references. The composed OS routes the transition through the
capability-checked kernel ABI, writes integer results back to the program
register file, and treats `exit` as a terminal scheduler transition.

**REQUIRED** The reference and mailbox interpreters MUST refuse `SYSCALL`. They
possess no kernel authority.

Exited children have a native `waitpid` boundary. A parent uses `nohang` for an
explicit empty result and receives deterministic PID-ordered exit records.
Reaping releases the child's scheduler state, private memory, descriptors, and
process-table entry. Zombie state is checkpointable until reaped.

### 7.8 Ownership

The kernel has an explicit init and adoptive parent. When a parent exits, live
descendants are reparented to init and the `process.adopt` transition is
journaled.

`set_subreaper` and `get_subreaper` expose a checkpointed process-local policy
bit. Adoption selects the nearest live subreaper in the ancestor chain before
falling back to init.

**REQUIRED** Service supervision MUST consume its own exited children with
`waitpid` before restart or terminal convergence, so that repeated service
failure does not leak process or resident-memory state.

### 7.9 Memory

The memory boundary is a native ABI. `mmap` reserves virtual pages using
deterministic first-fit allocation or an optional hint. First access performs
zero-fill demand paging. `mem_reclaim` moves private pages to content-addressed
backing, and later access faults them back losslessly. `read_into` and
`write_from` transfer descriptor bytes through process memory after non-mutating
page preflight. `munmap` and `mprotect` change the virtual map atomically.
`mem_read`, `mem_write`, and `mem_info` operate on process-local page images.
`shm_create`, `shm_attach`, and `shm_detach` operate on named shared regions.

**REQUIRED** Per-process and VM-wide resident quotas and capability checks MUST
fail before mutation.

**REQUIRED** Unreserved accesses MUST produce typed page faults.

Shared-region identity is validated across checkpoints.

### 7.10 Protocol

The typed syscall protocol targets the headless OS. Byte arguments and results
use an injective hex wire representation.

**REQUIRED** Malformed or failed memory calls MUST remain `Err` responses on the
bus rather than being converted into success.

The bus syscall server provides a transaction identity layer. Each request ID is
fingerprinted and its `Ok` or `Err` response is cached. Redelivery replays the
cached response without repeating side effects.

**REQUIRED** The same request ID with different contents MUST be refused.

### 7.11 Communication and persistence

Reliable communication control state is checkpointable: sequence counters,
pending frames, retry leases, deduplication identities, failed sequences,
delayed fault frames, FIFO message identities, and transport clocks restore
together.

The communication substrate provides a local durable mailbox transport.
Hash-chained append records persist binary-safe enqueue, dequeue, and consume
events; replay restores queue and identity state after reopen; tampered complete
records are refused; and only an incomplete final append is truncated. Reliable
pending frames and acknowledgements continue across a transport restart.

Reliable channels enforce a checkpointed sender-side sequence window.
`window_size` bounds in-flight frames, a full window returns explicit
backpressure, and acknowledgement or bounded retry failure releases a slot.

**REQUIRED** A digest MUST NOT be computed over a non-canonical encoding.
`mailcpu/_codec.py` clause 1 defines the canonical algebra and its required use.

### 7.12 Descriptors

Shared open-file descriptions are specified for `dup`, `dup2`, inheritance, pipe
endpoints, rename, checkpoint restore, and descriptor-local close-on-exec flags.

## 8. Beyond POSIX

POSIX is a guest-facing compatibility surface, not the kernel's organising
principle. The native ABI is a typed state-transition protocol:

```text
request      = (capability, operation, operands, correlation_id)
δ(request, state) = (new_state, reply, emitted_messages)
```

**REQUIRED** The same operation MUST be carryable by a local mailbox, a socket,
a relay, or a controlled mail path without altering its semantics.

Identity, ordering, authority, persistence, acknowledgement, expiry, and replay
are first-class parts of the virtual machine.

## 9. Staged obligations

The following stages remain to be built into the same system:

1. POSIX compatibility, distribution packaging, and host namespace integration.
2. Foreign CPU instruction execution through dynamic ELF relocation and linking.
3. Public infrastructure and E2 operation above controlled external networking.
4. Replicated multi-host durability and cross-host transactional commit.
5. Receiver-advertised windows and congestion control.
6. Full `termios` compatibility: handler installation, signal masks, restart
   semantics, and signal-frame ABI.
7. `epoll` edge and one-shot semantics.
8. Reproduction of any undisclosed third-party internal architecture.

## 10. Governing rule

No compatibility stage is admitted until the same workload passes against the
reference semantics and the result is replayable from the recorded
communication trajectory.
