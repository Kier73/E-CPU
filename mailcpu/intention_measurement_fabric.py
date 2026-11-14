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
    """Mathematics: Require an already negotiated, mutually authenticated native socket."""
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
    """Mathematics: Reconstruct a canonical IOS-002 request without trusting sender claims."""
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
    if type(raw["subject"]) is not dict:
        raise SufficiencyRefused("measurement subject is invalid")
    RepresentationRef.from_dict(raw["subject"])
    tick = raw["scheduler"]
    if type(tick) is not dict or set(tick) != {"scheduler_id", "tick"}:
        raise SufficiencyRefused("measurement scheduler fields differ")
    SchedulerReading(tick["scheduler_id"], tick["tick"])
    if _fingerprint({key: value for key, value in raw.items() if key != "request_digest"}) != raw["request_digest"]:
        raise SufficiencyRefused("measurement request digest changed")
    return raw


@dataclass(frozen=True)
class HostedMeasurement:
    """Receiver-installed observer binding and live, receiver-owned policy gate.

    ``read`` receives only the correlation request. The private state is
    retained in a closure or local substrate; it must not be serialized.
    ``admit`` is a locally owned hook to the existing authority system, NOT
    a permission imported from a remote directory advertisement.
    """

    contract: ObserverContract
    model_digest: str
    authority_now: Callable[[], str]
    admit: Callable[[Mapping[str, Any], str], bool]
    read: Callable[[Mapping[str, Any]], Any]
    allowed_values: tuple[Any, ...]
    max_projection_bytes: int = 512

    def __post_init__(self) -> None:
        if not lsinstance(self.contract, ObserverContract):
            raise SufficiencyRefused("hosted measurement requires native observer contract")
        _hash(self.model_digest, "hosted model")
        if any(not callable(x) for x in (self.authority_now, self.admit, self.read)):
            raise SufficiencyRefused("measurement needs locally provisioned authority, admission and read")
        if type(self.allowed_values) is not tuple or not 1 <= len(self.allowed_values) <= 256:
            raise SufficiencyRefused("measurement allowed-value domain must be finite")
        if type(self.max_projection_bytes) is not int or not 1 <= self.max_projection_bytes <= 8192:
            raise SufficiencyRefused("measurement payload ceiling invalid")
        # Values are verified against a finite, locally declared feature domain.
        canon = tuple(_bytes(value) for value in self.allowed_values)
        if len(set(canon)) != len(canon) or any(len(item) > self.max_projection_bytes for item in canon):
            raise SufficiencyRefused("measurement domain duplicates or exceeds payload bound")


class MeasurementReceiptLedger:
    """Persist completed read-only measurements before channel acknowledgement.

    A restarted host reuses a stored receipt for an identical request, and
    rejects a conflicting request that reuses (challenge, feature). A crash
    *during* a read before commit may repeat a read: installed readers must
    be deterministic, side-effect-free observations.
    """

    def __init__(self, filename: str | Path) -> None:
        self._db = sqlite3.connect(str(filename), timeout=5, isolation_level=None)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=FULL")
        self._db.execute("CREATE TABLE IF NOT EXISTS measurement_completion ("
                         "challenge TEXT NOT NULL, feature TEXT NOT NULL, request TEXT NOT NULL, "
                         "response TEXT NOT NULL, PRIMARY KEY(challenge,feature))")

    def complete(self, request: Mapping[str, Any], create: Callable[[], dict[str, Any]]) -> dict[str, Any]:
        """Mathematics: Atomically store or return the one result bound to a challenge/feature."""
        challenge, feature, request_digest = (request[k] for k in
                                              ("challenge_digest", "feature_id", "request_digest"))
        self._db.execute("BEGIN IMMEDIATE")
        try:
            row = self._db.execute(
                "SELECT request,response FROM measurement_completion WHERE challenge=? AND feature=?",
                (challenge, feature),
            ).fetchone()
            if row is not None:
                if row[0] != request_digest:
                    raise SufficiencyRefused("reused measurement challenge with conflicting request")
                result = json.loads(row[1])
            else:
                result = create()
                encoded = _bytes(result).decode("utf-8")
                self._db.execute(
                    "INSERT INTO measurement_completion(challenge,feature,request,response) VALUES(?,?,?,?)",
                    (challenge, feature, request_digest, encoded),
                )
            self._db.execute("COMMIT")
            return result
        except BaseException:
            self._db.execute("ROLLBACK")
            raise

    def close(self) -> None:
        """Mathematics: Close the local durable completion ledger."""
        self._db.close()


class MeasurementPeerServer:
    """Serve bounded feature-only measurements on a verified peer TLS connection."""

    def __init__(self, transport: SocketTransport, local_peer_id: str, client_peer_id: str,
                 expected_client_dns: str, installed: Mapping[str, HostedMeasurement],
                 ledger: MeasurementReceiptLedger,
                 policy: ReliabilityPolicy | None = None) -> None:
        _bound_transport(transport, local_peer_id, client_peer_id, expected_client_dns)
        if type(installed) is not dict or not installed or any(
            type(feature) is not str or not isinstance(binding, HostedMeasurement)
            or binding.contract.observation.projection_id != feature
            for feature, binding in installed.items()
        ):
            raise SufficiencyRefused("measurement host binding catalogue invalid")
        if not isinstance(ledger, MeasurementReceiptLedger):
            raise SufficiencyRefused("measurement host requires durable local completion ledger")
        self.installed = dict(installed)
        self.transport = transport
        self.peer_id = local_peer_id
        self.client_id = client_peer_id
        self.ledger = ledger
        self.inbound = ReliableChannel(transport, local_peer_id, local_peer_id,
                                       REQUEST_CHANNEL, policy, peer=client_peer_id)
        self.outbound = ReliableChannel(transport, local_peer_id, client_peer_id,
                                        RESPONSE_CHANNEL, policy)
        self._last_tick = time.monotonic()

    @classmethod
    def accept_mutual_tls(cls, listener: Any, tls_context: ssl.SSLContext,
                          local_peer_id: str, client_peer_id: str, expected_client_dns: str,
                          installed: Mapping[str, HostedMeasurement], ledger: MeasurementReceiptLedger,
                          **kwargs: Any) -> "MeasurementPeerServer":
        """Mathematics: Accept only a CA-verified client with the configured DNS SAN."""
        transport = accept_mutual_tls(listener, local_peer_id, client_peer_id, tls_context,
                                      expected_peer_dns=expected_client_dns)
        try:
            return cls(transport, local_peer_id, client_peer_id, expected_client_dns,
                       installed, ledger, **kwargs)
        except BaseException:
            transport.close()
            raise

    def _respond(self, payload: Any) -> dict[str, Any]:
        """Mathematics: Apply receiver-local authority before returning a feature-only receipt."""
        raw = _parse_request(payload)
        feature = raw["feature_id"]
        installed = self.installed.get(feature)
        if installed is None:
            raise SufficiencyRefused("feature not installed on receiver-owned host")
        contract = installed.contract
        if (raw["model_digest"] != installed.model_digest
                or raw["contract_digest"] != contract.digest
                or raw["subject"] != contract.subject.to_dict()):
            raise SufficiencyRefused("request does not match admitted Ground or observer contract")
        if raw["authority_digest"] != installed.authority_now():
            raise SufficiencyRefused("measurement receiver authority changed")
        if installed.admit(raw, self.client_id) is not True:
            raise SufficiencyRefused("receiver Hypervisor/capability policy refused observation")

        def make_response() -> dict[str, Any]:
            """Mathematics: Read one permitted projection and bind it to the native contract."""
            value = installed.read(raw)
            if _bytes(value) not in tuple(_bytes(item) for item in installed.allowed_values):
                raise SufficiencyRefused("host measurement is outside permitted projection domain")
            if len(_bytes(value)) > installed.max_projection_bytes:
                raise SufficiencyRefused("host measurement exceeded byte ceiling")
            scheduler = SchedulerReading(raw["scheduler"]["scheduler_id"], raw["scheduler"]["tick"])
            receipt = ObserverReceipt.issue(
                contract, operation_id=feature, input_digest=raw["request_digest"],
                projection_value=value,
                time_frame=TemporalFrame(contract.observer_id, scheduler=scheduler),
            )
            return {"kind": RESPONSE_KIND, "provider_peer": self.peer_id,
                    "feature_id": feature, "request_digest": raw["request_digest"],
                    "receipt": receipt.to_dict()}

        response = self.ledger.complete(raw, make_response)
        # A durable completion is not an irrevocable capability. Recheck the
        # recovered native receipt against today's installed observer contract
        # and domain, even when the old request/challenge is byte-identical.
        if (type(response) is not dict
                or set(response) != {"kind", "provider_peer", "feature_id", "request_digest", "receipt"}
                or response["kind"] != RESPONSE_KIND
                or response["provider_peer"] != self.peer_id
                or response["feature_id"] != feature
                or response["request_digest"] != raw["request_digest"]):
            raise SufficiencyRefused("durable measurement response identity changed")
        try:
            receipt = ObserverReceipt.from_dict(response["receipt"])
        except (ValueError, TypeError, KeyError) as exc:
            raise SufficiencyRefused("durable native observer receipt is invalid") from exc
        scheduler = SchedulerReading(raw["scheduler"]["scheduler_id"], raw["scheduler"]["tick"])
        if (not verify_observer_receipt(contract, receipt)
                or receipt.operation_id != feature
                or receipt.input_digest != raw["request_digest"]
                or receipt.time_frame is None
                or receipt.time_frame.scheduler != scheduler
                or _bytes(receipt.projection) not in tuple(_bytes(item) for item in installed.allowed_values)):
            raise SufficiencyRefused("durable measurement no longer satisfies current observer admission")
        return response

    def service_once(self) -> bool:
        """Mathematics: Commit response to durable ledger before acknowledgement of request."""
        self.outbound.process_ack()
        if self.outbound.available_window < 1:
            self._tick_if_due()
            return False
        handled = False

        def commit(_sequence: int, payload: Any) -> None:
            """Mathematics: publish a correlated durable response before consuming and ACKing its request sequence."""
            nonlocal handled
            handled = True
            try:
                response = self._respond(payload)
            except (SufficiencyRefused, ValueError, TypeError, KeyError) as exc:
                # Refusal is an authenticated response, never a measurement.
                request_digest = ""
                if type(payload) is dict and type(payload.get("request")) is dict:
                    candidate = payload["request"].get("request_digest")
                    if type(candidate) is str and len(candidate) == 64:
                        request_digest = candidate
                response = {"kind": ERROR_KIND, "provider_peer": self.peer_id,
                            "request_digest": request_digest, "reason": str(exc)}
            self.outbound.send(response)

        received = self.inbound.receive(commit=commit)
        self._tick_if_due()
        return handled or received is not None

    def _tick_if_due(self) -> None:
        """Mathematics: advance the bounded reliable-response retry coordinate only after a finite monotonic interval."""
        now = time.monotonic()
        if now - self._last_tick >= 0.03:
            self.outbound.tick()
            self._last_tick = now

    def close(self) -> None:
        """Mathematics: release the owned transport or ledger resource without admitting a new operation."""
        self.transport.close()


class MeasurementPeerClient:
    """Resolve exactly the selected observations over one authenticated peer stream."""

    def __init__(self, transport: SocketTransport, local_peer_id: str,
                 provider_peer_id: str, expected_provider_dns: str,
                 timeout: float = 3.0, policy: ReliabilityPolicy | None = None) -> None:
        _bound_transport(transport, local_peer_id, provider_peer_id, expected_provider_dns)
        if type(timeout) not in (int, float) or not 0 < timeout <= 30:
            raise SufficiencyRefused("measurement timeout must be finite and positive")
        self.transport = transport
        self.peer_id = local_peer_id
        self.provider_id = provider_peer_id
        self.timeout = float(timeout)
        self.outbound = ReliableChannel(transport, local_peer_id, provider_peer_id,
                                        REQUEST_CHANNEL, policy)
        self.inbound = ReliableChannel(transport, local_peer_id, local_peer_id,
                                       RESPONSE_CHANNEL, policy, peer=provider_peer_id)

    @classmethod
    def connect_mutual_tls(cls, endpoint_host: str, port: int,
                           tls_context: ssl.SSLContext, local_peer_id: str,
                           provider_peer_id: str, expected_provider_dns: str,
                           **kwargs: Any) -> "MeasurementPeerClient":
        """Mathematics: Connect after certificate-chain verification and exact server DNS SAN match."""
        transport = connect_mutual_tls(
            endpoint_host, port, local_peer_id, provider_peer_id, tls_context,
            server_hostname=expected_provider_dns,
        )
        try:
            return cls(transport, local_peer_id, provider_peer_id,
                       expected_provider_dns, **kwargs)
        except BaseException:
            transport.close()
            raise

    def _exchange(self, request: Mapping[str, Any]) -> ObserverReceipt:
        """Mathematics: Exchange one digest-correlated native receipt over peer-authenticated channels."""
        self.outbound.process_ack()
        self.outbound.send({"kind": REQUEST_KIND, "request": dict(request)})
        deadline = time.monotonic() + self.timeout
        last_tick = time.monotonic()
        while time.monotonic() < deadline:
            self.outbound.process_ack()
            reply = self.inbound.receive()
            if reply is not None:
                _, result = reply
                if type(result) is not dict or result.get("provider_peer") != self.provider_id or \
                        result.get("request_digest") != request["request_digest"]:
                    raise SufficiencyRefused("authenticated reply is not correlated to this request")
                if result.get("kind") == ERROR_KIND:
                    raise SufficiencyRefused("measurement host refused: " + str(result.get("reason", "")))
                if set(result) != {"kind", "provider_peer", "feature_id", "request_digest", "receipt"} \
                        or result["kind"] != RESPONSE_KIND or result["feature_id"] != request["feature_id"]:
                    raise SufficiencyRefused("unexpected authenticated measurement reply")
                receipt = ObserverReceipt.from_dict(result["receipt"])
                return receipt
            now = time.monotonic()
            if now - last_tick >= 0.03:
                if self.outbound.tick():
                    raise SufficiencyRefused("measurement request retries exhausted")
                last_tick = now
            time.sleep(0.002)
        raise SufficiencyRefused("authenticated measurement timed out")

    def resolve(self, model: FiniteGround, public_value: Any,
                offers: Sequence[MeasurementCapability], authority_digest: str,
                plan: Mapping[str, Any], contracts: Mapping[str, ObserverContract],
                subject: RepresentationRef, scheduler: SchedulerReading,
                challenge_digest: str) -> tuple[dict[str, Any], dict[str, ObserverReceipt]]:
        """Mathematics: Accept only TLS-observed receipts, then invoke the native IOS-002 resolver.

        The trusted receipt admission callback is generated here from *this*
        mTLS session. Neither request contents nor a remote advertisement can
        supply it. The result is not a portable signature or a durable grant.
        """
        requests = issue_measurement_requests(
            model, public_value, offers, authority_digest, plan,
            contracts, subject, scheduler, challenge_digest,
        )
        receipts: dict[str, ObserverReceipt] = {}
        admitted: dict[str, str] = {}
        for request in requests:
            receipt = self._exchange(request)
            contract = contracts[request["feature_id"]]
            if (not verify_observer_receipt(contract, receipt)
                    or receipt.operation_id != request["feature_id"]
                    or receipt.input_digest != request["request_digest"]
                    or receipt.time_frame is None
                    or receipt.time_frame.scheduler != scheduler):
                raise SufficiencyRefused("authenticated receipt is not bound to requested observer context")
            receipts[request["feature_id"]] = receipt
            admitted[request["request_digest"]] = receipt.digest

        def receiver_admits(request: Mapping[str, Any], contract: ObserverContract,
                            evidence: ObserverReceipt) -> bool:
            """Mathematics: accept only the exact peer-observed receipt bound to the current request and observer contract."""
            return (admitted.get(request["request_digest"]) == evidence.digest
                    and evidence.contract_digest == contract.digest)

        result = resolve_observer_receipts(
            model, public_value, offers, authority_digest, plan, contracts,
            subject, scheduler, challenge_digest, receipts,
            receiver_verify=receiver_admits if requests else None,
        )
        return result, receipts

    def close(self) -> None:
        """Mathematics: release the owned transport or ledger resource without admitting a new operation."""
        self.transport.close()
