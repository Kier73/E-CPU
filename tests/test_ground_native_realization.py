"""SAB-008: one Ground evaluated across three substrate-distinct realizers."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest

from mailcpu.ground_native_realization import (
    AffineGround, GroundIntention, PortGroundRealizer, TwoPortArithmeticGate,
    RealizationPolicy, RealizationRefused, FixedInterpreterRealizer,
    FederatedGroundRealizer, equivalent_observations, independent_observation,
    verify_receipt,
)
from mailcpu.runtime_qualification import (
    QualificationPolicy, SubprocessQualificationEndpoint, qualify,
)

try:
    from mailcpu.federated_placement import MutualTLSQualificationEndpoint
    from mailcpu import HeadlessOS
    HAVE_NATIVE = HeadlessOS is not None
except ImportError:
    HAVE_NATIVE = False


GROUND = AffineGround(5, 7, 65521, 19)
COORDINATE = 10**12 + 913
INTENTION = GroundIntention("sab008-one-ground", GROUND, COORDINATE)


def _policy(locus: str, method: str) -> RealizationPolicy:
    """Bind one exact locally controlled realization at a long coordinate."""
    return RealizationPolicy(frozenset({(locus, method)}), COORDINATE + 500)


def _qualified_subprocess(*, wrong: bool = False):
    """Qualify a fresh interpreter with closed, source-free operation vocabulary."""
    home = tempfile.TemporaryDirectory(prefix="sab008-interpreter-")
    argv = [sys.executable, "-m", "mailcpu.runtime_qualification_worker",
            "--host", "interpreter-A", "--directory", home.name]
    if wrong:
        argv.append("--wrong-compute")
    endpoint = SubprocessQualificationEndpoint("interpreter-A", tuple(argv), timeout=6)
    profile = QualificationPolicy(frozenset({"interpreter-A"}), "sab008-observer",
                                  COORDINATE + 500,
                                  frozenset({"observer", "computational_fragment"}), max_calls=4)
    return home, endpoint, profile


class SemanticContractTests(unittest.TestCase):
    """No native runtime is required to examine purely semantic claims."""

    def test_ground_identity_ignores_realizer(self):
        self.assertEqual(GROUND.fingerprint, AffineGround(5,7,65521,19).fingerprint)
        self.assertEqual(INTENTION.fingerprint,
                         GroundIntention("sab008-one-ground", AffineGround(5,7,65521,19), COORDINATE).fingerprint)

    def test_distant_coordinate_requires_no_linear_iteration(self):
        gate = TwoPortArithmeticGate("port-0", GROUND.modulus)
        observed = PortGroundRealizer("constrained-port", gate).observe(INTENTION, _policy("constrained-port", "port"))
        self.assertEqual(observed.payload["output"], {"value": independent_observation(INTENTION)})
        self.assertLess(observed.payload["event_count"], 128)
        self.assertEqual(observed.payload["event_count"], gate.sequence)

    def test_zero_coordinate(self):
        intent = GroundIntention("zero", GROUND, 0)
        receipt = PortGroundRealizer("constrained-port", TwoPortArithmeticGate("port-0", GROUND.modulus)).observe(
            intent, _policy("constrained-port", "port"))
        self.assertEqual(receipt.payload["output"], {"value": GROUND.seed})
        verify_receipt(receipt, intent, _policy("constrained-port", "port"))

    def test_port_rejects_bad_modulus(self):
        with self.assertRaisesRegex(RealizationRefused, "incompatible"):
            PortGroundRealizer("constrained-port", TwoPortArithmeticGate("port-0", 97)).observe(
                INTENTION, _policy("constrained-port", "port"))

    def test_port_rejects_unknown_opcode_and_malformed_frame(self):
        gate = TwoPortArithmeticGate("port-0", GROUND.modulus)
        with self.assertRaises(RealizationRefused):
            gate.invoke("eval_python", {"source": "print(1)"})
        with self.assertRaises(RealizationRefused):
            gate.invoke("compose", {"first": [1,2], "second": [True,1]})

    def test_observation_receipt_rejects_tampered_value_and_ground(self):
        policy = _policy("constrained-port", "port")
        receipt = PortGroundRealizer("constrained-port", TwoPortArithmeticGate("port-0", GROUND.modulus)).observe(INTENTION, policy)
        for key, modified in (("ground", "0"*64), ("coordinate", COORDINATE+1)):
            payload = deepcopy(receipt.payload); payload[key] = modified
            with self.subTest(key=key), self.assertRaises(RealizationRefused):
                verify_receipt(payload, INTENTION, policy)
        payload = deepcopy(receipt.payload); payload["output"]["value"] += 1
        with self.assertRaises(RealizationRefused):
            verify_receipt(payload, INTENTION, policy)

    def test_observation_receipt_rejects_evidence_tampering(self):
        policy = _policy("constrained-port", "port")
        receipt = PortGroundRealizer("constrained-port", TwoPortArithmeticGate("port-0", GROUND.modulus)).observe(INTENTION, policy)
        tampered = deepcopy(receipt.payload)
        tampered["events"][0]["sequence"] = -9
        with self.assertRaises(RealizationRefused):
            verify_receipt(tampered, INTENTION, policy)
        tampered = deepcopy(receipt.payload)
        tampered["evidence"]["physical"] = "attested-real-device"
        with self.assertRaises(RealizationRefused):
            verify_receipt(tampered, INTENTION, policy)

    def test_expired_policy_fails_closed(self):
        expired = RealizationPolicy(frozenset({("constrained-port", "port")}), COORDINATE-1)
        with self.assertRaisesRegex(RealizationRefused, "not permitted"):
            PortGroundRealizer("constrained-port", TwoPortArithmeticGate("port-0", GROUND.modulus)).observe(INTENTION, expired)

    def test_no_boolean_integer_or_unknown_observer(self):
        with self.assertRaises(RealizationRefused):
            AffineGround(True,2,11,0)
        with self.assertRaises(RealizationRefused):
            GroundIntention("intention", GROUND, COORDINATE, "fabricated_state")

    def test_interpreter_equivalent_to_constrained_port(self):
        home, endpoint, profile = _qualified_subprocess()
        with home:
            report = qualify(endpoint, profile, coordinate=5, seed="sab008-interpreter-qualifier")
            self.assertIn("computational_fragment", report.payload["verified_roles"])
            ipolicy = _policy("interpreter-A", "interpreter")
            portpolicy = _policy("constrained-port", "port")
            interpreter = FixedInterpreterRealizer("interpreter-A", endpoint, report.payload, profile).observe(INTENTION, ipolicy)
            port = PortGroundRealizer("constrained-port", TwoPortArithmeticGate("port-0", GROUND.modulus)).observe(INTENTION, portpolicy)
            self.assertTrue(equivalent_observations((port, interpreter), INTENTION,
                         {"port": portpolicy, "interpreter": ipolicy}))
            self.assertNotEqual(port.payload["event_digest"], interpreter.payload["event_digest"])
            self.assertNotEqual(port.payload["method"], interpreter.payload["method"])

    def test_duplicate_realizer_does_not_count_as_cross_substrate_equivalence(self):
        policy = _policy("constrained-port", "port")
        receipt = PortGroundRealizer("constrained-port", TwoPortArithmeticGate("port-0", GROUND.modulus)).observe(INTENTION, policy)
        with self.assertRaisesRegex(RealizationRefused, "not independently"):
            equivalent_observations((receipt, receipt), INTENTION, {"port": policy})

    def test_wrong_interpreter_advertisement_is_refused(self):
        home, endpoint, profile = _qualified_subprocess(wrong=True)
        with home, self.assertRaises(Exception):
            qualify(endpoint, profile, coordinate=5, seed="sab008-interpreter-qualifier")

    def test_mismatched_qualification_identity_is_refused(self):
        home, endpoint, profile = _qualified_subprocess()
        with home:
            report = qualify(endpoint, profile, coordinate=5, seed="sab008-interpreter-qualifier")
            with self.assertRaisesRegex(RealizationRefused, "identity mismatch"):
                FixedInterpreterRealizer("another-host", endpoint, report.payload, profile)

    def test_equivalence_is_not_output_coincidence(self):
        home, endpoint, profile = _qualified_subprocess()
        with home:
            report = qualify(endpoint, profile, coordinate=5, seed="sab008-interpreter-qualifier")
            ipolicy = _policy("interpreter-A", "interpreter")
            portpolicy = _policy("constrained-port", "port")
            interpreter = FixedInterpreterRealizer("interpreter-A", endpoint, report.payload, profile).observe(INTENTION, ipolicy)
            port = PortGroundRealizer("constrained-port", TwoPortArithmeticGate("port-0", GROUND.modulus)).observe(INTENTION, portpolicy)
            altered = GroundIntention("different", GROUND, COORDINATE)
            with self.assertRaises(RealizationRefused):
                equivalent_observations((port, interpreter), altered,
                       {"port": portpolicy, "interpreter": ipolicy})


def _openssl(*args: str) -> None:
    """Issue only harness-controlled test certificates with no committed keys."""
    subprocess.run(("openssl", *args), capture_output=True, check=True)


def _cert(root: Path, ca: Path, name: str, client: bool) -> tuple[Path, Path]:
    """Generate one pinned client or server certificate with explicit SAN."""
    key, csr, crt = (root / (name + extension) for extension in (".key", ".csr", ".crt"))
    _openssl("req", "-new", "-newkey", "rsa:2048", "-nodes",
             "-keyout", str(key), "-out", str(csr), "-subj", f"/CN={name}.sab008.test")
    ext = root / (name + ".ext")
    ext.write_text(f"subjectAltName=DNS:{name}.sab008.test\n"
                   "keyUsage=critical,digitalSignature,keyEncipherment\n"
                   f"extendedKeyUsage={'clientAuth' if client else 'serverAuth'}\n")
    _openssl("x509", "-req", "-in", str(csr), "-CA", str(ca), "-CAkey", str(root/"ca.key"),
             "-CAcreateserial", "-days", "1", "-extfile", str(ext), "-out", str(crt))
    return crt, key


@unittest.skipUnless(HAVE_NATIVE and shutil.which("openssl"),
                     "native E-CPU with mTLS receiver and OpenSSL required")
class FederatedNativeTests(unittest.TestCase):
    """Live mTLS loopback relay and receiver-native Hypervisor integration."""

    @classmethod
    def setUpClass(cls):
        """Create only explicitly permitted listener processes and ephemeral identities."""
        cls.home = tempfile.TemporaryDirectory(prefix="sab008-mtls-")
        cls.root = Path(cls.home.name)
        cls.ca = cls.root/"ca.crt"
        _openssl("req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
                 "-subj", "/CN=SAB008-CA", "-addext", "basicConstraints=critical,CA:TRUE",
                 "-addext", "keyUsage=critical,keyCertSign,cRLSign",
                 "-keyout", str(cls.root/"ca.key"), "-out", str(cls.ca))
        cls.client_cert, cls.client_key = _cert(cls.root, cls.ca, "origin", True)
        cls.servers = {name: _cert(cls.root, cls.ca, name, False) for name in ("gate-relay", "math-host")}
        cls.listeners = {}
        cls.endpoints = {}
        try:
            cls._launch("gate-relay", ("observe", "transfer"))
            cls._launch("math-host", ("observe", "affine_mod"))
        except Exception:
            cls.tearDownClass()
            raise

    @classmethod
    def _launch(cls, name, operations, *, revoke=False):
        """Start one locally installed fixed-vocabulary Hypervisor-capable receiver."""
        cert, key = cls.servers[name]
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        ready = cls.root/(name+".ready")
        storage = cls.root/(name+".store")
        storage.mkdir(exist_ok=True)
        ready.unlink(missing_ok=True)
        argv = [sys.executable, "-m", "mailcpu.federated_placement", "serve",
                "--host-id", name, "--listen-address", "127.0.0.1", "--port", str(port),
                "--certificate", str(cert), "--key", str(key), "--ca-file", str(cls.ca),
                "--client-dns", "origin.sab008.test", "--storage-directory", str(storage),
                "--ready-file", str(ready)]
        for operation in operations:
            argv += ["--allow", operation]
        if revoke:
            argv.append("--revoke-native")
        process = subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        cls.listeners[name] = process
        until = time.monotonic() + 12
        while not ready.exists() and time.monotonic() < until:
            if process.poll() is not None:
                raise RuntimeError("listener failed: " + process.stderr.read().decode()[:800])
            time.sleep(.03)
        if not ready.exists():
            raise RuntimeError("listener startup timed out")
        cls.endpoints[name] = MutualTLSQualificationEndpoint(
            name, ("127.0.0.1", port), server_dns=name+".sab008.test",
            client_certificate=str(cls.client_cert), client_key=str(cls.client_key),
            ca_file=str(cls.ca))

    @classmethod
    def tearDownClass(cls):
        """Stop ephemeral owned processes and destroy their certificate keys."""
        for process in getattr(cls, "listeners", {}).values():
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill(); process.wait(timeout=3)
            if process.stderr:
                process.stderr.close()
        if hasattr(cls, "home"):
            cls.home.cleanup()

    def _qualified(self, host, role):
        """Qualify only the fixed locally authorized role for a pinned TLS identity."""
        profile = QualificationPolicy(frozenset({host}), "sab008-observer", COORDINATE+500,
                 frozenset({"observer", role}),
                 max_calls=4 if role == "computational_fragment" else 2)
        report = qualify(self.endpoints[host], profile, coordinate=5, seed="sab008-mtls-observer")
        self.assertIn(role, report.payload["verified_roles"])
        return profile, report

    def test_three_realizations_share_one_semantic_observation(self):
        """Use port frames, a fresh interpreter, and two TLS peers with native Hypervisor."""
        relay_policy, relay_report = self._qualified("gate-relay", "framed_ipc")
        compute_policy, compute_report = self._qualified("math-host", "computational_fragment")
        federated_policy = _policy("fabric-A", "federated")
        federated = FederatedGroundRealizer(
            "fabric-A", self.endpoints["gate-relay"], self.endpoints["math-host"],
            relay_report.payload, compute_report.payload, relay_policy, compute_policy,
        ).observe(INTENTION, federated_policy)
        home, endpoint, profile = _qualified_subprocess()
        with home:
            interpreter_report = qualify(endpoint, profile, coordinate=5, seed="sab008-interpreter-qualifier")
            interpreter_policy = _policy("interpreter-A", "interpreter")
            interpreter = FixedInterpreterRealizer("interpreter-A", endpoint,
                          interpreter_report.payload, profile).observe(INTENTION, interpreter_policy)
        port_policy = _policy("constrained-port", "port")
        port = PortGroundRealizer("constrained-port", TwoPortArithmeticGate("port-0", GROUND.modulus)).observe(INTENTION, port_policy)
        self.assertTrue(equivalent_observations((port, interpreter, federated), INTENTION,
               {"port": port_policy, "interpreter": interpreter_policy, "federated": federated_policy}))
        self.assertEqual({x.payload["output"]["value"] for x in (port, interpreter, federated)},
                         {independent_observation(INTENTION)})
        self.assertEqual(federated.payload["event_count"], 2)
        self.assertFalse(federated.payload["physical_host_attested"])

    def test_federated_wrong_certificate_identity_refused(self):
        """TLS SAN mismatch is not repaired by a matching self-reported host ID."""
        relay_policy, relay_report = self._qualified("gate-relay", "framed_ipc")
        compute_policy, compute_report = self._qualified("math-host", "computational_fragment")
        good = self.endpoints["math-host"]
        bad = MutualTLSQualificationEndpoint("math-host", good.address,
                server_dns="not-math-host.sab008.test",
                client_certificate=str(self.client_cert), client_key=str(self.client_key), ca_file=str(self.ca))
        with self.assertRaises(RealizationRefused):
            FederatedGroundRealizer("fabric-A", self.endpoints["gate-relay"], bad,
                relay_report.payload, compute_report.payload, relay_policy, compute_policy).observe(
                    INTENTION, _policy("fabric-A", "federated"))

    def test_federated_local_policy_revocation_before_network_request(self):
        """Origin policy refuses before any relay request is transmitted."""
        relay_policy, relay_report = self._qualified("gate-relay", "framed_ipc")
        compute_policy, compute_report = self._qualified("math-host", "computational_fragment")
        with self.assertRaises(RealizationRefused):
            FederatedGroundRealizer("fabric-A", self.endpoints["gate-relay"], self.endpoints["math-host"],
                relay_report.payload, compute_report.payload, relay_policy, compute_policy).observe(
                    INTENTION, RealizationPolicy(frozenset({("other", "federated")}), COORDINATE + 500))


if __name__ == "__main__":
    unittest.main()
