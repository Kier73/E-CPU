"""PATH-GROUND-005 live mTLS test observers for real PATH-GROUND-004 captures.

The experiment launches four independently keyed observer processes with real
MailCPU mutual-TLS SocketTransport sessions, bound to four router/bridge
capture records. It does NOT create separate physical hosts, independent
capture hardware or externally administered identity authorities.

Usage (after running the privileged PATH-GROUND-004 harness):
  python -m examples.run_authenticated_router_witness \
    --input-dir artifacts/path-ground-004 --output artifacts/pg5.json
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import secrets
import socket
import ssl
import subprocess
import sys
import tempfile
import time

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from mailcpu.ip_router_path_ground import (
    ROUTES, RouterGroundRefused, recognize_router_ttl_ground, verify_router_route,
)
from mailcpu.router_witness_auth import (
    AuthenticatedRouterRefused, SCHEMA, make_capture_request, signed_capture,
    verify_authenticated_router_route,
)
from mailcpu.semantic_translation import canonical_value_digest
from mailcpu.mtls_transport import accept_mutual_tls, connect_mutual_tls, MutualTLSTransportError
from mailcpu.socket_transport import SocketTransport
from mailcpu.model import Message


CLIENT = "coordinator.pg5.invalid"
SERVER_DNS = {rid: "observer-" + rid.replace(".", "-") + ".pg5.invalid"
              for route in ROUTES.values() for rid in route}


def _save(path: Path, content: bytes) -> None:
    """Mathematics: write certificate or key bytes under job-local restrictive permissions."""
    path.write_bytes(content)
    os.chmod(path, 0o600)


def issue_test_identities(directory: Path) -> bytes:
    """Mathematics: create ephemeral P-256 CA and distinct mTLS observer leaf identities."""
    now = datetime.now(timezone.utc)
    ca_key = ec.generate_private_key(ec.SECP256R1())
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "PG5 local transient CA")])
    ca = (x509.CertificateBuilder()
          .subject_name(ca_name).issuer_name(ca_name)
          .public_key(ca_key.public_key()).serial_number(x509.random_serial_number())
          .not_valid_before(now - timedelta(minutes=3))
          .not_valid_after(now + timedelta(hours=2))
          .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
          .sign(ca_key, hashes.SHA256()))
    root = ca.public_bytes(serialization.Encoding.PEM)
    _save(directory / "ca.pem", root)

    for peer, dns, role in (
        [("coordinator", CLIENT, ExtendedKeyUsageOID.CLIENT_AUTH)] +
        [(rid, dns, ExtendedKeyUsageOID.SERVER_AUTH) for rid, dns in SERVER_DNS.items()]
    ):
        leaf_key = ec.generate_private_key(ec.SECP256R1())
        subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, dns)])
        leaf = (x509.CertificateBuilder()
                .subject_name(subject).issuer_name(ca.subject)
                .public_key(leaf_key.public_key())
                .serial_number(x509.random_serial_number())
                .not_valid_before(now - timedelta(minutes=3))
                .not_valid_after(now + timedelta(hours=2))
                .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
                .add_extension(x509.SubjectAlternativeName([x509.DNSName(dns)]), critical=False)
                .add_extension(x509.ExtendedKeyUsage([role]), critical=False)
                .sign(ca_key, hashes.SHA256()))
        _save(directory / (peer + ".pem"), leaf.public_bytes(serialization.Encoding.PEM))
        _save(directory / (peer + ".key"), leaf_key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ))
    return root


def client_context(keys: Path) -> ssl.SSLContext:
    """Mathematics: authenticate server SAN under the explicit receiver-owned ephemeral CA."""
    ctx = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=str(keys / "ca.pem"))
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(str(keys / "coordinator.pem"), str(keys / "coordinator.key"))
    return ctx


def server_context(keys: Path, ident: str) -> ssl.SSLContext:
    """Mathematics: enforce real mutual TLS and require a signed client certificate."""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.verify_mode = ssl.CERT_REQUIRED
    ctx.load_verify_locations(cafile=str(keys / "ca.pem"))
    ctx.load_cert_chain(str(keys / (ident + ".pem")), str(keys / (ident + ".key")))
    return ctx


def wire_send(t: SocketTransport, target: str, operation: str, body: dict) -> None:
    """Mathematics: use the existing MailCPU framed message algebra over mutual TLS."""
    t.send(target, Message(
        sender=t.local_endpoint, recipient=target, op=operation, body=(body,),
    ))


def wire_read(t: SocketTransport, expected: str, timeout: float = 7.0) -> dict:
    """Mathematics: receive exactly one authenticated, bounded MailCPU response."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        item = t.poll(t.local_endpoint)
        if item is not None:
            if (item.op not in (expected, "REJECT") or len(item.body) != 1
                    or type(item.body[0]) is not dict):
                raise AuthenticatedRouterRefused("unexpected MailCPU observer response")
            return {"op": item.op, "body": item.body[0]}
        if t.closed:
            raise AuthenticatedRouterRefused("observer closed before required receipt")
        time.sleep(0.005)
    raise AuthenticatedRouterRefused("authenticated observer did not respond within timeout")


def observer_process(
    router_id: str, capture_file: Path, keys: Path,
    ready_file: Path, expected_ground_digest: str,
    expected_route_digest: str, expected_policy_digest: str,
) -> None:
    """Mathematics: independently process receiver challenge against one locally held raw capture."""
    if router_id not in SERVER_DNS:
        raise AuthenticatedRouterRefused("unrecognized observer-host")
    capture = json.loads(capture_file.read_text(encoding="utf-8"))
    key = serialization.load_pem_private_key(
        (keys / (router_id + ".key")).read_bytes(), password=None,
    )
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(3)
    listener.settimeout(8)
    ready_file.write_text(json.dumps({"port": listener.getsockname()[1],
                                      "router_id": router_id}))
    used = set()
    try:
        # One connection; the coordinator sends a valid request, a repeated
        # request to test replay, and an explicitly acknowledged termination.
        with accept_mutual_tls(
            listener, router_id, "coordinator",
            server_context(keys, router_id), expected_peer_dns=CLIENT,
            handshake_timeout=7,
        ) as t:
            pass
    except TypeError:
        # SocketTransport supports close(), but is not a context manager.
        t = None
        try:
            t = accept_mutual_tls(
                listener, router_id, "coordinator", server_context(keys, router_id),
                expected_peer_dns=CLIENT, handshake_timeout=7,
            )
            while True:
                req = wire_read(t, "*", timeout=8)
                op, msg = req["op"], req["body"]
                if op == "OBSERVE":
                    try:
                        want = make_capture_request(
                            route_id=msg["route_id"], router_id=msg["router_id"],
                            ground_digest=msg["ground_digest"],
                            route_evidence_digest=msg["route_evidence_digest"],
                            receiver_policy_digest=msg["receiver_policy_digest"],
                            capture=capture, challenge=msg["challenge"],
                        )
                        valid = (want == msg
                                 and msg["router_id"] == router_id
                                 and msg["ground_digest"] == expected_ground_digest
                                 and msg["route_evidence_digest"] == expected_route_digest
                                 and msg["receiver_policy_digest"] == expected_policy_digest)
                        if not valid:
                            raise AuthenticatedRouterRefused("unlicensed route, packet or Ground")
                        if want["challenge"] in used:
                            wire_send(t, "coordinator", "REJECT", {"reason": "challenge-replay"})
                            continue
                        used.add(want["challenge"])
                        signed = signed_capture(key, want, capture, SERVER_DNS[router_id])
                        wire_send(t, "coordinator", "RECEIPT", {
                            "envelope": signed, "capture": capture,
                        })
                    except (AuthenticatedRouterRefused, KeyError, TypeError):
                        wire_send(t, "coordinator", "REJECT", {"reason": "invalid-observation-request"})
                elif op == "CLOSE":
                    wire_send(t, "coordinator", "CLOSED", {"done": True})
                elif op == "BYE":
                    break
                else:
                    wire_send(t, "coordinator", "REJECT", {"reason": "unknown-capability"})
        finally:
            if t is not None:
                t.close()
            listener.close()
    else:
        # The adapter should not implement context management; fail if an
        # unexpected transport implementation changes this assumption.
        raise AuthenticatedRouterRefused("unexpected context-managed MailCPU transport")


def run(input_dir: Path, output: Path) -> dict:
    """Mathematics: remotely authenticate actual capture claims then reconstruct native paths."""
    observations, raw = {}, {}
    for route_id, ids in ROUTES.items():
        source = json.loads((input_dir / f"sender-{route_id}.json").read_text())
        receiver = json.loads((input_dir / f"receiver-{route_id}.json").read_text())
        captures = [
            json.loads((input_dir / f"router-{route_id}-r{i + 1}.json").read_text())
            for i in range(len(ids))
        ]
        observations[route_id] = verify_router_route(route_id, source, receiver, captures)
        raw[route_id] = (source, receiver, captures)
    ground = recognize_router_ttl_ground(*(observations[r] for r in ROUTES))
    policy = canonical_value_digest({
        "scope": "pg5-owned-ephemeral-in-run-tls-test",
        "router_ground": ground.ground_digest,
        "raw_source_receiver_checked": True,
    })
    with tempfile.TemporaryDirectory(prefix="pg5-observers-") as temporary:
        keys = Path(temporary)
        root = issue_test_identities(keys)
        processes = []
        sessions = {}
        started = time.monotonic_ns()
        try:
            for router_id in SERVER_DNS:
                route_id = next(r for r, ids in ROUTES.items() if router_id in ids)
                index = ROUTES[route_id].index(router_id) + 1
                ready = keys / (router_id + ".ready")
                capture_file = input_dir / f"router-{route_id}-r{index}.json"
                proc = subprocess.Popen([
                    sys.executable, "-m", "examples.run_authenticated_router_witness",
                    "--serve", router_id, "--capture-file", str(capture_file),
                    "--cert-dir", str(keys), "--ready", str(ready),
                    "--ground", ground.ground_digest,
                    "--route", observations[route_id].evidence_digest,
                    "--policy", policy,
                ], stdout=(keys / (router_id + ".stdout")).open("w"),
                   stderr=(keys / (router_id + ".stderr")).open("w"))
                processes.append((router_id, proc))
            ports = {}
            for router_id, proc in processes:
                ready = keys / (router_id + ".ready")
                deadline = time.monotonic() + 8
                while not ready.exists() and time.monotonic() < deadline:
                    if proc.poll() is not None:
                        raise AuthenticatedRouterRefused(
                            f"observer {router_id} exited before ready: " +
                            (keys / (router_id + ".stderr")).read_text()[-1400:],
                        )
                    time.sleep(0.025)
                if not ready.exists():
                    raise AuthenticatedRouterRefused(f"observer {router_id} startup timed out")
                ports[router_id] = json.loads(ready.read_text())["port"]
            tls_certs = {}
            for router_id, port in ports.items():
                t = connect_mutual_tls(
                    "127.0.0.1", port, "coordinator", router_id,
                    client_context(keys), server_hostname=SERVER_DNS[router_id],
                    timeout=5, handshake_timeout=5,
                )
                sessions[router_id] = t
                observed_cert = t.socket.getpeercert(binary_form=True)
                pinned_cert = x509.load_pem_x509_certificate(
                    (keys / (router_id + ".pem")).read_bytes(),
                ).public_bytes(serialization.Encoding.DER)
                if observed_cert != pinned_cert:
                    raise AuthenticatedRouterRefused("authenticated TLS leaf changed from pinned capture signer")
                tls_certs[router_id] = observed_cert

            used_challenges: set[str] = set()
            signed_reports = []
            route_reports = {}
            replay_refused = False
            for route_id, ids in ROUTES.items():
                src, dst, captures = raw[route_id]
                requests = []
                envelopes = []
                for router_id, capture in zip(ids, captures, strict=True):
                    request = make_capture_request(
                        route_id=route_id, router_id=router_id,
                        ground_digest=ground.ground_digest,
                        route_evidence_digest=observations[route_id].evidence_digest,
                        receiver_policy_digest=policy,
                        capture=capture, challenge=secrets.token_hex(16),
                    )
                    t = sessions[router_id]
                    wire_send(t, router_id, "OBSERVE", request)
                    result = wire_read(t, "RECEIPT")
                    if result["op"] != "RECEIPT" or set(result["body"]) != {"envelope", "capture"}:
                        raise AuthenticatedRouterRefused("peer refused signed raw packet evidence")
                    if result["body"]["capture"] != capture:
                        raise AuthenticatedRouterRefused("peer's signed raw frame content differs from local capture")
                    requests.append(request)
                    envelopes.append(result["body"]["envelope"])
                    signed_reports.append({
                        "route": route_id, "router_id": router_id,
                        "request": request, "envelope": result["body"]["envelope"],
                        "leaf_der_sha256": sha256(tls_certs[router_id]).hexdigest(),
                    })
                    if not replay_refused:
                        wire_send(t, router_id, "OBSERVE", request)
                        response = wire_read(t, "REJECT")
                        replay_refused = (
                            response["op"] == "REJECT"
                            and response["body"] == {"reason": "challenge-replay"}
                        )
                authorized = lambda actual, expected=observations[route_id]: actual == expected
                outcome = verify_authenticated_router_route(
                    ground, route_id, src, dst, captures,
                    requests, envelopes,
                    {r: tls_certs[r] for r in ids},
                    {r: SERVER_DNS[r] for r in ids},
                    trusted_ca_pem=root, receiver_policy_digest=policy,
                    used_challenges=used_challenges,
                    admit_local_capture=authorized, now=datetime.now(timezone.utc),
                )
                route_reports[route_id] = outcome.to_dict()
            if not replay_refused or len(used_challenges) != len(SERVER_DNS):
                raise AuthenticatedRouterRefused("not all signed observer challenge checks succeeded")
            report = {
                "schema": SCHEMA + ".live-mtls-report",
                "status": "authenticated_live_mtls_capture_claims_and_native_packet_paths",
                "ground_digest": ground.ground_digest,
                "receiver_policy_digest": policy,
                "authenticated_observer_count": len(SERVER_DNS),
                "native_paths_verified": sum(len(x["native_path_digests"]) for x in route_reports.values()),
                "replay_refused": replay_refused,
                "routes": route_reports,
                "signed_receipts": signed_reports,
                "trusted_ephemeral_root_ca_pem": root.decode("ascii"),
                "leaf_certificates_pem": {
                    rid: (keys / (rid + ".pem")).read_text() for rid in SERVER_DNS
                },
                "duration_ns": time.monotonic_ns() - started,
                "transport": "actual_loopback_ECPU_mutual_TLS_SocketTransport",
                "scope": "independent_OS_processes_on_one_runner_not_independently_operated_hosts",
                "physical_capture_truth_from_signatures_alone": False,
                "public_keys_are_not_execution_authority": True,
            }
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
            return report
        finally:
            for rid, t in sessions.items():
                try:
                    wire_send(t, rid, "CLOSE", {"done": True})
                    closed = wire_read(t, "CLOSED", timeout=3)
                    if closed["op"] == "CLOSED":
                        wire_send(t, rid, "BYE", {"done": True})
                except Exception:
                    pass
            for rid, proc in processes:
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=3)
            for t in sessions.values():
                try:
                    t.close()
                except Exception:
                    pass


def main() -> None:
    """Mathematics: require explicit user-owned raw packet artifacts and bounded credentials."""
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input-dir", type=Path)
    p.add_argument("--output", type=Path)
    p.add_argument("--serve", choices=tuple(SERVER_DNS))
    p.add_argument("--capture-file", type=Path)
    p.add_argument("--cert-dir", type=Path)
    p.add_argument("--ready", type=Path)
    p.add_argument("--ground")
    p.add_argument("--route")
    p.add_argument("--policy")
    args = p.parse_args()
    if args.serve is not None:
        if not all((args.capture_file, args.cert_dir, args.ready,
                    args.ground, args.route, args.policy)):
            p.error("signed observer requires capture, certificate and pinned Ground policy")
        observer_process(
            args.serve, args.capture_file, args.cert_dir, args.ready,
            args.ground, args.route, args.policy,
        )
    else:
        if args.input_dir is None or args.output is None:
            p.error("coordinator requires actual raw packet input-dir and report output")
        result = run(args.input_dir, args.output)
        print(json.dumps({
            "ground": result["ground_digest"],
            "observers": result["authenticated_observer_count"],
            "native_paths": result["native_paths_verified"],
            "replay_refused": result["replay_refused"],
        }, sort_keys=True))


if __name__ == "__main__":
    main()
