"""Shared membership and durable authority paths for process recovery tests."""

from __future__ import annotations

import hashlib
from pathlib import Path

from mailcpu import (
    RecoveryCheckpointBundleStore,
    RecoveryLineageAuthority,
    RecoveryLineageCoordinator,
    SeedCommitMembership,
)

GENESIS = hashlib.sha256(b"mailcpu-transit-process-recovery-genesis-v1").hexdigest()


def open_recovery_bundle_store(root: str | Path) -> RecoveryCheckpointBundleStore:
    """Mathematics: Reopen the same fixed three-member authority set and its external checkpoint bundle directory."""

    directory = Path(root)
    anchors = directory / "authorities"
    anchors.mkdir(parents=True, exist_ok=True)
    membership = SeedCommitMembership(
        "transit-process-recovery-machine",
        1,
        ("A", "B", "C"),
        "A",
        1,
        GENESIS,
    )
    authorities = {
        member: RecoveryLineageAuthority(
            membership,
            member,
            anchors / f"{member}.jsonl",
        )
        for member in membership.member_ids
    }
    coordinator = RecoveryLineageCoordinator(membership, authorities)
    return RecoveryCheckpointBundleStore(directory / "bundles", coordinator)
