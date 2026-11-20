# Mainline specification-gate reconciliation — 2026-11-20

This is an evidence-based baseline audit before adding another integration layer.
The source is the **main** push `31bbfca9e8d62059bf598914ce2e1a2587c8c8b4`
and [GitHub Actions verify run 44802895394](https://github.com/Kier73/E-CPU/actions/runs/44802895394),
created 2026-11-20 19:31 UTC. This note does not assert that the verification gate
has passed, nor should a feature-specific green workflow be presented as a
substitute for the main specification matrix.

## Independent failure classes

| Gate | Verified original failure | Action |
| --- | --- | --- |
| Test collection | `numpy` absent in two NumPy-using test modules | Add explicit NumPy dev dependency; install the declared dev extra in the matrix |
| Test collection | `vgi.transitions` absent from VGI checkout pinned at `43289a5` | Advance the explicit dependency commit to `7a3c4a3`, which contains `vgi/transitions.py` and `vgi/partial_attention.py` |
| Invariant registry | 279 unresolved invariant/docstring entries | Existing contract debt; do not bypass the invariant scan |
| Repository conformance | 564 docstring, 279 invariant, 52 link, and 5 credential-pattern findings (900 total) | Keep independent scanner failures visible; triage and repair in follow-up scoped changes |

The five credential-pattern findings are **scanner matches**, not evidence that
credentials were exposed. They require manual review and safe correction. This
document deliberately does not reproduce flagged strings.

The successful package-build job, independently successful feature workflows,
and successful VGI Signal8 verification are real observations; none overrides
the failing main specification matrix.

## Public exports: source/implementation identity

At the audited revision, `mailcpu/__init__.py` has 861 unique imported public
names and 861 entries in `__all__`, with equal sets. This proves a **structural
registry alignment only**. The added `test_public_exports_contract.py`
goes further by comparing each imported implementation object to the publicly
exposed object. It deliberately does not claim behavioral correctness, typed
admission, authority enforcement or source attestation for every symbol.

Behavioral conformance for each new public symbol still requires a specific
fixture with a positive witness, a typed negative/refusal witness and an
implementation-level result check. Avoid registering additional portable
Ground operators until those gates have been exercised through the existing
E-CPU/VGI execution authorities.

## Review protocol

1. Verify Linux/Windows on Python 3.11–3.14 after installing the exact pinned
   VGI commit plus the development/test dependency set.
2. Confirm collection completes and analyze any **test execution** failures separately.
3. Preserve the invariant registry and repository conformance as mandatory
   gates; do not hide or skip failures to make verification green.
4. Compare subsequent public exports with their underlying implementation;
   require a focused positive and negative behavioral test for every *new* export.
5. Do not describe mainline as conformant until the whole matrix and registry
   passes at the same commit.

The VGI pin is a dependency-surface update, not a claim of semantic
compatibility until CI tests exercise it.
