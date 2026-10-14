"""Deterministic E1-owned network namespaces and point-to-point links.

The module deliberately stops at MailCPU's ownership boundary.  It models the
information logistics of a link (namespaces, interfaces, queues, framing, and
checkpoint state) without opening a host socket or claiming public-network
semantics.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
import re
from typing import Any, Protocol

from .journal import EventJournal


class OwnedNetworkError(ValueError):
    """A virtual namespace, link, frame, or checkpoint violates its contract."""


class FrameConsumer(Protocol):
    """The minimal semantic-driver contract for an owned raw-frame endpoint."""

    def ingest(self, logical_time: int, packet: bytes) -> Any:
        """Mathematics: consume packet `p` under transition `D(state,p) -> (state',events)` or raise before mutation."""

        ...


_NAME = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,63}$")
_MIN_MTU = 68
_MAX_MTU = 65_535


def _check_name(value: str, label: str) -> str:
    """Mathematics: accept identifier `x` exactly when `x ∈ [a-z0-9][a-z0-9_.-]^{0..63}`."""

    if not isinstance(value, str) or _NAME.fullmatch(value) is None:
        raise OwnedNetworkError(f"invalid {label}: {value!r}")
    return value


@dataclass(frozen=True, order=True)
class NetworkAddress:
    """The stable `(namespace, interface)` address of one owned endpoint."""

    namespace: str
    interface: str

    def __post_init__(self) -> None:
        """Mathematics: enforce `addr = (n,i)` with both coordinates in the bounded identifier language."""

        _check_name(self.namespace, "namespace")
        _check_name(self.interface, "interface")

    def path(self) -> str:
        """Mathematics: embed address `a=(n,i)` in capability space as `/net/n/i`."""

        return f"/net/{self.namespace}/{self.interface}"

    def to_dict(self) -> dict[str, str]:
        """Mathematics: serialize address `a` as its coordinate pair without information loss."""

        return {"namespace": self.namespace, "interface": self.interface}

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "NetworkAddress":
        """Mathematics: reconstruct `a` from `S(a)` while reapplying identifier validation."""

        return cls(str(payload["namespace"]), str(payload["interface"]))


@dataclass(frozen=True)
class NetworkFrame:
    """A received byte frame with deterministic identity and logical timestamp."""

    frame_id: int
    source: NetworkAddress
    destination: NetworkAddress
    payload: bytes
    logical_time: int
    route: tuple[NetworkAddress, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """Mathematics: serialize frame `f=(id,s,d,b,t,r)` with `b := hex(payload)` and route `r` explicit."""

        return {
            "frame_id": self.frame_id,
            "source": self.source.to_dict(),
            "destination": self.destination.to_dict(),
            "payload_hex": self.payload.hex(),
            "logical_time": self.logical_time,
            "route": [address.to_dict() for address in self.route],
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "NetworkFrame":
        """Mathematics: invert `to_dict` and require `id > 0`, `t ≥ 0`, and finite byte payload `b`."""

        frame_id = int(payload["frame_id"])
        logical_time = int(payload["logical_time"])
        if frame_id <= 0 or logical_time < 0:
            raise OwnedNetworkError("invalid network frame identity or logical time")
        try:
            body = bytes.fromhex(str(payload.get("payload_hex", "")))
        except ValueError as exc:
            raise OwnedNetworkError("invalid network frame payload encoding") from exc
        source = NetworkAddress.from_dict(dict(payload["source"]))
        destination = NetworkAddress.from_dict(dict(payload["destination"]))
        raw_route = payload.get("route")
        route = (
            (source, destination)
            if raw_route is None
            else tuple(NetworkAddress.from_dict(dict(item)) for item in raw_route)
        )
        if len(route) < 2 or route[0] != source or route[-1] != destination:
            raise OwnedNetworkError("network frame route must begin at source and end at destination")
        return cls(
            frame_id,
            source,
            destination,
            body,
            logical_time,
            route,
        )


@dataclass
class _Endpoint:
    """Mutable interface state: link attachment, administrative state, and bounded FIFO."""

    address: NetworkAddress
    mtu: int
    queue_limit: int
    link_id: str | None = None
    up: bool = True
    queue: deque[NetworkFrame] = field(default_factory=deque)


@dataclass(frozen=True)
class _Link:
    """An owned point-to-point edge joining exactly two interface addresses."""

    link_id: str
    left: NetworkAddress
    right: NetworkAddress

    def other(self, endpoint: NetworkAddress) -> NetworkAddress:
        """Mathematics: apply the involution `other(left)=right`, `other(right)=left`, undefined otherwise."""

        if endpoint == self.left:
            return self.right
        if endpoint == self.right:
            return self.left
        raise OwnedNetworkError(f"endpoint is not attached to link: {endpoint}")


class OwnedNetworkFabric:
    """Checkpointable E1-owned network fabric with explicit namespaces and direct links."""

    def __init__(
        self,
        journal: EventJournal | None = None,
        queue_limit: int = 256,
    ) -> None:
        """Mathematics: initialize finite graph `G=(N,V,L)` and frame counter `k=0` with `0<queue_limit`.

        The graph is intentionally point-to-point: a send is valid only when
        source and destination are the two endpoints of one attached link.
        """

        if queue_limit <= 0:
            raise ValueError("queue_limit must be positive")
        self.journal = journal or EventJournal()
        self.queue_limit = queue_limit
        self._namespaces: set[str] = set()
        self._endpoints: dict[NetworkAddress, _Endpoint] = {}
        self._links: dict[str, _Link] = {}
        self._next_frame_id = 1

    def create_namespace(self, name: str) -> None:
        """Mathematics: extend `N` with `n` iff `n∉N`; duplicate creation is rejected before mutation."""

        _check_name(name, "namespace")
        if name in self._namespaces:
            raise OwnedNetworkError(f"namespace already exists: {name}")
        self._namespaces.add(name)
        self.journal.append("network.namespace.create", {"namespace": name})

    def create_interface(self, namespace: str, interface: str, mtu: int = 1500) -> NetworkAddress:
        """Mathematics: add vertex `v=(n,i)` iff `n∈N`, `v∉V`, and `68≤mtu≤65535`."""

        address = NetworkAddress(namespace, interface)
        self._require_namespace(namespace)
        self._validate_mtu(mtu)
        if address in self._endpoints:
            raise OwnedNetworkError(f"interface already exists: {address.path()}")
        self._endpoints[address] = _Endpoint(address, int(mtu), self.queue_limit)
        self.journal.append(
            "network.interface.create",
            {"address": address.to_dict(), "mtu": int(mtu), "queue_limit": self.queue_limit},
        )
        return address

    def connect(self, link_id: str, left: NetworkAddress, right: NetworkAddress) -> None:
        """Mathematics: add edge `l=(left,right)` iff endpoints exist, differ, and have no prior edge."""

        _check_name(link_id, "link")
        if link_id in self._links:
            raise OwnedNetworkError(f"link already exists: {link_id}")
        if left == right:
            raise OwnedNetworkError("a point-to-point link needs two distinct endpoints")
        left_endpoint = self._require_endpoint(left)
        right_endpoint = self._require_endpoint(right)
        if left_endpoint.link_id is not None or right_endpoint.link_id is not None:
            raise OwnedNetworkError("an interface may attach to only one point-to-point link")
        self._links[link_id] = _Link(link_id, left, right)
        left_endpoint.link_id = link_id
        right_endpoint.link_id = link_id
        self.journal.append(
            "network.link.connect",
            {"link_id": link_id, "left": left.to_dict(), "right": right.to_dict()},
        )

    def set_interface_state(self, address: NetworkAddress, up: bool) -> None:
        """Mathematics: update interface availability `u_v := bool(up)` without changing queued frames."""

        endpoint = self._require_endpoint(address)
        endpoint.up = bool(up)
        self.journal.append("network.interface.state", {"address": address.to_dict(), "up": endpoint.up})

    def send(
        self,
        source: NetworkAddress,
        destination: NetworkAddress,
        payload: bytes,
        logical_time: int,
    ) -> int:
        """Mathematics: enqueue `f=(k,s,d,b,t)` iff `s↔d∈L`, both `u=1`, and `|b|≤min(MTU_s,MTU_d)`.

        Validation precedes allocation and enqueue, so every rejected frame is
        a state-preserving failure rather than an invisible drop.
        """

        if not isinstance(payload, (bytes, bytearray, memoryview)):
            raise OwnedNetworkError("network payload must be bytes-like")
        if logical_time < 0:
            raise OwnedNetworkError("logical_time must be non-negative")
        source_endpoint = self._require_endpoint(source)
        destination_endpoint = self._require_endpoint(destination)
        if not source_endpoint.up or not destination_endpoint.up:
            raise OwnedNetworkError("source and destination interfaces must be up")
        if source_endpoint.link_id is None or source_endpoint.link_id != destination_endpoint.link_id:
            raise OwnedNetworkError("source and destination are not directly linked")
        return self._enqueue_frame(
            source,
            destination,
            bytes(payload),
            int(logical_time),
            (source, destination),
            min(source_endpoint.mtu, destination_endpoint.mtu),
        )

    def send_routed(
        self,
        source: NetworkAddress,
        destination: NetworkAddress,
        payload: bytes,
        logical_time: int,
    ) -> int:
        """Mathematics: find deterministic shortest path `r=argmin_{p∈Paths(s,d)}(|p|,p)` and enqueue iff `|b|≤MTU(r)`.

        Same-namespace interface transitions model an owned forwarding plane;
        link transitions model physical point-to-point edges.  The selected
        route is stored in the frame and journal, making forwarding evidence
        part of the replay artifact rather than an implicit graph traversal.
        """

        self._validate_payload(payload, logical_time)
        source_endpoint = self._require_endpoint(source)
        destination_endpoint = self._require_endpoint(destination)
        if not source_endpoint.up or not destination_endpoint.up:
            raise OwnedNetworkError("source and destination interfaces must be up")
        route = self.find_route(source, destination)
        path_mtu = min(self._require_endpoint(address).mtu for address in route)
        return self._enqueue_frame(
            source,
            destination,
            bytes(payload),
            int(logical_time),
            route,
            path_mtu,
        )

    def find_route(self, source: NetworkAddress, destination: NetworkAddress) -> tuple[NetworkAddress, ...]:
        """Mathematics: compute lexicographically deterministic BFS path `r` in the active topology or reject `r=∅`."""

        source_endpoint = self._require_endpoint(source)
        destination_endpoint = self._require_endpoint(destination)
        if not source_endpoint.up or not destination_endpoint.up:
            raise OwnedNetworkError("source and destination interfaces must be up")
        if source == destination:
            return (source, destination)
        queue: deque[tuple[NetworkAddress, ...]] = deque(((source,),))
        visited = {source}
        while queue:
            path = queue.popleft()
            current = path[-1]
            for neighbor in self._neighbors(current):
                if neighbor in visited:
                    continue
                candidate = path + (neighbor,)
                if neighbor == destination:
                    return candidate
                visited.add(neighbor)
                queue.append(candidate)
        raise OwnedNetworkError("no active route between endpoints")

    def route_mtu(self, source: NetworkAddress, destination: NetworkAddress) -> int:
        """Mathematics: compute path capacity `MTU(s,d)=min_{v∈route(s,d)} MTU(v)` without mutating topology or queues."""

        route = self.find_route(source, destination)
        return min(self._require_endpoint(address).mtu for address in route)

    def queue_available(self, destination: NetworkAddress) -> int:
        """Mathematics: expose residual FIFO capacity `C_d=limit_d-|Q_d|` for atomic multi-segment preflight."""

        endpoint = self._require_endpoint(destination)
        return endpoint.queue_limit - len(endpoint.queue)

    def peek(self, destination: NetworkAddress, max_size: int | None = None) -> NetworkFrame | None:
        """Mathematics: return `head(Q_d)` without mutation, rejecting only when `|head.payload|>max_size`."""

        if max_size is not None and max_size < 0:
            raise OwnedNetworkError("max_size must be non-negative")
        endpoint = self._require_endpoint(destination)
        if not endpoint.queue:
            return None
        frame = endpoint.queue[0]
        if max_size is not None and len(frame.payload) > max_size:
            raise OwnedNetworkError("destination buffer is smaller than queued frame")
        return frame

    def receive(self, destination: NetworkAddress, max_size: int | None = None) -> NetworkFrame | None:
        """Mathematics: apply FIFO transition `Q_d := tail(Q_d)` and return `head(Q_d)` atomically."""

        frame = self.peek(destination, max_size)
        if frame is None:
            return None
        endpoint = self._require_endpoint(destination)
        received = endpoint.queue.popleft()
        if received != frame:
            raise OwnedNetworkError("receive queue changed during atomic dequeue")
        self.journal.append("network.frame.receive", {"frame": frame.to_dict()})
        return frame

    def _enqueue_frame(
        self,
        source: NetworkAddress,
        destination: NetworkAddress,
        payload: bytes,
        logical_time: int,
        route: tuple[NetworkAddress, ...],
        path_mtu: int,
    ) -> int:
        """Mathematics: apply `Q_d := Q_d || (k,s,d,b,t,r)` only after `|b|≤path_mtu` and queue capacity hold."""

        self._validate_payload(payload, logical_time)
        if not route or route[0] != source or route[-1] != destination:
            raise OwnedNetworkError("frame route endpoints do not match source and destination")
        for address in route:
            self._require_endpoint(address)
        if len(payload) > path_mtu:
            raise OwnedNetworkError("payload exceeds route MTU")
        destination_endpoint = self._require_endpoint(destination)
        if len(destination_endpoint.queue) >= destination_endpoint.queue_limit:
            raise OwnedNetworkError("destination receive queue is full")
        frame_id = self._next_frame_id
        frame = NetworkFrame(frame_id, source, destination, bytes(payload), logical_time, route)
        destination_endpoint.queue.append(frame)
        self._next_frame_id += 1
        self.journal.append(
            "network.frame.send",
            {"frame": frame.to_dict(), "forwarded": len(route) > 2},
        )
        if len(route) > 2:
            self.journal.append(
                "network.route.forward",
                {
                    "frame_id": frame_id,
                    "route": [address.to_dict() for address in route],
                },
            )
        return frame_id

    def _neighbors(self, address: NetworkAddress) -> tuple[NetworkAddress, ...]:
        """Mathematics: derive adjacency `Adj(v)=link_peer(v) ∪ {w | namespace(w)=namespace(v)}` over active interfaces."""

        endpoint = self._require_endpoint(address)
        neighbors: set[NetworkAddress] = set()
        if endpoint.link_id is not None:
            link = self._links[endpoint.link_id]
            peer = link.other(address)
            if self._require_endpoint(peer).up:
                neighbors.add(peer)
        for candidate, candidate_endpoint in self._endpoints.items():
            if candidate != address and candidate.namespace == address.namespace and candidate_endpoint.up:
                neighbors.add(candidate)
        return tuple(sorted(neighbors))

    @staticmethod
    def _validate_payload(payload: bytes, logical_time: int) -> None:
        """Mathematics: require `payload∈Bytes*` and logical clock `t∈ℕ₀` before any graph or queue mutation."""

        if not isinstance(payload, (bytes, bytearray, memoryview)):
            raise OwnedNetworkError("network payload must be bytes-like")
        if logical_time < 0:
            raise OwnedNetworkError("logical_time must be non-negative")

    def namespaces(self) -> tuple[str, ...]:
        """Mathematics: expose finite namespace set `N` in lexicographic canonical order."""

        return tuple(sorted(self._namespaces))

    def interfaces(self) -> tuple[dict[str, Any], ...]:
        """Mathematics: project vertices `V` with queue length `|Q_v|` in address order."""

        return tuple(
            {
                "namespace": endpoint.address.namespace,
                "interface": endpoint.address.interface,
                "mtu": endpoint.mtu,
                "queue_limit": endpoint.queue_limit,
                "queue_length": len(endpoint.queue),
                "link_id": endpoint.link_id,
                "up": endpoint.up,
            }
            for endpoint in sorted(self._endpoints.values(), key=lambda item: item.address)
        )

    def links(self) -> tuple[dict[str, Any], ...]:
        """Mathematics: project edge set `L` in stable link-id order."""

        return tuple(
            {
                "link_id": link.link_id,
                "left": link.left.to_dict(),
                "right": link.right.to_dict(),
            }
            for link in sorted(self._links.values(), key=lambda item: item.link_id)
        )

    def snapshot(self) -> dict[str, Any]:
        """Mathematics: serialize complete graph state `S(G,Q,k,J)` including every queued frame."""

        queues = [
            {
                "address": endpoint.address.to_dict(),
                "frames": [frame.to_dict() for frame in endpoint.queue],
            }
            for endpoint in sorted(self._endpoints.values(), key=lambda item: item.address)
            if endpoint.queue
        ]
        return {
            "queue_limit": self.queue_limit,
            "next_frame_id": self._next_frame_id,
            "namespaces": list(self.namespaces()),
            "interfaces": list(self.interfaces()),
            "links": list(self.links()),
            "queues": queues,
            "journal": self.journal.snapshot(),
        }

    @classmethod
    def from_snapshot(
        cls,
        payload: dict[str, Any],
        journal: EventJournal | None = None,
    ) -> "OwnedNetworkFabric":
        """Mathematics: reconstruct `G` and require queue/link/frame references to be closed and unique."""

        saved_journal = payload.get("journal", [])
        shared_journal = journal or EventJournal.from_snapshot(list(saved_journal))
        if journal is not None and shared_journal.snapshot() != saved_journal:
            raise OwnedNetworkError("owned network journal differs from environment journal")
        fabric = cls(shared_journal, int(payload["queue_limit"]))
        for name in payload.get("namespaces", ()):
            checked = _check_name(str(name), "namespace")
            if checked in fabric._namespaces:
                raise OwnedNetworkError(f"duplicate namespace: {checked}")
            fabric._namespaces.add(checked)
        for raw in payload.get("interfaces", ()):
            item = dict(raw)
            address = NetworkAddress(str(item["namespace"]), str(item["interface"]))
            fabric._require_namespace(address.namespace)
            fabric._validate_mtu(int(item["mtu"]))
            if address in fabric._endpoints:
                raise OwnedNetworkError(f"duplicate interface: {address.path()}")
            queue_limit = int(item["queue_limit"])
            if queue_limit <= 0:
                raise OwnedNetworkError("interface queue_limit must be positive")
            fabric._endpoints[address] = _Endpoint(
                address,
                int(item["mtu"]),
                queue_limit,
                None if item.get("link_id") is None else str(item["link_id"]),
                bool(item.get("up", True)),
            )
        for raw in payload.get("links", ()):
            item = dict(raw)
            link_id = _check_name(str(item["link_id"]), "link")
            left = NetworkAddress.from_dict(dict(item["left"]))
            right = NetworkAddress.from_dict(dict(item["right"]))
            if link_id in fabric._links or left == right:
                raise OwnedNetworkError("invalid or duplicate link in checkpoint")
            left_endpoint = fabric._require_endpoint(left)
            right_endpoint = fabric._require_endpoint(right)
            if left_endpoint.link_id != link_id or right_endpoint.link_id != link_id:
                raise OwnedNetworkError("interface/link attachment mismatch")
            fabric._links[link_id] = _Link(link_id, left, right)
        for endpoint in fabric._endpoints.values():
            if endpoint.link_id is not None and endpoint.link_id not in fabric._links:
                raise OwnedNetworkError("interface references a missing restored link")
        seen_frames: set[int] = set()
        for raw_queue in payload.get("queues", ()):
            queue_record = dict(raw_queue)
            address = NetworkAddress.from_dict(dict(queue_record["address"]))
            endpoint = fabric._require_endpoint(address)
            if endpoint.queue:
                raise OwnedNetworkError("duplicate queue record")
            for raw_frame in queue_record.get("frames", ()):
                frame = NetworkFrame.from_dict(dict(raw_frame))
                if frame.frame_id in seen_frames or frame.destination != address:
                    raise OwnedNetworkError("queued frame identity or destination mismatch")
                source_endpoint = fabric._require_endpoint(frame.source)
                if source_endpoint.link_id is None or source_endpoint.link_id != endpoint.link_id:
                    if not frame.route or frame.route[0] != frame.source or frame.route[-1] != address:
                        raise OwnedNetworkError("queued frame source is not directly linked to destination")
                for current, neighbor in zip(frame.route, frame.route[1:]):
                    current_endpoint = fabric._require_endpoint(current)
                    neighbor_endpoint = fabric._require_endpoint(neighbor)
                    same_namespace = current.namespace == neighbor.namespace
                    linked = current_endpoint.link_id is not None and current_endpoint.link_id == neighbor_endpoint.link_id
                    if not same_namespace and not linked:
                        raise OwnedNetworkError("restored frame route crosses a missing link")
                if len(frame.payload) > min(fabric._require_endpoint(address).mtu for address in frame.route):
                    raise OwnedNetworkError("queued frame exceeds restored MTU")
                if len(endpoint.queue) >= endpoint.queue_limit:
                    raise OwnedNetworkError("restored queue exceeds queue limit")
                seen_frames.add(frame.frame_id)
                endpoint.queue.append(frame)
        next_frame_id = int(payload["next_frame_id"])
        if next_frame_id <= 0 or (seen_frames and next_frame_id <= max(seen_frames)):
            raise OwnedNetworkError("invalid next frame identity")
        fabric._next_frame_id = next_frame_id
        return fabric

    def _require_namespace(self, name: str) -> None:
        """Mathematics: enforce membership predicate `n∈N` before graph mutation or lookup."""

        _check_name(name, "namespace")
        if name not in self._namespaces:
            raise OwnedNetworkError(f"unknown namespace: {name}")

    def _require_endpoint(self, address: NetworkAddress) -> _Endpoint:
        """Mathematics: resolve vertex `v∈V`, rejecting any address outside the graph domain."""

        if not isinstance(address, NetworkAddress):
            raise OwnedNetworkError("network address must be NetworkAddress")
        try:
            return self._endpoints[address]
        except KeyError as exc:
            raise OwnedNetworkError(f"unknown interface: {address.path()}") from exc

    @staticmethod
    def _validate_mtu(mtu: int) -> None:
        """Mathematics: require link payload bound `68≤mtu≤65535`, the bounded virtual Ethernet domain."""

        if not _MIN_MTU <= int(mtu) <= _MAX_MTU:
            raise OwnedNetworkError(f"mtu must be between {_MIN_MTU} and {_MAX_MTU}")


class OwnedLinkDriver:
    """Transactional adapter from one owned raw-frame queue to a semantic frame consumer."""

    def __init__(
        self,
        fabric: OwnedNetworkFabric,
        endpoint: NetworkAddress,
        consumer: FrameConsumer,
    ) -> None:
        """Mathematics: bind driver state `(F,e,D)` without consuming `Q_e`; delivery is commit-after-accept."""

        fabric._require_endpoint(endpoint)
        self.fabric = fabric
        self.endpoint = endpoint
        self.consumer = consumer

    def drain(self, max_frames: int = 1) -> tuple[Any, ...]:
        """Mathematics: repeat `peek → D.ingest → dequeue` at most `m` times; failed `D.ingest` leaves `Q_e` unchanged.

        The returned tuple contains one consumer result per accepted frame.
        This is the commit boundary between owned transport and semantic
        decoding: transport acknowledgement occurs only after decoding accepts.
        """

        if max_frames < 0:
            raise ValueError("max_frames must be non-negative")
        results: list[Any] = []
        for _ in range(max_frames):
            frame = self.fabric.peek(self.endpoint)
            if frame is None:
                break
            result = self.consumer.ingest(frame.logical_time, frame.payload)
            committed = self.fabric.receive(self.endpoint)
            if committed is None or committed.frame_id != frame.frame_id:
                raise OwnedNetworkError("owned link changed during driver commit")
            self.fabric.journal.append(
                "network.link_driver.commit",
                {"endpoint": self.endpoint.to_dict(), "frame_id": frame.frame_id},
            )
            results.append(result)
        return tuple(results)
