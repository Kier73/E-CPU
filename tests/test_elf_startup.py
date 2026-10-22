from __future__ import annotations

import struct

import pytest

from mailcpu import ElfError, VirtualMemory, materialize_startup_stack, parse_elf
from mailcpu.memory import VirtualMemoryError

from test_elf import _elf64_fixture


def _startup():
    """Mathematics: construct one valid `(I,M,L,A)` startup relation for stack-layout tests."""

    image = parse_elf(_elf64_fixture())
    memory = VirtualMemory()
    load = image.load_into(memory, base=0x400000)
    return image.startup_state(load), memory


def test_startup_stack_materializes_aligned_vectors_and_auxiliary_state() -> None:
    """Mathematics: startup memory is `[argc,argv,NULL,envp,NULL,auxv,strings]` with every pointer inside the committed mapping."""

    startup, memory = _startup()
    layout = materialize_startup_stack(
        memory,
        startup,
        argv=("app", "argument"),
        environment={"Z": "last", "A": "first"},
        stack_top=0x9000,
    )
    assert layout.stack_pointer % 16 == 0
    assert struct.unpack("<Q", memory.read(layout.stack_pointer, 8))[0] == 2
    argv_pointers = struct.unpack("<QQQ", memory.read(layout.argv_address, 24))
    assert argv_pointers[2] == 0
    assert memory.read(argv_pointers[0], 4) == b"app\x00"
    assert memory.read(argv_pointers[1], 9) == b"argument\x00"
    env_pointers = struct.unpack("<QQQ", memory.read(layout.envp_address, 24))
    assert env_pointers[2] == 0
    assert memory.read(env_pointers[0], 8) == b"A=first\x00"
    assert memory.read(env_pointers[1], 7) == b"Z=last\x00"
    auxiliary_count = len(startup.auxiliary_vector)
    assert memory.read(layout.auxiliary_address, auxiliary_count * 16) == b"".join(
        struct.pack("<QQ", tag, value) for tag, value in startup.auxiliary_vector
    )
    for pointer in (*argv_pointers[:2], *env_pointers[:2]):
        assert layout.mapping_start <= pointer < layout.mapping_start + layout.mapping_length


def test_startup_stack_failure_preserves_original_memory() -> None:
    """Mathematics: failed stack mapping satisfies `M_after=M_before` because all writes target an uncommitted clone."""

    startup, memory = _startup()
    memory.map(0x7000, 0x2000)
    before = memory.snapshot()
    with pytest.raises(VirtualMemoryError):
        materialize_startup_stack(memory, startup, argv=("app",), stack_top=0x9000)
    assert memory.snapshot() == before


def test_startup_stack_rejects_invalid_environment_before_mapping() -> None:
    """Mathematics: an invalid environment key lies outside the serialization domain and cannot publish any stack pages."""

    startup, memory = _startup()
    before = memory.snapshot()
    with pytest.raises(ElfError, match="environment"):
        materialize_startup_stack(memory, startup, environment={"BAD-KEY": "value"}, stack_top=0x9000)
    assert memory.snapshot() == before
