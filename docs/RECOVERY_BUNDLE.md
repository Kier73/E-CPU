# Quorum-gated recovery bundles

A recovery lineage is useful only when the process restore path is required to
consult it. This layer joins the independent requester and receiver checkpoint
files to the existing quorum anchor and makes successful bundle verification a
precondition for reconstruction.

## Capture protocol

`RecoveryCheckpointBundleStore` operates over a
`RecoveryLineageCoordinator` with a fixed `SeedCommitMembership`.

1. The requester writes its own channel checkpoint and the receiver writes its
   Transit session checkpoint using their existing durable checkpoint paths.
2. `seal(requester_path, receiver_path, capture_cut)` reads the exact bytes
   from both files. It requires a v2 Transit receiver checkpoint and extracts
   its canonical registered operation/resource manifest.
3. It copies all three payloads into a new immutable generation directory,
   writes the canonical manifest, fsyncs each artifact and the directory, and
   atomically publishes the generation directory.
4. Only after those data-plane bytes are durable does the coordinator prepare,
   certify, and commit the manifest root through the strict-majority authority
   journal.
5. The returned `VerifiedRecoveryCheckpointBundle` contains the exact bytes
   that were sealed. The manifest is never treated as proof by itself.

Generation directories use the form
`generation-00000000000000000001/` and contain:

| File | Contents |
|---|---|
| **requester.json** | Exact requester-side reliable-channel checkpoint bytes |
| **receiver.json** | Exact receiver-side Transit session checkpoint bytes |
| **backend-manifest.json** | Canonical operation/resource domain extracted from the receiver checkpoint |
| **manifest.json** | Canonical, versioned checkpoint manifest bound to all three payloads |

Directories are immutable. A retry may reuse a generation only when every
artifact byte is identical. A partial prepare or commit can therefore be
retried with the original proposal, but a changed checkpoint cannot silently
replace a prepared generation.

## Restore protocol

Call `load_latest()` before opening replacement listeners, connecting new
transports, or reconstructing runtime state. The store asks the authority
journals for the quorum-supported high-water proof; it does not trust a local
pointer or the highest directory name.

The store then:

- loads the selected generation's exact requester, receiver, backend, and
  manifest bytes;
- checks canonical manifest encoding and the backend manifest's agreement
  with the receiver checkpoint;
- verifies all three content digests against the manifest;
- asks the coordinator to verify that this exact root is the latest
  quorum-anchored generation.

Only then does it return a `VerifiedRecoveryCheckpointBundle`. Its
`restore_receiver_session(request_transport, response_transport)` method
reconstructs a `TransitComputeSession` from the same in-memory receiver bytes
that were verified. This avoids verifying a path and then rereading potentially
different bytes during restore. The requester side consumes
`bundle.requester_checkpoint` and validates its endpoint-specific envelope
before reconstructing its reliable channels.

A typical integration is:

```python
from mailcpu import RecoveryCheckpointBundleStore

store = RecoveryCheckpointBundleStore(bundle_directory, coordinator)

# During capture, after both endpoint checkpoint writers have completed:
captured = store.seal(
    requester_checkpoint_path,
    receiver_checkpoint_path,
    capture_cut="after_response_publish",
)

# In each replacement process, before opening its new transport:
bundle = store.load_latest()

# After verification, rebind fresh transports and reconstruct the receiver:
session = bundle.restore_receiver_session(
    request_transport,
    response_transport,
)
```

The authority journal directory must be configured separately from the bundle
directory and kept outside the rollback scope of the requester/receiver
checkpoint storage. For distributed operation, use
`DistributedRecoveryLineageCoordinator` with the owner authority local to the
coordinator process and one `RecoveryLineagePeerClient` for each remote
`RecoveryLineageProcessParticipant`. Each remote process owns a distinct
journal and can be restarted without copying the other members' storage. If
the requester, receiver, bundle directory, and every authority journal are
all rolled back together, the external high-water evidence is also rolled
back.

## Failure behavior

A missing artifact, malformed manifest, changed endpoint bytes, changed
backend manifest, unanchored generation, stale generation, future generation,
same-slot conflict, or unavailable read quorum causes admission to fail. A
durable local generation without a quorum commit is deliberately not a
recoverable generation. The previous quorum-anchored generation remains in
its own immutable directory.

The initial implementation is integrated into the hard-kill requester and
receiver tests at all four Transit transaction cuts. Both replacement workers
load and verify the same bundle before creating replacement transports; the
receiver reconstructs from verified bytes, while the requester reconstructs
its channel state from verified bytes.

## Proof boundary

The bundle store closes the local path-ordering and verify-then-reread gaps. It
does not turn the existing in-process reference coordinator into a remote
authority service: the authority journals are still distinct durable files
opened by the local coordinator. Deployments must place authority journals
outside the checkpoint rollback domain. This is not Byzantine consensus,
authenticated storage, a power-loss qualification, or a guarantee of
exactly-once arbitrary external side effects.
