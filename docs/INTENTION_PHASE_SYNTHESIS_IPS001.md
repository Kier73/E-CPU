# IPS-001 — Intention-first communication-state synthesis

**Status:** executable, non-authoritative mathematical possibility compiler over a route qualified through E-CPU's existing `EvidencePathResolver`. It does not send data, create network bandwidth, reserve slots, attest a future schedule, or grant an execution capability.

## Research question

Can an observer **impose a compact description of the needed communication process**, derive a possible future state from that description, and reach its coordinate without walking every intermediate clock tick?

This is different from a time-series forecaster. The initial object is the **intention**, not a fitted history. The observer describes a required payload, deadline, maximum transit duration, exact route/Ground/clock identities, and potential per-edge schedules. The compiler solves the inverse constraints:

```text
Intention (required delivered state)
  -> Native EvidencePathResolver (qualified, receiver-authorized route)
  -> Receiver-supplied periodic communication hypotheses
  -> Exact non-coprime modular intersection
  -> Earliest mathematically feasible scheduler coordinate
  -> Candidate only; execution admission and independent observation remain separate
```

For a qualified route with edges `e_0,...,e_(h-1)`, transit durations `d_j`, and cumulative offsets `D_j = sum_(i<j) d_i`, an intended start coordinate `t` must satisfy:

```text
t >= not_before
t + sum_j(d_j) <= arrive_by
sum_j(d_j) <= max_transit_ticks
payload_bytes <= capacity_bytes[j]                       for all j
(t + D_j) mod period[j] is in allowed_phases[j]           for all j
valid_from[j] <= t + D_j
t + D_j + d_j - 1 <= valid_through[j]                     for all j
```

The **possibility space** is the set of all such `t` on the native selected route. IPS-001 constructs the earliest point in this set by a generalized Chinese Remainder Theorem (CRT). It does not enumerate `not_before..t`. The candidate includes each edge-entry coordinate and an exact residue/modulus witness. The time horizon affects big-integer arithmetic cost, not the number of simulated ticks.

## Native E-CPU reuse

The public entry point `synthesize_communication_state` **calls the existing** `EvidencePathResolver.resolve(catalogue, request, operating_system, pid)` itself. A caller cannot supply a forged successful native route response. Native route verification still controls path evidence strength, Ground/context and preconditions, live receiver process permissions, typed costs, and resource ceilings. If the resolver refuses, the synthesis is `unqualified`.

Schedules are additional receiver-supplied **hypotheses** keyed by exact native edge IDs. All must use one declared logical clock digest and one schedule Ground digest, and leases must cover the proposed transit. These digests preserve identity, **not authenticity**. A native edge may qualify a semantic transformation without establishing that a proposed future periodic capacity schedule is physically true.

Statuses:
- `possible_under_description`: exact witness under a *hypothetical* periodic schedule; no reservation or dispatch.
- `impossible_under_description`: the supplied exact constraints contradict each other or have no coordinate before the deadline; this is **not** proof no other system or route could work.
- `undetermined`: windows are missing, duplicated, extra, or have incommensurate logical clock/Ground identities.
- `budget_exhausted`: bounded residue-class expansion was insufficient; not an impossibility proof.
- `unqualified`: native E-CPU did not accept the source-to-target route under current evidence and receiver authority.

`verify_communication_synthesis` independently recomputes against current native catalogue and live receiver permissions. An unchanged witness may still become invalid before dispatch; use native execution admission and actual receipts to accept physical or hosted effects.

## Exact example

Two selected route edges admit entry at respectively `t % 4 == 1` and `(t+2) % 6 == 3`, where the first edge requires two ticks and the second three ticks. The inverse conditions reduce to:

```text
t % 4 == 1
t % 6 == 1
=> t % 12 == 1
```

For `not_before=10^15`, the first possible start is **1,000,000,000,000,009** and the intended arrival is five ticks later. The algorithm does not execute the trillion intervening states. An incompatible phase changes the outcome to `impossible_under_description`, while missing evidence is `undetermined`.

## Verification

```bash
python -m pytest tests/test_intention_phase_synthesis.py -q
```

Tests exercise the exact large-coordinate witness, non-coprime CRT refusal, capacity and lease failures, missing clock/description, explicit class budget, and 120 independently step-enumerated random small cases. The native test uses actual `TranslationContract`, `ObservationComparison`, `EvidencePathCatalogue`, `EvidencePathRequest`, `HeadlessOS` capabilities and route re-verification, and refuses removal of the registered path evidence.

The pure solver was additionally checked locally against **1,200 randomized exhaustive small-window oracles**. This validates arithmetic consistency only; CI must verify the full E-CPU native integration.

## What this establishes and what comes next

A compact **desired system description can construct a mathematical possibility set**, and from that set an exact future coordinate can be synthesized without stepwise simulation. This is a testable preliminary instance of inverse design, **not** a claim that an articulated ideal automatically creates physical resources or that the entire distributed system has been reverse-engineered.

IPS-001 currently solves a qualified **single selected route**, with exact periodic schedules. It does not discover all possible routes, nor establish synchronization between unsynchronized physical hosts. Its logical scheduler clock is not UTC, cross-host monotonic time, or a measured propagation delay.

Next research:

1. Feed IPS-001 *hypothetical candidate windows* derived from `critnav.py`'s critical-line torus phase model; a fitted approximate window must be independently measured, calibrated, expiry-bounded and qualified before operational use. Never treat unit-circle eigenvalues as proof that network capacities recur.
2. Search multiple native-qualified route alternatives and jointly synthesize **route + representation + phase coordinate**, rather than timing only the first cost-optimal route.
3. Build an intention-relative admissibility certificate: identify precisely which missing observations would distinguish possible realizations; reuse IOS-001/003 and INTERNET-006 rather than creating an alternate observation authority.
4. Revalidate at the selected logical coordinate, dispatch only with native Hypervisor/Transit authority, and compare realized receipts with the intended state. A missed or invalid future condition must remain visible, not silently repaired.

The NOAA TPP-007 seven-day experiment in In-Formation-Space is a useful methodological counterpart: a descriptive model may remain algebraically coherent while its empirical applicability drifts. Its original observational evidence and limitations are retained in [TPP-007](https://github.com/Kier73/In-Formation-Space/tree/main/experiments/tactile-perception-continuity). Its observed correction is not an E-CPU network measurement.
