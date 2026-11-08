# State-Space Capacity and Navigation

## Purpose

This note records an architectural interpretation of symbolic capacity, finite observation, and time-indexed navigation. It is a design model, not a claim that the current MailCPU implementation already supports arbitrary symbolic spaces or concurrent remote orbit scheduling.

The governing principle is:

> Represent a space by its verified law; represent experience of that space by a finite trajectory.


The cross-subsystem view is indexed in [SYSTEM_MATHEMATICAL_MAP.md](SYSTEM_MATHEMATICAL_MAP.md). This document remains the focused specification for capacity versus finite trajectory.
## 1. Closed descriptions denote spaces

Let a finite description be

\[
D=(G,P,\mathcal{T},I),
\]

where:

- \(G\) is a grammar or symbolic representation language;
- \(P\) defines well-formed states;
- \(\mathcal{T}\) is the declared family of transition operators;
- \(I\) is the set of invariants and admissibility conditions.

Its denotation is the set

\[
\Omega_D=\{s\mid P(s)\land I(s)\}.
\]

A verified description establishes facts about this denotation and its declared transitions. It does **not** materialize every element of \(\Omega_D\). Nor does it establish every transformation imaginable outside the declared language. Its closure is relative to \(G\), \(P\), \(\mathcal{T}\), and the verification rules.

This distinction is important for E-CPU: the useful capacity is the set of states and transformations that the declared algebra can express and validate, not a stored list of every possible state.

## 2. Capacity is not a trace

Given an initial state \(s_0\), a navigation policy \(\pi\), and a finite budget \(B\), the observer produces a trace

\[
\tau_B=(s_0,s_1,\ldots,s_k),
\qquad
s_{j+1}=T_{a_j}(s_j),
\quad
a_j\in\mathcal{T},
\]

subject to the budget and invariants.

Three objects should remain distinct:

| Object | Meaning |
|---|---|
| \(\Omega_D\) | Symbolically described capacity |
| \(\tau_B\) | The finite path actually traversed |
| \(C_B\) | The part of the path retained, verified, and actionable within budget |

\(C_B\) is the observer's coherence envelope. It depends on available time, memory, compute, and the cost of maintaining and checking state. Increasing the budget can enlarge the useful trace without changing the underlying denoted space.

A digest, index, or compressed description can make a trace easier to verify or revisit. It is not automatically a reconstruction of omitted state. Any navigation shortcut must carry a certificate showing why it preserves the required semantics.

## 3. Decimal-space example

The interval \([0,1]\) denotes an uncountable set of real values. A finite description of the interval can state its boundaries and support operations over it without enumerating its elements.

A finite decimal prefix such as '0.314' is not one exact real number; it denotes a region of possible completions, here \([0.314,0.315)\) under the usual nonnegative decimal convention. A query can refine that region by extending the prefix.

Run-length structure illustrates compact representation. For an integer \(N\geq 0\),

\[
0.\underbrace{00\ldots0}_{N\text{ zeros}}1=10^{-(N+1)}.
\]

The description “\(N\) zeros, then a one” has size \(O(\log N)\) when \(N\) is encoded as an integer, while writing all decimal digits has size \(O(N)\). The compact form describes the value exactly without writing the expanded string.

There is a boundary worth preserving: a finite symbolic language can define an uncountable domain and many useful families of elements, but it cannot provide a distinct finite description for every real number. Some individual reals are not computable or finitely nameable. The system's capacity is therefore expressed through domains, constraints, families, and operators—not by claiming that every member has an executable address.

## 4. Time as navigation budget

Logical time is the ordering of accepted transitions. A worker advances when a transition is admitted and executed; a navigation policy chooses which admissible transition to attempt next.

A budget can bound, separately:

- transition count;
- instruction or scheduler ticks;
- memory and message bytes;
- wall-clock deadline;
- resource-specific costs.

These are operational budgets, not interchangeable units of physical energy. The phrase “time as energy” is useful as an architectural intuition: progress consumes a finite budget, and the system uses that budget to reach, inspect, and preserve states.

## 5. Communication paths and orbit-style concurrency

Model communication as a directed graph

\[
G=(V,E),
\]

with local worker states \(S_v\) and channel queues \(Q_e\). The global state is

\[
S_G=\left(\prod_{v\in V}S_v\right)\times
    \left(\prod_{e\in E}Q_e\right).
\]

Each job follows a trajectory through the graph. Informally, these trajectories can be pictured as jobs orbiting communication paths. At each logical step, a scheduler selects an enabled local transition or message-delivery transition. Independent trajectories can advance without requiring the entire graph to move in lockstep.

For deterministic execution, the scheduler must define a stable ordering rule. For useful service under load, the design must additionally specify:

- fairness or starvation bounds;
- per-job and per-worker budgets;
- queue capacity and backpressure;
- ordering and causality for messages;
- cancellation and failure transitions;
- capability checks at every effect boundary.

This is logical concurrency through interleaved state transitions. It does not prohibit using operating-system threads or parallel processors as an implementation detail. It means that correctness is defined by the transition relation and its observable traces, not by relying on thread timing.

## 6. E-CPU staging

The prudent implementation sequence is:

1. **Authenticated transit:** the mutual-TLS adapter now wraps the existing framed MailCPU transport, validates the server hostname and the client's expected DNS SAN, and requires TLS 1.2 or newer. A loopback integration test runs the bounded compute operation across authenticated request and result channels. A deployed separate-host service, certificate lifecycle, and WAN validation remain future work.
2. **Verified job capsule:** describe a job by its finite program, input state, operation identity, allowed effects, and resource budgets.
3. **Trajectory evidence:** record accepted transitions, state digests, event identities, and replay receipts. State clearly which information is a digest/index and which is sufficient to reconstruct a state.
4. **Navigation policy:** select the next job or transition using explicit fairness, cost, and resource rules.
5. **Orbit scheduler:** allow independent jobs to make progress along their own message paths while preserving a deterministic global transition order where deterministic replay is required.
6. **Validation:** test equivalence, fairness, backpressure, cancellation, checkpoint/restore, duplicate replay, and authenticated multi-host operation.

The current transit worker implements only the bounded compute capsule and one-request service boundary. The mutual-TLS adapter is implemented and operation-tested on loopback; deployment across separate hosts remains unproven. The orbit scheduler remains a future layer.

## 7. Design criterion

A successful system should not attempt to store its entire potential state-space. It should keep:

- a closed, verified description of admissible states and transformations;
- a finite current state;
- a navigable transition relation;
- bounded path evidence;
- explicit budgets and authority;
- a way to reconstruct or verify the state required for continuation.

That is the proposed bridge between symbolic capacity and computation in time.
