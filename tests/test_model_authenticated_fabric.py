"""USM-004 authenticating model/receiver in *different OS processes*.

These run real MailCPU mTLS sockets, ReliableChannel message/ACK framing,
structural-memory certification and a model-controlled syscall loop.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


pytestmark = pytest.mark.skipif(
    shutil.which("openssl") is None, reason="OpenSSL CLI required for temporary mutual TLS identities"
)


def openssl(root: Path, *args: str) -> None:
    process = subprocess.run(("openssl", *args), cwd=root, text=True,
                             capture_output=True, timeout=25, check=False)
    assert process.returncode == 0, process.stderr


def certs(root: Path) -> dict[str, Path]:
    ca = root / "ca.pem"
    ca_key = root / "ca.key"
    openssl(root, "req", "-x509", "-newkey", "rsa:2048", "-nodes",
            "-keyout", str(ca_key), "-out", str(ca),
            "-days", "3", "-sha256", "-subj", "/CN=ECPU Model Fabric Test",
            "-addext", "basicConstraints=critical,CA:TRUE",
            "-addext", "keyUsage=critical,keyCertSign,cRLSign")
    issued = {"ca": ca}
    for role, dns in (("receiver", "receiver-node"), ("model", "model-node"),
                      ("intruder", "other-node")):
        key, csr, cert, ext = (root / f"{role}.{suffix}" for suffix in ("key", "csr", "pem", "ext"))
        openssl(root, "req", "-newkey", "rsa:2048", "-nodes",
                "-keyout", str(key), "-out", str(csr), "-subj", f"/CN={dns}")
        ext.write_text(
            f"subjectAltName=DNS:{dns}\n"
            "extendedKeyUsage=clientAuth,serverAuth\n"
            "basicConstraints=critical,CA:FALSE\n"
            "keyUsage=critical,digitalSignature,keyEncipherment\n",
            encoding="utf-8"
        )
        openssl(root, "x509", "-req", "-in", str(csr),
                "-CA", str(ca), "-CAkey", str(ca_key), "-CAcreateserial",
                "-out", str(cert), "-days", "3", "-sha256", "-extfile", str(ext))
        issued[f"{role}_cert"] = cert
        issued[f"{role}_key"] = key
    return issued


def operate(
    root: Path,
    issued: dict[str, Path],
    *,
    kind: str = "affine",
    policy: str = "high-request",
    deny_admission: bool = False,
    client_role: str = "model",
):
    receiver_path = root / "receiver-report.json"
    model_path = root / "model-report.json"
    common = ("--ca", str(issued["ca"]), "--host", "127.0.0.1")
    receiver_cmd = (
        sys.executable, "-m", "examples.model_authenticated_fabric", "receiver", *common,
        "--cert", str(issued["receiver_cert"]), "--key", str(issued["receiver_key"]),
        "--source-kind", kind, "--source-seed", "201", "--policy", policy,
        "--output", str(receiver_path),
    ) + (("--deny-admission",) if deny_admission else ())
    receiver = subprocess.Popen(
        receiver_cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    try:
        assert receiver.stdout is not None
        ready = json.loads(receiver.stdout.readline())
        port = ready["ready_port"]
        assert port > 0
        model_cmd = (
            sys.executable, "-m", "examples.model_authenticated_fabric", "model", *common,
            "--cert", str(issued[f"{client_role}_cert"]),
            "--key", str(issued[f"{client_role}_key"]),
            "--port", str(port), "--output", str(model_path),
        )
        model = subprocess.run(model_cmd, capture_output=True, text=True,
                               timeout=28, check=False)
        out, err = receiver.communicate(timeout=28)
        return {
            "model_returncode": model.returncode,
            "model_stderr": model.stderr,
            "receiver_returncode": receiver.returncode,
            "receiver_stderr": err,
            "receiver_stdout": out,
            "receiver_report": json.loads(receiver_path.read_text()) if receiver_path.exists() else None,
            "model_report": json.loads(model_path.read_text()) if model_path.exists() else None,
        }
    finally:
        if receiver.poll() is None:
            receiver.kill()
            receiver.communicate(timeout=5)


@pytest.fixture(scope="module")
def temp_certificates(tmp_path_factory):
    root = tmp_path_factory.mktemp("usm004-certs")
    return certs(root)


def _assert_transport_completed(result):
    assert result["receiver_returncode"] == 0, result["receiver_stderr"]
    assert result["model_returncode"] == 0, result["model_stderr"]
    server = result["receiver_report"]
    model = result["model_report"]
    assert server["protocol"] == "mailcpu.model-fabric.v1"
    assert server["tls_version"] in ("TLSv1.2", "TLSv1.3")
    assert model["tls_version"] in ("TLSv1.2", "TLSv1.3")
    assert server["peer_dns_verified"] == "model-node"
    assert model["receiver_dns_verified"] == "receiver-node"
    assert server["receiver_process"] != model["model_process"]
    assert server["session"]["trace_digest"] == model["final"]["trace_digest"]
    assert len(server["exchanges"]) == model["requests_processed"]
    assert all(item["prompt_sequence"] == i and item["call_sequence"] == i
               for i, item in enumerate(server["exchanges"], start=1))
    return server


def test_model_operates_admitted_ground_over_real_mutual_tls(tmp_path, temp_certificates):
    result = operate(tmp_path, temp_certificates)
    report = _assert_transport_completed(result)
    assert report["status"] == "complete"
    assert [e["call"]["op"] for e in report["session"]["events"]] == [
        "observe", "propose", "read"
    ]
    assert report["session"]["events"][-1]["output"]["value"] == (
        7 + 201 + 5 * (10**12 + 137)
    ) % 97
    assert len(report["session"]["events"][-1]["output"]["read_receipt_id"]) == 64


def test_confident_remote_model_cannot_admit_nonlinear_source(tmp_path, temp_certificates):
    result = operate(tmp_path, temp_certificates, kind="nonlinear")
    report = _assert_transport_completed(result)
    assert report["status"] == "refused"
    assert [e["call"]["op"] for e in report["session"]["events"]] == ["observe", "propose"]
    assert report["session"]["events"][-1]["output"]["status"] == "refused_by_ecpu"


def test_model_can_defer_without_ground_effects(tmp_path, temp_certificates):
    result = operate(tmp_path, temp_certificates, policy="low-request")
    report = _assert_transport_completed(result)
    assert report["status"] == "deferred"
    assert [e["call"]["op"] for e in report["session"]["events"]] == ["observe", "stop"]


def test_remote_model_cannot_grant_receiver_admission(tmp_path, temp_certificates):
    result = operate(tmp_path, temp_certificates, deny_admission=True)
    report = _assert_transport_completed(result)
    assert report["status"] == "refused"
    assert report["session"]["events"][-1]["output"]["refusal"] == (
        "StructuralMemoryAuthorizationError"
    )


def test_trained_model_operates_over_authenticated_fabric_without_override(
    tmp_path, temp_certificates
):
    result = operate(tmp_path, temp_certificates, policy="trained")
    report = _assert_transport_completed(result)
    assert report["status"] in {"complete", "refused", "deferred"}
    operations = [item["call"]["op"] for item in report["session"]["events"]]
    assert operations[0] == "observe"
    assert operations[1] in {"propose", "stop"}
    if report["status"] == "complete":
        assert report["session"]["events"][-1]["output"]["value"] == (
            7 + 201 + 5 * (10**12 + 137)
        ) % 97


def test_wrong_peer_certificate_identity_never_reaches_ground(tmp_path, temp_certificates):
    result = operate(tmp_path, temp_certificates, client_role="intruder")
    assert result["receiver_returncode"] != 0
    assert result["receiver_report"] is None
    assert result["model_report"] is None
    assert "identity" in result["receiver_stderr"] or "DNS" in result["receiver_stderr"]
