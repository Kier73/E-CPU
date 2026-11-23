# AIG-001 — Addressable intelligence from externally hosted model structure

## The experiment

The motivating question is not whether a checkpoint was pretrained or
post-trained. It is **which information and operators actually determine the
requested behavior**, and whether observing that structure can construct
a smaller executable Ground or an entirely new model.

AIG-001 joins existing concrete implementations rather than building a
fourth inference engine:

- VL-64's original, historically acquired pretrained BF16 tensor-slice Ground:
  experiments/model_fabric/slice_ground.py and the recorded SmolLM2-135M
  source capsule (original trained norm row plus first four layer-0 Q
  projection rows).
- E-CPU's original finite intention-sufficiency planner
  mailcpu/intention_sufficiency.py, which searches for the lowest-declared-
  cost set of observations that separates relevant finite model states.
- VL-I's original GeneratedModelGround and GenerativeConversation, and
  Virtual-Layer-Dynamics' original compile_fsm_to_neural neural law
  construction and whole-domain exact-cell verifier.
- E-CPU's already-verified native HeadlessOS, M2 source admission and
  M3 session lineage/CAS with disposable real worker processes.

The original trained source is the archived VL-64 capsule from
Kier73/VL-64 at fea0d29d5a8a1edb03d9c66edd5ca4b15a1395d3:
experiments/model_fabric/datasets/2026-11-18-pretrained-bf16-slice-ground.json.

The original VL-I and VLD model generator sources are pinned at:
- VL-I 939b49291bb719ab531730088f759574db471c00
- Virtual-Layer-Dynamics 985ba5c2fbcc40842aed9f45f42587749620b98e

## Part A — One read can supply an executable model behavior

The actual original model tensor capsules have this geometry:

    G = 576 BF16 input-layer RMSNorm gain values
    Q = 4 x 576 BF16 pretrained layer-0 query projection weights
    initial observed trained payload = (576+4*576)*2 = 5,760 bytes

The original VL-64 source capsule is admitted and its exact trained BF16
bytes, original source witnesses, and source digest are verified. Its
original fixed numerical replay law is independently reconstructed
through current VLD's BF16 decoder, covering the original normalized
input, all four trained query coordinates, and an independent scalar
reference. The historical VL-64 runner exposes an older VLD import API;
this adapter preserves the actual original data and arithmetic while
using the current VLD numerical implementation.

A request for **which of two selected Q coordinates is larger**
does not need to compute the entire 4-row query projection.

For input h (width 576) and learned rows q_i and q_j, with positive
RMS denominator d(h),

    y_i(h)-y_j(h)
      = sum_k (q_i[k]-q_j[k]) * G[k] * h[k] / d(h)

and therefore

    sign(y_i-y_j)
      = sign(sum_k a_ij[k]*h[k])
    a_ij[k] = (q_i[k]-q_j[k])*G[k]

The Virtual Layer can construct the **trained direction a_ij from
an observation of two Q rows and the gain**. The logical training
information needed for this compiled question is

    two BF16 Q rows + BF16 norm gain = 3*576*2 = 3456 bytes

The historic original capsule already contains all 5,760 bytes and
is independently verified; 3,456 is therefore the *logical subset*
contributing to the new operator, not a claim that the original
pretrained source host transferred only 3,456 bytes. Repeated
execution reads zero new remote model bytes after the Ground has
been admitted.

### Exact stopping certificate

BF16 coefficients and finite IEEE input floats are exact dyadic
rationals. AIG-001 integerizes both without approximation.

Let A_k and X_k be integer-scaled coefficients and input vector.
A proposed prefix evaluates

    S_K = sum_{k in K} A_k X_k
    R_K^2 = (sum_{k outside K} A_k^2)
            (sum_{k outside K} X_k^2)

Cauchy-Schwarz proves the sign when

    S_K^2 > R_K^2.

This is an **exact integer predicate**, including boundary tests.
The model can stop before evaluating any unneeded dot-product
coordinates. For an unresolved prefix it continues; after all
coordinates, exact zero becomes a tie.

The result is a proof-carrying behavioral observation with
original pretrained model/revision/source digest, compiled
direction digest, input digest, selected coordinate count,
remaining squared bound, dyadic denominator and winner.

The full 4-row trained projection is separately calculated as an
independent FP64 numerical reference on new held-out hidden
vectors. Exact-real sign and a particular FP64/BF16 kernel can
differ near a rounding tie; that case needs a specified tolerance
or exact reference fallback for strict bitwise kernel parity.

The resulting model **is not a copy of the full language model**.
It is a newly formed exact operator for a precisely stated
pretrained behavior, executable independently of the original
host on arbitrary admitted hidden inputs.

## Part B — From observed behavior to generated neural intelligence

AIG-001 supplies multiple genuinely observed model preferences
(including different outcomes) to the original VLD transition
system compiler. Each distinct hidden vector gets an observed
state coordinate. Two actions, inspect and advance, are derived
from the finite observed environment. Output channels encode the
observed pretrained pairwise winner and whether its partial
coordinate evidence was sufficient.

The original VL-I/VLD compiler creates new **integer ReLU neural
weights** from that state/action law, then checks every cell of
the entire finite domain against the independent descriptive
oracle. No original pretrained network parameters are copied into
the newly generated neural model.

The generated model is free to produce future transitions within
this *admitted finite observed environment*. Its causal turns and
new text/code/byte-token response views can be maintained by
the original VL-I GenerativeConversation and E-CPU M3.

Generalization to unseen continuous hidden inputs is provided
by Part A's exact compiled trained direction, **not** by falsely
claiming the finite neural FSM has learned the entire source
model's language semantics.

These are two **complementary executable intelligence forms**:
the original source-conditioned operator that works on new
hidden vectors, and a newly formed stateful neural processor
from qualified behavioral observations.

## Part C — E-CPU observer-host and source continuity

The finite exact E-CPU sufficiency planner chooses an allowed
trained pair-readout capability rather than the full 4-row
projection for the requested finite source decision. Its cost
units are declared symbolic access costs (3 versus 5),
not measured latency or energy, and E-CPU's original
independent resolution verifier rejects unqualified reports.

The generated neural model runs through E-CPU's existing
VLIGenerativeModelAdapter and VLINeuralModelSessionBackend
without introducing a second quorum or alternate model
execution authority.

A worker is admitted against the original whole VL-I and VLD
source manifests; the original compiled neural model and
conversation checkpoint are stored in a native E-CPU HeadlessOS.
A new real worker process reconstructs source description,
generated model weights and prior complete causal history
before running its next original VL-I neural transition.
Original M3 revision CAS decides whether the new state can
replace the current accepted state. Original living TIME-001
temporal Ground remains in the same OS unchanged.

Thus the new procedural Ground does not inherit a particular
Python worker's lifespan.

## Verification contract

Tests in tests/test_addressable_intelligence.py exercise:

1. Actual archived pretrained BF16 slice source with original
   VL-64 numerical replay and pinned source digest.
2. Partial, integer-certified trained pair preference against
   independently recomputed full 4-coordinate original
   BF16 projection.
3. Held-out real vectors not present in the finite generated
   state machine; numeric comparison and correct source binding.
4. Missing/changed source, forged coefficients, forged
   observer reports and nonfinite input refusal.
5. Existing finite E-CPU minimum-observation proof and
   independent resolution verification.
6. Original VL-I/VLD synthesis of a new neural Ground from
   genuinely observed pretrained subgraph outputs, with
   exhaustive finite transition equivalence.
7. Real independent original VL-I neural interpreter subprocess
   replacement under original M3 session/quorum; generated
   neural identity, prior turns and living temporal state
   remain unchanged.

### Measured benchmark

scripts/benchmark_addressable_intelligence.py executes the actual
original-model readout and the newly generated original VL-I neural
processor on one runner. It freezes 64 held-out hidden vectors, measures
cold model-observation admission and compiled-direction construction
separately from warm full 4-row dense FP64 reference evaluation and
exact integer-certified pairwise navigation, and measures original
VLD neural formation plus four actual VL-I stateful turns.

Its JSON receipt includes per-model/source hashes, exact historical
trained payload bytes (5,760), logical source bytes relevant to the
intention (3,456), zero new remote weight reads, held-out
numerical sign matches, early-stop frequency, mean/min/max dot
coordinates, and observed wall time for each execution mode.
The two warm methods have different arithmetic and Python
overheads: a small-coordinate count alone is **not** evidence
of wall-clock speedup. The benchmark reports both outcomes.

CI stores one full JSON artifact per Linux/Windows and Python 3.11/3.14
environment, enabling exact independent replay of all reported
source and behavioral identities.

    python scripts/benchmark_addressable_intelligence.py \
      --trials 64 --out artifacts/addressable-intelligence-benchmark.json

Cross-platform CI:
https://github.com/Kier73/E-CPU/actions/workflows/addressable-intelligence.yml

### Reproduction

The workflow checks out the exact original VL-64 revision,
installs pinned original VL-I and VLD, and runs:

    python -m pytest -q tests/test_addressable_intelligence.py

Additional original E-CPU neural M3 and intention-sufficiency
tests are run in the same Linux/Windows Python 3.11/3.14 matrix.

### What this changes

The described behavioral operator can be executed without
loading a whole pretrained model, and a separate new neural
model is created from hosted-model observations without
inheriting its training history or weight representation.

This offers a direct basis for an **intention-addressable model
fabric**, where source information and observer context
are the input to processor construction rather than merely
the input to a conventional model inference API.

## To Do — progressively richer formed intelligence

- Replace the retained fixed trained slice with arbitrary
  qualified HF tensor coordinates, fetching exactly missing
  source ranges from source-authenticated E-CPU observers.
- Extend partial-coordinate completion to other model
  functions, attention, routing, causal memory and outputs
  under conservative numerical interval certificates.
- Link the retained learned directions, source-byte
  coordinates, generated neural operators and causally
  accepted states into one navigable multi-intention index.
- Introduce active observation and law induction for
  *unseen environments*, with independent held-out
  verification and counterexample-driven refinement,
  beyond a finite previously sampled behavior table.
- Test richer generated language and coding behavior,
  causal continuity across independent physical machines,
  and independently authenticated source/observer receipts.
- Measure cold construction, every source/network byte,
  actual hardware wall time, mathematical operations,
  page reuse, fork/rehome latency and quality on
  held-out real world tasks.

The governing principle is simple:

    A read is a run when the admitted observation or
    executable law suffices to realize the intention.

If the observation cannot determine the behavior, the
next operation is to navigate toward additional
necessary information rather than silently inventing
an answer.
