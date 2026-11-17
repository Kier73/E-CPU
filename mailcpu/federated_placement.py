"""SAB-005 mutual-TLS transport for SAB-003/SAB-004 qualified observer hosts.

A network identity and resource advertisement never grant computation: each
receiver invokes only its own installed worker and receiver-local Hypervisor.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
import secrets
import socket
import ssl
import subprocess
import sys
from typing import Any, Mapping, Sequence

from .runtime_qualification import (
    QualificationRefused, REQUEST_KIND, canonical, _check_response,
)

MAX_FRAME = 8192
OPS = frozenset({
    "observe", "affine_mod", "transfer", "retain", "retrieve", "execute_source",
    "lens64.navigate",
})


class FederationRefused(QualificationRefused):
    """Reject authentication, local admission, framing and receiver-lifetime failures."""


def _frame(stream: Any, limit: int) -> dict[str, Any]:
    """Read a single canonical, bounded JSON frame without accepting truncation."""
    raw = bytearray()
    while len(raw) <= limit:
        chunk = stream.recv(1)
        if not chunk:
            raise FederationRefused("connection closed before a complete frame")
        if chunk == b"\n":
            break
        raw.extend(chunk)
    if len(raw) >= limit:
        raise FederationRefused("frame exceeded the permitted budget")
    try:
        parsed = json.loads(raw)
        if not isinstance(parsed, dict) or canonical(parsed) != bytes(raw):
            raise FederationRefused("frame is noncanonical or not an object")
    except (ValueError, UnicodeError, TypeError) as exc:
        raise FederationRefused("invalid canonical JSON network frame") from exc
    return parsed


def _san_matches(cert: Mapping[str, Any], dns: str) -> bool:
    """Require exact DNS SAN identity in a certificate verified by the local CA."""
    sans = cert.get("subjectAltName", ())
    return (
        isinstance(sans, (list, tuple))
        and any(kind == "DNS" and value == dns for kind, value in sans)
    )


class MutualTLSQualificationEndpoint:
    """SAB-003 QualificationEndpoint bound to an authenticated receiver certificate."""

    separate_process_per_exchange = True

    def __init__(
        self, host_id: str, address: tuple[str, int], *, server_dns: str,
        client_certificate: str, client_key: str, ca_file: str,
        timeout: float = 4.0,
    ) -> None:
        """Pin the host's network and TLS identities independently from its offers."""
        if (
            not isinstance(host_id, str) or not host_id
            or not isinstance(server_dns, str) or not server_dns
            or type(address[0]) is not str or not address[0]
            or type(address[1]) is not int or not 0 < address[1] < 65536
            or timeout <= 0
        ):
            raise FederationRefused("invalid endpoint configuration")
        self.host_id = host_id
        self.address = address
        self.server_dns = server_dns
        self.timeout = float(timeout)
        self.context = ssl.create_default_context(
            ssl.Purpose.SERVER_AUTH, cafile=ca_file,
        )
        self.context.load_cert_chain(client_certificate, client_key)
        self.context.verify_mode = ssl.CERT_REQUIRED
        self.context.check_hostname = True

    def exchange(
        self, request: Mapping[str, Any], *, max_bytes: int,
    ) -> Mapping[str, Any]:
        """Enforce exact request identity, peer TLS identity, frame size and echo."""
        if (
            type(max_bytes) is not int or not 128 <= max_bytes <= MAX_FRAME
            or request.get("host") != self.host_id
            or request.get("kind") != REQUEST_KIND
        ):
            raise FederationRefused("request host or frame budget rejected")
        encoded = canonical(dict(request))
        if len(encoded) + 1 > MAX_FRAME:
            raise FederationRefused("request exceeds protocol bound")
        try:
            with socket.create_connection(
                self.address, timeout=self.timeout,
            ) as connection:
                connection.settimeout(self.timeout)
                with self.context.wrap_socket(
                    connection, server_hostname=self.server_dns,
                ) as tls:
                    tls.sendall(encoded + b"\n")
                    result = _frame(tls, max_bytes)
                    _check_response(request, result)
                    return result
        except (OSError, ssl.SSLError, TimeoutError) as exc:
            raise FederationRefused(
                "authenticated endpoint unavailable or identity rejected"
            ) from exc


class PinnedTLSServer:
    """Receiver-owned TLS listener with a finite allowlist and fixed subprocess."""

    def __init__(
        self, *, host_id: str, host: str, port: int,
        certificate: str, key: str, ca_file: str, client_dns: str,
        storage_directory: str, allowed_operations: frozenset[str],
        native_authority: bool = True, worker_timeout: float = 8.0,
        allowed_lens_grounds: frozenset[str] = frozenset(),
    ) -> None:
        """Install the receiver's own executable, identity and grant configuration."""
        if (
            not isinstance(host_id, str) or not host_id
            or not isinstance(client_dns, str) or not client_dns
            or not isinstance(allowed_operations, frozenset)
            or not allowed_operations <= OPS
            or type(port) is not int or not 0 <= port < 65536
            or worker_timeout <= 0
            or not isinstance(allowed_lens_grounds, frozenset)
            or len(allowed_lens_grounds) > 32
            or any(type(item) is not str or re.fullmatch(r"[0-9a-f]{64}", item) is None
                   for item in allowed_lens_grounds)
        ):
            raise FederationRefused("invalid receiver configuration")
        self.host_id = host_id
        self.host = host
        self.port = port
        self.client_dns = client_dns
        self.storage_directory = Path(storage_directory)
        self.allowed_operations = allowed_operations
        self.native_authority = bool(native_authority)
        self.allowed_lens_grounds = allowed_lens_grounds
        self.worker_timeout = worker_timeout
        self.context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self.context.load_cert_chain(certificate, key)
        self.context.load_verify_locations(cafile=ca_file)
        self.context.verify_mode = ssl.CERT_REQUIRED

    def _execute(self, request: Mapping[str, Any]) -> dict[str, Any]:
        """Refuse ungranted opcodes before launching a known receiver program."""
        if (
            set(request) != {"kind", "host", "nonce", "operation", "payload"}
            or request["kind"] != REQUEST_KIND or request["host"] != self.host_id
            or type(request["operation"]) is not str
            or not isinstance(request["payload"], dict)
            or type(request["nonce"]) is not str
            or not 8 <= len(request["nonce"]) <= 64
        ):
            raise FederationRefused("request schema refused before local worker")
        if request["operation"] not in self.allowed_operations:
            return {
                "kind": "mailcpu.sab003.reply.v1",
                "host": self.host_id,
                "nonce": request["nonce"],
                "boot": secrets.token_hex(16),
                "ok": False, "result": None, "error": "unsupported",
            }
        args = [
            sys.executable, "-m", "mailcpu.federated_native_worker",
            "--host", self.host_id, "--directory", str(self.storage_directory),
        ]
        for operation in sorted(self.allowed_operations):
            args.extend(("--allow", operation))
        for digest_value in sorted(self.allowed_lens_grounds):
            args.extend(("--allow-lens-ground", digest_value))
        if not self.native_authority:
            args.append("--revoke-native")
        try:
            result = subprocess.run(
                args,
                input=canonical(dict(request)) + b"\n",
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=self.worker_timeout,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise FederationRefused("receiver subprocess unavailable") from exc
        if result.returncode or result.stderr or len(result.stdout) > MAX_FRAME:
            raise FederationRefused("receiver-local worker refused the request")
        payload = result.stdout
        if not payload.endswith(b"\n") or payload.count(b"\n") != 1:
            raise FederationRefused("receiver worker returned invalid frame count")
        try:
            reply = json.loads(payload)
            if not isinstance(reply, dict) or canonical(reply) + b"\n" != payload:
                raise FederationRefused("receiver worker result is not canonical")
            _check_response(request, reply)
            return reply
        except (ValueError, UnicodeError, TypeError) as exc:
            raise FederationRefused("receiver worker result invalid") from exc

    def serve(
        self, *, ready_file: str | None = None, max_connections: int = 0,
    ) -> None:
        """Accept bounded TLS exchanges, refusing other clients without code execution."""
        if max_connections < 0:
            raise FederationRefused("negative connection limit")
        count = 0
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind((self.host, self.port))
            listener.listen(16)
            listener.settimeout(0.5)
            if ready_file:
                # Harness notification only: not authenticated execution evidence.
                Path(ready_file).write_text(
                    str(listener.getsockname()[1]), encoding="ascii",
                )
            while not max_connections or count < max_connections:
                try:
                    raw, _address = listener.accept()
                except socket.timeout:
                    continue
                count += 1
                try:
                    raw.settimeout(self.worker_timeout + 3)
                    with self.context.wrap_socket(raw, server_side=True) as tls:
                        if not _san_matches(
                            tls.getpeercert(), self.client_dns,
                        ):
                            raise FederationRefused(
                                "client certificate identity mismatch"
                            )
                        request = _frame(tls, MAX_FRAME)
                        reply = self._execute(request)
                        tls.sendall(canonical(reply) + b"\n")
                except (OSError, ssl.SSLError, FederationRefused):
                    raw.close()
                    # One unauthorized exchange must not stop the service.
                    continue


def main(argv: Sequence[str] | None = None) -> int:
    """Run a locally configured, bounded mTLS host listener."""
    p = argparse.ArgumentParser()
    p.add_argument("serve", choices=("serve",))
    for label in (
        "host-id", "listen-address", "certificate", "key", "ca-file",
        "client-dns", "storage-directory",
    ):
        p.add_argument("--" + label, required=True)
    p.add_argument("--port", type=int, required=True)
    p.add_argument("--allow", action="append", default=[])
    p.add_argument("--allow-lens-ground", action="append", default=[])
    p.add_argument("--ready-file")
    p.add_argument("--revoke-native", action="store_true")
    p.add_argument("--max-connections", type=int, default=0)
    args = p.parse_args(argv)
    PinnedTLSServer(
        host_id=args.host_id,
        host=args.listen_address,
        port=args.port,
        certificate=args.certificate,
        key=args.key,
        ca_file=args.ca_file,
        client_dns=args.client_dns,
        storage_directory=args.storage_directory,
        allowed_operations=frozenset(args.allow),
        allowed_lens_grounds=frozenset(args.allow_lens_ground),
        native_authority=not args.revoke_native,
    ).serve(
        ready_file=args.ready_file,
        max_connections=args.max_connections,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
