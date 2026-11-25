"""Actual E-CPU M1/M3/M4 reduced-state continuation over independent receiver stores.

This file runs against the full E-CPU repository; tests never substitute a
custom checkpoint or quorum implementation for the production components.
"""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import shutil

import pytest

pytest.importorskip("vgi.guarded_reduction")
from vgi.guarded_reduction import (  # noqa: E402
    GuardedGround, GuardedAction, discover_guarded_reduction,
    plan_migration, admit_guarded_reduction,
)
from vgi.symbolic_reduction import AffineAction  # noqa: E402

from mailcpu.computational_objects import ComputationalObjectStore  # noqa: E402
from mailcpu.computational_session import (  # noqa: E402
    ComputationalSessionConflictError, ComputationalSessionIntegrityError,
    ComputationalSessionStore,
)
from mailcpu.recovery_lineage import (  # noqa: E402
    RecoveryLineageAuthority, RecoveryLineageCoordinator,
)
from mailcpu.seed_commit_quorum import SeedCommitMembership  # noqa: E402
from mailcpu.vgi_guarded_runtime import (  # noqa: E402
    admit_vgi_guarded_runtime, vgi_guarded_backend_profile,
)
from mailcpu.vgi_guarded_recovery import (  # noqa: E402
    STATE_SCHEMA, CheckpointSourceObservation, GuardedProgram,
    VGIDurableGroundSession, VGIRecoveryError,
)

GENESIS = sha256(b"e-cpu-vgi-guarded-reduced-recovery-genesis").hexdigest()
SESSION = "vgi-guarded-recovery-test"


class DurablePageBacking:
    """Independent file-backed M1 provider; fixed pages survive process restarts."""

    def __init__(self, root: Path, page_size: int = 256) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.page_size = page_size

    def put_page(self, page: bytes) -> str:
        if type(page) is not bytes or len(page) != self.page_size:
            raise ValueError("M1 page size differs")
        digest = sha256(page).hexdigest()
        target = self.root / digest
        if target.exists():
            if target.is_symlink() or target.read_bytes() != page:
                raise ValueError("M1 page identity collision")
        else:
            import os
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as stream:
                stream.write(page)
                stream.flush()
                os.fsync(stream.fileno())
        return digest

    def get_page(self, digest: str) -> bytes:
        if len(digest) != 64 or any(x not in "0123456789abcdef" for x in digest):
            raise ValueError("invalid page identity")
        path = self.root / digest
        if path.is_symlink():
            raise ValueError("M1 page symlink refused")
        data = path.read_bytes()
        if len(data) != self.page_size or sha256(data).hexdigest() != digest:
            raise ValueError("M1 page integrity mismatch")
        return data


def _identity(n: int) -> tuple[tuple[int, ...], ...]:
    return tuple(tuple(int(a == b) for b in range(n)) for a in range(n))


def fixture_program(n: int = 32) -> tuple[GuardedProgram, GuardedGround, GuardedGround]:
    guard = (0, 1) + (0,) * (n - 2)
    flip = (1,) + (0,) * (n - 1)
    act = GuardedAction("tick", guard, 1,
        AffineAction("tick", _identity(n), flip),
        AffineAction("tick", _identity(n), (0,) * n))
    first = (1,) + (0,) * (n - 1)
    more = (0, 0, 1) + (0,) * (n - 3)
    old = GuardedGround(2, n, (act,), (first,), (0,))
    new = GuardedGround(2, n, (act,), (first, more), (0, 0))
    program = GuardedProgram.admit(((old, discover_guarded_reduction(old)),
                                    (new, discover_guarded_reduction(new))))
    return program, old, new


def _lineage(root: Path):
    membership = SeedCommitMembership(SESSION, 1, ("A", "B", "C"), "A", 1, GENESIS)
    authorities = {id_: RecoveryLineageAuthority(membership, id_, root / f"authority-{id_}.jsonl")
                   for id_ in membership.member_ids}
    return RecoveryLineageCoordinator(membership, authorities)


def _store(root: Path, node: str, *, artifact: str, backend: str):
    pages = DurablePageBacking(root / f"pages-{node}")
    store = ComputationalSessionStore(
        root / f"checkpoint-{node}",
        ComputationalObjectStore(pages, chunk_size=256),
        _lineage(root / "quorum"),
        artifact_manifest_digest=artifact,
        backend_fingerprint=backend,
        state_schema_id=STATE_SCHEMA,
        state_media_type="application/vnd.mailcpu.guarded-session+json",
    )
    return store


def _runtime_metadata():
    manifest, root = admit_vgi_guarded_runtime()
    assert root.is_dir()
    profile = vgi_guarded_backend_profile(manifest)
    return manifest.manifest_digest, profile.fingerprint


def _put_transfer_pages(source: ComputationalSessionStore, target: ComputationalSessionStore):
    """Re-admit bytes in a separate M1 provider before an M3-backed import."""
    verified = source.load_latest()
    transferred_manifest = target.object_store.put_bytes(
        verified.state_bytes, media_type=target.state_media_type)
    assert transferred_manifest.manifest_digest == verified.checkpoint.state_manifest.manifest_digest


def _apply(session: VGIDurableGroundSession, first, inputs=("tick",) * 5, op="advance-1"):
    return session.advance(inputs, operation_id=op,
        expected_revision=first.revision, expected_checkpoint_digest=first.checkpoint_digest)


def test_m3_guarded_process_moves_across_receivers_and_restarts(tmp_path: Path):
    program, old, new = fixture_program(48)
    artifact, backend = _runtime_metadata()
    source_store = _store(tmp_path, "source", artifact=artifact, backend=backend)
    source = VGIDurableGroundSession(source_store, program)
    x = (0, 1, 1) + (0,) * 45
    initial = source.initialize(x)
    first = _apply(source, initial, inputs=("tick",) * 16)
    assert first.revision == 2 and first.checkpoint.predecessor_checkpoint_digest == initial.checkpoint_digest
    assert first.lineage_manifest.predecessor_digest == initial.lineage_manifest.digest
    assert source.inspect()["virtual_steps"] == "16"
    retry = _apply(source, initial, inputs=("tick",) * 16)
    assert retry.replayed and retry.checkpoint_digest == first.checkpoint_digest
    for _ in range(16):
        x = old.step(x, "tick")

    exported = source.export_latest()
    target_store = _store(tmp_path, "target", artifact=artifact, backend=backend)
    _put_transfer_pages(source_store, target_store)
    trusted = {}
    def observe(context):
        # Receiver-owned observation for the exact last committed source revision.
        return CheckpointSourceObservation(context.checkpoint_digest, trusted[context.checkpoint_digest])
    target = VGIDurableGroundSession(target_store, program, source_observer=observe)
    restored = target.restore_export(exported)
    assert restored.revision == 2 and restored.checkpoint_digest == first.checkpoint_digest
    trusted[restored.checkpoint_digest] = x
    migration = target.migrate(target=1, operation_id="migration-1",
        expected_revision=restored.revision, expected_checkpoint_digest=restored.checkpoint_digest)
    assert migration.revision == 3
    changed = target.inspect()
    assert changed["coordinates"] == list(program.stages[1].admitted.project(x))
    assert len(changed["last_event"]["probes"]) == 1
    assert changed["last_event"]["predecessor_checkpoint"] == first.checkpoint_digest
    for _ in range(7):
        x = new.step(x, "tick")
    advanced = _apply(target, migration, inputs=("tick",) * 7, op="advance-2")
    assert advanced.revision == 4
    assert target.inspect()["coordinates"] == list(program.stages[1].admitted.project(x))
    assert target.inspect()["virtual_steps"] == "23"

    # Independent owner process can reopen journals, M1 pages and M3 state.
    del target
    restarted = VGIDurableGroundSession(
        _store(tmp_path, "target", artifact=artifact, backend=backend), program)
    recovered = restarted.load()
    assert recovered.checkpoint_digest == advanced.checkpoint_digest
    assert restarted.inspect()["coordinates"] == list(program.stages[1].admitted.project(x))
    after = _apply(restarted, recovered, inputs=("tick",), op="advance-after-restart")
    assert after.revision == 5 and restarted.inspect()["virtual_steps"] == "24"
    with pytest.raises(ComputationalSessionIntegrityError):
        restarted.restore_export(exported)  # valid historically, now stale


def test_migration_refuses_stale_or_contradictory_source_observation(tmp_path: Path):
    program, old, _ = fixture_program(32)
    artifact, backend = _runtime_metadata()
    state = (0, 1, 1) + (0,) * 29
    store = _store(tmp_path, "node", artifact=artifact, backend=backend)
    refused = VGIDurableGroundSession(store, program,
        source_observer=lambda ctx: CheckpointSourceObservation("0" * 64, state))
    initial = refused.initialize(state)
    with pytest.raises(VGIRecoveryError, match="checkpoint"):
        refused.migrate(operation_id="stale-probe", target=1,
            expected_revision=initial.revision, expected_checkpoint_digest=initial.checkpoint_digest)
    assert refused.load().revision == 1
    # The checkpoint identity is valid but the source state contradicts the
    # committed reduced coordinates; the migration still fails closed.
    wrong = (1, 1, 1) + (0,) * 29
    contradicted = VGIDurableGroundSession(store, program,
        source_observer=lambda ctx: CheckpointSourceObservation(ctx.checkpoint_digest, wrong))
    with pytest.raises(VGIRecoveryError, match="committed reduced state"):
        contradicted.migrate(operation_id="wrong-probe", target=1,
            expected_revision=initial.revision, expected_checkpoint_digest=initial.checkpoint_digest)
    assert contradicted.load().revision == 1


def test_cas_stale_writer_and_operation_reuse_fail_closed(tmp_path: Path):
    program, _, _ = fixture_program(16)
    artifact, backend = _runtime_metadata()
    store = _store(tmp_path, "node", artifact=artifact, backend=backend)
    runtime = VGIDurableGroundSession(store, program)
    first = runtime.initialize((0, 1, 1) + (0,) * 13)
    second = _apply(runtime, first, op="step-1")
    with pytest.raises(ComputationalSessionConflictError):
        runtime.advance(("tick",), operation_id="step-2",
                        expected_revision=first.revision, expected_checkpoint_digest=first.checkpoint_digest)
    with pytest.raises(ComputationalSessionConflictError):
        runtime.advance(("tick",) * 6, operation_id="step-1",
                        expected_revision=first.revision, expected_checkpoint_digest=first.checkpoint_digest)
    assert runtime.load().checkpoint_digest == second.checkpoint_digest


def test_tampered_m1_pages_fail_before_state_can_be_resumed(tmp_path: Path):
    program, _, _ = fixture_program(16)
    artifact, backend = _runtime_metadata()
    store = _store(tmp_path, "node", artifact=artifact, backend=backend)
    runtime = VGIDurableGroundSession(store, program)
    first = runtime.initialize((0, 1, 1) + (0,) * 13)
    target = next((tmp_path / "pages-node").iterdir())
    raw = target.read_bytes()
    target.write_bytes(bytes([raw[0] ^ 1]) + raw[1:])
    with pytest.raises((ComputationalSessionIntegrityError, ValueError)):
        runtime.load()
