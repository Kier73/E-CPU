"""SAB-005 authenticated process federation, native authority and checkpoint continuity."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest

from mailcpu.adaptive_placement import (
    AdaptivePlacement, CompositeIntent, PlacementAuthority, PlacementRefused,
    QualifiedHost, expected_result,
)
from mailcpu.federated_placement import (
    FederationRefused, MutualTLSQualificationEndpoint,
)
from mailcpu.runtime_qualification import (
    QualificationPolicy, _request, digest, qualify,
)

try:
    from mailcpu import HeadlessOS
    HAVE_NATIVE = HeadlessOS is not None
except ImportError:
    HAVE_NATIVE = False


def _openssl(*args: str) -> None:
    """Run only locally constructed test certificate commands."""
    subprocess.run(("openssl", *args), capture_output=True, check=True)


def _cert(root: Path, ca: Path, name: str) -> tuple[Path, Path]:
    """Issue a short-lived SAN-pinned client or server certificate."""
    key, csr, crt = (root / (name + ext) for ext in (".key", ".csr", ".crt"))
    _openssl("req", "-new", "-newkey", "rsa:2048", "-nodes",
             "-subj", f"/CN={name}.sab005.test",
             "-keyout", str(key), "-out", str(csr))
    ext = root / (name + ".ext")
    use = "clientAuth" if name in ("origin", "attacker") else "serverAuth"
    ext.write_text(f"subjectAltName=DNS:{name}.sab005.test\n"
                   "keyUsage=critical,digitalSignature,keyEncipherment\n"
                   f"extendedKeyUsage={use}\n")
    _openssl("x509", "-req", "-in", str(csr), "-CA", str(ca),
             "-CAkey", str(root / "ca.key"), "-CAcreateserial",
             "-days", "1", "-extfile", str(ext), "-out", str(crt))
    return crt, key


@unittest.skipUnless(shutil.which("openssl"), "ephemeral OpenSSL certificate fixtures required")
class FederatedTests(unittest.TestCase):
    """Five receiver listener processes; each fixed operation forks a fresh interpreter."""

    @classmethod
    def setUpClass(cls) -> None:
        """Build ephemeral PKI and independently owned listener/data directories."""
        cls.temp = tempfile.TemporaryDirectory(prefix="sab005-")
        cls.root = Path(cls.temp.name)
        cls.ca = cls.root / "ca.crt"
        _openssl("req", "-x509", "-newkey", "rsa:2048", "-nodes",
                 "-days", "1", "-subj", "/CN=SAB005-local-test-ca",
                 "-addext", "basicConstraints=critical,CA:TRUE",
                 "-addext", "keyUsage=critical,keyCertSign,cRLSign",
                 "-keyout", str(cls.root / "ca.key"), "-out", str(cls.ca))
        cls.client_crt, cls.client_key = _cert(cls.root, cls.ca, "origin")
        cls.attacker_crt, cls.attacker_key = _cert(cls.root, cls.ca, "attacker")
        cls.certs = {name: _cert(cls.root, cls.ca, name) for name in
                     ("calc-fast", "calc-slow", "port-relay", "store-a", "store-b")}
        cls.ops = {
            "calc-fast": ("observe", "affine_mod"),
            "calc-slow": ("observe", "affine_mod"),
            "port-relay": ("observe", "transfer"),
            "store-a": ("observe", "retain", "retrieve"),
            "store-b": ("observe", "retain", "retrieve"),
        }
        cls.processes: dict[str, subprocess.Popen] = {}
        cls.endpoints: dict[str, MutualTLSQualificationEndpoint] = {}
        for name in cls.ops:
            cls._launch(name)

    @classmethod
    def tearDownClass(cls) -> None:
        """Stop all controlled listeners and discard test credentials."""
        for name in tuple(cls.processes):
            cls._stop(name)
        cls.temp.cleanup()

    @classmethod
    def _stop(cls, name: str) -> None:
        """Terminate one server without deleting its durable data."""
        process = cls.processes.pop(name, None)
        if process is not None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            if process.stderr:
                process.stderr.close()

    @classmethod
    def _launch(cls, name: str, *, native_authority: bool = True) -> None:
        """Start a new listener process using the exact host-local key and allowlist."""
        cls._stop(name)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        cert, key = cls.certs[name]
        directory = cls.root / (name + "-data")
        directory.mkdir(exist_ok=True)
        ready = cls.root / (name + ".ready")
        ready.unlink(missing_ok=True)
        args = [
            sys.executable, "-m", "mailcpu.federated_placement", "serve",
            "--host-id", name, "--listen-address", "127.0.0.1", "--port", str(port),
            "--certificate", str(cert), "--key", str(key), "--ca-file", str(cls.ca),
            "--client-dns", "origin.sab005.test",
            "--storage-directory", str(directory), "--ready-file", str(ready),
        ]
        for op in cls.ops[name]:
            args.extend(("--allow", op))
        if not native_authority:
            args.append("--revoke-native")
        process = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        cls.processes[name] = process
        end = time.monotonic() + 12
        while not ready.exists() and time.monotonic() < end:
            if process.poll() is not None:
                raise AssertionError("listener exited: " + process.stderr.read().decode()[:1800])
            time.sleep(.03)
        if not ready.exists():
            cls._stop(name)
            raise AssertionError("receiver listener startup timed out")
        cls.endpoints[name] = MutualTLSQualificationEndpoint(
            name, ("127.0.0.1", port), server_dns=name + ".sab005.test",
            client_certificate=str(cls.client_crt), client_key=str(cls.client_key),
            ca_file=str(cls.ca), timeout=6,
        )

    def test_framed_tls_observer_qualifies_without_authority_promotion(self) -> None:
        """Observe and transfer through real TLS while retaining non-authoritative evidence."""
        name = "port-relay"
        policy = QualificationPolicy(frozenset({name}), "sab005-observer", 50,
                                     frozenset({"observer", "framed_ipc"}), max_calls=2)
        report = qualify(self.endpoints[name], policy, coordinate=5,
                         seed="sab005-tls-observation")
        self.assertIn("framed_ipc", report.payload["verified_roles"])
        self.assertFalse(report.payload["local_hypervisor_permission_granted"])

    def test_wrong_client_identity_rejected(self) -> None:
        """A CA-signed attacker without the pinned client SAN is still unauthorized."""
        endpoint = self.endpoints["port-relay"]
        forged = MutualTLSQualificationEndpoint(
            endpoint.host_id, endpoint.address, server_dns=endpoint.server_dns,
            client_certificate=str(self.attacker_crt), client_key=str(self.attacker_key),
            ca_file=str(self.ca),
        )
        with self.assertRaises(FederationRefused):
            forged.exchange(_request("port-relay", "observe", {"word": "x"},
                                     "forged-client", 0), max_bytes=4096)

    def test_wrong_server_identity_rejected(self) -> None:
        """IP reachability and a trusted CA do not replace the expected host identity."""
        endpoint = self.endpoints["port-relay"]
        forged = MutualTLSQualificationEndpoint(
            endpoint.host_id, endpoint.address, server_dns="store-a.sab005.test",
            client_certificate=str(self.client_crt), client_key=str(self.client_key),
            ca_file=str(self.ca),
        )
        with self.assertRaises(FederationRefused):
            forged.exchange(_request("port-relay", "observe", {"word": "x"},
                                     "forged-server", 0), max_bytes=4096)

    def test_receiver_local_opcode_allowlist(self) -> None:
        """A named observer cannot claim an executable operation it lacks."""
        endpoint = self.endpoints["port-relay"]
        request = _request("port-relay", "affine_mod",
                           {"a": 5, "c": 7, "mod": 65521, "x0": 19, "coordinate": 10},
                           "ungranted-operation", 0)
        result = endpoint.exchange(request, max_bytes=4096)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "unsupported")

    def test_storage_survives_listener_restart(self) -> None:
        """A new receiver lifetime returns exact bytes stored by the earlier lifetime."""
        key = digest({"test": "sab005-store-restart"})[:32]
        value = {"ground": "verified", "payload": [1, 2, 3]}
        endpoint = self.endpoints["store-b"]
        request = _request("store-b", "retain", {"key": key, "value": value},
                           "restart-retain", 0)
        self.assertTrue(endpoint.exchange(request, max_bytes=4096)["ok"])
        self._launch("store-b")
        reply = self.endpoints["store-b"].exchange(
            _request("store-b", "retrieve", {"key": key}, "restart-read", 0),
            max_bytes=4096,
        )
        self.assertEqual(reply["result"], {"key": key, "value": value})

    def test_host_mismatch_rejected_before_network(self) -> None:
        """The client cannot switch the qualified host with only a request field."""
        with self.assertRaises(FederationRefused):
            self.endpoints["port-relay"].exchange(
                _request("not-port-relay", "observe", {"word": "x"}, "host-switch", 0),
                max_bytes=4096,
            )

    @unittest.skipUnless(HAVE_NATIVE, "requires repository-native HeadlessOS and Hypervisor")
    def test_local_hypervisor_revocation_blocks_remote_compute(self) -> None:
        """Receiver-local compute-right revocation denies even a valid TLS origin."""
        self._launch("calc-slow", native_authority=False)
        try:
            req = _request(
                "calc-slow", "affine_mod",
                {"a": 5, "c": 7, "mod": 65521, "x0": 19, "coordinate": 31},
                "revoked-native-right", 0,
            )
            with self.assertRaises(FederationRefused):
                self.endpoints["calc-slow"].exchange(req, max_bytes=4096)
        finally:
            self._launch("calc-slow")

    @unittest.skipUnless(HAVE_NATIVE, "requires repository-native HeadlessOS and Hypervisor")
    def test_native_execution_has_receiver_local_hypervisor_receipt(self) -> None:
        """A successful native call leaves a content-bound receiver-owned audit record."""
        req = _request("calc-fast", "affine_mod",
                       {"a": 5, "c": 7, "mod": 65521, "x0": 19,
                        "coordinate": 10**12 + 913}, "native-audit", 0)
        reply = self.endpoints["calc-fast"].exchange(req, max_bytes=4096)
        self.assertTrue(reply["ok"])
        folder = self.root / "calc-fast-data" / "native-receipts"
        records = [json.loads(p.read_bytes()) for p in folder.glob("*.json")]
        self.assertTrue(any(
            r["request_digest"] == digest(req)
            and r["receiver_evidence"]["hypervisor_action"] == "allow"
            for r in records
        ))

    @unittest.skipUnless(HAVE_NATIVE, "requires repository-native HeadlessOS and Hypervisor")
    def test_replacement_and_survivor_only_checkpoint_recovery(self) -> None:
        """A changed compute route preserves Ground; storage survives other host lifetimes."""
        qualified = {}
        for name in self.ops:
            role = ("computational_fragment" if name.startswith("calc-") else
                    "framed_ipc" if name == "port-relay" else "retained_state")
            policy = QualificationPolicy(
                frozenset({name}), "sab005-observer", 50,
                frozenset({"observer", role}),
                max_calls={"computational_fragment": 4, "framed_ipc": 2, "retained_state": 3}[role],
            )
            report = qualify(self.endpoints[name], policy, coordinate=5,
                             seed="sab005-owned-qualification")
            self.assertIn(role, report.payload["verified_roles"])
            qualified[name] = QualifiedHost(self.endpoints[name], report.payload, policy)
        grants = frozenset({
            ("calc-fast", "affine_mod"), ("calc-slow", "affine_mod"),
            ("port-relay", "transfer"),
            ("store-a", "retain"), ("store-b", "retain"),
            ("store-a", "retrieve"), ("store-b", "retrieve"),
        })
        costs = {
            ("calc-fast", "affine_mod"): 1,
            ("calc-slow", "affine_mod"): 9,
            ("store-a", "retain"): 1,
            ("store-b", "retain"): 5,
        }
        def controller(hosts):
            """Configure one fresh controller with no inherited in-memory execution state."""
            return AdaptivePlacement(
                hosts, PlacementAuthority(grants, 40),
                quanta={k:v for k, v in costs.items() if k[0] in hosts},
            )
        intent = CompositeIntent(
            "sab005-mtls-" + digest(time.time_ns())[:12],
            5, 7, 65521, 19, 10**15 + 137,
        )
        run = controller(qualified)
        active = tuple(sorted(qualified))
        old_plan = run.compile(intent, active_hosts=active, coordinate=7)
        self.assertEqual(old_plan.assignment[0], "calc-fast")
        without_primary = tuple(h for h in active if h != "calc-fast")
        with self.assertRaises(PlacementRefused):
            run.execute(intent, old_plan, active_hosts=without_primary, coordinate=7)
        replacement = run.compile(intent, active_hosts=without_primary, coordinate=7)
        self.assertEqual(replacement.assignment[0], "calc-slow")
        finished = run.execute(
            intent, replacement, active_hosts=without_primary, coordinate=7, copies=2,
        )
        self.assertEqual(finished["result"], expected_result(intent))
        self.assertEqual(set(finished["replicas"]), {"store-a", "store-b"})
        self._stop("calc-slow")
        self._stop("port-relay")
        self._launch("store-b")
        survivors = {
            "store-b": QualifiedHost(
                self.endpoints["store-b"], qualified["store-b"].report,
                qualified["store-b"].policy,
            ),
        }
        resumed = controller(survivors).resume(
            intent, active_hosts=("store-b",), coordinate=8,
        )
        self.assertEqual(resumed["result"], finished["result"])
        self.assertFalse(resumed["reexecuted_computation"])
        self.assertFalse(finished["independent_physical_hosts_attested"])
        self._launch("calc-slow")
        self._launch("port-relay")


if __name__ == "__main__":
    unittest.main()
