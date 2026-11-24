# FAB-009 — Virtual parallelization of the complete loopback space

## Address Ground
All 24 variable IPv4 loopback bits are used: 127.A.X.T specifies multiplier A, initial state X, and logical time T (each 0..255). The admitted family is F_A(x) = (A*x+c) mod 256. The selected observation is F_A^T(X). The UDP port selects the current kernel realization, not a new address for each operation. Different seed increments can use the same address space under distinct Grounds.

## Recursive formation
The source is a native one-step cBPF operator. The recognizer reads the increment from a real coordinate, then observes each lane at inputs 0 and 1, recovering its slope and increment. Inputs 17 and 255 independently challenge the candidate. The current compiler accepts the structural family whose slope equals the lane octet and whose increment is shared, not arbitrary unknown laws. The recovered increment (not the supplied seed) forms a new selector. The independent receiver oracle uses the declared seed and sequential recurrence. Initial formation used 1,024 probes; the parameterized revision adds a single observation to recover the shared increment, totaling 1,025. The 167-instruction native selector implements affine composition by repeated squaring, not a replay of T packets.

For (m,b), composition with itself is (m*m, b*(m+1)) mod 256. The eight time bits select the corresponding powers. Result sockets identify 0..255. Four worker processes each host a fixed 256-socket reuseport group and 64 lanes. In batch mode each sends its 64 coordinates before receiving, checking source peer, destination ancillary evidence, result ordinal, per-batch uniqueness, complete lane membership, and empty remaining queue. There is no user-level arithmetic fallback. The verifier advances its separate recurrence once per logical time for each lane.

The Linux broadcast address 127.255.255.255 uses an isolated one-socket length-encoded native filter with a constant 255-byte payload; the other 16,777,215 requests are empty UDP datagrams. Peak sweep socket allocation is 1,030 UDP sockets (four groups of 257 plus the edge group of two), plus four or five epoll descriptors. No per-coordinate allocation. Group membership must remain fixed during a run. This is a controlled loopback-only experiment, not a multi-tenant security contract.

## Local evidence (2026-11-24)
Four processes, one Linux kernel, four-CPU cgroup quota. Both original seed-1 sweeps checked every address: 16,777,216/16,777,216; total state-value checksum 2,143,158,272. Serial requests across four workers: 19.163306 seconds. Queued batches across four workers: 16.626530 seconds (1.009 million observations/s). The first implementation used 1,024 formation probes; both reported durations exclude the formation pass but include worker setup. Batch verification adds explicit uniqueness/empty-queue checks; timing comparisons are observational, not controlled statistical estimates. The parameterized compiler also checked 524,288 observations with recovered increment 193 in 0.534052 s, and 1,026 deterministic samples each for increments 1 and 193 against sequential reference. The hosted cross-check runs the native existing E-CPU lcg_navigate for these same samples.

Virtual parallelism is independent addressability and bounded concurrent requests, not 16 million simultaneously executing physical processors. The sweep enumerates all coordinates for validation; a target observation needs one request and bounded binary composition. The 2,139,095,040 logical transition count for separately replaying every requested history from its initial state is a mathematical comparison, not measured physical work or a speedup against a shared incremental oracle.

## Reproduce
```sh
cc -O3 -Wall -Wextra -Werror examples/fab_127/fab009.c -o /tmp/fab009
/tmp/fab009 4 256 256 0 1 1 > fab009-full.txt
python examples/fab_127/verify_fab009.py /tmp/fab009 fab009-full.txt
/tmp/fab009 4 32 64 0 1 193
```

Arguments: worker count, initial-state count, logical-time count, length encoding (0=path), batch flag, source increment. Linux only; use an isolated authorized local environment. The implementation attaches filters only to its own sockets, uses loopback device binding and does not change system routing/firewall. Missing observations, incorrect values, changed group membership effects or mismatched peer/coordinate fail the run. Hosted verification is tracked by the dedicated workflow.

## To Do
Form heterogeneous lane laws and assign them dynamically by intention. Use Structural Memory to retain admitted law evidence; use E-CPU DAGs to form dependency-aware batches instead of a single affine family. Explore port-scoped contexts and extended logical-time pages, independent worker recovery and epoch-fenced group rebinding, and route-native compositions between physical E-CPU fabrics.
