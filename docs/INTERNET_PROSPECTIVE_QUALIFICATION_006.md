# INTERNET-006 — Prospective Internet Ground qualification

**Status:** proposed implementation under native E-CPU test and hosted live-observation gates. The local isolated runner exercises contract logic but does not substitute for native E-CPU or live Internet execution. No arbitrary Internet hosts, DNS resolvers, caches or routers are probed.

## Why this is the next architectural layer

INTERNET-001–004 recognized existing Git, HTTP and RFC state-space relations using actual authorized Internet services or controlled local services. INTERNET-005 compiled **already observed** exact relations into E-CPU's native `EvidencePathCatalogue`; `EvidencePathResolver` selected least-cost qualified routes under live HeadlessOS capabilities. An unsolved problem remained: **which missing relation should E-CPU observe *before* it can plan the requested navigation?**

The answer in this experiment is deliberately narrow and falsifiable. `ProspectiveQualifier` treats unobserved `ProbeOffer`s as hypotheses. It calls `InternetGroundRouter.resolve` on the **already verified** prefix `I.source -> offer.source` and suffix `offer.target -> I.target`. If both are independently reachable through the existing native resolver (including the zero-hop `ALREADY_AT_TARGET` case), then observing this one missing relation **could** complete the intention. Otherwise, no speculative route is added to the authoritative catalogue and the offer is not selected.

For each eligible single-gap offer, E-CPU sums the verified prefix cost, the receiver's **estimated** probe cost, and the verified suffix cost using the requested unit-bearing lexicographic metric order. The cheapest plausible completion is chosen. These estimates are *not* network measurements. There is no invented success probability or counterfeit expected information gain. In-Formation-Space's observation-path lifecycle and VGI partial-attention work explain why a *plan* and a *successful observation* must be kept distinct; this is a concrete first implementation of that separation.

## Actual E-CPU components used

| Boundary | Existing authority | INTERNET-006 reuse |
|---|---|---|
| Representation and context | `mailcpu.semantic_translation.RepresentationRef` | Source, target, context and Ground are exact pinned identities |
| Qualified path selection | `mailcpu.internet_ground_routing.InternetGroundRouter` (INTERNET-005) | Reuses the existing catalogue and its verifier callbacks; no alternate router |
| Route topology and budgets | `mailcpu.evidence_path_resolver.EvidencePathResolver` | Checks the verified prefix and suffix **before probing**; recomputes final route after |
| Probe permission | Existing `HeadlessOS` kernel process `Capability` | Requires `/internet/<kind>/<provider>` with `observe` before a handler runs |
| Source/protocol verification | Receiver-installed `InternetGroundRouter` verifier | Must independently verify original bytes/response and intention after probe |
| RFC application service | `mailcpu.public_internet_navigation` (INTERNET-004) | Optional live public RFC `GET` and independent offline link reconstruction |
| Mathematical law discovery | `mailcpu.active_ground_discovery.discover` (SAB-002) | Existing `admitted_affine_observation` can be a receiver-installed probe handler, preserving finite-witness scope |
| Persistence and distributed recovery | E-CPU M1/M3/Transit/Hypervisor | **Not claimed** by this increment; route planning remains non-authoritative |

## Lifecycle

```text
Receiver intention I = (source, target, Ground, context, goal and budgets)
    | qualified route already exists?  --> no new network requests
    v
Receiver-curated hypothetical provider offers (no observed edge)
    | filter by exact kind, Ground, context, lease, local handler, live process permission
    | for each missing relation E = (u -> v):
    |    native EvidencePathResolver: source -> u (qualified prefix)
    |    native EvidencePathResolver: v -> target (qualified suffix)
    |    check combined hop/metric/resource estimates
    v
One selected, receiver-installed bounded probe (read-only protocol)
    | record bytes, request count, requester-local elapsed duration, raw evidence ID
    | independent receiver verifier (not web-supplied code)
    | exact-case paired-observation check (not universal law)
    v
INTERNET-005 add only after independent receiver accepts
    | native EvidencePathResolver recomputes full route and live capabilities
    v
Qualified, selected route OR explicit refusal + append-only attempt receipt
```

### Security and scope

- **Offers are not edges.** The prospective result never sets `EvidencePathStatus.FOUND` by manufacturing a comparison case, oracle receipt, or Hypervisor permission.
- **No general crawling.** There is no URL or command in a `ProbeOffer`. An individual receiver installs provider-specific handlers with hard-coded allowlists, request limits, redirect rules and socket timeouts. Remote text, DNS records or response bodies never supply executable functions or destinations.
- **Authority before I/O.** Current process capabilities are read from the native HeadlessOS process table; missing/revoked rights prevent the probe from being called. That is not remote service authorization: each installed handler must separately respect provider policy and credentials.
- **Source identity before route admission.** The installed receiver verifier must check source pins and a declared observation contract. Matching hashes from the same untrusted response are not independent evidence or remote authentication. The pilot RFC data is semantically replay-verified but lacks independent external page-content pins.
- **Finite empirical evidence.** INTERNET-005's route edge is `PAIRED_CASE`; an intention demanding `INDEPENDENT_ORACLE` does not dispatch speculative probes through this adapter. SAB-002 candidate laws retain `finite_witness_only` status.
- **Accounting.** The handler receives a maximum raw byte count and declared max request count; the postflight check repeats these constraints. A badly behaved installed handler can exceed the quota *during* network I/O, which postflight validation cannot undo. Do not install unreviewed handlers. Full overrun bytes are recorded, not silently treated as zero.
- **Preflight failure ≠ observation.** An unavailable service or timed-out probe is preserved as `probe_refused`, not interpreted as an observed absence. The next receiver-approved candidate may be tried within the finite budget.
- **Drift and continuity.** An admitted case describes one snapshot within a bounded lease. Replaying an old receipt does not prove the service is unchanged. M3 quorum, retries, peer identity, hardware propagation, and cross-host exactly-once execution remain separate validation tasks.

## Falsifiable acceptance cases

The native tests include: DNS missing link plus qualified HTTP suffix beating a more expensive Git alternative; changed measurement objective; a prequalified route requiring **zero extra probes**; live capability denial; unsupported evidence grade; stale Ground/lease; no single-gap continuation; timeout with Git fallback and append-only hash-chain; forged source/target; digest-rehashed contradictory projection; wrong verifier; raw byte and request overshoot; and exhausted attention budget.

## Real public Internet pilot

The optional GitHub Actions job runs the **existing** RFC-Editor HTTPS navigator after prospective selection, stores exact HTML bytes and source URLs in the original INTERNET-004 capsule format, and then reruns the same admission and semantic link check **without network access** in a separate job. The declared intention is RFC 9293 -> RFC 793. This validates public HTTP interaction and receiver interpretation, *not* internet router computation or a service-issued E-CPU signature.

```bash
python -m unittest discover -s tests -p 'test_internet_prospective_qualification.py' -v
python examples/prospectively_navigate_public_internet.py observe \
  --seed 9293 --target 793 --output /tmp/internet006-live.json
python examples/prospectively_navigate_public_internet.py replay \
  --seed 9293 --target 793 --input /tmp/internet006-live.json \
  --output /tmp/internet006-replayed.json
```

## Next development

Add a **verified partial-frontier option** for when every prospective intention needs *two or more* as-yet unknown relations; use VGI partial-awareness and IFS append-only observation-path research to choose an information-gathering sequence. Then admit read-only Git/HTTP/DNS providers with their own externally pinned source/verifier modules, unify measured costs with `TransitPathSessionBinding`, and attach the results to existing Fabric discovery and Ground authority. No speculative edge should ever become authorized merely because it shortened a predicted route.
