# Evidence-Indexed Path Resolver

## Purpose

`EvidencePathResolver` composes exact, evidence-bearing translation edges
into a bounded route between two content-addressed representations. It is a
different level of navigation from `ContextualNavigator` and
`NavigationCoordinator`:

- contextual navigation finds a path through the states of one described
  process;
- formal navigation reasons about reachability, invariants, causal order, and
  representation equivalence;
- the evidence-path resolver finds a sequence of declared representation
  translations that connects one representation identity to another.

It does not execute any edge, reserve resources, change state, or issue a
capability. Its output is a non-authoritative route proposal.

## 1. Evidence edge

An `EvidencePathEdge` contains:

- a `TranslationContract` that identifies exact source, target, mapping,
  observation projection, context, preconditions, invariants, resource bounds,
  receiver-side authority requirements, and effect/replay class;
- a successful `ObservationComparison` bound to that exact contract and one
  concrete case;
- an explicit non-negative cost vector whose metric names and units are
  preserved; and
- optionally, receiver-committed `TransitTranslationEvidence`,
  `TransitOracleEvidence`, and the raw observed effect.

Generic translation edges may use paired-case evidence. A route request can
require the stronger `INDEPENDENT_ORACLE` tier. When an edge is ingested from
a `HypervisorExecutionResult`, `from_execution_result` checks the committed
translation and oracle records against the result before storing the edge.
Its stored raw effect allows those observation and digest bindings to be
rechecked when a catalogue snapshot is restored.

Every edge is content-addressed from its full contract, comparison, evidence,
and costs. The graph connects edges only when the complete target
`RepresentationRef` of one edge equals the complete source
`RepresentationRef` of the next. Equal type names or similar labels do not
make two representations interchangeable.

## 2. Request and eligibility

An `EvidencePathRequest` binds:

- exact source and target representation references;
- one primary context digest plus a bounded set of explicitly accepted
  per-edge context digests (the primary context is always included);
- the digests of preconditions and invariants that the trusted caller says
  have already been established;
- a minimum evidence tier;
- an ordered metric objective;
- optional aggregate resource ceilings; and
- finite maximum-hop and label-expansion budgets.

For every candidate edge, the resolver checks:

1. the translation contract's context digest is a member of the
   request's digest-bound `accepted_context_digests` set;
2. all declared precondition and invariant digests are present in the request;
3. the edge meets the request's minimum evidence tier;
4. every declared capability requirement is satisfied by the receiving
   process's *live kernel capability set*; and
5. the edge cost vector has exactly the requested metric dimensions and units.

The resolver reads capabilities from the receiver's process table. It does not
trust the sender's `ProcessContext.capabilities` or any capability claim
embedded in a translation contract. A missing capability blocks a candidate
route; it does not trigger an authorization grant.

The primary `context_digest` remains the result's primary context identity.
A multi-operation route may explicitly list different edge-local contexts in
`accepted_context_digests`; the set is sorted, bounded to 64 total digests,
and included in the request digest. This avoids rewriting an operation's exact
Transit request context merely to make two operations look identical.

Acceptance is not context equivalence. The caller is responsible for declaring
which exact operation contexts belong to the route. Where representations pass
between different contexts, the route should contain an explicit translation
edge whose mapping and observation evidence establish the required
case-specific handoff. The resolver checks context membership and exact
representation continuity; it does not infer that two contexts are equivalent
or prove their wider compatibility. Omitting an edge's context from the
accepted set blocks that edge.

Precondition and invariant digests are caller-supplied facts. The resolver
checks their exact identities but does not manufacture or authenticate their
underlying proofs. The trusted caller must establish them before making the
request, and the execution/admission layer must revalidate them when needed.

## 3. Cost model and search

A route cost is a vector, for example:

```text
(latency_us = 12, energy_nj = 90, work_units = 240)
```

The metric name and unit are part of the identity. Values from different
metrics are never added together or silently converted. Edges contribute
componentwise additive costs. The request's `metric_order` is an explicit
lexicographic objective: for example, minimize latency first, then energy,
then work units. This is a deliberate policy choice, not an inferred universal
exchange rate between physical quantities.

Aggregate ceilings are checked before a partial route is extended. If a
contract declares a resource bound with the same metric name, the edge cost
must also respect that per-edge bound.

The resolver uses bounded multi-label search. At each representation it
retains nondominated labels. A label can dominate another only when its cost
is no greater in every metric and its visited-node set imposes no additional
cycle restriction. Incomparable cost vectors remain available because the
lexicographically cheapest partial route may exceed a later aggregate ceiling.
Cycles are excluded from an individual candidate path. The first target label
under the explicit lexicographic ordering is selected; edge digests provide
deterministic tie-breaking.

Metric amounts are supplied by the edge publisher. They may be measurements,
conservative bounds, or engineering estimates, but their provenance is not
automatically measured by the resolver. The resolver records their units and
honors the supplied ceilings; it does not claim that a declared
`latency_us` value is a measured wall-clock latency or that `energy_nj`
is a measured energy reading.

## 4. Outcomes

| Status | Meaning |
|---|---|
| `found` | A route satisfies all evidence, context, authority, metric, and resource constraints. |
| `already_at_target` | Source and target representation references are identical; no edge is needed. |
| `unreachable` | No directed route exists in the registered representation graph. |
| `blocked` | A topological route exists, but context, prerequisites, authority, evidence strength, metric compatibility, or resource ceilings exclude it. |
| `budget_exhausted` | The hop or label-expansion ceiling prevents a complete decision. This is not unreachability. |

The result binds the request digest, catalogue digest, context digest, live
authority-snapshot digest, selected edge sequence, aggregate cost vector,
evidence tier, and any blocker codes. The result is explicitly
`authoritative=False`.

## 5. Authority and execution boundary

A route is knowledge about a possible translation sequence, not permission
to perform it. Receiver capabilities can change immediately after resolution;
resources can be consumed; context or state can become stale. A caller must
still submit the selected operation to the existing hypervisor admission and
execution paths, which recheck live authority, policy, state, and resource
conditions.

The catalogue does not itself provide a backend implementation for a generic
translation contract. Mapping an edge to a registered CPU, SIMT/GPU, memory,
or other backend is a later integration step. An edge that only describes a
semantic mapping is not executable merely because it appears in a route.

## 6. Proof boundary and next work

A paired comparison establishes equality only for its exact input case and
declared observation projection. An independent oracle adds a second
operation-specific derivation, but it is still finite-case evidence. Neither
tier proves a translation for every possible input. The contract's context,
precondition, invariant, and resource declarations remain explicit assumptions
that must be revalidated at admission.

The resolver is currently a local in-memory catalogue with a deterministic
snapshot format. Cross-host catalogue replication, authenticated evidence
provenance, dynamic metric calibration, route reservation, and execution of a
multi-edge route are not claimed.

The next integration should bind a selected route to receiver backend
manifests and per-edge admission. Each edge should cross the hypervisor
boundary as its own authorized operation; route selection must never become a
delegated or transitive capability grant.
