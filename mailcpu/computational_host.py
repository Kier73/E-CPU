"""Mathematics: General computational artifact admission and local backend hosting.

This module composes multi-file artifact identity over the M1 byte-object
store, keeps backend implementation identity separate from immutable artifact
identity, and exposes local execution through the existing Virtual Layer and
Transit authority boundaries. Backend libraries remain optional adapters.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Mapping, Protocol, Sequence

from .classifier import HypervisorArbitrationEvent
from .computational_objects import ComputationalObjectManifest, ComputationalObjectStore
from .transit_compute import TransitComputeHost
from .virtual_layer import (
    OperatorRegistry,
    OperatorSpec,
    VirtualLayerError,
    VirtualLayerRuntime,
    VirtualLayerWorkload,
    VIRTUAL_LAYER_OPERATOR_OPERATION,
    virtual_layer_operator_resource,
)

_ARTIFACT_KIND = "mailcpu.computational-artifact-manifest"
_ARTIFACT_SCHEMA_VERSION = 1
_HOST_RECEIPT_KIND = "mailcpu.computational-host-receipt"
_HOST_RECEIPT_SCHEMA_VERSION = 1
_HEX_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_ARTIFACT_LABEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,255}\Z")
_SUBSTRATES = frozenset({"cpu", "gpu", "fpga", "dpu", "network", "memory", "sensor", "delay-loop"})
_DEFAULT_MAX_ARTIFACT_BYTES = 1 << 40
_DEFAULT_MAX_ARTIFACT_FILES = 100_000
_FILE_HASH_BLOCK_SIZE = 1024 * 1024


class ComputationalHostError(ValueError):
    """Mathematics: A computational artifact, backend profile, or local execution contract is invalid."""


class ComputationalArtifactError(ComputationalHostError):
    """Mathematics: Composite artifact admission, manifest verification, or storage composition failed."""


class ComputationalBackendError(ComputationalHostError):
    """Mathematics: Backend identity, lifecycle, input, output, or execution failed."""


class _FrozenDict(dict):
    """Mathematics: JSON-compatible dictionary that rejects mutation after validation."""

    def _reject(self, *args: Any, **kwargs: Any) -> None:
        """Mathematics: Refuse mutation of a value already bound into an immutable identity."""
        raise TypeError("validated computational metadata is immutable")

    __setitem__ = _reject
    __delitem__ = _reject
    clear = _reject
    pop = _reject
    popitem = _reject
    setdefault = _reject
    update = _reject
    __ior__ = _reject


def _freeze_json(value: Any, label: str) -> Any:
    """Mathematics: Validate finite JSON and recursively detach caller-owned containers."""
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ComputationalHostError(f"{label} contains a non-finite number")
        return value
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise ComputationalHostError(f"{label} object keys must be strings")
        return _FrozenDict({key: _freeze_json(item, label) for key, item in value.items()})
    if isinstance(value, (tuple, list)):
        return tuple(_freeze_json(item, label) for item in value)
    raise ComputationalHostError(f"{label} contains a value outside the finite JSON domain")


def _thaw_json(value: Any) -> Any:
    """Mathematics: Return a detached ordinary JSON value from validated immutable containers."""
    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


def _canonical_bytes(value: Any, label: str) -> bytes:
    """Mathematics: Encode one finite JSON value in canonical sorted compact UTF-8 form."""
    try:
        return json.dumps(
            _thaw_json(value),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ComputationalHostError(f"{label} is outside canonical JSON") from exc


def _digest_bytes(data: bytes) -> str:
    """Mathematics: Return the lowercase SHA-256 content identity of a byte sequence."""
    return hashlib.sha256(data).hexdigest()


def _require_digest(value: Any, name: str) -> str:
    """Mathematics: Require an exact lowercase SHA-256 hexadecimal digest."""
    if not isinstance(value, str) or _HEX_DIGEST.fullmatch(value) is None:
        raise ComputationalHostError(f"{name} must be a lowercase SHA-256 digest")
    return value


def _strict_integer(value: Any, name: str, *, minimum: int = 0) -> int:
    """Mathematics: Require an integer value without admitting Boolean coercion."""
    if type(value) is not int or value < minimum:
        raise ComputationalHostError(f"{name} must be an integer greater than or equal to {minimum}")
    return value


def _label(value: Any, name: str) -> str:
    """Mathematics: Validate a bounded stable identifier used in an artifact or operation contract."""
    if not isinstance(value, str) or _ARTIFACT_LABEL.fullmatch(value) is None:
        raise ComputationalHostError(f"{name} must be a non-empty bounded identifier")
    return value


def _artifact_path(value: Any) -> str:
    """Mathematics: Require one normalized, non-traversing relative POSIX artifact path."""
    if (
        not isinstance(value, str)
        or not value
        or "\\" in value
        or "\x00" in value
        or value.startswith("/")
    ):
        raise ComputationalArtifactError("artifact component path must be a relative POSIX path")
    parsed = PurePosixPath(value)
    if (
        parsed.is_absolute()
        or any(part in {"", ".", ".."} for part in parsed.parts)
        or parsed.as_posix() != value
    ):
        raise ComputationalArtifactError("artifact component path is not canonical or contains traversal")
    return value


def _compute_file_digest(path: Path) -> tuple[str, int]:
    """Mathematics: Stream one regular file into SHA-256 and return its exact logical extent."""
    hasher = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while block := stream.read(_FILE_HASH_BLOCK_SIZE):
            hasher.update(block)
            size += len(block)
    return hasher.hexdigest(), size


def _excluded(relative_path: str, exclusions: tuple[str, ...]) -> bool:
    """Mathematics: Decide whether a canonical relative path lies within an explicit excluded prefix."""
    return any(relative_path == item or relative_path.startswith(item + "/") for item in exclusions)


def _artifact_files(root: Path, exclusions: tuple[str, ...]) -> list[tuple[str, Path]]:
    """Mathematics: Enumerate regular artifact files without following or admitting symlinks."""
    if root.is_symlink() or not root.is_dir():
        raise ComputationalArtifactError("artifact root must be an existing non-symlink directory")
    resolved_root = root.resolve()
    files: list[tuple[str, Path]] = []
    for item in sorted(root.rglob("*")):
        relative = item.relative_to(root).as_posix()
        if _excluded(relative, exclusions):
            continue
        if item.is_symlink():
            raise ComputationalArtifactError(f"artifact trees cannot contain symlinks: {relative}")
        if item.is_dir():
            continue
        if not item.is_file():
            raise ComputationalArtifactError(f"artifact tree contains a non-regular entry: {relative}")
        resolved_item = item.resolve()
        if not resolved_item.is_relative_to(resolved_root):
            raise ComputationalArtifactError(f"artifact path escapes its root: {relative}")
        files.append((_artifact_path(relative), item))
    return files


@dataclass(frozen=True)
class ComputationalArtifactComponent:
    """Mathematics: Bind one normalized artifact path to its exact bytes and optional M1 page manifest."""

    path: str
    size_bytes: int
    content_digest: str
    media_type: str = "application/octet-stream"
    storage_manifest: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        """Mathematics: Validate component path, content identity, logical extent, and any page-backed descriptor."""
        _artifact_path(self.path)
        _strict_integer(self.size_bytes, "component size_bytes")
        if not isinstance(self.media_type, str) or re.fullmatch(
            r"[A-Za-z0-9!#$&^_.+-]+/[A-Za-z0-9!#$&^_.+-]+", self.media_type
        ) is None:
            raise ComputationalArtifactError("component media_type must be a MIME type/subtype value")
        _require_digest(self.content_digest, "component content_digest")
        if self.storage_manifest is not None:
            if not isinstance(self.storage_manifest, Mapping):
                raise ComputationalArtifactError("storage_manifest must be a mapping")
            try:
                descriptor = ComputationalObjectManifest.from_dict(_thaw_json(_freeze_json(self.storage_manifest, "storage_manifest")))
            except Exception as exc:
                raise ComputationalArtifactError("component storage_manifest is invalid") from exc
            if (
                descriptor.size_bytes != self.size_bytes
                or descriptor.content_digest != self.content_digest
                or descriptor.media_type != self.media_type
            ):
                raise ComputationalArtifactError("storage manifest does not describe the component bytes")
            object.__setattr__(self, "storage_manifest", _freeze_json(self.storage_manifest, "storage_manifest"))

    def to_dict(self) -> dict[str, object]:
        """Mathematics: Project the component into detached canonical manifest data."""
        result: dict[str, object] = {
            "path": self.path,
            "size_bytes": self.size_bytes,
            "content_digest": self.content_digest,
            "media_type": self.media_type,
        }
        if self.storage_manifest is not None:
            result["storage_manifest"] = _thaw_json(self.storage_manifest)
        return result

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> ComputationalArtifactComponent:
        """Mathematics: Reconstruct a component while rejecting missing, unknown, and coercible field values."""
        if not isinstance(payload, Mapping) or set(payload) not in (
            {"path", "size_bytes", "content_digest", "media_type"},
            {"path", "size_bytes", "content_digest", "media_type", "storage_manifest"},
        ):
            raise ComputationalArtifactError("artifact component fields are invalid")
        return cls(
            path=payload["path"],
            size_bytes=payload["size_bytes"],
            content_digest=payload["content_digest"],
            media_type=payload["media_type"],
            storage_manifest=payload.get("storage_manifest"),
        )


@dataclass(frozen=True)
class ComputationalArtifactManifest:
    """Mathematics: Immutable composite identity for a typed collection of computational artifact files."""

    artifact_id: str
    artifact_kind: str
    components: tuple[ComputationalArtifactComponent, ...]
    total_size_bytes: int
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: int = _ARTIFACT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        """Mathematics: Enforce canonical component order, unique paths, size consistency, and immutable metadata."""
        _label(self.artifact_id, "artifact_id")
        _label(self.artifact_kind, "artifact_kind")
        _strict_integer(self.total_size_bytes, "total_size_bytes")
        if self.total_size_bytes > _DEFAULT_MAX_ARTIFACT_BYTES:
            raise ComputationalArtifactError("artifact exceeds the supported logical size")
        if type(self.schema_version) is not int or self.schema_version != _ARTIFACT_SCHEMA_VERSION:
            raise ComputationalArtifactError("unsupported computational artifact schema version")
        components = tuple(self.components)
        if not components or any(not isinstance(item, ComputationalArtifactComponent) for item in components):
            raise ComputationalArtifactError("artifact manifest requires typed file components")
        paths = [component.path for component in components]
        if paths != sorted(paths) or len(paths) != len(set(paths)):
            raise ComputationalArtifactError("artifact component paths must be unique and lexicographically ordered")
        if sum(component.size_bytes for component in components) != self.total_size_bytes:
            raise ComputationalArtifactError("artifact total_size_bytes does not match its components")
        if not isinstance(self.metadata, Mapping):
            raise ComputationalArtifactError("artifact metadata must be a JSON object")
        frozen_metadata = _freeze_json(self.metadata, "artifact metadata")
        if not isinstance(frozen_metadata, Mapping):
            raise ComputationalArtifactError("artifact metadata must be a JSON object")
        object.__setattr__(self, "components", components)
        object.__setattr__(self, "metadata", frozen_metadata)

    def _payload_dict(self) -> dict[str, object]:
        """Mathematics: Return the exact canonical identity projection excluding its self-referential digest."""
        return {
            "kind": _ARTIFACT_KIND,
            "schema_version": self.schema_version,
            "artifact_id": self.artifact_id,
            "artifact_kind": self.artifact_kind,
            "total_size_bytes": self.total_size_bytes,
            "components": [component.to_dict() for component in self.components],
            "metadata": _thaw_json(self.metadata),
        }

    @property
    def manifest_digest(self) -> str:
        """Mathematics: Compute the immutable composite artifact identity from its canonical representation."""
        return _digest_bytes(_canonical_bytes(self._payload_dict(), "artifact manifest"))

    def to_dict(self) -> dict[str, object]:
        """Mathematics: Return a portable wire projection with the verified composite manifest digest."""
        return self._payload_dict() | {"manifest_digest": self.manifest_digest}

    def canonical_bytes(self) -> bytes:
        """Mathematics: Return canonical UTF-8 manifest bytes suitable for storage or transport."""
        return _canonical_bytes(self.to_dict(), "artifact manifest")

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> ComputationalArtifactManifest:
        """Mathematics: Decode the exact supported manifest schema and verify its claimed composite digest."""
        expected = {
            "kind", "schema_version", "artifact_id", "artifact_kind",
            "total_size_bytes", "components", "metadata", "manifest_digest",
        }
        if not isinstance(payload, Mapping) or set(payload) != expected:
            raise ComputationalArtifactError("computational artifact manifest fields are invalid")
        if payload["kind"] != _ARTIFACT_KIND:
            raise ComputationalArtifactError("unsupported computational artifact manifest kind")
        if not isinstance(payload["components"], list):
            raise ComputationalArtifactError("artifact components must be a list")
        manifest = cls(
            artifact_id=payload["artifact_id"],
            artifact_kind=payload["artifact_kind"],
            components=tuple(ComputationalArtifactComponent.from_dict(item) for item in payload["components"]),
            total_size_bytes=payload["total_size_bytes"],
            metadata=payload["metadata"],
            schema_version=payload["schema_version"],
        )
        _require_digest(payload["manifest_digest"], "manifest_digest")
        if payload["manifest_digest"] != manifest.manifest_digest:
            raise ComputationalArtifactError("computational artifact manifest digest mismatch")
        return manifest


def admit_computational_artifact_directory(
    directory_path: Path,
    *,
    artifact_id: str,
    artifact_kind: str,
    object_store: ComputationalObjectStore | None = None,
    metadata: Mapping[str, Any] | None = None,
    exclude_paths: Sequence[str] = (),
    max_total_size: int = _DEFAULT_MAX_ARTIFACT_BYTES,
    max_files: int = _DEFAULT_MAX_ARTIFACT_FILES,
) -> ComputationalArtifactManifest:
    """Mathematics: Admit a directory as a canonical composite artifact, optionally paging every component through M1."""
    root = Path(directory_path)
    _strict_integer(max_total_size, "max_total_size", minimum=1)
    _strict_integer(max_files, "max_files", minimum=1)
    if max_total_size > _DEFAULT_MAX_ARTIFACT_BYTES:
        raise ComputationalArtifactError("max_total_size exceeds the supported artifact bound")
    if not isinstance(exclude_paths, (tuple, list)):
        raise ComputationalArtifactError("exclude_paths must be a sequence of relative path prefixes")
    exclusions = tuple(sorted({_artifact_path(item) for item in exclude_paths}))
    files = _artifact_files(root, exclusions)
    if not files:
        raise ComputationalArtifactError("artifact directory contains no admitted regular files")
    if len(files) > max_files:
        raise ComputationalArtifactError("artifact directory contains too many files")

    components: list[ComputationalArtifactComponent] = []
    total_size = 0
    for relative, file_path in files:
        digest, size = _compute_file_digest(file_path)
        total_size += size
        if total_size > max_total_size:
            raise ComputationalArtifactError("artifact directory exceeds max_total_size")
        suffix = file_path.suffix.lower()
        media_type = {
            ".json": "application/json",
            ".toml": "application/toml",
            ".yaml": "application/yaml",
            ".yml": "application/yaml",
            ".xml": "application/xml",
            ".txt": "text/plain",
            ".md": "text/markdown",
            ".safetensors": "application/x-safetensors",
        }.get(suffix, "application/octet-stream")

        storage_manifest: Mapping[str, Any] | None = None
        if object_store is not None:
            try:
                with file_path.open("rb") as stream:
                    stored = object_store.put_stream(stream, size, media_type=media_type)
            except Exception as exc:
                raise ComputationalArtifactError(f"M1 byte-object admission failed for {relative}") from exc
            if stored.size_bytes != size or stored.content_digest != digest or stored.media_type != media_type:
                raise ComputationalArtifactError(f"M1 byte-object identity differs from local file: {relative}")
            storage_manifest = stored.to_dict()

        components.append(
            ComputationalArtifactComponent(
                path=relative,
                size_bytes=size,
                content_digest=digest,
                media_type=media_type,
                storage_manifest=storage_manifest,
            )
        )

    return ComputationalArtifactManifest(
        artifact_id=artifact_id,
        artifact_kind=artifact_kind,
        components=tuple(components),
        total_size_bytes=total_size,
        metadata=metadata or {},
    )


def verify_computational_artifact_directory(
    manifest: ComputationalArtifactManifest,
    directory_path: Path,
    *,
    object_store: ComputationalObjectStore | None = None,
    verify_storage: bool = False,
    exclude_paths: Sequence[str] = (),
    strict_inventory: bool = True,
) -> bool:
    """Mathematics: Recompute component bytes and optionally every referenced M1 page before local backend loading."""
    if not isinstance(manifest, ComputationalArtifactManifest):
        raise TypeError("manifest must be a ComputationalArtifactManifest")
    if not isinstance(strict_inventory, bool) or not isinstance(verify_storage, bool):
        raise TypeError("verification flags must be Boolean")
    exclusions = tuple(sorted({_artifact_path(item) for item in exclude_paths}))
    files = _artifact_files(Path(directory_path), exclusions)
    by_path = {relative: path for relative, path in files}
    expected_paths = {component.path for component in manifest.components}
    if strict_inventory and set(by_path) != expected_paths:
        return False

    for component in manifest.components:
        file_path = by_path.get(component.path)
        if file_path is None:
            return False
        digest, size = _compute_file_digest(file_path)
        if digest != component.content_digest or size != component.size_bytes:
            return False
        if verify_storage:
            if object_store is None or component.storage_manifest is None:
                raise ComputationalArtifactError("storage verification requires M1 descriptors and an object store")
            descriptor = ComputationalObjectManifest.from_dict(_thaw_json(component.storage_manifest))
            if not object_store.verify(descriptor):
                return False
    return True


@dataclass(frozen=True)
class ComputationalBackendProfile:
    """Mathematics: Declared backend implementation, runtime, device, substrate, and resource identity."""

    backend_id: str
    implementation_id: str
    implementation_digest: str
    device: str = "cpu"
    substrates: tuple[str, ...] = ("cpu",)
    runtime_versions: Mapping[str, str] = field(default_factory=dict)
    configuration: Mapping[str, Any] = field(default_factory=dict)
    max_input_bytes: int = 1_000_000
    max_output_bytes: int = 2_000_000

    def __post_init__(self) -> None:
        """Mathematics: Validate stable backend identity, explicit implementation digest, resource bounds, and finite profile data."""
        _label(self.backend_id, "backend_id")
        _label(self.implementation_id, "implementation_id")
        _require_digest(self.implementation_digest, "implementation_digest")
        if not isinstance(self.device, str) or not self.device.strip() or len(self.device) > 128:
            raise ComputationalBackendError("device must be non-empty bounded text")
        if not isinstance(self.substrates, (tuple, list)):
            raise ComputationalBackendError("substrates must be a sequence")
        substrates = tuple(self.substrates)
        if not substrates or any(item not in _SUBSTRATES for item in substrates) or len(set(substrates)) != len(substrates):
            raise ComputationalBackendError("substrates must be unique supported E-CPU substrate names")
        if not isinstance(self.runtime_versions, Mapping) or any(
            not isinstance(key, str) or not key or not isinstance(value, str) or not value
            for key, value in self.runtime_versions.items()
        ):
            raise ComputationalBackendError("runtime_versions must map non-empty names to version strings")
        if not isinstance(self.configuration, Mapping):
            raise ComputationalBackendError("configuration must be a JSON object")
        _strict_integer(self.max_input_bytes, "max_input_bytes", minimum=1)
        _strict_integer(self.max_output_bytes, "max_output_bytes", minimum=1)
        object.__setattr__(self, "substrates", substrates)
        object.__setattr__(self, "runtime_versions", _freeze_json(self.runtime_versions, "runtime_versions"))
        object.__setattr__(self, "configuration", _freeze_json(self.configuration, "configuration"))

    def to_dict(self) -> dict[str, object]:
        """Mathematics: Project the declared backend profile into deterministic fingerprint input."""
        return {
            "schema": "mailcpu.computational-backend-profile.v1",
            "backend_id": self.backend_id,
            "implementation_id": self.implementation_id,
            "implementation_digest": self.implementation_digest,
            "device": self.device,
            "substrates": list(self.substrates),
            "runtime_versions": _thaw_json(self.runtime_versions),
            "configuration": _thaw_json(self.configuration),
            "max_input_bytes": self.max_input_bytes,
            "max_output_bytes": self.max_output_bytes,
        }

    @property
    def fingerprint(self) -> str:
        """Mathematics: Bind the explicitly declared backend implementation and profile into one SHA-256 identity."""
        return _digest_bytes(_canonical_bytes(self.to_dict(), "backend profile"))


@dataclass(frozen=True)
class ComputationalHostRequest:
    """Mathematics: Typed local operation request pinned to an immutable artifact and workload time coordinate."""

    request_id: str
    artifact_manifest_digest: str
    operation: str
    input_value: Any
    logical_time: int
    workload_id: str = "local"

    def __post_init__(self) -> None:
        """Mathematics: Validate the request identity and freeze its finite JSON input."""
        _label(self.request_id, "request_id")
        _require_digest(self.artifact_manifest_digest, "artifact_manifest_digest")
        _label(self.operation, "operation")
        _label(self.workload_id, "workload_id")
        _strict_integer(self.logical_time, "logical_time")
        object.__setattr__(self, "input_value", _freeze_json(self.input_value, "request input"))

    @property
    def input_digest(self) -> str:
        """Mathematics: Digest the operation, input value, workload identity, and logical-time coordinate."""
        return _digest_bytes(
            _canonical_bytes(
                {
                    "operation": self.operation,
                    "input_value": self.input_value,
                    "workload_id": self.workload_id,
                    "logical_time": self.logical_time,
                },
                "host request",
            )
        )


@dataclass(frozen=True)
class ComputationalHostReceipt:
    """Mathematics: Deterministic digest receipt binding artifact, backend, request, and output identities."""

    receipt_digest: str
    host_id: str
    artifact_manifest_digest: str
    backend_fingerprint: str
    request_id: str
    workload_id: str
    logical_time: int
    input_digest: str
    output_digest: str
    output_size_bytes: int
    status: str = "EXECUTED"

    def __post_init__(self) -> None:
        """Mathematics: Validate receipt identities and ensure its status does not imply durable commit or signature."""
        _require_digest(self.receipt_digest, "receipt_digest")
        _label(self.host_id, "host_id")
        _require_digest(self.artifact_manifest_digest, "artifact_manifest_digest")
        _require_digest(self.backend_fingerprint, "backend_fingerprint")
        _label(self.request_id, "request_id")
        _label(self.workload_id, "workload_id")
        _strict_integer(self.logical_time, "logical_time")
        _require_digest(self.input_digest, "input_digest")
        _require_digest(self.output_digest, "output_digest")
        _strict_integer(self.output_size_bytes, "output_size_bytes")
        if self.status != "EXECUTED":
            raise ComputationalBackendError("host receipt status must be EXECUTED")

    def _payload_dict(self) -> dict[str, object]:
        """Mathematics: Return the receipt identity projection without its self-referential digest."""
        return {
            "kind": _HOST_RECEIPT_KIND,
            "schema_version": _HOST_RECEIPT_SCHEMA_VERSION,
            "host_id": self.host_id,
            "artifact_manifest_digest": self.artifact_manifest_digest,
            "backend_fingerprint": self.backend_fingerprint,
            "request_id": self.request_id,
            "workload_id": self.workload_id,
            "logical_time": self.logical_time,
            "input_digest": self.input_digest,
            "output_digest": self.output_digest,
            "output_size_bytes": self.output_size_bytes,
            "status": self.status,
        }

    def to_dict(self) -> dict[str, object]:
        """Mathematics: Return the portable receipt projection with its deterministic digest."""
        return self._payload_dict() | {"receipt_digest": self.receipt_digest}

    @classmethod
    def create(
        cls,
        *,
        host_id: str,
        artifact_manifest_digest: str,
        backend_fingerprint: str,
        request_id: str,
        workload_id: str,
        logical_time: int,
        input_digest: str,
        output_digest: str,
        output_size_bytes: int,
    ) -> ComputationalHostReceipt:
        """Mathematics: Construct a receipt whose digest is exactly the canonical hash of its evidence fields."""
        values = {
            "host_id": host_id,
            "artifact_manifest_digest": artifact_manifest_digest,
            "backend_fingerprint": backend_fingerprint,
            "request_id": request_id,
            "workload_id": workload_id,
            "logical_time": logical_time,
            "input_digest": input_digest,
            "output_digest": output_digest,
            "output_size_bytes": output_size_bytes,
            "status": "EXECUTED",
        }
        body = {
            "kind": _HOST_RECEIPT_KIND,
            "schema_version": _HOST_RECEIPT_SCHEMA_VERSION,
            **values,
        }
        receipt_digest = _digest_bytes(_canonical_bytes(body, "host receipt"))
        return cls(receipt_digest=receipt_digest, **values)


@dataclass(frozen=True)
class ComputationalHostExecution:
    """Mathematics: Separate deterministic output evidence from a local monotonic performance observation."""

    output_json: str
    receipt: ComputationalHostReceipt
    elapsed_ns: int

    def __post_init__(self) -> None:
        """Mathematics: Verify canonical output JSON and non-negative local execution duration."""
        _strict_integer(self.elapsed_ns, "elapsed_ns")
        try:
            value = json.loads(self.output_json)
            if _canonical_bytes(value, "execution output").decode("utf-8") != self.output_json:
                raise ComputationalBackendError("execution output is not in canonical JSON form")
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ComputationalBackendError("execution output JSON is invalid") from exc
        if not isinstance(self.receipt, ComputationalHostReceipt):
            raise TypeError("receipt must be a ComputationalHostReceipt")

    @property
    def output(self) -> Any:
        """Mathematics: Return a detached JSON output value without exposing stored receipt state."""
        return json.loads(self.output_json)


class ComputationalBackendAdapter(Protocol):
    """Mathematics: Local trusted adapter contract for loading and executing an admitted artifact."""

    def load(
        self,
        manifest: ComputationalArtifactManifest,
        artifact_root: Path,
        profile: ComputationalBackendProfile,
    ) -> None:
        """Mathematics: Materialize or initialize this artifact under the declared local backend profile."""
        ...

    def execute(self, request: ComputationalHostRequest) -> Any:
        """Mathematics: Evaluate one typed operation and return a finite JSON-compatible result."""
        ...

    def unload(self) -> None:
        """Mathematics: Release adapter-owned execution resources."""
        ...


class LocalComputationalHost:
    """Mathematics: Local host H that admits an immutable artifact and interprets requests through one trusted adapter."""

    def __init__(
        self,
        *,
        host_id: str,
        manifest: ComputationalArtifactManifest,
        artifact_root: Path,
        profile: ComputationalBackendProfile,
        adapter: ComputationalBackendAdapter,
        object_store: ComputationalObjectStore | None = None,
    ) -> None:
        """Mathematics: Bind host identity to a verified artifact, backend fingerprint, local byte root, and adapter."""
        self.host_id = _label(host_id, "host_id")
        if not isinstance(manifest, ComputationalArtifactManifest):
            raise TypeError("manifest must be a ComputationalArtifactManifest")
        if not isinstance(profile, ComputationalBackendProfile):
            raise TypeError("profile must be a ComputationalBackendProfile")
        root = Path(artifact_root)
        if root.is_symlink() or not root.is_dir():
            raise ComputationalArtifactError("artifact_root must be an existing non-symlink directory")
        for method in ("load", "execute", "unload"):
            if not callable(getattr(adapter, method, None)):
                raise TypeError(f"backend adapter must implement {method}()")
        self.manifest = manifest
        self.artifact_root = root
        self.profile = profile
        self.adapter = adapter
        self.object_store = object_store
        self._loaded = False
        self._lock = threading.RLock()

    @property
    def is_loaded(self) -> bool:
        """Mathematics: Observe whether adapter resources are currently resident in this logical host."""
        with self._lock:
            return self._loaded

    @property
    def implementation_fingerprint(self) -> str:
        """Mathematics: Expose the backend profile identity separately from artifact identity."""
        return self.profile.fingerprint

    def load(self) -> None:
        """Mathematics: Transition from UNLOADED to LOADED only after bytes are reverified and adapter initialization succeeds."""
        with self._lock:
            if self._loaded:
                return
            if not verify_computational_artifact_directory(
                self.manifest,
                self.artifact_root,
                object_store=self.object_store,
                verify_storage=False,
                strict_inventory=True,
            ):
                raise ComputationalArtifactError("local artifact bytes differ from the admitted manifest")
            try:
                self.adapter.load(self.manifest, self.artifact_root, self.profile)
            except Exception as exc:
                raise ComputationalBackendError("backend adapter failed to load the admitted artifact") from exc
            self._loaded = True

    def unload(self) -> None:
        """Mathematics: Transition from LOADED to UNLOADED and release adapter-owned resources."""
        with self._lock:
            if not self._loaded:
                return
            try:
                self.adapter.unload()
            except Exception as exc:
                raise ComputationalBackendError("backend adapter failed to unload") from exc
            finally:
                self._loaded = False

    def execute(self, request: ComputationalHostRequest) -> ComputationalHostExecution:
        """Mathematics: Evaluate one bounded deterministic request and bind its output to the admitted artifact and backend."""
        if not isinstance(request, ComputationalHostRequest):
            raise TypeError("request must be a ComputationalHostRequest")
        if request.artifact_manifest_digest != self.manifest.manifest_digest:
            raise ComputationalBackendError("request artifact identity differs from the locally admitted artifact")
        input_bytes = _canonical_bytes(
            {
                "operation": request.operation,
                "input_value": request.input_value,
                "workload_id": request.workload_id,
                "logical_time": request.logical_time,
            },
            "host request",
        )
        if len(input_bytes) > self.profile.max_input_bytes:
            raise ComputationalBackendError("request exceeds the backend max_input_bytes bound")

        with self._lock:
            if not self._loaded:
                self.load()
            started = time.perf_counter_ns()
            try:
                raw_output = self.adapter.execute(request)
                output_bytes = _canonical_bytes(raw_output, "backend output")
            except Exception as exc:
                if isinstance(exc, ComputationalBackendError):
                    raise
                raise ComputationalBackendError("backend adapter execution failed or returned a non-JSON value") from exc
            elapsed_ns = time.perf_counter_ns() - started

        if len(output_bytes) > self.profile.max_output_bytes:
            raise ComputationalBackendError("backend output exceeds max_output_bytes")
        output_digest = _digest_bytes(output_bytes)
        receipt = ComputationalHostReceipt.create(
            host_id=self.host_id,
            artifact_manifest_digest=self.manifest.manifest_digest,
            backend_fingerprint=self.profile.fingerprint,
            request_id=request.request_id,
            workload_id=request.workload_id,
            logical_time=request.logical_time,
            input_digest=request.input_digest,
            output_digest=output_digest,
            output_size_bytes=len(output_bytes),
        )
        return ComputationalHostExecution(
            output_json=output_bytes.decode("utf-8"),
            receipt=receipt,
            elapsed_ns=elapsed_ns,
        )


def make_computational_host_operator(
    host: LocalComputationalHost,
    *,
    operator_id: str,
    version: int = 1,
    description: str = "Execute a typed operation through a locally admitted computational artifact",
    required_rights: frozenset[str] = frozenset({"compute"}),
    base_energy: int = 32,
    energy_per_byte: int = 1,
) -> tuple[OperatorSpec, Callable[[Any, VirtualLayerWorkload], Any]]:
    """Mathematics: Adapt one local host into a versioned pure Virtual Layer operator with receiver-local implementation binding."""
    if not isinstance(host, LocalComputationalHost):
        raise TypeError("host must be a LocalComputationalHost")
    _label(operator_id, "operator_id")
    spec = OperatorSpec(
        operator_id=operator_id,
        version=version,
        description=description,
        input_kind="object",
        output_kind="object",
        substrates=host.profile.substrates,
        required_rights=required_rights,
        base_energy=base_energy,
        energy_per_byte=energy_per_byte,
        max_input_bytes=host.profile.max_input_bytes,
        max_output_bytes=host.profile.max_output_bytes,
        deterministic=True,
        effect_mode="pure",
    )

    def handle(input_value: Any, workload: VirtualLayerWorkload) -> dict[str, object]:
        """Mathematics: Convert a finite workload object into a typed host request and return deterministic output evidence."""
        if not isinstance(input_value, Mapping) or set(input_value) not in (
            {"operation", "input"},
            {"operation", "input", "request_id"},
        ):
            raise VirtualLayerError("computational host input fields must be operation, input, and optional request_id")
        request_id = input_value.get("request_id", workload.workload_id)
        request = ComputationalHostRequest(
            request_id=request_id,
            artifact_manifest_digest=host.manifest.manifest_digest,
            operation=input_value["operation"],
            input_value=input_value["input"],
            logical_time=workload.logical_time,
            workload_id=workload.workload_id,
        )
        execution = host.execute(request)
        return {"receipt": execution.receipt.to_dict(), "output": execution.output}

    return spec, handle


def register_computational_host_operator(
    registry: OperatorRegistry,
    host: LocalComputationalHost,
    *,
    operator_id: str,
    version: int = 1,
    description: str = "Execute a typed operation through a locally admitted computational artifact",
) -> OperatorSpec:
    """Mathematics: Register the host adapter's exact versioned operator contract and trusted local handler."""
    if not isinstance(registry, OperatorRegistry):
        raise TypeError("registry must be an OperatorRegistry")
    spec, handler = make_computational_host_operator(
        host,
        operator_id=operator_id,
        version=version,
        description=description,
    )
    registry.register(spec, handler)
    return spec


class TransitComputationalHost(TransitComputeHost):
    """Mathematics: Bind a local computational host to receiver-owned Hypervisor and Virtual Layer execution."""

    operation_name = VIRTUAL_LAYER_OPERATOR_OPERATION

    def __init__(
        self,
        operating_system: Any,
        authority_pid: int,
        host: LocalComputationalHost,
        *,
        operator_id: str,
        version: int = 1,
        node_id: str = "node-computational-host",
    ) -> None:
        """Mathematics: Bind the local artifact adapter to one receiver process, exact operator resource, and substrate set."""
        super().__init__()
        if not callable(getattr(operating_system, "hypervisor_authorize_event", None)):
            raise TypeError("TransitComputationalHost requires a HeadlessOS-compatible receiver")
        if not isinstance(authority_pid, int) or isinstance(authority_pid, bool):
            raise TypeError("authority_pid must be an integer")
        operating_system.environment.kernel._process(authority_pid)
        if not isinstance(host, LocalComputationalHost):
            raise TypeError("host must be a LocalComputationalHost")
        self.operating_system = operating_system
        self.authority_pid = authority_pid
        self.host = host
        self.operator_id = _label(operator_id, "operator_id")
        self.version = _strict_integer(version, "version", minimum=1)
        self.node_id = _label(node_id, "node_id")
        self.resource_name = virtual_layer_operator_resource(self.operator_id, self.version)
        self.registry = OperatorRegistry()
        spec, handler = make_computational_host_operator(
            host,
            operator_id=self.operator_id,
            version=self.version,
        )
        self.registry.register(spec, handler)
        self.runtime = VirtualLayerRuntime(
            self.registry,
            self.node_id,
            frozenset(host.profile.substrates),
        )

    @property
    def implementation_fingerprint(self) -> str:
        """Mathematics: Return the explicit local backend profile fingerprint, not the artifact identity or a signature."""
        return self.host.implementation_fingerprint

    def handle(self, event: HypervisorArbitrationEvent) -> dict[str, object]:
        """Mathematics: Execute a matching authorized transit event through the receiver-local Virtual Layer runtime."""
        if not isinstance(event, HypervisorArbitrationEvent):
            raise TypeError("TransitComputationalHost requires a HypervisorArbitrationEvent")
        if (
            event.request.operation != self.operation_name
            or event.request.resource != self.resource_name
            or event.request.destructive
        ):
            raise ComputationalBackendError("transit event does not match the registered computational host operator")
        effect = self.runtime.execute_authorized_event(
            self.operating_system,
            self.authority_pid,
            event,
        )
        bound_effect = dict(effect)
        bound_effect["backend_implementation_fingerprint"] = self.implementation_fingerprint
        bound_effect["artifact_manifest_digest"] = self.host.manifest.manifest_digest
        return bound_effect


def build_computational_host_event(
    workload: VirtualLayerWorkload,
    source: str,
    channel: str,
    sequence: int,
    logical_time: int,
    runtime: VirtualLayerRuntime,
    operator_id: str,
) -> HypervisorArbitrationEvent:
    """Mathematics: Construct a typed Virtual Layer event for one version-pinned local computational host operator."""
    return runtime.build_event(
        source,
        channel,
        sequence,
        logical_time,
        workload,
        operator_id,
    )
