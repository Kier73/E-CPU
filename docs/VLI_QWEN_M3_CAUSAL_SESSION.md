# SOI-011 — M3-fenced original Qwen numerical causal state on E-CPU M1

## Capability and exact scope

This implementation composes the existing native E-CPU M1 and M3
storage/authority systems with VL-I's **original eight-layer
QwenArchitectureCausalPrefix**. Actual original VL-I GDN and GQA
numerical operators are executed in separate Python worker processes.

The initial qualified source is the pinned original VL-I tiny F32
eight-layer test architecture (three hidden dimensions, six GDN layers
and two GATED_GQA layers). The trained original Qwen3.8-27B weight
checkpoint, all decoder layers and vocabulary logits are not substituted
for this source and remain the next actual-weight experiment.

Source pins:
- VL-I: https://github.com/Kier73/VL-I/commit/939b49291bb719ab531730088f759574db471c00
- VL-64 original full model-fabric implementation:
  https://github.com/Kier73/VL-64/commit/fea0d29d5a8a1edb03d9c66edd5ca4b15a1395d3

SOI-010 established original numerical state in M1 immutable page
manifests and process-rehost recovery. SOI-011 adds the **current
accepted state authority** from E-CPU M3, including predecessor CAS,
one-source/one-backend identity, independent source execution, and
atomic native HeadlessOS revision publication.

## One native-OS-backed Qwen session

The current E-CPU OS contains:

    /vli/qwen/accepted-causal-state.json
      schema: mailcpu.vli-qwen-causal-m3.v1
      source: original model/architecture/index/config/plan identity
      source_manifest_digest: SHA256(original VL-I M2 source manifest)
      fabric_manifest_digest: SHA256(original VL-64 model-fabric manifest)
      position: current accepted token position
      causal_head: original Qwen chain-head digest
      input_sequence_digest: accepted source-token sequence digest
      checkpoint: original VL-I complete eight-layer causal checkpoint
      bundle: E-CPU M1 immutable original-layer page manifests

    /vli/qwen/accepted-results/<logical_time>_<operation_id>.json
      original 8-layer F64 output and original per-layer witnesses
      accepted original causal head and position
      GDN/GQA causal-state page statistics

    /vli/temporal/state.json (optional)
      independent original VL-I temporal Ground preserved unchanged

The full native OS is serialized and committed by the preexisting
ComputationalSessionStore with A/B/C recovery-lineage journal authority.
Its original OS journal, VM/scheduler, VFS, and all other existing
state coexist with the accepted model state.

The source description is derived from actual VL-I architecture
admission. Its fields include model and revision, qualified tensor
index Ground, exact config SHA-256, model plan digest, number of
executed layers, expected input width, maximum positions and chain
genesis.

The implementation also admits the exact original **two source trees**:

    A_VLI = M2.manifest(original installed vli/ source bytes)
    A_FABRIC = M2.manifest(original VL-64 experiments/model_fabric bytes)
    P = Original_VLI.QwenArchitectureCausalPrefix(source plan)
    B = SHA256("mailcpu.vli-qwen-causal-M3-backend.v1" || NUL ||
               A_VLI || A_FABRIC || canonical(source(P)))

E-CPU M3 binds B, A_VLI, the state schema and transition
interpretation. An executing worker cannot choose an alternative
model source, peer identity, initial OS checkpoint or token sequence
coordinate; the controller reconstructs these from the accepted M3
revision and the trusted source factory.

## Exact transition

At accepted revision r, let S_r be the complete native OS and C_r
the original eight-layer checkpoint. E-CPU retains the M1 source
pages identified by C_r.bundle and the original causal head H_r.

    (S_r, Q_r) = M3.load_latest_verified()
    require Q_r binds full OS state, M2 source trees and backend B
    C_r = OS(S_r).read("/vli/qwen/accepted-causal-state.json")
    require original Qwen plan/causal digest/M1 bundle all reconstruct
    x_r = typed hidden F64 vector and token ID
    input_sequence_{r+1} =
      SHA256("mailcpu.qwen-causal-sequence.v1" ||
             input_sequence_r || canonical(x_r))

    R_remote = new_original_Qwen_worker.step(C_r, x_r, M1)
    require response is bound to exact Q_r.context, assigned host
    R_ref = independent_original_Qwen_controller.step(C_r, x_r, M1)
    require canonical(R_remote) == canonical(R_ref)

    C_{r+1} = R_ref.original_Qwen_checkpoint
    OS_next = OS_r with C_{r+1}, M1 bundle, and numerical result
    S_next = Canonical(HeadlessOS.snapshot(OS_next))
    Q_{r+1} = existing_M3.CAS(
       expected_revision=r,
       expected_checkpoint_digest=Q_r.checkpoint_digest,
       new_state=S_next)

The original Qwen checkpoint is computed by original
QwenArchitectureCausalPrefix.checkpoint and then independently
restored with the original class's restore, including all six
full GDN recurrent/convolution pages and two gated GQA KV
histories. The E-CPU M1 adapter writes immutable pages only;
the M3 current-state pointer changes exactly once upon acceptance.

A delayed old host may have completed valid numerical work and
stored content-addressed M1 pages. Those pages are harmless until
an M3-accepted state points to them. If another host has already
committed a successor, the old predecessor CAS fails; no stale
model causal head can overwrite the new head.

### Model semantics versus path/host measurement

The original Qwen layer receipt contains both:
- semantic F64 source input/output digests, original layer
  causal-state digest, convolution digest, KV position and
  original chain head, and
- host-specific qualified tensor-range acquisition counts,
  source range chain, and weight bytes newly read.

When an original Qwen worker is recreated, it may read qualified
tensor ranges in a different order or quantity. Those acquisition
receipts legitimately differ from an uninterrupted host even
when **every numerical state and causal head is identical**.

SOI-011 compares complete remote and independent controller-side
executions made from the *same accepted source state* and
compares original semantic evidence against an uninterrupted
reference. The semantic head is **not** replaced by a digest of
host-dependent acquisition events. Each host's range evidence can
be retained as separate receipt provenance without changing model
state identity.

## Tests

- tests/test_vli_qwen_m3.py — three original numerical token
  positions through three actual Python worker processes and
  independently reopened M3 stores; original temporal Ground and
  full HeadlessOS preserved.
- Each step compares original Qwen F64 output and original
  causal-head/semantic layer witnesses with uninterrupted original
  Qwen execution, and checks full eight-layer GDN/GQA page state.
- A forged original numerical output with a correct model/source
  label is rejected against independent original source execution,
  without publishing a new M3 state.
- Two true Qwen workers compete from the same M3 predecessor.
  The winner commits; the late worker's correct output is fenced
  by the existing original M3 predecessor CAS.
- Worker killed before result publication cannot advance M3.
  Worker killed after publishing a valid result may have its
  independently checked successor accepted once.
- Corrupt a physical original M1 causal page under the active
  checkpoint: original restoration refuses before another worker
  performs numerical computation.
- Selected existing M3 ComputationalSession and transition
  regression tests and all SOI-010 original M1 worker/restore tests
  execute in the same four-platform workflow.

**Verified Linux/Windows matrix:** 46 tests passed in each of
Linux Python 3.11/3.14 and Windows Python 3.11/3.14, including
original M2 host regression tests, original M3 session/transition
regressions and the new original numerical Qwen M1/M3 experiments:
https://github.com/Kier73/E-CPU/actions/runs/45096226953

### Cross-platform artifact identity repaired in E-CPU M2

This experiment surfaced a more general source-admission invariant.
The original M2 source enumerator initially sorted Path objects,
whose comparisons can use case-insensitive ordering on Windows.
The immutable manifest expects **case-sensitive POSIX-relative
lexicographic component order** on every platform.

E-CPU now sorts enumerated source records by their actual canonical
relative path strings before constructing the manifest. This is a
general M2 source-identity fix, not a model-specific workaround.
The mixed-case directory regression verifies the same source
inventory order and repeated digest on Linux and Windows.
This prevents otherwise valid model/compiler artifact trees from
being refused because the execution host changed operating systems.

Full CI:
https://github.com/Kier73/E-CPU/actions/workflows/vli-qwen-m3.yml

## To Do — original large pretrained VL-I continuation

1. **Original model weight source:** pin actual Qwen3.8 original
   pretrained index, tokenizer/config and qualified tensor ranges,
   then execute the real Qwen model's layers using these operators
   and preserve their original GDN/GQA pages in M1/M3.
2. **Full trained decoder:** compose all actual model layers, output
   normalization, vocab projection and token-generation loop;
   qualify numerical parity against an independent execution.
3. **Independent physical quorum:** split M1, M3 authority members
   and neural workers across independent hosts and support
   authenticated E-CPU mTLS worker assignment.
4. **Receiver-side external effects:** use existing IPS-008
   freeze/activate fencing for source acquisition, resource
   ownership and external tool outputs.
5. **Original model economics:** measure actual original-weight
   range bytes, memory residency, GPU/CPU time, content-addressed
   causal-state growth and recovery latency per token and per host.

This milestone constructs an actual **model identity continuing
through a changing computation host**, where E-CPU owns its
current accepted state and original VL-I continues to own
the numerical interpretation.
