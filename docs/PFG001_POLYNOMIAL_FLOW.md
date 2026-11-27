# PFG-001 — Exact observable polynomial flow

Research-only successor to MGA-001/J; no native execution authority. Base main b3392249bc0950c2625307f7a6028959de836d28.

For a fully declared deterministic Boolean ANF map F and scalar observation h, work in R=GF(2)[x_1,...,x_n]/(x_i^2-x_i). Pullback U(f)=f composed with F is linear in R even when F is nonlinear. Generate h,U h,... until the first exact coefficient dependency U^r h=sum c_j U^j h. The first dependency is certified by independent expanded coefficient checks and independence of the r retained polynomials. It implies p(U)h=0 for p(z)=z^r+sum c_j z^j. For t>=0, compute z^t mod p by binary modular polynomial exponentiation, then evaluate the selected basis polynomials at x. The identity holds for every source state by induction, not just training trajectories. The scalar minimal polynomial is intention-specific, not a claim of minimal nonlinear state dimension.

At fixed r, schoolbook navigation costs O(r^2 log(t+1)) bit operations plus polynomial evaluations (and coordinate parsing); the BigInt implementation uses word-parallel operations. Discovery and checking may be exponential in n, degree, or symbolic support. The input source must be available and its semantics independently admitted. Work/product counts do not include all operations (sorting, elimination, allocations, hashing, network, observer acquisition). No latency or full-system speedup claimed.

## Executed campaign

Run:
    node experiments/pfg001_polynomial_flow.js

The checked-in evidence contains the exact report from executing the same JS function. Two maximal LFSRs of widths 11 and 13 and a nonlinear XOR-product accumulator give 25 source bits. The source fixture supplies equations, not a recurrence or cycle. Individual periods independently traversed: 2047 and 8191, coprime; their joint nonzero-control period is 16,766,977. The learned scalar closure has rank 144, degree at most 2 and 9441 retained monomial occurrences. Formation counted 22734 pair products, checker 32175 recursion visits. Huge query counted 65409 modular-multiplication inner iterations, excluding evaluations. This is not an observed runtime benchmark. No joint cycle is enumerated by the compiler.

The independent large-time oracle uses the fact that every pair of nonzero controls occurs once per joint period and each register output has an even number of ones. Hence the accumulator increment over a full joint period is zero. 64 such huge-coordinate comparisons, 192 moderate direct comparisons and 2752 exhaustive small-state/time comparisons passed. The deterministic LCG produces correlated low bits; these are not independent random samples. Coefficient tamper refused. The independently checked ANF identities establish all-state correctness within the declared source; the finite test campaign additionally checks the implementation.

## Negative control: binary increment

For n-bit modular increment F, let h be the highest bit, U the pullback. The Boolean sequence has period 2^n. With m=2^(n-1), (U+I)^m h=U^m h+h=1, and (U+I)^(m+1) h=0. Thus the scalar minimal polynomial is exactly (z+1)^(m+1) (it divides the latter, but no smaller power annihilates h). Rank grows exponentially even though the original problem has a direct addition-and-bit-selection solution. Ranks 3,5,9,17,33,65 were measured for n=2..7; n=8 refused a rank budget of 32. This is a counterexample to general efficient linear observable closure, not to efficient nonlinear navigation.

## Architecture and cost

Reuse the existing observed_orbit_pipeline, StructuralMemoryRegistry, receiver admission, and M3 checkpoint lineage rather than create a new authority. The standalone JS is a bounded fixture, not an untrusted public input parser or complete certificate serialization. Zero-observer rank zero is not implemented by the checker; source and state geometry are fixture-controlled. Current checks share representation and arithmetic conventions, not the coefficient expansion algorithm. No authenticated network receipt, remote execution, or full native CI result is claimed.

The next experiment should select among (1) direct coordinate arithmetic, (2) scalar recurrence, (3) factored polynomial or switching closure, and (4) conventional execution, charging discovery, verification, observation, transfer, and recovery. Use an explicit rank/term/work refusal as input to representation revision. Persist source identity, observer identity, recurrence certificate, state projection and logical coordinate through existing E-CPU contracts. A retained certificate is reusable only when pinned to the same source and intention.

A fixed-horizon jump is not a reachability solver. For SAT or halting-like intentions one still needs an admissible decision horizon and a method for existential detection. Exponential closure or acquisition remains possible. No P vs NP claim.
