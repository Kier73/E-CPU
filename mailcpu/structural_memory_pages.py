"""Content-addressed virtual-memory pages reconstructed from structural memory."""

from __future__ import annotations

import hashlib
from collections import OrderedDict
from collections.abc import Mapping
from typing import Any

from .providers import (
    StructuralMemoryFileReadReceipt,
    StructuralMemoryFileProvider,
    StructuralMemoryFileRef,
)


class StructuralMemoryPageBacking:
    """A PageBacking implementation whose immutable pages are pinned structural-memory byte ranges.

    The backing is host-bound. Snapshots contain page references and locally persisted
    non-structural pages only; the structural registry and executable host state are
    deliberately rebound after restore.
    """

    SNAPSHOT_KIND = "structural_memory_page_backing"
    SNAPSHOT_VERSION = 1
    MAX_PAGE_SIZE = 65_536
    MAX_CACHED_PAGES = 4

    def __init__(self, registry: Any | None = None) -> None:
        """Initialize an inert content-addressed backing with a bounded four-page host cache and optional local registry."""
        self._registry: Any | None = None
        self._references: dict[str, StructuralMemoryFileRef] = {}
        self._providers: dict[str, StructuralMemoryFileProvider] = {}
        self._local_pages: dict[str, bytes] = {}
        self._page_cache: OrderedDict[str, bytes] = OrderedDict()
        self._receipts: OrderedDict[str, StructuralMemoryFileReadReceipt] = OrderedDict()
        if registry is not None:
            self.bind_registry(registry)

    @staticmethod
    def _validate_digest(digest: str) -> None:
        """Mathematics: require `h∈{0,…,f}^64`, the canonical lowercase SHA-256 identity domain."""
        if (
            type(digest) is not str
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise ValueError("page identity must be a lowercase SHA-256 digest")

    @classmethod
    def _validate_reference(cls, digest: str, reference: StructuralMemoryFileRef) -> None:
        """Mathematics: admit `(h,r)` only when `r.size=2^k`, `1≤r.size≤65536`, and `h` is canonical SHA-256."""
        cls._validate_digest(digest)
        if not isinstance(reference, StructuralMemoryFileRef):
            raise ValueError("page backing requires a StructuralMemoryFileRef")
        if (
            reference.size <= 0
            or reference.size > cls.MAX_PAGE_SIZE
            or reference.size & (reference.size - 1)
        ):
            raise ValueError("structural-memory page size must be a power of two in [1, 65536]")

    def bind_registry(self, registry: Any) -> None:
        """Mathematics: bind symbolic reference set `R` to one trusted local registry `G`, without changing reference identity."""
        if not callable(getattr(registry, "read_revision", None)):
            raise ValueError("page backing binding requires a structural-memory read_revision interface")
        if self._registry is registry:
            return
        self._registry = registry
        self._providers = {
            digest: StructuralMemoryFileProvider(
                reference,
                registry,
                max_read_bytes=reference.size,
            )
            for digest, reference in sorted(self._references.items())
        }
        self._page_cache.clear()
        self._receipts.clear()

    def register_page_reference(
        self,
        digest: str,
        reference: StructuralMemoryFileRef,
    ) -> str:
        """Mathematics: extend `R[h↦r]` only when `r` is valid and no conflicting or local page already owns `h`."""
        self._validate_reference(digest, reference)
        existing = self._references.get(digest)
        if existing is not None and existing.to_dict() != reference.to_dict():
            raise ValueError("page digest is already bound to a different structural-memory reference")
        if digest in self._local_pages:
            raise ValueError("page digest is already backed by local page content")
        self._references[digest] = reference
        if self._registry is not None:
            self._providers[digest] = StructuralMemoryFileProvider(
                reference,
                self._registry,
                max_read_bytes=reference.size,
            )
        self._page_cache.pop(digest, None)
        self._receipts.pop(digest, None)
        return digest

    def page_size_for(self, digest: str) -> int:
        """Mathematics: return `|page(h)|` from its symbolic reference or local content without evaluating the generator."""
        self._validate_digest(digest)
        reference = self._references.get(digest)
        if reference is not None:
            return reference.size
        local = self._local_pages.get(digest)
        if local is not None:
            return len(local)
        raise KeyError(f"page backing has no registered page: {digest}")

    def get_page(self, digest: str) -> bytes:
        """Mathematics: resolve `G(r_h)=b` only when `|b|=r_h.size` and `SHA256(b)=h`."""
        self._validate_digest(digest)
        local = self._local_pages.get(digest)
        if local is not None:
            return local
        cached = self._page_cache.get(digest)
        if cached is not None:
            self._page_cache.move_to_end(digest)
            self._receipts.move_to_end(digest)
            return cached
        provider = self._providers.get(digest)
        reference = self._references.get(digest)
        if provider is None or reference is None:
            if self._registry is None and reference is not None:
                raise RuntimeError("structural-memory page backing has not been rebound to a local registry")
            raise KeyError(f"page backing has no registered page: {digest}")
        content, receipt = provider.read_with_receipt(0, reference.size)
        if (
            not isinstance(content, bytes)
            or len(content) != reference.size
            or hashlib.sha256(content).hexdigest() != digest
            or receipt.length != reference.size
            or receipt.content_digest != digest
        ):
            raise ValueError("structural-memory page bytes do not match the pinned page identity")
        # The provider has already returned complete byte-level evidence.
        # Its coordinate cache is redundant once the immutable page exists:
        # future hot access uses _page_cache, and an evicted page can regenerate
        # the same receipt identities from the pinned revision.
        provider._discard_value_cache()
        self._cache_structural_page(digest, content, receipt)
        return content

    def _cache_structural_page(
        self,
        digest: str,
        content: bytes,
        receipt: StructuralMemoryFileReadReceipt,
    ) -> None:
        """Mathematics: retain the most-recent min(4,|P|) verified structural pages and their receipts; evict the least-recent pair together."""
        self._page_cache[digest] = content
        self._page_cache.move_to_end(digest)
        self._receipts[digest] = receipt
        self._receipts.move_to_end(digest)
        while len(self._page_cache) > self.MAX_CACHED_PAGES:
            evicted_digest, _evicted_content = self._page_cache.popitem(last=False)
            self._receipts.pop(evicted_digest, None)

    @property
    def cached_page_count(self) -> int:
        """Mathematics: expose |dom(P_cache)|, the number of reconstructed structural pages retained by this backing."""
        return len(self._page_cache)

    @property
    def cached_page_bytes(self) -> int:
        """Mathematics: expose Σ_{h∈dom(P_cache)} |P_cache[h]|, the exact retained duplicate-page byte count."""
        return sum(len(content) for content in self._page_cache.values())

    @property
    def cached_receipt_coordinate_count(self) -> int:
        """Mathematics: expose Σ_h |ρ_h.value_receipt_ids| over retained structural-page receipts."""
        return sum(len(receipt.value_receipt_ids) for receipt in self._receipts.values())

    @property
    def cached_provider_coordinate_count(self) -> int:
        """Mathematics: expose Σ_p |V_cache(p)| across bound providers after page faults."""
        return sum(provider.cached_coordinate_count for provider in self._providers.values())

    def put_page(self, data: bytes) -> str:
        """Mathematics: map private page bytes `b` to immutable identity `h=SHA256(b)`, preserving any structural owner of `h`."""
        if not isinstance(data, bytes) or not data:
            raise ValueError("page backing accepts non-empty immutable byte strings")
        digest = hashlib.sha256(data).hexdigest()
        if digest in self._references:
            # A structural reference is authoritative. Confirm that the registered
            # generator really reconstructs the same bytes instead of shadowing it.
            if self.get_page(digest) != data:
                raise ValueError("published page conflicts with its structural-memory reference")
        else:
            self._local_pages[digest] = bytes(data)
        # Locally backed COW pages are already durably represented in
        # _local_pages; retaining a second page-cache copy is unnecessary.
        return digest

    def read_receipt(self, digest: str) -> StructuralMemoryFileReadReceipt | None:
        """Mathematics: project the latest structural read receipt `ρ_h` for page identity `h`, or `⊥` when not read."""
        self._validate_digest(digest)
        return self._receipts.get(digest)

    def snapshot(self) -> dict[str, Any]:
        """Mathematics: serialize `(R,L)`—symbolic references and local page bytes—without host registry state."""
        return {
            "provider_type": self.SNAPSHOT_KIND,
            "schema_version": self.SNAPSHOT_VERSION,
            "pages": {
                digest: reference.to_dict()
                for digest, reference in sorted(self._references.items())
            },
            "local_pages": {
                digest: data.hex()
                for digest, data in sorted(self._local_pages.items())
            },
        }

    @classmethod
    def from_snapshot(cls, payload: Mapping[str, Any]) -> "StructuralMemoryPageBacking":
        """Mathematics: reconstruct `(R,L)` as an inert descriptor, requiring trusted host rebinding before any `G(r)` read."""
        if (
            not isinstance(payload, Mapping)
            or payload.get("provider_type") != cls.SNAPSHOT_KIND
            or payload.get("schema_version") != cls.SNAPSHOT_VERSION
        ):
            raise ValueError("unsupported structural-memory page backing snapshot")
        raw_pages = payload.get("pages", {})
        raw_local_pages = payload.get("local_pages", {})
        if not isinstance(raw_pages, Mapping) or not isinstance(raw_local_pages, Mapping):
            raise ValueError("page backing snapshot maps must be mappings")
        backing = cls()
        for raw_digest, raw_reference in raw_pages.items():
            digest = str(raw_digest)
            reference = StructuralMemoryFileRef.from_dict(raw_reference)
            cls._validate_reference(digest, reference)
            backing._references[digest] = reference
        for raw_digest, encoded in raw_local_pages.items():
            digest = str(raw_digest)
            cls._validate_digest(digest)
            if type(encoded) is not str:
                raise ValueError("local page snapshot content must be hexadecimal text")
            try:
                data = bytes.fromhex(encoded)
            except ValueError as exc:
                raise ValueError("local page snapshot contains invalid hexadecimal content") from exc
            if not data or hashlib.sha256(data).hexdigest() != digest:
                raise ValueError(f"invalid local page content identity: {digest}")
            reference = backing._references.get(digest)
            if reference is not None:
                if len(data) != reference.size:
                    raise ValueError("local page size does not match structural-memory page reference")
                raise ValueError("page snapshot cannot contain both local bytes and a structural reference")
            backing._local_pages[digest] = data
        return backing
