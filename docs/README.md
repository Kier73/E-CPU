# Specifications

Index of normative documents. Every document here is written to
`../docs/STYLE.md` and uses the defined terms in `GLOSSARY.md`.

## Reading order

| Order | Document | Read it for |
|---|---|---|
| 1 | [`../README.md`](../README.md) | What the system is, how to run it, what it does not claim |
| 2 | [`STYLE.md`](STYLE.md) | How everything in this repository is written |
| 3 | [`GLOSSARY.md`](GLOSSARY.md) | The defined terms every other document relies on |
| 4 | [`ARCHITECTURE.md`](ARCHITECTURE.md) | State model, lifting table, capability model, evidence tiers |
| 5 | [`REPLACEMENT_SPEC.md`](REPLACEMENT_SPEC.md) | The replacement claim and its acceptance criteria |
| 6 | [`INTEGRATION_SPEC.md`](INTEGRATION_SPEC.md) | Adopted mechanisms and their integration boundaries |
| 7 | [`BOUNDARY_JEV.md`](BOUNDARY_JEV.md) | External classifier contract and refusal rules |
| 8 | [`BOUNDARY_PROCEDURAL_MODEL.md`](BOUNDARY_PROCEDURAL_MODEL.md) | Procedural model and non-copying boundary |
| 9 | [`INVARIANTS.md`](INVARIANTS.md) | Machine-checkable invariant registry |
| 10 | [`PLAN.md`](PLAN.md) | Research hypotheses and evaluation procedure |

## Document classes

**Specification.** `ARCHITECTURE.md`, `REPLACEMENT_SPEC.md`,
`INTEGRATION_SPEC.md`. States what the system does and what it refuses.

**Boundary.** `BOUNDARY_JEV.md`, `BOUNDARY_PROCEDURAL_MODEL.md`. States where
the system stops relative to material it does not own.

**Reference.** `GLOSSARY.md`, `INVARIANTS.md`. Look-up tables consumed by the
specifications.

**Procedure.** `STYLE.md`, `PLAN.md`, `../AGENTS.md`. States how work is
performed and evaluated.

## Cross-reference integrity

Every referenced path in this directory MUST resolve. The requirement is
enforced by:

```sh
python scripts/verify_repo.py --check links
```

## Conformance

The specification set is checked against the implementation by:

```sh
python scripts/verify_invariants.py     # registry entries resolve to code and tests
python scripts/verify_repo.py           # style, links, boundaries, secrets, hygiene
python -m pytest                        # invariants hold at runtime
```

An invariant listed in `INVARIANTS.md` with no enforcing test is a defect in
the specification, not only in the code.
