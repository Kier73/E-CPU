"""Supervised, mutually authenticated service for one recovery-lineage authority."""

from __future__ import annotations

import argparse
import json
import signal
import socket
import ssl
import threading
import time
from pathlib import Path
from typing import Sequence

from .mtls_transport import MutualTLSTransportError, accept_mutual_tls
from .recovery_lineage_transport import (
    RecoveryLineageProcessParticipant,
    RecoveryLineageTransportError,
)
from .reliability import ReliabilityPolicy
from .seed_commit_quorum import SeedCommitMembership
from .socket_transport import SocketTransport, SocketTransportError


class RecoveryLineageAuthorityService:
    """One fixed non-owner authority process with TLS-authenticated reconnect support."""

    def __init__(
        self,
        membership: SeedCommitMembership,
        member_id: str,
        journal_path: str | Path,
        listener: socket.socket,
        tls_context: ssl.SSLContext,
        *,
        expected_owner_dns: str,
        policy: ReliabilityPolicy | None = None,
        handshake_timeout: float = 5.0,
        poll_interval: float = 0.002,
        rejection_backoff: float = 0.05,
    ) -> None:
        """Mathematics: bind one journal J and member identity m to a listener accepting only the configured owner's mutually authenticated TLS stream."""

        if not isinstance(membership, SeedCommitMembership):
            raise ValueError("authority service requires fixed seed-commit membership")
        if not isinstance(member_id, str) or member_id not in membership.member_ids:
            raise ValueError("authority service member must belong to fixed membership")
        if member_id == membership.owner_id:
            raise ValueError("authority service hosts non-owner members only")
        if not isinstance(listener, socket.socket):
            raise TypeError("authority service listener must be a socket")
        if not isinstance(tls_context, ssl.SSLContext):
            raise TypeError("authority service requires a server SSLContext")
        if (
            not isinstance(expected_owner_dns, str)
            or not expected_owner_dns
            or expected_owner_dns.strip() != expected_owner_dns
        ):
            raise ValueError("expected owner DNS identity must be non-empty trimmed text")
        for value, name in (
            (handshake_timeout, "handshake timeout"),
            (poll_interval, "poll interval"),
            (rejection_backoff, "rejection backoff"),
        ):
            if (
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or value <= 0
            ):
                raise ValueError(f"{name} must be positive")
        self.membership = membership
        self.member_id = member_id
        self.journal_path = Path(journal_path)
        self.listener = listener
        self.tls_context = tls_context
        self.expected_owner_dns = expected_owner_dns
        self.policy = policy
        self.handshake_timeout = float(handshake_timeout)
        self.poll_interval = float(poll_interval)
        self.rejection_backoff = float(rejection_backoff)
        self._stop_event = threading.Event()
        self._active_lock = threading.Lock()
        self._active_transport: SocketTransport | None = None
        self._serving = False
        self.accepted_connections = 0
        self.rejected_connections = 0

    @property
    def address(self) -> tuple[str, int]:
        """Mathematics: expose the listener's bound address without changing service state."""

        host, port = self.listener.getsockname()[:2]
        return str(host), int(port)

    @property
    def stopped(self) -> bool:
        """Mathematics: project the service stop latch as a read-only Boolean state."""

        return self._stop_event.is_set()

    def stop(self) -> None:
        """Mathematics: set the stop latch and close both the listener and any active authenticated stream."""

        self._stop_event.set()
        with self._active_lock:
            active = self._active_transport
        if active is not None:
            active.close()
        try:
            self.listener.close()
        except OSError:
            pass

    def serve_forever(self) -> None:
        """Mathematics: repeatedly authenticate one owner stream, serve its durable ledger, and return to accept after disconnect."""

        if self._serving:
            raise RuntimeError("authority service may only be served once")
        self._serving = True
        try:
            while not self._stop_event.is_set():
                try:
                    transport = accept_mutual_tls(
                        self.listener,
                        self.member_id,
                        self.membership.owner_id,
                        self.tls_context,
                        expected_peer_dns=self.expected_owner_dns,
                        handshake_timeout=self.handshake_timeout,
                    )
                except MutualTLSTransportError:
                    if self._stop_event.is_set():
                        break
                    self.rejected_connections += 1
                    self._stop_event.wait(self.rejection_backoff)
                    continue

                self.accepted_connections += 1
                with self._active_lock:
                    self._active_transport = transport
                try:
                    participant = RecoveryLineageProcessParticipant(
                        self.membership,
                        self.member_id,
                        self.journal_path,
                        transport,
                        policy=self.policy,
                    )
                    while not self._stop_event.is_set() and not transport.closed:
                        try:
                            participant.service_once()
                        except (RecoveryLineageTransportError, SocketTransportError):
                            break
                        if transport.closed:
                            break
                        self._stop_event.wait(self.poll_interval)
                finally:
                    transport.close()
                    with self._active_lock:
                        if self._active_transport is transport:
                            self._active_transport = None
        finally:
            self.stop()


def _build_server_context(
    certificate: Path,
    private_key: Path,
    client_ca: Path,
) -> ssl.SSLContext:
    """Mathematics: construct a TLS server context that requires a CA-verified client certificate at TLS 1.2 or newer."""

    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(certfile=str(certificate), keyfile=str(private_key))
    context.load_verify_locations(cafile=str(client_ca))
    context.verify_mode = ssl.CERT_REQUIRED
    return context


def build_parser() -> argparse.ArgumentParser:
    """Mathematics: define the complete command-line configuration domain for one supervised authority member."""

    parser = argparse.ArgumentParser(
        description="Run one mutually authenticated recovery-lineage authority service."
    )
    parser.add_argument("--membership", type=Path, required=True)
    parser.add_argument("--member-id", required=True)
    parser.add_argument("--journal", type=Path, required=True)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--certificate", type=Path, required=True)
    parser.add_argument("--private-key", type=Path, required=True)
    parser.add_argument("--client-ca", type=Path, required=True)
    parser.add_argument("--expected-owner-dns", required=True)
    parser.add_argument("--handshake-timeout", type=float, default=5.0)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Mathematics: load one fixed membership and TLS identity, then serve until the process supervisor requests termination."""

    arguments = build_parser().parse_args(argv)
    if not 1 <= arguments.port <= 65535:
        raise ValueError("port must be between 1 and 65535")
    membership = SeedCommitMembership.from_snapshot(
        json.loads(arguments.membership.read_text(encoding="utf-8"))
    )
    context = _build_server_context(
        arguments.certificate,
        arguments.private_key,
        arguments.client_ca,
    )
    listener = SocketTransport.listen(arguments.host, arguments.port)
    service = RecoveryLineageAuthorityService(
        membership,
        arguments.member_id,
        arguments.journal,
        listener,
        context,
        expected_owner_dns=arguments.expected_owner_dns,
        handshake_timeout=arguments.handshake_timeout,
    )

    previous_handlers: dict[int, object] = {}

    def request_stop(signum: int, frame: object) -> None:
        """Mathematics: map SIGINT or SIGTERM to the service's monotonic stop transition."""

        service.stop()

    for selected_signal in (signal.SIGINT, signal.SIGTERM):
        previous_handlers[selected_signal] = signal.getsignal(selected_signal)
        signal.signal(selected_signal, request_stop)
    try:
        service.serve_forever()
    finally:
        service.stop()
        for selected_signal, previous in previous_handlers.items():
            signal.signal(selected_signal, previous)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
