# SOI-007/008 — Hosting a living original VL-I Ground in E-CPU

## Tested executable architecture

E-CPU now hosts the actual original VL-I TIME-001 temporal intelligence,
TIME-002 living observer, and TIME-005 source-signature implementation.
This is not a parallel approximation of VL-I mathematics. The original
VL-I Python code is installed at a separate admitted observer-host locus.

The source is pinned to:
https://github.com/Kier73/VL-I/commit/939b49291bb719ab531730088f759574db471c00

The original VL-I source tree contains 65 Python modules, totaling
958,045 source bytes at this pinned revision. E-CPU admits the complete
runtime package through M2's ComputationalArtifactManifest rather than
admitting only the TIME-001 module. Every worker re-verifies the actual
installed source and receives a bounded operation; it cannot select
new code, install a new handler, or grant itself CPU authority.

The owning E-CPU HeadlessOS contains native MailCPU scheduler, guest
registers/memory, kernel journal, VFS, source evidence and the entire
current VL-I Ground. E-CPU M1 stores immutable OS bytes and M3 uses its
pre-existing majority-anchored predecessor compare-and-swap to commit
the exact successor. A living interpreter is constructed from this
state on each new Python host.

| Component | Role |
| --- | --- |
| mailcpu/vli_temporal_host.py | Admit actual VL-I source as an M2 runtime; execute original interpreter and living observer methods |
| mailcpu/vli_temporal_session.py | M3 session verification, native OS semantic state publication and stale predecessor fencing |
| mailcpu/vli_temporal_worker.py | Independent one-shot Python interpreter host with injected hard-kill test cuts |
| mailcpu/vli_signed_source.py | Admit original TIME-005 signed publisher input; retain public key and signed evidence in OS |
| tests/test_vli_temporal_host.py | Real host migration, epoch drift, intention, numerical navigation, signature and adversarial tests |
| .github/workflows/vli-temporal-hosted.yml | Linux/Windows and Python 3.11/3.14 matrix |

## Reconstructable state and exact transition

Define the current committed state and Ground:

~~~
S_r = Canonical(HeadlessOS.snapshot(OS_r))
G_r = OS_r.VFS["/vli/temporal/state.json"]
H_r = G_r.head
Q_r = M3.latest_verified_quorum_revision
~~~

The original TemporalIntelligenceGround.restore accepts G_r only after
checking its exact externally supplied head, interpreter identity,
complete causal event chain, rational time ordering, and own semantic
contracts. E-CPU takes the current head from its M3-qualified state,
not from a worker-supplied replacement.

To extend the living Ground:

~~~
(Q_r, S_r) := M3.load_verified()
G_r := Original_VLI.TemporalIntelligenceGround.restore(S_r, H_r)
Sample_r := original signed-source validation, or explicitly admitted
            unsigned laboratory input on an unsigned session
Candidate_remote := New_Original_VLI_Host.execute(G_r, Sample_r, Q_r)
require Candidate_remote.M3_binding == Q_r.binding_digest
require remote M2 receipt matches source manifest, backend and request
Candidate_ref := Independent_Original_VLI_M2.execute(G_r, Sample_r)
require Candidate_ref.output == Candidate_remote.output
require original VL-I verifier accepts complete successor event chain
S_next := HeadlessOS.snapshot(with new G_{r+1} and semantic output)
Q_{r+1} := Existing_M3.CAS(Q_r, S_next)
~~~

The worker's locally staged checkpoint is marked
STAGED_FOR_M3_QUORUM. It becomes authoritative only after existing
E-CPU M3 accepts the complete new OS state. M2 receipt status EXECUTED
is deliberately separate from M3 commitment.

Deterministic state excludes host-local monotonic uptime and the
count of samples processed in this particular Python interpreter.
It preserves the actual VL-I source observations and interpretation
epochs, not hypothetical physical observations during a host outage.

The finite accepted operations are:

- temporal.ingest: original TIME-002 LiveTemporalObserver.ingest,
  with original TIME-001 checkpoint construction and causal validation.
- temporal.inquire: original TIME-002 next-observation intention.
- temporal.compile: original source-derived TIME-001 epoch interpreter.
- temporal.navigate: exact original TIME-001 rational-time navigation
  with independent source-processor verification.
- temporal.ingest_signed: an E-CPU M3 operation that authenticates the
  original TIME-005 signed packet before invoking the original
  TIME-002 ingest, then retains that signed packet beside the Ground.

## Original signed source evidence (TIME-005)

At signed session genesis, an authorized controller binds a
previously trusted publisher identity and **public** Ed25519 key into
the complete M3-admitted OS checkpoint:

~~~
/vli/temporal/source-root.json
  schema = mailcpu.vli-signed-source-root.v1
  source = external publisher identifier
  public_key = 32-byte Ed25519 public key, hex
~~~

The external publisher holds its private key; it does not reach
E-CPU worker IPC or the source interpreter. The source packet is
produced using the original VL-I sign_source_observation routine.

For every incoming signed sample, E-CPU invokes the original
verify_source_signature implementation. It requires the configured
publisher, valid Ed25519 signature, exact next sequence number,
canonical rational time/value and non-regressing publisher capture
clock. The signed packet's original domain-separated packet digest
becomes the VL-I source event's source_digest.

After E-CPU M3 commits, the exact signed packet lives under:

~~~
/vli/temporal/signed-observations/0000.json
/vli/temporal/signed-observations/0001.json
...
~~~

When any new host reads its checkpoint, it independently checks the
signature, publisher identity, sequence, values, time and packet
digest **for every historical accepted source event** against the
public key in the recovered source root. With the signed trust root
present, an unsigned temporal.ingest call is refused. The trust root
is admitted only at the empty verified VL-I Ground genesis and
cannot silently be changed or retroactively applied after unsigned history.

This authenticates the publisher's statements, not the physical
truth of those statements. The publisher and public key are
independent trust inputs supplied during original session admission.

## Evidence and adversarial controls

The eight-observation laboratory test creates different real Python
interpreter processes, reopening the existing M3 session on every
revision. The input environment changes from an affine series
1,3,5,7,9 to 30,31,32. Original VL-I detects two distinct qualified
interpretation epochs while retaining the earlier causal history.

A newly rehosted original TIME-002 observer proposes the next
observation at rational time 8/1. Another new host navigates the
second empirical epoch to time 13/2, deriving exact 63/2 with
no expanded trajectory steps. This is marked UNVERIFIED_INTERPOLATION
by the real VL-I code, not a claim to know unobserved physical state.

The signed experiment uses an independently generated Ed25519 private
key held by an external test publisher, with six consecutive signed
packets admitted by six disposable interpreter processes. Each
accepted revision is reconstructed with its original signed packets.

Negative tests include: changed signatures, wrong private key,
unsigned fallback into a signed session, duplicate source sequence,
rehashed historical signed-evidence tampering, altered Ground head,
a fabricated semantic value with a recomputed valid M2 receipt,
the lost result of an actual worker, hard-killed workers before and
after publication, and a valid obsolete observer competing with a
winning M3 predecessor CAS. A completed operation replay must not
reenter another observer host.

All source signatures are checked with the original VL-I TIME-005
function, not an E-CPU substitute. The tests reuse M1 immutable page
bytes in a controller-owned in-memory backing across reopened M3
sessions; M3's A/B/C authority journals are independently fsynced on
the same physical runner. Replaced Python observer processes are genuinely
independent; this is not controller-power-loss or three-machine
storage-failure recovery. No parallel authority system is introduced.

## Native Hypervisor authority

The same original VL-I source package is also installed as a
versioned E-CPU Virtual Layer operator through the existing
register_computational_host_operator factory. An admitted HeadlessOS
seeds its own SystemIdentity and VirtualGroundRef. A native kernel
process granted compute capability may invoke real
LiveTemporalObserver.ingest through VirtualLayerRuntime.execute_operator;
a second process without that capability is refused before execution.
Both outcomes remain in the real E-CPU kernel journal.

This directly tests native E-CPU admission of the VL-I runtime.
M3's one-shot subprocess session experiment currently invokes its
trusted registered M2 host through the session adapter; composing
per-revision remote Hypervisor authorization, mutual-TLS session
transport and IPS-008 effect admission is a next network-host step.

## Reproduction

~~~
python -m pip install -e ".[dev]"
python -m pip install "cryptography>=46,<47"
python -m pip install "git+https://github.com/Kier73/VL-I.git@939b49291bb719ab531730088f759574db471c00"
python -m pytest -q tests/test_vli_temporal_host.py tests/test_computational_session.py tests/test_computational_transition.py
~~~

Initial unsigned TIME-001/002 integration: 28 tests passed per
Linux/Windows × Python 3.11/3.14 matrix:
https://github.com/Kier73/E-CPU/actions/runs/45090065168

TIME-005 source-authenticated continuation adds original Ed25519 tests,
including trust-root immutability, and the actual E-CPU Hypervisor
capability admission/denial test. These invoke the genuine VL-I
source code and retain M3 as the state publication authority.

The focused cross-platform matrix:
https://github.com/Kier73/E-CPU/actions/runs/45090292189

## To Do toward a full hosted VL-I

1. Host and reconstruct additional VL-I states: evolving environment
   language, reflective generated processors, intention-space memory,
   recurrent causal state, versioned Grounds and larger model caches.
   Expand M1 page manifests for mutable bytes beyond a single JSON Ground.
2. Use E-CPU's real mutual-TLS worker and IPS-008 receiver freeze/activate
   barrier for external effects. The current source-authenticated
   observation host uses bounded subprocess IPC on one physical runner.
3. Put M1 backing and quorum members on independent physical machines,
   exercise network partitions and process/host/power loss independently,
   and test stale host publication at the actual receiver.
4. Admit complete pinned model weights, capability-gated inference
   backends, recoverable model-specific caches and real VL-I operator
   graphs. Distinguish real neural inference from temporal mathematical
   interpretation in receipts.
5. Benchmark simultaneous long-lived VL-I sessions, workload throughput,
   per-host and aggregate RSS, M1 state growth, event verification cost,
   quorum latency and cross-host recovery budget.

The proven implementation hosts a **real evolving VL-I Ground**, with
signed source authentication and E-CPU-owned durable OS state. A fully
realized VL-I model runtime and physical multi-machine continuity
remain the next development targets.
