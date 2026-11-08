"""Mutually authenticated TLS adapters for the MailCPU framed socket transport."""

from __future__ import annotations

import socket
import ssl
from typing import Any

from .socket_transport import SocketListener, SocketTransport


class MutualTLSTransportError(RuntimeError):
    """Mathematics: reject TLS setup unless peer chain, DNS identity, and protocol policy all satisfy the authenticated-channel invariant."""


def _validate_context(context: ssl.SSLContext, *, server_side: bool) -> None:
    """Mathematics: require peer-verifying TLS context C with protocol floor TLSv1.2 and role-correct certificate policy."""

    if not isinstance(context, ssl.SSLContext):
        raise TypeError("TLS context must be an ssl.SSLContext")
    if context.minimum_version == ssl.TLSVersion.MINIMUM_SUPPORTED:
        context.minimum_version = ssl.TLSVersion.TLSv1_2
    if context.minimum_version < ssl.TLSVersion.TLSv1_2:
        raise MutualTLSTransportError("TLS context minimum version must be TLS 1.2 or newer")
    if context.verify_mode is not ssl.CERT_REQUIRED:
        raise MutualTLSTransportError("mutual TLS requires CERT_REQUIRED peer verification")
    if not server_side and not context.check_hostname:
        raise MutualTLSTransportError("TLS client context must verify the server hostname")
    if server_side and context.check_hostname:
        raise MutualTLSTransportError("TLS server context must disable client hostname checking")


def _validate_negotiated_peer(tls_socket: ssl.SSLSocket) -> None:
    """Mathematics: accept negotiated channel only when protocol version v∈{TLS1.2,TLS1.3} and cipher c≠⊥."""

    if tls_socket.version() not in {"TLSv1.2", "TLSv1.3"}:
        raise MutualTLSTransportError("negotiated TLS version is below the supported security floor")
    if tls_socket.cipher() is None:
        raise MutualTLSTransportError("TLS handshake did not negotiate a cipher")


def _require_dns_identity(certificate: dict[str, Any], expected_identity: str) -> None:
    """Mathematics: authenticate peer only when expected DNS identity d is a member of certificate SAN_DNS."""

    if not expected_identity:
        raise MutualTLSTransportError("expected peer DNS identity must be non-empty")
    names = {
        value
        for kind, value in certificate.get("subjectAltName", ())
        if kind == "DNS"
    }
    if expected_identity not in names:
        raise MutualTLSTransportError(
            f"peer certificate does not contain expected DNS identity {expected_identity!r}"
        )


def connect_mutual_tls(
    host: str,
    port: int,
    local_endpoint: str,
    peer_endpoint: str,
    context: ssl.SSLContext,
    *,
    server_hostname: str,
    timeout: float = 5.0,
    handshake_timeout: float = 5.0,
    max_frame_size: int = 1 << 20,
    send_timeout: float = 5.0,
) -> SocketTransport:
    """Mathematics: establish authenticated stream S only if CA/path, server hostname, client certificate, and TLS policy verify."""

    _validate_context(context, server_side=False)
    if not server_hostname:
        raise MutualTLSTransportError("server_hostname is required for authenticated TLS")
    if timeout <= 0 or handshake_timeout <= 0:
        raise MutualTLSTransportError("TCP and TLS handshake timeouts must be positive")
    raw_socket: socket.socket | None = None
    tls_socket: ssl.SSLSocket | None = None
    try:
        raw_socket = socket.create_connection((host, int(port)), timeout=float(timeout))
        raw_socket.settimeout(float(handshake_timeout))
        tls_socket = context.wrap_socket(
            raw_socket,
            server_hostname=server_hostname,
            do_handshake_on_connect=True,
        )
        _validate_negotiated_peer(tls_socket)
        return SocketTransport(
            tls_socket,
            local_endpoint,
            peer_endpoint,
            max_frame_size=max_frame_size,
            send_timeout=send_timeout,
        )
    except Exception as exc:
        if tls_socket is not None:
            tls_socket.close()
        elif raw_socket is not None:
            raw_socket.close()
        if isinstance(exc, MutualTLSTransportError):
            raise
        raise MutualTLSTransportError(f"mutually authenticated TLS connection failed: {exc}") from exc


def accept_mutual_tls(
    listener: socket.socket | SocketListener,
    local_endpoint: str,
    peer_endpoint: str,
    context: ssl.SSLContext,
    *,
    expected_peer_dns: str,
    handshake_timeout: float = 5.0,
    max_frame_size: int = 1 << 20,
    send_timeout: float = 5.0,
) -> SocketTransport:
    """Mathematics: accept authenticated stream S only if client chain verifies and SAN_DNS contains expected_peer_dns."""

    _validate_context(context, server_side=True)
    if not isinstance(listener, (socket.socket, SocketListener)):
        raise TypeError("listener must be a SocketListener or socket.socket")
    if handshake_timeout <= 0:
        raise MutualTLSTransportError("TLS handshake timeout must be positive")
    raw_socket: socket.socket | None = None
    tls_socket: ssl.SSLSocket | None = None
    try:
        raw_socket, _address = (
            listener.accept_raw()
            if isinstance(listener, SocketListener)
            else listener.accept()
        )
        raw_socket.settimeout(float(handshake_timeout))
        tls_socket = context.wrap_socket(
            raw_socket,
            server_side=True,
            do_handshake_on_connect=True,
        )
        _validate_negotiated_peer(tls_socket)
        certificate = tls_socket.getpeercert()
        _require_dns_identity(certificate, expected_peer_dns)
        return SocketTransport(
            tls_socket,
            local_endpoint,
            peer_endpoint,
            max_frame_size=max_frame_size,
            send_timeout=send_timeout,
        )
    except Exception as exc:
        if tls_socket is not None:
            tls_socket.close()
        elif raw_socket is not None:
            raw_socket.close()
        if isinstance(exc, MutualTLSTransportError):
            raise
        raise MutualTLSTransportError(f"mutually authenticated TLS accept failed: {exc}") from exc
