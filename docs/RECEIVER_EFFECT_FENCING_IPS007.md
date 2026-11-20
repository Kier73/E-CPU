# IPS-007 — Receiver-side atomic effect fencing for generated Grounds

## Research question

IPS-005/006 proved that an independently committed mathematical result remains authoritative under worker rehome and recovery-authority process death. This did **not** by itself protect an external resource: a delayed worker could perform an effect after losing publication authority if the resource used a separate "check ownership, then write" sequence.

IPS-007 tests the next principle:

**Can a resource atomically enforce a verified generated-Ground publication and its local monotonic fence, rather than blindly trusting a worker's mathematically correct result?**

The test resource is a persistent SQLite register, representing one receiver-owned external state. It is not a general external effects framework and it does not execute arbitrary source instructions.

## Existing E-CPU contracts reused

- IPS-003: a finite, exact intention-generated primitive graph.
- IPS-004: Hypervisor-authorized stage execution through qualified observer-hosts, SAB-008 independent Ground receipts, typed predecessor DAG, exact replay.
- IPS-005: native quorum-fenced assignment and publication, RecoveryStateManifest, RecoveryLineageCoordinator majority high-water and immutable archived checkpoints.
- IPS-006: independently running mTLS recovery-lineage authority services with fixed configured members.

There is **no second consensus or network authority**. The effect receiver accepts a new authority root only after an unmodified IPS-005 FencedGroundLineage restores the exact archived artifact, checks the latest quorum proof and reconstructs the full native computation.

## The concrete receiver effect contract

The native module fenced_effect_receiver.py provides:

The local receiver is constructed with an **immutable resource-to-plan binding** (resource path plus exact IPS-003 plan digest), persisted in its receiver-owned database. Reopening the resource with a different plan digest is refused rather than allowing another valid Ground to replace its meaning.

- PublishedGroundEffect: a bounded **inert request**, carrying resource, current published manifest root/generation, original plan and checkpoint digests, stage, epoch, qualified host, exact SAB-008 receipt digest and output value. It is **not** a bearer credential.
- published_effect: extracts a stage description from a quorum-published Ground head. It performs no effect and grants no rights.
- FencedGroundEffectReceiver: stores an installed authority root, append-only semantic effect receipts and one persistent register in a receiver-owned SQLite database.

### Receiver installation

Before installing any root, the receiver calls the existing FencedGroundLineage.restore, which invokes the original majority read-high-water verifier and native IPS-004 replay. It independently checks that any newly published stage's SAB-008 observation matches the native committed DAG.

It installs the root using SQLite BEGIN IMMEDIATE, rejecting lower generations and conflicting roots for the same generation. Installing a newer **assignment** (not only a publication) also revokes writes bearing the older publication root. Receivers do not infer new authority from an outdated local checkpoint file.

### Atomic effect

A subsequent effect request starts its own SQLite BEGIN IMMEDIATE transaction. Within the *same transaction* it:

1. Reads the receiver-installed generation and exact manifest root.
2. Requires the exact plan, checkpoint, epoch, stage, qualified host, SAB-008 receipt digest and observed value, with event="publish".
3. Refuses on any mismatch, without touching the register or effect ledger.
4. Deduplicates an already committed exact semantic operation (plan+stage+receiver resource).
5. Inserts its exact effect receipt and updates the register, then commits **together**.

An exception in the register write rolls back the corresponding receipt. This is the resource-side atomicity missing from IPS-005.

The resource receiver uses SQLite write transactions as its local serialization primitive. Per official SQLite documentation, BEGIN IMMEDIATE obtains the writer reservation before reading and changing local state. The receiver configures WAL and synchronous=FULL; crash durability still depends on underlying storage, and no local SQLite mode can provide remote multi-machine consensus.

## Adversarial tests

- **Unpublished old worker:** an IPS-004 worker computes a correct intermediate state, then IPS-005 quorum reassigns its stage. A request constructed from that old work is refused because an assignment is not a publication.
- **Separate delayed writer process:** an independent subprocess reads a previously published, otherwise correct claim and pauses. The quorum advances and the receiver installs a newer assignment. After resuming, the old process is refused **inside the same database transaction that would write the effect**. A new authorized published stage can subsequently write.
- **Partial write crash/exception:** a SQLite trigger aborts the register update after the receipt insert. The transaction must leave **neither** accepted receipt nor changed register.
- **Concurrent replay:** multiple independent SQLite connections submit the exact same valid request; the resource ends with exactly one effect.
- **Receiver restart:** a separate receiver instance reopens persistent authority and effect state; it cannot roll back to an older root.
- **Authority and evidence refusal:** missing majority, stale quorum head, forged checkpoint, changed host, epoch, stage, output, receipt and resource are rejected.

## Important correctness distinction

**Quorum publication and local effect installation are not one atomic network transaction.** If a newer quorum epoch exists but has not yet been installed at this resource, a receiver may still admit a request for the last locally installed root. IPS-007 therefore establishes *atomic fencing after the newer root is installed*, plus monotonic local root order. To guarantee immediate global revocation at every independent external resource, its own service must participate in a synchronized handoff protocol (or validate a current conditional authorization using a coordinated durable mechanism).

Also, IPS-007 applies only to a **quorum-published, independently checked** pure result. It does not authorize a remote worker to mutate effects during the uncommitted compute phase, and it does not claim network-client authentication, physical host attestation, two-phase atomic commit across the independent quorum and SQLite, or exactly-once side effects in arbitrary downstream systems.

These distinctions follow the resource-side fencing argument in [Martin Kleppmann's distributed locking analysis](https://martin.kleppmann.com/2016/02/08/how-to-do-distributed-locking.html) and [SQLite's isolation and transaction documentation](https://www.sqlite.org/isolation.html).

## Reproduce

    python -m pytest -q tests/test_fenced_effect_receiver.py
    python -m pytest -q tests/test_fenced_effect_receiver.py tests/test_fenced_generated_ground.py tests/test_qualified_generated_ground.py tests/test_recovery_lineage.py

Dedicated Linux/Windows Python 3.11/3.13 CI includes real qualified subprocess Ground execution, independent worker writes, durable receiver transactions and the native lineage regressions. No signing secrets or fixture keys are committed.

## Next research

Extend the receiver to an authenticated socket service so the **service** owns both the resource and its installed fence under a distinct process identity. Test forced receiver death between transactions, remote owner recovery, and a lease-independent handoff barrier proving that an old worker cannot write after a new quorum epoch has been activated at that resource. Integrate a compact transportable verifier certificate into VGI/IFS for independently checking the admitted Ground's meaning.
