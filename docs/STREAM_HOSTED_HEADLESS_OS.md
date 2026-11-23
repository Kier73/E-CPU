# SOI-001 — HeadlessOS state in live communication streams

**Executable observation:** a complete native E-CPU HeadlessOS checkpoint crossed real AF_INET TCP between fresh Python interpreters. Distinct receiver processes reconstructed the VM, scheduler, process memories, kernel, VFS, descriptors, virtual network, services, hypervisor and event journal, advanced the OS and returned successor states. The terminal state matched independent, uninterrupted reference execution. Two hard process-kill cuts exercise recovery.

## Implementation and reproduction

- Test: [tests/test_stream_hosted_os.py](../tests/test_stream_hosted_os.py)
- Focused workflow: [stream-hosted-os.yml](../.github/workflows/stream-hosted-os.yml)
- Native OS: [mailcpu/headless.py](../mailcpu/headless.py) — HeadlessOS.snapshot, HeadlessOS.from_snapshot, HeadlessOS.run and HeadlessOS.syscall
- Exact state observer: [mailcpu/headless_relation.py](../mailcpu/headless_relation.py) — observe_headless_os_state and compare_headless_os_states
- Virtual byte-stream implementation: [mailcpu/stream.py](../mailcpu/stream.py)

    python -m pip install -e ".[dev,vgi]"
    python -m pytest -q tests/test_stream_hosted_os.py

The five focused tests cover the two-receiver continuation, payload mutation, truncation/oversize, and real process termination on both sides of successor publication. CI at commit 2d8992d: 5 passed in 3.42 seconds, https://github.com/Kier73/E-CPU/actions/runs/45085738798.

## Protocol and state relation

Let the closed OS state at a logical cut be

    S_r = (VM, scheduler, process memory, kernel, VFS, FDs,
           virtual network, services, hypervisor, journal)_r.

The test uses the native HeadlessOS snapshot as its state schema. It records initial identity SHA256(CanonicalJSON(S_0)), independently of physical host placement.

A test request is

    E_r = {schema, identity, revision=r, ticks<=200,
           consume_fd?, state=S_r, cut?}

The TCP wire frame is

    uint32_be(|CanonicalJSON(E_r)|)
      || SHA256(CanonicalJSON(E_r))
      || CanonicalJSON(E_r).

The receiver reassembles fragmented TCP input, validates its bounded length and body digest, checks envelope fields and budget, reconstructs HeadlessOS.from_snapshot, and validates the exact closed-state witness. It then invokes a native virtual socket read if requested, advances the real E-CPU scheduler, rechecks the OS relation, and returns S_(r+1) through TCP.

The independent reference executes the same operations without physical rehosting. The test asserts full OS equivalence, correct virtual process termination and final registers, and an intact kernel journal.

The network setup creates two virtual namespaces, virtual interfaces, a virtual link and connected file descriptors. Six bytes are written to the OS's own virtual stream before the first physical rehost. The receiver consumes those six queued bytes after restoring the state from physical TCP. A second physical receiver finishes the guest process.

## Failure cuts

**Before publication:** the worker executes the OS locally and sends only its prepared state digest. The parent hard-kills the worker. No complete successor was received, so the parent starts a new worker from its previous known S_r. The virtual socket read and computation are retried using closed state and produce the reference result.

**After publication, before acknowledgment:** the worker executes, transmits the complete successor S_(r+1) over TCP, and blocks for acknowledgment. After the parent has received that checkpoint, it hard-kills the worker. A different process continues from S_(r+1) rather than recalculating the first segment. Its final OS state also equals the reference.

The parent is the experiment's single serialization point. These are process-failure and transport-state experiments, not distributed quorum-commit proofs. Wire SHA-256 detects accidental frame alteration but supplies no sender authentication; parent-supplied identity and revision metadata are not M3 authority commitments. Guest operations execute on the receiving processor; an ordinary TCP link transports bytes rather than executing guest instructions itself.

## Native E-CPU integration map

| Required capability | Already implemented | Next composition |
|---|---|---|
| Complete OS state | HeadlessOS.snapshot/from_snapshot | Declare a versioned M3 OS schema |
| Immutable state storage | M1 ComputationalObjectStore | Transmit bounded manifest/page references |
| Accepted current revision | M3 ComputationalSessionStore | Quorum high-water and predecessor CAS |
| Typed state transition | ComputationalSessionTransitionAdapter | HeadlessOS domain backend with exact budget |
| Authenticated routing | mTLS, ReliableChannel, computational fabric | Receiver-authorized multi-hop transport |
| External resource fencing | IPS-007 and IPS-008 | Receiver freeze/activate before OS rehome |
| Restarted endpoint rejoin | continuous_session | Fresh route to the original stable session |
| Verification | headless_relation | Cross-host state/receipt comparison |

## To Do

1. Commit serialized HeadlessOS state to M1/M3 and enforce one authoritative OS high-water despite concurrent hosts, stale frames and retransmissions.
2. Send object references instead of full snapshots, then measure byte volume, snapshot and restore cost, path latency and transfer/recovery savings.
3. Hard-kill each host at every M3 prepare, quorum commit, response and receiver handoff boundary; prove that current state is chosen by the exact quorum root rather than network arrival order.
4. Compose IPS-008 effect barriers with the OS process/resource namespace so an obsolete host cannot modify receiver-owned external state.
5. Distribute pages and recovery authorities across independent machines, and measure safety, recovery and unavailable-quorum refusal under path and machine loss.
6. Use E-CPU path Grounds to identify operations natively available in permitted communication media and services (queue order, buffering, protocol predicates, forwarding), and qualify those as OS transition loci rather than merely checkpoint carriers.

This experiment reuses native E-CPU operating-system and scheduler dynamics. It introduces neither a replacement virtual machine nor a second quorum authority.


## SOI-002 — Quorum-authoritative HeadlessOS stream continuation

The next composition uses the existing M1 immutable object store, M3 session
checkpoint, recovery-lineage quorum and pure-transition CAS rather than
letting the transport receiver choose the authoritative OS state. The concrete
module is [stream_os_session.py](../mailcpu/stream_os_session.py), with
[executable integration tests](../tests/test_stream_os_quorum.py).

### Exact native transition contract

The state is the canonical JSON byte representation of the entire
HeadlessOS.snapshot() result, admitted only after the existing
observe_headless_os_state test. The session declares:

- State schema: mailcpu.headless-snapshot.v1
- Input schema: mailcpu.headless-pure-step.v1
- Transition ID: headless.os.continue.v1
- Backend/interpretation identities: SHA-256 of explicit versioned strings
  exposed as OS_BACKEND_FINGERPRINT and OS_INTERPRETATION_FINGERPRINT
- Input: canonical {"schema","ticks","read_fd","read_size"} mapping
  with 1 <= ticks <= 200 and virtual read size <= 4096
- Effect contract: deterministic, pure, snapshot-covered operations only
- Byte limit in the experiment: 4 MiB per complete OS state

The system is initialized using the real ComputationalSessionStore.create_session,
not an alternate checkpoint format. For each operation:

    Current = M3.load_latest()  # verified fixed-membership majority high-water
    Context = (session ID, revision, checkpoint digest, lineage digest,
               state digest, backend and contract identity, operation and input digest)
    Candidate = observer_host.execute(Current.state_bytes, input_bytes, Context)
    Reference = HeadlessOS.from_snapshot(Current.state_bytes)
    Reference.apply_the_same_native_virtual_io_and_scheduler_step(input_bytes)
    require(compare_headless_os_states(Candidate, Reference).equivalent)
    Next = M3.commit_state(Candidate, expected_revision=Current.revision,
                           expected_checkpoint_digest=Current.checkpoint_digest,
                           transition_id, operation_id, input_digest, logical_time)

The public M3 adapter implements the load/validate/CAS phases, and the new
HeadlessOSQuorumTransitionBackend implements the closed-state observation,
remote proposal and **independent reference check**. It returns candidate
bytes only when the native full-system state is equivalent to local reference
execution, including the VM, process registers, kernel, virtual queued stream,
journal, services and hypervisor state. This deliberate duplicate reference
execution is a strong initial correctness oracle, not an acceleration claim.

The provided execute_remote callable identifies the remote execution binding.
SOI-002's test binds it to SOI-001's fresh-process loopback TCP carrier.
The M3 authority remains local to the test runner: a real fixed 3-member
A/B/C quorum with separately fsynced durable authority journals, real M1
content-addressed 4 KiB pages, and immutable checkpoint envelopes.
Reopening a new ComputationalSessionStore with the same journals and M1
backing rereads the exact latest quorum-supported high-water.

### Execution and failure invariants

| Boundary | Native check |
|---|---|
| Worker result arrives | Restore closed OS; verify native journal and state; compare full successor to independent reference |
| Worker dies before delivering successor | M3 checkpoint/lineage remain at previous revision; fresh worker can retry |
| Worker dies after TCP successor, before acknowledgment | Caller verifies candidate and quorum-commits once; duplicate operation returns M3 replay without re-entering remote backend |
| A late old worker completes a correct transition | If another OS successor has advanced the quorum root, stale expected revision/digest fails at M3 CAS |
| A worker forges an extra valid VFS mutation | Exact full-system relation differs from the independent reference; M3 cannot accept it |
| Two distinct operation inputs use the same ID | The existing M3 adapter refuses the conflicting replay |
| Changed or damaged M1/state bytes | Existing M1 and M3 integrity checks prevent accepting the checkpoint |

The race experiment deliberately allows an old independently executing TCP
worker to finish its guest instructions, pauses before CAS, commits a different
successor from another worker, and then releases the old writer. Its local
candidate remains an observation but cannot become current. This tests the
difference between **a valid computed successor** and **the authoritative
committed session state**.

### Minimal repository-native API

    from mailcpu.stream_os_session import (
        HeadlessOSQuorumTransitionBackend, serialize_headless_state,
        encode_headless_step, OS_STATE_SCHEMA, OS_BACKEND_FINGERPRINT,
        OS_INTERPRETATION_FINGERPRINT, OS_TRANSITION_ID, OS_STEP_INPUT_SCHEMA,
    )
    from mailcpu.computational_transition import (
        ComputationalTransitionContract, ComputationalSessionTransitionAdapter,
    )

    # store is an existing M3 ComputationalSessionStore with M1 backing and
    # independent fixed-membership recovery-lineage authority journals.
    store.create_session(serialize_headless_state(operating_system))
    contract = ComputationalTransitionContract(
        transition_id=OS_TRANSITION_ID,
        state_schema_id=OS_STATE_SCHEMA,
        input_schema_id=OS_STEP_INPUT_SCHEMA,
        interpretation_fingerprint=OS_INTERPRETATION_FINGERPRINT,
        backend_fingerprint=OS_BACKEND_FINGERPRINT,
        max_input_bytes=1024, max_state_bytes=4_194_304,
    )
    backend = HeadlessOSQuorumTransitionBackend(execute_remote)
    controller = ComputationalSessionTransitionAdapter(store, contract, backend)
    current = store.load_latest()
    committed = controller.apply(
        encode_headless_step(ticks=8),
        operation_id="os-step-0001",
        expected_revision=current.revision,
        expected_checkpoint_digest=current.checkpoint_digest,
    )
    assert committed.revision == current.revision + 1

The example's execute_remote must be an explicitly supplied, trusted
network-executor binding; it is not an implicit discovery or admission
mechanism. The experiment deliberately uses the existing SOI-001 test
carrier and does not introduce an additional unauthenticated production
ingress service.

### To Do: crossing independent authority and effects domains

1. Replace the test-only TCP transport callback with an authenticated E-CPU
   mTLS/Virtual Layer operation carrying the exact M3 transition context and
   bounded M1 state references. Require receiver-local host/operator admission.
2. Move M1 pages and fixed recovery authorities into independently controlled
   storage/failure domains. Kill the original owner machine and distinguish
   safe refusal when quorum is absent from successful restoration when it survives.
3. Add IPS-008 PREPARE/ACTIVATE freezes around receiver-owned external effects
   before accepting a new execution host's assignment. The current pure OS
   transition contract admits only snapshot-contained effects.
4. Measure the full-snapshot TCP cost, content-addressed manifest/page reuse,
   duplicate-reference-verification cost, end-to-end recovery time and
   authenticated multi-hop overhead separately. Explore proof-carrying
   transition receipts to replace duplicate interpretation where qualified.
