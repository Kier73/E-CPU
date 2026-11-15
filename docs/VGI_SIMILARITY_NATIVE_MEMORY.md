# GEOMETRY-TRANSIT-002 — Native revision authority for transferable similarity Grounds

Status: **implemented and locally smoke-tested with an API-compatible E-CPU
registry stand-in; native E-CPU and GitHub CI tests pending**.

## Objective

Replace GEOMETRY-TRANSIT-001's trusted but separately provisioned
`PinnedSimilarityCatalogue` with E-CPU's own **checkpointed and journaled**
`StructuralMemoryRegistry` when navigating a portable VGI mathematical Ground.
Keep mathematical proof, revision provenance and physical execution authority
separate. Preserve the existing `vgi.similarity.navigate` pure Virtual Layer
contract and Transit backend rather than introducing another transport or
execution ledger.

## Reused components and exact scope

- **VGI** `admit_similarity_memory` independently rechecks every original
  matrix factor, commuting witness, basis and inverse, block partition, and
  local product. It never reruns similarity discovery on the receiving host.
- **E-CPU** `StructuralMemoryRegistry.propose/admit/version_for_revision` owns
  immutable revision numbers, compare-and-swap admission, spec/certificate
  digests, parent lineage, host admission policy and the OS EventJournal cut.
- **E-CPU** `VirtualLayerRuntime` and `TransitVGISimilarityHost` continue to
  govern compute rights, request/replay identity, resource accounting and
  eventual quorum-backed receiver recovery.
- A new `NativeSimilarityCatalogue` is an **adapter** to that registry; it
  does not maintain its own authoritative record collection. A lazy cache of
  verified mathematical objects is only an optimization, and the native
  revision is checked on every navigation query. A new host reconstructs the
  cache from its registry and rechecks the VGI proof.

## Why the native index law is not a matrix proof

The existing E-CPU registry accepts only `int`, `lcg`, `gf2`, and `fgraph`
recurrence families. It would be unsound to extend its verifier implicitly to
claim proof of arbitrary matrix similarity. Accordingly the adapter registers
one **explicitly labelled index-coordinate law**:

`Law(family="int", params={"x0": 0, "step": 1, "mod": 2147483647}, order=1, verdict="GROUND")`

with independent index witnesses `(0,0),(1,1),(2,2)`. That E-CPU certificate
proves **only that recurrence and the integrity of its context and revision**.
The complete VGI similarity record is stored as bounded, canonical JSON
under the revision's immutable context, with purpose schema
`mailcpu.vgi-similarity-native-index.v1`.

The mathematical similarity claim is separately checked in VGI, every time a
fresh native receiver admits the record. The effect exposes both proof
identities and states the index-law scope explicitly. Neither proof confers a
host capability.

## Admission and pinning

`admit_native_similarity_revision` requires trusted expected mathematical
memory and graph digests, a bounded canonical record, provenance label,
explicit `memory_id`, and expected prior revision. It reconstructs the VGI
proof **before staging** the E-CPU proposal. The host's existing
`admission_policy` must separately approve the proposed context and provenance
subject. The registry's CAS admission and parent lineage are not bypassed.

The receiving operator is configured locally with an immutable
`NativeSimilarityPin(memory_id, revision, spec_digest, certificate_digest,
memory_sha256, graph_fingerprint)`. The untrusted sender's v1 navigation
request still carries *only* the original mathematical digest and typed state,
not a new revision choice or authority claim. The host refuses if the request
does not match its trusted pin, if the pinned revision is no longer available,
or if spec, certificate, context and graph identities differ.

Both these permissions are required:

- E-CPU's existing `/virtual-layer/operators` **compute** capability for the
  pure navigation operation.
- Receiver-local `/structural-memory/read` **read** capability for resolving
  the native pinned revision. The adapter checks the live worker PID and the
  worker's actual capabilities, never trusting a peer's asserted grant.

The effect additionally carries an E-CPU **journalled structural-memory read
receipt** for index coordinate zero, obtained through the registry's own
`read_revision` operation after VGI's navigation. Its spec/certificate/context
identities are checked against the pinned revision. The native read receipt
certifies only the index-coordinate relation, not the VGI matrix proof.
When a committed E-CPU effect is replayed, the expected result is the original
read receipt with no second handler entry or native read. That full replay
claim still requires the existing dedicated Transit CI test to pass.

A historical revision remains independently addressable under an explicitly
pinned native identity. Strict active-head-only resolution is also available
(`require_active=True`). Rebinding changed matrix operands requires VGI's
full mathematical recheck and a *new* native revision, new parent lineage
and new mathematical graph/memory identity. Old receipts remain bound to the
original revision and cannot silently become receipts for the changed Ground.

## Recovery and independent observation

`examples/verify_native_similarity_revision.py` reconstructs an actual
E-CPU `StructuralMemoryRegistry` plus `EventJournal` snapshot in a separate
Python interpreter. It validates the externally pinned revision, rechecks
complete mathematical proof and navigates the distant logical coordinate,
**without calling** the discovery search. A modified journal anchor is
rejected. This is not a second execution ledger.

The existing GEOMETRY-TRANSIT-001 process test aims to establish the stronger
property of replaying an **already committed** E-CPU effect from a quorum-sealed
receiver checkpoint with zero backend re-entry. That test is defined but has
not yet passed integrated CI; the new native-index tests are not a substitute
for it. Likewise, the small local reference smoke uses an E-CPU-compatible
simulation of registry APIs and is **not** a physical host verification.

## Current local evidence

The compatibility harness independently navigated at logical time
`10^30+11`, yielding `(8,84,58,6,91,8)` for starting vector
`(2,4,8,16,32,64)` in the example Ground. It exercised initial admission,
revision 2 after a changed operand, parent provenance, historical pin reads,
active-only refusal, missing historical revision, missing read permission,
and wrong mathematical hash refusal. These are not E-CPU runtime results.

### Run in a fully provisioned E-CPU repository

Install E-CPU's normal dev dependencies and VGI GEOMETRY-FIRST-008 (currently
commit `30732bc4ba42c9555ab30fad21eb7b3778fb966b`, until the upstream
VGI stack merges), then run:

```sh
python -m pytest -q -v tests/test_vgi_similarity_native_memory.py
python -m pytest -q -v tests/test_vgi_similarity_host.py tests/test_vgi_similarity_transit_recovery.py
```

The existing opt-in `.github/workflows/vgi-similarity-transit.yml` now
includes the native revision tests on Python 3.11 and 3.13. A passing result
is required before merging into main. Avoid claiming multi-machine mTLS
transfer or remote attestation from localhost process evidence.

## Remaining research

Native E-CPU `StructuralMemoryRegistry` still certifies recurrence-family
indices, rather than directly treating portable matrix proofs as an intrinsic
new generator family. A future dedicated family/ground schema may eliminate
this explicitly described indexing convention, provided the registry verifier,
journal, snapshot and replay proofs are extended together. This would be a
separate deliberately reviewed mathematical ABI migration.