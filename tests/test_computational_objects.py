from __future__ import annotations

import hashlib
import io

import pytest

from mailcpu.computational_objects import (
    ComputationalObjectChunk,
    ComputationalObjectError,
    ComputationalObjectManifest,
    ComputationalObjectStore,
)


class MemoryPageStore:
    """Minimal fixed-page CAS used to exercise the object contract without transport."""

    def __init__(self, page_size: int = 8) -> None:
        """Create an empty page map with one declared page geometry."""
        self.page_size = page_size
        self.pages: dict[str, bytes] = {}
        self.reads: list[str] = []

    def put_page(self, data: bytes) -> str:
        """Admit a fixed-size page under its exact SHA-256 identity."""
        if not isinstance(data, bytes) or len(data) != self.page_size:
            raise ValueError("invalid test page geometry")
        digest = hashlib.sha256(data).hexdigest()
        previous = self.pages.setdefault(digest, data)
        if previous != data:
            raise ValueError("content-address collision in test backing")
        return digest

    def get_page(self, digest: str) -> bytes:
        """Resolve one page and record that the caller requested it."""
        self.reads.append(digest)
        return self.pages[digest]


def test_stream_manifest_roundtrip_and_complete_content_verification() -> None:
    """A complete object is reconstructed from ordered padded pages without changing its bytes."""
    raw = bytes(range(23))
    backing = MemoryPageStore(page_size=8)
    store = ComputationalObjectStore(backing, chunk_size=8)

    manifest = store.put_stream(
        io.BytesIO(raw),
        len(raw),
        media_type="application/x-model-weights",
    )
    restored_manifest = ComputationalObjectManifest.from_dict(manifest.to_dict())

    assert restored_manifest == manifest
    assert manifest.size_bytes == len(raw)
    assert manifest.content_digest == hashlib.sha256(raw).hexdigest()
    assert [item.byte_length for item in manifest.chunks] == [8, 8, 7]
    assert manifest.manifest_digest == restored_manifest.manifest_digest
    assert len(manifest.manifest_digest) == 64
    assert all(len(page) == 8 for page in backing.pages.values())
    assert store.read_bytes(manifest) == raw
    assert store.verify(manifest) is True


def test_byte_range_reads_only_intersecting_pages() -> None:
    """Range resolution addresses only the pages intersecting the selected logical interval."""
    raw = b"0123456789abcdefghi"
    backing = MemoryPageStore(page_size=8)
    store = ComputationalObjectStore(backing, chunk_size=8)
    manifest = store.put_bytes(raw)

    backing.reads.clear()
    assert store.read_range(manifest, 5, 8) == raw[5:13]
    assert backing.reads == [
        manifest.chunks[0].page_digest,
        manifest.chunks[1].page_digest,
    ]


def test_manifest_identity_binds_representation_metadata() -> None:
    """Equal content can have distinct object identities when their media types differ."""
    raw = b"same bytes"
    store = ComputationalObjectStore(MemoryPageStore(page_size=8), chunk_size=8)
    binary = store.put_bytes(raw, media_type="application/octet-stream")
    text = store.put_bytes(raw, media_type="text/plain")

    assert binary.content_digest == text.content_digest
    assert binary.manifest_digest != text.manifest_digest


def test_page_corruption_is_refused_before_bytes_are_returned() -> None:
    """A present page with a changed byte sequence cannot be interpreted as the addressed chunk."""
    backing = MemoryPageStore(page_size=8)
    store = ComputationalObjectStore(backing, chunk_size=8)
    manifest = store.put_bytes(b"abcdefgh")

    backing.pages[manifest.chunks[0].page_digest] = b"ABCDEFGH"
    with pytest.raises(ComputationalObjectError, match="wrong page digest"):
        store.read_range(manifest, 0, 4)


def test_nonzero_padding_is_refused_even_when_its_page_hash_is_pinned() -> None:
    """A manifest cannot hide bytes beyond the declared logical extent in a final padded page."""
    raw = b"abc"
    backing = MemoryPageStore(page_size=8)
    padded = b"abcDEF\x00\x00"
    page_digest = backing.put_page(padded)
    manifest = ComputationalObjectManifest(
        media_type="application/octet-stream",
        size_bytes=len(raw),
        chunk_size=8,
        content_digest=hashlib.sha256(raw).hexdigest(),
        chunks=(
            ComputationalObjectChunk(
                index=0,
                page_digest=page_digest,
                byte_length=3,
            ),
        ),
    )
    store = ComputationalObjectStore(backing, chunk_size=8)

    with pytest.raises(ComputationalObjectError, match="padding"):
        store.read_range(manifest, 0, 3)


def test_manifest_tampering_and_geometry_mismatch_are_refused() -> None:
    """The descriptor digest and contiguous chunk geometry are both admission requirements."""
    store = ComputationalObjectStore(MemoryPageStore(page_size=8), chunk_size=8)
    manifest = store.put_bytes(b"abcdefghijk")

    tampered = manifest.to_dict()
    tampered["media_type"] = "text/plain"
    with pytest.raises(ComputationalObjectError, match="manifest digest"):
        ComputationalObjectManifest.from_dict(tampered)

    with pytest.raises(ComputationalObjectError, match="chunk count"):
        ComputationalObjectManifest(
            media_type="application/octet-stream",
            size_bytes=11,
            chunk_size=8,
            content_digest=hashlib.sha256(b"abcdefghijk").hexdigest(),
            chunks=manifest.chunks[:1],
        )


def test_truncated_stream_does_not_publish_a_manifest() -> None:
    """A declared object extent must be read in full before a manifest becomes available."""
    backing = MemoryPageStore(page_size=8)
    store = ComputationalObjectStore(backing, chunk_size=8)

    with pytest.raises(ComputationalObjectError, match="ended before"):
        store.put_stream(io.BytesIO(b"short"), 8)

    assert len(backing.pages) == 0


def test_empty_object_has_a_valid_zero_chunk_manifest() -> None:
    """The empty byte sequence has one canonical content digest and no page references."""
    store = ComputationalObjectStore(MemoryPageStore(page_size=8), chunk_size=8)
    manifest = store.put_bytes(b"")

    assert manifest.chunks == ()
    assert manifest.size_bytes == 0
    assert manifest.content_digest == hashlib.sha256(b"").hexdigest()
    assert store.read_bytes(manifest) == b""
    assert store.verify(manifest) is True


def test_object_and_range_limits_are_checked_before_page_resolution() -> None:
    """Object and requested-range bounds fail before the page backing is read."""
    backing = MemoryPageStore(page_size=8)
    store = ComputationalObjectStore(backing, chunk_size=8, max_object_bytes=16)

    with pytest.raises(ComputationalObjectError, match="max_object_bytes"):
        store.put_bytes(b"x" * 17)
    manifest = store.put_bytes(b"0123456789")

    backing.reads.clear()
    with pytest.raises(ComputationalObjectError, match="outside the object"):
        store.read_range(manifest, 9, 2)
    with pytest.raises(ComputationalObjectError, match="read limit"):
        store.read_bytes(manifest, max_bytes=4)
    assert backing.reads == []


def test_backing_page_size_must_match_object_chunk_size() -> None:
    """A byte object cannot reinterpret fixed pages using incompatible chunk geometry."""
    with pytest.raises(ComputationalObjectError, match="match the fixed page size"):
        ComputationalObjectStore(MemoryPageStore(page_size=16), chunk_size=8)
