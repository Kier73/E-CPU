# GEOMETRY-TRANSIT-003 — Native revision recovery through E-CPU's committed effect ledger

**Status:** source and CI gate implemented; full E-CPU runtime/CI execution outstanding. Do not claim that this test passed solely from the mathematical local harness.

## Decisive experiment

The prior E-CPU Transit recovery gate used a receiver-local *separately provisioned* `PinnedSimilarityCatalogue`. The next frontier is to prove that **E-CPU's own journal-backed StructuralMemoryRegistry** is the mathematical record holder throughout the receiver's crash and recovery, while E-CPU's existing hypervisor and quorum-backed execution ledger remain the sole authorities for effect replay.

This is a dedicated real-process test and worker, not a second transport or replay implementation:

- `tests/helpers/vgi_similarity_native_continuity_worker.py` replaces only the *receiver's backend factory* in the established Transit/VGI semantic-continuity worker. The original reliable operation/result channels, `TransitComputeSession`, `RecoveryCheckpointBundleStore`, quorum lineage, and after-commit cut remain unchanged.
- The initial receiver obtains VGI record bytes and digests through an **out-of-band trusted test fixture**, revalidates the full mathematical certificate, and admits the bounded record into its **own StructuralMemoryRegistry** as revision 1 through the registry's existing trusted policy, parent lineage and journal.
- The receiver's worker PID has **both** `/virtual-layer/operators:compute` and `/structural-memory/read:read`. The peer request contains only the ordinary `vgi.similarity.navigate` operation and its typed mathematical address/vector/tick. It cannot install new record bytes or grant itself rights.
- The original E-CPU execution obtains one native **journaled** `structural_memory.read_revision` receipt for the exact pinned revision and exposes that index-only read in its full mathematical effect. VGI's similarity proof is verified separately; the E-CPU integer index law **never masquerades as a matrix proof**.
- After a quorum-backed **post-commit** checkpoint cut, the test **kills the original receiver** and **deletes the original provisioned record file**. This explicitly excludes reconstructing the mathematical memory from the original external catalogue.
- The restored process reloads only the quorum-sealed E-CPU receiver checkpoint and its **separately trusted revision identity pin**. The new native backend resolves the record from the **restored HeadlessOS structural-memory registry**. It cannot reach the deleted source file.
- The still-live sender retransmits its pending frame over reattached E-CPU reliable channels. The restored process must return **exactly** the previously committed effect and native index-read receipt. Its backend-entry count at replay must remain **zero** and the existing execution commit must remain intact.
- The still-live sender then submits a **new event with a different workload, start vector, logical tick and sequence**. The restored receiver must independently reverify the record from its own checkpointed registry, execute that new operation **once**, and match independent dense powering. Its native read journal count advances from one to two, execution commit count from one to two, and replay count stays one. The test explicitly disables the VGI basis-search function while this new request is running, so the result must come from the stored representation, not rediscovery.

## Proof and operational scope

Passing this test would establish process-level durable *effect replay* and memory-retention, not a new physical network cryptographic transport attestation. The source record and trusted mathematical digests are provisioned by the fixture; production authority/provenance to choose those pins remains the responsibility of E-CPU's host and fabric policies. E-CPU's StructuralMemoryRegistry certifies the revision and index relation; VGI certifies the exact matrix algebra. Neither content SHA nor independently correct mathematics asserts that an arbitrary remote observer is trustworthy.

The restored receiver does **not** rerun the backend to verify its mathematical proof when serving an already committed effect; replay relies on the sealed E-CPU ledger. The **second, fresh request** must independently resolve and reverify the native mathematical revision and execute the VGI navigation. Both distinct semantics are tested.

## Local checks vs. integration

The new helper and test compile under the available Python runtime, and VGI's existing standalone mathematical tests can be run from its local source bundle. This sandbox does **not** have the complete E-CPU package installed or GitHub network connectivity, so the actual end-to-end native-Transit test cannot currently be asserted as passing here. The GitHub Actions workflow includes this test for Python 3.11 and 3.13 alongside its pre-existing standalone laboratory, Virtual Layer, native revision and external-catalogue post-commit recovery tests.

### Reproduction (E-CPU with GEOMETRY-FIRST-008 dependency)

```sh
python -m pytest -q -v tests/test_vgi_similarity_native_transit_recovery.py
python -m pytest -q -v tests/test_vgi_similarity_host.py tests/test_vgi_similarity_native_memory.py tests/test_vgi_similarity_transit_recovery.py
```

### Explicit negative controls

1. Assert the provisioning record was deleted before the restart while replay still returns the identical effect.
2. Assert the effect retains E-CPU native spec, certificate, context, index read receipt and mathematical record identities.
3. Require a distinct receiver PID, zero backend re-entry **for replay**, exactly one *original* committed execution, one replay, and matching bundle manifest.
4. Require one further native backend entry for the new request, two total committed effects, exactly two native index-read events and no rediscovery, with no original external record file present.
5. Existing native host unit tests separately reject missing read capability, forged hashes, stale native revision and unauthorized admission.

## Next development after CI passes

Extend the verified two-phase recovery trace across real authenticated multi-node routes and producer/receiver machines, retaining independent authority over the mathematical Ground and the committed effect. First confirm the existing E-CPU job matrix and native-Transit integration results are green; the code is not yet a passing physical-host proof.