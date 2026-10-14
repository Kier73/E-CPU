# MailCPU Architecture

Normative specification of the MailCPU state model, its lifting of conventional
hardware surfaces, the capability model, and the evidence-tier vocabulary.

Defined terms follow `docs/GLOSSARY.md`.

## 1. Purpose

MailCPU specifies a virtual environment whose conventional hardware surfaces are
expressed as typed state transformations over communication paths. It is not a
remote shell, and it is not a wrapper that forwards commands across a network
link. Each surface below is defined by its state and its transition function,
independently of the substrate carrying its messages.

## 2. Feature decomposition

Every feature of the system is specified as a 7-tuple:

```text
Feature = (state, authority, request, transition, reply, persistence, failure)
```

Each element is total. A feature with an undefined element is not specified and
MUST NOT be exposed.

## 3. Kernel state and transition boundary

The kernel evaluates a request as a transition over a product state:

```text
K = (registers, pages, filesystem, mailboxes, processes, devices, routes, journal)
δ : (K, request) -> (K', reply, emitted_messages)
```

The instruction algebra beneath `δ` is:

```text
T : (pc, R, Q, O) -> (pc', R', Q', O')
```

**REQUIRED** `δ` MUST be total and deterministic on its domain.

**REQUIRED** `T` MUST be total on the domain of validated programs and MUST
return `step_limit` rather than halting when a step budget is exhausted.

### 3.1 Transport substitutability

The transport is substitutable only below `δ`.

A transport may alter latency, ordering, loss, duplication, and expiry. It MUST
NOT alter the semantics of any feature above the boundary. Transport faults are
observable as distinctness in `Q`, in `O`, and in the journal.

**REQUIRED** A change in transport behaviour MUST NOT be observable as a change
in the result of `δ` for an identical `K` and `request`.

## 4. Lifting of conventional surfaces

| Conventional surface | MailCPU lifting | Durable state / transition |
|---|---|---|
| CPU registers and instructions | Instruction algebra; instructions are messages | `T(pc, R, Q, O)` |
| RAM and pages | Content-addressed private pages, explicit shared regions, memory syscalls | `page_id = SHA256(page_bytes)`; fault is `f = (address, page, access)` |
| Process table | Capability-scoped task records and process mailboxes | `spawn`, `exit`, `send`, `receive` |
| System-call ABI | Typed request/reply messages on the kernel bus | `δ_syscall(process, request)` |
| Filesystem | Inode graph over immutable content blobs | directory edges + blob replacement |
| File descriptors | Per-process cursor and capability mappings | `offset' = offset + bytes_transferred` |
| Pipes and sockets | Addressed FIFO mailboxes | `Q_addr := Q_addr \\|\\| [message]` |
| Device files and drivers | Registered device endpoints behind `DeviceBus` | `read` / `write` driver contracts |
| Clock and scheduler | Journal sequence over logical time | `t := t + 1` per accepted event |
| Boot and init | Reproducible namespace bootstrap | fixed root tree + init PID |
| Crash recovery | Hash-chained journal and checkpoints | replay and audit boundary |
| Network interface | Bus destination names and transport adapters | route-specific delivery semantics |
| Classifier hypervisor | Shared request state with typed Choice/Score/Noul questions | decision receipt + `ALLOW/REVIEW/DENY` policy transition |

## 5. Capability model

Authority is explicit. A process holds a set of **capabilities**, each a pair
`(resource, rights)`. A path is authorised when both conditions hold:

1. the path lies within the subtree rooted at `resource`; and
2. the requested operation's right is a member of `rights`.

**REQUIRED** Authorisation MUST be a function of held capabilities alone.

**REQUIRED** Identity, argument validity, instruction origin, and model output
MUST NOT contribute to authorising an operation.

The purpose of the constraint is structural: without it, the premise that the
network constitutes the machine collapses into the premise that every endpoint
may write every state.

## 6. Evidence tiers

Every reportable result carries an **evidence tier**.

| Tier | Provenance | Permitted claim |
|---|---|---|
| `E0` | Captured frames, in-process emulation, or a deterministic fixture | The semantics execute as specified over the modelled substrate |
| `E1` | A substrate wholly owned by the implementation | The semantics execute over a real fabric with controlled endpoints |
| `E2` | Public or third-party infrastructure | The semantics execute over infrastructure outside implementation control |

**REQUIRED** Every reportable result MUST carry its tier.

**REQUIRED** A tier MUST NOT be asserted for a result whose substrate is not
present. Absence of a substrate is reported as a non-goal, not as an unmet
tier.

MailCPU reports `E0` and `E1` results only. No `E2` result is produced, and no
host socket is opened.

## 7. Implemented surfaces

The following surfaces are specified. Each states its contract; the governing
rules are `docs/ARCHITECTURE.md` clauses 3 and 5 and `docs/REPLACEMENT_SPEC.md`.

### 7.1 Execution substrate

- One transition algebra executes over a pure backend and a message-backed
  backend, with differential conformance required by
  `docs/REPLACEMENT_SPEC.md` clause 6.
- Registers, instruction tokens, inputs, outputs, filesystem files, IPC
  messages, and device streams have explicit state semantics.
- A deterministic fault transport exposes loss, duplication, delay, and
  reordering without altering the feature-level transition algebra.

### 7.2 Environment and processes

- The virtual environment boots a Unix-shaped namespace, performs
  file-descriptor I/O, enforces path capabilities, exchanges process messages,
  and emits a replayable journal.
- Multiple programs execute under a deterministic round-robin scheduler, with
  `SEND`/`WAIT` traffic waking blocked tasks over the virtual bus.
- The process ABI carries `argv`, parent PID, process group, session, inherited
  environment and capabilities, and optional descriptor inheritance. Group
  signals fan out in PID order. All fields checkpoint with the kernel.
- `setsid` creates a new session and group. `setpgid` permits self or
  direct-child reassignment within the caller's session and requires an existing
  group or the target's own PID. `getpgid` and `getsid` expose the resulting
  relation. Identities and refusal states checkpoint and journal.
- The image transition `execve` assembles descriptor-validated source before an
  atomic replacement of program, registers, scheduler state, and private memory.
  PID, descriptors, authority, environment, and lineage remain stable.
- `waitpid` reports would-block or `nohang = ⊥` for live children. Exited
  children are selected deterministically and returned exactly once. Reaping
  releases scheduler, memory, descriptor, and process-table state.
- The kernel records an explicit init PID and adopts live descendants of an
  exiting parent to init, preserving process-group identity.
- Any process MAY be a subreaper. Orphan adoption selects the nearest live
  subreaper, falls back to init, journals the ownership transfer, and survives
  checkpoint and restore. Service supervision reaps terminal children before
  restart.
- Scheduled `fork` clones private memory by content-addressed page identity,
  resumes the child at the post-trap program counter with a zero return, and
  inherits the parent's descriptor graph, authority, environment, and lineage.
  `pipe_into` supplies the compound-result ABI for userland pipe construction.
  Process exit closes local descriptor aliases; resource reclamation respects
  surviving aliases.
- `spawn_file` loads and spawns a child from the virtual filesystem through the
  same execute-authority and capability path as any other transition.

### 7.3 Memory

- Per-task memory images provide eager mappings, lazy reservations,
  deterministic first-fit allocation, demand zero-fill, atomic protection
  transitions, cross-page reads and writes, content-addressed pages,
  copy-on-write cloning, typed `PageFault` failures, per-process quotas, and
  shared-region mappings.
- Journaled `mmap`, `munmap`, `mprotect`, `mem_read`, `mem_write`, `mem_info`,
  and capability-gated shared-memory syscalls are exposed. A VM-wide
  resident-page budget covers spawn, shared attachment, and demand faults.
  Mapping identity and contents survive checkpoint and restore.
- `mem_reclaim` moves private resident pages to content-addressed backing; a
  later access faults the page back without byte loss.
- `read_into` and `write_from` transfer bytes between kernel descriptors and
  virtual memory. Non-mutating page preflight precedes destructive descriptor
  reads, preserving compound-syscall failure atomicity.

### 7.4 Descriptors and devices

- Descriptor-backed pipes use bounded kernel FIFO state with explicit
  would-block, broken-pipe, capacity, inheritance, and checkpoint semantics.
- Descriptor rights cross running process boundaries through typed bus messages.
  The transfer table retains one shared open description until `receive_fd` or
  destination cancellation, including native network-resource reachability.
- `DeviceBus` drivers are reachable as `/dev/<name>` open descriptions.
  Character reads, writes, readiness, input feeding, snapshot state, and
  close-on-exit follow the same descriptor and journal boundary as files and
  pipes.
- Capability-authorised process creation installs virtual-console descriptors
  `0`, `1`, and `2`.
- The console driver carries controlling-session and foreground-group identity
  with canonical, raw, and echo modes. Terminal control syscalls validate
  session and group invariants; background reads fail without consuming input.
- Dynamic pseudo-terminals are `DeviceBus` resources. `pty_open_into` returns a
  connected master/slave descriptor pair, byte flow is checkpointable, the slave
  reuses terminal session and mode rules, and last-alias closure reclaims the
  pair.
- Terminal `ISIG` is a typed control-plane bridge: `Ctrl-C`, `Ctrl-Z`, and
  `Ctrl-\\` become foreground-group `INT`, `STOP`, and `QUIT`. Scheduled and
  kernel-only process state stay synchronised.
- Canonical terminals implement stateful `VERASE`, `VKILL`, and `VEOF` with
  echo projections, raw-mode preservation, readable EOF, and checkpointed
  line-discipline state.
- PTY endpoint liveness is explicit: master closure preserves the surviving
  slave long enough to expose buffered bytes, `POLLHUP`, EOF, and one
  foreground-group `SIGHUP`.
- Descriptor-local `FD_CLOEXEC` state checkpoints separately from shared
  open-description flags. `fork` preserves it, `dup` clears it, and `exec`
  closes only marked aliases before the new image runs.

### 7.5 Blocking and readiness

- Scalar descriptor waits preserve the original instruction across readiness and
  deterministic virtual deadlines. Deadline jumps journal as time advances. The
  one-shot wake cause checkpoints, so expiry cannot silently reset the same
  wait.
- Scheduled programs place aligned descriptor vectors in their own memory.
  `poll_into` preflights the complete interval, writes only readiness masks, and
  shares the scalar wait and deadline machinery without consuming payloads.
- Bounded byte streams commit only the prefix admitted by capacity, window, and
  queue invariants, and return its cardinality. Acknowledgement progress is
  pumped before stream admission, making caller-controlled continuation explicit.
- Scheduled syscall failures become journaled `-errno` results with
  checkpointed process-local error state. Direct API calls raise typed
  exceptions at the outer API boundary.

### 7.6 Protocol

- Scheduled programs issue typed native `SYSCALL` traps with register-bound
  arguments. The OS backend dispatches them through the same kernel transition
  function. Transport-free interpreters refuse kernel effects explicitly.
- The syscall server uses request fingerprints and checkpointable response
  caching. At-least-once duplicate delivery is idempotent; request-ID reuse
  with altered contents is an explicit error.
- Structured syscalls cross the bus as typed request/reply messages with
  failures preserved as wire-level `Err` results.
- The typed syscall protocol dispatches against the full headless OS, so memory
  calls and byte payloads cross the bus with lossless encoding.

### 7.7 Communication and persistence

- A reliable channel provides sequence identity, acknowledgements, receiver
  deduplication, leases, bounded retries, an explicit failed-sequence set, and
  binary-safe checkpoint and restore of its control state.
- Reliable channels enforce a checkpointed sender window, returning typed
  backpressure when `|pending| = W` and releasing capacity only through
  acknowledgement or explicit retry failure.
- In-memory and fault-injection transports checkpoint FIFO identity, delayed
  staged frames, logical clocks, send indices, and fault observations, so a
  retry resumes from a crash boundary.
- Communication persists locally through a hash-chained append-only mailbox
  transport. Binary-safe enqueue, dequeue, and consume events replay into the
  same queue identity graph, and reliable acknowledgements survive reopen.
- The E0 network device consumes captured IPv4 and TCP frames, tracks bounded
  connection state, parses HTTP semantics, rejects malformed wire input, and
  attaches each accepted event to the shared journal receipt chain.
- The E1 owned network fabric provides namespace, interface, and link topology;
  deterministic multi-hop forwarding; bounded FIFO frames; route and MTU refusal;
  capability-gated byte transfers; checkpoint restoration; and a transactional
  commit-after-accept driver adapter.
- Native datagram and stream layers provide typed binary envelopes, port binding
  and demultiplexing, listener and connect state, sequence and acknowledgement
  accounting, socket queues, scheduled memory I/O, shared process file
  descriptors, `dup2` resource replacement, `fcntl` status flags, a unified
  immediate readiness vector, bounded write backpressure, and checkpointable
  scheduler waits.
- No host socket is opened at any layer.

### 7.8 Images

- Executable images v2 carry a bounded tagged binary instruction stream. The
  loader decodes and validates it, compares it against the readable graph, and
  refuses mismatches before installation or scheduling. v1 graph-only images
  remain migration-readable.
- The executable loader admits UTF-8 assembly or validated MCPB bytes through
  the same execute-authorised descriptor path. Bytecode is decoded before spawn
  or deferred `exec` mutation, preserving atomic image replacement and explicit
  refusal on malformed binaries.
- The executable boundary provides an ELF32 and ELF64 program-header parser and
  memory stager. Load segments, BSS, page protections, entry point, interpreter
  metadata, and dynamic presence are retained. Foreign instruction execution
  fails closed.

### 7.9 Control plane

- The classifier hypervisor separates typed probabilistic evidence from
  authority. Hard capability checks, confidence thresholds, destructive review,
  handler dispatch, and journal receipts are native control-plane transitions.
- Process signal dispositions checkpoint and are inherited. The integer-safe
  default and ignore ABI participates in explicit, group, and PTY-originated
  signal delivery. `SIGKILL` and `SIGSTOP` are non-ignorable.
- Process environments, typed signals, digest-addressed images, service
  policies, and continuation checkpoints are explicit control-plane state.

## 8. Obligations

The following are **REQUIRED** and are not statements of present capability.

1. Multi-tier eviction policy, durable remote page backing, execute permissions,
   and a broader memory ABI above the specified deterministic
   content-addressed reclamation, demand paging, ELF load staging, protection
   transitions, typed faults, quotas, and resident budget.
2. Terminal and session integration breadth, and signal and wait behaviour for
   richer workloads, above the specified context-byte transfers, dynamic PTYs,
   `ISIG` job control, canonical editing and EOF, hangup lifecycle, default and
   ignore dispositions, arguments, inheritance, subreapers, sessions, group
   signals, bounded pipes, `execve`, `waitpid`, native traps, descriptor
   aliasing, byte-buffer I/O, and the v2 bytecode format.
3. A replicated durable mailbox backend, transactional multi-host
   acknowledgement commits, receiver-advertised and congestion windows, and
   crash-recovery transaction boundaries, above the specified local durable
   mailbox, checkpointable channel, and sender-side sequence window.
4. Replay checking, sequence-window negotiation, and cross-transport migration
   around the reliable channel.
5. Typed protocol drivers, link-state negotiation, and evidence-bearing adapters
   for the E1 owned link fabric. No public infrastructure is assumed.
6. Migration compatibility for checkpoint and image formats, ELF relocations and
   dynamic linking, foreign CPU backends, and a package dependency graph above
   the digest registry.
7. A POSIX-compatibility layer, admitted only after the semantic layer is
   differential-tested.
8. Evidence tier reported for every result, per clause 6.
9. Typed classifier adapters for filesystem, network, service, process, and
   package operations, preserving deterministic policy and refusal when a model
   is unavailable or uncertain.

## 9. Non-goals

MailCPU does not implement, and does not claim, the following. These are not
items of outstanding work.

1. Linux compatibility, distribution packaging, or host namespace sharing.
2. Foreign CPU instruction execution. `parse_elf` validates and stages; it does
   not relocate, link, bind `libc`, or emulate.
3. Public or host networking. No host socket is opened and no public
   infrastructure is contacted. No `E2` result is produced.
4. Multi-host durability, transactional cross-host commit, receiver-advertised
   windows, and congestion control.
5. Reproduction of any undisclosed third-party internal architecture.
6. Cryptographic primitives.

## 10. Governing rule

No compatibility claim is accepted until a workload passes against the
reference semantics and the result is replayable from the recorded
communication trajectory.

