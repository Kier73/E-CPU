# NCR-STREAM-003 — Verified nonlinear conditional observation streams

## Intent

A nonlinear computational source can produce an indexed semantic output without
evaluating every preceding source transition or materializing the intervening
communication log. This module constructs a receiver-owned observation Ground
from a source-pinned NCR-007 mathematical packet, rather than inventing a
competing nonlinear lift or enumerating all source states.

**Implementation:** mailcpu/nonlinear_observer_stream.py
**Tests:** tests/test_nonlinear_observer_stream.py
**CI:** .github/workflows/ncr-nonlinear-stream.yml

## Source and proof obligations

The receiver independently pins two identities:

- Reviewed Navigable-Compute Git revision
  559a1a813012d13ed37c04e2a117467e34ed3cb1.
- Exact SHA-256 of a canonical NCR-007 mathematical packet.

Before accepting the packet, the existing NCR-007 wire decoder reconstructs
the source polynomial law and least observer-Koopman feature Ground, and runs
independent verification of source polynomial identities, feature closure and
optional result, if included in the packet.

CI checks out the **exact** upstream Git revision, validates HEAD, and installs
the source before executing the receiver's tests. A source-commit string alone
is only a receiver-declared pin; in a different deployment, the operator must
also verify the installed package's provenance.

The model supports width 2–128 Boolean source variables (2^128 possible
states at the upper size), without full source state enumeration. Algebraic
closure is in F_2 Boolean polynomials, where x_i^2 = x_i. For exact source
transition T_a and observer projection O, NCR-007 verifies:

```text
phi(T_a(x)) = M_a * phi(x)
O(x) = D * phi(x)
O(T_word^n(x0)) = D * M_word^n * phi(x0)
```

The matrices are exact over GF(2); this is no floating-point fit.

## Conditional emission semantics

The source has a specified nonempty word of actions `word=(a0,...,am)`.
One iteration applies the entire word and then reads the admitted observer
bits from the resulting state. `value_bit` chooses the emitted 0/1 value.
If `gate_bit` is supplied, that iteration emits only when the selected
Boolean observer bit is 1. Every emitted event records its **emission ordinal**
and its distinct **source-word iteration**.

This is a mathematical emission definition, *not* a native MailCPU SEND,
transport enqueue, delivery or quorum commit. The mailbox label identifies
the selected semantic readout only.

For every NCR-007 generator, unprotected bits at tier r may depend only on
strictly higher active tiers; protected bits are unchanged. Hence after at
most `H = 1 + max(tier)` generator actions all active bits are zero,
regardless of initial source state. The implementation computes

```text
transient_word_iterations = ceil(H / len(word)).
```

It evaluates and retains at most that many words, checks the source is a
fixed point after the declared bound, and verifies that the fixed-point
source observer and feature Ground agree.

Let E be the transient emitted events and G the gate value at the fixed
point:

```text
G = 0: length = |E|; out(k) = E[k] if k < |E|, otherwise REFUSED.
G = 1: length = infinite;
       out(k) = E[k]                         if k < |E|
       out(k) = (iteration=Hword+1+k-|E|,
                 value=tail_observer_value) if k >= |E|.
```

The receiver independently rechecks the selected logical-time readout with
`navigate_nonlinear(family,ground,initial,word,n)` and the separate
`verify_nonlinear_result` implementation.

### Example

```python
from hashlib import sha256
from mailcpu import (
    admit_ncr_stream_ground, NCRConditionalObserverStream,
    verify_nonlinear_stream_receipt,
)

raw = source_pinned_ncr007_packet
pin = sha256(raw).hexdigest()
admitted = admit_ncr_stream_ground(
    raw, receiver_expected_sha256=pin, source_commit=reviewed_commit,
)
stream = NCRConditionalObserverStream(
    admitted, initial=initial_source_bits,
    word=(0,), value_bit=0, gate_bit=1,
    mailbox="research.observed",
)
receipt = stream.issue_receipt(10**100 + 173)
assert verify_nonlinear_stream_receipt(
    receipt, packet=raw, receiver_expected_sha256=pin,
    source_commit=reviewed_commit,
    expected_request=stream.request,  # receiver's original intended query
)
```

### Observation equivalence versus intention identity

Two genuinely different action words can yield the **same** selected output,
particularly after a rank-draining system settles. A receiver verifying only
the claimed mathematical word and event should accept either word if both
are independently correct: this is genuine *observational equivalence*, not
a broken numerical audit.

But if the receiving observer intended a particular word, gate, readout and
mailbox, accepting a mathematically valid **different** query would be a
request substitution. The `NonlinearStreamRequest` object fixes all five
request dimensions. Passing it as `expected_request=` requires that the
received receipt match the observer's original intention *and* the
independently verified source computation. Identity, observational meaning,
and host execution authority are therefore distinct evidence relations.

The receipt is an exact canonical content identity over the source pin, model
digests, initial valuation, action word, chosen emission condition and
value, output ordinal, source iteration, and projected bit. An independently
constructed false result fails receiver-owned reconstruction even if the
attacker recomputes the receipt's own SHA-256.

## Cost and evidence

Let H be the causal drain horizon, w the action-word length, r the exact
observer-feature dimension, and k the requested emission index.

- Source transient: O(H * source_operator_cost) with at most ceil(H/w)
  retained observations. For NCR-007 H <= 33 and the receiver applies an
  explicit budget.
- Output ordinal → source iteration: O(1) integer arithmetic after transient
  preparation, even for k=10^100.
- Independently checked readout at the selected distant iteration:
  O(r^2 log k) GF(2) bit-vector matrix products using NCR-007's exact
  linear feature Ground; construction and independent algebra verification
  have their own finite costs.
- No 2^width source-state enumeration.
- Logical coordinates are admitted up to 4096 bits. Declared width,
  action-word length, canonical packet size and transient budget are bounded.

Tests cover exact 4-bit and 128-bit nonlinear sources, a quadratic Boolean
interaction, no output at the settled state, permanently emitted tail, mixed
action words, direct independent source stepping, edited packet refusals,
self-rehashed false receipts and 10^100-indexed observations.

## Integration with PEER-001/002 and E-CPU WIRE-001

PEER-001: affine state navigation for native SET/COPY/ADD loops.
PEER-002: affine SEND stream indexing with fixed count per loop.
NCR-STREAM-003: verified Boolean nonlinear state + per-iteration conditional
0/1 emission with a rank-draining constant tail.
WIRE-001: existing receiver-pinned NCR source bridge to E-CPU's
INTENT-001 finite observer processors and local admitted execution.

The present module reuses NCR verification but does not yet materialize a
native MailCPU Program from the source or directly integrate the
Hypervisor, observer-fabric delivery, structural-memory checkpoint or
quorum publication. This separation ensures a distant mathematical
observation cannot be confused with a committed message delivery.

## Next experiments

1. Admit a heterogeneous source-operation and event-count transducer,
   preserving exact per-step/word emission counts under composition, even
   when a stable tail does not exist.
2. Adapt VGI's polynomial lift to native MailCPU MUL loops, with exact
   integer polynomial coefficient closure (not a sampled fit), extending
   the PEER-002 quadratic probe into a general bounded certificate.
3. Add compact symbolic expressions when a numerical answer would need
   too many bits to materialize (e.g. x^(2^n)).
4. Connect source-qualified stream readout receipts to E-CPU's
   observer Ground and Hypervisor admission, explicitly distinguishing
   a semantic SEND prediction from a network-committed effect.
