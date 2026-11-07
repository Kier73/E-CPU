"""Mathematics: Federate computational host discovery and plan bounded multi-hop fabric routes.

This module joins the receiver-local computational resolver to authenticated
peer discovery and a cost-aware directed peer graph. Remote advertisements
are portable claims, never local process authority. Route witnesses are
non-authoritative; the destination must still resolve locally and execute
through its Virtual Layer and Hypervisor.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import heapq
import hashlib
import json
import math
import re
import socket
import ssl
import threading
import time
from typing import Any, Callable, Mapping, Sequence

from .computational_resolver import ComputationalAddress, ComputationalHostLocus
from .evidence_path_resolver import RouteMetric, RouteMetricKey
from .mtls_transport import accept_mutual_tls, connect_mutual_tls
from .reliability import ReliableChannel, ReliabilityPolicy
from .socket_transport import SocketTransport
from .virtual_layer import OperatorSpec, VirtualLayerError, VirtualLayerWorkload


COMPUTATIONAL_DIRECTORY_REQUEST_CHANNEL = "computational.directory.request"
COMPUTATIONAL_DIRECTORY_RESPONSE_CHANNEL = "computational.directory.response"
COMPUTATIONAL_DIRECTORY_REQUEST_KIND = "mailcpu.computational.directory.snapshot.request"
COMPUTATIONAL_DIRECTORY_SNAPSHOT_KIND = "mailcpu.computational.directory.snapshot"
COMPUTATIONAL_DIRECTORY_ERROR_KIND = "mailcpu.computational.directory.error"

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_PEER_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_DNS_LABEL = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\Z")
_MAX_PEER_LEASE_SECONDS = 300
_MAX_HOST_ADVERTISEMENTS = 512
_MAX_NETWORK_LINKS = 4096


class ComputationalFabricError(ValueError):
    """Mathematics: Reject an invalid peer directory, authenticated snapshot, or fabric route."""


class ComputationalFabricStatus(str, Enum):
    """Mathematics: Finite outcomes of one network-wide computational-address resolution."""

    FOUND = "found"
    UNREACHABLE = "unreachable"
    BLOCKED = "blocked"
    BUDGET_EXHAUSTED = "budget_exhausted"


class ComputationalFabricBlockerCode(str, Enum):
    """Mathematics: Stable reasons why a remote host or network path cannot satisfy an address."""

    NO_HOST = "no_host"
    CONTRACT_MISMATCH = "contract_mismatch"
    GROUND_MISMATCH = "ground_mismatch"
    PROGRAM_MISMATCH = "program_mismatch"
    PLACEMENT_MISMATCH = "placement_mismatch"
    SUBSTRATE_MISMATCH = "substrate_mismatch"
    OBSERVATION_MISMATCH = "observation_mismatch"
    INPUT_MISMATCH = "input_mismatch"
    STATE_UNAVAILABLE = "state_unavailable"
    IMPLEMENTATION_MISSING = "implementation_missing"
    AUTHORITY_REVALIDATION_REQUIRED = "authority_revalidation_required"
    PEER_UNAVAILABLE = "peer_unavailable"
    LINK_UNAVAILABLE = "link_unavailable"
    METRIC_MISMATCH = "metric_mismatch"
    RESOURCE_LIMIT = "resource_limit"
    HOP_LIMIT = "hop_limit"


def _label(value: Any, name: str, maximum: int = 256) -> str:
    """Mathematics: Require non-empty, trimmed UTF-8 text inside a finite byte bound."""
    if (
        not isinstance(value, str)
        or not value
        or value.strip() != value
        or len(value.encode("utf-8")) > maximum
    ):
        raise ComputationalFabricError(
            f"{name} must be trimmed non-empty text of at most {maximum} UTF-8 bytes"
        )
    return value


def _peer_id(value: Any, name: str = "peer_id") -> str:
    """Mathematics: Restrict peer identities to the stable bounded identifier alphabet."""
    if not isinstance(value, str) or _PEER_ID.fullmatch(value) is None:
        raise ComputationalFabricError(f"{name} is not a valid peer identity")
    return value


def _digest(value: Any, name: str) -> str:
    """Mathematics: Require one lowercase SHA-256 content identity."""
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ComputationalFabricError(f"{name} must be lowercase SHA-256 hex")
    return value


def _positive(value: Any, name: str, *, minimum: int = 1, maximum: int | None = None) -> int:
    """Mathematics: Validate a strict integer in the finite interval [minimum, maximum]."""
    if type(value) is not int or value < minimum or (maximum is not None and value > maximum):
        upper = "" if maximum is None else f" and at most {maximum}"
        raise ComputationalFabricError(f"{name} must be an integer of at least {minimum}{upper}")
    return value


def _canonical_bytes(value: Any) -> bytes:
    """Mathematics: Encode finite JSON into sorted compact UTF-8 bytes."""
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ComputationalFabricError(f"value is not canonical JSON: {exc}") from exc


def _canonical_digest(value: Any) -> str:
    """Mathematics: Compute H(x)=SHA256(J(x)) over canonical JSON bytes."""
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _dns_name(value: Any, name: str) -> str:
    """Mathematics: Validate a bounded DNS identity without accepting wildcards or URL syntax."""
    _label(value, name, 253)
    parts = value.rstrip(".").split(".")
    if not parts or any(not _DNS_LABEL.fullmatch(part) for part in parts):
        raise ComputationalFabricError(f"{name} must be a DNS hostname without wildcards")
    return value.rstrip(".").lower()


def _metric_vector(
    values: Sequence[RouteMetric],
    metric_order: Sequence[RouteMetricKey],
    label: str,
) -> tuple[int, ...]:
    """Mathematics: Project a typed metric vector into the request's exact ordered additive basis."""
    by_name = {item.name: item for item in values}
    if len(by_name) != len(values) or set(by_name) != {item.name for item in metric_order}:
        raise ComputationalFabricError(f"{label} dimensions differ from the requested metric basis")
    vector: list[int] = []
    for key in metric_order:
        metric = by_name[key.name]
        if metric.unit != key.unit:
            raise ComputationalFabricError(f"{label} metric {key.name!r} has an incompatible unit")
        vector.append(metric.amount)
    return tuple(vector)


def _metrics_from_vector(
    values: Sequence[int],
    metric_order: Sequence[RouteMetricKey],
) -> tuple[RouteMetric, ...]:
    """Mathematics: Reconstruct the typed additive metric vector in its declared objective order."""
    return tuple(
        RouteMetric(key.name, key.unit, amount)
        for key, amount in zip(metric_order, values)
    )


def _json_kind_matches(value: Any, kind: str) -> bool:
    """Mathematics: Check the JSON type algebra admitted by OperatorSpec without Boolean/integer confusion."""
    if kind == "any":
        return True
    if kind == "object":
        return isinstance(value, Mapping)
    if kind == "array":
        return isinstance(value, (list, tuple))
    if kind == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if kind == "number":
        return (
            isinstance(value, int) and not isinstance(value, bool)
        ) or (isinstance(value, float) and math.isfinite(value))
    if kind == "string":
        return isinstance(value, str)
    if kind == "boolean":
        return isinstance(value, bool)
    if kind == "null":
        return value is None
    return False


@dataclass(frozen=True)
class ComputationalPeerEndpoint:
    """One authenticated directory/forwarding peer endpoint, distinct from logical host identity."""

    peer_id: str
    tls_server_name: str
    endpoint_host: str
    port: int

    def __post_init__(self) -> None:
        """Mathematics: Validate peer identity, DNS certificate name, endpoint and finite TCP port."""
        _peer_id(self.peer_id)
        object.__setattr__(self, "tls_server_name", _dns_name(self.tls_server_name, "tls_server_name"))
        _label(self.endpoint_host, "endpoint_host", 253)
        _positive(self.port, "peer endpoint port", maximum=65535)

    def to_dict(self) -> dict[str, Any]:
        """Mathematics: Serialize stable peer identity and its independently verified TLS endpoint."""
        return {
            "peer_id": self.peer_id,
            "tls_server_name": self.tls_server_name,
            "endpoint_host": self.endpoint_host,
            "port": self.port,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ComputationalPeerEndpoint":
        """Mathematics: Reconstruct an endpoint only from its exact declared field set."""
        if not isinstance(payload, Mapping) or set(payload) != {
            "peer_id", "tls_server_name", "endpoint_host", "port"
        }:
            raise ComputationalFabricError("peer endpoint fields are malformed")
        return cls(
            payload["peer_id"],
            payload["tls_server_name"],
            payload["endpoint_host"],
            payload["port"],
        )


@dataclass(frozen=True)
class ComputationalHostAdvertisement:
    """Portable remote host/operator metadata; it contains no PID, handler, or local runtime object."""

    host_id: str
    node_id: str
    peer_id: str
    operator_spec: OperatorSpec
    substrates: tuple[str, ...]
    computational_ground_fingerprints: tuple[str, ...]
    program_fingerprints: tuple[str, ...]
    supports_ground_program_compilation: bool
    supports_structural_memory: bool
    implementation_fingerprint: str | None
    costs: tuple[RouteMetric, ...]
    virtual_capacity: int
    max_energy: int
    max_bytes: int
    max_virtual_ticks: int

    def __post_init__(self) -> None:
        """Mathematics: Validate portable host identity, operator contract, admitted capabilities, costs and resource bounds."""
        if not isinstance(self.host_id, str) or _PEER_ID.fullmatch(self.host_id) is None:
            raise ComputationalFabricError("host_id is not a valid logical host identity")
        _label(self.node_id, "node_id", 128)
        _peer_id(self.peer_id)
        if not isinstance(self.operator_spec, OperatorSpec):
            raise ComputationalFabricError("host advertisement requires an OperatorSpec")
        substrates = tuple(self.substrates)
        if (
            not substrates
            or len(set(substrates)) != len(substrates)
            or any(item not in self.operator_spec.substrates for item in substrates)
        ):
            raise ComputationalFabricError("host substrates must be unique members of the operator contract")
        object.__setattr__(self, "substrates", tuple(sorted(substrates)))
        grounds = tuple(self.computational_ground_fingerprints)
        for item in grounds:
            _digest(item, "computational Ground fingerprint")
        if not grounds or len(set(grounds)) != len(grounds):
            raise ComputationalFabricError("host must advertise unique computational Ground fingerprints")
        object.__setattr__(self, "computational_ground_fingerprints", tuple(sorted(grounds)))
        programs = tuple(self.program_fingerprints)
        for item in programs:
            _digest(item, "program fingerprint")
        if len(set(programs)) != len(programs):
            raise ComputationalFabricError("program fingerprints must be unique")
        object.__setattr__(self, "program_fingerprints", tuple(sorted(programs)))
        if type(self.supports_ground_program_compilation) is not bool:
            raise ComputationalFabricError("supports_ground_program_compilation must be Boolean")
        if type(self.supports_structural_memory) is not bool:
            raise ComputationalFabricError("supports_structural_memory must be Boolean")
        if self.implementation_fingerprint is not None:
            _digest(self.implementation_fingerprint, "implementation_fingerprint")
        costs = tuple(self.costs)
        if not costs or any(not isinstance(item, RouteMetric) for item in costs):
            raise ComputationalFabricError("host advertisement requires typed route costs")
        if len({item.name for item in costs}) != len(costs):
            raise ComputationalFabricError("host cost metric names must be unique")
        object.__setattr__(self, "costs", tuple(sorted(costs, key=lambda item: item.name)))
        for name in ("virtual_capacity", "max_energy", "max_bytes", "max_virtual_ticks"):
            _positive(getattr(self, name), name)

    @classmethod
    def from_locus(
        cls,
        locus: ComputationalHostLocus,
        peer_id: str,
    ) -> "ComputationalHostAdvertisement":
        """Mathematics: project a trusted local host locus into portable metadata, stripping its process authority and object bindings."""
        if not isinstance(locus, ComputationalHostLocus):
            raise ComputationalFabricError("from_locus requires a ComputationalHostLocus")
        return cls(
            host_id=locus.host_id,
            node_id=locus.node_id,
            peer_id=_peer_id(peer_id),
            operator_spec=locus.operator_spec,
            substrates=locus.substrates,
            computational_ground_fingerprints=locus.computational_ground_fingerprints,
            program_fingerprints=locus.program_fingerprints,
            supports_ground_program_compilation=locus.supports_ground_program_compilation,
            supports_structural_memory=locus.supports_structural_memory,
            implementation_fingerprint=locus.implementation_fingerprint,
            costs=locus.costs,
            virtual_capacity=locus.virtual_capacity,
            max_energy=locus.max_energy,
            max_bytes=locus.max_bytes,
            max_virtual_ticks=locus.max_virtual_ticks,
        )

    @property
    def resource(self) -> str:
        """Mathematics: Return the exact capability resource for the advertised operator version."""
        from .virtual_layer import virtual_layer_operator_resource

        return virtual_layer_operator_resource(
            self.operator_spec.operator_id,
            self.operator_spec.version,
        )

    def to_dict(self) -> dict[str, Any]:
        """Mathematics: Serialize the operator, Ground/program support, costs, and runtime bounds without local authority."""
        return {
            "host_id": self.host_id,
            "node_id": self.node_id,
            "peer_id": self.peer_id,
            "operator_spec": self.operator_spec.to_dict(),
            "substrates": list(self.substrates),
            "computational_ground_fingerprints": list(self.computational_ground_fingerprints),
            "program_fingerprints": list(self.program_fingerprints),
            "supports_ground_program_compilation": self.supports_ground_program_compilation,
            "supports_structural_memory": self.supports_structural_memory,
            "implementation_fingerprint": self.implementation_fingerprint,
            "costs": [item.to_dict() for item in self.costs],
            "virtual_capacity": self.virtual_capacity,
            "max_energy": self.max_energy,
            "max_bytes": self.max_bytes,
            "max_virtual_ticks": self.max_virtual_ticks,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ComputationalHostAdvertisement":
        """Mathematics: Reconstruct portable host metadata only after exact field-set and nested contract validation."""
        expected = {
            "host_id", "node_id", "peer_id", "operator_spec", "substrates",
            "computational_ground_fingerprints", "program_fingerprints",
            "supports_ground_program_compilation", "supports_structural_memory",
            "implementation_fingerprint", "costs", "virtual_capacity",
            "max_energy", "max_bytes", "max_virtual_ticks",
        }
        if not isinstance(payload, Mapping) or set(payload) != expected:
            raise ComputationalFabricError("host advertisement fields are malformed")
        try:
            return cls(
                payload["host_id"],
                payload["node_id"],
                payload["peer_id"],
                OperatorSpec.from_dict(payload["operator_spec"]),
                tuple(payload["substrates"]),
                tuple(payload["computational_ground_fingerprints"]),
                tuple(payload["program_fingerprints"]),
                payload["supports_ground_program_compilation"],
                payload["supports_structural_memory"],
                payload["implementation_fingerprint"],
                tuple(RouteMetric.from_dict(item) for item in payload["costs"]),
                payload["virtual_capacity"],
                payload["max_energy"],
                payload["max_bytes"],
                payload["max_virtual_ticks"],
            )
        except (KeyError, TypeError, ValueError) as exc:
            if isinstance(exc, ComputationalFabricError):
                raise
            raise ComputationalFabricError("host advertisement contains invalid nested fields") from exc

    @property
    def digest(self) -> str:
        """Mathematics: Identify portable host metadata by its canonical SHA-256 projection."""
        return _canonical_digest(self.to_dict())


@dataclass(frozen=True)
class ComputationalNetworkLink:
    """Directed advertised peer adjacency with typed additive costs and a finite frame-size ceiling."""

    source_peer_id: str
    target_peer_id: str
    costs: tuple[RouteMetric, ...]
    enabled: bool = True
    max_frame_bytes: int = 1_048_576

    def __post_init__(self) -> None:
        """Mathematics: Validate directed peer identity, finite typed link costs, status and frame-size ceiling."""
        _peer_id(self.source_peer_id, "source_peer_id")
        _peer_id(self.target_peer_id, "target_peer_id")
        if self.source_peer_id == self.target_peer_id:
            raise ComputationalFabricError("network links cannot be self-loops")
        costs = tuple(self.costs)
        if not costs or any(not isinstance(item, RouteMetric) for item in costs):
            raise ComputationalFabricError("network link requires typed route costs")
        if len({item.name for item in costs}) != len(costs):
            raise ComputationalFabricError("network link metric names must be unique")
        object.__setattr__(self, "costs", tuple(sorted(costs, key=lambda item: item.name)))
        if type(self.enabled) is not bool:
            raise ComputationalFabricError("network link enabled must be Boolean")
        _positive(self.max_frame_bytes, "max_frame_bytes")

    def to_dict(self) -> dict[str, Any]:
        """Mathematics: Serialize one directed adjacency, status and transport frame bound."""
        return {
            "source_peer_id": self.source_peer_id,
            "target_peer_id": self.target_peer_id,
            "costs": [item.to_dict() for item in self.costs],
            "enabled": self.enabled,
            "max_frame_bytes": self.max_frame_bytes,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ComputationalNetworkLink":
        """Mathematics: Reconstruct one exact directed edge from its strict portable schema."""
        expected = {"source_peer_id", "target_peer_id", "costs", "enabled", "max_frame_bytes"}
        if not isinstance(payload, Mapping) or set(payload) != expected:
            raise ComputationalFabricError("network link fields are malformed")
        return cls(
            payload["source_peer_id"],
            payload["target_peer_id"],
            tuple(RouteMetric.from_dict(item) for item in payload["costs"]),
            payload["enabled"],
            payload["max_frame_bytes"],
        )

    @property
    def link_id(self) -> str:
        """Mathematics: Identify an advertised directed edge by SHA-256 of its complete portable semantics."""
        return _canonical_digest(self.to_dict())


@dataclass(frozen=True)
class ComputationalPeerSnapshot:
    """One revisioned peer-owned host and outgoing-link snapshot returned over authenticated TLS."""

    endpoint: ComputationalPeerEndpoint
    revision: int
    lease_seconds: int
    hosts: tuple[ComputationalHostAdvertisement, ...]
    links: tuple[ComputationalNetworkLink, ...]

    def __post_init__(self) -> None:
        """Mathematics: Require a peer-owned finite snapshot with unique host/operator and outgoing-link identities."""
        if not isinstance(self.endpoint, ComputationalPeerEndpoint):
            raise ComputationalFabricError("peer snapshot requires a typed endpoint")
        _positive(self.revision, "peer revision", minimum=0)
        _positive(self.lease_seconds, "peer lease", maximum=_MAX_PEER_LEASE_SECONDS)
        hosts = tuple(self.hosts)
        if len(hosts) > _MAX_HOST_ADVERTISEMENTS or any(
            not isinstance(item, ComputationalHostAdvertisement) for item in hosts
        ):
            raise ComputationalFabricError("peer snapshot host set exceeds its bound or contains invalid values")
        if any(item.peer_id != self.endpoint.peer_id for item in hosts):
            raise ComputationalFabricError("peer snapshot contains a host owned by another peer")
        host_keys = [
            (item.host_id, item.operator_spec.operator_id, item.operator_spec.version)
            for item in hosts
        ]
        if len(set(host_keys)) != len(host_keys):
            raise ComputationalFabricError("peer snapshot contains duplicate host/operator identities")
        object.__setattr__(
            self,
            "hosts",
            tuple(sorted(hosts, key=lambda item: (item.host_id, item.operator_spec.operator_id, item.operator_spec.version))),
        )
        links = tuple(self.links)
        if len(links) > _MAX_NETWORK_LINKS or any(
            not isinstance(item, ComputationalNetworkLink) for item in links
        ):
            raise ComputationalFabricError("peer snapshot link set exceeds its bound or contains invalid values")
        if any(item.source_peer_id != self.endpoint.peer_id for item in links):
            raise ComputationalFabricError("peer snapshot may advertise only its own outgoing links")
        link_ids = [item.link_id for item in links]
        if len(set(link_ids)) != len(link_ids):
            raise ComputationalFabricError("peer snapshot contains duplicate network links")
        object.__setattr__(self, "links", tuple(sorted(links, key=lambda item: item.link_id)))

    @property
    def peer_id(self) -> str:
        """Mathematics: Project the stable peer identity from the endpoint bound into this snapshot."""
        return self.endpoint.peer_id

    def to_dict(self) -> dict[str, Any]:
        """Mathematics: Serialize the peer-owned snapshot with revision, lease, host advertisements and directed links."""
        return {
            "schema": "mailcpu.computational-peer-snapshot.v1",
            "endpoint": self.endpoint.to_dict(),
            "revision": self.revision,
            "lease_seconds": self.lease_seconds,
            "hosts": [item.to_dict() for item in self.hosts],
            "links": [item.to_dict() for item in self.links],
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ComputationalPeerSnapshot":
        """Mathematics: Reconstruct a peer snapshot after exact schema and nested identity checks."""
        expected = {"schema", "endpoint", "revision", "lease_seconds", "hosts", "links"}
        if not isinstance(payload, Mapping) or set(payload) != expected:
            raise ComputationalFabricError("peer snapshot fields are malformed")
        if payload["schema"] != "mailcpu.computational-peer-snapshot.v1":
            raise ComputationalFabricError("peer snapshot schema is unsupported")
        try:
            return cls(
                ComputationalPeerEndpoint.from_dict(payload["endpoint"]),
                payload["revision"],
                payload["lease_seconds"],
                tuple(ComputationalHostAdvertisement.from_dict(item) for item in payload["hosts"]),
                tuple(ComputationalNetworkLink.from_dict(item) for item in payload["links"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            if isinstance(exc, ComputationalFabricError):
                raise
            raise ComputationalFabricError("peer snapshot contains invalid nested fields") from exc

    @property
    def digest(self) -> str:
        """Mathematics: Identify a peer snapshot revision using its complete canonical content."""
        return _canonical_digest(self.to_dict())


class ComputationalFabricAuthority:
    """Peer-local authority that publishes only its own registered hosts and outgoing network links."""

    def __init__(
        self,
        endpoint: ComputationalPeerEndpoint,
        *,
        lease_seconds: int = 60,
    ) -> None:
        """Mathematics: Bind one peer identity to a monotonic revisioned advertisement set."""
        if not isinstance(endpoint, ComputationalPeerEndpoint):
            raise ComputationalFabricError("fabric authority requires a ComputationalPeerEndpoint")
        self.endpoint = endpoint
        self.lease_seconds = _positive(
            lease_seconds,
            "lease_seconds",
            maximum=_MAX_PEER_LEASE_SECONDS,
        )
        self._revision = 0
        self._hosts: dict[tuple[str, str, int], ComputationalHostAdvertisement] = {}
        self._links: dict[str, ComputationalNetworkLink] = {}
        self._lock = threading.RLock()

    @property
    def revision(self) -> int:
        """Mathematics: Expose the current monotonic advertisement revision."""
        with self._lock:
            return self._revision

    def register_host(
        self,
        advertisement: ComputationalHostAdvertisement | ComputationalHostLocus,
    ) -> str:
        """Mathematics: Register one peer-owned portable host advertisement, stripping all local execution authority."""
        if isinstance(advertisement, ComputationalHostLocus):
            advertisement = ComputationalHostAdvertisement.from_locus(
                advertisement,
                self.endpoint.peer_id,
            )
        if not isinstance(advertisement, ComputationalHostAdvertisement):
            raise ComputationalFabricError("register_host requires a host advertisement or local host locus")
        if advertisement.peer_id != self.endpoint.peer_id:
            raise ComputationalFabricError("a peer may register only host loci it owns")
        key = (
            advertisement.host_id,
            advertisement.operator_spec.operator_id,
            advertisement.operator_spec.version,
        )
        with self._lock:
            existing = self._hosts.get(key)
            if existing == advertisement:
                return advertisement.digest
            if existing is None and len(self._hosts) >= _MAX_HOST_ADVERTISEMENTS:
                raise ComputationalFabricError("peer host catalogue exceeds its advertisement bound")
            self._hosts[key] = advertisement
            self._revision += 1
            return advertisement.digest

    def remove_host(self, host_id: str, operator_id: str, version: int = 1) -> bool:
        """Mathematics: Remove one exact host/operator registration and advance the peer revision iff it existed."""
        key = (_label(host_id, "host_id"), _label(operator_id, "operator_id"), _positive(version, "version"))
        with self._lock:
            if self._hosts.pop(key, None) is None:
                return False
            self._revision += 1
            return True

    def register_link(self, link: ComputationalNetworkLink) -> str:
        """Mathematics: Register one directed outgoing link whose source is this authenticated peer."""
        if not isinstance(link, ComputationalNetworkLink):
            raise ComputationalFabricError("register_link requires a ComputationalNetworkLink")
        if link.source_peer_id != self.endpoint.peer_id:
            raise ComputationalFabricError("peer may register only its own outgoing links")
        with self._lock:
            existing = self._links.get(link.link_id)
            if existing == link:
                return link.link_id
            self._links[link.link_id] = link
            if len(self._links) > _MAX_NETWORK_LINKS:
                del self._links[link.link_id]
                raise ComputationalFabricError("peer link catalogue exceeds its bound")
            self._revision += 1
            return link.link_id

    def remove_link(self, link_id: str) -> bool:
        """Mathematics: Remove one exact content-addressed link and revise the peer snapshot iff it existed."""
        _digest(link_id, "link_id")
        with self._lock:
            if self._links.pop(link_id, None) is None:
                return False
            self._revision += 1
            return True

    def snapshot(self) -> ComputationalPeerSnapshot:
        """Mathematics: Produce the exact current peer-owned host and topology revision."""
        with self._lock:
            return ComputationalPeerSnapshot(
                self.endpoint,
                self._revision,
                self.lease_seconds,
                tuple(self._hosts.values()),
                tuple(self._links.values()),
            )

    @classmethod
    def from_snapshot(
        cls,
        snapshot: ComputationalPeerSnapshot,
    ) -> "ComputationalFabricAuthority":
        """Mathematics: Restore a peer-owned advertisement revision without importing receiver process authority."""
        if not isinstance(snapshot, ComputationalPeerSnapshot):
            raise ComputationalFabricError("authority restoration requires a ComputationalPeerSnapshot")
        authority = cls(
            snapshot.endpoint,
            lease_seconds=snapshot.lease_seconds,
        )
        authority._revision = snapshot.revision
        authority._hosts = {
            (
                item.host_id,
                item.operator_spec.operator_id,
                item.operator_spec.version,
            ): item
            for item in snapshot.hosts
        }
        authority._links = {item.link_id: item for item in snapshot.links}
        return authority


class ComputationalFabricDirectory:
    """Federated last-known peer directory with direct-TLS trust, revision monotonicity and local lease expiry."""

    def __init__(
        self,
        local_peer_id: str,
        trusted_peers: Mapping[str, str],
        *,
        max_peer_lease_seconds: int = 120,
        monotonic: Callable[[], float] = time.monotonic,
        max_peers: int = 256,
        max_hosts: int = 4096,
        max_links: int = 16_000,
    ) -> None:
        """Mathematics: establish local identity, explicit peer→DNS trust, finite catalogue bounds, and a local monotonic lease clock."""
        self.local_peer_id = _peer_id(local_peer_id, "local_peer_id")
        if not isinstance(trusted_peers, Mapping):
            raise ComputationalFabricError("trusted_peers must map peer identities to TLS DNS identities")
        normalized: dict[str, str] = {}
        for peer, dns_name in trusted_peers.items():
            peer_id = _peer_id(peer)
            if peer_id == self.local_peer_id or peer_id in normalized:
                raise ComputationalFabricError("trusted peer identities must be unique and exclude the local peer")
            normalized[peer_id] = _dns_name(dns_name, "trusted peer DNS identity")
        self._trusted_peers = dict(sorted(normalized.items()))
        self._lock = threading.RLock()
        self.max_peer_lease_seconds = _positive(
            max_peer_lease_seconds,
            "max_peer_lease_seconds",
            maximum=_MAX_PEER_LEASE_SECONDS,
        )
        if not callable(monotonic):
            raise ComputationalFabricError("monotonic must be callable")
        self._monotonic = monotonic
        self.max_peers = _positive(max_peers, "max_peers", maximum=4096)
        self.max_hosts = _positive(max_hosts, "max_hosts", maximum=65_536)
        self.max_links = _positive(max_links, "max_links", maximum=262_144)
        self._snapshots: dict[str, ComputationalPeerSnapshot] = {}
        self._deadlines: dict[str, float] = {}
        self._local_snapshot: ComputationalPeerSnapshot | None = None

    @property
    def trusted_peers(self) -> dict[str, str]:
        """Mathematics: Return a detached view of the immutable peer→TLS-DNS bootstrap trust mapping."""
        return dict(self._trusted_peers)

    @property
    def peer_snapshots(self) -> tuple[ComputationalPeerSnapshot, ...]:
        """Mathematics: Return all last-known peer snapshots in stable peer-id order, including expired entries."""
        with self._lock:
            values = dict(self._snapshots)
            if self._local_snapshot is not None:
                values[self.local_peer_id] = self._local_snapshot
            return tuple(values[key] for key in sorted(values))

    @property
    def active_snapshots(self) -> tuple[ComputationalPeerSnapshot, ...]:
        """Mathematics: Return only the local snapshot and remote snapshots whose receiver-local leases remain live."""
        with self._lock:
            now = self._monotonic()
            selected: dict[str, ComputationalPeerSnapshot] = {}
            if self._local_snapshot is not None:
                selected[self.local_peer_id] = self._local_snapshot
            for peer_id, snapshot in self._snapshots.items():
                if now < self._deadlines.get(peer_id, float("-inf")):
                    selected[peer_id] = snapshot
            return tuple(selected[key] for key in sorted(selected))

    @property
    def hosts(self) -> tuple[ComputationalHostAdvertisement, ...]:
        """Mathematics: Project host advertisements from active authenticated peer snapshots in stable identity order."""
        return tuple(
            sorted(
                (host for snapshot in self.active_snapshots for host in snapshot.hosts),
                key=lambda item: (item.host_id, item.operator_spec.operator_id, item.operator_spec.version, item.peer_id),
            )
        )

    @property
    def links(self) -> tuple[ComputationalNetworkLink, ...]:
        """Mathematics: Project directed links only from active peer-owned topology snapshots."""
        return tuple(
            sorted(
                (link for snapshot in self.active_snapshots for link in snapshot.links),
                key=lambda item: item.link_id,
            )
        )

    @property
    def expired_peer_ids(self) -> tuple[str, ...]:
        """Mathematics: Return remote peer identities whose local lease deadlines have elapsed."""
        with self._lock:
            now = self._monotonic()
            return tuple(sorted(
                peer_id for peer_id, deadline in self._deadlines.items()
                if now >= deadline
            ))

    def register_local_snapshot(self, snapshot: ComputationalPeerSnapshot) -> bool:
        """Mathematics: Register the local peer's own snapshot without inventing a remote TLS observation."""
        if not isinstance(snapshot, ComputationalPeerSnapshot):
            raise ComputationalFabricError("local registration requires a ComputationalPeerSnapshot")
        if snapshot.peer_id != self.local_peer_id:
            raise ComputationalFabricError("local snapshot peer identity differs from this directory")
        with self._lock:
            if self._local_snapshot is not None:
                previous = self._local_snapshot
                if snapshot.revision < previous.revision:
                    raise ComputationalFabricError("local peer snapshot revision cannot move backwards")
                if snapshot.revision == previous.revision:
                    if snapshot.digest != previous.digest:
                        raise ComputationalFabricError("local peer equivocated at an existing snapshot revision")
                    return False
            self._validate_capacity(snapshot, replacing_peer=self.local_peer_id)
            self._local_snapshot = snapshot
            return True

    def merge_authenticated_snapshot(
        self,
        snapshot: ComputationalPeerSnapshot,
        *,
        authenticated_transport: SocketTransport,
    ) -> bool:
        """Mathematics: Admit a snapshot only from the actual trusted mutual-TLS stream and its verified peer certificate."""
        if not isinstance(snapshot, ComputationalPeerSnapshot):
            raise ComputationalFabricError("remote merge requires a ComputationalPeerSnapshot")
        if not isinstance(authenticated_transport, SocketTransport):
            raise ComputationalFabricError("authenticated merge requires a SocketTransport")
        if authenticated_transport.local_endpoint != self.local_peer_id:
            raise ComputationalFabricError("authenticated transport is not bound to this local peer")
        peer_id = _peer_id(authenticated_transport.peer_endpoint, "authenticated transport peer")
        with self._lock:
            expected_dns = self._trusted_peers.get(peer_id)
        if expected_dns is None:
            raise ComputationalFabricError("snapshot source is not an explicitly trusted direct peer")
        if not _certificate_has_dns(authenticated_transport, expected_dns):
            raise ComputationalFabricError("transport peer certificate chain or DNS SAN is not authenticated")
        return self._merge_verified_peer_snapshot(
            snapshot,
            authenticated_peer_id=peer_id,
            authenticated_server_name=expected_dns,
        )

    def _merge_verified_peer_snapshot(
        self,
        snapshot: ComputationalPeerSnapshot,
        *,
        authenticated_peer_id: str,
        authenticated_server_name: str,
    ) -> bool:
        """Mathematics: Apply revision/lease state only after a trusted ingress has verified the direct peer transport."""
        if not isinstance(snapshot, ComputationalPeerSnapshot):
            raise ComputationalFabricError("verified merge requires a ComputationalPeerSnapshot")
        peer_id = _peer_id(authenticated_peer_id, "authenticated_peer_id")
        server_name = _dns_name(authenticated_server_name, "authenticated_server_name")
        if snapshot.peer_id != peer_id:
            raise ComputationalFabricError("snapshot peer identity differs from the authenticated transport peer")
        with self._lock:
            expected_dns = self._trusted_peers.get(peer_id)
            if expected_dns is None:
                raise ComputationalFabricError("snapshot source is not an explicitly trusted direct peer")
            if server_name != expected_dns or snapshot.endpoint.tls_server_name != expected_dns:
                raise ComputationalFabricError("authenticated TLS DNS identity differs from configured peer trust")
            previous = self._snapshots.get(peer_id)
            if previous is not None:
                if snapshot.revision < previous.revision:
                    raise ComputationalFabricError("peer snapshot revision rollback detected")
                if snapshot.revision == previous.revision and snapshot.digest != previous.digest:
                    raise ComputationalFabricError("peer equivocated at an existing snapshot revision")
            self._validate_capacity(snapshot, replacing_peer=peer_id)
            changed = previous is None or previous.digest != snapshot.digest
            self._snapshots[peer_id] = snapshot
            self._deadlines[peer_id] = self._monotonic() + min(
                snapshot.lease_seconds,
                self.max_peer_lease_seconds,
            )
            return changed

    def _validate_capacity(
        self,
        incoming: ComputationalPeerSnapshot,
        *,
        replacing_peer: str,
    ) -> None:
        """Mathematics: Check aggregate peer, host and link cardinalities before atomically admitting one revision."""
        snapshots = {
            peer_id: snapshot
            for peer_id, snapshot in self._snapshots.items()
            if peer_id != replacing_peer
        }
        if replacing_peer == self.local_peer_id:
            local_count = 1
        else:
            local_count = int(self._local_snapshot is not None)
        snapshots[incoming.peer_id] = incoming
        peer_count = len(snapshots) + local_count
        host_count = sum(len(item.hosts) for item in snapshots.values())
        link_count = sum(len(item.links) for item in snapshots.values())
        if self._local_snapshot is not None and replacing_peer != self.local_peer_id:
            host_count += len(self._local_snapshot.hosts)
            link_count += len(self._local_snapshot.links)
        if peer_count > self.max_peers:
            raise ComputationalFabricError("federated peer directory exceeds its peer bound")
        if host_count > self.max_hosts:
            raise ComputationalFabricError("federated host directory exceeds its host bound")
        if link_count > self.max_links:
            raise ComputationalFabricError("federated topology exceeds its directed-link bound")

    def purge_expired(self) -> tuple[str, ...]:
        """Mathematics: Remove expired remote snapshots and leases without mutating the local authority record."""
        with self._lock:
            now = self._monotonic()
            expired = tuple(sorted(
                peer_id for peer_id, deadline in self._deadlines.items()
                if now >= deadline
            ))
            for peer_id in expired:
                self._snapshots.pop(peer_id, None)
                self._deadlines.pop(peer_id, None)
            return expired

    @property
    def digest(self) -> str:
        """Mathematics: Bind the current active peer set, all active snapshot revisions, trust map and local identity."""
        active = self.active_snapshots
        return _canonical_digest({
            "schema": "mailcpu.computational-fabric-directory.v1",
            "local_peer_id": self.local_peer_id,
            "trusted_peers": self.trusted_peers,
            "active_peer_ids": [item.peer_id for item in active],
            "snapshots": [item.to_dict() for item in active],
        })

    @property
    def topology_digest(self) -> str:
        """Mathematics: Bind active peer endpoints and directed link state independently of operator advertisements."""
        active = self.active_snapshots
        return _canonical_digest({
            "peers": [item.endpoint.to_dict() for item in active],
            "links": [link.to_dict() for item in active for link in item.links],
        })


def _certificate_has_dns(transport: SocketTransport, dns_name: str) -> bool:
    """Mathematics: Require a completed TLS stream whose authenticated certificate contains the exact expected DNS SAN."""
    stream = getattr(transport, "socket", None)
    if not isinstance(stream, ssl.SSLSocket):
        return False
    # A SAN string alone is not authentication. Require that the stream's
    # handshake context also required and verified the peer certificate chain.
    if stream.context.verify_mode != ssl.CERT_REQUIRED:
        return False
    try:
        certificate = stream.getpeercert()
    except (OSError, ValueError):
        return False
    return any(
        kind == "DNS" and value.rstrip(".").lower() == dns_name.rstrip(".").lower()
        for kind, value in certificate.get("subjectAltName", ())
    )


class ComputationalFabricPeerServer:
    """Reliable snapshot responder for one mutual-TLS-authenticated client and one peer-local authority."""

    def __init__(
        self,
        authority: ComputationalFabricAuthority,
        transport: SocketTransport,
        client_peer_id: str,
        *,
        expected_client_dns: str,
        policy: ReliabilityPolicy | None = None,
    ) -> None:
        """Mathematics: Bind reciprocal reliable channels to the one TLS-authenticated client and peer-owned directory authority."""
        if not isinstance(authority, ComputationalFabricAuthority):
            raise ComputationalFabricError("peer server requires a ComputationalFabricAuthority")
        if not isinstance(transport, SocketTransport):
            raise ComputationalFabricError("peer server requires a SocketTransport")
        client_id = _peer_id(client_peer_id, "client_peer_id")
        expected_dns = _dns_name(expected_client_dns, "expected_client_dns")
        if (
            transport.local_endpoint != authority.endpoint.peer_id
            or transport.peer_endpoint != client_id
            or not _certificate_has_dns(transport, expected_dns)
        ):
            raise ComputationalFabricError("peer server stream is not bound to the configured authenticated client")
        self.authority = authority
        self.transport = transport
        self.client_peer_id = client_id
        selected_policy = policy or ReliabilityPolicy(lease_ticks=3, max_attempts=16, window_size=8)
        self.inbound = ReliableChannel(
            transport,
            authority.endpoint.peer_id,
            authority.endpoint.peer_id,
            COMPUTATIONAL_DIRECTORY_REQUEST_CHANNEL,
            selected_policy,
            peer=client_id,
        )
        self.outbound = ReliableChannel(
            transport,
            authority.endpoint.peer_id,
            client_id,
            COMPUTATIONAL_DIRECTORY_RESPONSE_CHANNEL,
            selected_policy,
        )

    @classmethod
    def accept_mutual_tls(
        cls,
        authority: ComputationalFabricAuthority,
        listener: socket.socket,
        client_peer_id: str,
        *,
        expected_client_dns: str,
        tls_context: ssl.SSLContext,
        policy: ReliabilityPolicy | None = None,
        handshake_timeout: float = 5.0,
    ) -> "ComputationalFabricPeerServer":
        """Mathematics: Accept a directory client only after CA, client-certificate and exact DNS-SAN validation."""
        if not isinstance(authority, ComputationalFabricAuthority):
            raise ComputationalFabricError("accept requires a ComputationalFabricAuthority")
        transport = accept_mutual_tls(
            listener,
            authority.endpoint.peer_id,
            client_peer_id,
            tls_context,
            expected_peer_dns=expected_client_dns,
            handshake_timeout=handshake_timeout,
        )
        try:
            return cls(
                authority,
                transport,
                client_peer_id,
                expected_client_dns=expected_client_dns,
                policy=policy,
            )
        except Exception:
            transport.close()
            raise

    def service_once(self) -> bool:
        """Mathematics: Commit one snapshot request into the reliable response channel before acknowledging its inbound sequence."""
        self.outbound.process_ack()
        if self.outbound.available_window < 1:
            self.outbound.tick()
            return False
        handled = False

        def apply(_sequence: int, payload: Any) -> None:
            """Mathematics: Encode one validated snapshot request into a reliable response before inbound acknowledgement."""
            nonlocal handled
            handled = True
            if not isinstance(payload, Mapping) or set(payload) != {"kind", "request_id"}:
                response = {
                    "kind": COMPUTATIONAL_DIRECTORY_ERROR_KIND,
                    "request_id": "",
                    "peer_id": self.authority.endpoint.peer_id,
                    "error": "directory request fields are malformed",
                }
            elif payload.get("kind") != COMPUTATIONAL_DIRECTORY_REQUEST_KIND:
                response = {
                    "kind": COMPUTATIONAL_DIRECTORY_ERROR_KIND,
                    "request_id": payload.get("request_id", ""),
                    "peer_id": self.authority.endpoint.peer_id,
                    "error": "directory request kind is unsupported",
                }
            else:
                request_id = payload.get("request_id")
                if not isinstance(request_id, str) or not request_id or len(request_id) > 256:
                    response = {
                        "kind": COMPUTATIONAL_DIRECTORY_ERROR_KIND,
                        "request_id": "",
                        "peer_id": self.authority.endpoint.peer_id,
                        "error": "directory request correlation identity is invalid",
                    }
                else:
                    response = {
                        "kind": COMPUTATIONAL_DIRECTORY_SNAPSHOT_KIND,
                        "request_id": request_id,
                        "peer_id": self.authority.endpoint.peer_id,
                        "snapshot": self.authority.snapshot().to_dict(),
                    }
            self.outbound.send(response)

        received = self.inbound.receive(commit=apply)
        self.outbound.tick()
        return handled or received is not None

    def serve_forever(
        self,
        stop_event: threading.Event,
        *,
        idle_sleep: float = 0.002,
    ) -> None:
        """Mathematics: Service reliable directory requests until the supplied finite-control event is set."""
        if not isinstance(stop_event, threading.Event):
            raise ComputationalFabricError("stop_event must be a threading.Event")
        if not isinstance(idle_sleep, (int, float)) or isinstance(idle_sleep, bool) or idle_sleep <= 0:
            raise ComputationalFabricError("idle_sleep must be positive")
        while not stop_event.is_set() and not self.transport.closed:
            if not self.service_once():
                time.sleep(float(idle_sleep))

    def close(self) -> None:
        """Mathematics: Close the underlying mutually authenticated peer stream."""
        self.transport.close()


class ComputationalFabricPeerClient:
    """Mutual-TLS directory client using reliable request/response channels and monotonic RPC deadlines."""

    def __init__(
        self,
        local_peer_id: str,
        remote_endpoint: ComputationalPeerEndpoint,
        transport: SocketTransport,
        *,
        timeout: float = 3.0,
        policy: ReliabilityPolicy | None = None,
    ) -> None:
        """Mathematics: Bind a TLS-authenticated remote endpoint to exact peer IDs and reciprocal reliable channels."""
        local_id = _peer_id(local_peer_id, "local_peer_id")
        if not isinstance(remote_endpoint, ComputationalPeerEndpoint):
            raise ComputationalFabricError("peer client requires a ComputationalPeerEndpoint")
        if not isinstance(transport, SocketTransport):
            raise ComputationalFabricError("peer client requires a SocketTransport")
        if (
            transport.local_endpoint != local_id
            or transport.peer_endpoint != remote_endpoint.peer_id
            or not _certificate_has_dns(transport, remote_endpoint.tls_server_name)
        ):
            raise ComputationalFabricError("peer client stream is not bound to the expected TLS server identity")
        if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or timeout <= 0:
            raise ComputationalFabricError("peer RPC timeout must be positive")
        self.local_peer_id = local_id
        self.remote_endpoint = remote_endpoint
        self.transport = transport
        self.timeout = float(timeout)
        self._sequence = 0
        selected_policy = policy or ReliabilityPolicy(lease_ticks=3, max_attempts=16, window_size=8)
        self.requests = ReliableChannel(
            transport,
            local_id,
            remote_endpoint.peer_id,
            COMPUTATIONAL_DIRECTORY_REQUEST_CHANNEL,
            selected_policy,
        )
        self.responses = ReliableChannel(
            transport,
            local_id,
            local_id,
            COMPUTATIONAL_DIRECTORY_RESPONSE_CHANNEL,
            selected_policy,
            peer=remote_endpoint.peer_id,
        )

    @classmethod
    def connect_mutual_tls(
        cls,
        local_peer_id: str,
        remote_endpoint: ComputationalPeerEndpoint,
        context: ssl.SSLContext,
        *,
        timeout: float = 3.0,
        handshake_timeout: float = 5.0,
        policy: ReliabilityPolicy | None = None,
    ) -> "ComputationalFabricPeerClient":
        """Mathematics: Connect only after the peer certificate chain and exact server DNS identity validate."""
        if not isinstance(remote_endpoint, ComputationalPeerEndpoint):
            raise ComputationalFabricError("connect_mutual_tls requires a ComputationalPeerEndpoint")
        transport = connect_mutual_tls(
            remote_endpoint.endpoint_host,
            remote_endpoint.port,
            _peer_id(local_peer_id, "local_peer_id"),
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
                timeout=timeout,
                policy=policy,
            )
        except Exception:
            transport.close()
            raise

    def _exchange_snapshot(self) -> ComputationalPeerSnapshot:
        """Mathematics: Obtain one correlated revisioned snapshot before a finite monotonic deadline."""
        self._sequence += 1
        request_id = f"{self.local_peer_id}:{self._sequence}"
        try:
            self.requests.process_ack()
            self.requests.send({
                "kind": COMPUTATIONAL_DIRECTORY_REQUEST_KIND,
                "request_id": request_id,
            })
        except Exception as exc:
            raise ComputationalFabricError(f"cannot send directory snapshot request: {exc}") from exc

        deadline = time.monotonic() + self.timeout
        last_tick = time.monotonic()
        while time.monotonic() < deadline:
            try:
                self.requests.process_ack()
                now = time.monotonic()
                if now - last_tick >= 0.03:
                    self.requests.tick()
                    last_tick = now
                received = self.responses.receive()
            except Exception as exc:
                raise ComputationalFabricError(f"directory peer stream failed: {exc}") from exc
            if received is not None:
                _sequence, response = received
                if not isinstance(response, Mapping):
                    raise ComputationalFabricError("directory peer response must be a mapping")
                if (
                    response.get("request_id") != request_id
                    or response.get("peer_id") != self.remote_endpoint.peer_id
                ):
                    raise ComputationalFabricError("directory response correlation or peer identity mismatch")
                if response.get("kind") == COMPUTATIONAL_DIRECTORY_ERROR_KIND:
                    raise ComputationalFabricError(
                        str(response.get("error", "remote directory peer refused request"))
                    )
                if response.get("kind") != COMPUTATIONAL_DIRECTORY_SNAPSHOT_KIND:
                    raise ComputationalFabricError("directory response kind is unsupported")
                snapshot = ComputationalPeerSnapshot.from_dict(response.get("snapshot"))
                if snapshot.endpoint != self.remote_endpoint:
                    raise ComputationalFabricError("directory snapshot endpoint differs from authenticated peer endpoint")
                return snapshot
            time.sleep(0.002)
        raise ComputationalFabricError("directory peer did not answer before the RPC deadline")

    def refresh(self, directory: ComputationalFabricDirectory) -> bool:
        """Mathematics: Merge a fetched peer snapshot only under the directly verified TLS peer and DNS identities."""
        if not isinstance(directory, ComputationalFabricDirectory):
            raise ComputationalFabricError("refresh requires a ComputationalFabricDirectory")
        if directory.local_peer_id != self.local_peer_id:
            raise ComputationalFabricError("directory local peer identity differs from this client")
        snapshot = self._exchange_snapshot()
        return directory.merge_authenticated_snapshot(
            snapshot,
            authenticated_transport=self.transport,
        )

    def close(self) -> None:
        """Mathematics: Close this peer client's authenticated stream."""
        self.transport.close()


@dataclass(frozen=True)
class ComputationalFabricBlocker:
    """One host/path exclusion with a deterministic logical host and optional peer identity."""

    subject_id: str
    code: ComputationalFabricBlockerCode
    detail: str = ""

    def __post_init__(self) -> None:
        """Mathematics: Validate one stable subject identity, typed blocker code and textual explanation."""
        _label(self.subject_id, "blocker subject_id", 256)
        if not isinstance(self.code, ComputationalFabricBlockerCode):
            object.__setattr__(self, "code", ComputationalFabricBlockerCode(self.code))
        if not isinstance(self.detail, str):
            raise ComputationalFabricError("blocker detail must be text")

    def to_dict(self) -> dict[str, Any]:
        """Mathematics: Serialize one stable blocker record."""
        return {
            "subject_id": self.subject_id,
            "code": self.code.value,
            "detail": self.detail,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ComputationalFabricBlocker":
        """Mathematics: Reconstruct one blocker from its exact portable field set."""
        if not isinstance(payload, Mapping) or set(payload) != {"subject_id", "code", "detail"}:
            raise ComputationalFabricError("fabric blocker fields are malformed")
        return cls(
            payload["subject_id"],
            ComputationalFabricBlockerCode(payload["code"]),
            payload["detail"],
        )


@dataclass(frozen=True)
class ComputationalFabricRouteWitness:
    """Non-authoritative multi-hop route proposal binding a semantic address to a remote advertised host."""

    address_digest: str
    directory_digest: str
    topology_digest: str
    origin_peer_id: str
    peer_path: tuple[str, ...]
    link_ids: tuple[str, ...]
    peer_endpoints: tuple[ComputationalPeerEndpoint, ...]
    target_host: ComputationalHostAdvertisement
    network_costs: tuple[RouteMetric, ...]
    host_costs: tuple[RouteMetric, ...]
    total_costs: tuple[RouteMetric, ...]

    def __post_init__(self) -> None:
        """Mathematics: Validate digests, cycle-free peer path, endpoint order, target ownership, and additive cost identity."""
        for name in ("address_digest", "directory_digest", "topology_digest"):
            _digest(getattr(self, name), name)
        _peer_id(self.origin_peer_id, "origin_peer_id")
        path = tuple(self.peer_path)
        if not path or path[0] != self.origin_peer_id:
            raise ComputationalFabricError("route peer_path must begin at its origin")
        for peer in path:
            _peer_id(peer)
        if len(set(path)) != len(path):
            raise ComputationalFabricError("route peer_path must be cycle-free")
        links = tuple(self.link_ids)
        for link_id in links:
            _digest(link_id, "link_id")
        if len(links) != len(path) - 1:
            raise ComputationalFabricError("route link count must equal peer_path hops")
        endpoints = tuple(self.peer_endpoints)
        if (
            len(endpoints) != len(path)
            or any(not isinstance(item, ComputationalPeerEndpoint) for item in endpoints)
            or tuple(item.peer_id for item in endpoints) != path
        ):
            raise ComputationalFabricError("route peer endpoints must exactly cover the ordered peer path")
        if not isinstance(self.target_host, ComputationalHostAdvertisement):
            raise ComputationalFabricError("route target_host must be a ComputationalHostAdvertisement")
        if self.target_host.peer_id != path[-1]:
            raise ComputationalFabricError("route target host does not belong to the final peer")
        object.__setattr__(self, "peer_path", path)
        object.__setattr__(self, "link_ids", links)
        object.__setattr__(self, "peer_endpoints", endpoints)
        metric_vectors: dict[str, tuple[RouteMetric, ...]] = {}
        for field_name in ("network_costs", "host_costs", "total_costs"):
            values = tuple(getattr(self, field_name))
            if not values or any(not isinstance(item, RouteMetric) for item in values):
                raise ComputationalFabricError(f"{field_name} must contain typed RouteMetric values")
            if len({item.name for item in values}) != len(values):
                raise ComputationalFabricError(f"{field_name} metric names must be unique")
            metric_vectors[field_name] = values
            object.__setattr__(self, field_name, values)
        basis = tuple(item.name for item in metric_vectors["total_costs"])
        for name, values in metric_vectors.items():
            if {item.name for item in values} != set(basis):
                raise ComputationalFabricError(f"{name} dimensions differ from total costs")
        network = {item.name: item for item in self.network_costs}
        host = {item.name: item for item in self.host_costs}
        total = {item.name: item for item in self.total_costs}
        if any(
            network[name].unit != total[name].unit
            or host[name].unit != total[name].unit
            or network[name].amount + host[name].amount != total[name].amount
            for name in basis
        ):
            raise ComputationalFabricError("route total costs do not equal network plus host costs")

    @property
    def authoritative(self) -> bool:
        """Mathematics: A planned fabric route is evidence for selection, never an execution authority."""
        return False

    @property
    def digest(self) -> str:
        """Mathematics: Identify the exact multi-hop route proposal by canonical SHA-256."""
        return _canonical_digest(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        """Mathematics: Serialize peer path, authenticated endpoints, target host claim and additive cost decomposition."""
        return {
            "schema": "mailcpu.computational-fabric-route-witness.v1",
            "authoritative": False,
            "address_digest": self.address_digest,
            "directory_digest": self.directory_digest,
            "topology_digest": self.topology_digest,
            "origin_peer_id": self.origin_peer_id,
            "peer_path": list(self.peer_path),
            "link_ids": list(self.link_ids),
            "peer_endpoints": [item.to_dict() for item in self.peer_endpoints],
            "target_host": self.target_host.to_dict(),
            "network_costs": [item.to_dict() for item in self.network_costs],
            "host_costs": [item.to_dict() for item in self.host_costs],
            "total_costs": [item.to_dict() for item in self.total_costs],
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ComputationalFabricRouteWitness":
        """Mathematics: Reconstruct a route proposal only from its exact schema and all digest-bound hop/cost fields."""
        expected = {
            "schema", "authoritative", "address_digest", "directory_digest",
            "topology_digest", "origin_peer_id", "peer_path", "link_ids",
            "peer_endpoints", "target_host", "network_costs", "host_costs",
            "total_costs",
        }
        if not isinstance(payload, Mapping) or set(payload) != expected:
            raise ComputationalFabricError("fabric route witness fields are malformed")
        if (
            payload["schema"] != "mailcpu.computational-fabric-route-witness.v1"
            or payload["authoritative"] is not False
        ):
            raise ComputationalFabricError("fabric route witness schema or authority marker is invalid")
        try:
            return cls(
                payload["address_digest"],
                payload["directory_digest"],
                payload["topology_digest"],
                payload["origin_peer_id"],
                tuple(payload["peer_path"]),
                tuple(payload["link_ids"]),
                tuple(ComputationalPeerEndpoint.from_dict(item) for item in payload["peer_endpoints"]),
                ComputationalHostAdvertisement.from_dict(payload["target_host"]),
                tuple(RouteMetric.from_dict(item) for item in payload["network_costs"]),
                tuple(RouteMetric.from_dict(item) for item in payload["host_costs"]),
                tuple(RouteMetric.from_dict(item) for item in payload["total_costs"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            if isinstance(exc, ComputationalFabricError):
                raise
            raise ComputationalFabricError("fabric route witness contains invalid nested values") from exc


@dataclass(frozen=True)
class ComputationalFabricResolutionResult:
    """Non-authoritative outcome of one federated multi-hop computational-address query."""

    status: ComputationalFabricStatus
    address_digest: str
    directory_digest: str
    topology_digest: str
    candidate_count: int
    expanded_states: int
    witness: ComputationalFabricRouteWitness | None = None
    blockers: tuple[ComputationalFabricBlocker, ...] = ()

    def __post_init__(self) -> None:
        """Mathematics: Enforce result status/witness consistency, typed digests, finite counts and canonical blockers."""
        if not isinstance(self.status, ComputationalFabricStatus):
            object.__setattr__(self, "status", ComputationalFabricStatus(self.status))
        for name in ("address_digest", "directory_digest", "topology_digest"):
            _digest(getattr(self, name), name)
        _positive(self.candidate_count, "candidate_count", minimum=0)
        _positive(self.expanded_states, "expanded_states", minimum=0)
        if self.status is ComputationalFabricStatus.FOUND and (
            self.candidate_count < 1 or self.expanded_states < 1
        ):
            raise ComputationalFabricError("FOUND fabric result requires candidates and expanded search states")
        if self.witness is not None:
            if not isinstance(self.witness, ComputationalFabricRouteWitness):
                raise ComputationalFabricError("witness must be ComputationalFabricRouteWitness or None")
            if self.witness.address_digest != self.address_digest:
                raise ComputationalFabricError("fabric witness belongs to a different computational address")
            if (
                self.witness.directory_digest != self.directory_digest
                or self.witness.topology_digest != self.topology_digest
            ):
                raise ComputationalFabricError("fabric witness belongs to a different directory/topology view")
        blockers = tuple(self.blockers)
        if any(not isinstance(item, ComputationalFabricBlocker) for item in blockers):
            raise ComputationalFabricError("blockers must contain ComputationalFabricBlocker values")
        object.__setattr__(
            self,
            "blockers",
            tuple(sorted(set(blockers), key=lambda item: (item.subject_id, item.code.value, item.detail))),
        )
        if (self.status is ComputationalFabricStatus.FOUND) != (self.witness is not None):
            raise ComputationalFabricError("FOUND fabric result must carry exactly one witness")

    @property
    def authoritative(self) -> bool:
        """Mathematics: Federated discovery and route planning never grant execution rights."""
        return False

    @property
    def digest(self) -> str:
        """Mathematics: Identify the complete federated route result by canonical SHA-256."""
        return _canonical_digest(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        """Mathematics: Serialize result status, selected witness and deterministic route blockers."""
        return {
            "schema": "mailcpu.computational-fabric-result.v1",
            "authoritative": False,
            "status": self.status.value,
            "address_digest": self.address_digest,
            "directory_digest": self.directory_digest,
            "topology_digest": self.topology_digest,
            "candidate_count": self.candidate_count,
            "expanded_states": self.expanded_states,
            "witness": None if self.witness is None else self.witness.to_dict(),
            "blockers": [item.to_dict() for item in self.blockers],
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ComputationalFabricResolutionResult":
        """Mathematics: Reconstruct a complete resolution result without elevating its non-authoritative witness."""
        expected = {
            "schema", "authoritative", "status", "address_digest",
            "directory_digest", "topology_digest", "candidate_count",
            "expanded_states", "witness", "blockers",
        }
        if not isinstance(payload, Mapping) or set(payload) != expected:
            raise ComputationalFabricError("fabric resolution result fields are malformed")
        if (
            payload["schema"] != "mailcpu.computational-fabric-result.v1"
            or payload["authoritative"] is not False
        ):
            raise ComputationalFabricError("fabric result schema or authority marker is invalid")
        try:
            witness_payload = payload["witness"]
            return cls(
                ComputationalFabricStatus(payload["status"]),
                payload["address_digest"],
                payload["directory_digest"],
                payload["topology_digest"],
                payload["candidate_count"],
                payload["expanded_states"],
                None if witness_payload is None else ComputationalFabricRouteWitness.from_dict(witness_payload),
                tuple(ComputationalFabricBlocker.from_dict(item) for item in payload["blockers"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            if isinstance(exc, ComputationalFabricError):
                raise
            raise ComputationalFabricError("fabric result contains invalid nested values") from exc


@dataclass(frozen=True)
class _PeerPathLabel:
    costs: tuple[int, ...]
    path: tuple[str, ...]
    link_ids: tuple[str, ...]


class ComputationalFabricResolver:
    """Federate remote host advertisements and select the least-cost bounded peer path."""

    def resolve(
        self,
        address: ComputationalAddress,
        directory: ComputationalFabricDirectory,
        *,
        origin_peer_id: str,
        max_hops: int = 8,
        max_expansions: int = 4096,
    ) -> ComputationalFabricResolutionResult:
        """Mathematics: Apply semantic host filters, bounded lexicographic Dijkstra over authenticated directed peers, then add endpoint host cost."""
        if not isinstance(address, ComputationalAddress):
            raise ComputationalFabricError("resolve requires a ComputationalAddress")
        if not isinstance(directory, ComputationalFabricDirectory):
            raise ComputationalFabricError("resolve requires a ComputationalFabricDirectory")
        origin = _peer_id(origin_peer_id, "origin_peer_id")
        if origin != directory.local_peer_id:
            raise ComputationalFabricError("origin_peer_id must equal this directory's local peer identity")
        max_hops = min(
            _positive(max_hops, "max_hops", minimum=0, maximum=128),
            address.workload.max_hops,
        )
        max_expansions = _positive(max_expansions, "max_expansions", maximum=100_000)
        address_digest = address.digest
        # Capture one lease-filtered view and derive both identities from that
        # same snapshot set; lease expiry between property reads must not
        # produce a witness whose directory and topology digests describe
        # different federated states.
        active = directory.active_snapshots
        directory_digest = _canonical_digest({
            "schema": "mailcpu.computational-fabric-directory.v1",
            "local_peer_id": directory.local_peer_id,
            "trusted_peers": directory.trusted_peers,
            "active_peer_ids": [item.peer_id for item in active],
            "snapshots": [item.to_dict() for item in active],
        })
        topology_digest = _canonical_digest({
            "peers": [item.endpoint.to_dict() for item in active],
            "links": [link.to_dict() for item in active for link in item.links],
        })
        peers = {snapshot.peer_id: snapshot for snapshot in active}
        if origin not in peers:
            return ComputationalFabricResolutionResult(
                ComputationalFabricStatus.BLOCKED,
                address_digest,
                directory_digest,
                topology_digest,
                0,
                0,
                blockers=(ComputationalFabricBlocker(
                    origin,
                    ComputationalFabricBlockerCode.PEER_UNAVAILABLE,
                    "origin peer has no active local snapshot",
                ),),
            )

        workload = address.workload
        reference = workload.operator_ref(address.operator_id)
        input_value = workload.input_value
        input_bytes = len(_canonical_bytes(input_value)) + sum(
            len(_canonical_bytes(item.to_dict()))
            for item in reference.structural_memory
        )
        metric_order = address.metric_order
        metric_names = tuple(item.name for item in metric_order)
        metric_units = {item.name: item.unit for item in metric_order}
        ceilings = {item.name: item.amount for item in address.resource_ceilings}
        request_frame_bytes = len(_canonical_bytes(address.to_dict()))
        blockers: set[ComputationalFabricBlocker] = set()
        hit_resource_limit = False
        adjacency: dict[str, list[ComputationalNetworkLink]] = {}
        for snapshot in active:
            for link in snapshot.links:
                if not link.enabled:
                    blockers.add(ComputationalFabricBlocker(
                        link.link_id,
                        ComputationalFabricBlockerCode.LINK_UNAVAILABLE,
                        "peer advertises this directed link as disabled",
                    ))
                    continue
                if link.target_peer_id not in peers:
                    blockers.add(ComputationalFabricBlocker(
                        link.link_id,
                        ComputationalFabricBlockerCode.PEER_UNAVAILABLE,
                        "link target is not in the active authenticated peer directory",
                    ))
                    continue
                if request_frame_bytes > link.max_frame_bytes:
                    hit_resource_limit = True
                    blockers.add(ComputationalFabricBlocker(
                        link.link_id,
                        ComputationalFabricBlockerCode.RESOURCE_LIMIT,
                        "serialized computational address exceeds the link frame bound",
                    ))
                    continue
                try:
                    _metric_vector(link.costs, metric_order, "network link costs")
                except ComputationalFabricError:
                    blockers.add(ComputationalFabricBlocker(
                        link.link_id,
                        ComputationalFabricBlockerCode.METRIC_MISMATCH,
                        "link cost dimensions or units differ from the address objective",
                    ))
                    continue
                adjacency.setdefault(link.source_peer_id, []).append(link)
        for outgoing in adjacency.values():
            outgoing.sort(key=lambda item: (item.target_peer_id, item.link_id))

        zero = tuple(0 for _ in metric_order)
        initial = _PeerPathLabel(zero, (origin,), ())
        # Hop count is part of the search state. Keeping only one
        # lexicographically cheapest prefix per peer can discard a more
        # expensive but shorter prefix that is the only one able to reach a
        # target within max_hops.
        best: dict[tuple[str, int], _PeerPathLabel] = {(origin, 0): initial}
        heap: list[tuple[tuple[int, ...], int, tuple[str, ...], tuple[str, ...], str]] = [
            (zero, 0, (origin,), (), origin)
        ]
        expanded = 0
        hit_hop_limit = False
        while heap:
            costs, hops, path, link_ids, current = heapq.heappop(heap)
            label = best.get((current, hops))
            if label is None or (
                label.costs != costs or label.path != path or label.link_ids != link_ids
            ):
                continue
            if expanded >= max_expansions:
                return ComputationalFabricResolutionResult(
                    ComputationalFabricStatus.BUDGET_EXHAUSTED,
                    address_digest,
                    directory_digest,
                    topology_digest,
                    0,
                    expanded,
                    blockers=tuple(blockers),
                )
            expanded += 1
            for link in adjacency.get(current, ()):
                if link.target_peer_id in path:
                    continue
                if hops >= max_hops:
                    hit_hop_limit = True
                    blockers.add(ComputationalFabricBlocker(
                        link.link_id,
                        ComputationalFabricBlockerCode.HOP_LIMIT,
                        "network route exceeds max_hops",
                    ))
                    continue
                edge = _metric_vector(link.costs, metric_order, "network link costs")
                candidate_costs = tuple(a + b for a, b in zip(costs, edge))
                exceeded_network = [
                    key.name
                    for index, key in enumerate(metric_order)
                    if key.name in ceilings and candidate_costs[index] > ceilings[key.name]
                ]
                if exceeded_network:
                    hit_resource_limit = True
                    blockers.add(ComputationalFabricBlocker(
                        link.link_id,
                        ComputationalFabricBlockerCode.RESOURCE_LIMIT,
                        "network path cost exceeds " + ", ".join(sorted(exceeded_network)),
                    ))
                    continue
                candidate_path = path + (link.target_peer_id,)
                candidate_links = link_ids + (link.link_id,)
                next_hops = hops + 1
                state_key = (link.target_peer_id, next_hops)
                previous = best.get(state_key)
                candidate_key = (candidate_costs, len(candidate_links), candidate_path, candidate_links)
                if previous is not None:
                    previous_key = (
                        previous.costs,
                        len(previous.link_ids),
                        previous.path,
                        previous.link_ids,
                    )
                    if previous_key <= candidate_key:
                        continue
                best[state_key] = _PeerPathLabel(
                    candidate_costs,
                    candidate_path,
                    candidate_links,
                )
                heapq.heappush(
                    heap,
                    (
                        candidate_costs,
                        next_hops,
                        candidate_path,
                        candidate_links,
                        link.target_peer_id,
                    ),
                )

        # A target may have several feasible hop-count states. Select
        # its best path only after preserving those states during search.
        best_by_peer: dict[str, _PeerPathLabel] = {}
        for (peer_id, _hops), candidate in best.items():
            previous = best_by_peer.get(peer_id)
            candidate_key = (
                candidate.costs,
                len(candidate.link_ids),
                candidate.path,
                candidate.link_ids,
            )
            if previous is None or candidate_key < (
                previous.costs,
                len(previous.link_ids),
                previous.path,
                previous.link_ids,
            ):
                best_by_peer[peer_id] = candidate

        hosts = tuple(
            item
            for snapshot in active
            for item in snapshot.hosts
            if item.operator_spec.operator_id == address.operator_id
            and item.operator_spec.version == reference.version
        )
        selected: list[tuple[tuple[Any, ...], ComputationalFabricRouteWitness]] = []
        budget_exhausted = hit_hop_limit or hit_resource_limit
        for host in hosts:
            spec = host.operator_spec
            reason: tuple[ComputationalFabricBlockerCode, str] | None = None
            route = best_by_peer.get(host.peer_id)
            if route is None:
                reason = (
                    ComputationalFabricBlockerCode.PEER_UNAVAILABLE,
                    "no active directed network route reaches the host peer",
                )
            elif spec.digest != address.operator_contract_digest or not spec.replay_safe:
                reason = (
                    ComputationalFabricBlockerCode.CONTRACT_MISMATCH,
                    "host operator contract does not exactly match the deterministic pure address contract",
                )
            elif address.computational_ground_fingerprint not in host.computational_ground_fingerprints:
                reason = (
                    ComputationalFabricBlockerCode.GROUND_MISMATCH,
                    "host does not advertise the requested Computational Ground",
                )
            elif address.program_fingerprint is not None and address.program_fingerprint not in host.program_fingerprints:
                reason = (
                    ComputationalFabricBlockerCode.PROGRAM_MISMATCH,
                    "host does not advertise the exact pinned program fingerprint",
                )
            elif address.program_fingerprint is None and not host.supports_ground_program_compilation:
                reason = (
                    ComputationalFabricBlockerCode.PROGRAM_MISMATCH,
                    "unpinned program requires explicit Ground-bounded compilation support",
                )
            elif reference.target_node is not None and reference.target_node != host.node_id:
                reason = (
                    ComputationalFabricBlockerCode.PLACEMENT_MISMATCH,
                    "operator target_node differs from the advertised placement node",
                )
            elif workload.eligible_nodes and host.node_id not in workload.eligible_nodes:
                reason = (
                    ComputationalFabricBlockerCode.PLACEMENT_MISMATCH,
                    "advertised placement node is outside the workload eligible_nodes",
                )
            elif (
                (reference.preferred_substrate is not None and reference.preferred_substrate not in host.substrates)
                or not (set(host.substrates) & set(spec.substrates))
            ):
                reason = (
                    ComputationalFabricBlockerCode.SUBSTRATE_MISMATCH,
                    "advertised host has no eligible operator substrate",
                )
            elif address.observation_kind != spec.output_kind:
                reason = (
                    ComputationalFabricBlockerCode.OBSERVATION_MISMATCH,
                    "observation kind differs from the operator output kind",
                )
            elif not _json_kind_matches(input_value, spec.input_kind):
                reason = (
                    ComputationalFabricBlockerCode.INPUT_MISMATCH,
                    "workload input kind differs from the operator input contract",
                )
            elif input_bytes > min(spec.max_input_bytes, workload.budget.max_bytes, host.max_bytes):
                reason = (
                    ComputationalFabricBlockerCode.RESOURCE_LIMIT,
                    "input/state description exceeds an operator, workload, or host byte bound",
                )
                budget_exhausted = True
            elif reference.structural_memory and not host.supports_structural_memory:
                reason = (
                    ComputationalFabricBlockerCode.STATE_UNAVAILABLE,
                    "host does not advertise Structural Memory binding support",
                )
            elif host.implementation_fingerprint is None:
                reason = (
                    ComputationalFabricBlockerCode.IMPLEMENTATION_MISSING,
                    "remote execution requires an explicit implementation fingerprint pin",
                )

            try:
                host_vector = _metric_vector(host.costs, metric_order, "host route costs")
            except ComputationalFabricError:
                host_vector = ()
                if reason is None:
                    reason = (
                        ComputationalFabricBlockerCode.METRIC_MISMATCH,
                        "host cost dimensions or units differ from the address objective",
                    )
            if route is not None and reason is None:
                energy = spec.estimated_energy(input_bytes)
                virtual_ticks = max(1, math.ceil(energy / host.virtual_capacity))
                if (
                    energy > min(workload.budget.max_energy, host.max_energy)
                    or virtual_ticks > min(workload.budget.max_virtual_ticks, host.max_virtual_ticks)
                ):
                    reason = (
                        ComputationalFabricBlockerCode.RESOURCE_LIMIT,
                        "host energy or virtual-tick estimate exceeds the workload/host budget",
                    )
                    budget_exhausted = True

            if route is not None and reason is None:
                total = tuple(a + b for a, b in zip(route.costs, host_vector))
                exceeded = [
                    key.name for index, key in enumerate(metric_order)
                    if key.name in ceilings and total[index] > ceilings[key.name]
                ]
                if exceeded:
                    reason = (
                        ComputationalFabricBlockerCode.RESOURCE_LIMIT,
                        "combined network and host cost exceeds " + ", ".join(sorted(exceeded)),
                    )
                    budget_exhausted = True

            if reason is not None:
                blockers.add(ComputationalFabricBlocker(host.host_id, reason[0], reason[1]))
                continue
            endpoint = peers[host.peer_id].endpoint
            peer_endpoints = tuple(peers[peer_id].endpoint for peer_id in route.path)
            network_metrics = _metrics_from_vector(route.costs, metric_order)
            host_metrics = _metrics_from_vector(host_vector, metric_order)
            total_metrics = _metrics_from_vector(total, metric_order)
            witness = ComputationalFabricRouteWitness(
                address_digest=address_digest,
                directory_digest=directory_digest,
                topology_digest=topology_digest,
                origin_peer_id=origin,
                peer_path=route.path,
                link_ids=route.link_ids,
                peer_endpoints=peer_endpoints,
                target_host=host,
                network_costs=network_metrics,
                host_costs=host_metrics,
                total_costs=total_metrics,
            )
            objective = (
                total,
                len(route.link_ids),
                route.path,
                route.link_ids,
                host.host_id,
                host.node_id,
            )
            selected.append((objective, witness))

        if selected:
            selected.sort(key=lambda item: item[0])
            return ComputationalFabricResolutionResult(
                ComputationalFabricStatus.FOUND,
                address_digest,
                directory_digest,
                topology_digest,
                len(hosts),
                expanded,
                selected[0][1],
                tuple(blockers),
            )
        if not hosts:
            status = ComputationalFabricStatus.UNREACHABLE
            blockers.add(ComputationalFabricBlocker(
                address.operator_id,
                ComputationalFabricBlockerCode.NO_HOST,
                "no active peer advertises the requested operator version",
            ))
        elif budget_exhausted:
            status = ComputationalFabricStatus.BUDGET_EXHAUSTED
        elif not any(host.peer_id in best_by_peer for host in hosts):
            status = ComputationalFabricStatus.UNREACHABLE
        else:
            status = ComputationalFabricStatus.BLOCKED
        return ComputationalFabricResolutionResult(
            status,
            address_digest,
            directory_digest,
            topology_digest,
            len(hosts),
            expanded,
            blockers=tuple(blockers),
        )
