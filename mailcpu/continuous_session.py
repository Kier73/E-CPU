"""Rejoin a quorum-backed E-CPU session through qualified observer-host paths.

A rejoin address is durable *naming*, not a cached state, process, socket,
credential, or authority. Substrate observations are possible paths only.
All admitted state is loaded through the existing M3 recovery lineage and M1
object store; all host and channel permissions remain receiver-local.
"""

from __future__ import annotations

from dataclasses import dataclass
import heapq
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Callable, Mapping

from .computational_session import (
    BackendCompatibility,
    ComputationalSessionSnapshot,
    ComputationalSessionStore,
)
from .substrate_bootstrap import (
    ChannelObservation,
    ResourceObservation,
    SubstrateObservation,
    canonical,
    digest,
    natural,
)

ADDRESS_SCHEMA = "mailcpu.continuous-session-address.v1"
ROUTE_SCHEMA = "mailcpu.continuous-session-route.v1"
REJOIN_OPERATION = "session.rejoin"
REJOIN_INPUT = "session.address.v1"
REJOIN_OUTPUT = "session.snapshot.v1"
_SESSION_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_STATE_SCHEMA = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,255}\Z")
_HEX = re.compile(r"[0-9a-f]{64}\Z")


class SessionRejoinRefused(ValueError):
    """A proposed attachment has insufficient path, scope, or state evidence."""


@dataclass(frozen=True)
class SessionRejoinAddress:
    """Revision-independent name for a fixed-membership M3 session lineage.

    The digest detects accidental edits. It does not authenticate this address
    or confer permission to attach to its named session.
    """

    session_id: str
    artifact_manifest_digest: str
    state_schema_id: str
    membership_digest: str

    def __post_init__(self) -> None:
        if type(self.session_id) is not str or _SESSION_ID.fullmatch(self.session_id) is None:
            raise SessionRejoinRefused("invalid stable session identifier")
        if type(self.state_schema_id) is not str or _STATE_SCHEMA.fullmatch(self.state_schema_id) is None:
            raise SessionRejoinRefused("invalid state schema identifier")
        for field in ("artifact_manifest_digest", "membership_digest"):
            value = getattr(self, field)
            if type(value) is not str or _HEX.fullmatch(value) is None:
                raise SessionRejoinRefused(f"invalid {field}")

    def to_dict(self) -> dict[str, object]:
        """Mathematics: Encode immutable scope without a stale checkpoint or mutable endpoint."""
        fields = {
            "schema": ADDRESS_SCHEMA,
            "session_id": self.session_id,
            "artifact_manifest_digest": self.artifact_manifest_digest,
            "state_schema_id": self.state_schema_id,
            "membership_digest": self.membership_digest,
        }
        return fields | {"digest": digest(fields)}

    @property
    def fingerprint(self) -> str:
        """Mathematics: Return the content identity of the immutable rejoin scope."""
        return str(self.to_dict()["digest"])

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "SessionRejoinAddress":
        """Mathematics: Reject altered, incomplete or noncanonical address descriptions."""
        expected = {
            "schema", "session_id", "artifact_manifest_digest",
            "state_schema_id", "membership_digest", "digest",
        }
        if not isinstance(payload, Mapping) or set(payload) != expected:
            raise SessionRejoinRefused("invalid rejoin address fields")
        if payload["schema"] != ADDRESS_SCHEMA:
            raise SessionRejoinRefused("unsupported rejoin address schema")
        address = cls(
            session_id=payload["session_id"],
            artifact_manifest_digest=payload["artifact_manifest_digest"],
            state_schema_id=payload["state_schema_id"],
            membership_digest=payload["membership_digest"],
        )
        if type(payload["digest"]) is not str or payload["digest"] != address.fingerprint:
            raise SessionRejoinRefused("rejoin address digest mismatch")
        return address

    @classmethod
    def bootstrap(cls, store: ComputationalSessionStore) -> "SessionRejoinAddress":
        """Mathematics: Issue a durable address only after M3 admits a quorum-anchored revision."""
        if not isinstance(store, ComputationalSessionStore):
            raise TypeError("bootstrap requires a ComputationalSessionStore")
        store.load_latest()
        return cls(
            session_id=store.session_id,
            artifact_manifest_digest=store.artifact_manifest_digest,
            state_schema_id=store.state_schema_id,
            membership_digest=store.membership.digest,
        )

    def save(self, path: str | os.PathLike[str]) -> None:
        """Mathematics: Persist only the rejoin address atomically, never credentials or state bytes."""
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = canonical(self.to_dict()) + b"\n"
        fd, tmp_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=str(target.parent))
        try:
            if hasattr(os, "fchmod"):
                os.fchmod(fd, 0o600)
            with os.fdopen(fd, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(tmp_name, target)
            try:
                directory_fd = os.open(
                    str(target.parent), os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
                )
            except OSError:
                directory_fd = None
            if directory_fd is not None:
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
        finally:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)

    @classmethod
    def load(cls, path: str | os.PathLike[str]) -> "SessionRejoinAddress":
        """Mathematics: Reload an exact saved address after the original bootstrap process ends."""
        try:
            source = Path(path)
            if source.stat().st_size > 4096:
                raise SessionRejoinRefused("rejoin address exceeds the accepted bound")
            value = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError) as exc:
            if isinstance(exc, SessionRejoinRefused):
                raise
            raise SessionRejoinRefused("rejoin address could not be read") from exc
        return cls.from_dict(value)


@dataclass(frozen=True)
class SessionRejoinRoute:
    """A non-authoritative candidate route through observed communication edges."""

    address_digest: str
    inventory_digest: str
    origin_id: str
    target_id: str
    coordinate: int
    channel_ids: tuple[str, ...]
    total_quanta: int

    def __post_init__(self) -> None:
        for field in ("address_digest", "inventory_digest"):
            value = getattr(self, field)
            if type(value) is not str or _HEX.fullmatch(value) is None:
                raise SessionRejoinRefused(f"invalid {field}")
        for field in ("origin_id", "target_id"):
            if not isinstance(getattr(self, field), str) or not getattr(self, field):
                raise SessionRejoinRefused(f"invalid {field}")
        natural(self.coordinate, "navigation coordinate")
        natural(self.total_quanta, "navigation cost", 1)
        if type(self.channel_ids) is not tuple or any(
            type(item) is not str or not item for item in self.channel_ids
        ):
            raise SessionRejoinRefused("invalid path channel identities")

    def to_dict(self) -> dict[str, object]:
        """Mathematics: Expose a deterministic plan, not a certificate of physical delivery."""
        return {
            "schema": ROUTE_SCHEMA,
            "address_digest": self.address_digest,
            "inventory_digest": self.inventory_digest,
            "origin_id": self.origin_id,
            "target_id": self.target_id,
            "coordinate": self.coordinate,
            "channel_ids": list(self.channel_ids),
            "total_quanta": self.total_quanta,
        }

    @property
    def fingerprint(self) -> str:
        """Mathematics: Content-bind the exact selected route and observation coordinate."""
        return digest(self.to_dict())


@dataclass(frozen=True)
class SessionAttachment:
    """A freshly verified M3 snapshot associated with a receiver-admitted path."""

    address: SessionRejoinAddress
    route: SessionRejoinRoute
    snapshot: ComputationalSessionSnapshot

    def __post_init__(self) -> None:
        if self.route.address_digest != self.address.fingerprint:
            raise SessionRejoinRefused("attachment route names a different address")
        if self.snapshot.checkpoint.session_id != self.address.session_id:
            raise SessionRejoinRefused("attachment snapshot names another session")

    def evidence(self) -> dict[str, object]:
        """Mathematics: Expose checked lineage coordinates without copying complete state bytes."""
        return {
            "schema": "mailcpu.continuous-session-attachment.v1",
            "address_digest": self.address.fingerprint,
            "route_digest": self.route.fingerprint,
            "host_id": self.route.target_id,
            "revision": self.snapshot.revision,
            "checkpoint_digest": self.snapshot.checkpoint_digest,
            "lineage_digest": self.snapshot.lineage_manifest.digest,
            "state_digest": self.snapshot.checkpoint.state_digest,
        }


HostAdmission = Callable[[ResourceObservation], bool]
ChannelAdmission = Callable[[ChannelObservation], bool]


class SessionRejoinNavigator:
    """Route a stable session address to a trusted local M3 store binding.

    An inventory is observational; only explicitly configured local store
    bindings plus trusted host/channel callbacks can result in attachment.
    A different process can construct a new navigator from the same address,
    refreshed observations, and reconnected durable M3 state.
    """

    def __init__(
        self,
        inventory: SubstrateObservation,
        stores: Mapping[str, ComputationalSessionStore],
        *,
        admit_host: HostAdmission,
        admit_channel: ChannelAdmission,
        max_hops: int = 16,
    ) -> None:
        if not isinstance(inventory, SubstrateObservation):
            raise TypeError("navigator requires a SubstrateObservation")
        if not isinstance(stores, Mapping) or any(
            not isinstance(key, str) or not isinstance(value, ComputationalSessionStore)
            for key, value in stores.items()
        ):
            raise TypeError("stores must bind resource IDs to local M3 stores")
        if not callable(admit_host) or not callable(admit_channel):
            raise TypeError("explicit host and channel admission callbacks are required")
        natural(max_hops, "maximum route hops", 1)
        if max_hops > 128:
            raise SessionRejoinRefused("maximum route hops exceeds the accepted bound")
        self.inventory = inventory
        self.stores = dict(stores)
        self.admit_host = admit_host
        self.admit_channel = admit_channel
        self.max_hops = max_hops

    @staticmethod
    def _live(observed_at: int, expires_at: int, coordinate: int) -> bool:
        """Mathematics: Evaluate only declared logical-time lease coordinates."""
        return observed_at <= coordinate <= expires_at

    @staticmethod
    def _scope_matches(address: SessionRejoinAddress, store: ComputationalSessionStore) -> bool:
        """Mathematics: Bind a candidate local host to the immutable M3 session lineage."""
        return (
            store.session_id == address.session_id
            and store.artifact_manifest_digest == address.artifact_manifest_digest
            and store.state_schema_id == address.state_schema_id
            and store.membership.digest == address.membership_digest
        )

    def plan(
        self,
        address: SessionRejoinAddress,
        *,
        origin_id: str,
        coordinate: int,
    ) -> SessionRejoinRoute:
        """Mathematics: Choose the cheapest qualifying admitted path without pretending delivery occurred."""
        if not isinstance(address, SessionRejoinAddress):
            raise TypeError("plan requires a SessionRejoinAddress")
        natural(coordinate, "navigation coordinate")
        resources = {resource.resource_id: resource for resource in self.inventory.resources}
        if origin_id not in resources:
            raise SessionRejoinRefused("origin is not present in the observed inventory")
        if not self._live(resources[origin_id].observed_at, resources[origin_id].expires_at, coordinate):
            raise SessionRejoinRefused("origin observation has expired")

        targets: dict[str, int] = {}
        for resource in self.inventory.resources:
            if resource.resource_id not in self.stores:
                continue
            if not self._live(resource.observed_at, resource.expires_at, coordinate):
                continue
            if not self._scope_matches(address, self.stores[resource.resource_id]):
                continue
            offers = (
                offer for offer in resource.offers
                if offer.operation == REJOIN_OPERATION
                and offer.accepts == REJOIN_INPUT
                and offer.produces == REJOIN_OUTPUT
            )
            costs = [offer.estimated_quanta for offer in offers]
            if costs and self.admit_host(resource) is True:
                targets[resource.resource_id] = min(costs)
        if not targets:
            raise SessionRejoinRefused("no receiver-authorized observer-host offers this session")

        payload_size = len(canonical(address.to_dict()))
        graph: dict[str, list[ChannelObservation]] = {key: [] for key in resources}
        for channel in self.inventory.channels:
            if (
                REJOIN_INPUT in channel.carries
                and channel.max_payload_bytes >= payload_size
                and self._live(channel.observed_at, channel.expires_at, coordinate)
                and self._live(resources[channel.source].observed_at, resources[channel.source].expires_at, coordinate)
                and self._live(resources[channel.target].observed_at, resources[channel.target].expires_at, coordinate)
                and self.admit_channel(channel) is True
            ):
                graph[channel.source].append(channel)

        # Equal-cost routes are ordered by hop count, then exact channel IDs.
        # A best-known state per node/hop keeps max-hop search finite even with cycles.
        queue: list[tuple[int, int, tuple[str, ...], str]] = [(0, 0, (), origin_id)]
        seen: dict[tuple[str, int], tuple[int, tuple[str, ...]]] = {}
        candidates: list[tuple[int, int, tuple[str, ...], str]] = []
        while queue:
            cost, hops, path, node = heapq.heappop(queue)
            state = (node, hops)
            previous = seen.get(state)
            if previous is not None and previous <= (cost, path):
                continue
            seen[state] = (cost, path)
            if node in targets:
                candidates.append((cost + targets[node], hops, path, node))
            if hops >= self.max_hops:
                continue
            for channel in graph[node]:
                heapq.heappush(
                    queue,
                    (cost + channel.estimated_quanta, hops + 1,
                     path + (channel.channel_id,), channel.target),
                )
        if not candidates:
            raise SessionRejoinRefused("no admitted communication path reaches an eligible observer-host")
        total, _, channels, host = min(candidates)
        return SessionRejoinRoute(
            address_digest=address.fingerprint,
            inventory_digest=self.inventory.fingerprint,
            origin_id=origin_id,
            target_id=host,
            coordinate=coordinate,
            channel_ids=channels,
            total_quanta=total,
        )

    def attach(
        self,
        address: SessionRejoinAddress,
        route: SessionRejoinRoute,
        *,
        coordinate: int,
        backend_compatibility: BackendCompatibility | None = None,
    ) -> SessionAttachment:
        """Mathematics: Revalidate routing and load the current M3 quorum high-water on the target."""
        if not isinstance(route, SessionRejoinRoute):
            raise TypeError("attach requires a SessionRejoinRoute")
        current_route = self.plan(address, origin_id=route.origin_id, coordinate=coordinate)
        if route != current_route:
            raise SessionRejoinRefused("route changed or its observation lease is no longer valid")
        store = self.stores[route.target_id]
        snapshot = store.load_latest(backend_compatibility=backend_compatibility)
        if (
            snapshot.checkpoint.session_id != address.session_id
            or snapshot.checkpoint.artifact_manifest_digest != address.artifact_manifest_digest
            or snapshot.checkpoint.state_schema_id != address.state_schema_id
        ):
            raise SessionRejoinRefused("verified checkpoint scope differs from rejoin address")
        return SessionAttachment(address, route, snapshot)
