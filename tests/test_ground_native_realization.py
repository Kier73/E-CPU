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

