# MGA-001/H — Joint-residue switching and ordered affine return maps

Let z in (Z/MZ)^2 and r=z mod q, with q dividing M. The exact declared
source specifies a homogeneous affine matrix H_r for each joint residue.
Then r' = H_r(r,1) mod q closes independently of the high coordinates.
The resulting deterministic quotient has q^2 states. Its first repeated
residue identifies a transient of length mu and cycle of length lambda.
Compose the ordered transient P, return map C and cycle prefix R_j.
For t>=mu, t-mu=k lambda+j, the exact state is R_j C^k P z.
For t<mu use the retained ordered prefix. No commutativity between
different layer maps is assumed.

This proves the jump for all lifts of the admitted initial residue.
The return map need not fix the full state. The quotient may be periodic
while the fibre has a very long orbit. General chaotic dynamics or
arbitrary state-dependent switching need not possess a small quotient.
The result is a finite modular construction, not evidence of positive
Lyapunov exponent, topological chaos, or a general nonlinear solver.

Native Python implementation reuses E-CPU affine_orbit matrix multiplication.
Its independent path checker uses images of 0,e1,e2 under the fixed
ordered affine path; those probes are algebraic map probes, not physical
source states with the same residue. The checker reconstructs every prefix
and cycle map, checks the quotient edges and exact source identity, then
navigation squares the certified return map. Each call rechecks its
Ground; one-time qualified reuse is a future optimization. Construction
and verification cost O(q^2) layer compositions/probes; jump uses O(log t)
matrix squares and applications after admission. Matrix dimension is
fixed; coefficient and time bit costs are not constant. The table is
explicit source description, not a learned law.

## Reproduction

    node experiments/mga001_switching_affine.js
    python -m unittest discover -s tests -p test_switching_affine_ground.py -v

Executed independent JS campaign: 36 generated sources (cycle, transient,
random quotient), 648 direct replay comparisons, 648 large-coordinate
semigroup comparisons, 36 certified itineraries, 36 noncommuting layer
examples, 36 non-affinity parallelogram witnesses, 24 smaller-residue
branch-map ambiguities, one rejected path forgery. One 2^80-state example
(q=8, M=2^40) jumps to 10^100+123 using 326 query matrix squares and
independently checks its return map via fixed-path affine probes plus
matrix powering. The JS and Python independent checkers differ; hosted
Python checks pending at publication. See retained JSON.

Related architecture: NCR-007 nonlinear Koopman observer closure,
E-CPU WIRE-001 and affine_orbit, IFS context switching evidence,
VL-I observer cuts. Next: discover a sufficient joint quotient from
declared guard structure, minimize it, reuse return actions across
phases and coalesce exact path certificates; then extend beyond residue
guards to nonlinear conjugacies and exact feature lifts.
