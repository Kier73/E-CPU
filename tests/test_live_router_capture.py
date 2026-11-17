"""PATH-GROUND-006 capture-time signing chain and native E-CPU admission tests.

Synthetic byte frames exercise mathematical and cryptographic validation.
Only the privileged Linux workflow can demonstrate that AF_PACKET actually
called the signer at real Ethernet acquisition time.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json

import pytest

pytest.importorskip("cryptography", minversion="42")
from cryptography import x509
from cryptography.hazmat.primitives import serialization

from examples.run_authenticated_router_witness import (
    SERVER_DNS, issue_test_identities,
)
from examples.run_live_capture_ground import GROUND_ID, prepare
from mailcpu.ip_router_path_ground import (
    ROUTES, recognize_router_ttl_ground,
)
from mailcpu.live_router_capture import (
    CaptureTimeRefused, CaptureTimeSigner, SCHEMA,
    make_sensor_plan, verify_capture_time_session, verify_live_router_route,
)
from mailcpu.semantic_translation import canonical_value_digest
from test_ip_router_path_ground import _make, _verified


def _setup(tmp_path, route="one"):
    """Prepare real distinct P-256 certs and 12 synthetic packet examples."""
    private = tmp_path / "secrets"
    private.mkdir()
    public = tmp_path / "public"
    public.mkdir()
    trust = prepare(private, public)
    assert trust["ground_digest"] == GROUND_ID
    src, dst, captured = _make(route)
    sessions = []
    for router, capture in zip(ROUTES[route], captured, strict=True):
        key = serialization.load_pem_private_key(
            (private / (router + ".key")).read_bytes(), password=None,
        )
        plan = trust["plans"][router]
        signer = CaptureTimeSigner(plan, key)
        # Unit test is synthetic; the real experiment calls the identical
        # signer from the Linux AF_PACKET recvfrom loop before persisting.
        for raw_frame in capture["frames"]:
            signer.observe(
                raw_frame["side"], raw_frame["interface"],
                bytes.fromhex(raw_frame["raw_hex"]),
            )
        sessions.append(signer.finalize(capture))
    return {
        "ground": recognize_router_ttl_ground(*_verified()),
        "route": route, "src": src, "dst": dst,
        "raw": captured, "sessions": sessions, "plans": [
            trust["plans"][name] for name in ROUTES[route]
        ],
        "trust": trust, "private": private,
        "pinned": {
            router: x509.load_pem_x509_certificate(
                (private / (router + ".pem")).read_bytes(),
            ).public_bytes(serialization.Encoding.DER)
            for router in ROUTES[route]
        },
        "used": set(),
    }


def _verify(f, *, used=None, admit=None):
    """Verify a complete finite router Ground with receiver-local policy."""
    return verify_live_router_route(
        f["ground"], f["route"], f["src"], f["dst"],
        f["raw"], f["plans"], f["sessions"], f["pinned"],
        trusted_ca_pem=f["trust"]["trusted_ca_pem"].encode("ascii"),
        receiver_policy_digest=f["trust"]["receiver_policy_digest"],
        used_challenges=f["used"] if used is None else used,
        admit_capture=(
            (lambda obs: obs in f["ground"].routes) if admit is None else admit
        ),
        now=datetime.now(timezone.utc),
    )


@pytest.mark.parametrize("route,signers,modes", [
    ("direct", 0, ["carrier", "observe"]),
    ("bridge", 1, ["carrier", "observe", "carrier", "observe"]),
    ("one", 1, ["carrier", "transform", "carrier", "observe"]),
    ("two", 2, ["carrier", "transform", "carrier", "transform", "carrier", "observe"]),
])
def test_capture_time_signed_sensor_and_native_observer_path(tmp_path, route, signers, modes):
    """Original raw evidence has independent per-event signatures and E-CPU native receipts."""
    f = _setup(tmp_path, route)
    result = _verify(f)
    assert len(result["sensors"]) == signers
    assert len(result["native_path_digests"]) == 6
    assert result["native_stage_modes"] == modes
    assert len(f["used"]) == signers
    assert all(r["signed_events"] == 12 for r in result["sensors"])
    assert result["scope"].startswith("observer_process_signs_at_AF_PACKET")
    for session in f["sessions"]:
        assert len(session["events"]) == 12
        assert session["events"][0]["body"]["previous_signed_event_digest"] == "0"*64
        assert session["events"][-1]["body"]["sequence"] == 11


def test_each_event_signature_is_bound_to_original_frame_and_preissued_challenge(tmp_path):
    """The receiver will not accept a replayed or merely re-hashed saved packet file."""
    f = _setup(tmp_path)
    p = f["plans"][0]
    cert = f["pinned"]["one.r1"]
    checked = verify_capture_time_session(
        p, f["raw"][0], f["sessions"][0],
        pinned_sensor_leaf_der=cert,
        trusted_ca_pem=f["trust"]["trusted_ca_pem"].encode("ascii"),
        now=datetime.now(timezone.utc),
    )
    assert checked.router_id == "one.r1"
    assert checked.challenge == p["challenge"]
    assert checked.signed_events == 12
    assert len(checked.peer_cert_sha256) == 64


@pytest.mark.parametrize("tamper", [
    "different-raw", "different-event-hash", "changed-monotonic",
    "swapped-events", "removed-event", "different-nonce",
    "different-signer", "wrong-interface", "changed-seal",
])
def test_capture_time_witness_tampering_refuses(tmp_path, tamper):
    """No signed packet chain can be spliced, reordered or rebound to a new identity."""
    f = _setup(tmp_path)
    if tamper == "different-raw":
        f["raw"][0]["frames"][1]["raw_hex"] = "00"*55
    elif tamper == "different-event-hash":
        f["sessions"][0]["events"][1]["body"]["frame_sha256"] = "a"*64
    elif tamper == "changed-monotonic":
        f["sessions"][0]["events"][1]["body"]["observed_monotonic_ns"] = 0
    elif tamper == "swapped-events":
        events = f["sessions"][0]["events"]
        events[0], events[1] = events[1], events[0]
    elif tamper == "removed-event":
        f["sessions"][0]["events"].pop()
    elif tamper == "different-nonce":
        f["plans"][0]["challenge"] = "f"*32
    elif tamper == "different-signer":
        # Wrong but otherwise valid CA-signed leaf key is never the
        # observer identity pinned in the route/plan.
        f["pinned"]["one.r1"] = x509.load_pem_x509_certificate(
            (f["private"] / "two.r1.pem").read_bytes(),
        ).public_bytes(serialization.Encoding.DER)
    elif tamper == "wrong-interface":
        f["raw"][0]["frames"][2]["interface"] = "fabricated"
    elif tamper == "changed-seal":
        f["sessions"][0]["seal"]["body"]["capture_digest"] = "0"*64
    with pytest.raises((CaptureTimeRefused, ValueError)):
        _verify(f)
    assert not f["used"]


def test_four_distinct_capture_sensors_commit_only_after_valid_route(tmp_path):
    """Two independent credential identities on a two-router path cannot be collapsed."""
    f = _setup(tmp_path, "two")
    outcome = _verify(f)
    assert len(outcome["sensors"]) == 2
    assert len({s["peer_cert_sha256"] for s in outcome["sensors"]}) == 2
    assert len({s["challenge"] for s in outcome["sensors"]}) == 2
    with pytest.raises(CaptureTimeRefused, match="replayed"):
        _verify(f)


def test_invalid_second_sensor_does_not_half_commit_first_challenge(tmp_path):
    """Atomic receiver admission prevents partial signature success on a route."""
    f = _setup(tmp_path, "two")
    f["sessions"][1]["events"][3]["signature_b64"] = "not-base64"
    with pytest.raises(CaptureTimeRefused):
        _verify(f)
    assert not f["used"]


def test_preissued_receiver_policy_can_refuse_perfectly_valid_signatures(tmp_path):
    """Crypto validity and permission to interpret the observation remain distinct."""
    f = _setup(tmp_path)
    with pytest.raises(CaptureTimeRefused, match="not admitted"):
        _verify(f, admit=lambda _: False)
    assert not f["used"]


def test_capture_time_signer_refuses_unrelated_packet_or_wrong_interface(tmp_path):
    """Observer code verifies the acquisition intention before signing a raw Ethernet frame."""
    f = _setup(tmp_path)
    sensor = "one.r1"
    key = serialization.load_pem_private_key(
        (f["private"]/(sensor + ".key")).read_bytes(), password=None,
    )
    signer = CaptureTimeSigner(f["plans"][0], key)
    record = f["raw"][0]["frames"][0]
    raw = bytes.fromhex(record["raw_hex"])
    with pytest.raises(CaptureTimeRefused):
        signer.observe("ingress", "not-its-interface", raw)
    with pytest.raises(CaptureTimeRefused):
        signer.observe("egress", "out", b"\x00"*64)
    assert signer.events == []


def test_capture_time_plan_is_issued_before_network_read_and_private_key_not_public(tmp_path):
    """The receiver's precommitted plan is not supplied by the sensor or result artifact."""
    f = _setup(tmp_path)
    root = tmp_path / "public"
    manifest = json.loads((root / "preissued-sensor-trust.json").read_text())
    assert set(manifest["plans"]) == {"bridge.r1", "one.r1", "two.r1", "two.r2"}
    assert manifest["physical_independence_claimed"] is False
    assert not list(root.rglob("*.key"))
    assert f["plans"][0]["challenge"] == manifest["plans"]["one.r1"]["challenge"]
