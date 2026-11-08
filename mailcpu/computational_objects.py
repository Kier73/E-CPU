"""Content-addressed computational objects over MailCPU page backings.

A computational object separates immutable byte identity from the mutable
communication, placement, and execution state that makes those bytes usable.
The store composes the existing PageBacking contract; it does not introduce a
second transport or memory authority.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
from dataclasses import dataclass
from typing import Any, BinaryIO, Mapping

_COMPUTATIONAL_OBJECT_KIND = "mailcpu.computational-object"
_SCHEMA_VERSION = 1
_DEFAULT_CHUNK_SIZE = 4096
_MAX_CHUNK_SIZE = 65_536
_MAX_OBJECT_BYTES = 1 << 40
_MAX_CHUNKS = 1_000_000
_HEX_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_MEDIA_TYPE = re.compile(
    r"[A-Za-z0-9!#$&^_.+-]+/[A-Za-z0-9!#$&^_.+-]+\Z"
)


class ComputationalObjectError(ValueError):
    """A computational object, manifest, byte range, or backing operation is invalid."""


def _strict_integer(value: Any, name: str, *, minimum: int = 0) -> int:
    """Require a built-in integer without admitting Boolean values."""
    if type(value) is not int or value < minimum:
        raise ComputationalObjectError(
            f"{name} must be an integer greater than or equal to {minimum}"
        )
    return value


def _require_digest(value: Any, name: str) -> str:
    """Require one lowercase SHA-256 hexadecimal digest."""
    if not isinstance(value, str) or _HEX_DIGEST.fullmatch(value) is None:
        raise ComputationalObjectError(f"{name} must be a lowercase SHA-256 digest")
    return value


def _canonical_bytes(value: Any) -> bytes:
    """Encode a manifest projection using the repository's ordered JSON convention."""
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ComputationalObjectError("manifest is outside canonical JSON") from exc


def _sha256(data: bytes) -> str:
    """Return the content identity of one immutable byte sequence."""
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class ComputationalObjectChunk:
    """One ordered fixed-size page reference and its logical byte extent."""

    index: int
    page_digest: str
    byte_length: int

    def __post_init__(self) -> None:
        """Validate a zero-based page coordinate, content identity, and logical extent."""
        _strict_integer(self.index, "chunk index")
        _require_digest(self.page_digest, "page_digest")
        _strict_integer(self.byte_length, "chunk byte_length", minimum=1)
        if self.byte_length > _MAX_CHUNK_SIZE:
            raise ComputationalObjectError("chunk byte_length exceeds the maximum page size")

    def to_dict(self) -> dict[str, object]:
        """Project this immutable chunk reference into its portable wire form."""
        return {
            "index": self.index,
            "page_digest": self.page_digest,
            "byte_length": self.byte_length,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> ComputationalObjectChunk:
        """Reconstruct a chunk reference while refusing missing or unknown fields."""
        if not isinstance(payload, Mapping) or set(payload) != {
            "index",
            "page_digest",
            "byte_length",
        }:
            raise ComputationalObjectError("computational object chunk fields are invalid")
        return cls(
            index=payload["index"],
            page_digest=payload["page_digest"],
            byte_length=payload["byte_length"],
        )


@dataclass(frozen=True)
class ComputationalObjectManifest:
    """Immutable description of a byte object stored as ordered padded pages."""

    media_type: str
    size_bytes: int
    chunk_size: int
    content_digest: str
    chunks: tuple[ComputationalObjectChunk, ...]
    schema_version: int = _SCHEMA_VERSION

    def __post_init__(self) -> None:
        """Enforce exact chunk geometry and freeze the ordered page-reference sequence."""
        if (
            not isinstance(self.media_type, str)
            or _MEDIA_TYPE.fullmatch(self.media_type) is None
        ):
            raise ComputationalObjectError("media_type must be a simple type/subtype value")
        _strict_integer(self.size_bytes, "size_bytes")
        if self.size_bytes > _MAX_OBJECT_BYTES:
            raise ComputationalObjectError("size_bytes exceeds the supported object limit")
        _strict_integer(self.chunk_size, "chunk_size", minimum=1)
        if (
            self.chunk_size > _MAX_CHUNK_SIZE
            or self.chunk_size & (self.chunk_size - 1)
        ):
            raise ComputationalObjectError(
                f"chunk_size must be a power of two in [1, {_MAX_CHUNK_SIZE}]"
            )
        _require_digest(self.content_digest, "content_digest")
        if type(self.schema_version) is not int or self.schema_version != _SCHEMA_VERSION:
            raise ComputationalObjectError("unsupported computational object schema version")
        chunks = tuple(self.chunks)
        if any(not isinstance(chunk, ComputationalObjectChunk) for chunk in chunks):
            raise ComputationalObjectError("chunks must contain typed chunk references")
        expected_count = (self.size_bytes + self.chunk_size - 1) // self.chunk_size
        if expected_count > _MAX_CHUNKS:
            raise ComputationalObjectError("object requires too many chunks")
        if len(chunks) != expected_count:
            raise ComputationalObjectError("chunk count does not match object size")
        for index, chunk in enumerate(chunks):
            expected_length = min(
                self.chunk_size,
                self.size_bytes - index * self.chunk_size,
            )
            if chunk.index != index or chunk.byte_length != expected_length:
                raise ComputationalObjectError(
                    "chunks must be contiguous, ordered, and match the declared object extent"
                )
        object.__setattr__(self, "chunks", chunks)

    def _payload_dict(self) -> dict[str, object]:
        """Return the canonical manifest body without its self-referential digest."""
        return {
            "kind": _COMPUTATIONAL_OBJECT_KIND,
            "schema_version": self.schema_version,
            "media_type": self.media_type,
            "size_bytes": self.size_bytes,
            "chunk_size": self.chunk_size,
            "content_digest": self.content_digest,
            "chunks": [chunk.to_dict() for chunk in self.chunks],
        }

    @property
    def manifest_digest(self) -> str:
        """Identify the complete descriptor, including media type and ordered chunk references."""
        return _sha256(_canonical_bytes(self._payload_dict()))

    def to_dict(self) -> dict[str, object]:
        """Return the portable descriptor with its independently verifiable manifest identity."""
        return self._payload_dict() | {"manifest_digest": self.manifest_digest}

    def canonical_bytes(self) -> bytes:
        """Return the canonical serialized manifest bytes."""
        return _canonical_bytes(self.to_dict())

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> ComputationalObjectManifest:
        """Decode a manifest only when its schema, geometry, and descriptor digest agree."""
        expected = {
            "kind",
            "schema_version",
            "media_type",
            "size_bytes",
            "chunk_size",
            "content_digest",
            "chunks",
            "manifest_digest",
        }
        if not isinstance(payload, Mapping) or set(payload) != expected:
            raise ComputationalObjectError("computational object manifest fields are invalid")
        if payload.get("kind") != _COMPUTATIONAL_OBJECT_KIND:
            raise ComputationalObjectError("unsupported computational object manifest kind")
        raw_chunks = payload.get("chunks")
        if not isinstance(raw_chunks, list):
            raise ComputationalObjectError("manifest chunks must be an array")
        manifest = cls(
            media_type=payload["media_type"],
            size_bytes=payload["size_bytes"],
            chunk_size=payload["chunk_size"],
            content_digest=payload["content_digest"],
            chunks=tuple(ComputationalObjectChunk.from_dict(item) for item in raw_chunks),
            schema_version=payload["schema_version"],
        )
        if _require_digest(payload["manifest_digest"], "manifest_digest") != manifest.manifest_digest:
            raise ComputationalObjectError("computational object manifest digest mismatch")
        return manifest


class ComputationalObjectStore:
    """Read and publish immutable byte objects through an existing page backing.

    Each logical chunk is padded with zero bytes to the backing's fixed page
    size. The manifest records the unpadded byte extent, so the padding is
    storage geometry rather than object content.
    """

    def __init__(
        self,
        page_backing: Any,
        *,
        chunk_size: int | None = None,
        max_object_bytes: int = _MAX_OBJECT_BYTES,
    ) -> None:
        """Bind a page store and establish finite per-object and page-size limits."""
        if not callable(getattr(page_backing, "put_page", None)) or not callable(
            getattr(page_backing, "get_page", None)
        ):
            raise TypeError("page_backing must implement put_page(bytes) and get_page(digest)")
        backend_page_size = getattr(page_backing, "page_size", None)
        selected_chunk_size = (
            backend_page_size
            if chunk_size is None and type(backend_page_size) is int
            else _DEFAULT_CHUNK_SIZE if chunk_size is None else chunk_size
        )
        _strict_integer(selected_chunk_size, "chunk_size", minimum=1)
        if (
            selected_chunk_size > _MAX_CHUNK_SIZE
            or selected_chunk_size & (selected_chunk_size - 1)
        ):
            raise ComputationalObjectError(
                f"chunk_size must be a power of two in [1, {_MAX_CHUNK_SIZE}]"
            )
        if backend_page_size is not None and backend_page_size != selected_chunk_size:
            raise ComputationalObjectError(
                "chunk_size must match the fixed page size exposed by the backing"
            )
        _strict_integer(max_object_bytes, "max_object_bytes", minimum=1)
        if max_object_bytes > _MAX_OBJECT_BYTES:
            raise ComputationalObjectError("max_object_bytes exceeds the supported object limit")
        self.page_backing = page_backing
        self.chunk_size = selected_chunk_size
        self.max_object_bytes = max_object_bytes

    def put_bytes(
        self,
        data: bytes,
        *,
        media_type: str = "application/octet-stream",
    ) -> ComputationalObjectManifest:
        """Publish one in-memory byte sequence and return its complete immutable manifest."""
        if not isinstance(data, bytes):
            raise TypeError("data must be bytes")
        return self.put_stream(io.BytesIO(data), len(data), media_type=media_type)

    def put_stream(
        self,
        source: BinaryIO,
        total_size: int,
        *,
        media_type: str = "application/octet-stream",
    ) -> ComputationalObjectManifest:
        """Read exactly total_size bytes, persist every padded page, then publish the manifest."""
        if not callable(getattr(source, "read", None)):
            raise TypeError("source must expose read(size) returning bytes")
        _strict_integer(total_size, "total_size")
        if total_size > self.max_object_bytes:
            raise ComputationalObjectError("object exceeds max_object_bytes")
        chunk_count = (total_size + self.chunk_size - 1) // self.chunk_size
        if chunk_count > _MAX_CHUNKS:
            raise ComputationalObjectError("object requires too many chunks")
        if not isinstance(media_type, str) or _MEDIA_TYPE.fullmatch(media_type) is None:
            raise ComputationalObjectError("media_type must be a simple type/subtype value")

        content_hash = hashlib.sha256()
        chunks: list[ComputationalObjectChunk] = []
        remaining = total_size
        index = 0
        while remaining:
            logical_length = min(self.chunk_size, remaining)
            raw = self._read_exactly(source, logical_length)
            content_hash.update(raw)
            padded = raw + bytes(self.chunk_size - logical_length)
            expected_page_digest = _sha256(padded)
            try:
                page_digest = self.page_backing.put_page(padded)
            except Exception as exc:
                raise ComputationalObjectError(
                    f"page backing rejected chunk {index}: {type(exc).__name__}: {exc}"
                ) from exc
            if _require_digest(page_digest, "page backing result") != expected_page_digest:
                raise ComputationalObjectError(
                    f"page backing changed the content identity for chunk {index}"
                )
            chunks.append(
                ComputationalObjectChunk(
                    index=index,
                    page_digest=page_digest,
                    byte_length=logical_length,
                )
            )
            remaining -= logical_length
            index += 1

        return ComputationalObjectManifest(
            media_type=media_type,
            size_bytes=total_size,
            chunk_size=self.chunk_size,
            content_digest=content_hash.hexdigest(),
            chunks=tuple(chunks),
        )

    def read_range(
        self,
        manifest: ComputationalObjectManifest | Mapping[str, Any],
        offset: int,
        length: int | None = None,
    ) -> bytes:
        """Read a bounded byte range by resolving only the intersecting page references."""
        descriptor = self._coerce_manifest(manifest)
        self._require_compatible_manifest(descriptor)
        _strict_integer(offset, "offset")
        selected_length = descriptor.size_bytes - offset if length is None else _strict_integer(
            length, "length"
        )
        if offset > descriptor.size_bytes or selected_length > descriptor.size_bytes - offset:
            raise ComputationalObjectError("requested byte range lies outside the object")
        if selected_length > self.max_object_bytes:
            raise ComputationalObjectError("requested range exceeds max_object_bytes")
        if selected_length == 0:
            if descriptor.size_bytes == 0 and offset == 0:
                if descriptor.content_digest != _sha256(b""):
                    raise ComputationalObjectError("empty object content digest mismatch")
            return b""

        range_end = offset + selected_length
        first_index = offset // self.chunk_size
        last_index = (range_end - 1) // self.chunk_size
        output = bytearray()
        for index in range(first_index, last_index + 1):
            chunk = descriptor.chunks[index]
            page = self._read_page(chunk)
            chunk_start = index * self.chunk_size
            local_start = max(offset, chunk_start) - chunk_start
            local_end = min(range_end, chunk_start + chunk.byte_length) - chunk_start
            if local_end > local_start:
                output.extend(page[local_start:local_end])

        result = bytes(output)
        if len(result) != selected_length:
            raise ComputationalObjectError("resolved page extents did not cover the requested range")
        if offset == 0 and selected_length == descriptor.size_bytes:
            if _sha256(result) != descriptor.content_digest:
                raise ComputationalObjectError("complete object content digest mismatch")
        return result

    def read_bytes(
        self,
        manifest: ComputationalObjectManifest | Mapping[str, Any],
        *,
        max_bytes: int | None = None,
    ) -> bytes:
        """Read and verify the complete object, applying an optional stricter caller limit."""
        descriptor = self._coerce_manifest(manifest)
        effective_limit = self.max_object_bytes if max_bytes is None else _strict_integer(
            max_bytes, "max_bytes"
        )
        if descriptor.size_bytes > min(self.max_object_bytes, effective_limit):
            raise ComputationalObjectError("object exceeds the requested read limit")
        return self.read_range(descriptor, 0, descriptor.size_bytes)

    def verify(
        self,
        manifest: ComputationalObjectManifest | Mapping[str, Any],
    ) -> bool:
        """Stream through every page and verify the complete logical content digest."""
        descriptor = self._coerce_manifest(manifest)
        self._require_compatible_manifest(descriptor)
        content_hash = hashlib.sha256()
        observed_size = 0
        for chunk in descriptor.chunks:
            page = self._read_page(chunk)
            logical = page[: chunk.byte_length]
            content_hash.update(logical)
            observed_size += len(logical)
        if observed_size != descriptor.size_bytes or content_hash.hexdigest() != descriptor.content_digest:
            raise ComputationalObjectError("complete object content digest mismatch")
        return True

    @staticmethod
    def _read_exactly(source: BinaryIO, length: int) -> bytes:
        """Read a requested stream extent despite short non-terminal reads."""
        parts: list[bytes] = []
        observed = 0
        while observed < length:
            part = source.read(length - observed)
            if not isinstance(part, bytes):
                raise ComputationalObjectError("source read(size) must return bytes")
            if not part:
                raise ComputationalObjectError("source ended before the declared object size")
            parts.append(part)
            observed += len(part)
            if observed > length:
                raise ComputationalObjectError("source returned more bytes than requested")
        return b"".join(parts)

    def _read_page(self, chunk: ComputationalObjectChunk) -> bytes:
        """Resolve one fixed-size page and verify its hash and zero-padding suffix."""
        try:
            page = self.page_backing.get_page(chunk.page_digest)
        except Exception as exc:
            raise ComputationalObjectError(
                f"cannot resolve object page {chunk.page_digest}: {type(exc).__name__}: {exc}"
            ) from exc
        if not isinstance(page, bytes) or len(page) != self.chunk_size:
            raise ComputationalObjectError("page backing returned a page with invalid geometry")
        if _sha256(page) != chunk.page_digest:
            raise ComputationalObjectError("page backing returned bytes with the wrong page digest")
        if any(page[chunk.byte_length :]):
            raise ComputationalObjectError("page padding after the logical extent must be zero")
        return page

    def _require_compatible_manifest(self, manifest: ComputationalObjectManifest) -> None:
        """Require the manifest's page geometry to match this store's backing."""
        if manifest.chunk_size != self.chunk_size:
            raise ComputationalObjectError("manifest chunk size differs from this page backing")

    @staticmethod
    def _coerce_manifest(
        manifest: ComputationalObjectManifest | Mapping[str, Any],
    ) -> ComputationalObjectManifest:
        """Accept one typed manifest or validate its portable mapping representation."""
        if isinstance(manifest, ComputationalObjectManifest):
            return manifest
        if isinstance(manifest, Mapping):
            return ComputationalObjectManifest.from_dict(manifest)
        raise TypeError("manifest must be a ComputationalObjectManifest or mapping")
