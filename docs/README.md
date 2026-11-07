# Specifications

Index of specification documents. Documents use defined terms from `GLOSSARY.md`.

## Reading order

| Order | Document | Read it for |
|---|---|---|
| 1 | [`../README.md`](../README.md) | What the system is, how to run it, and its architecture |
| 2 | [`GLOSSARY.md`](GLOSSARY.md) | The defined terms relied on across the documentation |
| 3 | [`ARCHITECTURE.md`](ARCHITECTURE.md) | State model, lifting table, capability model, evidence tiers |
| 4 | [`SEMANTIC_TRANSLATION.md`](SEMANTIC_TRANSLATION.md) | Representation identities, observable equivalence, context, resource, authority, and replay obligations |
| 5 | [`REPLACEMENT_SPEC.md`](REPLACEMENT_SPEC.md) | The replacement target and its acceptance criteria |
| 6 | [`INTEGRATION_SPEC.md`](INTEGRATION_SPEC.md) | Adopted mechanisms and their integration boundaries |
| 7 | [`HYPERVISOR_PROFILE.md`](HYPERVISOR_PROFILE.md) | Deep operational profile of the classifier, policy, time, replay, and revision control plane |
| 8 | [`BOUNDARY_PROCEDURAL_MODEL.md`](BOUNDARY_PROCEDURAL_MODEL.md) | Procedural decision model and generation interface |
| 9 | [`INVARIANTS.md`](INVARIANTS.md) | Machine-checkable invariant registry |
| 10 | [`PLAN.md`](PLAN.md) | Research hypotheses and evaluation procedure |
| 11 | [`BUILDOUT_REQUIREMENTS.md`](BUILDOUT_REQUIREMENTS.md) | Future architectural requirements and engineering milestones |
| 12 | [`COMMUNICATION_SUBSTRATES_AND_INFORMATION_THEORY.md`](COMMUNICATION_SUBSTRATES_AND_INFORMATION_THEORY.md) | Information-theoretic analysis of communication paths as virtual computational substrates |
| 13 | [`CROSS_SYSTEM_SYNTHESIS_TIME_COMPUTATION_MODELS.md`](CROSS_SYSTEM_SYNTHESIS_TIME_COMPUTATION_MODELS.md) | Cross-system synthesis of Virtual Quanta, VL_Logic Compiler, and MailCPU paradigms |
| 14 | [`ITERATION_2_BUILD_PLAN.md`](ITERATION_2_BUILD_PLAN.md) | Comprehensive engineering plan and external resource ingestion map for Iteration 2 |
| 15 | [`DOGFOODING_AND_EMPIRICAL_LIMITS.md`](DOGFOODING_AND_EMPIRICAL_LIMITS.md) | Empirical evaluation, discovered boundaries, ergonomic repairs, and Iteration 3 roadmap |
| 16 | [`VIRTUAL_LAYER_WORKLOAD.md`](VIRTUAL_LAYER_WORKLOAD.md) | Typed portable workload, node-local operator registry, digest-pinned structural-memory inputs, and hypervisor/reliable-channel integration |
| 17 | [`TRANSIT_COMPUTE.md`](TRANSIT_COMPUTE.md) | Receiver-side bounded compute capsules and authenticated transit execution |
| 18 | [`TRANSIT_PATH_STATE.md`](TRANSIT_PATH_STATE.md) | Persistent path state, SIMT, private-memory and structural-memory backends, evidence-bearing coordinate reads, recovery, and deterministic orbit scheduling |
| 19 | [`STATE_SPACE_NAVIGATION.md`](STATE_SPACE_NAVIGATION.md) | Symbolic capacity, finite trajectories, and time-budgeted state-space navigation |
| 20 | [`TRANSIT_PATH_MODES.md`](TRANSIT_PATH_MODES.md) | One path switching between RRNS memory, RTT sensing, and bounded processing |
| 21 | [`TRANSIT_PATH_BINDING.md`](TRANSIT_PATH_BINDING.md) | Live session binding for requester RTT, receiver service time, queue state, ACKs, and retries |
| 22 | [`TEMPORAL_CLOCK_FABRIC.md`](TEMPORAL_CLOCK_FABRIC.md) | Process-selected wall, monotonic, causal, scheduler, event, chronon, and chemical temporal domains |
| 23 | [`CONTEXTUAL_PROCESS_NAVIGATION.md`](CONTEXTUAL_PROCESS_NAVIGATION.md) | Context-resolved process addresses, declarative transition logic, bounded navigation, replay witnesses, and readiness contracts |
| 24 | [`FORMAL_NAVIGATION.md`](FORMAL_NAVIGATION.md) | Integer-affine interval analysis, conservative reachability, strong bisimulation, and vector-clock causal dependency graphs |
| 25 | [`NAVIGATION_BRIDGE.md`](NAVIGATION_BRIDGE.md) | Conservative compilation from concrete process descriptions to integer-affine abstract navigation |
| 26 | [`NAVIGATION_COORDINATOR.md`](NAVIGATION_COORDINATOR.md) | Unified formal and concrete navigation, causal and representation gates, and non-authoritative admission proposals |
| 27 | [`NAVIGATION_ADMISSION.md`](NAVIGATION_ADMISSION.md) | Hypervisor-owned live-context revalidation, kernel capability checks, policy arbitration, bounded path grants, and expiry |
| 28 | [`NAVIGATION_EXECUTION.md`](NAVIGATION_EXECUTION.md) | Journal provenance, live grant revalidation, deterministic path replay, atomic host compare-and-swap, durable receipt recovery, and execution receipts 
| 29 | [`NATIVE_VCPU_CONTEXT.md`](NATIVE_VCPU_CONTEXT.md) | Safepoint-only navigation of the native scheduler PC/register file with atomic checkpoint and receipt recovery |
| 30 | [`STRUCTURAL_MEMORY.md`](STRUCTURAL_MEMORY.md) | Verified generator specifications, evidence certificates, context-bound reads, VFS file providers, demand-paged structural-memory pages, COW, revision admission, and checkpoint/journal persistence |
| 31 | [`ARCHITECTURAL_EMERGENCE.md`](ARCHITECTURAL_EMERGENCE.md) | Present capabilities, current build boundaries, and testable possibilities created by architectural composition |
| 32 | [`EVIDENCE_PATH_RESOLVER.md`](EVIDENCE_PATH_RESOLVER.md) | Evidence-indexed representation routes, multidimensional resource costs, receiver-local capability filtering, and non-authoritative path proposals |
| 33 | [`NAVIGABLE_COMPUTATION_EXPERIMENT.md`](NAVIGABLE_COMPUTATION_EXPERIMENT.md) | End-to-end Structural Memory to Transit CPU composition, evidence-backed representation routing, replay, and measured boundaries |
| 34 | [NAVIGABLE_COMPUTATION_RECOVERY.md](NAVIGABLE_COMPUTATION_RECOVERY.md) | Integrity-bound recovery of receiver state, both channel endpoints, evidence route catalogue, and semantic retry identity |
| 35 | [NAVIGABLE_COMPUTATION_DAG.md](NAVIGABLE_COMPUTATION_DAG.md) | Persistent computation DAGs, predecessor-gated dispatch, independent Transit branches, monotonic operation revision, and dependency-guarded joins |
| 36 | [REPEATED_JOINT_PROCESS_RECOVERY.md](REPEATED_JOINT_PROCESS_RECOVERY.md) | Two consecutive hard-kill/restart cycles for independent requester and receiver checkpoints while one committed operation remains unpublished |
| 37 | [PROCESS_CRASH_BOUNDARIES.md](PROCESS_CRASH_BOUNDARIES.md) | Independent requester and receiver process termination at all four Transit execution/publication/acknowledgement cuts |
| 38 | [RECOVERY_LINEAGE.md](RECOVERY_LINEAGE.md) | Quorum-anchored checkpoint generations, independent requester/receiver/backend content identities, and rollback rejection |
| 39 | [`RECOVERY_BUNDLE.md`](RECOVERY_BUNDLE.md) | Immutable endpoint checkpoint bundles, durable capture ordering, and quorum-gated runtime restoration |
| 40 | [`RECOVERY_LINEAGE_PROCESSES.md`](RECOVERY_LINEAGE_PROCESSES.md) | Independent authority processes, reliable seed-quorum transport, and restart-safe prepare/commit/read quorum recovery |
| 41 | [`RECOVERY_LINEAGE_DEPLOYMENT.md`](RECOVERY_LINEAGE_DEPLOYMENT.md) | Fixed-membership topology validation, placement-node/failure-domain declarations, authority endpoints, and production deployment limits |
| 42 | [`COMMUNICATION_HOST_MODEL.md`](COMMUNICATION_HOST_MODEL.md) | Normative definition of host as a logical operational locus, identity versus placement, composable roles, and path-hosting |
| 43 | [`EGPU_NAVIGABLE_FABRIC.md`](EGPU_NAVIGABLE_FABRIC.md) | Navigable E-GPU method graph, SIMT/vector/reduction/workgroup methods, route receipts, and implementation limits |
| 44 | [`WORKGROUP_SHARED_MEMORY.md`](WORKGROUP_SHARED_MEMORY.md) | Workgroup-scoped shared-memory ownership, single-writer epochs, barrier publication, memory bounds, and visibility rules |
| 45 | [`VGI_VIRTUAL_LAYER.md`](VGI_VIRTUAL_LAYER.md) | Hosted VGI Signal8 computation, dual-Ground identity, bounded compile/execute, signal-valued receipts, checkpoints, and semantic replay |
| 46 | [`COMPUTATIONAL_FABRIC.md`](COMPUTATIONAL_FABRIC.md) | Mutual-TLS peer discovery, portable host advertisements, revision/lease handling, directed multi-hop route planning, and integration boundaries |

## Document classes

**Specification.** `ARCHITECTURE.md`, `SEMANTIC_TRANSLATION.md`, `REPLACEMENT_SPEC.md`, `INTEGRATION_SPEC.md`. Core system design and interfaces.

**System profile.** `HYPERVISOR_PROFILE.md`. Operational state, equations, receipts, replay, revisions, and integration surfaces of the hypervisor.

**Boundary.** `BOUNDARY_PROCEDURAL_MODEL.md`. Procedural decision model boundaries.

**Reference.** `GLOSSARY.md`, `INVARIANTS.md`. Look-up tables and registries consumed by the specifications.

**Procedure & Roadmap.** `PLAN.md`, `BUILDOUT_REQUIREMENTS.md`, `ITERATION_2_BUILD_PLAN.md`, `DOGFOODING_AND_EMPIRICAL_LIMITS.md`. Research plan, evaluation procedure, Iteration 2 build plan, and dogfooding report.

**Runtime & Navigation.** `COMMUNICATION_HOST_MODEL.md`, `COMPUTATIONAL_FABRIC.md`, `EGPU_NAVIGABLE_FABRIC.md`, `WORKGROUP_SHARED_MEMORY.md`, `VGI_VIRTUAL_LAYER.md`, `NAVIGABLE_COMPUTATION_DAG.md`, `NAVIGABLE_COMPUTATION_RECOVERY.md`, `REPEATED_JOINT_PROCESS_RECOVERY.md`, `PROCESS_CRASH_BOUNDARIES.md`, `RECOVERY_LINEAGE.md`, `RECOVERY_BUNDLE.md`, `RECOVERY_LINEAGE_PROCESSES.md`, `RECOVERY_LINEAGE_SERVICE.md`, `RECOVERY_LINEAGE_DEPLOYMENT.md`, `SEMANTIC_TRANSLATION.md`, `TRANSIT_COMPUTE.md`, `TRANSIT_PATH_STATE.md`, `STATE_SPACE_NAVIGATION.md`, `CONTEXTUAL_PROCESS_NAVIGATION.md`, `FORMAL_NAVIGATION.md`, `NAVIGATION_BRIDGE.md`, `NAVIGATION_COORDINATOR.md`, `NAVIGATION_ADMISSION.md`, `NAVIGATION_EXECUTION.md`, `NATIVE_VCPU_CONTEXT.md`, `STRUCTURAL_MEMORY.md`. Native vCPU context commits, bounded transit execution, persistent path state, orbit scheduling, symbolic capacity, contextual resolution, replayable derivation, abstract reachability, process equivalence, causal dependencies, conservative compilation, coordinated navigation plans, hypervisor-owned execution admission, crash-recoverable state execution, and verified generative memory.

**Research & Theory.** `COMMUNICATION_SUBSTRATES_AND_INFORMATION_THEORY.md`, `COMMUNICATION_HOST_MODEL.md`, `CROSS_SYSTEM_SYNTHESIS_TIME_COMPUTATION_MODELS.md`, `ARCHITECTURAL_EMERGENCE.md`. Substrate information theory, temporal models, cross-paradigm synthesis, and the distinction between demonstrated capability and architectural possibility.

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
