# LENS-003 — Evidence-preserving topology changes for navigable Grounds

**Status:** dependent integration experiment built on [LENS-001](LENS_GROUND_001.md)
and [LENS-002](LENS_GROUND_002.md). Native object contracts, terminal Hypervisor
execution, authenticated-ingress directory snapshots, Structural Memory journal
reads and durable quorum are exercised. The LENS-003 topology harness swaps only
first-hop network I/O for a controlled stub; the repository's separate native
mTLS suites test actual encrypted forwarding. Full CI must pass before the
integrated behavior is reported as independently verified.

## Previous work reused

LENS-003 deliberately avoids another router, native execution engine, claim
authority, Ground store or consensus protocol.

- **SAB-007:** `NativeGroundDispatcher` now exposes its shared
  `prepare_route`/`execute_route` route-and-live-topology checks;
  `_verify_receipt_chain` checks the exact native hop-cursor tree;
  `AtomicGroundEvidenceStore` persists canonical immutable evidence.
- **E-CPU Virtual Layer:** `VirtualStructuralMemoryRef` binds
  `(memory_id, revision, context, coordinate, spec_digest, certificate_digest)`;
  receiver `VirtualLayerRuntime` checks local `/structural-memory/read`
  capability before calling the existing revision-pinned read API.
- **E-CPU Structural Memory:** the original journaled verifier, witness
  certificate, revision and `StructuralMemoryReadReceipt` are authoritative;
  no second law evaluator is installed on the receiving host.
- **E-CPU Recovery Lineage:** the original `RecoveryLineageCoordinator`,
  `RecoveryStateManifest` and durable quorum journals seal exactly the
  verified native hop and Structural Memory receipt bytes, with rollback
  rejection by the quorum high-water.
- **LENS-001/002:** the origin independently replays a compact lens certificate
  and evaluates the same distant coordinate via an independent binary affine
  composition oracle. The LENS-002 mTLS test remains the live TLS identity gate.
- **IFS CAG/GCI and VGI geometry/similarity:** relevant independent-
  representation experiments, not assumed to confer network authority or
  universal law proof. See their own CI and evidence records.

## Formal seam

Let `P` denote the finite-witness-certified Structural Memory lens law,
`v` its admitted revision, and `t` a strictly bounded logical coordinate.
LENS-003 binds the host-independent intention

`I = H(request_id, proposal_id, spec_digest, certificate_digest, t, observer=value)`

to a native `ComputationalAddress` with a single fixed pure
`lens.fabric.read` operator. The workload contains only the exact typed
memory address; the receiver must **already** have admitted `v` under its
trusted local policy. No remote request carries a generator implementation,
admission authority, Python source or complete trajectory.

The admitted operation is:

```text
Origin: LENS-001 witness-grounded proposal and independent expectation
  |
  v
Native Computational Fabric directory (authenticated leases)
  | choose multi-hop path via SAB-007; old route is non-authoritative
  v
E-CPU forwarding envelope and digest-linked peer-hop receipt chain
  | terminal resolves its own local ComputationalHostLocus and Hypervisor
  v
VirtualLayerRuntime -> receiver StructuralMemoryRegistry.read_revision
  | emits exact journal-backed StructuralMemoryReadReceipt
  v
Pure lens.fabric.read operator -> {"value": admitted_revision_at(t)}
  | result effect includes exact read provenance and operator contract
  v
Origin independent verifier:
  * reconstruct all hop cursor and operation identities
  * require terminal admitted and executed
  * re-derive mathematical value by separate binary affine composition
  * reconstruct read receipt_id and value_digest from pinned revision
  * validate entire effect, resolved-input digest, Ground and result digests
  * re-evaluate live directory and route lease after return
  |
  v
Content-addressed evidence store -> original RecoveryLineage quorum
  | no successful quorum: no accepted recovered state
  v
Quorum-current state recovery; stale generations refused, no re-execution
```

The exact `spec_digest`, `certificate_digest`, `witness_digest`, and
`intention_digest` remain fixed as route selection changes. The peer
route digest and execution-receipt digest are allowed to differ. A content
digest identifies bytes, not the identity or trustworthiness of a host:
mTLS identity must be established by the native transport when live.

## Tests and negative controls

`tests/test_lens_fabric_continuity.py` exercises:

1. Real native receiver-local Hypervisors in two independent HeadlessOS objects,
   both admitting the same exact LENS-001 Structural Memory proposal;
2. Three-peer native hop receipts, with the original directory resolver choosing
   `peer-a -> peer-b -> peer-c`, then rehoming to `peer-d` while the intention
   remains unchanged and the terminal read is independently rechecked;
3. Actual RecoveryLineage majority sealing on three durable journal files:
   generation 2 supersedes generation 1; recovery of old proof is refused;
4. Changed authenticated peer lease before dispatch and during a successful
   terminal reply: neither becomes a verified current-route result;
5. Mutated Structural Memory receipt and a changed mathematical intention:
   neither is accepted despite otherwise valid route topology;
6. Corrupted persisted evidence and mismatched replay intent: both refused;
7. Recovery does not invoke a receiver, rerun the law or regenerate output.

The first-hop transport in this particular test is a controlled fake;
**real mTLS multi-hop routing with this exact operator remains a separate
integration gate**. Do not present the harness as proof of independent
hardware, remote provider domains, exact generalized model inference, or
universal mathematical conformance. This Ground's certification is finite
witness evidence over the selected descriptor, not an infinite-state proof.

## Reproduction

```sh
python -m pytest -q tests/test_lens_ground.py tests/test_lens_native_fabric.py tests/test_lens_fabric_continuity.py
python -m pytest -q tests/test_federated_ground_continuity.py tests/test_virtual_layer_structural_memory.py
python -m pytest -q tests/test_computational_fabric_forwarding.py
python scripts/verify_repo.py
```

## Next integration gates

1. Supply a real mTLS multi-hop transport for the LENS-003 workload, using
   `ComputationalFabricForwardingServer` and actual receiver-local
   `ComputationalHostCatalogue`, rather than the controlled first-hop stub.
2. Attach the existing `TransferableExecutionClaimStore` to each pure lens
   request and exercise **claim assignment epochs**, not merely result-lineage
   generations, for stale-runner publication fencing.
3. Recover a killed receiver's **admitted Structural Memory and Hypervisor**
   journal from a quorum-sealed checkpoint, as already pioneered by
   GEOMETRY-TRANSIT-003; verify no repeat of the committed semantic effect.
4. Extend representation refinement and independent oracle selection to VGI
   polynomial lifts and IFS GCI equivalence, rejecting candidate transformations
   that cannot satisfy exact observer projection invariants.
