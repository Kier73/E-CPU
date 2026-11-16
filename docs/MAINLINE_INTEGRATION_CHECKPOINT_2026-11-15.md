# E-CPU mainline integration checkpoint — 2026-11-15

**Status:** read-only architectural inventory followed by targeted regression repairs on a separate audit branch. **This is not a claim of a clean mainline.** The source snapshot is E-CPU `main` at commit `6fd416facdb2aefd6fc7d66a06b014e3d31b5a52`. Observed public GitHub Actions state was checked during the audit on 2026-11-16 UTC. Actions status is mutable; this document pins the observations, not their future outcomes.

## 1. Governing computation model

`docs/COMMUNICATION_HOST_MODEL.md` defines a host as an identifiable **observer** rather than a physical machine. `docs/LATENT_PATH_CAPACITY.md` makes capacity-before-recognition explicit. Together with `docs/COMPUTATIONAL_STATE_SPACE_ARCHITECTURE.md`, they establish a useful order:

1. Describe an intention and its Computational Ground.
2. Identify observable information relationships and their contexts.
3. Recognize or construct compatible observer-host relationships, including possible retained path state.
4. Navigate the admitted state-space to the requested observation.
5. Verify and accept the result under receiver-controlled contracts and preserve recoverable provenance.

**Bootstrap is not the same as maintaining a dedicated conventional processor at each subsequent computational locus.** A separately operated GitHub repository API, persistent object store, Actions scheduler and workflow runner can form a composite information path. The system can navigate and verify operations through those existing observer-host relationships without installing an E-CPU binary everywhere. Each effective transition still needs an actual available information relation; a digest, a proposed law or a passive carrier alone cannot authorize a semantic effect. A physical host may be one realizer but is not the definition of the logical host.

This is why an unverified software FIR model, an E-GPU reference interpreter, and an admitted network-state Ground must not be conflated. Their evidence and operational responsibilities differ.

## 2. Mainline inventory (exact source snapshot)

The Git tree at `6fd416facdb2` contains 169 `mailcpu/` Python-package files, 187 `tests/` files and 113 `docs/` files (the tree itself contains additional directories and non-Python files).

| Established responsibility | Existing implementation / integration anchor |
| --- | --- |
| Deterministic machine / virtual operating environment | `interpreter.py`, `headless.py`, `kernel.py`, `vm.py` |
| Receiver-local authority and typed operators | `classifier.py`, `virtual_layer.py`, `computational_execution.py` |
| Structural, revisioned and generative Ground | `structural_memory.py`, `law_certifier.py`, `composed_ground.py` |
| Observation-to-Ground-to-navigation | `observation.py`, `observer_orbit.py`, `observed_orbit_pipeline.py` |
| Logical and authenticated computational path | `computational_resolver.py`, `computational_fabric.py`, `computational_fabric_forwarding.py`, `reliability.py` |
| Execution-DAG and operation-native dispatch | `computation_dag.py`, `program_dataflow.py`, `program_dataflow_fabric.py`, `partitioned_dataflow.py` |
| Checkpoint / replay / quorum identity | `recovery.py`, `recovery_lineage.py`, `transferable_execution_claim.py` |
| Bounded SIMD/SIMT reference model | `transit_simt.py`, `egpu.py` |
| Bootstrap, qualification and adaptive assembly | `substrate_bootstrap.py`, `active_ground_discovery.py`, `runtime_qualification.py`, `adaptive_placement.py`, `ground_native_realization.py` |
| Path capacity and verified observer composition | `latent_path_capacity.py`, `observer_path_evidence.py`, `path_ground_probe.py`, `transit_path_modes.py` |
| Neural descriptions and local model-host integration | `weight_space.py`, `transition_space.py`, `neural_graph_bridge.py`, `computational_host.py` |
| Direct system use for real research | `examples/research_frontier.py`, `examples/research_proof_obligations.py`, `examples/model_ground_os.py` |

These are **implementation and source anchors**, not a claim that every pair is already composed into one validated production runtime. The existing Observed Orbit Pipeline deliberately reuses the law certifier, Structural Memory, observer contracts and Hypervisor rather than introducing competing authorities.

## 3. Feature-branch continuity: GitHub “merged” is not necessarily mainline

Pull-request merges into feature branches are valid Git operations; they do **not** imply those changes reached `main`.

| Series | On `main` at the pinned SHA | Additional branch-only work | Mainline action |
| --- | --- | --- | --- |
| SHN nested logical hosts | #120 (SHN-001) | #121 (SHN-002), merged into SHN-001 feature branch | Verify nested port tests and port-budget accounting before main integration |
| SAB active host formation | #122–129 as applicable, including #129 SAB-008 | #130 SAB-009 → #132 SAB-010 → #134 SAB-011 → #136 SAB-012, stacked into feature branches | Consolidate dependency leaf; validate formation, native Hypervisor authority and recovery against one current mainline |
| USM model-operated system | #138 USM-001 | #139 → #140 → #141 → #142 → #143 | Verify model-issued calls, authenticated fabric, crash cut and quorum publication as one chain |
| VGI similarity Transit | #145 | #146 → #147 | Verify native Structural Memory revision and post-commit recovery; do not treat existing external-catalogue test as the stronger claim |
| CAPACITY network-state | #152 CAPACITY-001 | #153 CAPACITY-002, merged into its parent feature branch | Prioritize because network queue slots are modeled as part of the computational state |
| Tensor path | Existing E-GPU and SIMT reference work | #154 TENSOR-PATH-001 remains **draft/unmerged** | Hold until mainline and observer-host integration gates pass |

The GitHub PR timelines were inspected for the actual `base.ref` of each merge. The relevant feature-branch heads at audit were SHN-002 `3237002ec447`, SAB-012 `d0279ff6a986`, model publication `e578903463ec`, VGI similarity `8f7173e37325`, and CAPACITY-002 `602e1b8012b0`. These are **not** asserted to be ancestors of `main`.

## 4. Verification truth at the audit point

The current `main` full `verify` run [43771448850](https://github.com/Kier73/E-CPU/actions/runs/43771448850) and CAPACITY-001 run [43771448704](https://github.com/Kier73/E-CPU/actions/runs/43771448704) were queued; the audit branch and tensor draft were also not yet confirmed by a full passing workflow. No queued, canceled or missing run is a success result.

The latest completed main-branch `verify` failure inspected was [43636024520](https://github.com/Kier73/E-CPU/actions/runs/43636024520), on an **earlier** SHA. On its Ubuntu/Python 3.12 gate it reported **1,588 passed, 11 failed, 6 warnings, and 7 passing subtests**, followed by 183 mathematical-docstring check findings, 59 invariant resolver/docstring findings, and one generated-file link finding. This cannot determine the exact current-head failure count, but it is an actionable integration regression baseline.

### Targeted corrections in this audit branch

The changes intentionally preserve existing semantic contracts:

- `tests/test_partitioned_dataflow.py`: a partition splitter returns a typed child request, not a nested partition object; derive the exact `ComputationalAddress` from that child.
- `tests/test_program_dataflow_fabric.py`: correct escaped assembly source delimiters in the wrong-operator test.
- `tests/test_program_dataflow.py`: compare the identity set of restored committed nodes, not canonical node order to actual execution commit order.
- `tests/test_transferable_execution_claims.py`: assert the precise current-assignment refusal, not a different refusal phrase.
- `tests/test_network.py`: retain an explicit exhaustive host-socket allowlist that includes the separately implemented federated mTLS adapter.
- `tests/test_computational_fabric.py`: supply a transport-owned `SocketListener` where the authenticated peer listener requires it, and expose typed child-dispatch failures in the multi-host regression.
- `mailcpu/__init__.py`: declare already imported multiply/frontier/placement APIs in `__all__`.
- `docs/TRANSFERABLE_EXECUTION_CLAIMS.md`: identify `claims.json` as a generated **runtime** artifact, not a tracked source file.
- `mailcpu/computational_fabric_forwarding.py`: retain small receiver-reconstructed goals verbatim; represent oversized goals by canonical SHA-256 and bounded kind in the 4 KiB control plane while the exact full envelope remains committed and receiver-validated. A new focused regression checks content identity and tamper sensitivity.
- `tests/test_observed_orbit_pipeline.py`: use a witnessed modular wrap for positive Ground recovery and explicitly retain the correct `FITTED` refusal for an unwrapped progression. Do **not** weaken `StructuralMemoryRegistry.propose_trace` admission.

**Unresolved:** the multi-host ADD frontier test returned 0/2 child receipts in the previous run. The revised test now surfaces its `PartitionedFrontierIncomplete.failures` in CI diagnostics instead of hiding the reason. The 59 missing public docstrings and broader governing-mathematics documentation backlog remain. No claim of passing tests is made for the audit branch until its exact head completes.

## 5. Ordered integration gates

**Gate A — mainline conformance.** On one exact main SHA, run Linux/Windows and supported Python versions, all invariant/public-surface/hygiene checks, and full pytest. Keep blockers visible and repair executable semantic defects before adding capability categories. Do not weaken admission or delete negative tests.

**Gate B — recover one feature branch at a time.** Verify exact ancestry, file overlap, active workflows and result provenance. Rebase or merge the smallest proven branch stack only after relevant gates pass. A “merged” nested PR is not evidence of mainline presence.

**Gate C — one canonical observer-host composition.** Use existing `ObservedOrbitPipeline`, `ComputationalAddressResolver`, `ComputationalFabricResolver`, `VirtualLayerRuntime`, Hypervisor, `StructuralMemoryRegistry`, and native recovery machinery as authorities. SAB and CAPACITY adapters should remain adapters, not competing routers or certifiers. Preserve three separate graphs: algorithm dependencies, communication topology and local operational loci.

**Gate D — direct use on an existing computational path.** Use the already merged USM-009/010 GitHub research-frontier workflow to classify current research observations by exact SHA and actual CI results. GitHub API → repository/workflow scheduling → accepted results form a meaningful observer-host path; verify where access and authorization belong. This demonstrates composite existing service computation, not arithmetic performed by a passive wire.

**Gate E — further tensor/model expansion.** Evaluate existing SIMT, operation-native DAG, CAPACITY-002 network-state model and current neural Grounds before adding another runtime. Require a specific experiment that distinguishes new observer-host capability from a second reference interpreter.

## 6. Preservation rule

Do not collapse **semantic identity**, **state ownership**, **execution authority**, **route witness**, **representation**, **observed effect**, **proof/certificate**, or **physical implementation metadata** into a single string or receipt. They may refer to the same event, but they answer different questions. A content digest is identity evidence, not authentication or a generalized proof of computation.

**Checkpoint result:** architecture mapped, branch-only integration identified, previous CI failures classified, targeted fixes isolated on a reviewable branch. Full-system verification and feature-branch integration remain in development until measured on exact revisions.
