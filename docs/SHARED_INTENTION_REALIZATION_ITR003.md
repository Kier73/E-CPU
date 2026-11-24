# ITR-003 — Shared proof formation and intention-directed realization

## Research objective

Measure discovery of computational structure rather than only the execution
of a known processor. ITR-001 measured cold and warm affine formation.
ITR-002 brought CIG-017 nonlinear sufficiency and CIG-021 constructive source
sections into SAB-001's existing host/path selection. ITR-003 admits a
family of nonlinear intentions over a common original source once, then
executes only the dependencies of a requested subset.

The source contract is (n, C, q, ordered targets f_1...f_m). No decoder or
execution host is specified. CIG-019 constructs a shared resolution prefix
over two copies of C with matching q, and a separate suffix for each
target disagreement. Its independent verifier replays all clauses and
reconstructs the compact signed-reference circuit. For each admitted
output i, C(x) implies f_i(x)=g_i(q(x)). An UNKNOWN or INSUFFICIENT output
cannot become an executable intention; independently sufficient siblings
remain usable.

## Implementation

- `mailcpu/shared_intention_realization.py`: SharedIntentionSession,
  evaluate_slice; original source, target order and receiver budget bound
  on admission. Detached proof export, independent replay on restoration.
- `tests/test_shared_intention_realization.py`: original-source checking,
  complete vs selected outputs, mixed sufficiency, forged or changed proof,
  replacement hosts, inert offers, and source-image qualification.
- `examples/shared_intention_benchmark.py`: matched source and target-code
  campaign using the real CIG-019 nonlinear and parity fixtures.

For a selected nonempty set S of output indices, define L(S) as the
transitive gate ancestors of their signed references. Since the checked
circuit is topologically ordered, reverse reachability identifies L(S);
evaluation in ascending gate index realizes exactly the selected outputs.
Constants and input reads need no gate computation. Gate evaluations are
|L(S)| rather than total gate count, with additional traversal and sorting
cost; no wall-time advantage is assumed. The receiver independently
compares every requested bit against a source-valid witness.

```python
from mailcpu.shared_intention_realization import SharedIntentionSession
session = SharedIntentionSession(n, clauses, observations, targets)
result = session.realize_code(code, (0, 2), admitted_capacity)
restored = SharedIntentionSession(
    n, clauses, observations, targets, receipt=session.receipt())
```

The code-only entry uses the actual CIG-021 constructive section. It
proves every observation code has a source model, then constructs a private
receiver witness and independently checks the original source. If the
section cannot be proved, use the explicit source-witness entry, not an
unqualified code. Neither case asserts external sensor authenticity.
Receipts are detached, and current-process proof admission is trusted;
a new session replays the saved proof. SAB-001 revalidates current
inventory/policy and bound handlers and carriers for every realization.
A changed route can preserve the same mathematical Ground and proof digest.
This prototype uses local admitted carriers, not independent physical hosts
or quorum commit.

## Matched measurements

Compare one shared proof to eight separately compiled single-target proofs
using the same CIG-019 producer/verifier. Both routes use E-CPU execution
and CIG-021 section qualification. Include proof discovery, admission, section
formation and validation, host path search, execution and independent checks.
Track bytes and gate evaluations separately; do not equate declared proof
search pairs to machine instructions. Compare selected vs full-family
realization as a distinct query-work comparison. A predeclared target
catalogue is the amortization domain; arbitrary unseen targets require
a new proof or a later prefix-extension construction.

The experiment's proof budget is at most 500000 resolution pairs, 200000
steps and width 32 per CIG prefix/suffix; the receiver independently
checks the admitted proof, not producer telemetry. Limits include 128
targets, an 8 MiB proof and the original CIG source constraints. A larger
or unstructured problem can remain unresolved. No general SAT performance
or unrestricted neural equivalence is inferred.

## Reproduction

With IFS commit 199acff952eee79dc19bd561333c35f1da4d57ba on PYTHONPATH:
```sh
python -m pytest -q tests/test_shared_intention_realization.py
python examples/shared_intention_benchmark.py
```
CI runs actual E-CPU and revision-pinned IFS code on Linux and Windows.
Next experiment: CIG-020 event-directed verified updates of retained gate
state. Bind a source/goal/proof identity and observation-event epoch to
E-CPU's transferable execution claims, test recovery without recomputing
unchanged gates, and charge persistence and proof validation.
