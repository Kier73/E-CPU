"""A native headless MailCPU operating environment with executable virtual files."""

from __future__ import annotations

import shlex
from dataclasses import asdict, dataclass
from typing import Any, Callable, Iterable, Mapping, Sequence

from .assembler import AssemblyError, assemble
from .bytecode import BytecodeExecutable
from .datagram import DatagramError, NetworkDatagram
from .classifier import (
    ClassifierHypervisor,
    HypervisorDecision,
    HypervisorDomain,
    HypervisorArbitrationEvent,
    HypervisorArbitrationLoop,
    HypervisorArbitrationResult,
    HypervisorRevisionArbitrationResult,
    HypervisorRevisionProposal,
    HypervisorRequest,
)
from .environment import CommandResult, VirtualEnvironment
from .evidence import EvidenceTier, with_evidence_tier
from .elf import ElfLoadResult, parse_elf
from .fs import FsError, normalize_path
from .kernel import (
    Errno,
    KernelError,
    O_NONBLOCK,
    POLLERR,
    POLLHUP,
    POLLIN,
    POLLNVAL,
    POLLOUT,
    ProcessStatus,
)
from .memory import VirtualMemoryError
from .model import DEFAULT_MAX_TICKS, Program
from .owned_network import NetworkAddress, NetworkFrame
from .posix_abi import PosixCompatibility, PosixResponse
from .registry import ImageRegistry
from .scheduler import ScheduleEvent, SyscallBlocked, TaskStatus
from .signals import DEFAULT_TERMINATION_EXIT_CODE, Signal, SignalError
from .stream import StreamError
from .trajectory import TrajectoryWriter
from .vm import MailCPUVirtualMachine


# The memory-backed poll record uses aligned four-byte integer fields: (int32 fd, uint32 events, uint32 revents).
_POLLFD_BYTES = 12
_POLLFD_FD_OFFSET = 0
_POLLFD_EVENTS_OFFSET = 4
_POLLFD_REVENTS_OFFSET = 8


@dataclass(frozen=True)
class ProcessReport:
    """Stable user-facing projection of a kernel process and its scheduled machine state."""

    pid: int
    name: str
    status: str
    pc: int
    steps: int
    registers: dict[str, int]
    exit_code: int | None
    errno: int
    environment: dict[str, str]
    argv: tuple[str, ...] = ()
    parent_pid: int | None = None
    group_id: int | None = None
    session_id: int | None = None
    subreaper: bool = False
    cwd: str = "/"

    def to_dict(self) -> dict[str, object]:
        """Mathematics: project report `r` into a JSON-compatible record without changing observable fields."""

        return with_evidence_tier(asdict(self), EvidenceTier.E0)


class HeadlessOS:
    """A booted, non-interactive OS facade whose programs and source files live in the virtual environment."""

    def __init__(
        self,
        environment: VirtualEnvironment | None = None,
        trajectory: TrajectoryWriter | None = None,
        max_resident_pages: int | None = None,
    ) -> None:
        """Mathematics: compose `OS = (E, VM)` where `E` supplies resources and `VM` supplies execution."""

        self.environment = environment or VirtualEnvironment.bootstrap()
        self.vm = MailCPUVirtualMachine(
            self.environment,
            trajectory=trajectory,
            max_resident_pages=max_resident_pages,
        )
        self._pending_exec: dict[int, tuple[Program, str, tuple[str, ...]]] = {}
        self._pending_fork: dict[int, int] = {}
        self.environment.kernel.terminal_signal_handler = self._handle_terminal_signal
        self.vm.host_syscall_handler = self._dispatch_program_syscall
        self.vm.scheduler.wait_predicate = self._scheduler_wait_ready
        self.vm.scheduler.post_step = self._apply_deferred_exec
        self.hypervisor = ClassifierHypervisor(journal=self.environment.kernel.journal)
        self.hypervisor_arbitration = HypervisorArbitrationLoop(self.hypervisor)
        self.posix = PosixCompatibility(self)
        from .service import ServiceSupervisor

        self.services = ServiceSupervisor(self)

    def install_source(self, path: str, source: str, mode: int = 0o755) -> str:
        """Mathematics: write source bytes `B = UTF8(source)` into inode `normalize(path)`, creating parent prefixes."""

        canonical = normalize_path(path)
        self._ensure_parent_directories(canonical)
        payload = source.encode("utf-8")
        try:
            self.environment.kernel.fs.write_file(canonical, payload, offset=0, truncate=True)
        except FsError:
            self.environment.kernel.fs.create_file(canonical, payload, mode=mode)
        return canonical

    def install_binary(self, path: str, program: Program, mode: int = 0o755) -> str:
        """Mathematics: write native executable bytes `B=encode_MCPB(program)` into inode `normalize(path)` with execute mode."""

        canonical = normalize_path(path)
        self._ensure_parent_directories(canonical)
        payload = BytecodeExecutable(program).to_bytes()
        try:
            self.environment.kernel.fs.write_file(canonical, payload, offset=0, truncate=True)
        except FsError:
            self.environment.kernel.fs.create_file(canonical, payload, mode=mode)
        return canonical

    def spawn(
        self,
        program: Program,
        name: str,
        initial_registers: dict[str, int] | None = None,
        environment: dict[str, str] | None = None,
        argv: Sequence[str] = (),
        parent_pid: int | None = None,
        group_id: int | None = None,
        inherit_fds: bool = False,
        max_pages: int | None = None,
    ) -> int:
        """Mathematics: allocate process ABI identity `pid` and insert its program orbit into the scheduler ready set."""

        return self.vm.spawn_program(
            program,
            name,
            initial_registers,
            environment,
            argv=argv,
            parent_pid=self.environment.init_pid if parent_pid is None else parent_pid,
            group_id=group_id,
            inherit_fds=inherit_fds,
            max_pages=max_pages,
        )

    def create_shared_memory(self, name: str, size: int):
        """Mathematics: create OS-visible shared region `S[name]` of exactly `size` zero bytes."""

        return self.vm.create_shared_memory(name, size)

    def attach_shared_memory(self, pid: int, name: str, start: int, writable: bool = True) -> None:
        """Mathematics: attach `S[name]` into process memory map `M_pid` at virtual address `start`."""

        self.vm.attach_shared_memory(pid, name, start, writable)

    def syscall(self, pid: int, syscall_name: str, **args: Any) -> Any:
        """Mathematics: evaluate `δ_os` over kernel, memory, and owned-network syscall partitions."""

        if syscall_name in {"read", "write", "close"}:
            process = self.environment.kernel._process(pid)
            descriptor = process.fds.get(int(args.get("fd", -1)))
            if descriptor is not None and descriptor.network_kind is not None:
                return self._network_fd_syscall(process, syscall_name, args, descriptor)
        if syscall_name == "dup2":
            process = self.environment.kernel._process(pid)
            return self._dup2_syscall(process, args)
        if syscall_name == "exec":
            raw_argv = args.get("argv")
            self.exec_file(
                pid,
                str(args["path"]),
                self._argument_vector(raw_argv, None),
                None if args.get("name") is None else str(args["name"]),
            )
            return 0
        if syscall_name == "spawn_file":
            process = self.environment.kernel._process(pid)
            if process.status is ProcessStatus.EXITED:
                raise KernelError("exited process cannot spawn")
            raw_name = args.get("name")
            child_name = None if raw_name is None else str(raw_name)
            return self.launch_file(
                str(args["path"]),
                name=child_name,
                argv=self._argument_vector(args.get("argv"), None),
                parent_pid=pid,
                inherit_fds=bool(args.get("inherit_fds", False)),
                max_pages=None if args.get("max_pages") is None else int(args["max_pages"]),
                loader_pid=pid,
            )
        if syscall_name == "waitpid":
            # Projection `σ_kernel := π(σ_scheduler)` runs before selection so
            # same-orbit `HALTED` children belong to the kernel's exited set.
            self._sync_kernel_processes()
            result = self.environment.kernel.syscall(pid, syscall_name, **args)
            if result is not None:
                child_pid = int(result["pid"])
                self.vm.reap_process(child_pid)
                canceled_transfers = self.environment.kernel.reap_process(child_pid)
                self.environment.release_fd_transfers(canceled_transfers)
                self.environment.release_network_handles(child_pid)
            return result
        if syscall_name not in {
            "mmap",
            "munmap",
            "mprotect",
            "mem_read",
            "mem_write",
            "mem_info",
            "mem_reclaim",
            "argv_into",
            "environ_into",
            "getcwd_into",
            "pty_open_into",
            "read_into",
            "write_from",
            "poll",
            "poll_fd",
            "poll_into",
            "pipe_into",
            "shm_create",
            "shm_attach",
            "shm_detach",
            "net_namespace_create",
            "net_interface_create",
            "net_connect",
            "net_send",
            "net_route_send",
            "net_receive",
            "net_info",
            "net_send_from",
            "net_route_send_from",
            "net_receive_into",
            "net_dgram_bind",
            "net_dgram_bind_fd",
            "net_dgram_send",
            "net_dgram_send_fd",
            "net_dgram_receive",
            "net_dgram_info",
            "net_dgram_close",
            "net_dgram_send_from",
            "net_dgram_receive_into",
            "net_stream_listen",
            "net_stream_listen_fd",
            "net_stream_connect",
            "net_stream_connect_fd",
            "net_stream_accept",
            "net_stream_accept_fd",
            "net_stream_send",
            "net_stream_receive",
            "net_stream_close",
            "net_stream_info",
            "net_stream_send_from",
            "net_stream_receive_into",
        }:
            return self.environment.kernel.syscall(pid, syscall_name, **args)
        process = self.environment.kernel._process(pid)
        if process.status is ProcessStatus.EXITED:
            raise KernelError("exited process cannot issue syscalls")
        logged_args = {key: self._memory_log_value(value) for key, value in args.items()}
        self.environment.kernel.journal.append(
            "syscall.begin",
            {"pid": pid, "name": syscall_name, "args": logged_args},
        )
        try:
            if syscall_name == "poll":
                result = self._poll_syscall(process, args)
            elif syscall_name == "poll_fd":
                result = self._poll_fd_syscall(process, args)
            elif syscall_name == "poll_into":
                result = self._poll_into_syscall(process, args)
            elif syscall_name.startswith("net_"):
                result = self._network_syscall(process, syscall_name, args)
            else:
                result = self._memory_syscall(process, syscall_name, args)
        except VirtualMemoryError:
            raise
        self.environment.kernel.journal.append(
            "syscall.end",
            {"pid": pid, "name": syscall_name, "result": self._memory_log_value(result)},
        )
        return result

    def posix_syscall(self, pid: int, number: int, **args: Any) -> PosixResponse:
        """Mathematics: expose the numbered ABI projection `Π(pid,number,args)` over this booted OS."""

        return self.posix.invoke(pid, number, **args)

    def syscall_server(self):
        """Mathematics: bind bus endpoint `kernel` to the OS transition function `δ_os(pid,request)` for typed remote calls."""

        from .protocol import SyscallServer

        return SyscallServer(self.environment.kernel.bus, self)

    def _dispatch_program_syscall(self, pid: int, name: str, arguments: dict[str, Any]) -> Any:
        """Mathematics: return `G` on success, preserve `SyscallBlocked`, and map recoverable failure `e` to `-errno(e)` while storing `errno(pid):=errno(e)`."""

        try:
            result = self._dispatch_program_syscall_unchecked(pid, name, arguments)
        except SyscallBlocked:
            raise
        except (KernelError, FsError, VirtualMemoryError, DatagramError, StreamError, SignalError, KeyError, ValueError, OverflowError) as exc:
            error_number = self._errno_for_exception(exc)
            process = self.environment.kernel._process(pid)
            process.errno = int(error_number)
            self.environment.kernel.journal.append(
                "syscall.error",
                {
                    "pid": pid,
                    "name": name,
                    "errno": int(error_number),
                    "error": str(exc),
                },
            )
            return -int(error_number)
        else:
            return result

    def _dispatch_program_syscall_unchecked(self, pid: int, name: str, arguments: dict[str, Any]) -> Any:
        """Mathematics: route program trap `G(pid,name,A)` through the headless memory ABI when `name∈M`, else through kernel authority, without converting failures."""

        if name == "exec":
            return self._queue_deferred_exec(pid, arguments)
        if name == "fork":
            return self._queue_deferred_fork(pid)
        task = self.vm.scheduler.tasks.get(pid)
        wake_request = None if task is None else task.wake_request
        resumed_wait = wake_request is not None
        wait_request = self._program_wait_request(pid, name, arguments)
        readiness_request = wake_request if resumed_wait else wait_request
        if wait_request is not None and readiness_request is not None and not self._scheduler_wait_ready(pid, readiness_request):
            blocked_request = dict(wait_request)
            if wake_request is not None and wake_request.get("deadline") is not None:
                blocked_request["deadline"] = wake_request["deadline"]
            self.environment.kernel.journal.append(
                "syscall.block",
                {"pid": pid, "name": name, "wait": self._memory_log_value(blocked_request)},
            )
            raise SyscallBlocked(blocked_request)
        effective_arguments = dict(arguments)
        if resumed_wait and name in {"poll", "poll_fd", "poll_into"} and int(effective_arguments.get("timeout", 0)) != 0:
            # The scheduler has already established readiness or deadline expiry; the native
            # immediate poll projection can now complete the same instruction.
            effective_arguments["timeout"] = 0

        if name in {
            "mmap",
            "munmap",
            "mprotect",
            "mem_read",
            "mem_write",
            "mem_info",
            "mem_reclaim",
            "argv_into",
            "environ_into",
            "getcwd_into",
            "pty_open_into",
            "read_into",
            "write_from",
            "poll",
            "poll_fd",
            "poll_into",
            "pipe_into",
            "shm_create",
            "shm_attach",
            "shm_detach",
            "net_namespace_create",
            "net_interface_create",
            "net_connect",
            "net_send",
            "net_route_send",
            "net_receive",
            "net_info",
            "net_send_from",
            "net_route_send_from",
            "net_receive_into",
            "net_dgram_bind",
            "net_dgram_send",
            "net_dgram_receive",
            "net_dgram_info",
            "net_dgram_close",
            "net_dgram_send_from",
            "net_dgram_receive_into",
            "net_stream_listen",
            "net_stream_connect",
            "net_stream_accept",
            "net_stream_send",
            "net_stream_receive",
            "net_stream_close",
            "net_stream_info",
            "net_stream_send_from",
            "net_stream_receive_into",
            "net_dgram_bind_fd",
            "net_dgram_send_fd",
            "net_stream_listen_fd",
            "net_stream_connect_fd",
            "net_stream_accept_fd",
            "read",
            "write",
            "close",
            "waitpid",
            "spawn_file",
        }:
            if name == "waitpid":
                result = self.syscall(pid, name, **effective_arguments)
                return 0 if result is None else int(result["pid"])
            return self.syscall(pid, name, **effective_arguments)
        return self.environment.kernel.syscall(pid, name, **effective_arguments)

    def _queue_deferred_exec(self, pid: int, arguments: Mapping[str, Any]) -> int:
        """Mathematics: construct pending image `X_pid=(assemble(read_exec(path)),name,argv)` without mutating the running image until its trap transition commits."""

        canonical = normalize_path(str(arguments["path"]))
        program = self.read_executable_program(canonical, loader_pid=pid)
        process = self.environment.kernel._process(pid)
        process_name = str(arguments.get("name", canonical.rsplit("/", 1)[-1]))
        if not process_name:
            raise KernelError("exec identity is invalid")
        process_argv = self._argument_vector(arguments.get("argv"), (canonical,))
        self.environment.kernel._validate_argv(process_argv)
        self._pending_exec[pid] = (program, process_name, process_argv)
        return 0

    @staticmethod
    def _argument_vector(raw: Any, default: tuple[str, ...] | None) -> tuple[str, ...] | None:
        """Mathematics: decode `A(raw)=default` for `raw=⊥`, else `A(raw)=tuple(raw)` for finite string sequences."""

        if raw is None:
            return default
        if isinstance(raw, str):
            return (raw,)
        if not isinstance(raw, (list, tuple)):
            raise KernelError("argv must be a sequence of strings")
        return tuple(raw)

    def _apply_deferred_exec(self, pid: int) -> None:
        """Mathematics: commit `X_pid` atomically as `T_pid:=exec(program,name)` and `P_pid:=exec(name,argv)` after the old trap step."""

        request = self._pending_exec.pop(pid, None)
        if request is None:
            self._apply_deferred_fork(pid)
            return
        program, process_name, argv = request
        self.vm.exec_program(pid, program, process_name)
        self.environment.kernel.exec_process(pid, process_name, argv)
        self.environment.release_network_handles(pid)

    def _queue_deferred_fork(self, pid: int) -> int:
        """Mathematics: reserve child identity `c=next_pid` and admit COW mapping cardinality before returning parent result `c`."""

        if pid in self._pending_fork:
            raise KernelError("fork already pending for process")
        parent_memory = self.vm.memories.get(pid)
        if parent_memory is None:
            raise KernelError(f"memory image missing for pid: {pid}")
        child_pid = self.environment.kernel._next_pid
        self.vm._admit_resident_pages(len(parent_memory.mapped_pages()))
        self._pending_fork[pid] = child_pid
        return child_pid

    def _apply_deferred_fork(self, pid: int) -> None:
        """Mathematics: commit child `C=(clone(M_p),P_p,pc_p+1,R_p[d↦0],F_p,E_p,C_p)` after parent trap completion."""

        child_pid = self._pending_fork.pop(pid, None)
        if child_pid is None:
            return
        task = self.vm.scheduler.tasks.get(pid)
        if task is None or task.state.pc <= 0:
            raise KernelError("fork parent has no post-trap instruction state")
        previous_instruction = task.program.instructions[task.state.pc - 1]
        if previous_instruction.op.value != "SYSCALL":
            raise KernelError("fork commit did not follow a syscall trap")
        destination = str(previous_instruction.args[0])
        child_registers = task.backend.snapshot_registers()
        child_registers[destination] = 0
        actual_pid = self.vm.fork_program(
            pid,
            child_pid,
            child_registers,
            task.state.pc,
            task.state.steps,
        )
        if actual_pid != child_pid:
            raise KernelError(f"fork child identity mismatch: {actual_pid} != {child_pid}")

    @staticmethod
    def _errno_for_exception(error: BaseException) -> Errno:
        """Mathematics: apply deterministic classification `κ(e)` from typed failure evidence to the finite errno alphabet."""

        message = str(error).lower()
        if "unknown pid" in message or "no such process" in message:
            return Errno.ESRCH
        if isinstance(error, VirtualMemoryError):
            if "quota" in message or "resident" in message or "budget" in message:
                return Errno.ENOMEM
            return Errno.EFAULT
        if "bad file descriptor" in message or "descriptor" in message and "unknown" not in message:
            return Errno.EBADF
        if "permission denied" in message or "capability" in message or "not executable" in message:
            return Errno.EACCES
        if "not found" in message or "unknown path" in message or "no such" in message:
            return Errno.ENOENT
        if "not a directory" in message:
            return Errno.ENOTDIR
        if "is a directory" in message:
            return Errno.EISDIR
        if "would block" in message or "pipe full" in message or "window is full" in message or "queue" in message and "full" in message:
            return Errno.EAGAIN
        if "broken pipe" in message:
            return Errno.EPIPE
        if "unknown syscall" in message:
            return Errno.ENOSYS
        if "no children" in message or "child" in message and "wait" in message:
            return Errno.ECHILD
        if "already" in message or "exists" in message:
            return Errno.EEXIST
        if "closed stream" in message or "not connected" in message:
            return Errno.ENOTCONN
        if "refused" in message or "no stream listener" in message:
            return Errno.ECONNREFUSED
        if "buffer too small" in message or "range" in message:
            return Errno.ERANGE
        if "quota" in message or "space" in message and "available" not in message:
            return Errno.ENOSPC
        if isinstance(error, (KeyError, ValueError, SignalError)):
            return Errno.EINVAL
        return Errno.EIO

    def _network_syscall(self, process: Any, name: str, args: Mapping[str, Any]) -> Any:
        """Mathematics: apply `δ_net(P,name,A)` while preserving capability checks and byte-transfer atomicity."""

        pid = process.pid
        if name == "net_namespace_create":
            self.environment.network_create_namespace(pid, str(args["name"]))
            return 0
        if name == "net_interface_create":
            self.environment.network_create_interface(
                pid,
                str(args["namespace"]),
                str(args["interface"]),
                int(args.get("mtu", 1500)),
            )
            return 0
        if name == "net_connect":
            self.environment.network_connect(
                pid,
                str(args["link"]),
                NetworkAddress(str(args["left_namespace"]), str(args["left_interface"])),
                NetworkAddress(str(args["right_namespace"]), str(args["right_interface"])),
            )
            return 0
        if name == "net_dgram_bind":
            return self.environment.network_datagram_bind(
                pid,
                str(args["namespace"]),
                str(args["interface"]),
                int(args["port"]),
                None if args.get("queue_limit") is None else int(args["queue_limit"]),
            )
        if name == "net_dgram_bind_fd":
            return self.environment.network_datagram_bind_fd(
                pid,
                str(args["namespace"]),
                str(args["interface"]),
                int(args["port"]),
                None if args.get("queue_limit") is None else int(args["queue_limit"]),
            )
        if name in {"net_dgram_send", "net_dgram_send_from"}:
            if name == "net_dgram_send":
                payload = bytes(args.get("payload", b""))
            else:
                address = int(args["address"])
                size = int(args["size"])
                memory = self._process_memory(process)
                self._authorize_memory(process, address, "read")
                memory.validate_access(address, size, "read")
                payload = memory.read(address, size)
            destination = NetworkAddress(
                str(args["destination_namespace"]),
                str(args["destination_interface"]),
            )
            return self.environment.network_datagram_send(
                pid,
                int(args["socket_id"]),
                destination,
                int(args["destination_port"]),
                payload,
                int(args.get("logical_time", self.vm.scheduler.tick)),
                bool(args.get("routed", True)),
            )
        if name == "net_dgram_send_fd":
            descriptor = process.fds.get(int(args["fd"]))
            if descriptor is None:
                raise KernelError(f"bad file descriptor: {args['fd']}")
            payload = bytes(args.get("payload", b""))
            destination = NetworkAddress(str(args["destination_namespace"]), str(args["destination_interface"]))
            self.environment.network_datagram_fd_send(
                pid,
                descriptor,
                destination,
                int(args["destination_port"]),
                payload,
                int(args.get("logical_time", self.vm.scheduler.tick)),
                bool(args.get("routed", True)),
            )
            return len(payload)
        if name in {"net_dgram_receive", "net_dgram_receive_into"}:
            socket_id = int(args["socket_id"])
            if name == "net_dgram_receive":
                return self.environment.network_datagram_receive(
                    pid,
                    socket_id,
                    None if args.get("max_size") is None else int(args["max_size"]),
                )
            address = int(args["address"])
            size = int(args["size"])
            memory = self._process_memory(process)
            self._authorize_memory(process, address, "write")
            memory.validate_access(address, size, "write")
            datagram = self.environment.network_datagram_peek(pid, socket_id, size)
            if datagram is None:
                return 0
            before = {mapping.page_number for mapping in memory.mapped_pages()}
            written = memory.write(address, datagram.payload)
            received = self.environment.network_datagram_receive(pid, socket_id, size)
            if received is None or received.frame_id != datagram.frame_id:
                raise DatagramError("datagram changed during memory transfer")
            self._journal_materialized_faults(pid, before, memory)
            self.environment.kernel.journal.append(
                "network.datagram.byte_transfer",
                {"pid": pid, "socket_id": socket_id, "frame_id": datagram.frame_id, "size": written},
            )
            return written
        if name == "net_dgram_info":
            self.environment.kernel._authorize(process, "/net", "read")
            return {"sockets": self.environment.datagrams.sockets()}
        if name == "net_dgram_close":
            self.environment.network_datagram_close(pid, int(args["socket_id"]))
            return 0
        if name == "net_stream_listen":
            return self.environment.network_stream_listen(
                pid,
                str(args["namespace"]),
                str(args["interface"]),
                int(args["port"]),
                None if args.get("backlog") is None else int(args["backlog"]),
            )
        if name == "net_stream_listen_fd":
            return self.environment.network_stream_listen_fd(
                pid,
                str(args["namespace"]),
                str(args["interface"]),
                int(args["port"]),
                None if args.get("backlog") is None else int(args["backlog"]),
            )
        if name == "net_stream_connect":
            return self.environment.network_stream_connect(
                pid,
                NetworkAddress(str(args["source_namespace"]), str(args["source_interface"])),
                int(args.get("source_port", 0)),
                NetworkAddress(str(args["destination_namespace"]), str(args["destination_interface"])),
                int(args["destination_port"]),
            )
        if name == "net_stream_connect_fd":
            return self.environment.network_stream_connect_fd(
                pid,
                NetworkAddress(str(args["source_namespace"]), str(args["source_interface"])),
                int(args.get("source_port", 0)),
                NetworkAddress(str(args["destination_namespace"]), str(args["destination_interface"])),
                int(args["destination_port"]),
            )
        if name == "net_stream_accept":
            accepted = self.environment.network_stream_accept(pid, int(args["listener"]))
            return 0 if accepted is None else accepted
        if name == "net_stream_accept_fd":
            descriptor = process.fds.get(int(args["fd"]))
            if descriptor is None:
                raise KernelError(f"bad file descriptor: {args['fd']}")
            accepted_fd = self.environment.network_stream_accept_fd(pid, descriptor)
            return 0 if accepted_fd is None else accepted_fd
        if name in {"net_stream_send", "net_stream_send_from"}:
            if name == "net_stream_send":
                payload = bytes(args.get("payload", b""))
            else:
                address = int(args["address"])
                size = int(args["size"])
                memory = self._process_memory(process)
                self._authorize_memory(process, address, "read")
                memory.validate_access(address, size, "read")
                payload = memory.read(address, size)
            return self.environment.network_stream_send(
                pid,
                int(args["handle"]),
                payload,
                int(args.get("logical_time", self.vm.scheduler.tick)),
            )
        if name in {"net_stream_receive", "net_stream_receive_into"}:
            handle = int(args["handle"])
            if name == "net_stream_receive":
                return self.environment.network_stream_receive(
                    pid,
                    handle,
                    None if args.get("max_size") is None else int(args["max_size"]),
                )
            address = int(args["address"])
            size = int(args["size"])
            memory = self._process_memory(process)
            self._authorize_memory(process, address, "write")
            memory.validate_access(address, size, "write")
            data = self.environment.network_stream_peek(pid, handle, size)
            if data is None or data == b"":
                return 0
            before = {mapping.page_number for mapping in memory.mapped_pages()}
            written = memory.write(address, data)
            received = self.environment.network_stream_receive(pid, handle, size)
            if received != data:
                raise StreamError("stream changed during memory transfer")
            self._journal_materialized_faults(pid, before, memory)
            self.environment.kernel.journal.append(
                "network.stream.byte_transfer",
                {"pid": pid, "handle": handle, "size": written},
            )
            return written
        if name == "net_stream_close":
            self.environment.network_stream_close(
                pid,
                int(args["handle"]),
                int(args.get("logical_time", self.vm.scheduler.tick)),
            )
            return 0
        if name == "net_stream_info":
            self.environment.kernel._authorize(process, "/net", "read")
            return {
                "listeners": self.environment.streams.listeners(),
                "connections": self.environment.streams.connections(),
            }
        if name in {"net_send", "net_route_send", "net_send_from", "net_route_send_from"}:
            source = NetworkAddress(str(args["source_namespace"]), str(args["source_interface"]))
            destination = NetworkAddress(str(args["destination_namespace"]), str(args["destination_interface"]))
            routed = name in {"net_route_send", "net_route_send_from"}
            if name in {"net_send", "net_route_send"}:
                payload = bytes(args.get("payload", b""))
            else:
                address = int(args["address"])
                size = int(args["size"])
                memory = self._process_memory(process)
                self._authorize_memory(process, address, "read")
                memory.validate_access(address, size, "read")
                payload = memory.read(address, size)
            send = self.environment.network_route_send if routed else self.environment.network_send
            return send(
                pid,
                source,
                destination,
                payload,
                int(args.get("logical_time", self.vm.scheduler.tick)),
            )
        if name in {"net_receive", "net_receive_into"}:
            destination = NetworkAddress(str(args["destination_namespace"]), str(args["destination_interface"]))
            if name == "net_receive":
                return self.environment.network_receive(
                    pid,
                    destination,
                    None if args.get("max_size") is None else int(args["max_size"]),
                )
            address = int(args["address"])
            size = int(args["size"])
            memory = self._process_memory(process)
            self._authorize_memory(process, address, "write")
            memory.validate_access(address, size, "write")
            frame = self.environment.owned_network.peek(destination, size)
            if frame is None:
                return 0
            before = {mapping.page_number for mapping in memory.mapped_pages()}
            written = memory.write(address, frame.payload)
            received = self.environment.network_receive(pid, destination, size)
            if received is None or received.frame_id != frame.frame_id:
                raise KernelError("network receive queue changed during byte transfer")
            self._journal_materialized_faults(pid, before, memory)
            self.environment.kernel.journal.append(
                "network.byte_transfer",
                {"pid": pid, "direction": "network_to_memory", "frame_id": frame.frame_id, "size": written},
            )
            return written
        if name == "net_info":
            self.environment.kernel._authorize(process, "/net", "read")
            return {
                "namespaces": self.environment.owned_network.namespaces(),
                "interfaces": self.environment.owned_network.interfaces(),
                "links": self.environment.owned_network.links(),
            }
        raise KernelError(f"unknown network syscall: {name}")

    def _network_fd_syscall(self, process: Any, name: str, args: Mapping[str, Any], descriptor: Any) -> Any:
        """Mathematics: map descriptor transition `δ_fd` onto the descriptor's native network kind and shared handle."""

        pid = process.pid
        if name == "read":
            return self.environment.network_fd_receive(pid, descriptor, int(args.get("size", -1)))
        if name == "write":
            return self.environment.network_fd_send(
                pid,
                descriptor,
                bytes(args["data"]),
                int(args.get("logical_time", self.vm.scheduler.tick)),
            )
        if name == "close":
            description_id = descriptor.description_id
            is_last = self._description_alias_count(description_id) == 1
            if is_last:
                self.environment.network_fd_close(
                    pid,
                    descriptor,
                    int(args.get("logical_time", self.vm.scheduler.tick)),
                )
            return self.environment.kernel.syscall(pid, "close", fd=int(args["fd"]))
        raise KernelError(f"unsupported network descriptor operation: {name}")

    def _dup2_syscall(self, process: Any, args: Mapping[str, Any]) -> int:
        """Mathematics: realize `dup2(a,b)` while applying native close iff `b` is the last alias of a different network description."""

        source_fd = int(args["fd"])
        target_fd = int(args["new_fd"])
        source = process.fds.get(source_fd)
        target = process.fds.get(target_fd)
        if source is not None and target is not None and source.description_id != target.description_id:
            alias_count = self._description_alias_count(target.description_id)
            if target.network_kind is not None and alias_count == 1:
                self.environment.network_fd_close(
                    process.pid,
                    target,
                    int(args.get("logical_time", self.vm.scheduler.tick)),
                )
        return self.environment.kernel.syscall(process.pid, "dup2", fd=source_fd, new_fd=target_fd)

    def _description_alias_count(self, description_id: str) -> int:
        """Mathematics: count all live and in-flight aliases `A(d)=|{fd:fds(fd)=d}|+|{t:T[t].D=d}|`."""

        process_aliases = sum(
            1
            for candidate_process in self.environment.kernel.processes.values()
            for candidate in candidate_process.fds.values()
            if candidate.description_id == description_id
        )
        transfer_aliases = sum(
            1
            for description in self.environment.kernel.pending_fd_handles()
            if description.description_id == description_id
        )
        return process_aliases + transfer_aliases

    def _program_wait_request(
        self,
        pid: int,
        name: str,
        args: Mapping[str, Any],
    ) -> dict[str, Any] | None:
        """Mathematics: derive a wait predicate `W(name,args)` only after non-mutating validation of compound memory destinations."""

        process = self.environment.kernel._process(pid)
        if name == "read_into":
            self._preflight_memory_destination(process, args)
            descriptor = process.fds.get(int(args["fd"]))
            if descriptor is None or not descriptor.readable:
                return None
            if descriptor.status_flags & O_NONBLOCK:
                return None
            if descriptor.network_kind == "stream_listener":
                return None
            if (
                descriptor.network_kind is None
                and descriptor.pipe_id is None
                and self.environment.kernel.device_name_for_path(descriptor.path) is None
            ):
                return None
            return {"kind": "fd", "fd": int(args["fd"]), "events": POLLIN}
        if name == "write_from":
            self._preflight_memory_source(process, args)
            descriptor = process.fds.get(int(args["fd"]))
            if descriptor is None or not descriptor.writable:
                return None
            if descriptor.status_flags & O_NONBLOCK:
                return None
            if descriptor.network_kind == "stream_connection" or descriptor.pipe_id is not None:
                return {"kind": "fd", "fd": int(args["fd"]), "events": POLLOUT}
            return None
        if name == "write":
            descriptor = process.fds.get(int(args["fd"]))
            if descriptor is None or not descriptor.writable:
                return None
            if descriptor.status_flags & O_NONBLOCK:
                return None
            if descriptor.network_kind == "stream_connection" or descriptor.pipe_id is not None:
                return {"kind": "fd", "fd": int(args["fd"]), "events": POLLOUT}
            return None
        if name == "net_dgram_receive_into":
            self._preflight_memory_destination(process, args)
            return {"kind": "datagram", "socket_id": int(args["socket_id"])}
        if name == "net_stream_receive_into":
            self._preflight_memory_destination(process, args)
            return {"kind": "stream", "handle": int(args["handle"])}
        if name == "net_stream_send_from":
            self._preflight_memory_source(process, args)
            return {"kind": "stream_write", "handle": int(args["handle"])}
        if name == "net_stream_send":
            return {"kind": "stream_write", "handle": int(args["handle"])}
        if name == "net_stream_accept_fd":
            descriptor = process.fds.get(int(args["fd"]))
            if descriptor is None or descriptor.network_kind != "stream_listener":
                return None
            if descriptor.status_flags & O_NONBLOCK:
                return None
            return {"kind": "fd", "fd": int(args["fd"]), "events": POLLIN}
        if name == "net_stream_accept":
            return {"kind": "listener", "listener": int(args["listener"])}
        if name == "receive_fd":
            raw_source = args.get("source_pid")
            return {
                "kind": "rights",
                "source_pid": None if raw_source is None else int(raw_source),
            }
        if name in {"poll", "poll_fd"}:
            timeout = int(args.get("timeout", 0))
            if timeout == 0:
                return None
            if timeout < -1:
                raise KernelError("poll timeout must be -1, 0, or a positive virtual-tick count")
            deadline = None if timeout == -1 else self.vm.scheduler.tick + timeout
            if name == "poll_fd":
                return {
                    "kind": "fd",
                    "fd": int(args["fd"]),
                    "events": int(args.get("events", 0)),
                    "deadline": deadline,
                }
            raw_fds = args.get("fds", ())
            if not isinstance(raw_fds, (list, tuple)):
                raise KernelError("poll fds must be a sequence")
            entries: list[dict[str, int]] = []
            for raw_entry in raw_fds:
                if not isinstance(raw_entry, Mapping):
                    raise KernelError("each poll entry must be a mapping")
                entries.append({"fd": int(raw_entry["fd"]), "events": int(raw_entry.get("events", 0))})
            return {"kind": "poll", "fds": entries, "deadline": deadline}
        if name == "poll_into":
            address = int(args["address"])
            count = int(args.get("count", 0))
            timeout = int(args.get("timeout", 0))
            if timeout == 0:
                return None
            if timeout < -1:
                raise KernelError("poll_into timeout must be -1, 0, or a positive virtual-tick count")
            memory = self._process_memory(process)
            before = {mapping.page_number for mapping in memory.mapped_pages()}
            entries = self._read_poll_entries(process, address, count)
            self._journal_materialized_faults(pid, before, memory)
            deadline = None if timeout == -1 else self.vm.scheduler.tick + timeout
            return {
                "kind": "poll_memory",
                "address": address,
                "count": count,
                "entries": entries,
                "deadline": deadline,
            }
        return None

    def _preflight_memory_destination(self, process: Any, args: Mapping[str, Any]) -> None:
        """Mathematics: validate destination interval `I=[a,a+n)` before any wait or destructive receive transition."""

        address = int(args["address"])
        size = int(args["size"])
        memory = self._process_memory(process)
        self._authorize_memory(process, address, "write")
        memory.validate_access(address, size, "write")

    def _preflight_memory_source(self, process: Any, args: Mapping[str, Any]) -> None:
        """Mathematics: validate source interval `I=[a,a+n)` before a backpressure wait can suspend the writer."""

        address = int(args["address"])
        size = int(args["size"])
        memory = self._process_memory(process)
        self._authorize_memory(process, address, "read")
        memory.validate_access(address, size, "read")

    def _scheduler_wait_ready(self, pid: int, request: dict[str, Any]) -> bool:
        """Mathematics: evaluate wake predicate `P(W)` as descriptor readiness or terminal error."""

        kind = str(request.get("kind", ""))
        try:
            if kind == "fd":
                fd = int(request["fd"])
                revents = self._descriptor_revents(
                    self.environment.kernel._process(pid),
                    fd,
                    int(request.get("events", 0)),
                )
                if revents & (int(request.get("events", 0)) | POLLERR | POLLHUP | POLLNVAL):
                    return True
                deadline = request.get("deadline")
                return deadline is not None and self.vm.scheduler.tick >= int(deadline)
            if kind == "poll":
                process = self.environment.kernel._process(pid)
                for raw_entry in request.get("fds", ()):
                    entry = dict(raw_entry)
                    events = int(entry.get("events", 0))
                    revents = self._descriptor_revents(process, int(entry["fd"]), events)
                    if revents & (events | POLLERR | POLLHUP | POLLNVAL):
                        return True
                deadline = request.get("deadline")
                return deadline is not None and self.vm.scheduler.tick >= int(deadline)
            if kind == "poll_memory":
                process = self.environment.kernel._process(pid)
                for raw_entry in request.get("entries", ()):
                    entry = dict(raw_entry)
                    events = int(entry.get("events", 0))
                    revents = self._descriptor_revents(process, int(entry["fd"]), events)
                    if revents & (events | POLLERR | POLLHUP | POLLNVAL):
                        return True
                deadline = request.get("deadline")
                return deadline is not None and self.vm.scheduler.tick >= int(deadline)
            if kind == "datagram":
                return self.environment.network_datagram_ready(pid, int(request["socket_id"]))
            if kind == "stream":
                return self.environment.network_stream_ready(pid, int(request["handle"]))
            if kind == "stream_write":
                return self.environment.network_stream_writable(pid, int(request["handle"]))
            if kind == "listener":
                return self.environment.network_stream_listener_ready(pid, int(request["listener"]))
            if kind == "rights":
                raw_source = request.get("source_pid")
                return self.environment.kernel.fd_transfer_pending(
                    pid,
                    None if raw_source is None else int(raw_source),
                )
        except (KernelError, DatagramError, StreamError, KeyError, ValueError):
            # Wake an invalid or destroyed target to return its error code.
            return True
        return False

    def _descriptor_revents(self, process: Any, fd: int, events: int) -> int:
        """Mathematics: compute `revents(fd,E)` for one descriptor, with `POLLNVAL` as the totalized invalid-FD result."""

        if events < 0:
            raise KernelError("poll events must be non-negative")
        if fd < 0:
            return 0
        if fd not in process.fds:
            return POLLNVAL
        descriptor = process.fds[fd]
        return (
            self.environment.network_fd_readiness(process.pid, descriptor, events)
            if descriptor.network_kind is not None
            else self.environment.kernel.descriptor_readiness(process.pid, fd, events)
        )

    def _poll_syscall(self, process: Any, args: Mapping[str, Any]) -> dict[str, Any]:
        """Mathematics: evaluate the readiness vector `R_i = poll(F_i,E_i)` atomically at one virtual instant."""

        raw_fds = args.get("fds", ())
        if not isinstance(raw_fds, (list, tuple)):
            raise KernelError("poll fds must be a sequence")
        timeout = int(args.get("timeout", 0))
        if timeout != 0:
            raise KernelError("blocking poll timeouts require a scheduler wait primitive; use timeout=0")
        results: list[dict[str, int]] = []
        ready_count = 0
        for raw in raw_fds:
            if not isinstance(raw, Mapping):
                raise KernelError("each poll entry must be a mapping")
            fd = int(raw["fd"])
            events = int(raw.get("events", 0))
            if events < 0:
                raise KernelError("poll events must be non-negative")
            revents = self._descriptor_revents(process, fd, events)
            if revents:
                ready_count += 1
            results.append({"fd": fd, "events": events, "revents": revents})
        return {"ready": ready_count, "fds": results}

    def _poll_fd_syscall(self, process: Any, args: Mapping[str, Any]) -> int:
        """Mathematics: project scalar readiness `poll_fd(fd,E)=revents(fd,E)` for integer-register program traps."""

        result = self._poll_syscall(
            process,
            {
                "fds": [{"fd": int(args["fd"]), "events": int(args.get("events", 0))}],
                "timeout": int(args.get("timeout", 0)),
            },
        )
        return int(result["fds"][0]["revents"])

    def _preflight_poll_array(self, process: Any, address: int, count: int) -> Any:
        """Mathematics: admit the complete poll interval `I=[a,a+12n)` for both descriptor inputs and revents outputs before mutation."""

        if address < 0 or count < 0:
            raise KernelError("poll_into address and count must be non-negative")
        memory = self._process_memory(process)
        size = _POLLFD_BYTES * count
        self._authorize_memory(process, address, "read")
        self._authorize_memory(process, address, "write")
        memory.validate_access(address, size, "read")
        memory.validate_access(address, size, "write")
        return memory

    def _read_poll_entries(
        self,
        process: Any,
        address: int,
        count: int,
    ) -> list[dict[str, int]]:
        """Mathematics: decode `E_i=(fd_i,events_i)` from little-endian records `B[a+12i:a+12i+8]` without touching revents fields."""

        memory = self._preflight_poll_array(process, address, count)
        entries: list[dict[str, int]] = []
        for index in range(count):
            record = memory.read(address + index * _POLLFD_BYTES, _POLLFD_BYTES)
            fd = int.from_bytes(
                record[_POLLFD_FD_OFFSET : _POLLFD_EVENTS_OFFSET],
                "little",
                signed=True,
            )
            events = int.from_bytes(
                record[_POLLFD_EVENTS_OFFSET : _POLLFD_REVENTS_OFFSET],
                "little",
                signed=False,
            )
            entries.append({"fd": fd, "events": events})
        return entries

    def _poll_into_syscall(self, process: Any, args: Mapping[str, Any]) -> int:
        """Mathematics: atomically compute `r_i=R(fd_i,E_i)` and write `revents_i=r_i` into each 12-byte user record, returning `|{i:r_i≠0}|`."""

        address = int(args["address"])
        count = int(args.get("count", 0))
        timeout = int(args.get("timeout", 0))
        if timeout != 0:
            raise KernelError("blocking poll_into timeouts require a scheduler wait primitive; use timeout=0")
        memory = self._preflight_poll_array(process, address, count)
        before = {mapping.page_number for mapping in memory.mapped_pages()}
        entries = self._read_poll_entries(process, address, count)
        readiness: list[int] = []
        for entry in entries:
            readiness.append(self._descriptor_revents(process, entry["fd"], entry["events"]))
        for index, revents in enumerate(readiness):
            memory.write(
                address + index * _POLLFD_BYTES + _POLLFD_REVENTS_OFFSET,
                int(revents).to_bytes(4, "little", signed=False),
            )
        self._journal_materialized_faults(process.pid, before, memory)
        return sum(1 for revents in readiness if revents)

    def _process_memory(self, process: Any) -> Any:
        """Mathematics: resolve total memory map `M_pid`, failing if `pid∉dom(M)` rather than creating hidden state."""

        try:
            return self.vm.memories[process.pid]
        except KeyError as exc:
            raise KernelError(f"memory image missing for pid: {process.pid}") from exc

    def _memory_syscall(self, process: Any, name: str, args: Mapping[str, Any]) -> Any:
        """Mathematics: apply a memory ABI case `δ_mem(P,name,args)` over `M_pid` and shared map `S`."""

        try:
            memory = self.vm.memories[process.pid]
        except KeyError as exc:
            raise KernelError(f"memory image missing for pid: {process.pid}") from exc
        if name == "mmap":
            requested_start = args.get("start")
            start = None if requested_start is None else int(requested_start)
            self._authorize_memory(process, 0 if start is None else start, "write")
            start = memory.allocate(
                int(args["length"]),
                bool(args.get("writable", True)),
                hint=start,
            )
            return start
        if name == "munmap":
            start = int(args["start"])
            self._authorize_memory(process, start, "write")
            memory.unmap(start, int(args["length"]))
            return 0
        if name == "mprotect":
            start = int(args["start"])
            self._authorize_memory(process, start, "write")
            memory.protect(start, int(args["length"]), bool(args["writable"]))
            return 0
        if name == "mem_read":
            address = int(args["address"])
            self._authorize_memory(process, address, "read")
            before = set(mapping.page_number for mapping in memory.mapped_pages())
            result = memory.read(address, int(args["size"]))
            self._journal_materialized_faults(process.pid, before, memory)
            return result
        if name == "mem_write":
            address = int(args["address"])
            self._authorize_memory(process, address, "write")
            before = set(mapping.page_number for mapping in memory.mapped_pages())
            result = memory.write(address, bytes(args["data"]))
            self._journal_materialized_faults(process.pid, before, memory)
            return result
        if name == "mem_info":
            self._authorize_memory(process, 0, "read")
            return {
                "page_size": memory.page_size,
                "max_pages": memory.max_pages,
                "mapped_pages": len(memory.mapped_pages()),
                "reserved_pages": len(memory.reserved_pages()),
                "resident_pages": self.vm.resident_pages(),
                "max_resident_pages": self.vm.max_resident_pages,
            }
        if name == "mem_reclaim":
            self._authorize_memory(process, 0, "write")
            raw_pages = args.get("pages")
            pages = None if raw_pages is None else tuple(int(page) for page in raw_pages)
            reclaimed = memory.reclaim(int(args.get("count", 1)), pages)
            self.environment.kernel.journal.append(
                "memory.reclaim",
                {"pid": process.pid, "pages": list(reclaimed)},
            )
            return reclaimed
        if name in {"argv_into", "environ_into", "getcwd_into"}:
            # Verify declared capacity n >= |B| before writing to memory.

            address = int(args["address"])
            capacity = int(args["size"])
            if capacity < 0:
                raise KernelError("context buffer size must be non-negative")
            field = {
                "argv_into": "argv",
                "environ_into": "environment",
                "getcwd_into": "cwd",
            }[name]
            payload = self.environment.kernel.process_context_blob(process.pid, field)
            if capacity < len(payload):
                raise KernelError(f"buffer too small: need {len(payload)} bytes")
            self._authorize_memory(process, address, "write")
            memory.validate_access(address, len(payload), "write")
            before = {mapping.page_number for mapping in memory.mapped_pages()}
            written = memory.write(address, payload)
            self._journal_materialized_faults(process.pid, before, memory)
            self.environment.kernel.journal.append(
                "memory.context_transfer",
                {
                    "pid": process.pid,
                    "field": field,
                    "address": address,
                    "capacity": capacity,
                    "size": written,
                },
            )
            return written
        if name == "pty_open_into":
            # Encode the connected PTY descriptors by the fixed-width bijection
            # `E(m,s)=u32(m)||u32(s)` over a preflighted eight-byte destination.
            address = int(args["address"])
            self._authorize_memory(process, address, "write")
            memory.validate_access(address, 8, "write")
            before = {mapping.page_number for mapping in memory.mapped_pages()}
            master_fd, slave_fd = self.environment.kernel.syscall(process.pid, "pty_open")
            try:
                memory.write(
                    address,
                    int(master_fd).to_bytes(4, "little", signed=True)
                    + int(slave_fd).to_bytes(4, "little", signed=True),
                )
            except BaseException:
                self.environment.kernel.syscall(process.pid, "close", fd=master_fd)
                self.environment.kernel.syscall(process.pid, "close", fd=slave_fd)
                raise
            self._journal_materialized_faults(process.pid, before, memory)
            self.environment.kernel.journal.append(
                "memory.pty_transfer",
                {"pid": process.pid, "address": address, "master_fd": master_fd, "slave_fd": slave_fd},
            )
            return int(master_fd)
        if name == "pipe_into":
            address = int(args["address"])
            self._authorize_memory(process, address, "write")
            memory.validate_access(address, 8, "write")
            before = {mapping.page_number for mapping in memory.mapped_pages()}
            read_fd, write_fd = self.environment.kernel.syscall(process.pid, "pipe")
            try:
                memory.write(
                    address,
                    int(read_fd).to_bytes(4, "little", signed=True)
                    + int(write_fd).to_bytes(4, "little", signed=True),
                )
            except BaseException:
                # Restore the pre-transition descriptor graph `F' = F` when the
                # result buffer cannot be materialized.
                self.environment.kernel.syscall(process.pid, "close", fd=read_fd)
                self.environment.kernel.syscall(process.pid, "close", fd=write_fd)
                raise
            self._journal_materialized_faults(process.pid, before, memory)
            self.environment.kernel.journal.append(
                "memory.pipe_transfer",
                {"pid": process.pid, "address": address, "read_fd": read_fd, "write_fd": write_fd},
            )
            return int(read_fd)
        if name == "read_into":
            address = int(args["address"])
            size = int(args["size"])
            self._authorize_memory(process, address, "write")
            memory.validate_access(address, size, "write")
            before = {mapping.page_number for mapping in memory.mapped_pages()}
            data = self.syscall(
                process.pid,
                "read",
                fd=int(args["fd"]),
                size=size,
            )
            result = memory.write(address, data)
            self._journal_materialized_faults(process.pid, before, memory)
            self.environment.kernel.journal.append(
                "memory.byte_transfer",
                {"pid": process.pid, "direction": "fd_to_memory", "address": address, "size": result},
            )
            return result
        if name == "write_from":
            address = int(args["address"])
            size = int(args["size"])
            self._authorize_memory(process, address, "read")
            memory.validate_access(address, size, "read")
            before = {mapping.page_number for mapping in memory.mapped_pages()}
            data = memory.read(address, size)
            result = self.syscall(
                process.pid,
                "write",
                fd=int(args["fd"]),
                data=data,
            )
            self._journal_materialized_faults(process.pid, before, memory)
            self.environment.kernel.journal.append(
                "memory.byte_transfer",
                {"pid": process.pid, "direction": "memory_to_fd", "address": address, "size": result},
            )
            return result
        if name == "shm_create":
            name_value = str(args["name"])
            self.environment.kernel._authorize(process, f"/memory/{name_value}", "write")
            self.vm.create_shared_memory(name_value, int(args["size"]))
            return name_value
        if name == "shm_attach":
            name_value = str(args["name"])
            start = int(args["start"])
            right = "write" if bool(args.get("writable", True)) else "read"
            self.environment.kernel._authorize(process, f"/memory/{name_value}", right)
            self.vm.attach_shared_memory(process.pid, name_value, start, bool(args.get("writable", True)))
            return start
        if name == "shm_detach":
            start = int(args["start"])
            self._authorize_memory(process, start, "write")
            memory.unmap(start, int(args["length"]))
            return 0
        raise KernelError(f"unknown memory syscall: {name}")

    def _journal_materialized_faults(self, pid: int, before: set[int], memory: Any) -> None:
        """Mathematics: record each newly resident page `p ∈ M_after - M_before` as a recovered demand fault."""

        after = {mapping.page_number for mapping in memory.mapped_pages()}
        for page_number in sorted(after - before):
            self.environment.kernel.journal.append(
                "memory.page_fault",
                {"pid": pid, "page_number": page_number, "resolution": "zero-fill"},
            )

    def _authorize_memory(self, process: Any, address: int, right: str) -> None:
        """Mathematics: require `∃c: c.allows(/memory/p,right)` before exposing memory state to process `p`."""

        resource = f"/memory/{process.pid}"
        if not any(capability.allows(resource, right) for capability in process.capabilities):
            raise KernelError(f"permission denied: {right} {resource}")

    @staticmethod
    def _memory_log_value(value: Any) -> Any:
        """Mathematics: recursively project bytes `b` to `hex(b)` and frames `f` to `S(f)` for journal JSON closure."""

        if isinstance(value, (bytes, bytearray)):
            return bytes(value).hex()
        if isinstance(value, NetworkFrame):
            return value.to_dict()
        if isinstance(value, NetworkDatagram):
            return value.to_dict()
        if isinstance(value, dict):
            return {str(key): HeadlessOS._memory_log_value(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [HeadlessOS._memory_log_value(item) for item in value]
        return value

    def launch_source(
        self,
        source: str,
        name: str = "source-task",
        initial_registers: dict[str, int] | None = None,
        environment: dict[str, str] | None = None,
        argv: Sequence[str] | None = None,
        parent_pid: int | None = None,
        group_id: int | None = None,
        inherit_fds: bool = False,
        max_pages: int | None = None,
    ) -> int:
        """Mathematics: compile `source` and return ABI process identity `pid` without advancing the scheduler orbit."""

        process_argv = tuple(argv) if argv is not None else (name,)
        return self.spawn(
            assemble(source),
            name,
            initial_registers,
            environment,
            argv=process_argv,
            parent_pid=parent_pid,
            group_id=group_id,
            inherit_fds=inherit_fds,
            max_pages=max_pages,
        )

    def launch_file(
        self,
        path: str,
        name: str | None = None,
        environment: dict[str, str] | None = None,
        argv: Sequence[str] | None = None,
        parent_pid: int | None = None,
        group_id: int | None = None,
        inherit_fds: bool = False,
        max_pages: int | None = None,
        loader_pid: int | None = None,
    ) -> int:
        """Mathematics: load executable bytes through `open → read → close` under `loader_pid` authority, decode, and enqueue the ABI process."""

        canonical = normalize_path(path)
        program = self.read_executable_program(canonical, loader_pid=loader_pid)
        process_name = name or canonical.rsplit("/", 1)[-1]
        process_argv = tuple(argv) if argv is not None else (canonical,)
        return self.spawn(
            program,
            process_name,
            environment=environment,
            argv=process_argv,
            parent_pid=parent_pid,
            group_id=group_id,
            inherit_fds=inherit_fds,
            max_pages=max_pages,
        )

    def exec_file(
        self,
        pid: int,
        path: str,
        argv: Sequence[str] | None = None,
        name: str | None = None,
        environment: dict[str, str] | None = None,
    ) -> ProcessReport:
        """Mathematics: apply `execve(pid,path,argv,environment)` after complete decode and validation, before mutating the current image."""

        canonical = normalize_path(path)
        program = self.read_executable_program(canonical, loader_pid=pid)
        process = self.environment.kernel._process(pid)
        process_name = name or canonical.rsplit("/", 1)[-1]
        process_argv = tuple(argv) if argv is not None else (canonical,)
        if process.status is ProcessStatus.EXITED:
            raise KernelError("exited process cannot exec")
        if not process_name or any(not isinstance(argument, str) for argument in process_argv):
            raise KernelError("exec identity is invalid")
        self.environment.kernel._validate_argv(process_argv)
        if environment is not None:
            self.environment.kernel._validate_environment(environment)
        self.vm.exec_program(pid, program, process_name)
        self.environment.kernel.exec_process(pid, process_name, process_argv, environment=environment)
        self.environment.release_network_handles(pid)
        return self.process(pid)

    def read_executable_program(self, path: str, loader_pid: int | None = None) -> Program:
        """Mathematics: decode `P = MCPB^{-1}(B)` when `B` has native magic, otherwise `P=assemble(UTF8(B))`, after execute-authorized descriptor I/O."""

        payload = self.read_executable(path, loader_pid=loader_pid)
        if payload.startswith(b"MCPB"):
            return BytecodeExecutable.from_bytes(payload).program
        try:
            source = payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("executable is neither valid MCPB nor UTF-8 source") from exc
        return assemble(source)

    def read_executable(self, path: str, loader_pid: int | None = None) -> bytes:
        """Mathematics: evaluate descriptor projection `bytes = read(open(path))` only when execute mode `mode & 0o111 ≠ 0`."""

        canonical = normalize_path(path)
        stat = self.environment.kernel.fs.stat(canonical)
        if stat.mode & 0o111 == 0:
            raise FsError(f"not executable: {canonical}")
        owner_pid = self.environment.init_pid if loader_pid is None else loader_pid
        fd = self.environment.kernel.syscall(owner_pid, "open", path=canonical, mode="r")
        try:
            return self.environment.kernel.syscall(owner_pid, "read", fd=fd, size=-1)
        finally:
            self.environment.kernel.syscall(owner_pid, "close", fd=fd)

    def load_elf_image(self, pid: int, path: str, base: int = 0x400000) -> ElfLoadResult:
        """Mathematics: parse and stage `ELF(path)` into `M_pid` at bias `b`, committing bytes/protections only after strict header validation."""

        process = self.environment.kernel._process(pid)
        if process.status is ProcessStatus.EXITED:
            raise KernelError("exited process cannot load ELF")
        image = parse_elf(self.read_executable(path, loader_pid=pid))
        memory = self._process_memory(process)
        result = image.load_into(memory, base)
        self.environment.kernel.journal.append(
            "elf.load",
            {
                "pid": pid,
                "path": normalize_path(path),
                "digest": image.digest,
                "machine": result.machine,
                "bits": result.bits,
                "entry": result.entry,
                "load_bias": result.load_bias,
                "mapped_pages": list(result.mapped_pages),
            },
        )
        return result

    def run(self, max_ticks: int = DEFAULT_MAX_TICKS) -> tuple[ScheduleEvent, ...]:
        """Mathematics: evaluate `S_{k+1} = T(S_k)` for at most `max_ticks`, then project task states to the kernel."""

        events = self.vm.run(max_ticks)
        self._sync_kernel_processes()
        return events

    def run_source(
        self,
        source: str,
        name: str = "source-task",
        initial_registers: dict[str, int] | None = None,
        environment: dict[str, str] | None = None,
        argv: Sequence[str] = (),
        parent_pid: int | None = None,
        group_id: int | None = None,
        inherit_fds: bool = False,
        max_ticks: int = DEFAULT_MAX_TICKS,
        max_pages: int | None = None,
    ) -> ProcessReport:
        """Mathematics: compute `report = project(run(max_ticks, spawn(assemble(source))))` in the native execution plane."""

        pid = self.launch_source(
            source,
            name,
            initial_registers,
            environment,
            argv=argv,
            parent_pid=parent_pid,
            group_id=group_id,
            inherit_fds=inherit_fds,
            max_pages=max_pages,
        )
        self.run(max_ticks)
        return self.process(pid)

    def run_file(
        self,
        path: str,
        max_ticks: int = DEFAULT_MAX_TICKS,
        name: str | None = None,
        max_pages: int | None = None,
    ) -> ProcessReport:
        """Mathematics: load `source = UTF8^-1(F[path])` from the virtual filesystem and execute its compiled program."""

        canonical = normalize_path(path)
        source = self.environment.kernel.fs.read_file(canonical).decode("utf-8")
        pid = self.launch_source(source, name or canonical.rsplit("/", 1)[-1], max_pages=max_pages)
        self.run(max_ticks)
        return self.process(pid)

    def inject(self, pid: int, mailbox: str, values: Iterable[int]) -> ProcessReport:
        """Mathematics: append `values` to `Q_mailbox(pid)` and apply `BLOCKED ∧ |Q|>0 ⇒ RUNNABLE`."""

        self.vm.scheduler.inject(pid, mailbox, tuple(values))
        self._sync_kernel_processes()
        return self.process(pid)

    def terminate(self, pid: int, exit_code: int = DEFAULT_TERMINATION_EXIT_CODE) -> ProcessReport:
        """Mathematics: apply the explicit control transition `terminate(pid, c): status := EXITED, code := c`."""

        self.vm.scheduler.terminate(pid)
        self.environment.kernel.sync_task_status(pid, ProcessStatus.EXITED, exit_code)
        return self.process(pid)

    def reap_process(self, pid: int, parent_pid: int | None = None) -> dict[str, Any]:
        """Mathematics: compose `waitpid(parent,pid); free(T_pid,M_pid,P_pid)` exactly once for an exited child."""

        owner = self.environment.init_pid if parent_pid is None else parent_pid
        result = self.environment.kernel.waitpid(owner, pid, nohang=True)
        if result is None:
            raise KernelError(f"process has not exited: {pid}")
        self.vm.reap_process(pid)
        canceled_transfers = self.environment.kernel.reap_process(pid)
        self.environment.release_fd_transfers(canceled_transfers)
        self.environment.release_network_handles(pid)
        return result

    def signal(
        self,
        pid: int,
        signal: Signal | str,
        exit_code: int | None = None,
    ) -> ProcessReport:
        """Mathematics: deliver `σ` through `δ_signal`, where `TERM/INT/KILL→EXITED`, `STOP→SUSPENDED`, `CONT→RUNNABLE`."""

        parsed = Signal.parse(signal)
        process = self.environment.kernel._process(pid)
        if process.status is ProcessStatus.EXITED:
            raise SignalError(f"cannot signal exited process: {pid}")
        if self.environment.kernel.signal_is_ignored(pid, parsed):
            self.environment.kernel.journal.append(
                "signal.ignored",
                {"pid": pid, "signal": parsed.value},
            )
            return self.process(pid)
        self.environment.kernel.journal.append("signal.deliver", {"pid": pid, "signal": parsed.value})
        if parsed is Signal.STOP:
            return self.suspend(pid)
        if parsed is Signal.CONT:
            return self.resume(pid)
        code = parsed.default_exit_code if exit_code is None else exit_code
        return self.terminate(pid, code)

    def signal_group(
        self,
        group_id: int,
        signal: Signal | str,
        exit_code: int | None = None,
    ) -> tuple[ProcessReport, ...]:
        """Mathematics: apply `σ` to every live `p∈P` with `group_id(p)=g` in PID order, preserving deterministic fan-out."""

        parsed = Signal.parse(signal)
        pids = tuple(
            process.pid
            for process in sorted(self.environment.kernel.processes.values(), key=lambda item: item.pid)
            if process.group_id == group_id and process.status is not ProcessStatus.EXITED
        )
        self.environment.kernel.journal.append(
            "signal.group",
            {"group_id": group_id, "signal": parsed.value, "pids": list(pids)},
        )
        return tuple(self.signal(pid, parsed, exit_code) for pid in pids)

    def _handle_terminal_signal(self, group_id: int, signal: str) -> None:
        """Mathematics: lift one terminal event `σ` to scheduler transitions for `p∈G`, while applying the kernel fallback to unscheduled init-only records."""

        parsed = Signal.parse(signal)
        pids = tuple(
            process.pid
            for process in sorted(self.environment.kernel.processes.values(), key=lambda item: item.pid)
            if process.group_id == group_id and process.status is not ProcessStatus.EXITED
        )
        self.environment.kernel.journal.append(
            "signal.terminal_group",
            {"group_id": group_id, "signal": parsed.value, "pids": list(pids)},
        )
        for pid in pids:
            if pid in self.vm.scheduler.tasks:
                self.signal(pid, parsed)
            else:
                process = self.environment.kernel._process(pid)
                self.environment.kernel._apply_process_signal(process, parsed.value)

    def hypervisor_decide(self, request: HypervisorRequest) -> HypervisorDecision:
        """Mathematics: expose the control-plane projection `d = H(request)` without executing the requested operation."""

        return self.hypervisor.decide(request)

    def hypervisor_arbitrate(self, event: HypervisorArbitrationEvent) -> HypervisorArbitrationResult:
        """Mathematics: apply the checkpointable loop `R:=RSI(R,event)` and reuse exact transport identities without re-evaluation."""

        return self.hypervisor_arbitration.arbitrate(event)

    def hypervisor_propose_revision(self, proposal: HypervisorRevisionProposal) -> HypervisorRevisionArbitrationResult:
        """Mathematics: apply revision receive/stabilize/inspect `R_r:=RSI_r(R_r,proposal)` without double-admitting retransmissions."""

        return self.hypervisor_arbitration.propose_revision(proposal)

    def hypervisor_dispatch(
        self,
        pid: int,
        operation: str,
        resource: str,
        payload: Mapping[str, Any],
        handlers: Mapping[HypervisorDomain | str, Callable[[], Any]],
        required_rights: frozenset[str] = frozenset(),
        destructive: bool = False,
    ) -> tuple[HypervisorDecision, Any | None]:
        """Mathematics: derive `G={r∈R | ∃c∈Caps(pid):c.allows(resource,r)}` and attach current epoch `τ=(λ,phase,τ_chem)`."""

        process = self.environment.kernel._process(pid)
        granted = frozenset(
            right
            for right in required_rights
            if any(capability.allows(resource, right) for capability in process.capabilities)
        )
        epoch = self.vm.scheduler.system_epoch
        request = HypervisorRequest(
            operation=operation,
            resource=resource,
            payload=dict(payload),
            required_rights=required_rights,
            granted_rights=granted,
            destructive=destructive,
            temporal={
                "event_lambda": epoch.event_lambda,
                "chronon_real": epoch.chronon_phase.real,
                "chronon_imag": epoch.chronon_phase.imag,
                "chemical_tau": epoch.chemical_tau,
            },
        )
        return self.hypervisor.dispatch(request, handlers)

    def hypervisor_read_file(
        self,
        pid: int,
        path: str,
        size: int = -1,
    ) -> tuple[HypervisorDecision, bytes | None]:
        """Mathematics: apply `ALLOW ⇒ read(open(path))` through the kernel descriptor ABI, otherwise return no bytes."""

        canonical = normalize_path(path)

        def read_descriptor() -> bytes:
            """Mathematics: read `size` bytes through a descriptor opened for `canonical`, releasing the descriptor on every exit path."""

            fd = self.environment.kernel.syscall(pid, "open", path=canonical, mode="r")
            try:
                return self.environment.kernel.syscall(pid, "read", fd=fd, size=size)
            finally:
                self.environment.kernel.syscall(pid, "close", fd=fd)

        decision, result = self.hypervisor_dispatch(
            pid,
            "read filesystem file path descriptor",
            canonical,
            {"path": canonical, "size": size},
            {HypervisorDomain.FILESYSTEM: read_descriptor},
            frozenset({"read"}),
        )
        return decision, result if isinstance(result, bytes) else None

    def hypervisor_start_service(
        self,
        pid: int,
        name: str,
    ) -> tuple[HypervisorDecision, Any | None]:
        """Mathematics: apply `ALLOW ⇒ ServiceSupervisor.start(name)` under process capability `execute` on `/service/name`."""

        return self.hypervisor_dispatch(
            pid,
            "start service supervisor process lifecycle",
            f"/service/{name}",
            {"service": name},
            {HypervisorDomain.SERVICE: lambda: self.services.start(name)},
            frozenset({"execute"}),
        )

    def hypervisor_launch_file(
        self,
        pid: int,
        path: str,
        name: str | None = None,
        argv: Sequence[str] | None = None,
        inherit_fds: bool = False,
        max_pages: int | None = None,
    ) -> tuple[HypervisorDecision, int | None]:
        """Mathematics: apply `G(pid,path)⊉{execute}⇒DENY`, else `ALLOW⇒launch_file(path)` exactly once under `loader_pid=pid`."""

        canonical = normalize_path(path)
        process_argv = None if argv is None else tuple(argv)
        return self.hypervisor_dispatch(
            pid,
            "spawn process executable file child image",
            canonical,
            {
                "path": canonical,
                "name": name,
                "argv": None if process_argv is None else list(process_argv),
                "inherit_fds": bool(inherit_fds),
                "max_pages": max_pages,
            },
            {
                HypervisorDomain.PROCESS: lambda: self.launch_file(
                    canonical,
                    name=name,
                    argv=process_argv,
                    parent_pid=pid,
                    inherit_fds=inherit_fds,
                    max_pages=max_pages,
                    loader_pid=pid,
                )
            },
            frozenset({"execute"}),
        )

    def hypervisor_install_package(
        self,
        pid: int,
        registry: ImageRegistry,
        digest: str,
    ) -> tuple[HypervisorDecision, Any | None]:
        """Mathematics: apply `G(pid,/package/h)⊉{write}⇒DENY`; else `ALLOW∧policy_destructive⇒registry.install(h,E)` exactly once."""

        if not isinstance(registry, ImageRegistry):
            raise TypeError("package adapter requires an ImageRegistry")
        if not isinstance(digest, str) or not digest:
            raise ValueError("package adapter digest must be non-empty")
        return self.hypervisor_dispatch(
            pid,
            "install package registry image digest deployment",
            f"/package/{digest}",
            {"digest": digest},
            {HypervisorDomain.PACKAGE: lambda: registry.install(digest, self.environment)},
            frozenset({"write"}),
            destructive=True,
        )

    def hypervisor_ingest_network(
        self,
        pid: int,
        logical_time: int,
        packet: bytes,
    ) -> tuple[HypervisorDecision, Any | None]:
        """Mathematics: apply `ALLOW ⇒ network.ingest(t,packet)` under capability `write` on `/net/capture`."""

        return self.hypervisor_dispatch(
            pid,
            "ingest network packet TCP socket route HTTP",
            "/net/capture",
            {"logical_time": logical_time, "packet_hex": packet.hex()},
            {HypervisorDomain.NETWORK: lambda: self.environment.network.ingest(logical_time, packet)},
            frozenset({"write"}),
        )

    def drain_owned_network_to_e0(
        self,
        pid: int,
        namespace: str,
        interface: str,
        max_frames: int = 1,
    ) -> tuple[object, ...]:
        """Mathematics: expose the transactional owned-link-to-E0 driver under capability `receive(/net/n/i)`."""

        return self.environment.network_drain_to_e0(pid, namespace, interface, max_frames)

    def suspend(self, pid: int) -> ProcessReport:
        """Mathematics: apply scheduler suspension `RUNNABLE/BLOCKED -> SUSPENDED` without changing program counter."""

        self.vm.scheduler.suspend(pid)
        self._sync_kernel_processes()
        return self.process(pid)

    def resume(self, pid: int) -> ProcessReport:
        """Mathematics: apply continuation transition `SUSPENDED -> RUNNABLE` and return the resulting process projection."""

        self.vm.scheduler.resume(pid)
        self._sync_kernel_processes()
        return self.process(pid)

    def process(self, pid: int) -> ProcessReport:
        """Mathematics: return the observable projection `P[pid] ⊕ T[pid]`, rejecting unknown identities."""

        process = self.environment.kernel._process(pid)
        task = self.vm.scheduler.tasks.get(pid)
        if task is None:
            return ProcessReport(
                pid=pid,
                name=process.name,
                status=process.status.value,
                pc=0,
                steps=0,
                registers={},
                exit_code=process.exit_code,
                errno=process.errno,
                environment=dict(sorted(process.environment.items())),
                argv=process.argv,
                parent_pid=process.parent_pid,
                group_id=process.group_id,
                session_id=process.session_id,
                subreaper=process.subreaper,
                cwd=process.cwd,
            )
        return ProcessReport(
            pid=pid,
            name=task.name,
            status=process.status.value,
            pc=task.state.pc,
            steps=task.state.steps,
            registers=task.backend.snapshot_registers(),
            exit_code=process.exit_code,
            errno=process.errno,
            environment=dict(sorted(process.environment.items())),
            argv=process.argv,
            parent_pid=process.parent_pid,
            group_id=process.group_id,
            session_id=process.session_id,
            subreaper=process.subreaper,
            cwd=process.cwd,
        )

    def processes(self) -> tuple[ProcessReport, ...]:
        """Mathematics: enumerate the finite process set `Reports = {project(P[p]) | p ∈ dom(P)}` in PID order."""

        return tuple(self.process(pid) for pid in sorted(self.environment.kernel.processes))

    def shell(self, command_line: str, pid: int | None = None) -> CommandResult:
        """Mathematics: evaluate the shell grammar `G = {run, ps} ∪ G_environment` as one deterministic command."""

        try:
            args = shlex.split(command_line, comments=True, posix=True)
        except ValueError as exc:
            return CommandResult(2, stderr=f"{exc}\n")
        if not args:
            return CommandResult(0)
        command, *rest = args
        if command in ("run", "exec"):
            if not rest:
                return CommandResult(2, stderr="run requires a virtual source path\n")
            try:
                max_ticks = int(rest[1]) if len(rest) > 1 else DEFAULT_MAX_TICKS
                report = self.run_file(rest[0], max_ticks=max_ticks)
            except (AssemblyError, FsError, UnicodeDecodeError, ValueError) as exc:
                return CommandResult(1, stderr=f"{exc}\n")
            return CommandResult(0 if report.status == ProcessStatus.EXITED.value else 1, stdout=_json_line(report.to_dict()))
        if command == "env":
            process_id = self.environment.init_pid if pid is None else pid
            try:
                values = self.environment.kernel.syscall(process_id, "environ")
            except KernelError as exc:
                return CommandResult(1, stderr=f"{exc}\n")
            return CommandResult(0, stdout="".join(f"{key}={value}\n" for key, value in values.items()))
        if command == "export":
            if len(rest) < 2:
                return CommandResult(2, stderr="export requires KEY VALUE\n")
            process_id = self.environment.init_pid if pid is None else pid
            try:
                self.environment.kernel.syscall(process_id, "setenv", key=rest[0], value=" ".join(rest[1:]))
            except KernelError as exc:
                return CommandResult(1, stderr=f"{exc}\n")
            return CommandResult(0)
        if command == "inject":
            if len(rest) < 3:
                return CommandResult(2, stderr="inject requires PID MAILBOX VALUE...\n")
            try:
                report = self.inject(int(rest[0]), rest[1], (int(value, 0) for value in rest[2:]))
            except (KeyError, ValueError) as exc:
                return CommandResult(1, stderr=f"{exc}\n")
            return CommandResult(0, stdout=_json_line(report.to_dict()))
        if command == "kill":
            if not rest:
                return CommandResult(2, stderr="kill requires PID [EXIT_CODE]\n")
            try:
                report = self.terminate(int(rest[0]), int(rest[1], 0) if len(rest) > 1 else DEFAULT_TERMINATION_EXIT_CODE)
            except (KeyError, ValueError) as exc:
                return CommandResult(1, stderr=f"{exc}\n")
            return CommandResult(0, stdout=_json_line(report.to_dict()))
        if command in ("stop", "suspend"):
            if not rest:
                return CommandResult(2, stderr="stop requires PID\n")
            try:
                report = self.suspend(int(rest[0]))
            except (KeyError, ValueError) as exc:
                return CommandResult(1, stderr=f"{exc}\n")
            return CommandResult(0, stdout=_json_line(report.to_dict()))
        if command in ("cont", "resume"):
            if not rest:
                return CommandResult(2, stderr="cont requires PID\n")
            try:
                report = self.resume(int(rest[0]))
            except (KeyError, ValueError) as exc:
                return CommandResult(1, stderr=f"{exc}\n")
            return CommandResult(0, stdout=_json_line(report.to_dict()))
        if command == "signal":
            if len(rest) < 2:
                return CommandResult(2, stderr="signal requires PID SIGNAL\n")
            try:
                report = self.signal(int(rest[0]), rest[1])
            except (KeyError, SignalError, ValueError) as exc:
                return CommandResult(1, stderr=f"{exc}\n")
            return CommandResult(0, stdout=_json_line(report.to_dict()))
        if command == "signal-group":
            if len(rest) < 2:
                return CommandResult(2, stderr="signal-group requires GROUP_ID SIGNAL [EXIT_CODE]\n")
            try:
                reports = self.signal_group(
                    int(rest[0], 0),
                    rest[1],
                    int(rest[2], 0) if len(rest) > 2 else None,
                )
            except (KeyError, SignalError, ValueError) as exc:
                return CommandResult(1, stderr=f"{exc}\n")
            return CommandResult(0, stdout=_json_line({"reports": [report.to_dict() for report in reports]}))
        if command == "ps":
            rows = self.processes()
            text = "".join(f"{row.pid}\t{row.status}\t{row.name}\n" for row in rows)
            return CommandResult(0, stdout=text)
        return self.environment.run_command(args, pid)

    def run_script(self, script: str, pid: int | None = None) -> tuple[CommandResult, ...]:
        """Mathematics: preserve shell composition `R = (eval(line_1), ..., eval(line_n))` over non-comment lines."""

        results: list[CommandResult] = []
        for line in script.splitlines():
            if line.strip() and not line.lstrip().startswith("#"):
                results.append(self.shell(line, pid))
        return tuple(results)

    def snapshot(self) -> dict[str, object]:
        """Mathematics: serialize `OS = (VM, Services, HypervisorPolicy)` into one continuation-capable checkpoint graph."""

        if self._pending_exec or self._pending_fork:
            raise ValueError("cannot snapshot an uncommitted exec or fork transition")
        return {
            "vm": self.vm.snapshot(),
            "services": self.services.snapshot(),
            "hypervisor": self.hypervisor.snapshot(),
            "hypervisor_arbitration": self.hypervisor_arbitration.snapshot(),
        }

    def save_checkpoint(self, path: str) -> str:
        """Mathematics: persist canonical checkpoint `C = JSON(sort_keys(OS))` and return its SHA-256 identity."""

        from .checkpoint import save_checkpoint

        return save_checkpoint(self, path)

    @classmethod
    def from_snapshot(
        cls,
        payload: dict[str, object],
        trajectory: TrajectoryWriter | None = None,
    ) -> "HeadlessOS":
        """Mathematics: reconstruct headless state `OS'` whose next scheduler transition equals the saved transition."""

        from .service import ServiceSupervisor

        machine = MailCPUVirtualMachine.from_snapshot(dict(payload["vm"]), trajectory=trajectory)
        operating_system = cls.__new__(cls)
        operating_system.environment = machine.environment
        operating_system.vm = machine
        operating_system._pending_exec = {}
        operating_system._pending_fork = {}
        operating_system.vm.host_syscall_handler = operating_system._dispatch_program_syscall
        operating_system.environment.kernel.terminal_signal_handler = operating_system._handle_terminal_signal
        operating_system.vm.scheduler.wait_predicate = operating_system._scheduler_wait_ready
        operating_system.vm.scheduler.post_step = operating_system._apply_deferred_exec
        operating_system.hypervisor = ClassifierHypervisor.from_snapshot(
            dict(payload.get("hypervisor", {})),
            operating_system.environment.kernel.journal,
        )
        operating_system.hypervisor_arbitration = HypervisorArbitrationLoop.from_snapshot(
            operating_system.hypervisor,
            dict(payload.get("hypervisor_arbitration", {})),
        )
        operating_system.services = ServiceSupervisor.from_snapshot(
            operating_system,
            dict(payload.get("services", {})),
        )
        return operating_system

    @classmethod
    def restore_checkpoint(cls, path: str) -> "HeadlessOS":
        """Mathematics: load checkpoint `C`, verify its digest, and return a continuation-capable `HeadlessOS` instance."""

        from .checkpoint import load_checkpoint

        return load_checkpoint(path)

    def _ensure_parent_directories(self, path: str) -> None:
        """Mathematics: ensure every prefix in `parent(path)` is a directory vertex in the filesystem graph."""

        parts = path.strip("/").split("/")[:-1]
        current = ""
        for component in parts:
            current += "/" + component
            try:
                self.environment.kernel.fs.stat(current)
            except FsError:
                self.environment.kernel.fs.mkdir(current)

    def _sync_kernel_processes(self) -> None:
        """Mathematics: apply the homomorphism `runnable↦RUNNABLE, blocked↦BLOCKED, halted↦EXITED` to kernel process state."""

        for pid, task in self.vm.scheduler.tasks.items():
            if task.status is TaskStatus.HALTED:
                self.environment.kernel.sync_task_status(pid, ProcessStatus.EXITED, 0)
            elif task.status is TaskStatus.BLOCKED:
                self.environment.kernel.sync_task_status(pid, ProcessStatus.BLOCKED)
            elif task.status is TaskStatus.SUSPENDED:
                self.environment.kernel.sync_task_status(pid, ProcessStatus.STOPPED)
            else:
                self.environment.kernel.sync_task_status(pid, ProcessStatus.RUNNABLE)


def _json_line(value: dict[str, object]) -> str:
    """Mathematics: serialize a finite report map with a stable key order `JSON(sort_keys(value))`."""

    import json

    return json.dumps(value, sort_keys=True) + "\n"
