"""Durable data bundles gated by quorum-anchored recovery lineage.

The checkpoint files are the recovery data plane. This module packages an
immutable requester/receiver/backend generation, persists its manifest, and
admits restoration only after the manifest is verified against the quorum
high-water mark.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .recovery_lineage import (
    RecoveryCheckpointManifest,
    RecoveryLineageCoordinator,
    RecoveryLineageError,
    RecoveryLineageProof,
)


class RecoveryCheckpointBundleError(RuntimeError):
    """Mathematics: A checkpoint bundle is incomplete, modified, unanchored, or not the quorum high-water."""


def _canonical_json(value: Any) -> bytes:
    """Mathematics: Encode a JSON value as its unique UTF-8 canonical byte representation."""

    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise RecoveryCheckpointBundleError("bundle value is outside canonical JSON") from exc


def _fsync_directory(path: Path) -> None:
    """Mathematics: Request persistence of directory-entry updates where the host filesystem supports it."""

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


def _backend_manifest_bytes(receiver_checkpoint: bytes) -> bytes:
    """Mathematics: Extract the canonical registered operation/resource domain from a v2 Transit receiver checkpoint."""

    try:
        envelope = json.loads(receiver_checkpoint.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RecoveryCheckpointBundleError("receiver checkpoint is not UTF-8 JSON") from exc
    if (
        not isinstance(envelope, Mapping)
        or envelope.get("format") != "mailcpu-transit-worker-checkpoint-v2"
        or not isinstance(envelope.get("state"), Mapping)
    ):
        raise RecoveryCheckpointBundleError(
            "recovery bundle requires a v2 Transit receiver checkpoint with an explicit backend manifest"
        )
    manifest = envelope["state"].get("backend_manifest")
    if not isinstance(manifest, list) or not manifest:
        raise RecoveryCheckpointBundleError("receiver checkpoint backend manifest is missing")
    pairs: list[tuple[str, str]] = []
    for item in manifest:
        if (
            not isinstance(item, list)
            or len(item) != 2
            or any(not isinstance(part, str) or not part for part in item)
        ):
            raise RecoveryCheckpointBundleError("receiver backend manifest entries must be non-empty string pairs")
        pairs.append((item[0], item[1]))
    if pairs != sorted(set(pairs)):
        raise RecoveryCheckpointBundleError("receiver backend manifest must be sorted and unique")
    return _canonical_json([[operation, resource] for operation, resource in pairs])


@dataclass(frozen=True)
class VerifiedRecoveryCheckpointBundle:
    """Mathematics: Immutable in-memory bytes admitted by one exact quorum checkpoint proof."""

    manifest: RecoveryCheckpointManifest
    proof: RecoveryLineageProof
    requester_checkpoint: bytes
    receiver_checkpoint: bytes
    backend_manifest: bytes

    def __post_init__(self) -> None:
        """Mathematics: Recheck byte identities and proof-root linkage before exposing a restored bundle."""

        if not isinstance(self.manifest, RecoveryCheckpointManifest):
            raise RecoveryCheckpointBundleError("verified bundle requires a typed manifest")
        if not isinstance(self.proof, RecoveryLineageProof):
            raise RecoveryCheckpointBundleError("verified bundle requires a typed quorum proof")
        try:
            self.manifest.verify_payloads(
                self.requester_checkpoint,
                self.receiver_checkpoint,
                self.backend_manifest,
            )
        except RecoveryLineageError as exc:
            raise RecoveryCheckpointBundleError(str(exc)) from exc
        if _backend_manifest_bytes(self.receiver_checkpoint) != self.backend_manifest:
            raise RecoveryCheckpointBundleError(
                "backend manifest file does not match the receiver checkpoint"
            )
        if (
            self.proof.proposal.slot != self.manifest.generation
            or self.proof.proposal.result_state_digest != self.manifest.digest
        ):
            raise RecoveryCheckpointBundleError("quorum proof does not anchor this bundle manifest")

    @property
    def generation(self) -> int:
        """Mathematics: Return the monotonic checkpoint generation admitted by the quorum proof."""

        return self.manifest.generation

    def restore_receiver_session(
        self,
        request_transport: Any,
        response_transport: Any,
        compute_host_factory: Any = None,
    ) -> Any:
        """Mathematics: Reconstruct the receiver runtime from the exact verified bytes after the caller rebinds fresh transports."""

        from .transit_session import TransitComputeSession

        try:
            payload = json.loads(self.receiver_checkpoint.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RecoveryCheckpointBundleError("verified receiver checkpoint is not valid UTF-8 JSON") from exc
        if not isinstance(payload, Mapping):
            raise RecoveryCheckpointBundleError("verified receiver checkpoint root must be an object")
        return TransitComputeSession.from_snapshot(
            payload,
            request_transport,
            response_transport,
            compute_host_factory=compute_host_factory,
        )


class RecoveryCheckpointBundleStore:
    """Mathematics: Immutable generation store whose restore read is gated by a strict-majority recovery lineage."""

    REQUESTER_FILE = "requester.json"
    RECEIVER_FILE = "receiver.json"
    BACKEND_FILE = "backend-manifest.json"
    MANIFEST_FILE = "manifest.json"

    def __init__(
        self,
        directory: str | os.PathLike[str],
        coordinator: RecoveryLineageCoordinator,
    ) -> None:
        """Mathematics: Bind an immutable local bundle directory to one fixed-membership quorum coordinator."""

        if not isinstance(coordinator, RecoveryLineageCoordinator):
            raise RecoveryCheckpointBundleError("bundle store requires a RecoveryLineageCoordinator")
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.coordinator = coordinator

    def _generation_directory(self, generation: int) -> Path:
        """Mathematics: Map a positive lineage slot to a stable, sortable immutable directory coordinate."""

        if not isinstance(generation, int) or isinstance(generation, bool) or generation <= 0:
            raise RecoveryCheckpointBundleError("checkpoint generation must be a positive integer")
        return self.directory / f"generation-{generation:020d}"

    def _persist_generation(
        self,
        generation: int,
        requester_checkpoint: bytes,
        receiver_checkpoint: bytes,
        backend_manifest: bytes,
        manifest: RecoveryCheckpointManifest,
    ) -> Path:
        """Mathematics: Durably publish all four generation artifacts as one immutable directory before quorum prepare."""

        target = self._generation_directory(generation)
        expected = {
            self.REQUESTER_FILE: requester_checkpoint,
            self.RECEIVER_FILE: receiver_checkpoint,
            self.BACKEND_FILE: backend_manifest,
            self.MANIFEST_FILE: _canonical_json(manifest.snapshot()) + b"\n",
        }
        if target.exists():
            try:
                actual = {name: (target / name).read_bytes() for name in expected}
            except OSError as exc:
                raise RecoveryCheckpointBundleError("existing generation directory is incomplete") from exc
            if actual != expected:
                raise RecoveryCheckpointBundleError(
                    f"generation {generation} already contains different checkpoint bytes"
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
                # A concurrent identical publisher may have won the directory
                # race. The winner must have published the exact same bytes.
                actual = {name: (target / name).read_bytes() for name in expected}
                if actual != expected:
                    raise RecoveryCheckpointBundleError(
                        f"generation {generation} was concurrently published with different bytes"
                    )
            _fsync_directory(self.directory)
        except Exception:
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)
            raise
        return target

    def seal(
        self,
        requester_checkpoint_path: str | os.PathLike[str],
        receiver_checkpoint_path: str | os.PathLike[str],
        capture_cut: str,
    ) -> VerifiedRecoveryCheckpointBundle:
        """Mathematics: Copy durable endpoint snapshots, persist their manifest, then seal the root on a strict-majority quorum."""

        try:
            requester_checkpoint = Path(requester_checkpoint_path).read_bytes()
            receiver_checkpoint = Path(receiver_checkpoint_path).read_bytes()
        except OSError as exc:
            raise RecoveryCheckpointBundleError(f"cannot read endpoint checkpoints: {exc}") from exc
        if not requester_checkpoint or not receiver_checkpoint:
            raise RecoveryCheckpointBundleError("requester and receiver checkpoint files must be non-empty")
        backend_manifest = _backend_manifest_bytes(receiver_checkpoint)
        try:
            previous_generation, predecessor_digest = self.coordinator.high_water()
        except RecoveryLineageError as exc:
            raise RecoveryCheckpointBundleError(f"cannot read recovery lineage high-water: {exc}") from exc

        membership = self.coordinator.membership
        try:
            manifest = RecoveryCheckpointManifest(
                machine_id=membership.system_id,
                incarnation=membership.incarnation,
                owner_id=membership.owner_id,
                owner_term=membership.owner_term,
                membership_digest=membership.digest,
                generation=previous_generation + 1,
                predecessor_digest=predecessor_digest,
                requester_checkpoint_digest=hashlib.sha256(requester_checkpoint).hexdigest(),
                receiver_checkpoint_digest=hashlib.sha256(receiver_checkpoint).hexdigest(),
                backend_manifest_digest=hashlib.sha256(backend_manifest).hexdigest(),
                capture_cut=capture_cut,
            )
        except RecoveryLineageError as exc:
            raise RecoveryCheckpointBundleError(f"checkpoint manifest is invalid: {exc}") from exc
        self._persist_generation(
            manifest.generation,
            requester_checkpoint,
            receiver_checkpoint,
            backend_manifest,
            manifest,
        )
        try:
            proof = self.coordinator.seal(manifest)
        except RecoveryLineageError as exc:
            raise RecoveryCheckpointBundleError(
                f"generation {manifest.generation} is durable locally but not quorum-anchored: {exc}"
            ) from exc
        return VerifiedRecoveryCheckpointBundle(
            manifest,
            proof,
            requester_checkpoint,
            receiver_checkpoint,
            backend_manifest,
        )

    def load(self, generation: int | None = None) -> VerifiedRecoveryCheckpointBundle:
        """Mathematics: Admit only a stored generation whose exact endpoint/backend bytes match the quorum-supported high-water root."""

        try:
            latest = self.coordinator.latest_proof()
        except RecoveryLineageError as exc:
            raise RecoveryCheckpointBundleError(f"cannot read recovery lineage quorum: {exc}") from exc
        if latest is None:
            raise RecoveryCheckpointBundleError("no checkpoint generation has been quorum-anchored")
        selected_generation = latest.proposal.slot if generation is None else generation
        directory = self._generation_directory(selected_generation)
        try:
            requester_checkpoint = (directory / self.REQUESTER_FILE).read_bytes()
            receiver_checkpoint = (directory / self.RECEIVER_FILE).read_bytes()
            backend_manifest = (directory / self.BACKEND_FILE).read_bytes()
            manifest_bytes = (directory / self.MANIFEST_FILE).read_bytes()
        except OSError as exc:
            raise RecoveryCheckpointBundleError(
                f"checkpoint generation {selected_generation} is not completely available: {exc}"
            ) from exc
        try:
            snapshot = json.loads(manifest_bytes.decode("utf-8"))
            manifest = RecoveryCheckpointManifest.from_snapshot(snapshot)
        except (UnicodeDecodeError, json.JSONDecodeError, RecoveryLineageError) as exc:
            raise RecoveryCheckpointBundleError(f"checkpoint generation {selected_generation} manifest is invalid") from exc
        if manifest_bytes != _canonical_json(manifest.snapshot()) + b"\n":
            raise RecoveryCheckpointBundleError("checkpoint manifest is not in canonical persisted form")
        embedded_backend = _backend_manifest_bytes(receiver_checkpoint)
        if embedded_backend != backend_manifest:
            raise RecoveryCheckpointBundleError("backend manifest file does not match the receiver checkpoint")
        try:
            proof = self.coordinator.verify_checkpoint_bundle(
                manifest,
                requester_checkpoint,
                receiver_checkpoint,
                backend_manifest,
            )
        except RecoveryLineageError as exc:
            raise RecoveryCheckpointBundleError(f"checkpoint generation {selected_generation} refused: {exc}") from exc
        return VerifiedRecoveryCheckpointBundle(
            manifest,
            proof,
            requester_checkpoint,
            receiver_checkpoint,
            backend_manifest,
        )

    def load_latest(self) -> VerifiedRecoveryCheckpointBundle:
        """Mathematics: Resolve and load exactly the current quorum high-water generation without trusting a local latest pointer."""

        return self.load()
