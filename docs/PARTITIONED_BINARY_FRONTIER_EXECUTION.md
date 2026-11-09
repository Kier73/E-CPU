# Partitioned Binary Frontier Execution

## Purpose

This document specifies the execution layer built on the deterministic child partition descriptions in [BINARY_FRONTIER_PARTITIONING.md](BINARY_FRONTIER_PARTITIONING.md). It lets one homogeneous ADD, COMPARE or MUL ready frontier use multiple authenticated computational hosts while retaining the original DAG as the only publication authority.

The key separation is:

- **The parent frontier** is the semantic transaction and the only DAG commit unit.
- **A child partition** is an independently addressed, routable operation.
- **A host** is a logical computational locus advertising a compatible operation contract, implementation pin, Computational Ground, substrate and bounded resource/cost profile.
- **The authenticated fabric** transports and admits each child independently.
- **The composite receipt** brings the separate execution paths back together as one verifiable parent result.

A child is not a smaller VM or a detached program. It is a typed subset of one already-compiled operation frontier, retaining the parent plan/context/frontier identities and the exact original DAG node identities.

## Addressing and route selection

`PartitionedComputationalFabricDataflowBinaryDispatcher` wraps the existing `ComputationalFabricDataflowBinaryDispatcher`.

For each child, the wrapped dispatcher constructs the exact `ComputationalAddress` from the child request. It then asks `ComputationalFabricResolver.resolve_candidates()` for a bounded ranked set of candidate routes. The planner requires one coherent directory and topology digest for the whole parent plan and uses a stable host-matching step to assign each child to a distinct logical `(peer_id, host_id)` pair.

Each child partition stores:

- its typed ADD@3, COMPARE@1 or MUL@1 request;
- the full typed `ComputationalAddress`;
- the complete `ComputationalFabricRouteWitness`; and
- a content digest over the entire child description.

A route is never copied from the unsplit parent request. The child address is exact to its own lane set and operands. A route proposal remains non-authoritative: before sending, the base dispatcher reconstructs the child address and resolves the live directory/topology again. The selected route must still be an exact candidate with the same digest. The receiver independently re-resolves, revalidates and passes the operation through its local Hypervisor / Virtual Layer admission boundary. No direct host invocation or transport shortcut is added.

The initial implementation requires at least two distinct logical hosts, considers at most 128 route candidates per child, and supports at most 64 partitions. If the live directory or topology changes during planning, the plan is refused rather than mixing route views.

## Child receipts and the composite parent receipt

Each existing dispatcher call returns its operation-specific typed receipt. `BinaryFrontierChildReceipt` pairs that receipt with the exact assigned partition and checks:

- child request digest and ordered node IDs;
- target host and peer;
- complete peer path and route witness digest;
- pinned implementation fingerprint; and
- exact Structural Memory binding coverage.

`BinaryFrontierCompositeReceipt` contains the original parent request, the full partition plan and one validated child receipt for every partition. It does not invent one host identity for a multi-host operation. The aggregate result projection is reconstructed from child results in stable node-ID order. The full child route, address, implementation and backend receipt evidence remains available in the serialized parent receipt.

The operation-native executor accepts the composite through the same receipt interface as a single-host receipt. It still compares the aggregate node identities with the original parent request, validates all pinned Structural Memory read receipts, checks each value against the independent ADD/COMPARE/MUL scalar oracle, and stages the complete parent ready frontier. Only after every lane across every child passes does it call `NavigableComputationDAG.commit_frontier()` once for the original ordered ready-node set.

The children do not commit DAG nodes independently. A failed or invalid child therefore cannot publish a sibling result from the parent frontier.

## Recovery and semantic replay

`BinaryFrontierExecutionCheckpoint` binds the exact parent request, exact partition plan and the typed child receipts already validated. The optional checkpoint sink receives the initial plan before any child is sent, then receives updated progress after child groups complete. The checkpoint can be serialized, restored and passed to `dispatch(request, checkpoint=...)`. The checkpoint is a portable orchestration record, not a replacement for the existing fabric recovery bundle: process-crash recovery requires the caller to persist it and restore the corresponding authenticated forwarding-client and receiver execution-ledger state through the existing E-CPU recovery mechanisms. Without a sink, the checkpoint is returned in memory on an incomplete dispatch and can be supplied directly for an in-process resume.

Resume retains the original semantic child identity, ComputationalAddress and stable origin sequence. When no claim store is configured, it preserves the original same-route replay behavior. When the origin has a TransferableExecutionClaimStore, the dispatcher may also rehome eligible failed children with max_rehome_rounds (default 1, finite range 0..3):

1. Only a bounded transport/path-loss failure is eligible. Hypervisor or Virtual Layer semantic refusal, invalid result evidence, a failed scalar oracle, stale claim proof and arbitrary handler errors are not treated as permission to move work.
2. The origin re-resolves the exact child address against one coherent live directory/topology view. It considers only authenticated remote candidates with pinned implementations, excludes every previously failed Host and all Hosts currently assigned to non-failed siblings, and solves a distinct-host assignment for the entire rehome batch.
3. A typed reassignment intent is persisted before reassign_many() advances the affected claim epochs. The batch transition commits every new owner in one quorum generation; partial or stale epoch batches are refused. Afterward the origin refreshes all pending child tickets from the new shared root.
4. The child is retried under its new claim epoch and route, retaining the original semantic request and stable origin sequence. Already-verified sibling receipts remain in the checkpoint and are not dispatched again.
5. Only after every child receipt is validated does the parent call complete_many() once and then publish the original DAG frontier with one atomic commit_frontier().

BinaryFrontierExecutionCheckpoint v2 records confirmed route replacements. Checkpoint v3 also records pending reassignment intents. If the process stops after the intent is durable but before quorum reassignment, after quorum reassignment but before the confirmed route checkpoint, or after completion but before the composite is returned, resume replays the same idempotent transition against the same claim ID/epoch/evidence digest. Route history must continue the exact previous route and adjacent assignment epochs; a changed parent, child, address, Ground, operator or route assignment is refused.

This is single-winner semantic result acceptance, not exactly-once physical computation. An isolated old Host may finish deterministic pure work after its route is lost; its old epoch cannot complete the claim after quorum reassignment. A replacement Host may therefore recompute the same pure child. Rehome is not available for external side effects or stateful sessions. A content digest is not a signature or hardware attestation.

## Bounded concurrency and reliable stream ordering

The wrapper has a configurable `max_concurrency` bounded to 1..64 and, when claims are configured, a separate bounded `max_rehome_rounds` (0..3). It groups child work by the first authenticated next-hop peer. Children using the same next-hop client are dispatched serially in stable plan order because the existing reliable client owns a stateful request/result stream and serializes its own transitions. Independent first-hop clients run in a bounded thread pool.

Each partitioned frontier reserves one 64-sequence origin window. Child sequence numbers are stable by partition-plan ordinal; the normal one-child fallback uses the beginning of the same frontier window. If one child in a next-hop group has an ambiguous failure, later children on that stream are not advanced past it. Recovery retries the blocked child first, then continues in order.

Concurrency is therefore bounded by independent authenticated streams, not by creating concurrent writes through one reliable channel. The current default grouping is deterministic and balanced across up to two partitions; callers may supply per-frontier partition groups and tune the partition count/concurrency.

## Resource interpretation

A fabric host is not inherently synonymous with a physical machine. It is a logical locus that advertises what it can interpret and execute: operator contract/version, implementation fingerprint, Computational Ground support, substrate, capacity, resource bounds, cost dimensions, and a peer path through the authenticated directory.

This is the useful direction for heterogeneous resource access: the same operation description can be resolved toward different kinds of compatible loci without changing its semantics. The current implementation demonstrates bounded binary operations over advertised CPU/E-GPU implementations and authenticated remote peers. It does not yet integrate arbitrary third-party providers, cloud APIs, untrusted public compute markets, storage-native execution, accelerators beyond the existing E-GPU profile, or cross-provider settlement. Those require their own admission, trust, accounting, privacy and replay boundaries.

## Limits and next work

This implementation supports dispatch, typed child receipts, composite receipts, resumable checkpoints, quorum-fenced rehome of failed deterministic-pure children, atomic parent commit integration and bounded concurrency for homogeneous binary frontiers. It still does not:

- distribute branches, loops, effects, syscalls or stateful sessions as independent child operations;
- move intermediate results directly between child hosts without returning through the origin;
- guarantee exactly-once physical computation after a host/network partition; a prior Host may finish pure work, although it cannot publish the stale result;
- automatically rehome after arbitrary semantic or policy refusal, or execute stateful/effectful operations under transferable claims;
- make a content digest equivalent to a signature or hardware attestation; or
- prove physical accelerator speedup or end-to-end WAN performance.

The next meaningful frontier is authenticated claim-status access on each execution Host and deeper adversarial verification of concurrent rehome/completion races, quorum loss and receiver restart. Generalizing resource advertisements beyond the supported binary CPU/E-GPU operator family follows once those recovery cuts are exercised.

## Invariants

- B-55 defines atomic original-frontier publication and exact whole-frontier retry.
- B-56 defines exact typed child partition and route descriptions.
- B-57 defines child receipt aggregation and preservation of the original parent commit boundary.
- B-58 defines replay-safe checkpoint recovery and bounded concurrency across independent authenticated streams.

See [INVARIANTS.md](INVARIANTS.md) for the executable registry.
