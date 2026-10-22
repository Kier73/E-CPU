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
| 6 | [`HYPERVISOR_PROFILE.md`](HYPERVISOR_PROFILE.md) | Deep operational profile of the classifier, policy, time, replay, and revision control plane |
| 7 | [`BOUNDARY_PROCEDURAL_MODEL.md`](BOUNDARY_PROCEDURAL_MODEL.md) | Procedural decision model and generation interface |
| 8 | [`INVARIANTS.md`](INVARIANTS.md) | Machine-checkable invariant registry |
| 9 | [`PLAN.md`](PLAN.md) | Research hypotheses and evaluation procedure |
| 10 | [`BUILDOUT_REQUIREMENTS.md`](BUILDOUT_REQUIREMENTS.md) | Future architectural requirements and engineering milestones |
| 11 | [`COMMUNICATION_SUBSTRATES_AND_INFORMATION_THEORY.md`](COMMUNICATION_SUBSTRATES_AND_INFORMATION_THEORY.md) | Information-theoretic analysis of communication paths as virtual computational substrates |
| 12 | [`CROSS_SYSTEM_SYNTHESIS_TIME_COMPUTATION_MODELS.md`](CROSS_SYSTEM_SYNTHESIS_TIME_COMPUTATION_MODELS.md) | Cross-system synthesis of Virtual Quanta, VL_Logic Compiler, and MailCPU paradigms |
| 13 | [`ITERATION_2_BUILD_PLAN.md`](ITERATION_2_BUILD_PLAN.md) | Comprehensive engineering plan and external resource ingestion map for Iteration 2 |
| 14 | [`DOGFOODING_AND_EMPIRICAL_LIMITS.md`](DOGFOODING_AND_EMPIRICAL_LIMITS.md) | Empirical evaluation, discovered boundaries, ergonomic repairs, and Iteration 3 roadmap |

## Document classes

**Specification.** `ARCHITECTURE.md`, `REPLACEMENT_SPEC.md`, `INTEGRATION_SPEC.md`. Core system design and interfaces.

**System profile.** `HYPERVISOR_PROFILE.md`. Operational state, equations, receipts, replay, revisions, and integration surfaces of the hypervisor.

**Boundary.** `BOUNDARY_PROCEDURAL_MODEL.md`. Procedural decision model boundaries.

**Reference.** `GLOSSARY.md`, `INVARIANTS.md`. Look-up tables and registries consumed by the specifications.

**Procedure & Roadmap.** `PLAN.md`, `BUILDOUT_REQUIREMENTS.md`, `ITERATION_2_BUILD_PLAN.md`, `DOGFOODING_AND_EMPIRICAL_LIMITS.md`. Research plan, evaluation procedure, Iteration 2 build plan, and dogfooding report.

**Research & Theory.** `COMMUNICATION_SUBSTRATES_AND_INFORMATION_THEORY.md`, `CROSS_SYSTEM_SYNTHESIS_TIME_COMPUTATION_MODELS.md`. Substrate information theory, temporal models, and cross-paradigm synthesis.

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
