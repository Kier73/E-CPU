"""Restart-aware direct-peer discovery and receiver-local lease refresh."""

from __future__ import annotations

import hashlib
import json
import ssl
import threading
import time
from dataclasses import dataclass, replace
from typing import Any, Callable, Mapping

from .computational_fabric import (
    ComputationalFabricDirectory,
    ComputationalFabricError,
    ComputationalFabricPeerClient,
    ComputationalPeerEndpoint,
)
from .reliability import ReliabilityPolicy


class ComputationalFabricDiscoveryError(RuntimeError):
    """Raised when discovery bootstrap state or service lifecycle is invalid."""


def _canonical_digest(value: Mapping[str, Any]) -> str:
    """Bind an immutable discovery bootstrap description to canonical JSON bytes."""
    encoded = json.dumps(
        dict(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _positive_seconds(value: float, field: str, *, maximum: float = 3600.0) -> float:
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or value <= 0
        or value > maximum
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
        """Return a detached telemetry projection; monotonic lease deadlines remain local."""
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
        """Expose deterministic direct-peer bootstrap identities."""
        return tuple(self._peer_endpoints)

    @property
    def connected_peer_ids(self) -> tuple[str, ...]:
        """Expose peers with currently open local client transports."""
        with self._lock:
            return tuple(
                peer_id
                for peer_id, client in sorted(self._clients.items())
                if not client.transport.closed
            )

    def bootstrap_snapshot(self) -> dict[str, Any]:
        """Persist restart inputs only; directory anti-rollback state is stored separately."""
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
        """Rebuild the service from trusted bootstrap data without restoring old TLS streams."""
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
        for snapshot in self.directory.peer_snapshots:
            if snapshot.peer_id == peer_id:
                return snapshot.revision, snapshot.digest
        return None, None

    def refresh_peer(self, peer_id: str) -> ComputationalFabricPeerRefresh:
        """Connect or reuse a direct TLS peer, fetch its latest snapshot, then renew the local lease."""
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
                changed = client.refresh(self.directory)
                revision, snapshot_digest = self._last_known(peer_id)
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
        """Refresh configured peers in stable order and purge only leases already expired locally."""
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
        """Refresh all direct peers at the configured cadence until stopped or closed."""
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
        """Drop every ephemeral authenticated stream; caller persists directory state separately."""
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
