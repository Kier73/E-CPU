"""Independent E-CPU-free audit of public PATH-GROUND-006 live packet evidence.

Reuses the *independent* PATH-GROUND-005 raw IPv4 and public X.509 auditor,
not E-CPU/mailcpu itself. The receiver's root/plan are carried in the same
experiment artifact; cryptographic consistency can be checked independently,
but an external administrative trust root is NOT demonstrated here.
"""
from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from scripts.audit_authenticated_router_witness import (
    audit_certificates, audit_route, canonical, digest, packet, require,
    AuditRefused, IP_SCHEMA, ROUTES, TTL,
)

SCHEMA = "mailcpu.path-ground-006.capture-time.v1"
ROUTE_ADDR = {
    "bridge": ("10.73.6.1", "10.73.6.2"),
    "one": ("10.73.1.1", "10.73.2.2"),
    "two": ("10.73.3.1", "10.73.5.2"),
}


def _ecdsa(cert: x509.Certificate, body: dict, encoded: str) -> None:
    """Mathematics: verify signature of exactly the recorded finite JSON value."""
    try:
        signature = base64.b64decode(encoded, validate=True)
        cert.public_key().verify(
            signature, canonical(body), ec.ECDSA(hashes.SHA256()),
        )
    except Exception as exc:
        raise AuditRefused("signed capture-time event or seal has invalid ECDSA") from exc


def independently_audit(input_dir: Path) -> dict:
    """Mathematics: recompute packet, source, receiver, signer and full event chain."""
    trust = json.loads((input_dir / "preissued-sensor-trust.json").read_text())
    report = json.loads((input_dir / "live-capture-verification.json").read_text())
    require(
        trust.get("schema") == SCHEMA + ".preissued-test-trust"
        and trust.get("scope") == "one_ephemeral_CA_one_runner_no_separate_administrators"
        and trust.get("physical_independence_claimed") is False,
        "unrecognized receiver-issued trust artifact",
    )
    require(
        report.get("schema") == SCHEMA + ".verification-report"
        and report.get("status") == "capture_time_signatures_verified_against_raw_kernel_observations"
        and report.get("sensor_count") == 4
        and report.get("signed_packet_events") == 48
        and report.get("native_packet_paths_verified") == 24
        and report.get("physical_admin_independence") is False
        and set(report.get("route_results", {})) == set(ROUTES)
        and report.get("receiver_policy_digest") == trust["receiver_policy_digest"]
        and report.get("ground_digest") == trust["ground_digest"],
        "producer result is incomplete or unrecognized",
    )
    expected_ground = digest({
        "schema": IP_SCHEMA + ".mathematical-ground",
        "operator": "ipv4.forward.ttl_decrement",
        "domain": "unfragmented_ipv4_udp_valid_forwarded",
        "per_router": "ttl_out=ttl_in-1",
        "valid_incoming_ttl": [2, 255],
        "fixed_source_probe_set": list(TTL),
    })
    require(trust["ground_digest"] == expected_ground,
            "externally recomputed mathematical Ground does not agree")
    ids = {x for points in ROUTES.values() for x in points}
    require(
        set(trust["plans"]) == ids
        and set(trust["pinned_sensor_leaf_der_b64"]) == ids,
        "preissued sensor identities incomplete",
    )
    # Feed the existing independent auditor only public certificate data.
    # This is not a restatement of the E-CPU verifier, which remains uninstalled.
    leaf_pem = {}
    for ident, der in trust["pinned_sensor_leaf_der_b64"].items():
        try:
            cert = x509.load_der_x509_certificate(base64.b64decode(der, validate=True))
        except Exception as exc:
            raise AuditRefused("invalid pinned sensor public certificate bytes") from exc
        leaf_pem[ident] = cert.public_bytes(serialization.Encoding.PEM).decode()
    certs = audit_certificates({
        "trusted_ephemeral_root_ca_pem": trust["trusted_ca_pem"],
        "leaf_certificates_pem": leaf_pem,
    }, datetime.now(timezone.utc))
    raw_result = {"routes": report["route_results"]}
    raw = {route: audit_route(input_dir, route, raw_result) for route in ROUTES}
    used = set()
    counted = 0
    for route, router_ids in ROUTES.items():
        summary = report["route_results"][route]
        route_digest, captures = raw[route]
        require(
            summary.get("route_id") == route
            and summary.get("ground_digest") == expected_ground
            and summary.get("route_evidence_digest") == route_digest
            and summary.get("receiver_policy_digest") == trust["receiver_policy_digest"]
            and len(summary.get("native_path_digests", [])) == 6
            and summary.get("native_stage_modes") == {
                "direct": ["carrier", "observe"],
                "bridge": ["carrier", "observe", "carrier", "observe"],
                "one": ["carrier", "transform", "carrier", "observe"],
                "two": ["carrier", "transform", "carrier", "transform",
                        "carrier", "observe"],
            }[route]
            and len(summary.get("sensors", [])) == len(router_ids),
            "signed route's native packet evidence is not structurally complete",
        )
        for i, ident in enumerate(router_ids):
            captured = captures[i]
            session = json.loads((input_dir / f"live-{route}-r{i+1}.json").read_text())
            expected_plan = trust["plans"][ident]
            source, destination = ROUTE_ADDR[route]
            plan = {
                "schema": SCHEMA + ".plan", "route_id": route, "router_id": ident,
                "ingress_iface": "in", "egress_iface": "out",
                "source_ip": source, "destination_ip": destination,
                "destination_port": 46831,
                "ground_digest": expected_ground,
                "receiver_policy_digest": trust["receiver_policy_digest"],
                "observer_dns": "observer-" + ident.replace(".", "-") + ".pg5.invalid",
                "challenge": expected_plan["challenge"],
                "expected_frames": 12,
            }
            require(
                expected_plan == plan and session.get("schema") == SCHEMA + ".session"
                and session.get("plan") == plan
                and isinstance(plan["challenge"], str)
                and len(plan["challenge"]) == 32
                and all(c in "0123456789abcdef" for c in plan["challenge"])
                and plan["challenge"] not in used,
                "preissued sensor challenge, topology or acquisition plan changed",
            )
            used.add(plan["challenge"])
            require(len(session.get("events", [])) == len(captured["frames"]) == 12,
                    "signed observation chain dropped or added packets")
            prev_digest, prev_ns = "0" * 64, -1
            cert = certs[ident]
            for counter, (frame, signed) in enumerate(zip(
                captured["frames"], session["events"], strict=True,
            )):
                require(set(frame) == {"side", "interface", "raw_hex"}
                        and set(signed) == {"body", "signature_b64"},
                        "sensor packet record has missing or unexpected fields")
                raw_frame = bytes.fromhex(frame["raw_hex"])
                decoded = packet(frame["raw_hex"])
                require(
                    decoded["src"] == source
                    and decoded["dst"] == destination
                    and decoded["dport"] == 46831
                    and frame["side"] in ("ingress", "egress")
                    and frame["interface"] == ("in" if frame["side"] == "ingress" else "out"),
                    "sensor signed unrelated network or interface data",
                )
                body = signed["body"]
                timestamp = body.get("observed_monotonic_ns")
                expected_body = {
                    "schema": SCHEMA + ".event",
                    "plan_digest": digest(plan), "sequence": counter,
                    "side": frame["side"], "interface": frame["interface"],
                    "frame_sha256": sha256(raw_frame).hexdigest(),
                    "observed_monotonic_ns": timestamp,
                    "previous_signed_event_digest": prev_digest,
                }
                require(
                    body == expected_body
                    and type(timestamp) is int and timestamp > prev_ns,
                    "event sequence, monotonic clock or signed raw frame changed",
                )
                _ecdsa(cert, body, signed["signature_b64"])
                prev_digest = digest(signed)
                prev_ns = timestamp
            expected_seal = {
                "schema": SCHEMA + ".seal",
                "plan_digest": digest(plan),
                "frame_count": 12,
                "last_signed_event_digest": prev_digest,
                "capture_digest": digest(captured),
            }
            require(session["seal"]["body"] == expected_seal,
                    "sensor's signed final event commitment does not match capture")
            _ecdsa(cert, expected_seal, session["seal"]["signature_b64"])
            current = summary["sensors"][i]
            peer_digest = sha256(cert.public_bytes(serialization.Encoding.DER)).hexdigest()
            require(
                current == {
                    "router_id": ident,
                    "challenge": plan["challenge"],
                    "peer_cert_sha256": peer_digest,
                    "session_digest": digest(session),
                    "capture_digest": digest(captured),
                    "signed_events": 12,
                    "last_monotonic_ns": prev_ns,
                },
                "native receiver sensor attribution differs from independently signed evidence",
            )
            counted += 12
    require(len(used) == 4 and counted == 48,
            "the full independently signed observer-host set was not witnessed")
    return {
        "schema": SCHEMA + ".independent-audit",
        "result": "exact_raw_packet_transitions_and_capture_time_ECDSA_event_chains_verified",
        "ground_digest": expected_ground,
        "separate_sensor_identities": 4,
        "signed_packet_events": counted,
        "native_packet_paths_reported": 24,
        "routes_checked": list(ROUTES),
        "limitations": [
            "self-contained ephemeral CA is not an independently pinned external root",
            "monotonic timestamps and AF_PACKET provenance are sensor-local assertions",
            "one runner is not independently administered physical machines",
            "auditor does not reinstall E-CPU or independently reconstruct native stage hashes",
        ],
    }


def main() -> None:
    """Mathematics: independently audit one public sensor trace with no E-CPU imported."""
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input-dir", type=Path, required=True)
    args = p.parse_args()
    print(json.dumps(independently_audit(args.input_dir), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
