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

1. Each claim embeds the complete typed `OperatorSpec` and is restricted to `pure-replay-safe/v1`. The claim constructor verifies that the spec's operator ID and digest match the claim and that E-CPU's existing `OperatorSpec.replay_safe` predicate holds (`deterministic=True` and `effect_mode="pure"`). A caller-supplied label or detached digest alone cannot make an effectful operator transferable.
2. The current assignment is recorded in a full owner-side claim-state snapshot and committed through the existing fixed-membership `RecoveryLineageCoordinator`.
3. A receiver or result coordinator must verify that the bundle's manifest is still the live quorum high-water and that its own peer, logical Host, implementation and workload identities match the current assignment.
4. Reassignment increments the assignment epoch and commits the new owner through the same quorum state chain.
5. Completion succeeds only when the expected epoch and producer exactly match the current assignment.
6. A result committed for the current epoch records both the result digest and typed child-receipt digest. Exact completion retries return the same bundle; changed results are rejected.

An old host may still finish already-started pure computation. Its old bundle is stale at quorum high-water, and its old epoch cannot commit the accepted result. A replacement host may recompute the same deterministic operation. Therefore the protocol provides **single-winner semantic result acceptance**, not exactly-once physical computation.

The protocol must not be used for external side effects, payments, device actions, state mutations or arbitrary user handlers until those operations have their own transactional idempotency/fencing boundary.

## Quorum state and durable artifact

`TransferableExecutionClaimStore` reuses `RecoveryLineageCoordinator` and its existing `SeedCommitMembership`, durable prepare votes, commit certificates and authority journals. It does not add a second consensus protocol.

Each transition writes the complete sorted claim set as the owner-side `claims.json` artifact, computes a domain-separated binary Merkle tree over the current claim IDs and claim digests, and creates a compact state-root envelope containing the generation, predecessor, claim count and Merkle root. The full claim artifact, root envelope and `RecoveryStateManifest` are fsynced into an immutable generation directory before the coordinator seals the manifest. The manifest's state digest commits to the canonical root envelope; when the owner store restores a generation, it recomputes the tree from the full claim artifact and requires the root/count to match before exposing any claim. The full owner snapshot is integrity-bound through the Merkle root, while each remote ticket needs only one leaf and its sibling path.

The portable bundle carries only:

- the typed current claim;
- the compact state-root envelope;
- the claim's sorted-tree index and logarithmic Merkle inclusion path;
- the typed `RecoveryStateManifest`; and
- the `RecoveryLineageProof` containing the matching proposal, fixed-membership prepare certificate and durable commit decisions.

A receiving Host first verifies the Merkle inclusion path against the root envelope, then calls `verify_state` against the live coordinator to require that root manifest to remain the current quorum high-water. Because this is one shared claim-set root, **any claim-state transition expires all previously issued tickets**, even when a particular claim's assignment did not change. A receiver must therefore obtain a fresh ticket by claim ID from the authenticated claim-status service immediately before admission; it must not treat a cached ticket as a long-lived lease. The ticket schema contains no full registry snapshot; for a maximum of 16,384 claims, an inclusion path has at most 14 sibling hashes. Target admission also requires the receiving Host's actual registered typed `OperatorSpec`, and compares the complete canonical operator contract—not just a caller-provided ID/digest—to the claim. A well-formed but older bundle is refused as stale. The proof is not a signature detached from the state: the quorum commits to the root envelope, and the Merkle path proves that the exact typed claim is a member of the committed set. The portable ticket is O(log n) in claim count; the full set remains local to the owner store.

The first implementation bounds the ledger to 16,384 claims, 64 assignments per claim, a 16 MiB serialized owner-side state snapshot and a 128 KiB portable ticket. Peer and logical-Host labels use the existing fabric identifier alphabet. Each transition writes the full sorted claim set and rebuilds the Merkle tree, so owner-side transition cost remains O(number of retained claims); the portable ticket itself contains only one claim and O(log n) sibling hashes. It is therefore bounded for transport independently of the retained registry size. Claim compaction and deterministic sharding by parent/frontier are follow-on optimization tracks and must preserve the same single-winner claim semantics.

The claim store serializes local writers with a cross-process lock. The existing fixed-membership quorum serializes distributed state generations and refuses conflicting values at an occupied generation. If a coordinator fails after writing the next immutable generation or after a minority prepare/commit, `resume_pending()` reloads and validates the exact persisted snapshot/manifest, then retries that same proposal. A different transition at the occupied slot is not silently substituted.

## Claim lifecycle

`ASSIGNED` claims can be completed by their current assignment or reassigned to a different logical Host. `COMPLETED` claims are terminal.

A first assignment has epoch 1. `reassign()` is the one-claim compatibility API; `reassign_many()` advances a bounded set of current claims in one quorum generation. Every item requires its expected current epoch, a distinct logical `(peer_id, host_id)`, a pinned implementation fingerprint and a failure-evidence digest. The batch refuses duplicate claim IDs, duplicate target Hosts, stale epochs, completed claims and a retry that mixes already-reassigned claims with still-assigned siblings. An exact full-batch retry returns the same generation without another transition.

The evidence digest commits the caller's recovery observation; it is **not** an independent proof that the prior Host is physically down. The quorum commit is the authority that revokes the prior epoch's result-acceptance permission. A quorum reassignment fences semantic result acceptance; it does not forcibly stop a processor or roll back work already performed.

Completion requires the exact current peer, Host, implementation and epoch, and binds a result digest with a child receipt digest. The store provides `complete_many()` so the entire parent frontier's child outcomes can be committed in one quorum generation. The operation-native partition dispatcher uses that batch after all child receipts have passed provenance checks. A stale child assignment aborts the whole batch; no sibling claim is completed independently.

For recovery, child reassignments are also batched. If several children fail in the same bounded recovery round, they are assigned to distinct replacement Hosts in one `reassign_many()` generation. Because any claim-state transition expires every portable ticket, the origin refreshes the pending child tickets together after the batch; it does not reuse one sibling's stale ticket.


## Automatic pure-child rehome

The partitioned binary dispatcher can opt into bounded automatic rehome by using a claim store and setting `max_rehome_rounds` (default 1, bounded 0..3). Only recognized forwarding transport/path-loss outcomes are eligible. Semantic refusals, invalid receipts, operator-contract mismatches and oracle failures do not authorize reassignment.

The origin keeps the parent plan immutable. It re-resolves each failed child's exact address through the current fabric directory, excludes the previous Host and all Hosts already occupied by unaffected siblings, and finds a distinct-host matching for all children being rehomed in the same recovery round. The replacement must still advertise the exact operator contract, Computational Ground and pinned implementation through a current authenticated route candidate.

The checkpoint records a typed rehome intent before the quorum state changes. The intent binds the exact parent/child, unchanged address and previous/replacement route identities, expected assignment epoch and deterministic failure-evidence digest. After `reassign_many()` commits, a confirmed route-history record carries the portable assignment ticket. Checkpoint schema v2 contains confirmed route replacements; schema v3 additionally contains pending intents. If restart occurs between the quorum commit and confirmed checkpoint publication, the origin replays the same intent idempotently and reconstructs the committed route transition.

A replacement execution is a new physical attempt under a new assignment epoch, not a continuation of the old Host's processor state. The original child request, address, plan/context and DAG node identities remain unchanged. Existing verified sibling receipts remain in the checkpoint. The parent still completes every claim in one `complete_many()` operation and publishes the original DAG frontier in one atomic commit.

This preserves the guarantee boundary: a prior isolated Host may still finish pure work, but only the current quorum epoch can complete the semantic claim. No arbitrary external side effects, payments, device operations or stateful sessions are eligible for this replay/rehome protocol.

## Fabric integration

The current fabric increment carries the portable claim through the existing authenticated forwarding path without introducing a second ownership ledger.

### Batch assignment before dispatch

The origin's `ComputationalFabricDataflowBinaryDispatcher.prepare_execution_claims()` builds one typed specification for each child partition and calls `TransferableExecutionClaimStore.create_many()`. All new child assignments are committed in one global claim-state generation, then each child receives a Merkle ticket for the same root. The bounded `get_many()` API refreshes multiple child tickets from one live quorum view. This is necessary because every claim-state transition expires all prior tickets.

### Forwarding envelope and terminal admission

Claim-bound forwarding uses envelope schema v2; legacy unclaimed operations retain schema v1. The envelope binds the exact parent request digest and portable child ticket, and every relay preserves the ticket unchanged. The receiving terminal Host must have its live distributed `RecoveryLineageCoordinator`; it verifies the ticket against current quorum high-water and compares the complete typed local `OperatorSpec`, child request, `ComputationalAddress`, Computational Ground, assigned peer/Host and pinned implementation before calling the normal `ComputationalAddressResolver` and `ComputationalExecutionAdmissionCoordinator`. The ordinary Virtual Layer and Hypervisor capability/policy/effect path remains authoritative. A relay does not independently authorize terminal execution.

The terminal result carries an execution-claim attestation binding the claim ID, assignment epoch, exact ticket digest, state generation and manifest digest. The origin checks the attestation and refreshes current claim state after the response arrives. If a concurrent reassignment changed the assignment before origin acceptance, the result is rejected even if the previous Host had already finished the pure computation.

### Parent-level completion

Claim-bound child receipts preserve the original assignment ticket and terminal attestation. After every child result and provenance receipt passes validation, the partition dispatcher calls `complete_many()` once for the complete parent child set. Each completed claim binds a canonical result digest and exact typed receipt digest. Completion tickets share one quorum generation and are retained in child-receipt schema v3. A checkpoint that contains all child receipts but was interrupted before completion can resume the idempotent batch completion; the operation-native executor still publishes the original DAG ready frontier through one atomic `commit_frontier()`.

### Remaining recovery boundary

This increment does not yet automatically rehome a failed child to another host. It refuses stale or conflicting child completion and preserves incomplete progress, but a later orchestration layer must use the existing `reassign()` transition, re-resolve a compatible route and retry the same semantic child under the new epoch. The failure-evidence digest is an observation commitment, not proof that an isolated prior Host has stopped.

The `DistributedRecoveryLineageCoordinator` and existing mutual-TLS authority service provide the multi-process authority path. Each participating Host must bind its own live coordinator to the same configured fixed membership; no local cache or caller-supplied ticket substitutes for current quorum status.

## Parallel work orders

These tracks can proceed independently once the claim schema remains stable:

| Track | Work | Dependency |
|---|---|---|
| A — Claim authority | Portable claim schema, immutable generation store, Merkle ticket, batch assignment/completion and quorum fencing | Merged claim authority |
| B — Fabric admission | Envelope v2, terminal verification, typed child receipt attestation, origin freshness check and parent batch completion | This increment |
| C — Rehome orchestration | Detect incomplete children, acquire a new epoch, resolve a compatible Host, retry and preserve the composite parent receipt | A + B |
| D — Recovery persistence | Restore forwarding servers with live claim authorities and reconcile assignment/completion tickets across process restarts | A + B + existing forwarding recovery |
| E — Adversarial proof | Race old/new completion, quorum loss, stale proof, changed workload, route drift and interrupted quorum transitions | A–D |

Track B can develop the transport/admission adapter while Track D defines the checkpoint composition. Track E can build model-level failure tests before Track C enables automatic reassignment. These are parallel implementations around one claim authority; they must not create independent result-winner ledgers.

## Invariants

- B-59 binds each portable claim to its exact semantic child identity, typed deterministic-pure operator contract, full assignment history, quorum-anchored state-root envelope and Merkle membership proof. The owner-side snapshot is recomputed against the root at restore; the portable ticket is compact and carries no registry snapshot. A ticket is valid only at its exact shared-ledger high-water; any later claim-state transition requires a fresh ticket.
- B-60 fences old assignment epochs at the live quorum high-water and admits completion only from the current assigned Host/implementation, with one terminal result/receipt commitment.

See [INVARIANTS.md](INVARIANTS.md) for the executable registry.
