"""Deterministic procedural file providers inspired by the GV VFS reference."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping

from .vl_procedural_primitives import feistel_stream_byte


class ProviderKind(str, Enum):
    """Finite provider families available to procedural inodes."""

    ZERO = "zero"
    ENTROPY = "entropy"
    FEISTEL = "feistel"
    PROC_TEXT = "proc_text"


@dataclass(frozen=True)
class ProceduralProvider:
    """A bounded, read-only function from `(offset, count)` to deterministic bytes."""

    kind: ProviderKind
    size: int
    seed: int = 0
    text: str = ""
    tau: int = 0xB16B00B5CAFE

    def __post_init__(self) -> None:
        """Mathematics: enforce `0≤offset,count`, `size≥0`, and 64-bit procedural seed/salt domains."""

        if self.size < 0:
            raise ValueError("provider size must be non-negative")
        if not 0 <= self.seed < 2**64 or not 0 <= self.tau < 2**64:
            raise ValueError("provider seed and tau must be unsigned 64-bit values")

    def read(self, offset: int, count: int) -> bytes:
        """Mathematics: return bounded slice `P[offset : min(offset + count, size)]` from the provider function `P`."""

        if offset < 0 or count < 0:
            raise ValueError("offset and count must be non-negative")
        if offset >= self.size or count == 0:
            return b""
        length = min(count, self.size - offset)
        if self.kind is ProviderKind.ZERO:
            return bytes(length)
        if self.kind is ProviderKind.PROC_TEXT:
            return self.text.encode("utf-8")[offset : offset + length]
        if self.kind is ProviderKind.FEISTEL:
            return bytes(feistel_stream_byte(offset + index, self.tau, self.seed) for index in range(length))
        data = bytearray(length)
        domain = self.kind.value.encode("ascii")
        for index in range(length):
            position = offset + index
            block = position // 32
            lane = position % 32
            digest = hashlib.sha256(
                domain + self.seed.to_bytes(16, "little", signed=False) + block.to_bytes(8, "little")
            ).digest()
            data[index] = digest[lane]
        return bytes(data)

    def snapshot(self) -> dict[str, Any]:
        """Mathematics: serialize provider identity `P = (kind, size, seed, text)` without materializing its bytes."""

        return {
            "kind": self.kind.value,
            "size": self.size,
            "seed": self.seed,
            "text": self.text,
            "tau": self.tau,
        }


def _provider_canonical_json(value: Any) -> str:
    """Mathematics: encode a finite JSON value in one stable sorted representation."""
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _provider_freeze_json(value: Any) -> Any:
    """Mathematics: recursively detach and freeze JSON mappings and sequences."""
    if isinstance(value, Mapping):
        return _FrozenProviderDict({key: _provider_freeze_json(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_provider_freeze_json(item) for item in value)
    return value


class _FrozenProviderDict(dict):
    """A JSON-serializable mapping that refuses mutation after address construction."""

    def _immutable(self, *args: Any, **kwargs: Any) -> None:
        """Mathematics: make every mapping update operation undefined after freezing."""
        raise TypeError("structural-memory file references are immutable")

    __setitem__ = _immutable
    __delitem__ = _immutable
    clear = _immutable
    pop = _immutable
    popitem = _immutable
    setdefault = _immutable
    update = _immutable
    __ior__ = _immutable


@dataclass(frozen=True)
class StructuralMemoryFileRef:
    """Immutable address of a bounded byte file generated from one admitted integer orbit."""

    memory_id: str
    revision: int
    context: Mapping[str, Any]
    coordinate_start: int
    size: int
    spec_digest: str
    certificate_digest: str

    def __post_init__(self) -> None:
        """Mathematics: validate one revision-pinned mapping from byte offset to generator coordinate."""
        if not isinstance(self.memory_id, str) or not self.memory_id.strip() or len(self.memory_id) > 256:
            raise ValueError("memory_id must be a non-empty string of at most 256 characters")
        for name, value, minimum in (
            ("revision", self.revision, 1),
            ("coordinate_start", self.coordinate_start, 0),
            ("size", self.size, 1),
        ):
            if type(value) is not int or value < minimum:
                raise ValueError(f"{name} must be an integer greater than or equal to {minimum}")
        if self.size > 1_048_576:
            raise ValueError("structural-memory file size exceeds the 1 MiB provider bound")
        if not isinstance(self.context, Mapping):
            raise ValueError("structural-memory file context must be an object")
        try:
            context = json.loads(_provider_canonical_json(dict(self.context)))
        except (TypeError, ValueError) as exc:
            raise ValueError("structural-memory file context must be finite canonical JSON") from exc
        if not isinstance(context, dict):
            raise ValueError("structural-memory file context must be an object")
        object.__setattr__(self, "context", _provider_freeze_json(context))
        for name, digest in (
            ("spec_digest", self.spec_digest),
            ("certificate_digest", self.certificate_digest),
        ):
            if (
                not isinstance(digest, str)
                or len(digest) != 64
                or any(character not in "0123456789abcdef" for character in digest)
            ):
                raise ValueError(f"{name} must be a lowercase SHA-256 digest")

    def to_dict(self) -> dict[str, Any]:
        """Mathematics: serialize the complete immutable file address without generator code."""
        return {
            "memory_id": self.memory_id,
            "revision": self.revision,
            "context": json.loads(_provider_canonical_json(dict(self.context))),
            "coordinate_start": self.coordinate_start,
            "size": self.size,
            "spec_digest": self.spec_digest,
            "certificate_digest": self.certificate_digest,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "StructuralMemoryFileRef":
        """Mathematics: reconstruct and validate the exact revision-pinned file address."""
        expected = {
            "memory_id", "revision", "context", "coordinate_start",
            "size", "spec_digest", "certificate_digest",
        }
        if not isinstance(payload, Mapping) or set(payload) != expected:
            raise ValueError("structural-memory file reference fields are invalid")
        return cls(
            payload["memory_id"],
            payload["revision"],
            payload["context"],
            payload["coordinate_start"],
            payload["size"],
            payload["spec_digest"],
            payload["certificate_digest"],
        )

    @classmethod
    def from_version(
        cls,
        version: Any,
        coordinate_start: int,
        size: int,
    ) -> "StructuralMemoryFileRef":
        """Mathematics: pin the file to one admitted immutable version and its certificate."""
        spec = getattr(version, "spec", None)
        certificate = getattr(version, "certificate", None)
        if spec is None or certificate is None:
            raise ValueError("structural-memory file reference requires an admitted version")
        return cls(
            spec.memory_id,
            spec.revision,
            spec.context,
            coordinate_start,
            size,
            spec.digest,
            certificate.digest,
        )


@dataclass(frozen=True)
class StructuralMemoryFileReadReceipt:
    """Evidence summary binding one returned file slice to its coordinate-level read receipts."""

    receipt_id: str
    memory_id: str
    revision: int
    offset: int
    length: int
    coordinate_start: int
    content_digest: str
    value_receipt_ids: tuple[str, ...]
    cache_hit_count: int

    def __post_init__(self) -> None:
        """Mathematics: validate the range receipt identity and all content/lineage digests."""
        for name, digest in (
            ("receipt_id", self.receipt_id),
            ("content_digest", self.content_digest),
        ):
            if (
                not isinstance(digest, str)
                or len(digest) != 64
                or any(character not in "0123456789abcdef" for character in digest)
            ):
                raise ValueError(f"{name} must be a lowercase SHA-256 digest")
        if not isinstance(self.memory_id, str) or not self.memory_id:
            raise ValueError("memory_id must be non-empty")
        for name, value in (
            ("revision", self.revision),
            ("offset", self.offset),
            ("length", self.length),
            ("coordinate_start", self.coordinate_start),
            ("cache_hit_count", self.cache_hit_count),
        ):
            if type(value) is not int or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if self.revision < 1:
            raise ValueError("revision must be positive")
        if len(self.value_receipt_ids) != self.length:
            raise ValueError("one structural read receipt is required for every returned byte")

    def to_dict(self) -> dict[str, Any]:
        """Mathematics: serialize the aggregate byte-range receipt and its ordered value receipts."""
        return {
            "kind": "structural_memory.file_read",
            "schema_version": 1,
            "receipt_id": self.receipt_id,
            "memory_id": self.memory_id,
            "revision": self.revision,
            "offset": self.offset,
            "length": self.length,
            "coordinate_start": self.coordinate_start,
            "content_digest": self.content_digest,
            "value_receipt_ids": list(self.value_receipt_ids),
            "cache_hit_count": self.cache_hit_count,
        }


class StructuralMemoryFileProvider:
    """Read-only, bounded VFS byte provider backed by one locally admitted structural-memory revision."""

    SNAPSHOT_KIND = "structural_memory_file"
    SNAPSHOT_VERSION = 1

    def __init__(
        self,
        reference: StructuralMemoryFileRef,
        registry: Any | None = None,
        max_read_bytes: int = 4096,
    ) -> None:
        """Mathematics: bind a bounded file interval to a pinned reference and optional local registry."""
        if not isinstance(reference, StructuralMemoryFileRef):
            raise ValueError("provider requires a StructuralMemoryFileRef")
        if type(max_read_bytes) is not int or not 1 <= max_read_bytes <= 65_536:
            raise ValueError("max_read_bytes must be an integer in [1, 65536]")
        self.reference = reference
        self.size = reference.size
        self.max_read_bytes = max_read_bytes
        self._registry = None
        self._value_cache: dict[int, tuple[int, str, bool]] = {}
        if registry is not None:
            self.bind_registry(registry)

    def bind_registry(self, registry: Any) -> None:
        """Mathematics: attach a trusted local registry without changing the serialized reference."""
        if not callable(getattr(registry, "read_revision", None)):
            raise ValueError("provider binding requires a structural-memory read_revision interface")
        self._registry = registry

    def read_with_receipt(
        self,
        offset: int,
        count: int,
    ) -> tuple[bytes, StructuralMemoryFileReadReceipt]:
        """Mathematics: map bounded byte interval [o,o+n) to pinned generator coordinates and verify every read."""
        if type(offset) is not int or offset < 0 or type(count) is not int or count < 0:
            raise ValueError("offset and count must be non-negative integers")
        if offset >= self.size or count == 0:
            content = b""
            receipt_ids: tuple[str, ...] = ()
            cache_hits = 0
        else:
            length = min(count, self.size - offset)
            if length > self.max_read_bytes:
                raise ValueError("structural-memory file read exceeds max_read_bytes")
            if self._registry is None:
                raise RuntimeError("structural-memory file provider has not been rebound to a local registry")
            values: list[int] = []
            ids: list[str] = []
            cache_hits = 0
            for relative in range(offset, offset + length):
                coordinate = self.reference.coordinate_start + relative
                cached = self._value_cache.get(coordinate)
                if cached is not None:
                    value, receipt_id, was_cache_hit = cached
                    cache_hits += 1
                else:
                    try:
                        receipt = self._registry.read_revision(
                            self.reference.memory_id,
                            self.reference.revision,
                            coordinate,
                            context=dict(self.reference.context),
                        )
                    except Exception as exc:
                        raise ValueError(f"structural-memory coordinate {coordinate} could not be read: {exc}") from exc
                    expected_context_digest = hashlib.sha256(
                        _provider_canonical_json(dict(self.reference.context)).encode("utf-8")
                    ).hexdigest()
                    if (
                        receipt.memory_id != self.reference.memory_id
                        or receipt.revision != self.reference.revision
                        or receipt.coordinate != coordinate
                        or receipt.spec_digest != self.reference.spec_digest
                        or receipt.certificate_digest != self.reference.certificate_digest
                        or receipt.context_digest != expected_context_digest
                        or type(receipt.value) is not int
                        or not 0 <= receipt.value <= 255
                    ):
                        raise ValueError("structural-memory read receipt does not match the pinned byte-file reference")
                    value = receipt.value
                    receipt_id = receipt.receipt_id
                    was_cache_hit = bool(receipt.cache_hit)
                    self._value_cache[coordinate] = (value, receipt_id, was_cache_hit)
                    if was_cache_hit:
                        cache_hits += 1
                values.append(value)
                ids.append(receipt_id)
            content = bytes(values)
            receipt_ids = tuple(ids)

        content_digest = hashlib.sha256(content).hexdigest()
        receipt_payload = {
            "memory_id": self.reference.memory_id,
            "revision": self.reference.revision,
            "spec_digest": self.reference.spec_digest,
            "certificate_digest": self.reference.certificate_digest,
            "offset": offset,
            "length": len(content),
            "coordinate_start": self.reference.coordinate_start + offset,
            "content_digest": content_digest,
            "value_receipt_ids": list(receipt_ids),
        }
        receipt_id = hashlib.sha256(_provider_canonical_json(receipt_payload).encode("utf-8")).hexdigest()
        return content, StructuralMemoryFileReadReceipt(
            receipt_id=receipt_id,
            memory_id=self.reference.memory_id,
            revision=self.reference.revision,
            offset=offset,
            length=len(content),
            coordinate_start=self.reference.coordinate_start + offset,
            content_digest=content_digest,
            value_receipt_ids=receipt_ids,
            cache_hit_count=cache_hits,
        )

    def read(self, offset: int, count: int) -> bytes:
        """Mathematics: project the evidence-bearing range read to its byte content for the VFS provider protocol."""
        return self.read_with_receipt(offset, count)[0]

    def snapshot(self) -> dict[str, Any]:
        """Mathematics: serialize only the provider address; never serialize the registry or executable callbacks."""
        return {
            "provider_type": self.SNAPSHOT_KIND,
            "schema_version": self.SNAPSHOT_VERSION,
            "reference": self.reference.to_dict(),
            "max_read_bytes": self.max_read_bytes,
        }

    @classmethod
    def from_snapshot(cls, payload: Mapping[str, Any]) -> "StructuralMemoryFileProvider":
        """Mathematics: restore an inert provider descriptor that requires trusted host registry rebinding."""
        if (
            not isinstance(payload, Mapping)
            or payload.get("provider_type") != cls.SNAPSHOT_KIND
            or payload.get("schema_version") != cls.SNAPSHOT_VERSION
        ):
            raise ValueError("unsupported structural-memory file provider snapshot")
        return cls(
            StructuralMemoryFileRef.from_dict(payload.get("reference", {})),
            registry=None,
            max_read_bytes=payload.get("max_read_bytes", 4096),
        )


class ProviderRegistry:
    """Named provider map shared by procedural filesystem inodes."""

    def __init__(self) -> None:
        """Mathematics: initialize partial provider function `P : key ⇀ ProceduralProvider` as empty."""

        self._providers: dict[str, Any] = {}

    def register(self, key: str, provider: Any) -> None:
        """Mathematics: extend P only for a unique provider exposing bounded size, read, and snapshot interfaces."""
        if not key or key in self._providers:
            raise ValueError(f"provider key unavailable: {key}")
        if (
            type(getattr(provider, "size", None)) is not int
            or provider.size < 0
            or not callable(getattr(provider, "read", None))
            or not callable(getattr(provider, "snapshot", None))
        ):
            raise ValueError("provider must expose a non-negative size, read(), and snapshot()")
        self._providers[key] = provider

    def get(self, key: str) -> Any:
        """Mathematics: perform partial lookup `P[key]`, failing on an unregistered provider."""

        try:
            return self._providers[key]
        except KeyError as exc:
            raise KeyError(f"unknown provider: {key}") from exc

    def snapshot(self) -> dict[str, dict[str, Any]]:
        """Mathematics: expose the finite provider graph `dom(P)` and its symbolic specifications."""

        return {key: provider.snapshot() for key, provider in sorted(self._providers.items())}

    @classmethod
    def from_snapshot(cls, payload: dict[str, dict[str, Any]]) -> "ProviderRegistry":
        """Mathematics: reconstruct symbolic provider descriptors, leaving host-bound services inert."""
        registry = cls()
        for key, specification in sorted(payload.items()):
            if not isinstance(specification, dict):
                raise ValueError("provider snapshot entry must be an object")
            if specification.get("provider_type") == StructuralMemoryFileProvider.SNAPSHOT_KIND:
                provider = StructuralMemoryFileProvider.from_snapshot(specification)
            elif "provider_type" not in specification:
                provider = ProceduralProvider(
                    ProviderKind(specification["kind"]),
                    int(specification["size"]),
                    int(specification.get("seed", 0)),
                    str(specification.get("text", "")),
                    int(specification.get("tau", 0xB16B00B5CAFE)),
                )
            else:
                raise ValueError("unsupported provider snapshot kind")
            registry.register(key, provider)
        return registry

    def bind_structural_memory_registry(self, registry: Any) -> None:
        """Mathematics: rebind every symbolic structural provider to the restored host-local registry."""
        for provider in self._providers.values():
            if isinstance(provider, StructuralMemoryFileProvider):
                provider.bind_registry(registry)

    def structural_memory_providers(self) -> tuple[StructuralMemoryFileProvider, ...]:
        """Mathematics: project all structural-memory providers in deterministic registry-key order."""
        return tuple(
            self._providers[key]
            for key in sorted(self._providers)
            if isinstance(self._providers[key], StructuralMemoryFileProvider)
        )
