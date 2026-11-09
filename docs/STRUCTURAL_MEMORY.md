# Adaptive Structural Memory Service (E0 / E0.2 / E0.3)

## Purpose

The Structural Memory Service is the first executable layer of Adaptive Structural Emulation. It stores a verified generative description of a state family rather than requiring every state to be materialized. E0 defines the generator, evidence, read and revision contracts; E0.2 connects those records to the HeadlessOS checkpoint and the kernel's hash-chained event journal; E0.3 adds context-only revisions and exact revision-pinned historical reads.

A structural memory version binds:

- a stable memory identity and immutable revision;
- a typed generator family and its canonical parameters;
- a domain label;
- exact context/boundary metadata;
- a verification certificate tied to the spec and context digests;
- a parent digest linking the revision to its predecessor.

The service is built above MailCPU's existing transition and law-certification code. It does not change the meaning of MailCPU instructions, create a second interpreter, or grant execution authority.

## E0 implementation boundary

The first registry admits only four existing deterministic law families:

| Family | Representation | Runtime navigation |
|---|---|---|
| int | Integer arithmetic progression, optionally modular | Existing guarded arithmetic-law navigation |
| lcg | Affine modular recurrence | Existing guarded affine recurrence navigation |
| gf2 | Linear recurrence over GF(2) | Existing guarded LFSR jump |
| fgraph | Finite orbit with a pre-period and cycle | Existing guarded orbit projection |

The registry rejects kreg, mixtures, arbitrary callables, generated Python, FITTED, and TAPE laws in this stage. Those are not declared invalid mathematical objects; they are simply outside this E0 admission contract.

The generator registry validates each family's exact parameter shape before reconstructing a Law. This avoids turning a memory description into an unrestricted code-execution mechanism.

## Objects and responsibilities

### StructuralMemorySpec

An immutable, canonical description of the generator, domain, context, revision, and parent. The digest covers all of those fields. Parameter and context dictionaries are stored internally as canonical JSON strings; accessors return detached copies.

### StructuralMemoryCertificate

A separately digest-addressed evidence object bound to the exact spec and context. It carries the witness digest, witness count, generator identity/version, and verification class.

The certificate is not a universal proof. It records the precise finite evidence that was replayed.

### GeneratorRegistry

A closed adapter registry over the four existing law families. It uses the law-certifier's guarded navigation interface for all runtime state reads.

### ContextMapper

E0 binds context as an exact boundary identity. The context object is canonicalized and hashed; a read under a different context is refused. E0.3 permits a new immutable revision to bind the same generator to a different context after fresh supplied witnesses are replayed. It does not map context fields into generator parameters; that form of adaptation remains deferred.

### StructuralMemoryVerifier

Reconstructs the deterministic law from the spec and independently replays the supplied observations before issuing a certificate. A staged proposal is rechecked again at admission.

### StructuralNavigator

Checks spec/certificate correspondence, context identity, coordinate type, and any prefix horizon before navigating to a state.

### StructuralMemoryRegistry

Owns staged proposals and active immutable versions. It provides propose, propose_trace, admit, and read.

## Proposal and admission sequence

A law may be supplied directly, or recovered from an observed training window and a withheld suffix:

1. STRUCTURE_PROPOSE / StructuralMemoryRegistry.propose_trace calls the existing recover_law routine.
2. The registry only proceeds when recovery returns GROUND or PREFIX-GROUND within the admitted family whitelist.
3. It replays all supplied observations against the candidate generator.
4. It stages an immutable proposal and certificate. No active memory changes.
5. STRUCTURE_ADMIT / StructuralMemoryRegistry.admit compares the candidate's parent and revision against the caller's expected active revision.
6. A trusted host-supplied admission policy must return the literal Boolean True.
7. The registry re-verifies the certificate and only then installs the new active version.

The admission callback is an authority boundary supplied by trusted host code. A model or a proposal cannot authorize itself. With no callback configured, admission fails closed.

Two competing proposals created against the same active revision cannot both win: after one is admitted, the other fails its parent/revision compare-and-swap.

### Context-only adaptation (E0.3)

`StructuralMemoryRegistry.propose_context_revision(memory_id, context, witnesses)` stages a new revision from the currently active revision. It does not accept a replacement `Law` or new generator parameters. The candidate is constructed by copying the active specification and changing only:

- `revision`, incremented by one;
- `context_json`, replaced by the canonical new context;
- `parent_digest`, set to the active specification digest.

The generator family, canonical parameters, order, domain, law verdict, and prefix horizon are therefore preserved by construction. A request that supplies the same canonical context is refused. The new witness mapping is replayed against that unchanged generator; a mismatch refuses the proposal. Proposal remains non-authoritative until the normal host admission policy and revision compare-and-swap both succeed.

The new witness set is newly supplied and independently replayed by the verifier. This is not proof of the external origin or independence of the observations; provenance of the observation source remains the caller's responsibility. A context-only revision proves only that the same admitted law agrees with the supplied observations under the new exact context.

`read()` always resolves the active revision. E0.3 also provides `read_revision(memory_id, revision, coordinate, context=...)`, which requires an exact admitted revision number and its exact context. This lets a caller explicitly replay an older immutable context after a newer revision becomes active. Such reads emit `structural_memory.read_revision` events; ordinary active reads continue to emit `structural_memory.read`. Restore verifies both event types against the referenced historical version and its generator. The ordinary active-read chronology rule remains unchanged.

## Evidence and horizons

The existing law certifier uses GROUND, PREFIX-GROUND, FITTED, and TAPE. The Structural Memory Service maps only the first two into admitted evidence classes:

- WITNESS_GROUNDED: every coordinate in the supplied witness set matches the deterministic generator. This is finite witness agreement, not a proof for every possible coordinate.
- PREFIX_GROUNDED: all supplied observations before first_bad match, and a witness at first_bad demonstrates escape from the proposed law. The valid coordinate interval is strictly t < first_bad.

FITTED and TAPE cannot be admitted. For a prefix-grounded memory, a read at or beyond the exclusive horizon is refused. The implementation uses the raw law evaluator at exactly first_bad only while checking the escape witness; runtime reads always use navigate_guarded.

Verification status travels with every read receipt. Consumers should not strip the verification class, witness digest, spec digest, or context digest when forwarding a generated value.

## Read contract

STRUCTURE_READ / StructuralMemoryRegistry.read(memory_id, coordinate, context=...) returns a StructuralMemoryReadReceipt containing:

- the integer value;
- memory identity and revision;
- spec and certificate digests;
- the coordinate and context digest;
- a value digest;
- verification class and witness digest;
- deterministic receipt identity and cache-hit indication.

Coordinates must be non-negative integers; Boolean values are rejected even though Python treats Booleans as integers. Context must exactly match the context bound to the active revision.

The receipt is provenance for a structural read. It is not an execution grant, hypervisor authorization, CPU retirement event, or proof that an external machine has been mutated.

## Persistence and replay (E0.2)

The HeadlessOS now owns one StructuralMemoryRegistry instance, exposed as os.structural_memory. Its registry state is part of the same composite checkpoint graph as the VM, services, hypervisor policy, arbitration ledger, seed admission, and kernel journal.

The registry snapshot contains:

- all staged proposals, including immutable specifications, certificates, and finite witness sets;
- all admitted proposal identities and historical immutable versions;
- the active revision head for every memory identity;
- canonical read-cache receipts;
- a journal anchor (sequence, terminal_digest) identifying the exact event-chain cut.

The shared kernel event journal records these event kinds:

- structural_memory.propose;
- structural_memory.admit;
- structural_memory.read;
- structural_memory.read_revision for explicitly pinned historical reads (E0.3);
- structural_memory.read_revision_range for bounded, ordered, explicitly pinned range reads.

Point reads retain their original one-coordinate receipt and event contract. A range read evaluates its coordinates under one reconstructed law instance, returns the ordered per-coordinate receipt IDs to its caller, and appends one compact range receipt. The range receipt binds the immutable revision, exact context, coordinate start and length, a digest of the ordered generated values, and a digest of the ordered value-receipt IDs. Restore re-evaluates the range against the admitted generator and verifies both digests. It compresses the durable journal representation without removing per-coordinate identity from the returned file-read receipt or relaxing generator/certificate validation.

A repeated exact proposal returns its original staged proposal and does not create another proposal event. Exact admission replay returns the original version and does not create another admission event. Reads produce a journal receipt even when the value is served from the structural read cache.

A composite HeadlessOS snapshot holds the registry transition lock while it captures the VM and registry state. The registry checks that the live event journal is byte-for-byte equal to the journal projection already captured inside the VM snapshot. If the journal changes between those two captures, checkpoint creation fails rather than publishing a split registry/journal cut.

Restore verifies the kernel journal hash chain through the existing kernel restore path. The structural registry then:

1. reconstructs every typed specification, certificate, proposal, version, and cached receipt;
2. replays every proposal witness set against the exact deterministic generator;
3. checks contiguous revision numbering and exact parent-digest lineage;
4. verifies that each active head points to the latest admitted version;
5. reconciles every proposal and admission event with its registry record;
6. replays every journaled active or revision-pinned read receipt and checks its generator value, context, certificate, and receipt identity;
7. requires the saved journal anchor to equal the restored kernel journal tail.

This makes staged proposals and active structural memories continuation-capable across a HeadlessOS process restart. It does not turn the registry into a multi-host consensus service or make the checkpoint atomic with arbitrary external effects.

In-place OS rollback is also a registry rebind boundary. When a rollback replaces the VM and kernel journal, HeadlessOS replaces the registry with the instance reconstructed from the same snapshot, ensuring that the registry points to the restored journal rather than the discarded journal object. The original trusted host admission callback is rebound from the live host object; it is not read from snapshot data.

System-seed projection deliberately removes `hypervisor.seed.*` control events before computing its canonical origin digest. Because the structural-memory snapshot carries a duplicate journal anchor, the seed projection recomputes that anchor from the same filtered and re-chained kernel journal. This preserves the existing seed-admission equivalence relation while retaining structural-memory proposal, admission, and read events in the seed state.

### Host policy is not checkpoint state

admission_policy is trusted executable host configuration. It is never serialized, hashed into the memory specification, or reconstructed from checkpoint data. A restored HeadlessOS can read previously admitted memories and can inspect staged proposals, but a new admission fails closed until trusted host code explicitly supplies a policy again:

    restored = HeadlessOS.restore_checkpoint(
        checkpoint_path,
        structural_memory_admission_policy=trusted_policy,
    )

Older checkpoints without a structural_memory field remain readable only when their kernel journal contains no structural-memory events. Removing the registry projection from a checkpoint whose journal contains structural-memory events is refused.

### Current persistence boundary

The registry's proposals, versions, read cache, and event receipts persist as part of the local HeadlessOS checkpoint. This is local checkpoint recovery, not a distributed registry or an atomic transaction spanning remote stores and external side effects. Multi-host replication, durable effect coupling, context-to-generator-parameter adaptation, heterogeneous generator composition, distributed page-store replication, writable shared file mappings, CPU macro-transitions, and neural operators remain later stages.

## Example

    from mailcpu.structural_memory import StructuralMemoryRegistry

    training = [(65500 + 17 * t) % 65536 for t in range(30)]
    withheld = [(65500 + 17 * t) % 65536 for t in range(30, 40)]

    registry = StructuralMemoryRegistry(
        admission_policy=lambda proposal: proposal.spec.domain == "integer-orbit"
    )
    proposal = registry.propose_trace(
        "counter-orbit",
        training,
        withheld,
        context={"source": "example"},
    )
    active = registry.admit(proposal.proposal_id, expected_revision=0)
    result = registry.read("counter-orbit", 1000)

The example uses a modular progression; actual candidate admission still depends on what the law certifier and withheld witnesses establish. Applications should choose a domain and observations that match the actual process semantics.

## Explicit non-goals and next stages

E0.3 adds context-only revisions while retaining the E0.2 local checkpoint and journal path. It still does not:

- adapt context fields into changed generator parameters;
- use learned models to prioritize or propose generator families;
- compose heterogeneous generators or coordinate systems;
- general-purpose mutable file-backed mappings or paging of arbitrary filesystem/device state;
- perform CPU instruction macro-transitions or change native vCPU state;
- execute model weights, recurrent state, or neural operators.

Those require their own typed contracts, checkpoint/replay obligations, authority rules, and differential or trajectory-level conformance tests.

Further work should keep broader context-to-parameter maps behind an explicit transformation contract. Distributed page-store replication, writable shared file mappings, and CPU macro-transitions remain separate stages with their own correspondence, authority, persistence, and recovery obligations.

## Test scope

The conformance suite covers proposal staging, host authorization, revision compare-and-swap, immutable parent lineage, canonical context binding, context-only adaptation with generator identity preservation, active and revision-pinned reads, journal replay, witness replay, prefix escape/horizon behavior, trace-based law recovery, and each admitted generator family. These tests establish the implemented finite contract; they do not certify universality or performance beyond their measured domains.


## Virtual Layer operator bindings

Virtual Layer workload schema v2 can carry an operator-scoped address into an admitted structural-memory revision. The address binds memory identity, immutable revision, exact context, coordinate, specification digest, and certificate digest. It carries no generator or executable material.

The receiving Virtual Layer runtime performs the read only after the existing hypervisor has authorized the operator operation. Its local authority process must independently hold `read` on `/structural-memory/read`. The runtime calls the receiver's existing `StructuralMemoryRegistry.read_revision`, checks the complete receipt against the pinned address, and presents the operator with the integer value alongside the full receipt. The operator result includes those receipts and a digest of the resolved input.

The workload's canonical digest binds the references. The existing hypervisor semantic execution ledger therefore replays the original effect for an exact semantic retry without invoking the memory backend or appending a second read event. Structural-memory registries remain receiver-local: this integration does not replicate revisions, transfer generator descriptions, or authenticate the external origin of the original witnesses.

See `docs/VIRTUAL_LAYER_WORKLOAD.md` for the workload schema, operator input envelope, byte-budget rules, and tested integration path.


## VFS file provider

A structural-memory revision can be explicitly exposed as a bounded, read-only virtual file. `StructuralMemoryFileRef` binds the memory identity, immutable revision, exact context, coordinate start, byte length, specification digest, and certificate digest. Byte offset `o` maps to generator coordinate `coordinate_start + o`.

The first provider contract uses one unsigned integer value per byte. The receiver refuses any value outside `0..255`; it never truncates, wraps, or silently converts a wider integer. File size is bounded to 1 MiB and each read is bounded by a configurable maximum (4 KiB by default). Reads are lazy: only coordinates in the requested byte range are resolved. The provider uses the registry's bounded `read_revision_range` operation when available; the registry evaluates the ordered coordinates with one reconstructed law instance and returns the per-coordinate receipt IDs plus a compact range receipt. Older local registry adapters that expose only `read_revision` continue to use the coordinate-read fallback. The provider checks the range receipt's identity and both aggregate digests before exposing any byte.

The VFS inode is registered as a read-only provider-backed file. Normal VFS path/mode and process-open authorization remain the file-access boundary. Host-side callers can use `VirtualFileSystem.read_file_with_receipt` to receive the bytes and aggregate range receipt together; ordinary read calls continue to return bytes only. The range receipt binds the returned byte digest, context, specification, certificate, and ordered coordinate receipt IDs. Provider cache entries contain only values already verified against those receipts.

Filesystem checkpoints serialize the symbolic file reference and read limit, never a registry pointer or executable callback. On `HeadlessOS.from_snapshot`, the host first restores the structural-memory registry from its checked snapshot and then rebinds the inert provider descriptors to that local registry. The host admission policy remains non-serialized, as before.

## Structural-memory demand paging

`StructuralMemoryPageBacking` implements the existing `PageBacking` protocol. It does not introduce a second memory manager: `VirtualMemory` continues to own virtual page numbers, resident quotas, page reservations, permissions, content hashes, and copy-on-write transitions.

A host registers one page by pairing its expected SHA-256 content hash with a `StructuralMemoryFileRef` whose size is a power of two from 1 through 65,536 bytes:

```python
import hashlib

page = b"ABCDEFGH"
digest = hashlib.sha256(page).hexdigest()
reference = StructuralMemoryFileRef.from_version(
    admitted_version,
    coordinate_start=0,
    size=len(page),
)
os.register_structural_memory_page(digest, reference)
memory.reserve(
    start=0,
    length=len(page),
    backing_blob_ids=(digest,),
)
```

Each page reference is a complete pinned byte interval. On first access, the backing reads that interval through the existing structural-memory file provider. The provider resolves the interval using one bounded range operation when supported, checks the range receipt's revision/context/specification/certificate identity and aggregate value/receipt commitments, and verifies `SHA256(page_bytes) == page_digest`. The caller still receives the ordered per-coordinate receipt IDs; the shared journal stores one replay-verifiable range event rather than one event per byte. A successful materialization moves the same digest from `PageReservation.backing_blob_id` to `PageMapping.blob_id`. The structural reference is not replaced by a newly generated page identity.

The memory manager resolves every externally backed page touched by one access before consuming any reservation. If a later page cannot be read or fails its hash check, no reservation in that access is materialized. Resident admission and the existing per-process page quota are checked before resolution; ordinary page read/write protections remain in force.

Writes preserve the existing copy-on-write rule. A write to a reconstructed page creates a new content hash in the writing memory image; the original structural page hash and reference remain immutable. If the changed page is later reclaimed, the backing persists its bytes as local page content so it can be restored independently of the structural generator. Structurally backed original pages remain symbolic rather than being copied into that local content store.

The backing exposes the last structural range receipt for a page through `read_receipt(digest)`. Page references and locally persisted non-structural pages are included in the backing snapshot; registry pointers, provider callbacks, and admission policy are not. `HeadlessOS.from_snapshot` restores the page backing as an inert descriptor and binds it to the restored local structural-memory registry before normal operation resumes.

This first contract is deliberately bounded: a structural page reference must describe exactly one power-of-two page no larger than 64 KiB. It supports demand reads and private COW writes; it does not yet add writable shared file mappings, page-table sharing across hosts, distributed page-store replication, or automatic page eviction policy.
