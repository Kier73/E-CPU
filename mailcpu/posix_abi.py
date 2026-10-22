"""Linux x86-64 syscall-number translation over the native MailCPU ABI."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Any, Protocol

from .fs import FileStat, FsError
from .kernel import (
    Errno,
    F_GETFD,
    F_GETFL,
    F_SETFD,
    F_SETFL,
    FD_CLOEXEC,
    KernelError,
    O_APPEND,
    O_NONBLOCK,
)
from .memory import VirtualMemoryError


# Linux x86-64 access and mapping bits are stable ABI values, not host flags.
O_RDONLY = 0
O_WRONLY = 1
O_RDWR = 2
O_CREAT = 0x40
O_EXCL = 0x80
O_TRUNC = 0x200
O_APPEND_POSIX = 0x400
O_NONBLOCK_POSIX = 0x800
O_CLOEXEC = 0x80000
PROT_READ = 0x1
PROT_WRITE = 0x2
PROT_EXEC = 0x4
MAP_PRIVATE = 0x02
MAP_ANONYMOUS = 0x20
MAP_FIXED = 0x10
WNOHANG = 0x1
AT_FDCWD = -100
_STAT_BYTES = 144
_MAX_C_STRING = 4096
_MAX_VECTOR_ITEMS = 4096


class PosixAbiError(Exception):
    """A deterministic ABI translation failure with its POSIX errno."""

    def __init__(self, message: str, errno: Errno = Errno.EINVAL) -> None:
        """Mathematics: bind translation failure `e` to the finite error code `κ(e)` without mutating OS state."""

        super().__init__(message)
        self.errno = errno


class PosixHost(Protocol):
    """The minimal host surface required by the POSIX adapter."""

    environment: Any
    vm: Any

    def syscall(self, pid: int, syscall_name: str, **args: Any) -> Any:
        """Mathematics: evaluate the native transition `δ_os(pid,name,args)` or raise its typed failure."""

        ...

    def exec_file(
        self,
        pid: int,
        path: str,
        argv: tuple[str, ...],
        name: str | None = None,
        environment: dict[str, str] | None = None,
    ) -> Any:
        """Mathematics: commit validated image replacement `X_pid:=exec(path,argv,environment)` or raise without a return image."""

        ...

    @staticmethod
    def _errno_for_exception(error: BaseException) -> Errno:
        """Mathematics: classify native failure evidence through the kernel errno projection `κ(error)`."""

        ...


@dataclass(frozen=True)
class PosixSyscallSpec:
    """One architecture-specific syscall number and its native transition name."""

    number: int
    name: str
    native_name: str
    arguments: tuple[str, ...]


@dataclass(frozen=True)
class PosixResponse:
    """The POSIX return partition `Ok(r,0) | Err(-e,e)`."""

    result: Any
    errno: int = 0
    error: str | None = None

    @property
    def ok(self) -> bool:
        """Mathematics: project success as `[errno = 0]`; every failed response has a positive error code."""

        return self.errno == 0

    @property
    def return_value(self) -> Any:
        """Mathematics: expose the ABI return register `r`, equal to `result` on success and `-errno` on failure."""

        return self.result

    def to_dict(self) -> dict[str, Any]:
        """Mathematics: serialize the response sum type without changing its success or failure identity."""

        return {
            "result": self.result,
            "errno": int(self.errno),
            "error": self.error,
            "ok": self.ok,
        }


def _syscall_specs() -> dict[int, PosixSyscallSpec]:
    """Mathematics: construct the finite x86-64 translation relation `N ↦ (name,native,args)`."""

    rows = (
        (0, "read", "read", ("fd", "address", "size")),
        (1, "write", "write", ("fd", "address", "size")),
        (2, "open", "open", ("path_address", "flags", "mode")),
        (59, "execve", "execve", ("path_address", "argv_address", "envp_address")),
        (3, "close", "close", ("fd",)),
        (5, "fstat", "fstat", ("fd", "stat_address")),
        (8, "lseek", "lseek", ("fd", "offset", "whence")),
        (9, "mmap", "mmap", ("address", "length", "prot", "flags", "fd", "offset")),
        (10, "mprotect", "mprotect", ("address", "length", "prot")),
        (11, "munmap", "munmap", ("address", "length")),
        (22, "pipe", "pipe", ("address",)),
        (32, "dup", "dup", ("fd",)),
        (33, "dup2", "dup2", ("fd", "new_fd")),
        (39, "getpid", "getpid", ()),
        (60, "exit", "exit", ("code",)),
        (61, "wait4", "wait4", ("child_pid", "status_address", "options", "rusage_address")),
        (72, "fcntl", "fcntl", ("fd", "command", "arg")),
        (79, "getcwd", "getcwd", ("address", "size")),
        (80, "chdir", "chdir", ("path_address",)),
    )
    return {
        number: PosixSyscallSpec(number, name, native_name, arguments)
        for number, name, native_name, arguments in rows
    }


class PosixCompatibility:
    """A strict x86-64 POSIX syscall boundary backed by the existing OS transitions."""

    def __init__(self, host: PosixHost, architecture: str = "x86_64") -> None:
        """Mathematics: bind `Π_a` only for the explicitly implemented architecture profile `a`."""

        normalized = str(architecture).lower().replace("-", "_")
        if normalized not in {"x86_64", "amd64", "linux_x86_64"}:
            raise ValueError(f"unsupported POSIX architecture: {architecture}")
        self.host = host
        self.architecture = "x86_64"
        self._specs = _syscall_specs()

    @property
    def supported_numbers(self) -> tuple[int, ...]:
        """Mathematics: return the ordered finite domain `dom(Π_x86_64)` of backed syscall numbers."""

        return tuple(sorted(self._specs))

    def spec(self, number: int) -> PosixSyscallSpec | None:
        """Mathematics: perform the partial lookup `Π_x86_64[number]`, returning `⊥` for an unbacked number."""

        if isinstance(number, bool):
            return None
        try:
            return self._specs.get(int(number))
        except (TypeError, ValueError, OverflowError):
            return None

    def invoke(self, pid: int, number: int, **args: Any) -> PosixResponse:
        """Mathematics: evaluate `Π(pid,n,args)` as native success or negative-errno failure without partial translation."""

        try:
            process = self.host.environment.kernel._process(int(pid))
        except (KernelError, TypeError, ValueError, OverflowError) as error:
            return self._failure(pid, number, None, error)
        spec = self.spec(number)
        if spec is None:
            error = PosixAbiError(f"unsupported x86-64 syscall number: {number}", Errno.ENOSYS)
            return self._failure(process.pid, number, None, error)
        try:
            result = self._dispatch(process.pid, spec, args)
        except (KernelError, FsError, VirtualMemoryError, PosixAbiError, KeyError, ValueError, TypeError, OverflowError) as error:
            return self._failure(process.pid, number, spec, error)
        return PosixResponse(result=result, errno=0)

    def _dispatch(self, pid: int, spec: PosixSyscallSpec, args: dict[str, Any]) -> Any:
        """Mathematics: realize the finite case split `δ_posix(name,args)` through exactly one backed native transition graph."""

        name = spec.name
        if name == "read":
            return self.host.syscall(
                pid,
                "read_into",
                fd=self._int(args, "fd"),
                address=self._int(args, "address"),
                size=self._nonnegative(args, "size"),
            )
        if name == "write":
            return self.host.syscall(
                pid,
                "write_from",
                fd=self._int(args, "fd"),
                address=self._int(args, "address"),
                size=self._nonnegative(args, "size"),
            )
        if name == "open":
            return self._open(pid, args)
        if name == "execve":
            return self._execve(pid, args)
        if name == "close":
            return self.host.syscall(pid, "close", fd=self._int(args, "fd"))
        if name == "fstat":
            return self._fstat(pid, args)
        if name == "lseek":
            return self.host.syscall(
                pid,
                "lseek",
                fd=self._int(args, "fd"),
                offset=self._int(args, "offset"),
                whence=self._int(args, "whence"),
            )
        if name == "mmap":
            return self._mmap(pid, args)
        if name == "mprotect":
            return self._mprotect(pid, args)
        if name == "munmap":
            return self.host.syscall(
                pid,
                "munmap",
                start=self._aligned(args, "address", pid),
                length=self._positive(args, "length"),
            )
        if name == "pipe":
            self.host.syscall(pid, "pipe_into", address=self._int(args, "address"))
            return 0
        if name == "dup":
            return self.host.syscall(pid, "dup", fd=self._int(args, "fd"))
        if name == "dup2":
            return self.host.syscall(
                pid,
                "dup2",
                fd=self._int(args, "fd"),
                new_fd=self._int(args, "new_fd"),
            )
        if name == "getpid":
            return self.host.syscall(pid, "getpid")
        if name == "exit":
            self.host.syscall(pid, "exit", code=self._int(args, "code", 0))
            return 0
        if name == "wait4":
            return self._wait4(pid, args)
        if name == "fcntl":
            return self.host.syscall(
                pid,
                "fcntl",
                fd=self._int(args, "fd"),
                command=self._int(args, "command"),
                arg=self._int(args, "arg", 0),
            )
        if name == "getcwd":
            address = self._int(args, "address")
            size = self._positive(args, "size")
            self.host.syscall(pid, "getcwd_into", address=address, size=size)
            return address
        if name == "chdir":
            path = self._path(pid, args)
            return self.host.syscall(pid, "chdir", path=path)
        raise PosixAbiError(f"missing dispatch for backed syscall: {name}", Errno.ENOSYS)

    def _open(self, pid: int, args: dict[str, Any]) -> int:
        """Mathematics: translate Linux flags `φ` into the native mode algebra `m∈{r,w,r+,a,r+a}` before opening."""

        path = self._path(pid, args)
        flags = self._int(args, "flags")
        access = flags & 0x3
        if access == 0x3:
            raise PosixAbiError("invalid POSIX access mode", Errno.EINVAL)
        supported = O_CREAT | O_EXCL | O_TRUNC | O_APPEND_POSIX | O_NONBLOCK_POSIX | O_CLOEXEC
        if flags & ~supported & ~0x3:
            raise PosixAbiError("unsupported POSIX open flag", Errno.EINVAL)
        if flags & O_EXCL and not flags & O_CREAT:
            raise PosixAbiError("O_EXCL requires O_CREAT", Errno.EINVAL)
        append = bool(flags & O_APPEND_POSIX)
        truncate = bool(flags & O_TRUNC)
        if truncate and access == O_RDONLY:
            raise PosixAbiError("O_TRUNC requires writable access", Errno.EINVAL)
        if access == O_RDONLY:
            mode = "r"
        elif access == O_WRONLY:
            mode = "a" if append else "w"
        else:
            mode = "r+a" if append else "r+"
            if truncate:
                mode = "w+"
        fd = self.host.syscall(
            pid,
            "open",
            path=path,
            mode=mode,
            create=bool(flags & O_CREAT),
            exclusive=bool(flags & O_EXCL),
        )
        try:
            status_flags = 0
            if append and access == O_RDONLY:
                status_flags |= O_APPEND
            if flags & O_NONBLOCK_POSIX:
                status_flags |= O_NONBLOCK
            if status_flags:
                current = self.host.syscall(pid, "fcntl", fd=fd, command=F_GETFL, arg=0)
                self.host.syscall(pid, "fcntl", fd=fd, command=F_SETFL, arg=int(current) | status_flags)
            if flags & O_CLOEXEC:
                self.host.syscall(pid, "fcntl", fd=fd, command=F_SETFD, arg=FD_CLOEXEC)
        except (KernelError, FsError, VirtualMemoryError, KeyError, ValueError, TypeError, OverflowError):
            self.host.syscall(pid, "close", fd=fd)
            raise
        return int(fd)

    def _fstat(self, pid: int, args: dict[str, Any]) -> int:
        """Mathematics: serialize native `stat(fd)` into the fixed x86-64 record `S∈bytes^144` before exposing its address."""

        address = self._int(args, "stat_address")
        self._preflight(pid, address, _STAT_BYTES, "write")
        record = self.host.syscall(pid, "fstat", fd=self._int(args, "fd"))
        payload = _encode_stat(record)
        self.host.syscall(pid, "mem_write", address=address, data=payload)
        return 0

    def _execve(self, pid: int, args: dict[str, Any]) -> int:
        """Mathematics: decode `(path,argv,envp)` completely, then commit one native image transition with no old-image return."""

        path = self._path(pid, args)
        argv = self._vector(pid, self._int(args, "argv_address"), "argv")
        environment_values = self._vector(pid, self._int(args, "envp_address", 0), "environment")
        environment: dict[str, str] = {}
        for entry in environment_values:
            if "=" not in entry:
                raise PosixAbiError("environment entry has no separator", Errno.EINVAL)
            key, value = entry.split("=", 1)
            if (
                not key
                or key in environment
                or not (key[0].isalpha() or key[0] == "_")
                or not all(character.isalnum() or character == "_" for character in key)
            ):
                raise PosixAbiError("environment key is invalid or duplicated", Errno.EINVAL)
            environment[key] = value
        self.host.exec_file(pid, path, argv=argv, name=None, environment=environment)
        return 0

    def _mmap(self, pid: int, args: dict[str, Any]) -> int:
        """Mathematics: map only `MAP_PRIVATE|MAP_ANONYMOUS` with modeled `PROT_READ/WRITE`, preserving unmapped flags as explicit failure."""

        address = self._int(args, "address", 0)
        length = self._positive(args, "length")
        prot = self._int(args, "prot")
        flags = self._int(args, "flags")
        fd = self._int(args, "fd", -1)
        offset = self._int(args, "offset", 0)
        if flags & MAP_FIXED:
            raise PosixAbiError("MAP_FIXED is not backed by the allocator", Errno.EINVAL)
        if flags != MAP_PRIVATE | MAP_ANONYMOUS or fd != -1 or offset != 0:
            raise PosixAbiError("only private anonymous mappings at offset zero are backed", Errno.EINVAL)
        if prot == 0 or prot & ~(PROT_READ | PROT_WRITE):
            raise PosixAbiError("requested memory protection is not modeled", Errno.EINVAL)
        start = None if address == 0 else self._aligned(args, "address", pid)
        return self.host.syscall(
            pid,
            "mmap",
            start=start,
            length=length,
            writable=bool(prot & PROT_WRITE),
        )

    def _mprotect(self, pid: int, args: dict[str, Any]) -> int:
        """Mathematics: apply `writable' := [PROT_WRITE∈prot]` over every page in the aligned interval."""

        prot = self._int(args, "prot")
        if prot == 0 or prot & ~(PROT_READ | PROT_WRITE):
            raise PosixAbiError("requested memory protection is not modeled", Errno.EINVAL)
        return self.host.syscall(
            pid,
            "mprotect",
            start=self._aligned(args, "address", pid),
            length=self._positive(args, "length"),
            writable=bool(prot & PROT_WRITE),
        )

    def _wait4(self, pid: int, args: dict[str, Any]) -> int:
        """Mathematics: select child `c` with `waitpid`, then encode exit status `W=(code mod 256)·2^8` into user memory."""

        child_pid = self._int(args, "child_pid")
        options = self._int(args, "options", 0)
        if options & ~WNOHANG:
            raise PosixAbiError("unsupported wait4 option", Errno.EINVAL)
        status_address = self._int(args, "status_address", 0)
        if status_address:
            self._preflight(pid, status_address, 4, "write")
        rusage_address = self._int(args, "rusage_address", 0)
        if rusage_address:
            raise PosixAbiError("rusage output is not yet backed", Errno.ENOSYS)
        result = self.host.syscall(
            pid,
            "waitpid",
            child_pid=child_pid,
            nohang=bool(options & WNOHANG),
        )
        if result is None:
            return 0
        if status_address:
            exit_code = int(result.get("exit_code") or 0) & 0xFF
            self.host.syscall(
                pid,
                "mem_write",
                address=status_address,
                data=struct.pack("<I", exit_code << 8),
            )
        return int(result["pid"])

    def _path(self, pid: int, args: dict[str, Any]) -> str:
        """Mathematics: decode POSIX path pointer `p` by the first NUL in `M_pid[p:]`, retaining a direct string only as a test-harness convenience."""

        if "path_address" in args:
            address = self._int(args, "path_address")
            path = self._read_c_string(pid, address)
            if not path:
                raise PosixAbiError("path must be non-empty", Errno.EINVAL)
            return path
        path = args.get("path")
        if isinstance(path, str) and path:
            return path
        raise PosixAbiError("POSIX path pointer is required", Errno.EFAULT)

    def _read_c_string(self, pid: int, address: int) -> str:
        """Mathematics: decode `s = M_pid[address:address+k]` at the least `k≤L` with `s[k-1]=NUL`, or fail explicitly."""

        if address < 0:
            raise PosixAbiError("string pointer is negative", Errno.EFAULT)
        raw = bytearray()
        for offset in range(_MAX_C_STRING):
            byte = self.host.syscall(pid, "mem_read", address=address + offset, size=1)
            if byte == b"\x00":
                try:
                    return bytes(raw).decode("utf-8")
                except UnicodeDecodeError as error:
                    raise PosixAbiError("string is not UTF-8", Errno.EINVAL) from error
            raw.extend(byte)
        raise PosixAbiError("string exceeds compatibility limit", Errno.EINVAL)

    def _vector(self, pid: int, address: int, field: str) -> tuple[str, ...]:
        """Mathematics: decode the bounded pointer vector `V(q)=[C(M[q+8i])]` through its first null pointer."""

        if address == 0:
            return ()
        if address < 0:
            raise PosixAbiError(f"{field} vector pointer is negative", Errno.EFAULT)
        values: list[str] = []
        for index in range(_MAX_VECTOR_ITEMS):
            pointer_bytes = self.host.syscall(pid, "mem_read", address=address + index * 8, size=8)
            pointer = struct.unpack("<Q", pointer_bytes)[0]
            if pointer == 0:
                return tuple(values)
            values.append(self._read_c_string(pid, pointer))
        raise PosixAbiError(f"{field} vector exceeds compatibility limit", Errno.E2BIG)

    def _preflight(self, pid: int, address: int, size: int, access: str) -> None:
        """Mathematics: prove `P(address,size)⊆M_pid` with the requested access before a compound transition mutates descriptors."""

        process = self.host.environment.kernel._process(pid)
        memory = self.host.vm.memories[pid]
        self.host._authorize_memory(process, address, access)
        memory.validate_access(address, size, access)

    def _aligned(self, args: dict[str, Any], name: str, pid: int) -> int:
        """Mathematics: require `address mod page_size = 0` for page-granular native memory transitions."""

        value = self._int(args, name)
        page_size = int(self.host.vm.memories[pid].page_size)
        if value < 0 or value % page_size:
            raise PosixAbiError(f"{name} must be page aligned", Errno.EINVAL)
        return value

    @staticmethod
    def _int(args: dict[str, Any], name: str, default: int | None = None) -> int:
        """Mathematics: project an ABI scalar `x` into `Z`, rejecting booleans and absent required arguments."""

        if name not in args:
            if default is None:
                raise PosixAbiError(f"missing POSIX argument: {name}", Errno.EINVAL)
            return default
        value = args[name]
        if isinstance(value, bool):
            raise PosixAbiError(f"POSIX argument is not an integer: {name}", Errno.EINVAL)
        try:
            return int(value)
        except (TypeError, ValueError, OverflowError) as error:
            raise PosixAbiError(f"POSIX argument is not an integer: {name}", Errno.EINVAL) from error

    @classmethod
    def _positive(cls, args: dict[str, Any], name: str) -> int:
        """Mathematics: require `x∈Z_{>0}` for a non-empty POSIX length."""

        value = cls._int(args, name)
        if value <= 0:
            raise PosixAbiError(f"POSIX argument must be positive: {name}", Errno.EINVAL)
        return value

    @classmethod
    def _nonnegative(cls, args: dict[str, Any], name: str) -> int:
        """Mathematics: require `x∈Z_{≥0}` for a byte count."""

        value = cls._int(args, name)
        if value < 0:
            raise PosixAbiError(f"POSIX argument must be non-negative: {name}", Errno.EINVAL)
        return value

    def _failure(
        self,
        pid: int,
        number: int,
        spec: PosixSyscallSpec | None,
        error: BaseException,
    ) -> PosixResponse:
        """Mathematics: classify `e` as `errno(e)`, store it in `P_pid`, and return the negative ABI result `-errno(e)`."""

        if isinstance(error, PosixAbiError):
            errno = error.errno
        else:
            errno = self.host._errno_for_exception(error)
        try:
            process = self.host.environment.kernel._process(int(pid))
            process.errno = int(errno)
            self.host.environment.kernel.journal.append(
                "posix.syscall.error",
                {
                    "pid": int(pid),
                    "number": int(number) if not isinstance(number, bool) else -1,
                    "name": None if spec is None else spec.name,
                    "errno": int(errno),
                    "error": str(error),
                },
            )
        except (KernelError, TypeError, ValueError, OverflowError):
            pass
        return PosixResponse(result=-int(errno), errno=int(errno), error=str(error))


def _encode_stat(stat: FileStat) -> bytes:
    """Mathematics: encode `FileStat` into the stable 144-byte x86-64 `struct stat` projection."""

    if not isinstance(stat, FileStat):
        raise PosixAbiError("native fstat did not return FileStat", Errno.EIO)
    payload = bytearray(_STAT_BYTES)
    inode_digits = "".join(character for character in stat.inode_id if character.isdigit())
    inode_number = int(inode_digits or "0")
    kind_bits = {
        "file": 0o100000,
        "directory": 0o040000,
        "pipe": 0o010000,
        "socket": 0o140000,
        "device": 0o020000,
    }.get(stat.kind, 0)
    struct.pack_into("<Q", payload, 0, 0)
    struct.pack_into("<Q", payload, 8, inode_number)
    struct.pack_into("<Q", payload, 16, 2 if stat.kind == "directory" else 1)
    struct.pack_into("<I", payload, 24, kind_bits | (int(stat.mode) & 0o7777))
    struct.pack_into("<I", payload, 28, int(stat.owner))
    struct.pack_into("<I", payload, 32, 0)
    struct.pack_into("<I", payload, 36, 0)
    struct.pack_into("<Q", payload, 40, 0)
    struct.pack_into("<q", payload, 48, int(stat.size))
    struct.pack_into("<q", payload, 56, 4096)
    struct.pack_into("<q", payload, 64, (int(stat.size) + 511) // 512)
    return bytes(payload)


__all__ = [
    "AT_FDCWD",
    "MAP_ANONYMOUS",
    "MAP_FIXED",
    "MAP_PRIVATE",
    "O_APPEND_POSIX",
    "O_CLOEXEC",
    "O_CREAT",
    "O_EXCL",
    "O_NONBLOCK_POSIX",
    "O_RDONLY",
    "O_RDWR",
    "O_TRUNC",
    "O_WRONLY",
    "PosixAbiError",
    "PosixCompatibility",
    "PosixResponse",
    "PosixSyscallSpec",
    "PROT_EXEC",
    "PROT_READ",
    "PROT_WRITE",
    "WNOHANG",
]
