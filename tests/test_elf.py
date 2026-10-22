from __future__ import annotations

import struct

import pytest

from mailcpu import ElfError, HeadlessOS, parse_elf
from mailcpu import VirtualMemoryError
from mailcpu.memory import VirtualMemory


def _elf64_fixture() -> bytes:
    """Mathematics: construct a bounded ELF64 image with two page-congruent `PT_LOAD` intervals and deterministic file bytes."""

    header = struct.Struct("<16sHHIQQQIHHHHHH")
    program_header = struct.Struct("<IIQQQQQQ")
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
        2,
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
    payload[0x1000:0x1007] = b"MAILCPU"
    payload[0x2000:0x2004] = b"DATA"
    return bytes(payload)


def _elf32_fixture() -> bytes:
    """Mathematics: construct a bounded ELF32 image satisfying `offset ≡ vaddr (mod 4096)` for its load segment."""

    header = struct.Struct("<16sHHIIIIIHHHHHH")
    program_header = struct.Struct("<IIIIIIII")
    payload = bytearray(0x1003)
    ident = b"\x7fELF" + bytes((1, 1, 1)) + b"\0" * 9
    payload[: header.size] = header.pack(
        ident,
        2,
        3,
        1,
        0x100,
        header.size,
        0,
        0,
        header.size,
        program_header.size,
        1,
        0,
        0,
        0,
    )
    payload[header.size : header.size + program_header.size] = program_header.pack(
        1,
        0x1000,
        0,
        0,
        3,
        0x1000,
        5,
        0x1000,
    )
    payload[0x1000:0x1003] = b"32!"
    return bytes(payload)


def test_elf_parser_accepts_32_and_64_bit_images_and_stages_permissions() -> None:
    """Mathematics: `parse_elf` preserves class/machine/segments, and load realizes bytes, zero-fill, and page `W` projections."""

    image32 = parse_elf(_elf32_fixture())
    assert image32.bits == 32
    assert image32.machine_name == "i386"
    assert image32.entry == 0x100

    image = parse_elf(_elf64_fixture())
    assert image.bits == 64
    assert image.machine_name == "x86_64"
    assert image.program_header_entry_size == 56
    assert image.program_header_count == 2
    memory = VirtualMemory()
    result = image.load_into(memory, base=0x400000)
    assert result.entry == 0x400100
    assert memory.read(0x400000, 7) == b"MAILCPU"
    assert memory.read(0x402000, 4) == b"DATA"
    assert memory.read(0x402004, 32) == b"\0" * 32
    assert 0x400000 // 4096 not in result.writable_pages
    assert 0x402000 // 4096 in result.writable_pages
    with pytest.raises(VirtualMemoryError, match="read-only"):
        memory.write(0x400000, b"X")
    memory.write(0x402000, b"OK")
    assert memory.read(0x402000, 2) == b"OK"
    startup = image.startup_state(result)
    assert startup.main_entry == 0x400100
    assert startup.initial_entry == 0x400100
    assert dict(startup.auxiliary_vector)[4] == 56
    assert dict(startup.auxiliary_vector)[5] == 2
    assert dict(startup.auxiliary_vector)[9] == 0x400100
    assert startup.auxiliary_vector[-1] == (0, 0)


def test_headless_os_loads_elf_segments_into_process_memory_without_fake_execution() -> None:
    """Mathematics: `load_elf_image(pid,path)` commits a validated `M_pid` projection and journals `entry`, while scheduler execution remains a separate backend relation."""

    os = HeadlessOS()
    pid = os.launch_source("halt\n", "elf-loader")
    os.environment.kernel.fs.create_file("/tmp/program.elf", _elf64_fixture(), mode=0o755)
    result = os.load_elf_image(pid, "/tmp/program.elf")
    assert result.entry == 0x400100
    assert os.vm.memories[pid].read(0x400000, 7) == b"MAILCPU"
    assert any(record.kind == "elf.load" for record in os.environment.kernel.journal.records())
    os.run()
    assert os.process(pid).status == "exited"


def test_elf_parser_refuses_a_foreign_machine() -> None:
    """Mathematics: `machine ∉ MACHINE_NAMES` places the image outside `parse_elf`'s domain, so admission fails closed instead of admitting foreign code."""

    foreign = bytearray(_elf64_fixture())
    foreign[18:20] = (8).to_bytes(2, "little")
    with pytest.raises(ElfError, match="unsupported ELF machine"):
        parse_elf(bytes(foreign))


def test_elf_parser_rejects_truncation_and_invalid_segment_overlap() -> None:
    """Mathematics: malformed bytes cannot enter the loader domain, and overlapping `PT_LOAD` intervals violate disjoint segment ownership."""

    with pytest.raises(ElfError, match="outside"):
        parse_elf(_elf64_fixture()[:-1])
    invalid = bytearray(_elf64_fixture())
    second_header = struct.Struct("<IIQQQQQQ")
    second_offset = 64 + second_header.size
    invalid[second_offset + 16 : second_offset + 24] = (0x800).to_bytes(8, "little")
    with pytest.raises(ElfError, match="congruence"):
        parse_elf(bytes(invalid))
