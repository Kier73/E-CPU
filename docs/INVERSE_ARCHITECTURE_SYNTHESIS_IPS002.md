# IPS-002 — Intention-first inverse architecture synthesis

**Research status:** bounded, executable candidate-architecture compiler over E-CPU's native evidence catalogue plus separately declared hypothetical relations. No deployment, physical materialization, future bandwidth reservation, autonomous network probe, privilege grant, or completed remote computation is claimed.

## Motivation

IPS-001 selected a future communication coordinate on a **single already-qualified route**. IPS-002 asks a stronger question: given an intended result, which arrangement of information relations and which coordinate could realize it?

A finite intention names a source and target representation, a logical-clock identity, a payload, an earliest start, an arrival deadline, a transit budget, a context and an ordered unit-bearing cost objective. A receiver supplies:

- Existing, independently checked native EvidencePathEdges (not just host names);
- Inert ProposedRelations between typed representation identities; each has an explicit verification obligation and **estimated** costs;
- Hypothetical PeriodicCommunicationWindows keyed by native edge ID or proposal ID.

The compiler forms finite simple directed paths through that palette. It uses IPS-001 generalized CRT to solve every route's phased transfer conditions exactly, without iterating intermediate ticks. Fully existing paths are **requalified** with a fresh native EvidencePathResolver resolution over exactly those catalogued edges, under the original EvidencePathRequest and live HeadlessOS process rights.

No offered relation is ever inserted into the native catalogue. A proposed architecture may be navigable *under its description* but remains a construction and verification obligation. A qualified native route may be valid at planning time while its **future schedule remains hypothetical**.

## The key test: cheapest route versus realizable time

Suppose E-CPU has two routes from source S to goal T, composed of separate observer-host relations:

    S -> A -> T      native cost = 2 latency units
    S -> B -> T      native cost = 8 latency units

The E-CPU native resolver quite correctly selects the first path when asked for the least cost under its verified current relation evidence. But the receiver's declared phase descriptions impose:

    route A: t mod 4 = 0; (t + 1) mod 6 = 0
             => impossible (first constraint even; second demands odd t)

    route B: t mod 4 = 1; (t + 2) mod 6 = 3
             => t mod 12 = 1

If the intended logical start is at least 10^15, the first candidate is impossible *under its schedule description*, while the second yields a specific feasible coordinate in O(log coordinate) integer arithmetic. IPS-002 synthesizes the second route, whose semantic edges are still subject to receiver-local native requalification. It neither claims the declared schedules are measured nor transmits a packet.

Add an offered direct relation S -> T, with fast transfer but no admitted evidence. IPS-002 also reports its earlier mathematical coordinate, under **construction_required** with its exact verifier obligation. That result cannot be promoted to the native route catalogue by the existence of a plausible schedule or by a matching hash.

## Contract and provenance

The public entry points are:

- mailcpu.inverse_architecture_synthesis.ProposedRelation
- mailcpu.inverse_architecture_synthesis.synthesize_architecture
- mailcpu.inverse_architecture_synthesis.verify_architecture_synthesis

The output contains *separate* selected_qualified and selected_construction candidates. Each candidate binds the ordered representation relation IDs, costs, phase witnesses, hypothesis identity and (if applicable) native route result digest. It records exact missing-relation IDs and receiver-supplied verifier digests. A verifier digest is an obligation identity, **not a certificate or an executable verification program**.

The search is finite, bounded and deterministic. Its default ceilings are 256 native edges, 64 offers, 320 windows, 6 route hops, 1024 prefix expansions, 64 inspected completed paths and 512 CRT classes. The search considers only simple paths; it cannot infer arbitrary loops, create new types, synthesize a previously unrepresented endpoint, or prove universal architectural optimality. Candidate ranking is earliest arrival, earliest start, route metric lexicographic order, hop count, then stable IDs. It does not equate declared cost estimates with actual measured network cost.

Status vocabulary:

| Status | Meaning |
|---|---|
| qualified_route_with_hypothetical_schedule | At least one exact schedule candidate uses only currently qualified native semantic edges; the schedule remains unobserved |
| construction_required | A phase-addressable candidate exists but needs one or more proposed relations independently verified and admitted |
| undetermined | Missing/ambiguous phase descriptions prevent determination |
| budget_exhausted | Prefix/path/CRT budget cannot certify complete enumeration |
| unqualified_under_current_authority | Native evidence or live receiver rights reject all possible existing paths |
| no_candidate_in_described_palette | No feasible architecture was found in the finite supplied palette and search scope; does not imply no other architecture exists |

The result preserves search_complete. Even a complete enumeration is relative to the supplied palette, context, evidence and clock. An incomplete enumeration must not be interpreted as impossibility. If a valid qualified candidate is returned while search_complete is false, it is **a candidate**, not a global optimum.

The recomputation verifier accepts the same full input bundle and live receiver context, then independently recomputes the result. Changing path evidence, offers, clock windows, policies, cost budgets or authority changes the bound result. Neither that digest nor the verifier establishes independent off-host attestation or timing continuity.

## Architectural distinction

An intention can create a **description-defined possibility space** without creating the external resources that would realize it:

    Intention I
       |
       v
    Typed Ground / representation palette
       |
       +-> Native qualified relations (E-CPU evidence + live rights)
       |
       +-> Inert architectural proposals (unknown, not admitted)
       |
       v
    Candidate route compositions + exact phase coordinate
       |
       +-> Native requalification and new observation at execution time
       |
       +-> Missing-relation verification obligations
       v
    Possible virtual realization, never automatically dispatched

There is a useful separation between *a system that is representable*, *a system that can be constructed with admitted transformations*, and *a system whose result has actually been realized and observed*. The first does not imply the second; the second does not guarantee the third.

This is one narrow, exact example of engineering from a requested behavioral description rather than solely replaying existing observed trajectories. It does not establish that every arbitrary system can be reverse-engineered from a specification, nor that passive media can carry out operations they do not physically implement. The communication links, authorization, state retention and observer transformations are still real phenomena with costs.

## Reproduce

    python -m pytest -q tests/test_inverse_architecture_synthesis.py tests/test_intention_phase_synthesis.py tests/test_evidence_path_resolver.py

Dedicated CI checks native E-CPU behavior on Linux/Windows and Python 3.11/3.13. Tests cover: a lowest-cost route with incompatible periodic constraints; an alternative route with a trillion-tick exact coordinate; a fast hypothetical link which must never enter native evidence; authority removal; edge removal; missing windows; explicit budget exhaustion; Ground/context/obligation tampering; resource ceiling enforcement; and deterministic plan re-verification.

## Next experiment: make description produce a realization

1. **Minimal observations for construction.** Route each ProposedRelation's verifier obligation to IOS-001/003 and INTERNET-006, allowing a receiver to determine which authorized measurement would resolve ambiguity or reject a proposal. No automatic public scanning.
2. **Ground construction.** Synthesize missing transformation relations from validated, composable operators with typed inputs and outputs; use E-CPU's Ground-native realization and computation DAG rather than claiming hypothetical relations are executable.
3. **Approximate-to-exact temporal qualification.** Use critnav.py to *propose* periodic window hypotheses from instrumented communication traces, then validate them on withheld observations and bound drift. A model's SO(2K) latent dynamics do not prove the physical link has available slots.
4. **Committed realization.** At a selected coordinate, require fresh phase evidence, native Hypervisor/Transit admission and actual delivery receipts. Compare realized output with the declared intention, preserve failure cases, and account for bytes, energy, latency and verifier work.

Related foundations: [IPS-001](INTENTION_PHASE_SYNTHESIS_IPS001.md), [E-CPU EvidencePathResolver](EVIDENCE_PATH_RESOLVER.md), [IOS-001](INTENTION_RELATIVE_OBSERVATION_SUFFICIENCY.md), [INTERNET-006](INTERNET_PROSPECTIVE_QUALIFICATION_006.md), and [In-Formation-Space TPP-007](https://github.com/Kier73/In-Formation-Space/tree/main/experiments/tactile-perception-continuity).
