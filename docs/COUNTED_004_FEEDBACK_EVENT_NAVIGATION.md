# COUNTED-004 — Navigating nonlinear feedback by counted observer quotients

## New capability

The exact semantic output of a **non-settling, feedback-driven finite
computation** can be indexed directly. Variable numbers of output events
per input action, multiple mailboxes, event order, and action-position
timestamps are preserved.

The source is an existing E-CPU `FiniteObserverLaw` and the observer-relative
machine is the existing `form_observer_machine`/ `verify_formed_machine`.
We neither require the source transition to be affine nor learn a law from
a short output prefix.

- Implementation: `mailcpu/counted_observer_stream.py`.
- Tests: `tests/test_counted_observer_stream.py`.
- CI: `.github/workflows/count-feedback-stream.yml`.

This extends the work in PEER-002 (affine fixed-number SEND events) and
NCR-STREAM-003 (nonlinear rank-draining sources) with a different algebraic
mechanism: a *recurring count transducer*.

## Observer semantics

A complete finite source law specifies the deterministic map of every
named action for every declared source state, plus finitely typed observer
fields. An intention declares:

- an initial state,
- an ordered, nonempty action word `w=(a_0,...,a_{r-1})`,
- ordered `EmitRule` entries, each with an optional source-action filter,
  an optional typed guard on an admitted observer field, the selected output
  field, and a mailbox name.

After each source action, the rules are evaluated in their declared order
against the **post-action** observation. A rule emits either zero or one
semantic event. Multiple rules and actions can emit multiple events in a
single word iteration. The event identity includes:

```text
(zero-based event ordinal,
 one-based word iteration,
 zero-based action position,
 mailbox,
 exact typed value).
```

Output delivery is not claimed by this mathematical observer.

## Exact quotient before the count

Construct the existing E-CPU minimum future-observation quotient `q` for
the union of all value and guard fields used by the observer's rules.

```text
q(T_a(s)) = Q_a(q(s))
O_selected(s) = D(q(s)).
```

`verify_formed_machine` checks this transformation against the complete
source table. The quotient is therefore a deterministic Ground that
preserves the future of **every selected emission predicate and value**
under any word of declared actions, rather than only the present readout.

For a chosen word, define:

```text
F : quotient state -> quotient state
E : quotient state -> ordered finite list of events per applied word
C : quotient state -> |E(state)|
```

The fundamental event-count composition is:

```text
(F2, C2) ∘ (F1, C1)
    = (F2 ∘ F1, C1 + C2 ∘ F1).
```

This is a cocycle: exact counts are transported with the state change.
It is associative, so count summaries admit powering, independently of
whether the source's original transition is linear.

## Exact event ordinal inversion

A deterministic endomorphism on a finite reachable quotient has an
eventually periodic orbit, including when it never becomes stationary.
Discover this *from the verified quotient transitions*:

```text
q_0, ..., q_(mu-1)     transient
q_mu, ..., q_(mu+lambda-1) recurring cycle
q_(mu+lambda) = q_mu
```

The state revisit proves all later state and emission behavior repeats
with period `lambda` under the same word, not only that a sampled
observation prefix happened to repeat.

Define `P` as the events in the transient, `R` the events within one
whole recurring period. Then:

```text
stream = P || R || R || R || ...

if |R| = 0: length = |P| (the infinite execution can have finite output)
if |R| > 0: length = infinity.
```

To find the zero-based emitted event k:

```text
k < |P|:
    select P[k] with its recorded word iteration and action offset
k >= |P| and |R| > 0:
    cycle_number, slot = divmod(k - |P|, |R|)
    template = R[slot]
    iteration = template.iteration + cycle_number * lambda
    event = (k, iteration, template.action_offset,
             template.mailbox, template.value)
```

The same proof yields cumulative count after any number `n` of
source-word iterations. If `n <= mu`, use exact transient prefix
counts. Otherwise:

```text
whole, rem = divmod(n-mu, lambda)
C_n = |P| + whole*|R|
      + (prefix_count[mu+rem] - prefix_count[mu]).
```

The receiver can independently reconstruct the quotient from the original
source law, rederive the cycle and event count, and check the exact requested
event. There is no need to replay the first k emissions.

### Concrete nonaffine feedback experiment

The source is a 3-bit nonlinear feedback shift:

```text
b0 = x & 1
b1 = (x >> 1) & 1
b2 = (x >> 2) & 1

T(x) = ((x << 1) & 7) | (b2 XOR (b0 AND b1) XOR b0)
```

Its second Boolean difference is nonzero:

```text
[T(3) XOR T(1) XOR T(2) XOR T(0)] & 1 = 1.
```

The source is genuinely nonaffine over GF(2). Beginning at state 1,
the exact orbit has **period 6** and never settles:

```text
1 -> 3 -> 6 -> 5 -> 2 -> 4 -> 1.
```

For two post-action rules, emit the low bit when low=1 and the high
bit when high=1. The six-word orbit produces the following six
emissions, with their word iteration:

```text
(1, low, 1)
(2, high, 1)
(3, low, 1)
(3, high, 1)
(5, high, 1)
(6, low, 1)
```

The independently derived query for event index `10^100+73` therefore
selects `(iteration=10^100+74, mailbox=low, value=1)`.
The output event is addressed by integer arithmetic over a six-state
period, not by executing `10^100` nonlinear transitions.

### Other exercised source families

- One word may contain two different actions, each followed by any
  applicable number of conditional emissions. Native reference stepping
  checks exact event order and count.
- A nontrivial two-state recurring cycle may be permanently silent even
  though a transient emitted an event. The resulting stream is *finite*
  although the source computation is infinite.
- A source with eight states and one unobserved retained bit has a
  **four-class future-observation quotient**: the hidden bit is not
  needed to answer the requested readout.
- Synthetic random total deterministic sources exercise event counts,
  group transitions, and requested output values independently of
  the compiled quotient.

## Proof and resource accounting

- Finite source: at most 64 states, 8 actions and 8 observer fields,
  admitted and content-addressed by the existing `FiniteObserverLaw`.
- Word length: at most 32 actions.
- Ordered emission rules: 1..16 per source action.
- Reachable quotient state count: Q <= 64. Preperiod plus period is at
  most Q; at most Q word iterations are compiled.
- Preprocessing: O(Q * word_length * emission_rules) predicate and
  transition evaluations, plus existing quotient construction/checking.
- Query: O(1) big-integer arithmetic operations after admission.
  Bit-complexity grows with the requested event index; up to 4096
  logical-coordinate bits are admitted.
- Memory: O(Q * word_length * emission_rules) templates.
- Each typed receipt is checked by an independent new construction of
  the observer quotient and counted orbit from the receiver's source,
  then compared canonically with the claimed event.

The emitted value is a finite declared scalar. This experiment does not
claim arbitrary-precision numerical state acceleration outside the finite
source table; the general compositional count identity is broader than
the specific finite-state cycle construction used here.

## Receipt and original intention

`CountedStreamReceipt` binds:

- original finite source fingerprint,
- future-observer quotient fingerprint,
- initial source state, action word, ordered emission rules and requested
  zero-based event index,
- selected word iteration, within-word action offset, mailbox and typed value.

`verify_counted_stream_receipt(receipt, source)` rebuilds the model and
checks the exact mathematical claim. Supplying
`expected_request=observer.request(k)` also checks that the answer
addresses the *receiving observer's original intention*, so a different
but mathematically valid event is not mistaken for the requested one.

Strict canonical packet parsing refuses duplicate keys, unknown fields,
unbounded integer encodings and type-ambiguous receipt variants. The
fingerprints are content identity rather than signatures; the caller owns
source provenance and any actual execution authorization.

## To Do: next nonlinear frontier

1. Replace finite-state cycle enumeration with an **algebraic count
   cocycle** represented by a compact invariant feature space.
   Seek feature closure simultaneously for `T`, selected `O`,
   event-count function `C`, and action-dependent output order.
2. Combine the VGI polynomial lift and NCR-007 exact Boolean Koopman
   observers with this `(F,C)` semidirect-product count structure.
   In a sufficiently closed feature Ground, powering counts and
   binary searching the source iteration can avoid source-state
   enumeration and handle large implicit non-settling systems.
3. Test observer-specific minimization when different internal cycles
   have identical future event streams. E-CPU's existing Moore quotient
   supplies the exact equivalence refinement for finite sources.
4. Admit resource-aware symbolic output values and later connect
   the mathematical observation receipt to E-CPU's Hypervisor,
   structural memory, delivery and quorum receipts.

The present implementation advances event navigation from
*affine loops* to *nonlinear systems that settle*, and now to
*nonlinear systems that keep changing forever*, while preserving an
independently verifiable observer-relative interpretation.
