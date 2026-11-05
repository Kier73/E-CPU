from __future__ import annotations

import pytest

from mailcpu import HeadlessOS, StructuralMemoryFileRef
from mailcpu.fs import FsError
from mailcpu.law_certifier import Law


def _operating_system() -> HeadlessOS:
    """Create a host whose structural-memory admission policy is explicitly rebound."""
    return HeadlessOS(
        structural_memory_admission_policy=lambda proposal: proposal.spec.domain == "byte-stream"
    )


def _admit_byte_memory(operating_system: HeadlessOS, *, memory_id: str = "byte-memory", x0: int = 65, mod: int = 256):
    """Admit one verified modular byte progression with a fixed context."""
    law = Law(
        family="int",
        params={"x0": x0, "step": 1, "mod": mod},
        order=1,
        verdict="GROUND",
    )
    witnesses = {coordinate: (x0 + coordinate) % mod for coordinate in range(8)}
    proposal = operating_system.structural_memory.propose(
        memory_id,
        law,
        witnesses,
        domain="byte-stream",
        context={"dataset": "alpha", "encoding": "raw-byte"},
    )
    return operating_system.structural_memory.admit(proposal.proposal_id, expected_revision=0)


def _reference(version, *, start: int = 0, size: int = 8) -> StructuralMemoryFileRef:
    return StructuralMemoryFileRef.from_version(version, coordinate_start=start, size=size)


def _read_revision_events(operating_system: HeadlessOS):
    return [
        record for record in operating_system.environment.kernel.journal.records()
        if record.kind == "structural_memory.read_revision"
    ]


def test_structural_memory_file_reads_bounded_byte_slices_with_provenance() -> None:
    operating_system = _operating_system()
    version = _admit_byte_memory(operating_system)
    reference = _reference(version)
    path = operating_system.register_structural_memory_file("/data/model.bin", reference)

    provider = operating_system.environment.kernel.fs.providers.structural_memory_providers()[0]
    first, receipt = provider.read_with_receipt(2, 4)
    assert first == b"CDEF"
    assert receipt.memory_id == "byte-memory"
    assert receipt.revision == 1
    assert receipt.offset == 2
    assert receipt.length == 4
    assert receipt.coordinate_start == 2
    assert len(receipt.content_digest) == 64
    assert len(receipt.value_receipt_ids) == 4

    assert operating_system.environment.kernel.fs.read_file(path, 2, 4) == b"CDEF"
    assert operating_system.environment.kernel.fs.read_file(path, 6, 20) == b"GH"
    assert len(_read_revision_events(operating_system)) == 6
    assert operating_system.environment.kernel.journal.verify()


def test_structural_memory_file_is_read_only_and_enforces_provider_read_bound() -> None:
    operating_system = _operating_system()
    version = _admit_byte_memory(operating_system)
    path = operating_system.register_structural_memory_file(
        "/data/read-only.bin",
        _reference(version),
        max_read_bytes=4,
    )

    with pytest.raises(FsError, match="procedural file is read-only"):
        operating_system.environment.kernel.fs.write_file(path, b"overwrite")
    with pytest.raises(FsError, match="max_read_bytes"):
        operating_system.environment.kernel.fs.read_file(path, 0, 5)


def test_structural_memory_file_refuses_digest_context_and_non_byte_mismatches() -> None:
    operating_system = _operating_system()
    version = _admit_byte_memory(operating_system)
    wrong_digest = StructuralMemoryFileRef(
        version.spec.memory_id,
        version.spec.revision,
        version.spec.context,
        0,
        8,
        "0" * 64,
        version.certificate.digest,
    )
    path = operating_system.register_structural_memory_file("/data/bad-digest.bin", wrong_digest)
    with pytest.raises(FsError, match="does not match the pinned byte-file reference"):
        operating_system.environment.kernel.fs.read_file(path, 0, 1)

    wrong_context = StructuralMemoryFileRef(
        version.spec.memory_id,
        version.spec.revision,
        {"dataset": "other", "encoding": "raw-byte"},
        0,
        8,
        version.spec.digest,
        version.certificate.digest,
    )
    path = operating_system.register_structural_memory_file("/data/bad-context.bin", wrong_context)
    with pytest.raises(FsError, match="could not be read"):
        operating_system.environment.kernel.fs.read_file(path, 0, 1)

    other_os = _operating_system()
    other_version = _admit_byte_memory(other_os, memory_id="wide-integer-memory", x0=500, mod=1000)
    other_path = other_os.register_structural_memory_file(
        "/data/non-byte.bin",
        _reference(other_version),
    )
    with pytest.raises(FsError, match="does not match the pinned byte-file reference"):
        other_os.environment.kernel.fs.read_file(other_path, 0, 1)


def test_structural_memory_file_provider_rebinds_after_headless_checkpoint_restore() -> None:
    operating_system = _operating_system()
    version = _admit_byte_memory(operating_system)
    reference = _reference(version)
    path = operating_system.register_structural_memory_file("/data/checkpoint.bin", reference)
    assert operating_system.environment.kernel.fs.read_file(path, 0, 4) == b"ABCD"

    restored = HeadlessOS.from_snapshot(
        operating_system.snapshot(),
        structural_memory_admission_policy=lambda proposal: proposal.spec.domain == "byte-stream",
    )
    assert restored.structural_memory.active_version("byte-memory") == version
    assert restored.environment.kernel.fs.read_file(path, 3, 4) == b"DEFG"
    assert restored.environment.kernel.journal.verify()
