"""Paged copy-on-write virtual memory for MailCPU tasks."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Protocol


class VirtualMemoryError(Exception):
    """A virtual memory mapping or access failed."""


class PageFault(VirtualMemoryError):
    """A virtual address had no mapping for the requested access."""

    def __init__(self, address: int, page_number: int, access: str) -> None:
        """Mathematics: materialize fault tuple `f=(address,page,access)` for unmapped page `page=⌊address/P⌋`."""

        self.address = address
        self.page_number = page_number
        self.access = access
        super().__init__(f"unmapped page: {page_number} ({access} at address {address})")


class MemoryQuotaExceeded(VirtualMemoryError):
    """A mapping request would exceed the virtual memory page quota."""


class ResidentQuotaExceeded(VirtualMemoryError):
    """A VM-wide resident-page admission request would exceed its resource budget."""


class PageBacking(Protocol):
    """Content-addressed provider used to publish evicted bytes and fault them back by digest."""

    def put_page(self, data: bytes) -> str:
        """Mathematics: publish `b` and return its identity `h=SHA256(b)`."""

        ...

    def get_page(self, digest: str) -> bytes:
        """Mathematics: resolve `CAS[h]=b` with `SHA256(b)=h`, or raise without inventing bytes."""

        ...


@dataclass(frozen=True)
class PageMapping:
    """One virtual-page mapping to immutable content and access rights."""

    page_number: int
    blob_id: str
    writable: bool
    shared_id: str | None = None
    shared_page: int | None = None


@dataclass(frozen=True)
class PageReservation:
    """A virtual page reserved for demand materialization, optionally backed by an evicted page blob."""

    page_number: int
    writable: bool
    backing_blob_id: str | None = None


@dataclass
class SharedRegion:
    """A named, page-aligned mutable byte region attachable to multiple virtual memories."""

    name: str
    size: int
    data: bytearray = field(default_factory=bytearray)

    def __post_init__(self) -> None:
        """Mathematics: require finite region domain `name≠ε`, `size>0`, and `|data|=size`."""

        if not self.name or self.size <= 0:
            raise VirtualMemoryError("shared region name and size must be positive")
        if not self.data:
            self.data = bytearray(self.size)
        if len(self.data) != self.size:
            raise VirtualMemoryError("shared region data length must equal size")

    def read(self, offset: int, size: int) -> bytes:
        """Mathematics: return bounded interval `S[offset:min(offset+size,|S|)]`."""

        if offset < 0 or size < 0 or offset > self.size:
            raise VirtualMemoryError("shared read interval is invalid")
        return bytes(self.data[offset : min(offset + size, self.size)])

    def write(self, offset: int, payload: bytes) -> int:
        """Mathematics: apply slice replacement `S[offset:offset+|B|] := B` within `0≤offset+|B|≤|S|`."""

        if offset < 0 or offset + len(payload) > self.size:
            raise VirtualMemoryError("shared write interval is invalid")
        self.data[offset : offset + len(payload)] = payload
        return len(payload)

    def snapshot(self) -> dict[str, Any]:
        """Mathematics: serialize shared identity and content `S=(name,size,data)` for exact restoration."""

        return {"name": self.name, "size": self.size, "data_hex": bytes(self.data).hex()}

    @classmethod
    def from_snapshot(cls, payload: Mapping[str, Any]) -> "SharedRegion":
        """Mathematics: reconstruct `S` and reject content whose declared size differs from `|data|`."""

        data = bytearray.fromhex(str(payload.get("data_hex", "")))
        return cls(str(payload["name"]), int(payload["size"]), data)


class VirtualMemory:
    """Fixed-page virtual memory using content hashes and copy-on-write updates."""

    def __init__(
        self,
        page_size: int = 4096,
        max_pages: int | None = None,
        resident_admitter: Callable[[int], None] | None = None,
        page_backing: PageBacking | None = None,
    ) -> None:
        """Mathematics: initialize page size `P`, quota `Q`, page map `M=∅`, blob cache `B=∅`, shared map `S=∅`, and optional backing `C`."""

        if page_size <= 0 or page_size & (page_size - 1):
            raise ValueError("page_size must be a positive power of two")
        if max_pages is not None and max_pages <= 0:
            raise ValueError("max_pages must be positive when provided")
        self.page_size = page_size
        self.max_pages = max_pages
        self._resident_admitter = resident_admitter
        self._page_backing = page_backing
        self._mappings: dict[int, PageMapping] = {}
        self._reservations: dict[int, PageReservation] = {}
        self._blobs: dict[str, bytes] = {}
        self._shared_regions: dict[str, SharedRegion] = {}

    def _put_page(self, data: bytes) -> str:
        """Mathematics: address a page by `h = SHA256(data)` and store it immutably in `B[h]`."""

        if len(data) != self.page_size:
            raise VirtualMemoryError("page payload must equal page_size")
        digest = hashlib.sha256(data).hexdigest()
        self._blobs[digest] = bytes(data)
        return digest

    def _get_page(self, blob_id: str) -> bytes:
        """Mathematics: resolve `B[h]`, then `C[h]` on a cache miss, requiring `SHA256(bytes)=h` at both paths."""

        local = self._blobs.get(blob_id)
        if local is not None:
            return local
        if self._page_backing is None:
            raise VirtualMemoryError(f"missing page blob: {blob_id}")
        try:
            data = self._page_backing.get_page(blob_id)
        except Exception as error:
            raise VirtualMemoryError(f"page backing could not resolve: {blob_id}") from error
        if not isinstance(data, bytes) or len(data) != self.page_size or hashlib.sha256(data).hexdigest() != blob_id:
            raise VirtualMemoryError(f"page backing returned invalid content: {blob_id}")
        self._blobs[blob_id] = data
        return data

    def preflight_mapping(self, page_numbers: tuple[int, ...], check_resident: bool = False) -> None:
        """Mathematics: admit a finite page set `P` iff `P∩(M∪R)=∅` and `|M|+|P|≤Q`, optionally requiring resident admission `A(|P|)`."""

        target = tuple(int(page_number) for page_number in page_numbers)
        if len(set(target)) != len(target) or any(page_number < 0 for page_number in target):
            raise VirtualMemoryError("mapping page set must be unique and non-negative")
        occupied = set(self._mappings) | set(self._reservations)
        collision = next((page_number for page_number in target if page_number in occupied), None)
        if collision is not None:
            raise VirtualMemoryError(f"page already mapped or reserved: {collision}")
        self._check_quota(len(target))
        if check_resident and target and self._resident_admitter is not None:
            self._resident_admitter(len(target))

    def map(self, start: int, length: int, writable: bool = True) -> None:
        """Mathematics: map pages `p ∈ [start/P, ceil((start+length)/P))` to zero-filled blobs."""

        if start < 0 or length <= 0 or start % self.page_size:
            raise VirtualMemoryError("mapping start must be aligned and length must be positive")
        first = start // self.page_size
        count = (length + self.page_size - 1) // self.page_size
        target_pages = tuple(range(first, first + count))
        self.preflight_mapping(target_pages)
        zero_blob = self._put_page(b"\x00" * self.page_size)
        for page_number in target_pages:
            self._mappings[page_number] = PageMapping(page_number, zero_blob, writable)

    def reserve(self, start: int, length: int, writable: bool = True) -> None:
        """Mathematics: reserve virtual pages `p ∈ [start/P, ceil((start+length)/P))` without allocating resident blobs."""

        if start < 0 or length <= 0 or start % self.page_size:
            raise VirtualMemoryError("reservation start must be aligned and length must be positive")
        first = start // self.page_size
        count = (length + self.page_size - 1) // self.page_size
        target_pages = tuple(range(first, first + count))
        if any(page_number in self._mappings or page_number in self._reservations for page_number in target_pages):
            duplicate = next(
                page_number
                for page_number in target_pages
                if page_number in self._mappings or page_number in self._reservations
            )
            raise VirtualMemoryError(f"page already mapped or reserved: {duplicate}")
        for page_number in target_pages:
            self._reservations[page_number] = PageReservation(page_number, writable)

    def allocate(self, length: int, writable: bool = True, hint: int | None = None) -> int:
        """Mathematics: choose the least free aligned interval of `k=ceil(length/P)` pages, preferring an available hint."""

        if length <= 0:
            raise VirtualMemoryError("allocation length must be positive")
        count = (length + self.page_size - 1) // self.page_size
        if hint is not None:
            if hint < 0 or hint % self.page_size:
                raise VirtualMemoryError("allocation hint must be non-negative and aligned")
            hinted_page = hint // self.page_size
            if self._range_free(hinted_page, count):
                self.reserve(hint, length, writable)
                return hint
        candidate = 0
        while not self._range_free(candidate, count):
            candidate += 1
        start = candidate * self.page_size
        self.reserve(start, length, writable)
        return start

    def attach_shared(self, start: int, region: SharedRegion, writable: bool = True) -> None:
        """Mathematics: map each shared page `j` to `M[start/P+j]=(region,j,writable)` under the page quota."""

        if start < 0 or start % self.page_size or region.size % self.page_size:
            raise VirtualMemoryError("shared mapping requires aligned start and region size")
        existing = self._shared_regions.get(region.name)
        if existing is not None and existing is not region:
            raise VirtualMemoryError(f"shared region identity collision: {region.name}")
        first = start // self.page_size
        target_pages = tuple(range(first, first + region.size // self.page_size))
        if any(page_number in self._mappings or page_number in self._reservations for page_number in target_pages):
            duplicate = next(
                page_number
                for page_number in target_pages
                if page_number in self._mappings or page_number in self._reservations
            )
            raise VirtualMemoryError(f"page already mapped: {duplicate}")
        self._check_quota(len(target_pages))
        self._shared_regions[region.name] = region
        for shared_page, page_number in enumerate(target_pages):
            self._mappings[page_number] = PageMapping(
                page_number,
                "",
                writable,
                region.name,
                shared_page,
            )

    def unmap(self, start: int, length: int) -> None:
        """Mathematics: remove every mapping in the aligned interval, `M := M \\ {p : p ∈ interval}`."""

        if start < 0 or length <= 0 or start % self.page_size:
            raise VirtualMemoryError("unmapping start must be aligned and length must be positive")
        first = start // self.page_size
        count = (length + self.page_size - 1) // self.page_size
        for page_number in range(first, first + count):
            self._mappings.pop(page_number, None)
            self._reservations.pop(page_number, None)

    def reclaim(self, count: int = 1, page_numbers: tuple[int, ...] | None = None) -> tuple[int, ...]:
        """Mathematics: replace selected private mappings `M[p]` with reservations `R[p]=(writable,h_p)`, preserving bytes via `h_p`."""

        if count <= 0:
            raise VirtualMemoryError("reclaim count must be positive")
        if page_numbers is None:
            selected = tuple(
                mapping.page_number
                for mapping in self.mapped_pages()
                if mapping.shared_id is None
            )[:count]
        else:
            selected = tuple(int(page_number) for page_number in page_numbers)
            if len(set(selected)) != len(selected):
                raise VirtualMemoryError("reclaim page list contains duplicates")
            if len(selected) > count:
                raise VirtualMemoryError("reclaim page list exceeds requested count")
        if not selected:
            raise VirtualMemoryError("no private resident pages available for reclaim")
        mappings: list[PageMapping] = []
        for page_number in selected:
            mapping = self._mappings.get(page_number)
            if mapping is None:
                raise VirtualMemoryError(f"page is not resident: {page_number}")
            if mapping.shared_id is not None:
                raise VirtualMemoryError(f"shared page cannot be reclaimed: {page_number}")
            self._get_page(mapping.blob_id)
            mappings.append(mapping)
        if self._page_backing is not None:
            for mapping in mappings:
                try:
                    persisted = self._page_backing.put_page(self._get_page(mapping.blob_id))
                except Exception as error:
                    raise VirtualMemoryError(f"remote page backing failed for {mapping.blob_id}") from error
                if persisted != mapping.blob_id:
                    raise VirtualMemoryError("remote page backing changed page identity")
        for mapping in mappings:
            self._reservations[mapping.page_number] = PageReservation(
                mapping.page_number,
                mapping.writable,
                mapping.blob_id,
            )
            del self._mappings[mapping.page_number]
            if self._page_backing is not None:
                self._blobs.pop(mapping.blob_id, None)
        return tuple(mapping.page_number for mapping in mappings)

    def protect(self, start: int, length: int, writable: bool) -> None:
        """Mathematics: atomically apply protection override `writable(p):=w` to every existing page in the interval."""

        if start < 0 or length <= 0 or start % self.page_size:
            raise VirtualMemoryError("protection start must be aligned and length must be positive")
        first = start // self.page_size
        count = (length + self.page_size - 1) // self.page_size
        target_pages = tuple(range(first, first + count))
        for page_number in target_pages:
            if page_number not in self._mappings and page_number not in self._reservations:
                raise PageFault(page_number * self.page_size, page_number, "protect")
        for page_number in target_pages:
            mapping = self._mappings.get(page_number)
            if mapping is not None:
                self._mappings[page_number] = PageMapping(
                    mapping.page_number,
                    mapping.blob_id,
                    writable,
                    mapping.shared_id,
                    mapping.shared_page,
                )
            else:
                self._reservations[page_number] = PageReservation(
                    page_number,
                    writable,
                    self._reservations[page_number].backing_blob_id,
                )

    def read(self, address: int, size: int) -> bytes:
        """Mathematics: concatenate page slices `read(a,n) = ||_p page[p][offset:offset+k_p]`."""

        if address < 0 or size < 0:
            raise VirtualMemoryError("address and size must be non-negative")
        self._prepare_access(address, size, "read")
        result = bytearray()
        remaining = size
        cursor = address
        while remaining:
            page_number, offset = divmod(cursor, self.page_size)
            mapping = self._mapping(page_number, cursor, "read")
            chunk = min(remaining, self.page_size - offset)
            if mapping.shared_id is not None:
                region = self._shared_regions[mapping.shared_id]
                result.extend(region.read(mapping.shared_page * self.page_size + offset, chunk))
            else:
                result.extend(self._get_page(mapping.blob_id)[offset : offset + chunk])
            cursor += chunk
            remaining -= chunk
        return bytes(result)

    def write(self, address: int, data: bytes) -> int:
        """Mathematics: for each touched page, replace `B[h]` with `page[:o] || data || page[o+k:]` under COW."""

        if address < 0:
            raise VirtualMemoryError("address must be non-negative")
        written = 0
        cursor = address
        payload = memoryview(data)
        self._prepare_access(address, len(payload), "write")
        while written < len(payload):
            page_number, offset = divmod(cursor, self.page_size)
            mapping = self._mapping(page_number, cursor, "write")
            if not mapping.writable:
                raise VirtualMemoryError(f"page is read-only: {page_number}")
            chunk = min(len(payload) - written, self.page_size - offset)
            part = bytes(payload[written : written + chunk])
            if mapping.shared_id is not None:
                self._shared_regions[mapping.shared_id].write(
                    mapping.shared_page * self.page_size + offset,
                    part,
                )
            else:
                page = bytearray(self._get_page(mapping.blob_id))
                page[offset : offset + chunk] = part
                blob_id = self._put_page(bytes(page))
                self._mappings[page_number] = PageMapping(page_number, blob_id, mapping.writable)
            cursor += chunk
            written += chunk
        return written

    def clone(self) -> "VirtualMemory":
        """Mathematics: create a snapshot sharing immutable `B` and `M`; later writes allocate new page hashes."""

        clone = VirtualMemory(self.page_size, self.max_pages, self._resident_admitter, self._page_backing)
        clone._mappings = dict(self._mappings)
        clone._reservations = dict(self._reservations)
        clone._blobs = dict(self._blobs)
        clone._shared_regions = dict(self._shared_regions)
        return clone

    def commit_from(self, candidate: "VirtualMemory") -> None:
        """Mathematics: replace this state by a validated clone `S:=S_candidate` only when page geometry and backing identity agree."""

        if not isinstance(candidate, VirtualMemory):
            raise VirtualMemoryError("memory commit candidate must be VirtualMemory")
        if (
            candidate.page_size != self.page_size
            or candidate.max_pages != self.max_pages
            or candidate._page_backing is not self._page_backing
        ):
            raise VirtualMemoryError("memory commit candidate has incompatible configuration")
        self._mappings = dict(candidate._mappings)
        self._reservations = dict(candidate._reservations)
        self._blobs = dict(candidate._blobs)
        self._shared_regions = dict(candidate._shared_regions)

    def mapped_pages(self) -> tuple[PageMapping, ...]:
        """Mathematics: expose the finite mapping relation `M` ordered by virtual page number."""

        return tuple(self._mappings[number] for number in sorted(self._mappings))

    def snapshot(self) -> dict[str, Any]:
        """Mathematics: serialize `(P,Q,M,R,B,S)` so resident and reserved address state replay without host pointers."""

        return {
            "page_size": self.page_size,
            "max_pages": self.max_pages,
            "page_backing": self._page_backing is not None,
            "reservations": [
                {
                    "page_number": reservation.page_number,
                    "writable": reservation.writable,
                    "backing_blob_id": reservation.backing_blob_id,
                }
                for reservation in self.reserved_pages()
            ],
            "mappings": [
                {
                    "page_number": mapping.page_number,
                    "blob_id": mapping.blob_id,
                    "writable": mapping.writable,
                    "shared_id": mapping.shared_id,
                    "shared_page": mapping.shared_page,
                }
                for mapping in self.mapped_pages()
            ],
            "blobs": {digest: data.hex() for digest, data in sorted(self._blobs.items())},
            "shared_regions": {
                name: region.snapshot() for name, region in sorted(self._shared_regions.items())
            },
        }

    @classmethod
    def from_snapshot(
        cls,
        payload: dict[str, Any],
        shared_regions: Mapping[str, SharedRegion] | None = None,
        resident_admitter: Callable[[int], None] | None = None,
        page_backing: PageBacking | None = None,
    ) -> "VirtualMemory":
        """Mathematics: reconstruct `(P,Q,M,B,S)` and require every private blob identity and shared reference to validate."""

        memory = cls(
            int(payload["page_size"]),
            None if payload.get("max_pages") is None else int(payload["max_pages"]),
            resident_admitter,
            page_backing,
        )
        memory._shared_regions = dict(shared_regions or {})
        for name, region in memory._shared_regions.items():
            if region.name != str(name):
                raise VirtualMemoryError(f"shared region name mismatch: {name}")
        for name, raw in payload.get("shared_regions", {}).items():
            canonical_name = str(name)
            candidate = SharedRegion.from_snapshot(dict(raw))
            if candidate.name != canonical_name:
                raise VirtualMemoryError(f"shared region name mismatch: {canonical_name}")
            existing = memory._shared_regions.get(canonical_name)
            if existing is None:
                memory._shared_regions[canonical_name] = candidate
            elif existing.snapshot() != candidate.snapshot():
                raise VirtualMemoryError(f"shared region content mismatch: {canonical_name}")
        for digest, encoded in payload.get("blobs", {}).items():
            data = bytes.fromhex(encoded)
            if len(data) != memory.page_size or hashlib.sha256(data).hexdigest() != digest:
                raise VirtualMemoryError(f"invalid page blob: {digest}")
            memory._blobs[str(digest)] = data
        for raw in payload.get("reservations", ()):
            reservation = PageReservation(
                int(raw["page_number"]),
                bool(raw["writable"]),
                None if raw.get("backing_blob_id") is None else str(raw["backing_blob_id"]),
            )
            if reservation.page_number < 0:
                raise VirtualMemoryError(f"invalid reserved page number: {reservation.page_number}")
            if reservation.backing_blob_id is not None:
                if reservation.backing_blob_id not in memory._blobs and memory._page_backing is None:
                    raise VirtualMemoryError(f"missing reserved page blob: {reservation.backing_blob_id}")
                if reservation.backing_blob_id in memory._blobs:
                    memory._get_page(reservation.backing_blob_id)
            if reservation.page_number in memory._reservations:
                raise VirtualMemoryError(f"duplicate page reservation: {reservation.page_number}")
            memory._reservations[reservation.page_number] = reservation
        for raw in payload.get("mappings", ()):
            mapping = PageMapping(
                int(raw["page_number"]),
                str(raw.get("blob_id", "")),
                bool(raw["writable"]),
                None if raw.get("shared_id") is None else str(raw["shared_id"]),
                None if raw.get("shared_page") is None else int(raw["shared_page"]),
            )
            if mapping.shared_id is not None:
                if mapping.shared_id not in memory._shared_regions or mapping.shared_page is None:
                    raise VirtualMemoryError(f"missing shared page region: {mapping.shared_id}")
                region = memory._shared_regions[mapping.shared_id]
                if region.size % memory.page_size:
                    raise VirtualMemoryError(f"shared region is not page aligned: {mapping.shared_id}")
                if not 0 <= mapping.shared_page < region.size // memory.page_size:
                    raise VirtualMemoryError(f"invalid shared page index: {mapping.shared_page}")
            elif mapping.blob_id not in memory._blobs and memory._page_backing is None:
                raise VirtualMemoryError(f"missing mapped page blob: {mapping.blob_id}")
            if mapping.page_number < 0:
                raise VirtualMemoryError(f"invalid mapped page number: {mapping.page_number}")
            if mapping.page_number in memory._mappings:
                raise VirtualMemoryError(f"duplicate page mapping: {mapping.page_number}")
            if mapping.page_number in memory._reservations:
                raise VirtualMemoryError(f"page is both mapped and reserved: {mapping.page_number}")
            memory._check_quota(1)
            memory._mappings[mapping.page_number] = mapping
        return memory

    def reserved_pages(self) -> tuple[PageReservation, ...]:
        """Mathematics: expose the finite reservation relation `R` ordered by virtual page number."""

        return tuple(self._reservations[number] for number in sorted(self._reservations))

    def _mapping(self, page_number: int, address: int = 0, access: str = "read") -> PageMapping:
        """Mathematics: perform partial lookup `M[page]`, raising typed fault `f=(address,page,access)` when absent."""

        mapping = self._mappings.get(page_number)
        if mapping is not None:
            if access == "write" and not mapping.writable:
                raise VirtualMemoryError(f"page is read-only: {page_number}")
            return mapping
        reservation = self._reservations.get(page_number)
        if reservation is None:
            raise PageFault(address, page_number, access)
        if access == "write" and not reservation.writable:
            raise VirtualMemoryError(f"page is read-only: {page_number}")
        return self._materialize(page_number, reservation)

    def _prepare_access(self, address: int, size: int, access: str) -> None:
        """Mathematics: preflight every touched page `P(a,n)={⌊x/P⌋:x∈[a,a+n)}` before any state mutation."""

        pending = self._preflight_access(address, size, access)
        for page_number, reservation in pending:
            self._materialize(page_number, reservation)

    def validate_access(self, address: int, size: int, access: str) -> None:
        """Mathematics: prove `P(a,n)⊆M∪R` and quota admission without changing `(M,R)`, yielding a transaction precondition for compound syscalls."""

        if address < 0 or size < 0:
            raise VirtualMemoryError("address and size must be non-negative")
        self._preflight_access(address, size, access)

    def _preflight_access(
        self,
        address: int,
        size: int,
        access: str,
    ) -> list[tuple[int, PageReservation]]:
        """Mathematics: compute pending demand set `D={p∈P(a,n):p∈R}` and require `|M|+|D|≤Q`, without materializing `D`."""

        if size == 0:
            return []
        remaining = size
        cursor = address
        pending: list[tuple[int, PageReservation]] = []
        seen: set[int] = set()
        while remaining:
            page_number, offset = divmod(cursor, self.page_size)
            mapping = self._mappings.get(page_number)
            if mapping is None:
                reservation = self._reservations.get(page_number)
                if reservation is None:
                    raise PageFault(cursor, page_number, access)
                if access == "write" and not reservation.writable:
                    raise VirtualMemoryError(f"page is read-only: {page_number}")
                if page_number not in seen:
                    pending.append((page_number, reservation))
                    seen.add(page_number)
            elif access == "write" and not mapping.writable:
                raise VirtualMemoryError(f"page is read-only: {page_number}")
            chunk = min(remaining, self.page_size - offset)
            cursor += chunk
            remaining -= chunk
        self._check_quota(len(pending))
        if pending and self._resident_admitter is not None:
            self._resident_admitter(len(pending))
        return pending

    def _materialize(self, page_number: int, reservation: PageReservation) -> PageMapping:
        """Mathematics: resolve `R[p]=(w,h)` into `M[p]=h` or a zero page when `h=⊥`, consuming one resident quota unit."""

        self._check_quota(1)
        blob_id = reservation.backing_blob_id or self._put_page(b"\x00" * self.page_size)
        mapping = PageMapping(page_number, blob_id, reservation.writable)
        self._mappings[page_number] = mapping
        del self._reservations[page_number]
        return mapping

    def _check_quota(self, additional_pages: int) -> None:
        """Mathematics: enforce `max_pages=None ∨ |M|+additional_pages≤max_pages` before allocation."""

        if self.max_pages is not None and len(self._mappings) + additional_pages > self.max_pages:
            raise MemoryQuotaExceeded(
                f"memory quota exceeded: {len(self._mappings) + additional_pages} > {self.max_pages} pages"
            )

    def _range_free(self, first_page: int, count: int) -> bool:
        """Mathematics: test interval disjointness `∀p∈[first,first+count), p∉M∪R`."""

        return all(
            page_number not in self._mappings and page_number not in self._reservations
            for page_number in range(first_page, first_page + count)
        )
