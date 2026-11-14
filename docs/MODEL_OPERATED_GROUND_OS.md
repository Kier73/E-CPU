# USM-001 — A trained model operating E-CPU Grounds

**Status: operational experiment.** This is a model using real E-CPU services,
not an assertion that E-CPU already hosts arbitrary neural architectures or
that the model constitutes an operating system.

## Question

Can a trainable model use E-CPU as its operating environment, choosing when
to invest in Ground construction, while leaving evidence, admission and
navigation under the existing receiver-owned authorities?

The actual system call path is:

```text
observed integer stream
  -> E-CPU neural-lifter features
  -> trained logistic policy (advisory, portable checkpoint)
  -> request / defer Ground construction
  -> StructuralMemoryRegistry.propose_trace
  -> E-CPU recover_law and withheld witness verification
  -> explicit receiver-owned admission policy
  -> StructuralMemoryRegistry.read at a distant logical coordinate
  -> certified read receipt and independently checked source result
```

The model learns from **actual E-CPU certifier verdicts**, not manually
hard-coded labels. It does not receive file-system, network, executable-code,
or hypervisor authority. Its decisions influence *whether* to request a
service, never whether an unverified result should count as true.

## Run it

From repository root, on Python 3.11 or later:

```bash
python -m examples.model_ground_os
python -m pytest -q tests/test_model_ground_os.py
```

The runner trains an eight-input logistic policy from 24 streams (12 finite
affine modular traces, 12 deliberately nonlinear traces), then operates an
independent receiver-side StructuralMemoryRegistry with an explicit admission
policy. It asks for the value at logical coordinate
`1_000_000_000_137`, so the service must navigate rather than replay all
preceding states. It compares this result with an independent source formula.

The demo forces its two **source-oracle cross-check requests** at the caller
layer to avoid concealing an E-CPU refusal behind a model threshold. It also
runs eight **unforced, held-out requests**, letting the trained model choose
whether to attempt construction. Their teacher labels are computed afterward
for task-coverage and selection-accuracy reporting; they are not supplied to
the controller during its decision. For ordinary
calls, `operate_ground` obeys the policy's threshold. A trusted caller can
override a model false negative, but the override does not bypass E-CPU
witness or host authorization checks.

The output contains a JSON model checkpoint with SHA-256 identity, training
metrics, per-request model decisions, admission/read evidence, and an
independent source comparison. Every episode has a canonical digest. Model
checkpoints are independently revalidated before inference.

## Explicit experimental limits

- The task data are reproducible mathematical streams; they are **not**
  externally observed physical sensor measurements. The operation, however,
  genuinely invokes the existing E-CPU certifier, registry admission, and
  structural navigator.
- The model is a small trained classifier, **not** a language model, general
  policy agent, or trainable neural interpreter. No accelerator is required.
- The training labels are defined by *finite* witness agreement. A successful
  Ground is not a theorem about an infinite unseen sequence.
- The E-CPU memory service and the model currently share one process; this is
  an actual service integration, **not** a multi-host deployment test.
- The 8 input features were originally introduced for law-family prediction.
  This experiment tests their usefulness for ground-admission workload
  selection; it does not pre-assume useful hold-out accuracy.
- A model false negative may defer a useful Ground. This makes task coverage
  and caller override important service-level measurements, not correctness
  violations.
- A model false positive cannot directly authorize admission; refusal and
  verification are owned by the registry.
- The demo reports an independently computed result only for the known affine
  evaluation stream. Its purpose is to check a real navigational output,
  not to use this source formula as an E-CPU admission shortcut.

## Continuation: model-native E-CPU

1. **System calls:** expose a typed model-facing E-CPU ABI for observe,
   propose, read, compare, and recover, instead of a domain-specific example.
2. **Persistent cognition:** retain model checkpoint revisions and rewards
   as separate evidence from the certified Grounds; only update the model
   after audited feedback.
3. **Independent hosting:** run the model in a separate authenticated
   observer-host while E-CPU retains receiver-side admission.
4. **Cross-repository Ground:** have VGI independently interrogate proposed
   interpretations and IFS reconstruct the operation trace and its temporal
   provenance.
5. **Stronger learned model:** replace the tiny policy with a hosted
   executable neural Ground and evaluate whether it can operate this same
   capability-restricted ABI.
6. **Meaningful external workload:** connect to a permitted real source of
   observations, compare model-driven selection with exhaustive admission,
   and measure latency, cost, useful-answer coverage, accuracy, and recovery.

The foremost design principle is that the learned model may become an active
operator of the E-CPU environment, but it does not become the unchallengeable
source of its own evidence.
