"""Operational checkpoint bundle storage and quorum admission tests."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from mailcpu import (
    RecoveryCheckpointBundleError,
    RecoveryCheckpointBundleStore,
    RecoveryCheckpointManifest,
    RecoveryLineageAuthority,
    RecoveryLineageCoordinator,
    SeedCommitMembership,
)

GENESIS = hashlib.sha256(b"mailcpu-recovery-bundle-tests-genesis-v1").hexdigest()


def _membership() -> SeedCommitMembership:
    """Construct the fixed strict-majority membership used by bundle-store tests."""

    return SeedCommitMembership("bundle-machine", 1, ("A", "B", "C"), "A", 1, GENESIS)


def _store(root: Path, *, members: tuple[str, ...] = ("A", "B", "C")) -> RecoveryCheckpointBundleStore:
    """Open one coordinator over independent durable test authority journals."""

    membership = _membership()
    authorities = {
        member: RecoveryLineageAuthority(membership, member, root / "authorities" / f"{member}.jsonl")
        for member in members
    }
    return RecoveryCheckpointBundleStore(
        root / "bundles",
        RecoveryLineageCoordinator(membership, authorities),
    )


def _receiver_bytes(backend: list[list[str]] | None = None) -> bytes:
    """Encode the explicit backend domain carried by a v2 Transit receiver checkpoint."""

    value = {
        "format": "mailcpu-transit-worker-checkpoint-v2",
        "state": {"backend_manifest": backend or [["cpu.execute", "/cpu/compute"]]},
    }
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _write_sources(root: Path, requester: bytes, receiver: bytes) -> tuple[Path, Path]:
    """Persist source endpoint bytes used as the inputs to immutable bundle capture."""

    root.mkdir(parents=True, exist_ok=True)
    requester_path = root / "requester-source.json"
    receiver_path = root / "receiver-source.json"
    requester_path.write_bytes(requester)
    receiver_path.write_bytes(receiver)
    return requester_path, receiver_path


def test_bundle_store_persists_exact_generation_and_reopens_from_quorum(tmp_path: Path) -> None:
    """A stored generation is usable after its authority coordinator is reconstructed."""

    requester = b'{"requester":"durable"}'
    receiver = _receiver_bytes()
    requester_path, receiver_path = _write_sources(tmp_path, requester, receiver)
    store = _store(tmp_path)

    captured = store.seal(requester_path, receiver_path, "after_response_publish")

    assert captured.generation == 1
    assert captured.requester_checkpoint == requester
    assert captured.receiver_checkpoint == receiver
    assert captured.manifest.capture_cut == "after_response_publish"
    generation_dir = tmp_path / "bundles" / "generation-00000000000000000001"
    assert (generation_dir / "requester.json").read_bytes() == requester
    assert (generation_dir / "receiver.json").read_bytes() == receiver
    assert (generation_dir / "backend-manifest.json").read_bytes() == (
        b'[["cpu.execute","/cpu/compute"]]'
    )

    reopened = _store(tmp_path).load_latest()
    assert reopened.manifest == captured.manifest
    assert reopened.proof.snapshot() == captured.proof.snapshot()


@pytest.mark.parametrize(
    ("filename", "replacement"),
    (
        ("requester.json", b'{"requester":"changed"}'),
        ("receiver.json", _receiver_bytes([["cpu.execute", "/cpu/other"]])),
        ("backend-manifest.json", b'[["cpu.execute","/cpu/other"]]'),
        ("manifest.json", b'{"version":1}'),
    ),
)
def test_bundle_store_rejects_modified_generation_artifacts(
    tmp_path: Path,
    filename: str,
    replacement: bytes,
) -> None:
    """No altered endpoint, backend, or manifest artifact can cross the restore gate."""

    requester_path, receiver_path = _write_sources(
        tmp_path,
        b'{"requester":"original"}',
        _receiver_bytes(),
    )
    store = _store(tmp_path)
    store.seal(requester_path, receiver_path, "after_execution_commit")
    artifact = tmp_path / "bundles" / "generation-00000000000000000001" / filename
    artifact.write_bytes(replacement)

    with pytest.raises(RecoveryCheckpointBundleError):
        _store(tmp_path).load_latest()


def test_valid_older_generation_is_rejected_after_newer_quorum_commit(tmp_path: Path) -> None:
    """A valid old bundle remains on disk but cannot be restored after the quorum high-water advances."""

    requester_path, receiver_path = _write_sources(
        tmp_path,
        b'{"requester":"generation-1"}',
        _receiver_bytes(),
    )
    store = _store(tmp_path)
    first = store.seal(requester_path, receiver_path, "after_execution_commit")

    requester_path.write_bytes(b'{"requester":"generation-2"}')
    receiver_path.write_bytes(_receiver_bytes([["cpu.execute", "/cpu/compute"], ["mem.read", "/memory"]]))
    second = store.seal(requester_path, receiver_path, "after_request_ack")

    assert second.generation == first.generation + 1
    assert store.load_latest().generation == 2
    with pytest.raises(RecoveryCheckpointBundleError, match="stale"):
        store.load(generation=1)


def test_locally_durable_but_unanchored_bundle_is_not_admitted(tmp_path: Path) -> None:
    """Persisted endpoint bytes are not recoverable until a strict-majority prepare and commit succeeds."""

    membership = _membership()
    authorities = {
        member: RecoveryLineageAuthority(
            membership,
            member,
            tmp_path / "authorities" / f"{member}.jsonl",
        )
        for member in membership.member_ids
    }
    coordinator = RecoveryLineageCoordinator(membership, authorities)
    conflicting = RecoveryCheckpointManifest(
        machine_id=membership.system_id,
        incarnation=membership.incarnation,
        owner_id=membership.owner_id,
        owner_term=membership.owner_term,
        membership_digest=membership.digest,
        generation=1,
        predecessor_digest=GENESIS,
        requester_checkpoint_digest=hashlib.sha256(b"other-requester").hexdigest(),
        receiver_checkpoint_digest=hashlib.sha256(_receiver_bytes()).hexdigest(),
        backend_manifest_digest=hashlib.sha256(b'[["cpu.execute","/cpu/compute"]]').hexdigest(),
        capture_cut="before_execution",
    )
    authorities["A"].prepare(coordinator.proposal_for(conflicting))
    store = RecoveryCheckpointBundleStore(tmp_path / "bundles", coordinator)
    requester_path, receiver_path = _write_sources(
        tmp_path,
        b'{"requester":"actual"}',
        _receiver_bytes(),
    )

    with pytest.raises(RecoveryCheckpointBundleError, match="not quorum-anchored"):
        store.seal(requester_path, receiver_path, "before_execution")
    assert (tmp_path / "bundles" / "generation-00000000000000000001" / "manifest.json").is_file()
    with pytest.raises(RecoveryCheckpointBundleError, match="no checkpoint generation"):
        store.load_latest()


def test_bundle_generation_refuses_different_bytes_on_retry_for_same_slot(tmp_path: Path) -> None:
    """A partially prepared slot is immutable and cannot silently adopt new endpoint snapshots."""

    requester_path, receiver_path = _write_sources(
        tmp_path,
        b'{"requester":"original"}',
        _receiver_bytes(),
    )
    membership = _membership()
    authorities = {
        member: RecoveryLineageAuthority(membership, member, tmp_path / "authorities" / f"{member}.jsonl")
        for member in membership.member_ids
    }
    coordinator = RecoveryLineageCoordinator(membership, authorities)
    conflict = RecoveryCheckpointManifest(
        membership.system_id,
        membership.incarnation,
        membership.owner_id,
        membership.owner_term,
        membership.digest,
        1,
        GENESIS,
        hashlib.sha256(b"conflicting").hexdigest(),
        hashlib.sha256(_receiver_bytes()).hexdigest(),
        hashlib.sha256(b'[["cpu.execute","/cpu/compute"]]').hexdigest(),
        "before_execution",
    )
    authorities["A"].prepare(coordinator.proposal_for(conflict))
    store = RecoveryCheckpointBundleStore(tmp_path / "bundles", coordinator)

    with pytest.raises(RecoveryCheckpointBundleError):
        store.seal(requester_path, receiver_path, "before_execution")
    requester_path.write_bytes(b'{"requester":"changed"}')
    with pytest.raises(RecoveryCheckpointBundleError, match="different checkpoint bytes"):
        store.seal(requester_path, receiver_path, "before_execution")
