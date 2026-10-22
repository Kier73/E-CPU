"""Bootable Unix-shaped MailCPU environment and a small deterministic command surface."""

from __future__ import annotations

import shlex
from dataclasses import dataclass
from typing import Iterable

from .kernel import Capability, KernelError, OpenFile, POLLERR, POLLHUP, POLLIN, POLLOUT, VirtualKernel
from .network import HeadlessNetworkDevice
from .datagram import DatagramError, NetworkDatagram, OwnedDatagramStack
from .evidence import EvidenceTier
from .owned_network import NetworkAddress, NetworkFrame, OwnedLinkDriver, OwnedNetworkFabric
from .stream import OwnedStreamStack, StreamError
from .providers import ProceduralProvider, ProviderKind


@dataclass(frozen=True)
class CommandResult:
    """Result of a built-in command invocation with explicit substrate provenance."""

    exit_code: int
    stdout: str = ""
    stderr: str = ""
    evidence_tier: EvidenceTier = EvidenceTier.E0


class VirtualEnvironment:
    """A reproducible root filesystem, kernel, bus, devices, and init process."""

    def __init__(
        self,
        kernel: VirtualKernel,
        init_pid: int,
        network: HeadlessNetworkDevice | None = None,
        owned_network: OwnedNetworkFabric | None = None,
        datagrams: OwnedDatagramStack | None = None,
        streams: OwnedStreamStack | None = None,
        datagram_owners: dict[int, int] | None = None,
        stream_listener_owners: dict[int, int] | None = None,
        stream_connection_owners: dict[int, int] | None = None,
    ) -> None:
        """Mathematics: bind `E=(K,init_pid,N_e,N_o,D_o,S_o)` without duplicating kernel or network state."""

        self.kernel = kernel
        self.init_pid = init_pid
        self.network = network or HeadlessNetworkDevice(journal=kernel.journal)
        self.owned_network = owned_network or OwnedNetworkFabric(journal=kernel.journal)
        self.datagrams = datagrams or OwnedDatagramStack(self.owned_network, journal=kernel.journal)
        self.streams = streams or OwnedStreamStack(self.owned_network, journal=kernel.journal)
        self._datagram_owners = dict(datagram_owners or {})
        self._stream_listener_owners = dict(stream_listener_owners or {})
        self._stream_connection_owners = dict(stream_connection_owners or {})

    @classmethod
    def bootstrap(cls) -> "VirtualEnvironment":
        """Mathematics: construct a finite Unix namespace `{/bin, /dev, /etc, /home, /proc, /run, /sys, /tmp, /var}`."""

        kernel = VirtualKernel()
        for path in ("/bin", "/dev", "/etc", "/home", "/proc", "/run", "/sys", "/tmp", "/var"):
            kernel.fs.mkdir(path)
        kernel.fs.create_file(
            "/etc/os-release",
            b"NAME=MailCPU\nID=mailcpu\nVIRTUALIZATION=communication-infrastructure\n",
        )
        kernel.fs.create_file("/etc/hostname", b"mailcpu\n")
        kernel.fs.create_file("/proc/cpuinfo", b"processor\t: mailcpu-vcpu\n")
        kernel.fs.create_file("/proc/meminfo", b"MemTotal: communication-backed\n")
        kernel.fs.register_procedural_file(
            "/dev/zero",
            ProceduralProvider(ProviderKind.ZERO, size=1024 * 1024),
        )
        kernel.fs.register_procedural_file(
            "/dev/entropy",
            ProceduralProvider(ProviderKind.ENTROPY, size=1024 * 1024, seed=0x9E3779B97F4A7C15),
        )
        kernel.fs.create_file("/dev/null", b"")
        kernel.fs.create_file("/dev/console", b"")
        init_pid = kernel.spawn("init")
        kernel.init_pid = init_pid
        owned_network = OwnedNetworkFabric(journal=kernel.journal)
        owned_network.create_namespace("root")
        datagrams = OwnedDatagramStack(owned_network, journal=kernel.journal)
        streams = OwnedStreamStack(owned_network, journal=kernel.journal)
        return cls(kernel, init_pid, HeadlessNetworkDevice(journal=kernel.journal), owned_network, datagrams, streams)

    def network_create_namespace(self, pid: int, name: str) -> None:
        """Mathematics: authorize `write(/net)` and extend owned namespace set `N_o := N_o ∪ {name}`."""

        process = self.kernel._process(pid)
        self.kernel._authorize(process, "/net", "write")
        self.owned_network.create_namespace(name)

    def feed_device(self, name: str, data: bytes) -> int:
        """Mathematics: inject external input `B` into driver queue `Q_device := Q_device || B` and journal one control-plane receipt."""

        count = self.kernel.devices.feed(name, bytes(data))
        self.kernel.dispatch_terminal_signals()
        self.kernel.journal.append(
            "device.feed",
            {"device": name, "size": count, "data_hex": bytes(data).hex()},
        )
        return count

    def network_create_interface(self, pid: int, namespace: str, interface: str, mtu: int = 1500) -> NetworkAddress:
        """Mathematics: authorize `write(/net/n/i)` and add endpoint `v=(n,i)` to `N_o`."""

        process = self.kernel._process(pid)
        self.kernel._authorize(process, f"/net/{namespace}/{interface}", "write")
        return self.owned_network.create_interface(namespace, interface, mtu)

    def network_connect(
        self,
        pid: int,
        link_id: str,
        left: NetworkAddress,
        right: NetworkAddress,
    ) -> None:
        """Mathematics: authorize both endpoints and add edge `l=(left,right)` to the owned graph."""

        process = self.kernel._process(pid)
        self.kernel._authorize(process, left.path(), "write")
        self.kernel._authorize(process, right.path(), "write")
        self.owned_network.connect(link_id, left, right)

    def network_send(
        self,
        pid: int,
        source: NetworkAddress,
        destination: NetworkAddress,
        payload: bytes,
        logical_time: int,
    ) -> int:
        """Mathematics: authorize `send(source) ∧ receive(destination)` and enqueue `f` under `Q_d := Q_d || f`."""

        process = self.kernel._process(pid)
        self.kernel._authorize(process, source.path(), "send")
        self.kernel._authorize(process, destination.path(), "receive")
        return self.owned_network.send(source, destination, payload, logical_time)

    def network_route_send(
        self,
        pid: int,
        source: NetworkAddress,
        destination: NetworkAddress,
        payload: bytes,
        logical_time: int,
    ) -> int:
        """Mathematics: authorize `send(source) ∧ receive(destination)` and enqueue along `r=route(source,destination)`."""

        process = self.kernel._process(pid)
        self.kernel._authorize(process, source.path(), "send")
        self.kernel._authorize(process, destination.path(), "receive")
        return self.owned_network.send_routed(source, destination, payload, logical_time)

    def network_datagram_bind(self, pid: int, namespace: str, interface: str, port: int, queue_limit: int | None = None) -> int:
        """Mathematics: authorize `write(/net/n/i)` and create unique binding `B[(n,i,p)] := socket_id`."""

        process = self.kernel._process(pid)
        address = NetworkAddress(namespace, interface)
        self.kernel._authorize(process, address.path(), "write")
        socket_id = self.datagrams.bind(address, port, queue_limit)
        self._datagram_owners[socket_id] = pid
        return socket_id

    def network_datagram_send(
        self,
        pid: int,
        socket_id: int,
        destination: NetworkAddress,
        destination_port: int,
        payload: bytes,
        logical_time: int,
        routed: bool = True,
    ) -> int:
        """Mathematics: authorize socket source `send` and destination `receive`, then transmit an encoded datagram."""

        process = self.kernel._process(pid)
        self._require_owner(self._datagram_owners, socket_id, pid, "datagram socket")
        source, _ = self.datagrams.binding(socket_id)
        self.kernel._authorize(process, source.path(), "send")
        self.kernel._authorize(process, destination.path(), "receive")
        return self.datagrams.send(socket_id, destination, destination_port, payload, logical_time, routed)

    def network_datagram_peek(self, pid: int, socket_id: int, max_size: int | None = None) -> NetworkDatagram | None:
        """Mathematics: authorize `receive(source_socket)` and expose `head(Q_socket)` without removing it."""

        process = self.kernel._process(pid)
        self._require_owner(self._datagram_owners, socket_id, pid, "datagram socket")
        address, _ = self.datagrams.binding(socket_id)
        self.kernel._authorize(process, address.path(), "receive")
        return self.datagrams.peek(socket_id, max_size)

    def network_datagram_receive(self, pid: int, socket_id: int, max_size: int | None = None) -> NetworkDatagram | None:
        """Mathematics: authorize `receive(source_socket)` and apply `Q_socket := tail(Q_socket)` atomically."""

        process = self.kernel._process(pid)
        self._require_owner(self._datagram_owners, socket_id, pid, "datagram socket")
        address, _ = self.datagrams.binding(socket_id)
        self.kernel._authorize(process, address.path(), "receive")
        return self.datagrams.receive(socket_id, max_size)

    def network_datagram_close(self, pid: int, socket_id: int) -> None:
        """Mathematics: authorize owner `pid=Owner(socket)` and remove socket binding plus queued decoded datagrams."""

        process = self.kernel._process(pid)
        self._require_owner(self._datagram_owners, socket_id, pid, "datagram socket")
        address, _ = self.datagrams.binding(socket_id)
        self.kernel._authorize(process, address.path(), "write")
        self.datagrams.close(socket_id)
        self._datagram_owners.pop(int(socket_id), None)

    def network_datagram_bind_fd(
        self,
        pid: int,
        namespace: str,
        interface: str,
        port: int,
        queue_limit: int | None = None,
    ) -> int:
        """Mathematics: compose datagram bind `s:=bind(n,i,p)` with descriptor allocation `fd:=least_free(F_pid)`."""

        socket_id = self.network_datagram_bind(pid, namespace, interface, port, queue_limit)
        return self._install_network_fd(pid, "datagram", socket_id, f"/net/{namespace}/{interface}")

    def network_datagram_fd_send(
        self,
        pid: int,
        socket: OpenFile,
        destination: NetworkAddress,
        destination_port: int,
        payload: bytes,
        logical_time: int,
        routed: bool = True,
    ) -> int:
        """Mathematics: use descriptor-bound datagram `s` as authority, then transmit `encode(p_s,p_d,b)`."""

        if socket.network_kind != "datagram" or socket.network_handle is None:
            raise KernelError("descriptor is not a datagram socket")
        process = self.kernel._process(pid)
        source, _ = self.datagrams.binding(socket.network_handle)
        self.kernel._authorize(process, source.path(), "send")
        self.kernel._authorize(process, destination.path(), "receive")
        return self.datagrams.send(socket.network_handle, destination, destination_port, payload, logical_time, routed)

    def network_datagram_ready(self, pid: int, socket_id: int) -> bool:
        """Mathematics: evaluate `ready(s) ⇔ |Q_s|>0` under owner and receive capability without dequeuing `Q_s`."""

        process = self.kernel._process(pid)
        self._require_owner(self._datagram_owners, socket_id, pid, "datagram socket")
        address, _ = self.datagrams.binding(socket_id)
        self.kernel._authorize(process, address.path(), "receive")
        return self.datagrams.ready(socket_id)

    def network_fd_receive(self, pid: int, socket: OpenFile, size: int) -> bytes:
        """Mathematics: map descriptor read `read(fd,n)` to a bounded stream/datagram dequeue or explicit would-block."""

        if socket.network_handle is None or socket.network_kind not in {"stream_connection", "datagram"}:
            raise KernelError("descriptor is not a readable network socket")
        process = self.kernel._process(pid)
        limit = None if size < 0 else size
        if socket.network_kind == "stream_connection":
            local, _, _, _ = self.streams.connection_binding(socket.network_handle)
            self.kernel._authorize(process, local.path(), "receive")
            data = self.streams.receive(socket.network_handle, limit)
            if data is None:
                raise KernelError("network stream would block")
            return data
        local, _ = self.datagrams.binding(socket.network_handle)
        self.kernel._authorize(process, local.path(), "receive")
        datagram = self.datagrams.receive(socket.network_handle, limit)
        if datagram is None:
            raise KernelError("network datagram would block")
        return datagram.payload

    def network_fd_send(self, pid: int, socket: OpenFile, payload: bytes, logical_time: int) -> int:
        """Mathematics: map descriptor write `write(fd,b)` to stream DATA frame emission."""

        if socket.network_kind != "stream_connection" or socket.network_handle is None:
            raise KernelError("network write requires a connected stream descriptor")
        process = self.kernel._process(pid)
        local, _, peer, _ = self.streams.connection_binding(socket.network_handle)
        self.kernel._authorize(process, local.path(), "send")
        self.kernel._authorize(process, peer.path(), "receive")
        return self.streams.send(socket.network_handle, payload, logical_time)

    def network_fd_close(self, pid: int, socket: OpenFile, logical_time: int = 0) -> None:
        """Mathematics: close the final descriptor description by applying the matching native socket close transition."""

        if socket.network_handle is None or socket.network_kind is None:
            raise KernelError("descriptor is not a network socket")
        process = self.kernel._process(pid)
        if socket.network_kind == "stream_connection":
            local, _, peer, _ = self.streams.connection_binding(socket.network_handle)
            self.kernel._authorize(process, local.path(), "send")
            self.kernel._authorize(process, peer.path(), "receive")
            self.streams.close(socket.network_handle, logical_time)
            self._stream_connection_owners.pop(socket.network_handle, None)
        elif socket.network_kind == "stream_listener":
            address, _ = self.streams.listener_binding(socket.network_handle)
            self.kernel._authorize(process, address.path(), "write")
            self.streams.destroy_listener(socket.network_handle)
            self._stream_listener_owners.pop(socket.network_handle, None)
        elif socket.network_kind == "datagram":
            local, _ = self.datagrams.binding(socket.network_handle)
            self.kernel._authorize(process, local.path(), "write")
            self.datagrams.close(socket.network_handle)
            self._datagram_owners.pop(socket.network_handle, None)
        else:
            raise KernelError(f"unsupported network descriptor kind: {socket.network_kind}")

    def network_fd_readiness(self, pid: int, socket: OpenFile, events: int) -> int:
        """Mathematics: project native state to `poll(fd,E)` bits, preserving `IN`, `OUT`, and terminal `HUP/ERR` evidence."""

        if socket.network_handle is None or socket.network_kind is None:
            raise KernelError("descriptor is not a network socket")
        requested = int(events)
        if requested < 0:
            raise KernelError("poll events must be non-negative")
        process = self.kernel._process(pid)
        readiness = 0
        if socket.network_kind == "datagram":
            local, _ = self.datagrams.binding(socket.network_handle)
            if requested & POLLIN:
                self.kernel._authorize(process, local.path(), "receive")
                if self.datagrams.ready(socket.network_handle):
                    readiness |= POLLIN
            if requested & POLLOUT:
                self.kernel._authorize(process, local.path(), "send")
                readiness |= POLLOUT
            return readiness
        if socket.network_kind == "stream_listener":
            local, _ = self.streams.listener_binding(socket.network_handle)
            if requested & POLLIN:
                self.kernel._authorize(process, local.path(), "receive")
                if self.streams.listener_ready(socket.network_handle):
                    readiness |= POLLIN
            return readiness
        if socket.network_kind == "stream_connection":
            local, _, peer, _ = self.streams.connection_binding(socket.network_handle)
            readable, writable, hangup = self.streams.connection_readiness(socket.network_handle)
            if requested & POLLIN:
                self.kernel._authorize(process, local.path(), "receive")
                if readable:
                    readiness |= POLLIN
            if requested & POLLOUT:
                self.kernel._authorize(process, local.path(), "send")
                self.kernel._authorize(process, peer.path(), "receive")
                if writable:
                    readiness |= POLLOUT
            if hangup:
                readiness |= POLLHUP
            return readiness
        return POLLERR

    def network_stream_listen(self, pid: int, namespace: str, interface: str, port: int, backlog: int | None = None) -> int:
        """Mathematics: authorize `write(/net/n/i)` and create listener state `L[(n,i,p)]` with bounded backlog."""

        process = self.kernel._process(pid)
        address = NetworkAddress(namespace, interface)
        self.kernel._authorize(process, address.path(), "write")
        listener = self.streams.listen(address, port, backlog)
        self._stream_listener_owners[listener] = pid
        return listener

    def network_stream_listen_fd(self, pid: int, namespace: str, interface: str, port: int, backlog: int | None = None) -> int:
        """Mathematics: compose listener transition `L:=listen(n,i,p)` with descriptor allocation `fd:=least_free(F_pid)`."""

        listener = self.network_stream_listen(pid, namespace, interface, port, backlog)
        return self._install_network_fd(pid, "stream_listener", listener, f"/net/{namespace}/{interface}")

    def network_stream_connect(
        self,
        pid: int,
        source: NetworkAddress,
        source_port: int,
        destination: NetworkAddress,
        destination_port: int,
    ) -> int:
        """Mathematics: authorize `send(source) ∧ receive(destination)` and create an established native stream pair."""

        process = self.kernel._process(pid)
        self.kernel._authorize(process, source.path(), "send")
        self.kernel._authorize(process, destination.path(), "receive")
        client = self.streams.connect(source, source_port, destination, destination_port)
        self._stream_connection_owners[client] = pid
        return client

    def network_stream_connect_fd(
        self,
        pid: int,
        source: NetworkAddress,
        source_port: int,
        destination: NetworkAddress,
        destination_port: int,
    ) -> int:
        """Mathematics: compose `connect(source,destination)` with descriptor allocation over the established client handle."""

        connection = self.network_stream_connect(pid, source, source_port, destination, destination_port)
        return self._install_network_fd(pid, "stream_connection", connection, source.path())

    def network_stream_accept(self, pid: int, listener: int) -> int | None:
        """Mathematics: authorize listener `receive` and consume one pending connection or return `⊥`."""

        process = self.kernel._process(pid)
        self._require_owner(self._stream_listener_owners, listener, pid, "stream listener")
        address, _ = self.streams.listener_binding(listener)
        self.kernel._authorize(process, address.path(), "receive")
        connection = self.streams.accept(listener)
        if connection is not None:
            self._stream_connection_owners[connection] = pid
        return connection

    def network_stream_listener_ready(self, pid: int, listener: int) -> bool:
        """Mathematics: evaluate `ready(l) ⇔ |pending(l)|>0` under listener ownership and receive capability."""

        process = self.kernel._process(pid)
        self._require_owner(self._stream_listener_owners, listener, pid, "stream listener")
        address, _ = self.streams.listener_binding(listener)
        self.kernel._authorize(process, address.path(), "receive")
        return self.streams.listener_ready(listener)

    def network_stream_accept_fd(self, pid: int, listener: OpenFile) -> int | None:
        """Mathematics: accept through a listener descriptor and wrap the resulting connection in a shared open description."""

        if listener.network_kind != "stream_listener" or listener.network_handle is None:
            raise KernelError("descriptor is not a stream listener")
        connection = self.network_stream_accept(pid, listener.network_handle)
        if connection is None:
            return None
        local, _, _, _ = self.streams.connection_binding(connection)
        return self._install_network_fd(pid, "stream_connection", connection, local.path())

    def network_stream_ready(self, pid: int, handle: int) -> bool:
        """Mathematics: evaluate `ready(c) ⇔ |R_c|>0 ∨ eof(c)` through the owned stream projection without consuming bytes."""

        process = self.kernel._process(pid)
        self._require_owner(self._stream_connection_owners, handle, pid, "stream connection")
        local, _, _, _ = self.streams.connection_binding(handle)
        self.kernel._authorize(process, local.path(), "receive")
        return self.streams.peek(handle) is not None

    def network_stream_writable(self, pid: int, handle: int) -> bool:
        """Mathematics: evaluate `writable(c) ⇔ state(c)=ESTABLISHED ∧ Σ pending(c)<W` under stream ownership and send authority."""

        process = self.kernel._process(pid)
        self._require_owner(self._stream_connection_owners, handle, pid, "stream connection")
        local, _, peer, _ = self.streams.connection_binding(handle)
        self.kernel._authorize(process, local.path(), "send")
        self.kernel._authorize(process, peer.path(), "receive")
        return self.streams.connection_readiness(handle)[1]

    def network_stream_send(self, pid: int, handle: int, payload: bytes, logical_time: int) -> int:
        """Mathematics: authorize connection local `send` and peer `receive`, then append bounded DATA segments."""

        process = self.kernel._process(pid)
        self._require_owner(self._stream_connection_owners, handle, pid, "stream connection")
        local, _, peer, _ = self.streams.connection_binding(handle)
        self.kernel._authorize(process, local.path(), "send")
        self.kernel._authorize(process, peer.path(), "receive")
        return self.streams.send(handle, payload, logical_time)

    def network_stream_peek(self, pid: int, handle: int, max_size: int | None = None) -> bytes | None:
        """Mathematics: authorize local `receive` and expose stream head `R_handle[0:max_size]` without removal."""

        process = self.kernel._process(pid)
        self._require_owner(self._stream_connection_owners, handle, pid, "stream connection")
        local, _, _, _ = self.streams.connection_binding(handle)
        self.kernel._authorize(process, local.path(), "receive")
        return self.streams.peek(handle, max_size)

    def network_stream_receive(self, pid: int, handle: int, max_size: int | None = None) -> bytes | None:
        """Mathematics: authorize local `receive` and remove the bounded stream head, preserving `None` versus EOF `b''`."""

        process = self.kernel._process(pid)
        self._require_owner(self._stream_connection_owners, handle, pid, "stream connection")
        local, _, _, _ = self.streams.connection_binding(handle)
        self.kernel._authorize(process, local.path(), "receive")
        return self.streams.receive(handle, max_size)

    def network_stream_close(self, pid: int, handle: int, logical_time: int = 0) -> None:
        """Mathematics: authorize local `send` and peer `receive`, then apply one FIN transition."""

        process = self.kernel._process(pid)
        self._require_owner(self._stream_connection_owners, handle, pid, "stream connection")
        local, _, peer, _ = self.streams.connection_binding(handle)
        self.kernel._authorize(process, local.path(), "send")
        self.kernel._authorize(process, peer.path(), "receive")
        self.streams.close(handle, logical_time)

    def release_network_handles(self, pid: int) -> None:
        """Mathematics: garbage-collect all `h` with `Owner(h)=pid` when process lifetime reaches exact reaping."""

        for socket_id, owner in tuple(self._datagram_owners.items()):
            if self._network_fd_referenced("datagram", socket_id):
                continue
            if owner != pid and owner in self.kernel.processes:
                continue
            self.datagrams.close(socket_id)
            self._datagram_owners.pop(socket_id, None)
        for listener, owner in tuple(self._stream_listener_owners.items()):
            if self._network_fd_referenced("stream_listener", listener):
                continue
            if owner != pid and owner in self.kernel.processes:
                continue
            self.streams.destroy_listener(listener)
            self._stream_listener_owners.pop(listener, None)
        for connection, owner in tuple(self._stream_connection_owners.items()):
            if self._network_fd_referenced("stream_connection", connection):
                continue
            if owner != pid and owner in self.kernel.processes:
                continue
            if self.streams.has_connection(connection):
                self.streams.destroy_connection(connection)
            self._stream_connection_owners.pop(connection, None)

    def release_fd_transfers(self, transfers: Iterable[object]) -> None:
        """Mathematics: release each canceled transfer resource `D_t` iff no process or remaining transfer references its native handle."""

        for transfer in transfers:
            description = getattr(transfer, "description", None)
            if description is None or description.network_kind is None or description.network_handle is None:
                continue
            kind = str(description.network_kind)
            handle = int(description.network_handle)
            if self._network_fd_referenced(kind, handle):
                continue
            if kind == "datagram":
                try:
                    self.datagrams.close(handle)
                except DatagramError:
                    pass
                self._datagram_owners.pop(handle, None)
            elif kind == "stream_connection":
                if self.streams.has_connection(handle):
                    self.streams.destroy_connection(handle)
                self._stream_connection_owners.pop(handle, None)
            elif kind == "stream_listener":
                try:
                    record = next(item for item in self.streams.listeners() if int(item["handle"]) == handle)
                except (StopIteration, StreamError):
                    record = None
                if record is not None:
                    for pending in record["pending"]:
                        self._stream_connection_owners.pop(int(pending), None)
                    self.streams.destroy_listener(handle)
                self._stream_listener_owners.pop(handle, None)

    def _install_network_fd(self, pid: int, kind: str, handle: int, path: str) -> int:
        """Mathematics: allocate least fresh `fd≥3` and bind shared description `D=(path,kind,handle)` to process `pid`."""

        process = self.kernel._process(pid)
        fd = process.next_fd
        while fd in process.fds:
            fd += 1
        process.next_fd += 1
        process.next_fd = max(process.next_fd, fd + 1)
        process.fds[fd] = self.kernel._new_open_file(
            path,
            0,
            True,
            True,
            network_kind=kind,
            network_handle=handle,
        )
        return fd

    def _network_fd_referenced(self, kind: str, handle: int) -> bool:
        """Mathematics: test descriptor reachability `∃p,fd: fds_p[fd].(kind,handle)=(kind,handle)`."""

        return any(
            descriptor.network_kind == kind and descriptor.network_handle == handle
            for process in self.kernel.processes.values()
            for descriptor in process.fds.values()
        ) or any(
            descriptor.network_kind == kind and descriptor.network_handle == handle
            for descriptor in self.kernel.pending_fd_handles()
        )

    def network_receive(self, pid: int, destination: NetworkAddress, max_size: int | None = None) -> NetworkFrame | None:
        """Mathematics: authorize `receive(destination)` and dequeue `head(Q_destination)` without hidden blocking."""

        process = self.kernel._process(pid)
        self.kernel._authorize(process, destination.path(), "receive")
        return self.owned_network.receive(destination, max_size)

    def network_drain_to_e0(self, pid: int, namespace: str, interface: str, max_frames: int = 1) -> tuple[object, ...]:
        """Mathematics: authorize `receive(/net/n/i)` and commit `peek→E0.ingest→dequeue` for at most `m` frames."""

        process = self.kernel._process(pid)
        endpoint = NetworkAddress(namespace, interface)
        self.kernel._authorize(process, endpoint.path(), "receive")
        return OwnedLinkDriver(self.owned_network, endpoint, self.network).drain(max_frames)

    def run_command(self, argv: Iterable[str], pid: int | None = None) -> CommandResult:
        """Mathematics: evaluate a command as a pure dispatch over argv, returning `(status, stdout, stderr)`."""

        args = tuple(argv)
        process_id = self.init_pid if pid is None else pid
        if not args:
            return CommandResult(0)
        command, *rest = args
        try:
            if command == "pwd":
                return CommandResult(0, self.kernel.syscall(process_id, "getcwd") + "\n")
            if command == "cd":
                if len(rest) != 1:
                    return CommandResult(2, stderr="cd requires PATH\n")
                self.kernel.syscall(process_id, "chdir", path=rest[0])
                return CommandResult(0)
            if command == "ls":
                path = rest[0] if rest else "/"
                names = self.kernel.syscall(process_id, "listdir", path=path)
                return CommandResult(0, "\n".join(names) + ("\n" if names else ""))
            if command == "cat":
                chunks: list[bytes] = []
                for path in rest:
                    fd = self.kernel.syscall(process_id, "open", path=path, mode="r")
                    try:
                        chunks.append(self.kernel.syscall(process_id, "read", fd=fd, size=-1))
                    finally:
                        self.kernel.syscall(process_id, "close", fd=fd)
                try:
                    return CommandResult(0, b"".join(chunks).decode("utf-8"))
                except UnicodeDecodeError as exc:
                    return CommandResult(1, stderr=f"cat: binary or invalid UTF-8 input: {exc}\n")
            if command == "mkdir":
                for path in rest:
                    self.kernel.syscall(process_id, "mkdir", path=path)
                return CommandResult(0)
            if command == "mv":
                if len(rest) != 2:
                    return CommandResult(2, stderr="mv requires SOURCE DESTINATION\n")
                self.kernel.syscall(process_id, "rename", old_path=rest[0], new_path=rest[1])
                return CommandResult(0)
            if command == "rm":
                if not rest:
                    return CommandResult(2, stderr="rm requires PATH\n")
                for path in rest:
                    self.kernel.syscall(process_id, "unlink", path=path)
                return CommandResult(0)
            if command == "rmdir":
                if not rest:
                    return CommandResult(2, stderr="rmdir requires PATH\n")
                for path in rest:
                    self.kernel.syscall(process_id, "rmdir", path=path)
                return CommandResult(0)
            if command == "write":
                if len(rest) < 2:
                    return CommandResult(2, stderr="write requires PATH TEXT\n")
                path, text = rest[0], " ".join(rest[1:])
                fd = self.kernel.syscall(process_id, "open", path=path, mode="w", create=True)
                try:
                    self.kernel.syscall(process_id, "write", fd=fd, data=text.encode("utf-8"))
                finally:
                    self.kernel.syscall(process_id, "close", fd=fd)
                return CommandResult(0)
            if command == "ps":
                rows = self.kernel.process_table()
                return CommandResult(0, "\n".join(f"{row['pid']}\t{row['status']}\t{row['name']}" for row in rows) + "\n")
            if command == "send":
                if len(rest) < 2:
                    return CommandResult(2, stderr="send requires DESTINATION PAYLOAD\n")
                message_id = self.kernel.syscall(
                    process_id,
                    "send",
                    destination=rest[0],
                    payload={"text": " ".join(rest[1:])},
                )
                return CommandResult(0, message_id + "\n")
            if command == "recv":
                message = self.kernel.syscall(process_id, "receive")
                if message is None:
                    return CommandResult(1, stderr="would block\n")
                return CommandResult(0, repr(message.payload) + "\n")
            return CommandResult(127, stderr=f"unknown command: {command}\n")
        except (KernelError, KeyError) as exc:
            return CommandResult(1, stderr=f"{exc}\n")

    def run_script(self, script: str, pid: int | None = None) -> tuple[CommandResult, ...]:
        """Mathematics: execute the ordered command composition `R = (r_1, ..., r_n)` and preserve every result."""

        results: list[CommandResult] = []
        for line in script.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            results.append(self.run_command(shlex.split(stripped), pid))
        return tuple(results)

    def snapshot(self) -> dict[str, object]:
        """Mathematics: return the replay artifact `S(E) = snapshot(K) + init_pid`, preserving all deterministic state."""

        return {
            "init_pid": self.init_pid,
            "kernel": self.kernel.snapshot(),
            "network": self.network.snapshot(),
            "owned_network": self.owned_network.snapshot(),
            "datagrams": self.datagrams.snapshot(),
            "streams": self.streams.snapshot(),
            "datagram_owners": {str(handle): pid for handle, pid in sorted(self._datagram_owners.items())},
            "stream_listener_owners": {str(handle): pid for handle, pid in sorted(self._stream_listener_owners.items())},
            "stream_connection_owners": {str(handle): pid for handle, pid in sorted(self._stream_connection_owners.items())},
        }

    @classmethod
    def from_snapshot(cls, payload: dict[str, object]) -> "VirtualEnvironment":
        """Mathematics: reconstruct environment product `E = (K, init_pid)` from a validated kernel checkpoint."""

        kernel = VirtualKernel.from_snapshot(dict(payload["kernel"]))
        init_pid = int(payload["init_pid"])
        kernel._process(init_pid)
        kernel.init_pid = init_pid
        network_payload = payload.get("network")
        network = (
            HeadlessNetworkDevice(kernel.journal)
            if network_payload is None
            else HeadlessNetworkDevice.from_snapshot(dict(network_payload), journal=kernel.journal)
        )
        owned_payload = payload.get("owned_network", payload.get("fabric"))
        if owned_payload is None:
            owned_network = OwnedNetworkFabric(journal=kernel.journal)
            owned_network.create_namespace("root")
        else:
            owned_network = OwnedNetworkFabric.from_snapshot(dict(owned_payload), journal=kernel.journal)
        datagram_payload = payload.get("datagrams")
        datagrams = (
            OwnedDatagramStack(owned_network, journal=kernel.journal)
            if datagram_payload is None
            else OwnedDatagramStack.from_snapshot(dict(datagram_payload), owned_network, journal=kernel.journal)
        )
        stream_payload = payload.get("streams")
        streams = (
            OwnedStreamStack(owned_network, journal=kernel.journal)
            if stream_payload is None
            else OwnedStreamStack.from_snapshot(dict(stream_payload), owned_network, journal=kernel.journal)
        )
        datagram_owners = {int(handle): int(pid) for handle, pid in dict(payload.get("datagram_owners", {})).items()}
        listener_owners = {int(handle): int(pid) for handle, pid in dict(payload.get("stream_listener_owners", {})).items()}
        connection_owners = {int(handle): int(pid) for handle, pid in dict(payload.get("stream_connection_owners", {})).items()}
        datagram_handles = {int(item["socket_id"]) for item in datagrams.sockets()}
        listener_handles = {int(item["handle"]) for item in streams.listeners()}
        connection_handles = {int(item["handle"]) for item in streams.connections()}
        if not set(datagram_owners).issubset(datagram_handles):
            raise KernelError("checkpoint owns an unknown datagram handle")
        if not set(listener_owners).issubset(listener_handles):
            raise KernelError("checkpoint owns an unknown stream listener")
        if not set(connection_owners).issubset(connection_handles):
            raise KernelError("checkpoint owns an unknown stream connection")
        for handle, owner in (*datagram_owners.items(), *listener_owners.items(), *connection_owners.items()):
            if owner not in kernel.processes:
                raise KernelError(f"network handle owner does not exist: pid {owner}")
        return cls(
            kernel,
            init_pid,
            network,
            owned_network,
            datagrams,
            streams,
            datagram_owners,
            listener_owners,
            connection_owners,
        )

    @staticmethod
    def _require_owner(owners: dict[int, int], handle: int, pid: int, kind: str) -> None:
        """Mathematics: authorize handle use iff `owners[handle]=pid`; unknown or foreign handles are explicit failures."""

        owner = owners.get(int(handle))
        if owner is None:
            raise KernelError(f"unknown {kind}: {handle}")
        if owner != pid:
            raise KernelError(f"{kind} belongs to process {owner}, not {pid}")
