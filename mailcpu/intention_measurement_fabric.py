"""IOS-003: receiver-owned measurement RPC over the existing E-CPU mTLS fabric.

This is a narrow measurement service, not a new scheduling, admission, or
signature authority. Only preinstalled permitted observer functions may run.
Mutual TLS authenticates this *live stream*, not exported receipt files.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import sqlite3
import ssl
import time
from typing import Any, Callable, Mapping, Sequence

from .intention_sufficiency import (
    FiniteGround, MeasurementCapability, SufficiencyRefused, _bytes, _fingerprint, _hash,
)
from .intention_observer_bridge import issue_measurement_requests, resolve_observer_receipts
from .mtls_transport import accept_mutual_tls, connect_mutual_tls
from .observer_orbit import ObserverContract, ObserverReceipt, verify_observer_receipt
from .reliability import ReliableChannel, ReliabilityPolicy
from .semantic_translation import RepresentationRef
from .socket_transport import SocketTransport
from .temporal import SchedulerReading, TemporalFrame

REQUEST_CHANNEL = "intention.measurement.request.v1"
RESPONSE_CHANNEL = "intention.measurement.response.v1"
REQUEST_KIND = "mailcpu.intention.measurement.request.v1"
RESPONSE_KIND = "mailcpu.intention.measurement.response.v1"
ERROR_KIND = "mailcpu.intention.measurement.refused.v1"
_REQUEST_FIELDS = frozenset({
    "schema", "model_digest", "plan_digest", "authority_digest", "public_digest",
    "feature_id", "contract_digest", "subject", "scheduler", "challenge_digest",
    "request_digest",
})


def _bound_transport(transport: SocketTransport, local: str, peer: str,
                     expected_peer_dns: str) -> None:
    """Require an already negotiated, mutually authenticated native socket."""
    if (not isinstance(transport, SocketTransport)
            or transport.local_endpoint != local or transport.peer_endpoint != peer
            or not isinstance(transport.socket, ssl.SSLSocket)):
        raise SufficiencyRefused("measurement requires a pinned native TLS transport")
    sock = transport.socket
    if (sock.context.verify_mode != ssl.CERT_REQUIRED
            or sock.version() not in ("TLSv1.2", "TLSv1.3")
            or sock.cipher() is None):
        raise SufficiencyRefused("measurement stream lacks a mutually verified TLS handshake")
    certificate = sock.getpeercert()
    if not isinstance(certificate, dict) or ("DNS", expected_peer_dns) not in certificate.get("subjectAltName", ()):
        raise SufficiencyRefused("measurement peer certificate has the wrong DNS identity")


def _parse_request(payload: Any) -> dict[str, Any]:
    """Reconstruct a canonical IOS-002 request without trusting sender claims."""
    if type(payload) is not dict or set(payload) != {"kind", "request"} or payload["kind"] != REQUEST_KIND:
        raise SufficiencyRefused("unsupported measurement request envelope")
    raw = payload["request"]
    if type(raw) is not dict or set(raw) != _REQUEST_FIELDS:
        raise SufficiencyRefused("measurement request field set differs")
    if raw["schema"] != "mailcpu.intention-observer-bridge.v1.request":
        raise SufficiencyRefused("unknown measurement request schema")
    for field in ("model_digest", "plan_digest", "authority_digest", "public_digest",
                  "contract_digest", "challenge_digest", "request_digest"):
        _hash(raw[field], field)
    if type(raw["feature_id"]) is not str or not raw["feature_id"]:
        raise SufficiencyRefused("measurement feature identity missing")
