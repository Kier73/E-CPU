"""Quorum-anchored per-hop recovery for federated computational forwarding.

The checkpoint joins one peer's Hypervisor replay state with its inbound,
outbound, and downstream reliable-channel state. Network transports, active
directory leases, runtime callables, and capability grants are rebound locally.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
from dataclasses import dataclass
from typing import Any, Mapping
import time

from .computational_fabric import ComputationalFabricDirectory
from .computational_fabric_forwarding import ComputationalFabricForwardingServer
from .headless import HeadlessOS
from .recovery_lineage import (
    RecoveryLineageCoordinator,
    RecoveryLineageError,
    RecoveryLineageProof,
    RecoveryStateManifest,
)


class ComputationalFabricForwardingRecoveryError(RuntimeError):
    """A forwarding checkpoint is malformed, incomplete, unanchored, or stale."""


_CAPTURE_CUTS = frozenset({
    "idle",
    "before_execution",
    "after_execution_commit",
    "after_response_publish",
    "after_request_ack",
})


def _canonical_json(value: Any) -> bytes:
    """Encode one finite record into the unique sorted compact JSON byte form."""
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ComputationalFabricForwardingRecoveryError(
            "forwarding checkpoint is outside canonical JSON"
        ) from exc


def _fsync_directory(path: Path) -> None:
    """Best-effort persistence of directory-entry updates on supported filesystems."""
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


def _validate_snapshot(value: Any, capture_cut: str | None = None) -> dict[str, Any]:
    """Validate the forwarding snapshot envelope without interpreting runtime-owned state."""
    if not isinstance(value, Mapping):
        raise ComputationalFabricForwardingRecoveryError(
            "forwarding checkpoint root must be an object"
        )
    snapshot = dict(value)
    if (
        snapshot.get("schema") != "mailcpu.computational-fabric-forwarding-server.v1"
        or type(snapshot.get("version")) is not int
        or snapshot["version"] != 1
    ):
        raise ComputationalFabricForwardingRecoveryError(
            "forwarding checkpoint schema or version is unsupported"
        )
    cut = snapshot.get("capture_cut")
    if not isinstance(cut, str) or cut not in _CAPTURE_CUTS:
        raise ComputationalFabricForwardingRecoveryError(
            "forwarding checkpoint capture cut is unsupported"
        )
    if capture_cut is not None and cut != capture_cut:
        raise ComputationalFabricForwardingRecoveryError(
            "forwarding checkpoint capture cut differs from the manifest"
        )
    required = {
        "schema",
        "version",
        "capture_cut",
        "local_peer_id",
        "previous_peer_id",
        "origin_peer_id",
        "origin_channel",
        "authority_pid",
        "timeout",
        "max_payload_bytes",
        "operating_system",
        "inbound_channel",
        "outbound_channel",
        "next_hop_clients",
    }
    if set(snapshot) != required:
        raise ComputationalFabricForwardingRecoveryError(
            "forwarding checkpoint fields are incomplete or unexpected"
        )
    for name in ("local_peer_id", "previous_peer_id", "origin_peer_id", "origin_channel"):
        item = snapshot.get(name)
        if not isinstance(item, str) or not item or item.strip() != item:
            raise ComputationalFabricForwardingRecoveryError(
                f"forwarding checkpoint {name} is invalid"
            )
    if (
        type(snapshot.get("authority_pid")) is not int
        or snapshot["authority_pid"] <= 0
        or not isinstance(snapshot.get("timeout"), (int, float))
        or isinstance(snapshot.get("timeout"), bool)
        or snapshot["timeout"] <= 0
        or type(snapshot.get("max_payload_bytes")) is not int
        or snapshot["max_payload_bytes"] < 256
    ):
        raise ComputationalFabricForwardingRecoveryError(
            "forwarding checkpoint runtime bounds or authority identity are invalid"
        )
    for field in ("operating_system", "inbound_channel", "outbound_channel", "next_hop_clients"):
        if not isinstance(snapshot.get(field), Mapping):
            raise ComputationalFabricForwardingRecoveryError(
                f"forwarding checkpoint {field} must be an object"
            )
    clients = snapshot["next_hop_clients"]
    if any(not isinstance(peer, str) or not peer for peer in clients):
        raise ComputationalFabricForwardingRecoveryError(
            "forwarding checkpoint downstream peer identities are invalid"
        )
    return snapshot


@dataclass(frozen=True)
class VerifiedComputationalFabricForwardingCheckpoint:
    """One immutable forwarding snapshot whose exact content root passed quorum verification."""

    manifest: RecoveryStateManifest
    proof: RecoveryLineageProof
    snapshot: Mapping[str, Any]
    snapshot_bytes: bytes

    def __post_init__(self) -> None:
        """Recheck payload digest, canonical projection, and exact quorum-root linkage."""
        if not isinstance(self.manifest, RecoveryStateManifest):
            raise ComputationalFabricForwardingRecoveryError(
                "verified forwarding checkpoint requires a typed state manifest"
            )
        if not isinstance(self.proof, RecoveryLineageProof):
            raise ComputationalFabricForwardingRecoveryError(
                "verified forwarding checkpoint requires a quorum proof"
            )
        try:
            self.manifest.verify_payload(self.snapshot_bytes)
        except RecoveryLineageError as exc:
            raise ComputationalFabricForwardingRecoveryError(str(exc)) from exc
        snapshot = _validate_snapshot(self.snapshot)
        if _canonical_json(snapshot) + b"\n" != self.snapshot_bytes:
            raise ComputationalFabricForwardingRecoveryError(
                "forwarding snapshot bytes are not the canonical persisted projection"
            )
        if (
            self.proof.proposal.slot != self.manifest.generation
            or self.proof.proposal.result_state_digest != self.manifest.digest
        ):
            raise ComputationalFabricForwardingRecoveryError(
                "quorum proof does not anchor this forwarding manifest"
            )
        object.__setattr__(self, "snapshot", snapshot)

    @property
    def generation(self) -> int:
        """Return the monotonic recovery generation sealed by the quorum proof."""
        return self.manifest.generation

    def restore_operating_system(self) -> HeadlessOS:
        """Restore the local VM, capabilities, Hypervisor decision/effect ledger, and journal state."""
        try:
            return HeadlessOS.from_snapshot(dict(self.snapshot["operating_system"]))
        except Exception as exc:
            raise ComputationalFabricForwardingRecoveryError(
                f"cannot reconstruct receiver-local HeadlessOS state: {exc}"
            ) from exc

    def restore_server(
        self,
        transport: Any,
        directory: ComputationalFabricDirectory,
        *,
        next_hop_transports: Mapping[str, Any] | None = None,
        catalogue: Any = None,
        operating_system: HeadlessOS | None = None,
    ) -> ComputationalFabricForwardingServer:
        """Rebind a verified peer snapshot to fresh authenticated transports and live local policy objects."""
        restored_os = operating_system or self.restore_operating_system()
        try:
            return ComputationalFabricForwardingServer.from_snapshot(
                self.snapshot,
                transport,
                directory,
                next_hop_transports=next_hop_transports,
                catalogue=catalogue,
                operating_system=restored_os,
            )
        except Exception as exc:
            raise ComputationalFabricForwardingRecoveryError(
                f"cannot rebind restored forwarding service: {exc}"
            ) from exc


class ComputationalFabricForwardingRecoveryStore:
    """Immutable per-peer checkpoint store gated by the existing fixed-membership recovery quorum."""

    SNAPSHOT_FILE = "forwarding.json"
    MANIFEST_FILE = "manifest.json"

    def __init__(
        self,
        directory: str | os.PathLike[str],
        coordinator: RecoveryLineageCoordinator,
    ) -> None:
        """Bind immutable forwarding checkpoint generations to one configured RecoveryLineageCoordinator."""
        if not isinstance(coordinator, RecoveryLineageCoordinator):
            raise ComputationalFabricForwardingRecoveryError(
                "forwarding recovery store requires a RecoveryLineageCoordinator"
            )
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.coordinator = coordinator

    def _generation_directory(self, generation: int) -> Path:
        """Map one positive recovery slot to a stable immutable on-disk coordinate."""
        if type(generation) is not int or generation <= 0:
            raise ComputationalFabricForwardingRecoveryError(
                "forwarding recovery generation must be a positive integer"
            )
        return self.directory / f"generation-{generation:020d}"

    def _persist_generation(
        self,
        generation: int,
        snapshot_bytes: bytes,
        manifest: RecoveryStateManifest,
    ) -> Path:
        """Fsync the full peer snapshot and manifest before atomically publishing the generation."""
        target = self._generation_directory(generation)
        expected = {
            self.SNAPSHOT_FILE: snapshot_bytes,
            self.MANIFEST_FILE: _canonical_json(manifest.snapshot()) + b"\n",
        }
        if target.exists():
            try:
                actual = {name: (target / name).read_bytes() for name in expected}
            except OSError as exc:
                raise ComputationalFabricForwardingRecoveryError(
                    "existing forwarding generation is incomplete"
                ) from exc
            if actual != expected:
                raise ComputationalFabricForwardingRecoveryError(
                    f"forwarding generation {generation} already contains different bytes"
                )
            return target

        staging = Path(tempfile.mkdtemp(
            prefix=f".generation-{generation:020d}.",
            dir=str(self.directory),
        ))
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
                    raise ComputationalFabricForwardingRecoveryError(
                        f"forwarding generation {generation} was concurrently published with different bytes"
                    )
            _fsync_directory(self.directory)
            return target
        finally:
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)

    def seal(
        self,
        server: ComputationalFabricForwardingServer,
        capture_cut: str,
    ) -> VerifiedComputationalFabricForwardingCheckpoint:
        """Persist one consistent per-hop capture cut, then quorum-commit its content root."""
        if not isinstance(server, ComputationalFabricForwardingServer):
            raise ComputationalFabricForwardingRecoveryError(
                "seal requires a ComputationalFabricForwardingServer"
            )
        if capture_cut not in _CAPTURE_CUTS:
            raise ComputationalFabricForwardingRecoveryError(
                f"capture_cut must be one of {sorted(_CAPTURE_CUTS)}"
            )
        try:
            snapshot = _validate_snapshot(server.snapshot(capture_cut=capture_cut), capture_cut)
            snapshot_bytes = _canonical_json(snapshot) + b"\n"
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
                state_digest=hashlib.sha256(snapshot_bytes).hexdigest(),
                capture_cut=capture_cut,
            )
        except RecoveryLineageError as exc:
            raise ComputationalFabricForwardingRecoveryError(
                f"cannot construct forwarding recovery manifest: {exc}"
            ) from exc
        self._persist_generation(manifest.generation, snapshot_bytes, manifest)
        try:
            proof = self.coordinator.seal(manifest)
        except RecoveryLineageError as exc:
            raise ComputationalFabricForwardingRecoveryError(
                f"forwarding generation {manifest.generation} is durable locally but not quorum-anchored: {exc}"
            ) from exc
        return VerifiedComputationalFabricForwardingCheckpoint(
            manifest,
            proof,
            snapshot,
            snapshot_bytes,
        )

    def load(
        self,
        generation: int | None = None,
    ) -> VerifiedComputationalFabricForwardingCheckpoint:
        """Load only the exact current quorum high-water artifact; stale peer snapshots are never admitted."""
        try:
            latest = self.coordinator.latest_proof()
        except RecoveryLineageError as exc:
            raise ComputationalFabricForwardingRecoveryError(
                f"cannot read forwarding recovery quorum: {exc}"
            ) from exc
        if latest is None:
            raise ComputationalFabricForwardingRecoveryError(
                "no forwarding generation has been quorum-anchored"
            )
        selected = latest.proposal.slot if generation is None else generation
        directory = self._generation_directory(selected)
        try:
            snapshot_bytes = (directory / self.SNAPSHOT_FILE).read_bytes()
            manifest_bytes = (directory / self.MANIFEST_FILE).read_bytes()
        except OSError as exc:
            raise ComputationalFabricForwardingRecoveryError(
                f"forwarding generation {selected} is unavailable: {exc}"
            ) from exc
        try:
            raw_manifest = json.loads(manifest_bytes.decode("utf-8"))
            manifest = RecoveryStateManifest.from_snapshot(raw_manifest)
            raw_snapshot = json.loads(snapshot_bytes.decode("utf-8"))
            snapshot = _validate_snapshot(raw_snapshot)
        except (UnicodeDecodeError, json.JSONDecodeError, RecoveryLineageError) as exc:
            raise ComputationalFabricForwardingRecoveryError(
                f"forwarding generation {selected} contains invalid checkpoint metadata"
            ) from exc
        if manifest_bytes != _canonical_json(manifest.snapshot()) + b"\n":
            raise ComputationalFabricForwardingRecoveryError(
                "forwarding recovery manifest is not canonically persisted"
            )
        if _canonical_json(snapshot) + b"\n" != snapshot_bytes:
            raise ComputationalFabricForwardingRecoveryError(
                "forwarding snapshot is not canonically persisted"
            )
        if manifest.generation != selected or manifest.capture_cut != snapshot["capture_cut"]:
            raise ComputationalFabricForwardingRecoveryError(
                "forwarding manifest generation or capture cut differs from the artifact"
            )
        try:
            manifest.verify_payload(snapshot_bytes)
            proof = self.coordinator.verify_state(manifest)
        except RecoveryLineageError as exc:
            raise ComputationalFabricForwardingRecoveryError(
                f"forwarding generation {selected} refused: {exc}"
            ) from exc
        return VerifiedComputationalFabricForwardingCheckpoint(
            manifest,
            proof,
            snapshot,
            snapshot_bytes,
        )

    def load_latest(self) -> VerifiedComputationalFabricForwardingCheckpoint:
        """Resolve and load exactly the latest quorum-anchored peer generation."""
        return self.load()
