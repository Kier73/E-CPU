"""SAB-001 fail-closed observer bootstrap and adaptive-realization contracts."""

from __future__ import annotations

from dataclasses import replace
import json
import unittest

from mailcpu.substrate_bootstrap import (
    AdaptiveBootstrap, BootstrapPolicy, BootstrapRefused, BootstrapTask,
    CarrierBinding, ChannelObservation, OperationOffer, RealizerBinding,
    ResourceObservation, SubstrateObservation, digest, owned_network_carriers,
    owned_network_probe, verify_bootstrap_report,
)


GROUND = digest({"kind": "synthetic-arithmetic-ground", "law": "x(t)=x0+step*t (mod m)"})
INPUT = {"seed": 29, "step": 7, "mod": 65521, "coordinate": 10**15 + 137}


def _value(data):
    """Use direct modular arithmetic as one locally installed realization."""
    return {"value": (data["seed"] + data["step"] * data["coordinate"]) % data["mod"],
            "coordinate": data["coordinate"]}


def _check(previous, result):
    """Independent arithmetic check of the output from its typed input."""
    return result == _value(previous)


def _verify(value):
    """Convert observed state to an explicitly checked observation."""
    return {"verified_value": value["value"], "at": value["coordinate"]}


def _verify_check(previous, result):
    """Recheck the projection without trusting the asserted output tag."""
    return result == {"verified_value": previous["value"], "at": previous["coordinate"]}


def obs(host, offers=(), hint="arbitrary-resource", epoch=2, expires=30):
    """Create one observation without treating its sensor claim as authority."""
    return ResourceObservation(host, hint, epoch, expires, "local-prober",
                               digest({"seen": host, "at": epoch}), tuple(offers))


def ch(channel, source, target, tag, cost=1, epoch=2, expires=30, budget=8192):
    """Create an observed one-way information path with finite cost."""
    return ChannelObservation(channel, source, target, (tag,), cost, epoch, expires,
                              digest({"path": channel, "at": epoch}), budget)


def _fixture(*, alternatives=True, include_compute=True, hint="local-port"):
    """One resource-agnostic graph: ingress -> transform -> check."""
    computing = OperationOffer("advance", "request", "state", 3)
    checking = OperationOffer("check", "state", "verified", 1)
    observations = [obs("start", hint=hint), obs("fast", (computing,) if include_compute else (), hint=hint),
                    obs("checker", (checking,), hint="resolver-observer")]
    channels = [ch("a", "start", "fast", "request"),
                ch("b", "fast", "checker", "state")]
    operations = {("fast", "advance"), ("checker", "check")}
    binding = [RealizerBinding("fast", "advance", _value, digest("fast-implementation"), _check),
               RealizerBinding("checker", "check", _verify, digest("checker-implementation"), _verify_check)]
    if alternatives:
        observations.append(obs("slow", (OperationOffer("advance", "request", "state", 10),), hint="cpu-cluster"))
        channels.extend((ch("c", "start", "slow", "request"), ch("d", "slow", "checker", "state")))
        binding.append(RealizerBinding("slow", "advance", _value, digest("slow-implementation"), _check))
        operations.add(("slow", "advance"))
    inventory = SubstrateObservation(tuple(observations), tuple(channels))
    drivers = [CarrierBinding(edge.channel_id, lambda data, coordinate: data,
                              digest({"local": "test-carrier", "link": edge.channel_id})) for edge in channels]
    policy = BootstrapPolicy(frozenset(operations), frozenset(x.channel_id for x in channels), "receiver-owned")
    task = BootstrapTask("navigate-to-observation", GROUND, "start", "request",
                         "checker", "verified", INPUT, require_oracle=True)
    return inventory, binding, drivers, policy, task


class AdaptiveBootstrapTests(unittest.TestCase):
    """Adversarial and continuity-oriented tests independent of a particular physical device."""

    def test_selects_cheapest_admitted_multi_host_path_and_rechecks_report(self):
        inventory, operators, channels, policy, task = _fixture()
        runtime = AdaptiveBootstrap(inventory, policy, operators, channels)
        plan = runtime.plan(task, coordinate=3)
        self.assertEqual([s.operation for s in plan.steps], ["a", "advance", "b", "check"])
        self.assertEqual(plan.estimated_quanta, 6)
        receipt = runtime.execute(task, plan, coordinate=3)
        self.assertEqual(receipt["output"], _verify(_value(INPUT)))
        self.assertEqual(receipt["receiver_oracle_checked_steps"], 2)
        self.assertTrue(verify_bootstrap_report(receipt, task, plan))
        self.assertFalse(receipt["physical_independence_attested"])

    def test_rebootstrap_after_observed_resource_loss_preserves_semantic_result(self):
        inventory, operators, channels, policy, task = _fixture()
        first_runtime = AdaptiveBootstrap(inventory, policy, operators, channels)
        first = first_runtime.plan(task, coordinate=3)
        first_report = first_runtime.execute(task, first, coordinate=3)
        changed = SubstrateObservation(tuple(x for x in inventory.resources if x.resource_id != "fast"),
                                      tuple(x for x in inventory.channels if x.channel_id not in {"a", "b"}))
        second_runtime = AdaptiveBootstrap(changed, policy, operators, channels)
        second = second_runtime.plan(task, coordinate=3)
        second_report = second_runtime.execute(task, second, coordinate=3)
        self.assertNotEqual(first.fingerprint, second.fingerprint)
        self.assertEqual([s.operation for s in second.steps], ["c", "advance", "d", "check"])
        self.assertEqual(first_report["output"], second_report["output"])
        self.assertEqual(first_report["ground_digest"], second_report["ground_digest"])
        with self.assertRaisesRegex(BootstrapRefused, "stale"):
            second_runtime.execute(task, first, coordinate=3)

    def test_substrate_names_do_not_determine_execution(self):
        inventory, operators, channels, policy, task = _fixture()
        runtime = AdaptiveBootstrap(inventory, policy, operators, channels)
        original = runtime.execute(task, runtime.plan(task, coordinate=3), coordinate=3)
        for label in ("fiber-cable", "dns-timing-observation", "single-physical-port", "remote-machine"):
            altered = SubstrateObservation(tuple(replace(x, substrate_hint=label) for x in inventory.resources), inventory.channels)
            runner = AdaptiveBootstrap(altered, policy, operators, channels)
            self.assertEqual(runner.execute(task, runner.plan(task, coordinate=3), coordinate=3)["output"], original["output"])

    def test_passive_resources_and_advertised_operations_do_not_authorize_compute(self):
        inventory, operators, channels, policy, task = _fixture(include_compute=False, alternatives=False)
        runtime = AdaptiveBootstrap(inventory, policy, operators, channels)
        with self.assertRaisesRegex(BootstrapRefused, "no admitted"):
            runtime.plan(task, coordinate=3)
        inventory, operators, channels, policy, task = _fixture()
        runtime = AdaptiveBootstrap(inventory, policy, [], channels)
        with self.assertRaises(BootstrapRefused):
            runtime.plan(task, coordinate=3)
        runtime = AdaptiveBootstrap(inventory, BootstrapPolicy(frozenset(), policy.allowed_channels, "receiver-owned"), operators, channels)
        with self.assertRaises(BootstrapRefused):
            runtime.plan(task, coordinate=3)

    def test_transport_only_can_never_fabricate_an_unoffered_transform(self):
        inventory, operators, channels, policy, task = _fixture(include_compute=False, alternatives=False)
        fake_carriers = channels + [CarrierBinding("unused", lambda x, t: x, digest("not-a-compute-operation"))]
        runtime = AdaptiveBootstrap(inventory, policy, operators, fake_carriers)
        with self.assertRaises(BootstrapRefused):
            runtime.plan(task, coordinate=3)

    def test_channel_must_be_observed_allowed_and_have_a_local_driver(self):
        inventory, operators, channels, policy, task = _fixture(alternatives=False)
        for denial in (
            AdaptiveBootstrap(inventory, policy, operators, []),
            AdaptiveBootstrap(inventory, BootstrapPolicy(policy.allowed_operations, frozenset(), "receiver-owned"), operators, channels),
        ):
            with self.assertRaises(BootstrapRefused):
                denial.plan(task, coordinate=3)

    def test_expired_observations_and_stale_plan_are_rejected(self):
        inventory, operators, channels, policy, task = _fixture()
        runner = AdaptiveBootstrap(inventory, policy, operators, channels)
        plan = runner.plan(task, coordinate=29)
        with self.assertRaisesRegex(BootstrapRefused, "no admitted"):
            runner.plan(task, coordinate=31)
        with self.assertRaises(BootstrapRefused):
            runner.execute(task, plan, coordinate=31)

    def test_resource_cost_budget_and_step_limit_fail_closed(self):
        inventory, operators, channels, policy, task = _fixture()
        runner = AdaptiveBootstrap(inventory, policy, operators, channels)
        for changed in (replace(task, max_quanta=5), replace(task, max_steps=3)):
            with self.assertRaisesRegex(BootstrapRefused, "no admitted"):
                runner.plan(changed, coordinate=3)

    def test_bad_channel_data_is_not_silently_accepted(self):
        inventory, operators, channels, policy, task = _fixture(alternatives=False)
        drivers = [CarrierBinding(x.channel_id, lambda raw, t: raw + b"bad", digest(x.channel_id)) for x in inventory.channels]
        runner = AdaptiveBootstrap(inventory, policy, operators, drivers)
        with self.assertRaisesRegex(BootstrapRefused, "altered"):
            runner.execute(task, runner.plan(task, coordinate=3), coordinate=3)

    def test_receiver_owned_oracle_detects_wrong_implementation(self):
        inventory, operators, channels, policy, task = _fixture(alternatives=False)
        bad = [replace(x, handler=lambda value: {"value": 1234, "coordinate": value["coordinate"]})
               if x.operation == "advance" else x for x in operators]
        runner = AdaptiveBootstrap(inventory, policy, bad, channels)
        with self.assertRaisesRegex(BootstrapRefused, "independent check rejected"):
            runner.execute(task, runner.plan(task, coordinate=3), coordinate=3)

    def test_missing_oracle_is_detected_before_execution_when_requested(self):
        inventory, operators, channels, policy, task = _fixture(alternatives=False)
        no_oracle = [replace(x, oracle=None) for x in operators]
        runner = AdaptiveBootstrap(inventory, policy, no_oracle, channels)
        with self.assertRaisesRegex(BootstrapRefused, "no admitted"):
            runner.plan(task, coordinate=3)
        relaxed = replace(task, require_oracle=False)
        plan = runner.plan(relaxed, coordinate=3)
        self.assertEqual(runner.execute(relaxed, plan, coordinate=3)["receiver_oracle_checked_steps"], 0)

    def test_tampered_report_and_receipt_chain_fail_independent_recheck(self):
        inventory, operators, channels, policy, task = _fixture(alternatives=False)
        runner = AdaptiveBootstrap(inventory, policy, operators, channels)
        plan = runner.plan(task, coordinate=3)
        valid = runner.execute(task, plan, coordinate=3)
        changed = json.loads(json.dumps(valid))
        changed["output"]["verified_value"] += 1
        with self.assertRaises(BootstrapRefused):
            verify_bootstrap_report(changed, task, plan)
        changed = json.loads(json.dumps(valid))
        changed["receipts"][1]["input_digest"] = "0" * 64
        changed.pop("report_digest")
        changed["report_digest"] = digest(changed)
        with self.assertRaisesRegex(BootstrapRefused, "continuity"):
            verify_bootstrap_report(changed, task, plan)

    def test_invalid_inventory_and_noncanonical_values_are_rejected(self):
        with self.assertRaises(BootstrapRefused):
            SubstrateObservation((obs("a"),), (ch("bad", "a", "missing", "request"),))
        with self.assertRaises(BootstrapRefused):
            BootstrapTask("bad", GROUND, "a", "input", "a", "output", {"nonfinite": float("nan")})
        with self.assertRaises(BootstrapRefused):
            ch("bad", "a", "b", "request", budget=0)
        with self.assertRaises(BootstrapRefused):
            ResourceObservation("a", "x", 9, 8, "origin", digest("obs"))

    def test_local_policy_changes_invalidate_existing_plan(self):
        inventory, operators, channels, policy, task = _fixture(alternatives=False)
        runtime = AdaptiveBootstrap(inventory, policy, operators, channels)
        plan = runtime.plan(task, coordinate=3)
        new_policy = BootstrapPolicy(policy.allowed_operations, policy.allowed_channels, "different-authority")
        new_runner = AdaptiveBootstrap(inventory, new_policy, operators, channels)
        with self.assertRaisesRegex(BootstrapRefused, "stale"):
            new_runner.execute(task, plan, coordinate=3)

    def test_probe_receipts_do_not_let_unknown_remote_software_execute(self):
        inventory, operators, channels, policy, task = _fixture(alternatives=False)
        advertised = SubstrateObservation(tuple(replace(x, observer_id="remote-untrusted-prober") for x in inventory.resources), inventory.channels)
        no_registered_code = AdaptiveBootstrap(advertised, policy, [], channels)
        with self.assertRaises(BootstrapRefused):
            no_registered_code.plan(task, coordinate=3)


class OwnedECPUIntegrationTests(unittest.TestCase):
    """The E-CPU installed package tests an actual owned network, not a JSON fake."""

    def test_real_owned_network_probes_and_executes_navigable_observation(self):
        try:
            from mailcpu.owned_network import OwnedNetworkFabric
            from mailcpu.law_certifier import lcg_navigate
        except ImportError:
            self.skipTest("E-CPU owned-network integration requires full repository checkout")
        fabric = OwnedNetworkFabric()
        for namespace in ("origin", "bridge", "executor", "verifier"):
            fabric.create_namespace(namespace)
        a = fabric.create_interface("origin", "port0")
        b = fabric.create_interface("bridge", "left")
        c = fabric.create_interface("bridge", "right")
        d = fabric.create_interface("executor", "port0")
        e = fabric.create_interface("executor", "port1")
        f = fabric.create_interface("verifier", "port0")
        fabric.connect("ab", a, b)
        fabric.connect("cd", c, d)
        fabric.connect("ef", e, f)
        offers = {"executor/port0": (OperationOffer("navigate", "request", "state", 6),),
                  "verifier/port0": (OperationOffer("verify", "state", "verified", 2),)}
        inventory = owned_network_probe(fabric, coordinate=12, offers=offers)
        carriers = owned_network_carriers(fabric, inventory)
        self.assertGreater(len(inventory.channels), 4)
        self.assertEqual(len(inventory.resources), 6)
        params = {"a": 5, "c": 1, "m": 65536, "x0": 314, "t": 10**12 + 19}
        def navigate(raw):
            return {"value": lcg_navigate(raw["a"], raw["c"], raw["m"], raw["x0"], raw["t"]),
                    "coordinate": raw["t"]}
        def check_navigate(raw, out):
            # Independent binary exponentiation of the affine pair (a,c).
            power_a, power_c, a0, c0, t, m = 1, 0, raw["a"], raw["c"], raw["t"], raw["m"]
            while t:
                if t & 1:
                    power_c = (a0 * power_c + c0) % m
                    power_a = (a0 * power_a) % m
                c0 = (a0 * c0 + c0) % m
                a0 = a0 * a0 % m
                t >>= 1
            return out == {"value": (power_a * raw["x0"] + power_c) % m,
                           "coordinate": raw["t"]}
        operators = [RealizerBinding("executor/port0", "navigate", navigate, digest("lcg-realization"), check_navigate),
                     RealizerBinding("verifier/port0", "verify", _verify, digest("projection"), _verify_check)]
        local_policy = BootstrapPolicy(frozenset({("executor/port0", "navigate"), ("verifier/port0", "verify")}),
                                       frozenset(x.channel_id for x in inventory.channels), "chip-resident-observer")
        task = BootstrapTask("real-fabric-navigation", digest(params), "origin/port0", "request", "verifier/port0", "verified", params, require_oracle=True)
        runtime = AdaptiveBootstrap(inventory, local_policy, operators, carriers)
        plan = runtime.plan(task, coordinate=12)
        self.assertTrue(any(x.kind == "carry" for x in plan.steps))
        report = runtime.execute(task, plan, coordinate=12)
        self.assertEqual(report["output"]["verified_value"], navigate(params)["value"])
        self.assertTrue(verify_bootstrap_report(report, task, plan))
        self.assertTrue(fabric.journal.verify())
        self.assertGreater(sum(x.get("kind") == "carry" for x in report["receipts"]), 0)


if __name__ == "__main__":
    unittest.main()