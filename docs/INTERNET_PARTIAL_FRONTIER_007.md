# INTERNET-007 — Multi-missing-relation attention over Internet Grounds

**Status (2026-11-16):** proposed, implemented, and checked in an isolated local API-compatible harness; **native E-CPU tests, GitHub-hosted live public HTTPS, and cross-process independent replay require successful CI**. This is neither unbounded internet browsing nor code running on passive network media.

## Question

E-CPU's founding [Internet-as-computer](THE_INTERNET_IS_THE_COMPUTER.md) proposition asks that the internet's *existing*, permissioned information relations become eligible computational loci. INTERNET-005 compiles **already verified** Git/HTTP/DNS/RFC and finite-witness mathematical observations into the native `EvidencePathCatalogue` and uses `EvidencePathResolver` under live HeadlessOS capabilities. INTERNET-006 allows **one missing** observation between fully verified route segments. A more interesting intention needs several missing observations: **which one must be looked at first, when none alone would close the route?**

`mailcpu.internet_partial_frontier.PartialFrontierQualifier` extends the existing `ProspectiveQualifier`. It does not replace its handlers, admission, attempt ledger, or the verified route planner. It changes only **which receiver-curated hypothetical probe is recommended next** when INTERNET-006 finds no one-gap completion.

## Mathematics and inference boundary

Let a typed intention be \(I=(s,t,G,C,\mathbf m,\mathbf b)\), and \(E_v\) be *independently verified exact-case* Internet edges. Let \(E_u\) be **unverified** `ProbeOffer` relations, created by the local receiver, not advertised as valid by a remote service. A speculative completion is a sequence:

\[
  s\xrightarrow{E_v^*}a_1\xrightarrow{?p_1}b_1
   \xrightarrow{E_v^*}\cdots\xrightarrow{?p_k}b_k
   \xrightarrow{E_v^*}t.
\]

Every \(E_v^*\) segment is obtained from the **real, native** `InternetGroundRouter.resolve`, which itself calls `EvidencePathResolver` and checks the current HeadlessOS process capabilities, Ground/context identity, evidence grade, exact projections, resource costs, and bounded route search. The \(?p_i\) terms are **never put in a route catalogue** and have no successful `ObservationComparison` until their bytes are independently observed and verified. A candidate sequence is *a possibility*, never a successful route or authorization.

Among candidate completions, attention minimizes the number \(k\) of missing relations first. For equal \(k\), it prefers an **accessible first probe** present in more finite completion hypotheses; then the minimum lexicographically ordered, unit-bearing estimated end-to-end cost. This is a **structural hypothesis count**, not a probability of success or a statistical expected information-gain estimate. It is inspired by VGI's *partial-observation attention* and IFS's observation-path evidence lifecycle; it does not claim those mathematical modules were applied to external DNS/HTTP facts. Those require separate Ground representation and provenance adapters.

The first gap is selected only when an actual verified route reaches its source. It is not permissible to probe a downstream gap by assuming that an untested upstream gap already occurred. After one probe, INTERNET-006 independently validates the raw observation, matches the exact expected projection and source, admits the case **only when receiver evidence accepts it**, and calls the native resolver again. A newly admitted case can be labelled `case_accepted_not_selected` because the rest of the intention is still unresolved. This successful *observation* must not be misreported as a completed *intention*.

### Bounded search and refusal

- At most **32** receiver-curated candidate offers from the inherited policy, **four** hypothetical gaps per plan, **2,048** speculative expansions per gap-count level, **256** candidate completion plans, and **1,200** native segment route queries per selection. These are deterministic **search effort** ceilings; native resolver retains its own hop and expansion budgets.
- A partial enumeration is **refused** as `budget_exhausted` with a `bounded_search_incomplete` reason; its first few candidates do not silently become an exhaustive optimality claim.
- Every proposed segment must fit the original intention's unit-bearing cost ceilings and hop budget; no sum mixes different units.
- Repeated offers, repeated representation states and disconnected proposed paths cannot fabricate a completed route. Native segments are checked against the existing case catalogue when composing the frontier.
- The existing upstream `ProspectiveQualifier` remains the only source of read-only handler dispatch, raw-byte/request limits, live process authorization, independent verifier rechecks, native route admission, and predecessor-hash attempt records. This policy does not write a second event ledger.
- A finite alternative count is sensitive to how the local receiver lists hypotheses. It is not a claim about the number of real-world routes or a learned success distribution.

## Competing path experiment

The native test fixture models a three-relation intention:

```text
Receiver intention: START ------------------------------------> GOAL
                   ? DNS: start->mid1
                   ? Git: mid1->mid2
                   ✓ HTTP: mid2->goal (pinned qualified case)
```

Neither unverified relation is inserted in `EvidencePathCatalogue`. On the first step, the correct decision is DNS, which has a zero-hop **verified** prefix. Its successful case becomes qualified but the intention is still unresolved. On the next call the now-verified DNS prefix allows Git to be tested. If Git succeeds, native E-CPU routing reports a three-edge verified `FOUND` result. Failure of DNS is a `probe_refused` event, not an observed DNS absence; a separate two-gap HTTP/DNS alternative can be considered within the receiver's attempt budget.

Other tests exercise changing observation priority, coverage ranking across competing hypotheses, complete-route no-probe behavior, expired Ground/leases, missing live capability, forged/rehashed responses, false output projection, cycles, disconnected links, exceeding estimated cost/hops, and hypothesis explosion. The local standalone harness ran **19 tests successfully** against this source, with simplified compatibility classes. This does **not** prove native E-CPU or remote-operation success.

## Public internet pilot: two different observations

The optional hosted example `examples/navigate_rfc_partial_frontier.py` executes a concrete controlled **read-only** intention:

```text
RFC 9293 --[observed reference in HTML]--> RFC 793
        --[observed reference in separate HTML]--> RFC 761
```

RFC 9293 states that it obsoletes RFC 793. RFC 793 identifies RFC 761 as its predecessor. The receiver independently declares the intended chain and permits requests only to canonical `https://www.rfc-editor.org/rfc/rfcN.html` URLs, via INTERNET-004's no-redirect/timeout/byte-limited HTTPS client. Each observation has an independent raw HTML archive, SHA-256 body identity, exact link checks, parent/path reconstruction, locally measured request duration, and subsequent receiver-installed case verifier. The two candidates use the same **receiver-scoped chain Ground**, while each HTML capsule retains its own stage-specific `Policy`. The chain Ground is *a logical provenance relation*, not evidence that an internet router executed a symbolic program.

The original live report is retained as a CI artifact; a different GitHub-hosted job replays **both** capsules without making an internet call, validates the event-chain identity, and recomputes the final native route. The isolated local fixture used simulated HTML responses while invoking the *real* INTERNET-004 parser and raw-byte replay logic. It did not contact public DNS or RFC servers.

**Source-authenticity qualification:** matching a freshly observed capsule digest with itself proves internal integrity, not independent content authenticity, HTTPS origin hardware identity, transport propagation computation, or durable remote authority. Receiver-owned external source pins remain a future step. If the RFC editor changes a referenced relation or serves unexpected content, the live probe must fail its declared intention rather than manufacture the missing edge.

## Reproduction and verification gates

```bash
# Native E-CPU checkout with this stacked PR present:
python -m unittest discover -s tests -p 'test_internet_partial_frontier.py' -v
python -m unittest discover -s tests -p 'test_internet_prospective_qualification.py' -v
python -m unittest discover -s tests -p 'test_internet_ground_routing.py' -v
python -m pytest -q tests/test_evidence_path_resolver.py

# Only an authorized internet-connected runner:
python examples/navigate_rfc_partial_frontier.py observe --output /tmp/internet007-live.json
# Later, separately, with NO external reads:
python examples/navigate_rfc_partial_frontier.py replay \
  --input /tmp/internet007-live.json --output /tmp/internet007-replayed.json
```

`.github/workflows/internet-partial-frontier.yml` runs native integration and regression tests on Linux and Windows with Python 3.11 and 3.13, followed by a public HTTPS job **only if tests pass**, and a separate offline-replay job **only if the live observation passes**. The workflow must report its actual final conclusion; a queued or cancelled job is not success.

## Next questions

1. Feed proven VGI distinguishability / intention-sufficiency scenarios into the structural attention policy, *without* letting a model issue receiver authority or inflate finite evidence into general laws.
2. Replace the RFC-only pilot with multiple **independently source-pinned** Git, DNS, HTTP, and authenticated transit observers, including drift and lease revocation across steps.
3. Connect the final native route proposal to E-CPU's separately authenticated M1/M3/Hypervisor effect and recovery path. Do not conflate a successful route proposal with an authorized effect.
4. Measure actual internet request bytes, local verification work, and route re-planning overhead separately. No path arithmetic or remote multi-host physical failure independence has been demonstrated here.
