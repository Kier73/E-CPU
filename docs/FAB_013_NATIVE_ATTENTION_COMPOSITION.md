# FAB-013 — Native attention composition

## Architectural synthesis

The 127/8 namespace supplies 2^24 logical machine identities. FAB-009–012 exercise full address sweeps, independently mutable contexts, continuous execution, effect journals and pure-region leaps in compact C realizers. A general machine environment should compose existing E-CPU components instead of extending that experimental interpreter into a second operating system.

- [HeadlessOS](../mailcpu/headless.py) owns native process trees, files, capabilities, syscalls and checkpoint binding; [VM](../mailcpu/vm.py) owns memory images and aggregate resident mapping admission.
- [VirtualMemory](../mailcpu/memory.py) provides demand reservations, private copy-on-write state, reclaim and shared mappings. [StructuralMemoryPageBacking](../mailcpu/structural_memory_pages.py) reconstructs revision-pinned bytes, checks exact SHA-256 identities and retains four cached structural pages ranked by measured regeneration cost times observed reuse per byte. The native resident quota counts mappings, not total host RSS; backing bytes, cached evidence, local mutable pages and interpreter overhead require separate accounting.
- [NavigableComputationDAG](../mailcpu/computation_dag.py) owns dependency readiness, atomic commit and exact replay. Its current hard bound is 256 nodes / 1024 edges per graph; a full fabric must use compositional DAGs, not a single flat graph of 16M objects.
- [DeterministicScheduler](../mailcpu/scheduler.py) owns local process transitions and logical time, including blocked wait and suspension. [TransitOrbitScheduler](../mailcpu/transit_orbit.py) owns fair ready path selection; [partitioned dataflow](../mailcpu/partitioned_dataflow.py) owns child dispatch, receipts, checkpoint and failed pure-child rehoming.
- [NativeCPUContextBackend](../mailcpu/native_cpu.py) projects real PC/registers at suspended safepoints and persists admitted navigation together with its receipt. It must not be treated as authority for unsuspended live writes.
- [Intention-formed fabric](../mailcpu/intention_formed_fabric.py) forms finite observation-preserving processors; [continuous session](../mailcpu/continuous_session.py) preserves naming across rejoin while recovering actual state through local authority and quorum lineage.
- [SOI-003–006](VL64_HOSTED_VM_FLEET.md) exercised 64 actual independent HeadlessOS/VM interpreter hosts and original VL-64 operations; [SOI-007/008](VLI_TEMPORAL_OS_HOSTING.md) preserves original VL-I temporal state across disposable hosts. These are relevant realizer and continuity evidence at smaller scale.

## Proposed hierarchical contract

A leaf identifies (fabric context, 24-bit machine ID, recursive process path, Ground revision, observation coordinate). The address is naming; resource grants and authorization remain separate. At each hierarchy level, derive available ready work from admitted dependencies and local observations, and allocate bounded execution quanta, resident mappings, regeneration cost and communication budgets. Descendant grants sum to at most the parent grant independently in each dimension. No object is needed for an inactive machine until its description must be materialized. A shared machine ID does not imply shared private process state.

Attention is a policy over eligible observations and work, not a new scheduler, memory manager or authorization authority. Existing readiness and receiver policy veto the candidate. A future allocator should compare estimated information gain, deadline/fairness debt, causal readiness, observed regeneration/transfer cost and physical resource pressure, retaining the complete inputs behind a decision. Scores are advisory and cannot grant rights. Start with deterministic equal-grant fairness and measured resource counts before introducing learned weights.

## Executable integration

[The integration test](../tests/test_fab013_attention_composition.py) uses real HeadlessOS process trees under address identities 0 and 0xffffff, two tasks per tree, and a native DAG requiring each child result before its parent. All four native tasks hold two ordinary resident pages and a third revision-pinned structural page reservation. A shared cap of nine resident mappings allows only one working page across the four tasks. A simple local attention policy chooses a ready leaf from the least-served machine (stable tie-break); the native OS materializes its structural page through authorized memory syscalls. The test challenges the shared quota by trying another process's page, executes the selected task for three native instructions from its observed input and predecessor value, suspends it, reclaims the working page, and commits its result to the DAG. The OS is checkpointed and restored after two leaves, and the DAG reconstructed from its own snapshot; the test checks retained data and native termination. This is a controlled host-side observation policy, not an implementation of a general distributed attention allocator. The two checkpoints are not an atomic distributed transaction. The page cap is a resident mapping count, not a nine-page RSS bound. There is one actual HeadlessOS instance with two labeled process trees, not two independently booted OS instances, and not 16M native HeadlessOS instances.

## Development order

1. Validate this composition with the native test and existing CPU/DAG regressions.
2. Expose an advisory resource offer and grant contract for recursive child scopes with deterministic budget conservation, readiness and revision binding. Test quota refusal, exact reuse, fairness and stale plan refusal.
3. Use sparse prefix summaries for pending work, not a full-space scan; measure hierarchical lookup and active-set costs at 16M address capacity. Extend to independently booted native environments under the same allocator.
4. Connect actual page-fault and observer measurements to selection; compare fairness-only, regeneration-cost and information-gain policies using real traces. Ensure reclaim preserves pinned byte identities and COW private effects.
5. Bind execution grants to native Hypervisor, durable channel and transferable claims; recover a lost worker without repeating a committed effect. Only then extend to full-fabric heterogeneous recursive processes and VL-I/VL-64 realizers.

## Verification

Run `python -m pytest -vv tests/test_fab013_attention_composition.py tests/test_native_cpu.py tests/test_computation_dag.py` on the actual repository. The dedicated hosted workflow runs these tests. No full-space native environment claim is inferred from this composition.
