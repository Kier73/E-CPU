# FAB-012 — Effectful computation with navigable pure regions

## Machine and communication Ground

For every admitted 24-bit machine identity i, the resident realizer retains one atomic 64-bit state: 24-bit logical instruction clock, 8-bit instruction selector, and 32-bit register. Machine identities are logical addresses, not UDP packets in this experiment. Four disjoint arithmetic groups use (a,b) = (5,3), (7,19), (0,123456789), and (2^32-1,100). Register arithmetic is modulo 2^32.

Each round contains 2k pure instructions (alternating MUL a and ADD b), SEND, RECV, BRANCH, selected ADD 37 or XOR 0xa5a5a5a5, and STORE. For N=2^d machines, the peer in round r is i XOR (2^(d-1) OR 2^(r mod (d-1))). This is a changing, reciprocal, fixed-per-round permutation. SEND writes the actual value to an immutable round record, and publishes the new clock via release store. RECV acquires the peer's published clock; if the send is not committed it stalls without advancing. Once admitted it reads the real sent value, retains it in its own record, and XORs it into its register. No predicted send substitutes for a message. STORE writes the actual new version of the machine's memory cell before publishing its next clock. Every round has a fresh 12-byte record (sent, received, stored); initial memory is zero. Each worker is the exclusive writer of its assigned range. The publication frontier makes committed journal fields visible to observers and dependent peers. Records are not recycled during this bounded run.

Workers advance independently by visits over their shards, without a round barrier. The observer waits for each shard's progress frontier before its second and third scans, but does not suspend workers. Each read acquires a single CPU's published snapshot; no global simultaneous snapshot is claimed. This is a shared-memory communication realizer, not native UDP, authentication, durable storage, arbitrary user programs, or E-CPU scheduler integration.

## Navigation and leap realization

F(x)=a*x+b mod 2^32, with composition (a,b)∘(c,d)=(ac,ad+b). For phase p in a pure region, q=floor(p/2), register = F^q(anchor) for even p and a*F^q(anchor) for odd p. The anchor is the initial register or preceding committed STORE. The table of powers is calibrated against literal sequential execution for every prefix of the configured length. Across SEND, RECV, BRANCH, and STORE, the navigator consumes only journal records already visible at the acquired clock. A requested time beyond that clock is refused, even if the machine advances afterward. Memory is the latest committed version, not a later store.

Literal mode publishes every instruction transition. Leap mode publishes the end of the pure region in one transition, advances the logical clock by 2k, and still realizes each of the five following instructions separately. Thus one round requires 2k+5 literal transitions or six leap transitions. Intermediate pure states in leap mode are symbolic reconstructions, not individually published physical states. Both modes have the same logical semantics for this workload. Retaining actual effect records prevents the navigator from fabricating a continuation through an uncommitted message. Branch and memory history are checked independently. The clock measures logical instructions, not elapsed wall time.

## Verification

Every scan reconstructs the packed state and compares it to the actual atomic read. Scan 1 (zero-based) also requests one past coordinate per machine and refuses one coordinate beyond the observed publication frontier. After joining the workers, a separate literal oracle generates each round's sends from the independently maintained previous anchors, verifies every receive against the oracle peer's send, recomputes every store, and checks all final machine states. It does not use the leap implementation. A nonchronological full-space historical sweep queries one selected time per CPU and checks register, instruction selector and memory against separate prefix replay. It is not an exhaustive sweep of the machine-time cross-product. Report samples retain each selected machine's complete effect chain; the independent Python checker verifies counts, chains, sampled peer links, and agreement of both modes; hosted CI additionally invokes the existing mailcpu.law_certifier.lcg_navigate on sample prefixes. Tamper mode modifies a committed receive and must fail the independent oracle.

## Local evidence (2026-11-24)

Exact C source blob 6b771040789d8b04530694658aa256fdfcd77d62. Four worker threads, one Linux process.

| Metric | Literal, 24-bit | Leap, 24-bit |
|---|---:|---:|
| CPU identities | 16,777,216 | 16,777,216 |
| Logical instructions | 1,056,964,608 | 1,056,964,608 |
| Interpreter transitions | 1,056,964,608 | 301,989,888 |
| Pure-region leaps | 0 | 50,331,648 |
| Sends / receives / stores (each) | 50,331,648 | 50,331,648 |
| Three full observer scans | 50,331,648 | 50,331,648 |
| Snapshots of noninitial, nonterminal CPU states | 47,460,055 | 30,626,547 |
| Past queries during observer scan | 16,777,216 | 16,777,216 |
| Beyond-publication refusals | 16,777,216 | 16,777,216 |
| Post-run historical queries | 16,777,216 | 16,777,216 |
| Execution + observer seconds | 6.621560 | 2.896764 |
| Independent full oracle seconds | 1.806135 | 1.740075 |
| Post-run history seconds | 1.061456 | 1.042827 |

Both modes: final checksum 38673967703130112; historical checksum 28313253773574144; all individual comparisons pass. State 128 MiB; three-round journal 576 MiB; independent oracle adds two 64 MiB temporary arrays. A separate longer region test (65,536 CPUs, 2 rounds, 2048 pure instructions per round) compared 269,090,816 literal transitions to 786,432 leap transitions, with 131,072 real sends, receives and stores in each mode. Execution+observer times 1.326053 and 0.063712 s, respectively; full oracle 0.242801 and 0.254449 s, post-run history 0.057984 and 0.059586 s. Final and history checksums 140327018659840 and 106800904958522. Timings are individual runs, not controlled throughput estimates; observer duration and wait stalls vary. The long leap run can finish before later scans: counts explicitly distinguish nonterminal from terminal snapshots.

Other local controls: 4,096 machines with 1, 3 and 16 workers, 16-machine one-round geometry, and a modified receive refused. Full-scale literal/leap samples independently checked by Python. The journal is resident and grows linearly with the number of effectful rounds.

## Reproduce

```sh
cc -O3 -std=c11 -Wall -Wextra -Werror -pthread examples/fab_127/fab012.c -o /tmp/fab012
/tmp/fab012 24 4 3 8 > fab012-literal.txt
/tmp/fab012 24 4 3 8 leap > fab012-leap.txt
python examples/fab_127/verify_fab012.py fab012-literal.txt fab012-leap.txt --native-law
/tmp/fab012 16 4 2 1024 leap
```

Arguments: address bits, worker count, rounds, pure MUL/ADD pairs per round, optional leap or tamper. Use an authorized Linux environment with sufficient resident memory. No network configuration changes, no external requests. The Python checker uses assertions, so run without optimization.

## To Do

- Replace the fixed round workload with admitted E-CPU instruction streams and native DAG readiness; classify effect boundaries from real program contracts, not only a hard-coded grammar.
- Retain effect witnesses through Structural Memory and native reliable channel receipts. Add explicit generation, ownership and independent crash recovery rather than relying on a single process.
- Move from symmetric peer pairs to general dependency graphs and independent process contexts; verify stalled, duplicated, missing, reordered and retried effects under native admission.
- Compact historical anchors by admitted equivalence while preserving independently observed effect identity, version and temporal addressability; benchmark bounded retention.
- Form and verify pure-region summaries recursively, including conditional and non-affine laws, and select leap versus literal realization from cost and observation requirements.
