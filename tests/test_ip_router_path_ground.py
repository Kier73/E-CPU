"""PATH-GROUND-004 independent raw-frame controls and mathematical navigation tests.

Synthetic raw Ethernet packets verify strict byte-level reconstruction. Only
the privileged Linux workflow uses genuine intermediary IP forwarding and
AF_PACKET captures, which must not be replaced by this unit fixture.
"""
from __future__ import annotations

from dataclasses import replace
import socket
import struct
import sys

import pytest

from mailcpu.ip_router_path_ground import (
    MAGIC, IP_HOPS, ROUTES, SCHEMA, TTL_PROBES,
    RouterGroundRefused, parse_ethernet_ipv4_udp, probe_payload,
    recognize_router_ttl_ground, verify_router_route,
)


def _checksum(buffer):
    """Return a correct IPv4 ones-complement checksum over a header."""
    words = struct.unpack("!" + "H" * (len(buffer) // 2), buffer)
    acc = sum(words)
    while acc >> 16:
        acc = (acc & 0xffff) + (acc >> 16)
    return (~acc) & 0xffff


def _raw_ipv4_packet(seq, ttl, *, source_ip, destination_ip, source_port, dest_port, ipid=None):
    """Generate a synthetic Ethernet frame for testing verification, NOT physical forwarding."""
    data = probe_payload(seq)
    if ipid is None:
        ipid = 2300 + seq
    header = struct.pack(
        "!BBHHHBBH4s4s", 0x45, 0, 20 + 8 + len(data), ipid, 0,
        ttl, socket.IPPROTO_UDP, 0,
        socket.inet_aton(source_ip), socket.inet_aton(destination_ip),
    )
    digest = _checksum(header)
    header = header[:10] + struct.pack("!H", digest) + header[12:]
    udp = struct.pack("!HHHH", source_port, dest_port, 8 + len(data), 0)
    return b"\xaa" * 6 + b"\xbb" * 6 + b"\x08\x00" + header + udp + data


def _make(route):
    """Build an intentionally labeled synthetic observation across the expected route shape."""
    hop_count = IP_HOPS[route]
    source_ip = {"direct": "10.73.0.1", "bridge": "10.73.6.1",
                 "one": "10.73.1.1", "two": "10.73.3.1"}[route]
    dest_ip = {"direct": "10.73.0.2", "bridge": "10.73.6.2",
               "one": "10.73.2.2", "two": "10.73.5.2"}[route]
    source_port = 48510
    port = 46831
    source = {
        "schema": SCHEMA + ".sender", "source_ip": source_ip,
        "destination_ip": dest_ip, "source_port": source_port,
        "destination_port": port, "frames": [
            {"seq": seq, "sent_ttl": ttl, "payload_hex": probe_payload(seq).hex()}
            for seq, ttl in enumerate(TTL_PROBES)
        ],
    }
    receiver = {
        "schema": SCHEMA + ".receiver", "destination_ip": dest_ip,
        "frames": [{
            "seq": seq, "received_ttl": ttl - hop_count,
            "payload_hex": probe_payload(seq).hex(),
            "source_ip": source_ip, "source_port": source_port,
        } for seq, ttl in enumerate(TTL_PROBES)],
    }
    routers = []
    for i, name in enumerate(ROUTES[route]):
        frames = []
        for seq, ttl in enumerate(TTL_PROBES):
            for side, remaining in (
                ("ingress", ttl - max(i, 0) if route != "bridge" else ttl),
                ("egress", ttl - i - 1 if route != "bridge" else ttl),
            ):
                raw = _raw_ipv4_packet(
                    seq, remaining, source_ip=source_ip,
                    destination_ip=dest_ip,
                    source_port=source_port, dest_port=port,
                )
                frames.append({
                    "side": side, "interface": "in" if side == "ingress" else "out",
                    "raw_hex": raw.hex(),
                })
        routers.append({
            "schema": SCHEMA + ".router", "router_id": name,
            "ingress_iface": "in", "egress_iface": "out", "frames": frames,
        })
    return source, receiver, routers


def _verified():
    """Create three verified SYNTHETIC route relationships without any network effects."""
    return [verify_router_route(route, *_make(route)) for route in ROUTES]


def test_ipv4_packet_parser_independently_checks_source_bytes_ttl_and_checksum():
    """Reconstruct the true packet header, not a claimed pre-decoded TTL."""
    data = _raw_ipv4_packet(
        3, 32, source_ip="10.73.3.1", destination_ip="10.73.5.2",
        source_port=48510, dest_port=46831,
    )
    parsed = parse_ethernet_ipv4_udp(data)
    assert parsed["seq"] == 3
    assert parsed["ttl"] == 32
    assert parsed["destination_port"] == 46831
    assert parsed["payload_hex"] == probe_payload(3).hex()
    assert parsed["ip_checksum_valid"] is True
    assert parsed["ip_id"] == 2303


def test_four_path_topologies_distinguish_l2_bridging_from_ip_ttl_forwarding():
    """One forwarding law has three distinct carrier placements and observed output orbits."""
    direct, bridge, one, two = _verified()
    assert direct.received_ttls == bridge.received_ttls == TTL_PROBES
    assert one.received_ttls == tuple(ttl - 1 for ttl in TTL_PROBES)
    assert two.received_ttls == tuple(ttl - 2 for ttl in TTL_PROBES)
    assert [x.router_captures for x in (direct, bridge, one, two)] == [0, 12, 12, 24]
    assert [x.checksum_valid_frames for x in (direct, bridge, one, two)] == [0, 12, 12, 24]
    assert len({x.evidence_digest for x in (direct, bridge, one, two)}) == 4
    assert bridge.hops == 0 and bridge.router_captures == 12
    ground = recognize_router_ttl_ground(direct, bridge, one, two)
    assert ground.navigate(64, 2)["destination_ttl"] == 62
    assert ground.navigate(64, 40)["destination_ttl"] == 24
    assert "symbolic_rfc" in ground.navigate(64, 40)["scope"]


def test_inverse_intention_realizes_same_observation_across_changed_route():
    """The observer requests a terminal TTL; E-CPU derives the different source coordinate."""
    ground = recognize_router_ttl_ground(*_verified())
    one = ground.inverse_intention(31, 1)
    two = ground.inverse_intention(31, 2)
    assert (one["source_ttl"], two["source_ttl"]) == (32, 33)
    assert one["destination_ttl"] == two["destination_ttl"] == 31
    assert ground.ground_digest == one["ground_digest"] == two["ground_digest"]
    assert ground.navigate(64, 40)["network_frames_sent_to_navigate"] == 0


def test_intention_equivalence_is_not_universal_transition_congruence():
    """Current matching output does not imply equal future TTL-domain admissibility.

    See IFS observation-equivalence transition-congruence and VGI's
    distinguishing-continuation analysis: a matched observation is only
    a quotient for the declared intention and its finite operating domain.
    """
    ground = recognize_router_ttl_ground(*_verified())
    a = ground.inverse_intention(31, 1)
    b = ground.inverse_intention(31, 2)
    assert a["destination_ttl"] == b["destination_ttl"] == 31
    # A future intention near the 8-bit TTL ceiling distinguishes routes:
    # source 255 can realize 254 after one hop, but source 256 is invalid.
    assert ground.inverse_intention(254, 1)["source_ttl"] == 255
    with pytest.raises(RouterGroundRefused, match="field capacity"):
        ground.inverse_intention(254, 2)


def test_reuse_native_sab_channel_observations_without_granting_kernel_authority():
    """Each checked route can be described as a native E-CPU channel observation."""
    ground = recognize_router_ttl_ground(*_verified())
    channels = ground.native_channel_observations()
    assert len(channels) == 4
    assert [x.channel_id for x in channels] == ["pg4.direct", "pg4.bridge", "pg4.one", "pg4.two"]
    assert len({x.evidence_digest for x in channels}) == 4
    assert channels[1].carries == ("ipv4.datagram",)
    assert channels[1].source != channels[1].target
    assert channels[1].expires_at == 1


@pytest.mark.parametrize("route", ("direct", "bridge", "one", "two"))
def test_source_destination_or_router_must_supply_every_packet(route):
    """Missing actual packet observations cannot be filled with expected mathematical data."""
    source, receiver, routers = _make(route)
    receiver["frames"].pop()
    with pytest.raises(RouterGroundRefused, match="missing|unexpected"):
        verify_router_route(route, source, receiver, routers)


def test_router_ingress_egress_are_not_interchangeable():
    """The same packet observed twice on ingress is not a forwarding transition."""
    src, dst, routers = _make("one")
    routers[0]["frames"][1]["side"] = "ingress"
    routers[0]["frames"][1]["interface"] = "in"
    with pytest.raises(RouterGroundRefused, match="duplicate"):
        verify_router_route("one", src, dst, routers)


def test_changed_router_ip_ttl_is_rejected_against_source_and_receiver():
    """Mutating only the egress TTL contradicts the admitted per-hop operator."""
    src, dst, routers = _make("two")
    frame = routers[0]["frames"][1]
    altered = bytearray.fromhex(frame["raw_hex"])
    altered[14 + 8] = 37
    frame["raw_hex"] = altered.hex()
    with pytest.raises(RouterGroundRefused, match="relation contradicts"):
        verify_router_route("two", src, dst, routers)


def test_router_must_show_no_udp_payload_change_and_no_ip_identity_change():
    """Forwarding changes TTL, but the tested IP/UDP representation remains bound."""
    for position in ("payload", "src"):
        src, dst, routers = _make("one")
        frame = routers[0]["frames"][3]
        raw = bytearray.fromhex(frame["raw_hex"])
        if position == "payload":
            raw[-1] ^= 1
        else:
            raw[14 + 12] = 192
        frame["raw_hex"] = raw.hex()
        with pytest.raises(RouterGroundRefused, match="identity"):
            verify_router_route("one", src, dst, routers)


def test_layer_two_bridge_cannot_announce_an_ip_router_ttl_transition():
    """Bridge packet continuity is observed, but that does not authorize a fictitious IP hop."""
    src, dst, routers = _make("bridge")
    observed = routers[0]["frames"][1]
    observed["raw_hex"] = _raw_ipv4_packet(
        0, TTL_PROBES[0] - 1, source_ip=src["source_ip"],
        destination_ip=src["destination_ip"],
        source_port=src["source_port"], dest_port=src["destination_port"],
    ).hex()
    with pytest.raises(RouterGroundRefused, match="relation contradicts"):
        verify_router_route("bridge", src, dst, routers)


def test_unexpected_router_packet_sequence_must_refuse_not_raise_key_error():
    """A captured probe outside the receiver-controlled set is invalid evidence."""
    src, dst, routers = _make("one")
    frame = routers[0]["frames"][1]
    raw = bytearray.fromhex(frame["raw_hex"])
    ip_header_length = 20
    udp_payload_start = 14 + ip_header_length + 8
    seq_offset = udp_payload_start + len(MAGIC)
    raw[seq_offset:seq_offset + 2] = (255).to_bytes(2, "big")
    frame["raw_hex"] = raw.hex()
    with pytest.raises(RouterGroundRefused, match="identity"):
        verify_router_route("one", src, dst, routers)


def test_tampered_receiver_ancillary_value_is_refused():
    """A remote sender cannot assert the receiver's actual kernel IP_RECVTTL measurement."""
    src, dst, routers = _make("one")
    dst["frames"][4]["received_ttl"] = TTL_PROBES[4]
    with pytest.raises(RouterGroundRefused, match="receiver IP TTL"):
        verify_router_route("one", src, dst, routers)


def test_unknown_router_or_path_requires_refusal():
    """An invented transit host cannot be added by changing names or self-hashed receipts."""
    src, dst, routers = _make("one")
    routers[0]["router_id"] = "untrusted-router"
    with pytest.raises(RouterGroundRefused, match="namespace identity"):
        verify_router_route("one", src, dst, routers)
    with pytest.raises(RouterGroundRefused):
        verify_router_route("unknown", src, dst, routers)


def test_router_identity_refuses_header_id_mismatch_and_fragmentation():
    """The same UDP bytes in a different IP datagram do not prove a single forwarding event."""
    src, dst, routers = _make("one")
    frame = routers[0]["frames"][1]
    raw = bytearray.fromhex(frame["raw_hex"])
    raw[14 + 4:14 + 6] = (654).to_bytes(2, "big")
    frame["raw_hex"] = raw.hex()
    with pytest.raises(RouterGroundRefused, match="identity"):
        verify_router_route("one", src, dst, routers)

    src, dst, routers = _make("one")
    frame = routers[0]["frames"][0]
    raw = bytearray.fromhex(frame["raw_hex"])
    raw[14 + 6:14 + 8] = (1).to_bytes(2, "big")
    frame["raw_hex"] = raw.hex()
    with pytest.raises(RouterGroundRefused, match="unfragmented"):
        verify_router_route("one", src, dst, routers)


def test_symbolic_navigation_refuses_ipv4_ttl_expiration_and_unsupported_inverse():
    """A symbolic description does not enable travel past the exact TTL expiry horizon."""
    ground = recognize_router_ttl_ground(*_verified())
    for ttl, hops in ((1, 1), (2, 2), (255, 255), (0, 0)):
        with pytest.raises(RouterGroundRefused):
            ground.navigate(ttl, hops)
    for desired, hops in ((254, 2), (0, 1), (31, 256)):
        with pytest.raises(RouterGroundRefused):
            ground.inverse_intention(desired, hops)


def test_corrupted_ethernet_or_illegal_ip_header_is_not_a_router_witness():
    """An ordinary byte digest does not make an invalid packet a valid IPv4 observation."""
    raw = _raw_ipv4_packet(
        1, 32, source_ip="10.73.1.1", destination_ip="10.73.2.2",
        source_port=48510, dest_port=46831,
    )
    with pytest.raises(RouterGroundRefused):
        parse_ethernet_ipv4_udp(raw[:16])
    bad = raw[:12] + b"\x08\x06" + raw[14:]
    with pytest.raises(RouterGroundRefused):
        parse_ethernet_ipv4_udp(bad)


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux IP_RECVTTL ancillary ABI")
def test_actual_linux_udp_loopback_delivers_kernel_ttl_ancillary():
    """Read IP TTL from a real kernel control message, independent of the source payload."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as receiver:
        receiver.setsockopt(socket.IPPROTO_IP, 12, 1)  # Linux IP_RECVTTL
        receiver.bind(("127.0.0.1", 0))
        receiver.settimeout(2)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sender:
            sender.setsockopt(socket.IPPROTO_IP, socket.IP_TTL, 44)
            payload = probe_payload(0)
            sender.sendto(payload, receiver.getsockname())
            data, ancillary, flags, addr = receiver.recvmsg(512, 128)
        observed = [
            int.from_bytes(value[:4], sys.byteorder)
            for level, typ, value in ancillary
            if level == socket.IPPROTO_IP and typ == socket.IP_TTL and len(value) == 4
        ]
        assert data == payload and observed == [44] and not flags & socket.MSG_TRUNC
