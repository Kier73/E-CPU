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
| 15 | [`VIRTUAL_LAYER_WORKLOAD.md`](VIRTUAL_LAYER_WORKLOAD.md) | Typed portable workload, operator registry, hypervisor and reliable-channel integration boundaries |
| 16 | [`TRANSIT_COMPUTE.md`](TRANSIT_COMPUTE.md) | Receiver-side bounded compute capsules and authenticated transit execution |
| 17 | [`TRANSIT_PATH_STATE.md`](TRANSIT_PATH_STATE.md) | Persistent path state, SIMT and memory backends, recovery, and deterministic orbit scheduling |
| 18 | [`STATE_SPACE_NAVIGATION.md`](STATE_SPACE_NAVIGATION.md) | Symbolic capacity, finite trajectories, and time-budgeted state-space navigation |
| 19 | [`TRANSIT_PATH_MODES.md`](TRANSIT_PATH_MODES.md) | One path switching between RRNS memory, RTT sensing, and bounded processing |
| 20 | [`TRANSIT_PATH_BINDING.md`](TRANSIT_PATH_BINDING.md) | Live session binding for requester RTT, receiver service time, queue state, ACKs, and retries |
| 21 | [`TEMPORAL_CLOCK_FABRIC.md`](TEMPORAL_CLOCK_FABRIC.md) | Process-selected wall, monotonic, causal, scheduler, event, chronon, and chemical temporal domains |
| 22 | [`CONTEXTUAL_PROCESS_NAVIGATION.md`](CONTEXTUAL_PROCESS_NAVIGATION.md) | Context-resolved process addresses, declarative transition logic, bounded navigation, replay witnesses, and readiness contracts |
| 23 | [`FORMAL_NAVIGATION.md`](FORMAL_NAVIGATION.md) | Integer-affine interval analysis, conservative reachability, strong bisimulation, and vector-clock causal dependency graphs |
| 24 | [`NAVIGATION_BRIDGE.md`](NAVIGATION_BRIDGE.md) | Conservative compilation from concrete process descriptions to integer-affine abstract navigation |
| 25 | [`NAVIGATION_COORDINATOR.md`](NAVIGATION_COORDINATOR.md) | Unified formal and concrete navigation, causal and representation gates, and non-authoritative admission proposals |
| 26 | [`NAVIGATION_ADMISSION.md`](NAVIGATION_ADMISSION.md) | Hypervisor-owned live-context revalidation, kernel capability checks, policy arbitration, bounded path grants, and expiry |
| 27 | [`NAVIGATION_EXECUTION.md`](NAVIGATION_EXECUTION.md) | Journal provenance, live grant revalidation, deterministic path replay, atomic host compare-and-swap, durable receipt recovery, and execution receipts 
| 28 | [`NATIVE_VCPU_CONTEXT.md`](NATIVE_VCPU_CONTEXT.md) | Safepoint-only navigation of the native scheduler PC/register file with atomic checkpoint and receipt recovery |

## Document classes

**Specification.** `ARCHITECTURE.md`, `REPLACEMENT_SPEC.md`, `INTEGRATION_SPEC.md`. Core system design and interfaces.

**System profile.** `HYPERVISOR_PROFILE.md`. Operational state, equations, receipts, replay, revisions, and integration surfaces of the hypervisor.

**Boundary.** `BOUNDARY_PROCEDURAL_MODEL.md`. Procedural decision model boundaries.

**Reference.** `GLOSSARY.md`, `INVARIANTS.md`. Look-up tables and registries consumed by the specifications.

**Procedure & Roadmap.** `PLAN.md`, `BUILDOUT_REQUIREMENTS.md`, `ITERATION_2_BUILD_PLAN.md`, `DOGFOODING_AND_EMPIRICAL_LIMITS.md`. Research plan, evaluation procedure, Iteration 2 build plan, and dogfooding report.

**Runtime & Navigation.** `TRANSIT_COMPUTE.md`, `TRANSIT_PATH_STATE.md`, `STATE_SPACE_NAVIGATION.md`, `CONTEXTUAL_PROCESS_NAVIGATION.md`, `FORMAL_NAVIGATION.md`, `NAVIGATION_BRIDGE.md`, `NAVIGATION_COORDINATOR.md`, `NAVIGATION_ADMISSION.md`, `NAVIGATION_EXECUTION.md`, `NATIVE_VCPU_CONTEXT.md`. Native vCPU context commits, bounded transit execution, persistent path state, orbit scheduling, symbolic capacity, contextual resolution, replayable derivation, abstract reachability, process equivalence, causal dependencies, conservative compilation, coordinated navigation plans, hypervisor-owned execution admission, and crash-recoverable state execution.

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
