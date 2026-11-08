from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

vgi = pytest.importorskip("vgi")
from vgi import SIGNAL8_GROUND, Signal8Backend

from mailcpu.computational_objects import ComputationalObjectStore
from mailcpu.computational_session import ComputationalSessionStore
from mailcpu.recovery_lineage import RecoveryLineageAuthority, RecoveryLineageCoordinator
from mailcpu.seed_commit_quorum import SeedCommitMembership
from mailcpu.vgi_session import (
    DEFAULT_MAX_STATE_BYTES,
    VGI_SESSION_MEDIA_TYPE,
    VGI_SESSION_STATE_SCHEMA,
    VGISessionError,
    VGICompiledSessionDescriptor,
    VGISessionTransferBundle,
    VGIPersistentSession,
    vgi_signal8_session_backend_fingerprint,
)

GENESIS = hashlib.sha256(b"mailcpu-recovery-lineage-genesis-v1").hexdigest()
SESSION_ID = "vgi-persistent-session"
STATE_LIMIT = 1024 * 1024


class MemoryPageBacking:
    """Mathematics: Fixed-size content-addressed page backing used to prove independent M1 host admission."""

    def __init__(self, page_size: int = 32) -> None:
        """Mathematics: Initialize one empty immutable page table with fixed page geometry."""
        self.page_size = page_size
        self.pages: dict[str, bytes] = {}

    def put_page(self, data: bytes) -> str:
        """Mathematics: Admit one exact page under its SHA-256 identity."""
        digest = hashlib.sha256(data).hexdigest()
        self.pages.setdefault(digest, data)
        return digest

    def get_page(self, digest: str) -> bytes:
        """Mathematics: Resolve one exact page previously admitted by its content digest."""
        return self.pages[digest]


def _task() -> dict[str, object]:
    """Mathematics: Declare a two-input addition task under the Signal8 computational Ground."""
    return {
        "name": "persistent-add",
        "inputs": ["input.a", "input.b"],
        "outputs": [{
            "label": "sum",
            "expression": {
                "type": "add",
                "left": {"type": "input", "address": "input.a"},
                "right": {"type": "input", "address": "input.b"},
            },
        }],
    }


def _membership() -> SeedCommitMembership:
    """Mathematics: Construct one strict-majority recovery membership dedicated to this VGI session."""
    return SeedCommitMembership(
        SESSION_ID,
        1,
        ("A", "B", "C"),
        "A",
        1,
        GENESIS,
    )


def _lineage(journal_root: Path) -> RecoveryLineageCoordinator:
    """Mathematics: Reopen each durable authority journal to construct an independent verifier for the same quorum lineage."""
    membership = _membership()
    authorities = {
        member: RecoveryLineageAuthority(
            membership,
            member,
            journal_root / f"{member}.jsonl",
        )
        for member in membership.member_ids
    }
    return RecoveryLineageCoordinator(membership, authorities)


def _store(
    root: Path,
    journal_root: Path,
    descriptor: VGICompiledSessionDescriptor,
    *,
    max_quantum_steps: int,
    max_total_steps: int = 100,
    max_state_bytes: int = STATE_LIMIT,
    backing: MemoryPageBacking | None = None,
    backend_compatibility=None,
):
    """Mathematics: Bind one M3 session to the descriptor artifact, target backend profile, and receiver-local M1 page table."""
    backend = vgi_signal8_session_backend_fingerprint(
        max_quantum_steps=max_quantum_steps,
        max_total_steps=max_total_steps,
        max_state_bytes=max_state_bytes,
    )
    object_store = ComputationalObjectStore(
        backing or MemoryPageBacking(),
        chunk_size=32,
    )
    store = ComputationalSessionStore(
        root,
        object_store,
        _lineage(journal_root),
        artifact_manifest_digest=descriptor.artifact_manifest_digest,
        backend_fingerprint=backend,
        state_schema_id=VGI_SESSION_STATE_SCHEMA,
        state_media_type=VGI_SESSION_MEDIA_TYPE,
    )
    runtime = VGIPersistentSession(
        store,
        descriptor,
        max_quantum_steps=max_quantum_steps,
        max_total_steps=max_total_steps,
        max_state_bytes=max_state_bytes,
        backend_compatibility=backend_compatibility,
    )
    return store, runtime


def _initial_memory() -> dict[str, object]:
    """Mathematics: Encode two bounded Signal8 symbols in the same observer coordinate."""
    backend = Signal8Backend()
    return {
        "input.a": backend.encode_symbol(2, observer=1),
        "input.b": backend.encode_symbol(3, observer=1),
    }


def test_m5_initializes_and_restores_machine_state_through_m1_and_m3(tmp_path: Path) -> None:
    """The initial VGI machine is represented as M1 bytes and exposed only by a quorum-anchored M3 checkpoint."""
    descriptor = VGICompiledSessionDescriptor.from_task(_task(), SIGNAL8_GROUND.fingerprint)
    store, runtime = _store(
        tmp_path / "host-A",
        tmp_path / "quorum",
        descriptor,
        max_quantum_steps=2,
    )

    created = runtime.initialize(_initial_memory())
    restored = runtime.load()

    assert created.revision == restored.revision == 1
    assert created.status == restored.status == "ready"
    assert restored.total_steps == 0
    assert restored.session.state_bytes
    assert restored.session.checkpoint.state_schema_id == VGI_SESSION_STATE_SCHEMA
    assert restored.session.checkpoint.state_manifest.media_type == VGI_SESSION_MEDIA_TYPE
    assert restored.session.checkpoint.artifact_manifest_digest == descriptor.artifact_manifest_digest
    assert restored.session.checkpoint.backend_fingerprint == runtime.backend_fingerprint
    assert store.object_store.verify(restored.session.checkpoint.state_manifest)
    assert restored.session.proof.proposal.result_state_digest == restored.session.lineage_manifest.digest


def test_m6_bounded_quanta_resume_the_same_machine_and_exact_retry_is_idempotent(tmp_path: Path) -> None:
    """A machine advances in bounded instruction quanta and resumes from each exact committed snapshot."""
    descriptor = VGICompiledSessionDescriptor.from_task(_task(), SIGNAL8_GROUND.fingerprint)
    store, runtime = _store(
        tmp_path / "host-A",
        tmp_path / "quorum",
        descriptor,
        max_quantum_steps=2,
    )
    runtime.initialize(_initial_memory())

    first = runtime.advance(2, operation_id="quantum-1")
    replay = runtime.advance(2, operation_id="quantum-1")

    assert first.revision == 2
    assert first.total_steps == 2
    assert first.status == "running"
    assert replay.replayed is True
    assert replay.revision == first.revision
    assert replay.checkpoint_digest == first.checkpoint_digest
    assert replay.session.checkpoint.logical_time == first.session.checkpoint.logical_time

    restarted_runtime = VGIPersistentSession(
        store,
        descriptor,
        max_quantum_steps=2,
        max_total_steps=100,
        max_state_bytes=STATE_LIMIT,
    )
    resumed = restarted_runtime.load()
    assert resumed.total_steps == first.total_steps
    assert resumed.execution.final_pc == first.execution.final_pc

    second = restarted_runtime.advance(2, operation_id="quantum-2")
    third = restarted_runtime.advance(2, operation_id="quantum-3")

    assert second.total_steps == 4
    assert second.status == "running"
    assert third.total_steps == 6
    assert third.status == "halted"
    assert third.halted is True
    assert third.revision == 4
    assert third.session.checkpoint.logical_time == 3
    assert len(third.execution.outputs) == 1
    assert Signal8Backend().observe_symbol(third.execution.outputs[0].value) == 5


def test_m6_quantum_and_total_step_bounds_are_enforced_without_losing_progress(tmp_path: Path) -> None:
    """Quantum admission is bounded and the cumulative limit commits an explicit step_limit state."""
    descriptor = VGICompiledSessionDescriptor.from_task(_task(), SIGNAL8_GROUND.fingerprint)
    _, runtime = _store(
        tmp_path / "host-A",
        tmp_path / "quorum",
        descriptor,
        max_quantum_steps=2,
        max_total_steps=3,
    )
    runtime.initialize(_initial_memory())

    with pytest.raises(VGISessionError, match="quantum_steps"):
        runtime.advance(3, operation_id="too-large")

    first = runtime.advance(2, operation_id="quantum-1")
    limited = runtime.advance(2, operation_id="quantum-2")
    replay = runtime.advance(2, operation_id="quantum-2")

    assert first.total_steps == 2
    assert limited.total_steps == 3
    assert limited.last_quantum_steps == 1
    assert limited.status == "step_limit"
    assert replay.replayed is True
    assert replay.checkpoint_digest == limited.checkpoint_digest
    with pytest.raises(VGISessionError, match="max_total_steps"):
        runtime.advance(1, operation_id="beyond-limit")


def test_m7_transfer_reanchors_m1_pages_and_continues_under_compatible_target_profile(tmp_path: Path) -> None:
    """A distinct target host imports state bytes into its own M1 store, verifies quorum proof, and continues with explicit backend compatibility."""
    descriptor = VGICompiledSessionDescriptor.from_task(_task(), SIGNAL8_GROUND.fingerprint)
    journal_root = tmp_path / "quorum"
    source_store, source = _store(
        tmp_path / "host-A",
        journal_root,
        descriptor,
        max_quantum_steps=2,
    )
    source.initialize(_initial_memory())
    first = source.advance(1, operation_id="source-quantum-1")
    bundle_dict = source.export_transfer().to_dict()
    bundle = VGISessionTransferBundle.from_dict(
        bundle_dict,
        max_state_bytes=STATE_LIMIT,
    )

    target_store, target_without_compatibility = _store(
        tmp_path / "host-B-no-compat",
        journal_root,
        descriptor,
        max_quantum_steps=1,
        backing=MemoryPageBacking(),
    )
    with pytest.raises(VGISessionError, match="backend differs"):
        target_without_compatibility.restore_transfer(bundle)

    source_backend = source.backend_fingerprint
    target_backend = vgi_signal8_session_backend_fingerprint(
        max_quantum_steps=1,
        max_total_steps=100,
        max_state_bytes=STATE_LIMIT,
    )
    approval = {"enabled": True}

    def compatibility(source_fp: str, target_fp: str, schema: str) -> bool:
        """Mathematics: Admit only the exact source/target backend profiles while migration approval remains active."""
        return (
            approval["enabled"]
            and source_fp == source_backend
            and target_fp == target_backend
            and schema == VGI_SESSION_STATE_SCHEMA
        )
    target_store, target = _store(
        tmp_path / "host-B",
        journal_root,
        descriptor,
        max_quantum_steps=1,
        backing=MemoryPageBacking(),
        backend_compatibility=compatibility,
    )

    restored = target.restore_transfer(bundle)
    assert restored.revision == first.revision
    assert restored.total_steps == first.total_steps
    assert restored.execution.final_pc == first.execution.final_pc
    assert restored.session.checkpoint.backend_fingerprint == source_backend
    assert target_store.object_store.verify(restored.session.checkpoint.state_manifest)

    approval["enabled"] = False
    with pytest.raises(VGISessionError, match="compatibility"):
        target.load()
    approval["enabled"] = True

    captured_contexts = []
    target_backend_adapter = target.transition_adapter.backend
    original_transition = target_backend_adapter.transition

    def capture_context(state_bytes, input_bytes, context):
        """Mathematics: Record migration provenance while preserving the actual VGI transition."""
        captured_contexts.append(context)
        return original_transition(state_bytes, input_bytes, context)

    target_backend_adapter.transition = capture_context
    continued = target.advance(1, operation_id="target-quantum-2")
    assert len(captured_contexts) == 1
    assert captured_contexts[0].backend_fingerprint == source_backend
    assert captured_contexts[0].execution_backend_fingerprint == target_backend
    assert continued.revision == restored.revision + 1
    assert continued.total_steps == 2
    assert continued.session.checkpoint.backend_fingerprint == target_backend
    assert continued.status == "running"
    assert target.load().checkpoint_digest == continued.checkpoint_digest

def test_m5_compiled_descriptor_binds_ground_task_program_and_m2_artifact() -> None:
    """The VGI session descriptor keeps declared Ground, typed task, Program IR, and artifact identities distinct."""
    first = VGICompiledSessionDescriptor.from_task(_task(), SIGNAL8_GROUND.fingerprint)
    changed_task = _task()
    changed_task["outputs"] = [{
        "label": "first",
        "expression": {"type": "input", "address": "input.a"},
    }]
    second = VGICompiledSessionDescriptor.from_task(changed_task, SIGNAL8_GROUND.fingerprint)

    assert first.ground_fingerprint == second.ground_fingerprint
    assert first.task_digest != second.task_digest
    assert first.program_fingerprint != second.program_fingerprint
    assert first.compiled_plan_digest != second.compiled_plan_digest
    assert first.interpretation_fingerprint != second.interpretation_fingerprint
    assert first.artifact_manifest_digest != second.artifact_manifest_digest
    restored = VGICompiledSessionDescriptor.from_dict(first.to_dict())
    assert restored.descriptor_digest == first.descriptor_digest
    assert restored.artifact_manifest_digest == first.artifact_manifest_digest


def test_m7_transfer_bundle_refuses_tampered_machine_state_bytes(tmp_path: Path) -> None:
    """A transfer envelope cannot substitute machine bytes while retaining its original M1 and bundle identities."""
    descriptor = VGICompiledSessionDescriptor.from_task(_task(), SIGNAL8_GROUND.fingerprint)
    _, source = _store(
        tmp_path / "host-A",
        tmp_path / "quorum",
        descriptor,
        max_quantum_steps=2,
    )
    source.initialize(_initial_memory())
    transfer = source.export_transfer().to_dict()
    altered = dict(transfer)
    encoded = transfer["state_bytes_base64"]
    replacement = ("A" if encoded[0] != "A" else "B") + encoded[1:]
    altered["state_bytes_base64"] = replacement

    with pytest.raises(VGISessionError, match="state length or digest mismatch|bundle digest mismatch"):
        VGISessionTransferBundle.from_dict(altered, max_state_bytes=STATE_LIMIT)