"""PATH-GROUND-004 controlled Linux network-namespace endpoint and router observers.

This module captures real AF_PACKET IPv4 headers on both sides of Linux
forwarding interfaces and real receiver-side IP_RECVTTL ancillary values.
It never implements the forwarding operator in Python. Only the native
kernel forwarding path decrements TTL. A separate verifier reads the raw
on-route bytes, not the source's claimed mathematical prediction.

Only use with scripts/run_ip_router_path_ground.sh on owned namespaces.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import select
import socket
import sys
import time

from mailcpu.ip_router_path_ground import (
    MAGIC, ROUTES, SCHEMA, TTL_PROBES,
    RouterGroundRefused, parse_ethernet_ipv4_udp, probe_payload,
    recognize_router_ttl_ground, verify_router_route,
)
from mailcpu.router_observer_path import (
    bind_router_packet_observer_path, verify_router_packet_path_binding,
)
from mailcpu.semantic_translation import canonical_value_digest

# Linux SOL_IP/IP_RECVTTL = 12. Python's socket module may omit the name.
_LINUX_IP_RECVTTL = 12
_DEST_PORT = 46831


def _write(path: Path, payload: object) -> None:
    """Mathematics: publish a complete finite observation only after its successful measurement."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def _ready(path: Path) -> None:
    """Mathematics: separate socket initialization from source emission."""
    path.write_text("ready\n", encoding="utf-8")


def send(source_ip: str, destination_ip: str, output: Path) -> None:
    """Mathematics: emit SOURCE-controlled TTLs without modifying router forwarding behavior."""
    frames = []
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as src:
        src.bind((source_ip, 0))
        source_port = src.getsockname()[1]
        for seq, ttl in enumerate(TTL_PROBES):
            src.setsockopt(socket.IPPROTO_IP, socket.IP_TTL, ttl)
            data = probe_payload(seq)
            if src.sendto(data, (destination_ip, _DEST_PORT)) != len(data):
                raise RouterGroundRefused("short source UDP datagram send")
            frames.append({"seq": seq, "sent_ttl": ttl, "payload_hex": data.hex()})
            time.sleep(0.025)
    _write(output, {
        "schema": SCHEMA + ".sender", "source_ip": source_ip,
        "destination_ip": destination_ip, "source_port": source_port,
        "destination_port": _DEST_PORT, "frames": frames,
    })


def receive(destination_ip: str, output: Path, ready: Path) -> None:
    """Mathematics: observe actual kernel IP_TTL ancillary data, without re-evaluating hop arithmetic."""
    frames = []
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as dst:
        dst.setsockopt(socket.IPPROTO_IP, _LINUX_IP_RECVTTL, 1)
        dst.bind((destination_ip, _DEST_PORT))
        dst.settimeout(8.0)
        _ready(ready)
        for _ in TTL_PROBES:
            raw, ancillary, flags, peer = dst.recvmsg(2048, 128)
            if flags & socket.MSG_TRUNC:
                raise RouterGroundRefused("destination datagram was truncated")
            fields = [
                int.from_bytes(value[:4], sys.byteorder)
                for level, opt, value in ancillary
                if level == socket.IPPROTO_IP and opt == socket.IP_TTL and len(value) == 4
            ]
            if len(fields) != 1:
                raise RouterGroundRefused("no unique native IP_TTL ancillary observation")
            if raw not in (probe_payload(seq) for seq in range(len(TTL_PROBES))):
                raise RouterGroundRefused("received unexpected test datagram")
            seq = int.from_bytes(raw[len(MAGIC):len(MAGIC) + 2], "big")
            frames.append({
                "seq": seq, "received_ttl": fields[0],
                "payload_hex": raw.hex(), "source_ip": peer[0],
                "source_port": peer[1],
            })
    _write(output, {
        "schema": SCHEMA + ".receiver", "destination_ip": destination_ip,
        "frames": frames,
    })


def capture_router(
    router_id: str, ingress: str, egress: str,
    destination_ip: str, output: Path, ready: Path,
    *, live_plan: Path | None = None, live_key: Path | None = None,
    live_receipt: Path | None = None,
) -> None:
    """Mathematics: capture both actual Ethernet/IP packet headers around native kernel forwarding.

    AF_PACKET is an observing socket only. It does not touch the forwarding
    routing table, modify TTL, or interpret an E-CPU execution request.
    """
    if router_id not in {name for ids in ROUTES.values() for name in ids}:
        raise RouterGroundRefused("unknown declared router identity")
    if ingress == egress:
        raise RouterGroundRefused("router ingress and egress cannot be same interface")
    # PATH-GROUND-006 is an opt-in sensor-local extension. Load the
    # challenge and private leaf key *inside the observer process before*
    # the first datagram arrives. The signer is called directly from recv,
    # not after reopening a saved raw capture.
    signer = None
    if any(value is not None for value in (live_plan, live_key, live_receipt)):
        if not all(value is not None for value in (live_plan, live_key, live_receipt)):
            raise RouterGroundRefused("incomplete capture-time signing identity")
        from cryptography.hazmat.primitives import serialization
        from mailcpu.live_router_capture import CaptureTimeSigner
        plan = json.loads(live_plan.read_text(encoding="utf-8"))
        key = serialization.load_pem_private_key(
            live_key.read_bytes(), password=None,
        )
        signer = CaptureTimeSigner(plan, key)
        if signer.plan["router_id"] != router_id:
            raise RouterGroundRefused("sensor key plan belongs to a different router")
    sockets = []
    selector = select.epoll()
    frames = []
    try:
        for name in (ingress, egress):
            # ETH_P_ALL captures all L2 frames; the verifier accepts only
            # exact observed IPv4/UDP probes. On Linux, binding an
            # AF_PACKET observer with protocol zero to this interface
            # retains the socket's nonzero ETH_P_ALL subscription.
            sock = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(0x0003))
            sock.bind((name, 0))
            sock.setblocking(False)
            sockets.append((name, sock))
            selector.register(sock.fileno(), select.EPOLLIN)
        _ready(ready)
        deadline = time.monotonic() + 8.0
        while len(frames) < len(TTL_PROBES) * 2:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RouterGroundRefused("router did not observe every ingress and egress packet")
            for fd, event in selector.poll(min(remaining, 0.5)):
                sock_name, sock = next((name, s) for name, s in sockets if s.fileno() == fd)
                while True:
                    try:
                        raw, peer = sock.recvfrom(2048)
                    except BlockingIOError:
                        break
                    try:
                        packet = parse_ethernet_ipv4_udp(raw)
                    except RouterGroundRefused:
                        continue
                    if (packet["destination_ip"] != destination_ip
                            or packet["destination_port"] != _DEST_PORT):
                        continue
                    side = "ingress" if sock_name == ingress else "egress"
                    if signer is not None:
                        # Sign this exact raw Ethernet frame at the live
                        # AF_PACKET receive boundary, before any JSON trace
                        # is written for later replay.
                        signer.observe(side, sock_name, raw)
                    frames.append({
                        "side": side, "interface": sock_name, "raw_hex": raw.hex(),
                    })
                    if len(frames) == 2 * len(TTL_PROBES):
                        break
                if len(frames) == 2 * len(TTL_PROBES):
                    break
    finally:
        selector.close()
        for _, sock in sockets:
            sock.close()
    raw_capture = {
        "schema": SCHEMA + ".router", "router_id": router_id,
        "ingress_iface": ingress, "egress_iface": egress,
        "frames": frames,
    }
    if signer is not None:
        # Complete the receipt chain in memory before persisting either
        # trace, so the receiver can compare both exact versions.
        signed = signer.finalize(raw_capture)
        _write(live_receipt, signed)
    _write(output, raw_capture)


def verify(input_dir: Path, output: Path) -> dict:
    """Mathematics: independently recheck each captured real network transition and compose its Ground."""
    observations = {}
    raw_evidence = {}
    for route in ROUTES:
        src = json.loads((input_dir / ("sender-" + route + ".json")).read_text())
        dst = json.loads((input_dir / ("receiver-" + route + ".json")).read_text())
        captures = [
            json.loads((input_dir / ("router-" + route + "-r" + str(i + 1) + ".json")).read_text())
            for i in range(len(ROUTES[route]))
        ]
        observations[route] = verify_router_route(route, src, dst, captures)
        raw_evidence[route] = (src, dst, captures)
    ground = recognize_router_ttl_ground(*(observations[x] for x in ROUTES))
    # Native receipts are authored by the trusted receiver after independent
    # raw frame verification. The callback is an owned-harness acceptance
    # policy, not a signature or independent kernel/physical attestation.
    policy_digest = canonical_value_digest({
        "schema": SCHEMA + ".receiver-policy",
        "revision": 1, "observed_kernel": "local-namespace-harness",
        "require_raw_ipv4_ingress_egress": True,
        "require_receiver_ip_recvttl": True,
    })
    native_paths = {}
    for route in ROUTES:
        raw_src, raw_dst, raw_captures = raw_evidence[route]
        admitted = lambda candidate, expected=observations[route]: candidate == expected
        bindings = []
        for seq in range(len(TTL_PROBES)):
            bound = bind_router_packet_observer_path(
                ground, route, seq, raw_src, raw_dst, raw_captures,
                admit_capture=admitted, receiver_policy_digest=policy_digest,
            )
            if not verify_router_packet_path_binding(
                bound, ground, route, seq, raw_src, raw_dst, raw_captures,
                admit_capture=admitted, receiver_policy_digest=policy_digest,
            ):
                raise RouterGroundRefused("native observer path failed receiver evidence replay")
            bindings.append(bound)
        native_paths[route] = {
            "verified_packet_count": len(bindings),
            "path_digests": [x.verified.path_digest for x in bindings],
            "ground_ref": bindings[0].verified.ground.to_dict(),
            "route_evidence_digest": observations[route].evidence_digest,
            "stage_modes": [x.mode for x in bindings[0].stages],
            "receiver_policy_digest": policy_digest,
            "authority": "owned_harness_callback_not_external_router_attestation",
        }
    target = 31
    one_intent = ground.inverse_intention(target, 1)
    two_intent = ground.inverse_intention(target, 2)
    if (one_intent["source_ttl"] != 32 or two_intent["source_ttl"] != 33
            or observations["one"].received_ttls[2] != target
            or observations["two"].received_ttls[3] != target):
        raise RouterGroundRefused("different router topologies failed the same desired observation")
    native = ground.native_channel_observations()
    result = {
        "schema": SCHEMA + ".verified-report",
        "status": "actual_kernel_forwarding_with_independently_observed_router_headers",
        "ground_digest": ground.ground_digest,
        "evidence_digest": ground.evidence_digest,
        "observed_routes": [{
            "route": r.route_id, "hops": r.hops,
            "source_ttls": list(r.source_ttls), "received_ttls": list(r.received_ttls),
            "packet_bytes": r.packet_bytes, "raw_router_headers": r.router_captures,
            "valid_ipv4_checksums_observed": r.checksum_valid_frames,
            "evidence_digest": r.evidence_digest,
        } for r in ground.routes],
        "same_target_after_topology_change": {
            "target_received_ttl": target,
            "one_router": one_intent,
            "two_routers": two_intent,
            "real_receiver_one": observations["one"].received_ttls[2],
            "real_receiver_two": observations["two"].received_ttls[3],
        },
        "symbolic_ground_navigation": ground.navigate(80, 40),
        "native_e_cpu_channel_observations": [edge.to_dict() for edge in native],
        "native_e_cpu_observer_paths": native_paths,
        "scope": ground.scope,
        "actual_in_network_transition": "Linux IPv4 kernel forwarding decrements TTL; source and receiver Python do not",
        "native_capture": "Linux AF_PACKET ingress and egress, separate receiver IP_RECVTTL",
        "not_claimed": [
            "separate physical machines", "Internet-wide routing", "optical computation",
            "signed remote router identity", "arbitrary arithmetic in routers",
            "observed physical realization at symbolic 40-hop coordinate",
        ],
    }
    _write(output, result)
    return result


def main() -> None:
    """Mathematics: select one bounded owned-namespace sensing or verification operation."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--role", choices=("sender", "receiver", "router", "verify"), required=True)
    parser.add_argument("--source-ip")
    parser.add_argument("--destination-ip")
    parser.add_argument("--router-id")
    parser.add_argument("--ingress")
    parser.add_argument("--egress")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ready", type=Path)
    parser.add_argument("--input-dir", type=Path)
    parser.add_argument("--live-plan", type=Path)
    parser.add_argument("--live-key", type=Path)
    parser.add_argument("--live-receipt", type=Path)
    args = parser.parse_args()
    if not sys.platform.startswith("linux"):
        raise SystemExit("PATH-GROUND-004 real networking requires Linux")
    if args.role == "sender":
        send(args.source_ip, args.destination_ip, args.output)
    elif args.role == "receiver":
        receive(args.destination_ip, args.output, args.ready)
    elif args.role == "router":
        capture_router(
            args.router_id, args.ingress, args.egress,
            args.destination_ip, args.output, args.ready,
            live_plan=args.live_plan, live_key=args.live_key,
            live_receipt=args.live_receipt,
        )
    else:
        report = verify(args.input_dir, args.output)
        print(json.dumps({
            "ground_digest": report["ground_digest"], "evidence_digest": report["evidence_digest"],
            "status": report["status"], "one_router_target": 31, "two_router_target": 31,
        }, sort_keys=True))


if __name__ == "__main__":
    main()
