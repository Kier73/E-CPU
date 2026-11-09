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

Before the receiver's ordinary address resolution and `ComputationalExecutionAdmissionCoordinator.execute()` handoff, the terminal server:

1. verifies the ticket's Merkle path and requires its `RecoveryStateManifest` to remain the live fixed-membership quorum high-water;
2. verifies the exact parent and child request digests and `ComputationalAddress` digest;
3. compares the receiving locus's complete typed `OperatorSpec` with the claim and requires the existing deterministic-pure replay predicate;
4. checks Computational Ground, local peer, logical Host and pinned implementation against the current assignment; and
5. only then continues through the regular receiver-local `ComputationalAddressResolver`, Virtual Layer, capability reconstruction and Hypervisor admission/effect path.

The terminal receipt includes an `execution-claim-attestation.v1` record with the claim ID, assignment epoch, ticket digest, state generation and manifest digest. The origin compares every field to the exact ticket it sent.

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

Automatic reassignment and route re-resolution are intentionally not included in this increment. When a claim is reassigned, the old terminal result is not accepted; the next orchestration layer must obtain failure observations, commit a new assignment epoch with `reassign()`, resolve a compatible route and retry the same child identity. The failure-evidence digest is an observation commitment, not proof that the prior Host has physically stopped.

## Parallel work orders

| Track | Implementation focus | Current boundary |
|---|---|---|
| A — Claim authority | Stable semantic identity, quorum Merkle root, assignment epochs, batch create/refresh/complete | Implemented |
| B — Fabric admission | Envelope v2, terminal live check, origin freshness, typed child attestation | Implemented in this increment |
| C — Rehome orchestration | Classify bounded path-loss failures, batch-reassign incomplete claims, resolve distinct Hosts, checkpoint intents and retry | Implemented for pure binary frontiers |
| D — Process recovery | Rebind live distributed claim authorities on each Host and reconcile the claim root with forwarding checkpoint restore | Partial; coordinator is caller-rebound |
| E — Adversarial verification | Concurrent rehome/completion races, quorum loss, root rollback, stale receipt, route drift and interruption at each completion cut | Continue expanding |

The work tracks share one `TransferableExecutionClaimStore` and the existing fixed-membership quorum. They must not add independent result-acceptance authorities.

## Executable invariants

- B-59: Portable claims bind the exact semantic child identity, typed deterministic-pure operator contract, assignment history, quorum-anchored root and compact Merkle inclusion proof; every state transition expires previous tickets.
- B-60: Assignment epochs fence old result acceptance; completion is terminal and requires the current peer, Host and implementation.
- B-61: Child tickets are batched before dispatch, forwarded through envelope v2, validated by the terminal Host and rechecked by the origin after response.
- B-62: One parent frontier's child claims complete in one all-or-none quorum generation; the composite preserves assignment and completion proofs.
- B-63: Failed pure children may be rehomed only after route re-resolution and a pre-persisted intent; all changed epochs commit in one quorum generation, pending sibling tickets refresh under the new root, and checkpoint replay preserves the exact semantic child and original DAG commit boundary.

See [INVARIANTS.md](INVARIANTS.md) for the executable registry.
