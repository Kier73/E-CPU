# FAB-023 — Persistent shared computational realization

## Exact reuse contract

PureContract binds receiver-selected interpretation, context, verifier fingerprint and bounded input/result sizes into a canonical SHA-256 identity. Its work key is SHA-256(contract digest bytes || exact input bytes). The caller is responsible for the meaning, authorization, determinism and purity of the operation and for supplying the qualified verifier implementation. A fingerprint alone is not runtime attestation. Results are immutable local SQLite records, synchronous FULL. Every recovered result is checked against exact source/contract and its result digest and then independently verified by the receiver. A forged result with a correspondingly modified digest cannot satisfy a correct independent verifier. Equal input within a bounded batch is resolved once. No result returned by this mechanism constitutes authority to advance a session.

A missing key executes the supplied pure producer, verifies its output, and publishes an immutable result. Concurrent workers may duplicate producer work; conflicting publication refuses. Local durability is distinct from quorum replication. Batch size is limited to 65536 elements; individual input and result limits are at most 4 MiB. Callers must set their own aggregate memory/operation budgets. The bank rechecks each distinct stored result for each batch rather than caching a durable assertion of truth.

Consumer records associate one namespace and 24-bit machine identity with an observed revision, checkpoint digest and dependency key. The reverse index returns exactly those recorded subscribers within a namespace. Updates are transactional and refuse regressions, conflicting same-revision coordinates and duplicate identities in a batch. This is advisory metadata, not a verified live head directory: the controller must revalidate native committed heads and intention inputs before using these coordinates. This initial geometry permits one dependency per machine, not multiple dependencies per process or a general DAG. The index does not atomically commit with M3.

## Measured local trial

Exact module Git blob 18ca4a1cb2c8b2d011798f6feb0763987ad5f672. Four local tests passed, exercising result reuse across reopen, context separation, false result refusal even with matching altered digest, stale/foreign dependency controls, transaction rollback and abrupt process loss. Benchmark uses seeded 64-byte circular autocorrelation, literal producer and independent carry-free packed integer convolution checker. Private projections retain distinct machine coordinates. Native commits are not part of this synthetic benchmark. All output projections match the literal baseline. All seconds are single-run local measurements.

| Consumers | Distinct inputs | Literal + checker | Cold durable bank | Verified reopen |
|---:|---:|---:|---:|---:|
| 4096 | 64 | 1.308382 s | 0.099446 s | 0.008747 s |
| 1024 | 1024 | 0.342266 s | 1.507100 s | 0.051803 s |
| 4096 | 1 | 1.289298 s | 0.005831 s | 0.004667 s |

Cold and reopen timings include private result projection. Baseline does not persist a result bank; database initialization and dependency index formation are separately accounted. For 4096/64, initial dependency indexing took 0.083637 s. After reopen, 64 affected consumers were found, one new result produced and checked, and their dependency records advanced transactionally in 0.007994 s. This interval does not include native successor execution or independent oracle rechecking outside the measured interval. Bank and index database size is 1716224 bytes after the update. For the all-distinct case, cold persistence is substantially slower than direct calculation; representation formation must charge publication overhead. For the one-input case the affected set contains all 4096 consumers and updating its index took 0.081648 s. Producer counts cold = 64/1024/1; after reopen = 0 in every trial. Independent checks still occur for every distinct input after reopen.

## Native composition

The hosted test constructs eight independent native generic M3 sessions over an in-memory native page backing and three local authority journals per session. Two exact shared square results are retained, independently checked after catalog reopen and used as operands by a trusted pure projection backend; it binds the operand to the actual session state source and preserves private bias. Every consumer executes the original native transition adapter and CAS. Assertions cover eight distinct checkpoint and lineage identities, exact retry without backend re-entry, stale base refusal, recovered lineage and four matching dependency subscribers. This is a trusted local backend fixture, not independent remote attestation. Native verification is pending. The new module is independent of the unmerged FAB-020/021 branches.

## To Do

- Bind reusable operands to admitted operation and evidence identities in the native computation DAG; dispatch distinct work, retain independently verified child results, then use native successor admission per consumer.
- Support multiple typed dependency edges per machine/process and durable affected-frontier propagation, with committed revision revalidation.
- Measure representation selection using producer, checker, grouping, durable write/read, transport and admission costs; decline cold reuse where its formation cost is greater.
- Reuse existing authenticated communication and recovery paths for independent-host result availability. Charge independently replicated publication, not only local SQLite.
