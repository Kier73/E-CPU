"""Operate the real USM-004 mTLS model/E-CPU path and save its receipts.

Generates ephemeral testing certificates under a temporary directory. Never
writes private keys to the retained report; no production credentials used.
Requires the OpenSSL command-line utility.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile

from examples.model_ground_os import _digest


def _openssl(root: Path, *argv: str) -> None:
    """Create short-lived local test certificates with OpenSSL, fail closed."""
    result = subprocess.run(("openssl", *argv), cwd=root, text=True, capture_output=True,
                            timeout=30, check=False)
    if result.returncode:
        raise RuntimeError("test certificate creation refused: " + result.stderr[-300:])


def ephemeral_certificates(root: Path) -> dict[str, Path]:
    """Create ephemeral trust root plus separate SAN-qualified model/receiver keys."""
    ca, ca_key = root / "ca.pem", root / "ca.key"
    _openssl(root, "req", "-x509", "-newkey", "rsa:2048", "-nodes",
             "-keyout", str(ca_key), "-out", str(ca), "-days", "1", "-sha256",
             "-subj", "/CN=USM004 Experimental Local CA",
             "-addext", "basicConstraints=critical,CA:TRUE",
             "-addext", "keyUsage=critical,keyCertSign,cRLSign")
    paths = {"ca": ca}
    for role, name in (("receiver", "receiver-node"), ("model", "model-node")):
        key, csr, cert, ext = (
            root / f"{role}.{suffix}" for suffix in ("key", "csr", "pem", "ext")
        )
        _openssl(root, "req", "-new", "-newkey", "rsa:2048", "-nodes",
                 "-keyout", str(key), "-out", str(csr), "-subj", f"/CN={name}")
        ext.write_text(
            f"subjectAltName=DNS:{name}\n"
            "extendedKeyUsage=clientAuth,serverAuth\n"
            "basicConstraints=critical,CA:FALSE\n"
            "keyUsage=critical,digitalSignature,keyEncipherment\n",
            encoding="utf-8"
        )
        _openssl(root, "x509", "-req", "-in", str(csr),
                 "-CA", str(ca), "-CAkey", str(ca_key), "-CAcreateserial",
                 "-out", str(cert), "-days", "1", "-sha256", "-extfile", str(ext))
        paths[f"{role}_cert"] = cert
        paths[f"{role}_key"] = key
    return paths


def run_case(
    directory: Path, keys: dict[str, Path], *,
    kind: str, policy: str,
) -> dict[str, object]:
    """Run both independently launched Python processes over native mTLS."""
    receiver_report, model_report = directory / "receiver.json", directory / "model.json"
    common = ("--host", "127.0.0.1", "--ca", str(keys["ca"]))
    receiver_cmd = (
        sys.executable, "-m", "examples.model_authenticated_fabric",
        "receiver", *common,
        "--cert", str(keys["receiver_cert"]), "--key", str(keys["receiver_key"]),
        "--source-kind", kind, "--source-seed", "201", "--policy", policy,
        "--output", str(receiver_report),
    )
    receiver = subprocess.Popen(
        receiver_cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    try:
        if receiver.stdout is None:
            raise RuntimeError("receiver did not expose startup stream")
        first = receiver.stdout.readline()
        try:
            ready = json.loads(first)
            port = ready["ready_port"]
        except (ValueError, KeyError, TypeError) as exc:
            raise RuntimeError("receiver did not publish a valid bound port") from exc
        model_cmd = (
            sys.executable, "-m", "examples.model_authenticated_fabric",
            "model", *common,
            "--cert", str(keys["model_cert"]), "--key", str(keys["model_key"]),
            "--port", str(port), "--output", str(model_report),
        )
        model = subprocess.run(model_cmd, text=True, capture_output=True,
                               check=False, timeout=35)
        _rest, stderr = receiver.communicate(timeout=35)
        if model.returncode or receiver.returncode:
            raise RuntimeError(
                "model/receiver did not complete authenticated protocol: " +
                (model.stderr + stderr)[-500:]
            )
        receiver_evidence = json.loads(receiver_report.read_text(encoding="utf-8"))
        model_evidence = json.loads(model_report.read_text(encoding="utf-8"))
        if receiver_evidence["session"]["trace_digest"] != model_evidence["final"]["trace_digest"]:
            raise RuntimeError("receiver/model evidence identity mismatch")
        if receiver_evidence["receiver_process"] == model_evidence["model_process"]:
            raise RuntimeError("model and E-CPU receiver are not separate OS processes")
        return {"kind": kind, "policy": policy, "receiver": receiver_evidence,
                "model_host": model_evidence}
    finally:
        if receiver.poll() is None:
            receiver.kill()
            receiver.communicate(timeout=5)


def run() -> dict[str, object]:
    """Retain complete operation evidence while deleting all ephemeral keys."""
    with tempfile.TemporaryDirectory(prefix="usm004-") as temporary:
        root = Path(temporary)
        certs = ephemeral_certificates(root)
        results = [
            run_case(root, certs, kind="affine", policy="high-request"),
            run_case(root, certs, kind="nonlinear", policy="high-request"),
            run_case(root, certs, kind="affine", policy="low-request"),
            run_case(root, certs, kind="affine", policy="trained"),
            run_case(root, certs, kind="nonlinear", policy="trained"),
        ]
    statuses = [x["receiver"]["status"] for x in results]
    if statuses[:3] != ["complete", "refused", "deferred"]:
        raise RuntimeError("unexpected independent model/E-CPU control outcomes")
    if any(status not in {"complete", "refused", "deferred"} for status in statuses[3:]):
        raise RuntimeError("trained model did not produce an admitted system-call outcome")
    if statuses[4] == "complete":
        raise RuntimeError("trained model admitted an invalid nonlinear Ground")
    first = results[0]["receiver"]["session"]
    coordinate = first["requested_coordinate"]
    expected = (7 + 201 + 5 * coordinate) % 97
    if first["events"][-1]["output"]["value"] != expected:
        raise RuntimeError("authenticated model's Ground read disagrees with source oracle")
    core = {
        "schema": "mailcpu.usm004.operational-evidence.v1",
        "transport": "real-mutual-tls-mailcpu-reliable-channels",
        "physical_independence_attested": False,
        "ephemeral_test_certificates": True,
        "cases": results,
        "oracle_checked": True,
        "trained_model_unforced": True,
        "trained_model_outcomes": [
            {"kind": x["kind"], "status": x["receiver"]["status"],
             "model_digest": x["receiver"]["model_digest"]}
            for x in results[3:]
        ],
    }
    return {**core, "report_digest": _digest(core)}


def main() -> None:
    """Write the artifact for independent inspection without private keys."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("usm004-report.json"))
    args = parser.parse_args()
    report = run()
    args.output.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n",
                           encoding="utf-8")
    print(json.dumps({
        "report_digest": report["report_digest"],
        "cases": [x["receiver"]["status"] for x in report["cases"]],
        "output": str(args.output),
    }, sort_keys=True))


if __name__ == "__main__":
    main()
