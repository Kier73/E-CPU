"""PATH-GROUND-006: preissue trusted local sensor plans, then verify live packet receipts.

'prepare' runs BEFORE the real packet experiment, issues separate test leaf
identities and fresh per-sensor challenges. It writes private keys only to
the caller's private temporary directory. The public trust manifest is
output separately so an independent auditor can inspect the certificates.
'verify' runs AFTER the real experiment with an independently held copy
of the preissued plans and original CA, and rejects post-hoc substituted
signed packets or changed receiver policy.
"""
from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import secrets

from cryptography import x509
from cryptography.hazmat.primitives import serialization

from mailcpu.ip_router_path_ground import (
    ROUTES, SCHEMA as IP_SCHEMA, TTL_PROBES,
    _digest, recognize_router_ttl_ground, verify_router_route,
)
from mailcpu.live_router_capture import (
    SCHEMA, ROUTE_ADDR, make_sensor_plan, verify_live_router_route,
)
from mailcpu.router_witness_auth import AuthenticatedRouterRefused
from mailcpu.semantic_translation import canonical_value_digest
from examples.run_authenticated_router_witness import issue_test_identities, SERVER_DNS

# Ground identity is a mathematical statement; the observation/evidence
# digest is not knowable until after packets actually traverse the route.
GROUND_SPEC = {
    "schema": IP_SCHEMA + ".mathematical-ground",
    "operator": "ipv4.forward.ttl_decrement",
    "domain": "unfragmented_ipv4_udp_valid_forwarded",
    "per_router": "ttl_out=ttl_in-1",
    "valid_incoming_ttl": [2, 255],
    "fixed_source_probe_set": list(TTL_PROBES),
}
GROUND_ID = _digest(GROUND_SPEC)


def _write(path: Path, value: dict) -> None:
    """Mathematics: preserve one exact finite JSON evidence manifest."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def prepare(private_dir: Path, public_dir: Path) -> dict:
    """Mathematics: preauthorize one observer and nonce per controlled router locus."""
    private_dir.mkdir(parents=True, exist_ok=True)
    public_dir.mkdir(parents=True, exist_ok=True)
    if private_dir.resolve() == public_dir.resolve():
        raise AuthenticatedRouterRefused("private sensor keys cannot enter public evidence directory")
    root = issue_test_identities(private_dir)
    policy_digest = canonical_value_digest({
        "schema": SCHEMA + ".receiver-acquisition-policy",
        "mode": "owned-runner-native-AF_PACKET",
        "ground_digest": GROUND_ID,
        "revision": 1,
        "capture": "observe-sign-before-persist",
    })
    plans = {}
    leaves = {}
    for route, sensors in ROUTES.items():
        if route not in ROUTE_ADDR:
            continue
        for sensor in sensors:
            nonce = secrets.token_hex(16)
            plan = make_sensor_plan(
                route_id=route, router_id=sensor,
                ground_digest=GROUND_ID,
                receiver_policy_digest=policy_digest,
                challenge=nonce, observer_dns=SERVER_DNS[sensor],
            )
            _write(private_dir / (sensor + ".plan.json"), plan)
            plans[sensor] = plan
            cert = x509.load_pem_x509_certificate(
                (private_dir / (sensor + ".pem")).read_bytes(),
            )
            leaves[sensor] = base64.b64encode(cert.public_bytes(
                serialization.Encoding.DER,
            )).decode("ascii")
    public = {
        "schema": SCHEMA + ".preissued-test-trust",
        "scope": "one_ephemeral_CA_one_runner_no_separate_administrators",
        "ground_digest": GROUND_ID,
        "receiver_policy_digest": policy_digest,
        "trusted_ca_pem": root.decode("ascii"),
        "plans": plans,
        "pinned_sensor_leaf_der_b64": leaves,
        "physical_independence_claimed": False,
    }
    _write(private_dir / "receiver-trust.json", public)
    _write(public_dir / "preissued-sensor-trust.json", public)
    return public


def verify(private_dir: Path, observations_dir: Path, output: Path) -> dict:
    """Mathematics: recheck real raw packets, live signed events and native E-CPU paths."""
    # Crucial: the receiver chooses this preissued trust manifest, NOT a
    # trust root supplied only by a self-authored sensor report.
    trust = json.loads((private_dir / "receiver-trust.json").read_text(encoding="utf-8"))
    if (trust["schema"] != SCHEMA + ".preissued-test-trust"
            or trust["ground_digest"] != GROUND_ID):
        raise AuthenticatedRouterRefused("preissued receiver trust was substituted")
    raw_by_route, route_observations = {}, {}
    for route, routers in ROUTES.items():
        src = json.loads((observations_dir / f"sender-{route}.json").read_text())
        dst = json.loads((observations_dir / f"receiver-{route}.json").read_text())
        captured = [
            json.loads((observations_dir / f"router-{route}-r{i + 1}.json").read_text())
            for i in range(len(routers))
        ]
        raw_by_route[route] = src, dst, captured
        route_observations[route] = verify_router_route(route, src, dst, captured)
    ground = recognize_router_ttl_ground(*(route_observations[r] for r in ROUTES))
    if ground.ground_digest != trust["ground_digest"]:
        raise AuthenticatedRouterRefused("observed kernel Ground differs from preissued law")
    used: set[str] = set()
    reports = {}
    for route, identities in ROUTES.items():
        src, dst, raw = raw_by_route[route]
        planned = [trust["plans"][ident] for ident in identities]
        sessions = [
            json.loads((observations_dir / f"live-{route}-r{i+1}.json").read_text())
            for i in range(len(identities))
        ]
        certs = {
            ident: base64.b64decode(
                trust["pinned_sensor_leaf_der_b64"][ident], validate=True,
            )
            for ident in identities
        }
        admission = lambda observed, expected=route_observations[route]: observed == expected
        reports[route] = verify_live_router_route(
            ground, route, src, dst, raw, planned, sessions, certs,
            trusted_ca_pem=trust["trusted_ca_pem"].encode("ascii"),
            receiver_policy_digest=trust["receiver_policy_digest"],
            used_challenges=used, admit_capture=admission,
            now=datetime.now(timezone.utc),
        )
    if len(used) != 4:
        raise AuthenticatedRouterRefused("signed capture did not account for all four active sensor identities")
    result = {
        "schema": SCHEMA + ".verification-report",
        "status": "capture_time_signatures_verified_against_raw_kernel_observations",
        "ground_digest": ground.ground_digest,
        "receiver_policy_digest": trust["receiver_policy_digest"],
        "sensor_count": len(used),
        "signed_packet_events": sum(
            sum(s["signed_events"] for s in x["sensors"]) for x in reports.values()
        ),
        "native_packet_paths_verified": sum(len(x["native_path_digests"]) for x in reports.values()),
        "route_results": reports,
        "physical_admin_independence": False,
        "trusted_evidence": "receiver_preissued_CA_and_plans_not_report_self_claims",
        "key_custody": "sensor-process-private-test-leaf_on_shared_kernel_runner",
        "not_proved": [
            "separately administered physical machines",
            "unforgeable packet acquisition timestamp",
            "attested hardware or independently operated network interface",
            "external PKI root",
        ],
    }
    _write(output, result)
    return result


def main() -> None:
    """Mathematics: choose the preissue or verify phase with explicit caller-controlled paths."""
    p = argparse.ArgumentParser(description=__doc__)
    modes = p.add_mutually_exclusive_group(required=True)
    modes.add_argument("--prepare", action="store_true")
    modes.add_argument("--verify", action="store_true")
    p.add_argument("--private-dir", type=Path, required=True)
    p.add_argument("--public-dir", type=Path)
    p.add_argument("--observations-dir", type=Path)
    p.add_argument("--output", type=Path)
    args = p.parse_args()
    if args.prepare:
        if args.public_dir is None:
            p.error("preissued public manifest directory is required")
        public = prepare(args.private_dir, args.public_dir)
        print(json.dumps({"sensor_count": len(public["plans"]),
                          "ground_digest": public["ground_digest"]}, sort_keys=True))
    else:
        if args.observations_dir is None or args.output is None:
            p.error("verification requires original raw observations and report output")
        report = verify(args.private_dir, args.observations_dir, args.output)
        print(json.dumps({
            "sensor_count": report["sensor_count"],
            "signed_packet_events": report["signed_packet_events"],
            "native_packet_paths": report["native_packet_paths_verified"],
        }, sort_keys=True))


if __name__ == "__main__":
    main()
