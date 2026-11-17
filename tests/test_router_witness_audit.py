"""Independent PATH-GROUND-005 auditor's packet decoder and fail-closed controls.

These are synthetic raw-frame negative tests only. The actual third-runner
certificate and packet audit consumes the privileged live experiment artifact.
"""
from __future__ import annotations

import json

import pytest

pytest.importorskip("cryptography", minversion="42")

from scripts.audit_authenticated_router_witness import (
    AuditRefused, audit, canonical, digest, packet, payload,
)
from test_ip_router_path_ground import _raw_ipv4_packet


def test_independent_decoder_reconstructs_ipv4_udp_without_importing_ecpu():
    """The auditor derives source/TTL/identity directly from raw Ethernet bytes."""
    raw = _raw_ipv4_packet(
        2, 33, source_ip="10.73.3.1", destination_ip="10.73.5.2",
        source_port=49117, dest_port=46831,
    )
    parsed = packet(raw.hex())
    assert parsed == {
        "seq": 2, "ttl": 33, "ipid": 2302,
        "src": "10.73.3.1", "dst": "10.73.5.2",
        "sport": 49117, "dport": 46831,
        "payload": payload(2).hex(),
    }


def test_independent_decoder_refuses_corrupted_payload_ethernet_header_or_extent():
    """Standalone auditor never upgrades a raw payload hash to an authoritative frame."""
    raw = _raw_ipv4_packet(
        0, 32, source_ip="10.73.1.1", destination_ip="10.73.2.2",
        source_port=49117, dest_port=46831,
    )
    for corrupt in (
        raw[:10], raw[:12]+b"\x08\x06"+raw[14:],
        raw[:-1]+bytes([raw[-1]^0x10]),
        raw[:14]+bytes([0x65])+raw[15:],
    ):
        with pytest.raises(AuditRefused):
            packet(corrupt.hex())
    with pytest.raises(AuditRefused):
        packet("malformed-not-hex")


def test_standalone_auditor_refuses_to_accept_producer_self_claimed_success(tmp_path):
    """A serialized success claim alone does not establish raw or signer evidence."""
    report = tmp_path/"claimed.json"
    report.write_text(json.dumps({
        "schema": "mailcpu.path-ground-005.authenticated-capture.v1.live-mtls-report",
        "status": "authenticated_live_mtls_capture_claims_and_native_packet_paths",
        "authenticated_observer_count": 4,
        "native_paths_verified": 24,
        "replay_refused": True,
        "transport": "actual_loopback_ECPU_mutual_TLS_SocketTransport",
        "routes": {"direct": {}, "bridge": {}, "one": {}, "two": {}},
        "ground_digest": "0"*64,
    }))
    with pytest.raises(AuditRefused, match="Ground"):
        audit(tmp_path, report)


def test_standalone_audit_uses_same_exact_canonical_sha256_for_any_key_order():
    """Receipt identity is deterministic across JSON ordering without trusting producer."""
    first = {"observation": {"ttl": 31, "sequence": 2}, "route": "one"}
    second = {"route": "one", "observation": {"sequence": 2, "ttl": 31}}
    assert canonical(first) == canonical(second)
    assert digest(first) == digest(second)
    assert digest(first) != digest({"route": "two", "observation": {"sequence": 2, "ttl": 31}})
