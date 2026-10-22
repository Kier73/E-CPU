from __future__ import annotations

import struct

import pytest

from mailcpu import ElfError, parse_elf


def _dynamic_fixture(with_symbol: bool = False) -> bytes:
    """Mathematics: construct a page-congruent ELF64 image whose dynamic relation contains dependency strings and RELA records."""

    header = struct.Struct("<16sHHIQQQIHHHHHH")
    program_header = struct.Struct("<IIQQQQQQ")
    dynamic_entry = struct.Struct("<qQ")
    rela_entry = struct.Struct("<QQq")
    symbol_entry = struct.Struct("<IBBHQQ")
    payload = bytearray(0x2200)
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
        3,
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
        0x700,
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
        0x1000,
        0x1000,
    )

    strings = b"\0libdep.so\0app.so\0extern\0"
    string_offset = 0x500
    payload[0x1000 + string_offset : 0x1000 + string_offset + len(strings)] = strings
    needed_offset = 1
    soname_offset = 11
    extern_offset = strings.index(b"extern")

    dynamic_address = 0x300
    dynamic_offset = 0x1000 + dynamic_address
    rela_address = 0x3C0
    rela_offset = 0x1000 + rela_address
    symbol_address = 0x440
    symbol_offset = 0x1000 + symbol_address
    rela_count = 2 if with_symbol else 1
    dynamic_records = [
        (5, string_offset),
        (10, len(strings)),
        (1, needed_offset),
        (14, soname_offset),
        (7, rela_address),
        (8, rela_count * rela_entry.size),
        (9, rela_entry.size),
    ]
    if with_symbol:
        dynamic_records.extend(((6, symbol_address), (11, symbol_entry.size)))
    dynamic_records.append((0, 0))
    for index, values in enumerate(dynamic_records):
        dynamic_entry.pack_into(payload, dynamic_offset + index * dynamic_entry.size, *values)
    rela_entry.pack_into(payload, rela_offset, 0x500, 8, 0x123)
    if with_symbol:
        symbol_entry.pack_into(payload, symbol_offset, 0, 0, 0, 0, 0, 0)
        symbol_entry.pack_into(payload, symbol_offset + symbol_entry.size, extern_offset, 0x10, 0, 0, 0, 0)
        rela_entry.pack_into(payload, rela_offset + rela_entry.size, 0x508, (1 << 32) | 1, 5)

    payload[header.size + 2 * program_header.size : header.size + 3 * program_header.size] = program_header.pack(
        2,
        0,
        dynamic_offset,
        dynamic_address,
        0,
        len(dynamic_records) * dynamic_entry.size,
        len(dynamic_records) * dynamic_entry.size,
        8,
    )
    payload[0x1000:0x1007] = b"MAILCPU"
    payload[0x2000:0x2004] = b"DATA"
    return bytes(payload)


def test_dynamic_elf_parses_dependencies_and_relative_relocation_plan() -> None:
    """Mathematics: `DT_NEEDED` resolves through `DT_STRTAB`, and `R_X86_64_RELATIVE` yields `base+addend` without external binding."""

    image = parse_elf(_dynamic_fixture())
    assert image.dynamic is not None
    assert image.dynamic.needed == ("libdep.so",)
    assert image.dynamic.soname == "app.so"
    assert len(image.dynamic.relocations) == 1
    plan = image.plan_relocations(base=0x400000)
    assert plan.dependencies == ("libdep.so",)
    assert plan.actions[0].target_address == 0x400500
    assert plan.actions[0].value == 0x400123


def test_dynamic_elf_requires_explicit_external_symbol_binding() -> None:
    """Mathematics: an undefined `R_SYMBOL(name)` is not assigned zero; `B[name]` must be supplied before a plan exists."""

    image = parse_elf(_dynamic_fixture(with_symbol=True))
    assert image.dynamic is not None
    assert image.dynamic.symbols[1].name == "extern"
    with pytest.raises(ElfError, match="unresolved dynamic symbol"):
        image.plan_relocations(base=0x400000)
    plan = image.plan_relocations(base=0x400000, bindings={"extern": 0x500000})
    assert plan.actions[-1].symbol_name == "extern"
    assert plan.actions[-1].value == 0x500005


def test_dynamic_elf_rejects_unterminated_dynamic_table() -> None:
    """Mathematics: absence of `DT_NULL` leaves `D` outside the terminated dynamic-table domain and refuses planning."""

    payload = bytearray(_dynamic_fixture())
    # The final dynamic record is DT_NULL at file offset 0x1370; turn its tag
    # into an ordinary tag without supplying a second terminator.
    struct.pack_into("<qQ", payload, 0x1370, 5, 0x380)
    with pytest.raises(ElfError, match="DT_NULL"):
        parse_elf(bytes(payload))
