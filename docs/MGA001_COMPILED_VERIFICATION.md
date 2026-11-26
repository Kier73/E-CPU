# MGA-001/E — Amortized exact verification through admitted affine action maps

MGA-001/D rechecks each retained coordinate from the original affine source.
This can erase the benefit of shorter relative continuation. The new
verification Ground compiles the source's transition action, not a set of
previously realized states.

For T(x)=ax+c mod m, maps are pairs (p,q) with composition
(p,q) after (r,s) = (pr,ps+q) mod m. For radix B=2^w and coordinate t with
digits d_j, retain A[j,d]=T^(d B^j). Every row starts with identity; verify
A[j,d+1]=A[j,d] after U_j, where U_0=T and
U_(j+1)=A[j,B-1] after U_j. These equations inductively establish every
entry for every input x, including unseen states. The last row covers only
the remaining bits of the inherited 63-bit coordinate range.

Producer generates rows by composition and advances the base by squaring.
The independent checker uses right composition and the row boundary
instead of squaring. Restored snapshots are checked completely, including
coherently rehashed false coefficients. No unverified arithmetic table is
admitted; an immutable checked object can be reused in one receiver process.
There is no cryptographic proof of historical execution or claim that a
hash authenticates a table.

For t = sum_j d_j B^j, apply only nonzero digit maps to x. This takes one
modular multiplication per nonzero digit (plus an addition/reduction).
No origin exponentiation or trajectory replay occurs for the compiled
source check. The same table supports any initial x for that law; the
checkpoint source context, authority and locus are still pinned by the
native ResultBank contract. MGA-001/D accepts the checked object optionally
for source-relative retention and lookup. Its native independent relative
continuation oracle is unchanged.

## Accounting

The native affine_expected loop costs 2 bit_length(t) + 2 popcount(t) + 1
modular multiplications. The compiled path costs nonzero radix digits.
For w=4 the table has 248 pairs, producer 584 multiplications and checker
494; a fresh restore pays the checker again. The profile counts these
costs plus all query applications and compares against cold. The selector
tries w=1..8 subject to an explicit entry budget, and selects cold if
preparation does not pay back. These are arithmetic counts, not a claim
of lower bit complexity, latency, memory traffic or full fabric speedup.
The table can make reuse worse on small/sparse workloads. SQLite reads,
digesting, route planning, relative checks and dissemination are excluded
from this arithmetic model and must be separately measured.

## Reproduction

    python -m unittest discover -s tests -p test_affine_verification_ground.py -v

Tests compare native independent affine_expected and direct sequential
replay across all supported radices, composite moduli, noninvertible maps,
constant maps, arbitrary states and large coordinates. The integration
test uses the previous native fixture and source-loss scenario with the
compiled verifier. Hosted CI status is separate from the mathematical
derivation.

Next: generalize action maps to finite matrix and recurrence Grounds,
select sparse or dense digit vocabularies from observed intentions, and
measure end-to-end cost including verification, storage and wire traffic.
