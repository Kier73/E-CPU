# MWS-001 — Snapshot-indexed Model Weight Grounds

**Status:** executable, bounded research implementation. A Ground for *parameter coordinates and representation identity*, not a claim of automatic inference, weight generation, training-history recovery or universal functional equivalence.

## Question

Can a model snapshot be treated as an exact address within a virtual Ground describing the space of model architectures and parameter values, and can E-CPU reconstruct selected weight values by navigation rather than requiring a conventional inference process to own the entire model?

**Yes, when the snapshot has complete, verified parameter bytes (or an independently verified generator that can reproduce them).** The space itself can be represented by a grammar without enumerating its points. A digest alone cannot supply missing unpredictable trained bits.

## Model-space mathematics

For each admitted architecture \(A\), let its tensor schema be \((n_i,d_i,s_i)\), where \(n_i\) is a name, \(d_i\) an explicit bit/byte representation and \(s_i\) a finite shape. Its representable parameter space is

\[
\mathcal{W}_A=\prod_{i=1}^k\mathcal{D}_{d_i}^{\mathrm{prod}(s_i)}.
\]

The cross-architecture collection \(\mathcal{M}=\bigsqcup_{A\in\mathcal{A}}\mathcal W_A\) is a **disjoint family** of parameter spaces, not one vector space that requires all models to share a shape. E-CPU does not materialize \(\mathcal{M}\). A snapshot is a parameter-space point selected by a pair

\[
\mathrm{Address}_{\rm snapshot}=(H(A),H(\{n_i,H(W_i)\}_i)),
\]

and a concrete parameter address is \((H(A),H(W),n_i,(j_1,\ldots,j_r))\). The stored tensor manifest maps the last coordinate to an authenticated content-addressed byte range. The point's identity depends on tensor **content**, not page size, local storage, host, or inference engine.

Tensor reading is **exact bit navigation**. It is not automatically a numerical proof, a behavioral interpretation of a parameter, or a proof of functional equivalence to another snapshot.

### Two distinct navigation relations

1. **Exact instance navigation:** choose an architecture, an exact committed snapshot identity, and a tensor coordinate; return the original bits with a verified byte-page and snapshot binding. This works for any *supported and fully supplied* parameter representation and need not materialize every tensor.
2. **Semantic/functional navigation:** prove that a transformation between two parameter points preserves a declared observation or objective. Known symmetries (such as certain hidden-neuron permutations or compensated rescalings) can be valid under exact architectural conditions. In-Formation-Space WSP-002 already demonstrates such bounded equivalence transformations. Arbitrary interpolation, approximate similarity, or a matching tensor hash is **not** an equivalence certificate.

There are potentially further navigation strategies: sparse deltas from a checkpoint, a certified generator with seed/parameter law, low-rank factorizations, equivalent representation orbits, structural operator compilers, and trained-weight transition chains. Each requires its own construction method and verification. A training endpoint does not disclose its unique trajectory; many initializations, stochastic choices and dataset orders can lead to similar or identical final parameters.

## Implemented components

`mailcpu/model_weight_ground.py` deliberately reuses existing E-CPU services:

- `ModelParameterSpace` — typed, exact model-family tensor-coordinate Ground, with canonical `RepresentationRef` identity.
- `ModelWeightSnapshot` — exact tensor-content hashes bound to `ComputationalObjectManifest` descriptors produced by existing `ComputationalObjectStore`. This is an index/reference, **not** StructuralMemoryRegistry admission.
- `ModelSpaceNavigator` — select a committed reference and read a requested coordinate; returns exact raw bytes and object/parameter identity. A request for an unknown model or coordinate refuses rather than guessing.
- `ingest_safetensors_snapshot` — stream single or multi-shard, locally provisioned Safetensors snapshot tensors into E-CPU's existing page store, verifying header geometry and an optional `model.safetensors.index.json` mapping. BF16 and other byte-aligned tensor elements retain their exact bits. No arbitrary Python checkpoint execution.
- `verify_all` — verify every parameter object's full SHA-256 without assembling a monolithic model byte array.

**No duplicate page backing, Hypervisor, Ground-certifier, or state-lineage service** is introduced. Snapshot indexing does **not** grant execution rights. The authoritative model/session admission, numerical operators, observer receipts and recovery high-water remain their existing E-CPU responsibilities.

### Executable reconstruction

Run:

```bash
python examples/model_weight_ground_demo.py
python -m pytest -q tests/test_model_weight_ground.py tests/test_model_weight_ground_demo.py
```

The demo constructs E-CPU's **two distinct exact 10,000-parameter Boolean networks** (XOR and AND) from its existing `weight_space` module, stores both as parameter-space coordinates, verifies their snapshots, reconstructs actual weights from content-addressed objects, and independently checks their complete four-case input domains. Two output coefficients differ; the model architecture Ground remains the same. This is a proof of snapshot-indexed reconstruction, **not** a trained frontier LLM.

## What this enables for pretrained models

For a locally provisioned BF16/F16/F32 model checkpoint, derive the architecture Ground from trusted model configuration + validated tensor inventory, stream its exact tensor payloads to E-CPU byte objects, and retain only their manifests in the model Ground. A later observer can navigate directly to a selected layer/expert/tensor/coordinate, under the appropriate authority and source provenance, without loading all weights. The same parameter point can be reconstructed on another qualified host if the corresponding content-addressed pages are available.

This is suitable for large MoE models: expert routing first determines which tensor objects to access; the model Ground resolves their exact contents. It does **not** imply that an unspecified provider can conjure missing weights, that all model families are currently interpretable, or that 235B model arithmetic is already virtualized.

For snapshots containing packed 4-bit/2-bit tensors or architecture-specific quantization, define a separate **bit-packing/scale semantics adapter** and independently check it before admission. This first implementation refuses unsupported packed dtypes rather than silently treating them as byte-aligned scalars.

## Next research frontier

1. Connect model/parameter Ground snapshots to `ComputationalSession` and recovery-lineage authority so the selected snapshot is committed and cannot be rolled back by a stale observer.
2. Integrate HFR/NSD tensor graph readers, VGI proof obligations and VP-003/VP-004 native sparse inference with these exact weight addresses.
3. Create verified **weight-transition** representations: sparse delta, stable low-rank update, quantized representation, symbolic parameter generator and mathematically valid equivalence orbit. Require exact byte identity after reconstruction, or an explicit bounded numerical/semantic observation contract where lossy.
4. Test with a pinned real pretrained multi-shard checkpoint, recording bytes moved, peak memory, number of admitted objects, and independent inference results.

A *generative* Ground whose law reproduces an exact trained weight tensor is stronger than a snapshot index. It can be sought and measured; it cannot be presumed. For arbitrary incompressible weights, the generator plus its data must still encode enough information to distinguish that exact instance.

## Related work

- E-CPU [`docs/WEIGHT_SPACE_PROGRAMMING.md`](WEIGHT_SPACE_PROGRAMMING.md), `mailcpu/weight_space.py`.
- E-CPU [`docs/COMPUTATIONAL_OBJECTS_AND_TIME.md`](COMPUTATIONAL_OBJECTS_AND_TIME.md), `mailcpu/computational_objects.py`.
- In-Formation-Space [WSP-002](https://github.com/Kier73/In-Formation-Space/tree/main/experiments/verified-weight-space-realization) (function-preserving weight-space orbits), [SRE-002](https://github.com/Kier73/In-Formation-Space/tree/main/experiments/sparse-encoding-landscape) (exact sparse encodings), and [HFR-002](https://github.com/Kier73/In-Formation-Space/tree/main/experiments/external_neural_structure_reading) (external tensor topology observation).
- VGI `virtual_ground_interpreter/vgi/neural_topology.py` for explicit, unresolved or verified proof obligations.
- Safetensors format specification: https://github.com/huggingface/safetensors#format.
