# FAB-027 / FAB-028 — Recoverable independent machines and dependent collective layers

Two independent capacity tracks. FAB-027 deliberately holds the FAB-025 application constant to isolate recovery semantics. FAB-028 changes the collective workload to a graph whose number of layers depends on its actual progress. Both full-coordinate runs are local experiments using compact records, not a measured population of native HeadlessOS/M3 sessions or separate physical network hosts.

## Shared local publication contract

The coordinator binds each contribution to its executable SHA-256, geometry and (for a successor) predecessor payload digest. It maps the predecessor read-only. The worker writes a separate exclusive staging file and synchronizes it before successful return. The coordinator checks the extent, hashes the staged bytes, renames them, synchronizes the directory, then publishes and synchronizes a separate receipt as the commit marker. On reopen, a matching receipt requires matching scope, extent and content digest. An uncommitted staging file (or data file with no receipt) is discarded and reconstructed. Required fleet predecessors must exist when advancing or verifying.

This is a single trusted local coordinator protocol: no concurrent writers to the same record, no adversarial authenticity or distributed consensus, and no general external side-effect rollback. Receipt metrics are trusted local diagnostics, not cryptographically authenticated proof of execution. The complete final source oracle is necessary for mathematical admission. Process loss during computation was tested; power-loss behavior, interrupted rename/receipt publication, coordinator crash at each publication cut and independent host/storage loss remain separate experiments. Retained bytes are native-endian, fixed-layout structures, not portable OS images.

## FAB-027 — Immutable shard successors for independent applications

The original FAB-025 bytecode interpreter and oracle are compiled directly into fab027.c. Each 128-byte machine contains private transaction records, two process contexts, registers, mailbox and file-like words. Sixteen disjoint ranges cover every identity from 000000 to ffffff, with 1,048,576 machines per shard. All initial states advance to the same 50-instruction cut. A new worker reads its shard's immutable initial state, advances both processes, and verifies each completed machine using the original independent high-level oracle. Its staging output is never the predecessor.

Injected process exit occurs after 524,288 machines in shard 8 (zero-indexed) have completed in the uncommitted staging mapping. The other workers in that batch finish and publish; dispatch stops after that batch. A separate coordinator reopens with three workers, reuses eleven committed successors, and computes five missing successors (the interrupted shard and four not yet dispatched). A separate read-only verification pass checks all final records. The failed speculative work is excluded from committed instruction counts.

| Full local measurement | Result |
|---|---:|
| Independent compact machine records | 16,777,216 |
| Internal process contexts | 33,554,432 |
| Committed initial instructions | 838,860,800 |
| Committed successor instructions | 1,056,971,516 |
| Total committed retired instructions | 1,895,832,316 |
| Debit records | 67,112,318 |
| Audit checksum | 36,030,127,363,648,171 |
| Initial publication (4 worker processes) | 2.701210393 s |
| Interrupted advancement (4 concurrent workers) | 2.703174898 s |
| Committed successors at interruption | 11/16 |
| Fresh coordinator recovery (3 concurrent workers) | 4.641259215 s |
| Retained successors reused / new | 11 / 5 |
| Final verification (4 concurrent workers) | 1.496281285 s |
| Initial + final committed payload bytes | 4,294,967,296 |
| Final oracle mismatches | 0 |

Wall times include local worker startup, synchronization and content hashing within each phase. Initialization, interrupted advance, resume and verify were distinct Python process invocations. Both 2 GiB generations were simultaneously retained on disk. Not all compact machine records were resident or executing simultaneously. A 4096-machine control with 8 shards reused 7 completed successors and rejected a corrupted final payload and an absent required predecessor.

## FAB-028 — Adaptive collective weighted-path computation

The graph is a single rooted tree over the entire 24-bit identity space. In logical order it has a long backbone and irregular branches; the coordinate permutation is id=(5*i+3) mod 2^bits, root id=3. Every nonroot has a positive integer edge weight and an earlier parent in the logical construction order. The initial graph stores each parent and weight explicitly; subsequent workers only read the prior committed graph layer, not the generator. Each node uses an eight-byte record. For any node whose parent is not root, the exact synchronous recurrence is

    p_next(i) = p(p(i))
    w_next(i) = w(i) + w(p(i))

A node already pointing at the root retains its weight. This is weighted pointer jumping: compose two existing path descriptions, preserving exact distance along the original tree. Each layer maps its predecessor read-only and writes a new array, divided across local threads. The coordinator stops at the first committed layer whose unresolved count is zero (bounded by address width). A failed worker exits its whole layer process during active computation. The coordinator reuses the four completed layers plus original input and recomputes the incomplete fifth layer. The final oracle is a separate sequential topological dynamic program over the original edge records, checking parent-before-child coverage and all output distances; it uses the known topological order of this generated family, not pointer jumping or the generator's weight formula.

| Full local measurement | Result |
|---|---:|
| Graph coordinates | 16,777,216 |
| Dependent layers until resolution | 22 |
| Committed layer-coordinate scans | 369,098,752 |
| Committed active pointer updates | 334,878,637 |
| Unresolved after final layer | 0 |
| Maximum weighted distance | 33,541,420 |
| Sum of exact distances | 175,835,083,396,679 |
| Interrupted initial realization (4 threads) | 1.875905013 s |
| Fresh coordinator completion (3 threads) | 6.198338559 s |
| Retained records reused / new at recovery | 5 / 18 |
| Final complete reopening (23 records, no new work) | 2.042878125 s |
| Final independent oracle after reopen | 0.415571790 s |
| All final coordinate matches | 16,777,216 |
| Retained payload bytes (23 x 128 MiB) | 3,087,007,744 |

Final SHA-256: 92f56b84d6d2bef76a9c00186425505021dc9827e424d0d3721457dd0665f00d. Recovery and final reopen matched. Counters refer to committed layers, not discarded failed work; reopening reports historical totals, not re-executed operations. Realization time includes retained-record hashing, subprocess startup and layer synchronization; excludes separately timed final oracle. All nodes are scanned each layer even though resolved nodes skip arithmetic. The data-dependent count contracts from 16,777,172 initially unresolved to 4,027,456 before the final layer and zero afterward. This is not a speed advantage over the sequential topological oracle (0.381497024 s following recovery). It establishes recoverable dependency-driven layers and exact source results for a structured graph family, not arbitrary graphs or general shortest paths. A 4096-node control also recovered after injected loss and refused an altered committed layer.

## Reproduce

Linux, GCC, Python >=3.11. From the repository root:

    gcc -O3 -std=c11 -Wall -Wextra -Werror -pthread examples/fab_127/fab027.c -o /tmp/fab027
    gcc -O3 -std=c11 -Wall -Wextra -Werror -pthread examples/fab_127/fab028.c -o /tmp/fab028
    python examples/fab_127/recoverable_fabric.py fleet fleet /tmp/fab027 --phase init
    python examples/fab_127/recoverable_fabric.py fleet fleet /tmp/fab027 --interrupt
    # Expected exit 17; restart independently:
    python examples/fab_127/recoverable_fabric.py fleet fleet /tmp/fab027 --workers 3
    python examples/fab_127/recoverable_fabric.py fleet fleet /tmp/fab027 --phase verify
    python examples/fab_127/recoverable_fabric.py graph graph /tmp/fab028 --interrupt
    # Expected exit 17:
    python examples/fab_127/recoverable_fabric.py graph graph /tmp/fab028 --workers 3
    python examples/fab_127/recoverable_fabric.py graph graph /tmp/fab028

Use fresh directories, reduce bits to 12 (and fleet shards to 8) for quick controls. Full run needs >7 GiB disk if retaining both experiments together. Temporary full payloads were removed following verification. Tested exact Git blobs: fab025.c cb76818025076c25627ea5b9d3b8384cb9c23730; fab027.c 4fcebf8762bc56e46039132a47d127ab3ab322a9; fab028.c 15420e2fd43442e2f8bb03d2b5417298b67e3d16; recoverable_fabric.py 80ff047b0b8ec94c051c4593b65d0f8eaf66882b. Dedicated hosted checks pending.

## Next implementation tracks

A. Bind immutable shard publication to the original M3 session/checkpoint authority, with independently verified machine heads, page-level structural memory and recoverable application state. Measure native application populations and actual resident working sets, not extrapolation from 128-byte compact records. Test failures while an application executes under native process and filesystem semantics. Add varied programs and inter-machine messaging to the compact full-population control.

B. Replace full-layer scanning with a retained active frontier; verify partition contributions against their exact inputs before publication, and retain successful sublayer contributions even when another worker fails. Connect actual native Transit partitioned frontier/rehome machinery, measure authenticated transport, and compare against appropriate direct algorithm controls. Extend to heterogeneous dependency graphs and demand-driven layer formation. Do not treat node-output coverage as evidence of separate resident VM capacity.
