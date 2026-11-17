"""PATH-GROUND-004: independently observed kernel IPv4 forwarding as a Ground.

This module RECONSTRUCTS evidence obtained by controlled sender, receiver,
and Linux AF_PACKET observers on both sides of actual forwarding interfaces.
No E-CPU handler executes on the routers: the OS forwarding path decrements
IPv4 TTL. The source's desired TTL and receiver's actual IP_RECVTTL ancillary
field are distinct facts. Router observations preserve the actual IP headers.

Content hashes do not authenticate a remote sensor. The executing trusted
network-namespace harness owns the observation boundary; this module does not
grant remote execution rights, create a second scheduler, or imply that paths
with different names inhabit independent physical machines.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import ipaddress
import json
import re
import socket
import struct
from typing import Any, Mapping, Sequence

from .law_certifier import Law
from .substrate_bootstrap import ChannelObservation

SCHEMA = "mailcpu.path-ground-004.kernel-ipv4-hop.v1"
MAGIC = b"ECPU-PG4:"
TTL_PROBES = (4, 7, 32, 33, 64, 127)
ROUTES = {"direct": (), "one": ("one.r1",), "two": ("two.r1", "two.r2")}
_MAX_FRAME = 2048
_HASH = re.compile(r"[0-9a-f]{64}\Z")


class RouterGroundRefused(ValueError):
    """A malformed or unverified intermediate network operation is refused."""


def _canonical(obj: Any) -> bytes:
    """Mathematics: assign deterministic bytes to finite JSON evidence."""
    try:
        return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise RouterGroundRefused("noncanonical router evidence") from exc


def _digest(obj: Any) -> str:
    """Mathematics: content-address an observation without minting authority."""
    return sha256(_canonical(obj)).hexdigest()


def _integer(x: Any, what: str, low: int, high: int) -> int:
    """Mathematics: admit exact integers only inside a finite observer budget."""
    if type(x) is not int or not low <= x <= high:
        raise RouterGroundRefused(f"{what} must be integer in [{low},{high}]")
    return x


def _ipv4(value: Any) -> str:
    """Mathematics: restrict this experiment to non-loopback private IPv4 loci."""
    if type(value) is not str:
        raise RouterGroundRefused("IPv4 address is missing")
    try:
        ip = ipaddress.IPv4Address(value)
    except ipaddress.AddressValueError as exc:
        raise RouterGroundRefused("invalid IPv4 address") from exc
    if not ip.is_private or ip.is_loopback or ip.is_multicast or ip.is_unspecified:
        raise RouterGroundRefused("IPv4 address is outside controlled private network")
    return str(ip)


def _seq(payload: bytes) -> int:
    """Mathematics: parse an exact deterministic packet identifier, never code."""
    if (not isinstance(payload, bytes) or not payload.startswith(MAGIC)
            or len(payload) != len(MAGIC) + 2 + 4):
        raise RouterGroundRefused("unexpected packet identifier or payload extent")
    return int.from_bytes(payload[len(MAGIC):len(MAGIC) + 2], "big")


def probe_payload(sequence: int) -> bytes:
    """Mathematics: construct identical typed payload bytes for every tested topology."""
    _integer(sequence, "probe sequence", 0, len(TTL_PROBES) - 1)
    body = MAGIC + sequence.to_bytes(2, "big")
    return body + sha256(body).digest()[:4]


def parse_ethernet_ipv4_udp(frame: bytes) -> dict[str, Any]:
    """Mathematics: independently decode actual Ethernet/IPv4/UDP bytes and IPv4 header fields."""
    if (type(frame) is not bytes or not 14 + 20 + 8 <= len(frame) <= _MAX_FRAME
            or frame[12:14] != b"\x08\x00"):
        raise RouterGroundRefused("captured frame is not bounded Ethernet IPv4")
    ip = frame[14:]
    version_ihl = ip[0]
    ihl = (version_ihl & 0x0F) * 4
    if version_ihl >> 4 != 4 or ihl < 20 or len(ip) < ihl + 8:
        raise RouterGroundRefused("IPv4 version or header extent is invalid")
    total_length = int.from_bytes(ip[2:4], "big")
    if total_length < ihl + 8 or total_length > len(ip):
        raise RouterGroundRefused("IPv4 total extent is inconsistent")
    if ip[9] != socket.IPPROTO_UDP or int.from_bytes(ip[6:8], "big") & 0x3FFF:
        raise RouterGroundRefused("only unfragmented UDP/IPv4 observations are supported")
    udp = ip[ihl:total_length]
    if int.from_bytes(udp[4:6], "big") != len(udp):
        raise RouterGroundRefused("UDP length disagrees with IP extent")
    payload = udp[8:]
    sequence = _seq(payload)
    checksum_words = struct.unpack("!" + "H" * (ihl // 2), ip[:ihl])
    acc = sum(checksum_words)
    while acc >> 16:
        acc = (acc & 0xFFFF) + (acc >> 16)
    return {
        "seq": sequence, "ttl": ip[8],
        "source_ip": socket.inet_ntoa(ip[12:16]),
        "destination_ip": socket.inet_ntoa(ip[16:20]),
        "source_port": int.from_bytes(udp[0:2], "big"),
        "destination_port": int.from_bytes(udp[2:4], "big"),
        "payload_hex": payload.hex(),
        "ip_id": int.from_bytes(ip[4:6], "big"),
        "ip_checksum_valid": acc == 0xFFFF,
    }


def _exact_keys(value: Any, fields: set[str], label: str) -> Mapping[str, Any]:
    """Mathematics: refuse undocumented extra/missing evidence coordinates."""
    if not isinstance(value, dict) or set(value) != fields:
        raise RouterGroundRefused(f"{label} has unsupported evidence fields")
    return value


@dataclass(frozen=True)
class ObservedRoute:
    """One complete source/router/receiver trace for one fixed controlled topology."""

    route_id: str
    hops: int
    source_ttls: tuple[int, ...]
    received_ttls: tuple[int, ...]
    evidence_digest: str
    packet_bytes: int
    router_captures: int
    checksum_valid_frames: int

    def __post_init__(self) -> None:
        """Mathematics: preserve exactly the known finite route/hop relation."""
        if type(self.route_id) is not str or self.route_id not in ROUTES:
            raise RouterGroundRefused("unknown router path")
        if self.hops != len(ROUTES[self.route_id]):
            raise RouterGroundRefused("route hop count differs from admitted shape")
        if self.source_ttls != TTL_PROBES or len(self.received_ttls) != len(TTL_PROBES):
            raise RouterGroundRefused("source TTL probes are not identical across routes")
        if self.received_ttls != tuple(t - self.hops for t in TTL_PROBES):
            raise RouterGroundRefused("observed receiver TTL contradicts actual route")
        if type(self.evidence_digest) is not str or not _HASH.fullmatch(self.evidence_digest):
            raise RouterGroundRefused("invalid route-evidence content identity")
        _integer(self.packet_bytes, "packet bytes", 1, _MAX_FRAME)
        _integer(self.router_captures, "captured frames", 0, 4 * len(TTL_PROBES))
        _integer(self.checksum_valid_frames, "valid IPv4 checksums", 0, self.router_captures)


def verify_router_route(route_id: str, source: Mapping[str, Any],
                        receiver: Mapping[str, Any],
                        routers: Sequence[Mapping[str, Any]]) -> ObservedRoute:
    """Mathematics: verify actual ingress/egress packet bytes across each expected forwarding hop.

    Source socket TTL declarations, raw intermediate router IP header TTLs,
    and receiver socket IP_RECVTTL results are independently checked. A caller
    must still trust who actually captured the three evidence classes; packet
    content hashes are not signatures or independent-host attestations.
    """
    if route_id not in ROUTES or type(route_id) is not str:
        raise RouterGroundRefused("unrecognized route intention")
    ids = ROUTES[route_id]
    src = _exact_keys(source, {"schema", "source_ip", "destination_ip", "source_port",
                               "destination_port", "frames"}, "sender")
    dst = _exact_keys(receiver, {"schema", "destination_ip", "frames"}, "receiver")
    if (src["schema"] != SCHEMA + ".sender" or dst["schema"] != SCHEMA + ".receiver"
            or _ipv4(src["source_ip"]) == _ipv4(src["destination_ip"])
            or _ipv4(dst["destination_ip"]) != src["destination_ip"]):
        raise RouterGroundRefused("source/destination identity disagrees")
    for key in ("source_port", "destination_port"):
        _integer(src[key], key, 1024, 65535)
    if (not isinstance(src["frames"], list) or not isinstance(dst["frames"], list)
            or len(src["frames"]) != len(TTL_PROBES)
            or len(dst["frames"]) != len(TTL_PROBES)
            or not isinstance(routers, (tuple, list)) or len(routers) != len(ids)):
        raise RouterGroundRefused("missing or unexpected source, router or destination packets")
    original: dict[int, bytes] = {}
    for i, frame in enumerate(src["frames"]):
        record = _exact_keys(frame, {"seq", "sent_ttl", "payload_hex"}, "sent packet")
        if record["seq"] != i or record["sent_ttl"] != TTL_PROBES[i]:
            raise RouterGroundRefused("source TTL/address coordinate was changed")
        if type(record["payload_hex"]) is not str or record["payload_hex"] != probe_payload(i).hex():
            raise RouterGroundRefused("source packet content changed")
        original[i] = bytes.fromhex(record["payload_hex"])
    received: list[int] = []
    for i, frame in enumerate(dst["frames"]):
        record = _exact_keys(frame, {"seq", "received_ttl", "payload_hex", "source_ip", "source_port"}, "received packet")
        if (record["seq"] != i or record["payload_hex"] != original[i].hex()
                or record["source_ip"] != src["source_ip"] or record["source_port"] != src["source_port"]):
            raise RouterGroundRefused("receiver did not observe the expected exact source packet")
        ttl = _integer(record["received_ttl"], "received IP_RECVTTL", 1, 255)
        if ttl != TTL_PROBES[i] - len(ids):
            raise RouterGroundRefused("receiver IP TTL does not match forwarded route")
        received.append(ttl)
    verified_frames = 0
    valid_checksums = 0
    for router_index, capture in enumerate(routers):
        record = _exact_keys(capture, {"schema", "router_id", "ingress_iface",
                                      "egress_iface", "frames"}, "router capture")
        if record["schema"] != SCHEMA + ".router" or record["router_id"] != ids[router_index]:
            raise RouterGroundRefused("router namespace identity changed")
        if (type(record["ingress_iface"]) is not str or type(record["egress_iface"]) is not str
                or record["ingress_iface"] == record["egress_iface"]):
            raise RouterGroundRefused("router ingress and egress must be distinct interfaces")
        frames = record["frames"]
        if not isinstance(frames, list) or len(frames) != len(TTL_PROBES) * 2:
            raise RouterGroundRefused("router did not observe both sides of all packets")
        by_edge: dict[tuple[int, str], dict[str, Any]] = {}
        for observation in frames:
            x = _exact_keys(observation, {"side", "interface", "raw_hex"}, "router header")
            if x["side"] not in ("ingress", "egress"):
                raise RouterGroundRefused("unknown router interface role")
            iface = record["ingress_iface"] if x["side"] == "ingress" else record["egress_iface"]
            if x["interface"] != iface or type(x["raw_hex"]) is not str:
                raise RouterGroundRefused("router interface record does not match its role")
            try:
                raw = bytes.fromhex(x["raw_hex"])
            except ValueError as exc:
                raise RouterGroundRefused("router captured malformed raw bytes") from exc
            parsed = parse_ethernet_ipv4_udp(raw)
            if (parsed["destination_ip"] != src["destination_ip"]
                    or parsed["source_ip"] != src["source_ip"]
                    or parsed["destination_port"] != src["destination_port"]
                    or parsed["source_port"] != src["source_port"]
                    or parsed["payload_hex"] != original[parsed["seq"]].hex()):
                raise RouterGroundRefused("router packet observation changed IP/UDP identity")
            key = parsed["seq"], x["side"]
            if key in by_edge:
                raise RouterGroundRefused("router reported a duplicate per-side packet")
            by_edge[key] = parsed
            valid_checksums += int(parsed["ip_checksum_valid"])
            verified_frames += 1
        for i, ttl in enumerate(TTL_PROBES):
            if ((i, "ingress") not in by_edge or (i, "egress") not in by_edge
                    or by_edge[(i, "ingress")]["ttl"] != ttl - router_index
                    or by_edge[(i, "egress")]["ttl"] != ttl - router_index - 1
                    or by_edge[(i, "ingress")]["ip_id"] != by_edge[(i, "egress")]["ip_id"]):
                raise RouterGroundRefused("in-network router hop did not decrement TTL exactly once")
    return ObservedRoute(
        route_id, len(ids), TTL_PROBES, tuple(received),
        _digest({"schema": SCHEMA + ".route", "route": route_id,
                 "sender": src, "receiver": dst, "routers": routers}),
        sum(len(b) for b in original.values()), verified_frames,
        valid_checksums,
    )


@dataclass(frozen=True)
class RouterTTLGround:
    """A shared per-router decrement relation with path-distinct evidence."""

    routes: tuple[ObservedRoute, ...]
    scope: str = "controlled_linux_kernel_forwarding_not_public_internet_or_optics"

    def __post_init__(self) -> None:
        """Mathematics: demand direct, one-hop and two-hop real observations before composing."""
        if (self.scope != "controlled_linux_kernel_forwarding_not_public_internet_or_optics"
                or len(self.routes) != 3 or {r.route_id for r in self.routes} != set(ROUTES)
                or any(not isinstance(r, ObservedRoute) for r in self.routes)):
            raise RouterGroundRefused("all three controlled paths must be independently observed")

    @property
    def ground_digest(self) -> str:
        """Mathematics: identify TTL decrement under forwardability independently of topology."""
        return _digest({"schema": SCHEMA + ".mathematical-ground",
                        "operator": "ipv4.forward.ttl_decrement",
                        "domain": "unfragmented_ipv4_udp_valid_forwarded",
                        "per_router": "ttl_out=ttl_in-1",
                        "valid_incoming_ttl": [2, 255],
                        "fixed_source_probe_set": list(TTL_PROBES)})

    @property
    def evidence_digest(self) -> str:
        """Mathematics: bind topology-specific measurements without changing the semantic Ground."""
        return _digest({x.route_id: x.evidence_digest for x in self.routes})

    def navigate(self, initial_ttl: int, hops: int) -> dict[str, Any]:
        """Mathematics: jump to the hypothetical or observed IPv4 hop orbit in O(1)."""
        _integer(initial_ttl, "initial TTL", 1, 255)
        _integer(hops, "hop coordinate", 0, 254)
        if hops >= initial_ttl:
            raise RouterGroundRefused("forwarded IPv4 packet expires before desired observation")
        law = Law("int", {"x0": initial_ttl, "step": -1}, 1, "GROUND")
        return {
            "schema": SCHEMA + ".navigation", "initial_ttl": initial_ttl,
            "hops": hops, "destination_ttl": law.navigate(hops),
            "ground_digest": self.ground_digest,
            "evidence_digest": self.evidence_digest,
            "scope": ("observed_controlled_route_relation" if hops <= 2
                      else "symbolic_rfc_model_not_observed_future_route"),
            "network_frames_sent_to_navigate": 0,
        }

    def inverse_intention(self, desired_ttl: int, hops: int) -> dict[str, Any]:
        """Mathematics: invert the declared hop relation without replay or state enumeration."""
        _integer(desired_ttl, "desired visible TTL", 1, 255)
        _integer(hops, "intended hop coordinate", 0, 254)
        if desired_ttl + hops > 255:
            raise RouterGroundRefused("inverse TTL intention exceeds IPv4 field capacity")
        source_ttl = desired_ttl + hops
        forward = self.navigate(source_ttl, hops)
        if forward["destination_ttl"] != desired_ttl:
            raise RouterGroundRefused("inverse intention does not forward-verify")
        return {
            "source_ttl": source_ttl, "hops": hops, "destination_ttl": desired_ttl,
            "ground_digest": self.ground_digest, "forward_check": forward,
            "scope": forward["scope"],
        }

    def native_channel_observations(self) -> tuple[ChannelObservation, ...]:
        """Mathematics: reuse SAB native channel types without claiming a route grants authority.

        One channel denotes each VERIFIED end-to-end path, not a proof that
        every passive edge computed. Router transformations are established
        separately by the actual ingress/egress Ethernet frame evidence.
        """
        return tuple(ChannelObservation(
            channel_id="pg4." + route.route_id,
            source="pg4.source." + route.route_id,
            target="pg4.receiver." + route.route_id,
            carries=("ipv4.datagram",), estimated_quanta=max(1, route.hops),
            observed_at=1, expires_at=1, evidence_digest=route.evidence_digest,
            max_payload_bytes=route.packet_bytes,
        ) for route in self.routes)


def recognize_router_ttl_ground(
    direct: ObservedRoute, one: ObservedRoute, two: ObservedRoute,
) -> RouterTTLGround:
    """Mathematics: compose three exact path observations into one shared hop relation."""
    return RouterTTLGround((direct, one, two))
