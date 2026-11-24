# ITR-001 — Intention to verified realization: discovery speed as computation

**Goal.** Measure the complete interval from a receiver's intended observation to an accepted result, while giving the formation engine neither the source's hidden coefficients, nor an algorithm, nor a chosen processor or host. Reuse the computational capacity E-CPU already exposes through its typed, receiver-admitted observer and substrate catalogues. The user-level premise that capable substrates may already contain E-CPU is an **architectural search convention**, not evidence that a particular unobserved substrate has authorization or executes a specific operator.

**Implementation:** [`mailcpu/intention_realization_latency.py`](../mailcpu/intention_realization_latency.py); pure, independently runnable cost-ledger math: [`mailcpu/intention_realization_metrics.py`](../mailcpu/intention_realization_metrics.py).  
**Native tests:** [`tests/test_intention_realization_latency.py`](../tests/test_intention_realization_latency.py); pure timing and exact-amortization tests: [`tests/test_intention_realization_metrics.py`](../tests/test_intention_realization_metrics.py).  
**Runnable benchmark:** [`examples/intention_realization_benchmark.py`](../examples/intention_realization_benchmark.py).  
**Cross-platform CI:** [`ITR-001`](../.github/workflows/itr001-intention-latency.yml).

## 1. What is supplied, and what is discovered

The supplied `ObserverConstructionIntention` is `(relation, source_digest, observer_id, authority_digest, modulus, requested_input)`. It does not contain source coefficients `(a,c)`, the program implementing the source, a named CPU, or an implementation. The receiver separately supplies existing `ProbeOffer` measurement capabilities, source-provider HMAC verification keys, `AffinePrimitive` operation offers, an ONP/SAB realization policy, and native SAB-001 `SubstrateObservation`, `BootstrapPolicy`, `CarrierBinding`, and admitted logical interpreter/observer loci. Those are existing *capacities*, not a chosen route or a program. Capability advertisements alone are insufficient to execute.

The controlled source family in this first benchmark is `f(x)=(ax+c) mod 13`. It is a deliberately finite original-source fixture; the true `(a,c)` stays inside the source observer. The single requested output at `q=7` is excluded from the observed-probe catalogue. ONP-001's actual IOS-001 sufficiency planner chooses measurements and a held-out challenge. The fixed source fixture yields `f(0)=8`, `f(1)=6`, `f(2)=4`; the admitted finite law is `a=11,c=8`. IPS-003 derives the least-symbolic-cost word `pre -> post` from the offered primitive set. This resulting program is **not supplied** to ITR-001. INTENT-001 forms the future-observation quotient machine, and SAB-001 chooses and executes the authorized host and path.

The goal for an independent cold query at `q=7` is `f(7)=7`. A separate earlier intention, `q=9`, can supply a verified source-evidence seed. Since the source identity, representation relation, observer identity, authority and modulus are unchanged, the later intention can use the source law from this seed without requesting new measurements. It still independently verifies the seed report and local authority policy. New native host placement is selected under the *current* receiver inventory.

## 2. Three realized paths

**Cold:**

```text
Typed intention + available capacities
    -> ONP-001 IOS sufficiency plan
    -> authenticated source readings + held-out challenge
    -> PFI/IPS-003 source law and minimal native primitive word
    -> native Ground/DAG execution and independent source-check
    -> independently requalified source evidence
    -> INTENT-001 minimal future-observation quotient
    -> SAB-001 current admissible host/path + execution
    -> independently checked observer result
```

The actual entry point `cold_realize(goal, capacity, sensors, now, nonce_factory)` invokes `realize_observed_processor` and `warm_realize(...reuse_identical_goal=False)`. It includes all source observation, plan search, verification, host selection and native realization costs. This is intentionally redundant verification, not a misleading execution-only timing.

**Warm new intention:**

```text
Retained ObservedProcessorRealization + new query coordinate
    -> verify_observed_processor against admitted signature keys, original
       source, chosen measurements, held-out evidence and native DAG
    -> derive FiniteObserverLaw from those independently checked coefficients
    -> INTENT-001 + SAB-001 form processor and select current host/path
    -> compare output with source replay + verify native receipt
```

The retention is an in-process verified `ObservedProcessorRealization`. It is not a long-lived signature-free cache and is not asserted to be a durable, remote consensus store. A source/observer/authority/relation/modulus change is refused. Signed evidence expiry still applies on every warm request.

**Warm identical intention:** After the exact same source qualification, return the previously accepted result and a content-bound reuse receipt. **No new source reading or host operation** is performed. The response explicitly records `machine_digest=null`, `route_digest=null`, so it cannot masquerade as a fresh fabric execution. The original evidence remains available through the signed report, not only a digest.

## 3. Mathematical invariants

The verified source family and observer identity are fixed across a warm reuse:

\[
  S=(\mathrm{relation},\mathrm{source},\mathrm{observer},\mathrm{authority},m),\quad S'=S.
\]

The individual intention `I=(S,q)` may change by `q` alone. Let admitted observations derive an affine law `f(x)=(ax+c) mod m`, where ONP-001 has confirmed its source-family constraints by a separately selected challenge. The transformed E-CPU Moore law is

\[
 M_f=(\mathbb Z/m\mathbb Z,\{\mathrm{step}\},\delta(x)=(ax+c)\bmod m,O(x)=x).
\]

For the requested `q`, INTENT-001 computes the smallest observation-preserving quotient `M_f/\sim_O` and SAB-001 realizes a processor/route. Its final result `r` must satisfy

\[
 r=O(\delta(q))=(a q+c)\bmod m.
\]

A source replay independently checks that equality; `verify_formed_machine` checks minimum quotient correctness, and `verify_bootstrap_report` checks the local native receipt. The machine fingerprint is independent of host placement; plan fingerprints are expected to change when available hosts change.

**Cost:** With `T_qualified(I)` denoting all source and receipt verification, `T_form(I)` formation/synthesis, `T_nav(I)` native route resolution, and `T_exec(I)` realization, the optimization objective is

\[
 T_{I\to R}=T_{\rm observation}+T_{\rm qualification}+T_{\rm formation}+T_{\rm navigation}+T_{\rm realization}.
\]

The code measures actual `perf_counter_ns` intervals. Native `realize_formed_intention` combines formation, path selection and execution in its current API, so that subtotal is reported as one measured stage; these costs are **not fabricated** as separate numbers.

The campaign compares **identical requested goals**: independent cold `f(7)` acquisitions against warm `f(7)` built from a prior verified seed `f(9)`. The seed itself is charged separately. Let `C=median(T_cold)` and `W=median(T_warm)`, and `S=T_seed`. For `C>W`, the first count of repeated later goals at which `N(C-W)>S` is `floor(S/(C-W))+1`. If `C<=W`, amortization is reported as **unresolved/no positive median advantage**. This is a local experimental cost statistic, not a general runtime guarantee. Timing always includes source verification on warm requests; source-probe counts are reported separately.

## 4. Existing E-CPU and CIG constructions used

| Existing implementation | Direct use in ITR-001 |
| --- | --- |
| `mailcpu.observation_formed_processor` / ONP-001 | Inversion from intended output to selected signed measurements, inferred law, IPS-003 program, actual native DAG receipt |
| `mailcpu.generative_ground_construction` / IPS-003 | Native Dijkstra over the offered finite affine transformation monoid, no preselected algorithm |
| `mailcpu.intention_formed_fabric` / INTENT-001 | Minimal future-observation Moore quotient, independent minimality audit, native formed execution |
| `mailcpu.substrate_bootstrap` / SAB-001 | Receiver-admitted capacity, current operation availability, lawful transport/host routing, native observer receipt |
| `CIG-011` In-Formation-Space | Architectural precedent for amortizing architecture selection, proof-retaining transitions, and charging formation costs; no CIG Python imported for the affine experiment |
| `CIG-017/019/020` | Next richer source class: proof-derived sufficient decoders, shared proof memory, and verified incremental realization; not invoked for this first finite affine benchmark |

## 5. Reproduction, controls and next implementation

```sh
python -m pytest -q tests/test_intention_realization_latency.py tests/test_intention_realization_metrics.py tests/test_observation_formed_processor.py tests/test_intention_formed_fabric.py
python examples/intention_realization_benchmark.py --trials 5
```

The native tests assert no supplied source coefficients or primitive word, exactly three source probes for cold ONP, zero new probes for warm requests, reformation after loss of a preferred Host, unchanged semantic fingerprints and changed route fingerprints, rejection of an unauthorized advertisement, rejection of stale HMAC observations and changed source identity, and comparison of the same requested `f(7)` via cold and warm pathways. The CI matrix runs Linux and Windows on Python 3.11/3.13. The stage ledger and cold/warm seed-amortization threshold are printed as bounded JSON.

**Next:** (1) integrate CIG-017 executable sufficient decoders as a second source-law class and compare against forming full Moore machines; (2) use CIG-011 warm architectural proof reuse for actual changing host availability; (3) package source certificate and derivative Ground as durable E-CPU claim-backed structural memory; (4) measure remote authenticated observation and path qualification against actual physical host loss. For now this benchmark uses the existing local signed sensor/receiver, local policy, and simulated SAB carriers, not an independently administered internet-scale active source.
