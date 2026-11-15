# GEOMETRY-TRANSIT-001 — Portable VGI basis on E-CPU hosts

Status: **experimental implementation and independent localhost-process evidence; actual E-CPU Transit/Hypervisor CI pending**.

## Goal

An observer first discovers a basis and proves that several typed operators
share independent invariant components. That observation should become a
**portable mathematical Ground** which another E-CPU host can verify without
re-running expensive commutant discovery. The receiving host should then
navigate the verified state at an arbitrarily distant *logical coordinate*,
subject to a finite exponent-bit budget, while the existing E-CPU hypervisor
and reliable Transit framework remain responsible for authorization,
committed effects, and recovery.

## Existing authorities reused

- VGI `CertifiedSimilarityBlocks`, `export_similarity_memory`,
  `admit_similarity_memory` validate the complete input factor snapshot,
  commuting witness, inverse, transformed blocks, and local products.
- E-CPU `OperatorSpec`, `VirtualLayerRuntime`, `HypervisorArbitrationEvent`
  and receiver-local capabilities authorize execution of the *pure* operator.
- E-CPU `TransitComputeHost`, `TransitBackendRouter`, `TransitComputeWorker`,
  `TransitComputeSession`, `ReliableChannel`, `RecoveryCheckpointBundleStore`
  and `RecoveryLineageCoordinator` remain the existing execution, transport,
  replay, checkpoint and quorum authorities. This experiment adds no second
  execution ledger.

The new `mailcpu.vgi_similarity_host.PinnedSimilarityCatalogue` is a
**receiver-local trusted configuration** of `(memory_sha256, graph_fingerprint,
record_bytes)`. Those pins must be provisioned by an independent E-CPU
admission/provenance decision. A peer cannot gain authority by transmitting
self-consistent JSON and a self-chosen hash. The catalogue mathematically
rechecks all records before exposing them to handlers. On restart a new
catalogue instance reconstructs those checks from trusted bytes.

A remote request includes precisely `schema`, `memory_sha256`,
`graph_fingerprint`, `initial` (typed vector), and `logical_tick`. Neither
untrusted Python code nor the mathematical record is carried as an executable
operator. The node-local `make_vgi_similarity_operator` returns an existing
E-CPU pure operator contract and a verifier-backed handler. E-CPU's scheduler
and budget policy apply to its work, while a separate **256-bit exponent bound**
limits mathematical logical time. The handler also requires the exponent's
bit count not exceed the workload's virtual tick budget.

## Physical-process experiment (executed locally)

`examples/vgi_similarity_transfer_process.py experiment`:

1. Producer PID discovers a common similarity basis for two dense operators
   over \\(\\mathbb F_{101}^6\\), with three hidden 2-dimensional invariant blocks.
   It produces a canonical 1,634-byte evidence record.
2. A separate receiver PID receives the record over loopback TCP. The
   controlling laboratory supplies the expected record and graph digests
   outside that TCP connection. The receiver independently proves the
   mathematical relationship without basis rediscovery.
3. Receiver navigates to logical coordinate \\(10^{30}+11\\), persistently
   publishes the record and result cut (`fsync` + atomic replacement +
   directory `fsync`) and is killed with `SIGKILL`.
4. A **different** receiver PID reconstructs the same mathematical
   certificate from durable bytes and reproduces the identical output and
   receipt digest. An independent dense-powering calculation agrees.
5. A deliberately byte-altered transfer fails before the cut is published.

**The standalone socket experiment is not E-CPU's `ReliableChannel` or a
quorum-committed execution replay.** The recovered mathematical state is
recomputed, not returned from E-CPU's previously committed effect ledger.
Loopback TCP in that experiment is not authenticated. The test controller's
out-of-band pin provisioning is a laboratory trust assumption, not a
production authority or signature.

## Stronger E-CPU integration test (awaits actual GitHub runner)

`tests/test_vgi_similarity_host.py` exercises the real `HeadlessOS`
hypervisor, authorized Virtual Layer operation, replay without handler
re-entry, wrong-pin refusal, typed frames, finite logical-time budget,
capability denial, and Transit operator contract identities.

`tests/test_vgi_similarity_transit_recovery.py` uses real E-CPU socket-based
`ReliableChannel`, `TransitComputeSession`, `RecoveryCheckpointBundleStore`,
three-member quorum lineage and `TransitVGISimilarityHost`. It freezes the
receiver **after** the E-CPU effect is committed, seals requester and receiver
checkpoints, kills that process, restores a fresh receiver PID, resends the
still-pending request, and asserts the same committed effect is replayed with
**zero backend re-entries**. This tests a stronger mechanism than the local
socket-only prototype, but it is not yet observed passing on GitHub CI.

The dedicated `.github/workflows/vgi-similarity-transit.yml` pins the
experimental VGI dependency to
`30732bc4ba42c9555ab30fad21eb7b3778fb966b`, the GEOMETRY-FIRST-008
feature branch commit, leaving E-CPU's existing default `vgi` extra
untouched while the upstream VGI PR stack is unmerged.

## Local reproduction

The producer/receiver experiment requires experimental VGI PR #31 (and its
ancestors) installed into Python. In its checked-out interpreter:

```bash
python examples/vgi_similarity_transfer_process.py experiment
python examples/vgi_similarity_transfer_process.py negative
```

The actual E-CPU tests additionally require E-CPU source and its full native
modules. From the E-CPU repository root after installing that pinned VGI:

```bash
python -m pytest -q tests/test_vgi_similarity_host.py tests/test_vgi_similarity_transit_recovery.py
```

## What remains in development

- GitHub Actions has been returning queued without conclusions for the
  GEOMETRY-FIRST-001 through 008 PR stack. The E-CPU integration job has
  not yet established a passing hardware/runner result.
- Actual host-to-host authenticated mTLS transport and federated allocation
  across different machines have not been demonstrated here. The present
  physical trial involves independent processes and localhost TCP.
- Production admission of a portable record into E-CPU structural-memory
  revisions and an authenticated provenance/authorization decision is not yet
  implemented. This experiment requires a trusted receiver-local catalogue.
- The source manifest hash is for implementation identity, not hardware
  attestation. Mathematical proof does not assert that a physical host
  correctly realizes its model without independent observation.
- The mathematical record includes all original factors. Discovery can be
  expensive and verification still costs work proportional to the admitted
  coefficients. The savings concern **not repeating expensive basis search**,
  not compressing arbitrary matrices without loss.