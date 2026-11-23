# SOI-010 — Original Qwen causal state through E-CPU M1

## Implemented state transfer

E-CPU now adapts the real original VL-64 LocalStatePages interface directly
to its existing immutable ComputationalObjectStore. The *original* VL-I
QwenArchitectureCausalPrefix continues to own all model mathematics and
causal state verification. It checkpoints six complete GDN-layer states
(recurrent matrices plus convolution history) and two gated GQA layers'
key/value histories, each with its original independent model plan,
position, source and causal digest.

Sources (pinned):
- VL-I: https://github.com/Kier73/VL-I/commit/939b49291bb719ab531730088f759574db471c00
- VL-64: https://github.com/Kier73/VL-64/commit/fea0d29d5a8a1edb03d9c66edd5ca4b15a1395d3

The original eight-layer architecture uses a tiny reproducible F32
fixture of Qwen-compatible operators. These are **synthetic F32 weights,
not original Qwen3.8-27B pretrained tensor bytes**. The experiment
qualifies numerical-state portability and process recovery rather than
full pretrained token-generation inference.

### Byte identity

Original VL-64 LocalStatePages.put accepts 1..65536 raw causal bytes
and returns {"sha256": SHA256(raw), "size": len(raw)}. The E-CPU adapter
is a subclass of the original LocalStatePages, preserving original
isinstance and descriptor checks, and supplies the bytes from immutable
E-CPU M1 objects with 4096-byte physical pages.

The M1 page bundle has a versioned canonical schema:
mailcpu.vli-qwen-causal-m1-bundle.v1. Its mapping associates each
original VL-64 causal SHA-256 digest with one exact typed
ComputationalObjectManifest. The bundle digest covers the full mapping
and byte extents. Reopening the bundle checks every original page
digest, typed M1 object descriptor and underlying physical page digest
before original QwenArchitectureCausalPrefix.restore executes.

The verified state structure is:

    Original Qwen causal checkpoint:
        model/index/config/plan digests
        position, input sequence digest and causal head
        layer 0,1,2,4,5,6 -> GDN recurrent/convolution page references
        layer 3,7         -> GQA key/value page references

    E-CPU M1 bundle:
        original causal digest -> M1 object manifest
        M1 object -> immutable SHA256-named 4096-byte disk pages

The original Qwen code defines how these bytes become causal state.
E-CPU provides content-addressed persistence, validation and recovery.

### Hard worker death

The test executes the actual original Qwen eight-layer prefix in one
Python interpreter process, checkpoints its six GDN and two GQA states
as real E-CPU M1 page objects, publishes the checkpoint and terminates
that interpreter with a hard OS kill. A second independently executed
interpreter reopens the disk-backed E-CPU M1 object store, restores
every original layer and computes the next causal token position.

The resumed output, original causal head, position and entire recurrent,
convolution and KV state match a separately executed uninterrupted
original Qwen prefix. Independent refusal tests change the signed-by-
digest bundle manifest and tamper a physical 4096-byte page, then verify
that neither can be admitted as valid causal state.

### Concrete files and reproduction

- mailcpu/vli_qwen_pages.py — durable M1 backing, original-page bridge,
  bundle import/export and original eight-layer checkpoint checks.
- tests/test_vli_qwen_m1_pages.py — original 8-layer model, M1 recovery,
  physical corruption refusal and killed worker.
- .github/workflows/vli-qwen-m1-pages.yml — Linux/Windows,
  Python 3.11/3.14 pinned source matrix and original upstream
  eight-layer worker recovery test.

CI: https://github.com/Kier73/E-CPU/actions/workflows/vli-qwen-m1-pages.yml

With original VL-I and VL-64 repositories checked out at their pinned
SHAs into original-vli and original-vl64:

    python -m pip install -e ".[dev]"
    python -m pip install -e ./original-vl64
    python -m pip install -e "./original-vli[test]"
    python -m pip install "numpy>=2.1"
    python -m pytest -q tests/test_vli_qwen_m1_pages.py

### Current measured trust domains

The model worker processes are distinct Python interpreters and can be
killed and replaced. The fixed immutable M1 backing is a **single
physical filesystem with fsync**, not multiple independent hosts.
The original layer model and checkpoint digest are the authorities
for causal interpretation. An E-CPU M3 revision/lineage authority for
this specific original Qwen checkpoint is the next integration.
M1 state pointers are content descriptors and must not be mistaken
for a majority-committed execution assignment or receiver capability.

## To Do — original pretrained VL-I runtime continuity

1. Publish the original eight-layer checkpoint and content-addressed
   causal bundle through E-CPU's existing M3 predecessor CAS, while
   retaining the original Qwen semantic head and all native OS state.
2. Use original pinned Qwen3.8 pretrained checkpoint tensor ranges,
   source-qualified index, and original VL-I/VL-64 trained operators.
   Preserve their actual changing GDN and GQA state in M1, independent
   of static model-weight manifests.
3. Extend all the way through all original layers, final normalization,
   vocabulary logits, tokenizer and token-generation loop with
   independent numerical parity.
4. Move M1 and quorum authority to independent machines; use authenticated
   E-CPU mTLS worker admission and IPS-008 receiver freeze/activate.
5. Measure state bytes, page reuse, real process RSS and GPU/CPU use,
   I/O costs, original-weight range reads and recovery latency.

This implementation verifies the **original Qwen causal architecture's
state reconstruction** using the same M1 objects already used to host
VL-I's generated neural model. It is the next typed state interface
on the path to the full pretrained decoder.
