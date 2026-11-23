# SOI-003/004 — Real VL-64 runtimes hosted by an E-CPU VM fleet

## Executable result

The E-CPU core hosts a **real, pinned VL-64 0.7.0 source package** through
its original M2 ComputationalBackendAdapter and Virtual Layer Hypervisor. A
benchmark on one Linux GitHub Actions runner created **64 separate fresh
Python processes**, each independently booting a HeadlessOS, its native
MailCPUVirtualMachine, scheduler, virtual guest memory and kernel, and
binding a genuine imported vld runtime to a locally registered M2 operator.

Run (original 4-op baseline): https://github.com/Kier73/E-CPU/actions/runs/45088291787

Current six-operation, 64-instance benchmark and cross-platform CI:
https://github.com/Kier73/E-CPU/actions/runs/45088977273
Pinned VL-64 source commit: fea0d29d5a8a1edb03d9c66edd5ca4b15a1395d3

| Observation | Measured |
|---|---:|
| Accepted HeadlessOS/VM instances | 64 |
| Distinct actual Python host-process IDs | 64 |
| Peak simultaneous Python VM-host workers (orchestrator ceiling) | 8 |
| Native VL-64 operations via M2/Hypervisor | 384 |
| Full guest working-set bytes (2 pages/VM) | 524,288 B |
| Combined full OS snapshot encoding | 20,880,424 B |
| Total fleet wall time in this runner trial | 10.2635 s |
| Checkpoints and math/receipt checks | 64/64 accepted |
| VM count refused under 128-page budget | 8 of 72 requested |
| Actual VL-64 core source footprint | 65,460 bytes |
| Host RSS at completion (mean, Linux) | 46,038,592 B per Python process |
| Source package content digest | c7e670767c7f4470b96f8c4fae3fe8199d708165b7e779b0af7dd873c9e17256 |

This 64-instance result establishes an admitted count for the **declared
logical guest-page budget and bounded VL-64 workload**. It is a density
sample, not an exhaustive physical RAM maximum or sustained throughput claim.
The 512 KiB count is guest pages, not host Python resident memory; measured post-work Python RSS averaged about 46.04 MB per host. The
benchmark schedules up to eight worker processes at once; each VM still
receives a unique process on execution.

## The actual implementation

- Core adapter: [mailcpu/vl64_runtime.py](../mailcpu/vl64_runtime.py)
- Native virtual-layer integration: [mailcpu/computational_host.py](../mailcpu/computational_host.py)
- Quorum-backed application: [mailcpu/vl64_session.py](../mailcpu/vl64_session.py)
- Disposable actual VL-64 process: [mailcpu/vl64_worker.py](../mailcpu/vl64_worker.py)
- Capacity benchmark: [scripts/benchmark_vl64_fleet.py](../scripts/benchmark_vl64_fleet.py)
- M2/Hypervisor tests: [tests/test_vl64_runtime_host.py](../tests/test_vl64_runtime_host.py)
- Multiple interpreter tests: [tests/test_vl64_hosted_fleet_process.py](../tests/test_vl64_hosted_fleet_process.py)
- M3 application-session tests: [tests/test_vl64_quorum_session.py](../tests/test_vl64_quorum_session.py)
- CI: [.github/workflows/vl64-hosted-fleet.yml](../.github/workflows/vl64-hosted-fleet.yml)

### What is running where

**E-CPU VM:** native MailCPU instructions execute through their normal
scheduler in a full HeadlessOS with independent kernel, VFS, journal, process
table and 4 KiB guest pages. E-CPU's Hypervisor decides whether a local
service process is allowed to invoke vl64.core.run; an unauthorized process
cannot grant itself compute access through a request.

**VL-64:** its *original* Python functions execute at an admitted observer-host
locus. The E-CPU M2 backend loads the real package, whose source manifest is
verified against its exact SHA-256 component digests. The runtime's Python
interpreter and modules are hosted outside MailCPU's virtual instruction set.
This makes the composition a real **hosted VL-64 runtime**, rather than a
claim that MailCPU can decode Python or boot a Linux system image.

A hosted operation is selected from a finite trusted local catalogue, not
supplied as user-authored code. Current operations:

- affine.navigate — genuine vld.affine_navigate using compositional jumps;
- intention.realize — genuine vld.IntentionCompiler with selected plan receipt;
- ground.cycle — genuine vld.ObservedGround with observed closed cycle;
- page.cow — genuine vld.PageSpace parent/child copy-on-write.
- core.verify — genuine vld.run_self_verification (five invariants).
- vm.nested — genuine vld.HeadlessOS fork, CoW bytes, descriptors and W^X refusal.
- page.session — mutable vld.PageSpace application bytes preserved by M3.

M2 results bind the exact source manifest digest, implementation/profile
fingerprint, request/input digest, host ID, logical time, output bytes and a
deterministic EXECUTED receipt. The enclosing Virtual Layer/Hypervisor
operation is responsible for deciding and recording the committed effect.

The finite operation set uses genuine VL-64 operators across different classes of the
actual VL-64 runtime. Broader functions are added through explicitly
registered backend methods, not broad reflective Python execution.

## SOI-004 — State that follows intention and survives its executing host

The same VL-64 application can now advance a **quorum-anchored HeadlessOS
session** rather than returning an ephemeral result. It composes the existing:

- M1: immutable state-object pages and SHA-256 content manifests;
- M3: authenticated-in-the-sense-of-fixed-local-quorum **lineage proof**, not
  network peer authentication; predecessor compare-and-swap and idempotent
  operation retries;
- M2: actual VL-64 semantic operation and immutable artifact identity;
- HeadlessOS: native VFS files, kernel, process/scheduler and journaling.

For the complete committed state S_r, request x_r, and source-admitted
backend B, an ordinary operation is:

    Context_r = M3.load_latest_verified()
    Remote_r = RemoteVL64Host(B).execute(x_r, Context_r)
    require(Remote_r.context_binding_digest == Context_r.binding_digest)
    require(Remote_r.receipt identifies source B and allowed host and request)
    require(SHA256(Canonical(Remote_r.output)) == Remote_r.receipt.output_digest)
    Reference_r = IndependentLocalM2VL64(B).execute(x_r)
    require(Remote_r.output == Reference_r.output)
    OS_next = HeadlessOS.from_snapshot(S_r)
    OS_next.install_source("/vl64/results/{time}_{operation_id}.json",
                           Canonical(semantic_output_without_host_receipt))
    OS_next.run(next_bounded_native_scheduler_tick)
    S_candidate = Canonical(HeadlessOS.snapshot(OS_next))
    S_{r+1} = M3.commit_state(S_candidate,
                             expected_revision=r,
                             expected_checkpoint_digest=Context_r.checkpoint_digest)

The **state contains the semantic answer and the native VM context**.
The host-specific execution receipt stays outside the committed OS state,
so another host's equivalent answer can reconstruct the same semantic
state without forging the previous worker's physical identity.

M3 is the only publication authority. In the test, a three-member
A/B/C fixed-membership quorum writes independently fsynced journals on
the same CI machine. A new process can reopen these journals and the
unchanged M1 page backing to recover the current state. This qualifies
durable **process failure** and stale publisher refusal, not physical
three-server consensus or externally effectful ownership transfers.

Adversarial tests exercise:
1. two different Python interpreter worker hosts, with M3 session-store
   reopening and preserved earlier virtual filesystem results;
2. exact retry of a committed operation without remote reexecution;
3. forged M3 context and a valid recomputed M2 receipt covering a
   *semantically wrong* value;
4. a delayed old worker which successfully executes VL-64 but loses
   M3 publication to an earlier competing commit; and
5. a lost worker response: its private pure work does not advance M3,
   while an independent host can repeat it.

A concrete security boundary is that SHA-256 input correlation is not peer
authentication. The worker protocol is local subprocess IPC with a fixed
registered operation set; deploy an authenticated E-CPU transport and
receiver-local capability admission before opening it to another machine.

## Repeat the full measured workload

    python -m pip install -e ".[dev]"
    python -m pip install "git+https://github.com/Kier73/VL-64.git@fea0d29d5a8a1edb03d9c66edd5ca4b15a1395d3"
    python -m pytest -q tests/test_vl64_runtime_host.py tests/test_vl64_hosted_fleet_process.py tests/test_vl64_quorum_session.py
    python scripts/benchmark_vl64_fleet.py --vm-count 32 --max-concurrent 8 \
        --guest-page-budget 64 --output vl64-hosted-fleet-32.json

The official workflow tests Linux and Windows on Python 3.11 and 3.14,
and writes a distinct 32-worker Linux/Python 3.13 capacity artifact.
OS/VL-64 memory and materialization behavior must be measured with
actual host RSS and not inferred from 4 KiB guest page totals.

## To Do — toward full VL-I hosting

1. **Long-lived interpreter/application state.** Today the admitted methods
   are pure and the durable application record retains semantic outputs.
   Add typed mutable VL-64 Ground / intention history / page-space snapshots
   and a schema migration path for interpreter or VL-I session state.
2. **Native E-CPU remote host authority.** Replace one-shot local subprocess
   transport with E-CPU authenticated mTLS execution and receiver-fenced
   IPS-008 external effect admission. The M3 quorum remains authoritative.
3. **Real source/model runtime.** Compose VL-I's original environment and
   source-observer processes as typed host services, including persisted
   state, ground revisions, system tools and native model runtime/weights
   when required. Verify actual state continuity and capability enforcement.
4. **Sustained fleet performance.** Run larger counts and long-duration
   mixed work. Record Python RSS, GPU/CPU load, scheduling latency, M1 growth,
   real network bytes, replay cost, lifecycle teardown, worker failure,
   quorum partition and recovery duration.
5. **Proof-carrying pure compute.** Reference reexecution is deliberately
   conservative and may double the computational work. Replace it only for
   qualified operations with independently checkable proof/witness paths
   preserving equivalent semantic refusal behavior.

The platform has demonstrably hosted real VL-64 packages at 32 independent
observer-host loci. Hosting a complete VL-I process is a next integration
task, not an extrapolated claim from the four pure VL-64 methods.


## SOI-005 — Persistent genuine VL-64 application memory

The first durable VL-64 service stores a bounded 256-byte live
application region (executed through the actual 4 KiB vld.PageSpace)
at the native virtual OS path /vl64/session/page-state.json.
The caller supplies only an offset and write bytes; the M3
controller reconstructs the authoritative previous state from its
quorum-verified OS snapshot, checks its full-page digest and prior
logical timestamp, then binds these bytes into the source-admitted
M2 request. The remote worker may propose a successor but cannot
supply an alternative historical source.

After the independent M2 reference re-executes the same actual vld
PageSpace transition and agrees with the remote output, the controller
writes the new application memory and digest inside native HeadlessOS
VFS and uses original M3 CAS to commit its complete successor state.
The host-specific M2 execution receipt remains outside the
quorum-committed state; that state retains portable semantic results.

The tests advance the same PageSpace via three separate real Python
interpreter hosts, reopening the M3 store on every revision:

    initial -> "vl64" -> "vl64-m3-" -> "vl64-m3-state"

They verify byte identity, full-page SHA-256, logical time, earlier
results, M3 lineage, exact no-reexecution retries and refusal of a
corrupted predecessor application state **before remote execution**.

This qualifies a portable bounded mutable application memory, not
the entire arbitrary VL-I Python process heap or pretrained neural
KV cache. Scaling means moving large state into M1 page manifests
and recovering only the page ranges a new observer needs.

## SOI-006 — Synchronized fleet capacity

The new simultaneous_gate mode requires every admitted VM/host
subprocess to boot its native E-CPU OS, load the source-admitted VL-64
backend, publish a ready PID and block before the orchestrator
releases *any* application operations. The report records the exact
simultaneous_live_ready_count. A requested gate larger than
max_concurrent_processes fails admission before subprocess startup.
Use the published CI artifact to distinguish 64 processes over time
from 64 actually live and prepared simultaneously.
