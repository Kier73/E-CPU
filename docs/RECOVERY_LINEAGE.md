# Quorum-anchored recovery checkpoint lineage

## Purpose

A checkpoint digest proves that checkpoint bytes match their content hash. It
does not prove that the checkpoint is the newest valid state. A stale
checkpoint can be internally intact and still roll a machine backward.

This module adds a separate recovery lineage. The requester and receiver
checkpoint files remain the data plane; a fixed-membership quorum of durable
authority journals stores the monotonic checkpoint root. Restore is admitted
only when the supplied checkpoint manifest matches the quorum-supported
high-water generation.

The implementation deliberately reuses the existing SeedCommitMembership,
DurableSeedCommitLedger, SeedCommitProposal, SeedCommitCertificate, and
SeedCommitDecision contracts. It does not create a second prepare/commit
algebra.

## Manifest

RecoveryCheckpointManifest binds:

- stable machine identity, incarnation, owner, owner term, and membership digest;
- monotonically increasing generation and exact predecessor root digest;
- requester checkpoint content digest;
- receiver checkpoint content digest;
- backend manifest digest;
- named capture cut.

The manifest root is the SHA-256 digest of its canonical snapshot. Its request
fingerprint is domain-separated for the recovery-lineage proposal namespace.
The root therefore changes if either endpoint checkpoint, the backend
registration, the machine identity, the cut, or the generation changes.

Before sealing, the caller must atomically write and fsync both endpoint
checkpoints and the backend manifest. On restore, call
verify_checkpoint_bundle with the exact bytes; it verifies their hashes and
then checks the separate quorum anchor.

## Seal protocol

For membership M, N configured members and strict-majority quorum q, where
2q > N:

1. Construct the exact proposal from the manifest root, generation, predecessor
   digest, machine membership, and domain-separated request fingerprint.
2. Each available authority fsyncs its one vote for that membership term and
   generation. An exact retry returns the original vote; a different proposal
   for an occupied slot is refused.
3. Form a prepare certificate only from at least q unique configured votes,
   including the configured owner.
4. Each participating authority fsyncs the commit decision. The coordinator
   returns a proof only after at least q durable decisions are available.
5. If a process dies after a minority of commit decisions were written, an
   exact retry discovers and reuses the already committed certificate. It does
   not invent a new certificate with a different voter set.

The one-vote-per-slot rule and strict-majority intersection prevent two
conflicting checkpoint roots from both obtaining a certificate under the same
fixed membership and owner term.

## Restore and rollback detection

latest_proof counts authority journals by committed
(generation, root_digest) and accepts a head only when at least q journals
report the same pair. A minority-ahead local journal does not advance the read
high-water.

verify_checkpoint requires exact equality with that head. It rejects:

- an older generation, even when its own checkpoint hashes are valid;
- a generation ahead of the committed anchor;
- a different manifest root at the anchored generation;
- a manifest bound to another machine incarnation, owner term, or membership.

A partial commit that exists on only one anchor member is not yet the read
high-water. The exact same manifest can be resubmitted to complete the durable
decision quorum.

## API sketch

    membership = SeedCommitMembership(
        system_id,
        incarnation,
        member_ids,
        owner_id,
        owner_term,
        genesis_digest,
    )
    authorities = {
        member: RecoveryLineageAuthority(
            membership, member, authority_journal_path[member]
        )
        for member in member_ids
    }
    lineage = RecoveryLineageCoordinator(membership, authorities)

    proof = lineage.seal(manifest)  # after endpoint checkpoints have been fsynced
    lineage.verify_checkpoint_bundle(
        manifest,
        requester_checkpoint_bytes,
        receiver_checkpoint_bytes,
        backend_manifest_bytes,
    )

The proof can be serialized with RecoveryLineageProof.snapshot() and
reconstructed with RecoveryLineageProof.from_snapshot().

## What this establishes

- A manifest binds exact requester, receiver, and backend content digests.
- A fixed membership and owner term bind each proposal to one machine lineage.
- Prepare votes are single-valued per slot and survive authority-object reopen.
- A certificate requires a strict majority and the configured owner.
- A seal succeeds only after a strict majority of authority journals persist the
  commit decision.
- Retries after a partial commit reuse the original certificate.
- Read high-water requires a quorum of matching committed generation/root pairs.
- A valid but older checkpoint is rejected after a newer generation is anchored.
- A conflicting manifest at the current generation is rejected.

## Proof boundary and deployment requirements

The local `RecoveryLineageCoordinator` remains a useful reference
coordinator for unit tests and single-process deployments. For distributed
operation, `DistributedRecoveryLineageCoordinator` keeps the owner authority
in the owner process and uses `RecoveryLineagePeerClient` connections to
independent `RecoveryLineageProcessParticipant` processes. Remote members own
one journal each and use the existing seed-quorum request/response channel
names, `ReliableChannel`, and `SocketTransport`; the recovery payloads are a
separate typed command family over that same transport substrate.

The process test harness hard-kills remote participants after PREPARE fsync
and after COMMIT fsync but before they send a response or acknowledge the
request. It then restarts the same member identity against the same journal
and verifies exact vote/certificate/decision recovery. A further test kills
both remote authorities after a quorum has committed a recovery bundle,
reopens the owner and remote journals, and requires a fresh read quorum before
the bundle is admitted.

Rollback resistance depends on the authority journals being outside the
checkpoint rollback scope. If an attacker can roll back the requester
checkpoint, receiver checkpoint, and every authority journal together, this
module has no surviving high-water evidence. Production deployment therefore
requires independently protected fault domains, authenticated peer identity
and transport, durable storage semantics, and an explicit membership/owner-term
lifecycle.

This is not Byzantine consensus, membership reconfiguration, power-loss
qualification, hardware monotonic-counter integration, or exactly-once
execution of arbitrary external side effects. The SHA-256 hash chain detects
content changes; it does not authenticate a malicious storage provider.
