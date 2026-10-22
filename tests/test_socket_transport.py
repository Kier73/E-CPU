from __future__ import annotations

import socket

import pytest

from mailcpu import Message, ReliabilityPolicy, ReliableChannel
from mailcpu.socket_transport import SocketTransport, SocketTransportError, _encode_frame


def test_tcp_loopback_transports_typed_messages_and_preserves_fifo() -> None:
    """Mathematics: verify `send(m_1);send(m_2)` produces `Q_addr=[m_1,m_2]` across a real TCP loopback stream."""

    listener = SocketTransport.listen()
    try:
        port = listener.getsockname()[1]
        client = SocketTransport.connect("127.0.0.1", port, "A", "B")
        server = SocketTransport.accept(listener, "B", "A")
        try:
            first = client.send("inbox", Message(sender="A", op="DATA", body=(b"bytes", {"tuple": (1, 2)})))
            second = client.send("inbox", Message(sender="A", op="DATA", body=(b"second",)))
            assert server.list("inbox") == (first, second)
            assert server.poll("inbox") == first
            assert server.consume(second) is True
            reply = server.send("acks", Message(sender="B", op="ACK", value=1))
            assert client.poll("acks") == reply
        finally:
            client.close()
            server.close()
    finally:
        listener.close()


def test_socket_transport_reassembles_partial_frame_without_early_delivery() -> None:
    """Mathematics: for `wire=H||P`, a prefix shorter than `|wire|` leaves `Q` unchanged until the suffix arrives."""

    left, right = socket.socketpair()
    sender = SocketTransport(left, "A", "B")
    receiver = SocketTransport(right, "B", "A")
    message = Message(sender="A", recipient="inbox", op="DATA", body=(b"partial",))
    wire = _encode_frame(Message(sender="A", recipient="inbox", op="DATA", body=(b"partial",), message_id="A:raw"), 1 << 20)
    try:
        split = len(wire) // 2
        left.sendall(wire[:split])
        assert receiver.service() == 0
        assert receiver.pending() == 0
        left.sendall(wire[split:])
        assert receiver.list("inbox") == (Message(sender="A", recipient="inbox", op="DATA", body=(b"partial",), message_id="A:raw"),)
        assert receiver.consume(message) is False
    finally:
        sender.close()
        receiver.close()


def test_socket_transport_rejects_integrity_failure_without_queue_mutation() -> None:
    """Mathematics: if `SHA256(C(m))≠d`, the frame is rejected and `Q' = Q`."""

    left, right = socket.socketpair()
    sender = SocketTransport(left, "A", "B")
    receiver = SocketTransport(right, "B", "A")
    wire = bytearray(_encode_frame(Message(sender="A", recipient="inbox", op="DATA", body=(b"tamper",), message_id="A:tamper"), 1 << 20))
    marker = b'"digest":"'
    digest_index = wire.index(marker) + len(marker)
    wire[digest_index] = ord("0") if wire[digest_index] != ord("0") else ord("1")
    try:
        left.sendall(wire)
        with pytest.raises(SocketTransportError, match="integrity"):
            receiver.service()
        assert receiver.pending() == 0
    finally:
        sender.close()
        receiver.close()


def test_socket_transport_rejects_sender_identity_spoofing() -> None:
    """Mathematics: require every received frame to satisfy `sender(frame)=peer_endpoint` before insertion into `Q`."""

    left, right = socket.socketpair()
    sender = SocketTransport(left, "A", "B")
    receiver = SocketTransport(right, "B", "A")
    wire = _encode_frame(Message(sender="C", recipient="inbox", op="DATA", body=(), message_id="C:1"), 1 << 20)
    try:
        left.sendall(wire)
        with pytest.raises(SocketTransportError, match="sender"):
            receiver.service()
        assert receiver.pending() == 0
        with pytest.raises(SocketTransportError, match="sender"):
            sender.send("inbox", Message(sender="C", op="DATA"))
    finally:
        sender.close()
        receiver.close()


def test_socket_transport_checkpoint_restores_received_mailboxes_on_rebind() -> None:
    """Mathematics: verify `restore(snapshot(Q,L,n))` preserves queued identities and FIFO continuation on a new stream."""

    left, right = socket.socketpair()
    sender = SocketTransport(left, "A", "B")
    receiver = SocketTransport(right, "B", "A")
    try:
        sent = sender.send("inbox", Message(sender="A", op="DATA", body=(b"checkpoint",)))
        assert receiver.list("inbox") == (sent,)
        snapshot = receiver.snapshot()
    finally:
        sender.close()
        receiver.close()
    rebound_left, rebound_right = socket.socketpair()
    restored = SocketTransport.from_snapshot(rebound_right, snapshot)
    try:
        assert restored.poll("inbox") == sent
        assert restored.pending() == 0
    finally:
        restored.close()
        rebound_left.close()


def test_reliable_channel_runs_over_tcp_transport_with_acknowledgement() -> None:
    """Mathematics: verify `F_s→ACK(s)` clears `P[s]` over the real stream while preserving FIFO delivery."""

    left, right = socket.socketpair()
    sender_transport = SocketTransport(left, "A", "B")
    receiver_transport = SocketTransport(right, "B", "A")
    sender = ReliableChannel(sender_transport, "A", "B", "data", ReliabilityPolicy(3, 2))
    receiver = ReliableChannel(receiver_transport, "B", "B", "data", peer="A")
    try:
        sequence = sender.send((b"remote", {"value": 7}))
        assert receiver.receive() == (sequence, (b"remote", {"value": 7}))
        assert sender.process_ack() == (sequence,)
        assert sender.pending_sequences() == ()
    finally:
        sender_transport.close()
        receiver_transport.close()
