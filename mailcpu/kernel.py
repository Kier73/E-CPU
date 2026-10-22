"""Capability-oriented virtual kernel and Unix-shaped syscall surface."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, IntEnum
from typing import Any, Callable, Sequence

from .bus import BusMessage, MailboxBus
from .devices import BufferDevice, DeviceBus, NullDevice, TerminalDevice
from .dns_cell import DnsLatchDevice
from .fs import FileStat, FsError, VirtualFileSystem, normalize_path
from .journal import EventJournal
from .signals import Signal


# Poll bit masks assign standard flags for input, priority, output, error, and hangup events.
POLLIN = 0x001
POLLPRI = 0x002
POLLOUT = 0x004
POLLERR = 0x008
POLLHUP = 0x010
POLLNVAL = 0x020
F_GETFL = 3
F_SETFL = 4
F_GETFD = 1
F_SETFD = 2
FD_CLOEXEC = 1
O_APPEND = 0x0400
O_NONBLOCK = 0x0800
_STATUS_FLAGS = O_APPEND | O_NONBLOCK
_ACCESS_MODE = 0x0003


class KernelError(Exception):
    """A syscall or process-management operation failed."""


class Errno(IntEnum):
    """Stable native error numbers returned through the scheduled MailCPU ABI."""

    EPERM = 1
    ENOENT = 2
    ESRCH = 3
    EINTR = 4
    EIO = 5
    ECHILD = 10
    EAGAIN = 11
    ENOMEM = 12
    EACCES = 13
    EFAULT = 14
    EEXIST = 17
    ENOTDIR = 20
    EISDIR = 21
    EINVAL = 22
    ERANGE = 34
    ENOSPC = 28
    EPIPE = 32
    ENOSYS = 38
    EBADF = 9
    EBUSY = 16
    ENOTCONN = 107
    ECONNREFUSED = 111


class ProcessStatus(str, Enum):
    """Lifecycle states exposed by the process table."""

    RUNNABLE = "runnable"
    BLOCKED = "blocked"
    STOPPED = "stopped"
    EXITED = "exited"


@dataclass(frozen=True)
class Capability:
    """A bearer-like authority over one resource subtree and a finite rights set."""

    resource: str
    rights: frozenset[str]

    def allows(self, path: str, right: str) -> bool:
        """Mathematics: authorize iff `right ∈ rights` and `path ∈ resource·(/.*)?`, a prefix-closed subtree relation."""

        resource = normalize_path(self.resource)
        candidate = normalize_path(path)
        in_subtree = candidate == resource or candidate.startswith(resource.rstrip("/") + "/")
        return right in self.rights and in_subtree


@dataclass
class OpenFile:
    """Per-process file descriptor state, including the shared inode and local cursor."""

    path: str
    offset: int
    readable: bool
    writable: bool
    pipe_id: str | None = None
    description_id: str = ""
    network_kind: str | None = None
    network_handle: int | None = None
    status_flags: int = 0


@dataclass(frozen=True)
class FdTransfer:
    """A bus-resident open-description reference awaiting receipt by one process."""

    transfer_id: str
    sender_pid: int
    destination_pid: int
    description: OpenFile


@dataclass
class PipeState:
    """Bounded byte FIFO shared by a pipe's inherited descriptor endpoints."""

    pipe_id: str
    buffer: bytearray = field(default_factory=bytearray)
    capacity: int = 65_536


@dataclass
class Process:
    """Process-table record for a MailCPU task."""

    pid: int
    name: str
    status: ProcessStatus
    capabilities: tuple[Capability, ...]
    cwd: str = "/"
    fds: dict[int, OpenFile] = field(default_factory=dict)
    fd_flags: dict[int, int] = field(default_factory=dict)
    next_fd: int = 3
    exit_code: int | None = None
    environment: dict[str, str] = field(default_factory=dict)
    argv: tuple[str, ...] = ()
    parent_pid: int | None = None
    group_id: int | None = None
    session_id: int | None = None
    reaped: bool = False
    subreaper: bool = False
    errno: int = 0
    signal_dispositions: dict[str, str] = field(default_factory=dict)


class VirtualKernel:
    """A message-backed kernel facade over filesystem, bus, devices, and process state."""

    def __init__(
        self,
        filesystem: VirtualFileSystem | None = None,
        bus: MailboxBus | None = None,
        devices: DeviceBus | None = None,
        journal: EventJournal | None = None,
    ) -> None:
        """Mathematics: initialize kernel state `K = (I, Q_bus, D, P, J)` with finite maps and monotone PID allocation."""

        self.fs = filesystem or VirtualFileSystem()
        self.bus = bus or MailboxBus()
        self.devices = devices or DeviceBus()
        self.journal = journal or EventJournal()
        self.processes: dict[int, Process] = {}
        self.pipes: dict[str, PipeState] = {}
        self.init_pid: int | None = None
        self._next_pipe = 1
        self._next_description = 1
        self._open_files: dict[str, OpenFile] = {}
        self._fd_transfers: dict[str, FdTransfer] = {}
        self._next_transfer = 1
        self._next_pid = 1
        self.terminal_signal_handler: Callable[[int, str], None] | None = None
        if not self.devices.names():
            self.devices.register("null", NullDevice())
            self.devices.register("console", TerminalDevice())
            self.devices.register("dns_latch", DnsLatchDevice())

    def spawn(
        self,
        name: str,
        capabilities: tuple[Capability, ...] | None = None,
        environment: dict[str, str] | None = None,
        argv: Sequence[str] = (),
        parent_pid: int | None = None,
        group_id: int | None = None,
        session_id: int | None = None,
        inherit_fds: bool = False,
        subreaper: bool = False,
    ) -> int:
        """Mathematics: allocate PID `p` and construct process state with capabilities `C`, environment `E`, descriptors `F`, and subreaper flag `s`."""

        if not name:
            raise KernelError("process name must be non-empty")
        self._validate_argv(argv)
        if environment is not None:
            self._validate_environment(environment)
        if group_id is not None and group_id <= 0:
            raise KernelError("group id must be positive")
        if session_id is not None and session_id <= 0:
            raise KernelError("session id must be positive")
        parent = None if parent_pid is None else self._process(parent_pid)
        pid = self._next_pid
        self._next_pid += 1
        caps = capabilities if capabilities is not None else (
            parent.capabilities
            if parent is not None
            else (Capability("/", frozenset({"read", "write", "execute", "send", "receive"})),)
        )
        inherited_fds = (
            {
                fd: handle
                for fd, handle in parent.fds.items()
            }
            if inherit_fds and parent is not None
            else {}
        )
        inherited_fd_flags = (
            {
                fd: int(parent.fd_flags.get(fd, 0))
                for fd in inherited_fds
            }
            if inherit_fds and parent is not None
            else {}
        )
        self.processes[pid] = Process(
            pid=pid,
            name=name,
            status=ProcessStatus.RUNNABLE,
            capabilities=tuple(caps),
            cwd=parent.cwd if parent is not None else "/",
            fds=inherited_fds,
            fd_flags=inherited_fd_flags,
            next_fd=max((max(inherited_fds) + 1 if inherited_fds else 3), 3),
            environment=dict(parent.environment if parent is not None and environment is None else (environment or {})),
            argv=tuple(argv),
            parent_pid=parent_pid,
            group_id=group_id if group_id is not None else (parent.group_id if parent is not None else pid),
            session_id=session_id if session_id is not None else (parent.session_id if parent is not None else pid),
            subreaper=bool(subreaper),
            signal_dispositions=(
                dict(parent.signal_dispositions)
                if parent is not None
                else {}
            ),
        )
        if self.init_pid is None and parent_pid is None:
            self.init_pid = pid
            self.processes[pid].subreaper = True
            if "console" in self.devices.names():
                if self.devices.terminal("console") is not None:
                    self.devices.set_terminal_foreground(
                        "console",
                        self.processes[pid].session_id or pid,
                        self.processes[pid].group_id or pid,
                    )
        if not inherited_fds:
            self._install_standard_descriptors(self.processes[pid])
        self.journal.append("process.spawn", {"pid": pid, "name": name})
        return pid

    def sync_task_status(
        self,
        pid: int,
        status: ProcessStatus,
        exit_code: int | None = None,
    ) -> None:
        """Mathematics: synchronize scheduler state into `P[pid]` under the status map `σ`, journaling terminal exits once."""

        process = self._process(pid)
        if status is ProcessStatus.EXITED:
            if process.status is not ProcessStatus.EXITED:
                process.status = status
                process.exit_code = 0 if exit_code is None else int(exit_code)
                self._close_process_descriptors(process)
                self.journal.append("process.exit", {"pid": pid, "code": process.exit_code})
                self._adopt_orphans(pid)
            return
        if process.status is not ProcessStatus.EXITED:
            process.status = status

    def dispatch_terminal_signals(self) -> None:
        """Mathematics: consume terminal events `E` exactly once and apply `δ_signal(g,σ)` through the configured scheduler-aware handler or kernel fallback."""

        for device, group_id, signal in self.devices.pop_terminal_signals():
            self.journal.append(
                "terminal.signal",
                {"device": device, "group_id": group_id, "signal": signal},
            )
            if self.terminal_signal_handler is not None:
                self.terminal_signal_handler(group_id, signal)
            else:
                self._apply_terminal_signal(group_id, signal)

    def _apply_terminal_signal(self, group_id: int, signal: str) -> None:
        """Mathematics: apply `σ` to every live process in `G=group_id`, with `STOP→STOPPED`, `CONT→RUNNABLE`, and fatal `σ→EXITED`."""

        for process in sorted(self.processes.values(), key=lambda item: item.pid):
            if process.group_id != group_id or process.status is ProcessStatus.EXITED:
                continue
            self._apply_process_signal(process, signal)

    def _apply_process_signal(self, process: Process, signal: str) -> None:
        """Mathematics: apply one typed event `δ_signal(P,σ)` to a live process record, including fatal exit cleanup."""

        exit_codes = {signal.value: signal.default_exit_code for signal in Signal if signal.is_fatal}
        if process.signal_dispositions.get(signal) == "ignore" and signal not in {"KILL", "STOP"}:
            self.journal.append("signal.ignored", {"pid": process.pid, "signal": signal})
            return
        if signal == "STOP":
            process.status = ProcessStatus.STOPPED
        elif signal == "CONT":
            process.status = ProcessStatus.RUNNABLE
        elif signal in exit_codes:
            process.status = ProcessStatus.EXITED
            process.exit_code = exit_codes[signal]
            self._close_process_descriptors(process)
            self._adopt_orphans(process.pid)
        else:
            raise KernelError(f"unknown terminal signal: {signal}")

    def set_signal_disposition(self, pid: int, signal: str | Signal, disposition: str) -> str:
        """Mathematics: update signal disposition `D_pid[σ]∈{default,ignore}` for allowed signals and return `D_pid^old[σ]`."""

        process = self._process(pid)
        parsed = Signal.parse(signal)
        normalized = str(disposition).lower().removeprefix("sig_")
        if normalized in {"sig_dfl", "dfl", "default"}:
            normalized = "default"
        elif normalized in {"sig_ign", "ign", "ignore"}:
            normalized = "ignore"
        else:
            raise KernelError("signal disposition must be default or ignore")
        if normalized == "ignore" and parsed in {Signal.KILL, Signal.STOP}:
            raise KernelError(f"signal cannot be ignored: {parsed.value}")
        previous = process.signal_dispositions.get(parsed.value, "default")
        if normalized == "default":
            process.signal_dispositions.pop(parsed.value, None)
        else:
            process.signal_dispositions[parsed.value] = normalized
        self.journal.append(
            "signal.disposition",
            {"pid": pid, "signal": parsed.value, "disposition": normalized},
        )
        return previous

    def signal_is_ignored(self, pid: int, signal: str | Signal) -> bool:
        """Mathematics: project `I(pid,σ)=[D_pid[σ]=ignore]` without changing process or journal state."""

        process = self._process(pid)
        return process.signal_dispositions.get(Signal.parse(signal).value) == "ignore"

    def exec_process(self, pid: int, name: str, argv: Sequence[str]) -> None:
        """Mathematics: replace process image metadata while preserving `pid,C,E,F,cwd,parent,group` and setting status to runnable."""

        process = self._process(pid)
        if process.status is ProcessStatus.EXITED:
            raise KernelError("exited process cannot exec")
        if not name:
            raise KernelError("exec name must be non-empty")
        self._validate_argv(argv)
        self._close_on_exec(process)
        process.name = name
        process.argv = tuple(argv)
        process.status = ProcessStatus.RUNNABLE
        process.exit_code = None
        self.journal.append("process.exec", {"pid": pid, "name": name, "argv": list(argv)})

    def _adopt_orphans(self, parent_pid: int) -> None:
        """Mathematics: set `parent(c) := A(parent_pid)` for each unreaped child, where `A` is the nearest live subreaper or init."""

        if self.init_pid is None:
            return
        target_pid = self._adoption_target(parent_pid)
        for child in sorted(self.processes.values(), key=lambda item: item.pid):
            if child.parent_pid == parent_pid and child.pid != target_pid and not child.reaped:
                old_parent_pid = child.parent_pid
                child.parent_pid = target_pid
                self.journal.append(
                    "process.adopt",
                    {"pid": child.pid, "old_parent_pid": old_parent_pid, "new_parent_pid": target_pid},
                )

    def _adoption_target(self, exiting_parent_pid: int) -> int | None:
        """Mathematics: compute `A(p)=argmin_k{k>0 | s(p_k)=1 ∧ live(p_k)}` or live init, else `⊥`."""

        visited: set[int] = {exiting_parent_pid}
        cursor_pid = self.processes.get(exiting_parent_pid).parent_pid if exiting_parent_pid in self.processes else None
        while cursor_pid is not None and cursor_pid not in visited:
            visited.add(cursor_pid)
            candidate = self.processes.get(cursor_pid)
            if candidate is None:
                break
            if candidate.status is not ProcessStatus.EXITED and not candidate.reaped and candidate.subreaper:
                return candidate.pid
            cursor_pid = candidate.parent_pid
        init = None if self.init_pid is None else self.processes.get(self.init_pid)
        if init is not None and init.pid != exiting_parent_pid and init.status is not ProcessStatus.EXITED and not init.reaped:
            return init.pid
        return None

    def set_subreaper(self, pid: int, enabled: bool) -> bool:
        """Mathematics: set process subreaper flag `s_pid := enabled` and return previous value `s_pid^old`."""

        process = self._process(pid)
        previous = process.subreaper
        process.subreaper = bool(enabled)
        self.journal.append("process.subreaper", {"pid": pid, "enabled": process.subreaper})
        return previous

    def getpgid(self, caller_pid: int, target_pid: int | None = None) -> int:
        """Mathematics: project process-group identity `G(c,t)=group(t)` for target `t` or caller `c`."""

        caller = self._process(caller_pid)
        target = caller if target_pid is None else self._process(target_pid)
        if target.session_id != caller.session_id:
            raise KernelError("process belongs to another session")
        if target.group_id is None:
            raise KernelError("process has no process group")
        return target.group_id

    def getsid(self, caller_pid: int, target_pid: int | None = None) -> int:
        """Mathematics: project session identity `S(c,t)=session(t)` for target `t` or caller `c`, requiring same-session visibility."""

        caller = self._process(caller_pid)
        target = caller if target_pid is None else self._process(target_pid)
        if target.session_id != caller.session_id:
            raise KernelError("process belongs to another session")
        if target.session_id is None:
            raise KernelError("process has no session")
        return target.session_id

    def setsid(self, pid: int) -> int:
        """Mathematics: realize `session(pid):=pid` and `group(pid):=pid` when `pid∉G`."""

        process = self._process(pid)
        if process.group_id == pid:
            raise KernelError("process-group leader cannot create a session")
        process.session_id = pid
        process.group_id = pid
        self.journal.append("process.setsid", {"pid": pid, "session_id": pid, "group_id": pid})
        return pid

    def setpgid(self, caller_pid: int, target_pid: int | None = None, group_id: int | None = None) -> int:
        """Mathematics: assign `group(target):=g` only for self/child `target` in caller's session and existing group `g` or `g=target`."""

        caller = self._process(caller_pid)
        target = caller if target_pid is None else self._process(target_pid)
        if target.pid != caller.pid and target.parent_pid != caller.pid:
            raise KernelError("setpgid target must be caller or direct child")
        if target.status is ProcessStatus.EXITED:
            raise KernelError("cannot set group of exited process")
        if target.session_id != caller.session_id:
            raise KernelError("target belongs to another session")
        requested = target.pid if group_id is None else int(group_id)
        if requested <= 0:
            raise KernelError("group id must be positive")
        if requested != target.pid and not any(
            process.session_id == target.session_id and process.group_id == requested
            for process in self.processes.values()
        ):
            raise KernelError("target process group does not exist in session")
        target.group_id = requested
        self.journal.append(
            "process.setpgid",
            {"caller_pid": caller_pid, "pid": target.pid, "group_id": requested},
        )
        return requested

    def waitpid(self, parent_pid: int, child_pid: int | None = None, nohang: bool = False) -> dict[str, Any] | None:
        """Mathematics: select least exited unreaped child `c`, return it once, or expose `⊥/would-block` when none is ready."""

        self._process(parent_pid)
        if child_pid is not None and child_pid == 0:
            raise KernelError("waitpid child pid must be positive or -1")
        children = [
            process
            for process in self.processes.values()
            if process.parent_pid == parent_pid
            and not process.reaped
            and (child_pid is None or child_pid == -1 or process.pid == child_pid)
        ]
        if not children:
            raise KernelError("no child process")
        exited = sorted(
            (process for process in children if process.status is ProcessStatus.EXITED),
            key=lambda item: item.pid,
        )
        if not exited:
            if nohang:
                return None
            raise KernelError("wait would block")
        child = exited[0]
        child.reaped = True
        result = {"pid": child.pid, "exit_code": child.exit_code, "status": child.status.value}
        self.journal.append("process.wait", {"parent_pid": parent_pid, **result})
        return result

    def reap_process(self, pid: int) -> tuple[FdTransfer, ...]:
        """Mathematics: remove reaped process `p`, cancel undeliverable transfers addressed to `p`, and return their held descriptions."""

        process = self._process(pid)
        if not process.reaped or process.status is not ProcessStatus.EXITED:
            raise KernelError("process is not ready to reap")
        orphaned_transfers = tuple(
            transfer
            for transfer in self._fd_transfers.values()
            if transfer.destination_pid == pid
        )
        orphaned_ids = {transfer.transfer_id for transfer in orphaned_transfers}
        for transfer_id in orphaned_ids:
            self._fd_transfers.pop(transfer_id, None)
        self.bus.remove_matching(
            f"proc:{pid}:rights",
            lambda message: message.kind == "SCM_RIGHTS"
            and message.payload.get("transfer_id") in orphaned_ids,
        )
        del self.processes[pid]
        for pipe_id in tuple(self.pipes):
            if not self._pipe_referenced(pipe_id):
                self.pipes.pop(pipe_id, None)
        self._gc_open_files()
        self.journal.append("process.reap", {"pid": pid})
        return orphaned_transfers

    def _process(self, pid: int) -> Process:
        """Mathematics: perform the partial process-table lookup `P[pid]`, failing instead of inventing a task."""

        try:
            return self.processes[pid]
        except KeyError as exc:
            raise KernelError(f"unknown pid: {pid}") from exc

    def _authorize(self, process: Process, path: str, right: str) -> None:
        """Mathematics: require `∃c ∈ capabilities(process): c.allows(path, right)`, otherwise reject the effect."""

        if not any(capability.allows(path, right) for capability in process.capabilities):
            raise KernelError(f"permission denied: {right} {normalize_path(path)}")

    def _resolve_path(self, process: Process, path: str) -> str:
        """Mathematics: resolve `p` by `N(p)` when absolute, otherwise by `N(cwd(process)/p)` within the root namespace."""

        if not isinstance(path, str) or not path:
            raise KernelError("path must be a non-empty string")
        if path.startswith("/"):
            return normalize_path(path)
        return normalize_path(process.cwd.rstrip("/") + "/" + path)

    def device_name_for_path(self, path: str) -> str | None:
        """Mathematics: identify `d` exactly when `path=/dev/d` and `d∈dom(DeviceBus)`, otherwise return `⊥`."""

        if not isinstance(path, str) or not path.startswith("/"):
            return None
        canonical = normalize_path(path)
        if not canonical.startswith("/dev/"):
            return None
        name = canonical.removeprefix("/dev/")
        if not name or "/" in name or name not in self.devices.names():
            return None
        return name

    def syscall(self, pid: int, name: str, **args: Any) -> Any:
        """Mathematics: evaluate the typed syscall transition `δ_syscall(P[pid], name, args) -> (P', I', Q', result)`."""

        process = self._process(pid)
        if process.status is ProcessStatus.EXITED:
            raise KernelError("exited process cannot issue syscalls")
        self.journal.append(
            "syscall.begin",
            {"pid": pid, "name": name, "args": _log_value(args)},
        )
        try:
            result = self._dispatch(process, name, args)
        except (FsError, KeyError, ValueError) as exc:
            raise KernelError(str(exc)) from exc
        self.journal.append("syscall.end", {"pid": pid, "name": name, "result": _log_value(result)})
        return result

    def process_context_blob(self, pid: int, field: str) -> bytes:
        """Mathematics: encode process context as `E(x)=||_i UTF8(x_i)||0x00`, with `x_i=argv_i`, `KEY=VALUE`, or `cwd`."""

        process = self._process(pid)
        if field == "argv":
            values = tuple(process.argv)
        elif field == "environment":
            values = tuple(
                f"{key}={value}"
                for key, value in sorted(process.environment.items())
            )
        elif field == "cwd":
            values = (process.cwd,)
        else:
            raise KernelError(f"unknown process context field: {field}")
        if any("\x00" in value for value in values):
            raise KernelError(f"process {field} contains NUL")
        return b"".join(value.encode("utf-8") + b"\x00" for value in values)

    @staticmethod
    def _validate_argv(argv: Sequence[str]) -> None:
        r"""Mathematics: require `argv ∈ (Σ* \ {NUL})*` so NUL-delimited decoding is injective."""

        if any(not isinstance(argument, str) or "\x00" in argument for argument in argv):
            raise KernelError("argv entries must be strings without NUL")

    @staticmethod
    def _validate_environment(environment: dict[str, str]) -> None:
        r"""Mathematics: require each environment pair `(k,v)` to lie in `K×(Σ*\{NUL})`, with POSIX-shaped identifier keys."""

        for key, value in environment.items():
            if (
                not isinstance(key, str)
                or not key
                or not (key[0].isalpha() or key[0] == "_")
                or not all(character.isalnum() or character == "_" for character in key)
            ):
                raise KernelError(f"invalid environment key: {key}")
            if not isinstance(value, str) or "\x00" in value or "=" in key:
                raise KernelError(f"invalid environment value for {key}")

    def _dispatch(self, process: Process, name: str, args: dict[str, Any]) -> Any:
        """Mathematics: implement the syscall case split as a partial function over the Unix surface."""

        if name == "getpid":
            return process.pid
        if name == "getppid":
            return 0 if process.parent_pid is None else process.parent_pid
        if name == "argv_size":
            return len(self.process_context_blob(process.pid, "argv"))
        if name == "environ_size":
            return len(self.process_context_blob(process.pid, "environment"))
        if name == "getcwd_size":
            return len(self.process_context_blob(process.pid, "cwd"))
        if name in {"errno", "get_errno"}:
            return process.errno
        if name == "getcwd":
            return process.cwd
        if name == "chdir":
            path = self._resolve_path(process, args["path"])
            self._authorize(process, path, "execute")
            if self.fs.stat(path).kind != "directory":
                raise KernelError(f"not a directory: {path}")
            process.cwd = path
            return 0
        if name == "set_subreaper":
            return self.set_subreaper(process.pid, bool(args.get("enabled", True)))
        if name == "signal_set_ignored":
            return int(
                self.set_signal_disposition(
                    process.pid,
                    str(args["signal"]),
                    "ignore" if bool(args.get("ignored", True)) else "default",
                )
                == "ignore"
            )
        if name == "signal_is_ignored":
            return int(self.signal_is_ignored(process.pid, str(args["signal"])))
        if name == "get_subreaper":
            return process.subreaper
        if name == "getpgid":
            raw_target = args.get("target_pid")
            return self.getpgid(process.pid, None if raw_target is None else int(raw_target))
        if name == "getsid":
            raw_target = args.get("target_pid")
            return self.getsid(process.pid, None if raw_target is None else int(raw_target))
        if name == "setsid":
            return self.setsid(process.pid)
        if name == "setpgid":
            raw_target = args.get("target_pid")
            raw_group = args.get("group_id")
            return self.setpgid(
                process.pid,
                None if raw_target is None else int(raw_target),
                None if raw_group is None else int(raw_group),
            )
        if name == "getenv":
            return process.environment.get(str(args["key"]))
        if name == "environ":
            return dict(sorted(process.environment.items()))
        if name == "setenv":
            key = str(args["key"])
            value = str(args["value"])
            if not key or not (key[0].isalpha() or key[0] == "_") or not all(
                character.isalnum() or character == "_" for character in key
            ):
                raise KernelError(f"invalid environment key: {key}")
            if "\x00" in value:
                raise KernelError("environment value must not contain NUL")
            process.environment[key] = value
            return 0
        if name == "open":
            return self._open(process, args["path"], args.get("mode", "r"), args.get("create", False))
        if name == "close":
            return self._close(process, args["fd"])
        if name == "read":
            return self._read(process, args["fd"], args.get("size", -1))
        if name == "write":
            return self._write(process, args["fd"], args["data"])
        if name == "dup":
            return self._dup(process, int(args["fd"]), None)
        if name == "dup2":
            return self._dup(process, int(args["fd"]), int(args["new_fd"]))
        if name == "fcntl":
            return self._fcntl(process, int(args["fd"]), int(args["command"]), int(args.get("arg", 0)))
        if name == "tcgetpgrp":
            return self._tcgetpgrp(process, int(args["fd"]))
        if name == "tcsetpgrp":
            return self._tcsetpgrp(process, int(args["fd"]), int(args["group_id"]))
        if name == "tty_setmode":
            self._tty_setmode(
                process,
                int(args["fd"]),
                bool(args.get("canonical", True)),
                bool(args.get("echo", False)),
                None if "isig" not in args else bool(args["isig"]),
            )
            return 0
        if name == "tty_canonical":
            return int(self._tty_mode(process, int(args["fd"]))[0])
        if name == "tty_echo":
            return int(self._tty_mode(process, int(args["fd"]))[1])
        if name == "tty_isig":
            return int(self._tty_mode(process, int(args["fd"]))[2])
        if name == "send_fd":
            return self._send_fd(process, int(args["fd"]), int(args["destination_pid"]))
        if name == "receive_fd":
            raw_source = args.get("source_pid")
            return self._receive_fd(
                process,
                None if raw_source is None else int(raw_source),
                None if args.get("target_fd") is None else int(args["target_fd"]),
            )
        if name == "fstat":
            return self._fstat(process, int(args["fd"]))
        if name == "lseek":
            return self._lseek(process, args["fd"], int(args.get("offset", 0)), args.get("whence", 0))
        if name == "pipe":
            return self._pipe(process)
        if name == "pty_open":
            return self._pty_open(process)
        if name == "waitpid":
            raw_child = args.get("child_pid")
            child_pid = None if raw_child is None else int(raw_child)
            return self.waitpid(process.pid, child_pid, bool(args.get("nohang", False)))
        if name == "mkdir":
            path = self._resolve_path(process, args["path"])
            self._authorize(process, path, "write")
            self.fs.mkdir(path, args.get("mode", 0o755), process.pid)
            return 0
        if name == "listdir":
            path = self._resolve_path(process, args["path"])
            self._authorize(process, path, "read")
            return self.fs.listdir(path)
        if name == "stat":
            path = self._resolve_path(process, args["path"])
            self._authorize(process, path, "read")
            return self.fs.stat(path)
        if name == "unlink":
            path = self._resolve_path(process, args["path"])
            self._authorize(process, path, "write")
            if self.fs.stat(path).kind == "directory":
                raise KernelError(f"is a directory: {path}")
            self.fs.remove(path)
            return 0
        if name == "rmdir":
            path = self._resolve_path(process, args["path"])
            self._authorize(process, path, "write")
            if self.fs.stat(path).kind != "directory":
                raise KernelError(f"not a directory: {path}")
            self.fs.remove(path)
            return 0
        if name == "rename":
            old_path = self._resolve_path(process, args["old_path"])
            new_path = self._resolve_path(process, args["new_path"])
            self._authorize(process, old_path, "write")
            self._authorize(process, new_path, "write")
            self.fs.rename(old_path, new_path, bool(args.get("replace", False)))
            self._rewrite_open_paths(old_path, new_path)
            return 0
        if name == "send":
            destination = args["destination"]
            self._authorize(process, f"/bus/{destination}", "send")
            message = self.bus.send(
                f"proc:{process.pid}",
                destination,
                args.get("kind", "data"),
                args.get("payload", {}),
            )
            return message.message_id
        if name == "receive":
            self._authorize(process, f"/bus/proc:{process.pid}", "receive")
            message = self.bus.receive(f"proc:{process.pid}")
            if message is None:
                process.status = ProcessStatus.BLOCKED
                return None
            process.status = ProcessStatus.RUNNABLE
            return message
        if name == "device_read":
            device = args["device"]
            self._authorize(process, f"/dev/{device}", "read")
            return self.devices.read(device, args.get("size", -1))
        if name == "device_write":
            device = args["device"]
            self._authorize(process, f"/dev/{device}", "write")
            return self.devices.write(device, args["data"])
        if name == "exit":
            process.status = ProcessStatus.EXITED
            process.exit_code = int(args.get("code", 0))
            self._close_process_descriptors(process)
            self.journal.append("process.exit", {"pid": process.pid, "code": process.exit_code})
            self._adopt_orphans(process.pid)
            return process.exit_code
        raise KernelError(f"unknown syscall: {name}")

    def _fstat(self, process: Process, fd: int) -> FileStat:
        """Mathematics: project descriptor state onto `F=(inode,kind,mode,owner,size)` for filesystem and synthetic resources."""

        handle = self._handle(process, fd)
        if handle.pipe_id is not None:
            pipe = self.pipes.get(handle.pipe_id)
            if pipe is None:
                raise KernelError(f"unknown pipe: {handle.pipe_id}")
            return FileStat(handle.description_id, "pipe", 0o600, 0, len(pipe.buffer))
        if handle.network_kind is not None:
            network_identity = f"{handle.network_kind}:{handle.network_handle}"
            return FileStat(network_identity, "socket", 0o600, 0, 0)
        device_name = self.device_name_for_path(handle.path)
        if device_name is not None:
            return FileStat(f"device:{device_name}", "device", 0o666, 0, 0)
        return self.fs.stat(handle.path)

    def _open(self, process: Process, path: str, mode: str, create: bool) -> int:
        """Mathematics: allocate the least unused descriptor `fd ≥ 3` and bind it to a validated access mode."""

        canonical = self._resolve_path(process, path)
        readable = "r" in mode or "+" in mode
        writable = "w" in mode or "a" in mode or "+" in mode
        if not readable and not writable:
            raise KernelError("open mode must contain r, w, a, or +")
        self._authorize(process, canonical, "read" if readable else "write")
        if writable:
            self._authorize(process, canonical, "write")
        if create:
            # Namespace creation is itself a write, even when the resulting
            # descriptor is requested read-only.
            self._authorize(process, canonical, "write")
        device_name = self.device_name_for_path(canonical)
        append_offset = 0
        try:
            self.fs.stat(canonical)
        except FsError:
            if device_name is None and not create:
                raise
            if device_name is None:
                self.fs.create_file(canonical, owner=process.pid)
        else:
            if device_name is None and "w" in mode and "a" not in mode:
                self.fs.write_file(canonical, b"", offset=0, truncate=True)
            if device_name is None and "a" in mode:
                append_offset = self.fs.stat(canonical).size
        fd = process.next_fd
        process.next_fd += 1
        process.fds[fd] = self._new_open_file(
            canonical,
            append_offset,
            readable,
            writable,
            status_flags=O_APPEND if "a" in mode else 0,
        )
        return fd

    def _new_open_file(
        self,
        path: str,
        offset: int,
        readable: bool,
        writable: bool,
        pipe_id: str | None = None,
        network_kind: str | None = None,
        network_handle: int | None = None,
        status_flags: int = 0,
    ) -> OpenFile:
        """Mathematics: allocate one description `D_d=(path,o,r,w,p,n,h,φ)` and register identity `d`."""

        if int(status_flags) < 0 or int(status_flags) & ~_STATUS_FLAGS:
            raise KernelError("unsupported open-file status flags")

        description_id = f"o{self._next_description:08d}"
        self._next_description += 1
        handle = OpenFile(
            path,
            offset,
            readable,
            writable,
            pipe_id,
            description_id,
            network_kind,
            network_handle,
            int(status_flags),
        )
        self._open_files[description_id] = handle
        return handle

    def _pipe(self, process: Process) -> tuple[int, int]:
        """Mathematics: create FIFO `Q_p` and return read/write descriptors `(r,w)` with `|Q_p|≤C`."""

        pipe_id = f"p{self._next_pipe:08d}"
        self._next_pipe += 1
        self.pipes[pipe_id] = PipeState(pipe_id)
        read_fd = process.next_fd
        write_fd = read_fd + 1
        process.next_fd += 2
        process.fds[read_fd] = self._new_open_file(f"pipe:{pipe_id}", 0, True, False, pipe_id)
        process.fds[write_fd] = self._new_open_file(f"pipe:{pipe_id}", 0, False, True, pipe_id)
        return read_fd, write_fd

    def _pty_open(self, process: Process) -> tuple[int, int]:
        """Mathematics: create connected devices `(m,s)`, bind terminal ownership `(session,group)`, and return descriptor pair `(fd_m,fd_s)`."""

        master_name, slave_name = self.devices.create_pty_pair()
        master_fd: int | None = None
        slave_fd: int | None = None
        try:
            self.devices.set_terminal_foreground(slave_name, int(process.session_id or process.pid), int(process.group_id or process.pid))
            master_fd = self._open(process, f"/dev/{master_name}", "r+", False)
            slave_fd = self._open(process, f"/dev/{slave_name}", "r+", False)
        except BaseException:
            for fd in (slave_fd, master_fd):
                if fd is not None and fd in process.fds:
                    self._close(process, fd)
            self._gc_open_files()
            raise
        self.journal.append(
            "pty.open",
            {
                "pid": process.pid,
                "pair_id": f"pty{master_name.removeprefix('ptym')}",
                "master_fd": master_fd,
                "slave_fd": slave_fd,
            },
        )
        if master_fd is None or slave_fd is None:
            raise KernelError("pty descriptor allocation did not complete")
        return master_fd, slave_fd

    def _dup(self, process: Process, fd: int, new_fd: int | None) -> int:
        """Mathematics: map `fd'` to the same open description `D`, replacing `new_fd` when supplied and choosing the least free descriptor otherwise."""

        handle = self._handle(process, fd)
        if new_fd is None:
            candidate = 3
            while candidate in process.fds:
                candidate += 1
            new_fd = candidate
        if new_fd < 0:
            raise KernelError("descriptor must be non-negative")
        if new_fd == fd:
            return new_fd
        if new_fd in process.fds:
            self._close(process, new_fd)
        process.fds[new_fd] = handle
        process.fd_flags[new_fd] = 0
        process.next_fd = max(process.next_fd, new_fd + 1)
        return new_fd

    def _close(self, process: Process, fd: int) -> int:
        """Mathematics: remove descriptor mapping `F[fd]` and return zero iff `fd ∈ dom(F)`."""

        if fd not in process.fds:
            raise KernelError(f"bad file descriptor: {fd}")
        handle = process.fds.pop(fd)
        process.fd_flags.pop(fd, None)
        if handle.pipe_id is not None and not self._pipe_referenced(handle.pipe_id):
            self.pipes.pop(handle.pipe_id, None)
        self._gc_open_files()
        return 0

    def _close_process_descriptors(self, process: Process) -> None:
        """Mathematics: apply process termination law `F_process := ∅` by closing every descriptor alias exactly once."""

        for fd in sorted(tuple(process.fds)):
            self._close(process, fd)
        self.journal.append("process.fd_close_on_exit", {"pid": process.pid})

    def _close_on_exec(self, process: Process) -> None:
        """Mathematics: apply `exec` descriptor law `F' = {fd∈F : flags(fd)∩FD_CLOEXEC=∅}` before installing the new image."""

        marked = tuple(sorted(fd for fd, flags in process.fd_flags.items() if flags & FD_CLOEXEC))
        for fd in marked:
            if fd in process.fds:
                self._close(process, fd)
        if marked:
            self.journal.append("process.fd_close_on_exec", {"pid": process.pid, "fds": list(marked)})

    def _install_standard_descriptors(self, process: Process) -> None:
        """Mathematics: add `F[0]=console_read`, `F[1]=F[2]=console_write` iff the capability graph authorizes those endpoint projections."""

        if "console" not in self.devices.names():
            return
        if any(capability.allows("/dev/console", "read") for capability in process.capabilities):
            process.fds[0] = self._new_open_file("/dev/console", 0, True, False)
        if any(capability.allows("/dev/console", "write") for capability in process.capabilities):
            process.fds[1] = self._new_open_file("/dev/console", 0, False, True)
            process.fds[2] = self._new_open_file("/dev/console", 0, False, True)

    def _terminal_name_for_fd(self, process: Process, fd: int) -> str:
        """Mathematics: project `F_process[fd]` to terminal name `d` iff the descriptor path is a registered `/dev/d` terminal."""

        handle = self._handle(process, fd)
        name = self.device_name_for_path(handle.path)
        if name is None or self.devices.terminal(name) is None:
            raise KernelError("descriptor is not a terminal")
        return name

    def _check_terminal_access(self, process: Process, name: str, operation: str) -> None:
        """Mathematics: allow terminal operation iff `session(process)=session(T)` and, for reads, `group(process)=fg(T)`."""

        terminal = self.devices.terminal(name)
        if terminal is None:
            raise KernelError("device is not a terminal")
        if terminal.controlling_session_id is not None and process.session_id != terminal.controlling_session_id:
            raise KernelError("process has no controlling terminal")
        if operation == "read" and terminal.foreground_group_id is not None and process.group_id != terminal.foreground_group_id:
            raise KernelError("background process group cannot read terminal")

    def _tcgetpgrp(self, process: Process, fd: int) -> int:
        """Mathematics: return foreground group `fg(T)` after validating terminal membership of `process` and `fd`."""

        name = self._terminal_name_for_fd(process, fd)
        self._check_terminal_access(process, name, "control")
        terminal = self.devices.terminal(name)
        if terminal is None or terminal.foreground_group_id is None:
            raise KernelError("terminal has no foreground group")
        return terminal.foreground_group_id

    def _tcsetpgrp(self, process: Process, fd: int, group_id: int) -> int:
        """Mathematics: set `fg(T):=g` iff `g>0`, `session(g)=session(process)`, and the target group has a live member."""

        if group_id <= 0:
            raise KernelError("terminal group id must be positive")
        name = self._terminal_name_for_fd(process, fd)
        self._check_terminal_access(process, name, "write")
        target = [
            candidate
            for candidate in self.processes.values()
            if candidate.status is not ProcessStatus.EXITED
            and candidate.group_id == group_id
            and candidate.session_id == process.session_id
        ]
        if not target:
            raise KernelError("terminal foreground group is not in caller session")
        self.devices.set_terminal_foreground(name, process.session_id or 0, group_id)
        self.journal.append(
            "terminal.foreground",
            {"fd": fd, "device": name, "session_id": process.session_id, "group_id": group_id},
        )
        return 0

    def _tty_mode(self, process: Process, fd: int) -> tuple[bool, bool, bool]:
        """Mathematics: project terminal mode vector `M(T)=(canonical,echo,isig)` for a validated terminal descriptor."""

        name = self._terminal_name_for_fd(process, fd)
        self._check_terminal_access(process, name, "control")
        terminal = self.devices.terminal(name)
        if terminal is None:
            raise KernelError("device is not a terminal")
        return terminal.canonical, terminal.echo, terminal.isig

    def _tty_setmode(
        self,
        process: Process,
        fd: int,
        canonical: bool,
        echo: bool,
        isig: bool | None = None,
    ) -> None:
        """Mathematics: apply terminal mode transition `M(T):=(canonical,echo,isig)` after validating the controlling session."""

        name = self._terminal_name_for_fd(process, fd)
        self._check_terminal_access(process, name, "write")
        self.devices.set_terminal_mode_with_isig(name, canonical, echo, isig)
        self.journal.append(
            "terminal.mode",
            {"fd": fd, "device": name, "canonical": canonical, "echo": echo, "isig": isig},
        )

    def _read(self, process: Process, fd: int, size: int) -> bytes:
        """Mathematics: return `file[offset : offset + size]` and advance `offset := offset + |result|`."""

        handle = self._handle(process, fd)
        if handle.network_kind is not None:
            raise KernelError("network descriptor requires the headless OS authority")
        if not handle.readable:
            raise KernelError("file descriptor is not readable")
        device_name = self.device_name_for_path(handle.path)
        if device_name is not None:
            if self.devices.terminal(device_name) is not None:
                self._check_terminal_access(process, device_name, "read")
            if (
                handle.status_flags & O_NONBLOCK
                and device_name != "null"
                and not self.devices.readiness(device_name, True)
            ):
                raise KernelError("device would block")
            return self.devices.read(device_name, size)
        if handle.pipe_id is not None:
            return self._pipe_read(handle.pipe_id, size)
        data = self.fs.read_file(handle.path, handle.offset, size)
        handle.offset += len(data)
        return data

    def _write(self, process: Process, fd: int, data: bytes) -> int:
        """Mathematics: apply file update at cursor `o`, then advance `o := o + |data|`."""

        handle = self._handle(process, fd)
        if handle.network_kind is not None:
            raise KernelError("network descriptor requires the headless OS authority")
        if not handle.writable:
            raise KernelError("file descriptor is not writable")
        device_name = self.device_name_for_path(handle.path)
        if device_name is not None:
            if self.devices.terminal(device_name) is not None:
                self._check_terminal_access(process, device_name, "write")
            if self.devices.peer_hungup(device_name):
                raise KernelError("pty peer hung up")
            count = self.devices.write(device_name, data)
            self.dispatch_terminal_signals()
            return count
        if handle.pipe_id is not None:
            return self._pipe_write(handle.pipe_id, data)
        if handle.status_flags & O_APPEND:
            handle.offset = self.fs.stat(handle.path).size
        count = self.fs.write_file(handle.path, data, handle.offset)
        handle.offset += count
        return count

    def _fcntl(self, process: Process, fd: int, command: int, argument: int) -> int:
        """Mathematics: apply shared-description `F_GETFL/F_SETFL` or descriptor-local `F_GETFD/F_SETFD` without conflating `D` and `fd` state."""

        handle = self._handle(process, fd)
        access = 2 if handle.readable and handle.writable else 1 if handle.writable else 0
        if command == F_GETFD:
            return int(process.fd_flags.get(fd, 0))
        if command == F_SETFD:
            if argument < 0 or argument & ~FD_CLOEXEC:
                raise KernelError("unsupported descriptor flags")
            process.fd_flags[fd] = argument & FD_CLOEXEC
            return 0
        if command == F_GETFL:
            return access | handle.status_flags
        if command != F_SETFL:
            raise KernelError(f"unsupported fcntl command: {command}")
        if argument < 0 or argument & ~(_STATUS_FLAGS | _ACCESS_MODE):
            raise KernelError("unsupported fcntl status flags")
        handle.status_flags = argument & _STATUS_FLAGS
        return 0

    def _send_fd(self, process: Process, fd: int, destination_pid: int) -> int:
        """Mathematics: create durable transfer `T[t]=(sender,destination,D_fd)` and enqueue one `SCM_RIGHTS` bus message without copying `D_fd`."""

        destination = self._process(destination_pid)
        self._authorize(process, f"/proc/{destination.pid}/fd", "send")
        description = self._handle(process, fd)
        transfer_id = f"x{self._next_transfer:08d}"
        self._next_transfer += 1
        transfer = FdTransfer(transfer_id, process.pid, destination.pid, description)
        self._fd_transfers[transfer_id] = transfer
        self.bus.send(
            f"proc:{process.pid}",
            f"proc:{destination.pid}:rights",
            "SCM_RIGHTS",
            {"transfer_id": transfer_id},
        )
        self.journal.append(
            "fd.send",
            {
                "transfer_id": transfer_id,
                "sender_pid": process.pid,
                "destination_pid": destination.pid,
                "description_id": description.description_id,
            },
        )
        return 0

    def _receive_fd(
        self,
        process: Process,
        source_pid: int | None,
        target_fd: int | None,
    ) -> int:
        """Mathematics: consume FIFO transfer head `T[t]`, install its shared description at a fresh `fd`, and return `0` iff no transfer is ready."""

        self._authorize(process, f"/proc/{process.pid}/fd", "receive")
        if target_fd is not None and target_fd < 0:
            raise KernelError("target descriptor must be non-negative")
        if target_fd is not None and target_fd in process.fds:
            raise KernelError("target descriptor is already occupied")
        destination = f"proc:{process.pid}:rights"
        head = self.bus.peek(destination)
        if not head:
            return 0
        message = head[0]
        expected_source = None if source_pid is None else f"proc:{source_pid}"
        if message.kind != "SCM_RIGHTS":
            raise KernelError("rights mailbox contains a non-rights message")
        if expected_source is not None and message.source != expected_source:
            return 0
        raw_transfer_id = message.payload.get("transfer_id")
        if not isinstance(raw_transfer_id, str):
            raise KernelError("SCM_RIGHTS message has no transfer identity")
        transfer = self._fd_transfers.get(raw_transfer_id)
        if transfer is None or transfer.destination_pid != process.pid:
            raise KernelError("SCM_RIGHTS transfer is missing or addressed to another process")
        consumed = self.bus.receive(destination)
        if consumed is None or consumed.message_id != message.message_id:
            raise KernelError("SCM_RIGHTS mailbox changed during receive")
        self._fd_transfers.pop(raw_transfer_id, None)
        fd = target_fd
        if fd is None:
            fd = process.next_fd
            while fd in process.fds:
                fd += 1
        process.fds[fd] = transfer.description
        process.fd_flags[fd] = 0
        process.next_fd = max(process.next_fd, fd + 1)
        self.journal.append(
            "fd.receive",
            {
                "transfer_id": transfer.transfer_id,
                "sender_pid": transfer.sender_pid,
                "destination_pid": process.pid,
                "fd": fd,
                "description_id": transfer.description.description_id,
            },
        )
        self._gc_open_files()
        return fd

    def fd_transfer_pending(self, pid: int, source_pid: int | None = None) -> bool:
        """Mathematics: evaluate `∃m∈Q_rights(pid): kind(m)=SCM_RIGHTS ∧ source(m)=source_pid` without dequeuing."""

        expected_source = None if source_pid is None else f"proc:{source_pid}"
        return any(
            message.kind == "SCM_RIGHTS"
            and (expected_source is None or message.source == expected_source)
            for message in self.bus.peek(f"proc:{pid}:rights")
        )

    def pending_fd_handles(self) -> tuple[OpenFile, ...]:
        """Mathematics: project in-flight descriptions `P={D_t | t∈dom(T)}` so external resource GC retains message references."""

        return tuple(transfer.description for transfer in self._fd_transfers.values())

    def _lseek(self, process: Process, fd: int, offset: int, whence: int | str) -> int:
        """Mathematics: set cursor `o' = b_w + offset`, where `b_0=0`, `b_1=o`, and `b_2=|file|`, requiring `o'≥0`."""

        handle = self._handle(process, fd)
        if handle.network_kind is not None:
            raise KernelError("cannot seek a network descriptor")
        if handle.pipe_id is not None:
            raise KernelError("cannot seek a pipe")
        if self.device_name_for_path(handle.path) is not None:
            raise KernelError("cannot seek a device descriptor")
        if whence in (0, "set"):
            base = 0
        elif whence in (1, "cur"):
            base = handle.offset
        elif whence in (2, "end"):
            base = self.fs.stat(handle.path).size
        else:
            raise KernelError(f"invalid seek origin: {whence}")
        result = base + offset
        if result < 0:
            raise KernelError("seek offset before start of file")
        handle.offset = result
        return result

    def _rewrite_open_paths(self, old_path: str, new_path: str) -> None:
        """Mathematics: transport each handle path by `p:=new ⧺ suffix` when `p=old ⧺ suffix`, preserving descriptor cursor state across file or directory rename."""

        for process in self.processes.values():
            for handle in process.fds.values():
                if handle.path == old_path or handle.path.startswith(old_path.rstrip("/") + "/"):
                    handle.path = new_path + handle.path[len(old_path) :]

    def _handle(self, process: Process, fd: int) -> OpenFile:
        """Mathematics: perform the partial descriptor lookup `F[fd]`, requiring `fd ∈ dom(F)`."""

        try:
            return process.fds[fd]
        except KeyError as exc:
            raise KernelError(f"bad file descriptor: {fd}") from exc

    def descriptor_readiness(self, pid: int, fd: int, events: int) -> int:
        """Mathematics: compute `R(fd,E) ⊆ {IN,OUT,ERR,HUP}` from the current finite descriptor state without consuming bytes."""

        process = self._process(pid)
        descriptor = self._handle(process, int(fd))
        if descriptor.network_kind is not None:
            raise KernelError("network descriptor readiness requires the headless OS authority")
        requested = int(events)
        if requested < 0:
            raise KernelError("poll events must be non-negative")
        readiness = 0
        if descriptor.pipe_id is not None:
            pipe = self.pipes.get(descriptor.pipe_id)
            if pipe is None:
                return POLLERR
            if descriptor.readable:
                if pipe.buffer:
                    readiness |= POLLIN
                if not self._pipe_has_endpoint(descriptor.pipe_id, readable=False):
                    readiness |= POLLHUP
            if descriptor.writable:
                if self._pipe_has_endpoint(descriptor.pipe_id, readable=True) and len(pipe.buffer) < pipe.capacity:
                    readiness |= POLLOUT
                elif not self._pipe_has_endpoint(descriptor.pipe_id, readable=True):
                    readiness |= POLLERR
        else:
            device_name = self.device_name_for_path(descriptor.path)
            if device_name is not None:
                if self.devices.terminal(device_name) is not None and requested & POLLIN:
                    self._check_terminal_access(process, device_name, "read")
                if self.devices.peer_hungup(device_name):
                    readiness |= POLLHUP
                if descriptor.readable and self.devices.readiness(device_name, True):
                    readiness |= POLLIN
                if descriptor.writable and self.devices.readiness(device_name, False):
                    readiness |= POLLOUT
            else:
                # Regular virtual files are seekable and therefore immediately
                # ready whenever the descriptor grants the corresponding mode.
                if descriptor.readable:
                    readiness |= POLLIN
                if descriptor.writable:
                    readiness |= POLLOUT
        return readiness & (requested | POLLERR | POLLHUP)

    def _pipe_referenced(self, pipe_id: str) -> bool:
        r"""Mathematics: determine `∃p,fd: fds_p[fd].pipe_id=p ∨ ∃t: T[t].description.pipe_id=p`, including in-flight FD transfers."""

        return any(
            handle.pipe_id == pipe_id
            for process in self.processes.values()
            for handle in process.fds.values()
        ) or any(
            transfer.description.pipe_id == pipe_id
            for transfer in self._fd_transfers.values()
        )

    def _gc_open_files(self) -> None:
        """Mathematics: retain exactly `D={handle | ∃p,fd: fds_p[fd]=handle}` and discard unreachable open descriptions."""

        referenced = {
            handle.description_id
            for process in self.processes.values()
            for handle in process.fds.values()
            if handle.description_id
        }
        referenced.update(
            transfer.description.description_id
            for transfer in self._fd_transfers.values()
            if transfer.description.description_id
        )
        for description_id in tuple(self._open_files):
            if description_id not in referenced:
                del self._open_files[description_id]
        referenced_paths = {
            handle.path
            for process in self.processes.values()
            for handle in process.fds.values()
        }
        referenced_paths.update(transfer.description.path for transfer in self._fd_transfers.values())
        hangups = self.devices.reconcile_pty_liveness(referenced_paths)
        for pair_id, session_id, group_id in hangups:
            self.journal.append(
                "pty.hangup",
                {
                    "pair_id": pair_id,
                    "session_id": session_id,
                    "group_id": group_id,
                    "signal": "HUP" if group_id is not None else None,
                },
            )
            if group_id is not None:
                if self.terminal_signal_handler is not None:
                    self.terminal_signal_handler(group_id, "HUP")
                else:
                    self._apply_terminal_signal(group_id, "HUP")

    def _pipe_has_endpoint(self, pipe_id: str, readable: bool) -> bool:
        """Mathematics: test endpoint existence `∃fd: pipe_id(fd)=p ∧ readable(fd)=r` for EOF/broken-pipe semantics."""

        return any(
            handle.pipe_id == pipe_id and (handle.readable if readable else handle.writable)
            for process in self.processes.values()
            for handle in process.fds.values()
        )

    def _pipe_read(self, pipe_id: str, size: int) -> bytes:
        """Mathematics: consume prefix `Q_p[:n]`, raising would-block when `Q_p=∅` and writers remain."""

        try:
            pipe = self.pipes[pipe_id]
        except KeyError as exc:
            raise KernelError(f"unknown pipe: {pipe_id}") from exc
        if not pipe.buffer:
            if self._pipe_has_endpoint(pipe_id, readable=False):
                raise KernelError("pipe would block")
            return b""
        count = len(pipe.buffer) if size < 0 else min(size, len(pipe.buffer))
        data = bytes(pipe.buffer[:count])
        del pipe.buffer[:count]
        return data

    def _pipe_write(self, pipe_id: str, data: bytes) -> int:
        """Mathematics: append the maximal prefix `B[:k]` where `k=min(|B|,C-|Q_p|)` and return `k`, failing only when `k=0` or readers are absent."""

        try:
            pipe = self.pipes[pipe_id]
        except KeyError as exc:
            raise KernelError(f"unknown pipe: {pipe_id}") from exc
        if not self._pipe_has_endpoint(pipe_id, readable=True):
            raise KernelError("broken pipe")
        available = pipe.capacity - len(pipe.buffer)
        if available <= 0:
            raise KernelError("pipe full")
        count = min(len(data), available)
        pipe.buffer.extend(data[:count])
        return count

    def process_table(self) -> tuple[dict[str, Any], ...]:
        """Mathematics: expose the finite projection `{pid, name, state, exit_code}` for each process-table row."""

        return tuple(
            {
                "pid": process.pid,
                "name": process.name,
                "status": process.status.value,
                "exit_code": process.exit_code,
                "argv": list(process.argv),
                "parent_pid": process.parent_pid,
                "group_id": process.group_id,
                "session_id": process.session_id,
                "reaped": process.reaped,
                "subreaper": process.subreaper,
                "errno": process.errno,
            }
            for process in sorted(self.processes.values(), key=lambda item: item.pid)
        )

    def snapshot(self) -> dict[str, Any]:
        """Mathematics: serialize the complete kernel state tuple `K = (I, Q, D, P, J)` into a replay artifact."""

        return {
            "filesystem": self.fs.snapshot(),
            "bus": self.bus.snapshot(),
            "processes": self.process_table(),
            "process_details": {
                str(process.pid): {
                    "pid": process.pid,
                    "name": process.name,
                    "status": process.status.value,
                    "capabilities": [
                        {"resource": capability.resource, "rights": sorted(capability.rights)}
                        for capability in process.capabilities
                    ],
                    "cwd": process.cwd,
                    "fds": {
                        str(fd): {
                            "path": handle.path,
                            "offset": handle.offset,
                            "readable": handle.readable,
                            "writable": handle.writable,
                            "pipe_id": handle.pipe_id,
                            "description_id": handle.description_id,
                            "network_kind": handle.network_kind,
                            "network_handle": handle.network_handle,
                            "status_flags": handle.status_flags,
                        }
                        for fd, handle in sorted(process.fds.items())
                    },
                    "fd_flags": {
                        str(fd): int(flags)
                        for fd, flags in sorted(process.fd_flags.items())
                    },
                    "next_fd": process.next_fd,
                    "exit_code": process.exit_code,
                    "environment": dict(sorted(process.environment.items())),
                    "argv": list(process.argv),
                    "parent_pid": process.parent_pid,
                    "group_id": process.group_id,
                    "session_id": process.session_id,
                    "reaped": process.reaped,
                    "subreaper": process.subreaper,
                    "errno": process.errno,
                    "signal_dispositions": dict(sorted(process.signal_dispositions.items())),
                }
                for process in sorted(self.processes.values(), key=lambda item: item.pid)
            },
            "next_pid": self._next_pid,
            "init_pid": self.init_pid,
            "pipes": {
                pipe_id: {
                    "buffer_hex": bytes(pipe.buffer).hex(),
                    "capacity": pipe.capacity,
                }
                for pipe_id, pipe in sorted(self.pipes.items())
            },
            "next_pipe": self._next_pipe,
            "next_description": self._next_description,
            "next_transfer": self._next_transfer,
            "fd_transfers": {
                transfer_id: {
                    "sender_pid": transfer.sender_pid,
                    "destination_pid": transfer.destination_pid,
                    "description_id": transfer.description.description_id,
                }
                for transfer_id, transfer in sorted(self._fd_transfers.items())
            },
            "open_descriptions": {
                description_id: {
                    "path": handle.path,
                    "offset": handle.offset,
                    "readable": handle.readable,
                    "writable": handle.writable,
                    "pipe_id": handle.pipe_id,
                    "network_kind": handle.network_kind,
                    "network_handle": handle.network_handle,
                    "status_flags": handle.status_flags,
                }
                for description_id, handle in sorted(self._open_files.items())
            },
            "devices": self.devices.names(),
            "device_state": self.devices.snapshot(),
            "journal": self.journal.snapshot(),
        }

    @classmethod
    def from_snapshot(cls, payload: dict[str, Any]) -> "VirtualKernel":
        """Mathematics: reconstruct kernel product `K = (F, Q, D, P, J)` and validate process/resource references."""

        filesystem = VirtualFileSystem.from_snapshot(dict(payload["filesystem"]))
        bus = MailboxBus.from_snapshot(dict(payload["bus"]))
        devices = DeviceBus.from_snapshot(dict(payload.get("device_state", {})))
        journal = EventJournal.from_snapshot(list(payload["journal"]))
        kernel = cls(filesystem, bus, devices, journal)
        kernel.processes = {}
        kernel.pipes = {}
        for pipe_id, raw in payload.get("pipes", {}).items():
            pipe_key = str(pipe_id)
            if not pipe_key.startswith("p") or not pipe_key[1:].isdigit() or int(pipe_key[1:]) <= 0:
                raise KernelError(f"invalid pipe identity: {pipe_key}")
            if not isinstance(raw, dict):
                raise KernelError(f"pipe state must be a mapping: {pipe_key}")
            capacity = int(raw.get("capacity", 65_536))
            buffer = bytearray.fromhex(str(raw.get("buffer_hex", "")))
            if capacity <= 0 or len(buffer) > capacity:
                raise KernelError(f"invalid pipe capacity or occupancy: {pipe_key}")
            kernel.pipes[pipe_key] = PipeState(pipe_key, buffer, capacity)
        kernel._next_pipe = int(payload.get("next_pipe", len(kernel.pipes) + 1))
        kernel._next_description = int(payload.get("next_description", 1))
        kernel._next_transfer = int(payload.get("next_transfer", 1))
        if kernel._next_pipe <= max((int(pipe_id[1:]) for pipe_id in kernel.pipes), default=0):
            raise KernelError("next_pipe collides with an existing pipe")
        if kernel._next_description <= 0 or kernel._next_transfer <= 0:
            raise KernelError("kernel resource counters must be positive")
        kernel._fd_transfers = {}
        kernel._open_files = {}
        description_payload = {
            str(description_id): dict(raw)
            for description_id, raw in payload.get("open_descriptions", {}).items()
        }
        for description_id, raw in description_payload.items():
            if not description_id.startswith("o") or not description_id[1:].isdigit() or int(description_id[1:]) <= 0:
                raise KernelError(f"invalid open-description identity: {description_id}")
            if not isinstance(raw, dict):
                raise KernelError(f"open-description state must be a mapping: {description_id}")
        if kernel._next_description <= max(
            (int(description_id[1:]) for description_id in description_payload),
            default=0,
        ):
            raise KernelError("next_description collides with an existing open description")
        details = payload.get("process_details")
        if details is None:
            raise KernelError("kernel snapshot is missing process_details")
        if not isinstance(details, dict):
            raise KernelError("kernel process_details must be a mapping")
        for detail_key, raw in details.items():
            if not isinstance(raw, dict):
                raise KernelError("kernel process detail must be a mapping")
            if int(detail_key) != int(raw["pid"]):
                raise KernelError("kernel process key does not match embedded PID")
            process = Process(
                pid=int(raw["pid"]),
                name=str(raw["name"]),
                status=ProcessStatus(raw["status"]),
                capabilities=tuple(
                    Capability(str(item["resource"]), frozenset(str(right) for right in item["rights"]))
                    for item in raw.get("capabilities", ())
                ),
                cwd=str(raw.get("cwd", "/")),
                fds={
                    int(fd): kernel._restore_open_file(
                        str(handle.get("description_id", f"legacy:{raw['pid']}:{fd}")),
                        handle,
                        description_payload,
                    )
                    for fd, handle in raw.get("fds", {}).items()
                },
                fd_flags={
                    int(fd): int(flags)
                    for fd, flags in raw.get("fd_flags", {}).items()
                },
                next_fd=int(raw.get("next_fd", 3)),
                exit_code=None if raw.get("exit_code") is None else int(raw["exit_code"]),
                environment={str(key): str(value) for key, value in raw.get("environment", {}).items()},
                argv=tuple(str(argument) for argument in raw.get("argv", ())),
                parent_pid=None if raw.get("parent_pid") is None else int(raw["parent_pid"]),
                group_id=None if raw.get("group_id") is None else int(raw["group_id"]),
                session_id=None if raw.get("session_id") is None else int(raw["session_id"]),
                reaped=bool(raw.get("reaped", False)),
                subreaper=bool(raw.get("subreaper", False)),
                errno=int(raw.get("errno", 0)),
                signal_dispositions={
                    str(signal): str(disposition)
                    for signal, disposition in raw.get("signal_dispositions", {}).items()
                },
            )
            if process.pid <= 0:
                raise KernelError("process PID must be positive")
            if any(fd < 0 for fd in process.fds) or process.next_fd < max(3, max(process.fds, default=2) + 1):
                raise KernelError(f"invalid descriptor allocation state for process: {process.pid}")
            for signal, disposition in process.signal_dispositions.items():
                if signal not in {item.value for item in Signal} or disposition != "ignore":
                    raise KernelError(f"invalid signal disposition for process: {process.pid}")
                if signal in {Signal.KILL.value, Signal.STOP.value}:
                    raise KernelError(f"non-ignorable signal disposition for process: {process.pid}")
            if any(flags < 0 or flags & ~FD_CLOEXEC for flags in process.fd_flags.values()):
                raise KernelError(f"invalid descriptor flags for process: {process.pid}")
            if any(fd not in process.fds for fd in process.fd_flags):
                raise KernelError(f"descriptor flags reference missing fd for process: {process.pid}")
            if process.pid in kernel.processes:
                raise KernelError(f"duplicate process identity: {process.pid}")
            kernel.processes[process.pid] = process
        for transfer_id, raw_transfer in dict(payload.get("fd_transfers", {})).items():
            transfer_key = str(transfer_id)
            if not transfer_key.startswith("x") or not transfer_key[1:].isdigit() or int(transfer_key[1:]) <= 0:
                raise KernelError(f"invalid FD transfer identity: {transfer_key}")
            if transfer_key in kernel._fd_transfers:
                raise KernelError(f"duplicate FD transfer identity: {transfer_key}")
            sender_pid = int(raw_transfer["sender_pid"])
            destination_pid = int(raw_transfer["destination_pid"])
            if sender_pid not in kernel.processes:
                raise KernelError(f"FD transfer sender does not exist: {sender_pid}")
            if destination_pid not in kernel.processes:
                raise KernelError(f"FD transfer destination does not exist: {destination_pid}")
            description_id = str(raw_transfer["description_id"])
            raw_description = description_payload.get(description_id)
            if raw_description is None:
                raise KernelError(f"FD transfer description does not exist: {description_id}")
            description = kernel._restore_open_file(description_id, raw_description, description_payload)
            kernel._fd_transfers[transfer_key] = FdTransfer(
                transfer_key,
                sender_pid,
                destination_pid,
                description,
            )
        if kernel._next_transfer <= max(
            (int(transfer_id[1:]) for transfer_id in kernel._fd_transfers),
            default=0,
        ):
            raise KernelError("next_transfer collides with an existing FD transfer")
        kernel._gc_open_files()
        kernel._next_pid = int(payload["next_pid"])
        if kernel._next_pid <= 0 or kernel._next_pid <= max(kernel.processes, default=0):
            raise KernelError("next_pid collides with an existing process")
        for process in kernel.processes.values():
            if process.parent_pid is not None:
                if process.parent_pid == process.pid or process.parent_pid not in kernel.processes:
                    raise KernelError(f"invalid parent reference for process: {process.pid}")
            if process.group_id is not None and process.group_id <= 0:
                raise KernelError(f"invalid process group for process: {process.pid}")
            if process.session_id is not None and process.session_id <= 0:
                raise KernelError(f"invalid process session for process: {process.pid}")
        raw_init_pid = payload.get("init_pid")
        kernel.init_pid = (
            None
            if raw_init_pid is None and not kernel.processes
            else int(raw_init_pid) if raw_init_pid is not None else None
        )
        if kernel.processes and kernel.init_pid not in kernel.processes:
            raise KernelError("init_pid does not identify a restored process")
        if kernel.init_pid is not None and kernel.processes[kernel.init_pid].parent_pid is not None:
            raise KernelError("init_pid must identify a root process")
        return kernel

    def _restore_open_file(
        self,
        description_id: str,
        raw_handle: dict[str, Any],
        descriptions: dict[str, dict[str, Any]],
    ) -> OpenFile:
        """Mathematics: reconstruct one canonical description `D[description_id]` and make every descriptor alias it."""

        raw = descriptions.get(description_id)
        if raw is None:
            raise KernelError(f"open description does not exist: {description_id}")
        candidate = OpenFile(
            str(raw["path"]),
            int(raw["offset"]),
            bool(raw["readable"]),
            bool(raw["writable"]),
            None if raw.get("pipe_id") is None else str(raw["pipe_id"]),
            description_id,
            None if raw.get("network_kind") is None else str(raw["network_kind"]),
            None if raw.get("network_handle") is None else int(raw["network_handle"]),
            int(raw.get("status_flags", 0)),
        )
        if candidate.offset < 0:
            raise KernelError(f"open description offset is negative: {description_id}")
        if candidate.pipe_id is not None:
            if candidate.pipe_id not in self.pipes or candidate.path != f"pipe:{candidate.pipe_id}":
                raise KernelError(f"open description references an invalid pipe: {description_id}")
        if candidate.network_kind is not None and candidate.network_handle is None:
            raise KernelError(f"network description has no handle: {description_id}")
        existing = self._open_files.get(description_id)
        if existing is not None:
            if (
                existing.path,
                existing.offset,
                existing.readable,
                existing.writable,
                existing.pipe_id,
                existing.network_kind,
                existing.network_handle,
                existing.status_flags,
            ) != (
                candidate.path,
                candidate.offset,
                candidate.readable,
                candidate.writable,
                candidate.pipe_id,
                candidate.network_kind,
                candidate.network_handle,
                candidate.status_flags,
            ):
                raise KernelError(f"inconsistent open description: {description_id}")
            return existing
        self._open_files[description_id] = candidate
        return candidate


def _log_value(value: Any) -> Any:
    """Mathematics: recursively map runtime values into a JSON domain, using injective `b -> hex(b)` for bytes."""

    if isinstance(value, bytes):
        return {"bytes_hex": value.hex()}
    if isinstance(value, dict):
        return {str(key): _log_value(item) for key, item in value.items()}
    if isinstance(value, FileStat):
        return {
            "inode_id": value.inode_id,
            "kind": value.kind,
            "mode": value.mode,
            "owner": value.owner,
            "size": value.size,
        }
    if isinstance(value, BusMessage):
        return {
            "message_id": value.message_id,
            "source": value.source,
            "destination": value.destination,
            "kind": value.kind,
            "payload": value.payload,
            "logical_time": value.logical_time,
            "reply_to": value.reply_to,
        }
    if isinstance(value, tuple):
        return [_log_value(item) for item in value]
    if isinstance(value, list):
        return [_log_value(item) for item in value]
    return value
