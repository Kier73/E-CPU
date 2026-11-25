# MGA-001/G — Coalescent action vocabulary

Three independent observers each acquire instructions for a separate
12-bit exponent motif. A packet pins the exact checked binary action
basis and includes dependency masks and affine coefficients. The
receiver unions proof descriptions, sorts by result popcount, and uses
the existing AffineVocabulary checker to validate every rule. A missing
dependency, foreign basis or wrong coefficient refuses the entire
batch. Valid proof unions are associative, commutative and idempotent;
incomplete packets need their dependencies in the same batch or existing
inventory. Alternative valid derivations are retained. No identity or
physical authority is inferred from packet hashes.

The new discovery stage starts from the union rather than binary.
It uses a largest-first disjoint exponent cover (not optimal set
packing) and learns frequent pair compositions of existing actions.
Each resulting rule denotes the action for every input state. This
permits composite instructions spanning separately acquired vocabularies.
The receiver verifies the new packet using the same native checker.
The native affine continuation accepts the coalescent vocabulary.

## Reproduction

    node experiments/mga001_coalescence.js
    python -m unittest discover -s tests -p test_affine_coalescent.py -v

Independent JavaScript campaign retained in experiments/mga001_coalescence.json.
Three 64-intention local batches discover 11 rules each; 96 cross-training
intentions discover 3 new rules from the coalesced vocabulary. Test
1024 distinct unseen coordinates with extra noise bits, four affine laws,
4096 exact action comparisons and all six merge orders. Arithmetic
total includes a single binary basis preparation (500), four operations
per distinct proof rule, and query applications. Independent observers
forming their own bases pay additional preparation; accounting for all
three basis formations instead of one adds 1000 modular multiplications
before transfer/revalidation costs. Pair visits and mask visits are
separate; no wall-time or distributed host claim. Campaign uses a
synthetic complementary workload, not a universal speedup. Python tests
cover dependency refusal, rehashed false coefficients and alternate proofs;
hosted verification status is separate.

Architectural source: NCR-022 coalescent fleet and its qualified proof
inventory; MGA-001/F action learning; IFS cost separation. No external
runtime dependency. Next: measure real operation spans; optimize mask
selection and sparse discovery; run independent authenticated E-CPU
observers with packet exchange, not just simulated independent learners.
