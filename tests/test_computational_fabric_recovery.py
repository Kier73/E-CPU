from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from mailcpu import (
    ComputationalFabricDirectory,
    ComputationalFabricRecoveryError,
    ComputationalFabricRecoveryStore,
    ComputationalPeerEndpoint,
    ComputationalPeerSnapshot,
    RecoveryLineageAuthority,
    RecoveryLineageCoordinator,
    RecoveryLineageError,
    SeedCommitMembership,
)


GENESIS = hashlib.sha256(b"computational-fabric-recovery-genesis-v1").hexdigest()


def _membership() -> SeedCommitMembership:
    """Construct fixed membership for the fabric directory's independent recovery root."""
    return SeedCommitMembership(
        "fabric-system",
        1,
        ("anchor-a", "anchor-b", "anchor-c"),
        "anchor-a",
        1,
        GENESIS,
    )


def _coordinator(root: Path) -> RecoveryLineageCoordinator:
    """Open three independent durable recovery authorities from their participant journals."""
    membership = _membership()
    authorities = {
        member: RecoveryLineageAuthority(
            membership,
            member,
            root / "authorities" / f"{member}.jsonl",
        )
        for member in membership.member_ids
    }
    return RecoveryLineageCoordinator(membership, authorities)


def _snapshot(peer_id: str, revision: int = 1, lease: int = 30) -> ComputationalPeerSnapshot:
    """Create one empty peer-owned snapshot with a stable endpoint identity."""
    return ComputationalPeerSnapshot(
        ComputationalPeerEndpoint(
            peer_id,
            f"{peer_id}.fabric.test",
            "127.0.0.1",
            41000 + len(peer_id),
        ),
        revision,
        lease,
        (),
        (),
    )


def _directory() -> ComputationalFabricDirectory:
    """Create a local directory with monotonic state for both its own peer and one directly trusted peer."""
    directory = ComputationalFabricDirectory(
        "peer-a",
        {"peer-b": "peer-b.fabric.test"},
    )
    local = _snapshot("peer-a", revision=3)
    remote = _snapshot("peer-b", revision=7)
    assert directory.register_local_snapshot(local)
    assert directory._merge_verified_peer_snapshot(
        remote,
        authenticated_peer_id="peer-b",
        authenticated_server_name="peer-b.fabric.test",
    )
    return directory


def test_fabric_directory_checkpoint_is_quorum_anchored_and_reauthenticates_after_restore(tmp_path: Path) -> None:
    """A restored federated directory retains anti-rollback state but never revives a remote lease."""
    directory = _directory()
    store = ComputationalFabricRecoveryStore(tmp_path / "fabric-checkpoints", _coordinator(tmp_path))

    sealed = store.seal(directory, "after_peer_snapshot_merge")

    assert sealed.generation == 1
    assert sealed.proof.proposal.slot == 1
    assert sealed.proof.proposal.result_state_digest == sealed.manifest.digest
    assert sealed.directory.peer_revision_high_water == directory.peer_revision_high_water
    assert sealed.directory.peer_snapshots == ()
    assert sealed.directory.active_snapshots == ()

    reopened_store = ComputationalFabricRecoveryStore(
        tmp_path / "fabric-checkpoints",
        _coordinator(tmp_path),
    )
    restored = reopened_store.load_latest()

    assert restored.generation == 1
    assert restored.manifest == sealed.manifest
    assert restored.directory.trusted_peers == directory.trusted_peers
    assert restored.directory.peer_revision_high_water == directory.peer_revision_high_water
    assert restored.directory.peer_snapshots == ()
    assert restored.directory.active_snapshots == ()

    with pytest.raises(ValueError, match="rollback"):
        restored.directory._merge_verified_peer_snapshot(
            _snapshot("peer-b", revision=6),
            authenticated_peer_id="peer-b",
            authenticated_server_name="peer-b.fabric.test",
        )
    with pytest.raises(ValueError, match="equivocated"):
        restored.directory._merge_verified_peer_snapshot(
            _snapshot("peer-b", revision=7, lease=45),
            authenticated_peer_id="peer-b",
            authenticated_server_name="peer-b.fabric.test",
        )

    assert restored.directory._merge_verified_peer_snapshot(
        _snapshot("peer-b", revision=7),
        authenticated_peer_id="peer-b",
        authenticated_server_name="peer-b.fabric.test",
    )
    assert tuple(item.peer_id for item in restored.directory.active_snapshots) == ("peer-b",)


def test_fabric_recovery_refuses_modified_artifact_and_unanchored_generation(tmp_path: Path) -> None:
    """Local bytes cannot override the quorum root, and a local artifact without a majority is not admitted."""
    directory = _directory()
    store = ComputationalFabricRecoveryStore(tmp_path / "fabric-checkpoints", _coordinator(tmp_path))
    sealed = store.seal(directory, "quorum_commit")

    generation_dir = store.directory / f"generation-{sealed.generation:020d}"
    checkpoint_path = generation_dir / store.DIRECTORY_FILE
    original = checkpoint_path.read_bytes()
    checkpoint_path.write_bytes(original + b" ")

    with pytest.raises(ComputationalFabricRecoveryError, match="digest"):
        store.load_latest()


def test_fabric_recovery_rejects_valid_older_generation_after_newer_commit(tmp_path: Path) -> None:
    """A previously valid local directory artifact is stale after a later quorum high-water commit."""
    root = tmp_path / "authority-root"
    store = ComputationalFabricRecoveryStore(tmp_path / "fabric-checkpoints", _coordinator(root))
    first_directory = _directory()
    first = store.seal(first_directory, "generation_one")

    second_directory = _directory()
    second_directory._merge_verified_peer_snapshot(
        _snapshot("peer-b", revision=8),
        authenticated_peer_id="peer-b",
        authenticated_server_name="peer-b.fabric.test",
    )
    second = store.seal(second_directory, "generation_two")

    assert second.generation == first.generation + 1
    assert second.manifest.predecessor_digest == first.manifest.digest
    with pytest.raises(ComputationalFabricRecoveryError, match="stale"):
        store.load(first.generation)


def test_fabric_recovery_refuses_missing_quorum_even_after_local_persistence(tmp_path: Path) -> None:
    """A locally durable fabric snapshot remains unadmitted when fewer than a strict majority commits its root."""
    membership = _membership()

    class PrepareRefusalAuthority(RecoveryLineageAuthority):
        """Keep readable genesis state while refusing to prepare a new recovery root."""

        def prepare(self, proposal):
            """Mathematics: Simulate an unavailable prepare participant without changing its durable high-water."""
            raise RecoveryLineageError("participant is unavailable for prepare")

    authorities = {
        member: (
            RecoveryLineageAuthority(membership, member, tmp_path / f"{member}.jsonl")
            if member == "anchor-a"
            else PrepareRefusalAuthority(membership, member, tmp_path / f"{member}.jsonl")
        )
        for member in membership.member_ids
    }
    coordinator = RecoveryLineageCoordinator(membership, authorities)
    store = ComputationalFabricRecoveryStore(tmp_path / "fabric-checkpoints", coordinator)

    with pytest.raises(ComputationalFabricRecoveryError, match="not quorum-anchored"):
        store.seal(_directory(), "no_quorum")

    generation_dir = store.directory / "generation-00000000000000000001"
    assert (generation_dir / store.DIRECTORY_FILE).is_file()
    with pytest.raises(ComputationalFabricRecoveryError):
        store.load_latest()
