# Glossary

Registry of defined terms for this repository.

## Notation

| Notation | Meaning |
|---|---|
| `Z` | Integers, excluding Boolean values |
| `N` | Non-negative integers |
| `N+` | Positive integers |
| `B` | Finite byte strings, `B*` |
| `A` | Symbolic register-name set |
| `S(n)` | Set of strings of length `n` over the MailCPU instruction alphabet |
| `sigma` | One state of a stateful subsystem |
| `pi` | One projection from a stateful subsystem onto a simpler subsystem |
| `SHA256` | SHA-256 digest, a map `B* -> B^{32}` |

## Core state and transition

**admission**
: Acceptance of a generated, learned, or externally sourced component into the
  execution path. Admission is gated on a stated obligation, never on
  availability.

**capability**
: A pair `(resource, rights)` authorising a named subset of operations on a
  named resource. Authority is a function of capabilities held, never of
  identity, argument validity, or model output.

**check pointable**
: A state component whose complete value round-trips through `save_checkpoint`
  and `load_checkpoint` without loss. Checkpointability is a property of a
  component, not of a version.

**deterministic**
: A function `f` such that `f(x) = y` for fixed `x`, independent of host
  scheduling, wall-clock time, iteration order of unordered containers, hash
  seed, and address-space layout. Every MailCPU subsystem is deterministic or is
  declared non-deterministic at its boundary.

**evidence tier**
: One of `E0`, `E1`, `E2`, classifying the provenance of an execution result.
  See `docs/ARCHITECTURE.md` clause 6.

**fail closed**
: Refusal of an operation whose preconditions are not satisfied. Distinct from
  granting degraded, partial, or assumed authority.

**kernel state** `K`
: The product `K = (registers, pages, filesystem, mailboxes, processes,
  devices, routes, journal)` defined in `docs/ARCHITECTURE.md` clause 3.

**logical time** `t`
: A value in `N` incremented by exactly one per accepted event. Distinct from
  wall-clock time and from host scheduler time.

**receipt**
: A record `H_n = SHA256(H_{n-1} || c_n)` extending a hash chain over canonical
  event payloads, where `c_n` is the canonical encoding of the `n`-th event.

**reference interpreter**
: The transport-free backend implementing the transition algebra `T`. Its
  result defines correct behaviour for every other backend.

**trajectory**
: An indexed, receipt-verified sequence of captured communication frames
  constituting a replayable record of an execution.

**transition algebra** `T`
: The total function `T : (pc, R, Q, O) -> (pc', R', Q', O')` over machine
  state, defined in `docs/ARCHITECTURE.md` clause 3.

**transport**
: Any substrate implementing the `Transport` protocol. Substitutable below the
  transition boundary only, and MUST NOT alter feature semantics.

## Execution

**block**
: A state in which a scheduled task awaits a predicate over kernel state. A
  blocked task is not terminated and is not a failure.

**execution regime**
: A tag in `{MAILCPU, SENSE, LEAP, HDC, MDL}` identifying the semantics under
  which an image is interpreted. Only `MAILCPU` is admitted. All other members
  fail closed.

**image**
: A content-addressed, validated executable artifact carrying a `Program` and,
  at image version 2, a `MCPB` bytecode payload.

**tick**
: One unit of scheduler progress. A tick budget is an absolute ceiling on
  logical time, not a wall-clock timeout.

## Authority and control plane

**classifier question**
: A typed query over structured request state, answered with typed
  probabilistic values and a confidence scalar.

**deny** / **review** / **allow**
: The three decisions of the control plane. Model output proposes a decision;
  policy and capability state determine it.

**hypervisor**
: The component mediating between request state and effectful handlers. It
  records every decision in the hash-chained journal.

**right**
: An element of a capability's rights set authorising one operation class.

**subreaper**
: A process flagged to adopt orphaned descendants when no nearer live ancestor
  exists. Init is a subreaper by default.

## Storage and memory

**blob**
: Content-addressed bytes `SHA256(bytes)`.

**copy-on-write**
: Page-sharing in which a write to a shared page allocates a new page hash and
  leaves the original immutable.

**inode**
: A metadata record in the virtual filesystem, binding a name subtree to a byte
  sequence by blob reference.

**page**
: A fixed-size aligned memory unit. The default page size is 4096 bytes.

**resident budget**
: The constraint `sum_pid |M_pid| <= B` bounding VM-wide resident private pages.
  Distinct from per-process page quota.

## Substrates and reversible execution

**chemical difficulty** $\tau_{\text{chem}}$
: The normalized information-theoretic parsing cost $H(w) + \text{LZ}(w)$ used
  as a computational currency to scale memory allocation quotas and retention lifetimes.

**chronofold**
: A compact structural trajectory descriptor $\mathcal{F} = \langle s_0, \mathcal{T}, \mathcal{A}, D \rangle$
  capturing shift-periodic recurrence $t_{i+P} = t_i + S$, enabling constant-space Bennett
  replay and tape reversal.

**delay loop**
: A wide-area network storage substrate where state circulates as optical packets
  in physical communication media without host RAM retention.

**discrete geometric phase** $D$
: The state-preserving phase factor $D = (-i)^{n_{\text{active}}}$ accumulated by active
  micro-operations, cycling on modulo-4 period.

**holonomy consensus**
: A distributed agreement protocol coordinating multi-node state vectors via
  $\text{SU}(2)$ Wilczek-Zee unitary operators and Fréchet mean centroids.

**law certifier** ($\Omega_5$)
: The implemented six-rung algebraic ladder (`int`, `lcg`, `gf2`, `fgraph`, `kreg`, `tape`)
  transforming raw execution traces into certified closed-form recurrence relations.

**orbit leap**
: A closed-form state evaluation $x_t = \mathcal{G}(t)$ computing the system state at
  time coordinate $t$ in $\mathcal{O}(\log t)$ time without step-by-step intermediate simulation.

**policy gate witness isolation**
: An authority boundary where advisory neural routing proposals must achieve 100%
  exact agreement against withheld verification probes before execution dispatch.

**redundant residue number system (RRNS)**
: An algebraic representation encoding integer state across coprime moduli $(m_1, \dots, m_n)$,
  permitting exact Garner-free CRT state recovery from any $k \le n$ surviving residues.

## Stage boundaries

**stage boundary**
: A capability that has a defined place in the system's build order but is not
  yet connected to the active execution path. Stage boundaries are recorded as
  implementation obligations and MUST remain visible until built.

**refusal**
: An explicit, typed negative result. Distinct from an exception propagating
  out of an API, and distinct from a silent default.

