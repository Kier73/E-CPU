"""IOS-003 native reliable mTLS measurement and durable refusal tests."""

from __future__ import annotations

from dataclasses import replace
import shutil
import socket
import ssl
import subprocess
import threading
import time

import pytest

from mailcpu.intention_sufficiency import (
    FiniteGround, FiniteState, MeasurementCapability, SufficiencyRefused,
    plan_sufficiency,
)
from mailcpu.intention_measurement_fabric import (
    HostedMeasurement, MeasurementPeerClient, MeasurementPeerServer,
    MeasurementReceiptLedger, _parse_request,
)
from mailcpu.intention_observer_bridge import issue_measurement_requests
from mailcpu.observer_orbit import ObserverContract
from mailcpu.semantic_translation import ObservationContract, RepresentationRef, canonical_value_digest
from mailcpu.socket_transport import SocketTransport
from mailcpu.temporal import SchedulerReading

AUTH = canonical_value_digest({"receiver": "authority-epoch-8"})
CHALLENGE = canonical_value_digest({"nonce": "example-unique-challenge-008"})
SCHED = SchedulerReading("measurement-scheduler", 117)


def _setup(*, state=3):
    """Keep the hidden physical phase private to the installed host reader."""
    subject = RepresentationRef.from_payload("ios.subject", 1, {"domain": "four-phase"})
    ground = RepresentationRef.from_payload("ios.ground", 1, {"law": "identity-mod4"})
    context = canonical_value_digest({"session": "ios-003", "revision": 8})
    public = ObservationContract.from_definition("threshold", 1, {"projection": "phase//2"})
    target = ObservationContract.from_definition("parity-target", 1, {"projection": "phase%2"})
    projection = ObservationContract.from_definition("parity", 1, {"projection": "phase%2"})
    contract = ObserverContract("observer.parity", 1, subject, ground, projection, context)
    model = FiniteGround(
        ground.content_digest, public.projection_digest, target.projection_digest,
        context,
        tuple(FiniteState.create(str(i), i // 2, i % 2, {"parity": i % 2}) for i in range(4)),
    )
    offers = (MeasurementCapability("parity", contract.digest, contract.observer_id, 1),)
    plan = plan_sufficiency(model, state // 2, offers, AUTH)
    assert plan["status"] == "MEASURE"
    return model, state // 2, offers, plan, {"parity": contract}, subject


def _requests(state=3, *, challenge=CHALLENGE):
    model, public, offers, plan, contracts, subject = _setup(state=state)
    return issue_measurement_requests(model, public, offers, AUTH, plan,
                                      contracts, subject, SCHED, challenge)


def _installed(state=3, *, reads=None, admissions=None, authority=lambda: AUTH):
    model, public, offers, plan, contracts, subject = _setup(state=state)

    def admit(request, peer):
        if admissions is not None:
            admissions.append((request["request_digest"], peer))
        return peer == "receiver-a" and request["model_digest"] == model.digest

    def read(request):
        if reads is not None:
            reads.append(request["request_digest"])
        return state % 2

    return {"parity": HostedMeasurement(
        contracts["parity"], model.digest, authority, admit, read, (0, 1),
    )}


def test_native_request_canonical_digest_reconstruction_and_mutations():
    req = _requests()[0]
    assert _parse_request({"kind": "mailcpu.intention.measurement.request.v1", "request": req}) == req
    changed = {**req, "feature_id": "full-state"}
    with pytest.raises(SufficiencyRefused, match="digest changed"):
        _parse_request({"kind": "mailcpu.intention.measurement.request.v1", "request": changed})
    with pytest.raises(SufficiencyRefused, match="field set"):
        _parse_request({"kind": "mailcpu.intention.measurement.request.v1", "request": {**req, "private_phase": 3}})


def test_ledger_recovery_reuses_receipt_and_refuses_cross_request_challenge(tmp_path):
    filename = tmp_path / "measurement-authority.sqlite"
    req = _requests()[0]
    produced = []

    def produce():
        produced.append(1)
        return {"kind": "test", "receipt_digest": "a" * 64}

    ledger = MeasurementReceiptLedger(filename)
    first = ledger.complete(req, produce)
    second = ledger.complete(req, produce)
    assert first == second and len(produced) == 1
    ledger.close()
    recovered = MeasurementReceiptLedger(filename)
    assert recovered.complete(req, produce) == first and len(produced) == 1
    conflicted = {**req, "request_digest": "b" * 64}
    with pytest.raises(SufficiencyRefused, match="conflicting request"):
        recovered.complete(conflicted, produce)
    assert len(produced) == 1
    recovered.close()


def test_host_denies_changed_live_authority_without_read(tmp_path):
    """Receiver admission must be rechecked; no request/receipt may authorize itself."""
    from mailcpu.intention_measurement_fabric import MeasurementPeerServer
    reads = []
    host = object.__new__(MeasurementPeerServer)
    host.installed = _installed(reads=reads, authority=lambda: "d" * 64)
    host.peer_id = "provider-b"
    host.client_id = "receiver-a"
    host.ledger = MeasurementReceiptLedger(tmp_path / "auth.sqlite")
    with pytest.raises(SufficiencyRefused, match="authority changed"):
        host._respond({"kind": "mailcpu.intention.measurement.request.v1", "request": _requests()[0]})
    assert reads == []
    host.ledger.close()


def test_host_refuses_output_outside_feature_domain_before_commit(tmp_path):
    reads = []
    host = object.__new__(MeasurementPeerServer)
    model, public, offers, plan, contracts, subject = _setup()
    binding = _installed(reads=reads)["parity"]
    host.installed = {"parity": replace(binding, read=lambda request: {"hidden_state": 3})}
    host.peer_id = "provider-b"
    host.client_id = "receiver-a"
    host.ledger = MeasurementReceiptLedger(tmp_path / "invalid.sqlite")
    with pytest.raises(SufficiencyRefused, match="outside permitted projection"):
        host._respond({"kind": "mailcpu.intention.measurement.request.v1", "request": _requests()[0]})
    host.ledger.close()


def test_recovered_measurement_refuses_a_new_installed_projection_domain(tmp_path):
    """A matching durable challenge never overrides newly restricted local values."""
    model, public, offers, plan, contracts, subject = _setup(state=3)
    request = _requests()[0]
    reads = []
    host = object.__new__(MeasurementPeerServer)
    host.installed = _installed(state=3, reads=reads)
    host.peer_id = "provider-b"
    host.client_id = "receiver-a"
    host.ledger = MeasurementReceiptLedger(tmp_path / "value-revocation.sqlite")
    response = host._respond({"kind": "mailcpu.intention.measurement.request.v1", "request": request})
    assert len(reads) == 1 and response["feature_id"] == "parity"
    host.installed = {"parity": replace(host.installed["parity"], allowed_values=(0,))}
    with pytest.raises(SufficiencyRefused, match="no longer satisfies current observer admission"):
        host._respond({"kind": "mailcpu.intention.measurement.request.v1", "request": request})
    assert len(reads) == 1  # neither reread nor disclose stale result
    host.ledger.close()


@pytest.fixture
def tls_pair(tmp_path):
    """Real CA-verified client and server certificates with pinned peer SANs."""
    if shutil.which("openssl") is None:
        pytest.skip("openssl executable unavailable")

    def cmd(*args):
        p = subprocess.run(["openssl", *args], cwd=tmp_path, capture_output=True, text=True)
        if p.returncode:
            raise RuntimeError(p.stderr)

    ca_key, ca_cert = tmp_path / "ca.key", tmp_path / "ca.pem"
    cmd("req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", str(ca_key),
        "-out", str(ca_cert), "-days", "1", "-subj", "/CN=IOS Test CA",
        "-addext", "basicConstraints=critical,CA:TRUE",
        "-addext", "keyUsage=critical,keyCertSign,cRLSign")
    certs = {}
    for name, dns in (("provider", "provider-b.fabric.test"), ("receiver", "receiver-a.fabric.test")):
        key, csr, cert, ext = (tmp_path / f"{name}.{suffix}" for suffix in ("key", "csr", "pem", "ext"))
        cmd("req", "-new", "-newkey", "rsa:2048", "-nodes", "-keyout", str(key),
            "-out", str(csr), "-subj", f"/CN={dns}")
        ext.write_text(f"subjectAltName=DNS:{dns}\nextendedKeyUsage=clientAuth,serverAuth\n"
                       "basicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature,keyEncipherment\n")
        cmd("x509", "-req", "-in", str(csr), "-CA", str(ca_cert), "-CAkey", str(ca_key),
            "-CAcreateserial", "-out", str(cert), "-days", "1", "-extfile", str(ext))
        certs[name] = (cert, key)

    server = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server.minimum_version = ssl.TLSVersion.TLSv1_2
    server.load_cert_chain(*map(str, certs["provider"]))
    server.load_verify_locations(cafile=str(ca_cert))
    server.verify_mode = ssl.CERT_REQUIRED
    client = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=str(ca_cert))
    client.minimum_version = ssl.TLSVersion.TLSv1_2
    client.load_cert_chain(*map(str, certs["receiver"]))
    return server, client


def _run_live(tmp_path, tls_pair, *, state=3, read_counter=None, challenge=CHALLENGE):
    server_context, client_context = tls_pair
    listener = SocketTransport.listen("127.0.0.1", 0)
    listener.settimeout(5)
    host_error = []
    server_ready = threading.Event()
    stop = threading.Event()
    ledger_file = tmp_path / "provider-ledger.sqlite"

    def serve():
        ledger = MeasurementReceiptLedger(ledger_file)
        service = None
        try:
            service = MeasurementPeerServer.accept_mutual_tls(
                listener, server_context, "provider-b", "receiver-a",
                "receiver-a.fabric.test", _installed(state, reads=read_counter), ledger,
            )
            server_ready.set()
            while not stop.is_set() and not service.transport.closed:
                service.service_once()
                time.sleep(0.002)
        except Exception as exc:
            host_error.append(exc)
        finally:
            if service:
                service.close()
            ledger.close()

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    client = None
    try:
        model, public, offers, plan, contracts, subject = _setup(state=state)
        client = MeasurementPeerClient.connect_mutual_tls(
            "127.0.0.1", listener.getsockname()[1], client_context,
            "receiver-a", "provider-b", "provider-b.fabric.test", timeout=4.0,
        )
        assert server_ready.wait(4.0)
        report, receipts = client.resolve(model, public, offers, AUTH, plan,
                                          contracts, subject, SCHED, challenge)
        assert report["resolution"]["result"] == state % 2
        assert report["resolution"]["remaining_candidates"] == 1
        assert set(receipts) == {"parity"}
        assert set(report["measurement_receipts"][0]) == {
            "feature_id", "request_digest", "observer_contract_digest", "observer_receipt_digest",
        }
        # This returns a feature only, not receiver-private phase/state.
        assert "hidden_state" not in str(report) and "private_phase" not in str(receipts["parity"].to_dict())
        return report, receipts
    finally:
        if client:
            client.close()
        stop.set()
        thread.join(timeout=5)
        listener.close()
        if host_error:
            raise host_error[0]
        assert not thread.is_alive()


def test_native_mutual_tls_reliable_measurement_resolves_without_hidden_state(tmp_path, tls_pair):
    reads = []
    report, receipts = _run_live(tmp_path, tls_pair, read_counter=reads)
    assert len(reads) == 1
    assert report["measurement_receipts"][0]["observer_receipt_digest"] == receipts["parity"].digest


def test_reconnect_same_challenge_recovers_same_receipt_without_new_measurement(tmp_path, tls_pair):
    reads = []
    first, first_receipts = _run_live(tmp_path, tls_pair, read_counter=reads)
    second, second_receipts = _run_live(tmp_path, tls_pair, read_counter=reads)
    assert len(reads) == 1
    assert first_receipts["parity"].digest == second_receipts["parity"].digest
    assert first == second


def test_receiver_rejects_wrong_authenticated_peer_dns_before_read(tmp_path, tls_pair):
    server_context, client_context = tls_pair
    listener = SocketTransport.listen("127.0.0.1", 0)
    listener.settimeout(4)
    errors = []

    def server():
        with_ledger = MeasurementReceiptLedger(tmp_path / "wrong-peer.sqlite")
        try:
            MeasurementPeerServer.accept_mutual_tls(
                listener, server_context, "provider-b", "receiver-a",
                "wrong-client.fabric.test", _installed(), with_ledger,
            )
        except Exception as exc:
            errors.append(exc)
        finally:
            with_ledger.close()

    thread = threading.Thread(target=server, daemon=True)
    thread.start()
    client = None
    try:
        client = MeasurementPeerClient.connect_mutual_tls(
            "127.0.0.1", listener.getsockname()[1], client_context,
            "receiver-a", "provider-b", "provider-b.fabric.test", timeout=1.0,
        )
    except Exception:
        pass
    finally:
        if client:
            client.close()
        thread.join(timeout=5)
        listener.close()
    assert errors and not thread.is_alive()
