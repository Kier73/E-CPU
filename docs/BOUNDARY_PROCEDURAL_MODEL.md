# Procedural Model Boundary

Normative specification of MailCPU's procedural decision model, its provenance
boundary, and the constraints under which a model may be substituted.

Defined terms follow `docs/GLOSSARY.md`.

## 1. Scope

This document specifies the procedural decision model, records the boundary
between MailCPU and the third-party material from which its design was studied,
and enumerates what is prohibited.

**REQUIRED** The wider third-party runtime is not imported. MailCPU has no
production dependency on it, and in particular no dependency on NumPy.

## 2. Provenance boundary

One narrow construction was adopted into the shipped package:
the four-round Feistel address permutation in `mailcpu/vl_procedural_primitives.py`.

**REQUIRED** The adopted construction MUST be:

1. narrow enough to be stated completely in one module;
2. dependency-free;
3. reversible, with its inverse verified by test;
4. scoped in its own module docstring to reversible address permutation over
   non-cryptographic domains.

**REQUIRED** The adopted construction MUST NOT be re-exported from the package
root. Its exports were removed from `mailcpu.__all__` because a self-described
non-cryptographic permutation at the public surface invites exactly the
misreading its scope statement excludes.

**REQUIRED** Adoption of any further third-party construction MUST satisfy this
clause. The test suite asserts the reversibility of the adopted construction.

## 3. Model specification

`ProceduralDecisionModel` regenerates every parameter from an address rather
than storing one:

```text
parameter = W(model_seed, namespace, logical_address)
```

The generator is finite and checkpointable:

```text
F = (model_name, seed, feature_bucket_count, temperature)
```

**REQUIRED** The model MUST NOT store a weight matrix.

**REQUIRED** Replay MUST require only the model identity and the generator
parameters.

## 4. Evaluation pipeline

```text
state
  -> canonical tokens
  -> addressable feature and criterion weights
  -> typed Choice, Score, and Noul probabilities
  -> deterministic confidence values
```

## 5. Refusal before acceleration

An accelerated or generated execution path is admissible only alongside a
precondition, a fuel limit, or a refusal path.

**REQUIRED** The procedural classifier is a proposal mechanism only. The
hypervisor applies deterministic capability and risk gates, and uncertain
decisions remain `REVIEW`.

**REQUIRED** A generated or leaped transition MUST match the ordinary MailCPU
transition algebra on a bounded witness set before **admission**. Executing a
generated path without this comparison is prohibited.

**REQUIRED** A procedural model MUST NOT alter exact process semantics. Where a
generated path and the ordinary algebra can disagree, the ordinary algebra is
authoritative.

## 6. Structured state

Model behaviour is specified as a generated decision field together with model
identity, the feature-address rule, probability normalisation, and a journal
receipt.

**REQUIRED** A decision MUST NOT be expressed as an opaque edge list or an
unjustified heuristic score.

## 7. Non-goals

The following are prohibited and are not items of outstanding work.

1. Importing the wider third-party runtime. Only the Feistel primitive is
   vendored.
2. Any claim of zero resident memory. The model holds bounded runtime memory for
   tokens and outputs.
3. Any Berry-phase, connectome, or universal-intelligence claim.
4. Any inference of learned weight semantics from a procedural hash.
5. Any override of capabilities, review thresholds, or journal integrity by a
   procedural model.
6. Any use of the vendored permutation as encryption.

## 8. Obligations

1. A bounded procedural feature registry whose addresses are named by OS ABI
   fields rather than by free text alone.
2. A comparison runner that contrasts procedural decisions against deterministic
   policy fixtures and records drift.
3. A procedural attention stage, admitted only after convergence, normalisation,
   and refusal tests exist.
4. A recurrence or leap adapter, specified separately from classification, which
   satisfies clause 5.
