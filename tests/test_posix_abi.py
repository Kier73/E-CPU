from __future__ import annotations

import struct

from mailcpu import (
    MAP_ANONYMOUS,
    MAP_PRIVATE,
    O_CLOEXEC,
    O_CREAT,
    O_EXCL,
    O_RDWR,
    O_TRUNC,
    PosixCompatibility,
    PROT_READ,
    PROT_WRITE,
    WNOHANG,
    HeadlessOS,
)
from mailcpu.kernel import Errno, F_GETFD, FD_CLOEXEC


def _process() -> tuple[HeadlessOS, int]:
    """Mathematics: construct one live process `p∈dom(P)∩dom(M)` for each ABI relation test."""

    operating_system = HeadlessOS()
    pid = operating_system.launch_source("halt\n", "posix-test")
    return operating_system, pid


def _write_c_string(operating_system: HeadlessOS, pid: int, address: int, value: str) -> None:
    """Mathematics: materialize `UTF8(value)||NUL` into `M_pid[address:]`, making the pointer decoder injective."""

    operating_system.syscall(pid, "mem_write", address=address, data=value.encode("utf-8") + b"\x00")


def test_posix_pointer_io_open_and_stat_follow_native_memory_laws() -> None:
    """Mathematics: `read` and `write` preserve byte cardinality while `fstat` writes one fixed 144-byte record."""

    operating_system, pid = _process()
    _write_c_string(operating_system, pid, 0, "/tmp/posix-data")
    opened = operating_system.posix.invoke(pid, 2, path_address=0, flags=O_CREAT | O_RDWR, mode=0o644)
    assert opened.ok
    fd = int(opened.result)
    operating_system.syscall(pid, "mem_write", address=32, data=b"hello")
    written = operating_system.posix.invoke(pid, 1, fd=fd, address=32, size=5)
    assert written.to_dict() == {"result": 5, "errno": 0, "error": None, "ok": True}
    assert operating_system.posix.invoke(pid, 8, fd=fd, offset=0, whence=0).result == 0
    read = operating_system.posix.invoke(pid, 0, fd=fd, address=64, size=5)
    assert read.result == 5
    assert operating_system.syscall(pid, "mem_read", address=64, size=5) == b"hello"
    stat_address = 128
    stat = operating_system.posix.invoke(pid, 5, fd=fd, stat_address=stat_address)
    assert stat.result == 0
    encoded = operating_system.syscall(pid, "mem_read", address=stat_address, size=144)
    assert struct.unpack_from("<q", encoded, 48)[0] == 5
    assert struct.unpack_from("<I", encoded, 24)[0] & 0o170000 == 0o100000


def test_posix_mmap_protection_and_pipe_are_real_translations() -> None:
    """Mathematics: `mmap` allocates a disjoint page interval, `mprotect` changes write permission, and `pipe` writes `(r,w)` atomically."""

    operating_system, pid = _process()
    mapped = operating_system.posix.invoke(
        pid,
        9,
        address=0,
        length=4096,
        prot=PROT_READ | PROT_WRITE,
        flags=MAP_PRIVATE | MAP_ANONYMOUS,
        fd=-1,
        offset=0,
    )
    assert mapped.ok
    address = int(mapped.result)
    assert address >= 8192 and address % 4096 == 0
    assert operating_system.posix.invoke(pid, 10, address=address, length=4096, prot=PROT_READ).ok
    denied = operating_system.posix.invoke(pid, 1, fd=1, address=address, size=0)
    assert denied.ok
    pipe_address = 256
    pipe = operating_system.posix.invoke(pid, 22, address=pipe_address)
    assert pipe.result == 0
    read_fd, write_fd = struct.unpack(
        "<ii", operating_system.syscall(pid, "mem_read", address=pipe_address, size=8)
    )
    assert read_fd != write_fd
    assert operating_system.posix.invoke(pid, 3, fd=read_fd).ok
    assert operating_system.posix.invoke(pid, 3, fd=write_fd).ok


def test_posix_wait4_encodes_status_and_wnohang_without_reaping_early() -> None:
    """Mathematics: `WNOHANG` returns zero for `Z=∅`, then `wait4` returns the least exited child and writes `code·2^8`."""

    operating_system = HeadlessOS()
    parent = operating_system.launch_source("wait inbox value\n", "wait-parent")
    child = operating_system.launch_source("set code 7\nSYSCALL ignored exit code=7\n", "wait-child", parent_pid=parent)
    early = operating_system.posix.invoke(
        parent,
        61,
        child_pid=child,
        status_address=512,
        options=WNOHANG,
        rusage_address=0,
    )
    assert early.result == 0
    operating_system.run(20)
    waited = operating_system.posix.invoke(
        parent,
        61,
        child_pid=child,
        status_address=512,
        options=0,
        rusage_address=0,
    )
    assert waited.result == child
    assert struct.unpack("<I", operating_system.syscall(parent, "mem_read", address=512, size=4))[0] == 7 << 8
    assert child not in operating_system.environment.kernel.processes


def test_posix_unsupported_and_invalid_transitions_are_explicit() -> None:
    """Mathematics: `n∉dom(Π)` yields `-ENOSYS`, while an invalid pointer yields `-EFAULT` without moving the file cursor."""

    operating_system, pid = _process()
    unsupported = operating_system.posix.invoke(pid, 59)
    assert unsupported.result == -int(Errno.ENOSYS)
    assert unsupported.errno == int(Errno.ENOSYS)
    _write_c_string(operating_system, pid, 0, "/tmp/atomic")
    opened = operating_system.posix.invoke(pid, 2, path_address=0, flags=O_CREAT | O_TRUNC | O_RDWR, mode=0o644)
    fd = int(opened.result)
    operating_system.syscall(pid, "mem_write", address=32, data=b"x")
    assert operating_system.posix.invoke(pid, 1, fd=fd, address=32, size=1).result == 1
    before = operating_system.syscall(pid, "fstat", fd=fd)
    failed = operating_system.posix.invoke(pid, 0, fd=fd, address=999_999, size=1)
    assert failed.result == -int(Errno.EFAULT)
    after = operating_system.syscall(pid, "fstat", fd=fd)
    assert before == after


def test_posix_open_cloexec_sets_descriptor_local_flag() -> None:
    """Mathematics: `O_CLOEXEC` is the descriptor-local projection `FD_FLAGS[fd] := FD_CLOEXEC`, not shared open-description state."""

    operating_system, pid = _process()
    _write_c_string(operating_system, pid, 0, "/tmp/cloexec")
    opened = operating_system.posix.invoke(pid, 2, path_address=0, flags=O_CREAT | O_RDWR | O_CLOEXEC, mode=0o644)
    fd = int(opened.result)
    assert operating_system.syscall(pid, "fcntl", fd=fd, command=F_GETFD, arg=0) == FD_CLOEXEC


def test_posix_exclusive_open_is_authorized_and_atomic() -> None:
    """Mathematics: `O_CREAT|O_EXCL` admits exactly one namespace insertion, so the second open returns `-EEXIST` without a descriptor."""

    operating_system, pid = _process()
    _write_c_string(operating_system, pid, 0, "/tmp/exclusive")
    first = operating_system.posix.invoke(pid, 2, path_address=0, flags=O_CREAT | O_EXCL | O_RDWR, mode=0o644)
    assert first.ok
    descriptors_before = set(operating_system.environment.kernel.processes[pid].fds)
    second = operating_system.posix.invoke(pid, 2, path_address=0, flags=O_CREAT | O_EXCL | O_RDWR, mode=0o644)
    assert second.errno == 17
    assert set(operating_system.environment.kernel.processes[pid].fds) == descriptors_before


def test_headless_exposes_numbered_posix_adapter() -> None:
    """Mathematics: `HeadlessOS.posix_syscall = PosixCompatibility.invoke` preserves one canonical ABI entry point."""

    operating_system, pid = _process()
    assert isinstance(operating_system.posix, PosixCompatibility)
    assert operating_system.posix_syscall(pid, 39).result == pid
