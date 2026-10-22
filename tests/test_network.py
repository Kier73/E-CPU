from __future__ import annotations

import ast
from pathlib import Path

import pytest

import mailcpu
from mailcpu import HeadlessNetworkDevice, HeadlessOS, HttpMethod, NetworkError, TcpState, http_to_hdc, parse_http


def _packet(src_ip: bytes, dst_ip: bytes, src_port: int, dst_port: int, flags: int, payload: bytes = b"") -> bytes:
    """Mathematics: construct an E0 frame with `total_length = 40 + |payload|` and fixed IPv4/TCP headers."""

    total_length = 40 + len(payload)
    packet = bytearray(total_length)
    packet[0] = 0x45
    packet[2:4] = total_length.to_bytes(2, "big")
    packet[9] = 6
    packet[12:16] = src_ip
    packet[16:20] = dst_ip
    packet[20:22] = src_port.to_bytes(2, "big")
    packet[22:24] = dst_port.to_bytes(2, "big")
    packet[32] = 0x50
    packet[33] = flags
    packet[34:36] = (4096).to_bytes(2, "big")
    packet[40:] = payload
    return bytes(packet)


def test_host_socket_access_is_confined_to_external_transport() -> None:
    """Mathematics: the host-socket import set is exactly the explicit external transport boundary, while semantic network modules remain socket-free."""

    package = Path(mailcpu.__file__).resolve().parent
    offenders: list[str] = []
    for module_path in sorted(package.glob("*.py")):
        tree = ast.parse(module_path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots = [alias.name.split(".")[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                roots = [(node.module or "").split(".")[0]]
            else:
                continue
            if "socket" in roots:
                offenders.append(f"{module_path.name}:{node.lineno}")
    assert offenders
    assert {Path(item.split(":", 1)[0]).name for item in offenders} == {"socket_transport.py"}


def test_e0_network_tracks_tcp_http_and_receipts() -> None:
    """Mathematics: SYN/ACK/HTTP composition reaches `ESTABLISHED` and emits receipt-linked semantic events."""

    device = HeadlessNetworkDevice()
    src = bytes((192, 168, 1, 100))
    dst = bytes((10, 0, 0, 1))
    assert device.ingest(1, _packet(src, dst, 54321, 80, 0x02))[0].state is TcpState.SYN_RCVD
    assert device.ingest(2, _packet(src, dst, 54321, 80, 0x10))[0].state is TcpState.ESTABLISHED
    events = device.ingest(
        3,
        _packet(src, dst, 54321, 80, 0x18, b"GET /os HTTP/1.1\r\nHost: mailcpu\r\n\r\n"),
    )
    http_events = [event for event in events if event.kind == "http.message"]
    assert http_events and http_events[0].http is not None
    assert http_events[0].http.method is HttpMethod.GET
    assert http_events[0].http.uri == "/os"
    assert device.journal.verify()
    assert all(event.receipt for event in device.events())


def test_e0_network_rejects_wire_errors_and_reports_http_errors() -> None:
    """Mathematics: malformed wire frames are rejected before state mutation, while malformed HTTP is an explicit event."""

    device = HeadlessNetworkDevice()
    bad = bytearray(40)
    bad[0] = 0x45
    bad[2:4] = (16).to_bytes(2, "big")
    bad[9] = 6
    with pytest.raises(NetworkError, match="truncated"):
        device.ingest(1, bytes(bad))
    assert device.total_packets == 0
    src = bytes((1, 1, 1, 1))
    dst = bytes((2, 2, 2, 2))
    device.ingest(2, _packet(src, dst, 1000, 80, 0x02))
    device.ingest(3, _packet(src, dst, 1000, 80, 0x10))
    malformed = _packet(src, dst, 1000, 80, 0x18, b"GET / HTTP/1.1\r\nContent-Length: bad\r\n\r\n")
    assert any(event.kind == "http.error" for event in device.ingest(4, malformed))


def test_http_parser_and_hdc_are_bounded_and_deterministic() -> None:
    """Mathematics: require exact Content-Length body bounds and deterministic 256-bit HDC output."""

    message = parse_http(b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nContent-Length: 5\r\n\r\nhello world")
    assert message.content_length == 5
    assert message.body == b"hello"
    assert http_to_hdc(message) == http_to_hdc(message)
    with pytest.raises(NetworkError, match="truncated HTTP body"):
        parse_http(b"GET / HTTP/1.1\r\nContent-Length: 4\r\n\r\nno")


def test_network_device_is_part_of_headless_checkpoint_graph(tmp_path: Path) -> None:
    """Mathematics: network state `N = (C, E, H)` survives `restore(save(N))` inside the OS product."""

    os = HeadlessOS()
    src = bytes((10, 0, 0, 1))
    dst = bytes((10, 0, 0, 2))
    os.environment.network.ingest(1, _packet(src, dst, 4000, 80, 0x02))
    os.environment.network.ingest(2, _packet(src, dst, 4000, 80, 0x10))
    checkpoint = tmp_path / "network.mcpu.json"
    os.save_checkpoint(checkpoint)
    restored = HeadlessOS.restore_checkpoint(checkpoint)
    assert restored.environment.network.connections() == os.environment.network.connections()
    assert len(restored.environment.network.events()) == len(os.environment.network.events())
    assert restored.environment.kernel.journal.verify()
