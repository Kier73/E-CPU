"""Independent PATH-GROUND-006 auditor positive and adversarial fixture regression.

These fixtures are SYNTHETIC raw Ethernet packets, not observed physical
forwarding. The auditor itself imports no mailcpu; this test only uses
mailcpu to create bounded fixture and native verification reports.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json

import pytest

pytest.importorskip("cryptography", minversion="42")
from cryptography import x509
from cryptography.hazmat.primitives import serialization

from examples.run_live_capture_ground import prepare
from mailcpu.ip_router_path_ground import ROUTES, recognize_router_ttl_ground
from mailcpu.live_router_capture import (
    CaptureTimeSigner, SCHEMA, verify_live_router_route,
)
from scripts.audit_live_capture_time import independently_audit
from scripts.audit_authenticated_router_witness import AuditRefused
from test_ip_router_path_ground import _make, _verified


def _record(path, value):
    """Write one raw synthetic experiment fixture or public JSON evidence artifact."""
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")


def _make_public_fixture(tmp_path):
    """Create all four exact synthetic routes and a truly signed public test artifact."""
    secret, public = tmp_path / "private", tmp_path / "public"
    trust = prepare(secret, public)
    ground = recognize_router_ttl_ground(*_verified())
    used = set()
    route_reports = {}
    for route, identities in ROUTES.items():
        src, dst, raw = _make(route)
        _record(public / f"sender-{route}.json", src)
        _record(public / f"receiver-{route}.json", dst)
        sensors = []
        for idx, ident in enumerate(identities):
            capture = raw[idx]
            _record(public / f"router-{route}-r{idx+1}.json", capture)
            key = serialization.load_pem_private_key(
                (secret / (ident + ".key")).read_bytes(), password=None,
            )
            signer = CaptureTimeSigner(trust["plans"][ident], key)
            for frame in capture["frames"]:
                signer.observe(
                    frame["side"], frame["interface"],
                    bytes.fromhex(frame["raw_hex"]),
                )
            session = signer.finalize(capture)
            _record(public / f"live-{route}-r{idx+1}.json", session)
            sensors.append(session)
        assert len(sensors) == len(identities)
        route_reports[route] = verify_live_router_route(
            ground, route, src, dst, raw,
            [trust["plans"][ident] for ident in identities], sensors,
            {
                ident: x509.load_pem_x509_certificate(
                    (secret / (ident + ".pem")).read_bytes(),
                ).public_bytes(serialization.Encoding.DER)
                for ident in identities
            },
            trusted_ca_pem=trust["trusted_ca_pem"].encode(),
            receiver_policy_digest=trust["receiver_policy_digest"],
            used_challenges=used,
            admit_capture=lambda actual: actual in ground.routes,
            now=datetime.now(timezone.utc),
        )
    assert len(used) == 4
    result = {
        "schema": SCHEMA + ".verification-report",
        "status": "capture_time_signatures_verified_against_raw_kernel_observations",
        "ground_digest": ground.ground_digest,
        "receiver_policy_digest": trust["receiver_policy_digest"],
        "sensor_count": 4, "signed_packet_events": 48,
        "native_packet_paths_verified": 24,
        "route_results": route_reports,
        "physical_admin_independence": False,
    }
    _record(public / "live-capture-verification.json", result)
    return public


def test_independent_auditor_reconstructs_complete_signed_synthetic_fixture(tmp_path):
    """The auditor checks all four raw transitions and four signed 12-event chains."""
    directory = _make_public_fixture(tmp_path)
    result = independently_audit(directory)
    assert result["signed_packet_events"] == 48
    assert result["separate_sensor_identities"] == 4
    assert result["native_packet_paths_reported"] == 24
    assert result["routes_checked"] == ["direct", "bridge", "one", "two"]


@pytest.mark.parametrize("attack", (
    "replace-frame", "rewrite-signature", "reorder-events",
    "wrong-cert", "rewrite-monotonic", "false-report",
    "replace-trust-policy",
))
def test_independent_auditor_does_not_trust_producer_or_public_signature_claim(tmp_path, attack):
    """Independent verifier must refuse tampered raw packets, signatures and report digests."""
    directory = _make_public_fixture(tmp_path)
    observed = directory / "live-one-r1.json"
    if attack in ("replace-frame", "rewrite-signature",
                  "reorder-events", "rewrite-monotonic"):
        source = directory / ("router-one-r1.json" if attack == "replace-frame"
                              else "live-one-r1.json")
        data = json.loads(source.read_text())
        if attack == "replace-frame":
            data["frames"][0]["raw_hex"] = "00"*55
        elif attack == "rewrite-signature":
            data["events"][0]["signature_b64"] = "AAAAAAAA"
        elif attack == "reorder-events":
            data["events"][0], data["events"][1] = data["events"][1], data["events"][0]
        else:
            data["events"][0]["body"]["observed_monotonic_ns"] = 0
        _record(source, data)
    elif attack == "wrong-cert":
        trust_file = directory / "preissued-sensor-trust.json"
        data = json.loads(trust_file.read_text())
        data["pinned_sensor_leaf_der_b64"]["one.r1"] = data["pinned_sensor_leaf_der_b64"]["two.r1"]
        _record(trust_file, data)
    elif attack == "false-report":
        source = directory / "live-capture-verification.json"
        data = json.loads(source.read_text())
        data["signed_packet_events"] = 49
        _record(source, data)
    else:
        source = directory / "preissued-sensor-trust.json"
        data = json.loads(source.read_text())
        data["receiver_policy_digest"] = "f"*64
        _record(source, data)
    with pytest.raises((AuditRefused, ValueError, KeyError)):
        independently_audit(directory)
