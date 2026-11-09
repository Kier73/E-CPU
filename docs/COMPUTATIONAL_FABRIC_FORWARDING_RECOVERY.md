# Federated forwarding recovery: per-peer state and replay

## Purpose

This document specifies the first recovery image for an authenticated computational-fabric forwarding peer. It composes existing state owners instead of introducing a second scheduler, execution ledger, or recovery quorum:

- `HeadlessOS` owns the local VM, capabilities, journal, Hypervisor decisions, and committed execution/replay ledger.
- `ReliableChannel` owns transport sequence cursors, delivered history, outgoing pending frames, retry state, and acknowledgements.
- `HypervisorOperationResultChannel` owns the semantic result de-duplication ledger in addition to its reliable outgoing queue.
- `RecoveryLineageCoordinator` owns the strict-majority, monotonic checkpoint-generation root.

The recovery image is **per peer**. It is not a distributed snapshot and does not imply that every peer has committed the same global transaction.

## Captured state

`ComputationalFabricForwardingServer.snapshot()` runs under the server transition lock and captures:

| State | Owner | Why it is required |
|---|---|---|
| VM, process capabilities, journal, Hypervisor arbitration and effect replay records | `HeadlessOS` | Reconstruct the same local authority and replay an already committed operation without calling its handler again |
| Incoming reliable request channel | server's `HypervisorOperationChannel` | Preserve peer/channel identity, receive cursor, duplicate history and any outgoing ACK/retry state maintained by the wrapper's reliable channel |
| Outgoing result reliable channel and semantic `seen` set | server's `HypervisorOperationResultChannel` | Re-publish unacknowledged receipts and avoid forgetting which semantic identities have been returned |
| Every downstream client's request and response channels | each `ComputationalFabricForwardingClient` | Preserve next-hop sender sequence, pending outbound requests, response receive cursor and semantic downstream-result identities |
| Local/previous/origin identities, authority PID and bounded service settings | forwarding server | Re-bind the recovered runtime to the same peer and operation namespace |

The incoming request's *unacknowledged frame payload* remains owned by the preceding peer's outbound reliable sender, not copied into the receiver's channel snapshot. Reliable transport keeps an unacknowledged request pending at its sender until an ACK arrives. Therefore a recovery set for a pre-ACK cut must include both adjacent peers' images: the receiver's receive cursor/replay state and the previous peer's sender snapshot. The previous peer retransmits the exact original semantic operation identity over a fresh connection. This avoids inventing an independent second owner for an inbound frame.

The snapshot intentionally omits TLS socket objects, authenticated TLS sessions, active remote directory leases/snapshots, local runtime callables, and portable capability grants. Endpoint metadata and stable peer/channel identities are retained, but the restored service must reconnect and revalidate them.

## Named transaction cuts

The server exposes a fault hook through `serve_once(fault_hook=...)`. The hook can seal a checkpoint on the serving thread at the named boundaries below. A re-entrant transition lock permits this capture while the same thread owns the in-flight service transition.

| Capture cut | Inbound request | Local execution ledger | Outbound response | Recovery action |
|---|---|---|---|---|
| `before_execution` | Still unacknowledged | No effect committed yet | Not published | Previous peer retransmits; this peer performs the first execution |
| `after_execution_commit` | Still unacknowledged | Effect and operation identity committed | Not published | Previous peer retransmits; Hypervisor returns the stored effect as replay, without re-entering the handler |
| `after_response_publish` | Still unacknowledged | Effect committed | Result frame pending until ACK | Request replay resolves from the local ledger; outbound result may be retransmitted; requester semantic ledger suppresses duplicates |
| `after_request_ack` | Consumed and ACKed | Effect committed | Result frame remains pending until its own ACK | A retransmitted copy of the already-consumed transport sequence is ACKed without re-entering the Hypervisor; the pending result remains the delivery owner |
| `idle` | Between operations | All prior committed state retained | No in-flight handler transition | Resume normal service |

A reliable transport retry must be distinguished from a new delivery of the same semantic operation. When an incoming frame has sequence (s < r), where (r) is the restored receive cursor, the receiver validates its persisted payload digest, consumes and ACKs the stale frame, and does not authorize or execute it again. Reliable-channel snapshot schema v5 stores the digest for each newly delivered sequence so a changed payload cannot reuse an acknowledged sequence after restore. Legacy snapshots remain readable; for previously delivered legacy sequences without a digest, the old duplicate is still never re-executed.

A new transport sequence (s=r) carrying the same semantic operation identity is different: it is a new reliable delivery. It advances the receive cursor and reaches the Hypervisor semantic execution ledger, which returns the committed result without re-entering the handler. This is the intended recovery path after `after_response_publish`, where the request had not yet been ACKed and the requester must be able to obtain the cached result again. The sender-side forwarding client also reconciles the request ACK after receiving a result, so an ordinary completed call does not accidentally reuse an acknowledged transport sequence on its next semantic retry.

The result channel applies the same two-dimensional distinction on the return path. An old response transport frame with `s < r` that repeats an already-observed semantic result is ACKed and suppressed; it must not be returned to a later RPC invocation that happens to use the same semantic operation identity. A fresh response frame with `s = r` carrying that same cached semantic result advances the response cursor and is returned with its semantic replay flag. This prevents an old retransmission from satisfying a new request before the relay has consumed that request, while preserving legitimate cached-result replay on a new transport delivery.

For a relay, its Hypervisor handler may synchronously complete a downstream hop before the relay's own local execution result is committed. The relay's `after_execution_commit` cut therefore records the downstream receipt inside the relay's own effect ledger. Replaying that relay operation returns the stored receipt and does not invoke the downstream client again.

## Durable generation and restore protocol

`ComputationalFabricForwardingRecoveryStore.seal(server, capture_cut)`:

1. obtains a consistent local server snapshot under the forwarding transition lock;
2. validates the exact snapshot schema and capture-cut label;
3. serializes canonical sorted compact JSON bytes;
4. writes the peer snapshot and typed `RecoveryStateManifest` into a new immutable generation directory;
5. flushes and fsyncs both files and the staging directory, atomically publishes the generation directory, and best-effort fsyncs its parent;
6. commits the manifest root through the configured strict-majority `RecoveryLineageCoordinator`.

A generation that is locally durable but not quorum-anchored is not recoverable. `load_latest()` obtains the quorum high-water first, verifies the exact stored payload digest, canonical manifest, and matching generation, then returns a `VerifiedComputationalFabricForwardingCheckpoint`. Modified, unanchored, or older generations are rejected. The returned object rechecks its in-memory snapshot projection against the same immutable payload digest before any OS/service restore, so mutating the loaded Python mapping cannot alter the restored state.

The `seal(server, cut)` path holds the peer's re-entrant transition lock through the durable file publication and quorum commit. The serving transition cannot advance beyond the selected cut while that generation is being anchored. Callers using `seal_snapshot(value, cut)` provide an already captured immutable projection and are responsible for coordinating that capture with the peer's transition lock.

Each peer must have a peer-scoped `RecoveryLineageCoordinator` and its own fixed-membership authority journals (with a peer-specific lineage/system identity). Do not share one single-state high-water coordinator across several peers: each `load_latest()` would otherwise refer to whichever peer most recently advanced that shared lineage. A future cluster-wide atomic snapshot would need a distinct multi-peer manifest that binds all participating peer artifacts together, not reuse of this single-peer store.

The caller then:

1. loads the verified peer generation before constructing a replacement service;
2. restores `HeadlessOS` from the exact verified snapshot (including its Hypervisor replay ledger);
3. rebuilds local executable runtime/catalogue objects against that restored OS using trusted local code;
4. refreshes the peer directory by direct mutual-TLS observation; no old remote lease is revived;
5. reconnects the previous peer and each next hop over fresh mutually authenticated TLS streams;
6. uses `VerifiedComputationalFabricForwardingCheckpoint.restore_server()` or `ComputationalFabricForwardingServer.from_snapshot()` to rebind the reliable channel snapshots to those streams;
7. has each previous peer retransmit any still-pending request using its own saved sender channel state.

Restore checks the exact downstream-peer transport set and verifies that every reliable channel's source, destination, peer, and operation channel match the captured identities. A caller-supplied OS object is accepted only when its full snapshot equals the checkpointed OS state. The terminal catalogue/runtime is deliberately rebuilt by local code; no callable or grant is deserialized.

## Process-level recovery experiments

The process experiments in [FEDERATED_FORWARDING_PROCESS_RECOVERY.md](FEDERATED_FORWARDING_PROCESS_RECOVERY.md) cover two different failure boundaries:

- **Relay B crash:** B is killed and restarted at each of its four forwarding cuts. A's saved sender state and C's independently captured terminal image provide the adjacent state needed to reconstruct the route. B reopens its local owner journal, reconnects to two independent recovery authorities, authenticates fresh A/B and B/C streams, and restores its own Hypervisor and downstream channel ledgers.
- **Terminal C crash:** C is killed and restarted at each of its four terminal cuts while B remains alive. C owns a separate peer-scoped checkpoint lineage and two independent recovery authorities. The relay supervisor observes a terminal downstream `SocketTransport`, reconnects to C over fresh mutual TLS, and calls `rebind_next_hop_transport`; the server swaps only the transport binding while preserving the downstream request/response reliable ledgers. C remains a service after restart: when its previous adjacent stream becomes terminal, it accepts a replacement authenticated stream and calls `rebind_transport`, which reattaches the server's inbound and outbound reliable channels without reconstructing the VM or result ledger. If the old request remains pending, `send_or_retransmit` sends the exact pending frame; if C already ACKed it, B can send a new transport frame carrying the same semantic operation identity. C's restored Hypervisor ledger supplies the committed effect without re-entering the operator. The process test no longer manually asks B to reconnect; it requires B's autonomous reconnect count to be positive and verifies one unchanged semantic operation history across the replacement stream.

A separate TCP transport test checks that pending semantic retransmission reuses the original sequence and refuses a changed fingerprint. The terminal-process test also issues a second distinct operation after recovery to prove the replacement path can continue doing useful work.

These are test implementations, not a claim of universal fault tolerance. CI status for the exact branch head must be checked before treating the new terminal-process experiment as verified.

## Explicit proof boundary

The earlier in-process A→B→C rebind test remains useful for isolating the recovery adapter, but it is not a process-kill proof. The B and C subprocess tests are separate runs; they do not yet demonstrate both peers crashing in sequence during one continuous operation history. The test supervisor owns A, and directory observations are supplied by fixtures rather than learned from a production peer-discovery service. Recovery-authority streams use peer-identified loopback `SocketTransport`; forwarding adjacencies use mutual TLS.

The per-peer checkpoint does not make a multi-peer snapshot globally atomic. Each peer has its own quorum-anchored generation and channel state; recovery reconciles those states through stable semantic operation identity and the existing Hypervisor ledgers. The tests exercise deterministic pure computation, not arbitrary external side effects. Exactly-once behavior for such side effects requires durable idempotency or an effect journal at the actual side-effect owner.

The digest is an integrity binding and the RecoveryLineage quorum supplies the rollback-resistant high-water decision. This is not hardware attestation or a signature over each hop receipt. Immediate neighbors authenticate through mutual TLS; origin trust remains transitive through configured relays.

## Tests

```sh
python -m pytest tests/test_computational_fabric_forwarding_recovery.py -q
python -m pytest tests/test_computational_fabric.py -k federated_workload_forwards_over_two_authenticated_hops_and_replays_once -q
python -m pytest tests/test_hypervisor_transport.py -q
python -m pytest tests/test_federated_forwarding_process_recovery.py -q
python scripts/verify_invariants.py
python scripts/verify_repo.py
```
