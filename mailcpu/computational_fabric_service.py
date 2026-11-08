"""Durable local peer advertisements and a restartable mutual-TLS fabric peer service."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
from pathlib import Path
import signal
import ssl
import threading
from typing import Any, Mapping, Sequence
import uuid

from .computational_fabric import (
    ComputationalFabricAuthority,
    ComputationalFabricError,
    ComputationalPeerEndpoint,
    ComputationalPeerSnapshot,
)
from .computational_fabric_discovery import ComputationalFabricPeerListener
from .socket_transport import SocketTransport
from .subprocess_service import publish_service_ready


class ComputationalFabricAuthorityStoreError(RuntimeError):
    """A local peer-authority snapshot could not be durably stored or verified."""


class ComputationalFabricAuthorityStore:
    """Atomically persist peer-owned portable advertisements, never runtime capabilities or TLS material."""

    SCHEMA = "mailcpu.computational-fabric-authority-store.v1"
    MAX_BYTES = 8 << 20

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        if not self.path.name:
            raise ComputationalFabricAuthorityStoreError("authority store path must name a file")

    @staticmethod
    def _canonical_digest(payload: Mapping[str, Any]) -> str:
        try:
            encoded = json.dumps(
                dict(payload),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            ).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise ComputationalFabricAuthorityStoreError(
                f"authority snapshot is not canonical JSON: {exc}"
            ) from exc
        return hashlib.sha256(encoded).hexdigest()

    def save(self, snapshot: ComputationalPeerSnapshot) -> str:
        if not isinstance(snapshot, ComputationalPeerSnapshot):
            raise ComputationalFabricAuthorityStoreError(
                "authority store accepts ComputationalPeerSnapshot values only"
            )
        unsigned = {"schema": self.SCHEMA, "snapshot": snapshot.to_dict()}
        payload = {**unsigned, "digest": self._canonical_digest(unsigned)}
        encoded = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8") + b"\n"
        if len(encoded) > self.MAX_BYTES:
            raise ComputationalFabricAuthorityStoreError("authority snapshot exceeds its byte bound")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.{uuid.uuid4().hex}.tmp")
        descriptor: int | None = None
        try:
            descriptor = os.open(
                str(temporary),
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                0o600,
            )
            with os.fdopen(descriptor, "wb") as stream:
                descriptor = None
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
            try:
                directory_fd = os.open(str(self.path.parent), os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            except OSError:
                pass
        except OSError as exc:
            raise ComputationalFabricAuthorityStoreError(
                f"could not atomically persist peer authority: {exc}"
            ) from exc
        finally:
            if descriptor is not None:
                os.close(descriptor)
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
        return snapshot.digest

    def load(self, *, expected_peer_id: str | None = None) -> ComputationalPeerSnapshot:
        try:
            size = self.path.stat().st_size
            if size <= 0 or size > self.MAX_BYTES:
                raise ComputationalFabricAuthorityStoreError(
                    "authority store file size is outside its accepted bound"
                )
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except ComputationalFabricAuthorityStoreError:
            raise
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ComputationalFabricAuthorityStoreError(
                f"could not read peer authority snapshot: {exc}"
            ) from exc
        expected = {"schema", "snapshot", "digest"}
        if not isinstance(payload, dict) or set(payload) != expected:
            raise ComputationalFabricAuthorityStoreError("authority store fields are malformed")
        if payload["schema"] != self.SCHEMA:
            raise ComputationalFabricAuthorityStoreError("authority store schema is unsupported")
        digest = payload["digest"]
        unsigned = {"schema": payload["schema"], "snapshot": payload["snapshot"]}
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or not hmac.compare_digest(self._canonical_digest(unsigned), digest)
        ):
            raise ComputationalFabricAuthorityStoreError("authority store digest does not match its content")
        try:
            snapshot = ComputationalPeerSnapshot.from_dict(payload["snapshot"])
        except (ComputationalFabricError, TypeError, ValueError) as exc:
            raise ComputationalFabricAuthorityStoreError(
                f"stored peer authority snapshot is invalid: {exc}"
            ) from exc
        if expected_peer_id is not None and snapshot.peer_id != expected_peer_id:
            raise ComputationalFabricAuthorityStoreError(
                "stored peer authority identity differs from the configured service identity"
            )
        return snapshot

    def open_authority(
        self,
        endpoint: ComputationalPeerEndpoint,
        *,
        lease_seconds: int = 60,
    ) -> ComputationalFabricAuthority:
        """Open a durable peer authority; each successful mutation fsyncs the new revision before returning."""

        if not isinstance(endpoint, ComputationalPeerEndpoint):
            raise ComputationalFabricAuthorityStoreError("open_authority requires a typed peer endpoint")
        if self.path.exists():
            snapshot = self.load(expected_peer_id=endpoint.peer_id)
            if snapshot.endpoint != endpoint:
                raise ComputationalFabricAuthorityStoreError(
                    "stored peer endpoint differs from configured endpoint identity"
                )
            return ComputationalFabricAuthority.from_snapshot(
                snapshot,
                on_snapshot=self.save,
            )
        authority = ComputationalFabricAuthority(
            endpoint,
            lease_seconds=lease_seconds,
            on_snapshot=self.save,
        )
        self.save(authority.snapshot())
        return authority


def _server_context(certificate: Path, private_key: Path, client_ca: Path) -> ssl.SSLContext:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(str(certificate), str(private_key))
    context.load_verify_locations(cafile=str(client_ca))
    context.verify_mode = ssl.CERT_REQUIRED
    return context


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run one restartable, mutually authenticated computational-fabric peer service."
    )
    parser.add_argument("--snapshot-store", type=Path, required=True)
    parser.add_argument("--peer-id", required=True)
    parser.add_argument("--bind-host", default="0.0.0.0")
    parser.add_argument("--listen-port", type=int, required=True)
    parser.add_argument("--client-peer-id", required=True)
    parser.add_argument("--expected-client-dns", required=True)
    parser.add_argument("--certificate", type=Path, required=True)
    parser.add_argument("--private-key", type=Path, required=True)
    parser.add_argument("--client-ca", type=Path, required=True)
    parser.add_argument("--handshake-timeout", type=float, default=5.0)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    if not 1 <= arguments.listen_port <= 65535:
        raise ValueError("listen port must be between 1 and 65535")
    if arguments.handshake_timeout <= 0 or arguments.handshake_timeout > 120:
        raise ValueError("handshake timeout must be positive and at most 120 seconds")

    store = ComputationalFabricAuthorityStore(arguments.snapshot_store)
    snapshot = store.load(expected_peer_id=arguments.peer_id)
    # --listen-port is the independently managed discovery/control endpoint.
    # The peer snapshot continues to advertise the data-plane forwarding port.
    authority = ComputationalFabricAuthority.from_snapshot(
        snapshot,
        on_snapshot=store.save,
    )
    context = _server_context(
        arguments.certificate,
        arguments.private_key,
        arguments.client_ca,
    )
    listener_socket = SocketTransport.listen(arguments.bind_host, arguments.listen_port)
    listener = ComputationalFabricPeerListener(
        authority,
        listener_socket,
        arguments.client_peer_id,
        expected_client_dns=arguments.expected_client_dns,
        tls_context=context,
        handshake_timeout=arguments.handshake_timeout,
    )
    stop_event = threading.Event()
    previous_handlers: dict[int, Any] = {}

    def request_stop(_signum: int, _frame: Any) -> None:
        stop_event.set()
        listener.close()

    for selected_signal in (signal.SIGINT, signal.SIGTERM):
        previous_handlers[selected_signal] = signal.getsignal(selected_signal)
        signal.signal(selected_signal, request_stop)
    try:
        publish_service_ready(
            {
                "peer_id": snapshot.peer_id,
                "revision": snapshot.revision,
                "snapshot_digest": snapshot.digest,
                "bind_host": arguments.bind_host,
                "port": arguments.listen_port,
                "control_port": arguments.listen_port,
                "forwarding_host": snapshot.endpoint.endpoint_host,
                "forwarding_port": snapshot.endpoint.port,
                "accepts_peer_id": arguments.client_peer_id,
            }
        )
        listener.serve_forever(stop_event)
    finally:
        stop_event.set()
        listener.close()
        for selected_signal, previous in previous_handlers.items():
            signal.signal(selected_signal, previous)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
