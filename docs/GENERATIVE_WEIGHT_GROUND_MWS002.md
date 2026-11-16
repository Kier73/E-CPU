# MWS-002 — Generative Weight Grounds: navigate, reconstruct, verify

**Status:** executable experiment, layered over [MWS-001](MODEL_WEIGHT_GROUND_MWS001.md). It does **not** provide model training, neural inference, universal weight compression, a new Hypervisor, or a new memory authority.

## Question

Can E-CPU recognize an exact trained-model snapshot as a **point in an architecture's parameter space**, then navigate its parameter coordinates using a representation more compact than a second dense weight copy, while preserving the *same* model identity and exact parameter bits?

A model parameter space is \(\mathcal{W}_A=\prod_i D_i^{s_i}\), where each tensor's dtype and shape belong to a specific model architecture Ground \(A\). The exact bit pattern \(\theta\) selects one point \((A,\theta)\). MWS-001 defines the point's identity from `space.identity` and ordered per-tensor **content** digests, independently of its storage pages or their chunk size. **MWS-002 keeps that exact identity ABI unchanged.**

The space of *describable* models is not a database of all models, and a cryptographic digest is not a decoder. Recovering exact weight bytes requires a source of the requisite information: stored pages, a previously retained snapshot plus differences, or a genuinely applicable, evidence-backed generating law.

## The three alternative reconstructions (plus a raw reference)

| Route | Source | Reconstructed property | Retained assumptions |
| --- | --- | --- | --- |
| `stored` | An existing MWS-001 snapshot + `ComputationalObjectStore` manifest | The original tensor bytes | Source pages remain available and verifiable |
| `replacement` | Exact MWS-001 snapshot plus bounded sorted (flat index, exact bytes) replacements | A different exact parameter point | Original snapshot and recorded edited coefficients must be available |
| `structural-law` | An **already admitted**, revision-pinned E-CPU `StructuralMemoryRegistry` generator | Exact byte sequence at selected generator coordinates | Receiver registry, revision, certificate and context remain verifiable; law's actual scope is retained |
| `reindex` | Existing snapshot plus bijective axis index map | A new parameter tensor with exactly permuted bits | Source snapshot and bijection; **functional equivalence is not inferred** |

All numerical domains from MWS-001, including BF16, float8 and float32, are supported as **raw bits**. The structural law operates on their bytes, not on floating-point semantics. For example, an admitted `int` law may reconstruct a BF16 tensor's exact byte sequence, but it does not imply that the resulting BF16 numbers represent a useful trained model.

`GenerativeModelSnapshot` pins a recipe for *every* tensor; its identity is derived from reconstructed per-tensor contents using the MWS-001 formula. It refuses an `expected_identity` that does not match. No model is silently relabeled as a known checkpoint because its *shape* looks right.

### Bounded read / verification procedure

1. Resolve the declared typed `ModelParameterSpace` and exact tensor name, dtype and contiguous row-major coordinate.
2. For a stored, replacement or reindex route, resolve the **pinned** MWS-001 source snapshot and its existing `ComputationalObjectManifest` pages. Every page read is SHA-256 validated by `ComputationalObjectStore`.
3. For a structural-law route, call the existing receiver registry's `read_revision_range(memory_id, revision, coordinate, length)` and compare receipt identifiers for the **spec**, **certificate**, **context**, **revision** and **range**; never call an unregistered generative Python callback.
4. Generate only the touched bounded chunk(s), verify each reconstructed chunk against the recipe's committed SHA-256, and return the exact parameter bits. A full `verify_all()` additionally hashes every reconstructed tensor and checks its exact content digest.
5. `materialize()` streams verified chunks into E-CPU's **existing** `ComputationalObjectStore.put_stream()`, and reconstructs an ordinary MWS-001 `ModelWeightSnapshot` with the *identical* point identity. The recipe is a different **realization** of the same exact model point, not a new model Ground.

Recipes are immutable, portable, canonical-json descriptors. Their hash is an integrity identity—not an authentication signature or a proof about which observer was authorized to admit the structural law. Trusted E-CPU receivers retain those responsibilities. Stored `source_snapshot` references and Structural Memory revisions must exist at the **receiving host** or be made available through qualified mechanisms.

## Functional equivalence and model symmetries are separate

In-Formation-Space [WSP-002](https://github.com/Kier73/In-Formation-Space/tree/main/experiments/verified-weight-space-realization) previously established *finite-observation* equivalence between selected networks after permutation and positive rescaling of hidden units, including a negative control. MWS-002 implements a **pure index permutation** of one tensor's bits. In its small two-layer ReLU test, compensating permutations of the first layer's rows, hidden biases and second layer's columns retain the chosen finite output observations, while a noncompensated transformation changes the function.

This is **not** a universal transformer equivalence theorem. Attention, shared embeddings, tied parameters, quantization, rotary positions, normalization and nonlinearities require independently specified transformation rules and observation evidence. Use E-CPU `TranslationContract` and VGI proof obligations for each such claim; do not call a byte-reindex operation semantically equivalent merely because it is invertible.

## Exact test and refusal gates

- `target.identity == reconstructed.identity == materialized.identity`, with all source pages intact; change one BF16 coefficient by exact *bits*, not by float arithmetic.
- Full and random-access verification with SHA-256 chunk commitments; explicit per-query read budget and refused out-of-range coordinates.
- Reject modified source pages, absent source snapshots, changed recipe fields, stale Structural Memory spec/certificate identities, unadmitted revisions and incorrect trained-instance target identity.
- Demonstrate a 128 KiB **synthetic law-generated** tensor whose reconstruction descriptor is less than 10% of its raw byte length; report actual descriptor bytes rather than theoretical compression claims.
- Demonstrate a pair of verified compensated neuron permutations and an uncompensated negative control over a finite input domain.

The synthetic byte law is **not evidence that arbitrary pretrained neural weights are compressible by affine or periodic formulas**. In general, an exact description of arbitrary independently chosen parameter bits cannot be assumed shorter than the bits themselves. Hash identities cannot reconstruct missing, nonderivable information.

## Local reproduction

With the MWS-001 base branch and dependencies installed:

```sh
python -m pytest -q tests/test_model_weight_ground.py tests/test_generative_weight_ground.py
python examples/generative_weight_ground_demo.py
```

For a demonstration without a pretrained checkpoint, the example constructs a 32 KiB law-generated byte tensor and a separate BF16 tensor revised by a one-element bit patch, and independently materializes the exact target point through E-CPU's byte-object store and admitted Structural Memory.

## Research significance and continuation

An LLM checkpoint is not one undifferentiated trained-data blob. Each parameter tensor can have an independently chosen **evidence-backed exact realization route**; some weights may remain raw, some may be reference-and-delta encodings, and other computational relationships may admit exact generators. The model identity stays stable across these representations and across eligible observer-hosts.

Next, measure real checkpoint redundancy across revisions, tensor blocks, and quantization formats *before* adding any new compression family. For known functional symmetries, record explicit source/target model identities and a VGI/E-CPU semantic-observation contract. For huge checkpoints, introduce hierarchical manifest pagination rather than eagerly materializing all tensor digests or assuming unlimited storage resources. Finally, bind the resulting tensor coordinate receipts into the Virtual Processor's native neural operator, under existing E-CPU Hypervisor authority.
