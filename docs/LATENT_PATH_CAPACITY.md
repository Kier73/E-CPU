# CAPACITY-001 — Computational capacity precedes E-CPU recognition

## Architectural proposition

The E-CPU is **not a piece of software that first has to arrive at a machine** for that machine, signal, channel, queue, memory or other information relation to become mathematically interesting. The capacity to host a particular computational relation can already exist within a state-space and its transitions **before the relation is named, observed or organized as E-CPU**.

An E-CPU Ground can describe and navigate part of that already-available structure. The observer-host does not require prior knowledge of E-CPU's name or a copy of a MailCPU runtime. Where an information relationship can receive, distinguish, retain or transform state under a definable contract, E-CPU can investigate whether that relationship is sufficient for a requested operation. Multiple partial relationships can compose into an addressable path.

The strongest form of this proposition is an **architectural research hypothesis** about how broad that realizable capacity is, not a proved statement that arbitrary hosts execute arbitrary E-CPU operations. A locus does not automatically gain permission or semantics when we describe it.

> **Capacity precedes recognition. Recognition makes a part of capacity addressable; admission makes a justified part operational.**

This reframes the foundational [The Internet Is the Computer](THE_INTERNET_IS_THE_COMPUTER.md) proposition. Neither conventional processors nor direct optical hardware experiments are prerequisites for exploring state-space and in-transit computational capacity. They are some of the possible realizers and sources of observations.

## Capacity is not throughput and not a finite trace

E-CPU's [State-Space Capacity and Navigation](STATE_SPACE_NAVIGATION.md) already distinguishes:

- \(\Omega_D\): all states denoted by a finite description;
- \(\tau_B\): a finite path or trajectory actually traversed;
- \(C_B\): the retained, verified, actionable portion of a trace within the observer's budget.

The [Computational State-Space Architecture](COMPUTATIONAL_STATE_SPACE_ARCHITECTURE.md) distinguishes the symbolic capacity \(\Sigma_G\), an admitted path \(\pi\), and a selected observation \(o\). These uses of *capacity* should not be collapsed into memory bytes per second, number of physical cores, the number of virtual hosts, or an experimentally traversed state count.

For an information-bearing structure \(S\) with transition relation \(R_S\), define *latent realizable capacity* relative to a representation language \(\mathcal L\) and an admissible interface family \(\mathcal E, \mathcal O\) as a **conceptual** set of transformations that can be formed by existing transitions:

\[
\operatorname{Cap}_{\mathcal L}(S)
=\{(G,T)\mid \text{there is an admissible representation and observation of}\ R_S
\text{ realizing }T\text{ on the declared domain of }G\}.
\]

This is not a computable universal inventory. We normally possess only an observer-relative candidate or a bounded proof about part of it. Encoding/decoding costs and authority must be accounted for so that we cannot trivially attribute all computation to a passive path while secretly calculating the answer in a decoder.

A practical recognition pipeline distinguishes:

1. **Pre-existing capacity:** a state or path has a relation, whether or not E-CPU has encountered it.
2. **Candidate description:** finite observations suggest a Ground and operator family; ignorance is not absence.
3. **Verified relation:** a proof or exhaustive finite-domain check supports an exact relation, at a stated scope, without materializing its full time orbit.
4. **Addressable navigation:** a known Ground supports asking directly for a logical coordinate, projection or target state.
5. **Operational admission:** the receiver's existing authority, provenance, budget and retention mechanisms decide whether a concrete effect may be accepted.

Step 5 does not create step 1. Steps 2–4 do not themselves confer step 5.

## In-transit state is a computational state-space

From [State-Space Capacity and Navigation](STATE_SPACE_NAVIGATION.md), a communication architecture with local information states \(S_v\) and channel states/queues \(Q_e\) has a composed state-space:

\[
S_{\mathrm{network}}=\left(\prod_{v\in V}S_v\right)\times
\left(\prod_{e\in E}Q_e\right).
\]

Messages and state references can move through this architecture. A queue offers a retention relation, a path can supply an observable ordering or temporal relation, and an already-present software or hardware transformer can implement a mathematical operator. The existence of these relations does not depend on any locus having installed E-CPU. The **composition** of the relations may offer computational capacity absent from any single endpoint.

A useful discovery question is not initially "where do I install the E-CPU?" but "which transitions, projections and lawful continuations are already available in this information space, and how should they be described as a Ground?"

Existing E-CPU mechanisms relevant to this question include `TransitPathState` (switchable retained memory, sensing, integer operations), `TransitPathSessionBinding` (observed queue/RTT/ACK state), `ObserverPathStage` and `VerifiedObserverPath` (typed path evidence), `SubstrateObservation` (candidate resource/channel relationships), `law_certifier` (generative law recovery and logarithmic coordinate navigation), `VirtualGround`/`StructuralMemory` (interpretation and reusable addressability), and the receiver-controlled Virtual Layer and Hypervisor. These are parts of one architecture, not parallel schedulers to replace.

Relevant independent demonstrations in In-Formation-Space: `experiments/passive-orbit-cache/` shows that available information and result addressability can survive changed holders or routes without requiring the holders to run a computation; `experiments/convergent-ground-fabric/` explores heterogeneous actual communication transports and reconstructed operations. VGI's geometry-first research shows that a hidden algebraic representation can be discovered, independently verified, and reused.

## Executable experiment: two paths unaware of E-CPU

File: `mailcpu/latent_path_capacity.py` (tests in `tests/test_latent_path_capacity.py`). The test fixture supplies two pre-existing **opaque** information paths. Neither imports MailCPU, receives E-CPU code, or advertises E-CPU endpoints. A caller sees only each path's `transmit(x)` result.

One path happens to perform two stages (all arithmetic modulo 101):

\[
u=3x+5,\qquad y=7u+11.
\]

Another performs different internal stages:

\[
v=x,\qquad y=21v+46.
\]

Both have the same externally realized relation:

\[
T(x)=(21x+46)\bmod 101.
\]

The recognition procedure observes all 101 possible inputs in the declared finite Ground. It derives the affine candidate from observations of 0 and 1, checks the candidate against **all** 101 outputs, and refuses the Ground if any input contradicts the proposed relation. An adversarial path deviating only at input 88 is rejected. The probe budget is explicit; a partial fit is not assigned the same verification grade.

The two paths yield the **same mathematical Ground digest** and distinct path-evidence digests. With the relation certified for this modeled snapshot, navigation uses E-CPU's existing `law_certifier.lcg_navigate`:

\[
T^t(x_0)=a^t x_0+b\sum_{k=0}^{t-1}a^k\pmod{m}.
\]

A query at \(t=10^{30}+11\) returns a mathematical state without sending \(10^{30}\) physical frames or generating an intermediate trajectory. A separate binary-composition oracle and short direct iterations verify the implementation. Re-observation checks that a currently accessible relation still agrees with the certificate. Exact-snapshot proofs are **not** claims about all future physical behavior.

The fixture tests a **finite, software-defined pre-existing relation**, not the range of capacities available on the public internet. It is a structural test, and its most important negative control is recognizing a false or incomplete law and refusing navigability.

## Research frontier

1. **Capacity discovery over a path**, not a catalog of preinstalled `cpu/gpu` substrates. Observe existing causal/operational relations, then choose a Ground that can represent their composition.
2. **Virtual hosting without prior E-CPU awareness.** Qualify only the specific information operation a locus can provide; don't demand a complete VM or an E-CPU interpreter at every locus.
3. **Recognize representations and state invariants.** Bring VGI's structural basis discovery and exact proof checking to descriptions of path-state transitions. Recover a usable basis once, then reuse it for many observations.
4. **Exploit time navigation.** A requested state or result may be reached through verified symbolic composition instead of physical repetition of every intermediate path state.
5. **Separate realization from proof.** Keep the actual path state, mathematical description, verified observations, authorized effects, and recoverable semantic identity as distinct, connected records.
6. **Broaden the capacity model.** Extend beyond affine modular relations: partial observations and unknown states, non-invertible actions, AND/OR causal transitions, conditional and stateful hosts, delay/queue relations, type-changing paths, and compositions whose useful law exists only at the network level.

The objective is to make the network's **existing information relationships** accessible to E-CPU's general navigator, including cases where those relationships were never installed as software intended for E-CPU.

## Reproduce and claim scope

```shell
python -m unittest discover -s tests -p 'test_latent_path_capacity.py' -v
python -m examples.run_latent_path_capacity
```

The local isolated compatibility harness substitutes only E-CPU's `law_certifier.lcg_navigate` and has **not** run the full E-CPU package. Full runtime CI should run the same tests against E-CPU's native certifier. Whole-domain equality is exact **inside the finite declared snapshot**; an opaque host can still be dishonest, ephemeral, or outside local authority. Content digests do not authenticate an unknown host, and no permission can be inferred merely from pre-existing capacity.