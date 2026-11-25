# MGA-001/J — Symbolic nonlinear switching closure

A source has control c in GF(2)^n, two modular numerical coordinates z,
an ANF guard g over declared parity forms, and two branches (B_b,A_b).
The control update is B_b c and the payload update is affine A_b z.
Close the row span of guard forms under right multiplication by every B_b.
The discovered basis Q admits guard decoder G and branch decoders D_b:
GQ equals the declared guard forms and D_b Q = Q B_b. An independent
checker verifies coefficient identities, independence and ancestry from
guard rows and earlier pullbacks. Ancestry proves inclusion in the least
closed linear row space, while closure proves the reverse inclusion.
Minimality is for preserving the declared parity forms under arbitrary
branch words, not every possible guard-only nonlinear quotient.

The symbolic controller uses s=Qc, branch g(Gs), successor D_b s.
Its actions are lazily indexed, never allocating the 2^rank quotient.
The existing H path compiler/checker is reused, with a separate private
ordered payload realization helper. The full binary control state is
also reconstructed by composing its ordered branch matrices, squaring
the return matrix, and applying the transient and tail. Both full
coordinates are preserved. Formation work depends on n, branch count
and discovered rank; path work depends on visited quotient states, and
may still be exponential in rank. Budgets refuse rather than truncate.
No arbitrary nonlinear control law or chaos claim.

Reproduce:
    node experiments/mga001_symbolic_switching.js
    python -m unittest discover -s tests -p test_symbolic_switching_ground.py -v

Independent executed campaign: 128 control bits and 80 payload bits,
two guard parity forms (AND), 3-dimensional least linear closure from
six pullbacks, at most 8 quotient states, maximum visited path length 6.
128 each direct replay, semigroup and projection comparisons. Witness
controls 2 and 6 have same current guard and parity forms but different
next guard. Exact 10^100+123 full-state jump retained. Synthetic source
is constructed by a dense change of control coordinates, hidden rotation
and shear with compensated low coordinates; the compiler receives only
the declared guard and branch matrices, not the conjugacy. JS campaign
and Python code have independent implementation paths; native CI pending.

Next: factor guard ANF itself instead of assuming parity rows, allow
nonlinear control updates through exact Koopman feature closure, measure
cost and qualify reusable path certificates across observers.
