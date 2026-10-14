"""Strict ELF program-header parsing and virtual-memory staging for MailCPU."""

from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING

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
MAX_PROGRAM_HEADERS = 4096
MAX_INTERPRETER_BYTES = 4096
MACHINE_NAMES = {
    3: "i386",
    40: "ARM",
    62: "x86_64",
    183: "AArch64",
    243: "RISC-V",
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
    )
