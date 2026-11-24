# FAB-011 — Live observation of an independently advancing CPU fleet

## Implementation

`examples/fab_127/fab011.c` extends the FAB-010 experimental model with a live observation Ground. Each 24-bit address is a CPU identity. Its 64-bit atomic state contains a 32-bit register, a 4-bit program counter and a 28-bit instruction clock. An immutable program table assigns CPU i the program i mod program_count. The loader admits up to 16 programs of up to 16 instructions each, with unsigned 32-bit ADD/MUL operands and one terminal JUMP 0. It refuses unsupported instructions, malformed geometry and overflowed operands. This is a bounded affine-loop ISA, not an arbitrary program loader for the full E-CPU ISA. FAB-010's general mailbox/process experiment is complementary, not imported into this compact state layout.

Each worker owns a disjoint range and advances each CPU by one real interpreter instruction per sweep. Atomic acquire/release snapshots preserve register, PC and time together. Workers do not stop for an observer scan. The observer waits for additional execution sweeps between scans to distinguish a scheduling stall from a computational mismatch. Two scans occur in each of two epochs, with a graceful stop/join and changed shard count between epochs. There is no simultaneous competing writer, process crash recovery or durable checkpoint in this experiment. CPU identity, loaded program and current state are retained across the ownership change.

## Direct temporal Ground

For a program of length L, write the prefix map P_r(x)=m_r*x+b_r mod 2^32, and the full-cycle map F(x)=P_L(x). JUMP is identity on the register but advances the instruction clock and sets the PC to zero. At t=qL+r the predicted state is

    register=P_r(F^q(initial(i))), PC=r, clock=t

where initial(i)=(2654435761*i+17) mod 2^32. Composition is (m,b)∘(n,c)=(mn,mc+b) mod 2^32. The program loader builds prefixes and 28 repeated-square powers; navigation uses the set bits of q. No snapshot is assembled from different instruction times, and no global synchronous state is inferred. The clock refuses exhaustion rather than wrapping. The actual interpreter never invokes the navigator to advance a state.

The refined compiler first executes three calibration contexts per program with initial registers 0, 1 and 0xdeadbeef. For every prefix, the first two actual interpreter observations determine m = y(1) - y(0) and b = y(0). The third independently challenges the candidate; all three PC/tick observations and the declared affine prefix are checked. Only these verified observed coefficients form the navigator. The four-program set requires 39 calibration instructions; the alternate set requires 30. This exploits an already admitted affine language, not unconstrained inference from three samples.

Before starting, each loaded program is checked for 4096 sequential instruction states against the formed law. Every live observation checks the entire packed state against the direct law and checks nonregression against the previous observed time. A final pass verifies every CPU and checks that the sum of its clocks equals the exact worker instruction count. A separate Python checker replays 64 unique final samples (including both address extremes) from the loaded source; hosted CI also compares these with the existing E-CPU `lcg_navigate`. The temporal equivalence is exact for the admitted affine language; future symbolic predictions are not physical future observations.

Native sampling uses an empty UDP datagram, kernel-supplied destination IP_PKTINFO and sender checks. It addresses up to 4096 unique CPU identities per epoch via an odd-multiplier permutation, including both ends of the space. It then reads and verifies the same atomic resident state. The full scans are direct resident reads, not 67 million UDP packets. No physical kernel computation of the CPU instruction is asserted here.

## Measured local evidence

Linux, four available CPU quota, 2026-11-24. Initial full run: 1,716,868,411 interpreter instructions. Refined run before adding inter-scan progress coordination: 1,771,394,362 instructions. Both verified 67,108,864 live observations across four complete scans. A progress-coordinated run of C blob 42a4ebd0522d410aefaec68f997832c2e076a55d verified 1,019,215,860 instructions. The final observation-formed C blob 2e1d20ad041a17a717bafee59ebf53eef0d4ef6a then repeated the full run:

| Measurement | Exact final source run |
|---|---:|
| CPU identities | 16,777,216 |
| Loaded programs | 4 |
| Live full-space snapshots | 67,108,864 |
| Native address-triggered samples | 8,192 |
| Final full-space verification | 16,777,216 |
| Resident CPU bytes | 134,217,728 |
| Observer clock bytes | 67,108,864 |
| Epoch 1 workers / instructions | 3 / 704,643,059 |
| Epoch 2 workers / instructions | 4 / 624,951,296 |
| Total instructions | 1,329,594,355 |
| Epoch durations | 1.257083 s / 0.916068 s |
| Final instruction clock range | 58–97 |
| Final sample replays | 64/64 |

All four scans observed every CPU advance relative to its previous scan in this run. Both epochs passed 4096 native samples. The final total exactly equals the sum of CPU clocks. A second loaded program set (including MUL 0 and a noninvertible map) ran 262,144 CPUs, 36,787,575 instructions, 1,048,576 live snapshots and 8192 native samples, with a 3-to-2 worker change and 64 independent final sample replays. A 16-CPU 1-to-3 worker test and an invalid JUMP 1 refusal passed. Instruction counts depend on scheduling and observation duration; they are not a fixed-workload speedup, physical instruction count or CPU-core count.

## Reproduce

```sh
cc -O3 -std=c11 -Wall -Wextra -Werror -pthread examples/fab_127/fab011.c -o /tmp/fab011
/tmp/fab011 examples/fab_127/fab011-programs.txt 24 3 4 native > fab011-full.txt
python examples/fab_127/verify_fab011.py examples/fab_127/fab011-programs.txt fab011-full.txt --native-law
```

Omit `native` for resident-only operation. Full scans are resident in either case. This uses owned loopback sockets only; no host routing changes. A native send refusal is an explicit test failure. Dedicated CI uses full resident scans and a smaller native-sampled run; the 24-bit native sample run was local. The independent verifier uses Python assertions and should be invoked without optimization.

## To Do

- Connect immutable program identity, process context and epoch to native E-CPU admission/receipt and Structural Memory; use existing HeadlessOS instruction and scheduler semantics rather than creating a competing general ISA.
- Add live heterogeneous non-affine/communication instructions with explicit effect history and verified pure-region navigation; retain actual effects instead of inferring them.
- Move ownership between distinct processes or hosts using durable state, generation fencing and recovery; test observer rejoin while a process disappears.
- Give each CPU multiple continuous process contexts and expand observation to arbitrary admitted historical instruction time and non-affine state.
- Compare sparse clock/exception retention with resident snapshots, measuring actual observer and execution cost.
