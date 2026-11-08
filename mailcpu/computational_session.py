"""Mathematics: Persistent, versioned computational session state over M1 and quorum recovery lineage.

This module owns immutable state snapshots and atomic continuation, while the
existing ComputationalObjectStore owns their byte pages and the existing
RecoveryLineageCoordinator owns the durable quorum high-water mark.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from .computational_objects import ComputationalObjectManifest, ComputationalObjectStore
from .recovery_lineage import (
    RecoveryLineageCoordinator,
    RecoveryLineageError,
    RecoveryLineageProof,
    RecoveryStateManifest,
)

_SESSION_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_LABEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,255}\Z")
_HEX_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_MEDIA_TYPE = re.compile(r"[A-Za-z0-9!#$&^_.+-]+/[A-Za-z0-9!#$&^_.+-]+\Z")
_CHECKPOINT_KIND = "mailcpu.computational-session-checkpoint"
_CHECKPOINT_SCHEMA_VERSION = 1
_RECORD_SCHEMA = "mailcpu.computational-session-anchor.v1"
_EXPORT_SCHEMA = "mailcpu.computational-session-export.v1"
_GENESIS_TRANSITION_ID = "session.initialize"
_GENESIS_OPERATION_ID = "session.initialize"
_GENESIS_INPUT_DIGEST = hashlib.sha256(b"").hexdigest()


class ComputationalSessionError(ValueError):
    """Mathematics: Base error for session identity, state checkpoints, and continuation failures."""


class ComputationalSessionIntegrityError(ComputationalSessionError):
    """Mathematics: Persisted session bytes, manifests, or quorum evidence do not match their declared identities."""


class ComputationalSessionConflictError(ComputationalSessionError):
    """Mathematics: A state transition was based on a stale revision or conflicting checkpoint identity."""


class ComputationalSessionPendingError(ComputationalSessionError):
    """Mathematics: An earlier unanchored transition occupies the next quorum lineage slot and must be resumed first."""


def _canonical_bytes(value: Any, label: str) -> bytes:
    """Mathematics: Encode finite JSON as sorted, compact, deterministic UTF-8 bytes."""
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ComputationalSessionError(f"{label} is outside canonical JSON") from exc


def _sha256(data: bytes) -> str:
    """Mathematics: Return the SHA-256 content identity of one exact byte sequence."""
    return hashlib.sha256(data).hexdigest()


def _require_digest(value: Any, name: str) -> str:
    """Mathematics: Require an exact lowercase 64-character SHA-256 digest."""
    if not isinstance(value, str) or _HEX_DIGEST.fullmatch(value) is None:
        raise ComputationalSessionError(f"{name} must be a lowercase SHA-256 digest")
    return value


def _require_label(value: Any, name: str) -> str:
    """Mathematics: Require one bounded, stable operation or schema identifier."""
    if not isinstance(value, str) or _LABEL.fullmatch(value) is None:
        raise ComputationalSessionError(f"{name} must be a non-empty bounded identifier")
    return value


def _require_positive_integer(value: Any, name: str) -> int:
    """Mathematics: Require a positive built-in integer without accepting Boolean values."""
    if type(value) is not int or value <= 0:
        raise ComputationalSessionError(f"{name} must be a positive integer")
    return value


def _require_nonnegative_integer(value: Any, name: str) -> int:
    """Mathematics: Require a non-negative built-in integer without accepting Boolean values."""
    if type(value) is not int or value < 0:
        raise ComputationalSessionError(f"{name} must be a non-negative integer")
    return value


@dataclass(frozen=True)
class ComputationalSessionCheckpoint:
    """Mathematics: Immutable revision descriptor binding one session state object to its artifact, backend, and predecessor."""

    session_id: str
    artifact_manifest_digest: str
    backend_fingerprint: str
    state_schema_id: str
    revision: int
    predecessor_checkpoint_digest: str
    state_manifest: ComputationalObjectManifest
    transition_id: str
    operation_id: str
    input_digest: str
    logical_time: int
    schema_version: int = _CHECKPOINT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        """Mathematics: Validate session scope, monotonic revision, immutable state-object identity, and transition coordinates."""
        if not isinstance(self.session_id, str) or _SESSION_ID.fullmatch(self.session_id) is None:
            raise ComputationalSessionError("session_id must be a bounded path-safe identifier")
        _require_digest(self.artifact_manifest_digest, "artifact_manifest_digest")
        _require_digest(self.backend_fingerprint, "backend_fingerprint")
        _require_label(self.state_schema_id, "state_schema_id")
        _require_positive_integer(self.revision, "revision")
        _require_digest(self.predecessor_checkpoint_digest, "predecessor_checkpoint_digest")
        if not isinstance(self.state_manifest, ComputationalObjectManifest):
            raise TypeError("state_manifest must be a ComputationalObjectManifest")
        _require_label(self.transition_id, "transition_id")
        _require_label(self.operation_id, "operation_id")
        _require_digest(self.input_digest, "input_digest")
        _require_nonnegative_integer(self.logical_time, "logical_time")
        if type(self.schema_version) is not int or self.schema_version != _CHECKPOINT_SCHEMA_VERSION:
            raise ComputationalSessionError("unsupported computational session checkpoint schema")

    def _payload_dict(self) -> dict[str, object]:
        """Mathematics: Project all immutable session revision fields except the self-referential checkpoint digest."""
        return {
            "kind": _CHECKPOINT_KIND,
            "schema_version": self.schema_version,
            "session_id": self.session_id,
            "artifact_manifest_digest": self.artifact_manifest_digest,
            "backend_fingerprint": self.backend_fingerprint,
            "state_schema_id": self.state_schema_id,
            "revision": self.revision,
            "predecessor_checkpoint_digest": self.predecessor_checkpoint_digest,
            "state_manifest": self.state_manifest.to_dict(),
            "transition_id": self.transition_id,
            "operation_id": self.operation_id,
            "input_digest": self.input_digest,
            "logical_time": self.logical_time,
        }

    @property
    def checkpoint_digest(self) -> str:
        """Mathematics: Hash the canonical checkpoint descriptor to create its immutable revision identity."""
        return _sha256(_canonical_bytes(self._payload_dict(), "computational session checkpoint"))

    @property
    def state_digest(self) -> str:
        """Mathematics: Return the logical state-byte digest independently from the M1 storage-manifest digest."""
        return self.state_manifest.content_digest

    def to_dict(self) -> dict[str, object]:
        """Mathematics: Project the checkpoint into its portable form with the verified checkpoint digest."""
        return self._payload_dict() | {"checkpoint_digest": self.checkpoint_digest}

    def canonical_bytes(self) -> bytes:
        """Mathematics: Return the exact canonical bytes that are anchored by RecoveryStateManifest."""
        return _canonical_bytes(self.to_dict(), "computational session checkpoint")

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> ComputationalSessionCheckpoint:
        """Mathematics: Decode the exact checkpoint schema and independently verify its canonical digest."""
        expected = {
            "kind",
            "schema_version",
            "session_id",
            "artifact_manifest_digest",
            "backend_fingerprint",
            "state_schema_id",
            "revision",
            "predecessor_checkpoint_digest",
            "state_manifest",
            "transition_id",
            "operation_id",
            "input_digest",
            "logical_time",
            "checkpoint_digest",
        }
        if not isinstance(payload, Mapping) or set(payload) != expected:
            raise ComputationalSessionIntegrityError("computational session checkpoint fields are invalid")
        if payload["kind"] != _CHECKPOINT_KIND:
            raise ComputationalSessionIntegrityError("unsupported computational session checkpoint kind")
        if type(payload["schema_version"]) is not int or payload["schema_version"] != _CHECKPOINT_SCHEMA_VERSION:
            raise ComputationalSessionIntegrityError("unsupported computational session checkpoint schema")
        try:
            checkpoint = cls(
                session_id=payload["session_id"],
                artifact_manifest_digest=payload["artifact_manifest_digest"],
                backend_fingerprint=payload["backend_fingerprint"],
                state_schema_id=payload["state_schema_id"],
                revision=payload["revision"],
                predecessor_checkpoint_digest=payload["predecessor_checkpoint_digest"],
                state_manifest=ComputationalObjectManifest.from_dict(payload["state_manifest"]),
                transition_id=payload["transition_id"],
                operation_id=payload["operation_id"],
                input_digest=payload["input_digest"],
                logical_time=payload["logical_time"],
                schema_version=payload["schema_version"],
            )
        except (KeyError, TypeError, ValueError) as exc:
            if isinstance(exc, ComputationalSessionError):
                raise
            raise ComputationalSessionIntegrityError("computational session checkpoint is malformed") from exc
        _require_digest(payload["checkpoint_digest"], "checkpoint_digest")
        if payload["checkpoint_digest"] != checkpoint.checkpoint_digest:
            raise ComputationalSessionIntegrityError("computational session checkpoint digest mismatch")
        return checkpoint


@dataclass(frozen=True)
class ComputationalSessionSnapshot:
    """Mathematics: A verified session revision combining immutable checkpoint metadata, resolved state bytes, and quorum proof."""

    checkpoint: ComputationalSessionCheckpoint
    state_bytes: bytes
    lineage_manifest: RecoveryStateManifest
    proof: RecoveryLineageProof
    replayed: bool = False

    def __post_init__(self) -> None:
        """Mathematics: Require state bytes and quorum evidence to match the checkpoint revision exactly."""
        if not isinstance(self.checkpoint, ComputationalSessionCheckpoint):
            raise TypeError("checkpoint must be a ComputationalSessionCheckpoint")
        if not isinstance(self.state_bytes, bytes):
            raise TypeError("state_bytes must be bytes")
        if not isinstance(self.lineage_manifest, RecoveryStateManifest):
            raise TypeError("lineage_manifest must be a RecoveryStateManifest")
        if not isinstance(self.proof, RecoveryLineageProof):
            raise TypeError("proof must be a RecoveryLineageProof")
        if not isinstance(self.replayed, bool):
            raise TypeError("replayed must be Boolean")
        if (
            self.lineage_manifest.generation != self.checkpoint.revision
            or self.lineage_manifest.machine_id != self.checkpoint.session_id
            or self.lineage_manifest.state_digest != _sha256(self.checkpoint.canonical_bytes())
            or self.proof.proposal.result_state_digest != self.lineage_manifest.digest
        ):
            raise ComputationalSessionIntegrityError("session snapshot checkpoint and lineage coordinates differ")
        if _sha256(self.state_bytes) != self.checkpoint.state_digest:
            raise ComputationalSessionIntegrityError("session snapshot state bytes do not match the checkpoint")

    @property
    def revision(self) -> int:
        """Mathematics: Expose the strictly positive committed session revision."""
        return self.checkpoint.revision

    @property
    def checkpoint_digest(self) -> str:
        """Mathematics: Expose the immutable checkpoint identity used as the next compare-and-swap base."""
        return self.checkpoint.checkpoint_digest

    def export_dict(self) -> dict[str, object]:
        """Mathematics: Export portable checkpoint and quorum evidence without embedding the M1 state payload bytes."""
        return {
            "schema": _EXPORT_SCHEMA,
            "checkpoint": self.checkpoint.to_dict(),
            "lineage_manifest": self.lineage_manifest.snapshot(),
            "proof": self.proof.snapshot(),
        }


BackendCompatibility = Callable[[str, str, str], bool]


class ComputationalSessionStore:
    """Mathematics: One session-scoped CAS state machine using M1 immutable pages and existing quorum recovery lineage."""

    def __init__(
        self,
        root: str | os.PathLike[str],
        object_store: ComputationalObjectStore,
        lineage: RecoveryLineageCoordinator,
        *,
        artifact_manifest_digest: str,
        backend_fingerprint: str,
        state_schema_id: str,
        state_media_type: str = "application/octet-stream",
    ) -> None:
        """Mathematics: Bind one session identity to its artifact, target backend, M1 page store, and independent lineage."""
        if not isinstance(object_store, ComputationalObjectStore):
            raise TypeError("object_store must be a ComputationalObjectStore")
        if not isinstance(lineage, RecoveryLineageCoordinator):
            raise TypeError("lineage must be a RecoveryLineageCoordinator")
        _require_digest(artifact_manifest_digest, "artifact_manifest_digest")
        _require_digest(backend_fingerprint, "backend_fingerprint")
        _require_label(state_schema_id, "state_schema_id")
        if not isinstance(state_media_type, str) or _MEDIA_TYPE.fullmatch(state_media_type) is None:
            raise ComputationalSessionError("state_media_type must be a MIME type/subtype value")

        membership = lineage.membership
        if not isinstance(membership.system_id, str) or _SESSION_ID.fullmatch(membership.system_id) is None:
            raise ComputationalSessionError(
                "the fixed recovery membership system_id must equal a bounded path-safe session_id"
            )

        selected_root = Path(root)
        if selected_root.is_symlink():
            raise ComputationalSessionError("session storage root cannot be a symlink")
        selected_root.mkdir(parents=True, exist_ok=True)
        resolved_root = selected_root.resolve()
        session_dir = resolved_root / membership.system_id
        if session_dir.is_symlink():
            raise ComputationalSessionError("session directory cannot be a symlink")
        session_dir.mkdir(parents=True, exist_ok=True)
        if not session_dir.resolve().is_relative_to(resolved_root):
            raise ComputationalSessionError("session directory escapes its configured root")

        self.root = resolved_root
        self.session_id = membership.system_id
        self.object_store = object_store
        self.lineage = lineage
        self.membership = membership
        self.artifact_manifest_digest = artifact_manifest_digest
        self.backend_fingerprint = backend_fingerprint
        self.state_schema_id = state_schema_id
        self.state_media_type = state_media_type
        self._session_dir = session_dir
        self._lock = threading.RLock()

    def create_session(
        self,
        initial_state: bytes,
        *,
        transition_id: str = _GENESIS_TRANSITION_ID,
        operation_id: str = _GENESIS_OPERATION_ID,
        input_digest: str = _GENESIS_INPUT_DIGEST,
        logical_time: int = 0,
    ) -> ComputationalSessionSnapshot:
        """Mathematics: Publish revision one by persisting its M1 state object before quorum-anchoring its recovery root."""
        if not isinstance(initial_state, bytes):
            raise TypeError("initial_state must be bytes")
        with self._lock:
            generation, predecessor = self.lineage.high_water()
            if generation != 0 or predecessor != self.membership.genesis_state_digest:
                try:
                    current = self.load_latest()
                except ComputationalSessionError as exc:
                    raise ComputationalSessionConflictError(
                        "session lineage is already occupied and its latest checkpoint cannot be admitted"
                    ) from exc
                if (
                    current.revision == 1
                    and current.checkpoint.transition_id == transition_id
                    and current.checkpoint.operation_id == operation_id
                    and current.checkpoint.input_digest == input_digest
                    and current.state_bytes == initial_state
                    and current.checkpoint.logical_time == logical_time
                ):
                    return self._with_replayed(current)
                raise ComputationalSessionConflictError("computational session is already initialized")
            pending = self._pending_proposal(1)
            if pending is not None:
                raise ComputationalSessionPendingError(
                    "an unanchored initial checkpoint already occupies revision one; call resume_pending()"
                )
            state_manifest = self.object_store.put_bytes(initial_state, media_type=self.state_media_type)
            if not self.object_store.verify(state_manifest):
                raise ComputationalSessionIntegrityError("initial state object did not verify after M1 admission")
            checkpoint = ComputationalSessionCheckpoint(
                session_id=self.session_id,
                artifact_manifest_digest=self.artifact_manifest_digest,
                backend_fingerprint=self.backend_fingerprint,
                state_schema_id=self.state_schema_id,
                revision=1,
                predecessor_checkpoint_digest=self.membership.genesis_state_digest,
                state_manifest=state_manifest,
                transition_id=transition_id,
                operation_id=operation_id,
                input_digest=input_digest,
                logical_time=logical_time,
            )
            recovery_manifest = self._recovery_manifest(
                checkpoint,
                predecessor_digest=self.membership.genesis_state_digest,
            )
            return self._seal_checkpoint(checkpoint, recovery_manifest)

    def commit_state(
        self,
        next_state: bytes,
        *,
        expected_revision: int,
        expected_checkpoint_digest: str,
        transition_id: str,
        operation_id: str,
        input_digest: str,
        logical_time: int,
        backend_compatibility: BackendCompatibility | None = None,
    ) -> ComputationalSessionSnapshot:
        """Mathematics: Compare the exact current revision before anchoring one successor state and refusing competing writers."""
        if not isinstance(next_state, bytes):
            raise TypeError("next_state must be bytes")
        _require_positive_integer(expected_revision, "expected_revision")
        _require_digest(expected_checkpoint_digest, "expected_checkpoint_digest")
        _require_label(transition_id, "transition_id")
        _require_label(operation_id, "operation_id")
        _require_digest(input_digest, "input_digest")
        _require_nonnegative_integer(logical_time, "logical_time")

        with self._lock:
            current = self.load_latest(backend_compatibility=backend_compatibility)
            if (
                current.revision != expected_revision
                or current.checkpoint_digest != expected_checkpoint_digest
            ):
                if self._is_exact_retry(
                    current,
                    expected_revision=expected_revision,
                    expected_checkpoint_digest=expected_checkpoint_digest,
                    next_state=next_state,
                    transition_id=transition_id,
                    operation_id=operation_id,
                    input_digest=input_digest,
                    logical_time=logical_time,
                ):
                    return self._with_replayed(current)
                raise ComputationalSessionConflictError(
                    "session state changed after the caller observed its expected revision"
                )

            next_generation = expected_revision + 1
            pending = self._pending_proposal(next_generation)
            if pending is not None:
                raise ComputationalSessionPendingError(
                    "an unanchored successor already occupies the next revision; call resume_pending()"
                )

            state_manifest = self.object_store.put_bytes(next_state, media_type=self.state_media_type)
            if not self.object_store.verify(state_manifest):
                raise ComputationalSessionIntegrityError("successor state object did not verify after M1 admission")
            checkpoint = ComputationalSessionCheckpoint(
                session_id=self.session_id,
                artifact_manifest_digest=self.artifact_manifest_digest,
                backend_fingerprint=self.backend_fingerprint,
                state_schema_id=self.state_schema_id,
                revision=next_generation,
                predecessor_checkpoint_digest=current.checkpoint_digest,
                state_manifest=state_manifest,
                transition_id=transition_id,
                operation_id=operation_id,
                input_digest=input_digest,
                logical_time=logical_time,
            )
            recovery_manifest = self._recovery_manifest(
                checkpoint,
                predecessor_digest=current.lineage_manifest.digest,
            )
            return self._seal_checkpoint(checkpoint, recovery_manifest)

    def load_latest(
        self,
        *,
        backend_compatibility: BackendCompatibility | None = None,
    ) -> ComputationalSessionSnapshot:
        """Mathematics: Admit only the checkpoint whose recovery-state manifest equals the quorum-supported latest root."""
        with self._lock:
            try:
                proof = self.lineage.latest_proof()
                generation, root_digest = self.lineage.high_water()
            except RecoveryLineageError as exc:
                raise ComputationalSessionIntegrityError(f"cannot read the session recovery high-water: {exc}") from exc
            if proof is None or generation <= 0:
                raise ComputationalSessionError("computational session has no quorum-anchored checkpoint")
            record_path = self._record_path(generation, root_digest)
            record = self._read_record(record_path)
            checkpoint, recovery_manifest = self._decode_record(record)
            if recovery_manifest.digest != root_digest or recovery_manifest.generation != generation:
                raise ComputationalSessionIntegrityError("local checkpoint record does not match the quorum high-water")
            self._validate_checkpoint_scope(checkpoint, backend_compatibility)
            recovery_manifest.verify_payload(checkpoint.canonical_bytes())
            if (
                recovery_manifest.machine_id != self.session_id
                or recovery_manifest.incarnation != self.membership.incarnation
                or recovery_manifest.owner_id != self.membership.owner_id
                or recovery_manifest.owner_term != self.membership.owner_term
                or recovery_manifest.membership_digest != self.membership.digest
                or checkpoint.revision != recovery_manifest.generation
            ):
                raise ComputationalSessionIntegrityError("checkpoint and fixed recovery membership coordinates differ")
            try:
                verified_proof = self.lineage.verify_state(recovery_manifest)
            except RecoveryLineageError as exc:
                raise ComputationalSessionIntegrityError(f"checkpoint is not the latest quorum-anchored state: {exc}") from exc
            if verified_proof.proposal.digest != proof.proposal.digest:
                raise ComputationalSessionIntegrityError("quorum high-water proof changed during checkpoint admission")
            try:
                self.object_store.verify(checkpoint.state_manifest)
                state_bytes = self.object_store.read_bytes(checkpoint.state_manifest)
            except Exception as exc:
                raise ComputationalSessionIntegrityError("session state object failed M1 integrity verification") from exc
            return ComputationalSessionSnapshot(
                checkpoint=checkpoint,
                state_bytes=state_bytes,
                lineage_manifest=recovery_manifest,
                proof=verified_proof,
            )

    def resume_pending(
        self,
        *,
        backend_compatibility: BackendCompatibility | None = None,
    ) -> ComputationalSessionSnapshot:
        """Mathematics: Resume the exact next-revision proposal already fsynced by an authority after a partial seal or owner crash."""
        with self._lock:
            try:
                generation, predecessor = self.lineage.high_water()
            except RecoveryLineageError as exc:
                raise ComputationalSessionIntegrityError(f"cannot read the session recovery high-water: {exc}") from exc
            next_generation = generation + 1
            proposal = self._pending_proposal(next_generation)
            if proposal is None:
                raise ComputationalSessionError("no prepared session checkpoint is pending")
            if proposal.predecessor_digest != predecessor:
                raise ComputationalSessionIntegrityError("pending checkpoint does not extend the current quorum high-water")
            path = self._record_path(next_generation, proposal.result_state_digest)
            record = self._read_record(path)
            checkpoint, recovery_manifest = self._decode_record(record)
            if (
                recovery_manifest.digest != proposal.result_state_digest
                or recovery_manifest.generation != next_generation
                or checkpoint.revision != next_generation
                or self.lineage.proposal_for(recovery_manifest).digest != proposal.digest
            ):
                raise ComputationalSessionIntegrityError("pending checkpoint does not match its prepared quorum proposal")
            self._validate_checkpoint_scope(checkpoint, backend_compatibility)
            recovery_manifest.verify_payload(checkpoint.canonical_bytes())
            try:
                self.object_store.verify(checkpoint.state_manifest)
            except Exception as exc:
                raise ComputationalSessionIntegrityError("pending state object failed M1 integrity verification") from exc
            self.lineage.seal(recovery_manifest)
            return self.load_latest(backend_compatibility=backend_compatibility)

    def export_latest(
        self,
        *,
        backend_compatibility: BackendCompatibility | None = None,
    ) -> dict[str, object]:
        """Mathematics: Export portable checkpoint and quorum proof while keeping bulk state bytes in the M1 page plane."""
        return self.load_latest(backend_compatibility=backend_compatibility).export_dict()

    def restore_export(
        self,
        payload: Mapping[str, Any],
        *,
        backend_compatibility: BackendCompatibility | None = None,
    ) -> ComputationalSessionSnapshot:
        """Mathematics: Reattach an exported session checkpoint only after matching local quorum high-water and M1 page verification."""
        expected = {"schema", "checkpoint", "lineage_manifest", "proof"}
        if not isinstance(payload, Mapping) or set(payload) != expected or payload.get("schema") != _EXPORT_SCHEMA:
            raise ComputationalSessionIntegrityError("computational session export fields or schema are invalid")
        try:
            checkpoint = ComputationalSessionCheckpoint.from_dict(payload["checkpoint"])
            recovery_manifest = RecoveryStateManifest.from_snapshot(payload["lineage_manifest"])
            exported_proof = RecoveryLineageProof.from_snapshot(payload["proof"])
        except (TypeError, ValueError, KeyError) as exc:
            if isinstance(exc, ComputationalSessionError):
                raise
            raise ComputationalSessionIntegrityError("computational session export is malformed") from exc
        with self._lock:
            self._validate_checkpoint_scope(checkpoint, backend_compatibility)
            if (
                recovery_manifest.generation != checkpoint.revision
                or recovery_manifest.machine_id != checkpoint.session_id
                or recovery_manifest.state_digest != _sha256(checkpoint.canonical_bytes())
            ):
                raise ComputationalSessionIntegrityError("exported checkpoint and recovery manifest disagree")
            recovery_manifest.verify_payload(checkpoint.canonical_bytes())
            try:
                verified_proof = self.lineage.verify_state(recovery_manifest)
            except RecoveryLineageError as exc:
                raise ComputationalSessionIntegrityError(f"exported checkpoint is not the current quorum state: {exc}") from exc
            if (
                exported_proof.proposal.digest != verified_proof.proposal.digest
                or exported_proof.certificate.snapshot() != verified_proof.certificate.snapshot()
            ):
                raise ComputationalSessionIntegrityError("exported quorum proof differs from the locally verified proof")
            try:
                self.object_store.verify(checkpoint.state_manifest)
                state_bytes = self.object_store.read_bytes(checkpoint.state_manifest)
            except Exception as exc:
                raise ComputationalSessionIntegrityError("exported session state pages are unavailable or corrupt") from exc
            self._persist_record(checkpoint, recovery_manifest)
            return ComputationalSessionSnapshot(
                checkpoint=checkpoint,
                state_bytes=state_bytes,
                lineage_manifest=recovery_manifest,
                proof=verified_proof,
            )

    def _seal_checkpoint(
        self,
        checkpoint: ComputationalSessionCheckpoint,
        recovery_manifest: RecoveryStateManifest,
    ) -> ComputationalSessionSnapshot:
        """Mathematics: Persist an immutable candidate before invoking the existing quorum prepare/certificate/commit protocol."""
        self._persist_record(checkpoint, recovery_manifest)
        try:
            proof = self.lineage.seal(recovery_manifest)
            verified = self.lineage.verify_state(recovery_manifest)
        except RecoveryLineageError as exc:
            raise ComputationalSessionPendingError(
                f"checkpoint bytes are durable but the recovery quorum has not anchored them: {exc}"
            ) from exc
        if proof.proposal.digest != verified.proposal.digest:
            raise ComputationalSessionIntegrityError("sealed checkpoint differs from the verified quorum high-water")
        state_bytes = self.object_store.read_bytes(checkpoint.state_manifest)
        return ComputationalSessionSnapshot(
            checkpoint=checkpoint,
            state_bytes=state_bytes,
            lineage_manifest=recovery_manifest,
            proof=verified,
        )

    def _recovery_manifest(
        self,
        checkpoint: ComputationalSessionCheckpoint,
        *,
        predecessor_digest: str,
    ) -> RecoveryStateManifest:
        """Mathematics: Bind the canonical checkpoint bytes into the existing single-state recovery manifest."""
        return RecoveryStateManifest(
            machine_id=self.session_id,
            incarnation=self.membership.incarnation,
            owner_id=self.membership.owner_id,
            owner_term=self.membership.owner_term,
            membership_digest=self.membership.digest,
            generation=checkpoint.revision,
            predecessor_digest=predecessor_digest,
            state_digest=_sha256(checkpoint.canonical_bytes()),
            capture_cut="computational-session-state",
        )

    def _validate_checkpoint_scope(
        self,
        checkpoint: ComputationalSessionCheckpoint,
        backend_compatibility: BackendCompatibility | None,
    ) -> None:
        """Mathematics: Require exact session/artifact/schema identity and explicit approval for backend-profile migration."""
        if checkpoint.session_id != self.session_id:
            raise ComputationalSessionIntegrityError("checkpoint belongs to another computational session")
        if checkpoint.artifact_manifest_digest != self.artifact_manifest_digest:
            raise ComputationalSessionIntegrityError("checkpoint belongs to another immutable computational artifact")
        if checkpoint.state_schema_id != self.state_schema_id:
            raise ComputationalSessionIntegrityError("checkpoint state schema is incompatible with this session")
        if checkpoint.state_manifest.media_type != self.state_media_type:
            raise ComputationalSessionIntegrityError("checkpoint state media type differs from the configured session")
        if checkpoint.backend_fingerprint != self.backend_fingerprint:
            if backend_compatibility is None:
                raise ComputationalSessionIntegrityError(
                    "checkpoint backend differs; an explicit backend compatibility predicate is required"
                )
            try:
                compatible = backend_compatibility(
                    checkpoint.backend_fingerprint,
                    self.backend_fingerprint,
                    checkpoint.state_schema_id,
                )
            except Exception as exc:
                raise ComputationalSessionIntegrityError("backend compatibility predicate failed") from exc
            if compatible is not True:
                raise ComputationalSessionIntegrityError("target backend refused the checkpoint state compatibility contract")

    def _pending_proposal(self, generation: int):
        """Mathematics: Find the unique already-prepared proposal at a session revision, refusing conflicting occupied-slot histories."""
        proposals: dict[str, Any] = {}
        for authority in self.lineage.authorities.values():
            try:
                proposal = authority.proposal_at(generation)
            except RecoveryLineageError:
                continue
            if proposal is not None:
                proposals[proposal.digest] = proposal
        if len(proposals) > 1:
            raise ComputationalSessionIntegrityError(
                f"conflicting prepared proposals occupy session revision {generation}"
            )
        return next(iter(proposals.values()), None)

    def _record_path(self, generation: int, recovery_manifest_digest: str) -> Path:
        """Mathematics: Address one immutable checkpoint envelope by its monotonic revision and recovery-manifest root."""
        _require_positive_integer(generation, "generation")
        _require_digest(recovery_manifest_digest, "recovery_manifest_digest")
        return self._session_dir / f"generation-{generation:020d}-{recovery_manifest_digest}.json"

    def _persist_record(
        self,
        checkpoint: ComputationalSessionCheckpoint,
        recovery_manifest: RecoveryStateManifest,
    ) -> None:
        """Mathematics: Fsync the exact canonical checkpoint envelope before any quorum anchor is requested."""
        payload = {
            "schema": _RECORD_SCHEMA,
            "checkpoint": checkpoint.to_dict(),
            "lineage_manifest": recovery_manifest.snapshot(),
        }
        encoded = _canonical_bytes(payload, "session checkpoint envelope")
        target = self._record_path(checkpoint.revision, recovery_manifest.digest)
        if target.is_symlink():
            raise ComputationalSessionIntegrityError("checkpoint envelope cannot be a symlink")
        if target.exists():
            if target.read_bytes() != encoded:
                raise ComputationalSessionConflictError("an immutable checkpoint path already contains different bytes")
            return
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".session-checkpoint-",
            suffix=".tmp",
            dir=str(self._session_dir),
        )
        temporary = Path(temporary_name)
        try:
            if hasattr(os, "fchmod"):
                os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
            try:
                directory_fd = os.open(
                    str(self._session_dir),
                    os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
                )
            except OSError:
                directory_fd = None
            if directory_fd is not None:
                try:
                    os.fsync(directory_fd)
                except OSError:
                    pass
                finally:
                    os.close(directory_fd)
        except Exception:
            try:
                os.close(descriptor)
            except OSError:
                pass
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
            raise

    def _read_record(self, path: Path) -> Mapping[str, Any]:
        """Mathematics: Read and canonicality-check one immutable local checkpoint envelope before interpreting it."""
        if path.is_symlink() or not path.is_file():
            raise ComputationalSessionIntegrityError("quorum-anchored checkpoint envelope is missing or unsafe")
        try:
            raw = path.read_bytes()
            payload = json.loads(raw)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ComputationalSessionIntegrityError("cannot read computational session checkpoint envelope") from exc
        if not isinstance(payload, Mapping) or set(payload) != {"schema", "checkpoint", "lineage_manifest"}:
            raise ComputationalSessionIntegrityError("computational session checkpoint envelope fields are invalid")
        if payload["schema"] != _RECORD_SCHEMA or _canonical_bytes(payload, "session checkpoint envelope") != raw:
            raise ComputationalSessionIntegrityError("computational session checkpoint envelope is non-canonical")
        return payload

    @staticmethod
    def _decode_record(
        payload: Mapping[str, Any],
    ) -> tuple[ComputationalSessionCheckpoint, RecoveryStateManifest]:
        """Mathematics: Reconstruct the typed checkpoint and single-state quorum manifest from one canonical envelope."""
        try:
            checkpoint = ComputationalSessionCheckpoint.from_dict(payload["checkpoint"])
            recovery_manifest = RecoveryStateManifest.from_snapshot(payload["lineage_manifest"])
            return checkpoint, recovery_manifest
        except (KeyError, TypeError, ValueError) as exc:
            if isinstance(exc, ComputationalSessionError):
                raise
            raise ComputationalSessionIntegrityError("session checkpoint envelope contains malformed manifests") from exc

    @staticmethod
    def _is_exact_retry(
        current: ComputationalSessionSnapshot,
        *,
        expected_revision: int,
        expected_checkpoint_digest: str,
        next_state: bytes,
        transition_id: str,
        operation_id: str,
        input_digest: str,
        logical_time: int,
    ) -> bool:
        """Mathematics: Recognize only the exact immediately preceding committed transition after its response was lost."""
        checkpoint = current.checkpoint
        return (
            checkpoint.revision == expected_revision + 1
            and checkpoint.predecessor_checkpoint_digest == expected_checkpoint_digest
            and checkpoint.backend_fingerprint == self.backend_fingerprint
            and checkpoint.transition_id == transition_id
            and checkpoint.operation_id == operation_id
            and checkpoint.input_digest == input_digest
            and checkpoint.logical_time == logical_time
            and checkpoint.state_digest == _sha256(next_state)
        )

    @staticmethod
    def _with_replayed(snapshot: ComputationalSessionSnapshot) -> ComputationalSessionSnapshot:
        """Mathematics: Mark an exact continuation retry without changing checkpoint or quorum evidence."""
        return ComputationalSessionSnapshot(
            checkpoint=snapshot.checkpoint,
            state_bytes=snapshot.state_bytes,
            lineage_manifest=snapshot.lineage_manifest,
            proof=snapshot.proof,
            replayed=True,
        )
