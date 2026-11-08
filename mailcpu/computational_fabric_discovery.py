"""Restart-aware direct-peer discovery and receiver-local lease refresh."""

from __future__ import annotations

import hashlib
import json
import math
import ssl
import threading
import time
from dataclasses import dataclass, replace
from typing import Any, Callable, Mapping

from .computational_fabric import (
    ComputationalFabricAuthority,
    ComputationalFabricDirectory,
    ComputationalFabricPeerClient,
    ComputationalFabricPeerServer,
    ComputationalPeerEndpoint,
)
from .reliability import ReliabilityPolicy
from .socket_transport import SocketListener


class ComputationalFabricDiscoveryError(RuntimeError):
    """Raised when discovery bootstrap state or service lifecycle is invalid."""


def _canonical_digest(value: Mapping[str, Any]) -> str:
    """Mathematics: Bind an immutable discovery bootstrap description to canonical JSON bytes."""
    encoded = json.dumps(
        dict(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _positive_seconds(value: float, field: str, *, maximum: float = 3600.0) -> float:
    """Mathematics: Validate a finite positive duration within the field-specific maximum."""
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or value <= 0
        or value > maximum
        or not math.isfinite(float(value))
    ):
        raise ComputationalFabricDiscoveryError(
            f"{field} must be positive and no greater than {maximum:g} seconds"
        )
    return float(value)


@dataclass(frozen=True)
class ComputationalFabricPeerRefresh:
    """One peer's authenticated refresh outcome, without exposing transport objects."""

    peer_id: str
    connected: bool
    refreshed: bool
    changed: bool
    active: bool
    revision: int | None
    snapshot_digest: str | None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Mathematics: Return a detached telemetry projection; monotonic lease deadlines remain local."""
        return {
            "peer_id": self.peer_id,
            "connected": self.connected,
            "refreshed": self.refreshed,
            "changed": self.changed,
            "active": self.active,
            "revision": self.revision,
            "snapshot_digest": self.snapshot_digest,
            "error": self.error,
        }


class ComputationalFabricPeerListener:
    """Reaccept direct mutual-TLS directory clients after transport loss or client restart."""

    def __init__(
        self,
        authority: ComputationalFabricAuthority,
        listener: SocketListener,
        client_peer_id: str,
        *,
        expected_client_dns: str,
        tls_context: ssl.SSLContext,
        policy: ReliabilityPolicy | None = None,
        handshake_timeout: float = 5.0,
        idle_sleep: float = 0.002,
    ) -> None:
        if not isinstance(authority, ComputationalFabricAuthority):
            raise ComputationalFabricDiscoveryError(
                "peer listener requires a ComputationalFabricAuthority"
            )
        if not isinstance(listener, SocketListener):
            raise ComputationalFabricDiscoveryError("peer listener requires a SocketListener transport handle")
        if not isinstance(tls_context, ssl.SSLContext):
            raise ComputationalFabricDiscoveryError("peer listener requires a server SSLContext")
        if not isinstance(client_peer_id, str) or not client_peer_id:
            raise ComputationalFabricDiscoveryError("client_peer_id must be non-empty")
        if policy is not None and not isinstance(policy, ReliabilityPolicy):
            raise ComputationalFabricDiscoveryError("policy must be a ReliabilityPolicy")
        self.authority = authority
        self.listener = listener
        self.client_peer_id = client_peer_id
        self.expected_client_dns = expected_client_dns
        self.tls_context = tls_context
        self.policy = policy
        self.handshake_timeout = _positive_seconds(
            handshake_timeout,
            "handshake_timeout",
            maximum=120.0,
        )
        self.idle_sleep = _positive_seconds(idle_sleep, "idle_sleep", maximum=5.0)
        self._closed = False
        self._lock = threading.RLock()
        self._active_server: ComputationalFabricPeerServer | None = None

    def serve_forever(
        self,
        stop_event: threading.Event,
        *,
        on_session: Callable[[ComputationalFabricPeerServer], None] | None = None,
        on_error: Callable[[Exception], None] | None = None,
    ) -> None:
        """Mathematics: Accept authenticated sessions serially and rebuild reliable channels for every new stream."""
        if not isinstance(stop_event, threading.Event):
            raise ComputationalFabricDiscoveryError("stop_event must be a threading.Event")
        if on_session is not None and not callable(on_session):
            raise ComputationalFabricDiscoveryError("on_session must be callable")
        if on_error is not None and not callable(on_error):
            raise ComputationalFabricDiscoveryError("on_error must be callable")
        if self._closed:
            raise ComputationalFabricDiscoveryError("peer listener is closed")

        try:
            self.listener.settimeout(0.25)
        except OSError as exc:
            raise ComputationalFabricDiscoveryError(
                f"peer listener cannot set a bounded accept timeout: {exc}"
            ) from exc
        while not stop_event.is_set():
            with self._lock:
                if self._closed:
                    return
            try:
                server = ComputationalFabricPeerServer.accept_mutual_tls(
                    self.authority,
                    self.listener,
                    self.client_peer_id,
                    expected_client_dns=self.expected_client_dns,
                    tls_context=self.tls_context,
                    policy=self.policy,
                    handshake_timeout=self.handshake_timeout,
                )
            except Exception:
                with self._lock:
                    closed = self._closed
                if stop_event.is_set() or closed or self.listener.fileno() < 0:
                    return
                # Rejected handshakes and bounded accept timeouts do not become
                # directory observations; a later client may authenticate.
                stop_event.wait(0.05)
                continue

            with self._lock:
                if self._closed or stop_event.is_set():
                    server.close()
                    return
                self._active_server = server
            try:
                if on_session is not None:
                    try:
                        on_session(server)
                    except Exception as exc:
                        if on_error is not None and not stop_event.is_set():
                            on_error(exc)
                        continue
                while not stop_event.is_set() and not server.transport.closed:
                    try:
                        serviced = server.service_once()
                    except Exception as exc:
                        with self._lock:
                            closed = self._closed
                        if (
                            on_error is not None
                            and not stop_event.is_set()
                            and not closed
                            and not server.transport.closed
                        ):
                            on_error(exc)
                        break
                    if not serviced:
                        stop_event.wait(self.idle_sleep)
            finally:
                server.close()
                with self._lock:
                    if self._active_server is server:
                        self._active_server = None

    def close(self) -> None:
        """Mathematics: Close the listener and any active authenticated session."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            server = self._active_server
            self._active_server = None
        if server is not None:
            try:
                server.close()
            except Exception:
                pass
        try:
            self.listener.close()
        except OSError:
            pass


class ComputationalFabricDiscoveryService:
    """Maintain direct mutual-TLS observations and reacquire leases after restart."""

    SNAPSHOT_SCHEMA = "mailcpu.computational-fabric-discovery-service.v1"

    def __init__(
        self,
        directory: ComputationalFabricDirectory,
        peer_endpoints: Mapping[str, ComputationalPeerEndpoint],
        tls_context: ssl.SSLContext,
        *,
        timeout: float = 3.0,
        refresh_interval: float = 10.0,
        policy: ReliabilityPolicy | None = None,
    ) -> None:
        if not isinstance(directory, ComputationalFabricDirectory):
            raise ComputationalFabricDiscoveryError(
                "discovery service requires a ComputationalFabricDirectory"
            )
        if not isinstance(peer_endpoints, Mapping):
            raise ComputationalFabricDiscoveryError(
                "peer_endpoints must map trusted peer IDs to typed endpoints"
            )
        if not isinstance(tls_context, ssl.SSLContext):
            raise ComputationalFabricDiscoveryError(
                "discovery service requires a client SSLContext"
            )
        trust = directory.trusted_peers
        endpoints: dict[str, ComputationalPeerEndpoint] = {}
        for peer_id, endpoint in peer_endpoints.items():
            if not isinstance(peer_id, str) or not isinstance(endpoint, ComputationalPeerEndpoint):
                raise ComputationalFabricDiscoveryError(
                    "every discovery endpoint must be a typed ComputationalPeerEndpoint"
                )
            if peer_id == directory.local_peer_id or endpoint.peer_id != peer_id:
                raise ComputationalFabricDiscoveryError(
                    "discovery endpoint identity must match a non-local peer key"
                )
            if trust.get(peer_id) != endpoint.tls_server_name:
                raise ComputationalFabricDiscoveryError(
                    "discovery endpoint DNS identity differs from the directory trust map"
                )
            if peer_id in endpoints:
                raise ComputationalFabricDiscoveryError("discovery peer IDs must be unique")
            endpoints[peer_id] = endpoint
        if not endpoints:
            raise ComputationalFabricDiscoveryError(
                "discovery service requires at least one configured direct peer"
            )

        self.directory = directory
        self._peer_endpoints = dict(sorted(endpoints.items()))
        self._tls_context = tls_context
        self.timeout = _positive_seconds(timeout, "timeout", maximum=120.0)
        self.refresh_interval = _positive_seconds(
            refresh_interval,
            "refresh_interval",
            maximum=3600.0,
        )
        if policy is not None and not isinstance(policy, ReliabilityPolicy):
            raise ComputationalFabricDiscoveryError("policy must be a ReliabilityPolicy")
        self.policy = policy
        self._clients: dict[str, ComputationalFabricPeerClient] = {}
        self._lock = threading.RLock()
        self._closed = False

    @property
    def configured_peer_ids(self) -> tuple[str, ...]:
        """Mathematics: Expose deterministic direct-peer bootstrap identities."""
        return tuple(self._peer_endpoints)

    @property
    def connected_peer_ids(self) -> tuple[str, ...]:
        """Mathematics: Expose peers with currently open local client transports."""
        with self._lock:
            return tuple(
                peer_id
                for peer_id, client in sorted(self._clients.items())
                if not client.transport.closed
            )

    def bootstrap_snapshot(self) -> dict[str, Any]:
        """Mathematics: Persist restart inputs only; directory anti-rollback state is stored separately."""
        with self._lock:
            if self._closed:
                raise ComputationalFabricDiscoveryError("discovery service is closed")
            payload: dict[str, Any] = {
                "schema": self.SNAPSHOT_SCHEMA,
                "local_peer_id": self.directory.local_peer_id,
                "peer_endpoints": [
                    endpoint.to_dict()
                    for endpoint in self._peer_endpoints.values()
                ],
                "timeout": self.timeout,
                "refresh_interval": self.refresh_interval,
            }
            payload["digest"] = _canonical_digest(payload)
            return payload

    @classmethod
    def from_bootstrap_snapshot(
        cls,
        payload: Mapping[str, Any],
        directory: ComputationalFabricDirectory,
        tls_context: ssl.SSLContext,
        *,
        policy: ReliabilityPolicy | None = None,
    ) -> "ComputationalFabricDiscoveryService":
        """Mathematics: Rebuild the service from trusted bootstrap data without restoring old TLS streams."""
        expected = {
            "schema",
            "local_peer_id",
            "peer_endpoints",
            "timeout",
            "refresh_interval",
            "digest",
        }
        if not isinstance(payload, Mapping) or set(payload) != expected:
            raise ComputationalFabricDiscoveryError(
                "discovery bootstrap snapshot fields are malformed"
            )
        if payload["schema"] != cls.SNAPSHOT_SCHEMA:
            raise ComputationalFabricDiscoveryError(
                "discovery bootstrap snapshot schema is unsupported"
            )
        digest = payload["digest"]
        if not isinstance(digest, str) or len(digest) != 64:
            raise ComputationalFabricDiscoveryError("discovery bootstrap digest is malformed")
        unsigned = {key: value for key, value in payload.items() if key != "digest"}
        if _canonical_digest(unsigned) != digest:
            raise ComputationalFabricDiscoveryError(
                "discovery bootstrap digest does not match its content"
            )
        if payload["local_peer_id"] != directory.local_peer_id:
            raise ComputationalFabricDiscoveryError(
                "discovery bootstrap local peer differs from the restored directory"
            )
        raw_endpoints = payload["peer_endpoints"]
        if not isinstance(raw_endpoints, (list, tuple)):
            raise ComputationalFabricDiscoveryError("discovery peer endpoint list is malformed")
        endpoints: dict[str, ComputationalPeerEndpoint] = {}
        previous_peer_id: str | None = None
        for raw in raw_endpoints:
            endpoint = ComputationalPeerEndpoint.from_dict(raw)
            if previous_peer_id is not None and endpoint.peer_id <= previous_peer_id:
                raise ComputationalFabricDiscoveryError(
                    "discovery endpoints must be unique and canonically ordered"
                )
            previous_peer_id = endpoint.peer_id
            endpoints[endpoint.peer_id] = endpoint
        return cls(
            directory,
            endpoints,
            tls_context,
            timeout=payload["timeout"],
            refresh_interval=payload["refresh_interval"],
            policy=policy,
        )

    def _last_known(self, peer_id: str) -> tuple[int | None, str | None]:
        """Mathematics: Return the observed peer revision and digest, or absent markers."""
        for snapshot in self.directory.peer_snapshots:
            if snapshot.peer_id == peer_id:
                return snapshot.revision, snapshot.digest
        return None, None

    def refresh_peer(self, peer_id: str) -> ComputationalFabricPeerRefresh:
        """Mathematics: Connect or reuse a direct TLS peer, fetch its latest snapshot, then renew the local lease."""
        if not isinstance(peer_id, str) or peer_id not in self._peer_endpoints:
            raise ComputationalFabricDiscoveryError(
                f"peer is not in the configured direct-peer set: {peer_id!r}"
            )
        with self._lock:
            if self._closed:
                raise ComputationalFabricDiscoveryError("discovery service is closed")
            client = self._clients.get(peer_id)
            if client is not None and client.transport.closed:
                self._clients.pop(peer_id, None)
                client = None
            try:
                if client is None:
                    client = ComputationalFabricPeerClient.connect_mutual_tls(
                        self.directory.local_peer_id,
                        self._peer_endpoints[peer_id],
                        self._tls_context,
                        timeout=self.timeout,
                        policy=self.policy,
                    )
                    self._clients[peer_id] = client
                previous_revision, previous_digest = self._last_known(peer_id)
                client.refresh(self.directory)
                revision, snapshot_digest = self._last_known(peer_id)
                changed = (previous_revision, previous_digest) != (revision, snapshot_digest)
                active = any(
                    item.peer_id == peer_id
                    for item in self.directory.active_snapshots
                )
                return ComputationalFabricPeerRefresh(
                    peer_id=peer_id,
                    connected=True,
                    refreshed=True,
                    changed=changed,
                    active=active,
                    revision=revision,
                    snapshot_digest=snapshot_digest,
                )
            except Exception as exc:
                failed = self._clients.pop(peer_id, None)
                if failed is not None:
                    failed.close()
                revision, snapshot_digest = self._last_known(peer_id)
                active = any(
                    item.peer_id == peer_id
                    for item in self.directory.active_snapshots
                )
                return ComputationalFabricPeerRefresh(
                    peer_id=peer_id,
                    connected=False,
                    refreshed=False,
                    changed=False,
                    active=active,
                    revision=revision,
                    snapshot_digest=snapshot_digest,
                    error=f"{type(exc).__name__}: {exc}"[:512],
                )

    def refresh_all(self) -> tuple[ComputationalFabricPeerRefresh, ...]:
        """Mathematics: Refresh configured peers in stable order and purge only leases already expired locally."""
        with self._lock:
            if self._closed:
                raise ComputationalFabricDiscoveryError("discovery service is closed")
            reports = [
                self.refresh_peer(peer_id)
                for peer_id in self._peer_endpoints
            ]
            self.directory.purge_expired()
            active = {
                item.peer_id
                for item in self.directory.active_snapshots
            }
            return tuple(
                replace(report, active=report.peer_id in active)
                for report in reports
            )

    def serve_forever(
        self,
        stop_event: threading.Event,
        *,
        on_cycle: Callable[[tuple[ComputationalFabricPeerRefresh, ...]], None] | None = None,
    ) -> None:
        """Mathematics: Refresh all direct peers at the configured cadence until stopped or closed."""
        if not isinstance(stop_event, threading.Event):
            raise ComputationalFabricDiscoveryError("stop_event must be a threading.Event")
        if on_cycle is not None and not callable(on_cycle):
            raise ComputationalFabricDiscoveryError("on_cycle must be callable")
        while not stop_event.is_set():
            with self._lock:
                if self._closed:
                    return
            reports = self.refresh_all()
            if on_cycle is not None:
                on_cycle(reports)
            if stop_event.wait(self.refresh_interval):
                return

    def close(self) -> None:
        """Mathematics: Drop every ephemeral authenticated stream; caller persists directory state separately."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            clients = tuple(self._clients.values())
            self._clients.clear()
        for client in clients:
            try:
                client.close()
            except Exception:
                pass
