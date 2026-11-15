# TENSOR-PATH-001 — Tensor computation as SIMT and communication-substrate realizations

## Objective

The path is not presumed to be a pipe delivering a computation to a conventional CPU.
A computational Ground may be realized by an **admitted transformation in the
communication substrate itself**. E-CPU should recognize, characterize, route,
observe and verify such transformations without requiring an entire E-CPU VM,
tensor runtime, or conventional processor at the transformation locus.

This increment implements two **different** realization classes under the
existing E-GPU operational graph and receiver-local Hypervisor contract:

| Method | E-GPU path | Computational transformation |
|---|---|---|
| \`tensor.matmul.tile\` | dispatch → SIMT → verification | Signed integer \`C[r,c] += A[r,k] B[k,c]\` in the bounded SIMT reference interpreter |
| \`tensor.path.fir\` | dispatch → characterized path transfer → verification | Float-valued finite impulse response convolution \`y_i = Σ h_j x_{i-j}\` as a path input/output transition |

An **active, independently observed transfer path** can directly implement a
Toeplitz tensor operator (FIR convolution). The E-GPU does not call SIMT for
this method; its \`PathTensorHost\` invokes a receiver-bound, calibrated
\`transmit(frame, observation_id)\` interface that must return the path's
**actual observed response**. It does **not** calculate the convolution as
its realization. The source runs a separate FIR oracle to check every response
against the evidence-scoped Ground.

The first fixture uses the existing **software FIR reference** and is
therefore **not evidence of a physical optical, RF or network medium
computing the convolution**. A hardware-backed path must provide actual
independently acquired transfer observations, physical calibration, controlled
bypass comparisons and provenance/authority before any physical attribution.

## SIMT realization: bounded matrix tiles

\`mailcpu.transit_simt.TransitSIMTHost\` now supports \`MAC dst,acc,a,b\`
with exact signed integer semantics, initialized-register checks, divergence
masking and intermediate bit bounds. \`compile_matmul_tile\` maps each
\`(row,col)\` output cell to a SIMT lane. With tile shape \`[r,c,k]\`:

- Number of lanes: \`r*c\` (at most the configured SIMT bound)
- Input elements: \`r*c*(2*k+1)\` (two operand broadcasts per depth step,
  plus the pre-existing accumulated result)
- Instructions: \`3*k+3\`
- Result: \`r*c\` exact integers, with a scalar arithmetic oracle at E-GPU
- Execution: the same \`TransitSIMTHost\` invoked from \`EGPUHost\`, not a new VM
- Admission: existing \`/gpu/egpu\` execute right; via Transit or the
  existing Virtual Layer node-local trusted adapter

\`execute_tiled_matmul\` decomposes larger matrices into row/column tiles and
depth chunks. Each chunk is a separate bounded work request; its response
contains route, SIMT state, state digest, result digest and E-GPU receipt
digest. The coordinator rechecks each partial dot product and carries
admitted accumulation into the next chunk. The callback may dispatch through
the existing authenticated Computational Fabric/Transit, but the coordinator
does **not** implement or bypass network admission by itself. The caller must
assign a unique semantic operation identity for each *new* chunk, preserving
the same identity for retransmission and replay. Boundedness is checked before
dispatching any chunk. The coordinator currently executes requests
sequentially; concurrent scheduling and durable partial checkpoints remain
in development.

This SIMT method is still **processor-realized**: useful for testing integer
tensor semantics and fabric composition, not proof of in-medium computation.

## Path-substrate realization: stream FIR tensor frames

The existing \`path_ground_probe.characterize_transfer\` accepts a full
impulse, a shifted impulse and at least two held-out probes. A receiver-bound
\`PathTensorHost\` requires that the supplied \`TransferGroundCandidate\`
**reconstructs** from those observations. Its evidence binds the transfer
kernel, environment digest, declared mechanism and measurement tolerance.

A qualified path with a finite impulse response \`h\` (length \`K\`) and
observation frame length \`N ≥ K\` can compute long signal tensors with a
bounded overlap-save/overlap-prefix frame protocol:

1. Include \`K-1\` previous *input* samples in each frame.
2. Send at most \`N-K+1\` new samples; zero-pad only the remaining frame space.
3. Observe exactly one response to that frame **from the path**.
4. Independently verify that its output matches \`h*x\` within the declared
   calibrated tolerance.
5. Take the output positions corresponding to the new samples; retain input
   history for the next frame.

Each \`tensor.path.fir\` request accepts
\`{"method":"tensor.path.fir","request_id":"...","samples":[[...],...],"max_frames":N}\`.
Rows are independent streams and may have different lengths. The receiver
binds the candidate, observation callback, path ID and maximum capacity; a
remote request cannot install its own purported path law or callback. Every
frame has an exact, unique per-request observation identity and records
input/output/evidence digests and discrepancy. A wrong identity, changed
environment, nonfinite sample, incompatible candidate, failed held-out
calibration, incomplete response, or live drift beyond tolerance is refused.

The E-GPU route \`dispatch → path → verify\` exists only as an available
method when its E-GPU instance has a qualified \`tensor_path_host\`.
No SIMT program executes for \`tensor.path.fir\`. An E-GPU method receipt
binds the result; it is a **content-integrity** record, not a signature.

A finite impulse-response operator is a **tensor/matrix operation**:
\`y=T_h x\` where \`T_h\` is a lower-triangular Toeplitz matrix. Repeated
path frames therefore represent high-volume tensor calculations without a
numerical dot-product kernel at the execution locus. Hardware-backed
throughput and substrate energy savings must be measured, not inferred.

## Source, path, observer and authority accounting

| Work | Actual locus |
|---|---|
| Tensor decomposition, frame encoding, overlap history | Request origin / receiving adapter |
| Mathematical transfer \`Φ_P\` of input frame to output frame | **Declared path mechanism**, observed by path callback |
| Frame acquisition and instrumental conversion | Instrument and observer endpoints |
| Independent FIR prediction and discrepancy check | Verifier processor (not claimed as path compute) |
| SIMT multiply-accumulate | Software reference SIMT interpreter |
| Capability checks, event commitment, retries/replay | Existing Hypervisor, Transit and receiver-ledger systems |

\`software_fir_reference\` is a correctly functioning integration fixture, but
is not a physical computing substrate. \`instrument_observation\` names an
independent observation channel; the name alone does not prove trusted
hardware, calibration, signal physics or exclusive in-medium execution.
External path evidence should use the existing
\`observer_path_evidence\`, \`substrate_bootstrap\`, and
\`path_ground_probe\` receiver-owned observation contracts.

## Reproduction

~~~python
from mailcpu import EGPUHost, TransitSIMTHost
from mailcpu.tensor_stream import execute_tiled_matmul

host = EGPUHost(simt_host=TransitSIMTHost())
product = execute_tiled_matmul(
    [[1, 2], [3, 4]], [[5, 6], [7, 8]],
    lambda payload: host.execute_authorized_method("tensor.matmul.tile", payload),
    tile_rows=2, tile_cols=2, chunk_depth=2,
)
assert product["values"] == [[19, 22], [43, 50]]
~~~

The lambda above is a **local already-authorized adapter**, not a remote
admission demonstration. \`PathTensorHost\` requires calibration and a
receiver-bound transmit interface; see \`tests/test_tensor_paths.py\` for
the complete synthetic FIR experiment and refusal tests.

~~~shell
python -m pytest -q tests/test_tensor_paths.py tests/test_egpu.py
python scripts/verify_repo.py
~~~

## Next experiments

- Replace the software FIR callback with instrumented physical-path signals
  and control for transducer, source, receiver and verification computation.
  Compare bypass, software, and physical-medium paths at matched accuracy.
- Map other useful measured path operators to tensor contractions and
  structural Grounds, including delays, passive linear mixing and calibrated
  feedback, without demanding a specific device ISA.
- Add a bounded path-capability advertisement to the existing Computational
  Fabric resolver, preserving exact Ground/implementation matching.
- Test independent physical hosts, authenticated Transit request/response
  receipts, interrupted partial-tile replay and throughput at multiple
  workgroup counts and frame sizes. Measure wall time, energy, accuracy,
  uncertainty and information cost separately.

**Status:** a bounded executable design and regression suite; physical
signal-path execution remains an explicitly testable research goal.
