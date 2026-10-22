# MailCPU Iteration 2: Comprehensive Architecture & Build Plan

Blueprint for transforming MailCPU from a local verified reference implementation into a unified, reversible, self-verifying, distributed computing ecosystem.

Defined terms follow `docs/GLOSSARY.md`. Core architecture follows `docs/ARCHITECTURE.md`. Substrate physics and information-theoretic formulations follow `docs/COMMUNICATION_SUBSTRATES_AND_INFORMATION_THEORY.md`. Cross-paradigm temporal models and synthesis follow `docs/CROSS_SYSTEM_SYNTHESIS_TIME_COMPUTATION_MODELS.md`.

---

## 1. System Vision & Governing Equations

Iteration 1 established the substrate-independent message-passing virtual machine, content-addressed virtual file system, and deterministic capability hypervisor.

Iteration 2 unifies MailCPU with the reversible physics of **Virtual Quanta** and the algebraic law certification of **VL_Logic Compiler**, constructing a virtual computer whose memory and execution are embedded directly into ambient communication substrates:

$$\mathcal{U}_2 = \langle \mathcal{S}_{\text{substrate}}, \; \mathcal{E}_{\text{reversible}}, \; \mathcal{L}_{\text{law\_lifter}}, \; \mathcal{T}_{\text{chemical}}, \; \mathcal{P}_{\text{capability}} \rangle$$

Where:
- $\mathcal{S}_{\text{substrate}}$: Physical in-flight network delay lines, Anantharam-Verdú timing channels, DNS TTL decaying latches, and TCP sliding-window arithmetic operators.
- $\mathcal{E}_{\text{reversible}}$: Involutive gate micro-ops ($X$, `swap`), chronofolded periodicity metadata, and discrete geometric phase accumulation ($D = (-i)^{n_{\text{active}}}$) supporting exact virtual-energy backtracking in the model.
- $\mathcal{L}_{\text{law\_lifter}}$: The $\Omega_5 = (\text{STATE}, \text{LIFT}, \text{NAVIGATE}, \text{DESCEND}, \text{VERIFY})$ loop that transforms raw message streams into certified closed-form algebraic laws, accelerating execution via logarithmic orbit leaps.
- $\mathcal{T}_{\text{chemical}}$: A unified triple-time coordinate $\tau_{\text{system}} = \langle \lambda_{\text{event}}, \; \tau_{\text{chronon}}, \; \tau_{\text{chem}} \rangle$, where structural parsing difficulty is the currency of memory persistence bounded by the $t_{\text{horizon}} = \text{first\_bad}$ horizon.
- $\mathcal{P}_{\text{capability}}$: Deterministic cryptographic authority boundary isolating advisory neural lifter proposals from execution dispatch.

---

## 2. Information-Theoretic Substrate Integration

Iteration 2 grounds its storage and operational primitives in the physical mechanisms detailed in `docs/COMMUNICATION_SUBSTRATES_AND_INFORMATION_THEORY.md`.

### 2.1 Bandwidth-Delay Scaling (BDS) & Memory Loops

In physical communication media (optical fiber, transoceanic cables, satellite links), state exists in transit. The storage capacity of a set of circulating network loops is governed by the Bandwidth-Delay Product (BDP):

$$C_{\text{physical}} = \sum_{p \in \text{Paths}} B_p \times \text{RTT}_p = \sum_{p \in \text{Paths}} B_p \times \frac{2 d_p}{v_p}$$

Where $B_p$ is available path bandwidth, $\text{RTT}_p$ is round-trip propagation delay, $d_p$ is physical route length, and $v_p \approx 2.04 \times 10^8\,\text{m/s}$ is wavefront velocity in optical silica.

#### Delay-Line Stability & Slot Clamping
For circulating packet streams, network jitter $\sigma_{\text{jitter}}$ induces packet reordering and potential collisions. To guarantee collision-free loop circulation, the frame injection slot width $\Delta_{\text{slot}}$ is bounded by:

$$\Delta_{\text{slot}} \ge 3 \sigma_{\text{jitter}}$$

Under packet loss probability $p$, an unprotected circulating block of $M$ frames has a half-life of:

$$t_{1/2} = \frac{\text{RTT} \cdot \ln 2}{M \cdot p}$$

To achieve persistence without host RAM anchoring, MailCPU pairs delay loops with continuous regeneration and algebraic erasure coding.

### 2.2 Redundant Residue Number System (RRNS) & CRT Erasure Recovery

State is striped across $n$ asymmetric network loops having coprime round-trip times $\tau_1, \tau_2, \dots, \tau_n$.

Let $\{m_1, m_2, \dots, m_k, m_{k+1}, \dots, m_n\}$ be pairwise coprime moduli ($m_i < m_{i+1}$). The system encodes integer state $X$ into residues $r_i = X \bmod m_i$:

- **Information Dynamic Range**: $M = \prod_{i=1}^k m_i$
- **Redundancy Range**: $M_R = \prod_{j=k+1}^n m_j$
- **Total Range**: $M_T = M \cdot M_R = \prod_{i=1}^n m_i$

By the Chinese Remainder Theorem (CRT), given any $k$ uncorrupted residue packets, the original state $X \in [0, M)$ is reconstructed uniquely:

$$X = \left( \sum_{i=1}^k r_i \cdot M_i \cdot \left( M_i^{-1} \bmod m_i \right) \right) \bmod M, \quad \text{where } M_i = \frac{M}{m_i}$$

#### Error Detection & Correction:
Any transmission corruption causing $X \ge M$ falls into the redundant interval $[M, M_T)$ and is flagged as an invalid state, providing zero-overhead error detection and multi-packet burst erasure tolerance across lossy WAN paths.

### 2.3 Anantharam-Verdú Timing Channels

Beyond payload bits, information is encoded in the inter-packet arrival cadence. For Poisson packet arrival rate $\lambda$ and server service rate $\mu$, the Anantharam-Verdú capacity bound is:

$$C_{\text{timing}}^{\max} = \frac{\mu}{e \ln 2} \approx 0.5307\,\mu \quad [\text{bits/s}]$$

MailCPU implements **Discrete Cadence Modulation (DCM)**, encoding virtual machine opcode and operand symbols $d \in \{0, \dots, 2^B - 1\}$ into quantized inter-packet delays:

$$\Delta t_k = \Delta_0 + d \cdot \delta_{\text{quantum}}$$

A Phase-Locked Loop (PLL) filter and Maximum Likelihood Estimator (MLE) demodulate the timing symbol stream in the presence of Gaussian network transit jitter $\mathcal{N}(0, \sigma^2)$.

### 2.4 DNS TTL as Universal Decaying Capacitor Latches

Recursive DNS resolver caches function as global, distributed, semi-persistent memory cells:

$$\text{TTL}_{\text{remaining}}(t) = \max(0, \text{TTL}_0 - (t - t_{\text{insert}}))$$

1. **Presence Bits via Non-Authoritative Probing**:
   - Querying a resolver with recursion disabled (`RD=0`) measures cache presence. Low response latency ($\le 5\,\text{ms}$) indicates a stored bit `1`; upstream resolution timeout or failure indicates bit `0`.
2. **Negative Caching (RFC 2308)**:
   - Queried non-existent domain labels store an `NXDOMAIN` state bounded by the SOA record's minimum TTL, creating an inverted capacitor latch for binary state flags.

### 2.5 TCP Sliding Window & Flow Dynamics as Arithmetic Operators

The TCP sequence space $\mathbb{Z}_{2^{32}}$ and Additive-Increase Multiplicative-Decrease (AIMD) congestion control operators provide decentralized arithmetic evaluation:

$$W_{t+1} = \begin{cases} W_t + \frac{1}{W_t} & \text{on ACK (linear accumulation)} \\ W_t \times \beta & \text{on packet loss (multiplicative descent)} \end{cases}$$

MailCPU harnesses this mechanism as an autonomous backpressure controller, regulating execution concurrency without centralized mutexes.

---

## 3. External Ingestion & Asset Adaptation Catalog

Specific algorithms, modules, and data structures identified for adaptation or integration:

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│                        EXTERNAL ADAPTATION MAP                               │
├─────────────────────────────────────┬────────────────────────────────────────┤
│  Virtual Quanta Source Component    │  MailCPU Iteration 2 Target Role       │
├─────────────────────────────────────┼────────────────────────────────────────┤
│ vquanta/gates.py                    │ mailcpu/reversible_gates.py            │
│ vquanta/temporal.py                 │ mailcpu/chronofold.py                  │
│ vquanta/warp.py                     │ mailcpu/masked_calendar.py             │
│ vquanta/holonomy.py                 │ mailcpu/holonomy_engine.py             │
├─────────────────────────────────────┼────────────────────────────────────────┤
│  VL_Logic Compiler Source           │  MailCPU Iteration 2 Target Role       │
├─────────────────────────────────────┼────────────────────────────────────────┤
│ alt_resources/inetcpu/rrns.py       │ mailcpu/rrns.py                        │
│ alt_resources/inetcpu/icmploop.py   │ mailcpu/delay_loop.py                  │
│ alt_resources/inetcpu/dns_cells.py  │ mailcpu/dns_cell.py                    │
│ VL_Embed/vl_agents/wide_cert.py     │ mailcpu/law_certifier.py               │
│ VL_Embed/vl_agents/chemical_time.py │ mailcpu/chemical_time.py               │
│ VL_Embed/vl_agents/vantage.py       │ mailcpu/vantage_transform.py           │
│ VL_Embed/vl_agents/mixture_cert.py  │ mailcpu/mixture_decomposition.py       │
│ VL_Embed/vl_ladder/distill.py       │ mailcpu/neural_lifter.py               │
└─────────────────────────────────────┴────────────────────────────────────────┘
```

### 3.1 Virtual Quanta Assets
1. ***vquanta/gates.py***:
   - *Core Asset*: Involutive gate primitives ($X$, `swap`), bitwise tape operations, and self-inverse gate reversal:
     $$(G_n \circ \dots \circ G_1)^{-1} = G_1 \circ \dots \circ G_n$$
   - *Target*: Implements reversible micro-ops beneath the 9-instruction MailCPU algebra, enabling zero-entropy state backtracking without full checkpoint snapshots.
2. ***vquanta/temporal.py***:
   - *Core Asset*: Chronofolding serializer, shift-periodic witness metadata, active chronon phase accumulation ($D = (-i)^{\#\text{active}}$), and Bennett constant-space tape recomputation.
   - *Target*: Establishes a validated periodicity index while retaining the trace; compact trace rewriting is a subsequent build requiring its own replay and corruption tests.
3. ***vquanta/warp.py***:
   - *Core Asset*: Mask-based SIMT predication without branch jumps.
   - *Target*: Eliminates timing-channel side leaks and branch-prediction divergence in distributed multi-node execution.
4. ***vquanta/holonomy.py***:
   - *Core Asset*: Non-Abelian Wilczek-Zee geometric phase evaluation:
     $$H(\Omega) = |e\rangle\langle B(\Omega)| + |B(\Omega)\rangle\langle e|, \quad U = \exp(-i \chi (\mathbf{n} \cdot \boldsymbol{\sigma}))$$
   - *Target*: Provides continuous geometric phase coordinates for multi-agent consensus and continuous state tracking.

### 3.2 VL_Logic Compiler Assets
1. ***alt_resources/inetcpu/rrns.py* & *icmploop.py***:
   - *Core Asset*: Redundant Residue Number System (RRNS) Chinese Remainder Theorem coder and live ICMP/UDP echo loop circulating buffers.
   - *Target*: Forms the production physical substrate driver for in-flight memory loops.
2. ***alt_resources/inetcpu/dns_cells.py***:
   - *Core Asset*: DNS TTL probing, negative caching latches, and non-authoritative cache presence decoders.
   - *Target*: Supplies global, distributed, semi-persistent decaying memory cells.
3. ***VL_Embed/vl_agents/wide_cert.py***:
    - *Core Asset*: Algebraic law certifier covering the implemented six-rung ladder (`int`, `lcg`, `gf2`, `fgraph`, `kreg`, `tape`).
   - *Target*: Bridges raw message streams into certified closed-form mathematical functions.
4. ***VL_Embed/vl_agents/chemical_time.py* & *persistence.py***:
   - *Core Asset*: Chemical time parsing metrics and `first_bad` persistence horizon tracking.
   - *Target*: Allocates virtual machine memory and execution priority proportional to stream complexity.
5. ***VL_Embed/vl_agents/vantage.py* & *mixture_cert.py***:
   - *Core Asset*: Vantage-point transformations (decimation, difference, integration, modulus fold) and residue stride decomposition.
   - *Target*: Decomposes chaotic or refused network streams into solvable parallel ground components.
6. ***VL_Embed/vl_ladder/distill.py***:
   - *Core Asset*: Feature extraction and classification pipeline training compact neural heads on algebraic state sequences.
   - *Target*: Implements fast zero-shot model guidance within the hypervisor.

---

## 4. Engineering Workstreams & Implementation Plan

```mermaid
flowchart TD
    subgraph S1["Workstream 1: Reversible Core"]
        A["mailcpu/reversible_gates.py"] --> B["mailcpu/chronofold.py"]
        B --> C["Chronofolded Scheduler"]
    end

    subgraph S2["Workstream 2: Substrate Drivers"]
        D["mailcpu/delay_loop.py"] --> E["mailcpu/rrns.py"]
        E --> F["mailcpu/timing_channel.py"]
    end

    subgraph S3["Workstream 3: Application Substrates"]
        G["mailcpu/dns_cell.py"] --> H["mailcpu/tcp_arithmetic.py"]
    end

    subgraph S4["Workstream 4: Law Lifter & Orbit Leap"]
        I["mailcpu/law_certifier.py"] --> J["mailcpu/vantage_transform.py"]
        J --> K["mailcpu/mixture_decomposition.py"]
        K --> L["Orbit Leap Accelerator"]
    end

    subgraph S5["Workstream 5: Unified Time & Holonomy"]
        M["mailcpu/chemical_time.py"] --> N["mailcpu/holonomy_engine.py"]
    end

    subgraph S6["Workstream 6: Neural Distillation & Tooling"]
        O["mailcpu/neural_lifter.py"] --> P["mailcpu/substrate_sim.py"]
        P --> Q["CLI Subcommands & MCA2 Packaging"]
    end

    S1 --> Core["MailCPU Iteration 2 Kernel"]
    S2 --> Core
    S3 --> Core
    S4 --> Core
    S5 --> Core
    S6 --> Core
```

---

### Workstream 1: Reversible Core & Chronofolded Scheduler

**Status**: `COMPLETED` (Verified: 10/10 test suite passing, full scheduler integration)

Integrate involutive gate mechanics and chronofolded execution into `mailcpu/kernel.py` and `mailcpu/scheduler.py`.

$$\text{Transition Storage: } \mathcal{O}(N) \text{ full states} \quad \xrightarrow{\quad\text{Chronofold}\quad} \quad \mathcal{O}(1) \text{ snapshots} + \text{periodic trace header}$$

#### Implemented Components & Verification:
1. `mailcpu/reversible_gates.py` (Completed):
   - Involutive gate primitives (`KIND_X`, `KIND_SWAP`), bitwise tape operations, and self-inverse gate sequences:
     $$(G_m \circ \dots \circ G_1)^{-1} = G_1 \circ \dots \circ G_m$$
   - Bennett zero-restoring bit allocator and reversible arithmetic networks (`emit_xor_add`, `emit_xor_sub`, `emit_xor_mul`, `emit_bitwise`, `emit_shl`, `emit_shr`, `emit_inc`).
2. `mailcpu/chronofold.py` (Completed):
   - Shift-periodic allocator snapshots: detects periodic recurrence $t_{i+P} = t_i + S$ across trace suffixes.
   - Bennett constant-space restoration: `recompute_final_tape()` and `reverse_tape()` replaying the trajectory in $\mathcal{O}(1)$ storage without preserving intermediate tapes.
   - Serialization to/from `mailcpu-chronofold/1` format preserving initial tape, trace ledger, phase, and period headers.
3. `mailcpu/scheduler.py` **Integration** (Completed):
   - Added `chronofold` field to `ScheduledTask`.
   - `scheduler.add(..., enable_chronofold=True)` enables trajectory logging.
   - `scheduler._step()` records micro-steps and tracks discrete geometric phase ledger $D = (-i)^{n_{\text{active}}}$.
   - Preserved across process forks (`fork_task`) and checkpoint snapshots (`snapshot()` / `from_snapshot()`).
4. **Verification Gate** (`tests/test_reversible.py` - 10/10 Passed):
   - `test_gate_involution_identity`: $G(G(s)) = s$ for $X$ and swap.
   - `test_controlled_gate_predication`: mask-based condition evaluations without branching.
   - `test_reversible_adder_and_ancilla_cleanup`: carry ancillas uncomputed to zero.
   - `test_reversible_subtractor_and_multiplier`: modular ring arithmetic reversal.
   - `test_discrete_geometric_phase_ledger`: $D(n) = (-i)^n$ modulo-4 cycle.
   - `test_chronofold_periodic_trace_compression`: shift-periodic pattern detection and metadata validation.
   - `test_chronofold_bennett_constant_space_replay_and_reversal`: exact $(T^N)^{-1}(T^N(s_0)) = s_0$ tape recovery.
   - `test_chronofold_serialization_roundtrip`: JSON export/import equivalence.
   - `test_scheduler_chronofold_integration`: scheduler micro-step trace and snapshot restore.

---

### Workstream 2: Physical Network Delay Loops & Substrate Drivers

**Status**: `COMPLETED` (Verified: 11/11 tests across delay loops and timing channels passing)

Graduate from in-process loopback queues to physical network transport across internet infrastructure.

$$\text{Memory Capacity: } C_{\text{physical}} = \sum_{p \in \text{Paths}} B_p \times \text{RTT}_p$$

#### Implemented Components & Verification:
1. `mailcpu/rrns.py` (Completed):
   - Garner-free incremental Chinese Remainder Theorem (`crt`) for arbitrary coprime moduli.
   - Coprime sieve (`primes_below`) and information capacity calculation (`legit_range`).
   - Redundant Residue Number System (`encode_rrns`, `recover_rrns`): recovers integer state $V$ from any $k$ of $n$ surviving packets, asserting consistency and detecting corruptions in the redundant interval $[M, M_T)$.
   - Logarithmic affine orbit jump (`affine_orbit_jump`): evaluates $(a x + b)^n \bmod m$ in $\mathcal{O}(\log n)$ time using 2x2 matrix exponentiation.
2. `mailcpu/delay_loop.py` (Completed):
   - Delay slot abstraction (`DelaySlot`) and group manager (`DelayGroup`).
   - Datagram frame encoding/decoding (`FRAME_HEADER_FORMAT = "!HHIQ"`).
   - In-flight packet scrubbing (`scrub_group`): detects packet drop, recovers state $V$ from surviving $k$ packets, and revives missing slots with incremented version counter.
   - Dynamic slot clamping: tracks empirical RTT jitter $\sigma_{\text{jitter}}$ and enforces $\Delta_{\text{slot}} \ge 3 \sigma_{\text{jitter}}$ to eliminate packet reordering and overtaking.
3. `mailcpu/timing_channel.py` (Completed):
   - Discrete Cadence Modulation (`CadenceModulator`): maps nibbles $d \in [0, 15]$ to transmission intervals $\Delta t_k = \Delta_0 + d \cdot \delta_{\text{quantum}}$.
   - Maximum-likelihood symbol estimator (`CadenceDemodulator`) with Phase-Locked Loop (PLL) baseline drift tracking: adapts to slow route latency shifts while maintaining zero bit errors under Gaussian network jitter $\sigma < \delta / 3$.
4. **Verification Gates** (`tests/test_delay_loops.py` & `tests/test_timing_channel.py` - 11/11 Passed):
   - `test_primes_below_sieve`: prime generation correctness.
   - `test_crt_exact_reconstruction`: Garner-free incremental CRT exact recovery.
   - `test_rrns_encoding_and_erasure_recovery`: exact recovery under 2-packet erasure out of 5.
   - `test_rrns_corruption_detection`: corrupt residue detection via base extension check.
   - `test_affine_orbit_jump_equivalence`: exact equivalence between $\mathcal{O}(\log n)$ jump and 1000 iterative steps.
   - `test_delay_loop_engine_scrub_and_regeneration`: erasure recovery and slot revival.
   - `test_delay_loop_unrecoverable_loss`: detection of irreversible loss when surviving slots $< k$.
   - `test_dynamic_slot_clamping`: jitter standard deviation tracking and spacing constraint.
   - `test_cadence_modulation_and_demodulation_exact`: noiseless timing channel byte recovery.
   - `test_timing_channel_resilience_to_gaussian_jitter`: error-free transmission under Gaussian jitter.
   - `test_pll_baseline_drift_tracking`: PLL tracking of dynamic baseline latency drift.

---

### Workstream 3: DNS & Application Substrate Drivers

**Status**: `COMPLETED` (Verified: 7/7 tests across DNS latches and TCP arithmetic passing)

Expose decaying network memory and transport layer arithmetic as virtual devices in the virtual file system.

$$\text{Decaying Memory: } \text{TTL}(t) = \max(0, \text{TTL}_0 - \Delta t), \quad \text{Flow Control: } W_{t+1} = f_{\text{AIMD}}(W_t)$$

#### Implemented Components & Verification:
1. `mailcpu/dns_cell.py` (Completed):
   - Linear TTL decay evaluator (`DnsRecord`): computes $\text{TTL}_{\text{remaining}}(t) = \max(0, \text{TTL}_0 - \lfloor t - t_0 \rfloor)$.
   - Resolver simulation and probe (`DnsResolverSim`): supports positive caching, RFC 2308 negative caching (`NXDOMAIN` latches), and cache snooping via `RD=0`.
   - Multi-resolver canary polling: evaluates quorum presence across independent recursive resolver trees (`8.8.8.8`, `1.1.1.1`, `9.9.9.9`) to bypass intermediate TTL clamping.
   - Character device driver (`DnsLatchDevice`): exposes `/dev/dns_latch` with line-by-line `SET <domain> <bit> <ttl>` and `LATCH <domain>` command interface, returning active binary presence flags and checkpoint snapshot serialization.
2. `mailcpu/tcp_arithmetic.py` (Completed):
   - TCP sequence ring arithmetic over $\mathbb{Z}_{2^{32}}$: modular signed difference `seq_diff`, circular precedence `seq_less_than`, and cyclic window containment `seq_in_window` across the $2^{32}$ wraparound boundary.
   - Additive-Increase Multiplicative-Decrease feedback controller (`AimdController`): autonomous flow controller evaluating $W \leftarrow \min(W_{\max}, W + \alpha / W)$ on ACK and $W \leftarrow \max(W_{\min}, W \cdot \beta)$ on loss to regulate concurrency and backpressure without centralized mutex locks.
3. **Verification Gate** (`tests/test_dns_cells.py` - 7/7 Passed):
   - `test_dns_record_ttl_decay`: exact linear TTL countdown and expiration detection.
   - `test_dns_resolver_positive_and_negative_caching`: positive `NOERROR` and negative `NXDOMAIN` latching.
   - `test_dns_resolver_cache_snoop_rd_zero`: non-recursive probe behavior before and after upstream population.
   - `test_dns_multi_resolver_canary_poll`: multi-resolver canary presence confirmation.
   - `test_dns_latch_device_read_write_snapshot`: device read/write and checkpoint serialization.
   - `test_tcp_sequence_ring_arithmetic`: circular arithmetic and window containment across $2^{32}$ boundary.
   - `test_aimd_controller_linear_increase_and_multiplicative_drop`: linear accumulation, multiplicative descent, and concurrency dispatch gating.

---

### Workstream 4: The $\Omega_5$ Law Lifter, Vantage Transforms & Orbit Leap

**Status**: `COMPLETED` (Verified: 10/10 tests across ladder certification, vantage transforms, and mixture decomposition passing)

Overcome physical network RTT latency bounds by algebraically forecasting future state transitions.

$$s_t = T^t(s_0) \quad \xrightarrow{\quad\text{Orbit Leap}\quad} \quad s_t = \Lambda(s_0, t) \quad \text{in } \mathcal{O}(\log t) \text{ time}$$

```text
Message Stream ──> [ Vantage Transform ] ──> [ Wide Certifier ] ──> Certified Ground Law
                         │                             │                    │
                         ▼                             ▼                    ▼
                    Decimate / Diff             Ladder: lcg/gf2       Orbit Jump: O(log t)
```

#### Implemented Components & Verification:
1. `mailcpu/vantage_transform.py` (Completed):
   - Discrete vantage-point transformations for stream re-parameterization: stride decimation `vp_stride` ($\sigma_k(x)_j = x_{k j}$), discrete difference `vp_difference` ($\Delta x_j = x_{j+1} - x_j$), prefix integration `vp_integrate` ($\Sigma x_j = \sum x_i$), origin centering `vp_origin` ($\Omega(x)_j = x_j - x_0$), modular projection `vp_modulus` ($\mu_M(x)_j = x_j \bmod M$), and uniform range folding `vp_fold`.
   - Unified transform pipeline dispatch via `apply_vantage`.
2. `mailcpu/law_certifier.py` (Completed):
    - Six-rung algebraic ladder classification: integer arithmetic progression `int`, binary linear recurrence `gf2` (Berlekamp-Massey), affine congruential recurrence `lcg`, functional graph periodic orbits `fgraph` (in-window collision and Brent cycle detection), $k$-regular sequences `kreg`, and fallback `tape`.
   - Data-driven wide modulus recovery using determinant GCD invariant: $M \mid \gcd_i |d_{i+1} d_{i-1} - d_i^2|$, recovering prime and non-power-of-two moduli ($2^{31}-1$, $65537$).
   - Closed-form logarithmic orbit leaping `orbit_leap` and `lcg_navigate` evaluating $s_t = (a^t s_0 + c \sum_{i=0}^{t-1} a^i) \bmod M$ in $\mathcal{O}(\log t)$ multiplications.
   - Dual-mode inversion `find_guarded`: $\mathcal{O}(\log M)$ 2-adic bit-lifting for full-period power-of-two affine recurrences, and $\mathcal{O}(\sqrt{M})$ baby-step giant-step (BSGS) for prime-order rings.
   - Strict horizon guard enforcement: `navigate_guarded` verifies $t < t_{\text{horizon}} = \text{first\_bad}$, raising `HorizonExceeded` on attempted extrapolation beyond verified truth.
3. `mailcpu/mixture_decomposition.py` (Completed):
   - Residue stride decomposition `decompose_mixture`: searches ascending interleave periods $s \in [2, s_{\max}]$, applying residue decimation $\sigma_{s, r}(x)_q = x_{s \cdot q + r}$ to isolate concurrent processes.
   - Composite law recovery `recover_mixture`: constructs composite laws `mixture_{family}` whose closed-form leap directly routes coordinates $t$ to component $r = t \bmod s$ evaluated at stride $q = \lfloor t / s \rfloor$.
4. **Verification Gate** (`tests/test_law_certifier.py` - 10/10 Passed):
   - `test_geometric_series_sum`: $\mathcal{O}(\log t)$ geometric series modulo $M$.
   - `test_int_law_certification_and_leap`: arithmetic progression certification, leap, and $\mathcal{O}(1)$ inversion.
   - `test_lcg_power_of_two_and_adic_inversion`: affine recurrence and 2-adic bit-lifting inversion.
   - `test_lcg_wide_prime_modulus_bsgs`: prime modulus $2^{31}-1$ recovery and BSGS inversion.
   - `test_gf2_berlekamp_massey_and_jump`: Berlekamp-Massey LFSR connection polynomial and $\mathcal{O}(L^3 \log t)$ jump.
   - `test_fgraph_brent_cycle_and_orbit`: Brent cycle detection and periodic orbit navigation.
   - `test_kreg_regular_sequence`: 2-regular sequence certification and recursive navigation.
   - `test_guarded_navigation_horizon`: strict enforcement of $t < \text{first\_bad}$ raising `HorizonExceeded`.
   - `test_vantage_transforms`: stride, difference, integration, and fold transforms.
   - `test_mixture_decomposition_interleaved_streams`: multi-thread interleave separation and composite orbit leap.

---

### Workstream 5: Unified Time Coordinate & Chemical Persistence

**Status**: `COMPLETED` (Verified: 11/11 tests across chemical difficulty, horizon tracking, holonomy consensus, and scheduler epoch integration passing)

Unify event ticks, quantum chronons, and parsing difficulty into a coherent temporal framework.

$$\tau_{\text{system}} = \langle \lambda_{\text{event}}, \; \tau_{\text{chronon}}, \; \tau_{\text{chem}} \rangle$$

#### Implemented Components & Verification:
1. `mailcpu/chemical_time.py` (Completed):
   - Shannon entropy evaluator `shannon_entropy` ($H(X) = -\sum p(x) \log_2 p(x)$) and Lempel-Ziv compression bits `gzip_compressed_bits`.
   - Chemical difficulty metric `compute_chemical_difficulty` synthesizing entropy, distinct symbol ratio, first difference variation, and compression density.
   - Difficulty-as-currency memory quota `calculate_difficulty_quota` allocating workspace proportional to stream complexity: $Q = \lfloor Q_0 (1 + \alpha \log(1 + \tau_{\text{chem}})) \rfloor$.
   - Delay-loop retention scaling `calculate_retention_delay`: $t_{\text{ret}} = t_0 (1 + \beta \tau_{\text{chem}})$, protecting computationally intensive state from premature eviction.
   - Persistence horizon tracking `HorizonTracker`: strictly enforces $t < t_{\text{horizon}} = \text{first\_bad}$, raising `HorizonExceeded` on attempted extrapolation beyond verified bounds.
   - Tripartite temporal coordinate `SystemEpoch`: unifies discrete event ticks $\lambda_{\text{event}}$, discrete chronon phase factor $D = (-i)^{n_{\text{active}} \bmod 4}$, and cumulative chemical difficulty $\tau_{\text{chem}}$.
2. `mailcpu/holonomy_engine.py` (Completed):
   - $\text{SU}(2)$ Wilczek-Zee geometric phase unitary builder `make_su2_unitary`: evaluates $U(\mathbf{n}, \chi) = \cos(\chi) I_2 - i \sin(\chi) (\mathbf{n} \cdot \boldsymbol{\sigma})$ with $\det(U) = 1$ and $U^\dagger U = I_2$.
   - Spherical trajectory solid angle integration `compute_loop_solid_angle`: evaluates $\Omega_{\text{solid}} = \sum (1 - \cos\theta_k) \Delta\phi_k$ for closed parameter loops on $S^2$.
   - Gauge-invariant Frobenius distance `unitary_frobenius_distance`: $d(U_1, U_2) = \sqrt{\max(0, 2 - \text{Re}(\text{Tr}(U_1^\dagger U_2)))}$.
   - Multi-node geometric consensus coordinator `HolonomyConsensus`: registers node unitaries, evaluates maximum pairwise distance against tolerance $\epsilon_{\text{consensus}}$, detects Byzantine drift, and computes the Fréchet mean consensus centroid projected back to $\text{SU}(2)$.
3. Scheduler Integration (`mailcpu/scheduler.py` - Completed):
   - `ScheduledTask` equipped with `chemical_cost` and `horizon_tracker`.
   - `DeterministicScheduler` tracks tripartite `system_epoch`, advancing $\lambda_{\text{event}}$, chronon phase $D$, and chemical $\tau_{\text{chem}}$ on each step.
   - Step execution enforces $t < t_{\text{horizon}}$, stopping runaway extrapolation before ground state breach.
   - Checkpoint snapshot serialization and restoration of `system_epoch`, task chemical costs, and horizon bounds.
4. **Verification Gate** (`tests/test_chemical_time.py` - 11/11 Passed):
   - `test_shannon_entropy_properties`: entropy for deterministic, binary, and quaternary distributions.
   - `test_gzip_compression_bits`: compression efficiency on repetitive vs diverse sequences.
   - `test_chemical_difficulty_ranking`: ranking constant, linear, and pseudorandom streams.
   - `test_difficulty_as_currency_and_retention`: memory quota and retention delay scaling.
   - `test_horizon_tracker`: assertion of $t < t_{\text{horizon}}$ and raising `HorizonExceeded`.
   - `test_system_epoch_advancement`: event, chronon phase, and chemical tau accumulation.
   - `test_su2_wilczek_zee_unitary_group`: unitarity ($U^\dagger U = I$) and unit determinant ($\det U = 1$).
   - `test_spherical_loop_solid_angle`: exact spherical solid angle calculation for circular loop.
   - `test_unitary_frobenius_distance`: metric properties and symmetry of unitary distance.
   - `test_holonomy_consensus_agreement_and_divergence`: multi-node consensus agreement, Byzantine detection, and centroid projection.
   - `test_scheduler_chemical_time_and_horizon_integration`: scheduler system epoch progression, horizon breach interruption, and checkpoint restoration.

---

### Workstream 6: Neural Lifter Distillation, Tooling & Verification Harness

**Status**: `COMPLETED` (Verified: 9/9 tests across neural lifter and substrate simulation passing, full CLI integration)

Equip the MailCPU hypervisor with fast zero-shot model guidance while maintaining deterministic authority boundaries, and deliver a comprehensive diagnostic and simulation toolchain.

$$\text{State Stream} \xrightarrow{\quad\text{Distilled Neural Head}\quad} \text{Candidate Law} \xrightarrow{\quad\text{Deterministic Certifier}\quad} \text{Authority Allow}$$

#### Implemented Components & Verification:
1. `mailcpu/neural_lifter.py` (Completed):
   - Fast $\mathcal{O}(|w|)$ 8-feature normalized extraction (`extract_lifter_features`): Shannon entropy, distinct value ratio, binary indicator, modal difference ratio, GCD diff unit flag, determinant GCD nonzero flag, max bit length, and cycle indicator.
   - Calibrated distilled linear classification head (`DistilledRungHead`): predicts algebraic ladder rungs (`int`, `lcg`, `gf2`, `fgraph`, `kreg`, `tape`) in $\mathcal{O}(1)$ time using weights distilled from algebraic manifolds.
   - Policy Gate Isolation hypervisor (`NeuralLifterPolicy`): retains neural predictions as advisory telemetry while deterministic witness verification (`certify_stream`) alone admits or refuses laws.
2. `mailcpu/substrate_sim.py` (Completed):
   - 2-state Gilbert-Elliott Markov burst erasure channel model (`GilbertElliottChannel`): Good/Bad states with configurable transition matrix $P = \begin{pmatrix} 1-p & p \\ q & 1-q \end{pmatrix}$ and independent state drop probabilities $(p_G, p_B)$.
   - Wide-area network simulation harness (`WanSubstrateSimulator`): Gaussian propagation latency $\mathcal{N}(\mu, \sigma^2)$ clamped $\ge \mu/4$, packet loss accounting, and automated offline CI benchmarks.
   - Delay loop circulation benchmark (`benchmark_delay_loop_circulation`): tests multi-round in-flight packet circulation, erasure events, and RRNS scrubbing/regeneration.
   - Cadence timing channel benchmark (`benchmark_timing_channel`): evaluates discrete modulation bit error rate (BER) under network jitter.
3. Native CLI Integration (`mailcpu/cli.py` & `tests/test_cli_surface.py`):
   - `mailcpu lift`: runs algebraic recurrence certification and orbit leaps over trace sequences with confidence scoring.
   - `mailcpu bench`: benchmarks reversible gate cycles ($\Delta S = 0$), delay loop circulation, and law certification.
   - `mailcpu substrate`: runs WAN delay-loop circulation simulations under stochastic Gilbert-Elliott packet erasure.
   - `mailcpu chronofold`: runs reversible chronofold executions, testing period detection, chronon accumulation, and geometric phase $D = (-i)^{n_{\text{active}}}$.
   - Verified 32/32 CLI surface tests passing with complete reachability and zero exit codes.
4. **Verification Gates** (`tests/test_neural_lifter.py` & `tests/test_substrate_sim.py` - 9/9 Passed):
   - `test_feature_extraction_properties`: 8-feature invariant bounds and normalized domains.
   - `test_distilled_head_predictions`: accurate prediction of linear, LCG, binary, and periodic sequences.
   - `test_policy_gate_isolation_guarantee`: policy gate authority allow and fallback guarantees.
   - `test_policy_gate_witness_rejection`: witness mismatch rejection and fallback to deterministic ground truth.
   - `test_gilbert_elliott_channel_transitions`: Markov chain state transitions and stationary loss rate bounds.
   - `test_wan_simulator_rtt_and_jitter`: Gaussian latency distribution and minimum delay clamping.
   - `test_wan_datagram_transmission`: packet delivery and loss tracking in the network simulator.
   - `test_delay_loop_circulation_benchmark`: delay loop scrubbing and slot revival under WAN burst erasure.
   - `test_timing_channel_wan_benchmark`: error-free cadence modulation and demodulation under network jitter.

---

## 5. Verification Gates, Conformance Criteria & Test Matrix

Every phase of Iteration 2 must pass five rigorous verification gates:

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│                       ITERATION 2 VERIFICATION MATRIX                       │
├───────────────────────────┬─────────────────────────────────────────────────┤
│ Verification Gate         │ Governing Invariant / Criterion                 │
├───────────────────────────┼─────────────────────────────────────────────────┤
│ 1. Reversible Involutions │ P⁻¹(P(s)) ≡ s, D_fwd ≡ D_rev                    │
│ 2. Substrate Recovery     │ Exact CRT recovery under 20% burst packet drop  │
│ 3. Timing Channel Decode  │ Bit error rate < 10⁻⁴ under σ_jitter = 5 ms     │
│ 4. Translation Closure    │ E_noise = ||Descend(Lift(S)) - S|| ≡ 0          │
│ 5. DNS Latch Persistence  │ NXDOMAIN / positive cache presence holds TTL    │
└───────────────────────────┴─────────────────────────────────────────────────┘
```

1. **Reversible Conformance (*tests/test_reversible.py*)**:
   - Assert $P^{-1}(P(s)) \equiv s$ for all admitted programs.
   - Confirm active chronon count and phase ledger $D$ agreement between forward execution and backward unraveling.
2. **Substrate Integrity Gate (*tests/test_delay_loops.py*)**:
   - Verify RRNS packet recovery across simulated $20\%$ packet drop on multi-path delay loops.
   - Assert dynamic slot clamping $\Delta_{\text{slot}} \ge 3\sigma_{\text{jitter}}$ prevents packet reordering.
3. **Timing Channel Gate (*tests/test_timing_channel.py*)**:
   - Validate Discrete Cadence Modulation and MLE demodulation under Gaussian network jitter $\sigma_{\text{jitter}} = 5\,\text{ms}$, asserting bit error rate $\text{BER} < 10^{-4}$.
4. **Translation Invariance Gate (*tests/test_translation_closure.py*)**:
   - Assert $E_{\text{noise}} \equiv 0$ across multiple generations of state translation, lifting, and descent.
   - Verify orbit leap accuracy against standard step-by-step interpretation up to $\text{first\_bad}$.
5. **Decaying Latch Gate (*tests/test_dns_cells.py*)**:
   - Validate DNS TTL decaying latch reads without premature cache expiration.
   - Confirm negative caching (`NXDOMAIN`) bit latching for the duration of the SOA record's minimum TTL.

---

## 6. Risk Analysis & Mitigations

| Risk | Impact | Likelihood | Mitigation Strategy |
|---|---|---|---|
| **Asymmetric WAN Loss** | Delay loop packet loss exceeding $(n - k)$ threshold causes state loss. | Medium | Asymmetric RRNS striping with adaptive modulus redundancy $n - k = f(\text{packet\_loss\_rate})$. |
| **Jitter Collapse / Collisions** | Packets collide or reorder in transit, breaking FIFO delay lines. | High | Dynamic slot clamping: $\Delta_{\text{slot}} \ge 3\sigma_{\text{jitter}}$ with sequence tags in frame headers. |
| **DNS TTL Clamping** | Upstream intermediate resolvers clamp TTL to low minimums (e.g. 60s). | Medium | Multi-resolver canary polling: distribute presence bits across independent public resolver trees. |
| **Raw Socket Privilege Limits** | Non-root environments cannot send raw ICMP packets. | High | Transparent dual-mode driver: automatic fallback to UDP echo / port 7 reflectors when ICMP is unavailable. |
| **Certification False Positives** | Neural or algebraic certifier predicts an invalid closed-form law. | Low | Deterministic ground witness verification: orbit leap advances only after passing exact witness evaluation. |
