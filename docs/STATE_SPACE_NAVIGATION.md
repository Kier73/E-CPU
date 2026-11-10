# State-Space Capacity and Navigation

## Purpose

This abstract model now has an executable observation-to-Ground vertical slice in [OBSERVED_ORBIT_PIPELINE.md](OBSERVED_ORBIT_PIPELINE.md). It keeps the sample's ordinal orbit coordinate distinct from source logical time, binds the observation trace into the Ground context, and realizes direct or inverse reads through the receiver Hypervisor.

This note records the relationship between symbolic capacity, finite observation, and time-indexed navigation. It is a design model for the state-space architecture described in [COMPUTATIONAL_STATE_SPACE_ARCHITECTURE.md](COMPUTATIONAL_STATE_SPACE_ARCHITECTURE.md). The executable mechanisms are identified separately from development paths.

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

subject to its declared budget and invariants.

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

An important distinction: a finite symbolic language can define an uncountable domain and many useful families of elements, but it cannot provide a distinct finite description for every real number. Some individual reals are not computable or finitely nameable. The system's capacity is therefore expressed through domains, constraints, families, and operators—not by claiming that every member has an executable address.

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
- capability checks at each effectful host.

This is logical concurrency through interleaved state transitions. It does not prohibit using operating-system threads or parallel processors as an implementation detail. It means that correctness is defined by the transition relation and its observable traces, not by relying on thread timing.

## 6. E-CPU staging

The intended E-CPU composition sequence is:

1. **Ground description:** identify the domain, representations, state family, admitted transformations, observers, invariants, cost description, and evidence.
2. **Input interpretation:** bind the external input and context to a versioned Ground-bound description; preserve ambiguity when meaning is unresolved.
3. **Observation intent:** state the requested output, predicate, state, transition, comparison, or logical-time coordinate.
4. **Navigation:** select direct coordinate evaluation, inverse lookup, reusable indexing, formal analysis, or declared path traversal.
5. **Realization:** resolve an eligible E-CPU host and authenticated communication path; reconstruct local authority before any effectful transition.
6. **Verification and rendering:** verify the result and its observer receipts, retain the accepted state/lineage, and translate the observation for the requesting system.

The existing mutual-TLS path is operation-tested on loopback. Separate-host deployment and broader service federation are in development. The orbit scheduler and global semantic resolver are also in development.

## 7. Design criterion

A successful system should not attempt to store its entire potential state-space. It should keep:

- a closed, verified description of admissible states and transformations;
- a finite current state;
- a navigable transition relation;
- evidence for the finite path;
- explicit budgets and authority;
- a way to reconstruct or verify the state required for continuation.

The initial implementation experiment is [examples/state_space_navigation_experiment.py](../examples/state_space_navigation_experiment.py). It compares sequential recurrence, direct contextual observation, and inverse coordinate navigation over one admitted integer-progression Ground. The corresponding test exercises the actual E-CPU observer and navigator APIs.

That is the proposed bridge between symbolic capacity and computation in time.
