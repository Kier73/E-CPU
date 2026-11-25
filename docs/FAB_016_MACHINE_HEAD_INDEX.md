# FAB-016 — Persistent, sparse machine-head addressing

## Purpose

FAB-009–012 demonstrated full-space address and compact CPU execution, and FAB-013–015 connect native resource attention and canonical machine identity to HeadlessOS. The next bottleneck is locating retained application state without allocating a native interpreter, full OS snapshot, or session-store object per potential machine.

The index is an immutable, advisory directory of observed M3 checkpoint heads. M3 remains the sole authority for current session state. The caller supplies an independently trusted index root and locally admitted session store; a hash is content identity, not authorization. An absent slot means no indexed observation, not proof that a machine has never existed. A missing referenced page is an error, never an empty slot. There is no automatic creation of replacement state.

## Geometry and encoding

A 24-bit machine identity is four base-64 digits. The four levels use fixed 4096-byte pages compatible with the existing native PageBacking contract. Each page binds its namespace, depth and address prefix in a canonical binary header. Branches hold 64 SHA-256 child identities; leaves hold 64 records, each (unsigned 64-bit revision, 32-byte checkpoint digest). The all-zero slot denotes unindexed. Positive revisions are required for real records. Unused padding must be zero; reads rehash the exact page and verify scope. Root and all ancestors bind the path.

A populated lookup reads at most four pages. An update rewrites at most four pages for one machine, and a batch rewrites shared ancestors only once. Revision regression and same-revision conflicting heads are refused relative to the supplied root. No root is mutated; previous roots still address their historical index observations. This does not imply that every historical OS snapshot is retained or independently readable. If a batch fails, unreachable immutable pages may remain; root publication and garbage collection belong to a separate durable protocol. There is no index-level concurrent-writer CAS, authenticated root publication or recovery lineage here. A malicious or stale caller-supplied root cannot override native M3.

`resolve_current(root, identity, store)` checks the exact `fab127.<namespace>.<24-bit hex>` session ID and loads the native M3 verified high-water checkpoint. It returns that native snapshot only when the indexed revision and checkpoint digest match. The store must be provided by a trusted local resolver; this method does not grant execution permissions. Future transitions still require native M3 compare-and-swap. This is intentionally distinct from using the index as a second state authority.

## Measured local evidence — 2026-11-24

The full-space experiment uses synthetic checkpoint digests computed independently from machine identity and revision. It verifies every stored record by walking all leaves and checks 4096 public lookups against independent expected heads. It then updates 64 sampled identities to revision two and verifies both old and new roots, as well as the original empty root. The full run used source blob aced52245aa5b5fb46cf38376c1b6aeff7eb2441; the final blob 71a9821eb9dbfa19db9dcebe5c84ee14ae6897f9 adds native M3 resolution and clarifies the meaning of absence without changing the measured index operations. Four local index tests and a 65,536-head benchmark passed again with the final blob.

| Metric | Full 24-bit index |
|---|---:|
| Verified head records | 16,777,216 |
| Live index pages | 266,305 |
| Live index bytes | 1,090,785,280 |
| Retained page bytes before update | 1,091,047,424 |
| Batch build seconds | 89.356799 |
| Exhaustive independent verification seconds | 22.186598 |
| Sampled lookups / page reads | 4,096 / 16,384 |
| Sampled lookup seconds | 0.289968 |
| Updated heads | 64 |
| Newly retained pages | 167 |
| Update seconds | 0.006496 |
| Peak whole benchmark RSS, KiB | 1,295,548 |

The dense live index uses about 65 bytes per address including directory pages and padding. The empty index uses one page; only observed branches are materialized in sparse mode. Timings use an in-memory backing and do not include disk fsync, network transport, M3 verification or application execution. The independent sweep verifies all synthetic head records, not all public lookup paths individually, and not actual quorum state. Local tests cover both address extremes, same-leaf batching, immutable history, invalid scope, stale/same-revision conflict, missing/corrupt pages, 40 randomized update epochs, and reopening a test file backing. The final 65,536-head repeat retained 1,042 live pages, built in 0.394310 seconds, and verified all records in 0.086033 seconds. The source and benchmark are under mailcpu/fabric_head_index.py and examples/fab_127/benchmark_head_index.py.

## Native application-density experiment

The separate hosted test uses 8 and 64 distinct actual HeadlessOS environments, each running a private memory-to-file native program. Each machine has an independent three-member M3 lineage with durable journals and three accepted revisions; machines share a native local M1 page CAS. The controller materializes at most four candidate work items at a time, realizes them in a process pool (up to four workers), verifies each proposed successor through the original HeadlessOSQuorumTransitionBackend and commits with the original M3 adapter. It replaces the worker pool between two execution phases. The test reopens native stores, verifies that indexed heads agree with current M3, challenges stale, missing and cross-machine roots, checks exact private memory and file content, descriptors at the cut, exit status and journal, and measures logical snapshot bytes versus unique page bytes, index bytes and lineage/session file bytes. Candidate-worker count is not total resident OS count; the controller also restores native reference states and holds bounded snapshot copies. Both page services and all lineage journals are local to one runner, not independent failure domains. The workload is native MailCPU with conventional-style syscalls, not arbitrary conventional binaries.

This integration test is staged for hosted verification, not measured locally, because direct repository checkout was unavailable. It uses the legacy native absolute scheduler ceilings 3 and 10, so it does not depend on the separately pending FAB-015 relative-quantum contract. Dedicated CI separates the full synthetic index benchmark from the native application-density benchmark.

## To Do

- Measure actual native density and identify repeated snapshot structure, byte-level deduplication and lineage overhead separately. Rework earlier snapshot representations using measured bottlenecks rather than assuming that compact CPU state scales directly to native application environments.
- Publish trusted index roots through sharded existing quorum state, with explicit stale-index refresh and independently recoverable page backing. Index updates after M3 commits must be recoverable even if the index publication is lost.
- Connect per-machine ready observations to the incremental attention hierarchy; avoid scanning all initialized machines for each grant.
- Use relative native execution quanta and external effect receipts; test cross-host loss and replay with independent storage replicas.
- Extend native workloads from files and private pages to multiple processes, conventional application runtime adapters and continuous application sessions. Report address capacity, retained native states, realized workers, and verified histories separately.
