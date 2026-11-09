# Transferable Execution Claims

## Purpose

A partitioned frontier can survive a lost receiver or failed route only if it can move unfinished work without allowing an obsolete assignment to publish a competing result. The merged partition executor already preserves child requests, typed receipts and exact receiver replay. This document introduces the next authority layer: a portable, quorum-anchored claim over one pure child operation.

The claim separates three identities:

- **Semantic identity:** the exact parent frontier, child request, child ComputationalAddress, operator contract and Computational Ground.
- **Assignment identity:** the current logical peer/host, pinned implementation and monotonically increasing assignment epoch.
- **Completion identity:** the verified result digest and typed child-receipt digest accepted for the current epoch.

The claim ID is stable across reassignment because it is derived only from semantic identity. An assignment epoch changes when ownership moves; the operation itself does not.

## Why the guarantee is result fencing, not physical exactly-once execution

A coordinator cannot prove that an isolated host has stopped computing merely because it cannot contact that host. A host may have started an operation, become partitioned, and continue running after another host receives a replacement assignment. Without a synchronized hardware fence or a shared transactional side-effect system, claiming that a quorum certificate physically prevents the old CPU from finishing would be incorrect.

The implemented guarantee is narrower and useful:

1. Each claim is restricted to the declared `pure-replay-safe/v1` policy.
2. The current assignment is recorded in a full state snapshot and committed through the existing fixed-membership `RecoveryLineageCoordinator`.
3. A receiver or result coordinator must verify that the bundle's manifest is still the live quorum high-water and that its own peer, logical Host, implementation and workload identities match the current assignment.
4. Reassignment increments the assignment epoch and commits the new owner through the same quorum state chain.
5. Completion succeeds only when the expected epoch and producer exactly match the current assignment.
6. A result committed for the current epoch records both the result digest and typed child-receipt digest. Exact completion retries return the same bundle; changed results are rejected.

An old host may still finish already-started pure computation. Its old bundle is stale at quorum high-water, and its old epoch cannot commit the accepted result. A replacement host may recompute the same deterministic operation. Therefore the protocol provides **single-winner semantic result acceptance**, not exactly-once physical computation.

The protocol must not be used for external side effects, payments, device actions, state mutations or arbitrary user handlers until those operations have their own transactional idempotency/fencing boundary.

## Quorum state and durable artifact

`TransferableExecutionClaimStore` reuses `RecoveryLineageCoordinator` and its existing `SeedCommitMembership`, durable prepare votes, commit certificates and authority journals. It does not add a second consensus protocol.

Each transition writes a canonical state snapshot containing the complete sorted set of current claims, plus a `RecoveryStateManifest`. The snapshot and manifest are fsynced into an immutable generation directory before the coordinator seals the manifest. The manifest binds the membership, machine/owner term, generation, predecessor root, snapshot state digest and capture-cut identity.

The portable bundle carries:

- the typed current claim;
- the full state snapshot needed to recompute the manifest's state digest;
- the typed `RecoveryStateManifest`; and
- the `RecoveryLineageProof` containing the matching proposal, fixed-membership prepare certificate and durable commit decisions.

A receiving Host verifies the snapshot bytes and the quorum proof, then calls `verify_state` against the live coordinator. A well-formed but older bundle is refused as stale. The proof is not a signature detached from the state: it anchors one exact state manifest, and the bundle includes the state bytes needed to verify that anchor.

The claim store serializes local writers with a cross-process lock. The existing fixed-membership quorum serializes distributed state generations and refuses conflicting values at an occupied generation. If a coordinator fails after writing the next immutable generation or after a minority prepare/commit, `resume_pending()` reloads and validates the exact persisted snapshot/manifest, then retries that same proposal. A different transition at the occupied slot is not silently substituted.

## Claim lifecycle

`ASSIGNED` claims can be completed by their current assignment or reassigned to a different logical Host. `COMPLETED` claims are terminal.

A first assignment has epoch 1. Reassignment requires the expected current epoch, a distinct logical `(peer_id, host_id)`, a pinned implementation fingerprint and a failure-evidence digest. The evidence digest commits the caller's recovery observation; it is **not** an independent proof that the prior host is physically down. The quorum commit is the authority that revokes the prior epoch's result-acceptance permission.

Completion requires the exact current peer, Host, implementation and epoch, and binds a result digest with a child receipt digest. The current API records those commitments; the fabric integration step will make the terminal receiver validate the claim before execution and make the origin validate the receipt's claim ID and epoch before accepting the result.

## Fabric integration boundary

This increment provides the portable claim data model, durable state store, quorum anchoring, current-owner verification, reassignment fencing, completion and restart recovery tests. It does not yet transport claim bundles inside the computational forwarding envelope or invoke claim verification from the terminal Hypervisor admission path.

The next integration increment should:

1. Attach the exact claim bundle to the partition child envelope.
2. Make the terminal peer verify the live quorum high-water and exact child request/address/operator/Ground/implementation binding before backend admission.
3. Bind claim ID, assignment epoch and result commitment into the typed child receipt.
4. Let the origin atomically reassign only incomplete child claims, re-resolve the new route and dispatch the same semantic request to the new owner.
5. Keep the original parent DAG frontier commit atomic; a collection of child claim completions is still not a partial DAG commit.

The `DistributedRecoveryLineageCoordinator` and existing mutual-TLS authority service provide the multi-process authority path. Each participating Host needs access to that configured quorum, not a private local assertion.

## Parallel work orders

These tracks can proceed independently once the claim schema remains stable:

| Track | Work | Dependency |
|---|---|---|
| A — Claim authority | Portable claim schema, immutable generation store, quorum proof, assignment epochs and completion fencing | This increment |
| B — Fabric admission | Envelope transport, terminal claim verification, receipt binding and origin verification | Claim bundle API |
| C — Rehome orchestration | Detect incomplete children, acquire a new epoch, resolve a compatible Host, retry and preserve composite parent receipt | A + B |
| D — Recovery persistence | Seal claim state alongside partition checkpoints and restore clients/authorities after process restart | A + existing forwarding recovery |
| E — Adversarial proof | Race old/new completion, quorum loss, stale proof, changed workload, route drift and interrupted quorum transitions | A–D |

Track B can develop the transport/admission adapter while Track D defines the checkpoint composition. Track E can build model-level failure tests before Track C enables automatic reassignment. These are parallel implementations around one claim authority; they must not create independent result-winner ledgers.

## Invariants

- B-59 binds each portable claim to its exact semantic child identity, pure replay policy, full assignment history, and a quorum-anchored complete state snapshot.
- B-60 fences old assignment epochs at the live quorum high-water and admits completion only from the current assigned Host/implementation, with one terminal result/receipt commitment.

See [INVARIANTS.md](INVARIANTS.md) for the executable registry.
