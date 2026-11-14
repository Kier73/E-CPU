# SAB-007 — Native forwarded Ground continuity and recovery-lineage cut

**Status:** experimental native-API bridge. Builds on merged SAB-004/005 and E-CPU's existing Computational Fabric and Recovery Lineage; it does not silently replace either. SAB-006's separate reconciliation PR remains an optional upstream source of current observations. This stage does **not** establish independent hardware placement or Byzantine resilience beyond the fixed-membership lineage policy.

## Question

Can one E-CPU computational intention remain stable as a native authenticated multi-hop route changes, and can its accepted observation be reconstructed from a quorum-sealed state artifact without re-running computation?

The bridge is intentionally conservative:

1. The **intention** is an existing `CompositeIntent`, whose `fingerprint`, `ground`, and `input()` are independent of placement.
2. A native `ComputationalAddress` carries an exact matching workload `input_value`, computational-Ground fingerprint, and `intention["goal"] = {"kind":"sab007.affine","intention": <fingerprint>,"ground": <ground>}`. Native `OperatorSpec`, `VirtualLayerWorkload`, and runtime are installed locally by the actual participating E-CPU hosts; this module never downloads or installs code.
3. `ComputationalFabricResolver.resolve_candidates` evaluates active receiver-local directory leases and ranks routes. A separate *exact receiver-local allowlist* filters eligible `(peer_id, host_id)` pairs. A route is **non-authoritative**.
4. Only an actual `ComputationalFabricForwardingClient`, with a verified adjacent-peer mTLS transport and an existing `ReliableChannel`, dispatches the `ComputationalFabricForwardingEnvelope`. The target `ComputationalFabricForwardingServer` must separately revalidate and execute through its local `ComputationalExecutionAdmissionCoordinator`/Hypervisor.
5. The bridge reconstructs every forwarding hop from the original envelope and checks the complete native `ComputationalFabricHopReceipt` chain, the terminal accepted execution, operator contract, Virtual Ground and the independently navigated mathematical output. It re-resolves the route after delivery. A changed directory, missed acknowledgement, failed Hypervisor authorization, or unverified output is **not** acknowledged as success.
6. The caller places the accepted canonical evidence bytes into `AtomicGroundEvidenceStore` (fsynced content address) and submits the root via **native `RecoveryStateManifest` and `RecoveryLineageCoordinator.seal`** to the configured majority. Only a verified quorum result is an accepted recovery state. A minority-prepared root is not a commit, and a later generation makes an older root stale. `recover_native_result` verifies both the authoritative high-water quorum and the exact source/route/observation evidence without contacting the original compute host.

## Experiment and falsifiers

`tests/test_federated_ground_continuity.py` constructs **native directory, operator, address, route witness, hop receipt, and recovery-lineage objects** and tests a two-hop route, remote host re-placement at a higher origin sequence, unchanged mathematical Ground, generation fencing, local allowlist refusal, revision movement, mid-flight topology change, malformed result, failed quorum, corrupted storage and changed mathematical intention. The test's forwarding network operation is deliberately a controlled fake for rapid deterministic exploration; it is **not an authenticated socket proof**.

The CI job independently exercises E-CPU's existing full native `test_federated_workload_forwards_over_two_authenticated_hops_and_replays_once` TLS/Hypervisor test, and the existing recovery lineage tests, in addition to the new bridge tests. Passing separate tests is **compatibility evidence**, not a claim the newly introduced bridge was itself observed inside the live TLS fixture. An end-to-end harness that directly invokes `NativeGroundDispatcher` over the real native forwarding client is the next integration gate.

### Explicitly unsupported conclusions

- A digest or an advertised host does not grant computation rights. Origin allowlists are not receiver authority.
- Quorum participant journals on the same CI machine establish separate durable files and majority semantics, not independent machine failure domains or Byzantine consensus.
- Re-submitting a *pure* request to a new host may repeat physical work. The new origin sequence fences assignment identity but this does not provide general exactly-once effect safety.
- A state artifact is local content-addressed data. This module does not automatically replicate the artifact to arbitrary networks, and a lineage proof does not itself store those bytes.
- A planned path is rejected if stale, but external effects already made before refusal are not rolled back.
- The verified arithmetic law is the bounded affine family used by SAB-004; general computational equivalence requires additional Ground-specific contracts.

## Next gate

After native CI passes, connect SAB-006's continuously requalified active view to this bridge and run the exact route with a real `ComputationalFabricForwardingClient` inside an independently launched origin, relay and destination process deployment. Interrupt at transport ACK, before/after quorum commit, and after controller restart. Then run with explicitly authorized geographically or physically independent machines and measure state navigation, transport, admission, persistence and verification costs separately.