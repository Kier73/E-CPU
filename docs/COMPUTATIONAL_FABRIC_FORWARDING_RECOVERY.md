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
| `after_request_ack` | Consumed and ACKed | Effect committed | Result frame remains pending until its own ACK | No request retransmission is needed; result channel retransmits until the requester acknowledges it |
| `idle` | Between operations | All prior committed state retained | No in-flight handler transition | Resume normal service |

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

## What the current integration proves

The A→B→C test now:

- executes a federated workload across two distinct mutually authenticated TLS streams;
- captures A's requester channel pair plus B's relay and C's terminal peer state;
- closes the original streams;
- restores B and C from their peer snapshots and restores A's channels over fresh TLS connections;
- retransmits the exact semantic operation identity;
- receives the same digest-linked receipt;
- verifies that the terminal operator's invocation count remains one.

Separate recovery-store tests verify quorum anchoring, reopening with the same durable authority journals, modified-artifact refusal, older-generation refusal, and rejection of unknown transaction cuts.

## Explicit proof boundary

This is a per-peer image and fresh-stream rebind/replay proof under one supervising test process. It is **not yet** the hard OS-process termination/restart proof for a federated relay or terminal peer. The next experiment is a subprocess harness that kills B or C at every named cut, independently restarts that peer from its anchored generation, restores adjacent sender/receiver channel state, and checks the same at-most-once handler-entry and eventual receipt behavior.

The per-peer checkpoint does not make a multi-peer snapshot globally atomic. Each peer has its own quorum-anchored generation and channel state; recovery must reconcile those states by retransmitting the same immutable operation identity through the existing Hypervisor ledgers.

The digest is an integrity binding and the RecoveryLineage quorum supplies the rollback-resistant high-water decision. This is not hardware attestation or a signature over each hop receipt. Immediate neighbors authenticate through mutual TLS; origin trust remains transitive through configured relays. The workload tested so far uses deterministic pure computation. Exactly-once behavior for arbitrary external side effects still requires durable idempotency or an effect journal at the actual side-effect owner.

## Tests

```sh
python -m pytest tests/test_computational_fabric_forwarding_recovery.py -q
python -m pytest tests/test_computational_fabric.py -k federated_workload_forwards_over_two_authenticated_hops_and_replays_once -q
python scripts/verify_invariants.py
python scripts/verify_repo.py
```
