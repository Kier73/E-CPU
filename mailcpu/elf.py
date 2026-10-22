"""Strict ELF program-header parsing and virtual-memory staging for MailCPU."""

from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING, Mapping, Sequence

if TYPE_CHECKING:
    from .memory import VirtualMemory


class ElfError(ValueError):
    """Exception for an invalid ELF payload or loader invariant failure."""


PT_LOAD = 1
PT_DYNAMIC = 2
PT_INTERP = 3
PT_PHDR = 6
PT_GNU_STACK = 0x6474E551
PF_X = 0x1
PF_W = 0x2
PF_R = 0x4
ET_EXEC = 2
ET_DYN = 3
ELF_PAGE_SIZE = 4096
AT_PHDR = 3
AT_PHENT = 4
AT_PHNUM = 5
AT_PAGESZ = 6
AT_BASE = 7
AT_FLAGS = 8
AT_ENTRY = 9
AT_NULL = 0
MAX_PROGRAM_HEADERS = 4096
MAX_INTERPRETER_BYTES = 4096
MACHINE_NAMES = {
    3: "i386",
    40: "ARM",
    62: "x86_64",
    183: "AArch64",
    243: "RISC-V",
}

DT_NULL = 0
DT_NEEDED = 1
DT_PLTRELSZ = 2
DT_STRTAB = 5
DT_STRSZ = 10
DT_SYMTAB = 6
DT_SYMENT = 11
DT_RELA = 7
DT_RELASZ = 8
DT_RELAENT = 9
DT_SONAME = 14
DT_RPATH = 15
DT_SYMBOLIC = 16
DT_REL = 17
DT_RELSZ = 18
DT_RELENT = 19
DT_PLTREL = 20
DT_JMPREL = 23
DT_RUNPATH = 29
DT_HASH = 4
DT_GNU_HASH = 0x6FFFFEF5
MAX_DYNAMIC_ENTRIES = 1_000_000
MAX_DYNAMIC_STRINGS = 1_048_576

_RELATIVE_TYPES = {3: {8}, 40: {23}, 62: {8}, 183: {1027}, 243: {3}}
_SYMBOL_RELOCATION_TYPES = {
    3: {1, 6, 7},
    40: {2, 21, 22},
    62: {1, 6, 7},
    183: {257, 1025, 1026},
    243: {2, 5, 6},
}


@dataclass(frozen=True)
class ElfSegment:
    """One validated ELF program-header projection and its file-backed bytes."""

    segment_type: int
    flags: int
    offset: int
    virtual_address: int
    physical_address: int
    file_size: int
    memory_size: int
    alignment: int
    data: bytes

    @property
    def readable(self) -> bool:
        """Mathematics: project `R=[PF_R∈flags]` from the ELF segment permission algebra."""

        return bool(self.flags & PF_R)

    @property
    def writable(self) -> bool:
        """Mathematics: project `W=[PF_W∈flags]` from the ELF segment permission algebra."""

        return bool(self.flags & PF_W)

    @property
    def executable(self) -> bool:
        """Mathematics: project `X=[PF_X∈flags]` from the ELF segment permission algebra."""

        return bool(self.flags & PF_X)


@dataclass(frozen=True)
class ElfLoadResult:
    """The deterministic result of mapping one validated ELF image into virtual memory."""

    entry: int
    load_bias: int
    machine: str
    bits: int
    interpreter: str | None
    mapped_pages: tuple[int, ...]
    writable_pages: tuple[int, ...]
    executable_pages: tuple[int, ...]


@dataclass(frozen=True)
class ElfStartupState:
    """Deterministic ELF handoff metadata for a future instruction backend."""

    main_entry: int
    initial_entry: int
    interpreter: str | None
    interpreter_base: int | None
    auxiliary_vector: tuple[tuple[int, int], ...]


@dataclass(frozen=True)
class ElfStackLayout:
    """Addresses and extent of one materialized x86-64 ELF startup stack."""

    stack_pointer: int
    argc: int
    argv_address: int
    envp_address: int
    auxiliary_address: int
    mapping_start: int
    mapping_length: int


@dataclass(frozen=True)
class ElfSymbol:
    """One dynamic symbol-table record with its resolved string-table name."""

    index: int
    name: str
    value: int
    size: int
    info: int
    other: int
    section_index: int

    @property
    def defined(self) -> bool:
        """Mathematics: a symbol is locally defined exactly when `st_shndx≠SHN_UNDEF=0`."""

        return self.section_index != 0


@dataclass(frozen=True)
class ElfRelocation:
    """One REL or RELA dynamic relocation before runtime binding."""

    offset: int
    relocation_type: int
    symbol_index: int
    addend: int | None
    symbol_name: str | None


@dataclass(frozen=True)
class ElfDynamicInfo:
    """Parsed dynamic loader metadata and relocation relation for one ELF image."""

    needed: tuple[str, ...]
    soname: str | None
    rpath: str | None
    runpath: str | None
    symbols: tuple[ElfSymbol, ...]
    relocations: tuple[ElfRelocation, ...]
    string_table_address: int | None
    string_table_size: int | None
    symbol_table_address: int | None
    symbol_entry_size: int | None


@dataclass(frozen=True)
class RelocationAction:
    """A resolved write intent produced without mutating virtual memory."""

    target_address: int
    relocation_type: int
    symbol_name: str | None
    addend: int
    value: int


@dataclass(frozen=True)
class DynamicLinkPlan:
    """A deterministic, dependency-preserving relocation plan awaiting a linker write phase."""

    load_bias: int
    dependencies: tuple[str, ...]
    actions: tuple[RelocationAction, ...]


@dataclass(frozen=True)
class ElfImage:
    """A validated ELF image whose loadable program headers are ready for staging."""

    bits: int
    endian: str
    elf_type: int
    machine: int
    entry: int
    segments: tuple[ElfSegment, ...]
    interpreter: str | None
    has_dynamic_segment: bool
    digest: str
    dynamic: ElfDynamicInfo | None = None
    program_header_offset: int = 0
    program_header_entry_size: int = 0
    program_header_count: int = 0
    program_header_address: int | None = None

    @property
    def machine_name(self) -> str:
        """Mathematics: project machine identity `m` through the finite ELF machine-name map."""

        return MACHINE_NAMES[self.machine]

    def load_into(self, memory: "VirtualMemory", base: int = 0) -> ElfLoadResult:
        """Mathematics: realize each `PT_LOAD` interval `[b+v,b+v+m)` in `M`, copy `filesz` bytes, zero-fill BSS, and apply `W` page protection."""

        if memory.page_size != ELF_PAGE_SIZE:
            raise ElfError("ELF staging requires a 4096-byte virtual memory page")
        if base < 0 or base % memory.page_size:
            raise ElfError("ELF load bias must be non-negative and page-aligned")
        if self.elf_type == ET_EXEC and base != 0:
            raise ElfError("ET_EXEC cannot be relocated by a non-zero load bias")
        page_writable: dict[int, bool] = {}
        page_executable: dict[int, bool] = {}
        for segment in self.segments:
            start = base + segment.virtual_address
            end = start + segment.memory_size
            first = start // memory.page_size
            last = (end + memory.page_size - 1) // memory.page_size
            for page_number in range(first, last):
                page_writable[page_number] = page_writable.get(page_number, False) or segment.writable
                page_executable[page_number] = page_executable.get(page_number, False) or segment.executable
        target_pages = tuple(sorted(page_writable))
        memory.preflight_mapping(target_pages, check_resident=True)
        for run_start, run_length in _page_runs(target_pages):
            memory.map(run_start * memory.page_size, run_length * memory.page_size, writable=True)
        for segment in self.segments:
            if segment.data:
                memory.write(base + segment.virtual_address, segment.data)
        for page_number in target_pages:
            if not page_writable[page_number]:
                memory.protect(page_number * memory.page_size, memory.page_size, writable=False)
        return ElfLoadResult(
            entry=base + self.entry,
            load_bias=base,
            machine=self.machine_name,
            bits=self.bits,
            interpreter=self.interpreter,
            mapped_pages=target_pages,
            writable_pages=tuple(sorted(page for page, writable in page_writable.items() if writable)),
            executable_pages=tuple(sorted(page for page, executable in page_executable.items() if executable)),
        )

    def startup_state(
        self,
        load: ElfLoadResult,
        *,
        interpreter_entry: int | None = None,
        interpreter_base: int | None = None,
    ) -> ElfStartupState:
        """Mathematics: construct auxiliary vector `A` and select `entry₀=interp_entry` iff `PT_INTERP` exists, else `entry₀=main_entry`."""

        if load.load_bias < 0 or load.load_bias % ELF_PAGE_SIZE:
            raise ElfError("startup load bias is not page-aligned")
        if load.entry != load.load_bias + self.entry:
            raise ElfError("startup load result does not match ELF entry")
        if self.interpreter is None:
            if interpreter_entry is not None or interpreter_base is not None:
                raise ElfError("interpreter handoff was supplied for a static ELF image")
            initial_entry = load.entry
        else:
            if interpreter_entry is None or interpreter_base is None:
                raise ElfError("interpreter entry and base are required for PT_INTERP handoff")
            if interpreter_entry < 0 or interpreter_base < 0 or interpreter_base % ELF_PAGE_SIZE:
                raise ElfError("interpreter handoff is not page-aligned")
            initial_entry = int(interpreter_entry)
        auxiliary: list[tuple[int, int]] = []
        if self.program_header_address is not None:
            auxiliary.append((AT_PHDR, load.load_bias + self.program_header_address))
        if self.program_header_entry_size > 0:
            auxiliary.append((AT_PHENT, self.program_header_entry_size))
        if self.program_header_count > 0:
            auxiliary.append((AT_PHNUM, self.program_header_count))
        auxiliary.extend(((AT_PAGESZ, ELF_PAGE_SIZE), (AT_FLAGS, 0), (AT_ENTRY, load.entry)))
        if self.interpreter is not None:
            auxiliary.append((AT_BASE, int(interpreter_base)))
        auxiliary.append((AT_NULL, 0))
        return ElfStartupState(
            main_entry=load.entry,
            initial_entry=initial_entry,
            interpreter=self.interpreter,
            interpreter_base=None if interpreter_base is None else int(interpreter_base),
            auxiliary_vector=tuple(auxiliary),
        )


    def plan_relocations(
        self,
        base: int = 0,
        bindings: Mapping[str, int] | None = None,
    ) -> DynamicLinkPlan:
        """Mathematics: resolve `R_RELATIVE=base+addend` and `R_SYMBOL=B[name]+addend` into immutable actions without writing memory."""

        if base < 0 or base % ELF_PAGE_SIZE:
            raise ElfError("ELF load bias must be non-negative and page-aligned")
        if self.elf_type == ET_EXEC and base != 0:
            raise ElfError("ET_EXEC cannot be relocated by a non-zero load bias")
        dynamic = self.dynamic
        if dynamic is None:
            return DynamicLinkPlan(base, (), ())
        symbol_bindings = {str(name): int(value) for name, value in dict(bindings or {}).items()}
        symbols = {symbol.index: symbol for symbol in dynamic.symbols}
        actions: list[RelocationAction] = []
        relative_types = _RELATIVE_TYPES.get(self.machine, set())
        symbol_types = _SYMBOL_RELOCATION_TYPES.get(self.machine, set())
        for relocation in dynamic.relocations:
            if relocation.relocation_type in relative_types:
                addend = int(relocation.addend or 0)
                actions.append(
                    RelocationAction(
                        base + relocation.offset,
                        relocation.relocation_type,
                        None,
                        addend,
                        base + addend,
                    )
                )
                continue
            if relocation.relocation_type not in symbol_types:
                raise ElfError(f"unsupported relocation type {relocation.relocation_type} for {self.machine_name}")
            symbol = symbols.get(relocation.symbol_index)
            if symbol is None or not symbol.name:
                raise ElfError(f"relocation references unknown dynamic symbol: {relocation.symbol_index}")
            if symbol.defined:
                symbol_value = base + symbol.value
            elif symbol.name in symbol_bindings:
                symbol_value = symbol_bindings[symbol.name]
            else:
                raise ElfError(f"unresolved dynamic symbol: {symbol.name}")
            addend = int(relocation.addend or 0)
            actions.append(
                RelocationAction(
                    base + relocation.offset,
                    relocation.relocation_type,
                    symbol.name,
                    addend,
                    symbol_value + addend,
                )
            )
        return DynamicLinkPlan(base, dynamic.needed, tuple(actions))

    def apply_relocations(self, memory: "VirtualMemory", plan: DynamicLinkPlan) -> None:
        """Mathematics: preflight every `write(target,width)` then commit `bytes(value)` for the complete relocation action set."""

        for action in plan.actions:
            width = _relocation_width(self.machine, action.relocation_type)
            if action.value < 0 or action.value >= 1 << (8 * width):
                raise ElfError(f"relocation value does not fit {width * 8}-bit target: {action.value}")
            try:
                memory.validate_access(action.target_address, width, "write")
            except Exception as error:
                raise ElfError(f"relocation target is not writable: {action.target_address:#x}") from error
        for action in plan.actions:
            width = _relocation_width(self.machine, action.relocation_type)
            try:
                memory.write(action.target_address, int(action.value).to_bytes(width, self.endian))
            except Exception as error:
                raise ElfError(f"relocation write failed at {action.target_address:#x}") from error


def materialize_startup_stack(
    memory: "VirtualMemory",
    startup: ElfStartupState,
    argv: Sequence[str] = (),
    environment: Mapping[str, str] | None = None,
    *,
    stack_top: int = 0x7FFF_FFFF_F000,
) -> ElfStackLayout:
    """Mathematics: publish `[argc,argv,NULL,envp,NULL,auxv,strings]` through clone-then-commit memory state with `sp mod 16 = 0`."""

    if not isinstance(startup, ElfStartupState):
        raise ElfError("startup state has the wrong type")
    page_size = int(memory.page_size)
    if page_size <= 0 or stack_top <= 0 or stack_top % page_size:
        raise ElfError("startup stack top must be positive and page-aligned")
    process_argv = tuple(argv)
    if any(not isinstance(value, str) or "\x00" in value for value in process_argv):
        raise ElfError("startup argv contains a non-string or NUL")
    env_map = dict(environment or {})
    for key, value in env_map.items():
        if (
            not isinstance(key, str)
            or not key
            or not (key[0].isalpha() or key[0] == "_")
            or not all(character.isalnum() or character == "_" for character in key)
            or not isinstance(value, str)
            or "\x00" in value
        ):
            raise ElfError("startup environment is invalid")
    auxiliary = tuple(startup.auxiliary_vector)
    if not auxiliary or auxiliary[-1] != (AT_NULL, 0) or any(tag == AT_NULL for tag, _value in auxiliary[:-1]):
        raise ElfError("startup auxiliary vector must terminate exactly once")
    if any(
        isinstance(tag, bool)
        or isinstance(value, bool)
        or not isinstance(tag, int)
        or not isinstance(value, int)
        or tag < 0
        or value < 0
        for tag, value in auxiliary
    ):
        raise ElfError("startup auxiliary vector contains an invalid word")
    environment_entries = tuple(f"{key}={env_map[key]}" for key in sorted(env_map))
    strings = process_argv + environment_entries
    string_bytes = tuple(value.encode("utf-8") + b"\x00" for value in strings)
    table_bytes = (
        8
        + 8 * (len(process_argv) + 1)
        + 8 * (len(environment_entries) + 1)
        + 16 * len(auxiliary)
    )
    string_length = sum(len(value) for value in string_bytes)
    raw_start = stack_top - table_bytes - string_length
    stack_pointer = _align_down(raw_start, 16)
    if stack_pointer < 0:
        raise ElfError("startup stack does not fit below stack top")
    mapping_start = _align_down(stack_pointer, page_size)
    mapping_length = stack_top - mapping_start
    if mapping_length <= 0:
        raise ElfError("startup stack mapping is empty")
    argv_address = stack_pointer + 8
    envp_address = argv_address + 8 * (len(process_argv) + 1)
    auxiliary_address = envp_address + 8 * (len(environment_entries) + 1)
    strings_address = auxiliary_address + 16 * len(auxiliary)
    staged = memory.clone()
    staged.map(mapping_start, mapping_length, writable=True)
    staged.write(stack_pointer, struct.pack("<Q", len(process_argv)))
    for index, _value in enumerate(process_argv):
        address = strings_address + sum(len(item) for item in string_bytes[:index])
        staged.write(argv_address + index * 8, struct.pack("<Q", address))
    staged.write(argv_address + len(process_argv) * 8, b"\x00" * 8)
    environment_start = strings_address + sum(len(item) for item in string_bytes[: len(process_argv)])
    for index, _value in enumerate(environment_entries):
        address = environment_start + sum(len(item) for item in string_bytes[len(process_argv) : len(process_argv) + index])
        staged.write(envp_address + index * 8, struct.pack("<Q", address))
    staged.write(envp_address + len(environment_entries) * 8, b"\x00" * 8)
    for index, (tag, value) in enumerate(auxiliary):
        staged.write(auxiliary_address + index * 16, struct.pack("<QQ", tag, value))
    cursor = strings_address
    for payload in string_bytes:
        staged.write(cursor, payload)
        cursor += len(payload)
    memory.commit_from(staged)
    return ElfStackLayout(
        stack_pointer,
        len(process_argv),
        argv_address,
        envp_address,
        auxiliary_address,
        mapping_start,
        mapping_length,
    )


def _align_down(value: int, alignment: int) -> int:
    """Mathematics: compute the greatest multiple `⌊value/alignment⌋·alignment` for positive `alignment`."""

    if alignment <= 0:
        raise ElfError("alignment must be positive")
    return (value // alignment) * alignment


def _relocation_width(machine: int, relocation_type: int) -> int:
    """Mathematics: map each admitted relocation family to its target word width `w∈{4,8}`."""

    if machine == 62 and relocation_type in {1, 6, 7, 8}:
        return 8
    if machine == 3 and relocation_type in {1, 6, 7, 8}:
        return 4
    if machine == 183 and relocation_type in {257, 1025, 1026, 1027}:
        return 8
    if machine == 40 and relocation_type in {2, 21, 22, 23}:
        return 4
    if machine == 243 and relocation_type in {2, 3, 5, 6}:
        return 8
    raise ElfError(f"unsupported relocation width for machine {machine}, type {relocation_type}")


def _page_runs(page_numbers: tuple[int, ...]) -> tuple[tuple[int, int], ...]:
    """Mathematics: factor sorted `P` into maximal consecutive intervals `(start,length)` whose union equals `P`."""

    if not page_numbers:
        return ()
    runs: list[tuple[int, int]] = []
    start = previous = page_numbers[0]
    for page_number in page_numbers[1:]:
        if page_number != previous + 1:
            runs.append((start, previous - start + 1))
            start = page_number
        previous = page_number
    runs.append((start, previous - start + 1))
    return tuple(runs)


def _checked_interval(offset: int, size: int, total: int, label: str) -> tuple[int, int]:
    """Mathematics: admit byte interval `[offset,offset+size)` iff `0≤offset≤offset+size≤total`."""

    if offset < 0 or size < 0 or offset + size > total:
        raise ElfError(f"{label} lies outside the ELF payload")
    return offset, offset + size


def _read_virtual_bytes(address: int, size: int, segments: tuple[ElfSegment, ...]) -> bytes:
    """Mathematics: invert one file-backed load projection `v↦file[v]` over `[address,address+size)` without crossing an absent interval."""

    if address < 0 or size < 0:
        raise ElfError("dynamic virtual interval is negative")
    for segment in segments:
        start = segment.virtual_address
        end = start + segment.file_size
        if start <= address and address + size <= end:
            offset = address - start
            return segment.data[offset : offset + size]
    raise ElfError(f"dynamic virtual interval is not file-backed: {address:#x}+{size:#x}")


def _read_dynamic_string(table: bytes, offset: int, label: str) -> str:
    """Mathematics: resolve `str[offset:next_nul)` inside the bounded dynamic string domain `0≤offset<|strtab|`."""

    if offset < 0 or offset >= len(table):
        raise ElfError(f"{label} string offset is outside DT_STRTAB")
    end = table.find(b"\0", offset)
    if end < 0:
        raise ElfError(f"{label} string is not NUL-terminated")
    try:
        return table[offset:end].decode("utf-8")
    except UnicodeDecodeError as error:
        raise ElfError(f"{label} string is not valid UTF-8") from error


def _parse_hash_symbol_count(
    address: int | None,
    endian: str,
    segments: tuple[ElfSegment, ...],
) -> int | None:
    """Mathematics: obtain `nchain` from SysV `DT_HASH`, or infer the terminal GNU-hash chain index."""

    if address is None:
        return None
    raw = _read_virtual_bytes(address, 8, segments)
    bucket_count, chain_count = struct.unpack_from(endian + "II", raw, 0)
    if bucket_count == 0:
        return chain_count
    return chain_count


def _parse_gnu_hash_symbol_count(address: int | None, bits: int, endian: str, segments: tuple[ElfSegment, ...]) -> int | None:
    """Mathematics: infer GNU-hash symbol domain cardinality from `symoffset` and the first terminal chain marker."""

    if address is None:
        return None
    word_size = 8 if bits == 64 else 4
    header = _read_virtual_bytes(address, 16, segments)
    header_format = struct.Struct(endian + "IIII")
    bucket_count, symbol_offset, bloom_size, _bloom_shift = header_format.unpack(header)
    if bucket_count == 0:
        return symbol_offset
    buckets_address = address + 16 + bloom_size * word_size
    buckets = _read_virtual_bytes(buckets_address, bucket_count * 4, segments)
    bucket_values = struct.unpack(endian + f"{bucket_count}I", buckets)
    maximum_bucket = max(bucket_values, default=0)
    if maximum_bucket < symbol_offset:
        return symbol_offset
    chains_address = buckets_address + bucket_count * 4
    chain_count = 0
    index = maximum_bucket - symbol_offset
    while chain_count <= MAX_DYNAMIC_ENTRIES:
        raw = _read_virtual_bytes(chains_address + index * 4, 4, segments)
        value = struct.unpack(endian + "I", raw)[0]
        chain_count += 1
        if value & 1:
            return maximum_bucket + chain_count
        index += 1
    raise ElfError("GNU hash symbol chain exceeds dynamic limit")


def _parse_dynamic(
    data: bytes,
    offset: int,
    size: int,
    bits: int,
    endian: str,
    segments: tuple[ElfSegment, ...],
) -> ElfDynamicInfo:
    """Mathematics: fold `PT_DYNAMIC` records until `DT_NULL`, then decode bounded strings, symbols, and REL/RELA relations."""

    entry_size = 16 if bits == 64 else 8
    if size <= 0 or size % entry_size:
        raise ElfError("dynamic table size is not an entry multiple")
    _checked_interval(offset, size, len(data), "dynamic table")
    dynamic_bytes = data[offset : offset + size]
    dynamic_format = struct.Struct(endian + ("qQ" if bits == 64 else "iI"))
    tags: dict[int, int] = {}
    needed_offsets: list[int] = []
    terminated = False
    for index in range(size // entry_size):
        tag, value = dynamic_format.unpack_from(dynamic_bytes, index * entry_size)
        if tag == DT_NULL:
            terminated = True
            break
        if index >= MAX_DYNAMIC_ENTRIES:
            raise ElfError("dynamic table exceeds entry limit")
        if tag == DT_NEEDED:
            needed_offsets.append(int(value))
        else:
            tags.setdefault(int(tag), int(value))
    if not terminated:
        raise ElfError("dynamic table has no DT_NULL terminator")

    string_address = tags.get(DT_STRTAB)
    string_size = tags.get(DT_STRSZ)
    string_table: bytes | None = None
    if string_address is not None or string_size is not None or needed_offsets:
        if string_address is None or string_size is None or string_size > MAX_DYNAMIC_STRINGS:
            raise ElfError("dynamic string table metadata is incomplete or too large")
        string_table = _read_virtual_bytes(string_address, string_size, segments)

    def string_at(value: int, label: str) -> str:
        """Mathematics: resolve one dynamic string-table offset `value` through the shared bounded table."""

        if string_table is None:
            raise ElfError(f"{label} requires DT_STRTAB")
        return _read_dynamic_string(string_table, value, label)

    needed = tuple(string_at(value, "DT_NEEDED") for value in needed_offsets)
    soname = None if DT_SONAME not in tags else string_at(tags[DT_SONAME], "DT_SONAME")
    rpath = None if DT_RPATH not in tags else string_at(tags[DT_RPATH], "DT_RPATH")
    runpath = None if DT_RUNPATH not in tags else string_at(tags[DT_RUNPATH], "DT_RUNPATH")

    def dynamic_table(tag: int, size_tag: int, entry_tag: int, expected: int, label: str, addend: bool) -> list[ElfRelocation]:
        """Mathematics: parse `size/entry` fixed records from dynamic virtual address `tag`, preserving `addend=⊥` for REL."""

        address = tags.get(tag)
        table_size = tags.get(size_tag, 0)
        if address is None:
            if table_size:
                raise ElfError(f"{label} size has no address")
            return []
        entry = tags.get(entry_tag, expected)
        if entry != expected or table_size % entry:
            raise ElfError(f"{label} entry size is invalid")
        raw_table = _read_virtual_bytes(address, table_size, segments)
        result: list[ElfRelocation] = []
        format_string = endian + ("QQq" if bits == 64 and addend else "QQ" if bits == 64 else "IIi" if addend else "II")
        record_format = struct.Struct(format_string)
        for cursor in range(0, table_size, entry):
            values = record_format.unpack_from(raw_table, cursor)
            relocation_offset, info = int(values[0]), int(values[1])
            symbol_index = info >> (32 if bits == 64 else 8)
            relocation_type = info & ((1 << (32 if bits == 64 else 8)) - 1)
            relocation_addend = int(values[2]) if addend else None
            result.append(ElfRelocation(relocation_offset, relocation_type, symbol_index, relocation_addend, None))
        return result

    relocations = dynamic_table(DT_RELA, DT_RELASZ, DT_RELAENT, 24 if bits == 64 else 12, "DT_RELA", True)
    relocations.extend(dynamic_table(DT_REL, DT_RELSZ, DT_RELENT, 16 if bits == 64 else 8, "DT_REL", False))
    jmprel_address = tags.get(DT_JMPREL)
    if jmprel_address is not None:
        plt_size = tags.get(DT_PLTRELSZ, 0)
        plt_kind = tags.get(DT_PLTREL)
        if plt_kind == DT_RELA:
            relocations.extend(dynamic_table(DT_JMPREL, DT_PLTRELSZ, DT_RELAENT, 24 if bits == 64 else 12, "DT_JMPREL/RELA", True))
        elif plt_kind == DT_REL:
            relocations.extend(dynamic_table(DT_JMPREL, DT_PLTRELSZ, DT_RELENT, 16 if bits == 64 else 8, "DT_JMPREL/REL", False))
        elif plt_size:
            raise ElfError("DT_JMPREL has no valid DT_PLTREL kind")

    symbol_address = tags.get(DT_SYMTAB)
    symbol_entry = tags.get(DT_SYMENT)
    symbols: list[ElfSymbol] = []
    if symbol_address is not None:
        expected_symbol_entry = 24 if bits == 64 else 16
        if symbol_entry != expected_symbol_entry:
            raise ElfError("dynamic symbol entry size is invalid")
        symbol_count = _parse_hash_symbol_count(tags.get(DT_HASH), endian, segments)
        if symbol_count is None:
            symbol_count = _parse_gnu_hash_symbol_count(tags.get(DT_GNU_HASH), bits, endian, segments)
        if symbol_count is None:
            symbol_count = max((relocation.symbol_index for relocation in relocations), default=-1) + 1
        if symbol_count > MAX_DYNAMIC_ENTRIES:
            raise ElfError("dynamic symbol table exceeds entry limit")
        raw_symbols = _read_virtual_bytes(symbol_address, symbol_count * expected_symbol_entry, segments)
        for index in range(symbol_count):
            raw = raw_symbols[index * expected_symbol_entry : (index + 1) * expected_symbol_entry]
            if bits == 64:
                name_offset, info, other, section_index, value, symbol_size = struct.unpack(endian + "IBBHQQ", raw)
            else:
                name_offset, value, symbol_size, info, other, section_index = struct.unpack(endian + "IIIBBH", raw)
            symbols.append(
                ElfSymbol(index, string_at(name_offset, "dynamic symbol"), int(value), int(symbol_size), int(info), int(other), int(section_index))
            )
    symbol_map = {symbol.index: symbol.name for symbol in symbols}
    relocations = tuple(
        ElfRelocation(relocation.offset, relocation.relocation_type, relocation.symbol_index, relocation.addend, symbol_map.get(relocation.symbol_index))
        for relocation in relocations
    )
    return ElfDynamicInfo(
        needed,
        soname,
        rpath,
        runpath,
        tuple(symbols),
        relocations,
        string_address,
        string_size,
        symbol_address,
        symbol_entry,
    )


def _read_virtual_bytes_from_file_segments(offset: int, size: int, segments: tuple[ElfSegment, ...]) -> bytes:
    """Mathematics: read a dynamic table's raw file interval by locating the segment whose stored bytes contain `offset..offset+size`."""

    if offset < 0 or size < 0:
        raise ElfError("dynamic file interval is negative")
    for segment in segments:
        segment_offset = segment.offset
        if segment_offset <= offset and offset + size <= segment_offset + segment.file_size:
            start = offset - segment_offset
            return segment.data[start : start + size]
    raise ElfError(f"dynamic file interval is not represented by a load segment: {offset:#x}+{size:#x}")


def parse_elf(payload: bytes) -> ElfImage:
    """Mathematics: parse ELF identification/header/program tables and establish bounded, non-overlapping `PT_LOAD` intervals."""

    data = bytes(payload)
    if len(data) < 16 or data[:4] != b"\x7fELF":
        raise ElfError("missing ELF magic")
    elf_class = data[4]
    bits = {1: 32, 2: 64}.get(elf_class)
    if bits is None:
        raise ElfError("unsupported ELF class")
    endian = {1: "<", 2: ">"}.get(data[5])
    if endian is None:
        raise ElfError("unsupported ELF byte order")
    if data[6] != 1:
        raise ElfError("unsupported ELF identification version")
    header_format = "HHIIIIIHHHHHH" if bits == 32 else "HHIQQQIHHHHHH"
    header = struct.Struct(endian + header_format)
    if len(data) < 16 + header.size:
        raise ElfError("ELF header is truncated")
    values = header.unpack_from(data, 16)
    elf_type, machine, version = values[:3]
    if elf_type not in {ET_EXEC, ET_DYN}:
        raise ElfError(f"unsupported ELF type: {elf_type}")
    if machine not in MACHINE_NAMES:
        raise ElfError(f"unsupported ELF machine: {machine}")
    if version != 1:
        raise ElfError("unsupported ELF header version")
    entry, phoff, phentsize, phnum = values[3], values[4], values[8], values[9]
    expected_phentsize = 32 if bits == 32 else 56
    if phentsize != expected_phentsize:
        raise ElfError("unexpected ELF program-header size")
    if phnum <= 0 or phnum > MAX_PROGRAM_HEADERS:
        raise ElfError("invalid ELF program-header count")
    _checked_interval(phoff, phentsize * phnum, len(data), "program-header table")
    load_segments: list[ElfSegment] = []
    interpreter: str | None = None
    has_dynamic = False
    dynamic_header: tuple[int, int] | None = None
    program_header_address: int | None = None
    program_header = struct.Struct(endian + ("IIIIIIII" if bits == 32 else "IIQQQQQQ"))
    for index in range(phnum):
        raw = program_header.unpack_from(data, phoff + index * phentsize)
        if bits == 32:
            segment_type, offset, virtual_address, physical_address, file_size, memory_size, flags, alignment = raw
        else:
            segment_type, flags, offset, virtual_address, physical_address, file_size, memory_size, alignment = raw
        _checked_interval(offset, file_size, len(data), f"program segment {index}")
        if segment_type == PT_DYNAMIC:
            has_dynamic = True
            dynamic_header = (int(offset), int(file_size))
        if segment_type == PT_PHDR:
            program_header_address = int(virtual_address)
        if segment_type == PT_INTERP:
            if file_size <= 1 or file_size > MAX_INTERPRETER_BYTES:
                raise ElfError("invalid ELF interpreter size")
            raw_interpreter = data[offset : offset + file_size]
            if raw_interpreter[-1:] != b"\0" or b"\0" in raw_interpreter[:-1]:
                raise ElfError("ELF interpreter is not one NUL-terminated path")
            try:
                interpreter = raw_interpreter[:-1].decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ElfError("ELF interpreter is not valid UTF-8") from exc
        if segment_type != PT_LOAD:
            continue
        if memory_size <= 0 or file_size > memory_size:
            raise ElfError(f"invalid PT_LOAD sizes at index {index}")
        if alignment not in {0, 1} and (alignment & (alignment - 1)):
            raise ElfError(f"PT_LOAD alignment is not a power of two at index {index}")
        if alignment >= ELF_PAGE_SIZE and virtual_address % alignment != offset % alignment:
            raise ElfError(f"PT_LOAD alignment congruence failed at index {index}")
        if virtual_address % ELF_PAGE_SIZE != offset % ELF_PAGE_SIZE:
            raise ElfError(f"PT_LOAD page congruence failed at index {index}")
        if virtual_address + memory_size > (1 << bits):
            raise ElfError(f"PT_LOAD address overflows ELF{bits}")
        load_segments.append(
            ElfSegment(
                segment_type,
                int(flags),
                int(offset),
                int(virtual_address),
                int(physical_address),
                int(file_size),
                int(memory_size),
                int(alignment),
                data[offset : offset + file_size],
            )
        )
    if not load_segments:
        raise ElfError("ELF contains no PT_LOAD segment")
    ordered = sorted(load_segments, key=lambda segment: segment.virtual_address)
    for previous, current in zip(ordered, ordered[1:]):
        if previous.virtual_address + previous.memory_size > current.virtual_address:
            raise ElfError("PT_LOAD memory intervals overlap")
    if not any(segment.virtual_address <= entry < segment.virtual_address + segment.memory_size for segment in ordered):
        raise ElfError("ELF entry point is outside PT_LOAD memory")
    if program_header_address is None:
        table_end = int(phoff) + int(phentsize) * int(phnum)
        for segment in ordered:
            if segment.offset <= phoff and table_end <= segment.offset + segment.file_size:
                program_header_address = segment.virtual_address + (int(phoff) - segment.offset)
                break
    dynamic = None
    if dynamic_header is not None and dynamic_header[1] > 0:
        dynamic = _parse_dynamic(data, dynamic_header[0], dynamic_header[1], bits, endian, tuple(ordered))
    return ElfImage(
        bits,
        "little" if endian == "<" else "big",
        int(elf_type),
        int(machine),
        int(entry),
        tuple(ordered),
        interpreter,
        has_dynamic,
        hashlib.sha256(data).hexdigest(),
        dynamic,
        int(phoff),
        int(phentsize),
        int(phnum),
        program_header_address,
    )
