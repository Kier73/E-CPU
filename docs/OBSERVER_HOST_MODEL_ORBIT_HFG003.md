# HFG-003 — Model-orbit continuity across observer-hosts

**Status:** source-level implementation / local tests. Native E-CPU, pretrained Hugging Face tensor acquisition and two independent GitHub Actions job realizations are explicit CI gates; this document is **not** a claim of successful federated model inference, physical-path tensor arithmetic or full-model generation.

## Continuity recovered from the repository, from origin to current experiments

The initial E-CPU commit (Oct 14, 2026, `672555ffbb591408509d267aebedf7de2cfba840`) held only a LICENSE. A subsequent substantive MailCPU README (`9f678ad71aabc2bed3a11c905021e2612f2c9f43`) defined a transition relation over `(pc, registers, mailboxes, output log)` and distinguished the transition's semantics from interchangeable communication transports. Thus, message paths and interchangeable realizers predate today's neural adaptations.

Mainline progression:

- MailCPU transitions, interpreter and Hypervisor: governed message effects, syscall state and explicit capability decisions rather than an unconstrained portable executor.
- ReliableChannel / mTLS / TCP fabric: authenticated transports and crash-resumable protocol sequence windows. Authenticated carriers supply evidence and routing; they do not acquire compute privileges by carrying messages.
- StructuralMemoryRegistry, `ContextualOrbitNavigator`, `ObservedOrbitPipeline`: description, observation, certified law selection, intention and direct/inverse navigation. Infinite-/large-horizon law queries avoid trajectory replay when the law's scope permits.
- `NavigableComputationDAG`, `TransitOrbitScheduler`, computational fabric, receiver-local `VirtualLayerRuntime`: typed frontier dependencies and qualified operator realization; transport and local execution authority remain different.
- `ComputationalObjectStore` (M1), `ComputationalSessionStore` (M3) and `RecoveryLineageCoordinator`: host-neutral state bytes, revision CAS, quorum-backed high-water and recovery. Their APIs already own byte storage and authoritative session continuation.
- `ground_native_realization`, `observer_path_evidence`, `latent_path_capacity` and `path_ground_probe`: observer-host/path characterization, qualified substitutions, first live TCP evidence, and explicit distinction between a passive carrier and an observed transformation locus.

Cross-repository progress:

- In-Formation-Space HFR/NSD reads exact pinned Hugging Face architecture and tensor-header relationships, with selected ranges fetched under budgets; IFS tensor-cut tests actual parameter-backed numerical operators.
- In-Formation-Space AKS-001–003 develops a multi-layer, multi-head **finite-field affine-kernel attention Ground** with sufficient prefix state and process-kill recovery through E-CPU M1/M3/quorum and native Hypervisor. Its compact state is *not* pretrained Transformer softmax or a true distributed multi-machine quorum; do not substitute its equations for Qwen3.
- VGI's proof and typed operator tools preserve exact semantic obligations and partial/unresolved status instead of interpreting a transport receipt as a theorem.
- Virtual Processor and E-CPU HFG-001/HFG-002 describe pinned MoE/dense model operation order and execute a *bounded single Qwen3 layer*, with a real layer's selected parameter bytes and explicit numerical policy in CI (as yet separately verified by the running workflow).

## Exact missing connection repaired

Before HFG-003, HFG-002's `NativeQwen3LayerHost.execute()` committed an attention/MLP E-CPU DAG and returned a **digest** of the hidden layer output, but discarded the actual output tensor on exit. The next observer could not consume a content-addressed predecessor Ground without recomputation.

HFG-003 adds **one optional, receiver-installed output hook** to HFG-002, called only after successful native Hypervisor admission, DAG completion and independent Torch comparison. It publishes the exact `<f4` hidden bytes in the existing E-CPU M1 `ComputationalObjectStore` and returns an immutable `model-orbit-handoff` record. The record binds:

- Hugging Face repo and immutable revision; HFG-001 model descriptor digest;
- Completed and next logical layer coordinates (no fixed total-model graph or VM image);
- Token position, sequence length, feature width and numeric dtype;
- Previous hidden-state digest, verified output digest, selected MWS-001 layer weight snapshot and native stage receipt digest;
- Existing M1 object manifest and previous handoff state digest;
- Its complete canonical content identity.

`resume_model_orbit()` verifies every field, exact model and next-layer coordinates, externally pinned high-water and stage-evidence digests, predecessor lineage, object pages and F32 tensor extent *before* releasing hidden values to the next realizer. Recomputed self-hashes are insufficient: `expected_state_digest` and `expected_native_receipt_digest` are supplied by an authority outside the received data. The function does not itself grant a Hypervisor right.

This is a **logical model-state handoff**, not a conventional machine snapshot, and it is independent of the architecture's parameter count at the interface. The selected numerical realizer remains HFG-002's dense Qwen3 operator; the method does not make unimplemented MoE/quantized attention kernels suddenly executable.

## Distinct GitHub observer-host test

The `.github/workflows/hfg003-observer-model-orbit.yml` tests distinct ephemeral GitHub jobs:

1. `ground-contract`: installs full E-CPU and runs existing HFG-002 plus HFG-003 tests. It *requires* actual HeadlessOS, DAG, object store, operator permission, and no compatibility stubs.
2. `observer-a`: inspects pinned `Qwen/Qwen3-0.6B@167b8104f88905a951069f5f95f9776908da5f68` using the pinned IFS HFR reader, fetches only 11 layer-0 parameter tensors (not whole model), executes native HFG-002, checks against Torch, commits its output into an M1 object backing, and exports the record and pages through an Actions artifact. Raw model weights never enter this artifact.
3. `observer-b`: runs on a **new GitHub job**, downloads the prior state artifact, receives the expected digest and native result pin through GitHub job outputs (separate from the artifact contents), re-inspects the pinned source, verifies M1 state, resolves only layer-1 parameters, and executes the second layer through its own fresh local Hypervisor. It emits a second layer Ground state referring to its predecessor.

This tests the **Github artifact/API path as a real communication and retention participant**, with two separate E-CPU operator realizers and no shared resident model-memory process. The job-output pins and artifact are both controlled by the same Actions workflow; they are not independent signed third-party authority nor evidence of an untrusted GitHub-origin witness. The artifact page backing is a test bridge for GitHub jobs; actual federated runtime should reuse existing E-CPU `RemotePageStore` and M3 high-water/quorum, not this helper as a new permanent storage system.

The initial hidden vector is an explicitly generated numerical stimulus, not a tokenizer-produced embedding or full user prompt. The two-layer test is not a complete decoder pass and does not retain KV cache for long-context incremental decoding. Local tests use synthetic BF16 weights; the real pinned pretrained-weight path is a separate hosted gate.

## Why this advances E-CPU's original ambition

The computation's identity is its **model Ground + token coordinate + data/parameter Grounds + verified transition chain**, not a dedicated CUDA device, server process, chip, or VM image. A host may become unavailable after commit, and another host can continue when it can resolve the required Ground and authorized realization. Attention state itself may be further transformed to a verified compact Ground where its exact law permits, following AKS's demonstration rather than imposing an affine approximation on Qwen softmax.

The goal is **not** to hide a model runtime behind TLS. It is to make the *state* and *observation* independently addressable through communication paths, then selectively realize only unresolved transformations. E-CPU can choose observer-hosts and path operations as their actual laws and permissions become known.

## Evidence ladder

1. **Described:** lazy Qwen3 layer Ground and full model address space, no arithmetic.
2. **Byte-bound:** HFR selected exact source tensor ranges and MWS-001 weight byte identities.
3. **Executed:** HFG-002 receiver-local numerical attention+MLP with native Hypervisor authorization.
4. **Verified:** independent Torch comparison and source/receipt integrity.
5. **Continued:** HFG-003 M1 output from A is read by B, and B executes layer 1, without A's resident memory or layer-0 reevaluation.
6. **Quorum-fenced:** requires follow-on integration with M3/AKS-003 under separate authority domains; not claimed here.
7. **Path-native arithmetic:** requires separately admitted transformation actually measured at the intended communication-path locus; not claimed here.
8. **Full-model generation:** requires embedding, all layers, final logits, token sampling and recoverable KV state; not claimed here.

## Reproduction

```
python -m pip install -e '.[dev]' numpy
python -m pip install torch==2.6.0 --index-url https://download.pytorch.org/whl/cpu
python -m pytest -q tests/test_hf_layer_realization.py tests/test_model_orbit_handoff.py
```

For actual hub tensors and **two different GitHub-hosted observer jobs**, run the PR workflow `HFG-003 two independent GitHub observer-hosts`. A successful CI run is required before reporting the real pretraining/observer-host continuity gate as verified.

## Next frontier after positive hosted evidence

Adopt *one authoritative M3 model session* and *AKS-003 recovery-lineage* for the same handoff format; move each page via already authenticated E-CPU transport rather than the Actions artifact bridge, kill both prior executor processes, and requalify a third path/observer. Then admit a mathematically valid sufficient-state Ground **only** for model components whose observations it proves. For Qwen softmax attention, maintain exact KV until a different Ground is proven observationally equivalent at the specified precision and context.

Do not infer universal acceleration, zero physical work, or exact trained weights from a model architecture alone. The objective is universal **semantic addressability and selectable authorized realizers**, with measured and minimized materialization, not predetermined dedicated hardware.
