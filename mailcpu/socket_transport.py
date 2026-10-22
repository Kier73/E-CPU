r"""Real stream-socket transport for moving MailCPU messages between hosts.

The transport preserves the existing mailbox algebra while replacing the local
queue's substrate with a TCP byte stream.  Active communication is energy in the
system's internal sense; the stream's frame size and Chemical Time can therefore
be measured at the same message boundary as local work.

Mathematics:
For a byte buffer $R$, complete frames are repeatedly removed by
\[
 R = H || P || R' \longrightarrow (P,R'),
\]
where $H=(magic,length)$ and $|P|=length$.  A frame's integrity receipt is
\[
 d = SHA256(JSON_{canonical}(version,message)).
\]
Only complete frames enter the mailbox product $Q=\prod_a Q_a$; an incomplete
suffix remains in $R$ and cannot become a message.
"""

from __future__ import annotations

from collections import deque
import hashlib
import hmac
import json
import select
import socket
import struct
import time
from typing import Any

from ._codec import decode_canonical_value, encode_canonical_value
from .model import Message


class SocketTransportError(RuntimeError):
    """A socket transport frame, route, peer, or recovery invariant is invalid."""


class SocketTransportClosed(SocketTransportError):
    """The peer closed a stream while a transport operation required it to remain active."""


_MAGIC = b"ECPU"
_VERSION = 1
_HEADER = struct.Struct("!4sI")
_DEFAULT_MAX_FRAME = 1 << 20
_RECV_CHUNK = 64 << 10


def _canonical_frame(message: Message) -> bytes:
    """Mathematics: encode `C(m)=JSON_canonical(version,message)` as one deterministic byte string."""

    payload = {"version": _VERSION, "message": _socket_message_to_record(message)}
    try:
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise SocketTransportError(f"message is outside the wire value algebra: {error}") from error


def _encode_frame(message: Message, maximum: int) -> bytes:
    """Mathematics: construct `wire=H||P` with `|P|≤maximum` and `digest(P_without_digest)`."""

    canonical = _canonical_frame(message)
    envelope = {
        "version": _VERSION,
        "message": _socket_message_to_record(message),
        "digest": hashlib.sha256(canonical).hexdigest(),
    }
    try:
        body = json.dumps(envelope, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise SocketTransportError(f"frame cannot be encoded: {error}") from error
    if len(body) == 0 or len(body) > maximum:
        raise SocketTransportError(f"frame length {len(body)} exceeds maximum {maximum}")
    return _HEADER.pack(_MAGIC, len(body)) + body


def _decode_frame(body: bytes, maximum: int) -> Message:
    """Mathematics: invert `_encode_frame` only when version, digest, and typed message identity all agree."""

    if not body or len(body) > maximum:
        raise SocketTransportError("wire frame length is outside bounds")
    try:
        envelope = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SocketTransportError("wire frame is not valid UTF-8 JSON") from error
    if not isinstance(envelope, dict) or int(envelope.get("version", -1)) != _VERSION:
        raise SocketTransportError("unsupported wire frame version")
    raw_message = envelope.get("message")
    if not isinstance(raw_message, dict):
        raise SocketTransportError("wire frame message is not a mapping")
    try:
        canonical = json.dumps(
            {"version": _VERSION, "message": raw_message},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        expected = hashlib.sha256(canonical).hexdigest()
    except (TypeError, ValueError) as error:
        raise SocketTransportError("wire frame message cannot be canonicalized") from error
    if not hmac.compare_digest(str(envelope.get("digest", "")), expected):
        raise SocketTransportError("wire frame integrity receipt mismatch")
    try:
        message = _socket_message_from_record(raw_message)
    except (TypeError, ValueError, KeyError, OverflowError) as error:
        raise SocketTransportError("wire frame message violates transport algebra") from error
    if not message.message_id or not message.sender or not message.recipient:
        raise SocketTransportError("wire message identity is incomplete")
    return message


def _socket_message_to_record(message: Message) -> dict[str, Any]:
    """Mathematics: encode `Message` with the injective canonical body algebra so `decode(record(m))=m` preserves tuples."""

    return {
        "sender": message.sender,
        "recipient": message.recipient,
        "op": message.op,
        "addr": message.addr,
        "value": message.value,
        "seq": message.seq,
        "body": encode_canonical_value(message.body),
        "message_id": message.message_id,
    }


def _socket_message_from_record(record: dict[str, Any]) -> Message:
    """Mathematics: invert `_socket_message_to_record` over the canonical value algebra and restore tuple body identity."""

    body = decode_canonical_value(record.get("body", {"tuple": []}))
    if not isinstance(body, tuple):
        raise SocketTransportError("socket wire message body must preserve tuple identity")
    return Message(
        sender=str(record.get("sender", "")),
        recipient=str(record.get("recipient", "")),
        op=str(record.get("op", "")),
        addr=str(record.get("addr", "")),
        value=None if record.get("value") is None else int(record["value"]),
        seq=int(record.get("seq", 0)),
        body=body,
        message_id=str(record.get("message_id", "")),
    )


class SocketTransport:
    """A nonblocking TCP mailbox transport with bounded framed messages."""

    def __init__(
        self,
        sock: socket.socket,
        local_endpoint: str,
        peer_endpoint: str,
        *,
        max_frame_size: int = _DEFAULT_MAX_FRAME,
        send_timeout: float = 5.0,
    ) -> None:
        """Mathematics: bind stream `S` to identities `(local,peer)` and initialize `R=∅`, `Q=Π_a[]`, `n=1`."""

        if not isinstance(sock, socket.socket):
            raise TypeError("sock must be a socket.socket")
        if not local_endpoint or not peer_endpoint:
            raise SocketTransportError("local and peer endpoints must be non-empty")
        if not isinstance(max_frame_size, int) or isinstance(max_frame_size, bool) or max_frame_size < 256:
            raise SocketTransportError("max_frame_size must be an integer of at least 256 bytes")
        if send_timeout < 0:
            raise SocketTransportError("send_timeout must be non-negative")
        self.socket = sock
        self.socket.setblocking(False)
        self.local_endpoint = local_endpoint
        self.peer_endpoint = peer_endpoint
        self.max_frame_size = max_frame_size
        self.send_timeout = float(send_timeout)
        self._receive_buffer = bytearray()
        self._queues: dict[str, deque[Message]] = {}
        self._locations: dict[str, str] = {}
        self._seen_ids: set[str] = set()
        self._next_id = 1
        self._closed = False
        self._terminal_error: SocketTransportError | None = None

    @classmethod
    def connect(
        cls,
        host: str,
        port: int,
        local_endpoint: str,
        peer_endpoint: str,
        *,
        timeout: float = 5.0,
        max_frame_size: int = _DEFAULT_MAX_FRAME,
        send_timeout: float = 5.0,
    ) -> "SocketTransport":
        """Mathematics: create stream `S=TCP.connect(host,port)` and bind its mailbox identity pair."""

        if timeout <= 0:
            raise SocketTransportError("connect timeout must be positive")
        try:
            sock = socket.create_connection((host, int(port)), timeout=float(timeout))
        except OSError as error:
            raise SocketTransportError(f"socket connection failed: {error}") from error
        try:
            return cls(
                sock,
                local_endpoint,
                peer_endpoint,
                max_frame_size=max_frame_size,
                send_timeout=send_timeout,
            )
        except Exception:
            sock.close()
            raise

    @classmethod
    def accept(
        cls,
        listener: socket.socket,
        local_endpoint: str,
        peer_endpoint: str,
        *,
        max_frame_size: int = _DEFAULT_MAX_FRAME,
        send_timeout: float = 5.0,
    ) -> "SocketTransport":
        """Mathematics: accept one stream `S=listener.accept()` and bind its expected peer identity before delivery."""

        if not isinstance(listener, socket.socket):
            raise TypeError("listener must be a socket.socket")
        try:
            sock, _address = listener.accept()
        except OSError as error:
            raise SocketTransportError(f"socket accept failed: {error}") from error
        try:
            return cls(
                sock,
                local_endpoint,
                peer_endpoint,
                max_frame_size=max_frame_size,
                send_timeout=send_timeout,
            )
        except Exception:
            sock.close()
            raise

    @staticmethod
    def listen(host: str = "127.0.0.1", port: int = 0, backlog: int = 16) -> socket.socket:
        """Mathematics: create bounded listener `L=bind(host,port); listen(backlog)` for external stream peers."""

        if not isinstance(backlog, int) or isinstance(backlog, bool) or backlog <= 0:
            raise SocketTransportError("backlog must be a positive integer")
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind((host, int(port)))
            listener.listen(backlog)
            return listener
        except OSError as error:
            listener.close()
            raise SocketTransportError(f"socket listener failed: {error}") from error

    def send(self, addr: str, msg: Message) -> Message:
        """Mathematics: allocate identity `m_n`, append its frame to `S`, and return the exact routed message."""

        self._require_open()
        if not addr:
            raise SocketTransportError("mailbox address must be non-empty")
        if not isinstance(msg, Message):
            raise SocketTransportError("socket transport accepts Message values only")
        if msg.sender != self.local_endpoint:
            raise SocketTransportError("message sender does not match local endpoint")
        message = Message(
            sender=msg.sender,
            recipient=addr,
            op=msg.op,
            addr=msg.addr,
            value=msg.value,
            seq=msg.seq,
            body=msg.body,
            message_id=f"{self.local_endpoint}:{self._next_id}",
        )
        self._send_bytes(_encode_frame(message, self.max_frame_size))
        self._next_id += 1
        return message

    def poll(self, addr: str) -> Message | None:
        """Mathematics: fold complete stream frames into `Q`, then apply `Q_addr=[m]||R→(m,R)` or return `⊥`."""

        self.service()
        queue = self._queues.get(addr)
        if not queue:
            return None
        message = queue.popleft()
        self._locations.pop(message.message_id, None)
        return message

    def consume(self, msg: Message) -> bool:
        """Mathematics: remove exactly identity `m` from `Q` when `m∈Q`, preserving all other mailbox order."""

        self.service()
        addr = self._locations.get(msg.message_id)
        if addr is None:
            return False
        queue = self._queues[addr]
        for queued in queue:
            if queued.message_id == msg.message_id:
                queue.remove(queued)
                del self._locations[msg.message_id]
                return True
        return False

    def list(self, addr: str) -> tuple[Message, ...]:
        """Mathematics: service complete frames and return immutable `Q_addr` without changing it."""

        self.service()
        return tuple(self._queues.get(addr, ()))

    def pending(self, addr: str | None = None) -> int:
        """Mathematics: calculate `|Q|=Σ_a|Q_a|`, or the restricted cardinality `|Q_addr|`."""

        self.service()
        if addr is not None:
            return len(self._queues.get(addr, ()))
        return sum(len(queue) for queue in self._queues.values())

    def service(self) -> int:
        """Mathematics: append available bytes to `R` and repeatedly apply `R=H||P||R'→P` for complete frames."""

        self._require_open_or_terminal()
        if self._terminal_error is not None:
            raise self._terminal_error
        if self._closed:
            return 0
        while True:
            try:
                chunk = self.socket.recv(_RECV_CHUNK)
            except BlockingIOError:
                break
            except OSError as error:
                raise SocketTransportError(f"socket receive failed: {error}") from error
            if not chunk:
                self._closed = True
                self.socket.close()
                if self._receive_buffer:
                    self._terminal_error = SocketTransportError("peer closed with incomplete frame")
                    raise self._terminal_error
                break
            self._receive_buffer.extend(chunk)
        accepted: list[Message] = []
        while True:
            if len(self._receive_buffer) < _HEADER.size:
                break
            magic, length = _HEADER.unpack(self._receive_buffer[: _HEADER.size])
            if magic != _MAGIC:
                raise SocketTransportError("wire frame magic mismatch")
            if length <= 0 or length > self.max_frame_size:
                raise SocketTransportError("wire frame length exceeds configured bound")
            total = _HEADER.size + length
            if len(self._receive_buffer) < total:
                break
            body = bytes(self._receive_buffer[_HEADER.size : total])
            del self._receive_buffer[:total]
            message = _decode_frame(body, self.max_frame_size)
            if message.sender != self.peer_endpoint:
                raise SocketTransportError("wire message sender does not match expected peer")
            if message.message_id in self._seen_ids or any(item.message_id == message.message_id for item in accepted):
                raise SocketTransportError("duplicate wire message identity")
            accepted.append(message)
        for message in accepted:
            self._seen_ids.add(message.message_id)
            self._queues.setdefault(message.recipient, deque()).append(message)
            self._locations[message.message_id] = message.recipient
        return len(accepted)

    def snapshot(self) -> dict[str, object]:
        """Mathematics: serialize `Q`, identity set, counters, and binding while preserving an empty partial suffix `R=∅`."""

        self.service()
        if self._receive_buffer:
            raise SocketTransportError("cannot checkpoint an incomplete wire frame")
        return {
            "version": 1,
            "local_endpoint": self.local_endpoint,
            "peer_endpoint": self.peer_endpoint,
            "max_frame_size": self.max_frame_size,
            "send_timeout": self.send_timeout,
            "next_id": self._next_id,
            "seen_ids": sorted(self._seen_ids),
            "queues": {
                address: [_socket_message_to_record(message) for message in queue]
                for address, queue in sorted(self._queues.items())
                if queue
            },
        }

    @classmethod
    def from_snapshot(cls, sock: socket.socket, payload: dict[str, Any]) -> "SocketTransport":
        """Mathematics: reconstruct `Q,L,n` on a rebound socket and reject identity collisions before use."""

        if int(payload.get("version", -1)) != 1:
            raise SocketTransportError("unsupported socket transport snapshot version")
        transport = cls(
            sock,
            str(payload["local_endpoint"]),
            str(payload["peer_endpoint"]),
            max_frame_size=int(payload.get("max_frame_size", _DEFAULT_MAX_FRAME)),
            send_timeout=float(payload.get("send_timeout", 5.0)),
        )
        transport._next_id = int(payload.get("next_id", 1))
        if transport._next_id <= 0:
            raise SocketTransportError("socket transport next_id must be positive")
        seen = [str(item) for item in payload.get("seen_ids", ())]
        if len(seen) != len(set(seen)) or any(not item for item in seen):
            raise SocketTransportError("socket transport seen identities must be unique")
        transport._seen_ids = set(seen)
        for raw_address, raw_queue in dict(payload.get("queues", {})).items():
            address = str(raw_address)
            if not address:
                raise SocketTransportError("socket transport mailbox address must be non-empty")
            queue: deque[Message] = deque()
            for raw_message in raw_queue:
                message = _socket_message_from_record(dict(raw_message))
                if (
                    not message.message_id
                    or message.message_id in transport._locations
                    or message.message_id not in transport._seen_ids
                    or message.recipient != address
                    or message.sender != transport.peer_endpoint
                ):
                    raise SocketTransportError("socket transport snapshot message identity is invalid")
                queue.append(message)
                transport._locations[message.message_id] = address
            if queue:
                transport._queues[address] = queue
        return transport

    @property
    def closed(self) -> bool:
        """Mathematics: expose stream state `closed∈{False,True}` without mutating mailbox state."""

        return self._closed

    def close(self) -> None:
        """Mathematics: transition the local stream to `closed=True` while retaining already received `Q` in memory."""

        if not self._closed:
            self._closed = True
            try:
                self.socket.close()
            except OSError:
                pass

    def _send_bytes(self, payload: bytes) -> None:
        """Mathematics: transmit every byte of `payload` or refuse after the bounded deadline `Δ≤send_timeout`."""

        deadline = time.monotonic() + self.send_timeout
        view = memoryview(payload)
        while view:
            self._require_open()
            try:
                written = self.socket.send(view)
            except BlockingIOError:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise SocketTransportError("socket send timed out under backpressure")
                _readable, writable, _exceptional = select.select([], [self.socket], [], remaining)
                if not writable:
                    raise SocketTransportError("socket send timed out under backpressure")
                continue
            except OSError as error:
                raise SocketTransportClosed(f"socket send failed: {error}") from error
            if written <= 0:
                raise SocketTransportClosed("socket send made no progress")
            view = view[written:]

    def _require_open(self) -> None:
        """Mathematics: require `closed=False` before a state-changing stream operation."""

        if self._closed:
            raise SocketTransportClosed("socket transport is closed")

    def _require_open_or_terminal(self) -> None:
        """Mathematics: permit one final receive transition after EOF, but reject a terminal framing error."""

        if self._terminal_error is not None:
            raise self._terminal_error

