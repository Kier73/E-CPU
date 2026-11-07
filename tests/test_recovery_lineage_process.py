"""Real process termination and restart tests for distributed recovery authorities."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from mailcpu import (
    DistributedRecoveryLineageCoordinator,
    DurableSeedCommitLedger,
    RecoveryCheckpointBundleStore,
    RecoveryLineageAuthority,
    RecoveryLineageCoordinator,
    RecoveryLineagePeerClient,
    RecoveryLineageTransportError,
    SeedCommitCertificate,
    SeedCommitMembership,
)
from mailcpu.recovery_lineage import RecoveryCheckpointManifest

GENESIS = hashlib.sha256(b"mailcpu-distributed-recovery-lineage-genesis-v1").hexdigest()


def _membership() -> SeedCommitMembership:
    """Construct one fixed three-member membership with owner A and a two-member strict majority."""

    return SeedCommitMembership(
        "distributed-transit-machine",
        1,
        ("A", "B", "C"),
        "A",
        1,
        GENESIS,
    )


def _manifest(membership: SeedCommitMembership, generation: int = 1, predecessor: str = GENESIS):
    """Bind deterministic requester, receiver, and backend bytes to one named process crash experiment."""

    return RecoveryCheckpointManifest(
        membership.system_id,
        membership.incarnation,
        membership.owner_id,
        membership.owner_term,
        membership.digest,
        generation,
        predecessor,
        hashlib.sha256(f"requester-{generation}".encode()).hexdigest(),
        hashlib.sha256(f"receiver-{generation}".encode()).hexdigest(),
        hashlib.sha256(b'[["cpu.execute","/cpu/compute"]]').hexdigest(),
        "after_response_publish",
    )


def _start_member(
    tmp_path: Path,
    membership: SeedCommitMembership,
    member_id: str,
    *,
    fault_stage: str = "-",
) -> tuple[subprocess.Popen[str], RecoveryLineagePeerClient]:
    """Launch one real authority process with its own journal and bind an owner-side reliable RPC client."""

    worker = Path(__file__).resolve().parent / "helpers" / "recovery_lineage_authority_worker.py"
    membership_path = tmp_path / "membership.json"
    membership_path.write_text(
        json.dumps(membership.snapshot(), sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    marker = tmp_path / f"{member_id}-{fault_stage}.json"
    journal = tmp_path / "authorities" / f"{member_id}.jsonl"
    process = subprocess.Popen(
        [
            sys.executable,
            str(worker),
            member_id,
            str(membership_path),
            str(journal),
            fault_stage,
            str(marker),
        ],
        cwd=Path(__file__).resolve().parents[1],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    assert process.stdout is not None
    line = process.stdout.readline()
    assert line, f"authority {member_id} exited before announcing its port: rc={process.poll()}"
    ready = json.loads(line)
    assert ready["member_id"] == member_id
    peer = RecoveryLineagePeerClient.connect(
        membership,
        member_id,
        "127.0.0.1",
        int(ready["port"]),
        timeout=0.6,
    )
    return process, peer


def _await_marker(path: Path, process: subprocess.Popen[str], timeout: float = 5.0) -> dict[str, Any]:
    """Wait for the durable post-fsync crash witness or report the child exit that prevented it."""

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and not path.is_file() and process.poll() is None:
        time.sleep(0.005)
    assert path.is_file(), f"authority did not publish crash witness; rc={process.poll()}"
    return json.loads(path.read_text(encoding="utf-8"))


def _stop(process: subprocess.Popen[str]) -> None:
    """Hard-terminate one authority process and close its captured output streams."""

    if process.poll() is None:
        process.kill()
    process.communicate(timeout=5)


def _owner_authority(tmp_path: Path, membership: SeedCommitMembership) -> RecoveryLineageAuthority:
    """Open the owner authority journal in the coordinating process, independently of every remote process."""

    return RecoveryLineageAuthority(
        membership,
        membership.owner_id,
        tmp_path / "authorities" / f"{membership.owner_id}.jsonl",
    )


def _coordinator(
    membership: SeedCommitMembership,
    owner: RecoveryLineageAuthority,
    peers: dict[str, RecoveryLineagePeerClient],
) -> DistributedRecoveryLineageCoordinator:
    """Compose one local owner authority and every independent remote member process."""

    return DistributedRecoveryLineageCoordinator(
        membership,
        {membership.owner_id: owner, **peers},
    )


def test_remote_prepare_process_death_preserves_vote_and_exact_retry(tmp_path: Path) -> None:
    """Mathematics: a child hard-killed after PREPARE fsync reopens with the same vote and then joins a durable quorum."""

    membership = _membership()
    manifest = _manifest(membership)
    owner = _owner_authority(tmp_path, membership)
    proposal = RecoveryLineageCoordinator(membership, {"A": owner}).proposal_for(manifest)

    crashed, first_peer = _start_member(
        tmp_path,
        membership,
        "B",
        fault_stage="after_prepare_fsync",
    )
    process_c, peer_c = _start_member(tmp_path, membership, "C")
    try:
        with pytest.raises(RecoveryLineageTransportError):
            first_peer.prepare(proposal)
        first_peer.close()
        marker_path = tmp_path / "B-after_prepare_fsync.json"
        marker = _await_marker(marker_path, crashed)
        assert marker["stage"] == "after_prepare_fsync"
        assert marker["member_id"] == "B"
        crashed.wait(timeout=5)
        assert crashed.returncode == 91

        # The journal is already durable although B never sent a vote or ACK.
        saved_vote = DurableSeedCommitLedger(
            tmp_path / "authorities" / "B.jsonl",
            "B",
            membership,
        ).prepared_vote(proposal)
        assert saved_vote is not None

        # B is unavailable; A and C are still a strict majority and can seal.
        coordinator_without_b = _coordinator(
            membership,
            owner,
            {"B": first_peer, "C": peer_c},
        )
        first_proof = coordinator_without_b.seal(manifest)
        assert tuple(sorted(vote.member_id for vote in first_proof.certificate.votes)) == ("A", "C")
        assert coordinator_without_b.high_water() == (1, manifest.digest)
    finally:
        first_peer.close()
        _stop(crashed)

    restarted_b, peer_b = _start_member(tmp_path, membership, "B")
    try:
        durable_vote = peer_b.prepare(proposal)
        assert durable_vote == saved_vote
        coordinator = _coordinator(membership, owner, {"B": peer_b, "C": peer_c})
        proof = coordinator.seal(manifest)
        assert proof.certificate.snapshot() == first_proof.certificate.snapshot()
        assert len(proof.decisions) >= membership.quorum
        assert coordinator.high_water() == (1, manifest.digest)
    finally:
        peer_b.close()
        peer_c.close()
        _stop(restarted_b)
        _stop(process_c)


def test_remote_commit_process_death_reuses_original_certificate(tmp_path: Path) -> None:
    """Mathematics: a child hard-killed after COMMIT fsync reopens with its decision and the coordinator reuses the exact certificate."""

    membership = _membership()
    manifest = _manifest(membership)
    owner = _owner_authority(tmp_path, membership)
    proposal = RecoveryLineageCoordinator(membership, {"A": owner}).proposal_for(manifest)
    owner_vote = owner.prepare(proposal)

    crashed, first_peer = _start_member(
        tmp_path,
        membership,
        "B",
        fault_stage="after_commit_fsync",
    )
    try:
        remote_vote = first_peer.prepare(proposal)
        original_certificate = SeedCommitCertificate(
            membership.digest,
            proposal.digest,
            tuple(sorted((owner_vote, remote_vote), key=lambda vote: vote.member_id)),
        )
        with pytest.raises(RecoveryLineageTransportError):
            first_peer.commit(proposal, original_certificate)
        first_peer.close()
        marker = _await_marker(tmp_path / "B-after_commit_fsync.json", crashed)
        assert marker["stage"] == "after_commit_fsync"
        crashed.wait(timeout=5)
        assert crashed.returncode == 91
    finally:
        _stop(crashed)

    restarted_b, peer_b = _start_member(tmp_path, membership, "B")
    process_c, peer_c = _start_member(tmp_path, membership, "C")
    try:
        restored_decision = peer_b.decision(proposal)
        assert restored_decision is not None
        assert restored_decision.certificate_members == ("A", "B")
        assert peer_b.certificate(proposal).snapshot() == original_certificate.snapshot()
        coordinator = _coordinator(membership, owner, {"B": peer_b, "C": peer_c})
        proof = coordinator.seal(manifest)
        assert proof.certificate.snapshot() == original_certificate.snapshot()
        assert len(proof.decisions) >= membership.quorum
        assert coordinator.high_water() == (1, manifest.digest)
    finally:
        peer_b.close()
        peer_c.close()
        _stop(restarted_b)
        _stop(process_c)


def test_remote_authorities_restart_after_quorum_commit_and_restore_bundle_high_water(
    tmp_path: Path,
) -> None:
    """Mathematics: quorum-sealed checkpoint roots remain readable after every remote authority process is hard-killed and reopened."""

    membership = _membership()
    owner = _owner_authority(tmp_path, membership)
    process_b, peer_b = _start_member(tmp_path, membership, "B")
    process_c, peer_c = _start_member(tmp_path, membership, "C")
    requester_path = tmp_path / "requester.json"
    receiver_path = tmp_path / "receiver.json"
    requester_path.write_bytes(b'{"requester":"independent durable state"}')
    receiver_path.write_text(
        json.dumps(
            {
                "format": "mailcpu-transit-worker-checkpoint-v2",
                "state": {"backend_manifest": [["cpu.execute", "/cpu/compute"]]},
            },
            sort_keys=True,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    try:
        coordinator = _coordinator(membership, owner, {"B": peer_b, "C": peer_c})
        bundle_store = RecoveryCheckpointBundleStore(tmp_path / "bundles", coordinator)
        sealed = bundle_store.seal(requester_path, receiver_path, "after_response_publish")
        assert sealed.generation == 1
        assert coordinator.high_water() == (1, sealed.manifest.digest)
    finally:
        peer_b.close()
        peer_c.close()
        _stop(process_b)
        _stop(process_c)

    # Recreate the owner authority object as well: all three journals are
    # reopened from disk before the bundle read quorum is queried.
    reopened_owner = _owner_authority(tmp_path, membership)
    restarted_b, reopened_b = _start_member(tmp_path, membership, "B")
    restarted_c, reopened_c = _start_member(tmp_path, membership, "C")
    try:
        restored_coordinator = _coordinator(
            membership,
            reopened_owner,
            {"B": reopened_b, "C": reopened_c},
        )
        restored_store = RecoveryCheckpointBundleStore(tmp_path / "bundles", restored_coordinator)
        restored = restored_store.load_latest()
        assert restored.manifest.digest == sealed.manifest.digest
        assert restored.proof.snapshot() == sealed.proof.snapshot()
        assert restored_coordinator.verify_checkpoint(restored.manifest).proposal.digest == (
            restored_coordinator.proposal_for(restored.manifest).digest
        )
        assert all(peer.verify() for peer in (reopened_b, reopened_c))
    finally:
        reopened_b.close()
        reopened_c.close()
        _stop(restarted_b)
        _stop(restarted_c)

