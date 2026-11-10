# Claim-Bound Fabric Admission

## Purpose

This increment connects the quorum-fenced transferable execution claim to actual partitioned computation. A claim is no longer only an owner-side record: it travels with the child computation, is checked by the terminal Host before its normal Hypervisor path, survives relay/receipt serialization, and is revalidated by the origin after the response.

The implementation reuses the existing `ComputationalFabricForwardingEnvelope`, `ComputationalAddressResolver`, `ComputationalExecutionAdmissionCoordinator`, `RecoveryLineageCoordinator` and `NavigableComputationDAG`. No parallel transport, receiver admission, or result-winner ledger is introduced.

## Batch assignment before sibling dispatch

All claims in one parent frontier must be created before any child is sent. The owner store's `create_many()` writes all new child assignments into one immutable claim-state generation and returns one compact Merkle ticket for each claim. All tickets therefore refer to one root and one shared freshness point.

A one-child-at-a-time claim loop would be incorrect: each new claim advances the global high-water and makes tickets already issued to earlier siblings stale. The `get_many()` operation refreshes an ordered set of tickets from one live generation; it does not mutate the ledger.

The production binary dispatcher exposes `prepare_execution_claims()` and `refresh_execution_claims()`. The partitioned dispatcher invokes the batch preparation before its first child send. If authority preparation fails, no sibling request is dispatched.

## Forwarding envelope v2

Unclaimed requests retain the legacy forwarding envelope v1. A claim-bound request uses v2 and adds:

- the original parent request digest; and
- the compact portable claim ticket for the exact child request and `ComputationalAddress`.

Envelope construction verifies that the claim binds the child intention's request digest, address digest, operator ID/version/contract, Computational Ground, and the route's assigned peer, logical Host and pinned implementation. Every relay advances the existing route cursor while preserving the same parent digest and ticket. Relays do not independently grant terminal execution authority.

The ticket is bounded by the claim protocol's 128 KiB transport limit and contains no full claim registry snapshot. Its Merkle path is bounded to 14 siblings for the configured 16,384-claim owner ledger.

## Terminal Host admission

A claim-bound terminal receiver must be configured with its own live `RecoveryLineageCoordinator`, normally a `DistributedRecoveryLineageCoordinator` using the existing mutual-TLS authority service. This live authority is a runtime dependency and is deliberately not serialized into a forwarding checkpoint; restore callers must rebind it.

An execution Host may also be configured with a direct mutual-TLS `ComputationalFabricPeerClient` to the claim owner, supplied in `ComputationalFabricForwardingServer.claim_status_clients` under the origin peer ID. The owner-side `ComputationalFabricPeerServer` or restart-aware `ComputationalFabricPeerListener` receives the durable `TransferableExecutionClaimStore` through `execution_claim_store`. This is a peer-control RPC over the existing authenticated peer service, not a relay operation or a second consensus path.

The status request identifies the claim and expected logical Host. The owner returns a fresh ticket only when the TLS-authenticated requester peer and requested Host exactly match the claim's current `ASSIGNED` owner. Completed/unknown claims, wrong Hosts, reassigned owners and unavailable stores are refused. The store's normal `get()` recovery path may finish replay of an already-persisted pending generation before returning the latest state; the status request itself cannot create a new assignment or reassign a claim. The client checks request correlation, remote peer identity, claim ID, status and local peer/Host assignment. The terminal verifies the returned ticket against its own live `RecoveryLineageCoordinator` and requires the refreshed assignment to equal the submitted assignment before continuing. Refresh does not follow reassignment; the origin must replan and issue a new child assignment.

Before the receiver's ordinary address resolution and `ComputationalExecutionAdmissionCoordinator.execute()` handoff, the terminal server:

1. verifies the ticket's Merkle path and requires its `RecoveryStateManifest` to remain the live fixed-membership quorum high-water;
2. verifies the exact parent and child request digests and `ComputationalAddress` digest;
3. compares the receiving locus's complete typed `OperatorSpec` with the claim and requires the existing deterministic-pure replay predicate;
4. checks Computational Ground, local peer, logical Host and pinned implementation against the current assignment; and
5. only then continues through the regular receiver-local `ComputationalAddressResolver`, Virtual Layer, capability reconstruction and Hypervisor admission/effect path.

Without a configured status client, the terminal emits `execution-claim-attestation.v1` for the submitted ticket, and stale tickets continue to fail closed. With authenticated refresh configured, it emits `execution-claim-attestation.v2`, binding the claim ID/epoch, submitted ticket digest, refreshed admission-ticket digest, state generation and manifest digest. These fields identify the terminal's admission input; the attestation digest is not itself a signature or an independent proof of terminal state.

## Origin-side freshness and result completion

The origin refreshes the child's claim by ID after receiving the terminal response. It accepts the receipt only when the live claim remains `ASSIGNED` and the current assignment still equals the ticket's peer, Host, implementation and epoch. An unrelated claim-state update may change the shared root, but it does not itself invalidate the child assignment; a changed assignment or terminal status does invalidate the response.

Child receipt schema v2 retains the original assignment ticket and terminal attestation. When all children of the parent have passed their receipt and scalar/provenance checks, the partitioned dispatcher calls `complete_many()` exactly once. That operation verifies every child producer against current quorum state, binds each canonical child result digest and typed child receipt digest, and commits all claims in one generation or commits none.

Child receipt schema v3 carries both the original assignment ticket and the completed claim ticket. All completion tickets in one parent composite must share one manifest generation/root. This gives the composite a clear proof chain:

- the assignment ticket proves what the terminal Host was authorized to execute;
- the terminal attestation proves which claim/epoch the Host admitted;
- the completion ticket proves the origin accepted the exact result/receipt under the still-current assignment; and
- the original DAG frontier remains unpublished until the operation-native executor validates the complete composite and calls one atomic `commit_frontier()`.

## Recovery behavior and limits

Partition checkpoints preserve child assignment tickets, verified child receipts and (after parent completion) completion tickets. An ambiguous child response can be replayed through the existing receiver semantic ledger; once every child receipt is available, the same parent-level `complete_many()` can be retried idempotently.

A rehome that races a result is fenced in two places: the origin's post-response refresh rejects a changed assignment, and the final parent `complete_many()` rejects any child whose epoch/Host/implementation no longer matches the live claim. The protocol does not claim to stop a physically isolated old Host from finishing a deterministic pure calculation. Its guarantee is single-winner semantic result acceptance.

Automatic pure-child rehome is now implemented in the partitioned frontier dispatcher. It is bounded by `max_rehome_rounds` (default 1; 0 disables it) and requires the origin's claim store. Only recognized transport/path-loss outcomes trigger the path. The origin resolves the unchanged child address against the current directory, finds distinct replacement Hosts, persists a typed intent, and commits every failed child's new epoch in one `reassign_many()` generation. It then refreshes pending sibling tickets under the new shared root and retries the same semantic child with the stable origin-sequence slot reserved for its new assignment epoch. Exact retries within that epoch reuse the slot; each rehome epoch advances to the next 64-slot sub-window within the reserved 256-sequence frontier range.

Checkpoint v2 preserves confirmed route changes; v3 includes the intent written before quorum reassignment. A restart after quorum commit but before route confirmation can replay the identical batch idempotently. Existing verified siblings remain intact and the original parent frontier still completes atomically.

The guarantee remains single-winner semantic result acceptance for deterministic pure operations, not physical exactly-once. A disconnected previous Host may finish its pure computation, but the old epoch cannot complete the claim. Arbitrary side effects, stateful sessions and semantic/policy refusals are not automatically rehomed. The failure-evidence digest is an observation commitment, not proof that a prior Host has physically stopped.

## Parallel work orders

| Track | Implementation focus | Current boundary |
|---|---|---|
| A — Claim authority | Stable semantic identity, quorum Merkle root, assignment epochs, batch create/refresh/complete | Implemented |
| B — Fabric admission | Envelope v2, terminal live check, origin freshness, typed child attestation | Implemented in this increment |
| C — Rehome orchestration | Classify bounded path-loss failures, batch-reassign incomplete claims, resolve distinct Hosts, checkpoint intents and retry | Implemented for pure binary frontiers |
| D — Process recovery | Rebind live distributed claim authorities and authenticated status clients on each Host; reconcile claim roots with forwarding checkpoint restore | Authenticated status refresh is implemented on the existing mutual-TLS peer-control service; runtime coordinator/client rebinding remains caller-configured |
| E — Adversarial verification | Concurrent rehome/completion races, quorum loss, root rollback, stale receipt, route drift and interruption at each completion cut | Continue expanding |

The work tracks share one `TransferableExecutionClaimStore` and the existing fixed-membership quorum. They must not add independent result-acceptance authorities.

## Executable invariants

- B-59: Portable claims bind the exact semantic child identity, typed deterministic-pure operator contract, assignment history, quorum-anchored root and compact Merkle inclusion proof; every state transition expires previous tickets.
- B-60: Assignment epochs fence old result acceptance; completion is terminal and requires the current peer, Host and implementation.
- B-61: Child tickets are batched before dispatch, forwarded through envelope v2, validated by the terminal Host and rechecked by the origin after response.
- B-62: One parent frontier's child claims complete in one all-or-none quorum generation; the composite preserves assignment and completion proofs.
- B-63: Failed pure children may be rehomed only after route re-resolution and a pre-persisted intent; all changed epochs commit in one quorum generation, pending sibling tickets refresh under the new root, and checkpoint replay preserves the exact semantic child and original DAG commit boundary.
- B-64: Execution Hosts refresh expired tickets only through direct mutual TLS; the owner scopes each response to the still-assigned peer/Host, and the receiver verifies the refreshed ticket against its own quorum coordinator without following reassignment.

See [INVARIANTS.md](INVARIANTS.md) for the executable registry.
