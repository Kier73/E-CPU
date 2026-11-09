from __future__ import annotations

import hashlib

import pytest

from mailcpu import (
    HeadlessOS,
    Instruction,
    MailCPUVirtualMachine,
    Op,
    Program,
    StructuralMemoryFileRef,
    StructuralMemoryPageBacking,
    VirtualMemory,
    VirtualMemoryError,
)
from mailcpu.law_certifier import Law


def _operating_system() -> HeadlessOS:
    return HeadlessOS(
        structural_memory_admission_policy=lambda proposal: proposal.spec.domain == "byte-stream"
    )


def _admit_byte_memory(operating_system: HeadlessOS, *, memory_id: str = "page-memory"):
    law = Law(
        family="int",
        params={"x0": 65, "step": 1, "mod": 256},
        order=1,
        verdict="GROUND",
    )
    witnesses = {coordinate: 65 + coordinate for coordinate in range(8)}
    proposal = operating_system.structural_memory.propose(
        memory_id,
        law,
        witnesses,
        domain="byte-stream",
        context={"dataset": "page-alpha", "encoding": "raw-byte"},
    )
    return operating_system.structural_memory.admit(proposal.proposal_id, expected_revision=0)


def _page_reference(version, *, start: int = 0, size: int = 8) -> StructuralMemoryFileRef:
    return StructuralMemoryFileRef.from_version(version, coordinate_start=start, size=size)


def test_structural_memory_page_fault_materializes_exact_hash_and_keeps_receipt() -> None:
    operating_system = _operating_system()
    version = _admit_byte_memory(operating_system)
    reference = _page_reference(version)
    expected = b"ABCDEFGH"
    digest = hashlib.sha256(expected).hexdigest()

    backing = StructuralMemoryPageBacking(operating_system.structural_memory)
    assert backing.register_page_reference(digest, reference) == digest
    memory = VirtualMemory(page_size=8, page_backing=backing)
    memory.reserve(0, 8, backing_blob_ids=(digest,))

    assert memory.mapped_pages() == ()
    assert memory.reserved_pages()[0].backing_blob_id == digest
    assert memory.read(0, 8) == expected
    assert memory.reserved_pages() == ()
    assert memory.mapped_pages()[0].blob_id == digest

    receipt = backing.read_receipt(digest)
    assert receipt is not None
    assert receipt.memory_id == "page-memory"
    assert receipt.revision == 1
    assert receipt.length == 8
    assert receipt.content_digest == digest
    assert len(receipt.value_receipt_ids) == 8


def test_structural_memory_page_backing_bounds_host_cache_and_reuses_verified_ranges() -> None:
    operating_system = _operating_system()
    version = _admit_byte_memory(operating_system)
    backing = StructuralMemoryPageBacking(operating_system.structural_memory)
    pages: list[tuple[str, bytes]] = []
    for page_index in range(5):
        coordinate_start = page_index * 8
        expected = bytes((65 + coordinate_start + offset) & 0xFF for offset in range(8))
        digest = hashlib.sha256(expected).hexdigest()
        backing.register_page_reference(
            digest,
            _page_reference(version, start=coordinate_start, size=8),
        )
        pages.append((digest, expected))

    for digest, expected in pages[:4]:
        assert backing.get_page(digest) == expected
    original_receipts = {
        digest: backing.read_receipt(digest)
        for digest, _expected in pages[:4]
    }
    assert all(receipt is not None for receipt in original_receipts.values())

    # A cache hit increases the observed reuse score without changing bytes.
    first_digest, first_expected = pages[0]
    score_before = backing._retention_score(first_digest)
    assert backing.get_page(first_digest) == first_expected
    assert backing._retention_score(first_digest) >= score_before * 2

    # The fifth candidate may itself be the lowest-value page. The weighted
    # policy must retain exactly four of the five and evict the minimum score,
    # not unconditionally displace an older page.
    assert backing.get_page(pages[4][0]) == pages[4][1]
    assert backing.cached_page_count == 4
    assert backing.cached_page_bytes == 4 * 8
    assert backing.cached_receipt_coordinate_count == 4 * 8
    assert backing.cached_provider_coordinate_count == 0
    original_all = {
        digest: (expected, receipt)
        for (digest, expected), receipt in zip(pages[:4], original_receipts.values())
    }
    original_all[pages[4][0]] = (pages[4][1], backing.read_receipt(pages[4][0]))
    evicted = [
        (digest, expected, receipt)
        for digest, (expected, receipt) in original_all.items()
        if backing.read_receipt(digest) is None
    ]
    assert len(evicted) == 1
    evicted_digest, evicted_expected, old_receipt = evicted[0]
    assert old_receipt is not None

    # Re-faulting whichever candidate lost the retention competition
    # regenerates identical bytes and the same immutable receipt identity.
    assert backing.get_page(evicted_digest) == evicted_expected
    regenerated = backing.read_receipt(evicted_digest)
    assert regenerated is not None
    assert regenerated.receipt_id == old_receipt.receipt_id
    assert len(regenerated.value_receipt_ids) == 8
    assert backing.cached_page_count == 4
    assert backing.cached_provider_coordinate_count == 0
    assert operating_system.environment.kernel.journal.verify()


def test_structural_memory_page_fault_preserves_copy_on_write_identity() -> None:
    operating_system = _operating_system()
    version = _admit_byte_memory(operating_system)
    expected = b"ABCDEFGH"
    digest = hashlib.sha256(expected).hexdigest()
    backing = StructuralMemoryPageBacking(operating_system.structural_memory)
    backing.register_page_reference(digest, _page_reference(version))

    original = VirtualMemory(page_size=8, page_backing=backing)
    original.reserve(0, 8, backing_blob_ids=(digest,))
    assert original.read(0, 8) == expected

    clone = original.clone()
    clone.write(1, b"Z")

    assert original.read(0, 8) == expected
    assert clone.read(0, 8) == b"AZCDEFGH"
    assert original.mapped_pages()[0].blob_id == digest
    assert clone.mapped_pages()[0].blob_id == hashlib.sha256(b"AZCDEFGH").hexdigest()
    assert backing.get_page(digest) == expected


def test_failed_structural_page_resolution_does_not_consume_any_reservation() -> None:
    operating_system = _operating_system()
    version = _admit_byte_memory(operating_system)
    reference = _page_reference(version)
    valid = b"ABCDEFGH"
    valid_digest = hashlib.sha256(valid).hexdigest()
    wrong_digest = hashlib.sha256(b"XXXXXXXX").hexdigest()
    backing = StructuralMemoryPageBacking(operating_system.structural_memory)
    backing.register_page_reference(valid_digest, reference)
    backing.register_page_reference(wrong_digest, reference)

    memory = VirtualMemory(page_size=8, page_backing=backing)
    memory.reserve(0, 16, backing_blob_ids=(valid_digest, wrong_digest))
    before = memory.snapshot()

    with pytest.raises(VirtualMemoryError, match="page backing could not resolve"):
        memory.read(0, 16)

    assert memory.snapshot() == before
    assert tuple(item.page_number for item in memory.reserved_pages()) == (0, 1)
    assert memory.mapped_pages() == ()


def test_backed_reservation_validates_reference_page_geometry_before_mutation() -> None:
    operating_system = _operating_system()
    version = _admit_byte_memory(operating_system)
    digest = hashlib.sha256(b"ABCDEFGH").hexdigest()
    backing = StructuralMemoryPageBacking(operating_system.structural_memory)
    backing.register_page_reference(digest, _page_reference(version))

    memory = VirtualMemory(page_size=16, page_backing=backing)
    before = memory.snapshot()
    with pytest.raises(VirtualMemoryError, match="page size"):
        memory.reserve(0, 16, backing_blob_ids=(digest,))
    assert memory.snapshot() == before

    unbacked = VirtualMemory(page_size=8)
    before_unbacked = unbacked.snapshot()
    with pytest.raises(VirtualMemoryError, match="attached page backing"):
        unbacked.reserve(0, 8, backing_blob_ids=(digest,))
    assert unbacked.snapshot() == before_unbacked


def test_reclaimed_cow_pages_are_persisted_and_snapshot_as_local_content() -> None:
    operating_system = _operating_system()
    version = _admit_byte_memory(operating_system)
    expected = b"ABCDEFGH"
    digest = hashlib.sha256(expected).hexdigest()
    backing = StructuralMemoryPageBacking(operating_system.structural_memory)
    backing.register_page_reference(digest, _page_reference(version))

    memory = VirtualMemory(page_size=8, page_backing=backing)
    memory.reserve(0, 8, backing_blob_ids=(digest,))
    assert memory.read(0, 8) == expected
    memory.write(2, b"Z")
    changed = b"ABZDEFGH"
    changed_digest = hashlib.sha256(changed).hexdigest()

    assert memory.reclaim(page_numbers=(0,)) == (0,)
    assert memory.reserved_pages()[0].backing_blob_id == changed_digest

    restored_backing = StructuralMemoryPageBacking.from_snapshot(backing.snapshot())
    assert restored_backing.get_page(changed_digest) == changed
    assert restored_backing.page_size_for(changed_digest) == 8


def test_headless_checkpoint_restores_inert_page_references_then_rebinds_registry() -> None:
    operating_system = _operating_system()
    version = _admit_byte_memory(operating_system)
    expected = b"ABCDEFGH"
    digest = hashlib.sha256(expected).hexdigest()
    operating_system.register_structural_memory_page(digest, _page_reference(version))

    pid = operating_system.vm.spawn_program(
        Program((Instruction(Op.HALT),)),
        "structural-page",
        page_size=8,
    )
    operating_system.vm.memories[pid].reserve(16, 8, backing_blob_ids=(digest,))

    restored = HeadlessOS.from_snapshot(
        operating_system.snapshot(),
        structural_memory_admission_policy=lambda proposal: proposal.spec.domain == "byte-stream",
    )
    reservation = restored.vm.memories[pid].reserved_pages()[0]
    assert reservation.backing_blob_id == digest
    assert restored.vm.page_backing.get_page(digest) == expected
    assert restored.vm.memories[pid].read(16, 8) == expected
    receipt = restored.vm.page_backing.read_receipt(digest)
    assert receipt is not None and receipt.content_digest == digest
    assert restored.environment.kernel.journal.verify()



def test_local_page_identity_cannot_be_rebound_to_structural_reference() -> None:
    operating_system = _operating_system()
    version = _admit_byte_memory(operating_system)
    backing = StructuralMemoryPageBacking(operating_system.structural_memory)
    local_data = b"XXXXXXXX"
    local_digest = backing.put_page(local_data)

    with pytest.raises(ValueError, match="already backed by local page content"):
        backing.register_page_reference(local_digest, _page_reference(version))


def test_non_structural_page_backing_snapshot_contract_remains_unchanged() -> None:
    class ExternalPageBacking:
        def put_page(self, data: bytes) -> str:
            return hashlib.sha256(data).hexdigest()

        def get_page(self, digest: str) -> bytes:
            raise KeyError(digest)

        def snapshot(self) -> dict[str, str]:
            return {"provider_type": "external_page_store", "version": "opaque"}

    machine = MailCPUVirtualMachine(page_backing=ExternalPageBacking())
    assert "page_backing_state" not in machine.snapshot()
