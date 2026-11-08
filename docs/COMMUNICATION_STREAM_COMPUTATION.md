# Communication Streams as Computational Substrate

## Purpose

This document describes a direction for E-CPU: treat communication infrastructure as a navigable computational substrate in which ports, services, queues, translators, memory providers, and execution hosts can participate as typed operational loci.

The underlying abstraction is **host = observer**. Any identifiable locus that observes information or changes information through observation and interaction is an observer-host candidate. An observer may be a receiver, sensor, queue, port, timing probe, memory provider, interpreter, or composite service; it need not be a conventional machine or general-purpose executor. Observation itself may be read-only, or it may change the observer's state, the observed state, or both.

The claim is deliberately narrower than “the Internet is already a computer.” A passive link only carries information. An observer-host performs a declared observation or interaction. For that locus to participate in an admitted computational path, its identity, observation/transition contract, applicable authority, resource bounds, and observable result must be established. A path becomes computational by composing such host contracts; it does not become trusted or executable merely by being connected.

## 1. The stream carries a state description

A message stream is not merely an opaque byte pipe. It can carry a continuation descriptor:

\[
m = (id, schema, payload, context, t, prerequisites, authority, budget)
\]

where:

- id is the stable semantic operation identity, distinct from a transport frame sequence;
- schema identifies the representation and its decoding rules;
- payload carries the value or a reference to content-addressed state;
- context binds the exact interpretation, Ground, revision, and relevant environment;
- t is the declared logical-time coordinate;
- prerequisites express causal dependencies;
- authority declares the receiver-side capability requirements;
- budget bounds bytes, work, time, hops, and other applicable resources.

Transport sequence, physical arrival time, and semantic operation identity are separate coordinates. A retry may use a new transport sequence while preserving the same semantic operation. A receiver must reject a conflicting payload that reuses an identity already committed to different content.

### Control-plane intent and bulk payload are separate projections

A large typed input must not be embedded wholesale into the Hypervisor's semantic intent representation. The Virtual Layer supplies an explicit intent projection alongside the full payload. The projection is a bounded summary of the workload goal, System/Ground coordinate, operator contract, resource budget, logical time, input byte extent and SHA-256 input/workload identities. The complete request payload remains present in the event and is included in its event fingerprint. The projection is restricted to the receiver-verified Virtual Layer operator contract and a 4 KiB canonical JSON bound. `HypervisorRequest.decision_state()` uses the compact projection plus the digest and byte length of the full payload for classifier/intent interpretation, while `state()` retains the complete request for replay, journaling and receiver execution. Virtual-cost accounting still charges the complete request's serialized semantic bits and chemical complexity, but evaluates the structural token count over the compact projection; this separates interpretation budget from data-materialization cost without treating the payload as free.

The projection is not accepted as a sender assertion. Before local capabilities are derived or a handler is prepared, the receiving Virtual Layer reconstructs the workload, resolves the local operator contract, remeasures the complete input, recomputes the projection, and requires exact equality. This is an interpretation-cost optimization, not a trust shortcut: a different bulk input changes the workload/input digest and event identity, and a forged intent summary is rejected. Requests without an explicit projection retain the original full-payload classification behavior.

## 2. Hosts interpret; links carry

Let a path be:

\[
P = H_0 \xrightarrow{e_1} H_1 \xrightarrow{e_2} \cdots
\xrightarrow{e_n} H_n
\]

Each e_i is a communication substrate edge. Each H_i is a logical host with its own identity, operational state, transition relation, capabilities, and lineage:

\[
H_i=(I_i,C_i,S_i,T_i,K_i,L_i).
\]

At a receiver, a message can pass through:

\[
\text{frame}
\rightarrow \text{decode}
\rightarrow \text{interpret}
\rightarrow \text{validate}
\rightarrow \text{authorize}
\rightarrow \text{transition}
\rightarrow \text{receipt / continuation}.
\]

The network does not execute the semantic transition merely by moving bytes. A host/observer is the locus that observes, interprets, or interacts with the information. Computation occurs when that observation is composed with a declared transition that produces an admitted effect or result. A port is not automatically a host merely because it has an address; the port or service becomes an observer-host when it actually receives, samples, inspects, measures, admits, acknowledges, transforms, or emits information under a defined contract. Such a host can be observational without having a general-purpose execution engine.

This creates a composable alternative to one machine containing every execution primitive. One host may decode a representation, another may perform a bounded transformation, another may supply memory, another may measure a link, and another may verify the result. The path is useful only when adjacent schemas, identities, causal relations, authority, and resource contracts agree. Observation-only hosts contribute their declared observation; they do not inherit the execution or authority of neighbouring hosts.

## 3. Meaningful interpretation is not free computation

The proposal is to navigate toward an interpretation that already exists at a receiver, instead of transporting every request to a single monolithic execution point. This can avoid unnecessary work or state movement, but it does not eliminate physical cost.

A path cost should retain separate dimensions:

\[
C(P)=(L, B, W, V, Q, R)
\]

where L is measured latency, B bytes moved, W execution work, V verification work, Q queue/retry pressure, and R recovery risk. Units must remain explicit. A route cannot honestly claim to compute “at network speed” without measuring receiver service time, transport latency, queueing, verification, and recovery overhead on the actual substrate.

The useful optimization target is not maximum raw clock rate. It is the least costly admissible path that preserves the required observation and authority contract.

## 4. Symbolic coordinates and the finite observer

A finite representation can denote a very large or infinite state family without materializing every member. For example, the decimal position of a digit can be represented symbolically:

\[
d=(\text{radix}=10,\ \text{leading\_zeros}=10^{12},\
\text{digit}=1).
\]

This descriptor denotes a decimal value whose explicit expansion would contain a trillion leading fractional zeroes before the 1. The descriptor is finite; the expanded string is not stored. An observer-host can ask for a bounded window, compare coordinates, or apply an algebraic transformation without enumerating the entire prefix. In this document, “observer” always denotes a possible logical host, not only an external person contemplating a representation.

The distinction is essential:

- Description capacity is the set denoted by a finite rule.
- Materialized state is the finite portion actually generated or stored.
- Navigation is an operation on symbolic coordinates or transitions.
- Observation is a bounded query whose result and cost must be explicit.

The descriptor does not physically contain infinite information. It contains a finite rule that denotes an unbounded family. If a request asks to materialize n digits, the work and storage still grow with n. If an operation supports a verified jump or symbolic coordinate transform, it may avoid linear enumeration; the cost then depends on the arithmetic representation, operand size, algorithm, and proof obligations.

A finite observer-host cannot traverse an infinite space linearly. It can navigate it by symbolic position, composition, indexing, or verified transformations. This only works when the representation defines those operations and a verifier can check their results. The observer's available operations, information horizon, resource budget, and evidence are part of its host contract; finite observation does not imply exhaustive knowledge of the represented space.

## 5. Describe → resolve → realize

The slogan “Describe what you want, and it exists as a result” is a design aspiration with an operational qualification.

A description becomes actionable when the system can:

1. parse it into a typed goal or representation;
2. resolve the exact Ground, context, and target observation;
3. find a host with the required transition and available resources;
4. obtain receiver-side authority;
5. perform a bounded transition;
6. verify the resulting observation;
7. commit or publish the result with stable identity and lineage.

A description alone does not allocate unlimited memory, grant capabilities, or prove that a solution exists. It creates an addressable request. Realization is a separately admitted and measured transition.

## 6. How this composes with E-CPU

The current repository already provides several necessary pieces:

- ComputationalFabricDirectory carries peer-owned host and directed-link descriptions under direct mutual-TLS authentication, revisions, and receiver-local leases.
- ComputationalFabricResolver selects a bounded network path but does not grant execution authority.
- ComputationalFabricForwardingServer revalidates the local hop and dispatches through the receiver's Hypervisor and local computational resolver.
- M1 provides content-addressed bytes; M3 provides quorum-anchored current session state; M4 provides a context-bound pure transition boundary.
- M5-M7 bind VGI interpretation, bounded instruction quanta, and portable host transfer to those persistent-state contracts.
- E-GPU provides a bounded local example of a composite host whose method is selected through an internal operational graph.

The first concrete composition now exists in `mailcpu/computational_fabric_vgi.py` as `VGIFabricSessionOperator`. The integrated test carries an M7 transfer bundle as a typed Virtual Layer workload across an authenticated A→B→C path. B performs only its local NETWORK forwarding transition; C re-admits the bundle into its own M1 backing, verifies the original M3 proof and exact VGI descriptor, then advances a bounded M4 quantum under the same session identity. Its receipt preserves Ground, task, Program, implementation, interpretation, artifact, state schema, backend, logical time, predecessor checkpoint, revision and lineage digest. Exact retries are checked at the M3/M4 session layer and at C's terminal Hypervisor CPU execution ledger. The complete specification and limits are in [FABRIC_VGI_SESSION_COMPOSITION.md](FABRIC_VGI_SESSION_COMPOSITION.md).

## 7. Proof obligations

A stream-based computational path must establish:

- exact representation and decoder identity;
- stable logical host identity separately from placement and peer identity;
- authenticated adjacent transport and receiver-local lease validity;
- local capability checks at every effectful host;
- bounded payload, queue, execution, and verification work;
- semantic deduplication independent of transport retries;
- explicit state ownership and revision/lineage continuity;
- observable equivalence or a declared result contract;
- recovery behavior at each publication and acknowledgement cut;
- measured path cost, including communication and interpretation overhead.

Physical ports, servers, or network operators do not become mutually trusted merely because they communicate. Direct trust roots, authority membership, and failure-domain claims require explicit evidence. The model is compatible with heterogeneous hardware, but it does not replace CPU/GPU execution semantics where those are required.

## 8. Development rule

Prefer a receiver that can interpret a small typed request using existing local state over shipping a complete machine image. Move state only when the receiving host cannot already resolve the required content. Preserve semantic identity as a request crosses new transport frames or hosts. Use symbolic coordinates to avoid unnecessary materialization, but measure the actual arithmetic, memory, communication, and verification cost.

The target is a fluid computational fabric: not a machine that has no hardware, but a system in which hardware endpoints become interpreters and state-transition hosts, and communication paths compose those hosts into larger computational structures.
