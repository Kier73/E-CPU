# E-CPU Mathematical System Map

## Purpose and reading discipline

This document maps the mathematics already present across E-CPU / MailCPU. Read it alongside [COMPUTATIONAL_STATE_SPACE_ARCHITECTURE.md](COMPUTATIONAL_STATE_SPACE_ARCHITECTURE.md), which gives the governing order for describing, interpreting, observing, navigating, realizing, and verifying computation. This map inventories mathematical structures and their implementation relationships; subsystem specifications remain authoritative for their individual contracts. Different state owners, graphs, clocks, and solvers retain their own identities and semantics.

Use four evidence labels when reading the map:

- **Executable contract** — defined in code and bounded by tests.
- **Integrated mechanism** — components joined by an executable interface, with explicit ownership and proof obligations.
- **Architectural model** — a formal description that guides implementation but is not itself evidence of universal capability.
- **Research hypothesis** — a possible extension that needs a falsifiable experiment.

A formula here inherits the evidence status of its referenced implementation. Mathematical notation is not, by itself, proof that a corresponding mechanism has been implemented.

## 1. The system is a composition of transition systems

A useful top-level representation is a family of labelled transition systems:

\[
\mathfrak{E} =
\left(
\{\mathcal{T}_i\}_{i\in\mathcal{I}},
\{\mathcal{C}_{ij}\}_{(i,j)\in\mathcal{L}}
\right)
\]

where each subsystem is:

\[
\mathcal{T}_i=(S_i,\Lambda_i,\delta_i,I_i,O_i)
\]

- \(S_i\) is the state owned by subsystem \(i\).
- \(\Lambda_i\) is its typed action/event alphabet.
- \(\delta_i\) is its transition relation or transition function.
- \(I_i\) is its set of invariants and admission conditions.
- \(O_i\) is its declared observation/result projection.
- \(\mathcal{C}_{ij}\) is a contract relating two subsystem boundaries: identity, schema, authority, causality, persistence, or observation.

The product \(\prod_i S_i\) is useful as an analyst's conceptual state vector, but it is not a promise that E-CPU captures or commits a globally atomic state. State is owned by separate schedulers, peers, journals, channels, and services. Cross-component consistency is established through contracts, receipts, checkpoints, and explicit causal dependencies.

The normative architecture gives each exposed feature a seven-part contract:

\[
\mathcal{F}=(S,A,Q,\delta,R,P,\Phi)
\]

Here \(S\) is state, \(A\) authority, \(Q\) request, \(\delta\) transition, \(R\) reply, \(P\) persistence, and \(\Phi\) failure behavior. A feature with an undefined contract element is not ready to be exposed.

### The local machine transition

The MailCPU kernel state is modelled as a product:

\[
K=(registers,pages,filesystem,mailboxes,processes,devices,routes,journal)
\]

and a kernel request acts as:

\[
\delta_K:(K,request)\rightarrow(K',reply,emitted\_messages)
\]

The instruction transition is separately bounded:

\[
T:(pc,R,Q,O)\rightarrow(pc',R',Q',O')
\]

The reference interpreter defines instruction semantics; scheduler, queue-backed, and communication-backed implementations are expected to preserve the declared observations. The instruction algebra is total on validated programs and reports budget exhaustion as a step-limit outcome rather than silently interpreting exhaustion as a successful halt.

This is the core formal pattern repeated throughout the repository: state has an owner, an action has a typed domain, and a transition is valid only when its invariants and observation contract hold.

## 2. Host, substrate, and operational path

A logical host is an identifiable observer-locus. **Host and observer are the same underlying abstraction**: any locus that can observe information or change information through observation and interaction is a host candidate. The observer need not be human, centralized, persistent, or implemented as a conventional machine.

\[
H=(I,C,S,T,K,L)
\]

- \(I\): stable logical identity.
- \(C\): communication interfaces and adjacency.
- \(S\): operational state; it may be empty for a stateless observer or transform.
- \(T\): its defined observation and/or information-transition relation.
- \(K\): capabilities available and permitted at that locus.
- \(L\): operational lineage, revision, provenance, and recovery identity.

An observation can be modelled as:

\[
\mathsf{O}_H:(X,S_H)\rightarrow(Y,S'_H,X',E)
\]

where X is the information made available to the observer, Y is the bounded observation, S'_H is the observer's resulting state, X' is the observed information after any interaction, and E is the evidence or receipt. A passive read may leave both states unchanged; an active observation may update the observer, the observed information, or both. The contract determines which behavior is permitted and observable.

A substrate carries information; a host/observer performs a defined observation or interaction; a path relates substrate edges and host transitions. A passive link that only carries signals is normally an edge, not a host. A link, port, or path segment that samples, measures, decodes, admits, acknowledges, filters, or otherwise interacts with information is an observer-host for that operation. A server process may realize a host, but process identity and logical host identity are not interchangeable.

For a path \(\pi=(h_0,\ldots,h_n)\), its semantic operation is a composition of admitted observations and transitions. An observation-only host can contribute a measured or verified result without being treated as an executor; where an observation changes state, that interaction is an explicit transition. The computation path is:

\[
F_\pi = T_{h_n}\circ T_{h_{n-1}}\circ\cdots\circ T_{h_0}
\]

This composition is meaningful only where adjacent request/reply schemas, semantic identities, causal dependencies, authority requirements, and observation contracts match. Observation is therefore not outside the computational fabric: it is a primitive host operation that can supply evidence, alter state, or participate in a larger transition path. Physical placement may change while logical host identity and required lineage remain stable.

The implementation has several related but distinct operational graphs. They must not be flattened into one universal graph:

| Structure | Nodes and edges mean | Main use |
|---|---|---|
| Peer connectivity graph \(G_P\) | Authenticated or observed peers and directed network links | Discover candidates and plan A→B→C forwarding routes |
| Host-operation graph \(G_H\) | Logical operational loci and capability-labelled transitions | Resolve an E-GPU or other composite host method path |
| Computation DAG \(G_D\) | Operation identities and dependency edges | Determine which jobs are ready and which results must precede others |
| Evidence graph \(G_E\) | Evidence identities, derivations, and provenance links | Resolve and inspect why a result or representation is admissible |
| State-transition system \(G_S\) | States and permitted transitions, often represented implicitly | Navigate a process, machine, law, or workload state space |

These structures can be composed by identity and contract, but an edge in one graph does not automatically become an edge in another. In particular, a network route is not a proof of semantic validity, a capability grant, or a causal dependency.

## 3. Computational identity and address

A declared computational domain can be represented as:

\[
\mathcal{C}=(G,P,\Sigma,\Delta,\mathcal{R})
\]

where \(G\) is its Computational Ground and observation rules, \(P\) is the program or transition description, \(\Sigma\) is the state space, \(\Delta\) is the permitted transition family, and \(\mathcal{R}\) resolves an admitted request to a suitable state and execution capability.

The semantic address used by the computational-addressing model is:

\[
A=(G_s,G_c,P,\theta,x,\tau,O)
\]

- \(G_s\): admitted System Ground and causal frontier.
- \(G_c\): the computational Ground that gives the operation meaning.
- \(P\): task/program identity and its pinned implementation fingerprint where required.
- \(\theta\): intention and operator contract.
- \(x\): input, state coordinate, structural-memory reference, or checkpoint.
- \(\tau\): logical execution coordinate and causal position.
- \(O\): requested result/observation projection.

A Virtual Layer workload already carries most of this address through system identity, Virtual Ground, intention, ordered operator references, input, budget, logical time, and eligible placement constraints. New fields should be added only when they introduce a distinct enforced obligation; parallel address protocols create identity drift.

The same address supports four distinct operations:

\[
Locate(A)\rightarrow(state/effect,receipt)
\]

\[
Restore(A,B)\rightarrow state
\]

\[
Continue(A,state,input)\rightarrow state'
\]

\[
Transform(G,P,state,\theta)\rightarrow(state',observation)
\]

Locate retrieves an already committed state/effect; Restore reconstructs an admitted checkpoint; Continue admits a new event from known state; Transform performs a declared operator. These modes share identity but must not be conflated. A committed event should be located and replayed, not re-executed merely to rediscover its result.

**Current build status:** Transit dispatch resolves exact operation/resource pairs against receiver-local registries. The computational fabric now combines authenticated direct-peer discovery, multi-hop route planning, and restart-aware lease reacquisition. The broader semantic-address resolver continues to grow across host, state, checkpoint, implementation, and evidence catalogues.

## 4. State-space capacity and navigation

A finite description can denote a much larger space than it explicitly stores:

\[
D=(G,P,\mathcal{T},I)
\]

\[
\Omega_D=\{s\mid P(s)\land I(s)\}
\]

Here \(G\) is the representation grammar, \(P\) defines well-formed states, \(\mathcal{T}\) defines permitted transition operators, and \(I\) gives invariants/admissibility conditions. A description is useful when its verified rules can generate, locate, restore, or validate states of interest without materializing every member of \(\Omega_D\).

The phrase **finite observer** refers to a finite observer-host: a locus with bounded observation and interaction resources. It is not restricted to a human or an external analyst. A host's observation horizon, sampling rules, state effects, and evidence contract bound what it can establish; an observer does not gain exhaustive knowledge merely because a symbolic description denotes an unbounded state family.

A finite navigation is a bounded trajectory:

\[
s_{k+1}=\delta_{a_k}(s_k), \qquad
\pi=(a_0,\ldots,a_{n-1}), \qquad n\leq B
\]

where \(B\) is the explicit transition/search budget. Capacity is the set of states expressible under the declared description; a trajectory is one finite realization under one policy and budget. Neither is equivalent to a complete execution trace.

### The implemented navigation family

| Method | Mathematical object | Current operation |
|---|---|---|
| Contextual navigation | Finite, guarded transition graph over a typed process context | Derives concrete paths/witnesses under explicit context and search budgets |
| Integer-affine abstract interpretation | Interval abstractions over affine integer expressions and a finite control graph | Conservative may-reachability, proved-unreachable, or inconclusive; interval correlation loss can produce false positives |
| Strong bisimulation | Two finite labelled transition systems | Checks label-preserving behavioural equivalence for the supplied finite representations |
| Causal dependency analysis | DAG plus vector-clock observations | Determines whether declared prerequisites are observed and ordered; it does not invent a global wall clock |
| Peer/host path resolution | Directed graphs with local route and capability contracts | A route/witness through the relevant graph; it does not itself authorize execution |
| Law/orbit navigation | Admitted arithmetic, affine-modular, GF(2), or finite-orbit descriptions | Provides guarded state lookup and orbit jumps for the registered generator families |

Abstract interpretation uses three-valued constraint dispositions: entailed, refuted, and unknown. Unknown is preserved as possible; it is not silently treated as false. A may-reachability result is not a concrete witness. A concrete path still requires exact bounded navigation and replay against trusted context.

Strong bisimulation compares finite labelled systems under the declared labels and transition relations. The causal DAG uses vector clocks to distinguish before/after from concurrency. These methods answer different questions and produce different evidence objects.

The coordinator composes these gates rather than replacing them: compile supported abstract projections; check declared causal prerequisites; run any explicitly required representation-equivalence gate; derive an exact concrete path and readiness result; then issue a proposal for hypervisor admission. A proposal is not an execution.


### Contextual orbit addressing and symbolic Virtual Ground projection

The executable observer/orbit composition is documented in [OBSERVER_ORBIT_CONTRACT.md](OBSERVER_ORBIT_CONTRACT.md) and implemented by mailcpu.observer_orbit.

A contextual orbit address binds an exact SystemIdentity, base VirtualGroundRef, Computational Ground representation, typed scheduler coordinate, and revision-pinned VirtualStructuralMemoryRef. The memory coordinate is relative to the base Ground:

\[
t = \tau_{\mathrm{target}} - G_s.coordinate.
\]

The Structural Memory context pins the system incarnation, base origin/state/input frontier, Computational Ground, scheduler identifier, and declared extensions. The locator revalidates the admitted spec/certificate and evaluates its guarded generator directly at \(t\), producing a symbolic Virtual Ground projection plus Structural Memory and observer receipts. The projection is a coordinate/value view anchored to the base Ground, not a complete OS snapshot or SystemSeed.

For the admitted E0 families, integer and finite-graph lookup are direct \(O(1)\) coordinate operations; LCG and GF(2) recurrence jumps are logarithmic in the coordinate for fixed recurrence parameters/order. The direct locator reports zero expanded intermediate states. A failed identity, context, admission, or prefix-horizon check refuses: it does not silently switch to contextual BFS or SystemSeed replay. Those mechanisms remain available for their distinct problem classes.

The target-directed locate_value path likewise uses only constant-time arithmetic inversion or full-period 2-adic LCG bit lifting; unsupported inverses refuse rather than selecting BSGS or linear finite-graph scans. The observer-orbit contract also records the limitation that the current VirtualGroundRef v1 coordinate does not carry its own scheduler identity.

Observer composition aggregates exactly the declared member receipts while preserving each projection independently. It is explicitly not a consensus algorithm. This gives the runtime a common observer identity/evidence contract without forcing every observer to become a state owner, executor, or authority.


## 5. Authority, commit, and semantic correctness

Authority belongs to the receiver that owns the effect. The sender may describe a requested operation and its required rights, but it cannot grant itself permission.

A simplified local decision is:

\[
Permit_h(q)=Policy_h(q,Capabilities_h,LiveContext_h)
\]

A route resolver may propose a host/path; the receiving Hypervisor reconstructs capabilities from its local kernel state and independently applies policy. Navigation admission is a bounded grant, not a mutation. The execution adapter rechecks live context, grant scope/expiry, capabilities, start-state identity, and readiness before it asks the state owner to commit.

For a state-owning backend, the critical commit shape is compare-and-swap:

\[
CAS(digest(s),s') =
\begin{cases}
commit(s') & \text{if the live state still matches }s\\
refuse & \text{otherwise}
\end{cases}
\]

The scheduler lock or backend transaction defines the atomicity boundary. A durable receipt is published with the committed state so an exact retry can find the prior effect.

### Representation and semantic verification

For a translation contract \(C\), the observation obligation is:

\[
Observe_C(Source(x))=Observe_C(Target(x))
\]

The projection, schema, input, context, preconditions, resource ceilings, authority, and replay model must all be bound by the contract. In the current paired checker, equality is canonical JSON equality for the supplied case. A successful pair is evidence for that case; it is not a proof over all possible inputs.

Independent oracles strengthen particular operations where they are available. Other checks establish state-digest integrity or receipt consistency only. Do not call a digest an independent semantic oracle.

A receipt digest can bind the operation identity, result projection, implementation identity, and evidence references. A hash provides integrity against alteration of the bytes under the assumed hash function; it does not, by itself, authenticate a remote host, attest hardware, or prove the computation's semantics.

## 6. Identity, causality, and time are separate coordinates

E-CPU has multiple kinds of identity and ordering:

| Coordinate | Scope | What it establishes |
|---|---|---|
| Semantic execution identity | Operation/workload and origin context | Which logical effect is being requested or replayed |
| Transport sequence | One reliable channel direction | Which frame is delivered, acknowledged, or retransmitted |
| Logical workload time | Declared workload domain | A task-level temporal coordinate |
| Scheduler tick | One named deterministic scheduler | Virtual deadline and work-budget progression |
| Lamport/vector clock | Actor/event causality | Causal order or concurrency |
| Local monotonic clock | Actor and boot/restore segment | Elapsed duration measured by that actor |
| Wall/calendar clock | Local clock sample | Calendar correlation, not causal order |
| SystemEpoch coordinates | Their owning model/scheduler | Event, chronon-phase, and chemical/structural coordinates |

For vector clocks \(u,v\), the causal relation \(u\prec v\) holds when every component of \(u\) is less than or equal to the corresponding component of \(v\), with at least one strict inequality. If neither \(u\prec v\) nor \(v\prec u\), the events are concurrent under the recorded vector-clock model.

A channel sequence is not a semantic operation identity. The same semantic event can be replayed in its existing pending frame or, after a transport ACK, carried in a later transport frame. Conversely, two different semantic events can use adjacent frames on one channel.

A local monotonic timestamp is meaningful only within its actor and monotonic segment. Wall time is not a causal order. Scheduler ticks are scoped to the scheduler ID. The temporal layer deliberately defines no universal conversion among physical duration, logical ticks, event coordinates, chronon phase, and chemical difficulty.

## 7. Cost, path choice, and the meaning of energy

A candidate route may have a vector of declared costs:

\[
\mathbf{C}(\pi)=(L(\pi),E(\pi),B(\pi),R(\pi))
\]

where the dimensions may encode latency, energy, byte movement, and recovery/verification risk according to each metric's declared unit and aggregation rule.

One route Pareto-dominates another when it is no worse on every comparable dimension and strictly better on at least one. A policy may then select from the non-dominated candidates, apply explicit ceilings, or define a lexicographic order. Collapsing incomparable dimensions into a weighted scalar is a policy decision, not a mathematical necessity.

A route is not admissible merely because it is cheap. Ground compatibility, local authority, causal prerequisites, resource budgets, and the requested verification tier are prior constraints.

Current route selection uses deterministic graph/path procedures, including bounded and minimum-hop traversal, with declared metric dimensions available to policy. Metric values retain their declared units and interpretation.

A potential function \(V(s)\) can be introduced as an additional navigation observable when its domain, observables, monotonicity conditions, and failure cases are explicit. It can help rank admissible states, but its score remains evidence about the chosen objective rather than a substitute for semantic verification.

## 8. Structural memory and generative state

Structural Memory stores a verified description of a state family rather than every state instance. A revision can be viewed as:

\[
M_r=(id,r,g,\theta,c,\kappa,p)
\]

where \(id\) is stable memory identity, \(r\) is immutable revision, \(g\) is an admitted generator family, \(\theta\) is its canonical parameter set, \(c\) is exact context identity, \(\kappa\) is its verification certificate, and \(p\) is the parent revision digest.

A read is accepted only when the requested coordinate, revision, context, and certificate correspond. The current typed generator registry covers deterministic integer progressions, affine modular recurrences, GF(2) recurrences, and finite-graph orbits. Each family is reconstructed through its validated law adapter.

This gives the system a compact way to represent large state families while keeping generation, context, revision, and verification explicit. It does not imply that every conceivable state is representable or that arbitrary transformations can be inferred from a certificate.

## 9. Reliable communication and recovery mathematics

For an in-transit path, the durable logical state is usefully separated as:

\[
X=(C,Q,L,E)
\]

- \(C\): checkpoints and admitted structural state.
- \(Q\): reliable-channel queues, retry frames, receive cursors, and acknowledgements.
- \(L\): execution/commit/replay ledgers.
- \(E\): receipts, event journal, and verification evidence.

Bytes in one TCP socket are not durable state. A process restart creates a new transport; recovery restores the logical channel and execution state, then rebinds a fresh authenticated stream.

The fabric discovery service follows the same rule for directory observations: its bootstrap snapshot retains configured direct-peer endpoints and refresh policy, while the separately checkpointed directory retains revision/digest high-water state. Restore reconstructs the service without old client streams or lease deadlines. The local runtime owner republishes its own current portable snapshot, then direct mutual-TLS refresh reacquires each remote lease. The active route view emerges again from new observations, not from serialized connections.

Keep semantic and transport identity separate. If an effect is committed under semantic identity \(e\), an exact retry must locate its committed receipt rather than invoke the effect handler again. The effective guarantee is bounded by the durability and scope of the effect ledger. Arbitrary external side effects need idempotency or an effect journal at the actual side-effect owner; the forwarding tests use deterministic pure computation and do not prove global exactly-once behavior.

### Per-peer checkpoint lineage

A recovery manifest binds a peer incarnation and owner term to a generation, predecessor root, endpoint/backend checkpoint digests, membership identity, and named capture cut. For a fixed membership of \(N\) authorities, a strict-majority quorum \(q\) satisfies:

\[
2q>N
\]

The intersection of any two such quorums is non-empty. Combined with one-vote-per-slot rules and durable decisions, this prevents conflicting roots from both being committed in the same fixed membership/term/generation slot.

Restore requires the supplied image to match the quorum-supported high-water root; an internally valid but stale checkpoint is refused. Each peer advances its own lineage and channel coordinates. Cross-peer continuity is composed by sequencing compatible peer generations and reconciling the same semantic operation identity, while quorum safety relies on the configured membership and owner-term rules.

## 10. Accelerator and vCPU interpretation

The E-GPU is implemented as a logical operational graph with dispatch, SIMT, reduction, workgroup/shared-memory, and verification loci. Its Python backend is a bounded reference evaluator, and the tree-reduction method records its reduction structure. The graph describes operational composition and can serve as the contract surface for accelerator backends.

The native vCPU context backend projects the scheduler's actual program counter and integer registers at a suspended-task safepoint. It applies bounded, compare-and-swap context edits and records receipts. The scheduler and existing interpreter remain the current instruction-retirement authorities; the context backend supplies a state-navigation and editing surface around them.

The ELF subsystem parses and stages load, relocation, and startup information for its current declared image formats. These facilities form part of the vCPU and accelerator integration path.

## 11. Information-theoretic substrates: useful models, not automatic capabilities

The substrate survey studies bandwidth-delay product, channel capacity, timing channels, DNS TTL, transport dynamics, and routing state as possible sources of storage, observation, or transition. These ideas can guide experiments, but a physical or protocol phenomenon becomes an E-CPU capability only after the system defines:

1. the state variable and the actor that can observe or control it;
2. the encode/decode map and its finite alphabet;
3. noise, loss, contention, expiry, and adversarial conditions;
4. a transition contract and resource bound;
5. durable identity, verification, and recovery semantics.

For example, a channel's bandwidth-delay product \(B\tau\) bounds the scale of bits that may be in flight under a particular rate and delay model. It does not automatically give the application a stable, addressable memory region. The application must be able to encode, observe, delimit, and recover the information under the actual channel model.

The survey is therefore a research substrate catalogue that can feed future typed adapters. Each candidate mechanism can be brought into the fabric when its observation, identity, transition, and recovery contracts have been established.

## 12. A single request's composition path

The following is a dependency map, not a claim that every code path uses one identical call stack:

\[
\begin{aligned}
A &\xrightarrow{\text{canonicalize/bind}} (G,P,x,\tau,O)\\
  &\xrightarrow{\text{resolve}} (\pi,s,\text{candidate host})\\
  &\xrightarrow{\text{validate}} (\text{Ground},\text{context},\text{causality},\text{budget})\\
  &\xrightarrow{\text{admit}} \text{bounded local grant}\\
  &\xrightarrow{\text{execute}} (s',o,\text{transition evidence})\\
  &\xrightarrow{\text{commit}} (\text{effect ledger},\text{receipt},\text{journal})\\
  &\xrightarrow{\text{publish/ack}} \text{reliable result path}
\end{aligned}
\]

A replay takes a different path: it locates the committed effect by semantic identity, verifies the relevant receipt/provenance, and republishes the saved result. It does not traverse the backend transition again.

The composition order is important. Routing precedes neither authority nor semantic correctness; a route only identifies a candidate path. A grant is not a commit. A commit is not a publication. A publication is not proof of downstream consumption. Each boundary has its own receipt or cursor.

## 13. Source map

| Mathematical area | Primary implementation/specification |
|---|---|
| Deterministic machine and feature contracts | [ARCHITECTURE.md](ARCHITECTURE.md), [INVARIANTS.md](INVARIANTS.md), mailcpu/interpreter.py, mailcpu/scheduler.py |
| Host identity and operational loci | [COMMUNICATION_HOST_MODEL.md](COMMUNICATION_HOST_MODEL.md), [EGPU_NAVIGABLE_FABRIC.md](EGPU_NAVIGABLE_FABRIC.md) |
| Computational Ground, address, and execution modes | [COMPUTATIONAL_ADDRESSING.md](COMPUTATIONAL_ADDRESSING.md), [VIRTUAL_LAYER_WORKLOAD.md](VIRTUAL_LAYER_WORKLOAD.md) |
| State-space and exact/formal navigation | [STATE_SPACE_NAVIGATION.md](STATE_SPACE_NAVIGATION.md), [FORMAL_NAVIGATION.md](FORMAL_NAVIGATION.md), [CONTEXTUAL_PROCESS_NAVIGATION.md](CONTEXTUAL_PROCESS_NAVIGATION.md) |
| Admission and state-owning commit | [NAVIGATION_COORDINATOR.md](NAVIGATION_COORDINATOR.md), [NAVIGATION_ADMISSION.md](NAVIGATION_ADMISSION.md), [NAVIGATION_EXECUTION.md](NAVIGATION_EXECUTION.md) |
| Causal computation dependencies | [NAVIGABLE_COMPUTATION_DAG.md](NAVIGABLE_COMPUTATION_DAG.md), [TEMPORAL_CLOCK_FABRIC.md](TEMPORAL_CLOCK_FABRIC.md) |
| Semantic equivalence and oracle evidence | [SEMANTIC_TRANSLATION.md](SEMANTIC_TRANSLATION.md), mailcpu/transit_oracles.py |
| Generative memory, revision, and context | [STRUCTURAL_MEMORY.md](STRUCTURAL_MEMORY.md), mailcpu/structural_memory.py, mailcpu/law_certifier.py |
| Authenticated peer discovery, lease refresh, and reconnectable listener | [COMPUTATIONAL_FABRIC.md](COMPUTATIONAL_FABRIC.md), mailcpu/computational_fabric_discovery.py, [FEDERATED_FORWARDING_PROCESS_RECOVERY.md](FEDERATED_FORWARDING_PROCESS_RECOVERY.md) |
| Checkpoint integrity and rollback detection | [RECOVERY_BUNDLE.md](RECOVERY_BUNDLE.md), [RECOVERY_LINEAGE.md](RECOVERY_LINEAGE.md), [COMPUTATIONAL_FABRIC_FORWARDING_RECOVERY.md](COMPUTATIONAL_FABRIC_FORWARDING_RECOVERY.md) |
| vCPU and accelerator integration | [NATIVE_VCPU_CONTEXT.md](NATIVE_VCPU_CONTEXT.md), [EGPU_NAVIGABLE_FABRIC.md](EGPU_NAVIGABLE_FABRIC.md), mailcpu/elf.py |
| Candidate physical/information substrates | [COMMUNICATION_SUBSTRATES_AND_INFORMATION_THEORY.md](COMMUNICATION_SUBSTRATES_AND_INFORMATION_THEORY.md) |

When in doubt, the local subsystem specification and its tests are authoritative. This map explains how the mathematics fits together and where each active build connects to its existing contracts.


## 14. In development — ongoing architectural work

These are active development paths for increasing the system's ability to describe, interpret, observe, navigate, realize, and verify computation. Move each forward through a typed contract, implementation, independent oracles where useful, and repeatable tests. Update this section as work is completed or decomposed.

- **Global semantic resolution — in progress:** extend the existing computational address and receiver-local resolver into coordinated search over host, state, checkpoint, implementation, and evidence catalogues. Keep resolution proposals separate from local authority and execution.
- **Authenticated topology discovery — in progress:** extend direct-peer refresh into restart-aware topology reconciliation across larger federations. Add controlled peer federation/gossip only with verifiable origin and revision evidence; a relayed claim must never be mistaken for a direct TLS observation.
- **Peer-service supervision — in progress:** a bounded parent-owned subprocess supervisor, readiness-token/PID validation, atomic peer-authority snapshot store, and hard-kill/restart/lease-reacquisition test now form the one-client service baseline. Extend this to parent-supervisor recovery, multi-identity listener acceptance, endpoint revision/rotation, multi-peer topology federation, and protected or recovery-lineage-anchored bootstrap state.
- **Multi-objective navigation — in progress:** evolve deterministic bounded routing into Pareto-aware or policy-lexicographic selection using measured latency, transfer volume, resource cost, verification work, and recovery risk. Calibrate physical energy claims against declared instruments and workloads.
- **General state-space acceleration — in progress:** broaden sound abstract interpretation and exact witness reconstruction beyond current affine and finite transition subsets; compose symbolic constraints with concrete path replay.
- **Structural Memory growth — in progress:** add further typed generator families, composable law forms, richer context mappings, and verified revisions while retaining safe admission rather than turning memory descriptions into arbitrary code execution.
- **Self-revision of transition algebra — in progress:** let the system propose and test revisions to its own admitted transition descriptions, with proof obligations for compatibility, provenance, revision ancestry, and rollback.
- **Attention as a navigation budget — in progress:** formalize bounded allocation of search/evaluation effort across candidate paths, with measurable information gain, path cost, and stopping criteria.
- **Distributed effects and multi-peer failure — in progress:** extend recovery beyond the current pure deterministic workload with effect-owner idempotency, durable side-effect journals, requester/anchor failure tests, and increasingly broad peer-failure schedules.
- **Heterogeneous refinement — in progress:** prove observable correspondence between abstract Ground transitions, native vCPU execution, E-GPU methods, emulators, and remote hosts under explicit contracts and independent semantic oracles.
- **vCPU and accelerator realization — in progress:** grow the native context adapter toward a complete instruction-execution core and connect the E-GPU operational graph to a faithful emulator or hardware backend, with resource and performance measurements.
- **Physical/information-theoretic substrates — in progress:** convert promising channel, delay, timing, and routing phenomena into typed state resources only after encoding, observation, noise, contention, expiry, security, and recovery have been experimentally established.
- **End-to-end origin evidence — in progress:** bind origin identity and semantic operation commitments to portable signed evidence while preserving immediate-neighbor mutual TLS and receiver-local authorization as separate trust layers.


## 15. Computational objects, byte identity, and temporal interpretation

The M0/M1 computational-hosting foundation is documented in
[COMPUTATIONAL_OBJECTS_AND_TIME.md](COMPUTATIONAL_OBJECTS_AND_TIME.md) and
[TRANSIT_BYTE_OBJECTS.md](TRANSIT_BYTE_OBJECTS.md).

It separates:

- immutable byte identity and manifest;
- computational Ground and representation semantics;
- live state and permitted transition relation;
- logical host identity and current placement;
- communication-path ordering and the time coordinates owned by existing
  event, causal, scheduler, monotonic, wall, chronon, and chemical domains.

The M1 implementation in `mailcpu/computational_objects.py` composes the
existing `PageBacking` contract. It represents an object as ordered,
fixed-size content-addressed pages with explicit logical byte lengths. The
manifest digest binds the ordered references and representation metadata;
the content digest binds the original unpadded logical bytes.

This is a data-plane foundation, not a universal interpreter. The bytes of a
model, ELF image, memory page, operating-system image, or activation tensor
still require their own Ground, layout and executable runtime contract.
Likewise, the object manifest is immutable and has no timestamp: admission,
transfer, interpretation, state transitions, commit, and recovery continue
to use their existing E-CPU identities and temporal coordinates.

The two distributed model-execution forms share this foundation:

1. Replicated hosting: compatible hosts retain the same admitted immutable
   artifact while requests and session continuations are routed.
2. Partitioned execution: distinct hosts realize typed partitions whose data
   dependencies are represented by the existing computation-graph and
   communication mechanisms.

Neither a global object resolver nor partitioned neural execution is claimed
by M1. The current remote composition reuses `RemotePageStore` and its
existing replicated-mailbox page transitions.


## 16. General computational artifact hosting

The M2 local-hosting contract is specified in
[COMPUTATIONAL_HOSTING.md](COMPUTATIONAL_HOSTING.md) and implemented in
mailcpu/computational_host.py.

It composes a multi-file artifact identity from component path, media type,
logical size, byte digest, metadata, and optional nested M1 byte-object
manifests. The artifact identity remains separate from the backend profile
fingerprint, operation identity, host identity, and output digest.

Backend adapters are trusted local implementations. The common contract
specifies load, execute, and unload, while domain-specific runtimes retain
their own Ground and representation semantics. Requests and results use a
bounded finite-JSON control envelope; large binary state remains in the M1
page/object plane and is referenced rather than embedded into ordinary
Virtual Layer workloads.

A deterministic host receipt binds artifact, backend, workload, logical time,
input, and output identities. Local monotonic duration is an independent
measurement and is not placed in a replayed pure-operation receipt. The
receipt status is EXECUTED, not a claim of durable commitment, signature, or
origin authentication. Existing Virtual Layer, receiver-local Hypervisor,
reliable channels, and Transit workers remain the authority and commit path.

This is a local hosting contract, not a general artifact catalog, hardware
attestation layer, session-state migration mechanism, or partition scheduler.


## 17. Persistent computational sessions and state

The M3 session contract is specified in
[COMPUTATIONAL_SESSIONS_AND_STATE.md](COMPUTATIONAL_SESSIONS_AND_STATE.md)
and implemented in mailcpu/computational_session.py.

Each session is one independent fixed-membership recovery lineage whose
system identity equals the session identity. Immutable state payloads are
stored through M1 ComputationalObjectStore pages. A typed checkpoint binds
the session, artifact, backend profile, state schema, revision, predecessor
checkpoint and lineage roots, transition identity, input commitment, logical
time, and M1 state manifest.

The checkpoint bytes are sealed through the existing RecoveryStateManifest
and RecoveryLineageCoordinator. A session revision is current only when its
root is the quorum-supported high-water; local revision numbers and files do
not select current state. Continuation requires an exact expected revision
and checkpoint digest. A conflicting or stale writer cannot overwrite the
anchored state. Exact immediate retries can recover the already committed
revision after a lost response.

Checkpoint envelopes are durably written before the quorum seal. A partially
prepared transition can be resumed only from its exact persisted proposal.
Portable exports carry checkpoint and quorum evidence while leaving bulk
state bytes in M1. Host replacement requires the same artifact and state
schema, an accessible M1 page backing, the same fixed session lineage, and
explicit backend compatibility when the backend fingerprint differs.

M3 persists and anchors state; it does not interpret the bytes, execute the
domain transition, atomically commit arbitrary external effects, or perform
membership reconfiguration.


## 18. Stateful interpretation and compiled virtual grounds

The M4 extension is specified in
[COMPUTATIONAL_SESSION_INTERPRETATION.md](COMPUTATIONAL_SESSION_INTERPRETATION.md)
and implemented by mailcpu/computational_transition.py.

A transition adapter admits only a declared deterministic pure backend. It
starts from a ComputationalSessionSnapshot already verified against M1
state pages and the existing quorum lineage, builds a context digest binding
the session revision, checkpoint, lineage root, artifact, backend, state
schema, interpretation, input and operation, and asks the local backend for
candidate successor bytes. The existing session store performs the revision
and checkpoint compare-and-swap and quorum seal. The adapter does not infer
state semantics from bytes and does not make arbitrary external effects
transactional.

The VGI adapter compiles a typed TaskSpec under the explicit Signal8
GroundSpec into an immutable Program IR and caches that plan by
computational-Ground fingerprint, E-CPU/VGI source implementation identity,
and canonical task digest. Every execution still constructs a fresh mutable
SignalStateMachine from its own validated input state. The plan digest is
included in the receipt and may be used as the generic transition contract's
interpretation fingerprint.

This is compilation of declared semantics, not inference of an unknown
Ground from opaque bytes. The admitted E-CPU System Ground, the VGI
Computational Ground, the compiled program, the session state, and the
execution host remain distinct identities. Cached IR is an optimization;
M1 pages and the quorum-anchored session checkpoint remain authoritative.

## 19. Persistent VGI interpretation, bounded quanta, and host transit

M5-M7 are specified in
[VGI_PERSISTENT_SESSIONS_AND_TRANSIT.md](VGI_PERSISTENT_SESSIONS_AND_TRANSIT.md)
and implemented by `mailcpu/vgi_session.py`.

A compiled VGI session descriptor binds the explicit Signal8 Computational
Ground, canonical typed TaskSpec, VGI Program IR, source implementation
fingerprint, semantic interpretation identity, and M2 composite artifact
manifest. Its semantic identity binds Ground, task, and Program; the compiled
plan identity additionally binds the compiler implementation.

The machine's mutable state is serialized using VGI's own checkpoint format.
E-CPU wraps it with the descriptor digest and bounded continuation status,
stores those exact bytes as an M1 computational object, and anchors the M1
manifest through the existing M3 session checkpoint and quorum lineage.
The machine is restored only under the exact Ground and Program.

M6 advances at most the caller-requested quantum (itself capped by the
configured maximum) using individual VGI instruction steps. Each successful
quantum produces one candidate state and one M3 compare-and-swap/quorum
revision through the M4 transition adapter. The cumulative step and state
bounds are independent of the per-quantum bound. A terminal `halted` or
`step_limit` status is part of the committed state envelope.

M7 exports the semantic descriptor, M3 checkpoint and proof, M1 manifest,
and bounded state bytes. A target host imports the bytes into its own M1
page store, requires identical page geometry, verifies that the resulting
manifest is exact, and then verifies the original quorum proof. A changed
execution backend profile or VGI implementation requires its respective
explicit compatibility predicate. The transition context carries both the
backend fingerprint of the current committed state and the target execution
backend fingerprint, so migration does not rewrite historical provenance.

The transfer package is bounded and currently serializes the complete state
payload as base64 JSON (default maximum 64 MiB); it is not a streaming
chunk-transfer protocol. The receiving process reconstructs a new VGI
interpreter and machine from the checkpoint, rather than migrating a live
Python process or synthesizing pre-checkpoint undo history. Only declared
pure execution is admitted by this path.


## 20. Persistent VGI continuation across a communication path

The first executable composition of M0-M7 session state with the peer
forwarding graph is described in
[FABRIC_VGI_SESSION_COMPOSITION.md](FABRIC_VGI_SESSION_COMPOSITION.md) and
implemented by `mailcpu/computational_fabric_vgi.py`.

The tested path is:

\[
A_{\text{source session}}
\rightarrow B_{\text{NETWORK relay}}
\rightarrow C_{\text{M1/M3 import + M4 VGI quantum}}
\]

The A→B→C peer graph, authenticated mutual-TLS streams, and typed
ComputationalAddress are distinct from the VGI Ground and Program. B handles
the forwarding transition only. C rebuilds local authority, admits the
terminal Virtual Layer operator, imports the M7 checkpoint into its own M1
page backing, verifies the source M3 quorum proof, and advances the original
VGI session by one bounded quantum. The target receipt retains the session,
descriptor, Ground, task, Program, interpretation, artifact, state schema,
backend, predecessor, logical-time and lineage coordinates.

The experiment also separates transport replay from semantic replay. A new
transport delivery may cause B to re-enter a NETWORK forwarding transition;
C's terminal execution ledger returns its cached CPU result, while the M3/M4
session transition recognizes its exact immediate retry. This is not a
global atomic transaction or an exactly-once guarantee for arbitrary
side-effects.

The test records source export time, bundle bytes, state bytes, M7 decode,
target M1 import/M3 proof verification, M4 transition plus persistence/quorum
commit, full target M1 verification, and end-to-end forwarding duration.
These measurements provide the first comparable baseline for deciding
whether inline base64 transfer should be replaced by chunked M1 page streaming.
They are empirical local-run measurements, not physical network speed
claims or a general performance model.


## 21. Intent interpretation versus payload materialization

Virtual Layer requests now have two related but non-interchangeable
representations:

\[
R=(\underbrace{\Pi(W)}_{\text{bounded intent}},\
\underbrace{P(W)}_{\text{complete payload}},\
d(W),\ |P(W)|)
\]

\(\Pi(W)\) contains the workload goal, Ground and system coordinates,
operator contract, resource budget, logical time, and input metadata.
\(P(W)\) is the full canonical workload and input, including any opaque state
or object transfer. Its digest and byte length are included in the intent
projection presented to the classifier.

The classifier and intent embedding operate on the bounded projection, which is restricted to the Virtual Layer operation contract and a 4 KiB canonical byte ceiling. Virtual-cost accounting retains full-payload semantic bits and chemical complexity while counting structural tokens only over the compact projection.
Event identity, replay conflict detection, durable request state, receiver
execution and operator input validation retain the complete payload. The
receiver independently recomputes \(\Pi(W)\) from \(P(W)\), the locally
resolved operator contract and resource bounds before preparing the handler.
A projection mismatch is rejected before the handler can run.

This separates semantic interpretation cost from data materialization cost.
It does not make payload bytes free: canonical hashing, event journaling,
transport, object admission, state persistence and output encoding still
consume measurable resources. The next optimization is to transfer M1 pages
as bounded content-addressed chunks while retaining the manifest and digest
checks; the intent projection remains the compact control-plane descriptor.


## 22. Compositional Virtual Ground and inverse state navigation

The executable composition layer is specified in [COMPOSED_VIRTUAL_GROUND.md](COMPOSED_VIRTUAL_GROUND.md) and implemented by `mailcpu.composed_ground`. It separates the two descriptions that must remain coupled:

\[
\text{Structural information}
\quad\leftrightarrow\quad
\text{Interpreted structure}.
\]

Structural information names bytes, fields, register/memory layout, component identities, state coordinates, generator parameters and digests. Interpreted structure names the Computational Ground, state schema, each field's meaning, scalar encoding, invariants and admitted transition semantics.

`ComposedVirtualGroundAddress` binds one SystemIdentity, base VirtualGroundRef, Computational Ground, typed scheduler coordinate, state schema, canonical template and a set of independently pinned component Structural Memory revisions. Each component binds a disjoint field path and content-addressed representation. All components share the same base-relative orbit coordinate. `ComposedVirtualGroundNavigator` evaluates each admitted generator directly at that coordinate and assembles a state-shaped Virtual Ground projection, retaining an independent receipt for each component and a digest for the composed result.

This projection is not automatically a HeadlessOS checkpoint. Full checkpoint promotion requires the state schema to establish complete VM/OS subsystem coverage and the state owner to validate the result through the existing restore path.

Inverse routes now include:
- GF(2) scalar-output-bit inversion from the initial register and feedback parity in O(L).
- Finite functional-graph inversion with a reusable earliest-coordinate index, O(N) build then expected O(1) lookup.
- `ProcessPathIndex` for one explicitly supplied declarative transition path, O(P) validation/index build then expected O(1) exact-state lookup. A deserialized index must be revalidated against its descriptor and context; path-index absence is not global unreachability.
- Existing arithmetic progression and eligible 2-adic LCG inverses.

The process path index verifies the declared transition sequence, guards, resource conditions and invariants. It is a proof about the declarative process model, not a claim that a physical host executed the transitions. An actual execution trace still needs the owning host's execution evidence.

These mechanisms reduce avoidable trajectory materialization but do not implement the future model-selection optimizer. Ranking candidate descriptions by predictive coverage, withheld error, description cost, navigation cost and verification cost remains a distinct next layer. The aspiration that the E-CPU abstraction outperform the system it describes is a research objective, not a guarantee established by state composition alone.


## 23. Predictive description selection over observed Virtual Grounds

The next layer is specified in [PREDICTIVE_DESCRIPTION_SELECTION.md](PREDICTIVE_DESCRIPTION_SELECTION.md) and implemented by mailcpu.predictive_selection. It compares fixed, admitted composed descriptions against independently captured state observations.

For one experiment identity \(E\), the same observations are evaluated by each candidate \(C_j\):

\[
\hat S_{j,t}
=
\operatorname{Compose}(C_j,t),
\qquad
\epsilon_{j,t}
=
\operatorname{Compare}(\hat S_{j,t},S_t^{\mathrm{observed}}).
\]

The experiment digest binds the system incarnation, base Ground, Computational Ground, scheduler, schema, template, component paths and encodings while excluding the candidate-specific generator revisions. An ObserverContract and ObserverReceipt bind every observed state to that experiment and its typed scheduler tick.

Selection is chronological: development observations are diagnostic, validation determines the Pareto frontier and recommendation, and later test observations report post-selection performance without changing the ranking. The evidence dimensions include whole-sample coverage, component accuracy, predictive yield, exact full-state match, residual/unmodeled state changes, description bytes, certificate witness count and a family-aware navigation-work proxy. It also counts distinct observed, predicted and matched component-value tuples, reporting matched distinct observed support as component-state-space coverage. This covers the states present in the sampled trajectory only; it does not enumerate or estimate the global reachable set. Each partition now includes per-component observed/predicted value support, point accuracy, changed/unchanged detection, false positives/missed changes, and exact sampled before/after transition matches. Component support is set-based and independent of timing; pointwise and transition metrics retain temporal alignment. The forward navigation-work proxy charges finite-graph reads for stored-orbit materialization and treats GF(2) initial-register outputs separately from matrix-jump coordinates. A sampled transition spans adjacent supplied observations; a refused prediction breaks transition continuity rather than being bridged.

PredictiveCandidatePoolBuilder now constructs a bounded baseline-plus-one-factor pool from already-admitted Structural Memory versions with exact matching component contexts. It never crosses every component revision combination; pool order, candidate budget and omitted count are deterministic and digest-bound. Candidate discovery is advisory and does not stage or admit revisions. The evaluate_pool path binds the exact pool digest, maximum candidate budget, and discovered/included/omitted counts into the selection report.

The selector uses ComposedVirtualGroundNavigator for direct reads at each observed coordinate. A guarded refusal lowers coverage; there is no hidden breadth-first search, orbit enumeration or SystemSeed replay. Each partition carries a navigation-evidence digest over the requested coordinates, projection identities and component read-receipt digests (including refusal outcomes).

The hypervisor adapter retains the complete canonical typed executed ALLOW result from the Virtual Layer and cross-checks its content digest, placement, estimated virtual energy/ticks, replay state and measured handler metrics during deserialization. An optional compute-fabric route witness contributes network/host/total cost vectors only as a non-authoritative route estimate, and its target node must match the hypervisor effect's execution node. Neither evidence source becomes a prediction label or an implicit selection weight; operational measurements remain a separate report profile.

The recommendation does not admit revisions, alter hypervisor policy, establish a physical checkpoint, or prove the observer was honest. The existing Hypervisor shadow-and-witness revision admission and idempotent proposal ledger are documented as the future promotion pattern, while the current selector remains advisory. The typed ComputationalAddress and fabric route/decomposition path are documented as the future distribution substrate; current evaluation remains local and route witnesses remain planning context. This creates an auditable first model-selection loop; candidate synthesis, vector/page generators, distributed evaluation and online policy promotion remain later work.
