# PEER-002 — Selective SEND observations and the nonlinear lifting frontier

## The question

Can an observer select the requested event of a potentially infinite MailCPU
execution without interpreting and materializing every preceding event?

The supplied peer experiment `send_leap.py` extends the affine state leaper
(PEER-001) from a final-state result to a **stream-indexed output readout**.
This integration retains that semantics while making distant observations
lazy, cost-admitted and independently reconstructable.

The relevant distinction is:

1. **Semantic observation:** compute what the native deterministic program's
   `SEND` log would contain at a declared zero-based index.
2. **Realization:** actually enqueue, deliver, acknowledge or commit the
   intervening messages through an E-CPU execution host or peer fabric.

The first can be answered without the second. Neither a stream-query result
nor its SHA-256 content identity is an authorization to claim delivery.

## MailCPU stream Ground

Implementation: `mailcpu/affine_stream.py`, exposed as
`AffineSendStream`, `StreamObservationReceipt`, and
`verify_stream_receipt`. Tests:
`tests/test_affine_stream.py`.

The admitted program has one backward `BRANCH`, a terminal `HALT`, and
only `SET/COPY/ADD/SEND` elsewhere. It is split at the branch:

```text
P = prefix              (affine state update, with ordered SEND readouts)
B = loop body            (affine state update, with ordered SEND readouts)
S = suffix before HALT   (affine state update, with ordered SEND readouts)
c = branch register
```

Each segment compiles into a homogeneous affine matrix and a sequence of
`(mailbox, row)` readouts. A SEND instruction does not change registers,
but registers may change between two SENDs in the same loop body, so each
readout row captures the exact program point.

Let `x0` be the homogeneous initial register valuation, `xp = P*x0`,
and `r_q` the q-th SEND readout in `B`. The q-th emission in the
zero-based loop iteration i is

```text
output(i,q) = (mailbox[q], r_q * B^i * xp).
```

Prefix sends read directly from `x0`. Suffix sends read from `B^n*xp`
only when a suffix observation is explicitly requested. A loop-free final
state is never eagerly computed.

The branch register must satisfy the exact invariant

```text
c(i+1) = c(i) + delta
delta depends only on registers unchanged by B.
```

If the counter first reaches zero at the positive iteration `n`, the
program terminates and the output count is known exactly:

```text
length = number_of_prefix_sends
       + n * number_of_body_sends
       + number_of_suffix_sends
```

If the counter never reaches zero, a loop with at least one SEND each
iteration has an infinite **semantic output log**, although its execution
never halts. A divergent loop with no body SEND can have only a finite
prefix of observable outputs.

When `delta == 0`, a starting counter of zero exits on its first body
iteration; a nonzero counter continues forever. Unproved counter dynamics,
other branches, input consumption (`WAIT`), arithmetic multiplication
(`MUL`), `COMPARE`, and `SYSCALL` are refused.

### Query API

```python
from mailcpu import AffineSendStream, verify_stream_receipt

stream = AffineSendStream(program, {"seed": 9}, max_bits=65536)
mailbox, value = stream.out(1_000_000)
evidence = stream.issue_receipt(1_000_000)

# Receiver with the exact program and starting valuation:
assert verify_stream_receipt(evidence, program, {"seed": 9})
```

The query performs `O(log i)` matrix products, plus source readout
compilation and the actual integer arithmetic cost. The resource gate
conservatively checks register dimension and coefficient/state bit width.
There is **no constant-time claim for constructing a number with
exponentially many output bits**.

The receipt binds typed instruction identity, the exact initial valuation,
indexed mailbox, and exact integer value; the receiver independently
recomputes the requested output. The SHA-256 digest is content identity,
not a remote signature or delivery receipt.

### Peer experiment and additional independent checks

The peer's generated 3,000-program experiment checks arbitrary prefix,
body and suffix SEND positions, including readouts interspersed with
register assignments and divergent pure-counter loops.

The implementation adds tests for: exact queue/reference agreement,
infinite streams, infinite computation with only finitely many emissions,
large finite horizons with cheap early observations, cost-budget refusal
only at the queried coordinate, and altered portable evidence.

Dedicated CI runs the new tests alongside the earlier PEER-001 and
AUDIT-001 conformance suites on Linux and Windows, Python 3.11 and 3.14.

## Nonlinear lift: what is already implemented elsewhere

The central generalization is to stop requiring the **machine state**
itself to transform affinely. Require only that the **observer's requested
feature space** close under the nonlinear source transition.

Let `T:X->X` be the source transition and `h:X->Y` the requested
output. Find an exact feature encoder `phi:X->K^d`, an exact linear
operator `M`, and a readout `D` such that

```text
phi(T(x)) = M * phi(x)       for every admitted source state x
h(x) = D * phi(x)
then h(T^n(x0)) = D * M^n * phi(x0)
```

This is an *observer-sufficient Koopman invariant subspace*, not a
claim that all nonlinear systems admit a small finite-dimensional
linearization.

### Existing reusable implementations

| Repo | Exact mechanism | Evidence and intended reuse |
| --- | --- | --- |
| Virtual-Ground-Interpreter GEOMETRY-FIRST-002/003 | Polynomial features over finite fields; full finite transition-domain checking, or sparse fitting with separately verified symbolic definitions | `vgi/polynomial_lift.py`, `vgi/sparse_polynomial.py`: candidate feature discovery and strict verification |
| Navigable-Compute NCR-007 | Source Boolean polynomial ANFs, exact pullback closure over GF(2), independently reconstructed feature matrix | `nonlinear_koopman.py`, `nonlinear_koopman_verify.py`: observer-specific nonlinear lifting beyond finite transition enumeration |
| E-CPU WIRE-001 | Receiver-pinned import and independent mathematical verification of NCR-007 source/ground/result packets | `cross_repository_nonlinear_ground.py`: typed source identity and existing inter-repository transport/admission |
| In-Formation-Space RCG-005 | Invertible polynomial encoding/decoding around a linear latent evolution, shared vector-time certificate | `conjugate_ground.py`, `capsule.py`: nonlinear conjugacy, portable reconstruction and independent-process verification |
| VL-64 nonaffine Grounds | Directly witnessed cycles and future-observation-preserving finite-state quotient classes | `discrete_ground.py`, `quotient_ground.py`: exact bounded-state or observer-sufficient fallback |
| VL-I NOC-001 | Nonlinear MLP sign decision from partial channels with a certified residual bound | `nonlinear_observer_cut.py`: inequality or decision observations when full numerical reconstruction is unnecessary |
| E-CPU LAW/INTENT | Field recurrence/cycle navigation, observer-equivalent finite-machine formation | `law_certifier.py`, `intention_formed_fabric.py`: pre-existing law and host-admission primitives |

All of these have distinct evidential scopes. A complete finite Ground,
an independently checked symbolic law, an observed recurrence window, and
an upper-bounded approximate readout should not share one unqualified
`CERTIFIED` label.

### A concrete infinite-integer nonlinear example

Consider the exact integer polynomial dynamics

```text
T(x,y) = (x + y*y, y + 1)
```

Although the first coordinate is nonlinear, the four-feature lift

```text
phi(x,y) = (1, y, y*y, x)
```

has **exact finite closure**:

```text
phi(T(x,y)) =
    [1, 0, 0, 0]   [1  ]
    [1, 1, 0, 0] * [y  ]
    [1, 2, 1, 0]   [y*y]
    [0, 0, 1, 1]   [x  ]
```

Each row is a polynomial identity over the integers:
`(y+1)^2 = y^2 + 2y + 1` and `x' = x + y^2`.
Therefore for an observation of `x_n`, a single row of `M^n`
is sufficient. This gives a concrete way to leap a native MailCPU loop
containing `MUL` *when that source law is independently proved*.

A separate Python exact-arithmetic check compared the powered matrix
with an independent sum-of-squares formula at logical timestamps
`0, 1, 2, 10, 10^12`, with equality in each check. With
`x0=2, y0=3, n=10^12`, the exact selected value is

```text
333333333335833333333339500000000002
```

The illustrative formula is

```text
x_n = x0 + n*y0^2 + y0*n*(n-1)
    + n*(n-1)*(2*n-1)/6
```

The repository's VGI implementation already offers analogous
polynomial-coordinate discovery in finite fields; NCR-007 supplies a
second, observer-directed construction based on Boolean polynomials.
The next integration should **reuse their verifiers** before
introducing an overlapping general-purpose symbolic ring.

### Where the lift may grow without bound

```text
x' = x*x
```

iteratively generates the polynomial observables `x^2,x^4,x^8,...`.
Over unrestricted integer states, no finite-dimensional span of
these monomials closes under pullback. This is a natural case for a
**compressed symbolic result**:

```text
x_n := x0^(2^n)
```

The symbolically represented number is compact; materializing all its
binary digits can require exponential resources in `n`. That
distinction should be encoded in the output contract, not hidden
inside a matrix-power benchmark.

Finite-field arithmetic changes the setting: states are bounded, so
a finite cycle or a sufficiently large polynomial feature basis can
provide an exact lift, with construction cost governed by the field
size and the observable quotient dimension.

## Next implementation sequence

1. **Source law and observer selection.** Accept a native MailCPU
   program, a declared observation (mailbox/value/threshold), and its
   semantic effect class. Extract a small symbolic source transition,
   but do not flatten unknown `WAIT` values into determinism.
2. **Witness-carrying lift selection.** Try an affine stream row, VGI
   polynomial closure, NCR Boolean ANF pullback closure, IFS conjugacy,
   then finite-state/observer quotient when appropriate. Each candidate
   identifies exactly what it preserves and what is required to verify it.
3. **Reader-owned verification.** Rebuild source/feature identities and
   verify `phi(T(x))=M phi(x)` by symbolic polynomial coefficients or
   exhaustive bounded finite-domain checking, not only a short fit.
   Observed recurrences are hypothesis generation until independently
   promoted by a structural proof.
4. **Indexed emission count.** Generalize the affine program's
   `prefix + n * body_count + suffix` to a certified event-count
   transducer. Conditional SEND requires exact event counts and
   order before a selected stream index can be inverted.
5. **Typed, resource-aware output.** Return either a materialized
   bounded integer, a compressed proof-bearing expression, a bounded
   inequality/decision, or a refusal. Distinguish computation cost
   from output materialization cost.
6. **Admission and persistence.** Bind the selected witness to E-CPU
   Structural Memory, the Virtual Layer and Hypervisor. State whether
   the result is a **semantic observation** or an **actual committed
   communication effect**; the latter still requires channel and
   quorum receipts.

The research objective is to choose the smallest exact computational
description sufficient for an observer's question, rather than forcing
the entire machine to fit one universal state representation.
