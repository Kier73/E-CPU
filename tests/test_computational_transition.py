from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from mailcpu.computational_objects import ComputationalObjectStore
from mailcpu.computational_session import (
    ComputationalSessionConflictError,
    ComputationalSessionStore,
)
from mailcpu.computational_transition import (
    ComputationalSessionTransitionAdapter,
    ComputationalTransitionContract,
    ComputationalTransitionContext,
    ComputationalTransitionError,
)
from mailcpu.recovery_lineage import RecoveryLineageAuthority, RecoveryLineageCoordinator
from mailcpu.seed_commit_quorum import SeedCommitMembership

GENESIS = hashlib.sha256(b"mailcpu-recovery-lineage-genesis-v1").hexdigest()
ARTIFACT = hashlib.sha256(b"transition-test-artifact").hexdigest()
BACKEND = hashlib.sha256(b"transition-test-backend").hexdigest()
INTERPRETATION = hashlib.sha256(b"declared-ground-and-transition").hexdigest()
STATE_SCHEMA = "decimal-integer.state.v1"


class MemoryPageBacking:
    """Fixed-size content-addressed page backing for transition-adapter tests."""

    def __init__(self, page_size: int = 32) -> None:
        """Create an in-memory immutable page table with one fixed page geometry."""
        self.page_size = page_size
        self.pages: dict[str, bytes] = {}

    def put_page(self, data: bytes) -> str:
        """Store an exact page under its SHA-256 identity."""
        digest = hashlib.sha256(data).hexdigest()
        self.pages.setdefault(digest, data)
        return digest

    def get_page(self, digest: str) -> bytes:
        """Resolve one previously admitted immutable page."""
        return self.pages[digest]


class DecimalAddBackend:
    """Pure reference backend that adds two bounded decimal-integer byte strings."""

    backend_fingerprint = BACKEND

    def __init__(self) -> None:
        """Initialize an invocation log used to prove retries do not re-enter the backend."""
        self.contexts: list[ComputationalTransitionContext] = []

    def transition(
        self,
        state_bytes: bytes,
        input_bytes: bytes,
        context: ComputationalTransitionContext,
    ) -> bytes:
        """Decode the explicitly declared test schema, add one input, and return the next state bytes."""
        self.contexts.append(context)
        return str(int(state_bytes.decode("ascii")) + int(input_bytes.decode("ascii"))).encode("ascii")


def _store(tmp_path: Path) -> ComputationalSessionStore:
    """Create an M3 session store with three local quorum authorities and M1 page backing."""
    membership = SeedCommitMembership(
        "transition-session",
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
            tmp_path / "authorities" / f"{member}.jsonl",
        )
        for member in membership.member_ids
    }
    lineage = RecoveryLineageCoordinator(membership, authorities)
    objects = ComputationalObjectStore(MemoryPageBacking(), chunk_size=32)
    return ComputationalSessionStore(
        tmp_path / "session",
        objects,
        lineage,
        artifact_manifest_digest=ARTIFACT,
        backend_fingerprint=BACKEND,
        state_schema_id=STATE_SCHEMA,
    )


def _contract(**changes: object) -> ComputationalTransitionContract:
    """Build a bounded deterministic contract for the declared decimal-integer state test domain."""
    payload: dict[str, object] = {
        "transition_id": "decimal.add",
        "state_schema_id": STATE_SCHEMA,
        "input_schema_id": "decimal-integer.input.v1",
        "interpretation_fingerprint": INTERPRETATION,
        "backend_fingerprint": BACKEND,
        "max_input_bytes": 16,
        "max_state_bytes": 32,
    }
    payload.update(changes)
    return ComputationalTransitionContract(**payload)


def _adapter(tmp_path: Path) -> tuple[ComputationalSessionStore, DecimalAddBackend, ComputationalSessionTransitionAdapter]:
    """Create and initialize one pure session transition path."""
    store = _store(tmp_path)
    store.create_session(b"10", logical_time=0)
    backend = DecimalAddBackend()
    return store, backend, ComputationalSessionTransitionAdapter(store, _contract(), backend)


def test_transition_adapter_binds_verified_snapshot_and_commits_successor(tmp_path: Path) -> None:
    """The backend sees the exact M1/quorum session coordinate and publishes through M3 CAS."""
    store, backend, adapter = _adapter(tmp_path)
    initial = store.load_latest()

    result = adapter.apply(b"5", operation_id="add-five")

    assert result.revision == 2
    assert result.state_bytes == b"15"
    assert result.checkpoint.logical_time == initial.checkpoint.logical_time + 1
    assert len(result.checkpoint.input_digest) == 64
    assert len(backend.contexts) == 1
    context = backend.contexts[0]
    assert context.session_id == initial.checkpoint.session_id
    assert context.revision == initial.revision
    assert context.checkpoint_digest == initial.checkpoint_digest
    assert context.lineage_digest == initial.lineage_manifest.digest
    assert context.state_digest == initial.checkpoint.state_digest
    assert context.interpretation_fingerprint == INTERPRETATION
    assert context.binding_digest == hashlib.sha256(
        json.dumps(
            context.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode("utf-8")
    ).hexdigest()


def test_transition_adapter_exact_retry_does_not_reenter_backend(tmp_path: Path) -> None:
    """A response-lost immediate retry returns the committed revision without interpreting again."""
    _, backend, adapter = _adapter(tmp_path)

    committed = adapter.apply(b"5", operation_id="same-operation")
    replay = adapter.apply(b"5", operation_id="same-operation")

    assert replay.replayed is True
    assert replay.revision == committed.revision == 2
    assert replay.checkpoint_digest == committed.checkpoint_digest
    assert len(backend.contexts) == 1


def test_transition_adapter_refuses_reused_operation_with_changed_input(tmp_path: Path) -> None:
    """An operation identity cannot be rebound to another input after its result is committed."""
    _, backend, adapter = _adapter(tmp_path)
    adapter.apply(b"5", operation_id="same-operation")

    with pytest.raises(ComputationalSessionConflictError, match="reused"):
        adapter.apply(b"6", operation_id="same-operation")

    assert len(backend.contexts) == 1


def test_transition_adapter_rejects_unverified_or_effectful_backend_profiles(tmp_path: Path) -> None:
    """The session adapter requires exact backend identity and a declared deterministic pure transition."""
    store = _store(tmp_path)
    store.create_session(b"10")
    backend = DecimalAddBackend()
    with pytest.raises(ComputationalTransitionError, match="pure"):
        ComputationalSessionTransitionAdapter(
            store,
            _contract(effect_mode="transactional"),
            backend,
        )
    with pytest.raises(ComputationalTransitionError, match="backend fingerprint"):
        ComputationalSessionTransitionAdapter(
            store,
            _contract(backend_fingerprint=hashlib.sha256(b"other-backend").hexdigest()),
            backend,
        )


def test_transition_adapter_refuses_skipped_logical_time_and_stale_base_before_execution(tmp_path: Path) -> None:
    """A rejected temporal coordinate or compare-and-swap base cannot enter the backend."""
    store, backend, adapter = _adapter(tmp_path)
    current = store.load_latest()

    with pytest.raises(ComputationalSessionConflictError, match="logical_time"):
        adapter.apply(b"5", operation_id="skip-time", logical_time=3)
    with pytest.raises(ComputationalSessionConflictError, match="expected transition base"):
        adapter.apply(
            b"5",
            operation_id="stale-base",
            expected_revision=current.revision + 1,
            expected_checkpoint_digest="0" * 64,
        )
    assert backend.contexts == []
