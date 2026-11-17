"""PATH-GROUND-005 authenticated observer receipts, raw packet and replay controls.

Synthetic packet fixtures prove strict verifier refusal and native E-CPU
integration only. The separate privileged Linux workflow is necessary to
claim a genuine observed in-network forwarding transition or live mTLS.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json

import pytest

pytest.importorskip("cryptography", minversion="42")
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from mailcpu.ip_router_path_ground import ROUTES, recognize_router_ttl_ground
from mailcpu.router_witness_auth import (
    AuthenticatedRouterRefused, make_capture_request,
    signed_capture, verify_authenticated_router_route,
    verify_signed_capture,
)
from mailcpu.semantic_translation import canonical_value_digest

# Reuse exactly the independently reconstructed PATH-GROUND-004 raw packet
# fixture; no second fake IP packet dialect is added for auth tests.
from test_ip_router_path_ground import _make, _verified


def _keys(identity="observer-one-r1.pg5.invalid", *, root=None, root_key=None):
    """Generate actual ECDSA P-256 test CA, leaf and strict SAN/EKU roles."""
    now = datetime.now(timezone.utc)
    if root is None:
        root_key = ec.generate_private_key(ec.SECP256R1())
        ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "PG5 local test root")])
        root = (x509.CertificateBuilder().subject_name(ca_name).issuer_name(ca_name)
                .public_key(root_key.public_key())
                .serial_number(x509.random_serial_number())
                .not_valid_before(now-timedelta(minutes=4))
                .not_valid_after(now+timedelta(hours=2))
                .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
                .sign(root_key, hashes.SHA256()))
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, identity)])
    leaf = (x509.CertificateBuilder().subject_name(name).issuer_name(root.subject)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now-timedelta(minutes=4))
            .not_valid_after(now+timedelta(hours=1))
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.SubjectAlternativeName([x509.DNSName(identity)]), critical=False)
            .add_extension(
                x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False,
            )
            .sign(root_key, hashes.SHA256()))
    return (
        key, leaf.public_bytes(serialization.Encoding.DER),
        root.public_bytes(serialization.Encoding.PEM),
        root, root_key,
    )


def _route(route="one", *, custom=None, seen=None):
    """Create one test receiver's exact signed requests over supplied raw captures."""
    ground = recognize_router_ttl_ground(*_verified())
    source, receiver, captures = _make(route)
    result = ground.routes[tuple(ROUTES).index(route)]
    policy = canonical_value_digest({"policy": "local-signature-test", "revision": 1})
    root, root_key = None, None
    requests, signed, peer_der, dns = [], [], {}, {}
    for idx, (router, capture) in enumerate(zip(ROUTES[route], captures, strict=True)):
        peer_name = "observer-" + router.replace(".", "-") + ".pg5.invalid"
        key, leaf, ca, root, root_key = _keys(
            peer_name, root=root, root_key=root_key,
        )
        challenge = f"{idx + 1:032x}"
        request = make_capture_request(
            route_id=route, router_id=router,
            ground_digest=ground.ground_digest,
            route_evidence_digest=result.evidence_digest,
            receiver_policy_digest=policy, capture=capture,
            challenge=challenge,
        )
        receipt = signed_capture(key, request, capture, peer_name)
        requests.append(request)
        signed.append(receipt)
        peer_der[router] = leaf
        dns[router] = peer_name
    if root is None:
        _, _, ca, _, _ = _keys()
    fixture = {
        "ground": ground, "route": route, "source": source,
        "receiver": receiver, "captures": captures,
        "requests": requests, "envelopes": signed,
        "certs": peer_der, "dns": dns, "ca": ca, "policy": policy,
        "used": set() if seen is None else seen,
        "admit": lambda candidate: candidate == result,
        "now": datetime.now(timezone.utc),
    }
    if custom:
        fixture.update(custom)
    return fixture


def _verify(f):
    """Run the complete existing native observer path and signed raw-receipt contract."""
    return verify_authenticated_router_route(
        f["ground"], f["route"], f["source"], f["receiver"],
        f["captures"], f["requests"], f["envelopes"],
        f["certs"], f["dns"],
        trusted_ca_pem=f["ca"], receiver_policy_digest=f["policy"],
        used_challenges=f["used"],
        admit_local_capture=f["admit"], now=f["now"],
    )


@pytest.mark.parametrize("route,signers", [
    ("direct", 0), ("bridge", 1), ("one", 1), ("two", 2),
])
def test_signed_observer_receipts_preserve_native_e_cpu_packet_paths(route, signers):
    """Authenticated observers establish key identity; raw bytes justify exact stage relation."""
    f = _route(route)
    accepted = _verify(f)
    assert len(accepted.captures) == signers
    assert len(accepted.paths) == 6
    assert len(f["used"]) == signers
    assert accepted.policy_digest == f["policy"]
    assert all(path.verified.ground == accepted.paths[0].verified.ground for path in accepted.paths)
    assert accepted.to_dict()["scope"] == "signed_test_leaf_assertions_plus_receiver_rechecked_raw_bytes"
    assert accepted.to_dict()["not_proved"] == "independently_operated_physical_hosts_or_live_capture_provenance"
    if signers:
        assert all(len(x.peer_cert_sha256) == 64 for x in accepted.captures)
    if route == "bridge":
        assert accepted.paths[2].stages[1].mode == "observe"
    if route in ("one", "two"):
        assert accepted.paths[2].stages[1].mode == "transform"


def test_same_ground_and_requested_observation_with_distinct_authenticated_routes():
    """The common mathematical Ground does not erase route-specific observer or certificate identities."""
    one = _verify(_route("one"))
    two = _verify(_route("two"))
    assert one.paths[2].destination_ttl == two.paths[3].destination_ttl == 31
    assert one.paths[2].ground_digest == two.paths[3].ground_digest
    assert one.observed.evidence_digest != two.observed.evidence_digest
    assert one.paths[2].verified.path_digest != two.paths[3].verified.path_digest


def test_signed_observer_request_does_not_allow_wrong_certificate_or_trust_root():
    """A signature by the wrong leaf key or a self-picked CA cannot authenticate a router."""
    f = _route("one")
    request, capture = f["requests"][0], f["captures"][0]
    actual_dns = f["dns"]["one.r1"]
    bogus_key, bogus_der, bogus_root, _, _ = _keys(actual_dns)
    wrong_signature = signed_capture(bogus_key, request, capture, actual_dns)
    f["envelopes"][0] = wrong_signature
    with pytest.raises(AuthenticatedRouterRefused, match="authentic"):
        _verify(f)
    f = _route("one")
    f["ca"] = bogus_root
    with pytest.raises(AuthenticatedRouterRefused, match="certificate|issuer|chain|pinned"):
        _verify(f)
    f = _route("one")
    f["certs"]["one.r1"] = bogus_der
    with pytest.raises(AuthenticatedRouterRefused, match="pinned|authentic|chain"):
        _verify(f)


def test_peer_dns_identity_is_mtls_bound_not_self_claimed_by_signed_payload():
    """A leaf from the right test CA but a different SAN is not the intended observer."""
    f = _route("one")
    f["dns"]["one.r1"] = "observer-two-r1.pg5.invalid"
    with pytest.raises(AuthenticatedRouterRefused, match="identity|SAN|rebound"):
        _verify(f)
    f = _route("one")
    f["envelopes"][0]["payload"]["observer_dns"] = "observer-two-r1.pg5.invalid"
    with pytest.raises(AuthenticatedRouterRefused, match="rebound"):
        _verify(f)


def test_exact_signed_ground_route_policy_and_challenge_cannot_be_substituted():
    """Even valid leaf signatures cannot reassign a witness to another receiver intention."""
    for kind in ("ground", "route", "policy", "nonce", "capture"):
        f = _route("one")
        if kind == "ground":
            f["requests"][0]["ground_digest"] = "f"*64
        elif kind == "route":
            f["requests"][0]["route_evidence_digest"] = "f"*64
        elif kind == "policy":
            f["policy"] = "f"*64
        elif kind == "nonce":
            f["requests"][0]["challenge"] = "f"*32
        else:
            f["captures"][0]["frames"][0]["raw_hex"] = "00"*40
        with pytest.raises((AuthenticatedRouterRefused, ValueError)):
            _verify(f)


def test_authenticated_replay_is_refused_only_after_a_complete_commit():
    """One accepted receipt cannot later satisfy a repeated observer challenge."""
    f = _route("two")
    _verify(f)
    assert f["used"] == {"0"*31+"1", "0"*31+"2"}
    with pytest.raises(AuthenticatedRouterRefused, match="replayed"):
        _verify(f)
    f = _route("two")
    f["envelopes"][1]["signature_b64"] = "AAAA"
    with pytest.raises(AuthenticatedRouterRefused):
        _verify(f)
    assert not f["used"]  # no half-committed certificate round


def test_two_router_host_identities_cannot_be_swapped_to_fake_one_path():
    """The capture and signer identities are distinct even on the same runner."""
    f = _route("two")
    f["certs"]["two.r1"], f["certs"]["two.r2"] = (
        f["certs"]["two.r2"], f["certs"]["two.r1"],
    )
    with pytest.raises(AuthenticatedRouterRefused):
        _verify(f)


def test_receiver_can_refuse_authentic_capture_for_local_policy_or_expiry():
    """A valid transport signature is never permission to admit a route."""
    f = _route("one")
    f["admit"] = lambda _: False
    with pytest.raises(AuthenticatedRouterRefused, match="receiver did not admit"):
        _verify(f)
    f = _route("one")
    f["now"] = datetime.now(timezone.utc) + timedelta(days=2)
    with pytest.raises(AuthenticatedRouterRefused, match="validity"):
        _verify(f)


def test_unauthorized_additional_capture_or_self_declared_router_is_refused():
    """No additional host or route stage can appear solely through a signed JSON field."""
    f = _route("one")
    f["captures"].append(f["captures"][0])
    with pytest.raises(AuthenticatedRouterRefused, match="topology"):
        _verify(f)
    f = _route("one")
    f["requests"][0]["router_id"] = "other.router"
    with pytest.raises(AuthenticatedRouterRefused, match="another Ground|approved route"):
        _verify(f)
    f = _route("one")
    f["envelopes"][0]["payload"]["future_operator"] = "read-private-mem"
    with pytest.raises(AuthenticatedRouterRefused, match="rebound"):
        _verify(f)


def test_malformed_challenge_and_response_are_refused_before_application_permission():
    """No unbounded, reflected, or injected peer request can impersonate an observer."""
    f = _route("one")
    capture = f["captures"][0]
    request = f["requests"][0]
    for nonce in ("abc", "\n"*32, "0"*64, 42, True):
        with pytest.raises(AuthenticatedRouterRefused, match="challenge"):
            make_capture_request(
                route_id="one", router_id="one.r1",
                ground_digest=f["ground"].ground_digest,
                route_evidence_digest=f["ground"].routes[2].evidence_digest,
                receiver_policy_digest=f["policy"], capture=capture,
                challenge=nonce,
            )
    f = _route("one")
    f["envelopes"][0]["signature_b64"] = "!!!!"
    with pytest.raises(AuthenticatedRouterRefused, match="authentic"):
        _verify(f)


@pytest.mark.parametrize("route", ["one", "bridge"])
def test_real_mailcpu_mutual_tls_process_authenticates_leaf_key_and_rejects_replay(
    tmp_path, route,
):
    """Real process/socket mTLS with SYNTHETIC raw packets; physical routing is separately tested.

    This avoids treating a cryptographic signing-only unit test as evidence
    that live MailCPU networking actually delivers authenticated receipts.
    """
    import os
    from pathlib import Path
    import subprocess
    import sys
    import time

    from examples.run_authenticated_router_witness import (
        SERVER_DNS, client_context, issue_test_identities,
        wire_read, wire_send,
    )
    from mailcpu.mtls_transport import connect_mutual_tls

    ground = recognize_router_ttl_ground(*_verified())
    source, receiver, captures = _make(route)
    router_id = ROUTES[route][0]
    observed = ground.routes[tuple(ROUTES).index(route)]
    policy = canonical_value_digest({"scenario": "synthetic-transport-only", "route": route})
    cert_dir = tmp_path / "keys"
    cert_dir.mkdir()
    root = issue_test_identities(cert_dir)
    capture = captures[0]
    capture_file = tmp_path / "raw-capture.json"
    capture_file.write_text(json.dumps(capture), encoding="utf-8")
    ready = tmp_path / "observer-ready.json"
    stdout = tmp_path / "observer.stdout"
    stderr = tmp_path / "observer.stderr"
    with stdout.open("w") as out, stderr.open("w") as err:
        proc = subprocess.Popen(
            [sys.executable, "-m", "examples.run_authenticated_router_witness",
             "--serve", router_id, "--capture-file", str(capture_file),
             "--cert-dir", str(cert_dir), "--ready", str(ready),
             "--ground", ground.ground_digest,
             "--route", observed.evidence_digest, "--policy", policy],
            stdout=out, stderr=err,
        )
    t = None
    try:
        deadline = time.monotonic() + 7
        while not ready.exists() and time.monotonic() < deadline:
            if proc.poll() is not None:
                raise AssertionError(
                    "authenticated observer terminated before listening: " + stderr.read_text()
                )
            time.sleep(0.02)
        assert ready.exists(), "signed test observer did not open an E-CPU network socket"
        port = json.loads(ready.read_text())["port"]
        t = connect_mutual_tls(
            "127.0.0.1", port, "coordinator", router_id,
            client_context(cert_dir),
            server_hostname=SERVER_DNS[router_id],
            timeout=4, handshake_timeout=4,
        )
        assert t.socket.version() in ("TLSv1.2", "TLSv1.3")
        actual_peer_der = t.socket.getpeercert(binary_form=True)
        actual_pinned = x509.load_pem_x509_certificate(
            (cert_dir / (router_id + ".pem")).read_bytes(),
        ).public_bytes(serialization.Encoding.DER)
        assert actual_peer_der == actual_pinned
        nonce = "f"*32
        request = make_capture_request(
            route_id=route, router_id=router_id, ground_digest=ground.ground_digest,
            route_evidence_digest=observed.evidence_digest,
            receiver_policy_digest=policy, capture=capture,
            challenge=nonce,
        )
        wire_send(t, router_id, "OBSERVE", request)
        result = wire_read(t, "RECEIPT")
        assert result["op"] == "RECEIPT"
        assert result["body"]["capture"] == capture
        assert verify_signed_capture(
            request, capture, result["body"]["envelope"],
            trusted_ca_pem=root, live_tls_peer_der=actual_peer_der,
            expected_dns=SERVER_DNS[router_id],
            now=datetime.now(timezone.utc),
        ).challenge == nonce
        wire_send(t, router_id, "OBSERVE", request)
        replay = wire_read(t, "REJECT")
        assert replay == {"op": "REJECT", "body": {"reason": "challenge-replay"}}
        wire_send(t, router_id, "CLOSE", {"done": True})
        assert wire_read(t, "CLOSED") == {"op": "CLOSED", "body": {"done": True}}
        wire_send(t, router_id, "BYE", {"done": True})
        assert proc.wait(timeout=5) == 0, stderr.read_text()
    finally:
        if t is not None:
            t.close()
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=4)


def test_received_certificate_claim_must_be_from_authenticated_tls_not_frame_metadata():
    """The signed frame cannot substitute a self-provided certificate for TLS peer identity."""
    f = _route("one")
    fake = _keys("observer-one-r1.pg5.invalid")[1]
    f["certs"]["one.r1"] = fake
    with pytest.raises(AuthenticatedRouterRefused):
        _verify(f)
