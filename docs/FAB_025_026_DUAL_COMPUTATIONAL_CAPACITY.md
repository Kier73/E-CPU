# FAB-025 / FAB-026 — Dual full-coordinate computational capacity

## Separate research objectives

A. Independent machine capacity: instantiate every 24-bit machine identity with independently mutable application state, progress and continuity. Increase per-machine application complexity and native operating environment compatibility while retaining all identities. Do not substitute shared pure work or output-coordinate coverage for evidence of independent machine capacity.

B. Collective computational capacity: partition a single substantial computational intention across the 24-bit coordinate space, including successive layers of that space. Qualify each contribution, retain successful work, recover missing work, and assemble an exact final result. Do not substitute logical output coordinates for independently executing full operating environments or physical hosts.

These are complementary measurements, not interchangeable claims. FAB-025 extends the compact stateful interpreter experiments; FAB-026 is an independent dense numerical partitioning/recovery experiment. Both were executed locally at full geometry, and their source Git blobs match the locally tested files. No private external research source is included.

## FAB-025: one private transaction application per machine

Source: examples/fab_127/fab025.c, tested blob cb76818025076c25627ea5b9d3b8384cb9c23730.

One 128-byte Machine contains eight private 32-bit transaction records, eight transaction registers, four audit registers, four file-like state words, one message slot and availability flag, two program counters, two instruction counters, and two process statuses. IDs are the dense indices 0..2^24-1, corresponding to 127/8 logical coordinates (no UDP operation in this experiment). The private records are seeded by identity; all machines use the same immutable bytecode. A 21-instruction transaction program loops over its records using loads, bitwise operations, conditional branches, arithmetic modulo 2^32, writes to file words and SEND. The independent 10-instruction audit program waits via RECV, reads the file words, computes its private audit result, stores it, and halts. Each context has its own PC and status; the scheduling policy first attempts audit receive, advances the transaction process, then awakens the audit process after SEND. No computation is factorized or skipped. The file words are compact application state, not a POSIX filesystem.

At the first checkpoint, all transaction contexts have executed exactly 50 instructions and remain runnable; all audit contexts are waiting at PC 0. The first executable maps a new exclusive file with 2^24 records and calls msync(MS_SYNC) and fsync before clean exit. A shell computes and checks SHA-256 before the new process reopens the same file using a different number of worker threads. Resume modifies it in place. A third read-only process verifies all transaction records, file words, selected final registers, both terminal PCs, both instruction counts, both statuses, and empty mailboxes against a separate high-level transaction/audit oracle. It does not reuse the bytecode interpreter for this oracle. The record generator is shared with the oracle, so it checks the intended deterministic inputs, not an independently generated dataset. The oracle requires 95+2d transaction instructions for d debit records and 10 audit instructions. The failed initial receive is not counted as a retired instruction.

| Measured local full geometry | Result |
|---|---:|
| Independent compact machines | 16,777,216 |
| Internal process contexts | 33,554,432 |
| Private records | 134,217,728 |
| Retired instructions before checkpoint | 838,860,800 |
| Retired instructions after reopen | 1,056,971,516 |
| Total retired instructions | 1,895,832,316 |
| Total debit records | 67,112,318 |
| Final audit checksum (sum of unsigned outputs) | 36,030,127,363,648,171 |
| Checkpoint extent | 2,147,483,648 bytes |
| Initial worker count / execution seconds | 4 / 5.390933301 |
| Initial synchronization seconds | 0.003545041 |
| Resumed worker count / execution seconds | 3 / 4.442304158 |
| Resume synchronization seconds | 0.177568788 |
| Full final oracle seconds | 0.275762120 |
| Oracle errors | 0 |
| Peak process RSS (largest phase) | 2,097,560 KiB |

Initial checkpoint SHA-256: 34bac964fda391edca3f7f1424c83067e3638ddd7aa28e8effdda711615a3492. Hashing and its immediate check are excluded from execution timings. A 4096-machine control also completed and verified with a changed worker allocation, then deliberately altered a final file word; the full verification refused. The checkpoint is native-endian fixed layout, local clean-cut process-restart evidence; it does not provide atomic rollback during interrupted in-place resume, cross-host durability, full OS semantics, native HeadlessOS or M3 quorum. All local execution was on one machine with a four-CPU cgroup quota and a 4 GiB memory limit. The full temporary checkpoint was removed after verification.

Reproduce (Linux, GCC, POSIX pthreads):
    gcc -std=c11 -O3 -Wall -Wextra -Werror -pthread examples/fab_127/fab025.c -o /tmp/fab025
    /tmp/fab025 init 24 4 fleet.chk
    sha256sum fleet.chk > fleet.sha256
    sha256sum -c fleet.sha256
    /tmp/fab025 resume 24 3 fleet.chk
    /tmp/fab025 verify 24 4 fleet.chk

## FAB-026: layered dense contraction

Source: examples/fab_127/fab026.py, tested blob fcd6c33cb1ef4bc674921e71374cad57a2051950.

Two independent seeded dense 4096 x 4096 matrices A and B have signed integer entries in [-7,7]. Output coordinate id = 4096*i+j covers precisely the 24-bit logical fabric. For L=8, layer l contributes A[:,512l:512(l+1)] times B[512l:512(l+1),:]. For each layer the row range is split into four nonoverlapping shards, each computed by a distinct subprocess using one BLAS thread and published as canonical receipt metadata plus exact little-endian int32 payload. Input descriptors pin both input file hashes and geometry; coordinator validates metadata, scope, extent, content hash and arithmetic magnitude before accumulating. A single trusted local coordinator assigns each shard once at a time; workers and inputs are trusted during execution, not remotely authenticated. Publication uses a temp file, fsync, atomic rename, directory fsync. Local reopen reconstructs by reading all contributions, not by redoing products. An injected worker exits after computing one shard but before publication; only that shard is retried. The receipt checks bytes and geometry, not mathematical correctness of an individual shard. Full final admission is the separately computed complete oracle; malicious coordinated compensating partial errors are not excluded by final equality alone.

Exactness: every product is an integer of magnitude <=49; every sum of any subset of terms has magnitude <=49*4096=200704, less than 2^24. Thus the chosen binary32 kernel and binary64 unpartitioned reference can represent each product and intermediate sum exactly. Compare the entire int32 result against the unpartitioned float64 BLAS reference (same library, different dtype/decomposition) and additionally check 4096 sampled coordinates by literal int64 dot products. This is dense standard matrix multiplication, not a complexity-class result. Both paths execute the same mathematical operation; the layered path is slower locally.

| Measured local full geometry | Result |
|---|---:|
| Output coordinates | 16,777,216 |
| Summation layers | 8 |
| Coordinate-layer contributions | 134,217,728 |
| Logical multiply-accumulates | 68,719,476,736 |
| Attempted multiply-accumulates including failed shard | 70,866,960,384 |
| Successful shards / worker invocations | 32 / 33 |
| Injected failed worker | 1 |
| Layered realization seconds | 9.097861428 |
| Full unpartitioned reference seconds | 0.877462314 |
| Literal integer dot checks / seconds | 4096 / 0.122946559 |
| Exact full-output matches | 16,777,216 |
| Shard storage including receipt headers | 536,878,932 bytes |
| Coordinator peak RSS (not total workers) | 635,444 KiB |
| Fresh coordinator reopen seconds | 1.596211746 |
| Reused shards / new worker invocations | 32 / 0 |
| Full reopened oracle matches | 16,777,216 |
| Reopened full reference seconds | 0.862755512 |
| Result sum | -2,978,593 |

Output SHA-256: 602c14ad5d60542d6ff3fd53141f91578a2130d35b368d2a6e22b2fabd66c186. Both initial and reopened realizations agree. Input identity eef7c4b49b13a990ebdaf0cf4a0f38215777ea383f010674f8a8fea350efd04b. Initial input generation/hash checks, final oracle and result hashing excluded from layered timing. Local worker processes are not 16.7 million concurrently resident VMs or independent physical hosts. No transport, native DAG admission or quorum cost is included. NumPy with OpenBLAS 0.3.30 (one thread per worker) and four threads for the reference; times are single-run observations. A small 64x64 control with four layers/three workers recovered all 12 shards, then removed one and reopened: one worker invocation, 11 retained shards, all 4096 outputs exact. One altered payload byte was refused. Temporary shard files removed after full verification.

Reproduce (Linux, Python, NumPy and threadpoolctl):
    python examples/fab_127/fab026.py collective
    python examples/fab_127/fab026.py collective --resume

## Tandem implementation sequence

Independent fleet:
- Extend compact per-identity application processes to heterogeneous admitted executable programs, memory geometry and independently persisted state. Keep a full-population literal execution control. Measure per-machine workload, process/IPC semantics, address coverage, latency, resident bytes, checkpoint/recovery cost and application correctness separately.
- Run actual native HeadlessOS application states at increasing populations (64, 256, 1024 and beyond, subject to measurement), integrating canonical fabric session identity, M1/M3 continuity, native head indexing, structural page backing and incremental attention as their dedicated checks complete. Distinguish resident, recoverable, runnable and actively executing counts. No extrapolated full-OS population as measured evidence.
- Test independent native network-connected hosts, failure while actively advancing, capability isolation, persistent application state and general executable/runtime compatibility.

Collective fabric:
- Treat layer/shard contributions as typed native work requests and bind them to the existing partitioned frontier dispatcher, native receipts and quorum-fenced rehome machinery. Start at modest actual multi-host scale; preserve exact output and count transport/verification/retention costs. Keep the full-coordinate dense reference as a control.
- Develop nested partition/reduction, sparse dependencies, reusable subgraphs, independent contribution verification and layer composition. Benchmark heterogeneous numerical, simulation and mathematical tasks; compare direct optimized kernels and structural alternatives with setup and verification fully charged. A failed or unprofitable representation remains explicit evidence.
- Measure actual 24-bit logical coverage, node work, layer count, distinct worker and host count, durable completion, missing-work recovery, and wall-clock cost independently. Aim for combined execution across actual independently identified E-CPU machine environments, not simply more output elements.

The two tracks can share native identity, resource allocation, communication, Structural Memory and verified continuity without conflating capacity metrics.
