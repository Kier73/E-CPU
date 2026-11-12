# E-CPU

**A computational state-space architecture for describing, interpreting, and navigating computation.**

E-CPU is being developed around a different centre of computation: the semantic state-space described by an input, the Ground that gives it meaning, and the observations and transformations needed to reach a requested result.

The goal is for computational meaning, logical state, and accepted results to belong to E-CPU. Connected computers, processors, models, services, and accelerators provide resources and interfaces that interpret information, realize selected transitions, and render results through the E-CPU path.

The physical processor is a realizer of computation, not the definition of the computation.

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
- [Predictive Description Selection](docs/PREDICTIVE_DESCRIPTION_SELECTION.md) — evaluate competing state descriptions against observed system states.
- [Computational Addressing](docs/COMPUTATIONAL_ADDRESSING.md) — semantic requests separated from physical placement.
- [Communication Streams as Computational Substrate](docs/COMMUNICATION_STREAM_COMPUTATION.md) — observer-hosts and in-transit operations.
- [Computational Fabric](docs/COMPUTATIONAL_FABRIC.md) — authenticated paths and remote realization.
- [Persistent Computational Sessions](docs/COMPUTATIONAL_SESSIONS_AND_STATE.md) — state continuity and continuation.
- [VGI Virtual Layer](docs/VGI_VIRTUAL_LAYER.md) — one hosted signal-state Ground and interpreter.

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

## Stateful transition checkpoints

The indexed trajectory bridge exposes [verified state checkpoints](docs/STATEFUL_TRANSITION_TRAJECTORY.md#state-checkpoint-lookup) at logical time coordinates. A checkpoint binds the state vector to the active transition program/model revision and both runtime-event and trajectory receipt identities. It is a time-navigation locator, not a mutable runtime restore; full replay remains available through `restore_stateful_transition_trajectory`.
