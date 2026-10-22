# MailCPU Future Buildout Requirements

Architectural requirements and engineering milestones to scale MailCPU from a verified local prototype into a distributed, network-resident execution environment.

Defined terms follow `docs/GLOSSARY.md`. Core system architecture is specified in `docs/ARCHITECTURE.md`.

---

## 1. System Target Formulation

The ultimate target is a distributed, network-resident operating environment $\mathcal{U}$:

$$\mathcal{U} = \langle \mathcal{L}_{\text{toolchain}}, \mathcal{L}_{\text{fabric}}, \mathcal{L}_{\text{consensus}}, \mathcal{L}_{\text{memory}}, \mathcal{L}_{\text{acceleration}}, \mathcal{L}_{\text{userland}} \rangle$$

The system preserves the primary invariant that feature semantics above the transport boundary are invariant under substrate transitions:

$$\delta(K, \text{request}) = (K', \text{reply}, \text{emitted}) \quad \forall \text{Substrates}$$

---

## 2. Engineering Pillars

### 2.1 Toolchain & Ingestion Layer ($\mathcal{L}_{\text{toolchain}}$)

To support general-purpose programming languages (C, Rust, Zig, Go), the instruction set architecture must be an ingestion target for standard compiler backends.

$$\mathcal{P}_{\text{High}} \xrightarrow{\quad\text{Clang/Rustc}\quad} \text{WASM / LLVM-IR} \xrightarrow{\quad\text{Codegen}\quad} \text{MCPB (v2 Tagged Bytecode)}$$

#### Stage 4 implemented

`ArtifactIngestor` is the shared admission boundary for UTF-8 assembly,
validated MCPB bytecode, and ELF payloads. It preserves source/content
digests, produces the existing `ExecutableImage` for MailCPU artifacts, and
retains ELF loader metadata without pretending that dynamic native binaries
are already executable by the MailCPU scheduler. The `ingest` CLI command
reports the same typed result and writes only validated outputs.

#### Stage 5 implemented

`ElfImage` now decodes bounded `PT_DYNAMIC` string, dependency, symbol, and
REL/RELA relocation tables. `plan_relocations` resolves load-bias-relative
actions and requires explicit bindings for undefined symbols, producing a
typed immutable `DynamicLinkPlan`; dependency loading and memory mutation are
the next linker slice.

#### Stage 6 implemented

`DynamicLinker` now resolves named ELF providers, deduplicates dependency
cycles, assigns deterministic page-aligned bases, builds a complete symbol map,
and applies supported relocation words to a staging clone before committing it
to virtual memory. Missing dependencies, unsupported relocation types, and
read-only targets preserve the caller's memory state.

#### Requirements
1. **WASM-to-MailCPU Transpiler**: Map WebAssembly linear memory and typed control-flow operations to MailCPU content-addressed pages and mailbox queues $\mathcal{Q}$.
2. **LLVM Architecture Target**: Implement a MailCPU code generator targeting the fundamental nine-instruction transition algebra (`SET`, `COPY`, `ADD`, `COMPARE`, `BRANCH`, `SEND`, `WAIT`, `SYSCALL`, `HALT`).
3. **Dynamic ELF Loader & Relocation**: Extend static segment staging in `mailcpu/elf.py` to support dynamic linking, symbol tables, and relocations. **Dynamic metadata parsing, relocation planning, provider resolution, and transactional application are implemented; broader ABI/linker coverage remains.**

---

### 2.2 Physical Network Transport & Reflection Mesh ($\mathcal{L}_{\text{fabric}}$)

Transition the execution substrate from local in-memory emulation ($E0$) to physically distributed infrastructure ($E1/E2$), where in-flight packets serve as state storage.

$$\text{Capacity } C = \sum_{p \in \text{Paths}} B_p \times \text{RTT}_p$$

#### Stage 1 implemented

`mailcpu/socket_transport.py` now provides a real TCP framed path for the
existing typed MailCPU message algebra. Canonical receipts, partial-frame
reassembly, peer identity binding, bounded backpressure, queue semantics, and
rebound checkpoint state are exercised over loopback TCP. The next fabric slice
is controlled reflector daemons and path profiling above this transport.

#### Requirements
1. **Echo Reflector Daemons**: Bare-metal, UDP, or eBPF packet-reflection services that circulate state packets with sequence and timestamp accounting.
2. **Dynamic Jitter & Path Profiler**: Measure network path distributions in real time to establish safe slot allocations:
   $$\Delta \ge 3\sigma_{\text{jitter}}$$
3. **Hardware-Level Packet Schedulers**: Integrate kernel bypass (e.g., AF_XDP or io_uring) to eliminate host scheduler jitter from the logical tick loop.

---

### 2.3 Distributed Consensus & Replicated Persistence ($\mathcal{L}_{\text{consensus}}$)

Enable distributed multi-node coordination without centralized single-points-of-failure or shared host RAM.

$$\mathcal{H}_n^{(i)} = \mathcal{H}_n^{(j)} \quad \forall i, j \in \text{ActiveNodes}$$

#### Stage 2 implemented

`ReplicatedMailboxStore` provides per-node hash-chained operation persistence,
FIFO mailbox replay, operation-id deduplication, and torn-final-record repair.
`ReplicatedMailboxNode` sends those operations through the Stage 1 socket path
and emits acknowledgements only after durable replica application. Quorum
receipts are explicit; full consensus election, receiver-window negotiation,
and public provider durability remain subsequent slices.

#### Requirements
1. **Replicated Journal Log**: Implement distributed consensus (Raft or Paxos variants) over addressable mailbox streams.
2. **Coprime Loop Striping & CRT Decoding**: Exploit coprime loop periods $(L_1, \dots, L_k)$ with $\gcd(L_i, L_j) = 1$:
   $$\Omega = \prod_{i=1}^k L_i, \quad x \equiv x_i \pmod{L_i}$$
   Reconstruct state erasures across network drops without point-to-point retransmission.
3. **Two-Phase Message Commits**: Ensure transactional delivery and deduplication across independent mailbox boundaries.

---

### 2.4 Hierarchical Virtual Memory & Remote Paging ($\mathcal{L}_{\text{memory}}$)

Expand virtual memory beyond local host allocations into a multi-tier distributed storage hierarchy.

$$\text{Memory Hierarchy } = \begin{cases}
\text{Tier 0: Resident Host Pages} & (\tau < 1\,\mu\text{s}) \\
\text{Tier 1: Local Content-Addressed Storage} & (\tau \sim 100\,\mu\text{s}) \\
\text{Tier 2: In-Flight Network Delay Loops} & (\tau \sim 10-100\,\text{ms}) \\
\text{Tier 3: Remote Peer Mailbox Store} & (\tau \sim 100-500\,\text{ms})
\end{cases}$$

#### Stage 3 implemented

`RemotePageStore` supplies fixed-size SHA-256 page CAS files with atomic
publication, request/response transfer over bidirectional replicated mailbox
channels, restart-safe local recovery, duplicate-safe page delivery, and
explicit missing/corrupt-page failures. `VirtualMemory` accepts this backing
provider; reclaim publishes before reservation and a later fault resolves the
same page identity through the provider.

#### Requirements
1. **Remote Page Eviction & Faulting**: Connect `mem_reclaim` to network-backed storage, transparently faulting evicted pages back via content-addressed digests. **Implemented by `RemotePageStore` and `PageBacking`.**
2. **Distributed Copy-on-Write (CoW)**: Share pages across remote nodes via SHA-256 digests, eliminating eager memory copies during distributed process spawns.

---

### 2.5 Algebraic Acceleration & Orbit Leap Scheduling ($\mathcal{L}_{\text{acceleration}}$)

Overcome network round-trip time bounds on step execution:

$$f_{\text{clock}} \le \frac{1}{\text{RTT}}$$

Analytically accelerate predictable computation loops via orbit leaping:

$$s_t = T^t(s_0) \quad \xrightarrow{\quad\text{Leap}\quad} \quad s_t = \Lambda(s_0, t) \quad \text{in } \mathcal{O}(\log t)$$

#### Requirements
1. **Loop Recurrence Engine**: Detect linear or affine transformations in compiled code and generate closed-form state advancement functions.
2. **Formal Witness Gate**: Verify algebraic leaps against bounded witness executions before journal commitment, ensuring strict trace equivalence with step-by-step execution.

---

### 2.6 Userland Surface & POSIX Compatibility ($\mathcal{L}_{\text{userland}}$)

Provide complete binary and ABI compatibility so unmodified UNIX tools execute natively within MailCPU processes.

$$\delta_{\text{syscall}} : \text{ABI}_{\text{standard}} \to \mathcal{K} \times \text{Receipt}$$

#### Stage 7 implemented

`PosixCompatibility` provides a numbered Linux x86-64 boundary over the
existing MailCPU kernel. Pointer paths and buffers cross through the virtual
memory ABI; `fstat` emits a fixed 144-byte x86-64 record; `wait4` encodes
child status; `mmap`/`mprotect`/`munmap`, descriptor duplication and flags,
file positioning, `pipe`, process identity, `exit`, `getcwd`, `chdir`, and
pointer-vector `execve` are translated through native transitions. Unsupported
syscall numbers and unsupported flag/protection families return explicit errno
results, and compound pointer destinations are preflighted before state
mutation.

#### Requirements
1. **Standard C Runtime (Musl Libc)**: Port and validate a standard C runtime against the numbered foundation, adding pointer-vector `execve`, interpreter handoff, and broader errno/structure coverage.
2. **Terminal & PTY Full Session Ecosystem**: Support complete job control, session switching, and ANSI line disciplines to run interactive shells (Bash, Dash, Zsh).
3. **OCI Container Rootfs Importer**: Ingest standard container filesystem layers directly into content-addressed inode trees.

---

## 3. Dependency Graph

```text
[1. Toolchain / WASM Target] ──┐
                               ▼
[6. Musl Libc / POSIX ABI] ──> [Functional Userland & Compiler Execution]
                               ▲
[4. Distributed Remote Paging] ─┤
                               ▼
[2. Physical Delay Loops] ───> [3. Consensus & CRT Striping] ───> [5. Leap Scheduling]
```


---

## 4. Iteration 2 Delivery Status & Iteration 3 Requirements

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│                       ITERATION MILESTONE PROGRESS                          │
├───────────────────────────────┬────────────┬────────────────────────────────┤
│ Subsystem / Capability        │ Status     │ Target Milestone               │
├───────────────────────────────┼────────────┼────────────────────────────────┤
│ Reversible Core & Chronofold  │ COMPLETED  │ Iteration 2 (Workstream 1)     │
│ Physical Delay Loops & RRNS   │ COMPLETED  │ Iteration 2 (Workstream 2)     │
│ DNS Latches & TCP Arithmetic  │ COMPLETED  │ Iteration 2 (Workstream 3)     │
│ Law Lifter & Orbit Leap       │ COMPLETED  │ Iteration 2 (Workstream 4)     │
│ Chemical Time & Holonomy      │ COMPLETED  │ Iteration 2 (Workstream 5)     │
│ Neural Distillation & Sim     │ COMPLETED  │ Iteration 2 (Workstream 6)     │
│ JIT Law Lifter in Scheduler   │ PLANNED    │ Iteration 3                    │
│ Adaptive Modulus Restriping   │ PLANNED    │ Iteration 3                    │
│ Multi-Hop Distributed Delay   │ PLANNED    │ Iteration 3                    │
│ POSIX syscall foundation      │ COMPLETE   │ Iteration 3                    │
│ Musl Libc / POSIX Userland    │ PLANNED    │ Iteration 3                    │
└───────────────────────────────┴────────────┴────────────────────────────────┘
```
