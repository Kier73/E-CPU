"""SAB-002: active probes, finite-witness law recognition and portable-host binding."""

from __future__ import annotations

from dataclasses import replace
import json
import os
import subprocess
import sys
import unittest

from mailcpu.active_ground_discovery import (
    DiscoveryRefused, GroundAdmission, GroundCandidate, ObservedCodeHost,
    ProbeAuthority, PROBE_COORDINATES, SubprocessObserver, discover,
)
from mailcpu.substrate_bootstrap import (
    AdaptiveBootstrap, BootstrapPolicy, BootstrapRefused, BootstrapTask,
    CarrierBinding, ChannelObservation, OperationOffer, RealizerBinding,
    ResourceObservation, SubstrateObservation, digest, verify_bootstrap_report,
)

A, C, MOD, X0 = 5, 7, 65521, 19
GROUND_TIME = 5


def reference(t):
    """Fixture oracle using independent affine-map composition, not the probe code."""
    p, q, mul, add = 1, 0, A, C
    while t:
        if t & 1:
            p, q = mul * p % MOD, (mul * q + add) % MOD
        add = (mul * add + add) % MOD
        mul = mul * mul % MOD
        t >>= 1
    return (p * X0 + q) % MOD


def host(host_id="worker", observe=reference, expires=30):
    """Create a permissive physical-description-neutral observation interface."""
    return ObservedCodeHost(host_id, "unfamiliar-code-and-data", MOD, "approved-probe", expires, observe)


def authority(*ids):
    """Permit only requested endpoints, not their advertised capabilities."""
    return ProbeAuthority(frozenset(ids or ("worker",)), "approved-probe")


def ground(host_id="worker", observe=reference, expires=30):
    """Recognize a finite-witness candidate under explicit local probe permission."""
    return discover(host(host_id, observe, expires), authority(host_id), coordinate=GROUND_TIME)


def channel(label, source, destination, carries, cost=1):
    """Build a directed observed channel with no implied processing power."""
    return ChannelObservation(label, source, destination, (carries,), cost, 5, 30,
                              digest({"channel": label}), 8192)


def bootstrap(candidate):
    """Route request -> admissible learned-law host -> checker using local binding."""
    checking = RealizerBinding("checker", "check", lambda data: {
        "checked_value": data["value"], "coordinate": data["coordinate"]},
        digest("trusted-check-v1"), lambda data, value: value == {
            "checked_value": data["value"], "coordinate": data["coordinate"]})
    resources = (
        ResourceObservation("ingress", "input-port", 5, 30, "approved-probe", digest("ingress")),
        candidate.to_resource(),
        ResourceObservation("checker", "trusted-observer", 5, 30, "approved-probe",
                            digest("checker"), (OperationOffer("check", "state_observation", "verified", 1),)),
    )
    channels = (
        channel("request", "ingress", candidate.host_id, "ground_query"),
        channel("result", candidate.host_id, "checker", "state_observation"),
    )
    admission = GroundAdmission(frozenset({(candidate.host_id, candidate.ground_digest)}), "receiver")
    bindings = (admission.bind(candidate, coordinate=GROUND_TIME), checking)
    carriers = tuple(CarrierBinding(edge.channel_id, lambda data, t: data, digest(edge.channel_id))
                     for edge in channels)
    policy = BootstrapPolicy(frozenset({(candidate.host_id, "navigate.affine_mod"), ("checker", "check")}),
                             frozenset(x.channel_id for x in channels), "receiver")
    inventory = SubstrateObservation(resources, channels)
    task = BootstrapTask("same-semantic-intention", candidate.ground_digest,
                         "ingress", "ground_query", "checker", "verified",
                         {"ground": candidate.ground_digest, "coordinate": 10**15 + 137},
                         require_oracle=True)
    runtime = AdaptiveBootstrap(inventory, policy, bindings, carriers)
    return runtime, task


class ProbeTests(unittest.TestCase):
    """Strict proof/authority boundary and adversarial empirical law discovery."""

    def test_infers_true_law_and_tracks_only_finite_verification(self):
        """Check recovered parameters, exact transcript and finite evidence grade."""
        c = ground()
        self.assertEqual((c.a, c.c, c.x0, c.modulus), (A, C, X0, MOD))
        self.assertEqual(c.verification, "finite_witness_only")
        self.assertEqual(tuple(x[0] for x in c.witness), PROBE_COORDINATES)
        self.assertEqual(c.transcript_digest, digest(c.transcript()))

    def test_large_navigation_matches_independent_reference(self):
        """Jump above a trillion without enumerating intervening coordinates."""
        c = ground()
        self.assertEqual(c.navigate(10**15 + 137), reference(10**15 + 137))
        self.assertEqual(c.navigate(0), X0)

    def test_probe_uses_declared_budget_and_exact_schedule(self):
        """Record the fixed holdout schedule and prevent arbitrary probing."""
        observed = []
        c = ground(observe=lambda t: observed.append(t) or reference(t))
        self.assertEqual(tuple(observed), PROBE_COORDINATES)
        self.assertEqual(len(c.witness), 8)

    def test_unlisted_host_refused_before_observation(self):
        """Never contact a host excluded from local probe authority."""
        calls = []
        with self.assertRaisesRegex(DiscoveryRefused, "authorization"):
            discover(host("unknown", lambda t: calls.append(t) or 0), authority("worker"), coordinate=5)
        self.assertFalse(calls)

    def test_observer_identity_mismatch_refused_before_observation(self):
        """Do not silently treat a differently named observer as trusted."""
        h = replace(host(), observer_id="other")
        with self.assertRaisesRegex(DiscoveryRefused, "authorization"):
            discover(h, authority("worker"), coordinate=5)

    def test_expired_host_refuses_before_io(self):
        """A stale capability observation cannot bootstrap a new Ground."""
        calls = []
        with self.assertRaisesRegex(DiscoveryRefused, "expired"):
            discover(host(observe=lambda t: calls.append(t) or 0, expires=3), authority("worker"), coordinate=5)
        self.assertFalse(calls)

    def test_non_affine_trace_rejected_by_withheld_samples(self):
        """Reject plausible initial fitting that breaks at an independent coordinate."""
        def deceit(t):
            return (reference(t) + (1 if t == 11 else 0)) % MOD
        with self.assertRaisesRegex(DiscoveryRefused, "contradicts"):
            ground(observe=deceit)

    def test_nondeterministic_observation_rejected_by_repeated_coordinate(self):
        """Repeated coordinate in one active probe detects changing behavior."""
        observed = {}
        def mutable(t):
            observed[t] = observed.get(t, 0) + 1
            return (reference(t) + (1 if observed[t] > 1 else 0)) % MOD
        with self.assertRaisesRegex(DiscoveryRefused, "contradicts"):
            ground(observe=mutable)

    def test_ambiguous_parameters_refused(self):
        """A constant trace never establishes a unique affine transition."""
        with self.assertRaisesRegex(DiscoveryRefused, "uniquely"):
            ground(observe=lambda t: 12)

    def test_wrong_type_and_out_of_range_observation_refused(self):
        """Boolean and overflow are not legal witnessed values."""
        for result in (True, -1, MOD, "4"):
            with self.subTest(result=result), self.assertRaises(DiscoveryRefused):
                ground(observe=lambda t, v=result: v)

    def test_witness_tamper_rejected(self):
        """An altered transcript, law or witness invalidates candidate identity."""
        c = ground()
        for change in ({"a": 6}, {"transcript_digest": "0" * 64},
                       {"witness": c.witness[:-1] + ((7, 123),)}):
            with self.subTest(change=change), self.assertRaises(DiscoveryRefused):
                replace(c, **change)

    def test_finite_witness_cannot_prove_unseen_coordinates(self):
        """Deliberately expose a law that lies outside all fixed probe witnesses."""
        hidden = 10**15 + 137
        deceit = lambda t: (reference(t) + (1 if t == hidden else 0)) % MOD
        candidate = ground(observe=deceit)
        self.assertEqual(candidate.verification, "finite_witness_only")
        self.assertNotEqual(candidate.navigate(hidden), deceit(hidden))

    def test_ground_is_independent_of_host_placement(self):
        """Different observers of the same law recover the same Ground identity."""
        self.assertEqual(ground("one").ground_digest, ground("two").ground_digest)
        self.assertNotEqual(ground("one").transcript_digest, ground("two").transcript_digest)

    def test_candidate_does_not_authorize_itself(self):
        """The local admitter must explicitly name the exact host AND Ground."""
        c = ground()
        for allowed in (frozenset(), frozenset({("other", c.ground_digest)}),
                        frozenset({("worker", "0" * 64)})):
            with self.assertRaisesRegex(DiscoveryRefused, "admission"):
                GroundAdmission(allowed, "receiver").bind(c, coordinate=5)

    def test_admission_lease_cannot_be_bypassed(self):
        """Refuse binding after the witnessed capability expired."""
        c = ground(expires=5)
        with self.assertRaisesRegex(DiscoveryRefused, "expired"):
            GroundAdmission(frozenset({("worker", c.ground_digest)}), "receiver").bind(c, coordinate=6)

    def test_admitted_realizer_rejects_wrong_ground_and_input(self):
        """Data-only requests remain pinned to the exact admitted law."""
        c = ground()
        b = GroundAdmission(frozenset({("worker", c.ground_digest)}), "receiver").bind(c, coordinate=5)
        for payload in ({"ground": "0" * 64, "coordinate": 3}, {"coordinate": 3},
                        {"ground": c.ground_digest, "coordinate": True}):
            with self.assertRaises(DiscoveryRefused):
                b.handler(payload)
        self.assertFalse(b.oracle({"ground": c.ground_digest, "coordinate": 10}, {"value": 5}))

    def test_subprocess_observer_executes_actual_separate_interpreter(self):
        """Probe a preinstalled code+data program as a distinct process, not a VM claim."""
        command = (sys.executable, "-m", "mailcpu.probe_worker", "--host", "worker",
                   "--a", str(A), "--c", str(C), "--mod", str(MOD), "--x0", str(X0))
        remote = SubprocessObserver(command, "worker")
        c = ground(observe=remote.observe)
        self.assertEqual(c.ground_digest, ground().ground_digest)
        self.assertEqual(c.navigate(10**14 + 13), reference(10**14 + 13))

    def test_subprocess_spoofed_response_rejected(self):
        """A JSON response cannot substitute another host or requested coordinate."""
        command = (sys.executable, "-c", "import json;print(json.dumps({'kind':'sab002.observation','host':'other','coordinate':0,'value':1}))")
        with self.assertRaisesRegex(DiscoveryRefused, "identity"):
            SubprocessObserver(command, "worker").observe(0)

    def test_subprocess_timeout_is_bounded(self):
        """An indefinitely sleeping host cannot hang the discovery process."""
        command = (sys.executable, "-c", "import time;time.sleep(2)")
        with self.assertRaisesRegex(DiscoveryRefused, "did not complete"):
            SubprocessObserver(command, "worker", timeout=0.1).observe(0)

    def test_resource_offer_not_executable_without_local_admission(self):
        """A discovered offer is only descriptive; SAB-001 still checks receiver policy."""
        c = ground()
        observer = c.to_resource()
        self.assertEqual(observer.offers[0].operation, "navigate.affine_mod")
        runtime, task = bootstrap(c)
        no_rights = AdaptiveBootstrap(runtime.inventory,
                                      BootstrapPolicy(frozenset(), runtime.policy.allowed_channels, "receiver"),
                                      tuple(runtime.realizers.values()), tuple(runtime.carriers.values()))
        with self.assertRaises(BootstrapRefused):
            no_rights.plan(task, coordinate=5)

    def test_end_to_end_multihost_bootstrap_and_replay_check(self):
        """Compile discovered Ground into SAB-001 typed carrier and realizer path."""
        c = ground()
        runtime, task = bootstrap(c)
        plan = runtime.plan(task, coordinate=5)
        report = runtime.execute(task, plan, coordinate=5)
        self.assertEqual(report["output"], {"checked_value": reference(10**15 + 137),
                                            "coordinate": 10**15 + 137})
        self.assertEqual(report["ground_digest"], c.ground_digest)
        self.assertTrue(report["receiver_oracle_checked_steps"])
        self.assertFalse(report["physical_independence_attested"])
        self.assertTrue(verify_bootstrap_report(report, task, plan))

    def test_rebootstrap_after_loss_preserves_semantics(self):
        """Re-observe different placement; keep law/intent/result while route changes."""
        a, b = ground("primary"), ground("secondary")
        runtime_a, task_a = bootstrap(a)
        runtime_b, task_b = bootstrap(b)
        report_a = runtime_a.execute(task_a, runtime_a.plan(task_a, coordinate=5), coordinate=5)
        report_b = runtime_b.execute(task_b, runtime_b.plan(task_b, coordinate=5), coordinate=5)
        self.assertEqual(task_a.ground_digest, task_b.ground_digest)
        self.assertEqual(report_a["output"], report_b["output"])
        self.assertNotEqual(report_a["inventory_digest"], report_b["inventory_digest"])
        with self.assertRaises(BootstrapRefused):
            runtime_b.execute(task_a, runtime_a.plan(task_a, coordinate=5), coordinate=5)


if __name__ == "__main__":
    unittest.main()
