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

#### Requirements
1. **WASM-to-MailCPU Transpiler**: Map WebAssembly linear memory and typed control-flow operations to MailCPU content-addressed pages and mailbox queues $\mathcal{Q}$.
2. **LLVM Architecture Target**: Implement a MailCPU code generator targeting the fundamental nine-instruction transition algebra (`SET`, `COPY`, `ADD`, `COMPARE`, `BRANCH`, `SEND`, `WAIT`, `SYSCALL`, `HALT`).
3. **Dynamic ELF Loader & Relocation**: Extend static segment staging in `mailcpu/elf.py` to support dynamic linking, symbol tables, and relocations.

---

### 2.2 Physical Network Transport & Reflection Mesh ($\mathcal{L}_{\text{fabric}}$)

Transition the execution substrate from local in-memory emulation ($E0$) to physically distributed infrastructure ($E1/E2$), where in-flight packets serve as state storage.

$$\text{Capacity } C = \sum_{p \in \text{Paths}} B_p \times \text{RTT}_p$$

#### Requirements
1. **Echo Reflector Daemons**: Bare-metal, UDP, or eBPF packet-reflection services that circulate state packets with sequence and timestamp accounting.
2. **Dynamic Jitter & Path Profiler**: Measure network path distributions in real time to establish safe slot allocations:
   $$\Delta \ge 3\sigma_{\text{jitter}}$$
3. **Hardware-Level Packet Schedulers**: Integrate kernel bypass (e.g., AF_XDP or io_uring) to eliminate host scheduler jitter from the logical tick loop.

---

### 2.3 Distributed Consensus & Replicated Persistence ($\mathcal{L}_{\text{consensus}}$)

Enable distributed multi-node coordination without centralized single-points-of-failure or shared host RAM.

$$\mathcal{H}_n^{(i)} = \mathcal{H}_n^{(j)} \quad \forall i, j \in \text{ActiveNodes}$$

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

#### Requirements
1. **Remote Page Eviction & Faulting**: Connect `mem_reclaim` to network-backed storage, transparently faulting evicted pages back via content-addressed digests.
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

#### Requirements
1. **Standard C Runtime (Musl Libc)**: Port and validate a standard C runtime against native MailCPU syscall traps.
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
