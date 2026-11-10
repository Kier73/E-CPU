# Computational State-Space Architecture

## Purpose

This document defines the intended centre of E-CPU: a computational architecture in which finite descriptions establish navigable state-spaces, inputs give those spaces context, observers specify the information being sought, and E-CPU realizes a path to the required observation.

The physical computer, process, model host, or accelerator connected to E-CPU supplies resources and interfaces for interpreting, transporting, and rendering information. It does not need to own the semantic identity or complete execution history of the computation. Those identities and accepted transitions belong to the E-CPU computational path.

This is the architectural direction. The codebase already contains important pieces of it, but the complete description-to-observation path remains in development.

## 1. The central idea

A finite description can represent a state-space much larger than the description itself. A recurrence can describe a sequence without storing every term. A transition grammar can describe a family of possible processes without enumerating every path. A mathematical domain can be represented through its laws and supported observations without materializing every member.

E-CPU should treat a verified description of a state-space as a computational resource.

It should not attempt to store a literal list of every possible state. Its aim is to contain the representational and operational capacity to describe every computation expressible within its admitted languages and Grounds, and to navigate the relevant portions of that capacity when a request is interpreted.

This capacity is relative to the declared languages and rules. A Ground does not automatically describe objects or operations outside what its language can express.

Let a Computational Ground be:

\[
G=(\mathcal L,\Sigma_G,\Delta_G,\mathcal I_G,\mathcal O_G,\mathcal C_G,\mathcal E_G,\nu_G)
\]

where:

- \(\mathcal L\) is the description and representation language;
- \(\Sigma_G\) is the state-space denoted by valid descriptions in that language;
- \(\Delta_G\) is the family of admitted transformations and transitions;
- \(\mathcal I_G\) is the set of invariants and admissibility rules;
- \(\mathcal O_G\) is the family of observer projections and predicates;
- \(\mathcal C_G\) describes navigation, materialization, communication, and verification costs;
- \(\mathcal E_G\) is the evidence supporting the Ground and its operations;
- \(\nu_G\) identifies the Ground version and schema.

### Capacity, path, and observation

Keep three objects distinct:

| Object | Meaning |
|---|---|
| \(\Sigma_G\) | The symbolic capacity described by the Ground |
| \(\pi\) | A particular path through admitted states or transformations |
| \(o\) | The information selected by an observer at a state or coordinate |

A description can denote a very large space while one request observes only a small portion of it. The path need not be fully materialized for a direct coordinate evaluation or a verified inverse lookup to be useful.

## 2. Input gives the Ground context

An external input is not automatically a program in one universal instruction language. It may be source code, a mathematical expression, a typed task, a model request, a signal, a process observation, or a symbolic state reference.

An interpretation step associates the input with a Ground and context:

\[
D_x=\operatorname{Interpret}(x,G,c)
\]

The resulting description constrains the relevant state-space:

\[
\Sigma_{G|x,c}
=
\{s\in\Sigma_G\mid D_x(s)\land \mathcal I_G(s)\}.
\]

The system need not construct every possible state and then filter them. A suitable representation can carry the constraints symbolically.

Interpretation must preserve uncertainty. If the input does not identify a unique meaning, the result should carry alternatives, an explicit ambiguity, or an unresolved requirement. Missing information must not silently become an assumed operation or transition.

The semantic request should remain distinct from its physical realization:

\[
A=(G_s,G_c,D_x,\theta,x,\tau,\mathcal O)
\]

where \(G_s\) is the admitted system Ground, \(G_c\) is the computational Ground, \(D_x\) is the interpreted description, \(\theta\) is the intention or requested property, \(x\) is the input/state reference, \(\tau\) is the logical or causal coordinate, and \(\mathcal O\) is the requested observation.

A physical address, process identifier, CPU core, or model server is a placement choice, not part of this semantic identity.

## 3. Observation as computation

Observation is central, but it is useful to distinguish a passive read from an active interpretation.

A passive read retrieves an already materialized value. An active observation can evaluate a generative law at a requested coordinate, resolve a symbolic state reference, apply a representation projection, test whether a state satisfies a predicate, compare multiple observers or candidate descriptions, or derive a coordinate whose observed value matches a requested condition.

Those active forms are computational operations.

For a Ground \(G\), description \(D\), observer \(\mathcal O\), and coordinate \(t\):

\[
y=\operatorname{Observe}(G,D,\mathcal O,t).
\]

The result may be obtained through direct evaluation, indexed retrieval, a verified inverse, a composed transformation, or a search over a declared path.

This is the precise sense in which observation can be execution: the system's interpretation of the description produces the requested information. It does not mean that every passive observation is itself a state-changing computation.

## 4. Time and navigation

A computation may be described as an orbit through a Ground:

\[
s_{t+1}=T_G(s_t),\qquad s_t\in\Sigma_G.
\]

A conventional method may generate each intermediate state. E-CPU should select a method appropriate to the Ground and request.

For a known coordinate:

\[
s_t=\operatorname{Eval}_G(D,t).
\]

For a requested observation predicate \(P\):

\[
t^\star=\min\{t\in\mathcal T_G:
P(\mathcal O_G(s_t))=\mathrm{true}\}.
\]

When the Ground supports a verified inverse, E-CPU can derive \(t^\star\), then evaluate and verify the candidate state. When no direct method applies, the navigator can traverse an explicitly described path or graph using its declared resource policy.

The available strategy families include direct algebraic coordinate evaluation, inverse navigation from a target value or observation, reusable indexes over finite state families or supplied paths, abstract reachability and equivalence analysis, bounded traversal of explicit transitions, and composed navigation across compatible Grounds.

Logical time, scheduler ticks, wall-clock time, monotonic duration, and causal order are different coordinates. A request must name the relevant time domain rather than allowing an implicit conversion.

The optimization objective is not simply to minimize instruction count. It is to select a valid method using a cost vector that can include arithmetic work, expanded states, memory, materialization, communication, verification, and recovery.

## 5. In-transit computation

"In transit" describes a logical path through which a computation's identity, representation, state references, and evidence move.

A message can carry a continuation description:

\[
m=(id,G,P,x,c,\tau,\theta,\mathcal O,B,E)
\]

where the fields identify the operation, Ground, program or transition description, input/state references, context, logical coordinate, intention, requested observation, resource budget, and evidence prerequisites.

A passive link transports the message. A host or observer on the path performs a declared interpretation, observation, or transition. Multiple hosts may contribute different transformations to one computation.

The path can therefore look like:

\[
\text{input adapter}
\rightarrow
\text{Ground resolver}
\rightarrow
\text{state observer}
\rightarrow
\text{navigator}
\rightarrow
\text{realizer}
\rightarrow
\text{verifier}
\rightarrow
\text{output adapter}.
\]

The same semantic operation may be realized on different physical hosts without changing its identity, provided the selected implementations preserve the admitted Ground, state, and observation contracts.

Network propagation alone does not perform computation. Information becomes an admitted computational path when its interpreters and transitions are declared, authorized, resourced, observed, and connected by compatible contracts.

## 6. The computational path, ordered

The intended end-to-end method is:

1. **Describe.** Receive an input in an identified language or representation.
2. **Interpret.** Associate it with a versioned Ground, schema, context, and intention.
3. **Constrain.** Derive the relevant state-space or symbolic subspace without materializing unrelated states.
4. **Observe.** Define the requested information and the evidence required to accept it.
5. **Navigate.** Select direct evaluation, inverse, indexing, transformation, or explicit traversal.
6. **Realize.** Resolve an appropriate E-CPU host/path and execute only the transitions required by the selected method.
7. **Verify.** Check the result against the declared observation, invariants, provenance, and independent evidence where available.
8. **Render.** Translate the accepted observation into the representation requested by the external system.

The eight stages describe one logical request. An implementation may combine stages, but it should preserve their distinct identities and obligations.

## 7. Existing E-CPU mechanisms that already fit

The current codebase contains several mechanisms that become more powerful when operated in this order.

| Mechanism | Existing role in the intended architecture | Primary source |
|---|---|---|
| Structural Memory and Law Certifier | Stores admitted generative descriptions with context, revisions, and evidence instead of materializing every value | [STRUCTURAL_MEMORY.md](STRUCTURAL_MEMORY.md), [mailcpu/structural_memory.py](../mailcpu/structural_memory.py), [mailcpu/law_certifier.py](../mailcpu/law_certifier.py) |
| Virtual Ground references | Bind a computation to an admitted system state and input frontier | [mailcpu/virtual_layer.py](../mailcpu/virtual_layer.py) |
| Composed Virtual Grounds | Describe a multi-component state from independently identified components and their admitted laws | [COMPOSED_VIRTUAL_GROUND.md](COMPOSED_VIRTUAL_GROUND.md) |
| Observer contracts and receipts | Give observations stable subject, Ground, context, projection, and evidence identities | [OBSERVER_ORBIT_CONTRACT.md](OBSERVER_ORBIT_CONTRACT.md), [mailcpu/observer_orbit.py](../mailcpu/observer_orbit.py) |
| Typed substrate observations | Decode resolver, timing, delay, temporal, and phase observations into typed evidence and register projections | [mailcpu/observation.py](../mailcpu/observation.py), [tests/test_observation_bridge.py](../tests/test_observation_bridge.py) |
| Quorum-gated observation ingestion | Collect source-linked observations, compare them under a declared source/quorum policy, and apply authorized representatives through a crash-safe coordinator | [mailcpu/gated_observation.py](../mailcpu/gated_observation.py), [mailcpu/observation.py](../mailcpu/observation.py) |
| Structural intent representation | Encode an already structured request deterministically from its typed paths, values, and sequence positions; prototype predictions remain advisory | [mailcpu/intent_embedding.py](../mailcpu/intent_embedding.py), [tests/test_intent_embedding.py](../tests/test_intent_embedding.py) |
| Candidate Ground-family suggestion | Rank likely law families from an observed integer window while deterministic law recovery and witness verification determine the admitted result | [mailcpu/neural_lifter.py](../mailcpu/neural_lifter.py), [mailcpu/law_certifier.py](../mailcpu/law_certifier.py), [tests/test_neural_lifter.py](../tests/test_neural_lifter.py) |
| Composed Virtual Ground projections | Assemble independently admitted component laws into one structured state projection at a shared scheduler coordinate | [COMPOSED_VIRTUAL_GROUND.md](COMPOSED_VIRTUAL_GROUND.md), [mailcpu/composed_ground.py](../mailcpu/composed_ground.py) |
| Predictive description selection | Compare admitted candidate descriptions with independent chronological observations and rank them using predictive and cost metrics | [PREDICTIVE_DESCRIPTION_SELECTION.md](PREDICTIVE_DESCRIPTION_SELECTION.md), [mailcpu/predictive_selection.py](../mailcpu/predictive_selection.py) |
| Typed temporal coordinates | Keep wall, monotonic, causal, scheduler, event, chronon, and chemical coordinates distinct | [TEMPORAL_CLOCK_FABRIC.md](TEMPORAL_CLOCK_FABRIC.md), [mailcpu/temporal.py](../mailcpu/temporal.py) |
| Reversible trajectory representation | Record reversible gate traces and periodicity metadata for trajectory analysis and Bennett-style replay | [mailcpu/chronofold.py](../mailcpu/chronofold.py), [mailcpu/reversible_gates.py](../mailcpu/reversible_gates.py) |
| Contextual orbit navigation | Evaluate a certified law at a scheduler coordinate and return a typed projection and receipt | [OBSERVER_ORBIT_CONTRACT.md](OBSERVER_ORBIT_CONTRACT.md) |
| Inverse navigation | Derive coordinates for selected integer, LCG, GF(2), and finite-graph observation families | [mailcpu/law_certifier.py](../mailcpu/law_certifier.py), [mailcpu/observer_orbit.py](../mailcpu/observer_orbit.py) |
| Formal navigation and navigation coordination | Compare concrete process navigation, abstract integer-affine reachability, representation equivalence, and causal dependencies | [FORMAL_NAVIGATION.md](FORMAL_NAVIGATION.md), [NAVIGATION_COORDINATOR.md](NAVIGATION_COORDINATOR.md) |
| Predictive description selection | Compare admitted component-law descriptions against independently observed, chronologically separated system states | [PREDICTIVE_DESCRIPTION_SELECTION.md](PREDICTIVE_DESCRIPTION_SELECTION.md), [mailcpu/predictive_selection.py](../mailcpu/predictive_selection.py) |
| Semantic translation contracts | Identify exact source/target representations and the observation expected to survive translation | [SEMANTIC_TRANSLATION.md](SEMANTIC_TRANSLATION.md), [mailcpu/semantic_translation.py](../mailcpu/semantic_translation.py) |
| Program dataflow compilation | Translate a supported pure program into an operation DAG rather than requiring one monolithic VM image | [PROGRAM_DATAFLOW_COMPILATION.md](PROGRAM_DATAFLOW_COMPILATION.md), [mailcpu/program_dataflow.py](../mailcpu/program_dataflow.py) |
| Evidence-path resolver | Search for a compatible route between representation identities using evidence and named cost dimensions | [EVIDENCE_PATH_RESOLVER.md](EVIDENCE_PATH_RESOLVER.md), [mailcpu/evidence_path_resolver.py](../mailcpu/evidence_path_resolver.py) |
| Computational objects and sessions | Keep artifact identity, state bytes, interpretation identity, and persistent session revisions distinct | [COMPUTATIONAL_OBJECTS_AND_TIME.md](COMPUTATIONAL_OBJECTS_AND_TIME.md), [COMPUTATIONAL_SESSIONS_AND_STATE.md](COMPUTATIONAL_SESSIONS_AND_STATE.md) |
| Transit and computational fabric | Move typed descriptions and state references between authenticated observer-hosts | [COMMUNICATION_STREAM_COMPUTATION.md](COMMUNICATION_STREAM_COMPUTATION.md), [COMPUTATIONAL_FABRIC.md](COMPUTATIONAL_FABRIC.md) |
| VGI and E-GPU | Supply distinct computational realizers for signal-native and lane-wise operations | [VGI_VIRTUAL_LAYER.md](VGI_VIRTUAL_LAYER.md), [EGPU_NAVIGABLE_FABRIC.md](EGPU_NAVIGABLE_FABRIC.md) |
| Recovery lineage and transferable claims | Preserve semantic identity and accepted state while execution placement changes | [RECOVERY_LINEAGE.md](RECOVERY_LINEAGE.md), [TRANSFERABLE_EXECUTION_CLAIMS.md](TRANSFERABLE_EXECUTION_CLAIMS.md) |

These systems should not be collapsed into one universal graph or instruction format. Their value comes from their different roles and the contracts connecting them.


## 7A. An existing observation-to-Ground composition

The codebase contains an especially useful sequence that is easy to miss when each subsystem is read on its own. It provides much of the material for moving from observed information to a candidate computational description, then comparing and navigating that description.

1. **Acquire typed observations.** `mailcpu/observation.py` defines a typed protocol for substrate observations. The current families include resolver, timing, delay, temporal, and phase observations. Each supplies a structured payload and a projection into a register valuation. This means observed system behaviour can already enter E-CPU through identified data forms rather than arriving only as an untyped byte stream.

2. **Establish source agreement and event identity.** `GatedObservationCoordinator` connects observations to source identities, reliable channels, an `ObservationAuthorityPolicy`, and `ObservationConsensus`. For one declared observation kind and logical event coordinate, it can gather source-linked evidence, finalize the quorum decision, and apply only an authorized representative through a crash-safe VM update path. This is an executable observation-ingestion mechanism. It does not yet feed a general Ground induction service; adapting its accepted event/evidence records to that role is in development.

3. **Describe request structure.** `IntentEmbedding` produces a deterministic structural encoding from an already typed/structured request: field paths, values, and sequence positions are hashed into a normalized vector. `IntentPrototypeModel` compares that vector with finite domain prototypes. This can help characterize request shape and propose a domain or handler family. It is not a natural-language parser, it does not discover a Ground, and its prediction is advisory. The exact request and its canonical identity remain available for later interpretation.

4. **Suggest a candidate law family.** `NeuralLifterPolicy` uses observed integer windows to produce a likely generator-family suggestion from the current `int`, `lcg`, `gf2`, `fgraph`, `kreg`, and `tape` ladder. It separately calls deterministic `recover_law`; that recovery and its witness checks determine the law verdict. A wrong or high-confidence suggestion cannot admit or veto a law. This is a useful model for how learned guidance may prioritize interpretation while deterministic evidence remains responsible for Ground admission.

5. **Admit a generative description.** A recovered law can be represented as a `StructuralMemorySpec` with exact parameters, context, revision, and certificate. The registry stages a proposal and requires the configured host admission policy before the version becomes available for reads. A typed law can then represent a state family without storing all of its values.

6. **Compose component descriptions.** `ComposedVirtualGroundAddress` combines multiple independently pinned component laws under one SystemIdentity, base Virtual Ground, Computational Ground, schema, and scheduler coordinate. `ComposedVirtualGroundNavigator` reads each selected component coordinate and assembles a structured projection with per-component read receipts. That gives E-CPU a concrete method for describing selected fields of a larger system from a set of generative descriptions.

7. **Compare descriptions with independent observations.** `PredictiveDescriptionSelector` compares already-admitted composed Ground candidates against observer-receipted states partitioned chronologically into development, validation, and later test samples. It evaluates prediction yield, coverage, full-state matches, unmodelled changes, description size, verification witnesses, and navigation work. Its candidate-pool builder can vary one component revision at a time rather than enumerate the full Cartesian product. Selection is offline and advisory: it neither learns a law from the samples nor admits or promotes a revision.

8. **Navigate the requested information.** Once the Ground and the observation intention are identified, contextual orbit navigation can directly evaluate a requested coordinate or invert a supported target value. Formal navigation can add conservative reachability analysis, representation bisimulation, and causal dependency checks. `NavigationCoordinator` composes the supported analyses into a non-authoritative proposal; the receiver's normal admission and execution path remains responsible for authority and state mutation.

9. **Translate and realize the selected path.** Semantic translation contracts identify the representation relationships that must preserve an observation. The evidence-path resolver can search known, evidence-backed representation edges under named cost dimensions. The computational fabric can then find authenticated host routes and perform receiver-authorized operations. Recovery lineage and transferable execution claims preserve the identity of accepted work as realization moves.

### What this composition reveals

The existing components form a plausible architecture for:

[
	ext{observed information}
ightarrow
	ext{typed evidence}
ightarrow
	ext{candidate description}
ightarrow
	ext{deterministically admitted Ground}
ightarrow
	ext{composed state model}
ightarrow
	ext{predictively selected description}
ightarrow
	ext{requested observation}
ightarrow
	ext{verified navigation path}.
]

The sequence above is an architectural composition proposal, not a claim that one end-to-end service already runs these stages automatically. Several pieces are independently executable and tested; their orchestration into a reusable Ground-construction and observation-planning service is in development.

The important separation to preserve is:

- **Intent suggestion** proposes what the request may concern.
- **Ground induction** proposes a law or state description from observations.
- **Evidence admission** determines which descriptions become available for use.
- **Predictive selection** compares admitted descriptions against independent observations.
- **Observation and navigation** answer the actual request using the selected Ground.
- **Physical realization** supplies resources for the transitions chosen by E-CPU.

These are related operations, but none should silently substitute for another. In particular, a request embedding is not semantic understanding; a likely law family is not a certified Ground; a high predictive score is not admission; and a reachable host is not authority to execute.

## 8. How the pieces should operate together

A useful interpretation of the current architecture is:

- Structural Memory supplies generative state descriptions.
- Computational Grounds define what those descriptions mean.
- Virtual Grounds anchor them to the admitted system and its causal state.
- Observers define which projections are meaningful.
- Navigators find coordinates and paths using the methods supported by each description.
- Translation contracts connect compatible representations.
- The evidence-path resolver finds viable compositions of those translations.
- The computational fabric supplies physical realizers for the selected path.
- Persistent sessions and recovery lineage preserve state and identity across continuation and placement changes.
- Verification and output adapters make the result usable by the requesting system.

This ordering matters. A host should not be selected before the request's Ground and observation are known. A transition should not be dispatched before its state and operation identities are resolved. A result should not be published merely because one handler returned bytes; it must satisfy the requested observation and the required evidence.

## 9. Mathematics already present and its role

The mathematical inventory in [SYSTEM_MATHEMATICAL_MAP.md](SYSTEM_MATHEMATICAL_MAP.md) should be read as a collection of reusable tools, not as a single universal solver.

Particularly useful connections are:

- **Generative laws and symbolic capacity:** a finite law represents a family of states; only requested coordinates need evaluation.
- **Modular arithmetic and recurrence inversion:** exact coordinate calculations can replace step-by-step traversal for admitted families.
- **Finite functional graphs:** an orbit can be indexed once and queried repeatedly.
- **Integer-affine abstract interpretation:** a conservative abstraction can establish reachability information without executing every concrete state.
- **Strong bisimulation:** two representations can be shown to preserve the same observable transition behavior under declared relations.
- **Vector clocks and causal DAGs:** dependencies can be distinguished from physical arrival order.
- **Information theory:** communication paths can be analyzed for capacity and information movement, while path measurements remain separate from logical work.
- **Pareto cost vectors:** latency, energy estimates, bytes, verification effort, and risk can remain distinct rather than being combined into one opaque score.
- **Signal algebra:** a representation can carry operations in its own algebra, as VGI demonstrates for its finite signal Ground.
- **Content-addressed identity and quorum lineage:** descriptions, states, and accepted continuations can retain stable identities as their placement changes.

The useful selection question is not "which one mathematical framework explains everything?" It is "which admitted structure supplies the shortest verifiable route for this particular description and observation?"

## 10. In development — capabilities to solve for

The following work connects the current mechanisms into the intended general architecture.

### Ground and description language

**In development:** a shared, versioned Ground contract that can describe domains, representations, state variables, transition families, observers, predicates, cost models, and evidence without forcing all domains into the same mathematics.

The common Ground interface should identify semantics; domain-specific backends should retain their own algebra. VGI Signal8 is one Ground implementation, not the template every other domain must imitate.

### Input and output interpretation

**In development:** adapters that translate external languages, programs, equations, model requests, tensor descriptions, signals, and application state into typed Ground-bound descriptions and back into application-usable results.

The first translator should be typed and inspectable. Natural-language interpretation can propose a typed description, but the request should preserve the source, interpretation, unresolved ambiguity, and validation evidence.

### Ground construction from observations

**In development:** a shared induction process that turns observations and controlled interventions into candidate state variables, transition laws, invariants, and observer models. It should retain known, unknown, and ambiguous transitions separately, use held-out observations, and refine descriptions in response to counterexamples.

The VGI research builds provide useful experiments for this work. Their findings should be imported as versioned evidence, not treated as automatically admitted laws.

### Observation and intention language

**In development:** a reusable way to express queries such as "find the first state satisfying this condition", "return this projection at time t", "compare these two state descriptions", or "derive the state transition connecting these observations".

The observer must say what information is required and which distinctions matter. Different tasks may legitimately use different observation projections.

### Navigation strategy selection

**In development:** a coordinator that examines the admitted Ground and requested observation, then selects direct evaluation, inverse navigation, index construction, formal analysis, explicit path traversal, or another domain-supported method.

It should expose why a strategy was selected, what work it performs, what it expands or materializes, and what evidence supports the answer.

### Compositional verification

**In development:** evidence that composes across multiple Ground translations, observations, and state transitions. Existing paired translation checks and independent operation oracles provide the initial pieces. The next stage should verify entire composed paths, not only isolated cases.

### Network-wide semantic resolution

**In development:** a resolver that can search for a compatible state, Ground, observer, translator, and physical realizer across the computational fabric. The current fabric can plan authenticated routes and dispatch declared operations, while several state and operation resolvers remain specialized or receiver-local.

### General model and tensor computation

**In development:** a Ground and operation family for tensor layouts, numeric types, vector/matrix operations, attention, stateful model sessions, and model-specific observations. It should begin with one useful workload and compare direct model execution against E-CPU interpretation, including data movement and verification costs.

The current E-CPU hosting abstraction is backend-neutral. That is a useful integration point, but it is not itself a Transformer or general model execution engine.

## 11. First falsifiable experiment: iteration, direct evaluation, and inverse navigation

The first end-to-end experiment should use an admitted modular progression:

\[
x_t=(x_0+dt)\bmod m
\]

and ask for the state at a known coordinate or the first coordinate matching a target value.

It compares three methods:

1. **Sequential iteration:** apply the recurrence one transition at a time.
2. **Direct navigation:** construct the contextual address for t and ask the actual E-CPU ContextualOrbitNavigator to evaluate and observe that coordinate.
3. **Inverse navigation:** supply the target value to ContextualOrbitNavigator.locate_value, derive the matching coordinate, forward-verify the law, and obtain the normal observation receipt.

The experiment records wall-clock samples, transition evaluations, symbolic state expansions, exact result agreement, and the navigation complexity declared by the implementation. Setup and certification work are reported separately from each query.

The expected mathematical profile for the modular progression is:

| Method | Work profile | Relevant evidence |
|---|---|---|
| Sequential iteration | O(t) transitions | Exact final value from replay |
| Direct coordinate | O(1) law evaluation for the integer-progression Ground | Structural Memory read receipt and ObserverReceipt |
| Inverse then observation | O(1) coordinate inversion plus forward verification and observation | Located coordinate, exact forward match, Structural Memory and ObserverReceipts |

This is not a claim that direct or inverse navigation will always be faster. The experiment must report actual Python implementation costs, including hashing, registry lookup, receipt construction, and interpreter overhead. It must also retain the sequential path as the correctness reference.

The executable experiment lives in [examples/state_space_navigation_experiment.py](../examples/state_space_navigation_experiment.py). Its deterministic smoke test is [tests/test_state_space_navigation_experiment.py](../tests/test_state_space_navigation_experiment.py). The results are meaningful for this admitted Ground and workload; other transition families need their own experiments.

## 12. Decision rule

E-CPU should prioritize capabilities that increase its ability to describe more computational domains through explicit, versioned Grounds; interpret more input and output representations without losing semantic identity; represent larger state-spaces through compact verified laws; navigate to required states without unnecessary expansion; compose observers, translations, and transitions into verifiable paths; select physical realizers without making placement part of computational identity; and preserve accepted state and evidence while computation continues or moves.

Execution, scheduling, storage, communication, and recovery remain essential. They are mechanisms by which the computational state-space architecture operates; they are not the final definition of the system.


## 13. Observed orbits, communication paths, and temporal memory

A Ground describes a transform system; its orbit is the sequence or relation of states that the Ground produces at its own admissible coordinates. A sensor stream or communication path can expose observations of that orbit. The received stream is evidence about the Ground, not automatically a proof of its transition law.

E-CPU now has an initial implementation that composes the existing mechanisms into the following path:

\[
\text{Observation}
\rightarrow
\text{Ground construction}
\rightarrow
\text{Description selection}
\rightarrow
\text{Intention interpretation}
\rightarrow
\text{Navigation strategy}
\rightarrow
\text{Verified realization}.
\]

The key separation is between **observed history** and **generative memory**. Observed history preserves source payloads, quorum decisions, event coordinates, and typed source/receiver timing. Generative memory preserves the admitted law, parameters, context, revision, certificate, witnesses, and evidence-bearing reads. The trace digest is embedded in the Ground context, so the generator remains connected to the stream from which it was recovered.

The trace uses an explicit ordinal sample coordinate for the first trace-recovery ABI while retaining the source's logical event time separately. An irregular signal cadence therefore does not silently become a unit-step recurrence.

Latency is treated as a typed temporal vector rather than one global number. Local monotonic duration, wall time, causal order, scheduler progress, event sequence, chemical time, and chronon phase retain their distinct comparison rules. A cross-host causal relation does not manufacture a comparable monotonic duration.

The initial implementation also closes two realization paths: a single admitted Ground can be navigated directly or inversely under the receiver's actual Hypervisor read capability; a selected composed Ground can be navigated at a common scheduler coordinate under a capability scoped to its component revisions and context. Both paths produce evidence-bearing observer results.

See [Observed Orbit Pipeline](OBSERVED_ORBIT_PIPELINE.md) for the API, contracts, latency model, tests, and active development sequence. The current implementation is a deliberate first vertical slice: arbitrary symbolic/tensor induction, multi-hop six-stage realization, and long-lived stream compaction remain in development.
