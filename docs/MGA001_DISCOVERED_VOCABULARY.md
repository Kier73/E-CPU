# MGA-001/F — Intention-discovered action vocabulary

A learned rule combines two admitted disjoint exponent masks a,b into a|b.
By composition its action is T^(a+b) on every initial state. Greedy training
counts co-occurring pairs of atoms, rewrites coordinates, and admits rules
only when forecast savings exceed four modular multiplications (two for
construction and two for independent checking). Search work is separately
metered. The checked radix-2 basis guarantees coverage; each query recipe
is checked for disjoint union exactly equal to the exponent. Restore checks
the basis and all rule coefficients. This is not an optimal addition-chain
solver or proof of physical acceleration.

Architectural reuse: [NCR procedural vocabulary](https://github.com/Kier73/Navigable-Compute/blob/main/navigable_compute/procedural_vocabulary.py)
(qualified rewrite rules); [NCR coalescent fleet](https://github.com/Kier73/Navigable-Compute/blob/main/navigable_compute/coalescent_fleet.py)
(source-scoped contributions, convergence is future work);
[IFS adaptive Ground compiler](https://github.com/Kier73/In-Formation-Space/blob/main/experiments/pnp-ground-navigation/spectral_phase_navigation/adaptive_ground_compiler.py)
(separate strategy selection and source-bound correctness).
The existing E-CPU affine continuation accepts the admitted vocabulary as an
optional source-relative verifier.

Independent JavaScript arithmetic campaign (xorshift32 seed 20261125):
400 training intentions, 1000 held-out structured intentions, 62 rules,
565318 discovery pair visits, 834 distinct held-out coordinates absent from
training, 4000 exact action comparisons over four laws. Structured workload:
11214 binary modular multiplications, 3424 learned (748 preparation,2676
applications), best fixed radix 8:10906. Uniform control: learned 26349,
best radix 64:13418. These include table formation and admission but exclude
discovery and rule visitation from modular multiplication counts; learned
query rule visits 62000 per 1000 queries. The JS campaign is independent of
the committed Python test, which uses a different RNG and is run by CI.
No end-to-end speedup claim. Next: retain measured cost profiles, online
portfolio selection, coalescent contributions and generalized action maps.

Run: python -m unittest discover -s tests -p test_affine_vocabulary.py -v
