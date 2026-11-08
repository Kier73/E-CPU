from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest

from mailcpu import (
    ComputationalFabricForwardingRecoveryError,
    ComputationalFabricForwardingRecoveryStore,
    RecoveryLineageAuthority,
    RecoveryLineageCoordinator,
    SeedCommitMembership,
)


GENESIS = hashlib.sha256(b"computational-fabric-forwarding-recovery-genesis-v1").hexdigest()


def _membership() -> SeedCommitMembership:
    """Construct one fixed three-member majority for independent hop checkpoint roots."""
    return SeedCommitMembership(
        "fabric-forwarding-system",
        1,
        ("anchor-a", "anchor-b", "anchor-c"),
        "anchor-a",
        1,
        GENESIS,
    )


def _coordinator(root: Path) -> RecoveryLineageCoordinator:
    """Open the same durable authority journals as a fresh coordinator incarnation."""
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


def _snapshot(capture_cut: str, *, inbound_cursor: int = 1) -> dict[str, Any]:
    """Make a structurally valid minimal peer snapshot for the immutable lineage-store tests."""
    return {
        "schema": "mailcpu.computational-fabric-forwarding-server.v1",
        "version": 1,
        "capture_cut": capture_cut,
        "local_peer_id": "peer-b",
        "previous_peer_id": "peer-a",
        "origin_peer_id": "peer-a",
        "origin_channel": "application.batch",
        "authority_pid": 7,
        "timeout": 5.0,
        "max_payload_bytes": 1_048_576,
        "operating_system": {
            "vm": {"state": "checkpointed"},
            "services": {},
            "hypervisor": {},
            "hypervisor_arbitration": {
                "executions": [{"source": "peer-a", "channel": "operation", "sequence": 9}]
            },
            "seed_admission": {},
            "structural_memory": {},
        },
        "inbound_channel": {
            "version": 4,
            "source": "peer-b",
            "destination": "peer-b",
            "channel": "forwarding",
            "peer": "peer-a",
            "next_receive_sequence": inbound_cursor,
            "pending": {},
        },
        "outbound_channel": {
            "version": 1,
            "channel": {
                "version": 4,
                "source": "peer-b",
                "destination": "peer-a",
                "channel": "forwarding.result",
                "peer": None,
                "pending": {},
            },
            "operation_source": "peer-a",
            "operation_channel": "operation",
            "seen": [],
        },
        "next_hop_clients": {},
    }


def test_forwarding_peer_snapshot_is_quorum_anchored_and_restores_exact_capture_cut(tmp_path: Path) -> None:
    """A fresh coordinator admits only the exact durable peer snapshot named by the quorum root."""
    root = tmp_path / "authorities"
    store = ComputationalFabricForwardingRecoveryStore(
        tmp_path / "forwarding-checkpoints",
        _coordinator(root),
    )
    snapshot = _snapshot("after_execution_commit", inbound_cursor=1)

    sealed = store.seal_snapshot(snapshot, "after_execution_commit")

    assert sealed.generation == 1
    assert sealed.manifest.capture_cut == "after_execution_commit"
    assert sealed.proof.proposal.result_state_digest == sealed.manifest.digest
    assert sealed.snapshot == snapshot

    reopened = ComputationalFabricForwardingRecoveryStore(
        tmp_path / "forwarding-checkpoints",
        _coordinator(root),
    ).load_latest()
    assert reopened.generation == 1
    assert reopened.manifest == sealed.manifest
    assert reopened.snapshot == snapshot
    assert reopened.snapshot_bytes == sealed.snapshot_bytes


def test_forwarding_recovery_refuses_modified_peer_snapshot(tmp_path: Path) -> None:
    """Changing one endpoint ledger after durable publication cannot override its quorum-bound digest."""
    store = ComputationalFabricForwardingRecoveryStore(
        tmp_path / "forwarding-checkpoints",
        _coordinator(tmp_path / "authorities"),
    )
    sealed = store.seal_snapshot(_snapshot("after_response_publish"), "after_response_publish")
    artifact = (
        store.directory
        / f"generation-{sealed.generation:020d}"
        / store.SNAPSHOT_FILE
    )
    artifact.write_bytes(artifact.read_bytes() + b" ")

    with pytest.raises(ComputationalFabricForwardingRecoveryError, match="digest"):
        store.load_latest()


def test_forwarding_recovery_rejects_valid_older_peer_generation(tmp_path: Path) -> None:
    """An earlier valid hop image is stale after a later capture is quorum committed."""
    root = tmp_path / "authorities"
    store = ComputationalFabricForwardingRecoveryStore(
        tmp_path / "forwarding-checkpoints",
        _coordinator(root),
    )
    first = store.seal_snapshot(_snapshot("after_execution_commit"), "after_execution_commit")
    second = store.seal_snapshot(
        _snapshot("after_response_publish", inbound_cursor=2),
        "after_response_publish",
    )

    assert second.generation == first.generation + 1
    assert second.manifest.predecessor_digest == first.manifest.digest
    with pytest.raises(ComputationalFabricForwardingRecoveryError, match="stale"):
        store.load(first.generation)


def test_forwarding_recovery_rejects_unknown_transaction_cut(tmp_path: Path) -> None:
    """Only named request/commit/publication/ack boundaries can be sealed."""
    store = ComputationalFabricForwardingRecoveryStore(
        tmp_path / "forwarding-checkpoints",
        _coordinator(tmp_path / "authorities"),
    )
    with pytest.raises(ComputationalFabricForwardingRecoveryError, match="capture_cut"):
        store.seal_snapshot(_snapshot("somewhere"), "somewhere")

def test_forwarding_restore_refuses_mutated_verified_checkpoint_projection(tmp_path: Path) -> None:
    """A caller cannot mutate the loaded object after disk verification and restore a different peer state."""
    store = ComputationalFabricForwardingRecoveryStore(
        tmp_path / "forwarding-checkpoints",
        _coordinator(tmp_path / "authorities"),
    )
    sealed = store.seal_snapshot(_snapshot("after_execution_commit"), "after_execution_commit")
    sealed.snapshot["origin_channel"] = "forged.operation"

    with pytest.raises(ComputationalFabricForwardingRecoveryError, match="modified in memory"):
        sealed.restore_operating_system()

