from __future__ import annotations

import struct

import pytest

from mailcpu import (
    ArtifactIngestionError,
    ArtifactKind,
    ExecutableImage,
    ingest_bytes,
    ingest_path,
)


def _elf64_fixture(dynamic: bool = False) -> bytes:
    """Mathematics: construct a bounded ELF64 projection with congruent load intervals and optional `PT_DYNAMIC` metadata."""

    header = struct.Struct("<16sHHIQQQIHHHHHH")
    program_header = struct.Struct("<IIQQQQQQ")
    program_count = 3 if dynamic else 2
    payload = bytearray(0x2004)
    ident = b"\x7fELF" + bytes((2, 1, 1)) + b"\0" * 9
    payload[: header.size] = header.pack(
        ident,
        3,
        62,
        1,
        0x100,
        header.size,
        0,
        0,
        header.size,
        program_header.size,
        program_count,
        0,
        0,
        0,
    )
    payload[header.size : header.size + program_header.size] = program_header.pack(
        1,
        5,
        0x1000,
        0,
        0,
        7,
        0x1000,
        0x1000,
    )
    payload[header.size + program_header.size : header.size + 2 * program_header.size] = program_header.pack(
        1,
        6,
        0x2000,
        0x2000,
        0,
        4,
        0x2000,
        0x1000,
    )
    if dynamic:
        payload[header.size + 2 * program_header.size : header.size + 3 * program_header.size] = program_header.pack(
            2,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
        )
    payload[0x1000:0x1007] = b"MAILCPU"
    payload[0x2000:0x2004] = b"DATA"
    return bytes(payload)


def test_ingestion_unifies_assembly_and_bytecode_into_one_validated_image() -> None:
    """Mathematics: `ingest(assembly)` and `ingest(MCPB(assembly))` yield equal validated program graphs and content identity."""

    source = b"set left 20\nset right 22\nadd result left right\nhalt\n"
    assembly = ingest_bytes(source, "answer.mca")
    bytecode = ingest_bytes(assembly.require_image().bytecode or b"", "answer.mcpb")
    assert assembly.kind is ArtifactKind.ASSEMBLY
    assert bytecode.kind is ArtifactKind.BYTECODE
    assert assembly.require_image().program == bytecode.require_image().program
    assert assembly.content_digest == bytecode.content_digest
    assert assembly.source_digest != bytecode.source_digest


def test_ingestion_preserves_elf_loader_metadata_without_fabricating_execution() -> None:
    """Mathematics: `ingest(ELF)` preserves `digest`, machine, segment count, and `PT_DYNAMIC` projection as an `ElfImage` only."""

    artifact = ingest_bytes(_elf64_fixture(dynamic=True), "native.elf")
    assert artifact.kind is ArtifactKind.ELF
    assert artifact.image is None
    assert artifact.elf is not None
    assert artifact.elf.has_dynamic_segment is True
    assert artifact.report()["dynamic"] is True
    with pytest.raises(ArtifactIngestionError, match="no MailCPU executable image"):
        artifact.require_image()


def test_ingestion_rejects_invalid_input_before_output_creation(tmp_path) -> None:
    """Mathematics: invalid `x∉dom(ingest)` has no image and cannot produce an output path."""

    source = tmp_path / "broken.mca"
    output = tmp_path / "broken.mcp.json"
    source.write_bytes(b"not an opcode\n")
    with pytest.raises(ArtifactIngestionError):
        ingest_path(source)
    assert not output.exists()


def test_ingested_image_save_round_trips_through_existing_image_validator(tmp_path) -> None:
    """Mathematics: `load(save(ingest(S)))` preserves the admitted image graph and compiled digest."""

    artifact = ingest_bytes(b"halt\n", "idle.mca")
    destination = tmp_path / "idle.mcp.json"
    artifact.save(destination)
    restored = ExecutableImage.load(destination)
    assert restored == artifact.require_image()
