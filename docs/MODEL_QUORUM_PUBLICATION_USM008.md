# USM-008 — Quorum-fenced model-result publication

**Status:** code and tests committed; execution remains unverified until a
native runner completes. No general exactly-once or multi-machine claim.

## The operation this experiment actually performs

This extends model-operated E-CPU from advisory inference through authenticated
system calls and receiver hard-crash recovery into an **authorized publication
of the resulting Ground read**.

It reuses rather than replaces E-CPU's current authority:

- `StructuralMemoryRegistry` provides the actual admitted, revision-pinned
  navigable mathematical Ground and a read receipt.
- `GroundSystemCallSession` retains the model-issued observe/propose/read
  chronology with a content-bound model identity.
- `SocketTransport`, `connect_mutual_tls`, `accept_mutual_tls`, and
  `ReliableChannel` are the real bidirectional candidate channels.
- `RecoveryLineageAuthorityService`,
  `RecoveryLineagePeerClient.connect_mutual_tls`,
  `DistributedRecoveryLineageCoordinator`, and
  `RecoveryStateManifest` implement a **native strict-majority quorum**.
- `ModelRecoveryStore` is the original USM-005/006 checkpoint store, upgraded
  so a result publication is a **recoverable version-two Ground checkpoint**
  rather than a separate, conflicting authority ledger.

The experiment intentionally retains an immutable *fixed authority owner A*.
Replacement candidates do **not** receive authority A credentials. Instead a
single trusted owner-side publication gate accepts typed, mTLS-authenticated
requests from **two independently launched candidate OS processes** using
distinct certificate SANs. The gate checks the peer certificate identity,
validates the original recovered model/receiver trace, loads and verifies the
current quorum-backed Ground, and attempts exactly one next-generation
transition through the existing distributed lineage coordinator.

Two candidates are permitted to request the same Ground result. Only the
first native majority-committed claimant becomes the authorized logical
publisher. The other receives `superseded` and no publication payload.

The actual sequence is:

```text
model host ----evidence----> receiver #1
                                Ground read committed
                                generation 1 sealed by A+B+C
                                HARD KILL (before ACK)
model host ----retry------> receiver #2
                                Ground/read restored
                                original read ACK
                                generation 2 sealed by A+B+C

candidate A -- mTLS --> E-CPU publication authority owner A <-- mTLS -- candidate B
                         |
                         v
                    Native A+B+C quorum
                         |
                      generation 3
                         |
              complete restored Ground plus
               one publication owner claim
                         |
              winner: authorized publication
              loser:  superseded, no result
```

The publication gate validates the **same model trace, Ground digest, read
receipt, target coordinate, and source formula** as the underlying model
operation. It does not accept an arbitrary model confidence score as
permission to publish. The quorum generation and full restorable Ground
state are advanced as one typed state. After all authority services stop,
an explicit read-only auditor independently reopens their durable journals
and reconstructs the winner's Ground/read.

## Why a version-two recoverable checkpoint matters

An early USM-008 design considered sealing only the publication claim into
generation three. That would make the latest recovery high-water no longer
loadable as a `GroundSystemCallSession` checkpoint.

The implemented design instead stores the already verified *complete
receiver checkpoint* with one additional `publication_claim` field under
`mailcpu.usm008.model-recovery-published-checkpoint.v1`. This extends, but
does not replace, the original USM-005 checkpoint schema. Both are
validated by `ModelRecoveryStore.load()`. A stale generation-two
checkpoint is refused after publication even though its bytes remain
intact.

## Reproduce

With E-CPU installed and OpenSSL available:

```bash
python -m pytest -q tests/test_model_quorum_publication.py
python -m examples.model_quorum_publication demo --output usm008-publication.json
```

The tests exercise actual subprocess hard-kill recovery, the native remote
mTLS quorum authorities, distinct TLS candidate identities and native
reliable frames, exact one-winner/one-loser outcomes, reloading the
generation-three Ground, refusing generation-two rollback, refusing a
modified Ground result even after its outer hash is recomputed, rejecting
ambiguous peer certificate SAN identities, and rejecting local checkpoint
tampering against the durable quorum root.

All certificate private keys are temporary test fixtures. They are never
saved in the result JSON. The retained output contains the independent
candidate PIDs, winner/loser verdicts and native checkpoint authority
identities, receipts and hashes.

## Precisely scoped interpretation

This is **one logical publication** of a real E-CPU Ground result, not
execution of an external side effect. The result gate does not provide a
cryptographically nonrepudiable signature: E-CPU's majority certificates
are durable vote/decision records bound to exact proposal hashes, and the
remote authority streams use mTLS. A recipient outside the trusted
authority cannot infer the correctness of TLS from an exported JSON object.

The quorum runs in three OS processes but **one physical runner and one
filesystem failure domain**. Candidate processes also share the test
runner's local filesystem and OS user; they are not adversarial sandboxes.
The gate's fixed authority owner A mediates competing claims. There is
no distributed leader election among multiple A owners.

No arbitrary-effect exactly-once guarantee is asserted. If a future sink
publishes to a real-world service, it must validate the current quorum
ownership generation *at its own commit boundary* and/or deduplicate by
the stable accepted result identity. A stale cached verdict cannot
replace that check.

## Direct use: making E-CPU do useful work

The actual input is the model-operated receiver-recovery result, not a
fabricated pre-authorized publication. The model requests a navigated
Ground read after observing the source; E-CPU admits the law only when
its own evidence verifier and capability policy allow it; the system
recovers the result after the receiver dies and chooses which replacement
may publish it.

This is a meaningful internally produced computational outcome: the
model controls *which computation is requested* while E-CPU's evidence,
recovery and authorization mechanisms control whether the result may
become a committed result. The next practical milestone is to drive
this same path with a task the development process needs—for example,
native architecture evidence exploration or proof-obligation navigation—
instead of the deterministic affine test workload.

No test or live model execution should be reported as complete solely
because this experiment's code and workflow exist.
