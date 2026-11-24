# ITR-002 — Intention-formed nonlinear realization: proof decoder versus formed processor

## Research question

What is faster from intention to a **verified observation**: derive the computational structure sufficient to answer the intended result directly, or first construct and realize a finite processor? E-CPU already knows how to form and place a processor (`INTENT-001`, `SAB-001`); In-Formation-Space already knows how to construct **independently checked** nonlinear observation decoders (`CIG-017`). This experiment uses those exact implementations rather than copying an inference algorithm or creating a second host scheduler.

**Implementation:** [`mailcpu/inverse_nonlinear_realization.py`](../mailcpu/inverse_nonlinear_realization.py)  
**Actual-source tests:** [`tests/test_inverse_nonlinear_realization.py`](../tests/test_inverse_nonlinear_realization.py)  
**Measured workload:** [`examples/inverse_nonlinear_benchmark.py`](../examples/inverse_nonlinear_benchmark.py)  
**Linux/Windows matrix:** [`.github/workflows/itr002-nonlinear-formation.yml`](../.github/workflows/itr002-nonlinear-formation.yml)

### Given information

`NonlinearIntention(n,C,q,f)` contains only a finite **original CNF** `C(x)`, ordered observation predicates `q(x)`, and requested Boolean predicate `f(x)`. No decoder, program, resolved result or selected execution host is provided. A test-only `SourceObservation(model)` supplies an exact *source-valid witness*, used to qualify the observed code `u=q(model)` and verify the final result. The witness is **not** an argument to either execution handler, and does not cross a bootstrap carrier.

The other inputs are receiver-admitted existing capacity: E-CPU `SubstrateObservation`, `BootstrapPolicy`, `CarrierBinding`, and approved logical interpreter/observer loci. A capability advertisement with no bound handler or local authorization never grants execution. This is a local, authorized SAB-001 realization, **not** an authenticated remote measurement, cryptographic source attestation or execution on an unexamined internet host.

### Two realizations and two independent construction algorithms

**Direct, proof-derived:**

1. Call the **actual** IFS CIG-017 `global_sufficiency.synthesize(n,C,q,f)` and `verify_global_sufficiency.verify` (original source, exact predicates, independent producer/checker).
2. Admit a proof only for `SUFFICIENT` with an **executable** decoder. A source-valid counterexample pair is `INSUFFICIENT`; `UNKNOWN`, verifier rejection or decoder absent cannot authorize execution.
3. Receiver independently checks witness satisfies the original CNF; computes observation code `u=q(x)` using CIG's independent checker. The host handler receives **only** `(source identity,u)`.
4. Existing E-CPU `AdaptiveBootstrap` discovers an admitted `proof.decode.boolean.v1` host and carrier path, executes the proof-derived decoder, and passes the result through an admitted observation locus. The receiver's independent source-witness oracle checks it; `verify_bootstrap_report` checks the full native result.
5. `ReceiverProofMemory` retains verified canonical proof bytes only within one trusted process, keyed by exact source, observation predicates, target and verifier budgets. A warm request skips proof creation/verification but still checks the new source observation and executes on the **current** admitted host. There is no durable or remote proof authority.

**Formed processor, independent baseline:**

1. Independently enumerate **all** `2^n` source assignments (for `n<=16`), using the CIG-017 checker only to test original-CNF satisfaction and compute individual predicates. This route never uses the CIG producer's decoder.
2. Build the exact observation-image table `u → f` from source-valid assignments. If two source-valid states share `u` but differ on `f`, refuse. No artificial value is assigned outside the realized image.
3. Form a native `FiniteObserverLaw` whose states are **realized observation codes**, whose observation field is `f`, and whose sole `read` action is the identity transition. Invoke existing `realize_formed_intention`, which constructs the minimal Moore quotient, selects a permitted host/path, executes and verifies original-source replay through SAB-001. This is a static observation processor; it is **not** a discovered temporal law for source state evolution.
4. Keep all formation, source-image construction, path planning, execution and independent receipt-check costs in the timing. The present baseline explicitly refuses `n>16` or more than 64 realized codes; this does not show that forming processors is generally impossible above those sizes.

Both routes use the **same** source-valid observation, original source, existing resource inventory, local authority allowlist, and native carrier system. The comparison refuses mismatched intention/source/code/result identities. The direct and formed outputs are checked through structurally different algorithms; they are not simply two labels for one interpreter.

## Exact mathematical distinction

CIG-017 asks if the target factors through the observer:

\[
\exists g\;\forall x\models C:\; f(x)=g(q(x)).
\]

A decoder exists iff the paired witness obligation is UNSAT:

\[
C(x)\land C(y)\land(q(x)=q(y))\land(f(x)\ne f(y)).
\]

A verified `UNSAT` proof permits direct evaluation of `g(u)` **on the original source's realized observation image**; a verified SAT pair supplies two indistinguishable original states disagreeing on the intention. A proof may exist without an executable decoder; this experiment admits only the latter for actual execution. The formed baseline, instead, reconstructs the entire finite map `u→f` through exhaustive source enumeration, then forms a quotient processor from that map.

The full comparison cost is:

\[
T_\mathrm{direct}^{\mathrm{cold}}=T_\mathrm{CIG\ proof+audit}+T_\mathrm{source\ qualification}+T_\mathrm{route}+T_\mathrm{native\ execution+check},
\]

\[
T_\mathrm{formed}=T_\mathrm{source\ qualification}+T_\mathrm{image\ enumeration}+T_\mathrm{processor\ formation+route+execution+audit}.
\]

Warm direct calls reuse a **previously independently admitted** proof, not a guessed output. All four execution stages have monotonic wall-clock spans; CI runners also publish a median campaign and detailed per-phase timings. Source-witness acquisition itself is outside both timings and is an already-provisioned controlled test fixture, not an uncharged physical sensor/network read.

## Source workloads and distinguishing tests

- **Two nonlinear gates:** original source encodes `x3=x1 AND x2`, `x5=x3 OR x4`; intention observes `(x1,x2,x4)` and asks for `x5`. CIG-017's real `circuit` route derives a two-gate decoder; the independently formed processor discovers eight realized observation codes, then uses a minimal one-bit two-class Moore quotient. All eight observed inputs are compared.
- **Composed nonlinear chain:** independent input bits and source-encoded alternating AND/OR relations. The compiler receives only ordinary CNF constraints and observation/target predicates. For 7 independent inputs, the 13-variable source admits both routes. At 12 independent inputs, the 23-variable source is eligible for the proof-derived circuit but is outside the finite full-enumeration control. No exponential enumeration is performed in the direct route.
- **Refusals:** actual CIG `INSUFFICIENT` counterexample; `UNKNOWN` width budget; source-state inconsistency; changed original clauses; source-target changes; unauthorized advertised hosts; current host withdrawal; proof-memory mutation; forged output; and mismatched comparison receipts.

## Measurement plan

Run the exact workload through actual CIG-017 and E-CPU on Linux and Windows, Python 3.11 and 3.13. Five full trials per workload/path; compare **median intention-to-verified-result duration**, with phase totals and proof-memory reuse recorded. Publish result JSON in Actions artifacts and repository docs only after observed CI logs are checked. Direct and formed variants may have different costs; no speed advantage is presumed. Repeated CIG proof admission is charged in cold trials; proof construction is **not** charged in warm trials, but the original cold seed cost must be included when discussing amortization.

The next experiment uses CIG-019 shared interpolant proof memory for **multiple** target intentions, E-CPU's ITR-001 measured formation ledger, and live `TransferableExecutionClaimStore` for placement-independent result acceptance. It should compare source-verified incremental proof reuse against complete reformation and account for actual network hops. Until then, this result is a controlled local source-and-fabric experiment.

## CIG-021 extension — No full source witness required as an input

The next path follows directly from the original CIG source-image work. The CIG-021 `source_section.compile_section(n,C,q)` producer and **independent** `verify_source_section.verify_section` can establish, for an admitted source grammar, a total constructive section

\[
 s:\{0,1\}^{|q|}\longrightarrow\{0,1\}^n,
 \qquad C(s(u))\;\wedge\;q(s(u))=u\quad\forall u.
\]

`ReceiverSourceSectionMemory` retains the independently checked section as immutable canonical bytes keyed by source and observer contract. `realize_from_observation_code(goal,u,capacity,proofs,sections)` then:

1. Reuses or constructs and independently checks the actual CIG-021 section certificate.
2. Produces a compatible source witness `s(u)` *internally* and independently checks source satisfaction and `q(s(u))=u`.
3. Reuses or produces the CIG-017 proof of `f=g(q)`, and runs `g(u)` through the existing E-CPU admitted decoder host and path.
4. Uses the source witness only for the **receiver-side independent oracle**; the executable handler and carriers receive the observation code but never the model bits.

Thus the supplied request includes **no model state, decoder, program or selected host**. The resulting code is a **mathematically realizable virtual coordinate**, not a physical sensor reading. The source-section proof makes every declared observation code legal under the original source; it does not authenticate how a real-world sensor obtained a code. Ineligible sources or uncovered clauses refuse rather than invent a section. The added source-section formation and proof-admission time is explicitly included in cold timing; a warm request reuses the exact previously checked section and target decoder.

On the controlled alternating 23-variable nonlinear source, this direct section route is intended to cover all 4096 input observation codes using bounded CIG-017/021 circuit descriptions, while the complete original-state enumeration baseline deliberately refuses `n>16`. This distinction is one of **source-structure-dependent formation cost**, not a general guarantee about every CNF source. Tests compare decoded results with separately constructed original-source witnesses and independently check a forged section-gate table is refused.
