# External Classifier Boundary

Normative specification of the boundary between MailCPU and externally
supplied classifier models, including the refusal rules that constrain how model
output may be used.

Defined terms follow `docs/GLOSSARY.md`.

## 1. Scope

This document specifies what may be inferred from publicly documented external
classifier contracts, and what MailCPU refuses to infer.

**REQUIRED** No claim is made that the private weights, training corpus,
serving stack, or low-level architecture of any external classifier has been
reproduced. Where an external implementation is undisclosed, MailCPU treats its
interior as unavailable and uses only its documented surface.

## 2. External sources

The public contract is drawn from TypeSafe AI's published documentation on
System One models and the Jev model:

- [Introducing System One models and Jev](https://typesafe.ai/blog/introducing-system-one-models-and-jev)
- [Documentation: Introduction](https://docs.typesafe.ai/introduction)
- [Choice primitive](https://docs.typesafe.ai/primitives/choice)
- [Score primitive](https://docs.typesafe.ai/primitives/score)
- [Noul primitive](https://docs.typesafe.ai/primitives/noul)
- [Confidence](https://docs.typesafe.ai/confidence)
- [Patterns](https://docs.typesafe.ai/patterns)

MailCPU treats the interior of the external model as undisclosed. Where the
documentation is ambiguous, MailCPU resolves toward refusal rather than toward
an assumed reading.

## 3. Observable contract

The documented contract is:

```text
unstructured state + typed question(s)
  -> typed probabilistic answer(s) + confidence
```

| Primitive | MailCPU representation | Governing mathematics |
|---|---|---|
| Choice | finite named options | `p_i >= 0`, `sum_i p_i = 1`; `c = (p_max - 1/n) / (1 - 1/n)` |
| Score | ordered levels | `m = sum_i i * p_i`; confidence decreases with `sum_i p_i * abs(i - m)` |
| Noul | binary proposition | `p = P(true)` in `[0, 1]`; operational thresholds remain in code |

The documentation describes evaluating multiple questions against shared state
independently, then composing their results in ordinary code.

**REQUIRED** A model MUST propose typed evidence only. Composition and
authority determination MUST be performed by a reviewable policy function
outside the model.

## 4. MailCPU control plane

```text
HypervisorRequest.state()
  -> Choice(domain) and Noul(danger)
  -> HypervisorPolicy
  -> ALLOW | REVIEW | DENY
  -> EventJournal receipt
```

Two models implement the `ClassifierModel` protocol:

| Model | Role |
|---|---|
| `LexicalDecisionModel` | Deterministic local reference model; the test oracle |
| `ProceduralDecisionModel` | Default model; parameters generated from a checkpointable model seed |

Both implement the same protocol.

**REQUIRED** Substituting one model for another MUST NOT alter authority,
resource, or receipt semantics.

## 5. Refusal rules

Model output is never authority. The following rules are unconditional.

**R-1** A request whose required capability right is absent from the kernel
capability graph is denied. This holds regardless of model confidence.

**R-2** An ambiguous domain classification is routed to review.

**R-3** A classification below the confidence threshold is routed to review.

**R-4** A destructive request requires both a higher confidence threshold and a
low danger probability.

**R-5** Only an explicit `ALLOW` reaches a registered handler.

**R-6** Every decision is appended to the OS hash-chained journal before the
reply is returned.

**R-7** An unavailable, nondeterministic, or distribution-shifted model yields
review or refusal. It never yields an implicit host-side operation.

## 6. Protocol stages

The control plane is specified as four separable stages.

1. **State construction.** Canonicalise the request, resource identity, payload,
   capability sets, and declared risk.
2. **Typed inference.** Evaluate bounded questions independently against the
   shared state.
3. **Policy gating.** Apply deterministic thresholds and hard capability rules.
4. **Execution and evidence.** Dispatch approved operations and append the
   receipt before returning it.

Stages 1, 3, and 4 are native MailCPU state transitions and are independent of
which model serves stage 2.

## 7. Retained risks

Confidence is not correctness. A high probability does not establish that the
selected domain or action is safe.

**REQUIRED** The hard capability boundary and the destructive-operation review
gate remain mandatory even when a model reports certainty.

**REQUIRED** A model MUST NOT be permitted to override capabilities, review
thresholds, or journal integrity.

## 8. Obligations

1. Typed request schemas for filesystem, service, network, process, and package
   operations.
2. Handler adapters, admitted one domain at a time, each satisfying rules R-1
   through R-6.
3. Replay and adversarial-input testing for every admitted adapter.
4. Evaluation of learned or remote models against the reference behaviour, and
   only after obligations 1 through 3 hold for the deterministic model.

## 9. Non-goals

1. Reproduction of any undisclosed external model architecture.
2. Granting a model authority over the host, over capabilities, or over journal
   integrity.
3. Treating model confidence as proof of safety.
4. Defaulting to execution on model unavailability.
