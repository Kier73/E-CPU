"""SAB-003 adversarial tests for actual process restart and role qualification."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest

from mailcpu.runtime_qualification import (
    QualificationPolicy, QualificationRefused, SubprocessQualificationEndpoint,
    ROLES, affine_expected, digest, qualify, verify_report,
)


def policy(roles=ROLES, *, expiry=30, max_calls=8):
    """Provide a locally authorized, finite permission and quota policy."""
    return QualificationPolicy(frozenset({"worker"}), "local-review", expiry,
                               frozenset(roles), max_calls)


class QualificationTests(unittest.TestCase):
    """Check the actual fixed worker process without trusting advertised roles."""

    def setUp(self):
        """Give every test an isolated physical file namespace."""
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)

    def endpoint(self, *flags):
        """Launch a fresh Python interpreter for every bounded request."""
        return SubprocessQualificationEndpoint(
            "worker", (sys.executable, "-m", "mailcpu.runtime_qualification_worker",
                       "--host", "worker", "--directory", str(self.directory), *flags))

    def test_full_role_witness_is_not_full_runtime_or_attestation(self):
        """A separate subprocess stores data and executes a fixed algebraic opcode."""
        report = qualify(self.endpoint(), policy(), coordinate=8, seed="sab003-full-host")
        self.assertTrue(verify_report(report, policy(), coordinate=8))
        self.assertEqual(set(report.payload["verified_roles"]), set(ROLES))
        self.assertEqual(len(report.payload["probes"]), 8)
        self.assertFalse(report.payload["hardware_attested"])
        self.assertFalse(report.payload["full_ecpu_runtime_verified"])
        self.assertFalse(report.payload["local_hypervisor_permission_granted"])
        self.assertNotEqual(report.payload["probes"][5]["response"]["boot"],
                            report.payload["probes"][6]["response"]["boot"])

    def test_volatile_write_not_upgraded_to_post_restart_memory(self):
        """A write acknowledgement does not establish retained state."""
        report = qualify(self.endpoint("--volatile"), policy(), coordinate=8)
        self.assertNotIn("retained_state", report.payload["verified_roles"])
        self.assertEqual(report.payload["statuses"]["retained_state"],
                         "not_recovered_after_restart")

    def test_compute_disabled_is_valid_nonprocessor_host(self):
        """Observed memory and IPC do not imply mathematical execution."""
        report = qualify(self.endpoint("--no-compute"), policy(), coordinate=8)
        self.assertNotIn("computational_fragment", report.payload["verified_roles"])
        self.assertIn("retained_state", report.payload["verified_roles"])

    def test_memory_disabled_is_computational_fragment(self):
        """An interpreter may compute without persistent storage."""
        report = qualify(self.endpoint("--no-storage"), policy(), coordinate=8)
        self.assertIn("computational_fragment", report.payload["verified_roles"])
        self.assertNotIn("retained_state", report.payload["verified_roles"])

    def test_transfer_disabled_does_not_imply_framed_ipc(self):
        """A computational relation does not inherently carry arbitrary bytes."""
        report = qualify(self.endpoint("--no-transfer"), policy(), coordinate=8)
        self.assertNotIn("framed_ipc", report.payload["verified_roles"])
        self.assertIn("computational_fragment", report.payload["verified_roles"])

    def test_wrong_math_fails_closed(self):
        """A successful but false result is contradictory rather than unavailable."""
        with self.assertRaisesRegex(QualificationRefused, "contradictory"):
            qualify(self.endpoint("--wrong-compute"), policy(), coordinate=8)

    def test_dynamic_source_acceptance_fails_closed(self):
        """One unsafe dispatch result invalidates the restricted-opcode claim."""
        with self.assertRaisesRegex(QualificationRefused, "contradictory"):
            qualify(self.endpoint("--unsafe-dispatch"), policy(), coordinate=8)

    def test_corrupt_retained_record_is_refused(self):
        """An altered persisted value cannot be recovered as the original state."""
        p = policy(roles={"observer", "retained_state"}, max_calls=3)
        report = qualify(self.endpoint(), p, coordinate=8, seed="sab003-storage")
        self.assertTrue(verify_report(report, p, coordinate=8))
        saved, = self.directory.glob("*.json")
        changed = json.loads(saved.read_text())
        changed["record"]["value"]["payload"] = [77]
        saved.write_text(json.dumps(changed))
        with self.assertRaises(QualificationRefused):
            qualify(self.endpoint(), p, coordinate=8, seed="sab003-storage")

    def test_expired_or_unauthorized_host_denied_without_io(self):
        """Probe policy prevents contact before any external process launch."""
        with self.assertRaises(QualificationRefused):
            qualify(self.endpoint(), policy(expiry=2), coordinate=8)
        self.assertEqual(list(self.directory.glob("*.json")), [])
        with self.assertRaises(QualificationRefused):
            qualify(self.endpoint(), QualificationPolicy(
                frozenset({"another-host"}), "local-review", 30), coordinate=8)

    def test_insufficient_budget_refused_before_io(self):
        """A truncated probe set may not silently claim full qualification."""
        with self.assertRaisesRegex(QualificationRefused, "quota"):
            qualify(self.endpoint(), policy(max_calls=1), coordinate=8)
        self.assertEqual(list(self.directory.glob("*.json")), [])

    def test_mutating_roles_and_rehashing_does_not_forge_evidence(self):
        """Independent verification recomputes capability decisions from raw probes."""
        p = policy(roles={"observer", "framed_ipc"}, max_calls=2)
        original = qualify(self.endpoint(), p, coordinate=8)
        modified = deepcopy(original.payload)
        modified["verified_roles"].remove("framed_ipc")
        del modified["report_digest"]
        modified["report_digest"] = digest(modified)
        with self.assertRaisesRegex(QualificationRefused, "contradicts"):
            verify_report(modified, p, coordinate=8)

    def test_replayed_probe_nonce_rejected_even_if_report_rehashed(self):
        """Every probe is bound to the host, operation, input and index."""
        p = policy(roles={"observer", "framed_ipc"}, max_calls=2)
        report = qualify(self.endpoint(), p, coordinate=8)
        modified = deepcopy(report.payload)
        modified["probes"][1]["request"]["nonce"] = modified["probes"][0]["request"]["nonce"]
        del modified["report_digest"]
        modified["report_digest"] = digest(modified)
        with self.assertRaisesRegex(QualificationRefused, "correlation"):
            verify_report(modified, p, coordinate=8)

    def test_report_rejected_under_new_policy_or_stale_coordinate(self):
        """Host observations have a bounded authority and time scope."""
        p = policy(roles={"observer"}, max_calls=1)
        report = qualify(self.endpoint(), p, coordinate=8)
        with self.assertRaises(QualificationRefused):
            verify_report(report, p, coordinate=31)
        with self.assertRaises(QualificationRefused):
            verify_report(report, policy(), coordinate=8)

    def test_observer_only_never_probes_compute_or_persistence(self):
        """A locally allowed subset does not become broader authority."""
        p = policy(roles={"observer"}, max_calls=1)
        report = qualify(self.endpoint(), p, coordinate=8)
        self.assertEqual(report.payload["verified_roles"], ["observer"])
        self.assertEqual(len(report.payload["probes"]), 1)
        self.assertEqual(list(self.directory.glob("*.json")), [])

    def test_subprocess_unreachable_refused(self):
        """Unavailable process resources do not become virtual compute hosts."""
        bad = SubprocessQualificationEndpoint("worker", ("__sab003_missing_program__",), timeout=0.2)
        with self.assertRaises(QualificationRefused):
            qualify(bad, policy(roles={"observer"}, max_calls=1), coordinate=8)

    def test_native_ecpu_law_matches_mathematical_probe(self):
        """The fixed host law agrees with E-CPU native long-coordinate navigation."""
        from mailcpu.law_certifier import lcg_navigate
        t = 10**12 + 913
        self.assertEqual(affine_expected(5, 7, 65521, 19, t),
                         lcg_navigate(5, 7, 65521, 19, t))

    def test_qualified_offer_cannot_run_without_native_receiver_binding(self):
        """Finite witness can advertise, but not grant a SAB-001 execution right."""
        from mailcpu.substrate_bootstrap import (
            AdaptiveBootstrap, BootstrapPolicy, BootstrapTask, SubstrateObservation,
        )
        p = policy(roles={"observer", "computational_fragment"}, max_calls=4)
        report = qualify(self.endpoint(), p, coordinate=8)
        resource = report.to_resource()
        self.assertEqual(len(resource.offers), 1)
        inventory = SubstrateObservation((resource,), ())
        admission = BootstrapPolicy(frozenset({("worker", "affine_mod")}), frozenset(), "reviewer")
        runtime = AdaptiveBootstrap(inventory, admission, (), ())
        task = BootstrapTask("no-auto-execution", digest("ground"), "worker", "affine_request",
                             "worker", "affine_result", {}, require_oracle=False)
        with self.assertRaisesRegex(ValueError, "no admitted navigable"):
            runtime.plan(task, coordinate=8)


if __name__ == "__main__":
    unittest.main()
