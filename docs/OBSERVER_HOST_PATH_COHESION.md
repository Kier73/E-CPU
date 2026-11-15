# Observer-host and communication-path cohesion

## Normative interpretation

The [Communication Host Model](COMMUNICATION_HOST_MODEL.md) defines the **host as an identifiable observer**, not as a processor or a location. A passive substrate edge may carry information without being an observer; a port, queue, path segment, sensor or decoder becomes an **observer-host** when it has a declared information-operation relation. Transformation, execution, persistence, coordination, and authority are **additional roles**, not automatic consequences of observation. One physical process may contain many logical hosts; many physical realizers may continue one logical host through evidence-bound recovery.

The path is an architecture in its own right: a directed composition of *carrier edges* and *operational loci*. The same semantic intention and computational Ground can reach its result through different path topologies, while actual route evidence, admission, budgets, causal order and realization identities remain separately recorded.

## New executable evidence adapter

`mailcpu.observer_path_evidence` composes **existing native types** rather than creating another scheduler, transport, Ground, or authority:

| Stage | Native representation | Meaning | Must not be inferred |
|---|---|---|---|
| Carrier | `substrate_bootstrap.ChannelObservation` | A candidate directed edge with lease, representation type and bounded payload | The channel delivered a frame; a passive wire computed |
| Observer | `observer_orbit.ObserverContract` and `ObserverReceipt` | An identified locus carried out a bounded observation | The receipt authenticates its author; observation implies execution |
| Transform | The same native observer evidence, plus before/after subject-state digests | Content changed through a declared locus and operation | The declared transform was authorized or mathematically correct |
| Whole path | `VerifiedObserverPath` | Receiver-verified adjacency, representations, Ground/context continuity and evidence identity | Physical host separation, signatures, independent failure domains or real-time liveness |

A route stage must retain exact representation identity through passive carriers; only a *local observer-host operation* may claim to transform it, and that requires exact before/after content digests. Each active stage keeps its own native observer receipt and distinct operational identity. Every observer must refer to the same computational-Ground representation and context, but the incoming/outgoing source representations may change at admitted transformations.

**Authority remains receiver-local.** `verify_observer_path` *requires* trusted callback functions for delivery and observer admission, each returning literal `True`. They are never serialized with the path witness, and a SHA-256 digest never supplies permission. A real host must implement those callbacks using `ReliableChannel`/mTLS transport and hypervisor/Virtual Layer or native authority evidence; a test callback does not do so. A receiver-supplied `receiver_policy_digest` identifies the verifier policy used for the decision; it does not make that policy or its callback available to senders. Two receivers may accept the same mathematical Ground through different policies and will produce different path-witness digests. The adapter does not send, execute, admit, or checkpoint requests by itself.

This separation permits a path's observational state to be used in route planning without laundering untrusted advertisements into capabilities. It also provides a place to account for path components that matter semantically, such as a bounded decoder that changes representation, an active queue that retains/acknowledges a frame, or a verifier that checks a prior transform. Paths can host meaningful operations without pretending a passive carrier is a CPU.

## Current E-CPU coverage (November 15, 2026)

- `substrate_bootstrap` constructs a bounded local environment using observed resource contracts, explicit receiver bindings and policy, and directed carriers.
- `observer_orbit` provides native, versioned observer contracts and receipts with separate subject, interpretation (Ground), context, temporal and evidence fields.
- `transit_path_modes` and `transit_path_binding` observe real session queues, sensor samples and service-time relations.
- `computational_fabric` and `evidence_path_resolver` use authenticated peer knowledge and typed route evidence, not rights grants.
- `virtual_layer`, `navigation_admission` and the Hypervisor own capability and state admission; `transit_session` and recovery-lineage authorities own durable execution and replay.
- SHN-001/002 test constrained nested port-host paths; SAB-008–012 test the more general qualification, formation, composition and recovery of operational loci. These **research branches remain separate** until their native integration gates are verified.
- VGI geometry-first PRs #24–31 are now merged to VGI `main`. They enable operator-graph structure discovery and independently reconstructible mathematical Grounds. E-CPU GEOMETRY-TRANSIT PRs #145–147 still need actual hypervisor/Transit recovery CI.

## Physical machine frontier

When native machine access becomes available, record distinct **logical host IDs**, **placement nodes**, **failure domains**, **interface/transport identities**, **causal frames** and **authority decisions**. Then compare a single-machine two-process route with a physically distributed route under otherwise identical Ground and intention. Require recovered receipts, channel acknowledgements and trusted host/membership evidence to support stronger claims. The route witness is valuable evidence for that test; it is not a substitute for it.

## Negative conformance

The focused test requires refusal for expired/incorrect carrier leases, unauthorized stage callbacks, incorrect direction, representation conversion on a passive edge, inconsistent Ground or observer revision, altered exact subject-state evidence, duplicated observer receipts, broken adjacency, oversized payloads, and modified receipt hashes. A path with only a carrier remains a carrier-only path; it is not labeled as executing computation.