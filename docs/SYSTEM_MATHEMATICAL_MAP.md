# E-CPU Mathematical System Map

## Purpose and reading discipline

This document maps the mathematics already present across E-CPU / MailCPU. It is an index and a composition model, not a replacement for subsystem specifications. E-CPU is organized as a family of typed transition systems whose contracts compose through explicit interfaces. Different state owners, graphs, clocks, and solvers retain their own identities and semantics.

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

A logical host is an identifiable operational locus:

\[
H=(I,C,S,T,K,L)
\]

- \(I\): stable logical identity.
- \(C\): communication interfaces and adjacency.
- \(S\): operational state; it may be empty for a stateless transform.
- \(T\): its defined information transition.
- \(K\): capabilities available and permitted at that locus.
- \(L\): operational lineage, revision, provenance, and recovery identity.

A substrate carries information; a host performs a defined operation; a path relates substrate edges and host transitions. A passive link is normally an edge, not a host. A server process may realize a host, but process identity and logical host identity are not interchangeable.

For a path \(\pi=(h_0,\ldots,h_n)\), its semantic computation is a composition of admitted transitions:

\[
F_\pi = T_{h_n}\circ T_{h_{n-1}}\circ\cdots\circ T_{h_0}
\]

This composition is meaningful only where adjacent request/reply schemas, semantic identities, causal dependencies, authority requirements, and observation contracts match. Physical placement may change while logical host identity and required lineage remain stable.

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


## 14. To Do — ongoing builds

These are development directions, not fixed exclusions. Each item is an active extension path; move it forward through a typed contract, implementation, independent oracles where useful, and repeatable tests. Update this section as work is completed or decomposed.

- **Global semantic resolution — in progress:** extend the existing computational address and receiver-local resolver into coordinated search over host, state, checkpoint, implementation, and evidence catalogues. Keep resolution proposals separate from local authority and execution.
- **Authenticated topology discovery — in progress:** extend direct-peer refresh into restart-aware topology reconciliation across larger federations. Add controlled peer federation/gossip only with verifiable origin and revision evidence; a relayed claim must never be mistaken for a direct TLS observation.
- **Peer-service supervision — in progress:** extend the reconnectable listener and refresh manager into process-supervised services with lifecycle telemetry, endpoint rotation/revision, restart policy, and deployment-managed local authority re-registration. Bind endpoint/refresh bootstrap configuration to protected deployment or recovery-lineage state, not merely a self-digest.
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
