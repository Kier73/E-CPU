# FAB-010 — Statefully materialized CPUs and an independent temporal view

## Two meanings of every 127/8 coordinate

This experiment implements the two address Grounds concurrently in resident memory. Machine identity i is the low 24 bits of the IPv4 destination. Each address has one primary process context and one secondary process context, with distinct mutable registers, program counter, step count, program ID and halt state. The primary context has a one-word mailbox. In a separate observation context, the same 24 bits denote instruction time of a single moving CPU. An ingress/port context selects which interpretation applies; the physical address itself does not authenticate or authorize a request.

The current Linux C realizer is a compact prototype: two 32-bit registers per process, fixed shared instruction programs, one atomic mailbox per machine, four worker threads by default. No process-per-address or per-address sockets. The 8 instruction types are ADD, XOR, MUL, SEND, RECV, BRANCH, HALT and JUMP. The two primary programs exercise distinct arithmetic, reciprocal communication, conditional control flow and termination. The second context performs nine instructions of a three-instruction loop and remains runnable. The primary process is rechecked after secondary execution and after the time sweep. This is an address-identified instruction-machine fleet, with program loading, dynamic process creation, arbitrary communication graphs, scheduling fairness, general memory, isolation and native E-CPU authority still to be integrated.

## Native ingress and execution

Four worker threads have one loopback-bound receiving socket and one sending socket each. Each transmits at most 32 empty UDP datagrams before receiving. The first instruction of each primary process occurs only after observing the kernel-supplied destination (IP_PKTINFO) of its address; uniqueness, peer, batch membership and queue tail are verified. All 16,777,216 addresses, including 127.0.0.0 and 127.255.255.255, are exercised with zero application payload. Subsequent instructions execute in the userspace C interpreter, not the networking kernel. Inter-CPU SEND/RECV uses the realizer's atomic in-memory mailbox, not physical UDP for every message. Each sender has a distinct peer i XOR (2^23 OR 1). Empty, reserved and full mailbox states are separate; a blocked instruction does not advance PC. Phase barriers ensure the workload's causal order.

The primary oracle independently computes expected final registers, mailbox consumption, PC, instruction count, branch and halt state for every machine. The secondary oracle checks all secondary states and rechecks the primary fleet. The report checks individual values before emitting counts and sums. The 4,096-CPU run produced identical semantic counts and checksums for 1, 3, 4 and 16 workers. An explicit self-test checks blocked empty receives, full mailbox sends, zero delivery and subsequent successful sends.

## A machine in motion

For the loop program MUL 5; ADD 3; JUMP 0, let q=floor(t/3), r=t mod 3. Define F(x)=(5x+3) mod 2^32. At instruction time t the complete relevant observation is PC=r and register x=F^q(12345) for r=0, 5*F^q(12345) for r=1, and 5*F^q(12345)+3 for r=2, all modulo 2^32. The other register remains zero, program ID and halt flag fixed and instruction count equals t. Affine powers are composed by repeated squaring, with no history materialization needed for a query. Each requested coordinate arrives through a real UDP destination. The sweep uses the permutation (5k+3) mod 2^24, allowing requests in nonchronological order. A separately generated sequential interpreter trace is retained solely for verification; the navigator does not read it to form the answer. Every coordinate's PC and register are compared. The Python checker separately uses the existing E-CPU lcg_navigate for live temporal probes.

## Local full-scale evidence (2026-11-24)

On one Linux kernel, four physical worker threads, exact full-scale source blob e8dc4843312834e16b4b5fdd9459526d590d6f00:

- 16,777,216 distinct actual activation datagrams; 9.363825 s.
- 16,777,216 halted primary CPUs; 124,518,400 primary instructions including activation; 16,777,216 sends and receives; 9,699,328 taken branches; post-activation execution 0.260054 s.
- 16,777,216 separate secondary contexts, 150,994,944 secondary instructions in 0.610611 s. 33,554,432 co-resident contexts, 275,513,344 total primary/secondary instructions; 939,524,096 bytes (896 MiB) retained machine/process data.
- 16,777,216 distinct actual temporal query datagrams, complete PC and register matches; 10.831032 s. Sequential oracle trace generation 0.842952 s. Peak RSS 1,049,088 KiB including oracle trace. Primary final states independently rechecked.
- All result sums: primary 36349145441370112, secondary 36028801104216064, temporal 36033477933371508.

These are actual virtual instruction executions in four threads, not millions of physical CPU cores or OS processes. The benchmark is a fixed bounded workload, not a general VM performance claim. Timings exclude some setup and verification; comparing independent temporal requests against shared sequential traversal is not a navigation speedup claim.

## Realization equivalence and hosted refusal

A hosted full-network run returned EPERM at 127.246.55.222. This is recorded as a substrate refusal; it is not treated as a missing/accepted coordinate or bypassed. The hosted native controls (4,096-machine runs at 1, 3, 4 and 16 workers and 40 direct temporal probes checked by the existing E-CPU law navigator) passed. The same CPU semantics are now separately testable with --resident: direct logical coordinates without networking, explicitly reported as zero packets. Native mode remains separately runnable, including as workflow_dispatch; neither mode's report can satisfy the other mode's packet-count requirement.

Exact refined source blob 09970f699d82a30a83ad7e153d7b464b12cd6b01 repeated both full local modes: all machine, secondary and temporal checksums identical to the original full run. Native activation 11.287265 s, primary post-activation execution 0.473936 s, secondary 0.327183 s, motion navigation sweep 10.688598 s. Resident activation 0.142010 s, primary post-activation execution 0.985021 s, secondary 0.523239 s, motion navigation sweep 0.507154 s. Resident timings exclude initialization and other checks and do not establish a statistically controlled speedup. The native run independently checked all 33,554,432 address events; the resident run independently resolved the same number of logical coordinates. Both retain 896 MiB of primary, secondary and mailbox state.

## Reproduce

```sh
cc -O3 -std=c11 -Wall -Wextra -Werror -pthread examples/fab_127/fab010.c -o /tmp/fab010
/tmp/fab010 --selftest
/tmp/fab010 --probe 16777215
/tmp/fab010 12 4
/tmp/fab010 24 4 | tee fab010-native.txt
/tmp/fab010 --resident 24 4 | tee fab010-resident.txt
python examples/fab_127/verify_fab010.py /tmp/fab010 fab010-native.txt native
python examples/fab_127/verify_fab010.py /tmp/fab010 fab010-resident.txt resident
```

Use an authorized isolated Linux loopback environment. The full run retains about 1 GiB including verification data, plus runtime and kernel allocations. It does not modify system routes. Missing or mismatched packets fail rather than fabricating a result. Full address support varies across hosts, so the dedicated hosted run is a separate evidence requirement.

## To Do

1. Map CPU identity, process context, observation Ground and epoch into E-CPU native task/receipt and receiver admission contracts.
2. Load arbitrary bounded admitted programs; generalize SEND and RECV to authenticated routes and typed dependencies.
3. Run a continuously advancing workload with independent observer queries and checkpoint/rejoin. Preserve identity across worker removal; validate epoch fencing and duplicate suppression.
4. Lower verified pure blocks to native kernel/virtual-layer Grounds and select navigation instead of replay when justified. Use retained explicit state for irreducible effects, not an invented global law.
5. Bring the same address semantics to VL-I and VL-64 as host-independent realizers; measure program complexity, memory geometry, latency and concurrent throughput separately.
