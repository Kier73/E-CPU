from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from mailcpu.computational_objects import ComputationalObjectStore
from mailcpu.computational_session import (
    ComputationalSessionConflictError,
    ComputationalSessionError,
    ComputationalSessionIntegrityError,
    ComputationalSessionPendingError,
    ComputationalSessionStore,
)
from mailcpu.recovery_lineage import (
    RecoveryLineageAuthority,
    RecoveryLineageCoordinator,
    RecoveryLineageError,
)
from mailcpu.seed_commit_quorum import SeedCommitMembership

GENESIS = hashlib.sha256(b"mailcpu-recovery-lineage-genesis-v1").hexdigest()
ARTIFACT = hashlib.sha256(b"generic-computational-artifact").hexdigest()
BACKEND_A = hashlib.sha256(b"backend-profile-A").hexdigest()
BACKEND_B = hashlib.sha256(b"backend-profile-B").hexdigest()
STATE_SCHEMA = "generic.state.v1"


class MemoryPageBacking:
    """Fixed-size content-addressed pages for computational session state tests."""

    def __init__(self, page_size: int = 32) -> None:
        """Create an empty page table with one immutable page geometry."""
        self.page_size = page_size
        self.pages: dict[str, bytes] = {}

    def put_page(self, data: bytes) -> str:
        """Admit one fixed-size page under its SHA-256 identity."""
        if not isinstance(data, bytes) or len(data) != self.page_size:
            raise ValueError("invalid page size")
        digest = hashlib.sha256(data).hexdigest()
        previous = self.pages.setdefault(digest, data)
        if previous != data:
            raise ValueError("content-address collision")
        return digest

    def get_page(self, digest: str) -> bytes:
        """Resolve one immutable page by its digest."""
        return self.pages[digest]


class CommitFailingAuthority(RecoveryLineageAuthority):
    """Authority fixture that persists PREPARE but refuses COMMIT at a selected crash cut."""

    def __init__(self, membership, member_id, journal_path, *, fail_commit: bool) -> None:
        """Bind the real durable journal while optionally injecting a commit refusal."""
        super().__init__(membership, member_id, journal_path)
        self.fail_commit = fail_commit

    def commit(self, proposal, certificate):
        """Inject failure before COMMIT fsync while preserving the already durable vote."""
        if self.fail_commit:
            raise RecoveryLineageError("injected commit interruption")
        return super().commit(proposal, certificate)


def _membership(session_id: str = "session-A") -> SeedCommitMembership:
    """Create a fixed strict-majority membership dedicated to one session identity."""
    return SeedCommitMembership(
        session_id,
        1,
        ("A", "B", "C"),
        "A",
        1,
        GENESIS,
    )


def _authorities(root: Path, membership: SeedCommitMembership, *, failing: bool = False):
    """Open one independent durable journal per configured recovery authority."""
    result = {}
    for member in membership.member_ids:
        journal = root / "authorities" / f"{membership.system_id}-{member}.jsonl"
        if failing:
            result[member] = CommitFailingAuthority(
                membership,
                member,
                journal,
                fail_commit=member in {"B", "C"},
            )
        else:
            result[member] = RecoveryLineageAuthority(membership, member, journal)
    return result


def _object_store(backing: MemoryPageBacking | None = None) -> ComputationalObjectStore:
    """Create the existing M1 object store over the test page backing."""
    return ComputationalObjectStore(backing or MemoryPageBacking(), chunk_size=32)


def _store(
    root: Path,
    lineage: RecoveryLineageCoordinator,
    *,
    object_store: ComputationalObjectStore | None = None,
    backend: str = BACKEND_A,
    artifact: str = ARTIFACT,
    schema: str = STATE_SCHEMA,
) -> ComputationalSessionStore:
    """Create one session store bound to a fixed session lineage and generic computational identities."""
    return ComputationalSessionStore(
        root,
        object_store or _object_store(),
        lineage,
        artifact_manifest_digest=artifact,
        backend_fingerprint=backend,
        state_schema_id=schema,
    )


def _input_digest(value: bytes) -> str:
    """Return the request input digest used as the transition identity commitment."""
    return hashlib.sha256(value).hexdigest()


def _initialize(store: ComputationalSessionStore, state: bytes = b"state-0"):
    """Commit the initial revision with a stable generic initialization identity."""
    return store.create_session(state)


def test_create_and_load_initial_state_is_quorum_anchored(tmp_path: Path) -> None:
    """Initial state bytes are page-backed before revision one becomes the quorum high-water."""
    membership = _membership()
    lineage = RecoveryLineageCoordinator(membership, _authorities(tmp_path, membership))
    store = _store(tmp_path / "host-A", lineage)

    created = _initialize(store)

    assert created.revision == 1
    assert created.state_bytes == b"state-0"
    assert created.checkpoint.session_id == membership.system_id
    assert created.lineage_manifest.generation == 1
    assert created.proof.proposal.result_state_digest == created.lineage_manifest.digest
    assert lineage.high_water() == (1, created.lineage_manifest.digest)
    restored = store.load_latest()
    assert restored.checkpoint == created.checkpoint
    assert restored.state_bytes == b"state-0"


def test_state_transition_advances_both_checkpoint_and_lineage_predecessors(tmp_path: Path) -> None:
    """A successor checkpoint binds its prior checkpoint digest and the previous quorum lineage root."""
    membership = _membership()
    lineage = RecoveryLineageCoordinator(membership, _authorities(tmp_path, membership))
    store = _store(tmp_path, lineage)
    first = _initialize(store)

    second = store.commit_state(
        b"state-1",
        expected_revision=first.revision,
        expected_checkpoint_digest=first.checkpoint_digest,
        transition_id="transition-1",
        operation_id="runtime.step",
        input_digest=_input_digest(b"advance by one"),
        logical_time=12,
    )

    assert second.revision == 2
    assert second.state_bytes == b"state-1"
    assert second.checkpoint.predecessor_checkpoint_digest == first.checkpoint_digest
    assert second.checkpoint.predecessor_lineage_digest == first.lineage_manifest.digest
    assert second.lineage_manifest.predecessor_digest == first.lineage_manifest.digest
    assert lineage.high_water() == (2, second.lineage_manifest.digest)


def test_stale_writer_cannot_overwrite_a_newer_session_revision(tmp_path: Path) -> None:
    """Two stores that read the same revision cannot both advance it with different states."""
    membership = _membership()
    lineage = RecoveryLineageCoordinator(membership, _authorities(tmp_path, membership))
    objects = _object_store()
    writer_a = _store(tmp_path / "shared", lineage, object_store=objects)
    writer_b = _store(tmp_path / "shared", lineage, object_store=objects)
    first = _initialize(writer_a)
    observed_by_b = writer_b.load_latest()

    committed = writer_a.commit_state(
        b"state-from-A",
        expected_revision=first.revision,
        expected_checkpoint_digest=first.checkpoint_digest,
        transition_id="writer-A",
        operation_id="runtime.step",
        input_digest=_input_digest(b"A"),
        logical_time=2,
    )
    with pytest.raises(ComputationalSessionConflictError, match="changed"):
        writer_b.commit_state(
            b"state-from-B",
            expected_revision=observed_by_b.revision,
            expected_checkpoint_digest=observed_by_b.checkpoint_digest,
            transition_id="writer-B",
            operation_id="runtime.step",
            input_digest=_input_digest(b"B"),
            logical_time=2,
        )

    assert writer_a.load_latest().checkpoint_digest == committed.checkpoint_digest
    assert writer_a.load_latest().state_bytes == b"state-from-A"


def test_exact_retry_returns_the_same_committed_revision_without_advancing(tmp_path: Path) -> None:
    """A response-lost retry with the same transition identity and state bytes is recognized as a replay."""
    membership = _membership()
    lineage = RecoveryLineageCoordinator(membership, _authorities(tmp_path, membership))
    store = _store(tmp_path, lineage)
    first = _initialize(store)
    kwargs = {
        "expected_revision": first.revision,
        "expected_checkpoint_digest": first.checkpoint_digest,
        "transition_id": "transition-idempotent",
        "operation_id": "runtime.step",
        "input_digest": _input_digest(b"same input"),
        "logical_time": 9,
    }
    committed = store.commit_state(b"same next state", **kwargs)
    replay = store.commit_state(b"same next state", **kwargs)

    assert replay.replayed is True
    assert replay.checkpoint_digest == committed.checkpoint_digest
    assert replay.revision == 2
    assert lineage.high_water() == (2, committed.lineage_manifest.digest)


def test_exact_retry_after_backend_profile_change_is_not_assumed(tmp_path: Path) -> None:
    """A transition executed by another backend profile requires a new domain decision, not an implicit replay."""
    membership = _membership()
    lineage = RecoveryLineageCoordinator(membership, _authorities(tmp_path, membership))
    backing = MemoryPageBacking()
    objects = _object_store(backing)
    source = _store(tmp_path / "host-A", lineage, object_store=objects, backend=BACKEND_A)
    first = _initialize(source)
    source.commit_state(
        b"committed-by-A",
        expected_revision=first.revision,
        expected_checkpoint_digest=first.checkpoint_digest,
        transition_id="transition-backend-A",
        operation_id="runtime.step",
        input_digest=_input_digest(b"same input"),
        logical_time=10,
    )
    target = _store(tmp_path / "host-B", lineage, object_store=objects, backend=BACKEND_B)
    compatibility = lambda source_fp, target_fp, schema: (
        source_fp == BACKEND_A and target_fp == BACKEND_B and schema == STATE_SCHEMA
    )
    with pytest.raises(ComputationalSessionConflictError):
        target.commit_state(
            b"committed-by-A",
            expected_revision=first.revision,
            expected_checkpoint_digest=first.checkpoint_digest,
            transition_id="transition-backend-A",
            operation_id="runtime.step",
            input_digest=_input_digest(b"same input"),
            logical_time=10,
            backend_compatibility=compatibility,
        )


def test_reusing_a_transition_identity_with_different_state_is_refused(tmp_path: Path) -> None:
    """A request id cannot silently identify two different successor state values."""
    membership = _membership()
    lineage = RecoveryLineageCoordinator(membership, _authorities(tmp_path, membership))
    store = _store(tmp_path, lineage)
    first = _initialize(store)
    kwargs = {
        "expected_revision": 1,
        "expected_checkpoint_digest": first.checkpoint_digest,
        "transition_id": "transition-same-id",
        "operation_id": "runtime.step",
        "input_digest": _input_digest(b"input"),
        "logical_time": 3,
    }
    store.commit_state(b"state-one", **kwargs)
    with pytest.raises(ComputationalSessionConflictError):
        store.commit_state(b"state-two", **kwargs)


def test_partial_quorum_commit_resumes_the_exact_prepared_checkpoint(tmp_path: Path) -> None:
    """A candidate fsynced before COMMIT quorum is recovered from the original proposal, not recomputed."""
    membership = _membership()
    failing_authorities = _authorities(tmp_path, membership, failing=True)
    failing_lineage = RecoveryLineageCoordinator(membership, failing_authorities)
    backing = MemoryPageBacking()
    objects = _object_store(backing)
    interrupted_store = _store(
        tmp_path / "session-data",
        failing_lineage,
        object_store=objects,
    )

    with pytest.raises(ComputationalSessionPendingError, match="not anchored"):
        interrupted_store.create_session(b"pending-state")
    assert RecoveryLineageCoordinator(
        membership,
        _authorities(tmp_path, membership),
    ).high_water() == (0, GENESIS)

    restored_lineage = RecoveryLineageCoordinator(membership, _authorities(tmp_path, membership))
    resumer = _store(tmp_path / "session-data", restored_lineage, object_store=objects)
    resumed = resumer.resume_pending()

    assert resumed.revision == 1
    assert resumed.state_bytes == b"pending-state"
    assert restored_lineage.high_water() == (1, resumed.lineage_manifest.digest)


def test_resume_pending_refuses_to_invent_a_transition_when_no_prepare_exists(tmp_path: Path) -> None:
    """No pending checkpoint can be resumed from a local file name or unanchored page alone."""
    membership = _membership()
    lineage = RecoveryLineageCoordinator(membership, _authorities(tmp_path, membership))
    store = _store(tmp_path, lineage)

    with pytest.raises(ComputationalSessionError, match="no prepared"):
        store.resume_pending()


def test_corrupted_checkpoint_envelope_is_rejected_before_state_restore(tmp_path: Path) -> None:
    """A local checkpoint descriptor altered after commit cannot pass its anchored manifest digest."""
    membership = _membership()
    lineage = RecoveryLineageCoordinator(membership, _authorities(tmp_path, membership))
    store = _store(tmp_path, lineage)
    created = _initialize(store)
    path = store._record_path(created.revision, created.lineage_manifest.digest)
    path.write_bytes(b'{"schema":"changed"}')

    reopened = _store(tmp_path, lineage)
    with pytest.raises(ComputationalSessionIntegrityError):
        reopened.load_latest()


def test_corrupted_m1_state_pages_are_rejected_before_continuation(tmp_path: Path) -> None:
    """State objects are read through M1 page digest and complete-content verification."""
    membership = _membership()
    lineage = RecoveryLineageCoordinator(membership, _authorities(tmp_path, membership))
    backing = MemoryPageBacking()
    objects = _object_store(backing)
    store = _store(tmp_path, lineage, object_store=objects)
    created = _initialize(store, b"state bytes that span more than one page " * 3)
    first_page = created.checkpoint.state_manifest.chunks[0]
    backing.pages[first_page.page_digest] = b"X" * backing.page_size

    with pytest.raises(ComputationalSessionIntegrityError, match="M1 integrity"):
        store.load_latest()


def test_exported_session_restores_on_another_host_with_explicit_backend_compatibility(tmp_path: Path) -> None:
    """A host migration reuses the same quorum lineage and M1 pages but requires explicit backend compatibility."""
    membership = _membership()
    lineage = RecoveryLineageCoordinator(membership, _authorities(tmp_path, membership))
    backing = MemoryPageBacking()
    objects = _object_store(backing)
    source = _store(tmp_path / "host-A", lineage, object_store=objects, backend=BACKEND_A)
    initial = _initialize(source)
    current = source.commit_state(
        b"portable-state",
        expected_revision=initial.revision,
        expected_checkpoint_digest=initial.checkpoint_digest,
        transition_id="portable-transition",
        operation_id="runtime.step",
        input_digest=_input_digest(b"portable input"),
        logical_time=44,
    )
    exported = source.export_latest()

    target = _store(tmp_path / "host-B", lineage, object_store=objects, backend=BACKEND_B)
    with pytest.raises(ComputationalSessionIntegrityError, match="compatibility"):
        target.restore_export(exported)

    compatibility = lambda source_fp, target_fp, schema: (
        source_fp == BACKEND_A and target_fp == BACKEND_B and schema == STATE_SCHEMA
    )
    restored = target.restore_export(exported, backend_compatibility=compatibility)
    assert restored.state_bytes == b"portable-state"
    assert restored.checkpoint_digest == current.checkpoint_digest

    migrated = target.commit_state(
        b"state-after-migration",
        expected_revision=restored.revision,
        expected_checkpoint_digest=restored.checkpoint_digest,
        transition_id="post-migration-transition",
        operation_id="runtime.step",
        input_digest=_input_digest(b"after migration"),
        logical_time=45,
        backend_compatibility=compatibility,
    )
    assert migrated.checkpoint.backend_fingerprint == BACKEND_B
    assert migrated.state_bytes == b"state-after-migration"


def test_exported_checkpoint_cannot_be_replayed_after_a_newer_revision_is_anchored(tmp_path: Path) -> None:
    """The quorum high-water rejects a previously valid export after a successor state is committed."""
    membership = _membership()
    lineage = RecoveryLineageCoordinator(membership, _authorities(tmp_path, membership))
    backing = MemoryPageBacking()
    objects = _object_store(backing)
    source = _store(tmp_path / "host-A", lineage, object_store=objects)
    first = _initialize(source)
    old_export = source.export_latest()
    source.commit_state(
        b"revision-two",
        expected_revision=first.revision,
        expected_checkpoint_digest=first.checkpoint_digest,
        transition_id="revision-two",
        operation_id="runtime.step",
        input_digest=_input_digest(b"two"),
        logical_time=2,
    )

    target = _store(tmp_path / "host-B", lineage, object_store=objects)
    with pytest.raises(ComputationalSessionIntegrityError, match="latest quorum"):
        target.restore_export(old_export)


def test_backend_and_state_schema_are_bound_to_the_session_checkpoint(tmp_path: Path) -> None:
    """Artifact, backend and state schema identity cannot silently drift during recovery."""
    membership = _membership()
    lineage = RecoveryLineageCoordinator(membership, _authorities(tmp_path, membership))
    source = _store(tmp_path, lineage, schema=STATE_SCHEMA)
    _initialize(source)

    wrong_artifact = _store(
        tmp_path,
        lineage,
        artifact=hashlib.sha256(b"another artifact").hexdigest(),
    )
    with pytest.raises(ComputationalSessionIntegrityError, match="artifact"):
        wrong_artifact.load_latest()

    wrong_schema = _store(tmp_path, lineage, schema="generic.state.v2")
    with pytest.raises(ComputationalSessionIntegrityError, match="schema"):
        wrong_schema.load_latest()


def test_session_memberships_isolate_revision_high_water_between_sessions(tmp_path: Path) -> None:
    """Independent session memberships allow one session to advance without moving another session's revision."""
    membership_a = _membership("session-A")
    membership_b = _membership("session-B")
    lineage_a = RecoveryLineageCoordinator(membership_a, _authorities(tmp_path / "A", membership_a))
    lineage_b = RecoveryLineageCoordinator(membership_b, _authorities(tmp_path / "B", membership_b))
    store_a = _store(tmp_path / "data", lineage_a)
    store_b = _store(tmp_path / "data", lineage_b)

    first_a = _initialize(store_a, b"A-0")
    first_b = _initialize(store_b, b"B-0")
    store_a.commit_state(
        b"A-1",
        expected_revision=first_a.revision,
        expected_checkpoint_digest=first_a.checkpoint_digest,
        transition_id="A-next",
        operation_id="runtime.step",
        input_digest=_input_digest(b"A"),
        logical_time=1,
    )

    assert store_a.load_latest().revision == 2
    assert store_b.load_latest().revision == 1
    assert store_b.load_latest().state_bytes == b"B-0"


def test_checkpoint_manifest_round_trip_preserves_exact_state_and_transition_identity(tmp_path: Path) -> None:
    """The portable checkpoint representation retains every coordinate needed to bind a later continuation."""
    membership = _membership()
    lineage = RecoveryLineageCoordinator(membership, _authorities(tmp_path, membership))
    store = _store(tmp_path, lineage)
    created = _initialize(store, b"typed-state")
    restored = type(created.checkpoint).from_dict(created.checkpoint.to_dict())

    assert restored == created.checkpoint
    assert restored.checkpoint_digest == created.checkpoint_digest
    assert restored.state_digest == hashlib.sha256(b"typed-state").hexdigest()


def test_restore_export_rejects_a_forged_quorum_proof(tmp_path: Path) -> None:
    """Changing the certified proposal in a portable export cannot pass local high-water verification."""
    membership = _membership()
    lineage = RecoveryLineageCoordinator(membership, _authorities(tmp_path, membership))
    backing = MemoryPageBacking()
    objects = _object_store(backing)
    source = _store(tmp_path / "host-A", lineage, object_store=objects)
    _initialize(source)
    exported = source.export_latest()
    exported["proof"]["proposal"]["request_fingerprint"] = "f" * 64

    target = _store(tmp_path / "host-B", lineage, object_store=objects)
    with pytest.raises((ComputationalSessionIntegrityError, ValueError)):
        target.restore_export(exported)
