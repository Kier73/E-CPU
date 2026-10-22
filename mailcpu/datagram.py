"""Provide typed datagram sockets and port demultiplexing over the network fabric."""

from __future__ import annotations

from collections import deque
import struct
from dataclasses import dataclass, field
from typing import Any

from .evidence import EvidenceTier, with_evidence_tier
from .journal import EventJournal
from .owned_network import NetworkAddress, NetworkFrame, OwnedNetworkError, OwnedNetworkFabric


class DatagramError(ValueError):
    """A typed datagram or socket state violates the MailCPU protocol contract."""


_MAGIC = b"MCPD"
_VERSION = 1
_HEADER = struct.Struct(">4sBBHHI")
_MAX_PORT = 65_535


def _validate_port(port: int) -> int:
    """Mathematics: accept port `p` exactly when `1≤p≤65535`."""

    if not 1 <= int(port) <= _MAX_PORT:
        raise DatagramError("port must be between 1 and 65535")
    return int(port)


def encode_datagram(source_port: int, destination_port: int, payload: bytes) -> bytes:
    """Mathematics: encode `d=(p_s,p_d,b)` as `MCPD || v || flags || p_s || p_d || |b| || b` injectively."""

    source = _validate_port(source_port)
    destination = _validate_port(destination_port)
    if not isinstance(payload, (bytes, bytearray, memoryview)):
        raise DatagramError("datagram payload must be bytes-like")
    body = bytes(payload)
    return _HEADER.pack(_MAGIC, _VERSION, 0, source, destination, len(body)) + body


def decode_datagram(payload: bytes) -> tuple[int, int, bytes]:
    """Mathematics: invert `encode_datagram` only when `len(payload)=header+declared_length` and header invariants hold."""

    if not isinstance(payload, (bytes, bytearray, memoryview)):
        raise DatagramError("datagram wire payload must be bytes-like")
    wire = bytes(payload)
    if len(wire) < _HEADER.size:
        raise DatagramError("datagram envelope is truncated")
    magic, version, flags, source_port, destination_port, size = _HEADER.unpack(wire[: _HEADER.size])
    if magic != _MAGIC or version != _VERSION or flags != 0:
        raise DatagramError("unsupported datagram envelope")
    _validate_port(source_port)
    _validate_port(destination_port)
    body = wire[_HEADER.size :]
    if len(body) != size:
        raise DatagramError("datagram length does not match envelope")
    return source_port, destination_port, body


@dataclass(frozen=True)
class NetworkDatagram:
    """A decoded datagram projected from one received owned frame."""

    frame_id: int
    source: NetworkAddress
    destination: NetworkAddress
    source_port: int
    destination_port: int
    payload: bytes
    logical_time: int
    route: tuple[NetworkAddress, ...]

    def to_dict(self) -> dict[str, Any]:
        """Mathematics: serialize `d` with binary payload `b:=hex(payload)` and explicit route `r`."""

        return with_evidence_tier(
            {
                "frame_id": self.frame_id,
                "source": self.source.to_dict(),
                "destination": self.destination.to_dict(),
                "source_port": self.source_port,
                "destination_port": self.destination_port,
                "payload_hex": self.payload.hex(),
                "logical_time": self.logical_time,
                "route": [address.to_dict() for address in self.route],
            },
            EvidenceTier.E1,
        )

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "NetworkDatagram":
        """Mathematics: reconstruct `d` from a checkpoint and reapply all scalar, byte, and route invariants."""

        try:
            body = bytes.fromhex(str(payload["payload_hex"]))
            route = tuple(NetworkAddress.from_dict(dict(item)) for item in payload["route"])
        except (KeyError, TypeError, ValueError) as exc:
            raise DatagramError("invalid datagram checkpoint record") from exc
        source = NetworkAddress.from_dict(dict(payload["source"]))
        destination = NetworkAddress.from_dict(dict(payload["destination"]))
        if not route or route[0] != source or route[-1] != destination:
            raise DatagramError("datagram route endpoints do not match addresses")
        frame_id = int(payload["frame_id"])
        logical_time = int(payload["logical_time"])
        if frame_id <= 0 or logical_time < 0:
            raise DatagramError("invalid datagram frame identity or logical time")
        return cls(
            frame_id,
            source,
            destination,
            _validate_port(int(payload["source_port"])),
            _validate_port(int(payload["destination_port"])),
            body,
            logical_time,
            route,
        )


@dataclass
class _Socket:
    """Bound socket state: address/port identity, bounded inbox, and queue ownership."""

    socket_id: int
    address: NetworkAddress
    port: int
    queue_limit: int
    inbox: deque[NetworkDatagram] = field(default_factory=deque)


class OwnedDatagramStack:
    """Port-binding and datagram-demultiplexing layer over `OwnedNetworkFabric`."""

    def __init__(
        self,
        fabric: OwnedNetworkFabric,
        journal: EventJournal | None = None,
        default_queue_limit: int = 256,
    ) -> None:
        """Mathematics: initialize binding relation `B`, socket queues `Q`, and monotone socket identity `k=1`."""

        if default_queue_limit <= 0:
            raise ValueError("default_queue_limit must be positive")
        self.fabric = fabric
        self.journal = journal or fabric.journal
        self.default_queue_limit = default_queue_limit
        self._sockets: dict[int, _Socket] = {}
        self._bindings: dict[tuple[NetworkAddress, int], int] = {}
        self._next_socket_id = 1

    def bind(self, address: NetworkAddress, port: int, queue_limit: int | None = None) -> int:
        """Mathematics: add binding `B[(address,port)] = s` iff endpoint exists, port is free, and `0<|Q_s|≤limit`."""

        self.fabric._require_endpoint(address)
        checked_port = _validate_port(port)
        if (address, checked_port) in self._bindings:
            raise DatagramError(f"address already bound: {address.path()}:{checked_port}")
        limit = self.default_queue_limit if queue_limit is None else int(queue_limit)
        if limit <= 0:
            raise DatagramError("socket queue_limit must be positive")
        socket_id = self._next_socket_id
        self._next_socket_id += 1
        self._sockets[socket_id] = _Socket(socket_id, address, checked_port, limit)
        self._bindings[(address, checked_port)] = socket_id
        self.journal.append(
            "network.datagram.bind",
            {"socket_id": socket_id, "address": address.to_dict(), "port": checked_port, "queue_limit": limit},
        )
        return socket_id

    def binding(self, socket_id: int) -> tuple[NetworkAddress, int]:
        """Mathematics: project socket identity `s` to its immutable binding `(address_s,port_s)` or reject unknown `s`."""

        try:
            socket = self._sockets[int(socket_id)]
        except KeyError as exc:
            raise DatagramError(f"unknown socket: {socket_id}") from exc
        return socket.address, socket.port

    def send(
        self,
        socket_id: int,
        destination: NetworkAddress,
        destination_port: int,
        payload: bytes,
        logical_time: int,
        routed: bool = True,
    ) -> int:
        """Mathematics: construct envelope `e=encode(p_s,p_d,b)` and apply direct or routed fabric transition `F(e)`."""

        socket = self._socket(socket_id)
        wire = encode_datagram(socket.port, destination_port, payload)
        if routed:
            return self.fabric.send_routed(socket.address, destination, wire, logical_time)
        return self.fabric.send(socket.address, destination, wire, logical_time)

    def peek(self, socket_id: int, max_size: int | None = None) -> NetworkDatagram | None:
        """Mathematics: return `head(Q_s)` after deterministic demultiplexing, without removing the socket datagram."""

        if max_size is not None and max_size < 0:
            raise DatagramError("max_size must be non-negative")
        socket = self._socket(socket_id)
        self._pump_until(socket, max_size)
        if not socket.inbox:
            return None
        datagram = socket.inbox[0]
        if max_size is not None and len(datagram.payload) > max_size:
            raise DatagramError("socket receive buffer is smaller than queued datagram")
        return datagram

    def receive(self, socket_id: int, max_size: int | None = None) -> NetworkDatagram | None:
        """Mathematics: apply FIFO transition `Q_s := tail(Q_s)` after `_pump_until`, preserving max-size atomicity."""

        datagram = self.peek(socket_id, max_size)
        if datagram is None:
            return None
        socket = self._socket(socket_id)
        received = socket.inbox.popleft()
        if received != datagram:
            raise DatagramError("socket inbox changed during receive")
        self.journal.append("network.datagram.receive", {"datagram": datagram.to_dict()})
        return datagram

    def ready(self, socket_id: int) -> bool:
        """Mathematics: evaluate `readable(s) ⇔ |Q_s|>0` after deterministic wire demultiplexing, without dequeuing `Q_s`."""

        socket = self._socket(socket_id)
        self._pump_until(socket, None)
        return bool(socket.inbox)

    def close(self, socket_id: int) -> None:
        """Mathematics: remove binding `B[(address,port)]` and socket queue `Q_s` exactly once."""

        socket = self._socket(socket_id)
        self._bindings.pop((socket.address, socket.port), None)
        self._sockets.pop(socket.socket_id, None)
        self.journal.append(
            "network.datagram.close",
            {"socket_id": socket.socket_id, "address": socket.address.to_dict(), "port": socket.port},
        )

    def sockets(self) -> tuple[dict[str, Any], ...]:
        """Mathematics: project all socket bindings and queue cardinalities in ascending socket identity order."""

        return tuple(
            {
                "socket_id": socket.socket_id,
                "address": socket.address.to_dict(),
                "port": socket.port,
                "queue_limit": socket.queue_limit,
                "queue_length": len(socket.inbox),
            }
            for socket in sorted(self._sockets.values(), key=lambda item: item.socket_id)
        )

    def snapshot(self) -> dict[str, Any]:
        """Mathematics: serialize complete socket state `S(B,Q,k,J)` with every queued datagram."""

        return {
            "default_queue_limit": self.default_queue_limit,
            "next_socket_id": self._next_socket_id,
            "sockets": [
                {
                    **{key: value for key, value in record.items() if key != "queue_length"},
                    "inbox": [datagram.to_dict() for datagram in self._sockets[int(record["socket_id"])].inbox],
                }
                for record in self.sockets()
            ],
            "journal": self.journal.snapshot(),
        }

    @classmethod
    def from_snapshot(
        cls,
        payload: dict[str, Any],
        fabric: OwnedNetworkFabric,
        journal: EventJournal | None = None,
    ) -> "OwnedDatagramStack":
        """Mathematics: reconstruct binding map `B` and inboxes `Q`, requiring unique identities and receipt-chain agreement."""

        saved_journal = payload.get("journal", [])
        shared_journal = journal or EventJournal.from_snapshot(list(saved_journal))
        if journal is not None and shared_journal.snapshot() != saved_journal:
            raise DatagramError("datagram journal differs from environment journal")
        stack = cls(fabric, shared_journal, int(payload["default_queue_limit"]))
        for raw in payload.get("sockets", ()):
            item = dict(raw)
            socket_id = int(item["socket_id"])
            address = NetworkAddress.from_dict(dict(item["address"]))
            port = _validate_port(int(item["port"]))
            limit = int(item["queue_limit"])
            if socket_id <= 0 or limit <= 0 or socket_id in stack._sockets:
                raise DatagramError("invalid or duplicate socket checkpoint identity")
            fabric._require_endpoint(address)
            if (address, port) in stack._bindings:
                raise DatagramError("duplicate socket binding in checkpoint")
            socket = _Socket(socket_id, address, port, limit)
            for raw_datagram in item.get("inbox", ()):
                datagram = NetworkDatagram.from_dict(dict(raw_datagram))
                if datagram.destination != address or datagram.destination_port != port:
                    raise DatagramError("socket inbox datagram does not match binding")
                for route_address in datagram.route:
                    fabric._require_endpoint(route_address)
                if datagram.source != datagram.route[0] or datagram.destination != datagram.route[-1]:
                    raise DatagramError("socket inbox datagram route is not closed")
                if len(socket.inbox) >= limit:
                    raise DatagramError("socket inbox exceeds queue limit")
                socket.inbox.append(datagram)
            stack._sockets[socket_id] = socket
            stack._bindings[(address, port)] = socket_id
        next_socket_id = int(payload["next_socket_id"])
        if next_socket_id <= 0 or (stack._sockets and next_socket_id <= max(stack._sockets)):
            raise DatagramError("invalid next socket identity")
        stack._next_socket_id = next_socket_id
        return stack

    def _socket(self, socket_id: int) -> _Socket:
        """Mathematics: resolve `s∈dom(S)` without creating implicit socket state."""

        try:
            return self._sockets[int(socket_id)]
        except KeyError as exc:
            raise DatagramError(f"unknown socket: {socket_id}") from exc

    def _pump_until(self, target: _Socket, max_size: int | None) -> None:
        """Mathematics: repeatedly apply `peek wire → decode → bind lookup → dequeue → enqueue Q_port` until target has data or wire is empty."""

        while not target.inbox:
            frame = self.fabric.peek(target.address)
            if frame is None:
                return
            source_port, destination_port, body = decode_datagram(frame.payload)
            socket_id = self._bindings.get((target.address, destination_port))
            if socket_id is None:
                dropped = self.fabric.receive(target.address)
                if dropped is None or dropped.frame_id != frame.frame_id:
                    raise DatagramError("network frame changed during unbound datagram discard")
                self.journal.append(
                    "network.datagram.drop",
                    {
                        "frame_id": frame.frame_id,
                        "destination": target.address.to_dict(),
                        "destination_port": destination_port,
                        "reason": "unbound-port",
                    },
                )
                continue
            socket = self._socket(socket_id)
            if len(socket.inbox) >= socket.queue_limit:
                raise DatagramError("socket receive queue is full")
            if socket_id == target.socket_id and max_size is not None and len(body) > max_size:
                raise DatagramError("socket receive buffer is smaller than queued datagram")
            received = self.fabric.receive(target.address)
            if received is None or received.frame_id != frame.frame_id:
                raise DatagramError("network frame changed during datagram demultiplexing")
            datagram = NetworkDatagram(
                received.frame_id,
                received.source,
                received.destination,
                source_port,
                destination_port,
                body,
                received.logical_time,
                received.route,
            )
            socket.inbox.append(datagram)
            self.journal.append("network.datagram.deliver", {"datagram": datagram.to_dict()})
