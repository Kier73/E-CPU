"""Mutual-TLS integration tests for the MailCPU framed socket transport."""

from __future__ import annotations

import shutil
import socket
import ssl
import subprocess
import threading
import time
from pathlib import Path

import pytest

from mailcpu import Message
from mailcpu.mtls_transport import (
    MutualTLSTransportError,
    accept_mutual_tls,
    connect_mutual_tls,
)
from mailcpu.socket_transport import SocketTransport


def _openssl(tmp_path: Path, *arguments: str) -> None:
    """Mathematics: execute one finite certificate-generation command and require exit status zero."""
    result = subprocess.run(
        ["openssl", *arguments],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise AssertionError(f"openssl failed: {result.stderr}")


def _make_test_certificates(tmp_path: Path) -> dict[str, Path]:
    """Mathematics: construct a test CA and two leaf certificates with disjoint DNS identities and opposite EKUs."""
    ca_key = tmp_path / "ca.key"
    ca_cert = tmp_path / "ca.pem"
    _openssl(
        tmp_path,
        "req", "-x509", "-newkey", "rsa:2048", "-nodes",
        "-keyout", str(ca_key), "-out", str(ca_cert),
        "-days", "30", "-sha256", "-subj", "/CN=MailCPU Test CA",
        "-addext", "basicConstraints=critical,CA:TRUE",
        "-addext", "keyUsage=critical,keyCertSign,cRLSign",
    )

    files: dict[str, Path] = {"ca": ca_cert}
    for role, dns_name, usage in (
        ("server", "worker-node", "clientAuth,serverAuth"),
        ("client", "client-node", "clientAuth,serverAuth"),
    ):
        key = tmp_path / f"{role}.key"
        csr = tmp_path / f"{role}.csr"
        certificate = tmp_path / f"{role}.pem"
        extensions = tmp_path / f"{role}.ext"
        _openssl(
            tmp_path,
            "req", "-new", "-newkey", "rsa:2048", "-nodes",
            "-keyout", str(key), "-out", str(csr),
            "-subj", f"/CN={dns_name}",
        )
        extensions.write_text(
            "\n".join(
                (
                    f"subjectAltName=DNS:{dns_name}",
                    f"extendedKeyUsage={usage}",
                    "basicConstraints=critical,CA:FALSE",
                    "keyUsage=critical,digitalSignature,keyEncipherment",
                )
            ) + "\n",
            encoding="utf-8",
        )
        _openssl(
            tmp_path,
            "x509", "-req", "-in", str(csr),
            "-CA", str(ca_cert), "-CAkey", str(ca_key), "-CAcreateserial",
            "-out", str(certificate), "-days", "30", "-sha256",
            "-extfile", str(extensions),
        )
        files[f"{role}_cert"] = certificate
        files[f"{role}_key"] = key
    return files


def _wait_for_message(transport: SocketTransport, address: str):
    """Mathematics: observe queue Q_address until it is nonempty or finite wall-time budget Δ expires."""
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        messages = transport.list(address)
        if messages:
            return messages[0]
        time.sleep(0.005)
    raise AssertionError(f"timed out waiting for mailbox {address!r}")



def _wait_for_ack(channel, expected: tuple[int, ...]) -> tuple[int, ...]:
    """Mathematics: observe ACK set A(t) until expected sequence set is acknowledged or finite deadline Δ expires."""
    deadline = time.monotonic() + 3.0
    observed: list[int] = []
    while time.monotonic() < deadline:
        observed.extend(channel.process_ack())
        if set(expected).issubset(observed):
            return tuple(observed)
        time.sleep(0.005)
    raise AssertionError(f"timed out waiting for acknowledgements {expected!r}; observed {tuple(observed)!r}")


@pytest.mark.skipif(shutil.which("openssl") is None, reason="OpenSSL CLI is required to create ephemeral test certificates")
def test_mutual_tls_authenticates_both_peers_and_carries_mailcpu_frames(tmp_path) -> None:
    """Mathematics: require CA trust and SAN identities in both directions before admitting the framed message relation."""
    certificates = _make_test_certificates(tmp_path)

    server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_context.minimum_version = ssl.TLSVersion.TLSv1_2
    server_context.load_cert_chain(
        str(certificates["server_cert"]),
        str(certificates["server_key"]),
    )
    server_context.load_verify_locations(cafile=str(certificates["ca"]))
    server_context.verify_mode = ssl.CERT_REQUIRED

    client_context = ssl.create_default_context(
        ssl.Purpose.SERVER_AUTH,
        cafile=str(certificates["ca"]),
    )
    client_context.minimum_version = ssl.TLSVersion.TLSv1_2
    client_context.load_cert_chain(
        str(certificates["client_cert"]),
        str(certificates["client_key"]),
    )

    listener = SocketTransport.listen("127.0.0.1", 0)
    server_result: dict[str, object] = {}
    server_errors: list[BaseException] = []

    def accept_peer() -> None:
        """Mathematics: accept exactly one peer only when its chain and DNS SAN authenticate as client-worker."""
        try:
            server_result["transport"] = accept_mutual_tls(
                listener,
                "worker",
                "client",
                server_context,
                expected_peer_dns="client-node",
            )
        except BaseException as exc:
            server_errors.append(exc)

    thread = threading.Thread(target=accept_peer, daemon=True)
    thread.start()
    client_transport: SocketTransport | None = None
    server_transport: SocketTransport | None = None
    try:
        client_transport = connect_mutual_tls(
            "127.0.0.1",
            listener.getsockname()[1],
            "client",
            "worker",
            client_context,
            server_hostname="worker-node",
        )
        thread.join(timeout=5.0)
        assert not thread.is_alive()
        assert not server_errors, repr(server_errors)
        server_transport = server_result["transport"]
        assert isinstance(server_transport, SocketTransport)
        assert isinstance(client_transport.socket, ssl.SSLSocket)
        assert isinstance(server_transport.socket, ssl.SSLSocket)
        assert client_transport.socket.version() in {"TLSv1.2", "TLSv1.3"}
        assert server_transport.socket.version() in {"TLSv1.2", "TLSv1.3"}

        sent = client_transport.send(
            "jobs",
            Message(sender="client", op="JOB", body=("bounded", 48)),
        )
        received = _wait_for_message(server_transport, "jobs")
        assert received == sent

        returned = server_transport.send(
            "results",
            Message(sender="worker", op="RESULT", body=("complete", 48)),
        )
        assert _wait_for_message(client_transport, "results") == returned
    finally:
        if client_transport is not None and not client_transport.closed:
            client_transport.close()
        if server_transport is not None and not server_transport.closed:
            server_transport.close()
        listener.close()
        thread.join(timeout=1.0)


def test_mutual_tls_rejects_client_context_without_peer_verification() -> None:
    """Mathematics: refuse connection setup for client context C with verify_mode(C) != CERT_REQUIRED."""
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    with pytest.raises(MutualTLSTransportError, match="CERT_REQUIRED"):
        connect_mutual_tls(
            "127.0.0.1",
            1,
            "client",
            "worker",
            context,
            server_hostname="localhost",
        )


def _server_context(cert: Path, key: Path, ca: Path) -> ssl.SSLContext:
    """Mathematics: create server context C_s with CA verification and mandatory client certificates."""
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(str(cert), str(key))
    context.load_verify_locations(cafile=str(ca))
    context.verify_mode = ssl.CERT_REQUIRED
    return context


def _client_context(cert: Path, key: Path, ca: Path) -> ssl.SSLContext:
    """Mathematics: create client context C_c with trusted CA, hostname validation, and an outbound client certificate."""
    context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=str(ca))
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(str(cert), str(key))
    return context


def _tls_pair(
    client_context: ssl.SSLContext,
    server_context: ssl.SSLContext,
    client_endpoint: str,
    server_endpoint: str,
    *,
    server_hostname: str,
    expected_client_dns: str,
) -> tuple[SocketTransport, SocketTransport]:
    """Mathematics: establish reciprocal stream adapters only after both client and server peer authentication succeed."""
    listener = SocketTransport.listen("127.0.0.1", 0)
    result: dict[str, object] = {}
    errors: list[BaseException] = []

    def accept_peer() -> None:
        """Mathematics: accept one TLS peer under expected identity expected_client_dns."""
        try:
            result["transport"] = accept_mutual_tls(
                listener,
                server_endpoint,
                client_endpoint,
                server_context,
                expected_peer_dns=expected_client_dns,
            )
        except BaseException as exc:
            errors.append(exc)

    thread = threading.Thread(target=accept_peer, daemon=True)
    thread.start()
    client: SocketTransport | None = None
    try:
        client = connect_mutual_tls(
            "127.0.0.1",
            listener.getsockname()[1],
            client_endpoint,
            server_endpoint,
            client_context,
            server_hostname=server_hostname,
        )
        thread.join(timeout=5.0)
        assert not thread.is_alive()
        assert not errors, repr(errors)
        server = result.get("transport")
        assert isinstance(server, SocketTransport)
        return client, server
    except Exception:
        if client is not None and not client.closed:
            client.close()
        raise
    finally:
        listener.close()
        thread.join(timeout=1.0)



def _wait_for_operation_result(channel):
    """Mathematics: observe reliable result FIFO R until the next typed result arrives or finite deadline Δ expires."""
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        result = channel.receive()
        if result is not None:
            return result
        time.sleep(0.005)
    raise AssertionError("timed out waiting for mutually authenticated operation result")


@pytest.mark.skipif(shutil.which("openssl") is None, reason="OpenSSL CLI is required to create ephemeral test certificates")
def test_transit_compute_operation_executes_over_mutual_tls(tmp_path) -> None:
    """Mathematics: authenticated operation path preserves receiver authorization, execution, result, and request/result ACKs."""
    from mailcpu import (
        Capability,
        HeadlessOS,
        HypervisorArbitrationEvent,
        HypervisorDomain,
        HypervisorOperationChannel,
        HypervisorOperationResultChannel,
        HypervisorPolicy,
        HypervisorRequest,
        ReliabilityPolicy,
        ReliableChannel,
        TransitComputeWorker,
    )

    certs = _make_test_certificates(tmp_path)
    worker_server = _server_context(certs["server_cert"], certs["server_key"], certs["ca"])
    client_client = _client_context(certs["client_cert"], certs["client_key"], certs["ca"])

    # One mutually authenticated full-duplex path carries both requests and results.
    client_transport, worker_transport = _tls_pair(
        client_client,
        worker_server,
        "client",
        "worker",
        server_hostname="worker-node",
        expected_client_dns="client-node",
    )

    policy = ReliabilityPolicy(lease_ticks=1, max_attempts=3, window_size=4)
    request_sender = HypervisorOperationChannel(
        ReliableChannel(client_transport, "client", "worker", "compute", policy)
    )
    request_receiver = HypervisorOperationChannel(
        ReliableChannel(worker_transport, "worker", "worker", "compute", policy, peer="client")
    )
    result_sender = HypervisorOperationResultChannel(
        ReliableChannel(worker_transport, "worker", "client", "compute.result", policy),
        "client",
        "compute",
    )
    result_receiver = HypervisorOperationResultChannel(
        ReliableChannel(client_transport, "client", "client", "compute.result", policy, peer="worker"),
        "client",
        "compute",
    )

    receiver = HeadlessOS()
    receiver.hypervisor.policy = HypervisorPolicy(
        review_confidence=0.0,
        automatic_confidence=0.0,
        destructive_confidence=0.0,
        danger_review_probability=1.0,
    )
    worker_pid = receiver.environment.kernel.spawn(
        "transit-compute-worker",
        capabilities=(Capability("/cpu/compute", frozenset({"execute"})),),
        parent_pid=receiver.environment.init_pid,
    )
    worker = TransitComputeWorker(receiver, worker_pid)

    event = HypervisorArbitrationEvent(
        "client",
        "compute",
        1,
        100,
        HypervisorRequest(
            "execute deterministic CPU arithmetic program",
            "/cpu/compute",
            {
                "source": "\n".join(
                    (
                        "set left 19",
                        "set right 23",
                        "add total left right",
                        "set offset 6",
                        "add result total offset",
                        "halt",
                    )
                ),
                "initial_registers": {},
                "max_ticks": 64,
            },
            frozenset({"execute"}),
            frozenset(),
        ),
    )

    try:
        assert request_sender.send(event) == 1
        served = worker.serve_once(request_receiver, result_sender)
        assert served is not None and served.executed is True
        assert served.action.value == "allow"
        returned = _wait_for_operation_result(result_receiver)
        assert returned is not None
        assert returned.effect == served.effect
        assert returned.effect["registers"]["result"] == 48
        assert _wait_for_ack(request_sender.channel, (1,)) == (1,)
        assert _wait_for_ack(result_sender.channel, (1,)) == (1,)

        # A fresh TLS-carried frame with the same semantic operation identity
        # must replay the stored result instead of launching another compute VM.
        assert request_sender.send(event) == 2
        replay = worker.serve_once(request_receiver, result_sender)
        assert replay is not None and replay.replayed is True
        replay_result = _wait_for_operation_result(result_receiver)
        assert replay_result is not None and replay_result.replayed is True
        assert replay_result.effect == served.effect
        assert _wait_for_ack(request_sender.channel, (2,)) == (2,)
        assert _wait_for_ack(result_sender.channel, (2,)) == (2,)
        assert receiver.environment.kernel.journal.verify()
    finally:
        for transport in (client_transport, worker_transport):
            if not transport.closed:
                transport.close()
