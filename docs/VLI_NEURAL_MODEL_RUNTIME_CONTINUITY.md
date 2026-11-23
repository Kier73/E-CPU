# SOI-009 — Original VL-I generated neural model hosted across E-CPU M3

## What is executable

E-CPU now hosts **the original, complete COORD-002 VL-I generated neural
model**, including original VLD neural weight synthesis, full finite-domain
verification, actual neural forward evaluation, VLD output dependency DAG,
rendered response projections, and original VL-I causal conversation
checkpoint reconstruction.

This is the **full execution path of a described finite-state neural model**.
It synthesizes a real small ReLU network and executes its learned-from-source
transition coefficients. It is a materially stronger hosted computation than
TIME-001 rational observation alone.

It is also distinct from a pretrained LLM decoder. The model source is a
3-state/3-action described transition Ground; VL-I and VLD construct the
neural weights locally rather than downloading a Qwen checkpoint. The source
provides finite behavioral laws, not natural-language semantics. Native
tool-call outputs are inert typed proposals. This distinction is reflected
in all receipts.

The independent source versions used in the test are:

- VL-I: https://github.com/Kier73/VL-I/commit/939b49291bb719ab531730088f759574db471c00
- Full Virtual-Layer-Dynamics: https://github.com/Kier73/Virtual-Layer-Dynamics/commit/985ba5c2fbcc40842aed9f45f42587749620b98e
- Input descriptive Ground: original VL-I COORD-002
  experiments/coord002/described_model.json (3,199 exact source bytes);
  test fixture copied byte-for-byte into
  tests/fixtures/vli_original_described_neural_model.json.

### Runtime files

| Component | Contract |
| --- | --- |
| mailcpu/vli_neural_model.py | Source-admit original VL-I and original VLD compiler as separate M2 artifacts; fingerprint dependency and model source, run original GenerativeModelGround and GenerativeConversation |
| mailcpu/vli_neural_session.py | Reconstruct model source/causal checkpoint from native HeadlessOS; verify remote output against independent M2 neural execution; publish through existing M3 revision CAS |
| mailcpu/vli_neural_worker.py | Disposable Python interpreter that imports and executes the original neural runtime after source verification |
| tests/test_vli_neural_model_host.py | Real neural execution, 4-host continuation, original temporal coexistence, multiple parallel M3 sessions, forged output/stale host, source tamper and actual hard worker kills |
| .github/workflows/vli-neural-model-hosted.yml | Linux/Windows Python 3.11/3.14 M3 integration; separately verify original upstream VL-I COORD-002 neural tests |

### Source admission and model identity

M2 admits and verifies the **whole installed original VL-I Python source
tree**, not a single wrapper. A second independent M2 artifact manifest
hashes the **whole original full VLD compiler/runtime tree**. Their exact
content identities and Python/runtime versions are bound in a deterministic
ComputationalBackendProfile:

    A_VLI = SHA256(canonical E-CPU manifest(original vli/ source files))
    A_VLD = SHA256(canonical E-CPU manifest(original vld/ source files))
    I_M2  = SHA256("mailcpu.vli-neural-model-host.v1" || 0x00
                   || A_VLI || A_VLD)
    B_M2  = ECPU.ComputationalBackendProfile(
              implementation_digest=I_M2,
              configuration={vld_source_digest=A_VLD, ...},
              effect_mode="pure", deterministic=True)

The host re-verifies the VLD dependency inventory at every fresh load, as
well as E-CPU's original primary model source inventory and version. An
incoming request cannot substitute an executable function, numerical
backend or source package. It names only a supported model.respond
operation with an exact source description and reconstructed checkpoint.

The **model parameters** are also identified independently of the
interpreter source:

    G = VL-I.GeneratedModelGround(exact_description_bytes)
    W = G.weights_digest
    require G.system.fingerprint == G.neural.system_fingerprint
    require for all declared states s and actions a:
             G.neural.step_neural(s,a) == G.system.step(s,a)

The original VL-I whole-domain neural compiler checks all nine declared
transition cells. Changing model-description bytes changes its manifest,
generated weights and state-coordinate roots. Source model bytes and
original conversation state are retained by E-CPU's native OS VFS, not
in a disposed Python interpreter's heap.

### State identity and continuation

The native OS contains at least:

    /vli/neural/source.json
    /vli/neural/conversation.json
    /vli/neural/results/<logical_time>_<operation_id>.json

Optionally, the *same* native OS can contain the independently qualified
original VL-I TIME-001/002 Ground:

    /vli/temporal/state.json

The neural session preserves all existing native OS files, kernel,
scheduler/guest program state and the living temporal Ground unchanged
while its original neural conversation advances.

Let C_r be the accepted original GenerativeConversation checkpoint,
H_r its causal head, P the exact description source, W its generated
neural weight digest, and Q_r the E-CPU M3 revision authority.

    (S_r, Q_r) := M3.load_verified()
    P := OS(S_r).VFS["/vli/neural/source.json"]
    C_r := Original_VLI.GenerativeConversation.restore(
               Original_VLI.GeneratedModelGround(P),
               OS(S_r).VFS["/vli/neural/conversation.json"],
               expected_head=checkpoint_digest(C_r))
    T_r := (prompt, action, requested_views)
    R_remote := New_Admitted_M2_VLI_Host.execute("model.respond", P, C_r, T_r)
    require R_remote.context_binding_digest == Q_r.context.binding_digest
    require M2_receipt identifies source, backend, context, output bytes
    R_ref := Independently_Admitted_M2_VLI_Host.execute("model.respond",P,C_r,T_r)
    require R_remote.output == R_ref.output
    require original_neural_step == 1 and source/checkpoint chronology holds
    OS_next := OS(S_r) with C_{r+1} and rendered semantic result stored in VFS
    S_{r+1} := Canonical(HeadlessOS.snapshot(OS_next))
    Q_{r+1} := M3.CAS(expected_revision=r,
                      expected_checkpoint_digest=Q_r.checkpoint_digest,
                      candidate=S_{r+1})

The original VL-I restore operation independently recomputes and checks
the entire preceding conversation: each source state, neural forward step,
channel output, render source address and observed response digest. The
next result contains the real forward-step receipt, state coordinate,
generated weight digest and fully materialized text/code/token or inert
tool-proposal views. Each turn selects its position **before** the new
output is realized, as implemented by original VL-I COORD-002.

Every new worker is a separate real Python process, not a renamed Python
object in a single interpreter. A host-local M2 receipt remains outside the
native committed semantic state so equivalent computation can be performed
on a different physical host identity. M3's original fixed-quorum
predecessor CAS is the sole publication authority. A worker that is
killed before its response leaves no accepted successor. A worker killed
after response publication may still have its independently verified
candidate committed once. Exact replay returns the accepted checkpoint
without launching another worker. A delayed obsolete worker fails CAS
after the new owner wins the predecessor revision.

### Usage

Install E-CPU, original VL-I source and original VLD model dependency:

    python -m pip install -e ".[dev]"
    python -m pip install "git+https://github.com/Kier73/Virtual-Layer-Dynamics.git@985ba5c2fbcc40842aed9f45f42587749620b98e"
    python -m pip install "git+https://github.com/Kier73/VL-I.git@939b49291bb719ab531730088f759574db471c00"

Bootstrap one original model inside a native HeadlessOS:

    from pathlib import Path
    from mailcpu.vli_neural_session import (
        bootstrap_vli_neural_model, encode_vli_model_turn,
        read_vli_model_checkpoint,
    )

    source = Path("tests/fixtures/vli_original_described_neural_model.json").read_bytes()
    native_os_state = bootstrap_vli_neural_model(
        source, observer="vli-neural-host", include_living_ground=True,
    )
    model_source, original_checkpoint = read_vli_model_checkpoint(native_os_state)
    assert model_source == source

    request = encode_vli_model_turn(
        "Advance the described state and render the result",
        "advance", views=("text", "code", "tokens", "tool_call"),
    )

Create an M3 session with original M1 bytes and quorum lineage, then apply
the request through ComputationalSessionTransitionAdapter using
vli_model_session_contract(reference_host) and
VLINeuralModelSessionBackend(reference_host,remote,...). See the executable
tests for the exact A/B/C quorum and worker protocol.

### Verification

Unit/integration tests run the original model:
1. Reproduce all 9 complete 3-state x 3-action model transition cells by
   real original VLD ReLU neural execution and independent transition oracle.
2. Execute a new complete model.forward + response DAG operation with
   actual generated weights, text/code/UTF-8 bytes/inert tool proposal.
3. Run four successive neural turns across **four independent Python
   observer-host processes** with M3 reopened after each; retain complete
   causal checkpoint, existing results, native OS journal and an unchanged
   living TIME-001 interpreter Ground.
4. Require all previous neural turns to replay exactly on restore; tampering
   with the model description must refuse before remote execution.
5. Replace the remote output with a fabricated model target, recompute a
   syntactically valid M2 receipt, and refuse via independent real neural
   execution (not just the advertised SHA-256).
6. Run two separately executed valid competing successor neural results,
   allow one M3 CAS to win and refuse the obsolete publisher.
7. Kill actual neural model worker subprocesses before and after response
   publication; continue with a fresh host without duplicate semantic turns.
8. Execute four *different* M3 model session identities concurrently,
   with independent quorum journal directories and model state, and
   replace all four worker hosts while preserving each accepted head.

The original upstream VL-I COORD-002 neural suite executes separately
using the same pinned original source/compiler. CI also includes
selected E-CPU ComputationalSession and transition regression tests.
The workflow's results are the authority for passing cross-platform
counts and executable scope:

https://github.com/Kier73/E-CPU/actions/workflows/vli-neural-model-hosted.yml

## To Do — fully realized pretrained VL-I hosting

The present result is a complete **source-described neural model runtime**
and causal application state, not a complete Qwen3.8-27B decoder or general
language reasoning model. Fully pretrained VL-I hosting can reuse these
exact state/session layers by adding:

1. **Original trained checkpoint admission**: exact pinned full model
   weights/index and validated source range manifests. The trained
   tensor operator host should materialize ranges on demand; model
   identity must not be confused with model-description identity.
2. **Original causal attention state**: preserve Qwen3.8 GDN recurrent
   matrices, convolution history, GQA keys/values and token timeline
   through VGI/E-CPU M1 typed content-addressed page sets rather than
   embedding enormous Python arrays in a JSON OS snapshot.
3. **Whole decoder**: combine original VL-I/VLD causal layer chain,
   final norm, vocabulary head, tokenizer, token-generation loop,
   and independent numerical parity. Keep receipt-level distinctions
   between complete trained logits and partial architecture probes.
4. **Remote physical host authority**: replace local subprocess IPC
   with E-CPU authenticated mTLS worker identities and IPS-008 receiver
   activation fencing, on independently administered worker/authority
   machines.
5. **Capacity and resource measurements**: simultaneous model instances,
   per-model and aggregate weight residency, KV memory, CPU/GPU utilization,
   M1 page growth, CAS latency, and model continuation under host death
   or network partition. Calibrate separately against the verified
   64-instance smaller VL-64 hosting fleet.

This is a functioning complete finite-neural hosting foundation: it
executes original compiled weights and response synthesis, not simply
recovered observational mathematics. It explicitly maintains the
source-evidence chain and all native E-CPU processor/OS state so the
same continuation contract can be extended to original pretrained
models without inventing their missing weights.
