# Specifications

Index of specification documents. Documents use defined terms from `GLOSSARY.md`.

## Reading order

| Order | Document | Read it for |
|---|---|---|
| 1 | [`../README.md`](../README.md) | What the system is, how to run it, and its architecture |
| 2 | [`GLOSSARY.md`](GLOSSARY.md) | The defined terms relied on across the documentation |
| 3 | [`ARCHITECTURE.md`](ARCHITECTURE.md) | State model, lifting table, capability model, evidence tiers |
| 4 | [`SYSTEM_MATHEMATICAL_MAP.md`](SYSTEM_MATHEMATICAL_MAP.md) | Cross-subsystem mathematical models, composition rules, and proof boundaries |
| 5 | [`SEMANTIC_TRANSLATION.md`](SEMANTIC_TRANSLATION.md) | Representation identities, observable equivalence, context, resource, authority, and replay obligations |
| 6 | [`REPLACEMENT_SPEC.md`](REPLACEMENT_SPEC.md) | The replacement target and its acceptance criteria |
| 7 | [`INTEGRATION_SPEC.md`](INTEGRATION_SPEC.md) | Adopted mechanisms and their integration boundaries |
| 8 | [`HYPERVISOR_PROFILE.md`](HYPERVISOR_PROFILE.md) | Deep operational profile of the classifier, policy, time, replay, and revision control plane |
| 9 | [`BOUNDARY_PROCEDURAL_MODEL.md`](BOUNDARY_PROCEDURAL_MODEL.md) | Procedural decision model and generation interface |
| 10 | [`INVARIANTS.md`](INVARIANTS.md) | Machine-checkable invariant registry |
| 11 | [`PLAN.md`](PLAN.md) | Research hypotheses and evaluation procedure |
| 12 | [`BUILDOUT_REQUIREMENTS.md`](BUILDOUT_REQUIREMENTS.md) | Future architectural requirements and engineering milestones |
| 13 | [`COMMUNICATION_SUBSTRATES_AND_INFORMATION_THEORY.md`](COMMUNICATION_SUBSTRATES_AND_INFORMATION_THEORY.md) | Information-theoretic analysis of communication paths as virtual computational substrates |
| 14 | [`CROSS_SYSTEM_SYNTHESIS_TIME_COMPUTATION_MODELS.md`](CROSS_SYSTEM_SYNTHESIS_TIME_COMPUTATION_MODELS.md) | Cross-system synthesis of Virtual Quanta, VL_Logic Compiler, and MailCPU paradigms |
| 15 | [`ITERATION_2_BUILD_PLAN.md`](ITERATION_2_BUILD_PLAN.md) | Comprehensive engineering plan and external resource ingestion map for Iteration 2 |
| 16 | [`DOGFOODING_AND_EMPIRICAL_LIMITS.md`](DOGFOODING_AND_EMPIRICAL_LIMITS.md) | Empirical evaluation, discovered boundaries, ergonomic repairs, and Iteration 3 roadmap |
| 17 | [`VIRTUAL_LAYER_WORKLOAD.md`](VIRTUAL_LAYER_WORKLOAD.md) | Typed portable workload, node-local operator registry, digest-pinned structural-memory inputs, and hypervisor/reliable-channel integration |
| 18 | [`TRANSIT_COMPUTE.md`](TRANSIT_COMPUTE.md) | Receiver-side bounded compute capsules and authenticated transit execution |
| 19 | [`TRANSIT_PATH_STATE.md`](TRANSIT_PATH_STATE.md) | Persistent path state, SIMT, private-memory and structural-memory backends, evidence-bearing coordinate reads, recovery, and deterministic orbit scheduling |
| 20 | [`STATE_SPACE_NAVIGATION.md`](STATE_SPACE_NAVIGATION.md) | Symbolic capacity, finite trajectories, and time-budgeted state-space navigation |
| 21 | [`TRANSIT_PATH_MODES.md`](TRANSIT_PATH_MODES.md) | One path switching between RRNS memory, RTT sensing, and bounded processing |
| 22 | [`TRANSIT_PATH_BINDING.md`](TRANSIT_PATH_BINDING.md) | Live session binding for requester RTT, receiver service time, queue state, ACKs, and retries |
| 23 | [`TEMPORAL_CLOCK_FABRIC.md`](TEMPORAL_CLOCK_FABRIC.md) | Process-selected wall, monotonic, causal, scheduler, event, chronon, and chemical temporal domains |
| 24 | [`CONTEXTUAL_PROCESS_NAVIGATION.md`](CONTEXTUAL_PROCESS_NAVIGATION.md) | Context-resolved process addresses, declarative transition logic, bounded navigation, replay witnesses, and readiness contracts |
| 25 | [`FORMAL_NAVIGATION.md`](FORMAL_NAVIGATION.md) | Integer-affine interval analysis, conservative reachability, strong bisimulation, and vector-clock causal dependency graphs |
| 26 | [`NAVIGATION_BRIDGE.md`](NAVIGATION_BRIDGE.md) | Conservative compilation from concrete process descriptions to integer-affine abstract navigation |
| 27 | [`NAVIGATION_COORDINATOR.md`](NAVIGATION_COORDINATOR.md) | Unified formal and concrete navigation, causal and representation gates, and non-authoritative admission proposals |
| 28 | [`NAVIGATION_ADMISSION.md`](NAVIGATION_ADMISSION.md) | Hypervisor-owned live-context revalidation, kernel capability checks, policy arbitration, bounded path grants, and expiry |
| 29 | [`NAVIGATION_EXECUTION.md`](NAVIGATION_EXECUTION.md) | Journal provenance, live grant revalidation, deterministic path replay, atomic host compare-and-swap, durable receipt recovery, and execution receipts 
| 30 | [`NATIVE_VCPU_CONTEXT.md`](NATIVE_VCPU_CONTEXT.md) | Safepoint-only navigation of the native scheduler PC/register file with atomic checkpoint and receipt recovery |
| 31 | [`STRUCTURAL_MEMORY.md`](STRUCTURAL_MEMORY.md) | Verified generator specifications, evidence certificates, context-bound reads, VFS file providers, demand-paged structural-memory pages, COW, revision admission, and checkpoint/journal persistence |
| 32 | [`ARCHITECTURAL_EMERGENCE.md`](ARCHITECTURAL_EMERGENCE.md) | Historical post-PR #16–22 architecture review; evidence discipline and hypotheses remain useful, but current capabilities are indexed in the README and system mathematical map |
| 33 | [`EVIDENCE_PATH_RESOLVER.md`](EVIDENCE_PATH_RESOLVER.md) | Evidence-indexed representation routes, multidimensional resource costs, receiver-local capability filtering, and non-authoritative path proposals |
| 34 | [`NAVIGABLE_COMPUTATION_EXPERIMENT.md`](NAVIGABLE_COMPUTATION_EXPERIMENT.md) | End-to-end Structural Memory to Transit CPU composition, evidence-backed representation routing, replay, and measured boundaries |
| 35 | [NAVIGABLE_COMPUTATION_RECOVERY.md](NAVIGABLE_COMPUTATION_RECOVERY.md) | Integrity-bound recovery of receiver state, both channel endpoints, evidence route catalogue, and semantic retry identity |
| 36 | [NAVIGABLE_COMPUTATION_DAG.md](NAVIGABLE_COMPUTATION_DAG.md) | Persistent computation DAGs, predecessor-gated dispatch, independent Transit branches, monotonic operation revision, and dependency-guarded joins |
| 37 | [REPEATED_JOINT_PROCESS_RECOVERY.md](REPEATED_JOINT_PROCESS_RECOVERY.md) | Two consecutive hard-kill/restart cycles for independent requester and receiver checkpoints while one committed operation remains unpublished |
| 38 | [PROCESS_CRASH_BOUNDARIES.md](PROCESS_CRASH_BOUNDARIES.md) | Independent requester and receiver process termination at all four Transit execution/publication/acknowledgement cuts |
| 39 | [RECOVERY_LINEAGE.md](RECOVERY_LINEAGE.md) | Quorum-anchored checkpoint generations, independent requester/receiver/backend content identities, and rollback rejection |
| 40 | [`RECOVERY_BUNDLE.md`](RECOVERY_BUNDLE.md) | Immutable endpoint checkpoint bundles, durable capture ordering, and quorum-gated runtime restoration |
| 41 | [`RECOVERY_LINEAGE_PROCESSES.md`](RECOVERY_LINEAGE_PROCESSES.md) | Independent authority processes, reliable seed-quorum transport, and restart-safe prepare/commit/read quorum recovery |
| 42 | [`RECOVERY_LINEAGE_DEPLOYMENT.md`](RECOVERY_LINEAGE_DEPLOYMENT.md) | Fixed-membership topology validation, placement-node/failure-domain declarations, authority endpoints, and production deployment limits |
| 43 | [`COMMUNICATION_HOST_MODEL.md`](COMMUNICATION_HOST_MODEL.md) | Normative definition of host as a logical operational locus, identity versus placement, composable roles, and path-hosting |
| 44 | [`EGPU_NAVIGABLE_FABRIC.md`](EGPU_NAVIGABLE_FABRIC.md) | Navigable E-GPU method graph, SIMT/vector/reduction/workgroup methods, route receipts, and implementation limits |
| 45 | [`WORKGROUP_SHARED_MEMORY.md`](WORKGROUP_SHARED_MEMORY.md) | Workgroup-scoped shared-memory ownership, single-writer epochs, barrier publication, memory bounds, and visibility rules |
| 46 | [`VGI_VIRTUAL_LAYER.md`](VGI_VIRTUAL_LAYER.md) | Hosted VGI Signal8 computation, dual-Ground identity, bounded compile/execute, signal-valued receipts, checkpoints, and semantic replay |
| 47 | [`COMPUTATIONAL_FABRIC.md`](COMPUTATIONAL_FABRIC.md) | Mutual-TLS peer discovery, portable host advertisements, revision/lease handling, directed multi-hop route planning, and integration boundaries |
| 48 | [`COMPUTATIONAL_FABRIC_FORWARDING_RECOVERY.md`](COMPUTATIONAL_FABRIC_FORWARDING_RECOVERY.md) | Per-peer Hypervisor and reliable-channel checkpoints, quorum-anchored recovery generations, fresh TLS rebinding, capture cuts, and crash-recovery proof limits |
| 49 | [`FEDERATED_FORWARDING_PROCESS_RECOVERY.md`](FEDERATED_FORWARDING_PROCESS_RECOVERY.md) | Independent relay and terminal-peer hard-kill recovery, peer-scoped quorums, downstream stream rebinding, and semantic replay continuity |

| 50 | [COMPUTATIONAL_OBJECTS_AND_TIME.md](COMPUTATIONAL_OBJECTS_AND_TIME.md) | Computational object identity, host interpretation, time coordinates, temporal composition of communication paths, and replicated versus partitioned execution |
| 51 | [TRANSIT_BYTE_OBJECTS.md](TRANSIT_BYTE_OBJECTS.md) | M1 content-addressed byte objects over existing page backings, page manifests, bounded range reads, remote page composition, and proof boundaries |
| 52 | [COMPUTATIONAL_HOSTING.md](COMPUTATIONAL_HOSTING.md) | M2 backend-neutral multi-file artifact admission, backend profiles, local execution adapters, deterministic receipts, and Hypervisor/Transit composition |
| 53 | [COMPUTATIONAL_SESSIONS_AND_STATE.md](COMPUTATIONAL_SESSIONS_AND_STATE.md) | M3 persistent computational sessions, immutable state checkpoints, quorum-anchored revisions, CAS continuation, and host migration |
| 54 | [COMPUTATIONAL_SESSION_INTERPRETATION.md](COMPUTATIONAL_SESSION_INTERPRETATION.md) | M4 pure state-transition adapters, compiled interpretation identities, VGI Ground/task plan reuse, session-bound context, and cache authority boundaries |
| 55 | [VGI_PERSISTENT_SESSIONS_AND_TRANSIT.md](VGI_PERSISTENT_SESSIONS_AND_TRANSIT.md) | M5 persistent VGI machine state, M6 bounded resumable instruction quanta, M7 portable session transfer, target M1 re-admission, and backend compatibility |
| 56 | [COMMUNICATION_STREAM_COMPUTATION.md](COMMUNICATION_STREAM_COMPUTATION.md) | Typed communication streams as computational state carriers, host-side interpretation, symbolic navigation, and finite-observer resource bounds |
| 57 | [FABRIC_VGI_SESSION_COMPOSITION.md](FABRIC_VGI_SESSION_COMPOSITION.md) | End-to-end M7 persistent VGI session transfer through authenticated A→B→C forwarding, receiver M1/M3/M4 continuation, identity continuity, replay, and measured stages |
| 58 | [PROGRAM_DATAFLOW_COMPILATION.md](PROGRAM_DATAFLOW_COMPILATION.md) | Bounded compilation from native MailCPU assembly to register-definition DAGs, Structural Memory input receipts, invariant-preserving observations, and topology profiles |
| 59 | [OPERATION_NATIVE_COMPUTATIONAL_FABRIC.md](OPERATION_NATIVE_COMPUTATIONAL_FABRIC.md) | Map ready algorithm-operation frontiers onto authenticated communication paths and heterogeneous local implementations without distributing full VMs; resolve symbolic Structural Memory at receiving hosts |
| 60 | [OPERATIONAL_SEMANTICS_AND_STATE_SPACE.md](OPERATIONAL_SEMANTICS_AND_STATE_SPACE.md) | Formalize portable semantic operations, contextual interpretation, state-space orbits, direct inverse navigation, and the boundary between interpretation and physical execution |
| 61 | [CONTEXTUAL_ORBIT_FABRIC.md](CONTEXTUAL_ORBIT_FABRIC.md) | Receiver-executed inverse navigation over authenticated multi-hop routes, authority-only Structural Memory access, located-coordinate evidence, and refusal/budget boundaries |
| 62 | [`OPERATION_FRONTIER_TIMING.md`](OPERATION_FRONTIER_TIMING.md) | Endpoint-local phase timing and a correctness-checked local CPU / remote CPU / remote E-GPU frontier placement benchmark |
| 63 | [`PLACEMENT_PROFILES.md`](PLACEMENT_PROFILES.md) | Workload-, Ground-, implementation- and route-bound empirical timing profiles with complete frontier receipts and advisory ranking |
| 64 | [`BINARY_FRONTIER_PARTITIONING.md`](BINARY_FRONTIER_PARTITIONING.md) | Atomic DAG frontier publication and deterministic, receipt-bound child request partitions across fabric hosts |
| 65 | [`PARTITIONED_BINARY_FRONTIER_EXECUTION.md`](PARTITIONED_BINARY_FRONTIER_EXECUTION.md) | Authenticated child dispatch, typed composite receipts, checkpoint recovery, stable stream sequencing and bounded cross-host concurrency |

## Document classes

**Specification.** `ARCHITECTURE.md`, `SEMANTIC_TRANSLATION.md`, `REPLACEMENT_SPEC.md`, `INTEGRATION_SPEC.md`. Core system design and interfaces.

**System profile.** `HYPERVISOR_PROFILE.md`. Operational state, equations, receipts, replay, revisions, and integration surfaces of the hypervisor.

**Boundary.** `BOUNDARY_PROCEDURAL_MODEL.md`. Procedural decision model boundaries.

**Reference.** `GLOSSARY.md`, `INVARIANTS.md`. Look-up tables and registries consumed by the specifications.

**Procedure & Roadmap.** `PLAN.md`, `BUILDOUT_REQUIREMENTS.md`, `ITERATION_2_BUILD_PLAN.md`, `DOGFOODING_AND_EMPIRICAL_LIMITS.md`. Research plan, evaluation procedure, Iteration 2 build plan, and dogfooding report.

**Runtime & Navigation.** `COMPUTATIONAL_OBJECTS_AND_TIME.md`, `TRANSIT_BYTE_OBJECTS.md`,  `COMMUNICATION_HOST_MODEL.md`, `COMPUTATIONAL_FABRIC.md`, `COMPUTATIONAL_FABRIC_FORWARDING_RECOVERY.md`, `FEDERATED_FORWARDING_PROCESS_RECOVERY.md`, `FABRIC_VGI_SESSION_COMPOSITION.md`, `EGPU_NAVIGABLE_FABRIC.md`, `WORKGROUP_SHARED_MEMORY.md`, `VGI_VIRTUAL_LAYER.md`, `NAVIGABLE_COMPUTATION_DAG.md`, `NAVIGABLE_COMPUTATION_RECOVERY.md`, `REPEATED_JOINT_PROCESS_RECOVERY.md`, `PROCESS_CRASH_BOUNDARIES.md`, `RECOVERY_LINEAGE.md`, `RECOVERY_BUNDLE.md`, `RECOVERY_LINEAGE_PROCESSES.md`, `RECOVERY_LINEAGE_SERVICE.md`, `RECOVERY_LINEAGE_DEPLOYMENT.md`, `SEMANTIC_TRANSLATION.md`, `TRANSIT_COMPUTE.md`, `TRANSIT_PATH_STATE.md`, `STATE_SPACE_NAVIGATION.md`, `CONTEXTUAL_PROCESS_NAVIGATION.md`, `FORMAL_NAVIGATION.md`, `NAVIGATION_BRIDGE.md`, `NAVIGATION_COORDINATOR.md`, `NAVIGATION_ADMISSION.md`, `NAVIGATION_EXECUTION.md`, `NATIVE_VCPU_CONTEXT.md`, `STRUCTURAL_MEMORY.md`, `PROGRAM_DATAFLOW_COMPILATION.md`, `OPERATION_NATIVE_COMPUTATIONAL_FABRIC.md`, `OPERATIONAL_SEMANTICS_AND_STATE_SPACE.md`, `CONTEXTUAL_ORBIT_FABRIC.md`, `OPERATION_FRONTIER_TIMING.md`, `PLACEMENT_PROFILES.md`, `BINARY_FRONTIER_PARTITIONING.md`, `PARTITIONED_BINARY_FRONTIER_EXECUTION.md`. Native vCPU context commits, bounded transit execution, persistent path state, orbit scheduling, symbolic capacity, contextual resolution, replayable derivation, abstract reachability, process equivalence, causal dependencies, conservative compilation, coordinated navigation plans, hypervisor-owned execution admission, crash-recoverable state execution, verified generative memory, and native-program dataflow compilation with operation-native execution across heterogeneous fabric hosts, receiver-resolved Structural Memory operands, contextual state-space navigation, and endpoint-local phase-separated measurement of communication and execution, with bounded ranked alternatives for computational host placement, empirical workload-specific placement profiles, evidence-gated advisory comparison, all-or-none frontier publication, deterministic multi-host partition descriptions, and resumable authenticated multi-host binary-frontier execution with typed composite receipts and bounded cross-stream concurrency.

**Research & Theory.** `COMPUTATIONAL_OBJECTS_AND_TIME.md`,  `COMMUNICATION_SUBSTRATES_AND_INFORMATION_THEORY.md`, `COMMUNICATION_HOST_MODEL.md`, `COMMUNICATION_STREAM_COMPUTATION.md`, `CROSS_SYSTEM_SYNTHESIS_TIME_COMPUTATION_MODELS.md`, `ARCHITECTURAL_EMERGENCE.md`. Substrate information theory, temporal models, cross-paradigm synthesis, and the distinction between demonstrated capability and architectural possibility.

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
