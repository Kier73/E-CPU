"""SAB-004: separate-process qualification, typed composition and durable re-placement."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import json
import sys
import tempfile
import unittest

from mailcpu.adaptive_placement import (
    AdaptivePlacement, CompositeIntent, PlacementAuthority, PlacementRefused,
    QualifiedHost, checkpoint_record, expected_result,
)
from mailcpu.runtime_qualification import (
    QualificationPolicy, SubprocessQualificationEndpoint, digest, qualify,
)


class AdaptivePlacementTests(unittest.TestCase):
    """Five isolated worker data directories and separate Python processes per exchange."""

    @classmethod
    def setUpClass(cls) -> None:
        """Qualify each fixed-vocabulary host once, then reuse witnessed profiles."""
        cls.temp = tempfile.TemporaryDirectory()
        cls.hosts = {}
        for name, role, extras in (
            ("calc-fast", "computational_fragment", ("--no-storage", "--no-transfer")),
            ("calc-slow", "computational_fragment", ("--no-storage", "--no-transfer")),
            ("port-relay", "framed_ipc", ("--no-storage", "--no-compute")),
            ("store-a", "retained_state", ("--no-compute", "--no-transfer")),
            ("store-b", "retained_state", ("--no-compute", "--no-transfer")),
        ):
            directory = Path(cls.temp.name) / name
            endpoint = cls.endpoint(name, directory, *extras)
            calls = {"computational_fragment": 4, "framed_ipc": 2, "retained_state": 3}[role]
            p = QualificationPolicy(frozenset({name}), "sab004-observer", 50,
                                    frozenset({"observer", role}), max_calls=calls)
            report = qualify(endpoint, p, coordinate=5, seed="sab004-known-owned-probe")
            assert role in report.payload["verified_roles"]
            cls.hosts[name] = QualifiedHost(endpoint, report.payload, p)

    @classmethod
    def tearDownClass(cls) -> None:
        """Dispose the owned storage directories after the process tests."""
        cls.temp.cleanup()

    @staticmethod
    def endpoint(name, directory, *extra):
        """Launch one fresh executable interpreter for each bounded worker exchange."""
        argv = (sys.executable, "-m", "mailcpu.runtime_qualification_worker", "--host", name,
                "--directory", str(directory), *extra)
        return SubprocessQualificationEndpoint(name, argv)

    def setUp(self) -> None:
        """Keep task identities distinct so intentional partial writes do not affect peers."""
        self.intent = CompositeIntent(self._testMethodName, 5, 7, 65521, 19, 10**15 + 137)
        self.grants = frozenset({("calc-fast", "affine_mod"), ("calc-slow", "affine_mod"),
                                 ("port-relay", "transfer"), ("store-a", "retain"),
                                 ("store-b", "retain"), ("store-a", "retrieve"),
                                 ("store-b", "retrieve")})
        self.authority = PlacementAuthority(self.grants, expires_at=40)
        self.costs = {("calc-fast", "affine_mod"): 1, ("calc-slow", "affine_mod"): 9,
                      ("store-a", "retain"): 1, ("store-b", "retain"): 5}
        self.all_hosts = tuple(sorted(self.hosts))

    def controller(self, *, hosts=None, grants=None, costs=None, expiry=40):
        """Construct a fresh controller with no inherited in-memory execution state."""
        selected_hosts = self.hosts if hosts is None else hosts
        operation_costs = self.costs if costs is None else costs
        return AdaptivePlacement(selected_hosts,
                                 PlacementAuthority(self.grants if grants is None else grants,
                                                    expires_at=expiry),
                                 quanta={key: value for key, value in operation_costs.items()
                                         if key[0] in selected_hosts})

    def test_distinct_qualifications_compose_with_real_sab001_plan(self) -> None:
        """A CPU fragment, framed IPC endpoint and retained-state host form one route."""
        run = self.controller()
        placed = run.compile(self.intent, active_hosts=self.all_hosts, coordinate=6)
        self.assertEqual(placed.assignment, ("calc-fast", "port-relay", "store-a"))
        self.assertEqual([s.operation for s in placed.plan.steps if s.kind == "realize"],
                         ["affine_mod", "transfer", "retain"])
        outcome = run.execute(self.intent, placed, active_hosts=self.all_hosts, coordinate=6)
        self.assertEqual(outcome["result"], expected_result(self.intent))
        self.assertEqual(outcome["verified_operation_count"], 3)
        self.assertTrue(outcome["complete"])
        self.assertEqual(outcome["replicas"], ["store-a"])
        self.assertGreater(outcome["measured_controller_ns"], 0)
        self.assertFalse(outcome["remote_hypervisor_authority_granted"])
        self.assertFalse(outcome["independent_physical_hosts_attested"])

    def test_replication_and_new_controller_restore_without_computation(self) -> None:
        """Two freshly launched storage workers recover after the original compute host vanishes."""
        first = self.controller()
        p = first.compile(self.intent, active_hosts=self.all_hosts, coordinate=7)
        completed = first.execute(self.intent, p, active_hosts=self.all_hosts, coordinate=7, copies=2)
        self.assertEqual(set(completed["replicas"]), {"store-a", "store-b"})
        second = self.controller(hosts={k:v for k,v in self.hosts.items() if k.startswith("store-")})
        resumed = second.resume(self.intent, active_hosts=("store-b",), coordinate=8)
        self.assertEqual(resumed["result"], completed["result"])
        self.assertEqual(resumed["decision_digest"], completed["decision_digest"])
        self.assertFalse(resumed["reexecuted_computation"])

    def test_missing_compute_replans_without_changing_mathematical_intention(self) -> None:
        """Recompile over available operations; original plan fails stale before side effects."""
        controller = self.controller()
        before = controller.compile(self.intent, active_hosts=self.all_hosts, coordinate=10)
        without_fast = tuple(x for x in self.all_hosts if x != "calc-fast")
        with self.assertRaisesRegex(PlacementRefused, "stale"):
            controller.execute(self.intent, before, active_hosts=without_fast, coordinate=10)
        after = controller.compile(self.intent, active_hosts=without_fast, coordinate=10)
        self.assertEqual(after.assignment[0], "calc-slow")
        report = controller.execute(self.intent, after, active_hosts=without_fast, coordinate=10)
        self.assertEqual(report["result"], expected_result(self.intent))
        self.assertEqual(report["ground"], self.intent.ground)
        self.assertNotEqual(before.plan.fingerprint, after.plan.fingerprint)

    def test_no_false_commit_if_replica_requirement_cannot_be_met(self) -> None:
        """A prepared primary checkpoint is not a committed result without a decision."""
        active = ("calc-fast", "port-relay", "store-a")
        run = self.controller()
        placed = run.compile(self.intent, active_hosts=active, coordinate=11)
        with self.assertRaisesRegex(PlacementRefused, "required durable replica"):
            run.execute(self.intent, placed, active_hosts=active, coordinate=11, copies=2)
        with self.assertRaisesRegex(PlacementRefused, "no stored checkpoint verified"):
            self.controller().resume(self.intent, active_hosts=("store-a",), coordinate=11)

    def test_pure_retry_and_immutable_storage_replay_are_idempotent(self) -> None:
        """Same intention replays fixed pure results and immutable retention addresses."""
        run = self.controller()
        p = run.compile(self.intent, active_hosts=self.all_hosts, coordinate=12)
        a = run.execute(self.intent, p, active_hosts=self.all_hosts, coordinate=12)
        b = run.execute(self.intent, p, active_hosts=self.all_hosts, coordinate=12)
        self.assertEqual(a["checkpoint_digest"], b["checkpoint_digest"])
        self.assertEqual(a["decision_digest"], b["decision_digest"])
        self.assertEqual(a["result"], b["result"])

    def test_readback_grant_required_before_any_storage_write(self) -> None:
        """An admitted write-only endpoint is not mistaken for a recoverable store."""
        grants = self.grants - {("store-a", "retrieve"), ("store-b", "retrieve")}
        run = self.controller(grants=frozenset(grants))
        with self.assertRaisesRegex(PlacementRefused, "no admitted"):
            run.compile(self.intent, active_hosts=self.all_hosts, coordinate=13)

    def test_corrupt_commit_decision_refuses_recovery(self) -> None:
        """Even a correct data record cannot authorize itself after decision corruption."""
        active = ("calc-fast", "port-relay", "store-a")
        run = self.controller()
        p = run.compile(self.intent, active_hosts=active, coordinate=26)
        run.execute(self.intent, p, active_hosts=active, coordinate=26)
        marker_path = Path(self.temp.name)/"store-a"/(self.intent.decision_key+".json")
        original = json.loads(marker_path.read_text())
        original["record"]["value"]["required"] = 8
        marker_path.write_text(json.dumps(original))
        with self.assertRaisesRegex(PlacementRefused, "no stored checkpoint verified"):
            self.controller().resume(self.intent, active_hosts=("store-a",), coordinate=27)

    def test_partial_preparation_can_be_committed_on_pure_retry(self) -> None:
        """A local crash after data write can be retried without conflicting immutable bytes."""
        run = self.controller()
        record = checkpoint_record(self.intent, expected_result(self.intent))
        run._store("store-a", self.intent, record)
        active = ("calc-fast", "port-relay", "store-a")
        p = run.compile(self.intent, active_hosts=active, coordinate=28)
        report = run.execute(self.intent, p, active_hosts=active, coordinate=28)
        resumed = self.controller().resume(self.intent, active_hosts=("store-a",), coordinate=29)
        self.assertEqual(resumed["result"], report["result"])
        self.assertEqual(resumed["decision_digest"], report["decision_digest"])

    def test_permission_not_inferred_from_successful_host_probe(self) -> None:
        """A verified computational role cannot run unless a receiver grant exists."""
        grant = self.grants - {("port-relay", "transfer")}
        run = self.controller(grants=frozenset(grant))
        with self.assertRaisesRegex(PlacementRefused, "no admitted"):
            run.compile(self.intent, active_hosts=self.all_hosts, coordinate=13)

    def test_no_passive_host_promoted_to_computer(self) -> None:
        """Only observed and permitted roles generate executable operation edges."""
        without_cpu = ("port-relay", "store-a", "store-b")
        with self.assertRaises(PlacementRefused):
            self.controller().compile(self.intent, active_hosts=without_cpu, coordinate=14)

    def test_unqualified_host_name_refused_before_execution(self) -> None:
        """A newly seen name does not imply a new executable placement."""
        with self.assertRaisesRegex(PlacementRefused, "unknown"):
            self.controller().compile(self.intent, active_hosts=self.all_hosts+("untrusted",), coordinate=15)

    def test_lease_expiry_refuses_without_touching_worker(self) -> None:
        """The qualification and local execution leases must both be current."""
        with self.assertRaisesRegex(PlacementRefused, "expired"):
            self.controller(expiry=10).compile(self.intent, active_hosts=self.all_hosts, coordinate=20)
        with self.assertRaises(PlacementRefused):
            self.controller().compile(self.intent, active_hosts=self.all_hosts, coordinate=51)

    def test_wrong_computing_worker_caught_by_native_ground_oracle(self) -> None:
        """A post-qualification switched implementation cannot publish wrong arithmetic."""
        original = self.hosts["calc-fast"]
        bad = self.endpoint("calc-fast", Path(self.temp.name)/"calc-fast",
                            "--no-storage", "--no-transfer", "--wrong-compute")
        qualified = QualifiedHost(bad, original.report, original.policy)
        hosts = dict(self.hosts)
        hosts["calc-fast"] = qualified
        run = self.controller(hosts=hosts)
        placed = run.compile(self.intent, active_hosts=self.all_hosts, coordinate=16)
        with self.assertRaisesRegex(ValueError, "independent check rejected"):
            run.execute(self.intent, placed, active_hosts=self.all_hosts, coordinate=16)

    def test_changed_role_report_rejected_even_if_rehashed(self) -> None:
        """An adversary cannot upgrade storage to computation by rewriting a digest."""
        original = self.hosts["store-a"]
        forged = deepcopy(original.report)
        forged["verified_roles"].append("computational_fragment")
        forged.pop("report_digest")
        forged["report_digest"] = digest(forged)
        hosts = dict(self.hosts)
        hosts["store-a"] = QualifiedHost(original.endpoint, forged, original.policy)
        with self.assertRaisesRegex(PlacementRefused, "qualification"):
            self.controller(hosts=hosts).compile(self.intent, active_hosts=self.all_hosts, coordinate=17)

    def test_revoked_grant_stales_existing_placement(self) -> None:
        """An old route witness never transfers authority after policy is changed."""
        previous = self.controller()
        plan = previous.compile(self.intent, active_hosts=self.all_hosts, coordinate=18)
        updated = self.controller(grants=self.grants - {("calc-fast", "affine_mod")})
        with self.assertRaises(PlacementRefused):
            updated.execute(self.intent, plan, active_hosts=self.all_hosts, coordinate=18)

    def test_changed_declared_cost_selects_new_realizer(self) -> None:
        """Placement follows permitted observed roles and current costs, not fixed host names."""
        cost = dict(self.costs)
        cost["calc-fast", "affine_mod"] = 100
        plan = self.controller(costs=cost).compile(self.intent, active_hosts=self.all_hosts, coordinate=19)
        self.assertEqual(plan.assignment[0], "calc-slow")
        self.assertEqual(plan.task.ground_digest, self.intent.ground)

    def test_corrupt_checkpoint_record_cannot_be_recovered(self) -> None:
        """A post-commit byte mutation fails closed at recovery even without a second host."""
        run = self.controller()
        active = ("calc-fast", "port-relay", "store-a")
        plan = run.compile(self.intent, active_hosts=active, coordinate=20)
        run.execute(self.intent, plan, active_hosts=active, coordinate=20)
        path = Path(self.temp.name)/"store-a"/(self.intent.storage_key+".json")
        saved = json.loads(path.read_text())
        saved["record"]["value"]["result"]["value"] ^= 1
        path.write_text(json.dumps(saved))
        with self.assertRaisesRegex(PlacementRefused, "no stored checkpoint verified"):
            self.controller().resume(self.intent, active_hosts=("store-a",), coordinate=20)

    def test_restore_requires_a_durable_commit_decision_not_just_data(self) -> None:
        """Prepared records and uncorrelated storage reads cannot impersonate committed work."""
        record = checkpoint_record(self.intent, expected_result(self.intent))
        run = self.controller()
        run._store("store-a", self.intent, record)
        with self.assertRaises(PlacementRefused):
            self.controller().resume(self.intent, active_hosts=("store-a",), coordinate=21)

    def test_replica_count_and_storage_endpoint_are_not_physical_attestation(self) -> None:
        """The experiment never upgrades distinct processes to independent physical hardware."""
        run = self.controller()
        plan = run.compile(self.intent, active_hosts=self.all_hosts, coordinate=22)
        report = run.execute(self.intent, plan, active_hosts=self.all_hosts, coordinate=22, copies=2)
        self.assertEqual(report["replicas"], ["store-a", "store-b"])
        self.assertFalse(report["independent_physical_hosts_attested"])
        self.assertFalse(report["remote_hypervisor_authority_granted"])

    def test_out_of_domain_intention_fails_before_any_host_io(self) -> None:
        """Malformed parameters never enter qualification-derived placement."""
        with self.assertRaises(PlacementRefused):
            CompositeIntent("bad", 0, 0, 2, 0, -1)
        with self.assertRaises(PlacementRefused):
            CompositeIntent("bad", 0, 0, 1, 0, 1)

    def test_role_labels_not_used_as_hardware_type_assumptions(self) -> None:
        """A CPU-like name is irrelevant when no probed computing role is available."""
        self.assertEqual(self.hosts["store-a"].validate(coordinate=23),
                         frozenset({"observer", "retained_state"}))
        self.assertEqual(self.hosts["calc-fast"].validate(coordinate=23),
                         frozenset({"observer", "computational_fragment"}))


if __name__ == "__main__":
    unittest.main()
