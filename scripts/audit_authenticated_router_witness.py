"""Independent, E-CPU-free audit of PATH-GROUND-005 public observer artifacts.

Uses only Python standard library and optional 'cryptography'; imports NO
mailcpu or VGI packages. Recomputes raw Ethernet/IPv4/UDP relations and
ECDSA leaf-key signatures, rather than trusting the producing E-CPU result.

The emitted test root is job-local and self-contained. This proves internal
cryptographic/semantic consistency, NOT independently pinned external PKI,
capture truth, independently owned physical hardware, or TLS transcript proof.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import base64
import ipaddress
import json
from pathlib import Path
import re

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID

SCHEMA = "mailcpu.path-ground-005.authenticated-capture.v1"
IP_SCHEMA = "mailcpu.path-ground-004.kernel-ipv4-hop.v1"
ROUTES = {
    "direct": (), "bridge": ("bridge.r1",),
    "one": ("one.r1",), "two": ("two.r1", "two.r2"),
}
STEPS = {"bridge.r1": 0, "one.r1": -1, "two.r1": -1, "two.r2": -1}
TTL = (4, 7, 32, 33, 64, 127)
HASH = re.compile(r"[a-f0-9]{64}\Z")
NONCE = re.compile(r"[a-f0-9]{32}\Z")
MAGIC = b"ECPU-PG4:"


class AuditRefused(ValueError):
    """One immutable source/packet/credential claim failed independent audit."""


def require(condition: bool, message: str) -> None:
    """Mathematics: admit a claim only when its independent predicate is exactly true."""
    if condition is not True:
        raise AuditRefused(message)


def canonical(value) -> bytes:
    """Mathematics: serialize exactly the signed finite JSON representation."""
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False,
    ).encode("utf-8")


def digest(value) -> str:
    """Mathematics: independent SHA-256 content address, not an authority token."""
    return sha256(canonical(value)).hexdigest()


def payload(seq: int) -> bytes:
    """Mathematics: reconstruct original finite packet stimulus without importing E-CPU."""
    prefix = MAGIC + seq.to_bytes(2, "big")
    return prefix + sha256(prefix).digest()[:4]


def packet(frame: str) -> dict:
    """Mathematics: parse actual recorded raw L2/L3 bytes independently of E-CPU."""
    require(type(frame) is str and len(frame) <= 4096, "raw frame byte budget")
    try:
        raw = bytes.fromhex(frame)
    except ValueError as exc:
        raise AuditRefused("raw frame is not hexadecimal") from exc
    require(14 + 20 + 8 <= len(raw) <= 2048 and raw[12:14] == b"\x08\x00",
            "raw Ethernet frame is not IPv4")
    ip = raw[14:]
    ihl = (ip[0] & 0x0f) * 4
    total = int.from_bytes(ip[2:4], "big")
    require((ip[0] >> 4) == 4 and ihl >= 20 and ihl + 8 <= total <= len(ip)
            and ip[9] == 17 and int.from_bytes(ip[6:8], "big") & 0x3fff == 0,
            "raw IP header invalid, fragmented or not UDP")
    datagram = ip[ihl:total]
    require(int.from_bytes(datagram[4:6], "big") == len(datagram),
            "UDP/IP declared length mismatch")
    body = datagram[8:]
    require(len(body) == len(MAGIC) + 6 and body.startswith(MAGIC),
            "raw packet does not contain exactly the admitted probe")
    seq = int.from_bytes(body[len(MAGIC):len(MAGIC) + 2], "big")
    require(seq in range(len(TTL)) and body == payload(seq),
            "raw probe identity or exact content differs")
    return {
        "seq": seq, "ttl": ip[8],
        "ipid": int.from_bytes(ip[4:6], "big"),
        "src": str(ipaddress.IPv4Address(ip[12:16])),
        "dst": str(ipaddress.IPv4Address(ip[16:20])),
        "sport": int.from_bytes(datagram[0:2], "big"),
        "dport": int.from_bytes(datagram[2:4], "big"),
        "payload": body.hex(),
    }


def audit_route(path: Path, route: str, report: dict) -> tuple[str, list[dict]]:
    """Mathematics: rederive one route's exact raw source, hops and receiver TTL relation."""
    ids = ROUTES[route]
    source = json.loads((path / f"sender-{route}.json").read_text())
    receiver = json.loads((path / f"receiver-{route}.json").read_text())
    routers = [
        json.loads((path / f"router-{route}-r{i + 1}.json").read_text())
        for i in range(len(ids))
    ]
    require(source.get("schema") == IP_SCHEMA+".sender"
            and receiver.get("schema") == IP_SCHEMA+".receiver"
            and len(source.get("frames", [])) == 6
            and len(receiver.get("frames", [])) == 6,
            "raw source and receiver witness incomplete")
    for seq, ttl in enumerate(TTL):
        src = source["frames"][seq]
        dst = receiver["frames"][seq]
        require(src == {"seq": seq, "sent_ttl": ttl,
                        "payload_hex": payload(seq).hex()},
                "source did not emit exact probe")
        require(type(dst["received_ttl"]) is int
                and dst["seq"] == seq
                and dst["received_ttl"] == ttl-sum(STEPS[r] == -1 for r in ids)
                and dst["source_ip"] == source["source_ip"]
                and dst["source_port"] == source["source_port"]
                and dst["payload_hex"] == src["payload_hex"],
                "raw receiver packet/TTL does not match source and claimed IP hops")
        previous_id = None
        prior_hops = 0
        for index, rtr in enumerate(routers):
            require(rtr.get("schema") == IP_SCHEMA+".router"
                    and rtr.get("router_id") == ids[index]
                    and rtr.get("ingress_iface") != rtr.get("egress_iface")
                    and len(rtr.get("frames", [])) == 12,
                    "intermediate raw capture identity or extent invalid")
            selected = [
                frame for frame in rtr["frames"]
                if isinstance(frame, dict)
                and frame.get("side") in ("ingress", "egress")
                and packet(frame["raw_hex"])["seq"] == seq
            ]
            require(len(selected) == 2 and {x["side"] for x in selected} == {
                "ingress", "egress",
            }, "router did not witness exactly one ingress and egress packet")
            x = {f["side"]: packet(f["raw_hex"]) for f in selected}
            for side, expected_iface in (
                ("ingress", rtr["ingress_iface"]),
                ("egress", rtr["egress_iface"]),
            ):
                require(next(f for f in selected if f["side"] == side)["interface"]
                        == expected_iface,
                        "captured packet was assigned a different interface")
            a, b = x["ingress"], x["egress"]
            require(a["ttl"] == ttl-prior_hops
                    and b["ttl"] - a["ttl"] == STEPS[ids[index]]
                    and a["ipid"] == b["ipid"]
                    and (previous_id is None or previous_id == a["ipid"]),
                    "observed intermediate in-path transition contradicted Ground")
            for item in (a, b):
                require(item["src"] == source["source_ip"]
                        and item["dst"] == source["destination_ip"]
                        and item["sport"] == source["source_port"]
                        and item["dport"] == source["destination_port"]
                        and item["payload"] == src["payload_hex"],
                        "router changed IP/UDP identity or exact payload")
            previous_id = b["ipid"]
            prior_hops -= STEPS[ids[index]]
    route_digest = digest({
        "schema": IP_SCHEMA+".route", "route": route,
        "sender": source, "receiver": receiver, "routers": routers,
    })
    require(report["routes"][route]["route_evidence_digest"] == route_digest,
            "receiver route digest disagrees with raw source and packet bytes")
    require(len(report["routes"][route]["native_path_digests"]) == 6
            and all(type(x) is str and HASH.fullmatch(x)
                    for x in report["routes"][route]["native_path_digests"]),
            "native packet path digest extent missing")
    return route_digest, routers


def audit_certificates(report: dict, now: datetime) -> dict[str, x509.Certificate]:
    """Mathematics: reconstruct the self-contained test CA and leaf signature chain."""
    try:
        root = x509.load_pem_x509_certificate(
            report["trusted_ephemeral_root_ca_pem"].encode(),
        )
        require(root.subject == root.issuer
                and root.extensions.get_extension_for_class(
                    x509.BasicConstraints,
                ).value.ca is True
                and isinstance(root.public_key(), ec.EllipticCurvePublicKey)
                and isinstance(root.public_key().curve, ec.SECP256R1)
                and root.not_valid_before_utc <= now <= root.not_valid_after_utc,
                "self-contained ephemeral root identity invalid")
        root.public_key().verify(
            root.signature, root.tbs_certificate_bytes,
            ec.ECDSA(root.signature_hash_algorithm),
        )
        result = {}
        for ident, pem in report["leaf_certificates_pem"].items():
            require(ident in {x for ids in ROUTES.values() for x in ids},
                    "unexpected observer certificate identity")
            dns = "observer-" + ident.replace(".", "-") + ".pg5.invalid"
            leaf = x509.load_pem_x509_certificate(pem.encode())
            root.public_key().verify(
                leaf.signature, leaf.tbs_certificate_bytes,
                ec.ECDSA(leaf.signature_hash_algorithm),
            )
            sans = leaf.extensions.get_extension_for_class(
                x509.SubjectAlternativeName,
            ).value.get_values_for_type(x509.DNSName)
            require(
                leaf.issuer == root.subject
                and sans == [dns]
                and leaf.extensions.get_extension_for_class(
                    x509.BasicConstraints,
                ).value.ca is False
                and ExtendedKeyUsageOID.SERVER_AUTH in leaf.extensions.get_extension_for_class(
                    x509.ExtendedKeyUsage,
                ).value
                and isinstance(leaf.public_key(), ec.EllipticCurvePublicKey)
                and isinstance(leaf.public_key().curve, ec.SECP256R1)
                and leaf.not_valid_before_utc <= now <= leaf.not_valid_after_utc,
                "observer leaf SAN, certificate scope, key or validity changed",
            )
            result[ident] = leaf
        require(len(result) == 4, "the four independently keyed observer roles are missing")
        return result
    except AuditRefused:
        raise
    except Exception as exc:
        raise AuditRefused("certificate chain or P-256 role cannot be independently verified") from exc


def audit(input_dir: Path, report_file: Path) -> dict:
    """Mathematics: verify all raw routes and signed observer claims without trusting E-CPU imports."""
    report = json.loads(report_file.read_text(encoding="utf-8"))
    require(report.get("schema") == SCHEMA+".live-mtls-report"
            and report.get("status") == "authenticated_live_mtls_capture_claims_and_native_packet_paths"
            and report.get("authenticated_observer_count") == 4
            and report.get("native_paths_verified") == 24
            and report.get("replay_refused") is True
            and report.get("transport") == "actual_loopback_ECPU_mutual_TLS_SocketTransport"
            and set(report.get("routes", {})) == set(ROUTES),
            "source report did not complete the exact authenticated experiment")
    expected_ground = digest({
        "schema": IP_SCHEMA+".mathematical-ground",
        "operator": "ipv4.forward.ttl_decrement",
        "domain": "unfragmented_ipv4_udp_valid_forwarded",
        "per_router": "ttl_out=ttl_in-1",
        "valid_incoming_ttl": [2, 255],
        "fixed_source_probe_set": list(TTL),
    })
    require(report["ground_digest"] == expected_ground,
            "reported Ground is not the independently reconstructed IPv4 Ground")
    root = audit_certificates(report, datetime.now(timezone.utc))
    raw = {}
    for route in ROUTES:
        raw[route] = audit_route(input_dir, route, report)
    require([len(report["routes"][r]["authenticated_captures"]) for r in ROUTES]
            == [0, 1, 1, 2], "one or more route-level observer coverage claims invalid")
    require(len(report["signed_receipts"]) == 4, "one or more observer signatures missing")
    seen_challenges = set()
    seen_routers = set()
    for entry in report["signed_receipts"]:
        route, router = entry["route"], entry["router_id"]
        require(route in ROUTES and router in ROUTES[route]
                and router not in seen_routers,
                "signed observer identity or route is duplicated or unexpected")
        seen_routers.add(router)
        request, envelope = entry["request"], entry["envelope"]
        receipt = envelope["payload"]
        index = ROUTES[route].index(router)
        capture = raw[route][1][index]
        expect = {
            "schema": SCHEMA+".request",
            "route_id": route,
            "router_id": router,
            "ground_digest": expected_ground,
            "route_evidence_digest": raw[route][0],
            "receiver_policy_digest": report["receiver_policy_digest"],
            "capture_digest": digest(capture),
            "challenge": request["challenge"],
        }
        require(request == expect
                and type(request["challenge"]) is str
                and NONCE.fullmatch(request["challenge"]) is not None
                and request["challenge"] not in seen_challenges,
                "signed request has changed Ground, raw bytes, policy or challenge")
        seen_challenges.add(request["challenge"])
        dns = "observer-" + router.replace(".", "-") + ".pg5.invalid"
        expected_payload = {
            "schema": SCHEMA+".signed-receipt", "request": request,
            "request_digest": digest(request),
            "capture_digest": digest(capture), "observer_dns": dns,
        }
        require(receipt == expected_payload,
                "signed observer receipt contains a rebinding or unauthorized field")
        cert = root[router]
        actual_cert_digest = sha256(cert.public_bytes(
            serialization.Encoding.DER,
        )).hexdigest()
        require(entry["leaf_der_sha256"] == actual_cert_digest,
                "reported live TLS peer DER identity differs from signer certificate")
        record = next(x for x in report["routes"][route]["authenticated_captures"]
                      if x["router_id"] == router)
        require(record["peer_cert_sha256"] == actual_cert_digest
                and record["challenge"] == request["challenge"]
                and record["capture_digest"] == digest(capture)
                and record["observer_dns"] == dns
                and record["receipt_digest"] == digest(envelope),
                "native route signer linkage diverged from signed packet witness")
        try:
            sig = base64.b64decode(envelope["signature_b64"], validate=True)
            cert.public_key().verify(
                sig, canonical(receipt), ec.ECDSA(hashes.SHA256()),
            )
        except Exception as exc:
            raise AuditRefused("independent public leaf-key receipt signature failed") from exc
    require(seen_routers == set(root), "authenticated router coverage incomplete")
    return {
        "schema": SCHEMA+".independent-audit",
        "result": "internally_consistent_raw_packets_and_four_cryptographic_claims",
        "ground_digest": expected_ground, "authenticated_observers": len(root),
        "routes_checked": list(ROUTES),
        "signed_raw_capture_receipts_checked": len(seen_routers),
        "reported_native_paths": report["native_paths_verified"],
        "limitations": [
            "test root came from the same job artifact, not independent operator PKI",
            "TLS handshake was reported by the producer, not independently observed by the auditor",
            "router sensor signing saved bytes does not independently authenticate hardware collection",
            "native E-CPU path digests are shape-checked, not recomputed by this standalone auditor",
        ],
    }


def main() -> None:
    """Mathematics: audit one completed, finite raw and signed artifact set offline."""
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input-dir", type=Path, required=True)
    p.add_argument("--report", type=Path, required=True)
    args = p.parse_args()
    print(json.dumps(audit(args.input_dir, args.report), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
