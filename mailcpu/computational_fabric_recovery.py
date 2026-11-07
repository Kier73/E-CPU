"""Quorum-anchored durable recovery for federated computational directories.

Directory checkpoints contain only policy and anti-rollback high-water state.
Remote snapshots and monotonic leases are deliberately reacquired after restore.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping
import time

from .computational_fabric import ComputationalFabricDirectory, ComputationalFabricError
from .recovery_lineage import (
    RecoveryLineageCoordinator,
    RecoveryLineageError,
    RecoveryLineageProof,
    RecoveryStateManifest,
)


class ComputationalFabricRecoveryError(RuntimeError):
    """Mathematics: A federated directory artifact is incomplete, modified, stale, or not quorum-anchored."""


def _canonical_json(value: Any) -> bytes:
    """Mathematics: Encode a finite record as sorted compact UTF-8 JSON bytes."""
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ComputationalFabricRecoveryError("fabric recovery record is outside canonical JSON") from exc


def _fsync_directory(path: Path) -> None:
    """Mathematics: Request persistence of directory-entry updates where supported by the host filesystem."""
    try:
        descriptor = os.open(str(path), os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


@dataclass(frozen=True)
class VerifiedComputationalFabricCheckpoint:
    """A directory restored only after its exact state root passes quorum high-water verification."""

    manifest: RecoveryStateManifest
    proof: RecoveryLineageProof
    directory: ComputationalFabricDirectory
    directory_checkpoint: Mapping[str, Any]
    directory_bytes: bytes

    def __post_init__(self) -> None:
        """Mathematics: Recheck the artifact digest and proof-root linkage before exposing recovered directory state."""
        if not isinstance(self.manifest, RecoveryStateManifest):
            raise ComputationalFabricRecoveryError("verified fabric checkpoint requires a typed state manifest")
        if not isinstance(self.proof, RecoveryLineageProof):
            raise ComputationalFabricRecoveryError("verified fabric checkpoint requires a quorum proof")
        if not isinstance(self.directory, ComputationalFabricDirectory):
            raise ComputationalFabricRecoveryError("verified fabric checkpoint requires a restored directory")
        try:
            self.manifest.verify_payload(self.directory_bytes)
        except RecoveryLineageError as exc:
            raise ComputationalFabricRecoveryError(str(exc)) from exc
        if (
            self.proof.proposal.slot != self.manifest.generation
            or self.proof.proposal.result_state_digest != self.manifest.digest
        ):
            raise ComputationalFabricRecoveryError("quorum proof does not anchor this fabric directory manifest")
        if _canonical_json(dict(self.directory_checkpoint)) + b"\n" != self.directory_bytes:
            raise ComputationalFabricRecoveryError("directory checkpoint bytes are not canonical")

    @property
    def generation(self) -> int:
        """Mathematics: Return the monotonic recovery generation sealed by the quorum proof."""
        return self.manifest.generation


class ComputationalFabricRecoveryStore:
    """Immutable directory-checkpoint store gated by the existing fixed-membership recovery lineage."""

    DIRECTORY_FILE = "directory.json"
    MANIFEST_FILE = "manifest.json"

    def __init__(
        self,
        directory: str | os.PathLike[str],
        coordinator: RecoveryLineageCoordinator,
    ) -> None:
        """Mathematics: Bind an immutable artifact directory to one configured recovery-lineage quorum."""
        if not isinstance(coordinator, RecoveryLineageCoordinator):
            raise ComputationalFabricRecoveryError("fabric recovery store requires a RecoveryLineageCoordinator")
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.coordinator = coordinator

    def _generation_directory(self, generation: int) -> Path:
        """Mathematics: Map one positive recovery slot to a stable immutable directory coordinate."""
        if not isinstance(generation, int) or isinstance(generation, bool) or generation <= 0:
            raise ComputationalFabricRecoveryError("fabric recovery generation must be a positive integer")
        return self.directory / f"generation-{generation:020d}"

    def _persist_generation(
        self,
        generation: int,
        directory_bytes: bytes,
        manifest: RecoveryStateManifest,
    ) -> Path:
        """Mathematics: Fsync the checkpoint and manifest before atomically publishing one immutable generation."""
        target = self._generation_directory(generation)
        expected = {
            self.DIRECTORY_FILE: directory_bytes,
            self.MANIFEST_FILE: _canonical_json(manifest.snapshot()) + b"\n",
        }
        if target.exists():
            try:
                actual = {name: (target / name).read_bytes() for name in expected}
            except OSError as exc:
                raise ComputationalFabricRecoveryError("existing fabric generation is incomplete") from exc
            if actual != expected:
                raise ComputationalFabricRecoveryError(
                    f"fabric generation {generation} already contains different checkpoint bytes"
                )
            return target

        staging = Path(tempfile.mkdtemp(prefix=f".generation-{generation:020d}.", dir=str(self.directory)))
        try:
            for name, payload in expected.items():
                path = staging / name
                with path.open("xb") as stream:
                    stream.write(payload)
                    stream.flush()
                    os.fsync(stream.fileno())
            _fsync_directory(staging)
            try:
                os.rename(staging, target)
            except FileExistsError:
                actual = {name: (target / name).read_bytes() for name in expected}
                if actual != expected:
                    raise ComputationalFabricRecoveryError(
                        f"fabric generation {generation} was concurrently published with different bytes"
                    )
            _fsync_directory(self.directory)
            return target
        finally:
            if staging.exists():
                for item in staging.iterdir():
                    item.unlink(missing_ok=True)
                staging.rmdir()

    def seal(
        self,
        directory: ComputationalFabricDirectory,
        capture_cut: str,
    ) -> VerifiedComputationalFabricCheckpoint:
        """Mathematics: Persist one canonical directory checkpoint, then quorum-commit its content root."""
        if not isinstance(directory, ComputationalFabricDirectory):
            raise ComputationalFabricRecoveryError("seal requires a ComputationalFabricDirectory")
        if not isinstance(capture_cut, str) or not capture_cut or capture_cut.strip() != capture_cut:
            raise ComputationalFabricRecoveryError("capture_cut must be non-empty trimmed text")
        checkpoint = directory.checkpoint()
        directory_bytes = _canonical_json(checkpoint) + b"\n"
        try:
            previous_generation, predecessor_digest = self.coordinator.high_water()
            membership = self.coordinator.membership
            manifest = RecoveryStateManifest(
                machine_id=membership.system_id,
                incarnation=membership.incarnation,
                owner_id=membership.owner_id,
                owner_term=membership.owner_term,
                membership_digest=membership.digest,
                generation=previous_generation + 1,
                predecessor_digest=predecessor_digest,
                state_digest=hashlib.sha256(directory_bytes).hexdigest(),
                capture_cut=capture_cut,
            )
        except RecoveryLineageError as exc:
            raise ComputationalFabricRecoveryError(f"cannot construct fabric recovery manifest: {exc}") from exc

        self._persist_generation(manifest.generation, directory_bytes, manifest)
        try:
            proof = self.coordinator.seal(manifest)
        except RecoveryLineageError as exc:
            raise ComputationalFabricRecoveryError(
                f"fabric generation {manifest.generation} is durable locally but not quorum-anchored: {exc}"
            ) from exc
        restored = ComputationalFabricDirectory.from_checkpoint(checkpoint)
        return VerifiedComputationalFabricCheckpoint(
            manifest,
            proof,
            restored,
            checkpoint,
            directory_bytes,
        )

    def load(
        self,
        generation: int | None = None,
        *,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> VerifiedComputationalFabricCheckpoint:
        """Mathematics: Admit only the exact stored directory artifact matching the current quorum high-water root."""
        try:
            latest = self.coordinator.latest_proof()
        except RecoveryLineageError as exc:
            raise ComputationalFabricRecoveryError(f"cannot read fabric recovery quorum: {exc}") from exc
        if latest is None:
            raise ComputationalFabricRecoveryError("no fabric directory generation has been quorum-anchored")
        selected_generation = latest.proposal.slot if generation is None else generation
        directory_path = self._generation_directory(selected_generation)
        try:
            directory_bytes = (directory_path / self.DIRECTORY_FILE).read_bytes()
            manifest_bytes = (directory_path / self.MANIFEST_FILE).read_bytes()
        except OSError as exc:
            raise ComputationalFabricRecoveryError(
                f"fabric directory generation {selected_generation} is unavailable: {exc}"
            ) from exc
        try:
            snapshot = json.loads(manifest_bytes.decode("utf-8"))
            manifest = RecoveryStateManifest.from_snapshot(snapshot)
        except (UnicodeDecodeError, json.JSONDecodeError, RecoveryLineageError) as exc:
            raise ComputationalFabricRecoveryError(
                f"fabric directory generation {selected_generation} manifest is invalid"
            ) from exc
        if manifest_bytes != _canonical_json(manifest.snapshot()) + b"\n":
            raise ComputationalFabricRecoveryError("fabric recovery manifest is not canonically persisted")
        if manifest.generation != selected_generation:
            raise ComputationalFabricRecoveryError("fabric manifest generation differs from its directory coordinate")
        try:
            manifest.verify_payload(directory_bytes)
            proof = self.coordinator.verify_state(manifest)
        except RecoveryLineageError as exc:
            raise ComputationalFabricRecoveryError(f"fabric generation {selected_generation} refused: {exc}") from exc
        try:
            checkpoint = json.loads(directory_bytes.decode("utf-8"))
            if not isinstance(checkpoint, Mapping):
                raise ComputationalFabricRecoveryError("fabric directory checkpoint root must be an object")
            restored = ComputationalFabricDirectory.from_checkpoint(checkpoint, monotonic=monotonic)
        except (UnicodeDecodeError, json.JSONDecodeError, ComputationalFabricError) as exc:
            raise ComputationalFabricRecoveryError("fabric directory checkpoint is invalid") from exc
        return VerifiedComputationalFabricCheckpoint(
            manifest,
            proof,
            restored,
            checkpoint,
            directory_bytes,
        )

    def load_latest(
        self,
        *,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> VerifiedComputationalFabricCheckpoint:
        """Mathematics: Resolve and load exactly the current quorum high-water fabric generation."""
        return self.load(monotonic=monotonic)
