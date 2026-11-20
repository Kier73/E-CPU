# IPS-004 — Qualified generated Ground execution across observer-hosts

**Research scope:** An IPS-003 intention-constructed affine program is executed using E-CPU's existing receiver-side Hypervisor and Virtual Layer, native dependency DAG, SAB-003/SAB-008 qualification and observation, and checkpoint recovery. The mTLS integration test uses two independently launched loopback peer service processes. No arbitrary source execution or new execution authority is installed.

## Experiment

Can an imposed mathematical behavior generate a virtual computation whose intermediate values are evaluated by separate qualified observer-hosts while retaining one Ground identity and reconstructable results after a host disappears?

The initial Ground is an intention rather than fitted historical data:

    Required: f(0)=4, f(1)=11 over Z/17Z
    IPS-003 derives P1(x)=3x+2, P2(x)=8x+5
    Native DAG: stage 0 -> stage 1
    Origin Virtual Layer: Hypervisor authorization for each operation
    Stage 0: qualified peer A computes P1(9)
    Native DAG commits the intermediate value and verified receipt
    Checkpoint saved; peer A service process terminates
    New coordinator reconstructs checkpoint without contacting peer A
    Stage 1: qualified peer B computes P2(prior committed value)
    Full Ground is checked at its requested output: 16

## Existing contracts reused

1. IPS-003's verified synthesized plan and native DAG compiler determine the ordered primitive word. No untrusted source text becomes executable code.
2. QualifiedStageHost binds an existing QualificationEndpoint, a verified QualificationPolicy and source-checked SAB-008 RealizationPolicy. It can use the existing per-request subprocess endpoint or a MutualTLSQualificationEndpoint. All endpoints must be explicitly provisioned and permitted.
3. The native VirtualLayerRuntime, OperatorRegistry and OperatorSpec expose one fixed deterministic/pure stage operator. Its trusted local handler uses SAB-008 FixedInterpreterRealizer; the existing HeadlessOS/Hypervisor checks the admitted virtual Ground, operator identity, capability and workload before invoking the host.
4. The generated DAG commits each stage with the predecessor scalar, primitive identity, SAB-008 receipt digest and native Hypervisor effect digest. No later stage can start until that dependency has committed.
5. The checkpoint retains the native DAG snapshot and historical stage reports. Recovery independently recalculates the affine relation for every stage, verifies retained SAB-003 qualification and SAB-008 receipts, rechecks typed Hypervisor workload/result digests, and demands equality with the native committed DAG snapshot. It does not contact earlier peers.
6. An identity Ground is committed without inventing a remote effect.

## Native verification

Tests cover distinct fresh subprocess workers, a new coordinator OS/Hypervisor after checkpoint reconstruction, and two separately launched mTLS peer services. The first peer process is really terminated before the next stage is dispatched through a newly qualified second peer. Both the peer's fixed-operation allowlist and origin Hypervisor are exercised.

Negative cases reject missing origin compute rights **before any peer invocation**, wrong-computation hosts at qualification, changed primitive or Ground, tampered observation receipts, self-consistently rehashed but numerically false DAG checkpoints, invalid checkpoint digests, wrong TLS DNS certificate identity, and changed virtual Ground.

Checkpoint checksums are **not signatures** and do not replace protected recovery high-water records, quorum fencing or independent attestation. Recomputed arithmetic is evidence of the Ground law, not proof that a remote physical location supplied the result. The mTLS experiment uses local loopback and short-lived generated certificates, not separately managed geographic machines. Active execution still consumes ordinary host CPU and network resources.

## Reproduce

    python -m pytest -q tests/test_qualified_generated_ground.py
    python -m pytest -q tests/test_qualified_generated_ground.py tests/test_generative_ground_construction.py tests/test_virtual_layer.py tests/test_ground_native_realization.py

Dedicated CI covers Linux/Windows on Python 3.11/3.13. OpenSSL is required for the mTLS case; if absent that test is explicitly skipped. No private key files are committed.

## Next research

Connect the recovered DAG to E-CPU's independently protected recovery-lineage high-water and quorum-fenced publication; rehome a failed peer via the authenticated computational-fabric directory, while rejecting late old-host publications. Measure actual message bytes, TLS setup and execution costs before claiming any efficiency advantage.

Related: IPS-001, IPS-002, IPS-003, SAB-003, SAB-008, Virtual Layer Runtime, Navigable Computation DAG, Federated Placement and recovery-lineage services.
