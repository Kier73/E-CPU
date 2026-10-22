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

Checkpoint restore is accepted as a continuation only when the restored
machine produces the same post-checkpoint semantic trajectory as uninterrupted
execution. The trajectory receipt stream remains a separate integrity proof.

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

| Tier | Provenance | System role |
|---|---|---|
| `E0` | Captured frames, in-process emulation, or a deterministic fixture | Local semantic development and exact replay |
| `E1` | A substrate wholly owned by the implementation | Controlled physical or owned network paths |
| `E2` | Public or third-party infrastructure | Public Internet paths and externally operated infrastructure |

**REQUIRED** Every reportable result MUST carry its tier.

**REQUIRED** A tier MUST be attached only when its substrate is present. When a
substrate is not yet attached, its execution stage remains an explicit build
boundary rather than being silently inferred.

MailCPU currently reports `E0` and `E1` results. The dedicated socket transport
opens host sockets for controlled external paths; public E2 operation remains a
later infrastructure stage.

The report boundary is explicit: native CLI JSON records and public
`to_dict()` result projections carry an `evidence_tier` field. Deterministic
process, classifier, service, and E0 network-event projections use `E0`;
owned-network frames and datagrams use `E1`. Checkpoint/image encodings remain
state formats rather than evidence reports and do not infer a substrate tier.

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
- `PageBacking` is an optional continuation path for evicted pages.
  `RemotePageStore` persists fixed-size page bytes in an fsynced local CAS and
  transfers them through bidirectional replicated-mailbox messages, validating
  each page by its SHA-256 identity before admission.
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
- The semantic network layers remain host-socket-free. `SocketTransport` is the
  explicit framed bridge from those layers to a real external stream.
- `SocketTransport` preserves the typed message algebra over bounded TCP frames,
  canonical tuple-preserving bodies, integrity receipts, peer identity binding,
  partial-frame recovery, backpressure, and rebound checkpoint state.
- `ReplicatedMailboxStore` and `ReplicatedMailboxNode` persist enqueue,
  dequeue, and consume operations on each node, deduplicate operation identities,
  and expose quorum receipts whose acknowledgements follow durable application.

### 7.8 Images

- `ArtifactIngestor` is the common admission path for UTF-8 MailCPU assembly,
  validated MCPB bytecode, and ELF payloads. It preserves source and compiled
  content digests, returns an installable image for MailCPU artifacts, and
  returns a loader artifact for ELF without confusing native bytes with a
  schedulable MailCPU program.
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
- Dynamic ELF metadata is decoded into bounded dependencies, symbols, REL/RELA
  records, and a digest-preserving `DynamicLinkPlan`. Relative actions and
  explicitly supplied symbol bindings produce typed write intents without
  mutating memory before a later linker stage admits them.
- `DynamicLinker` resolves `DT_NEEDED` through an explicit provider relation,
  assigns deterministic page-aligned dependency bases, stages a clone, and
  commits relocation writes only after every image and target preflight passes.
- `DynamicLinker.link_runtime` extends that transaction to a provider-backed
  `PT_INTERP` image. `ElfStartupState` records the main entry, interpreter
  entry, interpreter base, and derivable auxiliary-vector values; startup
  metadata is validated before the shared memory clone commits.
- `materialize_startup_stack` turns that handoff into a 16-byte-aligned
  x86-64 `[argc,argv,NULL,envp,NULL,auxv,strings]` mapping with deterministic
  environment order. The mapping is published only after all words and
  strings are written to a clone.
- `ExecutionBackendRegistry` maps an exact `(machine,bits)` identity to a
  validator supplied by a verified CPU/ABI backend. `ElfRuntimeLoader.admit`
  composes linking and startup-stack materialization on a private clone,
  invokes that validator, and commits once only after the complete handoff is
  accepted. Missing or rejecting backends leave caller memory unchanged.

### 7.11 Numbered POSIX boundary

- `PosixCompatibility` translates the Linux x86-64 syscall-number relation
  into the already-backed kernel and memory transitions. The initial domain is
  `read`, `write`, `open`, `close`, `fstat`, `lseek`, `mmap`, `mprotect`,
  `munmap`, `pipe`, `dup`, `dup2`, `fcntl`, `getpid`, `exit`, `wait4`,
  `getcwd`, and `chdir`.
- Pointer arguments are read from or written to the process virtual memory
  image. Compound destinations are preflighted before descriptor creation,
  waiting, or file-position mutation, and failures return the negative errno
  projection while recording the process errno.
- Numbered `execve(59)` decodes bounded argv and environment pointer vectors
  from virtual memory, validates the complete environment, and then invokes
  the existing atomic executable replacement. It preserves ordinary
  descriptors and clears the replaced process environment according to the
  supplied vector.
- `fstat` emits the fixed x86-64 144-byte record, `wait4` emits the encoded
  exit status, and `pipe` emits its descriptor pair through the existing
  memory-transfer law. Unsupported numbers and unsupported flag families
  return explicit `ENOSYS` or `EINVAL` rather than fabricated behavior.

### 7.9 Control plane

- The classifier hypervisor separates typed probabilistic evidence from
  authority. Hard capability checks, confidence thresholds, destructive review,
  handler dispatch, and journal receipts are native control-plane transitions.
- The hypervisor arbitration loop receives distributed source/channel/sequence
  envelopes, stabilizes exact retransmissions by canonical fingerprint, and
  refuses same-identity payload changes. Its ledger and cycle count checkpoint
  with the headless OS; learned revision remains a separately witnessed
  proposal until admitted.
- Candidate classifier revisions run in a shadow hypervisor and replace the
  active model only after reproducing every supplied policy witness. Accepted
  revision number and witness digest checkpoint with the policy; mismatches
  preserve the active model and produce an explicit refusal receipt.
- Process signal dispositions checkpoint and are inherited. The integer-safe
  default and ignore ABI participates in explicit, group, and PTY-originated
  signal delivery. `SIGKILL` and `SIGSTOP` are non-ignorable.
- Process environments, typed signals, digest-addressed images, service
  policies, and continuation checkpoints are explicit control-plane state.

### 7.10 Substrates, reversible core, and algebraic law lifting

- Micro-operation execution admits an involutive reversible gate engine ($X$, $\text{swap}$)
  where self-inverse compositions satisfy $(G_m \circ \dots \circ G_1)^{-1} = G_1 \circ \dots \circ G_m$
  and Bennett carry uncomputation returns ancilla registers strictly to zero.
- Trajectory execution compresses shift-periodic patterns into $\mathcal{O}(1)$ chronofold
  descriptors, supporting constant-space backward replay and discrete geometric phase
  accumulation $D = (-i)^{n_{\text{active}}}$ on modulo-4 cycles.
- Scheduler trajectory frames retain the semantic instruction projection
  `(step, pc_before, op, args, pc_after, registers, output_delta)` alongside
  scheduler identity and receipt metadata. This makes single-task machine
  traces comparable with the reference interpreter and preserves multi-task
  event order for checkpoint differential replay, while leaving complete
  filesystem and multi-host replay as separate state relations.
- Ambient communication substrates store in-flight memory across physical delay loops
  without host RAM residency. Dynamic slot clamping enforces $\Delta_{\text{slot}} \ge 3 \sigma_{\text{jitter}}$,
  and Redundant Residue Number Systems (RRNS) guarantee exact Garner-free CRT state reconstruction
  from any $k \le n$ surviving packets under continuous in-flight scrubbing.
- Discrete Cadence Modulation encodes nibbles into inter-packet transmission intervals
  $\Delta t = \Delta_0 + d \cdot \delta_{\text{quantum}}$, paired with PLL-stabilized maximum-likelihood
  demodulation achieving zero bit error rate under bounded Gaussian route jitter.
- Virtual devices `/dev/dns_latch` expose decaying TTL memory latches and RFC 2308 negative
  caching, while TCP sequence operators provide arithmetic over the cyclic ring $\mathbb{Z}_{2^{32}}$
  and autonomous AIMD feedback concurrency control.
- The $\Omega_5 = (\text{STATE}, \text{LIFT}, \text{NAVIGATE}, \text{DESCEND}, \text{VERIFY})$ loop
  transforms message streams into certified closed-form recurrence relations across the implemented six-rung ladder,
  enabling $\mathcal{O}(\log t)$ closed-form orbit leaps guarded by strict horizon bounds $t < \text{first\_bad}$.
- Tripartite temporal coordinates $\langle \lambda_{\text{event}}, \tau_{\text{chronon}}, \tau_{\text{chem}} \rangle$
  govern execution, scaling memory quotas and retention delays by normalized parsing difficulty $\tau_{\text{chem}}$,
  and coordinating distributed multi-node consensus via $\text{SU}(2)$ Wilczek-Zee unitaries.
- Lightweight distilled neural routing heads propose candidate algebraic ladder rungs in $\mathcal{O}(1)$ time,
  subject to strict policy gate witness isolation that accepts proposals only upon 100% agreement
  with withheld verification probes, falling back to exhaustive ladder search on mismatch.

## 8. Obligations

The following are **REQUIRED** staged obligations of the same machine.

1. Multi-tier eviction policy, execute permissions, and a broader memory ABI
   above the specified deterministic local and remote
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
7. Broader POSIX compatibility, admitted incrementally above the numbered
   syscall foundation and differential-tested at each new ABI surface.
8. Evidence tier reporting is enforced at the native CLI and public result
   projection boundaries, per clause 6. Future result surfaces must use the
   same typed boundary before they are considered complete.
9. Typed classifier adapters for filesystem, network, service, process, and
   package operations, preserving deterministic policy and refusal when a model
   is unavailable or uncertain.

## 9. Current stage boundaries

The following are the next infrastructure layers of the same system. They are
not alternative machine models:

1. Linux compatibility, distribution packaging, or host namespace sharing.
2. Foreign CPU instruction execution. `parse_elf` validates and stages; it does
   not relocate, link, bind `libc`, or emulate.
3. Public Internet infrastructure and E2 operation beyond the controlled
   external socket transport.
4. Multi-host durability, transactional cross-host commit, receiver-advertised
   windows, and congestion control.
5. Reproduction of any undisclosed third-party internal architecture.
6. Cryptographic primitives.

## 10. Governing rule

Every compatibility stage is admitted when its workload preserves the
reference transition semantics and the result is replayable from the recorded
communication trajectory.

