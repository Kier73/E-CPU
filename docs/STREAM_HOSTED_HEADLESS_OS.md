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
