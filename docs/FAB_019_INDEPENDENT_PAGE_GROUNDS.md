# FAB-019 — Independently observable page Grounds

## Architectural contract

A machine's exact native M1 page identity remains SHA-256 of the original 4096 bytes. FAB-018 describes complete snapshots relative to a pinned shared base. FAB-019 instead implements the native PageBacking interface itself; the original M1 manifest and M3 checkpoint format need not change. It can also retain non-JSON memory, artifacts and application state. Local retention uses SQLite, one connection per worker, synchronous FULL.

A page has one of three representations: raw bytes; independently zlib-compressed bytes; or a compressed XOR relative to an immutable raw basis page. For target P and basis B, D = P XOR B and P = B XOR D. Both B and P are independently checked against their original SHA-256 identities. The decoder bounds inflation to exactly one page, refuses trailing compressed streams, and refuses noncanonical raw basis references, cycles through alternate bases, missing pages and digest mismatch. A raw basis must be explicitly admitted; it never depends on a delta. No chain traversal is required. Candidate selection is a storage heuristic, not semantic admission: eight fixed 64-byte anchors, at most eight candidates per anchor, at most four evaluated candidate masks, at most 1024 admitted raw bases. The compressed XOR must beat the selected direct representation after charging a 64-byte reference allowance.

Publication inserts and verifies the immutable row inside a local SQLite transaction before returning the original page identity. Reopen derives the candidate index from raw bases; it reads and retains those admitted basis pages at startup. Later reconstruction independently re-reads the referenced raw basis from the database. No missing page is treated as empty state. One delta page read uses at most two payload rows and one basis membership lookup; ordinary page reads use one payload row. Whole-object verification remains the native M1 operation. Direct range reads are only claims about the selected verified bytes under a trusted manifest, not proof that the whole object is available or that a session is current. M3 continues to determine the authoritative committed state.

## Measured local experiment

Exact page_ground.py Git blob 2697208d5549cc90fb914824728590d3fa011dc6. Three standalone local tests passed: 128 independently retained mutations, reopen, unrelated-page corruption isolation, missing basis refusal, ordinary compression/raw fallback, altered raw page refusal, abrupt exit after commit and during a later uncommitted deletion, and absent database refusal. Native M1/M3 integration tests are staged for hosted execution, not locally measured.

All modes use the same local SQLite FULL protocol. Synthetic workload: 1024 objects of 16 x 4096-byte pages, shared seeded incompressible bases, two distinct four-byte private mutations per object. All 16,384 page observations per mode verified after database reopen; 1024 changed pages additionally observed in permuted order.

| Metric | Raw | Independent zlib | Page Ground |
|---|---:|---:|---:|
| Logical bytes | 67,108,864 | 67,108,864 | 67,108,864 |
| Database bytes | 9,691,136 | 9,691,136 | 524,288 |
| Raw stored pages | 2064 | 2064 | 16 |
| Delta stored pages | 0 | 0 | 2048 |
| Delta payload bytes | 0 | 0 | 79,141 |
| Write seconds | 3.310677 | 2.903725 | 2.562309 |
| Full verification seconds | 0.226400 | 0.233899 | 0.227398 |
| Sparse read seconds | 0.017518 | 0.018509 | 0.049353 |
| Sparse read SQL SELECTs | 1024 | 1024 | 3072 |

The measured database size reduction is 18.48x. Database sizes include SQLite row/index overhead but exclude native M1 manifests and M3 journals. Durability is local transaction/process-loss recovery; filesystem power-loss guarantees and independent-host replicas were not tested. The data are intentionally related; unrelated pages may use ordinary compression or raw fallback. Wall-clock measurements are one run, not a performance guarantee. An earlier byte-loop XOR implementation took 0.212057 s for sparse reads; fixed-width integer XOR reduced that to 0.049353 s while preserving byte identity. The benchmark excludes opening the basis index from the timed read intervals.

## Native composition

The original ComputationalObjectStore is used directly over PageGroundBacking. Hosted tests compare native manifests from raw and structural backings, perform a four-byte range observation with only three SELECT statements after reopen, and corrupt a distant page: the unaffected local range remains valid while complete native verification refuses. A separate original M3 session test creates a 64 KiB fixed-page state, reopens and restores its exact exported checkpoint, commits a change to another page, reopens again, then exercises corruption refusal without changing quorum high-water. It uses three local durable journals, not independent failure domains. Both hosted integration results remain pending.

This implementation is independent of the stacked FAB-017/018 snapshot-level representation, so it can be verified and merged separately. The two are complementary: structural JSON descriptions exploit semantic alignment and differing lengths; fixed-page Grounds preserve independent native page observations and can support arbitrary bytes.

## Next implementation

- Measure native HeadlessOS snapshots, memory pages, model artifacts and actual application state against raw, independent compression, page Ground and snapshot Ground representations under matched durability.
- Connect selected page and observation offers to the recursive attention allocator. Current M3 load_latest still verifies and reads the whole state; a separately verified metadata-only head observation is needed before scheduling selective application reads.
- Reuse native authenticated communication and remote page services to replicate raw bases and alternate records across independent hosts. Local storage is not federated recovery.
- Support page-aware native state construction and qualified partial execution, so an application operation can consume only its verified input region while committing exact complete successor identity under existing authority.
