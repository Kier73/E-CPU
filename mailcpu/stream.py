"""Implement bounded byte-stream sockets and windowed connections over the network fabric."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from enum import Enum
import struct
from typing import Any

from .journal import EventJournal
from .owned_network import NetworkAddress, OwnedNetworkError, OwnedNetworkFabric


class StreamError(ValueError):
    """A stream endpoint, segment, sequence, or checkpoint violates its contract."""


class StreamState(str, Enum):
    """Finite native stream states exposed by the stack."""

    ESTABLISHED = "established"
    CLOSED = "closed"


STREAM_DATA = 0x01
STREAM_ACK = 0x02
STREAM_FIN = 0x04
_MAGIC = b"MCPS"
_VERSION = 1
_HEADER = struct.Struct(">4sBBQIIHHI")
_MAX_SEQUENCE = (1 << 32) - 1
_EPHEMERAL_START = 32_768
_EPHEMERAL_END = 60_000


@dataclass(frozen=True)
class StreamSegment:
    """A typed stream segment carrying connection, sequence, acknowledgement, and port identity."""

    connection_id: int
    flags: int
    sequence: int
    acknowledgement: int
    source_port: int
    destination_port: int
    payload: bytes

    def to_bytes(self) -> bytes:
        """Mathematics: encode `s=(c,f,q,a,p_s,p_d,b)` as a fixed header plus exact body `b`."""

        if self.connection_id <= 0 or self.connection_id > (1 << 64) - 1:
            raise StreamError("stream connection identity is out of range")
        if self.flags & ~(STREAM_DATA | STREAM_ACK | STREAM_FIN):
            raise StreamError("unknown stream flags")
        if not 0 <= self.sequence <= _MAX_SEQUENCE or not 0 <= self.acknowledgement <= _MAX_SEQUENCE:
            raise StreamError("stream sequence is out of range")
        _validate_port(self.source_port)
        _validate_port(self.destination_port)
        if not isinstance(self.payload, (bytes, bytearray, memoryview)):
            raise StreamError("stream segment payload must be bytes-like")
        body = bytes(self.payload)
        if not self.flags & STREAM_DATA and body:
            raise StreamError("non-data stream segment cannot carry payload")
        return _HEADER.pack(
            _MAGIC,
            _VERSION,
            self.flags,
            self.connection_id,
            self.sequence,
            self.acknowledgement,
            self.source_port,
            self.destination_port,
            len(body),
        ) + body

    @classmethod
    def from_bytes(cls, wire: bytes) -> "StreamSegment":
        """Mathematics: invert `to_bytes` exactly when magic/version/length/flag invariants hold."""

        if not isinstance(wire, (bytes, bytearray, memoryview)):
            raise StreamError("stream wire payload must be bytes-like")
        data = bytes(wire)
        if len(data) < _HEADER.size:
            raise StreamError("stream segment is truncated")
        magic, version, flags, connection_id, sequence, acknowledgement, source_port, destination_port, length = _HEADER.unpack(
            data[: _HEADER.size]
        )
        if magic != _MAGIC or version != _VERSION:
            raise StreamError("unsupported stream segment")
        body = data[_HEADER.size :]
        if len(body) != length:
            raise StreamError("stream segment length does not match header")
        segment = cls(
            connection_id,
            flags,
            sequence,
            acknowledgement,
            source_port,
            destination_port,
            body,
        )
        segment.to_bytes()
        return segment


def encode_stream_segment(
    connection_id: int,
    flags: int,
    sequence: int,
    acknowledgement: int,
    source_port: int,
    destination_port: int,
    payload: bytes = b"",
) -> bytes:
    """Mathematics: expose the bijective constructor `E(c,f,q,a,p_s,p_d,b)=StreamSegment(...).to_bytes()`."""

    return StreamSegment(
        connection_id,
        flags,
        sequence,
        acknowledgement,
        source_port,
        destination_port,
        payload,
    ).to_bytes()


def decode_stream_segment(wire: bytes) -> StreamSegment:
    """Mathematics: expose inverse `D(E(x))=x` for valid stream segment bytes and explicit rejection otherwise."""

    return StreamSegment.from_bytes(wire)


def _validate_port(port: int) -> int:
    """Mathematics: accept port `p` iff `1≤p≤65535`."""

    if not 1 <= int(port) <= 65_535:
        raise StreamError("stream port must be between 1 and 65535")
    return int(port)


@dataclass
class _Listener:
    """Bound listener and its bounded queue of accepted connection handles."""

    handle: int
    address: NetworkAddress
    port: int
    backlog: int
    pending: deque[int] = field(default_factory=deque)


@dataclass
class _Connection:
    """Per-direction stream state with cumulative sequence and byte-buffer invariants."""

    handle: int
    wire_id: int
    local: NetworkAddress
    local_port: int
    peer: NetworkAddress
    peer_port: int
    role: str
    state: StreamState = StreamState.ESTABLISHED
    send_next: int = 0
    acknowledged: int = 0
    receive_next: int = 0
    pending: dict[int, int] = field(default_factory=dict)
    receive_buffer: bytearray = field(default_factory=bytearray)
    eof: bool = False


class OwnedStreamStack:
    """A checkpointable native stream/listener layer over `OwnedNetworkFabric`."""

    def __init__(
        self,
        fabric: OwnedNetworkFabric,
        journal: EventJournal | None = None,
        window: int = 65_536,
        default_backlog: int = 16,
    ) -> None:
        """Mathematics: initialize listener relation `L`, connection map `C`, receive buffers `R`, and handles `h=1`."""

        if window <= 0 or default_backlog <= 0:
            raise ValueError("stream window and default_backlog must be positive")
        self.fabric = fabric
        self.journal = journal or fabric.journal
        self.window = int(window)
        self.default_backlog = int(default_backlog)
        self._listeners: dict[int, _Listener] = {}
        self._listener_bindings: dict[tuple[NetworkAddress, int], int] = {}
        self._connections: dict[int, _Connection] = {}
        self._wire_index: dict[tuple[NetworkAddress, int, int], int] = {}
        self._next_handle = 1
        self._next_wire_id = 1
        self._next_ephemeral = _EPHEMERAL_START

    def listen(self, address: NetworkAddress, port: int, backlog: int | None = None) -> int:
        """Mathematics: add listener `L[(address,port)]` iff the binding is free and `0<backlog≤window`."""

        self.fabric._require_endpoint(address)
        checked_port = _validate_port(port)
        if (address, checked_port) in self._listener_bindings:
            raise StreamError("stream listener binding already exists")
        limit = self.default_backlog if backlog is None else int(backlog)
        if limit <= 0:
            raise StreamError("stream backlog must be positive")
        handle = self._allocate_handle()
        self._listeners[handle] = _Listener(handle, address, checked_port, limit)
        self._listener_bindings[(address, checked_port)] = handle
        self.journal.append(
            "network.stream.listen",
            {"handle": handle, "address": address.to_dict(), "port": checked_port, "backlog": limit},
        )
        return handle

    def listener_binding(self, handle: int) -> tuple[NetworkAddress, int]:
        """Mathematics: project listener handle `h` to `(address_h,port_h)` or reject `h∉dom(L)`."""

        try:
            listener = self._listeners[int(handle)]
        except KeyError as exc:
            raise StreamError(f"unknown stream listener: {handle}") from exc
        return listener.address, listener.port

    def connect(
        self,
        source: NetworkAddress,
        source_port: int,
        destination: NetworkAddress,
        destination_port: int,
    ) -> int:
        """Mathematics: establish a bounded pair `(client,server)` iff destination listener exists and backlog has space."""

        self.fabric._require_endpoint(source)
        self.fabric._require_endpoint(destination)
        checked_destination_port = _validate_port(destination_port)
        listener_id = self._listener_bindings.get((destination, checked_destination_port))
        if listener_id is None:
            raise StreamError("no stream listener at destination")
        listener = self._listeners[listener_id]
        if len(listener.pending) >= listener.backlog:
            raise StreamError("stream listener backlog is full")
        selected_source_port = self._allocate_source_port(source, source_port)
        wire_id = self._next_wire_id
        self._next_wire_id += 1
        client_handle = self._allocate_handle()
        server_handle = self._allocate_handle()
        client = _Connection(
            client_handle,
            wire_id,
            source,
            selected_source_port,
            destination,
            checked_destination_port,
            "client",
        )
        server = _Connection(
            server_handle,
            wire_id,
            destination,
            checked_destination_port,
            source,
            selected_source_port,
            "server",
        )
        self._connections[client_handle] = client
        self._connections[server_handle] = server
        self._wire_index[(client.local, client.local_port, wire_id)] = client_handle
        self._wire_index[(server.local, server.local_port, wire_id)] = server_handle
        listener.pending.append(server_handle)
        self.journal.append(
            "network.stream.connect",
            {
                "wire_id": wire_id,
                "client_handle": client_handle,
                "server_handle": server_handle,
                "source": source.to_dict(),
                "destination": destination.to_dict(),
                "source_port": selected_source_port,
                "destination_port": checked_destination_port,
                "state": StreamState.ESTABLISHED.value,
            },
        )
        return client_handle

    def accept(self, listener_handle: int) -> int | None:
        """Mathematics: consume `head(pending(listener))` or return `⊥` without blocking or fabric mutation."""

        listener = self._listener(listener_handle)
        if not listener.pending:
            return None
        connection_handle = listener.pending.popleft()
        self.journal.append(
            "network.stream.accept",
            {"listener": listener_handle, "connection": connection_handle},
        )
        return connection_handle

    def connection_binding(self, handle: int) -> tuple[NetworkAddress, int, NetworkAddress, int]:
        """Mathematics: project connection `c` to `(local,local_port,peer,peer_port)` or reject unknown `c`."""

        connection = self._connection(handle)
        return connection.local, connection.local_port, connection.peer, connection.peer_port

    def has_connection(self, handle: int) -> bool:
        """Mathematics: evaluate membership predicate `handle∈dom(C)` without creating or mutating connection state."""

        return int(handle) in self._connections

    def listener_ready(self, handle: int) -> bool:
        """Mathematics: evaluate `readable(l) ⇔ |pending(l)|>0` without consuming the accept queue."""

        return bool(self._listener(handle).pending)

    def connection_readiness(self, handle: int) -> tuple[bool, bool, bool]:
        """Mathematics: return `(in,out,hup)` where `in := |R_c|>0 ∨ eof`, `out := state=ESTABLISHED ∧ |P_c|<W ∧ C_peer>0`, and `hup := eof ∨ state=CLOSED`."""

        connection = self._connection(handle)
        self._pump_address(connection.local)
        peer = self._peer_connection(connection)
        readable = bool(connection.receive_buffer) or connection.eof
        writable = (
            connection.state is StreamState.ESTABLISHED
            and sum(connection.pending.values()) < self.window
            and len(peer.receive_buffer) < self.window
            and self.fabric.queue_available(connection.peer) > 0
        )
        hangup = connection.eof or connection.state is StreamState.CLOSED
        return readable, writable, hangup

    def send(self, handle: int, payload: bytes, logical_time: int) -> int:
        """Mathematics: commit the maximal prefix `b[:k]` satisfying `k≤W-Σ|pending|` and `ceil(k/chunk)≤C_peer`, segment it, and return `k`; fail only when `k=0`."""

        connection = self._connection(handle)
        self._pump_address(connection.local)
        if connection.state is not StreamState.ESTABLISHED:
            raise StreamError("closed stream cannot send")
        if not isinstance(payload, (bytes, bytearray, memoryview)):
            raise StreamError("stream payload must be bytes-like")
        body = bytes(payload)
        if logical_time < 0:
            raise StreamError("logical_time must be non-negative")
        if not body:
            return 0
        outstanding = sum(connection.pending.values())
        available_window = self.window - outstanding
        if available_window <= 0:
            raise StreamError("stream send window is full")
        route_mtu = self.fabric.route_mtu(connection.local, connection.peer)
        chunk_size = route_mtu - _HEADER.size
        if chunk_size <= 0:
            raise StreamError("route MTU cannot carry a stream header")
        available_queue = self.fabric.queue_available(connection.peer)
        if available_queue <= 0:
            raise StreamError("stream destination queue cannot accept all segments")
        peer = self._peer_connection(connection)
        available_receiver = self.window - len(peer.receive_buffer)
        if available_receiver <= 0:
            raise StreamError("stream receiver window is full")
        body = body[: min(len(body), available_window, available_receiver, available_queue * chunk_size)]
        chunks = [body[index : index + chunk_size] for index in range(0, len(body), chunk_size)]
        next_sequence = connection.send_next
        if next_sequence + len(body) > _MAX_SEQUENCE:
            raise StreamError("stream sequence space exhausted")
        for chunk in chunks:
            segment = StreamSegment(
                connection.wire_id,
                STREAM_DATA,
                next_sequence,
                connection.receive_next,
                connection.local_port,
                connection.peer_port,
                chunk,
            )
            self.fabric.send_routed(connection.local, connection.peer, segment.to_bytes(), logical_time)
            connection.pending[next_sequence] = len(chunk)
            next_sequence += len(chunk)
        connection.send_next = next_sequence
        self.journal.append(
            "network.stream.send",
            {"handle": handle, "wire_id": connection.wire_id, "size": len(body), "logical_time": logical_time},
        )
        return len(body)

    def peek(self, handle: int, max_size: int | None = None) -> bytes | None:
        """Mathematics: pump accepted segments into `R_c`, then return `head(R_c[0:max_size])` without removal."""

        if max_size is not None and max_size < 0:
            raise StreamError("max_size must be non-negative")
        connection = self._connection(handle)
        self._pump_address(connection.local)
        if not connection.receive_buffer:
            return b"" if connection.eof else None
        limit = len(connection.receive_buffer) if max_size is None else min(max_size, len(connection.receive_buffer))
        return bytes(connection.receive_buffer[:limit])

    def receive(self, handle: int, max_size: int | None = None) -> bytes | None:
        """Mathematics: remove exactly the bytes projected by `peek(c,max_size)` from `R_c`, preserving EOF `b''`."""

        data = self.peek(handle, max_size)
        if data is None or data == b"":
            return data
        connection = self._connection(handle)
        del connection.receive_buffer[: len(data)]
        self.journal.append(
            "network.stream.receive",
            {"handle": handle, "wire_id": connection.wire_id, "size": len(data)},
        )
        return data

    def close(self, handle: int, logical_time: int = 0) -> None:
        """Mathematics: emit one FIN segment and transition `ESTABLISHED→CLOSED` exactly once."""

        connection = self._connection(handle)
        if connection.state is StreamState.CLOSED:
            return
        segment = StreamSegment(
            connection.wire_id,
            STREAM_FIN,
            connection.send_next,
            connection.receive_next,
            connection.local_port,
            connection.peer_port,
            b"",
        )
        self.fabric.send_routed(connection.local, connection.peer, segment.to_bytes(), logical_time)
        connection.state = StreamState.CLOSED
        self.journal.append("network.stream.close", {"handle": handle, "wire_id": connection.wire_id})

    def destroy_listener(self, handle: int) -> None:
        """Mathematics: remove listener `l` and all still-pending accepted connections from `L` and `C`."""

        listener = self._listener(handle)
        for connection_handle in tuple(listener.pending):
            self.destroy_connection(connection_handle)
        self._listener_bindings.pop((listener.address, listener.port), None)
        self._listeners.pop(listener.handle, None)
        self.journal.append("network.stream.listener_destroy", {"handle": listener.handle})

    def destroy_connection(self, handle: int) -> None:
        """Mathematics: remove connection `c` and socket index `I[(local,port,wire)]`."""

        connection = self._connection(handle)
        for listener in self._listeners.values():
            listener.pending = deque(value for value in listener.pending if value != handle)
        self._wire_index.pop((connection.local, connection.local_port, connection.wire_id), None)
        self._connections.pop(connection.handle, None)
        self.journal.append("network.stream.connection_destroy", {"handle": connection.handle, "wire_id": connection.wire_id})

    def listeners(self) -> tuple[dict[str, Any], ...]:
        """Mathematics: expose listener relation `L` with pending cardinalities in handle order."""

        return tuple(
            {
                "handle": listener.handle,
                "address": listener.address.to_dict(),
                "port": listener.port,
                "backlog": listener.backlog,
                "pending": list(listener.pending),
            }
            for listener in sorted(self._listeners.values(), key=lambda item: item.handle)
        )

    def connections(self) -> tuple[dict[str, Any], ...]:
        """Mathematics: expose connection state `C` with sequence, acknowledgement, and buffered-byte invariants."""

        return tuple(
            {
                "handle": connection.handle,
                "wire_id": connection.wire_id,
                "local": connection.local.to_dict(),
                "local_port": connection.local_port,
                "peer": connection.peer.to_dict(),
                "peer_port": connection.peer_port,
                "role": connection.role,
                "state": connection.state.value,
                "send_next": connection.send_next,
                "acknowledged": connection.acknowledged,
                "receive_next": connection.receive_next,
                "pending": [[key, value] for key, value in sorted(connection.pending.items())],
                "receive_hex": bytes(connection.receive_buffer).hex(),
                "eof": connection.eof,
            }
            for connection in sorted(self._connections.values(), key=lambda item: item.handle)
        )

    def snapshot(self) -> dict[str, Any]:
        """Mathematics: serialize full stream state `S(L,C,R,k,J)` for exact continuation."""

        return {
            "window": self.window,
            "default_backlog": self.default_backlog,
            "next_handle": self._next_handle,
            "next_wire_id": self._next_wire_id,
            "next_ephemeral": self._next_ephemeral,
            "listeners": list(self.listeners()),
            "connections": list(self.connections()),
            "journal": self.journal.snapshot(),
        }

    @classmethod
    def from_snapshot(
        cls,
        payload: dict[str, Any],
        fabric: OwnedNetworkFabric,
        journal: EventJournal | None = None,
    ) -> "OwnedStreamStack":
        """Mathematics: reconstruct listeners/connections and revalidate map closure, sequence bounds, and journal identity."""

        saved_journal = payload.get("journal", [])
        shared_journal = journal or EventJournal.from_snapshot(list(saved_journal))
        if journal is not None and shared_journal.snapshot() != saved_journal:
            raise StreamError("stream journal differs from environment journal")
        stack = cls(fabric, shared_journal, int(payload["window"]), int(payload["default_backlog"]))
        for raw in payload.get("listeners", ()):
            item = dict(raw)
            handle = int(item["handle"])
            address = NetworkAddress.from_dict(dict(item["address"]))
            port = _validate_port(int(item["port"]))
            backlog = int(item["backlog"])
            if handle <= 0 or backlog <= 0 or handle in stack._listeners or (address, port) in stack._listener_bindings:
                raise StreamError("invalid or duplicate listener checkpoint")
            fabric._require_endpoint(address)
            pending = deque(int(value) for value in item.get("pending", ()))
            stack._listeners[handle] = _Listener(handle, address, port, backlog, pending)
            stack._listener_bindings[(address, port)] = handle
        for raw in payload.get("connections", ()):
            item = dict(raw)
            handle = int(item["handle"])
            wire_id = int(item["wire_id"])
            local = NetworkAddress.from_dict(dict(item["local"]))
            peer = NetworkAddress.from_dict(dict(item["peer"]))
            local_port = _validate_port(int(item["local_port"]))
            peer_port = _validate_port(int(item["peer_port"]))
            if handle <= 0 or wire_id <= 0 or handle in stack._connections:
                raise StreamError("invalid or duplicate connection checkpoint")
            fabric._require_endpoint(local)
            fabric._require_endpoint(peer)
            pending = {int(key): int(value) for key, value in item.get("pending", ())}
            if any(key < 0 or value < 0 or key + value > _MAX_SEQUENCE for key, value in pending.items()):
                raise StreamError("invalid pending sequence checkpoint")
            try:
                receive_buffer = bytearray.fromhex(str(item.get("receive_hex", "")))
            except ValueError as exc:
                raise StreamError("invalid stream receive buffer checkpoint") from exc
            connection = _Connection(
                handle,
                wire_id,
                local,
                local_port,
                peer,
                peer_port,
                str(item["role"]),
                StreamState(item["state"]),
                int(item["send_next"]),
                int(item["acknowledged"]),
                int(item["receive_next"]),
                pending,
                receive_buffer,
                bool(item.get("eof", False)),
            )
            if not 0 <= connection.send_next <= _MAX_SEQUENCE or not 0 <= connection.acknowledged <= connection.send_next:
                raise StreamError("invalid stream send sequence checkpoint")
            if not 0 <= connection.receive_next <= _MAX_SEQUENCE:
                raise StreamError("invalid stream receive sequence checkpoint")
            key = (local, local_port, wire_id)
            if key in stack._wire_index:
                raise StreamError("duplicate stream wire endpoint checkpoint")
            stack._connections[handle] = connection
            stack._wire_index[key] = handle
        connection_handles = set(stack._connections)
        for listener in stack._listeners.values():
            if any(handle not in connection_handles for handle in listener.pending):
                raise StreamError("listener pending queue references missing connection")
        next_handle = int(payload["next_handle"])
        next_wire_id = int(payload["next_wire_id"])
        next_ephemeral = int(payload["next_ephemeral"])
        if next_handle <= 0 or (stack._connections or stack._listeners) and next_handle <= max(
            (*stack._connections, *stack._listeners)
        ):
            raise StreamError("invalid next stream handle")
        if next_wire_id <= 0 or (stack._connections and next_wire_id <= max(item.wire_id for item in stack._connections.values())):
            raise StreamError("invalid next stream wire identity")
        if not _EPHEMERAL_START <= next_ephemeral <= _EPHEMERAL_END:
            raise StreamError("invalid next ephemeral port")
        stack._next_handle = next_handle
        stack._next_wire_id = next_wire_id
        stack._next_ephemeral = next_ephemeral
        return stack

    def _listener(self, handle: int) -> _Listener:
        """Mathematics: resolve listener `l∈dom(L)` without creating implicit state."""

        try:
            return self._listeners[int(handle)]
        except KeyError as exc:
            raise StreamError(f"unknown stream listener: {handle}") from exc

    def _connection(self, handle: int) -> _Connection:
        """Mathematics: resolve connection `c∈dom(C)` without creating implicit state."""

        try:
            return self._connections[int(handle)]
        except KeyError as exc:
            raise StreamError(f"unknown stream connection: {handle}") from exc

    def _allocate_handle(self) -> int:
        """Mathematics: allocate fresh handle `h_k=k`, then advance `k:=k+1` without collision."""

        handle = self._next_handle
        self._next_handle += 1
        return handle

    def _allocate_source_port(self, address: NetworkAddress, requested: int) -> int:
        """Mathematics: choose requested `p` or the first free `p∈[32768,60000]` under deterministic cyclic search."""

        if requested:
            port = _validate_port(requested)
            if (address, port) in self._listener_bindings or any(
                connection.local == address and connection.local_port == port
                for connection in self._connections.values()
            ):
                raise StreamError("stream source port is already in use")
            return port
        span = _EPHEMERAL_END - _EPHEMERAL_START + 1
        for offset in range(span):
            port = _EPHEMERAL_START + ((self._next_ephemeral - _EPHEMERAL_START + offset) % span)
            if (address, port) not in self._listener_bindings and not any(
                connection.local == address and connection.local_port == port
                for connection in self._connections.values()
            ):
                self._next_ephemeral = _EPHEMERAL_START + ((port - _EPHEMERAL_START + 1) % span)
                return port
        raise StreamError("ephemeral stream port range is exhausted")

    def _pump_address(self, address: NetworkAddress) -> None:
        """Mathematics: consume only accepted segments at `address`, applying `ACK`, `DATA`, and `FIN` transitions atomically."""

        while True:
            frame = self.fabric.peek(address)
            if frame is None:
                return
            segment = StreamSegment.from_bytes(frame.payload)
            handle = self._wire_index.get((address, segment.destination_port, segment.connection_id))
            if handle is None:
                dropped = self.fabric.receive(address)
                if dropped is None or dropped.frame_id != frame.frame_id:
                    raise StreamError("network frame changed during orphan stream discard")
                self.journal.append(
                    "network.stream.drop",
                    {
                        "frame_id": frame.frame_id,
                        "destination": address.to_dict(),
                        "connection_id": segment.connection_id,
                        "destination_port": segment.destination_port,
                        "reason": "unknown-connection",
                    },
                )
                continue
            connection = self._connection(handle)
            if frame.source != connection.peer or segment.source_port != connection.peer_port:
                raise StreamError("stream segment peer identity mismatch")
            if segment.flags == STREAM_ACK:
                self._acknowledge(connection, segment.acknowledgement)
                received = self.fabric.receive(address)
                if received is None or received.frame_id != frame.frame_id:
                    raise StreamError("stream ACK changed during dequeue")
                self.journal.append(
                    "network.stream.ack",
                    {"handle": handle, "acknowledgement": segment.acknowledgement},
                )
                continue
            if segment.flags == STREAM_FIN:
                next_ack = connection.receive_next
                acknowledgement = StreamSegment(
                    connection.wire_id,
                    STREAM_ACK,
                    0,
                    next_ack,
                    connection.local_port,
                    connection.peer_port,
                    b"",
                )
                self.fabric.send_routed(connection.local, connection.peer, acknowledgement.to_bytes(), frame.logical_time)
                received = self.fabric.receive(address)
                if received is None or received.frame_id != frame.frame_id:
                    raise StreamError("stream FIN changed during dequeue")
                connection.eof = True
                connection.state = StreamState.CLOSED
                self.journal.append("network.stream.fin", {"handle": handle, "wire_id": connection.wire_id})
                continue
            if segment.flags != STREAM_DATA:
                raise StreamError("unsupported stream flag combination")
            if segment.sequence != connection.receive_next:
                raise StreamError("out-of-order stream segment")
            if len(connection.receive_buffer) + len(segment.payload) > self.window:
                raise StreamError("stream receiver window is full")
            next_receive = connection.receive_next + len(segment.payload)
            if next_receive > _MAX_SEQUENCE:
                raise StreamError("stream receive sequence space exhausted")
            acknowledgement = StreamSegment(
                connection.wire_id,
                STREAM_ACK,
                0,
                next_receive,
                connection.local_port,
                connection.peer_port,
                b"",
            )
            self.fabric.send_routed(connection.local, connection.peer, acknowledgement.to_bytes(), frame.logical_time)
            received = self.fabric.receive(address)
            if received is None or received.frame_id != frame.frame_id:
                raise StreamError("stream data changed during dequeue")
            connection.receive_buffer.extend(segment.payload)
            connection.receive_next = next_receive
            self.journal.append(
                "network.stream.data",
                {"handle": handle, "sequence": segment.sequence, "size": len(segment.payload)},
            )

    def _peer_connection(self, connection: _Connection) -> _Connection:
        r"""Mathematics: resolve the unique peer `C[(peer, peer_port, wire_id)]` required for receiver-credit accounting."""

        peer_handle = self._wire_index.get((connection.peer, connection.peer_port, connection.wire_id))
        if peer_handle is None:
            raise StreamError("stream peer connection is missing")
        return self._connection(peer_handle)

    def _acknowledge(self, connection: _Connection, acknowledgement: int) -> None:
        """Mathematics: advance cumulative ACK `A:=ack` only when `old_A≤ack≤send_next`, removing `q+len(q)≤ack`."""

        if acknowledgement < connection.acknowledged or acknowledgement > connection.send_next:
            raise StreamError("invalid cumulative acknowledgement")
        for sequence, size in tuple(connection.pending.items()):
            if sequence + size <= acknowledgement:
                del connection.pending[sequence]
        connection.acknowledged = acknowledgement
