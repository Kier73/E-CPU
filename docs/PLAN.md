# MailCPU Research Plan

Hypotheses, evaluation procedure, and evidence discipline for the MailCPU
research programme.

Defined terms follow `docs/GLOSSARY.md`.

## 1. Scope

This document contains two research programmes with disjoint identifiers.

| Programme | Clauses | Identifier namespace | Status |
|---|---|---|---|
| **A — Substrate independence** | 2 through 6 | `H1` through `H4`, `Phase A0` through `Phase A7` | Specified and implemented at the `E0` tier |
| **B — Network-resident state** | 7 through 12 | `H-VL`, `P1` through `P9` | Specified; no result produced |

Identifiers MUST NOT be shared between programmes. Where a phase identifier
appears without a programme prefix, the prefix is inferred from the clause in
which it appears.

## 2. Programme A: thesis

A virtual machine whose state resides in communication infrastructure. Mailboxes
are registers, messages are instructions, and delivery is execution. One
substrate-neutral transition algebra executes over interchangeable transports
without alteration.

The target is a **finite-resource** universal emulator.

**REQUIRED** No claim is made that any email provider, relay, or transport is
itself Turing complete. Real services impose finite storage, rate limits, and
expiry, and these bounds are part of every result reported under Programme A.

## 3. Programme A: hypotheses

| ID | Claim | Pass condition | Diagnostic on failure |
|---|---|---|---|
| `H1` | The instruction primitives are computationally sufficient | A counter machine expressible as INC/DEC/JZ runs on them | Which primitive is missing or redundant |
| `H2` | Semantics are substrate-independent | Identical final state and trace on every transport | Which transport leaks semantics |
| `H3` | A minimal reliability layer restores `H2` | Passes under injected loss, duplication, and reordering | The minimum guarantee a substrate must provide |
| `H4` | Message existence encodes bits | A mailbox-group register matches a value-in-body register | The cost of bit-existence encoding |

## 4. Programme A: core specification

### 4.1 Mapping

| Machine concept | Communication concept |
|---|---|
| Register or location | Mailbox or address |
| Opcode | Subject or `OP` field |
| Operands | Body |
| Return address | Sender |
| Temporal coordinate | Timestamp or `SEQ` |
| State transition | Message arrival |
| Consumed state | Deleted message |

### 4.2 Envelope

`FROM`, `TO`, `OP`, `ADDR`, `VALUE`, `SEQ`.

### 4.3 Instruction set

`SET`, `COPY`, `ADD`, `COMPARE`, `BRANCH`, `SEND`, `WAIT`, `HALT`, `SYSCALL`.

The instruction set and its transition function are specified in
`README.md` clause 2.1.

### 4.4 Transport interface

The only varying component:

```text
send(addr, msg)
poll(addr)
consume(msg)
list(addr)
```

### 4.5 Resolved semantic questions

The following were open and are now fixed. Each is stated as a rule with its
resolution.

| Question | Resolution |
|---|---|
| Does a read consume the message? | A register read is a non-consuming observation. A `WAIT` consumes the FIFO head. |
| How is order enforced? | By `SEQ` within a mailbox, with FIFO order per address. |
| How are duplicates detected? | By message identity. The reliable channel adds deduplication on sequence number. |
| What does `WAIT` mean without a global clock? | `WAIT` blocks. A blocked task is a resumable state, not a termination. |
| How is a halted machine represented? | By a halted flag on the machine state with `pc` not advanced. |

## 5. Programme A: phases

Phase identifiers are `Phase A0` through `Phase A7`.

| Phase | Objective | Pass condition |
|---|---|---|
| `A0` | Specify mapping, envelope, and semantics; implement the transport-free reference interpreter | The reference interpreter validates every program before execution |
| `A1` | Execute the algebra over in-memory queues | Deterministic traces recordable as golden files |
| `A2` | Conformance and differential testing | The queue backend and the reference interpreter agree on `(status, state, trace, outputs)` across the random corpus |
| `A3` | Transport adapters, local before remote | A transport counts as verified only when messages cross the real service |
| `A4` | Fault injection | The set of points at which `H2` breaks is recorded exactly |
| `A5` | Reliability layer: acknowledgements, sequence windows, deduplication | `H2` holds under injected loss, duplication, and reordering |
| `A6` | Bit-existence encoding | `H4` measured against value-in-body on message count, latency, and failure modes |
| `A7` | Trajectory capture | A recorded trajectory alone reconstructs and replays the run |

**REQUIRED** A divergence between the reference interpreter and any other
backend MUST be recorded, whether or not its cause is identified. The failure map
is a deliverable.

**REQUIRED** Phase `A7` results MUST satisfy `docs/REPLACEMENT_SPEC.md`
clause 10 before any compatibility claim is admitted.

## 6. Programme A: constraints and risks

| Risk | Constraint |
|---|---|
| Provider limits | Public relay and mail providers carry rate limits and terms of service. Runs against public infrastructure are low-volume and deliberate. |
| Ordering | Mail and relay substrates provide weak ordering. `H2` is expected to fail here first; that is the intended measurement. |
| Expiry | Short-lived mailboxes expire, so long-running programs require a bounded step budget. |
| Failure logging | Every failed run is recorded with its cause. |

## 7. Programme B: scope

A machine whose memory, interconnect, clock, and a portion of its logic are
properties of the Internet itself.

The network supplies state, time, interconnect, entropy, and a bounded set of
primitives. Arbitrary logic executes at endpoints. The full-scope claim is that
the machine's state and time reside in the network, so the program's trajectory
is carried by it.

**REQUIRED** Programme B results MUST carry an evidence tier per
`docs/ARCHITECTURE.md` clause 6. A lower-tier pass MUST NOT be reported as a
higher-tier pass.

## 8. Programme B: component mapping

| Machine part | Internet mechanism | Constraint |
|---|---|---|
| Character | Unassigned | Requires a proposal |
| Delay-line memory | Packets in flight (UDP or ICMP echo) | Volatile; capacity `B x RTT`; must be regenerated |
| Cache memory | DNS TTL records; resolver, HTTP, and CDN caches | Decays on TTL; presence and absence encode a bit; readable by timing or non-recursive query |
| Queue memory | SMTP retry queues, message brokers, relay event stores | Semi-durable; weak ordering |
| Table memory | NAT and conntrack tables, ARP, BGP RIBs | Not writable by the machine; observation only |
| Interconnect | Routes, anycast, ECMP | The path is the wire; RTT is wire length |
| Clock | RTT; TTL decrement and expiry | Latency is the tick; jitter is clock noise |
| Fixed-function logic | TTL decrement-and-test, NXDOMAIN versus answer, ECMP flow hash, anycast nearest-wins | Restricted to network behaviour that is deterministic |
| Programmable logic | Endpoints under operator control | Where `ADD` and `COMPARE` execute |

## 9. Programme B: delay-line theory

### 9.1 Capacity

`C = B x RTT` per path. At 1 Gb/s and 100 ms RTT, approximately 12.5 MB is held
in flight. Capacity scales linearly with RTT.

### 9.2 Prior art and the capacity/reliability trade-off

Pingfs stores file data only within the Internet, as ICMP echo packets
travelling to remote hosts and back. Data is re-sent when a reply arrives and is
lost when no reply arrives. Close hosts give lower latency and higher
reliability at lower storage. The data resides in buffers along the path, so the
storage cost is externalised to network providers.

### 9.3 Access and compilation

Access is sequential, with worst-case latency of one period. Delay-line machines
addressed this by optimum programming, placing data so that it arrives when
required. In this formulation, compilation is placement in time.

### 9.4 Regeneration

Each arrival is re-emitted with an updated payload. Loss is an erasure.

### 9.5 Coprime loop lengths

Loops of coprime period `L_i` yield a composite state of period `prod(L_i)`. Each
loop is therefore an RNS channel and the Chinese remainder theorem provides
readout. Redundant moduli give erasure tolerance: any surviving subset whose
modulus product exceeds the value range reconstructs the value.

### 9.6 Orbit hypothesis `H-VL`

Where each loop is a known shift on `Z/L`, its state at time `t` is computable
by orbit jump in `O(log n)`. The network is then consulted to verify and correct,
which is the oracle pattern already used for DNS.

**REQUIRED** `H-VL` results MUST be reported separately from measured results.
An orbit jump that is verified but not confirmed by measurement is reported as
an unverified prediction.

## 10. Programme B: architecture

| Layer | Role |
|---|---|
| `L0` Transport adapters | The four-method interface of clause 4.4, plus send and receive timestamps |
| `L1` Substrate profiler | Per-path profile: delay distribution, loss, reorder, MTU, TTL clamping, capacity |
| `L2` Memory classes | `DelayLoop` with regeneration and RNS striping; `TTLCells`; `Queue` |
| `L3` Memory manager | Hot, warm, and cold placement; refresh deadlines; phase scheduling |
| `L4` vCPU | The MailCPU transition algebra; instructions are messages |
| `L5` Trajectory recorder | State is which packets and cells exist, where, and when |

**REQUIRED** Each layer MUST ship as a reusable module with a command-line entry
point.

## 11. Programme B: phases

| Phase | Build | Pass condition | Expected failure modes |
|---|---|---|---|
| `P1` | Profiler at `E0`, then `E1` | Profiles reproducible across runs | Time-of-day variance; rate limiting |
| `P2` | Single `DelayLoop` on an owned UDP echo host | Capacity matches `B x RTT`; `N` bytes held for `T` | Jitter breaks slotting; MTU; drops |
| `P3` | Regeneration and k-of-n erasure coding across parallel loops | Retention against loss `p` matches the analytic curve | Correlated loss invalidates the analytic model |
| `P4` | Coprime-loop RNS striping with redundant moduli | CRT readout survives erasures within the redundancy bound | Phase drift between loops |
| `P5` | `TTLCells` on an operator-authoritative DNS zone | Bit lifetime tracks TTL | Resolver TTL clamping; shared-cache pollution |
| `P6` | Fixed-function logic probes: TTL counter, NXDOMAIN predicate, ECMP hash | Each classified deterministic or non-deterministic | Load balancers and middleboxes rewrite or randomise |
| `P7` | Memory manager and placement compiler; Programme A corpus on the hierarchy | Final state equals the reference interpreter's result | Refresh deadline misses |
| `P8` | Multi-node machine; RTT matrix as address geometry | Run replayable from the recorded schedule alone | Route changes mid-run |
| `P9` | Reservoir mode: retain jitter as dynamics and run the same task both ways | Quantified comparison against deterministic mode | Reservoir does not beat the baseline |

## 12. Programme B: predictions and constraints

### 12.1 Predictions to attempt to break

- Measured capacity falls within an agreed tolerance of `B x RTT`.
- Retention follows the analytic erasure curve established at `P3`.
- Slot width must exceed jitter `sigma`, so the minimum viable slot is
  determined by `sigma`.
- Kill test: a loop retains 1 KB for 10 minutes at `E1`. Where this fails, the
  cause is identified before higher layers are built.

### 12.2 `E2` constraint

Public infrastructure used as bulk storage is the abuse pattern, as Pingfs
itself documents. `E2` runs are therefore restricted to ping-scale volume, and
in-path behaviour such as TTL handling and route selection is observation only.

### 12.3 Open decisions

- UDP echo on an operator-owned host before ICMP, which requires raw sockets and
  elevated privileges.
- One large packet per loop against many small slotted packets.
- Whether `H-VL` orbit jumps replace waiting, or only verify.
- Harness language, with a compiled reflector hot path.
