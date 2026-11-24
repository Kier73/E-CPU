# FAB-020 — Quorum-verified head observation before realization

## Native authority and observation

The existing ComputationalSessionStore.load_latest previously read the current quorum proof and high-water, decoded the immutable local checkpoint envelope, verified checkpoint scope and membership coordinates, verified the native lineage proof, then verified and read all native M1 state pages. FAB-020 factors the first stage into observe_head(), returning a typed ComputationalSessionHead (checkpoint, lineage manifest, verified proof). Every original metadata/lineage check is retained. It performs no M1 page resolution. A head is a point-in-time observation of the committed state identity, not proof of currently available bytes, runnable process state, or authorization to execute.

load_latest() retains full native verification through the same metadata path followed by _materialize_head(). New load_observed(head) re-observes the local current quorum head and compares the full checkpoint, lineage identity and proposal identity before reading any pages. It refuses stale/foreign head coordinates, then performs the original full M1 verification and read and constructs the original ComputationalSessionSnapshot. The original successor CAS remains authoritative; neither observation nor materialization leases the head against a concurrent writer. No persisted checkpoint format changes. A missing state page may leave a valid committed head observable but must refuse materialization. The returned head includes the native page manifest, so metadata size and verification cost may scale with the number of page references. There is no claim of constant-time native quorum verification.

## Incremental pending-intention index

HeadAttentionIndex binds a single controller to a canonical fab127.<64 hex namespace>.<6 hex machine identity> session naming convention (compatible with FAB-015). refresh(store,demand) invokes native observe_head and records monotone revision/checkpoint/lineage coordinates; explicit nonempty demand inserts or replaces one pending offer; demand=None removes it. Regressing or same-revision conflicting observations are refused. The epoch advances on meaningful index changes. The index keeps observed coordinates for known identities and full head metadata only for pending intents. It does not automatically infer that an application is runnable from a checkpoint. It is volatile, single-controller state; durable intent admission, expiration, notification replay, trusted scope resolution and multi-controller ownership remain separate.

The existing FAB-014 allocator is reused over only pending offers. It still rebuilds its active trie and hashes the pending input set per plan; the index eliminates repeated scanning of dormant identities, not the O(pending) construction. Service counts are supplied by the caller from completed grants. Plans are advisory; verify against current epoch/inputs before use. load_grant checks the currently pending offer, uses load_observed for selected state, and does not itself confer permissions or check a whole plan. withdraw removes exactly the matching offer. Execution still goes through native admission and CAS. Neither a verified head nor an externally supplied demand establishes an application process's readiness; that needs a receiver-verified state projection or an independently admitted work event.

## Measured controller-only experiment

Exact locally tested head_attention.py blob 02652825410392fdbdcd0933d8528c3bc498da73 and existing merged attention.py blob 258a6a9ab7b141e16ed03646b82b3aeb0c3da2. Three local tests with a session fixture passed: lifecycle and stale withdrawal, same-revision conflict, regression and namespace refusal, hierarchical budgets and service priority. Native store was not available for local checkout (DNS); the fixture only implements the observation/materialization interface and does not simulate or establish actual quorum verification. The checked-in controller benchmark uses an explicit subclass fixture with overridden methods, never as native authority.

| Metric | Local result |
|---|---:|
| Logical coordinate population | 16,777,216 |
| Distinct fixture heads observed initially | 65,536 |
| Pending intentions | 64 |
| Initial refresh seconds | 0.229234 |
| Full offer set planning seconds | 0.210468 |
| Pending-only planning seconds | 0.000594798 |
| Initial grant equality | exact |
| Active nodes, both plans | 199 |
| Update epochs | 256 |
| Changed-head observations | 256 |
| Selected fixture materializations | 256 |
| Epoch loop seconds | 0.559164 |

Both plans have identical active prefixes and initial grants. The full input includes 65,472 nonready offers, whereas the sparse input includes only pending work. Offer construction was excluded from the dense planning time. The reduction is from avoiding sorting/hashing/scanning dormant offers, not from a faster native quorum or a claim that millions of native machines have been initialized. The epoch loop plans and verifies, selects one of four grants for fixture advancement, refreshes that changed head and verifies stale-plan refusal, then updates completed-service counts. All timings are single local runs.

## Native integration tests (hosted, pending)

tests/test_head_attention.py uses actual ComputationalSessionStore, ComputationalObjectStore and RecoveryLineageCoordinator with separate local authority journals and a counting native page backing. Tests cover absent checkpoint, metadata-only observation with missing payload, exact selected recovery, cross-machine/stale refusal before payload reads, tampered checkpoint envelope, pending lifecycle and exact grant identity. Two fleet trials create 8/32 actual native generic sessions with sixteen 4 KiB pages each, compare full-state recovery of every candidate to metadata-first selection of 2/4 machines, and advance one selected native CAS before refreshing just that leaf. The expected payload accounting is 256 vs 64 reads and 1024 vs 128 reads, respectively, because the original full recovery separately verifies and reads each page. Metadata observations and planning are expected to perform zero page reads. These are explicit test assertions, not measured native results yet. Three authority journals per session are local, not independent hosts. Existing native session, transition and attention regression tests run in the same workflow.

## Next development

Connect a compact receiver-verified readiness projection to exact committed checkpoints and existing durable mailbox/DAG events. Use those events to update the index without reconstructing or polling every machine. Integrate native head indexing from FAB-016 and independently observed pages from FAB-019 when their hosted verification succeeds. Measure complete native metadata/lineage cost, pending-set maintenance and physical realization cost. Persist/replay readiness and retirement independently of the execution worker and preserve the distinction between an advisory observation, qualified execution and authoritative successor admission.
