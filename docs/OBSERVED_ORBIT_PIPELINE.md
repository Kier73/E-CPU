# Observed Orbit Pipeline

## Purpose

This specification connects the existing observation, Structural Memory, Virtual Ground, predictive selection, intention, navigation, Hypervisor, and host mechanisms into one testable path:

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

The pipeline integrates existing E-CPU mechanisms. It does not create a second law certifier, a second authority model, or a second host-execution mechanism.

The first implementation has two realizations of the final stages:

- a single-Ground path, built from a quorum-authorized integer observation stream and realized through the receiver's HeadlessOS Hypervisor;
- a composed-Ground path, where an existing predictive description-selection report selects a composed state description and the receiver realizes that selected composition at a requested scheduler coordinate.

These are executable vertical slices, not a claim that arbitrary sensor languages or every transform system are already automatically inducted.

## 1. The orbit belongs to a transform system

For one Ground \(G\), let its admitted transition be \(T_G\), its state at an admissible coordinate \(t\) be \(s_t\), and its observer be \(\mathcal O_G\):

\[
s_{t+1}=T_G(s_t), \qquad o_t=\mathcal O_G(s_t).
\]

The orbit is not merely a sequence of values detached from the system that produced them. It is a contextual relation among:

- the system Ground and its identity;
- the Computational Ground that gives the observed values meaning;
- the admitted transition description;
- the observer and requested projection;
- the time coordinate and the rule relating that coordinate to the state;
- the evidence that supports the observation and the Ground.

A sensor stream or communication path can expose samples of this orbit. The stream itself does not automatically prove the transition law. It provides observations from which a candidate law may be proposed, withheld samples against which it can be tested, and temporal/source evidence that can be carried with the resulting description.

The implementation therefore distinguishes the observed stream from the admitted generator. The former records what was received and when; the latter describes the transform that passed Ground certification and trusted admission.

## 2. Observation: capture authorized samples as a trace

ObservationTraceBuilder consumes an existing ObservationConsensus. It does not accept raw measurements as if they were already trusted.

For each requested event coordinate it:

1. checks the current consensus status;
2. finalizes an event only after it reaches quorum;
3. retrieves the authorized representative observation;
4. extracts one explicitly named integer register;
5. retains the exact canonical observation payload, source set, dissenting and missing sources, and consensus-decision digest;
6. optionally records typed source and receiver TemporalFrame values.

The builder produces an ObservedOrbitTrace. Its samples have two intentionally separate coordinates:

| Coordinate | Meaning |
|---|---|
| logical_time | The source/event coordinate supplied to observation consensus |
| coordinate | The zero-based position in the strictly ordered, accepted sample sequence |

The ordinal coordinate is the argument used by the first Structural Memory trace-recovery ABI. It is not an assertion that the underlying sensor's event clock advances by one at each observation. Irregular logical times remain present in the trace and its digest.

The trace requires contiguous ordinal coordinates, strictly increasing event logical times, one observation kind/register, source membership in the authority policy, and a non-dissenting representative source. Observed and missing sources must partition the configured source set. It retains at least the configured source quorum for every accepted sample.

Consensus checks the configured source identifiers and quorum. It does not, by itself, cryptographically authenticate a remote sender. Authentication of the source identity belongs to the trusted ingress/transport mechanism; the trace digest binds the identity and payload that the receiver admitted, but is not a signature.

ObservedOrbitTrace.to_dict() and from_dict() preserve and recheck the complete sample identity, including the temporal evidence digest.

## 3. Ground construction: infer, withhold, certify, then admit

ObservationGroundBuilder.propose() uses the registry's existing StructuralMemoryRegistry.propose_trace() method. The caller chooses a training prefix; the remaining suffix is passed as withheld observations.

\[
X=(x_0,\ldots,x_{n-1})
\quad\Rightarrow\quad
X_{\mathrm{train}}=(x_0,\ldots,x_{k-1}),
\quad
X_{\mathrm{holdout}}=(x_k,\ldots,x_{n-1}).
\]

The existing law-recovery and verification mechanism determines whether an admitted generator family explains the samples. A fitted description or an unsupported transition family is not promoted by this adapter.

The proposal's Structural Memory context includes a digest-bound observation binding with:

- the complete observed trace digest;
- stream identity, observation kind, and extracted register;
- sample count and event-time range;
- allowed source identities, quorum, and strictness;
- the digest of source/receiver temporal evidence.

The proposal remains staged. ObservationGroundBuilder.admit() calls the existing registry admission method, which re-verifies the proposal, checks the expected revision, and requires the trusted host-supplied admission policy to return literal True. Only then does it create a VirtualStructuralMemoryRef, ContextualOrbitAddress, and matching ObserverContract.

The resulting GroundBinding retains the admitted StructuralMemoryVersion and the original ObservedOrbitTrace. Structural Memory stores the generative law, context, revision, witnesses, and certificate; the trace remains the detailed observation/provenance record. The exact trace digest is bound into the Ground context so that the law cannot be quietly reused as though it came from a different stream.

## 4. Description selection: compare admitted Grounds, not guesses

The existing PredictiveCandidatePoolBuilder and PredictiveDescriptionSelector remain the selection mechanism.

select_composed_description() builds the existing one-factor candidate pool from already-admitted component revisions, evaluates those candidate descriptions against independent PredictiveGroundObservation values, and returns:

- the bounded candidate pool;
- its chronological development, validation, and test evaluations;
- the non-authoritative ranking and Pareto frontier;
- the selected candidate object.

A candidate is a complete pinned ComposedVirtualGroundAddress, not a class label or a free-floating parameter guess. The selection report does not admit new component laws and does not authorize execution. The selected candidate is carried directly into VerifiedComposedGroundRealizer, which checks that the navigation plan cites the exact selection report and intention digest before asking the Hypervisor to act.

For one newly constructed scalar Ground there may be only one certified description in the current candidate set. In that case selection is trivial; the full predictive selection machinery becomes useful when competing admitted descriptions or component revisions exist.

## 5. Intention interpretation: name the requested observation

interpret_intention() accepts a finite structured mapping. IntentPrototypeModel produces a deterministic structural embedding and an advisory domain prediction.

The interpretation is content-addressed. Its metadata explicitly records that its authority is advisory. It can help organize a request such as:

- observe a value at a requested scheduler coordinate;
- find the coordinate producing a target value;
- observe a complete composed state;
- evaluate a predicate or compare two descriptions.

It does not certify a Ground, choose its transition law, grant host rights, or invoke an operation.

The navigation plan binds to the digest of the intention interpretation. The receiver Hypervisor still performs its own classification and policy arbitration from the concrete operation, resource, payload, required rights, and rights actually held by the requesting process.

## 6. Navigation strategy: declare the method before realizing it

NavigationPlan is a typed, non-executing request. The first vertical slice provides:

- Direct coordinate: address the absolute scheduler tick; the contextual address converts it into a base-relative orbit offset.
- Inverse value: ask the admitted integer generator for a coordinate producing the requested value; the existing navigator forward-verifies the candidate before observing it.

A scalar plan can bind an intention digest. A composed plan also binds the exact predictive selection report digest. A composed description-selection report cannot be attached to a scalar realizer, and a scalar plan cannot silently consume a composed candidate.

The navigator's declared work profile and evidence remain visible in its output. The direct and inverse methods use existing admitted-law and receipt paths; unsupported inverse families refuse instead of silently falling back to an unbounded scan.

## 7. Verified realization: the receiver remains the authority

### Single Ground

VerifiedGroundRealizer accepts a HeadlessOS, a process identifier, the pinned contextual address and observer contract, and the navigation plan.

It first confirms that the registry passed to the realizer is exactly the receiver OS's own Structural Memory registry. It then derives a capability resource from all three of:

\[
(\text{memory identity},\text{revision},\text{Ground context digest}).
\]

The resource is therefore not a generic right to read every revision or context under one memory name.

The realizer invokes HeadlessOS.hypervisor_dispatch() with a read right on that resource. The OS constructs the request using the requesting process's actual capabilities. The navigation handler is invoked only when the Hypervisor returns ALLOW. REVIEW and DENY return without the Ground read.

After dispatch, the realizer independently checks:

- the Hypervisor decision is ALLOW;
- the exact observer receipt verifies against its observer contract;
- the Structural Memory read receipt matches the pinned memory, revision, law digest, certificate digest, and context digest;
- the projection retains the requested system and Computational Ground identities;
- inverse navigation, when selected, agrees with the realized coordinate and value.

The returned VerifiedGroundRealization binds the decision receipt, observer and Structural Memory evidence, address, plan, value, host identity, and local host duration into one content-addressed receipt.

Observer and Structural Memory digests establish content identity and contract consistency. They are not remote signatures, and the word verified here means that the receiver checked the declared contract, pinned revisions, local authority decision, and returned evidence. Remote observer authenticity continues to depend on the existing authenticated host/fabric mechanisms.

### Composed Ground

VerifiedComposedGroundRealizer consumes the explicit DescriptionSelectionStage, the IntentionInterpretation, and a direct-coordinate NavigationPlan. It moves the selected composition to one common scheduler coordinate while preserving each component's pinned law and context.

Its read resource identifies the exact composition: system and base Ground, Computational Ground, state schema, template, scheduler, extensions, and each component's memory/revision/spec/certificate/context identity. The resource intentionally does not include the target coordinate, so a host can be granted read access to the one selected composition at its navigable coordinates without gaining access to another description.

The receiver Hypervisor must authorize that resource. Only the ALLOW handler invokes ComposedVirtualGroundNavigator. The realizer then creates an observer contract for the exact composed address and a receipt over the complete state projection, including its component evidence. It checks that the returned component receipt set matches the selected component revisions. The receipt digest binds this local result to its contract; it does not turn the local observer into a cryptographic identity claim about a remote host.

This closes the path from selected description to verified composed realization without turning the selector into authority.

## 8. Latency is a temporal vector carried by the path

A single scalar called latency hides important distinctions. E-CPU already has typed temporal domains; the pipeline keeps them separate.

For a source frame \(\tau_s\) and receiver frame \(\tau_r\), TemporalDelta.between() reports the comparable coordinates:

| Temporal domain | What it can establish | Comparison rule |
|---|---|---|
| Monotonic elapsed | Local processing or transport duration | Same actor and monotonic segment only |
| Wall time | Local calendar estimate | Same actor only; not causal proof |
| Causal stamp | Before, after, equal, or concurrent relation | Vector-clock comparison across actors |
| Scheduler | Logical progress in a named runtime | Same scheduler identity |
| Event coordinate | Event-stream progress | Same actor and non-regressing event values |
| Chemical time | A selected process' accumulated \(\tau\) | Same actor |
| Chronon phase | Phase at the two observations | Preserve endpoints; do not infer elapsed duration |

A missing duration is not zero. Two hosts' monotonic clocks are not directly subtractable. Wall-clock difference is not a substitute for causal order. A scheduler tick is not a nanosecond.

TemporalPathTrace carries a sequence of named stage observations and their typed frames. Its intervals are recomputed on serialization restoration and covered by its digest. It can represent stages such as:

\[
\text{source observation}
\rightarrow
\text{transport arrival}
\rightarrow
\text{receiver admission}
\rightarrow
\text{Ground construction}
\rightarrow
\text{description selection}
\rightarrow
\text{navigation}
\rightarrow
\text{realization}.
\]

The first implementation automatically measures the local receiver realizer with a same-actor monotonic clock. Earlier and later path stages can be appended by the corresponding source, transport, receiver, or observer host. This avoids manufacturing a single end-to-end duration from incomparable clocks.

A useful operational latency model is therefore a vector:

\[
\Lambda(p)=
\left(
\Delta_{\mathrm{mono}}^{(a,s)},
\Delta_{\mathrm{wall}}^{(a)},
\preceq_{\mathrm{causal}},
\Delta_{\mathrm{scheduler}}^{(q)},
\Delta_{\mathrm{event}}^{(a)},
\Delta_{\mathrm{chemical}}^{(a)},
\phi_{\mathrm{chronon}}^{\mathrm{start,end}}
\right).
\]

Only explicitly comparable components may be aggregated into a scalar cost. The path keeps its other temporal coordinates as evidence.

## 9. Memory is both generative structure and observed history

Two forms of memory cooperate:

**Generative memory** retains the admitted transition law, parameters, context, revision, certificate, witnesses, and read receipts. This describes how to reconstruct a state at a coordinate.

**Observed history** retains the sensor/event samples, exact source observations, quorum decisions, event logical times, and any typed source/receiver temporal frames. This records what the system actually observed along the communication path.

The trace digest is embedded in the Ground context. The Structural Memory certificate is attached to the exact Ground specification and context. The observer receipt is attached to the resulting projection. Together they connect observed history, generative description, and verified output without requiring every possible state to be stored.

The intended relationship is:

\[
\underbrace{X_{\mathrm{observed}}}_{\text{what was received}}
\quad\xrightarrow{\text{induction + witnesses}}\quad
\underbrace{G_{\mathrm{admitted}}}_{\text{what transform is supported}}
\quad\xrightarrow{\text{coordinate + observer}}\quad
\underbrace{o_t}_{\text{what was verified}}.
\]

A stream can therefore serve as a carrier of information about a Ground's orbit while the Ground remains the description that makes that orbit navigable. The communication path is not merely a place where bytes wait; it can host observations, temporal relations, and admitted transformations. But a stream is not automatically its own law: source authority, temporal identity, and withheld verification are needed before observations can become a reusable Ground.

## 10. Current implementation and active development

The implementation lives in mailcpu/observed_orbit_pipeline.py and is exported from mailcpu.

The implementation now demonstrates:

- quorum-authorized integer-register extraction from typed sensor observations;
- an immutable, round-trippable observation trace with source and temporal provenance;
- trace-bound, witness-tested Ground proposal and trusted admission;
- binding into the existing system/Virtual Ground/Computational Ground contextual address and ObserverContract;
- advisory intent interpretation;
- existing predictive selection of composed descriptions;
- direct and inverse scalar navigation;
- direct navigation of a selected composed description;
- receiver-local Hypervisor authorization, exact read capability scope, component/read receipts, and observer verification;
- temporal path serialization and per-domain latency calculations.

The following capabilities remain in development:

- induction of vector, matrix, tensor, symbolic, and general transition-system Grounds from richer observation languages;
- interventions and explicit recording of unknown or ambiguous transitions;
- source/receiver clock synchronization models where a physically meaningful cross-host duration is required;
- automatic composition of observation extraction schemas with Ground language discovery;
- multi-hop realization of the entire six-stage pipeline across the computational fabric, with each hop contributing its own typed timing and admission evidence;
- non-integer inverse navigation and richer predicate/constraint queries over composed Grounds;
- long-lived storage, compaction, replay, and revalidation of large observed-orbit traces;
- making predictive selection a reusable stage over more than the current composed-Ground candidate family.

The present implementation is intentionally strict about what it claims: an authorized trace can support a recoverable law; a certified law can be admitted under host policy; a selected composed description can be realized at a coordinate; and the result can carry evidence. It does not infer an unrestricted model of the physical world from any arbitrary stream.
