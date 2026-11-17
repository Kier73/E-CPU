# AGA-002 — Reuse the computational Ground instead of replaying its neural realization

**Status:** focused integration of *existing E-CPU mechanisms*, with source-pinned atlas dependency. Does not establish native full-language-model inference, universal equivalence, or a new Ground authority.

## Research question

If a finite mathematical intention has two architecturally different neural realizations, can the E-CPU preserve their verified observation relation and subsequently answer the same intention by a more direct Ground evaluation, **without replaying neural operations**?

This asks something different from running an LLM in an opaque host. It first tests the premise of virtual computation: **the meaning and observable result of a computational structure belong to its Ground, not the chosen implementation**. A realizer can be qualified once, while a later query can use an independently established relation better suited to the information requested.

The parent [AGA-001 atlas](AI_COMPUTATIONAL_GROUND_ATLAS.md) lists 108 Ground *descriptions*, not runnable laws. AGA-002 supplies one narrowly scoped, executable equivalence reuse recipe for atlas entry `model.compile`; all other atlas entries remain catalogued-only until separately qualified.

## Existing facilities actually used

| Existing API | Role in AGA-002 |
| --- | --- |
| `mailcpu.ai_ground_atlas.load / find / representation_ref` | Version-pin the catalogued structure and its inspected source anchors |
| `mailcpu.weight_space.compile_boolean_gate` | **Actually realize** the same exact Boolean function in two separate 10,000-parameter ReLU networks, with different hidden-layer topologies |
| `mailcpu.weight_space.boolean_gate_program` | The corresponding typed MailCPU program, independent of the neural architecture |
| `mailcpu.interpreter.ReferenceInterpreter` and `QueueInterpreter` | Independently run the exact native instruction semantics |
| `mailcpu.semantic_translation.program_representation_ref / RepresentationRef / ObservationContract` | Bind source and interpretation identity and projection comparison meaning |
| `mailcpu.observer_orbit.ObserverContract / ObserverReceipt` | Produce a native content-addressed, observer-contract-bound result for subsequent direct-Ground queries |

No new operator registry, scalar law family, portable byte store, scheduler, Hypervisor or execution backend is introduced. The adapter is not itself a grant of receiver capability.

## Exact evidence

Choose the Boolean domain `D = {0,1}^2` and Ground `G = XOR` or `AND`.

The existing compiler constructs the same exact relation through architectures `(2,85,112,1)` and `(2,17,254,21,1)`, **each with 10,000 declared parameters**. AGA-002 executes all four inputs for each network *and* both MailCPU interpreters, comparing them to the direct Boolean oracle. The resulting reusable certificate binds the atlas source revisions, source program identity, both parameter-content identities, the complete observed truth table, and the comparison scope.

For this very small Ground, four cases are an **exhaustive proof over its declared finite domain**, not merely held-out samples. For a large nonlinear model this is generally impossible, and numerical/statistical equivalence cannot silently inherit this exact certificate.

After independent certificate verification, `GroundReuseSession.query` selects the exact Boolean law. It invokes **zero neural forward evaluations per query** and emits an actual native E-CPU `ObserverReceipt`. The receipt is evidence for this observation; it is not a remote signature, a durable commit, or authorization to run code on another host.

## Try it on a full E-CPU checkout

```bash
python -m mailcpu.ai_ground_atlas validate
python -m mailcpu.ai_ground_reuse inspect model.compile --gate xor
python -m mailcpu.ai_ground_reuse certify xor --output /tmp/boolean-ground.json
python -m mailcpu.ai_ground_reuse verify --certificate /tmp/boolean-ground.json
python -m mailcpu.ai_ground_reuse query --certificate /tmp/boolean-ground.json --left 1 --right 0
python -m pytest -q tests/test_ai_ground_reuse.py tests/test_weight_space.py tests/test_ai_ground_atlas.py
```

The `certify` step actually executes native neural and interpreter realizers; it does not generate a result from invented assertions. Each new process independently rechecks the finite proof before serving queries, while a long-lived authorized process verifies once and performs subsequent exact symbolic observations. If a supplied certificate is merely rehashed after tampering, verification still refuses it because the existing independent E-CPU realizations must agree again.

## What the result does, and does not, mean

**It establishes (if native CI passes):** one concrete AI-derived mathematical Ground whose verified semantics survive alternative numerical/network representations. Subsequent observations need not replay an implementation's computation. A subject with 10,000 neural parameters can have a significantly shorter mathematical description for this specific task.

**It does not establish:** that arbitrary neural weights have a compact exact law; that a large Transformer may skip all attention/matrix operations without equivalent evidence; that the catalog is an admission authority; or that a particular passive communication medium performed the neural arithmetic.

The correct optimization policy is: **prefer a verified direct law where it exists; otherwise choose a verified compositional/numerical/path realizer; otherwise refuse and identify the missing observation or proof.** A request for `forward.attention` therefore returns an unresolved inspection rather than a fabricated direct evaluator.

## Next discriminating experiment

Use IFS `semantic_neural_compilation` and `tensor_cut_realization` to attempt the same form of *scope-preserving Ground factoring* on a nontrivial, real-parameter-bearing neural block. Derive which subrelations can be navigated directly, which require evaluated tensor cuts, and how the result is independently checked. If no compression is possible, record the negative result and preserve the existing E-CPU numeric realizer. For a frontier model, only an admitted, evidence-backed compositional rewrite—not the architectural ambition by itself—can justify bypassing neural work.
