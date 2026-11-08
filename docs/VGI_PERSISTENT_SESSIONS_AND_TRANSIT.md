# Persistent VGI sessions, bounded execution, and host transit (M5-M7)

## Purpose and boundaries

M5-M7 connect VGI's declared computational Ground and compiled Program to
E-CPU's existing M1 byte objects, M2 artifact identity, M3 persistent session
checkpoints, and M4 pure transition adapter. The result is a persistent
interpreted computation whose machine state can be advanced in bounded
quanta, reconstructed after process loss, and transferred to a compatible
target host.

The components retain distinct responsibilities:

- **VGI Ground and Program:** define the computation's semantics.
- **M2 descriptor artifact:** binds the canonical typed TaskSpec and compiled
  Program IR as immutable component identities.
- **M1 byte object:** stores one exact serialized VGI machine checkpoint.
- **M3 session:** determines which machine-state bytes are current through a
  quorum-anchored checkpoint and predecessor chain.
- **M4 transition adapter:** invokes a declared pure backend and commits only
  through the existing session CAS and quorum lineage.
- **Target host:** independently admits the source descriptor, M1 bytes,
  backend compatibility, and original quorum proof before continuation.

This is a VGI-specific integration over a backend-neutral session substrate,
not a universal interpreter or a claim that arbitrary opaque bytes disclose
their own semantics.

## 1. M5 — Compiled session descriptor and persistent machine state

`VGICompiledSessionDescriptor.from_task(task, ground_fingerprint)` compiles
the typed task through the existing VGI adapter and derives a descriptor
binding:

`D = H(Gc, Iv, H(T), H(P), H(A), Is)`

where `Gc` is the computational-Ground fingerprint, `Iv` is the
VGI/E-CPU implementation fingerprint, `T` is the canonical typed task,
`P` is the immutable compiled Program, `A` is the M2 composite artifact
manifest, and `Is` is the semantic interpretation identity. The semantic
identity binds Ground, task, and Program; the compiled-plan identity
additionally binds the compiler implementation.

The M2 manifest has two components, **task.json** and **program.json**, with
exact byte sizes and SHA-256 digests. Its metadata records the Ground, task,
and Program identities. The descriptor also carries the canonical task and
Program representations required to reconstruct the plan and independently
checks their digests and the composite artifact identity.

The mutable VGI state is separate. Initialization constructs a fresh
`SignalStateMachine` using the declared `SIGNAL8_GROUND` and compiled
Program, validates that initial memory addresses exactly match the task's
declared inputs, and obtains `machine.snapshot()`. E-CPU wraps that checkpoint
with the descriptor digest and session status:

`S0 = Envelope(D, Snapshot(M0), ready, 0)`

These canonical envelope bytes are admitted as an M1 computational object.
The M3 session checkpoint binds the M2 artifact digest, the VGI state schema
and media type, the backend profile, revision one, and logical time zero.
The recovery-lineage quorum seals the session checkpoint only after the M1
object has been admitted and verified.

Loading the session selects the current checkpoint from the quorum high-water,
reads and verifies the M1 object, checks the descriptor digest, and restores
the VGI machine through VGI's own `SignalStateMachine.restore()` method.
That restore verifies the VGI machine snapshot digest, Ground fingerprint,
and Program fingerprint. No machine state is shared merely because the same
immutable Program is reused.

## 2. M6 — Bounded instruction quanta

`VGIPersistentSession.advance(q, operation_id=...)` accepts a positive
quantum `q` no greater than the configured `max_quantum_steps`. The backend
reconstructs the current machine from the verified M1/M3 snapshot, executes
no more than `q` individual calls to `machine.step()`, serializes the resulting
machine checkpoint, and returns those exact candidate bytes.

`M(r+1) = Step^min(q, Rr)(Mr)`

where `Rr = Nmax - nr` is the remaining cumulative instruction budget.
The configured `max_total_steps` bounds the complete session separately
from the per-quantum ceiling. `max_state_bytes` bounds the serialized machine
checkpoint, independently from M1's global object limit.

A successful quantum advances the M3 revision and logical time exactly once.
Its transition context binds the current checkpoint and quorum lineage,
state digest, input, operation identity, semantic interpretation, source
backend identity, and target execution backend identity. Candidate bytes
become current only through the existing compare-and-swap and quorum seal.

The session envelope records `ready`, `running`, `halted`, or `step_limit`.
A halted machine is not advanced. When the cumulative step ceiling is reached,
the final bounded quantum is committed with `step_limit`; exceeding the
per-quantum limit is rejected before execution. A step error produces no
successor checkpoint.

An exact immediate retry of the latest operation returns the already
committed snapshot as replayed and does not call the VGI transition backend
again. Reusing an operation ID with different input or transition identity
is refused. This is M3's immediate retry contract, not a global operation
catalogue.

A new process does not resume a live Python object. It reads the M1 bytes,
verifies the M3 quorum checkpoint, recompiles or retrieves the immutable
Program descriptor, and restores a fresh VGI machine. VGI intentionally does
not synthesize the pre-checkpoint undo stack; new steps after restore remain
undoable, but historical machine-local undo records are not claimed to be
portable.

## 3. M7 — Portable host transfer and continuation

`VGISessionTransferBundle` binds four parts:

1. the exact semantic descriptor, including Ground, task, Program, and M2
   artifact manifest;
2. the M3 portable checkpoint, recovery manifest, and quorum proof;
3. the exact M1 object manifest;
4. the state bytes whose size and SHA-256 digest match that manifest.

The bundle digest commits the descriptor, M3 export, M1 manifest, state
digest, and byte extent. The JSON wire form includes the state bytes as
base64 and the bundle digest. `from_dict()` applies the configured maximum
before accepting the state extent and verifies both byte length and digest.

On the target host:

1. the descriptor is reconstructed and its local Ground/task/Program
   semantics are verified; a changed VGI implementation requires an explicit
   `implementation_compatibility(source_fp, target_fp)` predicate;
2. the target imports the state bytes through its own M1 object store;
3. the resulting M1 manifest must exactly equal the source manifest, which
   currently requires identical chunk/page geometry;
4. M3 verifies that the exported checkpoint is still the latest source
   quorum-anchored state and that the exported proof matches a fresh local
   quorum verification;
5. a changed backend profile requires an explicit
   `backend_compatibility(source_fp, target_fp, state_schema)` predicate;
6. the target restores a fresh machine under the exact Ground and Program.

The backend compatibility predicate is checked on subsequent state reads
and commits until the target has committed a revision using its own backend
fingerprint. This ensures a successful restore does not silently become
permanent approval for all later work.

The first target-side quantum context preserves both backend identities:
the source backend that produced the current checkpoint, and the target
backend that is executing the next transition. The resulting M3 checkpoint
records the target backend as its producer; the predecessor checkpoint
remains unchanged and retains the source backend identity.

The session continues only if the descriptor, state schema, M1 page manifest,
recovery membership, source quorum proof, and compatibility conditions all
remain valid. A stale transfer after a newer quorum revision is committed
is refused by M3 high-water verification.

## 4. Resource and failure limits

The default quantum is at most 128 instructions, cumulative steps are bounded
at 100,000, and serialized state is bounded at 64 MiB. The transfer bundle
currently embeds the complete state bytes as base64 in one JSON object. It
is a bounded portable transfer format, not a streaming page-transfer
protocol. A future transport can send the M1 pages separately and send only
the manifest and proof in the control envelope.

The current M7 proof assumes the target can verify the same fixed recovery
membership and quorum lineage. It does not introduce membership
reconfiguration, a new quorum authority, automatic host discovery, or
automatic page-geometry conversion.

The path admits only deterministic pure transitions. It does not provide
atomic commitment of arbitrary external effects, hardware attestation,
cryptographic proof that a compatibility predicate is honest, or a universal
translation between semantically different VGI Grounds.

## 6. Composition with authenticated computational forwarding

The first end-to-end M5-M7 transfer through the computational fabric is
specified in [FABRIC_VGI_SESSION_COMPOSITION.md](FABRIC_VGI_SESSION_COMPOSITION.md)
and implemented by `VGIFabricSessionOperator` in
`mailcpu/computational_fabric_vgi.py`. The destination receives the M7 bundle
as a typed Virtual Layer workload input, imports its own M1 pages, verifies
the original M3 proof, and advances one M4 quantum under the same session
identity. The same test traverses a mutual-TLS A→B→C forwarding path and
checks descriptor, Ground, task, Program, interpretation, artifact, state
schema, backend, logical time, predecessor checkpoint, and replay continuity.
This is one bounded Signal8 experiment, not a universal session-over-fabric
protocol or an arbitrary-effect transaction.

## 5. Tests and proof boundaries

`tests/test_vgi_session.py` exercises descriptor identity, initial M1/M3
persistence, machine reconstruction, bounded execution, per-quantum retry,
cumulative step limits, independent target M1 admission, explicit backend
compatibility, and tampered transfer refusal.

These tests demonstrate the VGI Signal8 path under the pinned VGI
implementation. They do not establish that every VGI task or every other
computational domain is migratable without a domain-specific state schema,
Ground declaration, and backend compatibility contract.