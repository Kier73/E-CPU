# ONP-001 — An observation forms the processor that realizes its intention

**Implemented capability.** Give E-CPU a result to realize, a source identity, an
explicit hypothesis family, locally admitted observation methods, and available
computational primitives. The observer acquires the **minimum sufficient signed
measurements**, infers a complete mathematical law, automatically forms a native
processor/DAG for that law, and executes a result at a coordinate it did **not**
observe at the original source.

This closes an executable path between four existing E-CPU components:

| Stage | Existing implementation | New ONP-001 operation |
| --- | --- | --- |
| Intention | IPS-002 `ProposedRelation` | Target coordinate and semantic context, **no source coefficients** |
| Observation | IOS-001 `FiniteGround`, `plan_sufficiency`, `resolve_sufficiency` | Derive which active source measurements identify the required law |
| Construction | IPS-003 `synthesize_ground`, `compile_ground_dag` | Infer cheapest typed instruction word implementing observed law |
| Realization | `NavigableComputationDAG`, SAB-008 `TwoPortArithmeticGate` and `RealizationPolicy` | Run derived operations, commit predecessor-dependent receipts and independently verify result |

Source: [`mailcpu/observation_formed_processor.py`](../mailcpu/observation_formed_processor.py).
Tests: [`tests/test_observation_formed_processor.py`](../tests/test_observation_formed_processor.py).
Reproduce: `python examples/observation_forms_processor_demo.py`.

## The fundamental inversion

Ordinary computation specifies a machine or program before execution:

```
known algorithm -> chosen processor -> execute -> observe result
```

ONP-001 starts with an incomplete computational description:

```
observer intention I=(source identity, family, target coordinate)
         |
         v
construct hypothesis Ground G of all candidate source laws
         |
         v
ask IOS-001: which observable features are sufficient to determine this intention?
         |
         v
acquire only selected, authenticated observations
         |
         v
infer exact law -> independently test one unselected challenge observation
         |
         v
IPS-003 derives primitive word from currently offered operations
         |
         v
existing E-CPU DAG + authorized SAB-008 native execution
         |
         v
result + source witnesses + sufficiency proof + generated-machine receipts
```

The observation events are the input that forms the executable program. No
hidden source coefficients or final instruction word are accepted by the
constructor. The source host retains the true law and responds only to bounded
requested observations. The observer receives measurements; it does not
receive source code, a full state table, or original checkpoint data.

## 1. Exact finite experiment

The declared source family is a finite affine map:

\[
f_{a,c}(x) = (ax+c) \\bmod m, \\quad
(a,c)\\in(\\mathbb Z/m\\mathbb Z)^2,\\quad 3\\le m\\le16.
\]

The unknown true pair `(a,c)` exists *only inside* the source sensor. The
hypothesis Ground includes all `m²` candidates, up to IOS-001's existing
256-state bound. Each available observation feature is a source query at
coordinate `x`: `probe.x -> f(x)`. The intended result is `f(q)`, but the
requested coordinate `q` is deliberately **excluded** from the probe
catalogue. The observer must produce `f(q)` without reading it at the source.

Let `C` be the candidate laws and `Q` the authorized active probes.
IOS-001 finds the minimum symbolic-cost subset `S` of `Q` for which

\[
\\forall g,h\\in C:\quad
\\left[\\forall x\\in S,\\;g(x)=h(x)\\right]
\\implies(g.a,g.c)=(h.a,h.c).
\]

This is *complete family identification*; it is stronger than determining a
single target coordinate. The IOS-001 ordering is exactly
`(total declared cost, number of probes, sorted feature IDs)`.
The result is bound to the candidate model, intention, authority fingerprint,
and offered catalogue. No observation is requested if IOS cannot prove a
sufficient subset.

For `m=13`, two distinct points determine a unique affine law. For
composite `m`, a pair `x0,x1` determines the slope only when

\[
\\gcd(x_1-x_0,m)=1.
\]

The existing IOS-001 finite proof distinguishes these cases, rather than
assuming that two arbitrary readings suffice. For example, in
`Z/12Z`, the features `x=0,4,8` cannot resolve the multiplier. The
observer **refuses without sampling the source**.

## 2. Signed source observations

An offered measurement is

```python
ProbeOffer(source_digest, provider_id, point, cost_units)
```

with a feature contract derived from the exact source ID, provider and
coordinate. It is only a description of a capability; an actual sensor
handler and its receiver-provisioned 256-bit-or-better HMAC key must be present.

Each active source measurement is a complete canonical frame:

```text
source identity, intention identity, provider identity,
probe point, projection contract, 128-bit random challenge,
observed integer, issue/expiry time, HMAC-SHA256
```

The receiver validates all fields and freshness against an approved key.
Duplicate per-session challenge nonces are refused. The signed receipt
contains no secret key. Tampering, stale measurements, changed sources,
unapproved providers, wrong challenge nonces and extra fields are refused.

This is a receiver-approved **source observation**, not a claim that arbitrary
public internet content is authenticated. HMAC proves possession of the
provisioned key; it does not establish an independent physical sensor
attestation or prove that the source belongs to the declared function family.

## 3. Observation becomes a mathematical Ground

The resolver reconstructs the unique `(a,c)` consistent with all accepted
measurements. The native compiler receives no user-supplied coefficients.
It derives the exact IPS-003 intention:

```text
f(0) = c
f(1) = (a+c) mod m
requested output coordinate = q
```

A *third* active measurement is chosen from an offered coordinate absent from
the sufficiency set. It must match `f(x)` under the inferred law.

A non-affine source can therefore falsify the inferred law after the first two
observations, **before** native port operations occur. A third consistent
sample supports the family assumption for that sample; it is not a proof that
every unobserved coordinate is affine.

IPS-003 then derives a least-symbolic-cost primitive word using the existing
finite transformation-monoid search. The processor's instruction sequence
comes from observed relations and admitted primitive offers, not from a
prewritten application. Each stage is committed to the E-CPU
`NavigableComputationDAG`; SAB-008 checks an independently evaluated
complete Ground and the exact finite source law.

## 4. Reproducible causal experiment

Use the local simulated active port with a hidden source law:

\[
f(x)=(11x+8)\\bmod13.
\]

The observer requests `f(9)`, without knowing those coefficients.
Offer the following separately specified native operations:

```text
first:    x -> 3x + 2 (mod 13)
second:   x -> 8x + 5 (mod 13)
optional: x -> x + 1 (mod 13)
```

Given probes at 0, 1, 2 and 4, with respective symbolic costs
`1,1,3,8`, IOS-001 chooses `0,1`; the active held-out challenge is
`2`. The sensor returns:

```text
f(0) = 8
f(1) = 6
f(2) = 4
```

Those source readings uniquely yield `a=11,c=8`.
IPS-003 discovers **`first -> second`**, because

\[
8(3x+2)+5\\equiv11x+8\\pmod {13}.
\]

The generated processor produces

\[
f(9) = (11\\cdot9+8)\\bmod13 = 3
\]

without observing `x=9` at the original source. Two bounded port
operations and their content-addressed DAG commits constitute the native
execution record. The verifier independently reconstructs
every HMAC measurement, the IOS proof, generated law, exact IPS-003
plan and SAB-008 execution evidence without calling the source again.

The experiment's primitive catalogue is supplied as existing capability,
**not** as an already selected program. Replacing or withdrawing that
catalogue changes the synthesizer's result, and can produce an explicit
`not_derivable_in_supplied_palette` refusal even after sufficient
source observation.

## 5. From observed law to host-selected processor

The next implementation step is already part of ONP-001:
`realize_observed_processor_on_fabric(...)` accepts a **verified existing
observation-formation receipt** and E-CPU's native
`SubstrateObservation`, `BootstrapPolicy` and `CarrierBinding`
objects.

It does not ask the user for the source-state machine or a chosen
host/route. Instead it derives the `FiniteObserverLaw` from the
authenticated observations and their verified affine semantics:

```text
states       = v00, v01, ..., v(m-1)
action       = step
transition   = v(x) --step--> v((a*x+c) mod m)
observation  = value(x) = x
```

This law is fed directly to the existing INTENT-001
`realize_formed_intention` algorithm, which forms the minimal
future-observation processor under the requested field `value` and
selects its current authorized execution path through the
existing SAB-001 `AdaptiveBootstrap` planner.

The resulting receipt explicitly binds the original signed observation
evidence, generated finite law, formed machine fingerprint, target
intention, selected execution path and reconstructed result.

For the 13-state experiment, retaining `value` creates a 13-class
processor with 4 theoretical register bits. Two differently priced
execution loci (`alpha`, `beta`) and an independently positioned
observer (`witness`) are present in the **observed** host/path
inventory. No execution locus is named in the mathematical intention.

The receiver-admitted planner chooses `alpha` initially. Remove
`alpha` from the observed inventory and the system forms the same
machine on `beta`:

```text
same source evidence  -> same formed machine fingerprint
same intended result  -> same output observation
different availability -> different plan/path fingerprint
new source probes      -> 0
```

A `shadow` host can advertise a cheaper operation but cannot execute
it without the appropriate *receiver-owned* realizer binding and policy
permission. The adapter reuses native INTENT-001, rather than
introducing another private scheduler or authority system.

Both remote-path examples here use SAB-001's locally bound simulated
carriers/interpreters. Real independent machine-host execution and
authenticated transport belong to the already implemented E-CPU
Computational Fabric / mutual-TLS layers and are the next physical
integration benchmark.

## 6. Negative controls and interpretation

The automated tests check:

- Minimum sufficient observation selection and no direct-target source read.
- Mathematical refusal when the observed features cannot distinguish the law.
- Composite-modulus ambiguity (two cheap probes need not suffice).
- Signed source receipts, freshness, challenge nonces and source/provider pins.
- A hidden source that falsifies the inferred law at the held-out observation.
- Receiver realization authority checked **before** even requesting a source reading.
- Impossible operator palette refusal rather than fabricating execution.
- Exact native DAG, port-frame and independent ground-receipt reconstruction.
- Tamper detection for source witnesses, model identity, artifact/program and result.
- Two different intentions over the same source law forming separate realizations.
- Host/path selection from observed receiver-authorized offers, reformation after preferred
  host disappearance, and refusal of cheap but unbound advertised capabilities.

### Exact scientific scope

The current mathematical realization is an active, software-modeled two-port
native executor, not a passive physical Internet link or a newly provisioned
remote Hypervisor. The declared affine hypothesis family supplies the
inductive model. Without such a justified structural family—or enough actual
observation to distinguish the alternatives—no finite set of measurements can
guarantee the complete behavior of an arbitrary function.

This is therefore an experimental form of **observation-created computation**:
the observer's chosen measurements determine a unique law within an admitted
family; that law automatically determines a new executable program and local
realization, with independently reconstructable evidence.

## Next frontier

1. Replace the explicit finite affine hypothesis catalogue with **observation-
   discovered candidate laws** from VGI structural memory, VL-I generated
   processors, and E-CPU's existing Ground qualification.
2. Let each physical host expose a typed, authenticated source observation
   and receiver-authorized operator binding, then use SAB-001 to **select
   the realization path from live available capacity**.
3. Allow observation to discover new vocabulary/operations where a complete
   primitive palette was not supplied; require independent execution evidence
   before promoting any hypothetical relation into an admitted one.
4. Scale from `m²<=256` explicit finite candidates to symbolic proof and
   sparse refinement for very large state spaces.
5. Compare the cost of on-demand observation, program synthesis, and
   realization against prebuilding a processor or fully sampling the source.

The throughline remains: **the observer describes what is needed; observation
determines which computational relationships exist for that intention;
the verified relations form the processor that realizes it.**
