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
        ("server", "localhost", "serverAuth"),
        ("client", "client-worker", "clientAuth"),
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
                expected_peer_dns="client-worker",
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
            server_hostname="localhost",
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
