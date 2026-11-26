# MGA-001/D — Persistent starting points for unseen affine intentions

MGA-001/C shares one copyable observation along a native SAB-001 tree. This
build makes every actually reached locus with a receiver-installed ResultBank
eligible to retain the mathematical coordinate for a later intention. No
new storage engine or execution authority is introduced.

For the declared affine law T(x)=ax+c mod m, a retained state x_s=T^s(x_0)
gives x_t=T^(t-s)(x_s) for t>=s by composition. The new query may be a
coordinate never previously realized. Native lcg_navigate evaluates the
relative transition, and affine_expected independently checks it. On
retention and lookup, the bank checks the original source-relative value.
This deliberately pays for source revalidation; it is not a net speedup
claim. The measured relative horizon bit length is a structural proxy,
not the exact multiplication count or total bit complexity.

The receiver explicitly installs a distinct ResultBank per logical locus
and offers known coordinates. The contract binds source law, source
context, locus, receiver authority, verifier and coordinate. A new
ResultBank.lookup operation never invokes a producer on a missing key;
corrupt stored values fail closed. No remote state or hardware retention
is inferred from a local database. Provenance of a real remote checkpoint
requires native authenticated readback and recovery authority.

Planning checks available checkpoints, existing native local operation
grants and shared-observation routes. A placeholder with the same fixed
width canonical state encoding permits route planning without calculating
the desired result. Candidate ordering is lexicographic by declared
quanta (local operator + the existing shortest-hop tree), relative horizon
bit length, number of tree edges, stable locus and start coordinate.
This is optimal only among the enumerated candidate plans for this declared
ordering; it is not a general minimum multicast tree solver. Execute the
selected native local continuation, verify its receipt and independent
relative law, bind the actual value to a new shared plan, and realize the
tree using existing native carriers. Retain verified values only at the
actually realized loci with installed banks, including intermediate nodes.
Publication is not an atomic multi-bank transaction; prior sends and
committed bank entries can survive a subsequent error.

## Experiment

A -> B -> {C,D}. Cold intention t=2^40+17 sends the value over three
logical edges and retains the result at four locally simulated loci.
Reopen banks, remove A from the admitted inventory, then request t+1 at
C,D. Start at B,t; relative horizon one instead of 41 bits and two
logical transmissions instead of the original three. This is a new
observation, not an answer-cache hit. The warm path incurs bank checks,
planning, independent oracle work and new retention; count those before
claiming a runtime benefit.

Tests include a missing offer without production, source/locus/authority
mismatch, coherent database tampering, blocked paths, new coordinates and
reopening banks. Run:

    python -m unittest discover -s tests -p test_affine_shared_continuation.py -v
    python -m pytest tests/test_shared_result_bank.py -q

Next: replace full origin revalidation with independently qualified
compositional certificates, retain a catalogue of portable law fragments
rather than only checkpoints, and bind remote source availability to
native authenticated directory and durable recovery lineage.
