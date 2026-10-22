from __future__ import annotations

from dataclasses import replace

import pytest

from mailcpu import DynamicLinker, ElfDynamicInfo, ElfError, ElfImage, ElfSymbol, LinkerError, VirtualMemory, parse_elf
from mailcpu.elf import PF_W

from test_dynamic_elf import _dynamic_fixture


def _static_provider() -> ElfImage:
    """Mathematics: project a validated static segment image into a dependency provider with `dynamic=∅`."""

    parsed = parse_elf(_dynamic_fixture())
    return replace(parsed, has_dynamic_segment=False, dynamic=None)


def _main_with_defined_provider_symbol() -> tuple[ElfImage, ElfImage]:
    """Mathematics: construct `main→libdep` where `main` has undefined `extern` and `libdep` defines it at `st_value=0x100`."""

    main = parse_elf(_dynamic_fixture(with_symbol=True))
    writable_segments = tuple(replace(segment, flags=segment.flags | PF_W) for segment in main.segments)
    main = replace(main, segments=writable_segments)
    provider_base = _static_provider()
    provider_dynamic = ElfDynamicInfo(
        needed=(),
        soname="libdep.so",
        rpath=None,
        runpath=None,
        symbols=(ElfSymbol(1, "extern", 0x100, 0, 0x10, 0, 1),),
        relocations=(),
        string_table_address=None,
        string_table_size=None,
        symbol_table_address=None,
        symbol_entry_size=None,
    )
    provider = replace(provider_base, has_dynamic_segment=True, dynamic=provider_dynamic)
    return main, provider


def test_dynamic_linker_resolves_provider_and_applies_relocation_transactionally() -> None:
    """Mathematics: `link(main,provider)` stages both images and writes `B[extern]+addend` at the planned writable target."""

    main, provider = _main_with_defined_provider_symbol()
    memory = VirtualMemory()
    result = DynamicLinker({"libdep.so": provider}).link(main, memory, name="app", base=0x400000)
    assert result.main.name == "app"
    assert result.dependencies[0].name == "libdep.so"
    assert result.dependencies[0].base == 0x403000
    expected = (0x403000 + 0x100 + 5).to_bytes(8, "little")
    assert memory.read(0x400508, 8) == expected


def test_dynamic_linker_missing_provider_and_readonly_target_preserve_memory(tmp_path) -> None:
    """Mathematics: failed `link` leaves caller state `M` invariant when `provider∉D` or `write(target)` is not admitted."""

    main, provider = _main_with_defined_provider_symbol()
    memory = VirtualMemory()
    memory.map(0, 4096)
    before = memory.snapshot()
    with pytest.raises(LinkerError, match="dependency"):
        DynamicLinker({}).link(main, memory, base=0x400000)
    assert memory.snapshot() == before

    readonly_main = replace(main, segments=tuple(replace(segment, flags=segment.flags & ~PF_W) for segment in main.segments))
    with pytest.raises(LinkerError, match="writable"):
        DynamicLinker({"libdep.so": provider}).link(readonly_main, memory, base=0x400000)
    assert memory.snapshot() == before


def test_dynamic_linker_rejects_unsupported_relocation_before_memory_commit() -> None:
    """Mathematics: an unadmitted relocation type is outside the linker action algebra and cannot alter caller memory."""

    main = parse_elf(_dynamic_fixture())
    dynamic = main.dynamic
    assert dynamic is not None
    relocation = replace(dynamic.relocations[0], relocation_type=999)
    unsupported = replace(main, dynamic=replace(dynamic, relocations=(relocation,)))
    memory = VirtualMemory()
    before = memory.snapshot()
    with pytest.raises(LinkerError, match="unsupported relocation"):
        DynamicLinker({"libdep.so": _static_provider()}).link(unsupported, memory, base=0x400000)
    assert memory.snapshot() == before
