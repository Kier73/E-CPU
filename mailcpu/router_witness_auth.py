"""PATH-GROUND-005: authenticated packet observer-host receipts for native E-CPU paths.

This is an optional cryptographic adapter. It reuses E-CPU's existing
mutual-TLS socket transport, router Ground verifier and ObserverPath receipts.
The peer's mTLS certificate key signs a fresh, exact receiver-requested
capture commitment. Authentication establishes the credential that made the
claim; independently reconstructed raw packet evidence establishes its
mathematical consistency. Neither alone establishes an independent physical
sensor or host machine.

Requires the optional 'cryptography' package when invoked. The core E-CPU
installation and PATH-GROUND-004 do not import cryptography.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
import re
from typing import Any, Callable, Mapping, Sequence

from .ip_router_path_ground import (
    ROUTES, SCHEMA as IP_SCHEMA, ObservedRoute, RouterGroundRefused,
    RouterTTLGround, verify_router_route,
)
from .router_observer_path import (
    NativeRouterPathBinding, bind_router_packet_observer_path,
    verify_router_packet_path_binding,
)
from .semantic_translation import canonical_value_digest

SCHEMA = "mailcpu.path-ground-005.authenticated-capture.v1"
RECEIPT = SCHEMA + ".signed-receipt"
REQUEST = SCHEMA + ".request"
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_NONCE = re.compile(r"[0-9a-f]{32}\Z")
_ALLOWED = {locus for route in ROUTES.values() for locus in route}
_MAX_CAPTURE_BYTES = 128 * 1024


class AuthenticatedRouterRefused(RouterGroundRefused):
    """Reject an invalid credential, stale challenge or unverified claimed packet sensor."""


def _canonical(value: Any) -> bytes:
    """Mathematics: choose one injective finite JSON representation to sign or hash."""
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"),
            ensure_ascii=False, allow_nan=False,
        ).encode("utf-8")
    except (ValueError, TypeError, OverflowError) as exc:
        raise AuthenticatedRouterRefused("unsigned or noncanonical evidence") from exc


def _hash(value: Any) -> str:
    """Mathematics: content-identity of exact JSON; no authentication is inferred."""
    return sha256(_canonical(value)).hexdigest()


def _digest(value: Any, label: str) -> str:
    """Mathematics: admit only one exact SHA-256 lowercase hexadecimal identity."""
    if type(value) is not str or _HASH.fullmatch(value) is None:
        raise AuthenticatedRouterRefused(label + " is not an exact SHA-256 identity")
    return value


def _capture(capture: Any, router_id: str) -> dict[str, Any]:
    """Mathematics: allow one finite PATH-GROUND-004 raw capture with exact top-level shape."""
    if (type(capture) is not dict
            or set(capture) != {"schema", "router_id", "ingress_iface",
                                "egress_iface", "frames"}
            or capture["schema"] != IP_SCHEMA + ".router"
            or capture["router_id"] != router_id
            or type(capture["frames"]) is not list
            or len(capture["frames"]) != 12
            or len(_canonical(capture)) > _MAX_CAPTURE_BYTES):
        raise AuthenticatedRouterRefused("capture identity, shape or byte budget refused")
    return capture


def make_capture_request(
    *, route_id: str, router_id: str,
    ground_digest: str, route_evidence_digest: str,
    receiver_policy_digest: str, capture: Mapping[str, Any],
    challenge: str,
) -> dict[str, Any]:
    """Mathematics: bind one exact router, route, Ground and fresh challenge to source bytes."""
    if (type(route_id) is not str or route_id not in ROUTES
            or type(router_id) is not str or router_id not in ROUTES[route_id]
            or type(challenge) is not str or _NONCE.fullmatch(challenge) is None):
        raise AuthenticatedRouterRefused("capture request requires one approved route and 128-bit challenge")
    for label, value in (
        ("ground", ground_digest), ("route evidence", route_evidence_digest),
        ("receiver policy", receiver_policy_digest),
    ):
        _digest(value, label)
    candidate = _capture(capture, router_id)
    return {
        "schema": REQUEST,
        "route_id": route_id, "router_id": router_id,
        "ground_digest": ground_digest,
        "route_evidence_digest": route_evidence_digest,
        "receiver_policy_digest": receiver_policy_digest,
        "capture_digest": _hash(candidate),
        "challenge": challenge,
    }


def _validated_request(request: Any, capture: Any) -> dict[str, Any]:
    """Mathematics: verify the exact request contract against its claimed raw capture bytes."""
    if type(request) is not dict or set(request) != {
        "schema", "route_id", "router_id", "ground_digest",
        "route_evidence_digest", "receiver_policy_digest",
        "capture_digest", "challenge",
    } or request.get("schema") != REQUEST:
        raise AuthenticatedRouterRefused("unknown or incomplete capture request")
    expected = make_capture_request(
        route_id=request["route_id"], router_id=request["router_id"],
        ground_digest=request["ground_digest"],
        route_evidence_digest=request["route_evidence_digest"],
        receiver_policy_digest=request["receiver_policy_digest"],
        capture=capture, challenge=request["challenge"],
    )
    if request != expected:
        raise AuthenticatedRouterRefused("requested capture commitment does not match raw bytes")
    return expected


def signed_capture(private_key: Any, request: Mapping[str, Any],
                   capture: Mapping[str, Any], observer_dns: str) -> dict[str, Any]:
    """Mathematics: sign the exact receiver challenge and raw capture with an EC leaf key.

    The key is expected to be the very same P-256 key installed for the
    authenticated E-CPU TLS server session; its private bytes never enter
    an observation receipt.
    """
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    if (not isinstance(private_key, ec.EllipticCurvePrivateKey)
            or not isinstance(private_key.curve, ec.SECP256R1)):
        raise AuthenticatedRouterRefused("capture signer requires P-256 leaf credential")
    validated = _validated_request(dict(request), capture)
    if (type(observer_dns) is not str or not observer_dns.endswith(".pg5.invalid")
            or len(observer_dns) > 128):
        raise AuthenticatedRouterRefused("observer leaf DNS identity is invalid")
    payload = {
        "schema": RECEIPT,
        "request": validated,
        "request_digest": _hash(validated),
        "capture_digest": validated["capture_digest"],
        "observer_dns": observer_dns,
    }
    signature = private_key.sign(_canonical(payload), ec.ECDSA(hashes.SHA256()))
    return {"payload": payload, "signature_b64": base64.b64encode(signature).decode("ascii")}


def _trusted_leaf(
    ca_pem: bytes, peer_der: bytes, expected_dns: str, *,
    now: datetime,
) -> Any:
    """Mathematics: independently check exact CA, leaf chain, SAN, role and validity.

    The peer DER bytes MUST originate from a verified live mutual-TLS socket,
    not from the untrusted observation receipt being audited.
    """
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import ExtendedKeyUsageOID
    if (type(ca_pem) is not bytes or not ca_pem.startswith(b"-----BEGIN CERTIFICATE-----")
            or type(peer_der) is not bytes or not peer_der
            or type(expected_dns) is not str or not expected_dns.endswith(".pg5.invalid")
            or not isinstance(now, datetime) or now.tzinfo is None):
        raise AuthenticatedRouterRefused("trusted CA, live TLS peer, DNS or aware time is missing")
    try:
        ca = x509.load_pem_x509_certificate(ca_pem)
        leaf = x509.load_der_x509_certificate(peer_der)
        if (not isinstance(ca.public_key(), ec.EllipticCurvePublicKey)
                or not isinstance(ca.public_key().curve, ec.SECP256R1)
                or not isinstance(leaf.public_key(), ec.EllipticCurvePublicKey)
                or not isinstance(leaf.public_key().curve, ec.SECP256R1)
                or ca.subject != ca.issuer or leaf.issuer != ca.subject
                or ca.extensions.get_extension_for_class(x509.BasicConstraints).value.ca is not True
                or leaf.extensions.get_extension_for_class(x509.BasicConstraints).value.ca is not False):
            raise AuthenticatedRouterRefused("unsupported CA/leaf chain or issuer/role")
        ca.public_key().verify(
            ca.signature, ca.tbs_certificate_bytes, ec.ECDSA(ca.signature_hash_algorithm),
        )
        ca.public_key().verify(
            leaf.signature, leaf.tbs_certificate_bytes, ec.ECDSA(leaf.signature_hash_algorithm),
        )
        names = leaf.extensions.get_extension_for_class(
            x509.SubjectAlternativeName,
        ).value.get_values_for_type(x509.DNSName)
        if (names != [expected_dns]
                or ExtendedKeyUsageOID.SERVER_AUTH not in leaf.extensions.get_extension_for_class(
                    x509.ExtendedKeyUsage,
                ).value
                or not ca.not_valid_before_utc <= now <= ca.not_valid_after_utc
                or not leaf.not_valid_before_utc <= now <= leaf.not_valid_after_utc):
            raise AuthenticatedRouterRefused("peer SAN, TLS role or certificate validity refused")
    except AuthenticatedRouterRefused:
        raise
    except Exception as exc:
        raise AuthenticatedRouterRefused("pinned certificate signature or role invalid") from exc
    return leaf


@dataclass(frozen=True)
class AuthenticatedCapture:
    """A peer-key signed, mTLS-linked assertion over one raw capture and exact request."""

    router_id: str
    observer_dns: str
    challenge: str
    capture_digest: str
    peer_cert_sha256: str
    receipt_digest: str

    def __post_init__(self) -> None:
        """Mathematics: enforce one recognized router/claim identity and finite hashes."""
        if self.router_id not in _ALLOWED or type(self.observer_dns) is not str:
            raise AuthenticatedRouterRefused("unknown capture observer identity")
        if type(self.challenge) is not str or _NONCE.fullmatch(self.challenge) is None:
            raise AuthenticatedRouterRefused("invalid authenticated challenge")
        for value in (self.capture_digest, self.peer_cert_sha256, self.receipt_digest):
            _digest(value, "authenticated capture digest")


def verify_signed_capture(
    request: Mapping[str, Any],
    capture: Mapping[str, Any],
    envelope: Mapping[str, Any], *,
    trusted_ca_pem: bytes,
    live_tls_peer_der: bytes,
    expected_dns: str,
    now: datetime,
) -> AuthenticatedCapture:
    """Mathematics: check a signed request commitment with the actual live mTLS peer key.

    This only authenticates the observer credential and signed *claim*,
    not the physical truth of a supplied Ethernet capture.
    """
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    checked = _validated_request(dict(request), capture)
    if type(envelope) is not dict or set(envelope) != {"payload", "signature_b64"}:
        raise AuthenticatedRouterRefused("signed witness envelope is incomplete")
    payload = envelope["payload"]
    if type(payload) is not dict or set(payload) != {
        "schema", "request", "request_digest", "capture_digest", "observer_dns",
    } or payload != {
        "schema": RECEIPT,
        "request": checked,
        "request_digest": _hash(checked),
        "capture_digest": checked["capture_digest"],
        "observer_dns": expected_dns,
    }:
        raise AuthenticatedRouterRefused("signed observer request or identity was rebound")
    if type(envelope["signature_b64"]) is not str or len(envelope["signature_b64"]) > 256:
        raise AuthenticatedRouterRefused("signed witness signature shape refused")
    leaf = _trusted_leaf(trusted_ca_pem, live_tls_peer_der, expected_dns, now=now)
    try:
        signature = base64.b64decode(envelope["signature_b64"], validate=True)
        if not 64 <= len(signature) <= 80:
            raise AuthenticatedRouterRefused("invalid P-256 ECDSA signature extent")
        leaf.public_key().verify(signature, _canonical(payload), ec.ECDSA(hashes.SHA256()))
    except AuthenticatedRouterRefused:
        raise
    except Exception as exc:
        raise AuthenticatedRouterRefused("signed observation is not authentic to live peer") from exc
    return AuthenticatedCapture(
        checked["router_id"], expected_dns, checked["challenge"],
        checked["capture_digest"], sha256(live_tls_peer_der).hexdigest(),
        _hash(envelope),
    )


@dataclass(frozen=True)
class AuthenticatedRouterRoute:
    """A raw-verified route plus signed observer identities and native path witnesses."""

    observed: ObservedRoute
    captures: tuple[AuthenticatedCapture, ...]
    paths: tuple[NativeRouterPathBinding, ...]
    policy_digest: str

    def to_dict(self) -> dict[str, Any]:
        """Mathematics: serialize independently checkable evidence IDs without exporting keys."""
        return {
            "schema": SCHEMA + ".verified-route",
            "route_id": self.observed.route_id,
            "route_evidence_digest": self.observed.evidence_digest,
            "authenticated_captures": [
                {"router_id": x.router_id, "observer_dns": x.observer_dns,
                 "challenge": x.challenge, "capture_digest": x.capture_digest,
                 "peer_cert_sha256": x.peer_cert_sha256,
                 "receipt_digest": x.receipt_digest}
                for x in self.captures
            ],
            "native_path_digests": [x.verified.path_digest for x in self.paths],
            "receiver_policy_digest": self.policy_digest,
            "scope": "signed_test_leaf_assertions_plus_receiver_rechecked_raw_bytes",
            "not_proved": "independently_operated_physical_hosts_or_live_capture_provenance",
        }


def verify_authenticated_router_route(
    ground: RouterTTLGround, route_id: str,
    source: Mapping[str, Any], receiver: Mapping[str, Any],
    router_captures: Sequence[Mapping[str, Any]],
    requests: Sequence[Mapping[str, Any]],
    envelopes: Sequence[Mapping[str, Any]],
    tls_peer_der_by_router: Mapping[str, bytes],
    expected_dns_by_router: Mapping[str, str], *,
    trusted_ca_pem: bytes,
    receiver_policy_digest: str,
    used_challenges: set[str],
    admit_local_capture: Callable[[ObservedRoute], bool],
    now: datetime,
) -> AuthenticatedRouterRoute:
    """Mathematics: cryptographic provenance and original raw packets must independently agree.

    The only trusted origin for live_tls_peer_der is the already authenticated
    E-CPU TLS session. The receiver's local policy must still accept the
    reconstructed raw evidence, and all challenge nonces are consumed only
    after the *entire* route is verified, preventing partial success commits.
    """
    if (not isinstance(ground, RouterTTLGround)
            or type(route_id) is not str or route_id not in ROUTES
            or type(receiver_policy_digest) is not str
            or not isinstance(used_challenges, set)
            or not callable(admit_local_capture)):
        raise AuthenticatedRouterRefused("receiver Ground, policy or replay registry is missing")
    _digest(receiver_policy_digest, "receiver policy")
    ids = ROUTES[route_id]
    if (not isinstance(router_captures, (list, tuple))
            or not isinstance(requests, (list, tuple))
            or not isinstance(envelopes, (list, tuple))
            or (len(router_captures), len(requests), len(envelopes))
               != (len(ids), len(ids), len(ids))
            or set(tls_peer_der_by_router) != set(ids)
            or set(expected_dns_by_router) != set(ids)):
        raise AuthenticatedRouterRefused("missing or unrecognized signed observer route topology")
    observed = verify_router_route(route_id, source, receiver, router_captures)
    if (observed not in ground.routes or admit_local_capture(observed) is not True):
        raise AuthenticatedRouterRefused("receiver did not admit original raw route evidence")
    seen = set()
    attestations = []
    for ident, capture, request, receipt in zip(
        ids, router_captures, requests, envelopes, strict=True,
    ):
        if (type(request) is not dict
                or request.get("route_id") != route_id
                or request.get("router_id") != ident
                or request.get("ground_digest") != ground.ground_digest
                or request.get("route_evidence_digest") != observed.evidence_digest
                or request.get("receiver_policy_digest") != receiver_policy_digest):
            raise AuthenticatedRouterRefused("signed capture belongs to another Ground or policy")
        record = verify_signed_capture(
            request, capture, receipt,
            trusted_ca_pem=trusted_ca_pem,
            live_tls_peer_der=tls_peer_der_by_router[ident],
            expected_dns=expected_dns_by_router[ident], now=now,
        )
        if record.challenge in used_challenges or record.challenge in seen:
            raise AuthenticatedRouterRefused("replayed or duplicated observer challenge")
        seen.add(record.challenge)
        attestations.append(record)
    paths = tuple(
        bind_router_packet_observer_path(
            ground, route_id, seq, source, receiver, router_captures,
            admit_capture=admit_local_capture,
            receiver_policy_digest=receiver_policy_digest,
        )
        for seq in range(len(TTL_PROBES))
    )
    # Stronger than self-hashed statements: all actual raw witnesses must
    # reproduce the same native E-CPU Ground and receipt path under policy.
    for seq, bound in enumerate(paths):
        if not verify_router_packet_path_binding(
            bound, ground, route_id, seq, source, receiver, router_captures,
            admit_capture=admit_local_capture,
            receiver_policy_digest=receiver_policy_digest,
        ):
            raise AuthenticatedRouterRefused("native observer-path reconstruction did not verify")
    result = AuthenticatedRouterRoute(
        observed, tuple(attestations), paths, receiver_policy_digest,
    )
    used_challenges.update(seen)
    return result
