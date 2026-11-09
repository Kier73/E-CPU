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

Resume has three rules:

1. A successful child with a retained verified receipt is not dispatched again.
2. An incomplete child is retried with the same child request, route witness and origin sequence.
3. The retry is accepted only if the existing live resolver still recognizes that exact route as a candidate.

This reuses the existing forwarding server and receiver execution ledger. If the receiver completed the pure operation but its response was lost, an exact replay can recover the existing semantic effect/receipt rather than enter the backend again. A changed request, changed route, stale topology or invalid checkpoint is refused.

**Ambiguous outcomes are not reassigned to a different host in this increment.** If a receiver may have executed but its response was lost, sending the same semantic child to another host could repeat an effect because the current deduplication authority is receiver-local. This implementation fails closed and retries the original route/sequence; it does not pretend that independent host ledgers already provide a federated exactly-once guarantee. Safe cross-host reassignment requires a shared/transferable effect-claim protocol or a stronger origin-issued idempotency authority and remains future work.

## Bounded concurrency and reliable stream ordering

The wrapper has a configurable `max_concurrency` bounded to 1..64. It groups child work by the first authenticated next-hop peer. Children using the same next-hop client are dispatched serially in stable plan order because the existing reliable client owns a stateful request/result stream and serializes its own transitions. Independent first-hop clients run in a bounded thread pool.

Each partitioned frontier reserves one 64-sequence origin window. Child sequence numbers are stable by partition-plan ordinal; the normal one-child fallback uses the beginning of the same frontier window. If one child in a next-hop group has an ambiguous failure, later children on that stream are not advanced past it. Recovery retries the blocked child first, then continues in order.

Concurrency is therefore bounded by independent authenticated streams, not by creating concurrent writes through one reliable channel. The current default grouping is deterministic and balanced across up to two partitions; callers may supply per-frontier partition groups and tune the partition count/concurrency.

## Resource interpretation

A fabric host is not inherently synonymous with a physical machine. It is a logical locus that advertises what it can interpret and execute: operator contract/version, implementation fingerprint, Computational Ground support, substrate, capacity, resource bounds, cost dimensions, and a peer path through the authenticated directory.

This is the useful direction for heterogeneous resource access: the same operation description can be resolved toward different kinds of compatible loci without changing its semantics. The current implementation demonstrates bounded binary operations over advertised CPU/E-GPU implementations and authenticated remote peers. It does not yet integrate arbitrary third-party providers, cloud APIs, untrusted public compute markets, storage-native execution, accelerators beyond the existing E-GPU profile, or cross-provider settlement. Those require their own admission, trust, accounting, privacy and replay boundaries.

## Limits and next work

This increment implements dispatch, typed child receipts, composite receipts, resumable checkpoints, atomic parent commit integration and bounded concurrency for homogeneous binary frontiers. It still does not:

- distribute branches, loops, effects, syscalls or stateful sessions as independent child operations;
- move intermediate results directly between child hosts without returning through the origin;
- guarantee safe alternate-host reassignment after an ambiguous completed-but-unacknowledged operation;
- make a content digest equivalent to a signature or hardware attestation; or
- prove physical accelerator speedup or end-to-end WAN performance.

The next meaningful frontier is to design transferable idempotency/effect claims so an incomplete child can be safely rehomed after host loss, then generalize the resource advertisement and admission model beyond the currently supported binary CPU/E-GPU operator family.

## Invariants

- B-55 defines atomic original-frontier publication and exact whole-frontier retry.
- B-56 defines exact typed child partition and route descriptions.
- B-57 defines child receipt aggregation and preservation of the original parent commit boundary.
- B-58 defines replay-safe checkpoint recovery and bounded concurrency across independent authenticated streams.

See [INVARIANTS.md](INVARIANTS.md) for the executable registry.
