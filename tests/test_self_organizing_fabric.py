"""SAB-006: adversarial reconciliation against native directory and SAB-004 roles.

The test-only synthetic TLS adapter isolates orchestration checks. SAB-005's
real OpenSSL/mTLS tests independently cover the actual transport authentication.
Remote directory snapshots in this unit fixture enter through the native
*verified-ingress-only* method; this is not a claim of TLS testing here.
"""
from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest
import secrets

from mailcpu.adaptive_placement import CompositeIntent, PlacementAuthority, PlacementRefused, expected_result
from mailcpu.computational_fabric import (
    ComputationalFabricDirectory, ComputationalPeerEndpoint,
    ComputationalPeerSnapshot, ComputationalFabricError,
)
from mailcpu.federated_placement import MutualTLSQualificationEndpoint
from mailcpu.runtime_qualification import (
    QualificationPolicy, QualificationRefused, digest, affine_expected,
)
from mailcpu.self_organizing_fabric import SelfOrganizingFabric, ReconciliationRefused

PEERS = ("calc-fast", "calc-slow", "port-relay", "store-a", "store-b")
KINDS = {"calc-fast": "computational_fragment", "calc-slow": "computational_fragment",
         "port-relay": "framed_ipc", "store-a": "retained_state", "store-b": "retained_state"}
ARGS = {"calc-fast": ("--no-storage", "--no-transfer"),
        "calc-slow": ("--no-storage", "--no-transfer"),
        "port-relay": ("--no-storage", "--no-compute"),
        "store-a": ("--no-compute", "--no-transfer"),
        "store-b": ("--no-compute", "--no-transfer")}
GRANTS = frozenset({("calc-fast", "affine_mod"), ("calc-slow", "affine_mod"),
                    ("port-relay", "transfer"), ("store-a", "retain"),
                    ("store-b", "retain"), ("store-a", "retrieve"),
                    ("store-b", "retrieve")})


class MockTLSEndpoint(MutualTLSQualificationEndpoint):
    """Test-only response bridge, not TLS authentication or a production endpoint."""

    def __init__(self, peer_id: str, command: tuple[str, ...]) -> None:
        """Simulate the strict ABI and stable store with a deliberately fake SAN."""
        self.host_id = peer_id
        self.server_dns = peer_id + ".sab006.test"
        self.address = ("127.0.0.1", 443)
        self.fail = False
        self.calls = 0
        self.saved: dict[str, object] = {}

    def exchange(self, request, *, max_bytes):
        """Return canonical fixed-vocabulary observations, never execute supplied code."""
        self.calls += 1
        if self.fail:
            raise QualificationRefused("test endpoint became unavailable")
        operation = request["operation"]
        payload = request["payload"]
        kind = KINDS[self.host_id]
        good, value, error = True, None, None
        if operation == "observe":
            value = {"word_digest": digest(payload["word"])}
        elif operation == "affine_mod" and kind == "computational_fragment":
            value = {"value": affine_expected(payload["a"], payload["c"], payload["mod"],
                                                 payload["x0"], payload["coordinate"])}
        elif operation == "transfer" and kind == "framed_ipc":
            value = dict(payload)
        elif operation == "retain" and kind == "retained_state":
            key, content = payload["key"], payload["value"]
            if key in self.saved and self.saved[key] != content:
                raise QualificationRefused("immutable test store conflict")
            self.saved[key] = content
            value = {"key": key, "receipt": digest(content)}
        elif operation == "retrieve" and kind == "retained_state":
            if payload["key"] in self.saved:
                value = {"key": payload["key"], "value": self.saved[payload["key"]]}
            else:
                good, error = False, "not_found"
        else:
            good, error = False, "unsupported"
        return {"kind": "mailcpu.sab003.reply.v1", "host": self.host_id,
                "nonce": request["nonce"], "boot": secrets.token_hex(16),
                "ok": good, "result": value, "error": error}


class SelfOrganizingTests(unittest.TestCase):
    """A native anti-rollback directory drives a changing five-host environment."""

    def setUp(self) -> None:
        """Isolate each test's immutable worker storage and logical clock."""
        self.temp = tempfile.TemporaryDirectory(prefix="sab006-")
        self.addCleanup(self.temp.cleanup)
        self.now = 0.0
        self.endpoints: dict[str, MockTLSEndpoint] = {}
        self.dir = ComputationalFabricDirectory(
            "origin", {peer: peer + ".sab006.test" for peer in PEERS},
            monotonic=lambda: self.now,
        )
        for peer in PEERS:
            command = (sys.executable, "-m", "mailcpu.runtime_qualification_worker",
                       "--host", peer, "--directory", str(Path(self.temp.name) / peer), *ARGS[peer])
            self.endpoints[peer] = MockTLSEndpoint(peer, command)
            self.publish(peer, revision=1)
        self.grants = GRANTS
        self.authority = PlacementAuthority(self.grants, expires_at=40)
        self.costs = {("calc-fast", "affine_mod"): 1,
                      ("calc-slow", "affine_mod"): 9,
                      ("store-a", "retain"): 1,
                      ("store-b", "retain"): 5}
        self.intent = CompositeIntent("sab006-" + self._testMethodName, 5, 7, 65521, 19,
                                      10**15 + 137)

    def publish(self, peer: str, *, revision: int, lease: int = 60) -> None:
        """Inject a native snapshot at its already-authenticated ingress for tests."""
        endpoint = ComputationalPeerEndpoint(peer, peer + ".sab006.test", "127.0.0.1", 443)
        snapshot = ComputationalPeerSnapshot(endpoint, revision, lease, (), ())
        self.dir._merge_verified_peer_snapshot(
            snapshot, authenticated_peer_id=peer,
            authenticated_server_name=endpoint.tls_server_name,
        )

    @staticmethod
    def policy(peer: str) -> QualificationPolicy:
        """Supply local probe authorization, never copied from a peer advertisement."""
        role = KINDS[peer]
        return QualificationPolicy(frozenset({peer}), "sab006-test-observer", 40,
                                   frozenset({"observer", role}),
                                   max_calls={"computational_fragment": 4,
                                              "framed_ipc": 2, "retained_state": 3}[role])

    def fabric(self, *, endpoint_for=None) -> SelfOrganizingFabric:
        """Construct one controller whose only discovery input is the native directory."""
        return SelfOrganizingFabric(self.dir,
                                   endpoint_for or (lambda snap: self.endpoints[snap.peer_id]),
                                   self.policy, self.authority, quanta=self.costs)

    def test_qualified_peers_compose_one_navigable_environment(self) -> None:
        """The same Ground spans three specialized simulated response roles."""
        fabric = self.fabric()
        selected = fabric.compile(self.intent, coordinate=7)
        self.assertEqual(selected.placement.assignment,
                         ("calc-fast", "port-relay", "store-a"))
        report = fabric.execute(self.intent, selected, coordinate=7, copies=2)
        self.assertEqual(report["ground"], self.intent.ground)
        self.assertEqual(report["result"], expected_result(self.intent))
        self.assertEqual(report["replicas"], ["store-a", "store-b"])
        self.assertEqual(report["verified_operation_count"], 3)
        self.assertEqual(report["federated_view"], selected.view_fingerprint)

    def test_cached_probes_do_not_reprobe_unchanged_authenticated_revision(self) -> None:
        """A stable snapshot can reuse its finite-witness transcript within the lease."""
        f = self.fabric()
        f.compile(self.intent, coordinate=8)
        first = {key: ep.calls for key, ep in self.endpoints.items()}
        f.compile(self.intent, coordinate=8)
        self.assertEqual(first, {key: ep.calls for key, ep in self.endpoints.items()})

    def test_new_revision_invalidates_old_plan_and_reprobes(self) -> None:
        """Revision change forces fresh role observation and plan reconstruction."""
        f = self.fabric()
        before = f.compile(self.intent, coordinate=9)
        measured = self.endpoints["calc-fast"].calls
        self.publish("calc-fast", revision=2)
        with self.assertRaisesRegex(ReconciliationRefused, "stale"):
            f.execute(self.intent, before, coordinate=9)
        self.assertGreater(self.endpoints["calc-fast"].calls, measured)
        after = f.compile(self.intent, coordinate=9)
        self.assertNotEqual(before.view_fingerprint, after.view_fingerprint)
        self.assertEqual(before.placement.assignment, after.placement.assignment)

    def test_expired_leases_remove_hosts_and_replace_computation(self) -> None:
        """A live host roster loses expired compute-fast, even with cached role evidence."""
        f = self.fabric()
        old = f.compile(self.intent, coordinate=10)
        # Renew all peers *except* the preferred computation host.
        self.now = 56.0
        for peer in PEERS:
            if peer != "calc-fast":
                self.publish(peer, revision=2, lease=60)
        self.now = 61.0
        with self.assertRaisesRegex(ReconciliationRefused, "stale"):
            f.execute(self.intent, old, coordinate=10)
        new = f.compile(self.intent, coordinate=10)
        self.assertEqual(new.placement.assignment[0], "calc-slow")
        self.assertNotEqual(old.placement.fingerprint, new.placement.fingerprint)
        result = f.execute(self.intent, new, coordinate=10)
        self.assertEqual(result["result"], expected_result(self.intent))

    def test_a_stopped_receiver_requires_new_probes_before_use(self) -> None:
        """A failed forced probe excludes the host and requires a new placement."""
        f = self.fabric()
        previous = f.compile(self.intent, coordinate=11)
        self.endpoints["calc-fast"].fail = True
        view = f.refresh(coordinate=11, force_probes=True)
        self.assertNotIn("calc-fast", view.active_hosts)
        with self.assertRaisesRegex(ReconciliationRefused, "stale"):
            f.execute(self.intent, previous, coordinate=11)
        replaced = f.compile(self.intent, coordinate=11)
        self.assertEqual(replaced.placement.assignment[0], "calc-slow")

    def test_receiver_identity_must_match_native_peer(self) -> None:
        """Cross-peer runtime host substitution is rejected before probing."""
        def swap(snap):
            return self.endpoints["store-b"] if snap.peer_id == "calc-fast" else self.endpoints[snap.peer_id]
        with self.assertRaisesRegex(ReconciliationRefused, "host differs"):
            self.fabric(endpoint_for=swap).compile(self.intent, coordinate=12)

    def test_runtime_tls_identity_must_match_native_directory(self) -> None:
        """A peer at the same IP but a different DNS SAN is not the same host."""
        self.endpoints["calc-fast"].server_dns = "not-the-same.sab006.test"
        with self.assertRaisesRegex(ReconciliationRefused, "TLS identity"):
            self.fabric().compile(self.intent, coordinate=13)

    def test_runtime_port_must_match_native_directory(self) -> None:
        """A same-host same-SAN alternate port is a distinct service and refused."""
        self.endpoints["calc-fast"].address = ("127.0.0.1", 444)
        with self.assertRaisesRegex(ReconciliationRefused, "TLS identity/address"):
            self.fabric().compile(self.intent, coordinate=13)

    def test_expired_local_grant_forbids_recompilation(self) -> None:
        """Fresh peer evidence is insufficient without locally valid operation grants."""
        f = self.fabric()
        selected = f.compile(self.intent, coordinate=14)
        f.authority = PlacementAuthority(self.grants - {("calc-fast", "affine_mod")}, 40)
        with self.assertRaisesRegex(ReconciliationRefused, "stale"):
            f.execute(self.intent, selected, coordinate=14)
        new = f.compile(self.intent, coordinate=14)
        self.assertEqual(new.placement.assignment[0], "calc-slow")

    def test_native_directory_rejects_revision_rollback_and_equivocation(self) -> None:
        """The native authenticated-ingress rules preserve monotonic peer lineage."""
        with self.assertRaises(ComputationalFabricError):
            self.publish("store-a", revision=0)
        with self.assertRaises(ComputationalFabricError):
            self.publish("store-a", revision=1, lease=20)

    def test_recovered_checkpoint_survives_compute_and_relay_disappearance(self) -> None:
        """Read a committed result from one live replica without reentering dead services."""
        f = self.fabric()
        p = f.compile(self.intent, coordinate=15)
        saved = f.execute(self.intent, p, coordinate=15, copies=2)
        count_before = {host: self.endpoints[host].calls for host in ("calc-fast", "port-relay")}
        self.now = 57.0
        for host in ("store-a", "store-b"):
            self.publish(host, revision=2)
        self.now = 61.0
        replay = f.resume(self.intent, coordinate=15)
        self.assertEqual(replay["result"], saved["result"])
        self.assertFalse(replay["reexecuted_computation"])
        self.assertEqual(count_before,
                         {host: self.endpoints[host].calls for host in count_before})

    def test_directory_restart_does_not_restore_live_remote_leases(self) -> None:
        """The native checkpoint preserves anti-rollback, but not authentication."""
        before = self.dir.checkpoint()
        resumed = ComputationalFabricDirectory.from_checkpoint(before, monotonic=lambda: self.now)
        self.assertEqual(resumed.active_snapshots, ())
        self.assertEqual(resumed.peer_revision_high_water, self.dir.peer_revision_high_water)
        f = SelfOrganizingFabric(resumed,
                                lambda snap: self.endpoints[snap.peer_id],
                                self.policy, self.authority, quanta=self.costs)
        with self.assertRaises(PlacementRefused):
            f.compile(self.intent, coordinate=16)

    def test_ungranted_advertisement_never_becomes_capability(self) -> None:
        """A peer's presence is discovery, not authority to execute source or compute."""
        f = self.fabric()
        f.authority = PlacementAuthority(frozenset({("store-a", "retrieve")}), 40)
        view = f.reconcile(coordinate=17)
        self.assertEqual(view.active_hosts, ("store-a",))
        with self.assertRaises(PlacementRefused):
            f.compile(self.intent, coordinate=17)


if __name__ == "__main__":
    unittest.main()