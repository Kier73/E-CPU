# Specifications

Index of specification documents. Documents use defined terms from `GLOSSARY.md`.

## Reading order

| Order | Document | Read it for |
|---|---|---|
| 1 | [`../README.md`](../README.md) | What the system is, how to run it, and its architecture |
| 2 | [`GLOSSARY.md`](GLOSSARY.md) | The defined terms relied on across the documentation |
| 3 | [`ARCHITECTURE.md`](ARCHITECTURE.md) | State model, lifting table, capability model, evidence tiers |
| 4 | [`REPLACEMENT_SPEC.md`](REPLACEMENT_SPEC.md) | The replacement target and its acceptance criteria |
| 5 | [`INTEGRATION_SPEC.md`](INTEGRATION_SPEC.md) | Adopted mechanisms and their integration boundaries |
| 6 | [`BOUNDARY_PROCEDURAL_MODEL.md`](BOUNDARY_PROCEDURAL_MODEL.md) | Procedural decision model and generation interface |
| 7 | [`INVARIANTS.md`](INVARIANTS.md) | Machine-checkable invariant registry |
| 8 | [`PLAN.md`](PLAN.md) | Research hypotheses and evaluation procedure |
| 9 | [`BUILDOUT_REQUIREMENTS.md`](BUILDOUT_REQUIREMENTS.md) | Future architectural requirements and engineering milestones |

## Document classes

**Specification.** `ARCHITECTURE.md`, `REPLACEMENT_SPEC.md`, `INTEGRATION_SPEC.md`. Core system design and interfaces.

**Boundary.** `BOUNDARY_PROCEDURAL_MODEL.md`. Procedural decision model boundaries.

**Reference.** `GLOSSARY.md`, `INVARIANTS.md`. Look-up tables and registries consumed by the specifications.

**Procedure & Roadmap.** `PLAN.md`, `BUILDOUT_REQUIREMENTS.md`. Research plan, evaluation procedure, and future buildout requirements.

## Cross-reference integrity

Referenced paths resolve cleanly, checked by:

```sh
python scripts/verify_repo.py --check links
```

## Conformance

The specification set is checked against the implementation by:

```sh
python scripts/verify_invariants.py     # registry entries resolve to code and tests
python scripts/verify_repo.py           # links, secrets, invariants, hygiene
python -m pytest                        # invariants hold at runtime
```
