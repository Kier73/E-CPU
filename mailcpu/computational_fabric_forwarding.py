"""Authenticated, hop-by-hop forwarding for non-authoritative computational routes."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import json
import threading
import time
from typing import Any

from .classifier import (
    HypervisorAction,
    HypervisorArbitrationEvent,
    HypervisorDomain,
    HypervisorExecutionResult,
    HypervisorRequest,
)
from .computational_execution import ComputationalExecutionAdmissionCoordinator
from .computational_fabric import (
    ComputationalFabricDirectory,
    ComputationalFabricRouteWitness,
    ComputationalPeerEndpoint,
    _certificate_has_dns,
)
from .computational_resolver import (
    ComputationalAddress,
    ComputationalAddressResolver,
    ComputationalHostCatalogue,
)
from .headless import HeadlessOS
from .hypervisor_transport import (
    HypervisorOperationChannel,
    HypervisorOperationResultChannel,
)
from .mtls_transport import accept_mutual_tls, connect_mutual_tls
from .reliability import ReliabilityPolicy, ReliableChannel
from .socket_transport import SocketTransport


COMPUTATIONAL_FABRIC_FORWARD_OPERATION = "forward network packet for federated computation"
COMPUTATIONAL_FABRIC_FORWARD_RESOURCE = "/network/computational-fabric/forward"
COMPUTATIONAL_FABRIC_EXECUTE_OPERATION = "receive network request for local computational execution"
COMPUTATIONAL_FABRIC_EXECUTE_RESOURCE = "/network/computational-fabric/execute"
COMPUTATIONAL_FABRIC_FORWARD_RESULT_KIND = "mailcpu.computational_fabric.hop_receipt"
_FORWARD_CHANNEL_PREFIX = "computational.fabric.forward.v1."
_RESPONSE_SUFFIX = ".result"
_MAX_FORWARD_HOPS = 16
_DEFAULT_MAX_PAYLOAD_BYTES = 1_048_576


class ComputationalFabricForwardingError(ValueError):
    """A federated forwarding envelope, authenticated hop, or execution receipt is invalid."""


def _text(value: Any, name: str, maximum: int = 256) -> str:
    """Mathematics: Require one finite, trimmed UTF-8 identity label."""
    if (
        not isinstance(value, str)
        or not value
        or value.strip() != value
        or len(value.encode("utf-8")) > maximum
    ):
        raise ComputationalFabricForwardingError(
            f"{name} must be non-empty trimmed text of at most {maximum} UTF-8 bytes"
        )
    return value


def _peer(value: Any, name: str) -> str:
    """Mathematics: Validate one bounded logical peer identifier."""
    value = _text(value, name, 128)
    if any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._:-" for character in value):
        raise ComputationalFabricForwardingError(f"{name} contains unsupported characters")
    return value


def _sha256(value: Any, name: str) -> str:
    """Mathematics: Require a lowercase SHA-256 content identity."""
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ComputationalFabricForwardingError(f"{name} must be lowercase SHA-256 hex")
    return value


def _canonical_bytes(value: Any, name: str) -> bytes:
    """Mathematics: Project one JSON value into the unique wire byte representation."""
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ComputationalFabricForwardingError(f"{name} is outside canonical JSON") from exc


def _canonical_digest(value: Any, name: str) -> str:
    """Mathematics: Identify a canonical JSON value with SHA-256."""
    return hashlib.sha256(_canonical_bytes(value, name)).hexdigest()


def _json_copy(value: Mapping[str, Any], name: str) -> dict[str, Any]:
    """Mathematics: Detach a mapping through its canonical JSON round trip."""
    if not isinstance(value, Mapping):
        raise ComputationalFabricForwardingError(f"{name} must be a JSON object")
    try:
        copied = json.loads(_canonical_bytes(dict(value), name).decode("utf-8"))
    except (TypeError, ValueError) as exc:
        raise ComputationalFabricForwardingError(f"{name} is outside canonical JSON") from exc
    if not isinstance(copied, dict):
        raise ComputationalFabricForwardingError(f"{name} must be a JSON object")
    return copied


def computational_fabric_forward_channel_id(origin_peer_id: str, origin_channel: str) -> str:
    """Mathematics: Derive one stable forwarding channel from the original requester identity."""
    origin = _peer(origin_peer_id, "origin_peer_id")
    channel = _text(origin_channel, "origin_channel")
    return _FORWARD_CHANNEL_PREFIX + _canonical_digest(
        {"origin_peer_id": origin, "origin_channel": channel},
        "forwarding channel identity",
    )


@dataclass(frozen=True)
class ComputationalFabricForwardingEnvelope:
    """Portable operation identity and route cursor; it carries no authority or executable binding."""

    address: ComputationalAddress
    route: ComputationalFabricRouteWitness
    origin_peer_id: str
    origin_channel: str
    origin_sequence: int
    logical_time: int
    current_peer_id: str
    previous_peer_id: str | None
    hop_index: int

    def __post_init__(self) -> None:
        """Mathematics: Bind semantic address, route, stable origin identity, and one exact path coordinate."""
        if not isinstance(self.address, ComputationalAddress):
            raise ComputationalFabricForwardingError("envelope requires a ComputationalAddress")
        if not isinstance(self.route, ComputationalFabricRouteWitness):
            raise ComputationalFabricForwardingError("envelope requires a ComputationalFabricRouteWitness")
        origin = _peer(self.origin_peer_id, "origin_peer_id")
        channel = _text(self.origin_channel, "origin_channel")
        current = _peer(self.current_peer_id, "current_peer_id")
        if self.route.address_digest != self.address.digest or self.route.origin_peer_id != origin:
            raise ComputationalFabricForwardingError("route witness does not bind this address and origin")
        if type(self.origin_sequence) is not int or self.origin_sequence < 1:
            raise ComputationalFabricForwardingError("origin_sequence must be a positive strict integer")
        if type(self.logical_time) is not int or self.logical_time < 0:
            raise ComputationalFabricForwardingError("logical_time must be a non-negative strict integer")
        if self.logical_time != self.address.workload.logical_time:
            raise ComputationalFabricForwardingError("envelope logical time differs from the addressed workload")
        path = self.route.peer_path
        if (
            len(path) < 2
            or len(path) > _MAX_FORWARD_HOPS + 1
            or len(path) - 1 > self.address.workload.max_hops
        ):
            raise ComputationalFabricForwardingError("route path exceeds the bounded workload hop budget")
        if type(self.hop_index) is not int or not 0 <= self.hop_index < len(path):
            raise ComputationalFabricForwardingError("hop_index is outside the route path")
        if current != path[self.hop_index]:
            raise ComputationalFabricForwardingError("current peer does not match the route path coordinate")
        previous = self.previous_peer_id
        if self.hop_index == 0:
            if previous is not None or current != origin:
                raise ComputationalFabricForwardingError("origin envelope must begin at its origin without a previous peer")
        else:
            if previous is None or _peer(previous, "previous_peer_id") != path[self.hop_index - 1]:
                raise ComputationalFabricForwardingError("previous peer does not match the preceding route coordinate")
        object.__setattr__(self, "origin_peer_id", origin)
        object.__setattr__(self, "origin_channel", channel)
        object.__setattr__(self, "current_peer_id", current)

    @classmethod
    def begin(
        cls,
        address: ComputationalAddress,
        route: ComputationalFabricRouteWitness,
        *,
        origin_channel: str,
        origin_sequence: int,
    ) -> "ComputationalFabricForwardingEnvelope":
        """Mathematics: Create the initial route cursor at the authenticated origin peer."""
        if not isinstance(route, ComputationalFabricRouteWitness):
            raise ComputationalFabricForwardingError("begin requires a fabric route witness")
        return cls(
            address,
            route,
            route.origin_peer_id,
            origin_channel,
            origin_sequence,
            address.workload.logical_time,
            route.origin_peer_id,
            None,
            0,
        )

    @property
    def channel_id(self) -> str:
        """Mathematics: Return the deterministic transport channel for this end-to-end identity."""
        return computational_fabric_forward_channel_id(self.origin_peer_id, self.origin_channel)

    @property
    def operation_digest(self) -> str:
        """Mathematics: Bind original source, channel, sequence, and semantic address."""
        return _canonical_digest(
            {
                "origin_peer_id": self.origin_peer_id,
                "origin_channel": self.origin_channel,
                "origin_sequence": self.origin_sequence,
                "address_digest": self.address.digest,
            },
            "operation identity",
        )

    @property
    def digest(self) -> str:
        """Mathematics: Identify this exact peer-local route cursor."""
        return _canonical_digest(self.to_dict(), "forwarding envelope")

    def advance(self) -> "ComputationalFabricForwardingEnvelope":
        """Mathematics: Move exactly one directed path edge and bind the prior peer as the immediate sender."""
        next_index = self.hop_index + 1
        if next_index >= len(self.route.peer_path):
            raise ComputationalFabricForwardingError("terminal peer cannot advance beyond the route")
        return ComputationalFabricForwardingEnvelope(
            self.address,
            self.route,
            self.origin_peer_id,
            self.origin_channel,
            self.origin_sequence,
            self.logical_time,
            self.route.peer_path[next_index],
            self.current_peer_id,
            next_index,
        )

    def to_dict(self) -> dict[str, Any]:
        """Mathematics: Serialize only portable address, non-authoritative route evidence, and operation cursor."""
        return {
            "schema": "mailcpu.computational-fabric-forward-envelope.v1",
            "address": self.address.to_dict(),
            "route": self.route.to_dict(),
            "origin_peer_id": self.origin_peer_id,
            "origin_channel": self.origin_channel,
            "origin_sequence": self.origin_sequence,
            "logical_time": self.logical_time,
            "current_peer_id": self.current_peer_id,
            "previous_peer_id": self.previous_peer_id,
            "hop_index": self.hop_index,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ComputationalFabricForwardingEnvelope":
        """Mathematics: Reconstruct a route cursor only from its exact versioned JSON schema."""
        expected = {
            "schema",
            "address",
            "route",
            "origin_peer_id",
            "origin_channel",
            "origin_sequence",
            "logical_time",
            "current_peer_id",
            "previous_peer_id",
            "hop_index",
        }
        if not isinstance(payload, Mapping) or set(payload) != expected:
            raise ComputationalFabricForwardingError("forwarding envelope fields are malformed")
        if payload["schema"] != "mailcpu.computational-fabric-forward-envelope.v1":
            raise ComputationalFabricForwardingError("forwarding envelope schema is unsupported")
        try:
            return cls(
                ComputationalAddress.from_dict(payload["address"]),
                ComputationalFabricRouteWitness.from_dict(payload["route"]),
                payload["origin_peer_id"],
                payload["origin_channel"],
                payload["origin_sequence"],
                payload["logical_time"],
                payload["current_peer_id"],
                payload["previous_peer_id"],
                payload["hop_index"],
            )
        except (KeyError, TypeError, ValueError) as exc:
            if isinstance(exc, ComputationalFabricForwardingError):
                raise
            raise ComputationalFabricForwardingError("forwarding envelope contains invalid nested values") from exc


@dataclass(frozen=True)
class ComputationalFabricHopReceipt:
    """Digest-linked local Hypervisor decision and downstream result for one authenticated hop."""

    peer_id: str
    previous_peer_id: str
    next_peer_id: str | None
    hop_index: int
    operation_digest: str
    envelope_digest: str
    next_envelope_digest: str | None
    decision_receipt: str
    status: str
    downstream: "ComputationalFabricHopReceipt | None" = None
    terminal_execution: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        """Mathematics: Enforce receipt-chain adjacency, envelope linkage, and terminal/relay result consistency."""
        peer = _peer(self.peer_id, "peer_id")
        previous = _peer(self.previous_peer_id, "previous_peer_id")
        if peer == previous:
            raise ComputationalFabricForwardingError("hop receipt cannot name itself as its previous peer")
        if type(self.hop_index) is not int or self.hop_index < 1:
            raise ComputationalFabricForwardingError("hop receipt index must be a positive strict integer")
        _sha256(self.operation_digest, "operation_digest")
        _sha256(self.envelope_digest, "envelope_digest")
        _sha256(self.decision_receipt, "decision_receipt")
        if not isinstance(self.status, str) or self.status not in {"forwarded", "executed", "replayed", "refused"}:
            raise ComputationalFabricForwardingError("hop receipt status is unsupported")
        if self.next_peer_id is None:
            if self.downstream is not None or self.next_envelope_digest is not None:
                raise ComputationalFabricForwardingError("terminal receipt cannot contain downstream forwarding fields")
            if self.terminal_execution is None:
                raise ComputationalFabricForwardingError("terminal receipt requires a typed execution outcome")
            terminal = _json_copy(self.terminal_execution, "terminal execution")
            accepted = terminal.get("accepted") is True and terminal.get("executed") is True
            replayed = terminal.get("replayed") is True
            expected_status = "replayed" if accepted and replayed else "executed" if accepted else "refused"
            if self.status != expected_status:
                raise ComputationalFabricForwardingError("terminal receipt status differs from its execution outcome")
            object.__setattr__(self, "terminal_execution", terminal)
        else:
            next_peer = _peer(self.next_peer_id, "next_peer_id")
            next_digest = _sha256(self.next_envelope_digest, "next_envelope_digest")
            if self.terminal_execution is not None or not isinstance(self.downstream, ComputationalFabricHopReceipt):
                raise ComputationalFabricForwardingError("relay receipt requires one downstream receipt and no terminal outcome")
            downstream = self.downstream
            if (
                downstream.peer_id != next_peer
                or downstream.previous_peer_id != peer
                or downstream.hop_index != self.hop_index + 1
                or downstream.operation_digest != self.operation_digest
                or downstream.envelope_digest != next_digest
            ):
                raise ComputationalFabricForwardingError("downstream receipt does not continue the exact operation and path")
            expected_status = "forwarded" if downstream.succeeded else "refused"
            if self.status != expected_status:
                raise ComputationalFabricForwardingError("relay receipt status differs from downstream outcome")
            object.__setattr__(self, "next_peer_id", next_peer)
            object.__setattr__(self, "next_envelope_digest", next_digest)

    @property
    def succeeded(self) -> bool:
        """Mathematics: Report end-to-end success only when the terminal local execution was committed."""
        if self.next_peer_id is not None:
            return self.downstream is not None and self.downstream.succeeded
        return (
            self.terminal_execution is not None
            and self.terminal_execution.get("accepted") is True
            and self.terminal_execution.get("executed") is True
        )

    @property
    def digest(self) -> str:
        """Mathematics: Identify the complete receipt subtree by canonical SHA-256."""
        return _canonical_digest(self.to_dict(), "hop receipt")

    def to_dict(self) -> dict[str, Any]:
        """Mathematics: Serialize hop-local decision provenance and the recursively linked downstream result."""
        return {
            "schema": "mailcpu.computational-fabric-hop-receipt.v1",
            "peer_id": self.peer_id,
            "previous_peer_id": self.previous_peer_id,
            "next_peer_id": self.next_peer_id,
            "hop_index": self.hop_index,
            "operation_digest": self.operation_digest,
            "envelope_digest": self.envelope_digest,
            "next_envelope_digest": self.next_envelope_digest,
            "decision_receipt": self.decision_receipt,
            "status": self.status,
            "downstream": None if self.downstream is None else self.downstream.to_dict(),
            "terminal_execution": None if self.terminal_execution is None else dict(self.terminal_execution),
            "succeeded": self.succeeded,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ComputationalFabricHopReceipt":
        """Mathematics: Reconstruct a receipt tree only when every nested digest and hop coordinate is consistent."""
        expected = {
            "schema",
            "peer_id",
            "previous_peer_id",
            "next_peer_id",
            "hop_index",
            "operation_digest",
            "envelope_digest",
            "next_envelope_digest",
            "decision_receipt",
            "status",
            "downstream",
            "terminal_execution",
            "succeeded",
        }
        if not isinstance(payload, Mapping) or set(payload) != expected:
            raise ComputationalFabricForwardingError("hop receipt fields are malformed")
        if payload["schema"] != "mailcpu.computational-fabric-hop-receipt.v1":
            raise ComputationalFabricForwardingError("hop receipt schema is unsupported")
        try:
            downstream_payload = payload["downstream"]
            receipt = cls(
                payload["peer_id"],
                payload["previous_peer_id"],
                payload["next_peer_id"],
                payload["hop_index"],
                payload["operation_digest"],
                payload["envelope_digest"],
                payload["next_envelope_digest"],
                payload["decision_receipt"],
                payload["status"],
                None if downstream_payload is None else cls.from_dict(downstream_payload),
                payload["terminal_execution"],
            )
        except (KeyError, TypeError, ValueError) as exc:
            if isinstance(exc, ComputationalFabricForwardingError):
                raise
            raise ComputationalFabricForwardingError("hop receipt contains invalid nested values") from exc
        if payload["succeeded"] is not receipt.succeeded:
            raise ComputationalFabricForwardingError("hop receipt success marker is inconsistent")
        return receipt


def _active_snapshot_map(directory: ComputationalFabricDirectory) -> dict[str, Any]:
    """Mathematics: Capture one receiver-local lease-filtered peer view."""
    if not isinstance(directory, ComputationalFabricDirectory):
        raise ComputationalFabricForwardingError("forwarding requires a ComputationalFabricDirectory")
    return {item.peer_id: item for item in directory.active_snapshots}


def _directed_link(snapshot: Any, link_id: str, source: str, target: str) -> Any:
    """Mathematics: Find the exact peer-owned directed edge named by the origin route."""
    matches = tuple(
        link
        for link in snapshot.links
        if link.link_id == link_id
        and link.source_peer_id == source
        and link.target_peer_id == target
        and link.enabled
    )
    if len(matches) != 1:
        raise ComputationalFabricForwardingError(
            f"active local peer view does not contain the exact directed edge {source}->{target}"
        )
    return matches[0]


def _authenticated_neighbor(
    directory: ComputationalFabricDirectory,
    snapshots: Mapping[str, Any],
    transport: SocketTransport,
    local_peer_id: str,
    remote_peer_id: str,
) -> Any:
    """Mathematics: Bind one live directly observed snapshot to the mutually authenticated adjacent TLS stream."""
    remote = snapshots.get(remote_peer_id)
    if remote is None:
        raise ComputationalFabricForwardingError("adjacent peer has no live receiver-local lease")
    trusted_dns = directory.trusted_peers.get(remote_peer_id)
    if (
        trusted_dns is None
        or trusted_dns != remote.endpoint.tls_server_name
        or transport.local_endpoint != local_peer_id
        or transport.peer_endpoint != remote_peer_id
        or not _certificate_has_dns(transport, trusted_dns)
    ):
        raise ComputationalFabricForwardingError("adjacent transport is not bound to the configured live TLS peer identity")
    return remote


def _envelope_size(envelope: ComputationalFabricForwardingEnvelope) -> int:
    """Mathematics: Measure canonical portable envelope bytes before any hop forwards them."""
    return len(_canonical_bytes(envelope.to_dict(), "forwarding envelope"))


class ComputationalFabricForwardingClient:
    """One directly authenticated reliable sender that advances an envelope by exactly one route edge."""

    def __init__(
        self,
        local_peer_id: str,
        remote_endpoint: ComputationalPeerEndpoint,
        transport: SocketTransport,
        *,
        origin_peer_id: str,
        origin_channel: str,
        timeout: float = 5.0,
        max_payload_bytes: int = _DEFAULT_MAX_PAYLOAD_BYTES,
        policy: ReliabilityPolicy | None = None,
    ) -> None:
        """Mathematics: Bind one adjacent TLS stream and reliable request/result pair to a stable origin operation channel."""
        local = _peer(local_peer_id, "local_peer_id")
        if not isinstance(remote_endpoint, ComputationalPeerEndpoint):
            raise ComputationalFabricForwardingError("client requires a ComputationalPeerEndpoint")
        if not isinstance(transport, SocketTransport):
            raise ComputationalFabricForwardingError("client requires a SocketTransport")
        if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or timeout <= 0:
            raise ComputationalFabricForwardingError("timeout must be positive")
        if type(max_payload_bytes) is not int or max_payload_bytes < 256:
            raise ComputationalFabricForwardingError("max_payload_bytes must be at least 256 bytes")
        channel_id = computational_fabric_forward_channel_id(origin_peer_id, origin_channel)
        if (
            transport.local_endpoint != local
            or transport.peer_endpoint != remote_endpoint.peer_id
            or not _certificate_has_dns(transport, remote_endpoint.tls_server_name)
        ):
            raise ComputationalFabricForwardingError("client stream is not bound to the configured mutual-TLS peer")
        selected_policy = policy or ReliabilityPolicy(lease_ticks=2, max_attempts=12, window_size=4)
        self.local_peer_id = local
        self.remote_endpoint = remote_endpoint
        self.transport = transport
        self.origin_peer_id = _peer(origin_peer_id, "origin_peer_id")
        self.origin_channel = _text(origin_channel, "origin_channel")
        self.channel_id = channel_id
        self.timeout = float(timeout)
        self.max_payload_bytes = max_payload_bytes
        self.request = HypervisorOperationChannel(
            ReliableChannel(transport, local, remote_endpoint.peer_id, channel_id, selected_policy)
        )
        self.response = HypervisorOperationResultChannel(
            ReliableChannel(
                transport,
                local,
                local,
                channel_id + _RESPONSE_SUFFIX,
                selected_policy,
                peer=remote_endpoint.peer_id,
            ),
            local,
            channel_id,
        )
        self._transition_lock = threading.RLock()

    @classmethod
    def connect_mutual_tls(
        cls,
        local_peer_id: str,
        remote_endpoint: ComputationalPeerEndpoint,
        context: Any,
        *,
        origin_peer_id: str,
        origin_channel: str,
        timeout: float = 5.0,
        handshake_timeout: float = 5.0,
        max_payload_bytes: int = _DEFAULT_MAX_PAYLOAD_BYTES,
        policy: ReliabilityPolicy | None = None,
    ) -> "ComputationalFabricForwardingClient":
        """Mathematics: Open a direct peer stream only after CA-chain and exact DNS SAN validation."""
        if not isinstance(remote_endpoint, ComputationalPeerEndpoint):
            raise ComputationalFabricForwardingError("connect_mutual_tls requires a ComputationalPeerEndpoint")
        transport = connect_mutual_tls(
            remote_endpoint.endpoint_host,
            remote_endpoint.port,
            _peer(local_peer_id, "local_peer_id"),
            remote_endpoint.peer_id,
            context,
            server_hostname=remote_endpoint.tls_server_name,
            timeout=timeout,
            handshake_timeout=handshake_timeout,
        )
        try:
            return cls(
                local_peer_id,
                remote_endpoint,
                transport,
                origin_peer_id=origin_peer_id,
                origin_channel=origin_channel,
                timeout=timeout,
                max_payload_bytes=max_payload_bytes,
                policy=policy,
            )
        except Exception:
            transport.close()
            raise

    def _validate_outgoing(
        self,
        envelope: ComputationalFabricForwardingEnvelope,
        directory: ComputationalFabricDirectory,
    ) -> tuple[Any, Any, ComputationalFabricForwardingEnvelope]:
        """Mathematics: Validate the local route coordinate, active peer lease, owned edge, endpoint, and bounded child frame."""
        if not isinstance(envelope, ComputationalFabricForwardingEnvelope):
            raise ComputationalFabricForwardingError("forward requires a typed forwarding envelope")
        if (
            envelope.origin_peer_id != self.origin_peer_id
            or envelope.origin_channel != self.origin_channel
            or envelope.channel_id != self.channel_id
            or envelope.current_peer_id != self.local_peer_id
        ):
            raise ComputationalFabricForwardingError("envelope operation or current peer differs from this forwarding client")
        if directory.local_peer_id != self.local_peer_id:
            raise ComputationalFabricForwardingError("forwarding directory belongs to a different local peer")
        snapshots = _active_snapshot_map(directory)
        local_snapshot = snapshots.get(self.local_peer_id)
        if (
            local_snapshot is None
            or local_snapshot.endpoint != envelope.route.peer_endpoints[envelope.hop_index]
        ):
            raise ComputationalFabricForwardingError("local snapshot does not match the route's current peer endpoint")
        next_index = envelope.hop_index + 1
        if next_index >= len(envelope.route.peer_path):
            raise ComputationalFabricForwardingError("route has no next peer")
        next_peer = envelope.route.peer_path[next_index]
        next_snapshot = _authenticated_neighbor(
            directory,
            snapshots,
            self.transport,
            self.local_peer_id,
            next_peer,
        )
        if next_snapshot.endpoint != self.remote_endpoint or self.remote_endpoint != envelope.route.peer_endpoints[next_index]:
            raise ComputationalFabricForwardingError("TLS endpoint differs from the exact next route endpoint")
        link = _directed_link(
            local_snapshot,
            envelope.route.link_ids[envelope.hop_index],
            self.local_peer_id,
            next_peer,
        )
        child = envelope.advance()
        size = _envelope_size(child)
        if size > min(self.max_payload_bytes, self.transport.max_frame_size - 1024, link.max_frame_bytes):
            raise ComputationalFabricForwardingError("forwarding envelope exceeds a configured payload or link frame bound")
        return next_snapshot, link, child

    def forward(
        self,
        envelope: ComputationalFabricForwardingEnvelope,
        directory: ComputationalFabricDirectory,
    ) -> ComputationalFabricHopReceipt:
        """Mathematics: Serialize one downstream request with capture so its channel cut is recoverable."""
        with self._transition_lock:
            return self._forward(envelope, directory)

    def _forward(
        self,
        envelope: ComputationalFabricForwardingEnvelope,
        directory: ComputationalFabricDirectory,
    ) -> ComputationalFabricHopReceipt:
        """Mathematics: Advance one route edge, receive a locally admitted Hypervisor result, and verify its hop receipt."""
        _next_snapshot, _link, child = self._validate_outgoing(envelope, directory)
        terminal = child.hop_index == len(child.route.peer_path) - 1
        request = HypervisorRequest(
            COMPUTATIONAL_FABRIC_EXECUTE_OPERATION if terminal else COMPUTATIONAL_FABRIC_FORWARD_OPERATION,
            COMPUTATIONAL_FABRIC_EXECUTE_RESOURCE if terminal else COMPUTATIONAL_FABRIC_FORWARD_RESOURCE,
            {"envelope": child.to_dict()},
            frozenset({"execute"}) if terminal else frozenset({"forward"}),
            frozenset(),
            False,
        )
        event = HypervisorArbitrationEvent(
            self.local_peer_id,
            child.channel_id,
            child.origin_sequence,
            child.logical_time,
            request,
        )
        try:
            self.request.send(event)
        except Exception as exc:
            raise ComputationalFabricForwardingError(f"could not enqueue forwarding operation: {exc}") from exc

        deadline = time.monotonic() + self.timeout
        last_tick = time.monotonic()
        result: HypervisorExecutionResult | None = None
        while time.monotonic() < deadline:
            try:
                self.request.channel.process_ack()
                result = self.response.receive()
            except Exception as exc:
                raise ComputationalFabricForwardingError(f"forwarding peer stream failed: {exc}") from exc
            if result is not None:
                break
            now = time.monotonic()
            if now - last_tick >= 0.03:
                failed = self.request.channel.tick()
                if failed:
                    raise ComputationalFabricForwardingError("forwarding request exhausted reliable retry attempts")
                last_tick = now
            time.sleep(0.002)
        if result is None:
            raise ComputationalFabricForwardingError("next peer did not return a result before the RPC deadline")
        if (
            result.source != self.local_peer_id
            or result.channel != child.channel_id
            or result.sequence != child.origin_sequence
            or result.logical_time != child.logical_time
            or result.action is not HypervisorAction.ALLOW
            or result.domain is not HypervisorDomain.NETWORK
            or not result.executed
            or not isinstance(result.effect, Mapping)
        ):
            raise ComputationalFabricForwardingError("next peer did not return an executed local Hypervisor ALLOW result")
        if (
            result.effect.get("kind") != COMPUTATIONAL_FABRIC_FORWARD_RESULT_KIND
            or not isinstance(result.effect.get("receipt"), Mapping)
        ):
            raise ComputationalFabricForwardingError("next peer result is missing the typed fabric hop receipt")
        receipt = ComputationalFabricHopReceipt.from_dict(result.effect["receipt"])
        if (
            result.effect.get("receipt_digest") != receipt.digest
            or receipt.peer_id != self.remote_endpoint.peer_id
            or receipt.previous_peer_id != self.local_peer_id
            or receipt.hop_index != child.hop_index
            or receipt.operation_digest != child.operation_digest
            or receipt.envelope_digest != child.digest
            or receipt.decision_receipt != result.decision_receipt
        ):
            raise ComputationalFabricForwardingError("next peer receipt does not bind this exact authenticated forwarding hop")
        return receipt

    def snapshot(self) -> dict[str, Any]:
        """Mathematics: Capture operation identity and both reliable channel ledgers for one adjacent TLS hop."""
        with self._transition_lock:
            return {
                "schema": "mailcpu.computational-fabric-forwarding-client.v1",
                "version": 1,
                "local_peer_id": self.local_peer_id,
                "remote_endpoint": self.remote_endpoint.to_dict(),
                "origin_peer_id": self.origin_peer_id,
                "origin_channel": self.origin_channel,
                "timeout": self.timeout,
                "max_payload_bytes": self.max_payload_bytes,
                "request_channel": self.request.channel.snapshot(),
                "response_channel": self.response.snapshot(),
            }

    @classmethod
    def from_snapshot(
        cls,
        payload: Mapping[str, Any],
        transport: SocketTransport,
    ) -> "ComputationalFabricForwardingClient":
        """Mathematics: Restore a client channel pair over a newly authenticated adjacent-peer transport."""
        expected = {
            "schema", "version", "local_peer_id", "remote_endpoint",
            "origin_peer_id", "origin_channel", "timeout", "max_payload_bytes",
            "request_channel", "response_channel",
        }
        if (
            not isinstance(payload, Mapping)
            or set(payload) != expected
            or payload.get("schema") != "mailcpu.computational-fabric-forwarding-client.v1"
            or type(payload.get("version")) is not int
            or payload.get("version") != 1
            or not isinstance(payload.get("remote_endpoint"), Mapping)
            or not isinstance(payload.get("request_channel"), Mapping)
            or not isinstance(payload.get("response_channel"), Mapping)
        ):
            raise ComputationalFabricForwardingError("forwarding client snapshot fields or version are invalid")
        endpoint = ComputationalPeerEndpoint.from_dict(payload["remote_endpoint"])
        client = cls(
            str(payload["local_peer_id"]),
            endpoint,
            transport,
            origin_peer_id=str(payload["origin_peer_id"]),
            origin_channel=str(payload["origin_channel"]),
            timeout=float(payload["timeout"]),
            max_payload_bytes=int(payload["max_payload_bytes"]),
        )
        restored_request = ReliableChannel.from_snapshot(
            dict(payload["request_channel"]),
            transport,
        )
        if (
            restored_request.source != client.local_peer_id
            or restored_request.destination != endpoint.peer_id
            or restored_request.channel != client.channel_id
            or restored_request.peer is not None
        ):
            raise ComputationalFabricForwardingError(
                "restored downstream request channel is bound to another peer or operation"
            )
        client.request = HypervisorOperationChannel(restored_request)
        restored_response = HypervisorOperationResultChannel.from_snapshot(
            payload["response_channel"],
            transport,
        )
        if (
            restored_response.operation_source != client.local_peer_id
            or restored_response.operation_channel != client.channel_id
            or restored_response.channel.source != client.local_peer_id
            or restored_response.channel.destination != client.local_peer_id
            or restored_response.channel.peer != endpoint.peer_id
            or restored_response.channel.channel != client.channel_id + _RESPONSE_SUFFIX
        ):
            raise ComputationalFabricForwardingError(
                "restored downstream result channel is bound to another peer or operation"
            )
        client.response = restored_response
        return client

    def close(self) -> None:
        """Mathematics: Close the directly authenticated peer stream and its associated reliable channels."""
        self.transport.close()


class ComputationalFabricForwardingServer:
    """Receiver-side per-hop admission and forwarding service using the existing Hypervisor execution ledger."""

    def __init__(
        self,
        local_peer_id: str,
        previous_peer_id: str,
        transport: SocketTransport,
        directory: ComputationalFabricDirectory,
        operating_system: HeadlessOS,
        authority_pid: int,
        *,
        origin_peer_id: str,
        origin_channel: str,
        catalogue: ComputationalHostCatalogue | None = None,
        next_hop_clients: Mapping[str, ComputationalFabricForwardingClient] | None = None,
        timeout: float = 5.0,
        max_payload_bytes: int = _DEFAULT_MAX_PAYLOAD_BYTES,
        policy: ReliabilityPolicy | None = None,
    ) -> None:
        """Mathematics: Bind one adjacent authenticated stream, local capability identity, receiver view and optional terminal catalogue."""
        local = _peer(local_peer_id, "local_peer_id")
        previous = _peer(previous_peer_id, "previous_peer_id")
        if local == previous:
            raise ComputationalFabricForwardingError("server previous peer must differ from local peer")
        if not isinstance(transport, SocketTransport):
            raise ComputationalFabricForwardingError("server requires a SocketTransport")
        if not isinstance(directory, ComputationalFabricDirectory) or directory.local_peer_id != local:
            raise ComputationalFabricForwardingError("server directory must belong to its local peer")
        if not isinstance(operating_system, HeadlessOS):
            raise ComputationalFabricForwardingError("server requires a receiver-local HeadlessOS")
        if type(authority_pid) is not int or isinstance(authority_pid, bool):
            raise ComputationalFabricForwardingError("authority_pid must be a strict integer")
        try:
            operating_system.environment.kernel._process(authority_pid)
        except Exception as exc:
            raise ComputationalFabricForwardingError("authority_pid is not a live receiver-local process") from exc
        if catalogue is not None and not isinstance(catalogue, ComputationalHostCatalogue):
            raise ComputationalFabricForwardingError("catalogue must be a ComputationalHostCatalogue or None")
        if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or timeout <= 0:
            raise ComputationalFabricForwardingError("timeout must be positive")
        if type(max_payload_bytes) is not int or max_payload_bytes < 256:
            raise ComputationalFabricForwardingError("max_payload_bytes must be at least 256 bytes")
        snapshots = _active_snapshot_map(directory)
        _authenticated_neighbor(directory, snapshots, transport, local, previous)
        self.local_peer_id = local
        self.previous_peer_id = previous
        self.transport = transport
        self.directory = directory
        self.operating_system = operating_system
        self.authority_pid = authority_pid
        self.origin_peer_id = _peer(origin_peer_id, "origin_peer_id")
        self.origin_channel = _text(origin_channel, "origin_channel")
        self.channel_id = computational_fabric_forward_channel_id(origin_peer_id, origin_channel)
        self.catalogue = catalogue
        self.next_hop_clients = dict(next_hop_clients or {})
        if any(not isinstance(client, ComputationalFabricForwardingClient) for client in self.next_hop_clients.values()):
            raise ComputationalFabricForwardingError("next-hop clients must be ComputationalFabricForwardingClient values")
        if any(
            peer_id != client.remote_endpoint.peer_id
            or client.local_peer_id != local
            or client.channel_id != self.channel_id
            for peer_id, client in self.next_hop_clients.items()
        ):
            raise ComputationalFabricForwardingError("next-hop client map contains a misbound client")
        selected_policy = policy or ReliabilityPolicy(lease_ticks=2, max_attempts=12, window_size=4)
        self.timeout = float(timeout)
        self.max_payload_bytes = max_payload_bytes
        self.inbound = HypervisorOperationChannel(
            ReliableChannel(
                transport,
                local,
                local,
                self.channel_id,
                selected_policy,
                peer=previous,
            )
        )
        self.outbound = HypervisorOperationResultChannel(
            ReliableChannel(
                transport,
                local,
                previous,
                self.channel_id + _RESPONSE_SUFFIX,
                selected_policy,
            ),
            previous,
            self.channel_id,
        )
        self.retry_interval = 0.03
        self._last_retry = time.monotonic()
        self.last_error: str | None = None
        self._transition_lock = threading.RLock()

    @classmethod
    def accept_mutual_tls(
        cls,
        listener: Any,
        local_peer_id: str,
        previous_peer_id: str,
        context: Any,
        directory: ComputationalFabricDirectory,
        operating_system: HeadlessOS,
        authority_pid: int,
        *,
        origin_peer_id: str,
        origin_channel: str,
        catalogue: ComputationalHostCatalogue | None = None,
        next_hop_clients: Mapping[str, ComputationalFabricForwardingClient] | None = None,
        handshake_timeout: float = 5.0,
        timeout: float = 5.0,
        max_payload_bytes: int = _DEFAULT_MAX_PAYLOAD_BYTES,
        policy: ReliabilityPolicy | None = None,
    ) -> "ComputationalFabricForwardingServer":
        """Mathematics: Accept one client only when its CA-verified certificate presents the directory's exact trusted DNS SAN."""
        previous = _peer(previous_peer_id, "previous_peer_id")
        expected_dns = directory.trusted_peers.get(previous)
        if not expected_dns:
            raise ComputationalFabricForwardingError("previous peer is not in the receiver's configured trust map")
        transport = accept_mutual_tls(
            listener,
            _peer(local_peer_id, "local_peer_id"),
            previous,
            context,
            expected_peer_dns=expected_dns,
            handshake_timeout=handshake_timeout,
        )
        try:
            return cls(
                local_peer_id,
                previous,
                transport,
                directory,
                operating_system,
                authority_pid,
                origin_peer_id=origin_peer_id,
                origin_channel=origin_channel,
                catalogue=catalogue,
                next_hop_clients=next_hop_clients,
                timeout=timeout,
                max_payload_bytes=max_payload_bytes,
                policy=policy,
            )
        except Exception:
            transport.close()
            raise

    def _decode_envelope(self, event: HypervisorArbitrationEvent) -> ComputationalFabricForwardingEnvelope:
        """Mathematics: Bind wire request, immediate TLS neighbor, stable origin identity, and current path coordinate."""
        if (
            not isinstance(event, HypervisorArbitrationEvent)
            or event.source != self.previous_peer_id
            or event.channel != self.channel_id
            or event.sequence < 1
        ):
            raise ComputationalFabricForwardingError("forwarded event is not bound to the authenticated previous peer")
        payload = event.request.payload
        if not isinstance(payload, Mapping) or set(payload) != {"envelope"}:
            raise ComputationalFabricForwardingError("forwarded event payload must contain exactly one envelope")
        envelope = ComputationalFabricForwardingEnvelope.from_dict(payload["envelope"])
        if (
            envelope.origin_peer_id != self.origin_peer_id
            or envelope.origin_channel != self.origin_channel
            or envelope.channel_id != self.channel_id
            or envelope.origin_sequence != event.sequence
            or envelope.logical_time != event.logical_time
            or envelope.current_peer_id != self.local_peer_id
            or envelope.previous_peer_id != self.previous_peer_id
            or envelope.hop_index < 1
        ):
            raise ComputationalFabricForwardingError("forwarded envelope differs from the authenticated operation identity or peer cursor")
        if _envelope_size(envelope) > min(self.max_payload_bytes, self.transport.max_frame_size - 1024):
            raise ComputationalFabricForwardingError("incoming forwarding envelope exceeds the receiver payload bound")
        terminal = envelope.hop_index == len(envelope.route.peer_path) - 1
        expected_operation = COMPUTATIONAL_FABRIC_EXECUTE_OPERATION if terminal else COMPUTATIONAL_FABRIC_FORWARD_OPERATION
        expected_resource = COMPUTATIONAL_FABRIC_EXECUTE_RESOURCE if terminal else COMPUTATIONAL_FABRIC_FORWARD_RESOURCE
        expected_rights = frozenset({"execute"}) if terminal else frozenset({"forward"})
        if (
            event.request.operation != expected_operation
            or event.request.resource != expected_resource
            or event.request.required_rights != expected_rights
            or event.request.destructive
        ):
            raise ComputationalFabricForwardingError("forwarded event does not match the exact receiver role contract")
        return envelope

    def _validate_local_route(
        self,
        envelope: ComputationalFabricForwardingEnvelope,
    ) -> tuple[Any, Any | None, ComputationalFabricForwardingClient | None]:
        """Mathematics: Revalidate both adjacent directed edges against this peer's live, directly observed directory view."""
        snapshots = _active_snapshot_map(self.directory)
        local_snapshot = snapshots.get(self.local_peer_id)
        index = envelope.hop_index
        if (
            local_snapshot is None
            or local_snapshot.endpoint != envelope.route.peer_endpoints[index]
        ):
            raise ComputationalFabricForwardingError("local peer endpoint differs from the route's current coordinate")
        previous_snapshot = _authenticated_neighbor(
            self.directory,
            snapshots,
            self.transport,
            self.local_peer_id,
            self.previous_peer_id,
        )
        if previous_snapshot.endpoint != envelope.route.peer_endpoints[index - 1]:
            raise ComputationalFabricForwardingError("previous peer endpoint differs from the route witness")
        incoming_link = _directed_link(
            previous_snapshot,
            envelope.route.link_ids[index - 1],
            self.previous_peer_id,
            self.local_peer_id,
        )
        incoming_size = _envelope_size(envelope)
        if incoming_size > min(self.max_payload_bytes, self.transport.max_frame_size - 1024, incoming_link.max_frame_bytes):
            raise ComputationalFabricForwardingError("incoming envelope exceeds its authenticated directed link frame bound")

        if index == len(envelope.route.peer_path) - 1:
            if envelope.route.target_host.peer_id != self.local_peer_id:
                raise ComputationalFabricForwardingError("terminal advertisement is not owned by the terminal peer")
            if self.catalogue is None:
                raise ComputationalFabricForwardingError("terminal peer has no receiver-local host catalogue")
            return local_snapshot, None, None

        next_peer = envelope.route.peer_path[index + 1]
        next_snapshot = snapshots.get(next_peer)
        if next_snapshot is None or next_snapshot.endpoint != envelope.route.peer_endpoints[index + 1]:
            raise ComputationalFabricForwardingError("next route peer has no matching live directly observed endpoint")
        outgoing_link = _directed_link(
            local_snapshot,
            envelope.route.link_ids[index],
            self.local_peer_id,
            next_peer,
        )
        client = self.next_hop_clients.get(next_peer)
        if (
            client is None
            or client.remote_endpoint != next_snapshot.endpoint
            or client.local_peer_id != self.local_peer_id
            or client.channel_id != self.channel_id
        ):
            raise ComputationalFabricForwardingError("next route peer has no matching authenticated forwarding client")
        child = envelope.advance()
        if _envelope_size(child) > min(self.max_payload_bytes, client.transport.max_frame_size - 1024, outgoing_link.max_frame_bytes):
            raise ComputationalFabricForwardingError("outgoing envelope exceeds its directed link or transport frame bound")
        return local_snapshot, outgoing_link, client

    def _execute_terminal(
        self,
        envelope: ComputationalFabricForwardingEnvelope,
    ) -> dict[str, Any]:
        """Mathematics: Resolve the exact advertised host locally, then use the existing admission coordinator and Hypervisor."""
        if self.catalogue is None:
            raise ComputationalFabricForwardingError("terminal peer has no local host catalogue")
        advertisement = envelope.route.target_host
        candidates = tuple(
            locus
            for locus in self.catalogue.loci
            if locus.host_id == advertisement.host_id
            and locus.operator_spec.operator_id == envelope.address.operator_id
            and locus.operator_spec.version == envelope.address.workload.operator_ref(envelope.address.operator_id).version
        )
        if len(candidates) != 1:
            raise ComputationalFabricForwardingError("advertised terminal logical host is absent or ambiguous locally")
        locus = candidates[0]
        from .computational_fabric import ComputationalHostAdvertisement

        local_advertisement = ComputationalHostAdvertisement.from_locus(locus, self.local_peer_id)
        if local_advertisement.digest != advertisement.digest:
            raise ComputationalFabricForwardingError("terminal host advertisement differs from the live local locus")
        resolution = ComputationalAddressResolver().resolve(
            envelope.address,
            self.catalogue,
            self.operating_system,
        )
        if (
            resolution.status.value != "found"
            or resolution.witness is None
            or resolution.witness.host_id != advertisement.host_id
            or resolution.witness.node_id != advertisement.node_id
            or resolution.witness.implementation_fingerprint != advertisement.implementation_fingerprint
        ):
            raise ComputationalFabricForwardingError("fresh terminal semantic resolution did not reproduce the advertised host locus")
        outcome = ComputationalExecutionAdmissionCoordinator(self.operating_system).execute(
            envelope.address,
            resolution.witness,
            self.catalogue,
            locus.runtime_binding,
            source=envelope.origin_peer_id,
            channel=envelope.origin_channel,
            sequence=envelope.origin_sequence,
        )
        return {
            "kind": "terminal",
            "terminal_execution": outcome.to_dict(),
        }

    def _handle(self, event: HypervisorArbitrationEvent) -> dict[str, Any]:
        """Mathematics: Execute exactly one locally admitted route transition or the receiver-local terminal operation."""
        envelope = self._decode_envelope(event)
        _local_snapshot, _outgoing_link, client = self._validate_local_route(envelope)
        if envelope.hop_index == len(envelope.route.peer_path) - 1:
            return self._execute_terminal(envelope)
        if client is None:
            raise ComputationalFabricForwardingError("relay has no next-hop client")
        downstream = client.forward(envelope, self.directory)
        child = envelope.advance()
        return {
            "kind": "downstream",
            "next_envelope_digest": child.digest,
            "downstream_receipt": downstream.to_dict(),
        }

    def _encode_receipt(
        self,
        raw_effect: Any,
        authorized_event: HypervisorArbitrationEvent,
    ) -> dict[str, Any]:
        """Mathematics: Bind the hop result to the local Hypervisor decision and exact child-envelope transition."""
        if not isinstance(raw_effect, Mapping):
            raise ComputationalFabricForwardingError("forwarding handler effect must be a JSON object")
        decision = self.operating_system.hypervisor_arbitration.decision_projection_for(
            authorized_event.identity
        )
        if decision is None:
            raise ComputationalFabricForwardingError("forwarding effect has no committed local Hypervisor decision")
        action, domain, decision_receipt, _revision = decision
        if action is not HypervisorAction.ALLOW or domain is not HypervisorDomain.NETWORK:
            raise ComputationalFabricForwardingError("forwarding receipt requires a local NETWORK ALLOW decision")
        envelope = self._decode_envelope(authorized_event)
        next_peer = None
        next_digest = None
        downstream = None
        terminal_execution = None
        if raw_effect.get("kind") == "downstream":
            if envelope.hop_index >= len(envelope.route.peer_path) - 1:
                raise ComputationalFabricForwardingError("terminal peer cannot publish a downstream relay receipt")
            next_peer = envelope.route.peer_path[envelope.hop_index + 1]
            next_digest = raw_effect.get("next_envelope_digest")
            downstream_payload = raw_effect.get("downstream_receipt")
            downstream = ComputationalFabricHopReceipt.from_dict(downstream_payload)
            status = "forwarded" if downstream.succeeded else "refused"
        elif raw_effect.get("kind") == "terminal":
            if envelope.hop_index != len(envelope.route.peer_path) - 1:
                raise ComputationalFabricForwardingError("intermediate peer cannot publish a terminal execution receipt")
            terminal_execution = raw_effect.get("terminal_execution")
            if not isinstance(terminal_execution, Mapping):
                raise ComputationalFabricForwardingError("terminal result is missing its typed execution outcome")
            status = (
                "replayed"
                if terminal_execution.get("accepted") is True and terminal_execution.get("replayed") is True
                else "executed"
                if terminal_execution.get("accepted") is True and terminal_execution.get("executed") is True
                else "refused"
            )
        else:
            raise ComputationalFabricForwardingError("forwarding handler effect kind is unsupported")
        receipt = ComputationalFabricHopReceipt(
            self.local_peer_id,
            self.previous_peer_id,
            next_peer,
            envelope.hop_index,
            envelope.operation_digest,
            envelope.digest,
            next_digest,
            decision_receipt,
            status,
            downstream,
            terminal_execution,
        )
        return {
            "kind": COMPUTATIONAL_FABRIC_FORWARD_RESULT_KIND,
            "receipt": receipt.to_dict(),
            "receipt_digest": receipt.digest,
        }

    def serve_once(
        self,
        *,
        fault_hook: Any = None,
    ) -> HypervisorExecutionResult | None:
        """Mathematics: Serialize one hop transition with checkpoint capture and expose its exact commit/publication cuts."""
        with self._transition_lock:
            return self._serve_once(fault_hook=fault_hook)

    def _serve_once(
        self,
        *,
        fault_hook: Any = None,
    ) -> HypervisorExecutionResult | None:
        """Mathematics: Apply one reliable request as local authorize → Hypervisor → receipt publish → request ACK."""
        try:
            self.outbound.channel.process_ack()
        except Exception as exc:
            raise ComputationalFabricForwardingError(f"cannot process forwarding result acknowledgement: {exc}") from exc
        now = time.monotonic()
        if now - self._last_retry >= self.retry_interval:
            self.outbound.channel.tick()
            self._last_retry = now
        if self.outbound.channel.available_window < 1:
            return None
        authorized_events: list[HypervisorArbitrationEvent] = []

        def authorize(event: HypervisorArbitrationEvent) -> HypervisorArbitrationEvent:
            """Mathematics: Verify the envelope and replace every peer-supplied grant with this process's local rights."""
            self._decode_envelope(event)
            self._validate_local_route(ComputationalFabricForwardingEnvelope.from_dict(event.request.payload["envelope"]))
            authorized = self.operating_system.hypervisor_authorize_event(self.authority_pid, event)
            if authorized.identity != event.identity:
                raise ComputationalFabricForwardingError("local authority changed the forwarding event identity")
            authorized_events[:] = [authorized]
            return authorized

        def execute(event: HypervisorArbitrationEvent) -> dict[str, Any]:
            """Mathematics: Dispatch one authorized CPU operation to the local route transition."""
            return self._handle(event)

        def encode(raw_effect: Any) -> dict[str, Any]:
            """Mathematics: Convert one committed pure operation effect into a digest-linked per-hop receipt."""
            if not authorized_events:
                raise ComputationalFabricForwardingError("forwarding effect has no locally authorized event")
            return self._encode_receipt(raw_effect, authorized_events[0])

        result = self.inbound.receive_and_reply_event(
            self.operating_system.hypervisor_arbitration,
            authorize,
            {HypervisorDomain.NETWORK: execute},
            self.outbound,
            encode,
            fault_hook=fault_hook,
        )
        try:
            self.outbound.channel.process_ack()
        except Exception as exc:
            raise ComputationalFabricForwardingError(f"cannot reconcile forwarding result acknowledgement: {exc}") from exc
        return result

    def snapshot(self, *, capture_cut: str = "idle") -> dict[str, Any]:
        """Mathematics: Capture OS replay state and every hop-local reliable channel at one serialized boundary.

        Active remote leases and transport objects are intentionally omitted.
        The caller must authenticate fresh streams and refresh the directory
        before invoking from_snapshot.
        """
        allowed_cuts = {
            "idle",
            "before_execution",
            "after_execution_commit",
            "after_response_publish",
            "after_request_ack",
        }
        if capture_cut not in allowed_cuts:
            raise ComputationalFabricForwardingError(
                f"capture_cut must be one of {sorted(allowed_cuts)}"
            )
        with self._transition_lock:
            return {
                "schema": "mailcpu.computational-fabric-forwarding-server.v1",
                "version": 1,
                "capture_cut": capture_cut,
                "local_peer_id": self.local_peer_id,
                "previous_peer_id": self.previous_peer_id,
                "origin_peer_id": self.origin_peer_id,
                "origin_channel": self.origin_channel,
                "authority_pid": self.authority_pid,
                "timeout": self.timeout,
                "max_payload_bytes": self.max_payload_bytes,
                "operating_system": self.operating_system.snapshot(),
                "inbound_channel": self.inbound.channel.snapshot(),
                "outbound_channel": self.outbound.snapshot(),
                "next_hop_clients": {
                    peer_id: client.snapshot()
                    for peer_id, client in sorted(self.next_hop_clients.items())
                },
            }

    @classmethod
    def from_snapshot(
        cls,
        payload: Mapping[str, Any],
        transport: SocketTransport,
        directory: ComputationalFabricDirectory,
        *,
        next_hop_transports: Mapping[str, SocketTransport] | None = None,
        catalogue: ComputationalHostCatalogue | None = None,
        operating_system: HeadlessOS | None = None,
    ) -> "ComputationalFabricForwardingServer":
        """Mathematics: Rebind one verified peer checkpoint to fresh streams and caller-reconstructed host runtimes."""
        expected = {
            "schema", "version", "capture_cut", "local_peer_id", "previous_peer_id",
            "origin_peer_id", "origin_channel", "authority_pid", "timeout",
            "max_payload_bytes", "operating_system", "inbound_channel",
            "outbound_channel", "next_hop_clients",
        }
        if (
            not isinstance(payload, Mapping)
            or set(payload) != expected
            or payload.get("schema") != "mailcpu.computational-fabric-forwarding-server.v1"
            or type(payload.get("version")) is not int
            or payload.get("version") != 1
            or payload.get("capture_cut") not in {
                "idle", "before_execution", "after_execution_commit",
                "after_response_publish", "after_request_ack",
            }
            or not isinstance(payload.get("operating_system"), Mapping)
            or not isinstance(payload.get("inbound_channel"), Mapping)
            or not isinstance(payload.get("outbound_channel"), Mapping)
            or not isinstance(payload.get("next_hop_clients"), Mapping)
        ):
            raise ComputationalFabricForwardingError("forwarding server snapshot fields or version are invalid")
        restored_os = operating_system or HeadlessOS.from_snapshot(
            dict(payload["operating_system"])
        )
        if not isinstance(restored_os, HeadlessOS):
            raise ComputationalFabricForwardingError("restore requires a receiver-local HeadlessOS")
        raw_clients = payload["next_hop_clients"]
        supplied_transports = dict(next_hop_transports or {})
        if set(supplied_transports) != set(raw_clients):
            raise ComputationalFabricForwardingError(
                "fresh downstream transports must exactly match the checkpointed next-hop set"
            )
        clients = {
            peer_id: ComputationalFabricForwardingClient.from_snapshot(
                raw_clients[peer_id],
                supplied_transports[peer_id],
            )
            for peer_id in sorted(raw_clients)
        }
        server = cls(
            str(payload["local_peer_id"]),
            str(payload["previous_peer_id"]),
            transport,
            directory,
            restored_os,
            int(payload["authority_pid"]),
            origin_peer_id=str(payload["origin_peer_id"]),
            origin_channel=str(payload["origin_channel"]),
            catalogue=catalogue,
            next_hop_clients=clients,
            timeout=float(payload["timeout"]),
            max_payload_bytes=int(payload["max_payload_bytes"]),
        )
        restored_inbound = ReliableChannel.from_snapshot(
            dict(payload["inbound_channel"]),
            transport,
        )
        if (
            restored_inbound.source != server.local_peer_id
            or restored_inbound.destination != server.local_peer_id
            or restored_inbound.peer != server.previous_peer_id
            or restored_inbound.channel != server.channel_id
        ):
            raise ComputationalFabricForwardingError(
                "restored inbound channel is bound to another peer or operation"
            )
        server.inbound = HypervisorOperationChannel(restored_inbound)
        restored_outbound = HypervisorOperationResultChannel.from_snapshot(
            payload["outbound_channel"],
            transport,
        )
        if (
            restored_outbound.operation_source != server.previous_peer_id
            or restored_outbound.operation_channel != server.channel_id
            or restored_outbound.channel.source != server.local_peer_id
            or restored_outbound.channel.destination != server.previous_peer_id
            or restored_outbound.channel.channel != server.channel_id + _RESPONSE_SUFFIX
        ):
            raise ComputationalFabricForwardingError(
                "restored outbound channel is bound to another peer or operation"
            )
        server.outbound = restored_outbound
        return server

    def serve_forever(
        self,
        stop_event: threading.Event,
        *,
        idle_sleep: float = 0.002,
    ) -> None:
        """Mathematics: Service this authenticated peer until stopped, pacing idle polling and failed downstream attempts."""
        if not isinstance(stop_event, threading.Event):
            raise ComputationalFabricForwardingError("stop_event must be a threading.Event")
        if not isinstance(idle_sleep, (int, float)) or isinstance(idle_sleep, bool) or idle_sleep <= 0:
            raise ComputationalFabricForwardingError("idle_sleep must be positive")
        while not stop_event.is_set() and not self.transport.closed:
            try:
                result = self.serve_once()
            except Exception as exc:
                # A failed downstream operation is intentionally not ACKed.
                # Stop this peer loop so an unchanged queued frame cannot spin forever;
                # a supervisor may restore/rebind the service before retrying.
                self.last_error = f"{type(exc).__name__}: {exc}"
                return
            self.last_error = None
            if result is None:
                time.sleep(float(idle_sleep))

    def close(self) -> None:
        """Mathematics: Close this receiver's authenticated peer stream."""
        self.transport.close()
