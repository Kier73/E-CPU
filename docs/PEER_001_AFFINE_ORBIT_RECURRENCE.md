# PEER-001 — Exact affine orbit and observed recurrence lift

## Origin and objective

This integration is derived from three peer explorations supplied as
`orbit_leap.py`, `bm_lift.py`, and `ec_probes.py`. The peer algorithms were
adapted to E-CPU's typed MailCPU instruction model and verification practices.

The new path connects **native instruction transitions → symbolic structural
Ground → exact orbit navigation** and, separately, **observed transitions →
candidate recurrence → independently checked conditional navigation**.

The two routes must not silently promote an observed fit to execution
authority.

## A. Symbolic orbit leap: a verified computational structure

Implementation: `mailcpu/affine_orbit.py` and
`tests/test_affine_orbit.py`.

The admitted native instruction fragment is `SET`, `COPY`, and `ADD`,
together with exactly one backward `BRANCH` and a terminal `HALT`.
The prefix, loop body, and suffix are finite affine maps on the homogeneous
register vector `x=(r_1,...,r_d,1)`.

```text
P = affine map of prefix
B = affine map of branch body (one iteration)
S = affine map of suffix before HALT
c = branch register
c(k) = c(0) + k * delta
n = least positive integer with c(n) = 0
x_final = S * B^n * P * x_initial
steps = prefix_length + n * (body_length + 1) + suffix_length
```

The proof requires the `c` row of `B` to be the identity in `c`
plus a constant and contributions from **unchanged registers only**.
If `delta != 0` and `-c(0)/delta` is a positive integer, its exact
iteration count yields `LEAP`. If no positive integer zero exists, the
same invariant yields `DIVERGES`. If the control/counter expression
cannot be proved in this fragment, the verdict is `REFUSED`.

No interpreter trace is synthesized; a leap returns final registers,
program counter, counted semantic steps, and the counter witness.

```python
from mailcpu.affine_orbit import leap_affine_loop

result = leap_affine_loop(program, initial_registers={"seed": 3})
if result.verdict == "LEAP":
    final_registers = result.register_map()
    exact_steps = result.steps
elif result.verdict == "DIVERGES":
    # Proven for the particular admitted pure-counter program.
    ...
else:
    # Outside this fragment or the allocation budget.
    ...
```

Exponentiation uses logarithmically many matrix multiplications:
`O(d^3 log n)` scalar operations for naive dense matrices. Integer-bit
cost remains independently relevant; `max_registers` and `max_bits`
admit bounded dimensions and coefficient arithmetic before each large
matrix multiplication. The bound is conservative; refusal makes no
semantic claim. No global execution step budget was increased.

## B. Recurrence observer: finite evidence, conditional future

Implementation: `mailcpu/recurrence_observer.py` and
`tests/test_recurrence_observer.py`.

For an observed exact sequence `s_0, ..., s_(N-1)`, Berlekamp–Massey
over rational numbers finds minimal order `L` and coefficients
`c_1, ..., c_L` fitting the observed window:

```text
s[k] = c[1]*s[k-1] + ... + c[L]*s[k-L]
every observed equation k >= L is re-verified
N >= 2*L + margin  (default margin = 3)
```

Verdicts:

- `WINDOW_VERIFIED`: all available equations are exact and the sample
  count exceeds the stated redundancy margin.
- `UNRESOLVED`: observation does not establish even that evidence level.

An observed fit is **not a mathematical proof about unseen samples**.
A deliberately corrupted next Fibonacci term demonstrates why a window
certificate must never authorize future state publication by itself.

Two independent evaluators implement conditional extrapolation:

- `nth_recurrence_matrix`: companion matrix power.
- `nth_recurrence_polynomial`: polynomial exponentiation in the
  characteristic quotient ring (Kitamasa-style reduction).

They agree for the same *assumed* recurrence. Their agreement does
not prove that the real system will continue obeying that recurrence.
The Fibonacci MailCPU test crosschecks the observed coefficients with
the independent symbolic affine map, which *does* establish the
relevant exact transition law for that program.

```python
from mailcpu.recurrence_observer import (
    infer_recurrence_window,
    nth_recurrence_matrix,
    nth_recurrence_polynomial,
)

window = infer_recurrence_window(observed_register_values)
if window.verdict == "WINDOW_VERIFIED":
    # Conditional prediction, never a quorum-authorized execution receipt.
    value_a = nth_recurrence_matrix(window.coefficients, window.samples[:window.order], 100)
    value_b = nth_recurrence_polynomial(window.coefficients, window.samples[:window.order], 100)
    assert value_a == value_b
```

Only exact integer/rational values are admitted. The evaluators have
an exact-rational bit-cost gate.

## C. Adversarial peer probes

Source: `ec_probes.py`. Results from its interpreter P1–P3, P5, P8–P10
probes were integrated into the earlier interpreter audit
(`docs/AUDIT_001_INTERPRETER_QUORUM.md` and existing conformance tests).

The still-open journal and resource findings are represented as
**strict expected-failure regression targets** in
`tests/test_peer_audit_probes.py`: non-string mapping key collisions,
tuple/list payload collisions, snapshot sequence coercion, nonfinite
number admission, and multiplicative integer bit growth under an
instruction-only step budget.

These tests remain explicit To Do work, not implemented fixes.
In particular, the existing canonical codec also stringifies dictionary
keys, so swapping the journal codec alone would not solve typed-key
injectivity. Historic journal snapshot compatibility requires an
explicit versioning and migration plan.

## Verification

```bash
python -m pytest -q \
    tests/test_affine_orbit.py \
    tests/test_recurrence_observer.py \
    tests/test_peer_audit_probes.py \
    tests/test_conformance.py
```

Dedicated CI: `.github/workflows/mailcpu-peer-orbit.yml`.

## Next experiments

1. Encode an admitted affine leap as a typed, versioned structural-memory
   witness with exact program digest and initial-state digest.
2. Enable an external observer to independently reconstruct the matrix
   and verify the counter proof before admitting a leap.
3. Connect exact leaps to the navigator and Virtual Layer through a
   capability-gated realization API rather than bypassing the Hypervisor.
4. Use recurrence windows for active observation selection (which sample
   can reduce uncertainty most?), preserving the distinction between
   empirical model and mathematically certified transition.
5. Resolve outstanding journal identity and cost-admission probes in
   their own backwards-compatible changes.
