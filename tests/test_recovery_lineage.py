"""Quorum-anchored recovery checkpoint lineage tests."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from mailcpu import (
    RecoveryCheckpointManifest,
    RecoveryLineageAuthority,
    RecoveryLineageCoordinator,
    RecoveryLineageError,
    RecoveryLineageProof,
    SeedCommitMembership,
    SeedCommitProposal,
    SeedCommitCertificate,
)


GENESIS = hashlib.sha256(b"mailcpu-recovery-lineage-genesis-v1").hexdigest()


def _membership() -> SeedCommitMembership:
    """Construct a fixed three-member membership with a strict-majority quorum."""

    return SeedCommitMembership(
        "machine-A",
        1,
        ("A", "B", "C"),
        "A",
        1,
        GENESIS,
    )


def _authorities(tmp_path: Path, membership: SeedCommitMembership):
    """Open independent participant journals for all configured anchor members."""

    return {
        member: RecoveryLineageAuthority(
            membership,
            member,
            str(tmp_path / f"anchor-{member}.jsonl"),
        )
        for member in membership.member_ids
    }


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _manifest(
    membership: SeedCommitMembership,
    generation: int,
    predecessor: str,
    *,
    requester: bytes | None = None,
    receiver: bytes | None = None,
    backend: bytes = b"backend-manifest-v1",
    cut: str = "after_response_publish",
) -> RecoveryCheckpointManifest:
    """Create a checkpoint manifest whose digests bind independent byte payloads."""

    return RecoveryCheckpointManifest(
        machine_id=membership.system_id,
        incarnation=membership.incarnation,
        owner_id=membership.owner_id,
        owner_term=membership.owner_term,
        membership_digest=membership.digest,
        generation=generation,
        predecessor_digest=predecessor,
        requester_checkpoint_digest=_digest(requester or f"requester-{generation}".encode()),
        receiver_checkpoint_digest=_digest(receiver or f"receiver-{generation}".encode()),
        backend_manifest_digest=_digest(backend),
        capture_cut=cut,
    )


def test_checkpoint_manifest_round_trips_and_binds_all_three_payloads() -> None:
    """A manifest digest binds requester state, receiver state, and the backend manifest."""

    membership = _membership()
    requester = b"client channel checkpoint"
    receiver = b"receiver session checkpoint"
    backend = b"registered backend manifest"
    manifest = _manifest(
        membership,
        1,
        GENESIS,
        requester=requester,
        receiver=receiver,
        backend=backend,
    )

    restored = RecoveryCheckpointManifest.from_snapshot(manifest.snapshot())
    assert restored == manifest
    assert restored.digest == manifest.digest
    assert len(restored.digest) == 64
    restored.verify_payloads(requester, receiver, backend)
    malformed_version = manifest.snapshot()
    malformed_version["version"] = True
    with pytest.raises(RecoveryLineageError, match="fields or version"):
        RecoveryCheckpointManifest.from_snapshot(malformed_version)

    with pytest.raises(RecoveryLineageError, match="requester checkpoint digest"):
        restored.verify_payloads(b"modified client state", receiver, backend)
    with pytest.raises(RecoveryLineageError, match="receiver checkpoint digest"):
        restored.verify_payloads(requester, b"modified receiver state", backend)
    with pytest.raises(RecoveryLineageError, match="backend manifest digest"):
        restored.verify_payloads(requester, receiver, b"modified backend manifest")


def test_quorum_lineage_advances_and_rejects_a_valid_older_checkpoint(tmp_path: Path) -> None:
    """A valid generation-1 checkpoint is rejected after generation 2 becomes the quorum high-water."""

    membership = _membership()
    authorities = _authorities(tmp_path, membership)
    coordinator = RecoveryLineageCoordinator(membership, authorities)

    first = _manifest(membership, 1, GENESIS)
    first_proof = coordinator.seal(first)
    assert len(first_proof.certificate.votes) >= membership.quorum
    assert len(first_proof.decisions) >= membership.quorum
    assert coordinator.high_water() == (1, first.digest)
    assert coordinator.verify_checkpoint(first) == first_proof

    second = _manifest(membership, 2, first.digest)
    second_proof = coordinator.seal(second)
    assert second_proof.proposal.slot == 2
    assert coordinator.high_water() == (2, second.digest)
    assert coordinator.verify_checkpoint(second) == second_proof
    requester_bytes = b"requester-2"
    receiver_bytes = b"receiver-2"
    backend_bytes = b"backend-manifest-v1"
    second_with_material = _manifest(
        membership,
        2,
        first.digest,
        requester=requester_bytes,
        receiver=receiver_bytes,
        backend=backend_bytes,
    )
    coordinator.seal(second_with_material)
    assert coordinator.verify_checkpoint_bundle(
        second_with_material,
        requester_bytes,
        receiver_bytes,
        backend_bytes,
    ).proposal.digest == coordinator.proposal_for(second_with_material).digest
    with pytest.raises(RecoveryLineageError, match="receiver checkpoint digest"):
        coordinator.verify_checkpoint_bundle(
            second_with_material,
            requester_bytes,
            b"wrong receiver bytes",
            backend_bytes,
        )

    with pytest.raises(RecoveryLineageError, match="stale"):
        coordinator.verify_checkpoint(first)


def test_same_generation_manifest_conflict_is_rejected_even_when_its_bytes_are_valid(
    tmp_path: Path,
) -> None:
    """The anchor rejects a different but internally valid checkpoint root at an occupied generation."""

    membership = _membership()
    coordinator = RecoveryLineageCoordinator(membership, _authorities(tmp_path, membership))
    accepted = _manifest(membership, 1, GENESIS, requester=b"accepted-client")
    conflicting = _manifest(membership, 1, GENESIS, requester=b"other-client")

    coordinator.seal(accepted)
    assert conflicting.digest != accepted.digest
    with pytest.raises(RecoveryLineageError, match="conflicts"):
        coordinator.verify_checkpoint(conflicting)
    with pytest.raises(RecoveryLineageError, match="prepare quorum"):
        coordinator.seal(conflicting)


def test_incomplete_prepare_quorum_can_be_retried_without_changing_proposal(tmp_path: Path) -> None:
    """A minority prepare is not an anchor; the exact proposal can complete when another peer returns."""

    membership = _membership()
    authorities = _authorities(tmp_path, membership)
    manifest = _manifest(membership, 1, GENESIS)

    only_owner = RecoveryLineageCoordinator(membership, {"A": authorities["A"]})
    with pytest.raises(RecoveryLineageError, match="prepare quorum"):
        only_owner.seal(manifest)
    assert authorities["A"].verify() is True

    owner_and_peer = RecoveryLineageCoordinator(
        membership,
        {"A": authorities["A"], "B": authorities["B"]},
    )
    proof = owner_and_peer.seal(manifest)
    assert proof.proposal.digest == owner_and_peer.proposal_for(manifest).digest
    assert len(proof.decisions) == 2
    assert owner_and_peer.high_water() == (1, manifest.digest)


def test_quorum_intersection_blocks_a_conflicting_prepared_history(tmp_path: Path) -> None:
    """Two prepare quorums cannot certify different checkpoint roots for the same slot."""

    membership = _membership()
    authorities = _authorities(tmp_path, membership)
    original = _manifest(membership, 1, GENESIS, requester=b"original")
    conflict = _manifest(membership, 1, GENESIS, requester=b"conflict")
    coordinator = RecoveryLineageCoordinator(membership, authorities)

    original_proposal = coordinator.proposal_for(original)
    authorities["A"].prepare(original_proposal)
    authorities["B"].prepare(original_proposal)

    with pytest.raises(RecoveryLineageError, match="prepare quorum"):
        coordinator.seal(conflict)

    original_proof = coordinator.seal(original)
    assert original_proof.proposal.digest == original_proposal.digest
    assert coordinator.high_water() == (1, original.digest)


def test_partially_persisted_commit_reuses_its_original_certificate(tmp_path: Path) -> None:
    """A crash after one local COMMIT resumes with the same certificate and reaches a durable majority."""

    membership = _membership()
    authorities = _authorities(tmp_path, membership)
    manifest = _manifest(membership, 1, GENESIS)
    coordinator = RecoveryLineageCoordinator(membership, authorities)
    proposal = coordinator.proposal_for(manifest)

    vote_a = authorities["A"].prepare(proposal)
    vote_b = authorities["B"].prepare(proposal)
    original_certificate = SeedCommitCertificate(
        membership.digest,
        proposal.digest,
        (vote_a, vote_b),
    )
    first_decision = authorities["A"].commit(proposal, original_certificate)
    assert first_decision.state_digest == manifest.digest

    # The coordinator returns after a crash with only A's COMMIT durable.
    # The retry must not mint a larger certificate whose voter projection
    # differs from the already committed decision.
    proof = coordinator.seal(manifest)
    assert proof.certificate.snapshot() == original_certificate.snapshot()
    assert len(proof.decisions) == 3
    assert coordinator.high_water() == (1, manifest.digest)


def test_one_local_commit_does_not_advance_the_read_quorum_high_water(tmp_path: Path) -> None:
    """A checkpoint is not admitted until a quorum of anchor journals has persisted its decision."""

    membership = _membership()
    authorities = _authorities(tmp_path, membership)
    manifest = _manifest(membership, 1, GENESIS)
    coordinator = RecoveryLineageCoordinator(membership, authorities)
    proposal = coordinator.proposal_for(manifest)

    vote_a = authorities["A"].prepare(proposal)
    vote_b = authorities["B"].prepare(proposal)
    certificate = SeedCommitCertificate(membership.digest, proposal.digest, (vote_a, vote_b))
    authorities["A"].commit(proposal, certificate)

    # B and C still report genesis, so the quorum-supported head has not moved.
    assert coordinator.high_water() == (0, GENESIS)
    with pytest.raises(RecoveryLineageError, match="no checkpoint generation"):
        coordinator.verify_checkpoint(manifest)

    # Re-submission reuses A's durable vote and certificate, commits B, and
    # upgrades the lineage head only after a read quorum can observe generation 1.
    proof = coordinator.seal(manifest)
    assert len(proof.decisions) >= membership.quorum
    assert coordinator.high_water() == (1, manifest.digest)


def test_lineage_proof_round_trips_and_survives_authority_reopen(tmp_path: Path) -> None:
    """Quorum decisions and their certificate survive process-like object reconstruction."""

    membership = _membership()
    authorities = _authorities(tmp_path, membership)
    manifest = _manifest(membership, 1, GENESIS)
    coordinator = RecoveryLineageCoordinator(membership, authorities)
    proof = coordinator.seal(manifest)

    restored_proof = RecoveryLineageProof.from_snapshot(proof.snapshot())
    assert restored_proof == proof
    for authority in authorities.values():
        assert authority.verify() is True

    reopened = _authorities(tmp_path, membership)
    restored_coordinator = RecoveryLineageCoordinator(membership, reopened)
    assert restored_coordinator.high_water() == (1, manifest.digest)
    assert restored_coordinator.verify_checkpoint(manifest).snapshot() == proof.snapshot()


def test_lineage_refuses_generation_gaps_and_wrong_predecessors(tmp_path: Path) -> None:
    """A checkpoint must extend exactly the currently committed generation and root digest."""

    membership = _membership()
    coordinator = RecoveryLineageCoordinator(membership, _authorities(tmp_path, membership))
    wrong_parent = "e" * 64
    with pytest.raises(RecoveryLineageError, match="prepare quorum"):
        coordinator.seal(_manifest(membership, 1, wrong_parent))

    first = _manifest(membership, 1, GENESIS)
    coordinator.seal(first)
    with pytest.raises(RecoveryLineageError, match="prepare quorum"):
        coordinator.seal(_manifest(membership, 3, first.digest))


def test_lineage_rejects_membership_and_machine_identity_changes(tmp_path: Path) -> None:
    """Checkpoint roots cannot be transplanted across machine incarnations or authority memberships."""

    membership = _membership()
    coordinator = RecoveryLineageCoordinator(membership, _authorities(tmp_path, membership))
    manifest = _manifest(membership, 1, GENESIS)

    wrong_machine = RecoveryCheckpointManifest(
        machine_id="machine-B",
        incarnation=manifest.incarnation,
        owner_id=manifest.owner_id,
        owner_term=manifest.owner_term,
        membership_digest=manifest.membership_digest,
        generation=manifest.generation,
        predecessor_digest=manifest.predecessor_digest,
        requester_checkpoint_digest=manifest.requester_checkpoint_digest,
        receiver_checkpoint_digest=manifest.receiver_checkpoint_digest,
        backend_manifest_digest=manifest.backend_manifest_digest,
        capture_cut=manifest.capture_cut,
    )
    with pytest.raises(RecoveryLineageError, match="machine membership"):
        coordinator.proposal_for(wrong_machine)
