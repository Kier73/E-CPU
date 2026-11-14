# SAB-006 — Self-organizing Federated Grounds

**Status:** bounded, verified research bridge between native E-CPU discovery and SAB-004/SAB-005 adaptive placement. This is **not** uninvited Internet discovery, general fabric forwarding, hardware attestation, or independent-machine validation.

## Research question

Can a mathematical intention preserve its Ground and meaning while authorized peers arrive, change revision, become unavailable, and are replaced, without promoting peer advertisements into execution authority?

SAB-006 connects two existing mechanisms:

1. **Native control plane:** `ComputationalFabricDirectory` and optionally `ComputationalFabricDiscoveryService` maintain mutually authenticated, revision-monotone, receiver-locally leased peer snapshots. The directory's own checkpoint retains per-peer revision/digest high-water marks; it does not revive old remote leases.
2. **Behavior and realization:** SAB-003's `qualify` runs finite tests through a permitted endpoint; SAB-004's `AdaptivePlacement` composes qualified computational, framed-transport and retained-state roles under exact local grants; SAB-005's `MutualTLSQualificationEndpoint` and receiver-owned Hypervisor worker actually perform permitted network requests.

The new `SelfOrganizingFabric` reads **only** `directory.active_snapshots` to enumerate current candidates. In this initial profile **one peer ID corresponds to one SAB-005 host ID**. It does not derive executable operators from the snapshot's `hosts` advertisement, nor does it treat links as processors. A receiver-local endpoint factory binds each peer to a known SAB-005 TLS service; discovery and workload services may use distinct TCP ports. The factory must pin the same server DNS SAN and network host as the native peer snapshot. No remote peer can furnish executable source, a trusted client certificate, or its own local permission policy.

### Discrete reconciliation cycle

At logical coordinate `t`, one cycle:

1. Optionally asks the configured native discovery service to `refresh_all()` over authenticated direct-peer channels.
2. Reads the directory's active snapshots (receiver-monotonic lease time) and checks their identity, revision and digest high-water continuity.
3. Rejects identities missing from the local exact-operation grant catalogue; verifies the runtime endpoint host, TLS DNS identity and network host against native peer metadata.
4. Uses a **receiver-owned** `QualificationPolicy` to test only allowed roles. A changed peer revision requires new tests; an unchanged, still-valid profile can reuse its finite transcript. `force_probes=True` permits requalification after suspected failure.
5. Compiles a fresh SAB-004 typed placement from **current qualified** hosts. Host-independent `CompositeIntent.ground` and the expected mathematical result remain constant across placement changes.
6. On execution, revalidates the entire directory/qualification view before dispatch and again before acknowledging success. A changed view is refused. `resume` reads immutable committed evidence from a remaining qualified storage host, without rerunning pure computation.

The `FederatedView.fingerprint` contains the active peer revisions/digests, exact qualification report digests, local authority digest and logical coordinate. The selected `FederatedPlacement` additionally binds the exact SAB-004 plan and intention. This is content continuity evidence, **not** cryptographic evidence of physical execution. Native mTLS and the receiver Hypervisor retain their separate responsibilities.

## What changed from SAB-005

SAB-005 took a **fixed** list of five mutually authenticated receiver endpoints. SAB-006 instead re-creates the active list from native authenticated directory leases and current qualification, retains an anti-rollback high-water view, and invalidates stale plans when a peer revision, lease, or local authority changes. The same specialized roles can now be reassembled after controlled infrastructure changes.

The new test suite simulates five role-limited receivers and drives actual `ComputationalFabricDirectory` revision/lease/checkpoint state in CI. **The synthetic receiver class in that suite is explicitly not a TLS implementation or an independent process.** The dedicated CI separately reruns SAB-005's real mTLS and receiver-native Hypervisor tests, plus selected native directory tests (including real authenticated snapshot exchange). Their passing together is integration *compatibility evidence*, not yet one live end-to-end directory-to-worker TLS test across distinct machines.

## Security, correctness and scope

- **Observation ≠ authority.** A peer snapshot only permits the local controller to *consider* probing. `QualificationPolicy`, `PlacementAuthority`, and the receiving Hypervisor remain separately authoritative. A digest does not authenticate a source by itself.
- **Lease and revision safety.** Deadlines come from the native directory's monotonic clock; logical `coordinate` is separate. A directory restart restores revision high-water but no authenticated remote active set. SAB-006 additionally rejects decreasing observation coordinates and same-revision equivocation.
- **Reconfiguration.** An old plan is rejected after membership or grant changes. Replanning is an explicit new operation, never a silent reinterpretation of a former receipt.
- **Liveness.** An unchanged peer snapshot can outlive an unavailable data service until its lease ends; forced probes can exclude it earlier. A failed network execution is refused, not treated as success. There is no autonomous background monitor in this milestone.
- **Topology and physical transport.** SAB-004's typed cross-host carrier edges are currently logical controller orchestration; traffic to receivers uses SAB-005 direct mTLS, **not** the native `ComputationalFabricForwardingServer` over all advertised intermediate links. Native `ComputationalNetworkLink` claims are not proof of reachable data paths. This is an intentional next integration gate.
- **Recovery.** SAB-004 keeps immutable checkpoint and decision records and can recover from one live admitted storage replica without repeating computation. SAB-006 retains original replica identities in its in-memory qualified-host history. A brand-new controller must be supplied its historical peer bindings separately; restoring the native directory alone intentionally does not restore peer authority or old reports.
- **Effects.** Pure computation can be repeated. Storage is immutable by key but is not a general transactional consensus or exactly-once effect system. A membership change during execution may leave prepared data even though success is refused. Quorum-anchored recovery lineage is not yet connected.
- **Environment diversity.** Any permitted substrate able to implement this exact constrained ABI may later qualify. This particular demonstration uses software processes and synthetic unit hosts; passive cable/delay/DNS cannot be assumed to compute or provide durable storage.

## Verification

The dedicated workflow runs Python 3.11 and 3.13, compiles the package, executes all SAB-006 reconciliation tests, re-runs SAB-005 mutual-TLS/native-operator regressions, SAB-004 placement tests, and selected native directory authentication/revision/lease tests. The normal repository-wide verification gate is separate and may include existing unrelated failures.

### Suggested SAB-007

Bind this reconciler to `ComputationalFabricForwardingServer` and `ComputationalExecutionAdmissionCoordinator` for **actual** typed multi-hop execution. Persist controller lineage with E-CPU's `RecoveryLineageCoordinator`; test process/transport failure during a preparation/commit cut, simultaneous controllers and changed certificate identities. Then run on physically separate authorized machines and measure operational cost versus state navigation.