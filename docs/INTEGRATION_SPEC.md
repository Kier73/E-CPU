# MailCPU Integration Specification

Normative specification of the mechanisms MailCPU adopts from external reference material, the boundaries at which each mechanism attaches to the kernel state, and the obligations that gate its admission.

Defined terms follow `docs/GLOSSARY.md`. Governing rules are `docs/ARCHITECTURE.md` clauses 3, 5, and 6.

## 1. Scope and boundary

### 1.1 Reference material

The reference material supplies mechanisms bearing on the MailCPU replacement target. It is a design and test corpus, and not a verified drop-in kernel.

**REQUIRED** Production code MUST NOT import, link against, or require the reference corpus.

The reference bundle is not distributed with this repository. Every boundary in this document is stated in terms of MailCPU state and transitions, and MUST remain intelligible to a reader with no access to the bundle.

### 1.2 Adoptable mechanism boundaries

The module names in the table below record the mechanism from which each boundary was derived. They are provenance labels and not dependencies; the third column is the normative constraint set for the corresponding MailCPU mechanism.

| GV module | MailCPU use | Integration boundary |
|---|---|---|
| `substrate` | Sparse append-only trajectory streams, binary seek, receipt chains, CRT witnesses, Byzantine-lane diagnosis, inline invariant detection | Journal/trajectory layer above transport; no change to MailCPU transition semantics |
| `vfs` | Procedural inode providers for `/proc`, `/dev/zero`, entropy, generated data, and codon tables | New `VirtualFileProvider` interface alongside content-addressed files |
| `os_kernel` | Explicit task lifecycle, procedural page synthesis, interrupt harvesting, leap scheduler experiments | Scheduler/memory extension; every leap must carry a proof domain and fallback stepper |
| `gvm` | SENSE/LEAP/HDC/MDL execution regimes, DMA-shaped VFS access, attestation receipts | Optional execution backend and image regime metadata; MailCPU algebra remains the conformance oracle |
| `gvm_asm` | Assembly/disassembly and labels for portable executable images | Image toolchain; assembler output must round-trip through the image loader |
| `net` | Headless TCP state tracking, HTTP parsing, wire-to-semantic payload extraction | Device/transport adapter; E0 emulation first, E1 owned links before E2 public infrastructure |
| GV unit/e2e/adversarial tests | Cross-language, invariant, corruption, boundary, and end-to-end acceptance patterns | New MailCPU acceptance tiers, with unmeasured statements marked explicitly |

The module names carry no build-time and no run-time dependency. Clause 15 governs the disposition of any copied source.

### 1.3 Evidence tiers and substrate ordering

**Evidence tier** is as defined in `docs/ARCHITECTURE.md` clause 6. MailCPU
currently reports `E0` and `E1` results; E2 enters with public infrastructure.

**REQUIRED** Conformance at a substrate tier MUST be recorded before a mechanism is attached to a higher tier. `E0` emulation precedes `E1` owned links, and `E1` owned links precede `E2` public infrastructure.

**REQUIRED** Host-socket access MUST be confined to the explicit framed
`SocketTransport` boundary. E0 and owned semantic network layers MUST remain
independent of the host socket API.

### 1.4 Admission constraints

**REQUIRED** MailCPU transition algebra remains the conformance oracle for every adopted execution backend, image regime, and model.

**REQUIRED** A generated, learned, or externally sourced component MUST match the ordinary transition algebra on a bounded conformance corpus before **admission** into the execution path.

**REQUIRED** A mechanism whose invariant does not hold MUST **fail closed** through an explicit **refusal** or a defined fallback path.

## 2. Journal, trajectory, and receipt substrate

### 2.1 Trajectory format

The trajectory substrate is a binary append-only stream with a sparse index `K`, monotone timestamps, and binary seek:

```text
trajectory = (frame_0, ..., frame_n)
index[j] = (sequence, logical_time, byte_offset)
seek(t) = binary_search(index, t) + linear_scan_at_most_K_frames
```

**REQUIRED** Timestamps MUST be monotone across the stream.

### 2.2 Receipt chain

Every accepted transition emits a **receipt**-chain link:

```text
H_0 = 0
H_n = SHA256(H_{n-1} || canonical(sequence, event, payload))
```

### 2.3 Substrate contract

`mailcpu/trajectory.py` provides scheduler integration, sparse seek, chain verification, replay callbacks, deliberate corruption rejection, and a native image-runner capture option. The substrate operates over the modelled journal. Evidence tier: E0.

Scheduler trajectory frames include the semantic instruction projection
`(step, pc_before, op, args, pc_after, registers, output_delta)` in addition
to scheduler identity and receipt metadata. Single-task trajectories can
therefore be compared directly with the reference interpreter trace, and
multi-task trajectories retain task identity and event order for differential
checkpoint replay. Complete filesystem and multi-host replay remain separate
state captures.
`TrajectoryWriter.resume` verifies an existing stream before opening it for
append and continues its sequence, logical time, sparse index, and receipt
chain, allowing checkpoint continuation to remain one integrity-verified
trajectory.

## 3. Procedural storage providers

### 3.1 Provider interface

The filesystem admits provider-backed **inode** records alongside content-addressed **blob** references. A provider implements:

```text
read(inode, offset, count) -> bytes
stat(inode) -> metadata
```

### 3.2 Provider kinds

Provider kinds are `ZERO`, `ENTROPY`, `PROC_TEXT`, and `FEISTEL`, each deterministic.

**REQUIRED** Every provider MUST expose synthesized-byte counts, its seed, and a replay **receipt**.

Zero storage denotes the absence of backing blocks. It does not denote absence of computation, and it does not discharge a verification obligation.

The native provider kinds are bounded `ZERO` and seeded `ENTROPY`, and provider metadata participates in filesystem snapshots. `FEISTEL`-like deterministic bytes are available as a provider kind.

Receipt accounting for procedural providers and a richer `/proc` provider surface are specified in clause 16.

## 4. Processes and lifecycle

### 4.1 Headless process control

`mailcpu/headless.py` stores source in the virtual filesystem, launches it as a process, synchronizes scheduler status into the kernel, exposes process reports, and captures the execution trajectory. Host source loading is an explicit CLI boundary; execution after installation is virtual-filesystem-only.

Process control provides:

- mailbox injection, which wakes blocked tasks;
- explicit termination recording an exit code;
- shell commands `inject` and `kill`;
- suspension and resumption as explicit scheduler states.

### 4.2 Service supervision and checkpoint

Service supervision carries desired-state records, mailbox-oriented long-lived workloads, bounded restart policies, and stop semantics. Checkpoint and restore persist the virtual filesystem, bus, journal, processes, scheduler graph, memory, and service controller. A digest-checked restore must produce the same post-checkpoint semantic trajectory as uninterrupted execution, including a blocked consumer awakened by a producer through the FIFO bus; trajectory receipt continuity remains a separate capture concern.

Executable loading crosses kernel descriptors and enforces execute mode.

### 4.3 Process ABI

The process ABI carries:

- argument vectors;
- parent and process-group identity;
- inherited environment and **capability** sets;
- optional descriptor inheritance;
- checkpoint persistence;
- **deterministic** process-group signal fan-out;
- bounded descriptor-backed pipes.

### 4.4 Image replacement

The image transition `execve` loads executable source through descriptors and assembles it before mutation. PID, descriptors, authority, environment, and lineage survive; program, registers, scheduler state, and private memory are replaced. The transition is available locally and through the typed system-call bus.

### 4.5 Wait, reap, and adoption

`waitpid` reports would-block, or `nohang = ⊥` for a live child. Exited children are selected in PID order, and reaping removes scheduler, memory, descriptor, and process-table state.

The kernel records an explicit init PID and reparents live descendants of an exiting parent to init, with a journaled `process.adopt` event.

### 4.6 Sessions, process groups, and subreapers

The process tree carries session identity in addition to parent and process-group identity.

- `setsid` creates a new session and group only for a non-group-leader.
- `setpgid` permits self or direct-child reassignment only within the caller's session, and requires an existing group or the target's own PID.
- `getpgid` and `getsid` expose the resulting relation.
- Identities and refusal states are check pointable and journaled.

Any process MAY be a **subreaper**. `set_subreaper` and `get_subreaper` expose the control boundary; the subreaper bit is check pointable. Orphan adoption walks the ancestor chain to the nearest live subreaper before falling back to init.

Service supervision consumes exited children before restart or terminal convergence, so a bounded restart policy accumulates neither zombies nor resident memory images.

### 4.7 Fork and inherited byte pipes

`fork` reserves the next PID, admits the parent's resident mappings before mutation, and commits a child with the same program at the post-trap program counter. Parent and child observe the conventional integer results (`child_pid` and `0`) through the destination register. The child receives copied registers, input queues, output history, environment, capabilities, group and session lineage, and inherited open descriptions.

Private memory is cloned by immutable content-addressed page identity, so a later write allocates a divergent page hash without copying untouched content.

`pipe_into(address)` exposes the bounded pipe pair as an atomic eight-byte little-endian memory ABI, permitting scheduled userland to construct a pipe and then use `read_into` and `write_from` across a fork boundary.

Process termination closes every descriptor alias, reclaiming unreachable pipe state while preserving descriptors still referenced by surviving children. Checkpoint restoration reinstalls the deferred fork and exec transition state, and a child exchanges bytes with its parent after restore-compatible scheduler operations.

The fork boundary is narrower than Linux `fork`/`clone`: threads, signal-disposition cloning, robust futexes, ELF auxiliary vectors, and a full POSIX descriptor flag matrix are outside the boundary.

**REQUIRED** Process image, private memory, descriptor graph, authority, and lifecycle ownership MUST be separate state relations with auditable commit points.

### 4.8 Self-hosted child launch and image replacement

`spawn_file(path,name,inherit_fds,max_pages)` loads an executable source through the caller's virtual filesystem authority and creates a child with `parent(child)=caller`. The child receives inherited environment, capabilities, session and group lineage, and optional shared open-description aliases through the spawn path. The returned PID is an integer scheduled-syscall result, so a supervisor spawns, polls, and waits without host-side launch orchestration. Load, execute-mode, capability, memory-admission, and assembly failures pass through the negative-errno channel. The parent/child relation remains visible while the parent is live, and the subreaper adoption policy of clause 4.6 applies when the parent exits.

The scheduled `exec(path,name)` trap loads and validates the virtual executable without mutating the current image. After the trap transition commits, the scheduler applies one atomic image replacement: same PID, new program graph, fresh registers and memory, and a new process name and argument vector. The prior instruction continuation cannot run, because the replacement is committed before the next scheduler event is formed. The replacement callback is installed on restored schedulers, and a pending image request is transient and is never check pointable mid-instruction. Direct host `exec_file` behaviour shares the same loader, capability, execute-mode, and memory-admission rules. Malformed replacement source returns `-EINVAL` through the scheduled result channel and leaves the prior image unchanged.

### 4.9 Scheduled result channel

A scheduled program receives a recoverable system-call failure as a state transition and does not terminate the scheduler orbit.

- A failed scheduled system call is classified into a stable finite errno alphabet and returns `-errno` in the destination register.
- The process stores the positive errno value, exposed through `errno` and `get_errno`, and preserves it across successful calls until another failure overwrites it.
- Errno participates in process reports, process-table projections, kernel checkpoints, and restore validation.
- The journal records `syscall.error` with process, operation, errno, and typed failure text, preserving auditability without altering direct-call exception behaviour.
- Page faults and quotas, capability failures, descriptor failures, would-block and full pipes, broken pipes, filesystem absence, and protocol failures each have an explicit classification path.

### 4.10 Scheduled process-wait ABI

A process supervisor remains inside the MailCPU instruction plane. Scheduled `waitpid(child_pid, nohang=true)` returns the reaped child PID, or `0` when no terminal child is ready. The return is an integer register result, while the host-facing system call retains its structured wait record and its direct exception behaviour. The wait boundary projects `σ_scheduler` into `σ_kernel`, so a child that halted within the same scheduler orbit is observable without an outer API call. Successful reaping removes the child task, memory, process-table entry, and pending descriptor-transfer references through the lifecycle path of clause 4.5. Lineage remains enforced: a process cannot reap a child owned by another parent.

### 4.11 Native scheduled syscall traps

A process controlled by the operating system invokes the operating system from its own instruction stream. The instruction algebra includes:

- `SYSCALL destination name key=value...`, with `$register`, integer, boolean, hexadecimal-byte, and string operand decoding;
- explicit scheduler injection of the kernel handler, keeping host authority outside the generic interpreter;
- integer result write-back and terminal `exit` handling;
- check pointable restoration of the handler binding through the composed virtual machine;
- explicit refusal in the transport-free **reference interpreter** and pure mailbox backends, preserving failure evidence rather than fabricating a kernel result.

The transition is native to MailCPU. Evidence tier: E0. Linux system-call ABI compatibility is outside the boundary.

## 5. Memory and page model

### 5.1 Typed memory boundary and shared regions

The memory boundary is typed and check pointable.

- `PageFault(address, page_number, access)` preserves unmapped-access failure as structured state.
- `MemoryQuotaExceeded` and atomic map/attach admission prevent partial allocation transitions.
- `SharedRegion` provides mutable named byte storage with explicit page alignment and shared visibility across processes.
- The headless operating system exposes `mmap`, `munmap`, `mem_read`, `mem_write`, `mem_info`, `shm_create`, `shm_attach`, and `shm_detach`, with journal receipts and capability checks.
- Virtual machine snapshots validate private blob hashes, shared-region identity and content, mapping bounds, and page quotas.

**REQUIRED** The memory acceptance corpus MUST cover private map and unmap, cross-process shared writes, read-only attachment, failure atomicity, and checkpoint restoration.

Demand zero-fill, allocation, protection, reclamation, and a VM-wide **resident budget** are specified here and are not Linux `mmap` compatibility. Evidence tier: E0.

### 5.2 Content-addressed reclamation

`mem_reclaim` deterministically evicts selected private pages into content-addressed
backing. With an injected `PageBacking`, publication completes before the
resident mapping becomes a reservation; a later access resolves the same
digest through local or remote CAS and restores exact bytes. `RemotePageStore`
uses atomic local page files plus `PAGE_PUT`, `PAGE_GET`, `PAGE_DATA`, and
`PAGE_MISS` mailbox messages over bidirectional replicated channels. A missing
or corrupted remote page is an explicit failure, never fabricated zero data.
The reservation/backing relation remains checkpointable, while the provider is
re-injected on restore. Evidence tier: E1 for controlled multi-node paths.

### 5.3 Demand paging and resident accounting

The memory ABI is a two-level virtual/resident model:

- `PageReservation` records virtual pages without allocating resident content.
- The first read or write to a permitted reservation materializes a zero-filled content-addressed **page**.
- `mmap(length)` uses deterministic first-fit allocation and accepts an optional aligned hint.
- `mprotect` changes writable protection for eager, lazy, and shared mappings atomically per process.
- Access preflight validates every touched page and quota before mutation, so a later fault or quota failure cannot leave an earlier page half-written.
- Recovered demand faults are emitted as `memory.page_fault` journal events.
- `MailCPUVirtualMachine(max_resident_pages=B)` enforces `Σ_pid |M_pid| ≤ B` across process spawn, shared attachment, and reservation materialization.
- The resident budget and lazy reservations survive checkpoint and restore, with restored state revalidated before use.

The accounting unit is a resident page mapping. An attached shared page is charged once per process mapping. Evidence tier: E0.

### 5.4 Process-context memory ABI

The process boundary carries a deterministic, memory-addressable context contract.

- `argv_size`, `environ_size`, and `getcwd_size` expose exact UTF-8 byte counts including one NUL terminator per record.
- `argv_into(address,size)` writes `argv[0]\0argv[1]\0...`, `environ_into` writes sorted `KEY=VALUE\0` records, and `getcwd_into` writes the current directory as one NUL-terminated record.
- Each transfer preflights capability, capacity, and every touched virtual page before writing, so `-ERANGE` or `-EFAULT` cannot leave a partial context record.
- Embedded NULs are refused at process creation, image replacement, and environment mutation, because the packed representation must remain injective.
- Scheduled callers receive the same negative-errno channel as other memory system calls, while direct callers retain typed failures.
- Process context transfers are journaled and continue across checkpoint and restore, giving shells, launchers, and later libc layers a stable information boundary.

Evidence tier: E0.

## 6. Descriptors, readiness, and blocking

### 6.1 Driver-backed device descriptors

The device bus participates in the same descriptor algebra as files, pipes, and native sockets.

- Registered drivers at `/dev/<name>` open through the ordinary kernel descriptor path, including the boot `null` and the buffered `console` devices.
- Descriptor `read` and `write` dispatch to driver state while preserving shared open-description identity, capability checks, checkpoint serialization, and close-on-exit cleanup.
- Readiness is driver-specific: a null read is terminal-ready, buffered input is `POLLIN` only when data exists, and writes are immediately admissible.
- Scheduled `read_into` **blocks** on empty console input and resumes from the same program counter after a communication-backed driver feed.
- Capability-authorized process creation installs standard descriptors `0`, `1`, and `2`, mapped to virtual console input and output, so userland uses conventional streams without host descriptor injection.
- Device seeking is rejected explicitly, because a character driver has no virtual-file cursor law.

Evidence tier: E0. Linux device management, `ioctl`, terminal line discipline, and host-device passthrough are outside the boundary.

### 6.2 Process-owned network handles

Network resources participate in process authority and lifetime.

- Datagram sockets, stream listeners, and stream connections are owned by the creating or accepting PID.
- Foreign process use is refused, even where the caller holds broad filesystem and network capabilities.
- Ownership maps are check pointable and validated against the restored socket, listener, and connection domains.
- `net_dgram_close` removes a datagram binding and its decoded inbox.
- Exact process reaping releases owned datagram, listener, and connection resources, so stale network handles do not survive process-table cleanup.

This is native resource ownership. `SCM_RIGHTS` and the full Unix descriptor flag and `ioctl` compatibility surface are specified in clauses 6.6 and 16.

### 6.3 Descriptor-backed network sockets

Network resources participate in the shared open-file-description model.

- `OpenFile` descriptions carry network kind and native handle identity through `dup`, inheritance, and checkpoints.
- Stream listeners, stream connections, and datagram sockets are allocatable as process file descriptors.
- Stream descriptors implement `read`, `write`, and `close`. Datagram descriptors implement `read`, an explicit `net_dgram_send_fd`, and `close`.
- `read_into` and `write_from` route through headless descriptor authority, so scheduled programs use network file descriptors through virtual memory.
- An inherited descriptor remains usable by the child because the descriptor itself carries the authority, and exact reaping releases the native resource after the final description disappears.
- Descriptor state remains separate from host sockets and preserves explicit capability checks and would-block failures.

Evidence tier: E1 for owned-network handles, E0 for descriptor plumbing.

### 6.4 Shared descriptor status flags

Open-file descriptions carry an explicit status-flag algebra.

- `F_GETFL` and `F_SETFL` operate on the shared description, so `dup`, inheritance, and checkpoint restore observe one flag state.
- `O_NONBLOCK` prevents scheduled empty-listener and empty-receive waits from becoming hidden sleeps; the operation exposes the existing explicit would-block failure or no-connection result.
- `O_APPEND` is honoured on virtual-file writes by recomputing the end offset at each write transition.
- Access mode bits remain read-only projections, and unsupported flag bits and commands fail explicitly.
- Flag state is serialized and revalidated alongside network identity, pipe identity, cursor, and capability state.

Evidence tier: E0. Full `fcntl`/`ioctl` breadth and errno-number ABI are specified in clause 16.

### 6.5 Descriptor-local close-on-exec

The descriptor graph distinguishes shared open-description state from per-descriptor lifetime flags.

- `F_GETFD` and `F_SETFD` expose the descriptor-local `FD_CLOEXEC` bit, while `F_GETFL` and `F_SETFL` operate on shared cursor and status state.
- `dup` and `dup2` create unmarked aliases; `fork` and inherited descriptors preserve the parent's descriptor-local flags; `receive_fd` creates an unmarked destination alias.
- Image replacement removes exactly the descriptors marked `FD_CLOEXEC` before the replacement image becomes runnable, and unmarked descriptors retain their shared descriptions.
- Checkpoint and restore validate descriptor-flag domains and reject flags that reference missing descriptors.
- A native network resource marked for close-on-exec is released only when no surviving alias remains.

Evidence tier: E0.

### 6.6 Communication-backed descriptor rights passing

Running processes transfer open descriptions through the MailCPU bus.

- `send_fd` enqueues a typed rights message to a dedicated recipient mailbox and retains the canonical open description while the message is in flight.
- `receive_fd` installs the same description object, preserving cursor, flags, pipe identity, network kind, native handle, and shared alias semantics.
- Network descriptors remain capability-checked at use time, while a transferred description keeps the native network resource reachable until receipt or explicit cancellation.
- Rights messages and transfer references survive checkpoint and restore, and destination reaping removes undeliverable transfers with native-resource cleanup.
- A scheduled program blocks on an empty rights mailbox and wakes when the sender transmits a descriptor.
- Source closure before receipt is safe, because the transfer table is itself an open-description reference.

Evidence tier: E0.

### 6.7 Unified descriptor readiness

The descriptor boundary exposes a deterministic, non-consuming readiness vector.

- `poll(timeout=0)` reports `POLLIN`, `POLLOUT`, `POLLHUP`, and `POLLNVAL` across regular files, bounded pipes, stream listeners and connections, and datagram descriptors.
- Readiness pumps only the native receive and demultiplex state needed to make queued communication visible; payload consumption remains the separate `read` or `accept` transition.
- Stream readiness distinguishes buffered bytes and EOF, send-window availability, and hangup. Pipe readiness distinguishes data, capacity, EOF, and broken-reader states.
- Replacing the final network open description through `dup2` closes the native listener, connection, or datagram resource before the kernel descriptor map is replaced.
- `poll_fd(fd,events,timeout=0)` exposes the same `revents` mask to integer-register scheduled programs, so an event loop branches without a structured-result channel.
- A non-zero blocking timeout is refused until a scheduler wait primitive establishes wakeup ordering and continuation semantics.

Evidence tier: E0. `epoll`, edge-triggered delivery, and Linux socket ABI compatibility are outside the boundary.

### 6.8 Scheduler-integrated descriptor waits

A scheduled program suspends on communication without losing the system-call transition.

- A **blocked** `accept` or memory-backed receive keeps the same program counter, register valuation, and preflighted memory state.
- The scheduler stores a typed wait predicate for descriptor, listener, datagram, or stream readiness, and wakes only when that predicate becomes true.
- External communication wakes a scheduler whose ready queue was empty, while ordinary mailbox `WAIT` wakeups retain their existing path.
- Wait predicates survive checkpoint and restore, including a stopped task resumed into a blocked wait.
- Each refusal is distinguishable from suspension: `syscall.block` records the wait evidence, and the original system call is retried to expose any later resource failure.
- A blocked receive validates its memory destination before suspension, preserving compound-system-call failure atomicity.

Evidence tier: E0.

### 6.9 Scheduler-integrated write backpressure

The wait algebra covers producer-side capacity.

- Scheduled `write`, `write_from`, and native stream send operations suspend when a bounded pipe or stream send window cannot accept the attempted transition.
- Memory sources are fully preflighted before a writer enters the wait set, so invalid user memory cannot be hidden behind future capacity.
- Pipe capacity release and stream acknowledgement readiness wake the exact blocked writer, without host blocking threads.
- Ordinary virtual files and invalid write modes retain immediate completion or explicit failure behaviour.
- The wait predicate and program counter remain check pointable through the same scheduler state graph.

Evidence tier: E0.

### 6.10 Deadline-aware descriptor waits

The scheduler treats timed scalar readiness as a continuation distinct from a host sleep.

- Scheduled `poll_fd(fd, events, -1)` preserves the program counter until the descriptor reports requested readiness or terminal `ERR`/`HUP`/`NVAL` evidence.
- A positive timeout is represented as an absolute logical deadline `τ_deadline = τ_block + t`, so a blocked-only scheduler advances **logical time** without fabricating an instruction transition.
- The wake cause is carried through exactly one resumed system call, preventing deadline expiry from recomputing a later deadline and re-blocking the same instruction.
- Deadline state and the pending wake cause are check pointable, while direct structured `poll(timeout≠0)` continues to fail explicitly because it has no synchronous event-loop owner.
- Timeout expiry returns the native scalar readiness mask, `0` when no event is ready, preserving the integer-register ABI and journal evidence.

Evidence tier: E0.

### 6.11 Memory-backed descriptor vectors

The event-loop ABI has a user-memory form for scheduled programs.

- `poll_into(address,count,timeout)` consumes fixed 12-byte little-endian records `(fd:int32, events:uint32, revents:uint32)` and returns the number of records with nonzero readiness.
- The complete input and output interval is preflighted for read and write access before any `revents` field changes.
- Descriptor readiness is projected across files, pipes, native datagrams, stream listeners and connections, invalid descriptors, and terminal masks, without consuming payloads.
- Blocking waits store the decoded descriptor vector, wake on level-triggered readiness or terminal evidence, and preserve positive deadlines through checkpoint and restore.
- `poll_into` returns an integer result, so an assembled program uses the same system-call trap and register ABI as `poll_fd` while inspecting detailed masks in virtual memory.

Evidence tier: E0. The record layout is intentionally aligned and four-byte-mask based, and is not Linux binary ABI equivalence.

### 6.12 Prefix-committing byte streams

The byte-transfer layer exposes partial progress; an oversized write is not an all-or-nothing failure.

- A pipe write commits `k=min(requested, capacity−queued)` bytes when readers exist and capacity is positive, returns `k`, and leaves the caller-owned suffix untouched.
- A native stream write commits the maximal prefix bounded by send-window bytes, route-frame capacity, and peer queue slots, and returns the exact transmitted count.
- Protocol acknowledgements are pumped before stream-window admission, so receiver progress is visible to the next sender transition.
- Zero-progress conditions remain explicit: `broken pipe`, a full pipe, a closed stream, or no destination queue. Bytes are never dropped silently.
- Memory-backed `write_from` and descriptor writes support ordinary userland advance-by-returned-count loops.

Evidence tier: E0. Linux `PIPE_BUF` atomicity policy, retransmission, congestion control, and cancellation semantics are outside the boundary.

### 6.13 System-call bus

The structured system-call protocol accepts any dispatcher with the native `syscall(pid, name, **args)` shape. A headless operating system binds a server to the `kernel` mailbox, preserving byte payloads and explicit `Ok`/`Err` outcomes across the communication boundary. Memory calls and byte payloads cross the bus with lossless encoding.

The system-call server applies the information-logistics rule to kernel effects: request identity is fingerprinted, successful and failed responses are cached, duplicate delivery is idempotent, conflicting reuse is refused, and the cache is check pointable.

Evidence tier: E0.

## 7. Terminals and pseudo-terminals

### 7.1 Terminal and session control

The virtual console carries a session-aware terminal driver rather than only a byte buffer.

- Terminal state includes controlling session, foreground process group, canonical and raw input mode, echo mode, queued input, and output history.
- A canonical read becomes ready only after a newline and returns bounded line prefixes; raw mode exposes queued bytes immediately.
- `tcgetpgrp`, `tcsetpgrp`, `tty_setmode`, `tty_canonical`, and `tty_echo` are native control transitions with session and live-group validation.
- A read from a background process group fails explicitly, control queries require session membership, and writes retain the defined terminal policy.
- Terminal queues, foreground ownership, and mode bits survive checkpoint and restore.
- Standard descriptors `0`, `1`, and `2` provide a conventional process-to-terminal boundary entirely inside the virtual state graph.

Evidence tier: E0.

### 7.2 Pseudo-terminals

The terminal boundary supports dynamic pseudo-terminal pairs inside the virtual device graph.

- `pty_open` allocates a deterministic master and slave pair and returns ordinary file descriptors; `pty_open_into` exposes the same result through the eight-byte scheduled memory ABI.
- A master write becomes slave input, a slave write becomes master-readable output, and slave canonical, raw, and echo modes remain enforced by the terminal driver law.
- The slave inherits the creator's session and foreground process group, so `tcgetpgrp`, `tcsetpgrp`, background-read refusal, and mode control apply without host-terminal attachment.
- Pseudo-terminal queues, endpoint modes, ownership, write traces, and peer identities are check pointable and reconnected under strict pair validation.
- A dynamic pair is reclaimed only after no process descriptor and no in-flight rights transfer references either endpoint.
- Scheduled pair construction is transactional: an invalid memory destination closes both descriptors and reclaims the pair instead of leaking a half-created resource.

Evidence tier: E0. Window geometry, packet mode, and `ioctl` breadth are outside the boundary.

### 7.3 Control-character signal delivery

The pseudo-terminal line discipline connects terminal input to the process-control plane.

- With `ISIG` enabled, `ETX` (`Ctrl-C`), `SUB` (`Ctrl-Z`), and `FS` (`Ctrl-\`) are consumed as `INT`, `STOP`, and `QUIT` events instead of entering slave input.
- Each event targets the terminal's current foreground process group, preserving deterministic PID order and the signal exit codes `130` and `131`, or stopped and runnable scheduler states.
- The kernel-only init record and scheduled tasks share one dispatch path, so terminal signals leave the process table and the scheduler agreeing.
- `tty_setmode(..., isig=...)` and `tty_isig` expose the control bit, while pending events, mode state, and peer queues remain check pointable.
- Console injection and pseudo-terminal master writes traverse the same event queue and the journaled `terminal.signal` receipt.

Evidence tier: E0.

### 7.4 Canonical editing and EOF

The terminal driver carries a stateful canonical line discipline.

- `VERASE` (`DEL`) removes one byte from the current line, `VKILL` (`Ctrl-U`) removes the current line suffix, and `VEOF` (`Ctrl-D`) exposes buffered bytes followed by one explicit EOF.
- Edit operations are consumed before the slave queue, while echo emits the corresponding erase sequence through the console history or the pseudo-terminal master queue.
- Raw mode leaves these bytes untouched, and `POLLIN` and scheduler readiness treat a pending canonical EOF as readable.
- Control characters, EOF state, line-edit configuration, peer queues, and terminal modes are included in check pointable state.
- The same line discipline applies to `/dev/console` injection and pseudo-terminal master input, preserving one driver law across external and process-local communication.

Evidence tier: E0.

### 7.5 Endpoint hangup and session teardown

Pseudo-terminal endpoint lifetime is part of the device state machine rather than only a garbage-collection concern.

- Closing the last master alias marks the surviving slave endpoint as peer-hung-up, keeps it addressable until the slave aliases also disappear, and exposes buffered bytes followed by EOF.
- The surviving endpoint reports `POLLHUP` together with readable buffered data, so descriptor waits wake instead of sleeping indefinitely.
- A master-side hangup emits one journaled `pty.hangup` event and sends `SIGHUP`, exit code `129`, to the slave's foreground process group.
- Closing the slave first marks the master side as hung up without fabricating a session signal, and final endpoint closure still reclaims the dynamic pair.
- Peer-liveness bits, terminal ownership, and one-shot event behaviour survive checkpoints, including restoration of the headless scheduler's terminal-signal bridge.

Evidence tier: E0.

## 8. Network device and owned fabric

### 8.1 Captured-frame network device

`mailcpu/network.py` is a pure packet-to-event driver. It consumes captured or emulated frames and emits:

- connection state transitions;
- payload boundaries;
- parsed HTTP events;
- malformed-packet failures;
- a receipt-chain attestation.

The device validates bounded IPv4 and TCP headers, tracks a finite RFC-shaped connection subset, parses HTTP/1.x requests and responses, reports malformed HTTP separately from malformed wire frames, computes a deterministic HDC projection, and anchors every semantic event in the shared journal receipt chain. It is integrated into the virtual environment and the checkpoint graph. Evidence tier: E0.

**REQUIRED** Connection to an owned real link MUST follow recorded `E0` conformance.

### 8.2 Owned namespaces and links

`mailcpu/owned_network.py` is an information-logistics layer above the captured-frame device of clause 8.1.

- Namespaces and interfaces are explicit graph vertices with bounded identifiers, MTUs, administrative state, and bounded receive FIFOs.
- Links are point-to-point edges, so a frame is accepted only when source and destination are the two attached endpoints of one owned link.
- Frame identity, logical time, source and destination addresses, payload bytes, queue capacity, and topology are check pointable and restored.
- `net_namespace_create`, `net_interface_create`, `net_connect`, `net_send`, `net_receive`, and `net_info` expose the external operating-system boundary.
- `net_send_from` and `net_receive_into` move bytes through a scheduled program's own virtual memory, with capability checks and preflight before destructive dequeue.
- All effects are journaled, malformed topology and over-MTU or over-capacity
  sends fail explicitly. The owned fabric remains in-process; the explicit
  `SocketTransport` boundary carries its typed message algebra to external
  controlled peers. The external loopback witness also carries a durable
  hypervisor proposal relay and a remote page provider over a real
  `AF_INET` connection; public-infrastructure reachability remains a separate
  obligation.

Evidence tier: E1. Linux network-namespace compatibility and public-infrastructure reachability are later infrastructure stages.

### 8.3 Owned-link driver adapter

`OwnedLinkDriver` bridges an owned interface queue into the captured-frame decoder of clause 8.1 under a commit-after-accept rule:

```text
frame := peek(Q_endpoint)
events := E0.ingest(frame.logical_time, frame.payload)
dequeue(Q_endpoint, frame)       # only after ingest succeeds
```

A malformed or unsupported semantic frame remains queued for inspection and retry. An accepted frame is removed only after the decoder has emitted its journaled events. The adapter preserves the `E0`/`E1` evidence distinction. Evidence tier: E0 at the decoder boundary and E1 at the owned queue boundary.

### 8.4 Multi-hop owned routing

The owned fabric carries a forwarding plane across namespace interfaces.

- A same-namespace interface transition models forwarding inside an owned namespace, and an attached link models a point-to-point edge.
- Breadth-first route selection is deterministic, with lexical tie-breaking and explicit refusal when no active path exists.
- The selected route is stored on every frame, is check pointable, and is recorded in `network.route.forward` journal events.
- The effective MTU is the minimum interface MTU along the route, so forwarding cannot accept a frame that an intermediate interface cannot carry.
- `net_route_send` and `net_route_send_from` expose routed transmission at the operating-system and scheduled-program boundaries.

Evidence tier: E1. Linux namespace implementation and public Internet reachability are later infrastructure stages.

## 9. Datagram and stream layers

### 9.1 Typed datagram sockets

`mailcpu/datagram.py` is a protocol and socket layer above routed raw frames.

- The `MCPD` envelope uses explicit magic, version, flags, source and destination ports, and length fields, with exact-length decoding.
- `OwnedDatagramStack` binds `(namespace, interface, port)` identities, maintains bounded socket inboxes, and demultiplexes frames without host sockets.
- Socket receive is FIFO and size-atomic: a too-small caller buffer leaves the raw or socket head unchanged.
- Socket bindings, queued decoded datagrams, frame routes, and monotone identities survive checkpoint and restore.
- `net_dgram_bind`, `net_dgram_send`, `net_dgram_receive`, `net_dgram_info`, `net_dgram_send_from`, and `net_dgram_receive_into` cross the headless operating-system boundary.
- A scheduled program stages a datagram payload in virtual memory and retrieves it through the same native trap path.

Evidence tier: E1. POSIX and BSD socket compatibility and public-network reachability are later infrastructure stages.

A diagnostic command, `python -m mailcpu network-demo`, boots a routed four-interface topology, binds source and destination ports, transmits a binary datagram, validates the receipt chain, and reports the selected route.

### 9.2 Bounded stream sockets

`mailcpu/stream.py` sits above the routed fabric.

- Listeners own explicit `(namespace, interface, port, backlog)` state and return deterministic accepted connection handles.
- Connections carry local and peer identities, role, state, cumulative sequence and acknowledgement counters, bounded send windows, pending byte accounting, and receive buffers.
- Stream payloads are segmented against route MTU, delivered in order, acknowledged cumulatively, and refused when queue, window, or sequence bounds would be violated.
- `FIN` transitions provide close and EOF semantics, and all connection, listener, and buffer state is check pointable.
- `net_stream_listen`, `net_stream_connect`, `net_stream_accept`, `net_stream_send`, `net_stream_receive`, `net_stream_close`, `net_stream_info`, and memory-backed send and receive variants cross the headless operating-system boundary.
- The datagram route diagnostic of clause 9.1 remains available; stream behaviour is covered by direct, check pointed, and scheduled-program tests.

Evidence tier: E1. TCP congestion control, retransmission over loss, BSD descriptor ABI, and Linux socket compatibility are outside the boundary.

## 10. Reliable communication and durable transport

### 10.1 Durable hash-chained mailbox transport

The communication substrate carries a persistence-backed transport independent of the in-memory queue.

- `DurableMailboxTransport` stores `ENQUEUE`, FIFO `DEQUEUE`, and identity-based `CONSUME` events in an append-only, fsync'd JSON log.
- Each record carries a sequence number, predecessor receipt, and SHA-256 receipt, so complete-record tampering, reordering, duplication, and truncation are explicit failures.
- Binary payloads and nested tuple and list structure use an injective tagged encoding and round-trip without type collapse.
- Reopening replays the product state `(Q,L,next_id)`. Only an incomplete final append is truncated; a malformed complete record refuses startup.
- Reliable-channel pending frames and acknowledgements continue across transport reopen, giving retry state a durable mailbox beneath it.
- A single-writer lock serializes local append critical sections.

The local durable mailbox and the replicated external mailbox are both explicit
stages. `ReplicatedMailboxStore` persists operation records on each controlled
node, and `ReplicatedMailboxNode` requires durable replica application before
acknowledgement and reports quorum receipts. Evidence tier: E1 for controlled
multi-node paths. Sequence-window negotiation below the channel and
network-provider durability guarantees remain the next stage.

### 10.2 Checkpointable reliable communication

The reliable channel and its transport substrate persist together.

- `ReliableChannel.snapshot/from_snapshot` preserves pending frames, sequence allocation, receiver deduplication, retry leases, tick state, and failed sequences.
- Message bodies use recursive binary-safe tags, so bytes remain bytes after restore.
- `InMemoryTransport` persists FIFO queues, message identities, and counters.
- `FaultInjectingTransport` persists staged delayed copies, clock, send index, fault observations, and its inner FIFO.
- A dropped frame is restored and retried to one delivered payload with one acknowledgement.

Evidence tier: E0.

### 10.3 Bounded sequence windows

Reliable communication carries explicit sender backpressure.

- `ReliabilityPolicy.window_size` enforces the invariant `|pending| ≤ W` before allocating or sending a sequence.
- A full window raises typed `ReliableChannelWouldBlock` evidence rather than growing unbounded retry state.
- Acknowledgements and explicit retry-budget failures release capacity, and `available_window` exposes the remaining admission budget.
- Window size and pending cardinality are validated across checkpoint restore, with version-1 snapshots migrating to the default window.
- The at-least-once retry, deduplication, durable mailbox, and fault-injection paths of clauses 10.1 and 10.2 use the same sequence identities.

Evidence tier: E0.

### 10.4 Durable hypervisor revision relay

`ReplicatedRevisionProposalRelay` carries a `HypervisorRevisionProposal`
through the existing `ReplicatedMailboxNode` without introducing a second
retry or quorum protocol.

- Submission uses the existing durable `ENQUEUE` operation and returns its
  operation identity for quorum receipt inspection.
- A remote replica durably applies the mailbox operation before its reliable
  acknowledgement; the proposal remains a typed FIFO message after transport
  delivery.
- The relay binds proposal source to the durable node identity, validates the
  mailbox envelope, and arbitrates before durable `CONSUME`.
- FIFO proposals remain recoverable after remote store reopen. Malformed or
  same-identity conflicting proposals remain at the mailbox head for diagnosis
  and retry rather than being silently discarded.
- The same envelope is exercised over an actual `SocketTransport.listen` /
  `connect` pair: the canonical body is compared after durable decode and
  before remote admission, so framing and mailbox persistence cannot silently
  alter the proposal.
- A remote page provider on that external path supplies a reclaimed page by
  content digest; virtual-memory fault recovery verifies the exact original
  bytes rather than merely successful transport.

Evidence tier: E1 for controlled multi-node persistence and relay admission.

### 10.5 Cross-host recovery coordination

Recovery composes the transport, reliable channel, durable mailbox, and
hypervisor ledgers rather than creating a second delivery identity.

- A peer reset is a closed-stream observation when no incomplete frame remains;
  a partial frame still fails explicitly and cannot be checkpointed as a
  message.
- A restored reliable sender retains every pending frame `F_s`, while the
  restored receiver retains delivered sequence set `D` and cursor `r`.
- After a new stream is bound, retransmission of `F_s` produces `ACK(s)` even
  when `s∈D`; the durable replica applies equal operation identity `o` as a
  no-op, preserving one mailbox message.
- The coordinator receipt becomes committed when `1+|A(o)|≥q`, and the
  target-aware hypervisor relay then admits the proposal once through its
  checkpointed identity ledger.

The direct witness closes a real TCP connection after replica application and
before sender acknowledgement processing, checkpoints both hosts, reconnects
with `SocketTransport.from_snapshot`, retransmits the pending operation, and
checks one durable message plus one intent revision admission. Evidence tier:
E1.

The public `CrossHostRecoveryCoordinator` now owns that composition. Its
`checkpoint()` captures the product `(T,R,N)` of socket, reliable-channel, and
durable-mailbox state; `rebind()` validates local/peer identity and inbound or
outbound channel direction before returning a live binding. `retry()` and
`service()` expose the existing lease and durable receive transitions, while
`status()` reports pending sequences, acknowledged peers, quorum commitment,
mailbox cardinality, and the latest semantic admission result. `admit_next()`
uses the existing relay arbitration and does not create a second delivery or
authority ledger.

The coordinator witness also round-trips its composite checkpoint and refuses
a direction mismatch before binding a socket. Evidence tier: E1.

The `CrossHostMultiPeerRecoveryCoordinator` extends the same product to every
peer factor of one durable node. It restores all outbound and inbound channel
maps together, exposes pending sequences by peer, and preserves the existing
quorum predicate during partial recovery. A three-host witness loses one ACK,
replays the other from its transport checkpoint, reports `2 < q=3` until the
lost peer is retransmitted, and then reaches `1+|A|=3` without duplicating the
durable mailbox message. Evidence tier: E1.

### 10.6 Typed hypervisor operation adapters

The hypervisor exposes typed adapters for operation domains that already have
native execution paths. Each adapter constructs one `HypervisorRequest` from
canonical operation, resource, and payload data, derives rights from the
calling process capabilities, and invokes its native handler only after the
existing policy returns `ALLOW`.

- Filesystem reads, service starts, and network ingestion remain covered by
  the original adapter witness.
- Process launch is represented by `HypervisorDomain.PROCESS` and delegates to
  `launch_file(..., loader_pid=pid)`, so executable reads and child creation
  retain the caller's authority context.
- Package installation is represented by `HypervisorDomain.PACKAGE`, requires
  `write` on `/package/<digest>`, marks the operation destructive, and invokes
  `ImageRegistry.install` only after policy admission. The registry remains
  responsible for digest verification and supported-image admission.
- A missing required right returns `DENY` without invoking the handler. A
  destructive package operation returns `REVIEW` under the default policy and
  leaves the filesystem unchanged.

The process and package witnesses exercise both allowed and refused paths,
including exact no-side-effect checks. Evidence tier: E0.

### 10.7 Hypervisor operation transport

`HypervisorOperationChannel` carries `HypervisorArbitrationEvent` through the
existing reliable channel and TCP frame codec. It validates the operation kind,
peer-bound source, channel, typed request, and transport sequence while the
frame is still peeked. `receive_and_execute` applies a receiver authority
function before `HypervisorArbitrationLoop.execute`, and consumes/acknowledges
the frame only after a typed effect result exists.

The receiver authority function reconstructs `granted_rights` from its local
process capability graph and preserves the event identity and temporal state;
remote authority claims are therefore inputs to inspect, not proof of local
access. A duplicate reliable frame after a lost acknowledgement may be
consumed and acknowledged again, but the effect ledger returns the stored
canonical effect without invoking the native handler. A malformed frame,
changed identity, or authority-construction failure is not acknowledged.

The AF_INET witness sends a process launch, closes the origin before processing
its acknowledgement, checkpoints both channels and the replica hypervisor,
reconnects, retransmits, and observes one child plus one replayed effect. A
second event carrying a forged `execute` grant is denied by a receiver process
that lacks that capability. Evidence tier: E1.

`HypervisorOperationRecoveryCoordinator` owns the single-peer recovery product
`(SocketTransport, ReliableChannel, HeadlessOS, direction, peer)`. Its
checkpoint/rebind path validates endpoint direction before restoring the
reliable FIFO and hypervisor effect ledger; `retry`, `service`, `send`, and
`receive_and_execute` expose the existing transitions without introducing a
second delivery or authority ledger. The coordinator witness produces the same
one-child, one-effect result as the manual Log 84 path and clears the restored
sender's pending sequence after the replay acknowledgement. Evidence tier: E1.

The same path also carries a `PACKAGE` event. Under explicit destructive-policy
admission, the receiver invokes only its local digest-verified registry and
returns `{"digest": h}` after the image files are present. Package authority is
therefore receiver-local in the same way as process `execute` authority.

`HypervisorOperationResultChannel` carries the typed execution result over a
reverse reliable channel. The executor sends the result before acknowledging
the request frame, so a response-send failure leaves the request retryable. The
initiator deduplicates response frames by the operation identity rather than
the response transport sequence, and checkpoints that semantic response
ledger. Thus a repeated request or a lost response acknowledgement can create
multiple transport frames while returning one effect.

`HypervisorOperationDuplexRecoveryCoordinator` composes both directions into
one checkpoint product. An origin owns request-outbound and result-inbound
factors; an executor owns request-inbound and result-outbound factors. Capture
and rebind validate that both TCP peers, reliable channels, operation identity,
role, and the headless effect ledger agree before exposing a live coordinator.
Retry and acknowledgement service operate only on the role's outbound factor,
while the executor's response semantic ledger remains part of the checkpoint.
The AF_INET duplex witness loses both request and response acknowledgements,
restores both sockets and FIFOs, returns replayed effects, and proves one
native process mutation. The same witness forms a process/package advisory
intent corpus from live operation states, checks held-out predictions, and
promotes the candidate only through the typed intent revision gate.

`RecoveryPolicyAdvertisement`, `RecoveryPolicyOffer`, and
`RecoveryPolicyAgreement` establish the receiver's recovery boundary before a
future handoff. The receiver advertises checkpoint kinds, target transport
substrates, maximum window, minimum lease, retry budget, cross-transport
permission, and effect-ledger support. The sender offers its requested source
and target; the receiver computes the bounded intersection
`W=min(W_sender,W_max)`, `L=max(L_sender,L_min)`, and
`R=min(R_sender,R_max)`. The policy channel carries these typed frames over
the existing reliable peer-bound path, leaving malformed or incompatible
heads queued without acknowledgement. This stage negotiates readiness only;
the later migration stage will bind the agreement to a target transport and
checkpoint movement.

`TransportMigrationCheckpoint` and `CrossTransportRecoveryCoordinator` now
bind that agreement to the first actual handoff: a reliable channel can move
from `SocketTransport` to a shared `InMemoryTransport` while preserving its
pending sequence, queued mailbox messages, payload, and receive cursor. The
source message storage identity is allowed to change because it is below the
reliable protocol identity. Agreement mismatch, target-substrate mismatch, or
invalid queue state refuses before the target is changed. This establishes
single-channel migration; duplex operation/result migration and durable
multi-host handoff remain subsequent compositions.

`DuplexTransportMigrationCheckpoint` and
`CrossTransportDuplexRecoveryCoordinator` now compose that handoff for one
hypervisor role. Request and result reliable factors, the result semantic
ledger, and the headless hypervisor snapshot move together into one shared
in-memory mailbox substrate. A shadow target must restore both directions and
the operation identity before the real target is changed. The migrated result
ledger returns an exact retransmission as a replay, the original native effect
remains singular, and both acknowledgement paths clear their pending frames.
This is still one role product; namespace isolation for multiple emulated
systems and durable multi-host duplex movement are subsequent obligations.

`SystemSeed` provides the first state-space navigation boundary. It encodes a
complete origin state `S_0`, its canonical digest `d_0`, a non-negative logical
coordinate `k`, the expected digest of `T^k(S_0)`, and a strictly ordered input
event prefix `E`, where `T` is the existing deterministic scheduler transition.
An input event records its source/sequence, target process/mailbox, integer
payload, target coordinate, and payload digest. Reading a seed reconstructs the
origin, injects each event immediately before its target tick, and replays to
`k`; rewind filters events after the requested coordinate and reconstructs the
same origin. Unreachable coordinates, origin tampering, input-event tampering,
and replay-digest mismatch refuse explicitly. Host admission metadata is held
at its neutral checkpoint identity in the seed projection, so the Hypervisor
can govern a seeded system without recursively changing the system state it
verifies. Algebraic orbit leaps and reversible-gate descent remain separate
certified navigators that may later replace replay only after their witnesses
prove the same state digest.

`SystemSeedEnvelope` lifts that seed boundary into a transport product for shared
hosting. Its identity is `I=(system_id,incarnation)`, and its route is an
injective namespace function of `(I,role,channel)`, so two systems or two
incarnations cannot share a mailbox by endpoint-label coincidence. The envelope
also carries the role, channel, complete `SystemSeed`, and a sorted frontier of
external-input receipts `(source,sequence,digest)` and the corresponding
replayable input-event prefix inside the seed. Its byte encoding uses the
repository's injective canonical value algebra, preserving tuples, lists,
bytes, and mappings before hashing; this makes a decoded envelope state-equal to
the source envelope rather than merely JSON-shaped like it. `to_message` and
`from_message` bind the envelope bytes to the derived route, and host restore
requires the expected identity before the seed is replayed. Real in-memory and
AF_INET transport tests exercise the same envelope bytes, while duplicate
frontier receipts, digest changes, and forged routes refuse before state
restoration. This leaves admission policy, authoritative frontier advancement,
and durable multi-host ownership as the next composition over the typed boundary.

### 10.8 Hypervisor seed admission

`HeadlessOS.seed_admission` is the authoritative registry for hosted seed
envelopes. `HypervisorSeedAdmissionCoordinator` shares the kernel's
hash-chained `EventJournal` with the classifier Hypervisor and persists its
registry and replay ledger in the OS checkpoint. Before any registry mutation,
it reconstructs the seed from its checkpoint payload and replays it; an invalid
origin or state digest therefore becomes a journaled refusal with no partial
registration.

For each `system_id`, the registry admits a new system or a higher incarnation.
Within one incarnation, the seed origin digest is invariant, the scheduler
coordinate cannot decrease, and the per-source maximal input frontier cannot
regress or change the digest at an equal sequence. A frontier extension must
advance the seed coordinate. Exact envelope bytes are keyed by their SHA-256
fingerprint and return the original admission or refusal receipt on
retransmission. A stale incarnation, frontier regression, origin conflict,
same-coordinate state conflict, or invalid restore leaves the current envelope
unchanged. Checkpoint restore reconstructs both the current registry and the
fingerprint ledger before the host resumes. Seed-state projection neutralizes
the admission registry and removes `hypervisor.seed.*` control records from all
shared journal views, so Hypervisor bookkeeping does not create false logical
state divergence.

### 10.9 Event-aware input and atomic live commit

`HypervisorSeedAdmissionCoordinator.advance_input` is the first live frontier
advance path. It derives the next seed by injecting one typed external event at
the next scheduler coordinate, appends the event's payload receipt to the
frontier, and submits the resulting envelope through ordinary admission. An
exact retransmission reconstructs the original event-prefix envelope, returns
its original receipt, and leaves the later authoritative envelope in place for
the caller; a changed payload for the same source/sequence is a conflict. The
resulting seed can be restored independently to inspect the new virtual state
before a later host-commit layer applies it to a long-lived process.

`HeadlessOS.commit_seed_input` closes that boundary for one admitted live host.
It first requires the projected live digest to equal the current admitted seed,
derives a candidate without mutating the registry, and executes the input on a
shadow checkpoint. The live input is applied only after the shadow digest equals
the candidate state digest. A post-transition mismatch or admission refusal
restores the complete pre-commit checkpoint, while an exact duplicate returns
its original receipt without re-injecting the input. This is an atomic local
commit witness: trajectory writers checkpoint and truncate their suffix during
rollback as well. Multi-host ownership and durable remote commit remain later
composition layers.

## 11. Images and execution regimes

### 11.1 Source assembly and headless execution

The assembler boundary provides labels, typed operand lowering, round-trip disassembly, and explicit malformed-source failures. `mailcpu/assembler.py` is a label-aware assembler and disassembler.

**REQUIRED** The source compiler MUST target the existing `Program` validation boundary and MUST NOT create a second instruction semantics.

**REQUIRED** Assembler output MUST round-trip through the image loader.

### 11.2 Execution regimes

An executable **image** carries an **execution regime** tag:

```text
regime ∈ {MAILCPU, SENSE, LEAP, HDC, MDL}
```

`MAILCPU` is the only admitted regime. `LEAP` is admissible only where a recurrence domain is established by a bounded conformance obligation; otherwise the runtime falls back to forward execution. `HDC` and `SENSE` remain typed data-plane operations and are not implicit replacements for exact integer state. `SENSE`, `LEAP`, `HDC`, and `MDL` tags are preserved as image metadata and fail closed until the corresponding interpreters and their admission obligations exist.

### 11.3 Validated binary executable images

Image version 2 carries a bounded tagged `MCPB` bytecode payload in addition to its readable instruction graph. The loader reconstructs `Program` from the binary, reapplies all static validation, compares the resulting graph with the human-readable representation, and refuses corruption or disagreement. Version 1 graph-only images remain readable for migration, and image digests commit to the compiled bytes.

`ArtifactIngestor` unifies the input path above the image loader. Magic-first
detection admits UTF-8 assembly through `assemble`, MCPB through
`BytecodeExecutable.from_bytes`, and ELF through `parse_elf`. Each result
contains source and admitted-content SHA-256 identities. MailCPU formats
produce `ExecutableImage`; ELF produces `ElfImage` and remains a staged loader
artifact, including its interpreter and dynamic-segment metadata.

### 11.4 Native binary userland loader

The virtual executable path admits readable assembly source and validated native `MCPB` bytecode.

- `install_binary(path, program)` serializes the same validated `Program` graph through `BytecodeExecutable` and stores it in the virtual filesystem with execute mode.
- `launch_file`, `spawn_file`, direct `exec_file`, and scheduled `exec` use one descriptor-backed loader that detects native magic, validates bounds, tags, and program invariants, and otherwise preserves UTF-8 source compatibility.
- Binary replacement is decoded before virtual machine image mutation, so malformed bytecode returns an explicit failure and leaves the prior process image untouched.
- Native bytecode execution remains inside the `MAILCPU` regime; unsupported polymorphic image regimes fail closed rather than falling back silently.

Evidence tier: E0.

### 11.5 ELF program-header loader

The executable boundary admits ELF payloads for virtual-memory staging.

- ELF32 and ELF64 little-endian and big-endian identification and headers are parsed with bounded program-header tables and supported-machine validation.
- `PT_LOAD` intervals enforce file and memory size ordering, page congruence, alignment, non-overlap, address bounds, and entry-point containment.
- `PT_INTERP` and dynamic-segment presence are retained as loader metadata rather than executed or discarded.
- `PT_DYNAMIC` metadata is decoded into bounded `DT_NEEDED`, soname/search-path,
  dynamic-symbol, and REL/RELA records. `ElfImage.plan_relocations` emits
  relative and explicitly bound symbol write intents with load-bias arithmetic;
  unresolved symbols and unsupported relocation types remain typed failures.
- `DynamicLinker` resolves named providers, deduplicates dependency cycles,
  assigns deterministic page-aligned ET_DYN bases, stages all images into a
  clone, and commits supported relocation writes only after target preflight.
  Missing providers, incompatible sonames, read-only targets, and unsupported
  relocation families preserve the caller memory image.
- `DynamicLinker.link_runtime` resolves the `PT_INTERP` path through the same
  provider relation, adds its dependency graph in deterministic order, and
  commits the main image, dependencies, and interpreter together. The
  resulting `ElfStartupState` separates the main `AT_ENTRY` from the
  interpreter's initial entry and records `AT_BASE`, `AT_PHDR`, `AT_PHENT`,
  `AT_PHNUM`, `AT_PAGESZ`, `AT_FLAGS`, and `AT_NULL` wherever metadata is
  derivable.
- `materialize_startup_stack` publishes argc, argv, environment, auxiliary
  vector, and NUL-terminated strings in one aligned virtual-memory mapping.
  Every pointer targets the same mapping, environment order is deterministic,
  and the mapping is committed only after clone-local writes succeed.
- `ExecutionBackendRegistry` admits only one validator for each exact
  `(machine,bits)` identity. `ElfRuntimeLoader.admit` composes dynamic
  linking, startup-stack materialization, candidate validation, and one final
  memory commit. It returns an `ElfExecutionHandoff` only after the matching
  backend accepts the entry and stack state; missing or rejecting backends
  leave the caller memory image unchanged.
- Load staging maps maximal page runs, copies file-backed bytes, preserves zero-filled BSS, and applies writable and non-writable page protections while exposing declared executable pages separately.
- `HeadlessOS.load_elf_image` reads the payload through the virtual descriptor path, journals its digest, entry point, and load bias, and stages it into a process memory image.

**REQUIRED** No instruction backend is fabricated for a foreign architecture. A parsed ELF image remains a staged artifact, and foreign instruction execution fails closed until a verified CPU and ABI backend is supplied.

Evidence tier: E0.

Dynamic planning, provider application, and runtime handoff are E0
deterministic artifact operations. The transactional linker boundary loads
named providers and mutates only a validated memory clone before commit. A
native instruction backend, signal startup, and libc initialization remain
separate boundaries; the handoff becomes executable when a verified backend is
registered for the exact machine and width.

### 11.6 Numbered POSIX boundary

`PosixCompatibility` is the first standard-numbered userland boundary. For
Linux x86-64 syscall number `n`, process `p`, and argument record `a`, it
computes

`Π(p,n,a) = (r,e)`

with `e=0` and native result `r` on success, or `r=-e` with `e∈Errno` on
failure. The adapter invokes the existing native transition for every backed
case and records failure errno in the process record and journal.

The current numbered domain is:

| Number | Name | Native transition | Pointer contract |
|---:|---|---|---|
| 0 | `read` | `read_into` | destination bytes are preflighted before descriptor read |
| 1 | `write` | `write_from` | source bytes are preflighted before descriptor write |
| 2 | `open` | `open` + `fcntl` | pathname is a NUL-terminated virtual-memory string |
| 3 | `close` | `close` | none |
| 5 | `fstat` | `fstat` + `mem_write` | fixed 144-byte x86-64 record |
| 8 | `lseek` | `lseek` | none |
| 9 | `mmap` | `mmap` | anonymous private page interval |
| 10 | `mprotect` | `mprotect` | aligned page interval |
| 11 | `munmap` | `munmap` | aligned page interval |
| 22 | `pipe` | `pipe_into` | two 32-bit descriptors are written atomically |
| 32 | `dup` | `dup` | shared open description |
| 33 | `dup2` | `dup2` | target replacement follows native descriptor law |
| 39 | `getpid` | `getpid` | none |
| 59 | `execve` | `exec_file` | path, argv, and environment are bounded virtual-memory vectors |
| 60 | `exit` | `exit` | process termination is native |
| 61 | `wait4` | `waitpid` + `mem_write` | four-byte encoded exit status; `WNOHANG` supported |
| 72 | `fcntl` | `fcntl` | descriptor-local and shared flags remain distinct |
| 79 | `getcwd` | `getcwd_into` | NUL-terminated cwd is written to virtual memory |
| 80 | `chdir` | `chdir` | pathname is a NUL-terminated virtual-memory string |

The adapter currently admits private anonymous mappings and modeled read/write
protection. `fork`, `brk`, `rusage`, executable page permissions, sockets, ELF
interpreter handoff, and broader flag families require their own backed
contracts. An unsupported number returns `ENOSYS`; an unsupported argument
family returns `EINVAL`; no unsupported behavior is represented as success.

`execve` decodes each pointer vector to its first null pointer, bounds both
vector length and string length, rejects malformed or duplicated environment
keys, and validates the complete replacement before image mutation. It admits
the existing source and MCPB executable loader. Foreign ELF instruction
execution and interpreter instruction startup remain separate boundaries;
stack and auxiliary-vector materialization are provided by the ELF handoff
surface.

Evidence tier: E0.

## 12. Control plane

### 12.1 Classifier-shaped hypervisor

The published TypeSafe AI contract supplies a public question-and-answer shape:

```text
shared state + typed questions
    -> probability distributions / score / binary probability
    -> confidence-aware deterministic policy
    -> capability-gated execution
```

It does not license assumptions about private model internals. `mailcpu/classifier.py` provides:

- bounded `Choice`, `Score`, and `Noul` question and result types;
- a deterministic lexical `E0` reference model behind a pluggable classifier boundary;
- Choice and Score confidence formulas;
- a **hypervisor** that selects CPU, filesystem, network, process, package, service, and review domains;
- hard missing-**right** denial, confidence review gates, destructive-operation review, and explicit handler dispatch;
- hash-chained `hypervisor.decision` receipts and check pointable model identity and policy thresholds.

`HypervisorArbitrationLoop` adds the first bounded RSI control loop around that
authority function:

```text
Receive(source, channel, sequence, logical_time, request)
    -> Stabilize(identity, canonical_fingerprint)
    -> Inspect(decision_receipt, replay/conflict)
```

The first event with identity `(source, channel, sequence)` evaluates the
existing policy once and records its request fingerprint and decision receipt.
An exact retransmission returns the original receipt without a second policy
evaluation; a changed payload under the same identity fails closed. The ledger
and cycle count participate in headless checkpoints. This loop is an
idempotent arbitration boundary, not an authority-changing model promotion;
future candidate revisions must pass a withheld witness corpus before
promotion.

`HypervisorArbitrationLoop.execute()` extends that boundary to native effects.
For the same identity it stores
`I ↦ (fingerprint, decision_receipt, action, domain, effect)`. An allowed
handler runs once and commits a canonical JSON effect; a denied or reviewed
operation commits an empty effect without invoking its handler; an exact
retransmission returns the stored effect without mutation; and a changed
payload is refused. The effect ledger participates in the same headless
checkpoint, making a lost acknowledgement recoverable for process and package
operations rather than merely recoverable for their policy decisions.

Every admitted decision also records the hypervisor revision that produced it.
The arbitration ledger therefore preserves `I ↦ (fingerprint, receipt,
revision)`. A duplicate returns the original receipt and original revision even
after a newer classifier revision is admitted; checkpoint restore preserves the
same binding. A legacy ledger entry without this field is interpreted as
revision `0`.

`ClassifierHypervisor.admit_classifier_revision` is the classifier revision
gate. It evaluates a classifier candidate in a shadow hypervisor with the
current policy, intent model, and virtual capacity. Promotion commits only
when every supplied witness reproduces the policy projection `(action, domain,
probabilities, confidence, risk, intent, virtual_cost)`. The active classifier
remains unchanged on any mismatch or shadow failure. Accepted revisions
increment a checkpointed revision number and record the candidate identity and
witness digest; refused revisions record their mismatch without changing
authority.

`ClassifierHypervisor.admit_intent_revision` is the typed advisory-model gate.
It reconstructs only an `IntentPrototypeModel`, checks every held-out
prediction, and evaluates current and candidate intent models in isolated
shadow hypervisors. With action permissiveness ordered by
`rank(DENY)=0 < rank(REVIEW)=1 < rank(ALLOW)=2`, promotion requires
`rank(action_candidate) ≤ rank(action_current)` for every witness. Intent
training may increase review, but cannot grant an operation that the current
hypervisor would deny or review. The active classifier and intent model remain
unchanged on any mismatch, stale baseline, or authority expansion.

`HypervisorRevisionProposal` carries a checkpointable candidate snapshot and
witness corpus through the same source/channel/sequence identity law as
arbitration. Its explicit target selects `classifier` or `intent`; envelopes
without a target remain classifier proposals for compatibility.
`HypervisorArbitrationLoop.propose_revision` reconstructs only the admitted
target-specific model kinds, applies the target gate once, stores the proposal
fingerprint and admission result, and returns that result on an exact
retransmission without a second promotion. A changed proposal under the same
identity fails closed; malformed model reconstruction is a journaled refusal.
The target, proposal ledger, and admission result checkpoint with the headless
OS.

`HypervisorRevisionChannel` carries the canonical envelope over the existing
`ReliableChannel` and therefore over the framed TCP implementation without
creating a second delivery protocol. It validates the proposal while peeking
and acknowledges only after reconstruction succeeds. The channel binds the
proposal source and channel to the expected peer; malformed, spoofed, or
wrong-kind payloads remain queued and unacknowledged.

The composed `receive_and_arbitrate` path keeps the validated frame queued
through revision arbitration. A same-identity conflict or other arbitration
exception therefore leaves both the data frame and acknowledgement mailbox
unchanged; only a typed first-seen or replay result permits reliable consume
and acknowledgement.

The hypervisor is a control plane and not an opaque authority. Operating-system surfaces remain callable as native APIs while their typed adapter boundaries are added. Each adapter MUST preserve `ALLOW ⇒ one authorized handler`, and a learned or remote model MUST pass the `E0` replay and adversarial corpus of clause 13 before **admission**.

Evidence tier: E0.

### 12.2 Procedural decision model

Procedural-model research material, including its generation tests, contributes design hypotheses about addressable parameters, deterministic regeneration, explicit refusal, and exactness before leaping. `mailcpu/procedural_model.py` provides:

- a finite generator specification `(model, seed, feature buckets, temperature)`;
- SHA-256 with the explicitly vendored address permutation for weights regenerated on demand instead of a stored dense weight matrix;
- deterministic hashed feature vectors and typed `Choice`, `Score`, and `Noul` evaluation;
- check pointable generator identity and model selection;
- no dependency on the external research runtime.

The procedural model is the default classifier inside the hypervisor; the lexical model of clause 12.1 remains a comparison oracle. The research boundary, the copied-source policy, and the adoption obligations are recorded in `docs/BOUNDARY_PROCEDURAL_MODEL.md`.

Evidence tier: E0.

### 12.3 Signal dispositions

The process control plane carries an explicit disposition ABI.

- A process selects `default` or `ignore` for typed signals through the integer-safe `signal_set_ignored` and `signal_is_ignored` system calls.
- An ignored disposition is inherited by child creation and preserved through checkpoints, and terminal and explicit signal delivery consult the same disposition map.
- `SIGKILL` and `SIGSTOP` cannot be ignored, and a malformed restored disposition map is rejected before continuation.
- An ignored `SIGHUP` makes pseudo-terminal master closure a state-preserving event for that process, with a journaled `signal.ignored` receipt.
- The native scheduled ABI remains integer-only.

Evidence tier: E0.

### 12.4 Process environments and image registry

Process environments are scoped to the process record, are inherited per the process ABI of clause 4.3, and are check pointable with the kernel. The local image registry is digest-addressed: an entry commits to the compiled bytes of clause 11.3, and registry digest identity and tamper rejection are part of the acceptance corpus of clause 13.

## 13. Acceptance corpus

### 13.1 Required suites

**REQUIRED** The acceptance corpus MUST contain cross-language and adversarial suites covering:

- byte-identical trajectory streams;
- image and assembler round trips;
- source-file-to-process execution with explicit bounded, blocked, and halted outcomes;
- procedural VFS determinism;
- `E0` TCP/HTTP event and receipt determinism;
- environment, signal, and process lifecycle transitions;
- registry digest identity and tamper rejection;
- transport corruption and Byzantine-lane diagnosis;
- execution regime fallback and refusal;
- replay from trajectory alone.

### 13.2 Per-subsystem coverage

**REQUIRED** Additional per-subsystem obligations are stated at the point of use: the memory corpus of clause 5.1, the stream and datagram scheduled-program tests of clause 9.2, and the descriptor-flag domain validation of clause 6.5.

## 14. Statements requiring independent verification

The reference documents contain strong performance and universality statements,
including large leap dividends, zero-storage "infinite" memory, and Linux
scheduler replacement. Each such statement MUST carry:

1. its mathematical domain and invariant;
2. a reference implementation;
3. a bounded resource model;
4. an adversarial test;
5. an evidence tier `E0`, `E1`, or `E2`;
6. a refusal or fallback path when the invariant does not hold.

## 15. Copy policy

The reference corpus is not distributed with this repository, and its sources are not imported by production code. The boundary record for the single vendored primitive, including what was deliberately not copied, is `docs/BOUNDARY_PROCEDURAL_MODEL.md`.

**REQUIRED** Ported code belongs in `mailcpu/` only after it carries MailCPU-native annotations, tests, and a clear semantic boundary.

Reference-suite results do not certify the unported C, Rust, build, benchmark, or public-infrastructure statements.

## 16. Obligations

The following are **REQUIRED** staged obligations. Each is stated relative to the mechanism it extends.

1. Receipt accounting for procedural providers, and a `/proc` provider surface beyond the provider interface of clause 3.
2. Signal and cancellation semantics beyond termination; migration compatibility for checkpoint and image formats; crash-recovery transaction boundaries.
3. Broader process-group lifecycle policy beyond init adoption, and subreaper policy beyond the init fallback of clause 4.6.
4. Multi-tier policy, execute permissions on pages, physically deduplicated shared-page accounting for shared mappings, and differential tests against selected POSIX memory behaviour.
5. Timed blocking deadlines on structured `poll`, `epoll` edge and one-shot modes, cancellation tokens, descriptor leases, `pidfd` semantics, and socket option and `ioctl` breadth.
6. Partial-write semantics for oversized atomic pipe payloads, and a complete Linux `PIPE_BUF` atomicity policy.
7. Numerical Linux errno identity for every system call, signal interruption, `EINTR` restart policy, `SIGPIPE`, and a libc-compatible return ABI.
8. Credential passing, multi-message ancillary vectors, and cross-host rights migration above the descriptor rights contract of clause 6.6.
9. `fork`/`clone` completeness, copy-on-write image sharing across process snapshots, startup-stack integration with process creation, and broader auxiliary-vector construction.
10. A broader dynamic-loader ABI: interpreter loading, dynamic linking, relocations, and host binary passthrough.
11. A foreign CPU and ABI backend for staged ELF images.
12. A typed protocol and socket layer above raw routed frames, link-state negotiation, and differential conformance tests against native semantics, above clauses 9.1, 9.2, and 8.4.
13. An evidence-bearing adapter for an owned real link, admitted only after recorded `E0` conformance per clause 8.1.
14. Retransmission over loss, receiver-advertised windows, congestion control, and loss-recovery policy above the bounded native stream layer of clause 9.2.
15. A replicated durable mailbox backend, transactional multi-host acknowledgement commits, sequence-window negotiation below the channel, and cross-transport migration, above clauses 10.1 and 10.3.
16. Terminal and session integration breadth: configurable control-character tables, window geometry, packet mode, alternate line disciplines, `SA_RESTART`, user signal handlers, signal masks, `sigaction` structures, and alternate signal stacks.
17. Typed classifier adapters for filesystem, network, service, process, and package operations are established by clause 10.6; future adapters must preserve the same deterministic policy and refusal boundary.
18. A bounded procedural feature registry whose addresses are named by operating-system ABI fields rather than free text alone.
19. A procedural attention stage, admitted only after convergence, normalization, and refusal tests exist.
20. A proven recurrence and leap adapter admitted separately from classification, such that model acceleration never changes exact process semantics silently.
21. Differential conformance testing against the **reference interpreter** for every mechanism above `δ`.

## 17. Staged obligations

The following capabilities are the next stages of the same system and remain to
be connected through the transition algebra.

1. Public infrastructure and E2 operation above the controlled socket transport.
2. Linux, BSD, or POSIX ABI compatibility for memory, processes, descriptors, syscalls, sockets, terminals, or images. Each compatibility layer follows differential testing against the reference interpreter.
3. Foreign CPU instruction execution. The ELF loader of clause 11.5 validates and stages; it does not relocate, link, bind `libc`, or emulate.
4. Host terminal attachment. The terminal law of clause 7 is entirely inside the virtual state graph.
5. Reproduction of any undisclosed third-party internal model architecture.
6. Learned-intelligence semantics attributed to a procedural hash; high classifier confidence remains an advisory signal while exact policy establishes correctness.
7. Cryptographic primitives.
8. Dependency on, or distribution of, the reference corpus named in clause 1.2.
9. Treating the reference corpus performance and universality statements of clause 14 as completed system behavior.
10. A verified drop-in kernel assembled from the reference corpus.
