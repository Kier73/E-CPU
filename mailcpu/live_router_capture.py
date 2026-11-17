"""PATH-GROUND-006: sign each actual AF_PACKET observation at acquisition time.

The E-CPU observer process calls CaptureTimeSigner.observe() directly from
the AF_PACKET recv loop, before writing a saved trace. The receiver later
checks the exact signed event chain against raw Ethernet frames, a preissued
challenge and a separately supplied trusted certificate. The signer does
not operate the router: kernel IPv4 forwarding remains a distinct process.

This proves control of a signing credential at the reported observation
boundary, subject to trusted acquisition code and key custody. Signatures
and local monotonic readings cannot independently establish honest physical
sensing, separate hardware, or remotely administered identity.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
import re
import time
from typing import Any, Callable, Mapping, Sequence

from .ip_router_path_ground import (
    LOCUS_TTL_STEPS, ROUTES, SCHEMA as IP_SCHEMA, TTL_PROBES,
    RouterTTLGround, ObservedRoute, parse_ethernet_ipv4_udp,
    verify_router_route,
)
from .router_observer_path import (
    NativeRouterPathBinding, bind_router_packet_observer_path,
    verify_router_packet_path_binding,
)
from .router_witness_auth import (
    AuthenticatedRouterRefused, _canonical, _trusted_leaf,
)

SCHEMA = "mailcpu.path-ground-006.capture-time.v1"
EVENT = SCHEMA + ".event"
SEAL = SCHEMA + ".seal"
PLAN = SCHEMA + ".plan"
ROUTE_ADDR = {
    "bridge": ("10.73.6.1", "10.73.6.2"),
    "one": ("10.73.1.1", "10.73.2.2"),
    "two": ("10.73.3.1", "10.73.5.2"),
}
_RENONCE = re.compile(r"[0-9a-f]{32}\Z")
_HASH = re.compile(r"[0-9a-f]{64}\Z")
FRAME_BUDGET = 12


class CaptureTimeRefused(AuthenticatedRouterRefused):
    """One capture-time packet, sensor plan, key or receiver policy is not admitted."""


def _sha(obj: Any) -> str:
    """Mathematics: bind one finite JSON value without claiming physical trust."""
    return sha256(_canonical(obj)).hexdigest()


def _keys(value: Any, expected: set[str], label: str) -> Mapping[str, Any]:
    """Mathematics: forbid undocumented sensor/packet evidence coordinates."""
    if type(value) is not dict or set(value) != expected:
        raise CaptureTimeRefused(label + " has missing or unknown fields")
    return value


def make_sensor_plan(
    *, route_id: str, router_id: str, ground_digest: str,
    receiver_policy_digest: str, challenge: str,
    observer_dns: str,
) -> dict[str, Any]:
    """Mathematics: precommit a finite sensor's exact acquisition task and nonce."""
    if (type(route_id) is not str or route_id not in ROUTE_ADDR
            or type(router_id) is not str or router_id not in ROUTES[route_id]
            or type(challenge) is not str or not _RENONCE.fullmatch(challenge)
            or type(observer_dns) is not str
            or observer_dns != "observer-" + router_id.replace(".", "-") + ".pg5.invalid"
            or any(type(v) is not str or not _HASH.fullmatch(v)
                   for v in (ground_digest, receiver_policy_digest))):
        raise CaptureTimeRefused("sensor request has unrecognized route, identity or challenge")
    source_ip, destination_ip = ROUTE_ADDR[route_id]
    return {
        "schema": PLAN,
        "route_id": route_id, "router_id": router_id,
        "ingress_iface": "in", "egress_iface": "out",
        "source_ip": source_ip, "destination_ip": destination_ip,
        "destination_port": 46831,
        "ground_digest": ground_digest,
        "receiver_policy_digest": receiver_policy_digest,
        "observer_dns": observer_dns,
        "challenge": challenge,
        "expected_frames": FRAME_BUDGET,
    }


def _plan(plain: Any) -> dict[str, Any]:
    """Mathematics: recompute every admissible plan field before trusting any event."""
    x = _keys(plain, {
        "schema", "route_id", "router_id", "ingress_iface", "egress_iface",
        "source_ip", "destination_ip", "destination_port",
        "ground_digest", "receiver_policy_digest", "observer_dns",
        "challenge", "expected_frames",
    }, "sensor plan")
    expected = make_sensor_plan(
        route_id=x["route_id"], router_id=x["router_id"],
        ground_digest=x["ground_digest"],
        receiver_policy_digest=x["receiver_policy_digest"],
        observer_dns=x["observer_dns"], challenge=x["challenge"],
    )
    if dict(x) != expected:
        raise CaptureTimeRefused("sensor plan does not match its exact approved topology")
    return expected


def _packet(plan: Mapping[str, Any], side: str, interface: str, raw: bytes) -> None:
    """Mathematics: compare an actually observed Ethernet/IPv4/UDP frame to its plan."""
    if (type(side) is not str or side not in ("ingress", "egress")
            or interface != plan["ingress_iface" if side == "ingress" else "egress_iface"]
            or type(raw) is not bytes):
        raise CaptureTimeRefused("signed frame is not from an authorized sensor interface")
    frame = parse_ethernet_ipv4_udp(raw)
    if (frame["source_ip"] != plan["source_ip"]
            or frame["destination_ip"] != plan["destination_ip"]
            or frame["destination_port"] != plan["destination_port"]
            or frame["payload_hex"] == ""
            or frame["seq"] not in range(len(TTL_PROBES))):
        raise CaptureTimeRefused("signed packet did not match the preissued acquisition intention")


def _sign(key: Any, value: Mapping[str, Any]) -> str:
    """Mathematics: sign exact event content with the observer-owned P-256 private key."""
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    if (not isinstance(key, ec.EllipticCurvePrivateKey)
            or not isinstance(key.curve, ec.SECP256R1)):
        raise CaptureTimeRefused("sensor credential must be a P-256 private key")
    return base64.b64encode(
        key.sign(_canonical(dict(value)), ec.ECDSA(hashes.SHA256()))
    ).decode("ascii")


class CaptureTimeSigner:
    """One observer-local capture session; sign on each AF_PACKET recv event."""

    def __init__(self, plan: Mapping[str, Any], private_key: Any) -> None:
        """Mathematics: establish finite event state and preissued session identity."""
        self.plan = _plan(dict(plan))
        self.key = private_key
        # Validate signing capability before observing any packets.
        _sign(private_key, {"schema": SCHEMA + ".key-check", "plan_digest": _sha(self.plan)})
        self.events: list[dict[str, Any]] = []
        self.last_ns = -1

    def observe(self, side: str, interface: str, raw: bytes) -> None:
        """Mathematics: sign a monotonic linked receipt immediately after live recvfrom."""
        _packet(self.plan, side, interface, raw)
        if len(self.events) >= FRAME_BUDGET:
            raise CaptureTimeRefused("sensor has exceeded finite packet budget")
        reading = time.monotonic_ns()
        if reading <= self.last_ns:
            raise CaptureTimeRefused("sensor-local monotonic clock did not advance")
        self.last_ns = reading
        body = {
            "schema": EVENT, "plan_digest": _sha(self.plan),
            "sequence": len(self.events),
            "side": side, "interface": interface,
            "frame_sha256": sha256(raw).hexdigest(),
            "observed_monotonic_ns": reading,
            "previous_signed_event_digest": (
                _sha(self.events[-1]) if self.events else "0" * 64
            ),
        }
        self.events.append({"body": body, "signature_b64": _sign(self.key, body)})

    def finalize(self, capture: Mapping[str, Any]) -> dict[str, Any]:
        """Mathematics: seal the chain after requiring exact one-to-one raw frame correspondence."""
        if (len(self.events) != FRAME_BUDGET
                or capture.get("schema") != IP_SCHEMA + ".router"
                or capture.get("router_id") != self.plan["router_id"]
                or capture.get("ingress_iface") != self.plan["ingress_iface"]
                or capture.get("egress_iface") != self.plan["egress_iface"]
                or type(capture.get("frames")) is not list
                or len(capture["frames"]) != FRAME_BUDGET):
            raise CaptureTimeRefused("sensor does not have a complete matching raw capture")
        for entry, observed in zip(capture["frames"], self.events, strict=True):
            if (entry["side"] != observed["body"]["side"]
                    or entry["interface"] != observed["body"]["interface"]
                    or sha256(bytes.fromhex(entry["raw_hex"])).hexdigest()
                       != observed["body"]["frame_sha256"]):
                raise CaptureTimeRefused("raw trace and signed live event sequence differ")
        body = {
            "schema": SEAL, "plan_digest": _sha(self.plan),
            "frame_count": FRAME_BUDGET,
            "last_signed_event_digest": _sha(self.events[-1]),
            "capture_digest": _sha(dict(capture)),
        }
        return {
            "schema": SCHEMA + ".session",
            "plan": self.plan,
            "events": list(self.events),
            "seal": {"body": body, "signature_b64": _sign(self.key, body)},
        }


@dataclass(frozen=True)
class VerifiedLiveSensor:
    """Content-grounded sensor identity for one finite precommitted session."""

    router_id: str
    challenge: str
    peer_cert_sha256: str
    session_digest: str
    capture_digest: str
    signed_events: int
    last_monotonic_ns: int


def verify_capture_time_session(
    expected_plan: Mapping[str, Any],
    raw_capture: Mapping[str, Any],
    session: Mapping[str, Any], *,
    pinned_sensor_leaf_der: bytes,
    trusted_ca_pem: bytes,
    now: datetime,
) -> VerifiedLiveSensor:
    """Mathematics: verify every event against original raw bytes and an externally pinned leaf.

    The pinned sensor credential must come from the receiver's own
    enrollment policy, not from the sensor's signed session dictionary.
    """
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    plan = _plan(dict(expected_plan))
    x = _keys(session, {"schema", "plan", "events", "seal"}, "sensor session")
    if x["schema"] != SCHEMA + ".session" or x["plan"] != plan:
        raise CaptureTimeRefused("sensor changed its preissued acquisition plan")
    capture = _keys(raw_capture, {
        "schema", "router_id", "ingress_iface", "egress_iface", "frames",
    }, "raw capture")
    if (capture["schema"] != IP_SCHEMA + ".router"
            or capture["router_id"] != plan["router_id"]
            or capture["ingress_iface"] != plan["ingress_iface"]
            or capture["egress_iface"] != plan["egress_iface"]
            or type(capture["frames"]) is not list
            or len(capture["frames"]) != FRAME_BUDGET
            or type(x["events"]) is not list
            or len(x["events"]) != FRAME_BUDGET):
        raise CaptureTimeRefused("signed sensor path is missing exact raw frame evidence")
    leaf = _trusted_leaf(
        trusted_ca_pem, pinned_sensor_leaf_der,
        plan["observer_dns"], now=now,
    )
    prev_hash, prev_ns = "0" * 64, -1
    for counter, (raw_record, event) in enumerate(
        zip(capture["frames"], x["events"], strict=True),
    ):
        _keys(raw_record, {"side", "interface", "raw_hex"}, "raw frame")
        _keys(event, {"body", "signature_b64"}, "signed event")
        body = _keys(event["body"], {
            "schema", "plan_digest", "sequence", "side", "interface",
            "frame_sha256", "observed_monotonic_ns",
            "previous_signed_event_digest",
        }, "signed packet observation")
        if type(raw_record["raw_hex"]) is not str:
            raise CaptureTimeRefused("raw Ethernet hex body invalid")
        try:
            raw = bytes.fromhex(raw_record["raw_hex"])
        except ValueError as exc:
            raise CaptureTimeRefused("raw Ethernet bytes malformed") from exc
        _packet(plan, raw_record["side"], raw_record["interface"], raw)
        ns = body["observed_monotonic_ns"]
        if (body["schema"] != EVENT
                or body["plan_digest"] != _sha(plan)
                or type(body["sequence"]) is not int or body["sequence"] != counter
                or body["side"] != raw_record["side"]
                or body["interface"] != raw_record["interface"]
                or body["frame_sha256"] != sha256(raw).hexdigest()
                or body["previous_signed_event_digest"] != prev_hash
                or type(ns) is not int or ns <= prev_ns):
            raise CaptureTimeRefused("signed packet chain, content or sequence changed")
        _check_signature(leaf, body, event["signature_b64"])
        prev_hash = _sha(event)
        prev_ns = ns
    _keys(x["seal"], {"body", "signature_b64"}, "end-of-capture seal")
    expected_seal = {
        "schema": SEAL, "plan_digest": _sha(plan),
        "frame_count": FRAME_BUDGET,
        "last_signed_event_digest": prev_hash,
        "capture_digest": _sha(dict(capture)),
    }
    if x["seal"]["body"] != expected_seal:
        raise CaptureTimeRefused("capture-finalization seal disagrees with live signed bytes")
    _check_signature(leaf, expected_seal, x["seal"]["signature_b64"])
    return VerifiedLiveSensor(
        router_id=plan["router_id"], challenge=plan["challenge"],
        peer_cert_sha256=sha256(pinned_sensor_leaf_der).hexdigest(),
        session_digest=_sha(dict(session)), capture_digest=_sha(dict(capture)),
        signed_events=FRAME_BUDGET, last_monotonic_ns=prev_ns,
    )


def _check_signature(cert: Any, body: Mapping[str, Any], signature_b64: Any) -> None:
    """Mathematics: validate one exact P-256 ECDSA signed event or finalized session."""
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    if type(signature_b64) is not str or len(signature_b64) > 256:
        raise CaptureTimeRefused("signed sensor event has an invalid signature extent")
    try:
        sig = base64.b64decode(signature_b64, validate=True)
        cert.public_key().verify(sig, _canonical(dict(body)), ec.ECDSA(hashes.SHA256()))
    except Exception as exc:
        raise CaptureTimeRefused("capture-time observer signature invalid") from exc


def verify_live_router_route(
    ground: RouterTTLGround, route_id: str,
    source: Mapping[str, Any], receiver: Mapping[str, Any],
    raw_captures: Sequence[Mapping[str, Any]],
    plans: Sequence[Mapping[str, Any]], sessions: Sequence[Mapping[str, Any]],
    pinned_leaf_der: Mapping[str, bytes], *,
    trusted_ca_pem: bytes,
    receiver_policy_digest: str,
    used_challenges: set[str],
    admit_capture: Callable[[ObservedRoute], bool],
    now: datetime,
) -> dict[str, Any]:
    """Mathematics: admit raw, signed, authorized native paths atomically as one route."""
    if (not isinstance(ground, RouterTTLGround)
            or type(route_id) is not str or route_id not in ROUTES
            or not isinstance(used_challenges, set)
            or not callable(admit_capture)
            or type(receiver_policy_digest) is not str):
        raise CaptureTimeRefused("receiver-owned Ground and policy must be present")
    ids = ROUTES[route_id]
    if (len(raw_captures) != len(ids)
            or len(plans) != len(ids)
            or len(sessions) != len(ids)
            or set(pinned_leaf_der) != set(ids)):
        raise CaptureTimeRefused("incomplete sensor topology or unexpected certificate")
    observed = verify_router_route(route_id, source, receiver, raw_captures)
    if observed not in ground.routes or admit_capture(observed) is not True:
        raise CaptureTimeRefused("raw network relation was not admitted by receiver")
    sensors: list[VerifiedLiveSensor] = []
    local_challenges: set[str] = set()
    for router_id, capture, plan, session in zip(
        ids, raw_captures, plans, sessions, strict=True,
    ):
        if (plan.get("router_id") != router_id
                or plan.get("route_id") != route_id
                or plan.get("ground_digest") != ground.ground_digest
                or plan.get("receiver_policy_digest") != receiver_policy_digest):
            raise CaptureTimeRefused("sensor's signed intention differs from receiver Ground")
        witnessed = verify_capture_time_session(
            plan, capture, session,
            pinned_sensor_leaf_der=pinned_leaf_der[router_id],
            trusted_ca_pem=trusted_ca_pem, now=now,
        )
        if witnessed.challenge in used_challenges or witnessed.challenge in local_challenges:
            raise CaptureTimeRefused("sensor session challenge was replayed")
        local_challenges.add(witnessed.challenge)
        sensors.append(witnessed)
    paths: list[NativeRouterPathBinding] = []
    for seq in range(len(TTL_PROBES)):
        bound = bind_router_packet_observer_path(
            ground, route_id, seq, source, receiver, raw_captures,
            admit_capture=admit_capture, receiver_policy_digest=receiver_policy_digest,
        )
        if not verify_router_packet_path_binding(
            bound, ground, route_id, seq, source, receiver, raw_captures,
            admit_capture=admit_capture, receiver_policy_digest=receiver_policy_digest,
        ):
            raise CaptureTimeRefused("signed sensor route could not reconstruct native E-CPU path")
        paths.append(bound)
    # A failed sensor signature or native path NEVER half-consumes a challenge.
    used_challenges.update(local_challenges)
    return {
        "schema": SCHEMA + ".verified-route",
        "route_id": route_id, "ground_digest": ground.ground_digest,
        "route_evidence_digest": observed.evidence_digest,
        "receiver_policy_digest": receiver_policy_digest,
        "sensors": [
            {
                "router_id": r.router_id, "challenge": r.challenge,
                "peer_cert_sha256": r.peer_cert_sha256,
                "session_digest": r.session_digest,
                "capture_digest": r.capture_digest,
                "signed_events": r.signed_events,
                "last_monotonic_ns": r.last_monotonic_ns,
            } for r in sensors
        ],
        "native_path_digests": [p.verified.path_digest for p in paths],
        "scope": "observer_process_signs_at_AF_PACKET_receive_no_physical_independence_claim",
    }
