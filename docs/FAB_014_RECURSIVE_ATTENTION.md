# FAB-014 — Recursive resource attention

## Implemented contract

[mailcpu/attention.py](../mailcpu/attention.py) is a sparse, deterministic, advisory planner over a 24-bit machine identity and a recursive process path. It does not instantiate an OS for an inactive identity or confer permission. `machine_scope(i,*path)` names the six hexadecimal digits of i followed by up to 32 bounded labels. Active work leaves must be distinct and prefix-free; a parent with its own work and children can name its own work under a reserved "self" leaf. The limit map can constrain any prefix, including root.

A resource vector B=(quanta, resident mappings, message units, observation units) contains nonnegative integers. An offer binds scope, positive revision, exact evidence digest, ready flag and whole nonzero demand. The evidence digest identifies an observation supplied by an upstream trusted observer; it does not authenticate that observer. The planner requires componentwise capacity conservation along every ancestor, not just globally. For each prefix p, sum of grants below p <= limit(p), and sum of all grants <= root capacity. Demand is indivisible in this initial implementation. Pages count simultaneous reservations within one plan; page reuse across epochs is observed by the OS rather than assumed by the allocator. No physical RSS bound is implied.

## Selection algorithm

1. Validate and sort all supplied offers; refuse duplicate/ancestor-overlapping work leaves. Hash the exact epoch, capacity, offers, prefix limits and prior service counts.
2. Create only prefixes of ready offers. Each internal node holds a heap ordered by (completed service count, child label). Prior service is supplied from actually completed work by the caller.
3. At a selected branch intersect all ancestor remaining budgets. Select a whole feasible offer, debit every ancestor and increment the chosen branch's service count. A subtree found infeasible can be retired for this plan because remaining capacities only decrease. Stop when no further whole offer fits.
4. Return immutable grants, spent vector, active-node count and selection visits. `verify_plan` deterministically recomputes the plan against current inputs, including epoch and revision, and refuses altered or stale results.

This is hierarchical least-served selection, not an optimal multidimensional packing algorithm or a guaranteed deadline/fairness theorem for arbitrary changing workloads. The plan is maximal for the given indivisible demands and monotone budgets: no remaining ready leaf fits all remaining ancestor capacities. Replaying a plan is not a commit; consumers must enforce once-only execution, current readiness, receiver authority and actual resource usage. Prior service is advisory and externally supplied; it is not a durable ledger.

## Local measured evidence (2026-11-24)

Exact tested module blob 258a6a9ab7b141e16ed03646b82b3ca3eb0c3da2. Four local pytest tests passed, including 100 seeded heterogeneous allocation cases checked against an independent componentwise conservation and maximality oracle. Reversed input order preserved plan identity; changed revision, epoch or grant order failed replay verification. Duplicate scopes and invalid capacities were refused.

A deterministic odd-multiplier permutation selected distinct identities from the full 24-bit space. Each offer had a two-label recursive suffix and unit demand in every dimension. Capacity was 64 in each dimension. Times include input sorting, digest, trie construction and selection; exclude offer construction and independent replay.

| Ready offers | Active prefix nodes | Grants | Selection node visits | Seconds |
|---:|---:|---:|---:|---:|
| 16 | 125 | 16 | 145 | 0.001584 |
| 256 | 1,715 | 64 | 577 | 0.008723 |
| 4,096 | 22,273 | 64 | 577 | 0.111094 |
| 65,536 | 294,298 | 64 | 577 | 3.153394 |

All plans were independently replayed; no full 16M address scan. The 577 visits are 64 eight-label paths plus root per grant and one final zero-capacity check, not the total work of building the trie. Heterogeneous blocked or infeasible demands can require additional visits. Construction cost grows with supplied offers. A persistent incremental prefix index is the next optimization; this implementation rebuilds for each plan.

## Native integration

The previously hosted-green FAB-013 test now invokes the allocator rather than its inline least-served selector. Two address-scoped process trees in one native HeadlessOS compete for one extra resident mapping. Native DAG readiness defines offers, and the digest binds node revision, actual process report, exact predecessor results, pinned page identity and native memory info. Each grant requests three scheduler quanta, one extra resident mapping, one mailbox injection and one declared working-page observation. The test independently verifies the actual page bytes, native quota refusal, native instructions, reclaim, result commit, checkpoint and final termination. Completed-grant service counts drive subsequent selection. The control/test observations, final cleanup instructions and checkpoint work are outside this workload grant; the vector is not comprehensive metering of all host activity.

The test uses the existing native OS/scheduler/memory authority; planner output alone does not authorize effects. The planner is not yet an authenticated or crash-durable resource reservation protocol. The current native test uses four tasks inside one OS, not 16M resident OS instances. The dedicated workflow includes existing native CPU-navigation and DAG regressions.

## To Do

- Maintain incremental digest-bound prefix summaries and measured ready-set updates. Separate planning cost from observation collection, selection, and execution.
- Bind the grant lifecycle to receiver-owned admission, leases, epochs, actual resource receipts and durable service accounting.
- Extend from one OS process tree to independent native environments, using existing Structural Memory, M3 recovery and compositional DAGs. Measure actual host RSS in addition to resident mapping counts.
- Incorporate observed regeneration cost, readiness, information gain and deadlines without overriding fairness, capability or dependency constraints.
- Use FAB-012 literal/leap realizers as alternate workload realizations behind the same observed resource contract.
