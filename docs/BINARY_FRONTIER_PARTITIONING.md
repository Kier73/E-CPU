# Binary Frontier Partition Plans

## Purpose

This document defines the deterministic description layer for splitting one homogeneous binary-operation frontier across multiple proposed fabric destinations.

It follows the atomic frontier commit boundary in NAVIGABLE_COMPUTATION_DAG.md. It does **not** yet dispatch partitions concurrently or claim multi-host execution. Its purpose is to make the split, node ownership, child-request identities, operation contract and route proposals explicit and serializable before the executor is extended.

## Parent frontier and child requests

A compiled MailCPU plan has one digest, one context digest and deterministic ready frontiers. Within a ready frontier, the operation-native executor groups independent ADD, COMPARE and MUL nodes by semantic operation. split_binary_frontier_request() accepts one such typed request and a stable sequence of child node-ID groups.

The split is accepted only when:

- there are 2..64 non-empty child groups;
- every child group is sorted by stable node ID and contains no more than 64 lanes;
- groups are ordered by their first node ID;
- no node appears in more than one group; and
- the union of child node IDs equals the exact parent request lane IDs.

Each child request retains the parent's compiled-plan digest, context digest and frontier index. Its ordered DataflowBinaryLane values retain node digests, operand values, symbolic Structural Memory references and contextual-orbit predecessor evidence. The child has a distinct content digest because its ordered lane subset differs.

The partition plan applies to one homogeneous operation family within a DAG frontier. A frontier containing both local nodes and multiple binary operation families is represented by separate operation partition plans; local nodes and other operation families remain under the same outer DAG frontier commit barrier.

## Route-bound partition

BinaryFrontierPartition binds one exact typed child request to one complete ComputationalFabricRouteWitness.

The route target must advertise the exact canonical ADD@3, COMPARE@1 or MUL@1 operator contract, a pinned implementation fingerprint and support for the partition plan's Computational Ground. The route must be remote. The witness retains its full peer path, link identities, authenticated endpoint identities, target-host advertisement and additive resource/cost decomposition.

BinaryFrontierPartitionPlan binds:

- the exact compiled plan and context digests;
- the original frontier index and homogeneous operation family;
- the Computational Ground fingerprint;
- origin peer, directory digest and topology digest;
- the complete sorted set of original DAG node IDs; and
- the complete ordered collection of child requests and their route witnesses.

Every child request must retain the parent plan/context/frontier identity. Every route must originate from the same origin and one coherent directory/topology view. The child node sets must be disjoint and cover the declared operation frontier exactly once. Each child has its own computational-address digest, and the plan must span at least two distinct logical hosts.

The plan's canonical digest commits all child request contents and complete route witnesses. from_dict() rehydrates typed lane operands, typed contextual-orbit inputs, pinned Structural Memory references and route witnesses before recomputing the enclosing digest.

## Authority and execution boundary

A partition plan is a deterministic proposal, not execution authority. The route witness is non-authoritative discovery evidence. It does not reserve capacity, bind a receiver to an old catalogue revision, grant capability, or replace receiver-side route resolution. Each eventual child dispatch must be sent through the existing authenticated per-hop forwarding path; the terminal peer must freshly resolve the child workload, revalidate the selected implementation and perform local Virtual Layer / Hypervisor admission.

The route witness for a child must be obtained from the exact ComputationalAddress built from that child request, not copied from a route query for the unsplit parent request. The address digest is request-specific. A route proposal from the parent workload cannot be relabeled as a child route.

Once child dispatch is implemented, the coordinator should collect one typed child receipt per partition, verify exact child request digests, node-ID coverage, host/implementation/path identities, Structural Memory receipts and independent scalar results, then construct a parent frontier receipt. The parent receipt must preserve the child receipts rather than inventing a single host identity.

Only after all child results for the entire ready frontier have passed validation may the coordinator call NavigableComputationDAG.commit_frontier(). A failed child therefore cannot publish a sibling DAG result from that frontier. Successful remote pure executions that occurred before a later child failure remain governed by the receiver execution ledger; an exact child retry should recover the same effect/receipt without re-entering the backend.

## Current implementation boundary

This increment delivers:

- all-or-none DAG frontier publication and exact whole-frontier retry;
- use of that commit boundary by both local and operation-native dataflow evaluation;
- stable typed child-request splitting;
- full route-bound partition descriptions;
- strict serialization and content-digest restoration; and
- focused coverage tests for exact split, full restore, route contract mismatch, missing/duplicate nodes, single-host plans, inconsistent catalogue views and tampering.

It does **not** yet deliver partition dispatch, a composite parent receipt, multi-host frontier execution, concurrent child scheduling, or partition-level crash-recovery orchestration. Those are the next execution-layer changes. The current single-dispatcher operation executor remains unchanged in its one-destination behavior, but now commits its whole prepared ready frontier atomically.

## Invariants

- B-55 requires all-or-none frontier publication and idempotent exact replay.
- B-56 requires child-request partitions to form an exact disjoint cover and bind to typed route proposals from one coherent fabric view across at least two logical hosts.

See INVARIANTS.md for the executable registry.
