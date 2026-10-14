# Operating Procedure for Automated Contributors

This document is the contract between this repository and any agent modifying
it. It is normative. An agent that follows it can produce a change that passes
every check without human review; an agent that does not follow it will produce
a change that fails review.

## 1. Orientation

Read in this order before changing anything:

1. `docs/STYLE.md` — how this repository is written. Read in full. It is not a
   preference document; `scripts/verify_repo.py` enforces clauses 3, 4, and 9.
2. `docs/GLOSSARY.md` — the defined terms. Use them; do not invent synonyms.
3. `docs/INVARIANTS.md` — what must remain true, and which test enforces each.
4. The specification governing the subsystem being changed, from
   `docs/README.md`.

## 2. Repository model

```text
mailcpu/     importable package. Behaviour lives here.
tests/       every invariant has an enforcing test here.
scripts/     verifiers and the golden-trace recorder.
docs/        normative specifications. No behaviour lives here.
examples/    assembly source fixtures.
_dev/        private, gitignored, never referenced from tracked files.
```

Two facts constrain all work:

- **`docs/` describes; `mailcpu/` implements.** A change to behaviour requires a
  change to the specification, in the same commit, or the change is incomplete.
- **`_dev/` is not part of the repository.** It holds the build log and an
  un-distributable reference bundle. `scripts/verify_repo.py --check boundaries`
  fails if any tracked file references it.

## 3. Before you change code

Run the full gate and confirm it is green:

```sh
python -m pytest
python scripts/verify_repo.py
```

A change is not started from a red baseline. If the baseline is red, report it
rather than absorbing it into an unrelated change.

## 4. Changing behaviour

### 4.1 Sequence

1. Locate the governing invariant in `docs/INVARIANTS.md`.
2. Locate the specification clause the change implements or narrows.
3. Make the code change.
4. Add or extend the enforcing test. A new behaviour with no test is not
   complete.
5. Update `docs/INVARIANTS.md` if an invariant was added, narrowed, or withdrawn.
6. Update the specification clause. Change the obligation, not the prose around it.
7. Re-run the gate.

### 4.2 Code conventions

These are enforced. Read `docs/STYLE.md` clause 7 for the reasoning.

| Convention | Rule |
|---|---|
| Module docstring | One sentence, present tense, responsibility only. Never history or provenance. |
| Class docstring | One sentence stating what the type represents. |
| Function docstring | One sentence stating the contract. |
| `Mathematics: ` prefix | Applied to a docstring stating an invariant, and to nothing else. Never on an inline comment. |
| Inline comment | No prefix. States a constraint, rationale, or boundary the code cannot express. Never restates the code. |
| Public API | Every name in `__all__` is importable from `mailcpu`. Every public name is in `__all__`. |
| Errors | One domain error per module. No builtin is shadowed at the package root. |

### 4.3 Invariants are not negotiable

An invariant in `docs/INVARIANTS.md` is discharged by an executing test. Where a
change appears to require breaking one:

1. Stop. Do not edit the test to accommodate the change.
2. Determine whether the specification clause or the invariant is wrong.
3. If the invariant is wrong, change the specification first, mark the invariant
   `Withdrawn` with the clause that withdrew it, and state the reasoning in the
   commit message.
4. If the invariant is right, the change is wrong.

### 4.4 Determinism

Every subsystem is deterministic. A change MUST NOT introduce dependence on:

- wall-clock time or host scheduler time;
- thread or process identity;
- iteration order of an unordered container;
- `PYTHONHASHSEED`;
- address-space layout;
- the host filesystem outside `tmp_path`;
- any network resource.

`docs/ARCHITECTURE.md` clause 6 governs evidence tiers. A new network or
transport surface MUST report a tier, and a surface with no substrate MUST be
reported as a non-goal rather than assigned an unearned tier.

### 4.5 Fail closed

A new operation whose preconditions are unmet MUST raise a typed refusal. It
MUST NOT return a partial result, a default, or an empty success. Where a
`README.md` clause 7 refusal already applies, the new surface inherits it.

## 5. Changing documentation

Documentation is specification, not commentary.

- Use the structure in `docs/STYLE.md` clause 5: numbered clauses, one
  obligation per clause, stable numbering.
- Use the status language in clause 6: **evidence tier** for working substrates,
  version scope for version-specific behaviour. Temporal narrative is
  prohibited.
- An obligation is written as an obligation. `The differential corpus MUST
  include blocking WAIT cases.` is a specification. `The test suite covers
  blocking waits.` is not.
- Never renumber a clause to improve flow. Mark a retired clause `Withdrawn`.
- Every referenced path is repository-relative with forward slashes and MUST
  resolve.

## 6. Adding an invariant

An invariant is added to `docs/INVARIANTS.md` when a specification clause states
an obligation that no existing entry enforces.

Required fields: `ID`, `Statement`, `Establishes`, `Enforced by`, `Required by`.

**REQUIRED** `Enforced by` names a specific test node id, for example
`` `tests/test_headless.py::test_exec_validates_before_commit` ``, not a test
module. `scripts/verify_invariants.py` rejects an entry whose target does not
resolve.

**REQUIRED** `ID` is never reused. A retired invariant is marked `Withdrawn`.

## 7. What must never be committed

- Anything under `_dev/`.
- Generated artifacts: `*.mcpu.json`, `*.mcp.json`, `*.mtrj`, `*.mtrj.idx`.
  These are reproducible from committed fixtures.
- Vendored third-party source whose redistribution rights are unestablished.
- Absolute filesystem paths, operator names, or hostnames.
- Credentials. A credential in a tracked file is a security incident: rotate it
  before staging.
- Development narrative. The chronological build log belongs in `_dev/BUILD_LOG.md`
  and is not distributed.

## 8. Verification gate

A change is complete when all of the following hold:

```sh
python -m pytest -q                        # 0 failures
python scripts/verify_invariants.py        # 0 unresolved registry entries
python scripts/verify_repo.py              # 0 findings across all 7 checks
```

Individual checks:

| Command | Checks |
|---|---|
| `verify_repo.py --check prose` | Prohibited vocabulary and rhetorical qualifiers |
| `verify_repo.py --check docstrings` | Docstring presence, `Mathematics:` prefix placement |
| `verify_repo.py --check links` | Every referenced path resolves |
| `verify_repo.py --check boundaries` | No tracked file references `_dev/` |
| `verify_repo.py --check secrets` | Credentials and environment leakage |
| `verify_repo.py --check invariants` | Registry entries resolve |
| `verify_repo.py --check hygiene` | No generated artifact is tracked |

## 9. Common failure modes

| Symptom | Cause | Resolution |
|---|---|---|
| `AssemblyError is not defined` | An exception type named in a `except` tuple is not imported. | Import it in the module. |
| Invariant registry reports an unresolved entry | A test or module was renamed. | Update the registry to the new node id, or restore the name. |
| `verify_repo --check links` fails on a module name | An external identifier was written with a file extension. | Drop the extension; external identifiers are not repository paths. |
| Prose check fires on a legitimate term | A required term is on a prohibited list. | Rewrite the sentence, or add a scoped exemption to `EXEMPT` in `scripts/verify_repo.py` with a reason. Never disable the check. |
| `verify_repo --check secrets` fires on `/home/x` in a test | A virtual filesystem path, not a host path. | The rule is prose-only by design. Rewrite if the finding is in documentation. |
| Golden trace test fails after a legitimate change | `tests/golden_traces.json` is stale. | Regenerate with `python scripts/record_golden.py` and justify the change in the commit message. |

## 10. Reporting

When reporting work:

- State which invariants were touched and which were proven unaffected.
- State the specification clauses changed.
- Paste the gate output. A report of "tests pass" without output is not a
  verification.
- Where a check was disabled or exempted, state why. An unexplained exemption is
  a defect.
