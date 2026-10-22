"""E0 headless IPv4/TCP and HTTP transduction over captured or emulated frames."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any

from .evidence import EvidenceTier, with_evidence_tier
from .journal import EventJournal


class NetworkError(ValueError):
    """A captured frame violates the bounded E0 wire grammar."""


class TcpState(str, Enum):
    """The finite connection states represented by the E0 driver."""

    CLOSED = "closed"
    SYN_RCVD = "syn_rcvd"
    ESTABLISHED = "established"
    CLOSE_WAIT = "close_wait"
    TIME_WAIT = "time_wait"


class HttpMethod(str, Enum):
    """HTTP methods recognized by the semantic parser."""

    GET = "GET"
    POST = "POST"
    HEAD = "HEAD"
    PUT = "PUT"
    RESPONSE = "RESPONSE"


TCP_FLAG_FIN = 0x01
TCP_FLAG_SYN = 0x02
TCP_FLAG_RST = 0x04
TCP_FLAG_ACK = 0x10


@dataclass(frozen=True)
class HttpMessage:
    """Parsed HTTP request/response independent of packet segmentation."""

    method: HttpMethod
    status_code: int
    uri: str
    headers: tuple[tuple[str, str], ...]
    body: bytes
    content_length: int
    content_type: str
    is_response: bool

    def to_dict(self) -> dict[str, object]:
        """Mathematics: project message `M` into a canonical JSON record with `body := hex(bytes)`."""

        return {
            "method": self.method.value,
            "status_code": self.status_code,
            "uri": self.uri,
            "headers": [list(item) for item in self.headers],
            "body_hex": self.body.hex(),
            "content_length": self.content_length,
            "content_type": self.content_type,
            "is_response": self.is_response,
        }


@dataclass(frozen=True)
class NetworkEvent:
    """One semantic event emitted by the E0 driver and anchored to a journal receipt."""

    kind: str
    logical_time: int
    connection: str | None
    state: TcpState | None
    payload: bytes
    http: HttpMessage | None
    error: str | None
    receipt: str

    def to_dict(self) -> dict[str, object]:
        """Mathematics: serialize event `e` while preserving payload identity and receipt `H_e`."""

        return with_evidence_tier(
            {
                "kind": self.kind,
                "logical_time": self.logical_time,
                "connection": self.connection,
                "state": None if self.state is None else self.state.value,
                "payload_hex": self.payload.hex(),
                "http": None if self.http is None else self.http.to_dict(),
                "error": self.error,
                "receipt": self.receipt,
            },
            EvidenceTier.E0,
        )


@dataclass
class _Connection:
    """Mutable RFC-793-shaped state for one canonical bidirectional flow."""

    identity: str
    src_ip: int
    dst_ip: int
    src_port: int
    dst_port: int
    state: TcpState = TcpState.CLOSED
    seq_num: int = 0
    ack_num: int = 0
    window_size: int = 0
    last_activity: int = 0
    packets: int = 0
    bytes_received: int = 0
    active: bool = True


def _parse_ipv4_tcp(packet: bytes) -> tuple[dict[str, int], bytes]:
    """Mathematics: parse bounded frame `f` only if `len(f) ≥ IHL + TCPHeader` and protocol `= 6`."""

    if len(packet) < 40:
        raise NetworkError("packet too small for IPv4 plus TCP")
    version_ihl = packet[0]
    if version_ihl >> 4 != 4:
        raise NetworkError("not IPv4")
    ihl = (version_ihl & 0x0F) * 4
    if ihl < 20 or ihl > len(packet):
        raise NetworkError("invalid IPv4 header length")
    total_length = int.from_bytes(packet[2:4], "big")
    if total_length < ihl + 20 or total_length > len(packet):
        raise NetworkError("truncated or invalid IPv4 total length")
    if packet[9] != 6:
        raise NetworkError("not TCP protocol")
    tcp = packet[ihl:total_length]
    data_offset = ((tcp[12] >> 4) & 0x0F) * 4
    if data_offset < 20 or data_offset > len(tcp):
        raise NetworkError("invalid TCP data offset")
    fields = {
        "src_ip": int.from_bytes(packet[12:16], "big"),
        "dst_ip": int.from_bytes(packet[16:20], "big"),
        "src_port": int.from_bytes(tcp[0:2], "big"),
        "dst_port": int.from_bytes(tcp[2:4], "big"),
        "seq_num": int.from_bytes(tcp[4:8], "big"),
        "ack_num": int.from_bytes(tcp[8:12], "big"),
        "flags": tcp[13],
        "window_size": int.from_bytes(tcp[14:16], "big"),
    }
    return fields, tcp[data_offset:]


def _connection_identity(fields: dict[str, int]) -> str:
    """Mathematics: canonicalize flow identity by sorting endpoint pairs `id = min(a,b) || max(a,b)`."""

    left = (fields["src_ip"], fields["src_port"])
    right = (fields["dst_ip"], fields["dst_port"])
    first, second = sorted((left, right))
    return f"{first[0]}:{first[1]}<->{second[0]}:{second[1]}"


def parse_http(payload: bytes) -> HttpMessage:
    """Mathematics: parse `HTTP = start_line || headers || body`, enforcing nonnegative Content-Length bounds."""

    if not payload:
        raise NetworkError("empty HTTP payload")
    delimiter = b"\r\n\r\n"
    delimiter_size = 4
    boundary = payload.find(delimiter)
    if boundary < 0:
        delimiter = b"\n\n"
        delimiter_size = 2
        boundary = payload.find(delimiter)
    header_end = len(payload) if boundary < 0 else boundary
    header_block = payload[:header_end].decode("utf-8", "strict")
    lines = header_block.splitlines()
    if not lines or not lines[0]:
        raise NetworkError("missing HTTP start line")
    start = lines[0].split()
    is_response = lines[0].startswith("HTTP/1.")
    uri = ""
    status_code = 0
    if is_response:
        if len(start) < 2 or not start[1].isdigit():
            raise NetworkError("invalid HTTP response line")
        status_code = int(start[1])
        method = HttpMethod.RESPONSE
    else:
        if len(start) != 3 or start[0] not in {item.value for item in HttpMethod if item is not HttpMethod.RESPONSE}:
            raise NetworkError("invalid HTTP request line")
        method = HttpMethod(start[0])
        if start[2] != "HTTP/1.1" and start[2] != "HTTP/1.0":
            raise NetworkError("unsupported HTTP version")
        uri = start[1][:2048]
    headers: list[tuple[str, str]] = []
    content_length: int | None = None
    content_type = ""
    for raw_line in lines[1:]:
        if not raw_line or ":" not in raw_line:
            raise NetworkError("malformed HTTP header")
        name, value = raw_line.split(":", 1)
        name = name.strip()
        value = value.strip()
        if not name:
            raise NetworkError("empty HTTP header name")
        headers.append((name, value))
        if name.lower() == "content-length":
            try:
                parsed_length = int(value)
            except ValueError as exc:
                raise NetworkError("invalid Content-Length") from exc
            if parsed_length < 0:
                raise NetworkError("negative Content-Length")
            content_length = parsed_length
        elif name.lower() == "content-type":
            content_type = value.split(";", 1)[0].strip()
    body = b"" if boundary < 0 else payload[boundary + delimiter_size :]
    if content_length is not None:
        if len(body) < content_length:
            raise NetworkError("truncated HTTP body")
        body = body[:content_length]
    return HttpMessage(
        method,
        status_code,
        uri,
        tuple(headers),
        body,
        len(body) if content_length is None else content_length,
        content_type,
        is_response,
    )


def _token_to_words(token: str) -> tuple[int, int, int, int]:
    """Mathematics: map token `w` to four 64-bit words of `SHA256(UTF8(w))`."""

    digest = hashlib.sha256(token.encode("utf-8")).digest()
    return tuple(int.from_bytes(digest[index : index + 8], "big") for index in range(0, 32, 8))


def http_to_hdc(message: HttpMessage) -> tuple[int, int, int, int]:
    """Mathematics: compute 256-bit majority bundle `H[b] = 1 iff Σ_i (2x_i[b]-1) ≥ 0` over bounded tokens."""

    text = (message.body if message.body else message.uri.encode("utf-8")).decode("utf-8", "ignore")
    tokens = re.findall(r"[A-Za-z0-9]+", text)[:64]
    if not tokens:
        tokens = [f"http_{message.method.value}_{message.status_code}"]
    votes = [0] * 256
    for token in tokens:
        words = _token_to_words(token.lower())
        for bit in range(256):
            word = words[bit // 64]
            votes[bit] += 1 if ((word >> (bit % 64)) & 1) else -1
    output: list[int] = []
    for word_index in range(4):
        value = 0
        for bit in range(64):
            if votes[word_index * 64 + bit] >= 0:
                value |= 1 << bit
        output.append(value)
    return tuple(output)  # type: ignore[return-value]


class HeadlessNetworkDevice:
    """Deterministic E0 network driver: captured bytes become journaled connection and HTTP events."""

    def __init__(self, journal: EventJournal | None = None, max_connections: int = 16) -> None:
        """Mathematics: initialize bounded connection relation `C`, event sequence `E`, and receipt chain `H`."""

        if max_connections <= 0:
            raise ValueError("max_connections must be positive")
        self.journal = journal or EventJournal()
        self.max_connections = max_connections
        self._connections: dict[str, _Connection] = {}
        self._events: list[NetworkEvent] = []
        self.total_packets = 0
        self.total_bytes = 0

    def ingest(self, logical_time: int, packet: bytes) -> tuple[NetworkEvent, ...]:
        """Mathematics: apply one frame transition `D(C, packet) -> (C', E', H')` or reject before mutation."""

        fields, payload = _parse_ipv4_tcp(packet)
        flags = fields["flags"]
        identity = _connection_identity(fields)
        connection = self._connections.get(identity)
        if connection is None:
            if not (flags & TCP_FLAG_SYN) or len(self._connections) >= self.max_connections:
                raise NetworkError("unknown flow or connection capacity exhausted")
            connection = _Connection(
                identity,
                fields["src_ip"],
                fields["dst_ip"],
                fields["src_port"],
                fields["dst_port"],
            )
            self._connections[identity] = connection
        previous_state = connection.state
        next_state = self._next_state(connection.state, flags)
        connection.state = next_state
        connection.seq_num = fields["seq_num"]
        connection.ack_num = fields["ack_num"]
        connection.window_size = fields["window_size"]
        connection.last_activity = logical_time
        connection.packets += 1
        connection.bytes_received += len(payload)
        self.total_packets += 1
        self.total_bytes += len(payload)
        events = [
            self._emit(
                "connection.state",
                logical_time,
                connection,
                b"",
                None,
                None if previous_state == next_state else f"{previous_state.value}->{next_state.value}",
            )
        ]
        if payload:
            events.append(self._emit("tcp.payload", logical_time, connection, payload, None, None))
            if _looks_like_http(payload):
                try:
                    message = parse_http(payload)
                except NetworkError as exc:
                    events.append(self._emit("http.error", logical_time, connection, payload, None, str(exc)))
                else:
                    events.append(self._emit("http.message", logical_time, connection, payload, message, None))
        if flags & TCP_FLAG_RST:
            connection.active = False
        return tuple(events)

    def connections(self) -> tuple[dict[str, object], ...]:
        """Mathematics: expose finite connection map `C` as stable records ordered by identity."""

        return tuple(
            {
                "identity": item.identity,
                "state": item.state.value,
                "seq_num": item.seq_num,
                "ack_num": item.ack_num,
                "window_size": item.window_size,
                "last_activity": item.last_activity,
                "packets": item.packets,
                "bytes_received": item.bytes_received,
                "active": item.active,
            }
            for item in sorted(self._connections.values(), key=lambda connection: connection.identity)
        )

    def events(self) -> tuple[NetworkEvent, ...]:
        """Mathematics: expose append-only semantic event sequence `E = (e_1, ..., e_n)`."""

        return tuple(self._events)

    def snapshot(self) -> dict[str, Any]:
        """Mathematics: serialize `(C, E, counters, H)` for deterministic network-driver restoration."""

        return {
            "max_connections": self.max_connections,
            "total_packets": self.total_packets,
            "total_bytes": self.total_bytes,
            "connections": list(self.connections()),
            "events": [event.to_dict() for event in self._events],
            "journal": self.journal.snapshot(),
        }

    @classmethod
    def from_snapshot(
        cls,
        payload: dict[str, Any],
        journal: EventJournal | None = None,
    ) -> "HeadlessNetworkDevice":
        """Mathematics: reconstruct `(C, E, H)` and require saved receipts to belong to the shared verified journal."""

        shared_journal = journal or EventJournal.from_snapshot(list(payload["journal"]))
        if journal is not None and shared_journal.snapshot() != payload.get("journal", []):
            raise NetworkError("network journal differs from environment journal")
        device = cls(shared_journal, int(payload["max_connections"]))
        device.total_packets = int(payload["total_packets"])
        device.total_bytes = int(payload["total_bytes"])
        for raw in payload.get("connections", ()):
            identity = str(raw["identity"])
            if identity in device._connections:
                raise NetworkError(f"duplicate network connection: {identity}")
            device._connections[identity] = _Connection(
                identity,
                0,
                0,
                0,
                0,
                TcpState(raw["state"]),
                int(raw["seq_num"]),
                int(raw["ack_num"]),
                int(raw["window_size"]),
                int(raw["last_activity"]),
                int(raw["packets"]),
                int(raw["bytes_received"]),
                bool(raw["active"]),
            )
        known_receipts = {record.digest for record in shared_journal.records()}
        for raw in payload.get("events", ()):
            receipt = str(raw["receipt"])
            if receipt not in known_receipts:
                raise NetworkError(f"network event receipt missing from journal: {receipt}")
            http_raw = raw.get("http")
            http = None if http_raw is None else _http_from_dict(dict(http_raw))
            device._events.append(
                NetworkEvent(
                    str(raw["kind"]),
                    int(raw["logical_time"]),
                    raw.get("connection"),
                    None if raw.get("state") is None else TcpState(raw["state"]),
                    bytes.fromhex(str(raw.get("payload_hex", ""))),
                    http,
                    raw.get("error"),
                    receipt,
                )
            )
        return device

    def _next_state(self, current: TcpState, flags: int) -> TcpState:
        """Mathematics: apply finite transition relation `δ_tcp(current, flags)` for the supported RFC-shaped subset."""

        if flags & TCP_FLAG_RST:
            return TcpState.CLOSED
        if current is TcpState.CLOSED and flags & TCP_FLAG_SYN:
            return TcpState.ESTABLISHED if flags & TCP_FLAG_ACK else TcpState.SYN_RCVD
        if current is TcpState.SYN_RCVD and flags & TCP_FLAG_ACK:
            return TcpState.ESTABLISHED
        if current is TcpState.ESTABLISHED and flags & TCP_FLAG_FIN:
            return TcpState.CLOSE_WAIT
        if current is TcpState.CLOSE_WAIT and flags & TCP_FLAG_ACK:
            return TcpState.TIME_WAIT
        return current

    def _emit(
        self,
        kind: str,
        logical_time: int,
        connection: _Connection,
        payload: bytes,
        http: HttpMessage | None,
        error: str | None,
    ) -> NetworkEvent:
        """Mathematics: append event receipt `H_n = SHA256(H_{n-1} || canonical(event_n))` through the shared journal."""

        record_payload = {
            "kind": kind,
            "logical_time": logical_time,
            "connection": connection.identity,
            "state": connection.state.value,
            "payload_hex": payload.hex(),
            "http": None if http is None else http.to_dict(),
            "error": error,
        }
        record = self.journal.append("network." + kind, record_payload)
        event = NetworkEvent(kind, logical_time, connection.identity, connection.state, payload, http, error, record.digest)
        self._events.append(event)
        return event


def _looks_like_http(payload: bytes) -> bool:
    """Mathematics: classify semantic candidate `p` by prefix membership in finite HTTP start-line languages."""

    return payload.startswith((b"GET ", b"POST ", b"HEAD ", b"PUT ", b"HTTP/1."))


def _http_from_dict(payload: dict[str, Any]) -> HttpMessage:
    """Mathematics: invert `HttpMessage.to_dict` while preserving the typed message domain."""

    return HttpMessage(
        HttpMethod(payload["method"]),
        int(payload["status_code"]),
        str(payload["uri"]),
        tuple((str(item[0]), str(item[1])) for item in payload["headers"]),
        bytes.fromhex(str(payload["body_hex"])),
        int(payload["content_length"]),
        str(payload["content_type"]),
        bool(payload["is_response"]),
    )
