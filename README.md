# E-CPU

**A computational state-space architecture for describing, interpreting, and navigating computation.**

E-CPU is being developed around a different centre of computation: the semantic state-space described by an input, the Ground that gives it meaning, and the observations and transformations needed to reach a requested result.

The goal is for computational meaning, logical state, and accepted results to belong to E-CPU. Connected computers, processors, models, services, and accelerators provide resources and interfaces that interpret information, realize selected transitions, and render results through the E-CPU path.

The physical processor is a realizer of computation, not the definition of the computation.

**Any observed data can first be made mathematically addressable.** A finite
byte sequence is already an exact coordinate space over `Z/256Z`,
regardless of whether its format is recognized. A richer interpretation
requires a **declared, verifiable lens** and the original evidence; the same
bytes may support several mutually different structural meanings. E-CPU
retains the source identity, interpretation contract and observation
comparison separately, never assuming that representation proves the
sender's intent. [DATA-GROUND-001](docs/DATA_GROUND_001_ANY_DATA_MATHEMATICAL_INTERPRETATION.md)
implements this first general finite data-to-Ground path over native
`RepresentationRef`, `TranslationContract`, `ObservationComparison`
and verified computational-object page ranges. It admits exact integers,
UTF-8, rational JSON, raw bytes and validated IPv4 datagrams while refusing
unsupported meaning.

**Modern AI as Computational Grounds:** [AGA-001](docs/AI_COMPUTATIONAL_GROUND_ATLAS.md) maps 108 AI structures—from data preparation and neural graphs through training, inference, retrieval, agents, and recovery—into typed representations, transition relations, requested observations, navigational strategies, dependencies, and verification obligations. [Inspect the source-anchored atlas](mailcpu/ai_ground_atlas.v1.json) using `python -m mailcpu.ai_ground_atlas list`. This is a catalog of *Ground descriptions*, not automatic admission or a claim that all associated computations already execute natively. It is intended to prevent redundant model-by-model emulation by reusing and qualifying E-CPU's existing Ground, observer-host, and path machinery first.

**Ground reuse experiment (AGA-002):** [Direct semantic Ground instead of neural replay](docs/AI_GROUND_REUSE_AGA002.md) exhaustively checks two E-CPU 10,000-parameter neural realizations against the same finite Boolean Ground, then answers subsequent observations from the direct law with native observer receipts. This is a scoped equivalence experiment, not general neural inference or new runtime authority.

**Model weights as navigable Grounds:** [MWS-001](docs/MODEL_WEIGHT_GROUND_MWS001.md) defines an architecture's tensor parameter space independently of any executor, then treats a complete model snapshot as an exact, content-addressed point within it. E-CPU can navigate to chosen parameter coordinates through its existing computational byte store without materializing the whole network; equivalence or generative recovery requires separate proof. The [executable reconstruction demo](examples/model_weight_ground_demo.py) uses two 10,000-parameter neural realizations from E-CPU's existing weight-space compiler. The model-space description does not invent missing pretrained weights or confer neural execution authority.


**Generative model-weight Grounds:** [MWS-002](docs/GENERATIVE_WEIGHT_GROUND_MWS002.md) extends exact snapshot navigation to *reconstruction*: one known model point can be realized through an already admitted Structural Memory byte law, sparse bit-level edits against another snapshot, or a pinned tensor-coordinate permutation. Every route must reconstruct the same MWS-001 content identity and refuse contradictory byte evidence. This is a tested, evidence-scoped step toward model instances as navigable structures—not a claim that arbitrary trained weights can be inferred from their digest, that all models are compressible, or that tensor permutations automatically preserve model behavior.

**Pretrained neural realization Ground (HFG-002):** [Real Qwen3 layer via Hugging Face tensor ranges and E-CPU operators](docs/HF_PRETRAINED_LAYER_HFG002.md) extends HFG-001's logical model Ground with an independently checked full Transformer-layer numerical route. It reuses MWS-001 byte objects, Hypervisor-authorized Virtual Layer operators, and E-CPU's computation DAG. A pinned Qwen3-0.6B source range experiment runs in GitHub Actions; the code and earlier synthetic tests do not themselves prove hosted pretrained execution.

## Intention forms the E-CPU

**E-CPU is not fundamentally a machine that must keep running. It is a computational relationship made operational when an observer's intention selects and qualifies the available capacities needed to realize an observation.** A processor, service, memory, communication path or other observer-host may already possess a useful information relation before anyone calls it E-CPU. The intention describes the required result; the Ground preserves the distinctions and invariants that matter; an appropriate interpreter, operations and communication topology are then formed from the available relations. Different substrates can realize the same intention-relative computational identity without hosting one perpetual E-CPU process.

The inverse development direction is **intention → sufficient Ground → problem-formed interpreter → observer-host/path composition → admitted execution → independently checked observation**. A mathematical possibility is not automatically a physical realization or permission to execute: transport carriers need not compute, observed offers do not confer authority, and claimed effects require evidence. Continuously rejoinable sessions remain a valuable *optional* realization for problems needing retained state, not the foundation of computational identity. See [the INTENT-001 executable experiment](docs/INTENT_001_OBSERVER_FORMED_FABRIC.md) and [research issue #204](https://github.com/Kier73/E-CPU/issues/204) for the integrated experiment, [IPS-002](docs/INVERSE_ARCHITECTURE_SYNTHESIS_IPS002.md) for inverse route formation, and [VL-I PFI-001](https://github.com/Kier73/VL-I/blob/main/docs/PROBLEM_FORMED_INTERPRETER_PFI001.md) for generated observer-relative processors.

## Foundational proposition: the internet is the computer

**E-CPU is not intended merely to distribute computation across conventional machines. It aims to discover, describe, form, and navigate computation within the information architecture that already constitutes the internet.** Communication paths, signal propagation, ports, queues, observers, and interfaces can provide lawful information relations; a processor is one possible realizer, not a privileged computational unit. A path may carry unchanged digital bytes while transforming a physical signal under another Ground. The computational role is defined by an **admitted, observable relation**, not by whether the component looks like a CPU.

**Host = observer; path = architecture.** A host can be any identified locus with a declared information operation. Several such loci and their connecting media may jointly realize a Ground without any one locus containing the whole E-CPU. This does **not** imply that passive links run arbitrary programs, that signal distortion is automatically useful computation, or that public network infrastructure can be used without permission. Mathematical laws, measured physical effects, receiver authority, and recovery evidence must each be established independently.

**Capacity precedes recognition.** An information path may already support a realizable transition, observation, or retention relation before it has ever encountered an E-CPU description. E-CPU does not need to install itself everywhere to make that capacity mathematically addressable: it can discover a relation, construct its Ground, and navigate what its verified structure permits. Admission and authority determine which effects can be accepted; they do not create the underlying relationship. See [Latent Path Capacity](docs/LATENT_PATH_CAPACITY.md) for the formal distinction, communication-state model and executable experiment.

See [The Internet Is the Computer](docs/THE_INTERNET_IS_THE_COMPUTER.md) for the full proposition, its relation to E-CPU's existing observer/path systems, and a falsifiable experimental programme.


**CONTINUOUS-001: recoverable, navigable computational sessions.** A [revision-independent rejoin address](docs/CONTINUOUS_SESSION_OBSERVER_REJOIN.md) now binds the existing M3 session identity, artifact, state schema, and fixed quorum membership without tying the session to a process, network connection, backend fingerprint or mutable checkpoint tip. `mailcpu.continuous_session` navigates explicit observer-host offers over directed, typed, lease-bounded communication paths; receiver-local admission gates every selected host/channel. Attachment revalidates the route and calls M3 to verify the current quorum-supported checkpoint and M1 state. The experiment includes a process-restart rejoin test, not a claim of persistent uptime or cross-machine Internet availability. Automatic remote ingress, independent-host storage replication, dynamic membership and physical failover remain in active development.



[INTERNET-001](docs/INTERNET_NATIVE_GROUND_001.md) now exercises a pre-existing Internet service as an observer-host rather than installing an E-CPU worker there. An authorized Git service publishes a content-addressed object and conditionally advances a versioned ref; a separate observer checks the resulting state over HTTPS against externally retained exact identities. The experiment establishes a real **Internet service-state** relation, not arithmetic by routers or optical fiber, and does not treat logical-time navigation as instantaneous physical propagation.

[INTERNET-002](docs/INTERNET_NATIVE_GROUND_002.md) now exercises **native state-space navigation in an already-existing Internet Git service**: two controlled branches and a two-parent merge produce a small causal graph whose ancestry, divergence and unique merge-base operations are evaluated by GitHub itself. Nine live queries matched a separately written oracle, with all twelve commit objects and three reference heads checked; its read-only verifier and HTTP conditional-response probe explicitly separate real service computation, native protocol state and still-unverified physical-path transformations.

[INTERNET-003](docs/INTERNET_NATIVE_GROUND_003.md) tests a **real active intermediary as a retained computational Ground**, using separate Nginx origin and caching proxy processes over localhost TCP. A configured, pre-existing HTTP implementation provides gzip, conditional and byte-range responses, and keeps answering version-pinned observations after the origin is terminated (80/80 local checks). Changed-source observations refuse even when the proxy still serves an old representation. This is controlled protocol and intermediary computation, **not a WAN path measurement or passive-fiber logic**; a separate public-HTTPS conditional probe remains subject to hosted verification.

[PATH-GROUND-001](docs/PATH_GROUND_001_COMMUNICATION_OBSERVATION.md) is the first evidence-scoped test: a live local TCP path is observed as both byte-stream transport and bounded endpoint timing, while a separately labeled numerical transfer kernel exercises calibration and held-out refusal. This **does not** claim computation inside physical optical fiber; it supplies the observation contract for such a future experiment.

[TENSOR-PATH-001](docs/TENSOR_COMPUTATION_PATHS.md) extends E-GPU with bounded SIMT integer matrix tiles **and a distinct path-native tensor FIR operator**. A receiver-bound characterized path supplies each convolution response directly; SIMT is not invoked on that route. The synthetic reference proves the interface and verification logic, while physical in-medium tensor computation still requires independent instrument evidence. 
[PATH-GROUND-002](docs/PATH_GROUND_002_KERNEL_NATIVE_PROJECTION.md) tests a **real Internet-protocol information operation** on an owned local IPv4/UDP kernel stack: connected-socket source selection and queued-datagram retention. It compares a bypass with kernel filtering, recovers an affine Ground **from selected receiver observations**, checks a second socket topology, and navigates distant symbolic coordinates through E-CPU Structural Memory. Sender-side arithmetic, kernel selection, and Ground navigation remain separately attributed; this is not a remote internet/optical computation claim.

[PATH-GROUND-003](docs/PATH_GROUND_003_CONDITIONAL_HTTP.md) extends the Internet-computer experiment to a **real public HTTPS observer-host operation**: GitHub's representation-specific ETag comparison (`200 → 304 → 200` under an exact commit-pinned file and changed request predicates). E-CPU independently binds the selected response to the same Git content through raw HTTPS, Git blob SHA-1, and its existing immutable computational-object store. The state predicate is an Internet service operation, **not** an assertion of arithmetic inside passive fiber; full live conditional CI is pending.

[PATH-GROUND-004](docs/PATH_GROUND_004_IPV4_FORWARDING.md) tests a **native in-network transition** rather than a remote worker: Linux IPv4 kernel forwarding decrements packet TTL inside intermediate routing namespaces **without a MailCPU forwarding operator** (separate local E-CPU observer scripts measure real packet headers). Real `AF_PACKET` ingress/egress headers and receiver-side `IP_RECVTTL` observations are checked against **direct, L2-bridge, one-router and two-router** paths, making L2 transit without TTL transformation a necessary negative control; the existing `Law` navigator and native `ChannelObservation` distinguish mathematical Ground, route evidence, and a topology-dependent intention. Privileged multi-hop CI remains the proof obligation; this is not an optical or public Internet path claim.


[PATH-GROUND-005](docs/PATH_GROUND_005_AUTHENTICATED_ROUTER_WITNESS.md) adds a **cryptographically authenticated observer-host evidence path** atop native router before/after measurements: four distinct P-256 test leaf credentials and real MailCPU mutual-TLS sessions sign exact source/route/Ground/policy-bound raw capture commitments under receiver-issued challenges. The receiver independently revalidates the packets, provenance permission, and E-CPU `ObserverPathStage` receipts before admitting any observation. A signature identifies the test credential that made a claim; it is **not** proof of honest hardware measurement or independently administered Internet hosts. The credentialed multi-process Linux CI experiment is pending.

[PATH-GROUND-006](docs/PATH_GROUND_006_CAPTURE_TIME_ATTESTATION.md) moves from signing saved captures to **signing each raw Ethernet observation as it arrives at the actual observer's AF_PACKET receive boundary**. Receiver-preissued Ground/policy/challenge plans and sensor-held P-256 test keys create a chained, per-packet signed record. The receiver and an E-CPU-free auditor independently compare the 48 expected signatures against actual direct/L2/one/two-router traces and admit only fully verified native path witnesses. Its isolated Linux runner remains **one administrative and physical test environment**, not yet a demonstration of independently operated Internet sensors; privileged CI is the proof obligation.


## Foremost capability: form computational environments from available substrates

**E-CPU must be able to actively form the computational environment it needs, not only discover one that already exists.** At first bootstrap, no CPU, Python process, operating system, virtual machine, network protocol, or specific host topology is a privileged native substrate. A *host* is an identifiable observer: a locus with an admitted information relation. It may begin as a port, interpreter, queue, sensor, storage medium, process, service, or composition of such resources. The substrate provides mechanisms; E-CPU gives admitted mechanisms a computational organization.

The intended bootstrap is **observe → qualify → construct → admit → navigate → verify → retain/recover**:

1. **Observe and qualify** what the receiving environment can actually distinguish, transform, transport, retain, or interpret, including the bounds and provenance of those observations.
2. **Construct or impose a realization** when the environment supports it: install a bounded interpreter seed, configure an active port or queue, compose multiple observer-host fragments, or construct a higher-level operator from verified primitive transitions. Do not require a preinstalled E-CPU-specific handler.
3. **Admit locally, then navigate** the desired Ground and intention under receiver-owned authority. Route and capability advertisements do not grant execution rights; an authorized receiving environment may be configured to acquire new capabilities, but mere reachability or reception does not authorize deployment.
4. **Verify observations and preserve continuity** independently of placement. The Ground and intention identify the computation; implementations, physical work, costs, receipts, and recoverable state remain separately accountable as substrates change.

**Ground-native** refers to a valid operation or observation within an admitted Computational Ground. **Implementation-native** refers only to the mechanism presently used to realize it. E-CPU should make the first independent of the second: its Python package, MailCPU instruction machine, TLS fabric, and Hypervisor implementations are *realizers*, not requirements for every future E-CPU bootstrap.

This is a **foremost development objective**, not a claim that every receptive medium can execute code. A passive carrier may contribute transport; a writable medium may retain a formed seed; an active observer with sufficient permitted transitions may become an execution locus. Whether a resource can be formed into a given role must be demonstrated by actual transitions, bounded observation, and current authority. General active formation across arbitrary physical substrates remains in development.

See [Communication Host Model](docs/COMMUNICATION_HOST_MODEL.md), [Computational State-Space Architecture](docs/COMPUTATIONAL_STATE_SPACE_ARCHITECTURE.md), and [Substrate-adaptive bootstrap](docs/SUBSTRATE_ADAPTIVE_BOOTSTRAP.md).

[Observer-host path cohesion](docs/OBSERVER_HOST_PATH_COHESION.md) now connects existing channel observations and native observer receipts into an independently checked path witness. Passive carriers cannot silently claim to transform information; observer-host transitions require exact representation and Ground continuity plus receiver-owned admission. This is path-level evidence, not a new authority or a claim of physical-host independence. The SAB-008 and SAB-009 experiments extend this direction through Ground-native realization and authorized code-and-data host formation.


## The intention

A finite description can denote a very large or infinite family of states and operations. A recurrence can describe a sequence without storing each term. A transition grammar can describe many possible paths without enumerating them. A mathematical domain can be represented through its laws and supported observations.

E-CPU aims to hold and navigate this described computational capacity.

An input gives a Ground context. Its language, structure, values, assumptions, and intention constrain which part of the described space is relevant. An observer then specifies what information is sought. E-CPU selects how to obtain it: direct evaluation, inverse navigation, indexing, transformation, or traversal of an explicitly described path.

The intent is not to materialize every possible state. It is to describe the laws and representations that make states addressable, then resolve the state or information required by a request.

This goal is relative to the computational languages and Grounds admitted by E-CPU. Expanding that descriptive and operational capacity is active development.

## The computational model

A Computational Ground can be described as:

\[
G=(\mathcal L,\Sigma_G,\Delta_G,\mathcal I_G,\mathcal O_G,\mathcal C_G,\mathcal E_G,\nu_G)
\]

- \(\mathcal L\): description and representation language.
- \(\Sigma_G\): state-space denoted by valid descriptions.
- \(\Delta_G\): admitted transformations and transitions.
- \(\mathcal I_G\): invariants and admissibility rules.
- \(\mathcal O_G\): observers, output projections, and predicates.
- \(\mathcal C_G\): navigation, realization, communication, and verification costs.
- \(\mathcal E_G\): evidence supporting the Ground and its operations.
- \(\nu_G\): Ground version and schema identity.

An interpreted input constrains that space:

\[
\Sigma_{G|x,c}
=
\{s\in\Sigma_G\mid D_x(s)\land\mathcal I_G(s)\}.
\]

A request identifies the relevant system Ground, computational Ground, description, intention, state reference, logical coordinate, and requested observation. Its semantic identity remains independent of the physical host selected to realize it.

For the complete model, the reading order and mathematical connections, see [Computational State-Space Architecture](docs/COMPUTATIONAL_STATE_SPACE_ARCHITECTURE.md) and [System Mathematical Map](docs/SYSTEM_MATHEMATICAL_MAP.md).

## Observation, execution, and time

Observation can be computation.

A passive read retrieves a value that is already materialized. An active observation can evaluate a law at a coordinate, resolve a symbolic reference, project a representation, test a predicate, or find the coordinate whose state satisfies a requested condition.

For an admitted Ground:

\[
y=\operatorname{Observe}(G,D,\mathcal O,t).
\]

The answer may be obtained without generating every earlier state. When a direct law or inverse exists, the system can navigate to the requested information and verify it. When no direct method applies, it can traverse an explicitly described path using the declared resource policy.

Logical time, scheduler ticks, physical duration, and causal order are kept as distinct coordinates. Navigation is about reaching a state or observation in the described computation, not assuming that all forms of time are interchangeable.

A sensor stream or communication path can be treated as an observed orbit of a particular transform system. E-CPU now has an initial implementation that carries quorum-approved samples and temporal provenance into a candidate Ground, then selects, navigates, and verifies the requested observation through receiver-side authority. Its latency is represented as a vector of comparable clock relations, not forced into one duration. See [Observed Orbit Pipeline](docs/OBSERVED_ORBIT_PIPELINE.md).

"In transit" refers to the logical path through which descriptions, state references, observations, transformations, and evidence move. Communication carries the information; observer-hosts on the path interpret it or perform admitted transitions.

## The computational path

```text
External input or observation
            |
            v
Ground and context interpretation
            |
            v
Constrained computational state-space
            |
            v
Requested observation / intention
            |
            v
Navigation strategy selection
   direct | inverse | index | transform | traverse
            |
            v
E-CPU realization path
            |
            v
Verification and accepted observation
            |
            v
Output translation to the connected system
```

A single path may use several logical hosts. One can translate an input, another resolve a generative state, another evaluate a transition, and another verify or render the result. The host that performs a transition is not required to own the computation's full semantic identity or history.

## What E-CPU is being built from

The current architecture already contains several important components of this model.

| Architectural role | Existing E-CPU systems |
|---|---|
| Generative state descriptions | Structural Memory, law certification, Virtual Grounds, Composed Virtual Grounds |
| Semantic identity and context | Computational addresses, Ground fingerprints, typed workloads, content-addressed objects |
| Observation | Observer contracts, observer receipts, contextual orbit projections |
| Typed observation intake | Resolver, timing, delay, temporal and phase observation records; quorum-gated event admission |
| Intent and Ground-family hints | Structural intent embeddings and advisory generator-family suggestions, checked by deterministic law recovery |
| Ground comparison and composition | Composed Virtual Ground projections and predictive description selection against independent observations |
| State-space navigation | Direct orbit evaluation, inverse navigation, process path indexes, formal reachability |
| Description and operation translation | Semantic translation contracts, MailCPU program dataflow compilation, VGI task compilation |
| Description selection | Predictive description selection over independently observed composed states |
| Path selection | Evidence-path resolver, computational fabric route resolver, placement profiles |
| Realization | Virtual Layer, Transit workers, E-GPU methods, VGI interpreter, MailCPU runtime |
| Continuity | Persistent computational sessions, Structural Memory revisions, recovery lineage, transferable execution claims |
| Verification | Paired observation checks, independent operation oracles, receipts, replay and quorum evidence |

These components have distinct semantics and state owners. Their value comes from composing them through explicit identities and contracts, not from forcing every domain into one instruction set.

## In development

E-CPU is not being defined as a conventional VM with a distributed scheduler added around it. MailCPU's instruction machine remains one concrete execution environment and one way to represent and realize selected work.

The larger architecture is in development through these connected efforts:

- **Ground language:** a shared versioned description for domains, state variables, transformations, observers, invariants, costs, and evidence, while retaining domain-specific mathematics.
- **Input and output interpretation:** typed translators for programs, equations, signals, model requests, tensors, and application state.
- **Ground construction:** integrate observation-driven induction, counterexample refinement, and explicit known, unknown, and ambiguous transitions.
- **Observation and intention:** express requests for target states, outputs, predicates, comparisons, and logical-time coordinates.
- **Navigation strategy selection:** select direct evaluation, inversion, indexing, formal analysis, or explicit traversal based on the admitted Ground and requested observation.
- **Compositional verification:** verify complete paths across translations, state transitions, observers, and hosts.
- **Network-wide semantic resolution:** locate compatible Grounds, state descriptions, observers, translators, and physical realizers across the fabric.
- **Active host formation (foremost):** derive suitable execution/observation roles from qualified primitive operations; construct needed E-CPU runtime fragments on authorized receiving surfaces, then independently validate, repair, and recover the formed environment.
- **General model computation:** develop actual tensor and model-operation Grounds, including stateful model sessions, then demonstrate useful workloads through E-CPU.

The current foundations are substantial, but the complete general description-to-observation path is still in active development. Current implementation and evidence are distinguished in the specifications rather than implied by the architectural goal.

## A concrete executable starting point

The repository retains an importable Python package named mailcpu. It currently provides deterministic instruction semantics, HeadlessOS, typed workloads, Structural Memory, contextual navigation, computational sessions, Transit and the authenticated computational fabric.

For example, the package can assemble a small instruction description:

```python
from mailcpu import assemble

program = assemble(
    """
    SET left, 19
    SET right, 23
    ADD answer, left, right
    HALT
    """
)
```

This is one current computational representation inside E-CPU. The architectural goal is to make such descriptions one member of a much wider family of Grounds and navigable state-spaces.

### Run and verify

```sh
python -m mailcpu demo
python -m pytest
python scripts/verify_invariants.py
python scripts/verify_repo.py
```

The package and CLI remain under active development. See [docs/README.md](docs/README.md) for specifications, experiments, and executable examples.

## Repository guide

- [Computational State-Space Architecture](docs/COMPUTATIONAL_STATE_SPACE_ARCHITECTURE.md) — intended model, mathematical structure, existing mechanisms, development sequence, and first experiment.
- [System Mathematical Map](docs/SYSTEM_MATHEMATICAL_MAP.md) — mathematics already represented across the codebase.
- [State-Space Navigation](docs/STATE_SPACE_NAVIGATION.md) — symbolic capacity, finite paths, and logical-time navigation.
- [Operational Semantics and State-Space](docs/OPERATIONAL_SEMANTICS_AND_STATE_SPACE.md) — portable operation meaning and contextual realization.
- [Semantic Translation](docs/SEMANTIC_TRANSLATION.md) — preservation of observations between representations.
- [Structural Memory](docs/STRUCTURAL_MEMORY.md) — admitted generative descriptions and state reads.
- [LENS-001: reversible observation-frame Grounds](docs/LENS_GROUND_001.md) — opt-in framed affine reconstruction, certification, inverse navigation, and revision-pinned receipts.
- [Predictive Description Selection](docs/PREDICTIVE_DESCRIPTION_SELECTION.md) — evaluate competing state descriptions against observed system states.
- [Computational Addressing](docs/COMPUTATIONAL_ADDRESSING.md) — semantic requests separated from physical placement.
- [Communication Streams as Computational Substrate](docs/COMMUNICATION_STREAM_COMPUTATION.md) — observer-hosts and in-transit operations.
- [Computational Fabric](docs/COMPUTATIONAL_FABRIC.md) — authenticated paths and remote realization.
- [Persistent Computational Sessions](docs/COMPUTATIONAL_SESSIONS_AND_STATE.md) — state continuity and continuation.
- [VGI Virtual Layer](docs/VGI_VIRTUAL_LAYER.md) — one hosted signal-state Ground and interpreter.
- [Neural Graph Bridge](docs/NEURAL_GRAPH_BRIDGE.md) — project HFR-002 typed neural topology into MailCPU's content-addressed computation DAG without loading tensor payloads.

## Development principle

Prefer the smallest verified capability that increases the amount of computation E-CPU can describe, interpret, navigate, or observe. Keep domain meaning separate from physical placement. Measure actual work and communication costs. Preserve ambiguity when evidence is incomplete. Compose new mechanisms from existing Ground, observer, translation, navigation, realization, and recovery contracts.

## Constructive neural weight realization

A bounded, no-training construction now lives in [docs/WEIGHT_SPACE_PROGRAMMING.md](docs/WEIGHT_SPACE_PROGRAMMING.md) and [mailcpu/weight_space.py](mailcpu/weight_space.py). It compiles two-input XOR/AND into two distinct 10,000-parameter ReLU architectures (2–85–112–1 and 2–17–254–21–1), records active versus total parameters, and demonstrates a two-weight XOR-to-AND intervention in both layouts. The tests compare them with the E-CPU reference and queue interpreters and use the existing semantic-translation contract for per-case exact checks. This is a finite constructive proof-of-mechanics, not a general neural compiler or a training replacement.

## Finite-state transition neural synthesis

[The finite transition compiler](docs/FINITE_TRANSITION_SPACE.md) converts complete Boolean transition tables and typed Boolean expression DAGs into exact ReLU weights, produces an executable MailCPU reference program from the same finite table, and supports digest-bound local transition interventions. It includes a liveness-compacted DAG compiler that prunes input and intermediate features no longer needed by future expressions. It is exercised on a reset-dominant two-bit counter and compared against VGI and both MailCPU execution backends.

## Stateful transition runtime

[The stateful transition runtime](docs/STATEFUL_TRANSITION_RUNTIME.md) executes typed Boolean transition programs through their liveness-compiled ReLU realization while maintaining live state, logical ticks, model revisions, and a SHA-256-linked event history. It preserves state across compatible model revisions and verifies snapshots by replaying every recorded step and revision.

## Stateful transition trajectory bridge

[The trajectory bridge](docs/STATEFUL_TRANSITION_TRAJECTORY.md) exports stateful step/revision events through the existing indexed `TrajectoryWriter`, projects the same events into E-CPU's `EventJournal`, and restores the runtime only after validating the trajectory receipts, manifest digest and original runtime replay chain. It also supports verified logical-time seek across same-tick model revisions.


## Sparse finite-transition execution

[The sparse transition realization](docs/SPARSE_TRANSITION_REALIZATION.md) converts an existing exact table, direct-DAG, or liveness-compacted ReLU transition model into a digest-bound sparse weight representation. It skips zero-weight products while preserving the dense source model and declared architecture as provenance. The E-CPU transition tests exhaustively compare dense and sparse executions across the counter, a one-row revision, and a deterministic generated Boolean program corpus. Stored parameters and structural operation counts are exposed separately; hardware speedup and runtime savings remain to be measured.
