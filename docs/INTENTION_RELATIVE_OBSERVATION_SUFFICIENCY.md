# Intention-relative observation sufficiency — IOS-001

**Status:** exact, bounded finite-Ground planning and reconstruction; **not** a new authority or a general Ground solver.

## The question

E-CPU can describe, navigate, and observe a computational state-space. But a receiver may only have a partial observation of its current state. **Does that specific observation suffice to determine the desired result?** If not, which *authorized* additional observations are sufficient, and when must the receiver refuse?

This implementation takes the finite quotient experiment from [In-Formation-Space GCI-003](https://github.com/Kier73/In-Formation-Space/tree/main/experiments/cross-ground-continuity/gci003) and gives E-CPU a reusable, typed **advisory** planner and independent resolver in `mailcpu/intention_sufficiency.py`. It is inspired by GCI-003 and independently implemented for E-CPU; the research experiment remains the source of its particular orbit test. It also respects the observer-relative, three-valued distinctions developed in [Virtual-Ground-Interpreter](https://github.com/Kier73/Virtual-Ground-Interpreter) and E-CPU's existing [Observer Contract](OBSERVER_ORBIT_CONTRACT.md) and [Semantic Translation](SEMANTIC_TRANSLATION.md).

## Formal obligation

For current public observation `o`, a finite, locally admitted model `S`, permitted feature set `Q`, and an intention-relative result `T`:

\[
\forall s,t\in S:\quad o(s)=o(t)=o_\mathrm{actual}
\ \land\ \bigwedge_{q\in Q}q(s)=q(t)
\quad\Longrightarrow\quad T(s)=T(t).
\]

The planner searches all feature subsets (maximum 12) of the receiver-supplied catalogue. A subset suffices only when all states in **each** remaining feature-equivalence class have identical target observations (not merely when the hidden true state gives a plausible result). The exact total ordering is `(sum of declared symbolic costs, number of features, sorted feature identifiers)`. There are three outcomes:

- `READY` — the initial observation alone determines this intention; the resolver can answer without any new measurement.
- `MEASURE` — a permitted minimum-cost feature set will make the intention determinate; the receiver must separately authorize and authenticate those measurements.
- `REFUSE` — no permitted feature subset suffices; a pair of still-indistinguishable states with different intended results is retained as the finite-model counterexample.

Different intentions over the same Ground can legitimately have different outcomes. In particular, needing more information to reconstruct the *entire* state is not grounds to refuse a narrower observation that is already determined.

## Contract and boundary

`FiniteGround` binds a sorted immutable table of state identifiers, public observations, target observations, and feature projections to four caller-verified SHA-256 identities: the Ground representation, public observer contract, target/intention contract, and exact context. These may be obtained from the existing E-CPU `RepresentationRef`, `ObservationContract`, and `canonical_value_digest` infrastructure; this module does **not** pretend that supplying a hash validates its source. Every row must have the same feature catalogue. Input JSON values are snapshotted; only strict JSON values (`null`, booleans, strings, safe integers, lists, mappings) are supported. Represent large mathematical integers or real-valued measurements with explicit canonical strings and separate Ground semantics. The content digest uses the E-CPU Python sorted-key JSON profile and **does not claim** compatibility with [RFC 8785 JCS](https://www.rfc-editor.org/rfc/rfc8785.html).

`MeasurementCapability` binds a named feature to a provider identifier, projection-contract digest, and **symbolic cost units**. Its presence means only that the caller has submitted an offer. It does not authorize execution, create a physical host, prove an observed resource is active, or prove a provider independent of another.

`plan_sufficiency(model, public_value, offers, authority_digest)` binds the result to the exact model, initial public value, receiver policy/authority fingerprint, and current offered-catalogue fingerprint. `verify_sufficiency_plan` recomputes the entire minimum-cost search against **fresh caller-supplied inputs**; changing the Ground, context, provider, cost, projection, authority digest, or public value makes a previous plan stale.

`resolve_sufficiency` accepts *exactly* the selected feature readings, checks a caller-supplied measurement receipt digest when any are required, and recomputes the surviving fiber. It refuses contradictions and residual ambiguity; it returns the target result, remaining candidate count, and a digest-bound report **without disclosing a selected state identifier**. `verify_sufficiency_resolution` independently reconstructs the report. A forged but mathematically plausible sensor reading **cannot** be detected by this mathematical solver alone; actual receiver authenticity, signing, replay/freshness, capability checks, and trusted Ground admission must happen through the existing observer / Hypervisor / computational-fabric components **before** resolution. A digest alone is not a signature.

Both the catalogue and current authority digest must be receiver-owned, observed, permissioned and revalidated at dispatch. This bounded method does not send packets, deploy code, automatically read sensors, create recovery claims, or replace E-CPU's admission coordinator.

## Executable cross-repository example

The exact 8-state GCI-003 modular-affine orbit is `x(t+1)=(5x(t)+1) mod 8`; its target is computed at logical horizons near `10^15` through logarithmic affine powering, **not** by simulating the intervening ticks. `tests/test_intention_sufficiency.py` verifies these separate intention outcomes across all eight phases:

| Request | Authorized additional features | Outcome |
|---|---|---|
| Threshold after 10^15+136 steps | none | `READY` (no additional measurement) |
| Future output parity after 10^15+137 steps | parity (cost 1), low2 (cost 2) | `MEASURE parity` |
| Threshold after one step | parity (1), bit1 (1), low2 (2) | `MEASURE low2` (tie broken by fewer features) |
| Full future output mod 8 after 10^15+137 steps | parity (1) | `REFUSE` with counterexample |

The tests also compare direct orbit values against E-CPU's `law_certifier.lcg_navigate` when run in the full repository, compare semantic digests, independently enumerate optima for all 16 four-state Boolean functions, and exercise altered authorizations, providers, costs, Ground fingerprints, forged plans, missing/extra/bogus measurements, and tampered resolutions.

Run in E-CPU:

```sh
python -m pytest tests/test_intention_sufficiency.py -q
```

## Research frontier

Next, qualify actual sensor/observer capabilities from authenticated peers, derive receiver policy fingerprints from native Hypervisor admission, and carry verified `ObserverReceipt` evidence into `resolve_sufficiency` rather than only a caller-supplied receipt digest. Use measured cost vectors instead of symbolic units when available, keeping clock and failure domains separate. For non-finite or partially constructed Grounds, use conservative abstractions and counterexample refinement; never claim that a finite quotient exhausts an unspecified infinite state-space.
