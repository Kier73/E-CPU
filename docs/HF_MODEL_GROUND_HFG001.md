# HFG-001 — Hugging Face model descriptions as navigable E-CPU inference Grounds

**Status:** executable architectural Ground compiler; **not** full neural inference. It does not fetch/verify model parameters, execute any neural operator, claim generated weights from model configuration, or certify network access. The intent is to use existing E-CPU and In-Formation-Space components, not emulate a conventional GPU graph or create a second Hypervisor.

## What was actually obtained from Hugging Face

The checked-in `examples/hf_pinned_model_configs.json` records selected **configuration facts transcribed from the indicated pinned Hugging Face config pages**, not verified raw-file SHA-256 digests. The pinned URLs are included in the records and must be re-read before numerical admission. The accompanying Qwen3 235B generation parameters are from a pinned `generation_config.json`. No tensor payload bytes or real HFR Safetensors header inventory were acquired during the preparation of this file, because this source environment cannot connect directly to the Hub.

| Model | Revision | Layers | Experts | Active / token / layer | Q heads / KV heads | Distinguishing Ground semantics |
|---|---|---:|---:|---:|---|---|
| `Qwen/Qwen3-235B-A22B` | `58ccb6e3fb22606f13e07de68b71f8fbce40a375` | 94 | 128 | 8 | 64 / 4 | BF16, Q/K RMSNorm, RoPE, router `softmax(all)` **before** top-k with renormalization |
| `Qwen/Qwen3-30B-A3B` | `e187836637046dedaf8a1f27c91bf65c5175cc97` | 48 | 128 | 8 | 32 / 4 | Same Qwen3 MoE semantic family, separate exact configuration and parameter Ground |
| `openai/gpt-oss-120b` | `9079e2a2391682aef7ce729f88da00a3160f16da` | 36 | 128 | 4 | 64 / 8 | alternating local sliding/full attention, attention sinks, YaRN, MXFP4 expert weights and biases, router **top-k(logits)** then `softmax(selected)` |

Source files: 
- https://huggingface.co/Qwen/Qwen3-235B-A22B/blob/58ccb6e3fb22606f13e07de68b71f8fbce40a375/config.json
- https://huggingface.co/Qwen/Qwen3-235B-A22B/blob/58ccb6e3fb22606f13e07de68b71f8fbce40a375/generation_config.json
- https://huggingface.co/Qwen/Qwen3-30B-A3B/blob/e187836637046dedaf8a1f27c91bf65c5175cc97/config.json
- https://huggingface.co/openai/gpt-oss-120b/blob/9079e2a2391682aef7ce729f88da00a3160f16da/config.json

Reference semantics cross-checked with Hugging Face `transformers` sources `src/transformers/models/qwen3_moe/modeling_qwen3_moe.py`, `src/transformers/models/gpt_oss/modeling_gpt_oss.py` and their configuration classes. Those **reference-source** versions must be pinned again before numerical acceptance; an evolving upstream `main` is not sufficient to certify exact outputs.

## How the existing system composes

1. **Observe:** In-Formation-Space HFR-001 `experiments/external_neural_structure_reading/hub.py` reads a pinned Hub revision, config, optional index and each Safetensors **header** via small ranged reads. It checks the Hub revision and the tensor-index/header consistency. No weight payload bytes are loaded. Output: NSD v0.1, source-pinned descriptive evidence.
2. **Form the Model Ground:** `mailcpu.hf_model_ground.HFModelGround.from_nsd` validates that NSD shape, tensor offsets and header digest references are internally consistent, binds the model source, and gives a stable **description identity**. This adapter is not a new E-CPU admission authority. It retains the difference between `config_only` and `hfr_header_observed` modes.
3. **Navigate tensor coordinates:** `HFModelGround.tensor_address(name)` returns the exact reported tensor shard, data offset, shape/dtype, and header commitment. **This does not authenticate or return tensor payload.** MWS-001 `model_weight_ground` and MWS-002 `generative_weight_ground` can then bind actual bytes, verified pages, or exact reconstruction recipes to the independent trained-snapshot identity.
4. **Compile intention / state transition:** `HFModelGround.start()` and `finish()` describe input tokenization/embedding and final logits, sampling and committed continuation. `HFModelGround.layer(i, token_coordinate=t, phase=...)` constructs a **lazy bounded per-layer Ground**, including the correct family-specific attention/router/expert dependency order. The compiler does **not** choose experts without router logits.
5. **Use existing E-CPU DAG:** `.compile_ecpu_dag()` converts a single layer to `ComputationNode` / `NavigableComputationDAG`, producing an execution proposal whose nodes have `execution_status=not_executed`. Each DAG is well below E-CPU's 256-node maximum. The 235B configuration yields **94 independently addressable layer frontiers**. A complete logical *one-token pass* includes **2,080 described operations** (5 input + 94×22 layer + 7 output). These are counts of description nodes, **not** physical arithmetic or runtime measurements.
6. **Realize, verify, retain:** Only receiver-owned `VirtualLayerRuntime`, admitted operator specifications, real parameter-bearing tensor transformations, `ComputationalExecutionAdmissionCoordinator`, and independent numerical verification can commit results. For cross-frontier continuity, pass a verified prior-hidden-state digest and real K/V state to the next layer; use `ComputationalObjectStore`, existing stateful computational sessions and recovery lineage for persistence. The plan alone cannot create or validate a hidden-state digest. If the operator cannot satisfy its Ground, fail closed rather than substitute an opaque unaudited backend.
7. **Check semantics:** In-Formation-Space tensor-cut numeric experiments provide real arithmetic precedent. VGI's neural-topology ProofGround adapter can express proof obligations. It does **not** prove a model-layer result until the relevant numerical/kernel evidence is admitted.

## Critical ordering, not a generic MoE emulation

Qwen3 MoE layer:

`read verified predecessor -> RMSNorm -> Q/K/V projections -> per-head Q/K RMSNorm -> RoPE -> cache state transition -> full causal attention -> O projection -> attention residual -> RMSNorm -> router linear -> softmax across all experts (FP32) -> top-k probabilities -> normalize selected weights -> bind only selected experts -> SiLU gate × up -> down -> weighted expert reduce -> layer residual`.

GPT-OSS layer:

`read verified predecessor -> RMSNorm -> Q/K/V projections -> YaRN-positioned RoPE -> KV state transition -> layer-selected full or sliding causal mask -> attention with learned sinks -> O projection -> attention residual -> RMSNorm -> router with bias -> top-k of raw logits -> softmax selected logits -> bind MXFP4 gated experts and biases -> clamped SwiGLU with alpha 1.702 and limit 7.0 -> weighted reduce -> layer residual`.

Both then apply final RMSNorm, vocabulary projection, generation-specific logit policy, token selection, and state commit/stop. A chat template and tokenizer must be bound to their **exact** source bytes. The model configuration alone cannot supply missing token mappings or a trained model's content.

Qwen3 generation defaults from the pinned source specify `do_sample=true`, `temperature=0.6`, `top_k=20`, `top_p=0.95`, and stop token IDs `[151645,151643]`. Sampling additionally requires a committed RNG/counter state if determinism across recovery is needed. Do **not** assume the same generation defaults for GPT-OSS; no separate generation configuration was acquired in this experiment.

### Why the model can be addressable without being materialized

The **model Ground** describes the space of valid operations and tensor addresses. The **trained snapshot** selects exact parameter bytes. The **inference Ground** selects logical token positions, activation history, expert routes and K/V state. A **realizer** establishes actual numerical transitions. These identities remain distinct. A trained instance cannot be reconstructed from a SHA-256 digest or config alone, and not all nonlinear computation has a direct closed-form navigation law. Yet a large model's architecture can be addressed and scheduled one verified frontier at a time, independent of a fixed conventional-machine form.

## Reproduction: offline and live HFR

Offline: config facts and executable proposal without weight payloads:

```bash
python -m mailcpu.hf_model_ground \
  --profiles examples/hf_pinned_model_configs.json \
  --repository Qwen/Qwen3-235B-A22B --layer 93 --token 42
python -m mailcpu.hf_model_ground \
  --profiles examples/hf_pinned_model_configs.json \
  --repository openai/gpt-oss-120b --layer 1
python -m mailcpu.hf_model_ground \
  --profiles examples/hf_pinned_model_configs.json \
  --repository Qwen/Qwen3-235B-A22B --all-layers
pytest -q tests/test_hf_model_ground.py
```

Online: reuse the HFR-001 reader in a checkout of In-Formation-Space **pinned at** `c9716242725be65937fda1dd7b6cb778ca1def91`; do not download weight payloads. This needs permitted HTTPS access. For the 235B model, the reader inspects 118 Safetensors shards and the sharded index; the Hub files are ~470GB, but header reads are bounded, metadata-only requests. The full index itself is several MB.

```bash
python external/In-Formation-Space/experiments/external_neural_structure_reading/hub.py \
  --repository Qwen/Qwen3-235B-A22B \
  --revision 58ccb6e3fb22606f13e07de68b71f8fbce40a375 \
  --output /tmp/qwen235-nsd.json
python -m mailcpu.hf_model_ground \
  --nsd /tmp/qwen235-nsd.json --layer 93
```

The first command downloads **header and metadata** only. To perform real inference, use HFR's separately bounded `fetch_selected_tensor_payloads` and E-CPU's existing MWS/Virtual Layer services with actual tensor-byte verification, plus tokenizer configuration and model-specific numerical contracts. Parameter bytes alone do not establish correct implementation semantics.

## Acceptance gates for the next iteration

- [x] Pinned three-family source configuration profiles and explicit evidence grades.
- [x] Qwen3 versus GPT-OSS operator-order distinction with refusal tests.
- [x] Lazy 94/48/36-layer Ground frontiers and per-frontier E-CPU DAG integration code.
- [x] HFR/NSD address and offset/header binding validation (synthetic offline fixtures).
- [ ] Live 235B HFR reader result with real shard header evidence, retained as a provenance digest (no weight payloads).
- [ ] Exact tokenizer/template and generation policies pinned to source bytes.
- [ ] Actual parameter-backed RMSNorm, QKV, GQA/attention, MoE and full-layer E-CPU numerical realization with independent numerical oracle.
- [ ] KV/session recovery with genuine committed state and fresh observer-host continuation.
- [ ] Independent proof of any novel faster-than-layer-evaluation navigation law. This is not implied by addressability.

All missing items are active development objectives—not reasons to privilege a physical machine as the Ground's definition.
