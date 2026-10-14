# Procedural Model Specification

Specification of MailCPU's procedural decision model, its parameter generation, and its interface boundary.

Defined terms follow `docs/GLOSSARY.md`.

## 1. Scope

This document specifies the procedural decision model and its deterministic parameter generation. The implementation is self-contained with no external scientific runtime dependencies.

## 2. Provenance boundary

The four-round Feistel address permutation is implemented in `mailcpu/vl_procedural_primitives.py`.

The construction is:
1. Contained in a single self-contained module.
2. Free of external third-party dependencies.
3. Reversible, with inverse operations verified by tests.
4. Scoped to reversible address permutations over non-cryptographic domains.

The primitive is internal and is not exported from the package root.

## 3. Model specification

`ProceduralDecisionModel` generates parameters deterministically from an address rather than storing a static weight matrix:

```text
parameter = W(model_seed, namespace, logical_address)
```

The generator configuration is finite and checkpointable:

```text
F = (model_name, seed, feature_bucket_count, temperature)
```

Replay requires only the model identity and generator parameters.

## 4. Evaluation pipeline

```text
state
  -> canonical tokens
  -> addressable feature and criterion weights
  -> typed Choice, Score, and Noul probabilities
  -> deterministic confidence values
```

## 5. Decision integration

The procedural classifier acts as a proposal mechanism within the control plane. The hypervisor applies deterministic capability checks and policy gates to all proposals.

When generated transitions are evaluated against the transition algebra, agreement on the witness set confirms execution correctness. Exact process semantics are governed by the primary transition algebra.

## 6. Structured state

Model behaviour is specified as a generated decision field together with model identity, the feature-address rule, probability normalisation, and a journal receipt.

## 7. Model extensions

1. A bounded procedural feature registry where addresses are named by OS ABI fields.
2. A comparison runner that evaluates procedural decisions against deterministic policy fixtures.
3. Attention and recurrence adapters maintaining deterministic trace equivalence with the transition algebra.
