"""MGA-001/C: exercise actual native bootstrap and owned network carriers."""
import json
import random
import unittest
from dataclasses import replace

from mailcpu.substrate_bootstrap import (
    AdaptiveBootstrap, BootstrapPolicy, BootstrapRefused, CarrierBinding,
    ChannelObservation, ResourceObservation, SubstrateObservation, digest,
    owned_network_probe, owned_network_carriers,
)
from mailcpu.shared_observation_ground import plan_shared, verify_shared_plan, execute_shared

GROUND = digest("shared-label-source")
VALUE = {"label": 7, "source": GROUND}
KIND = "label"


def fixture(allowed=("ab", "bc", "bd"), *, bad=False):
    names = ("a", "b", "c", "d")
    resources = tuple(ResourceObservation(n, "port", 0, 10, "observer", digest(n))
                      for n in names)
    edges = tuple(ChannelObservation(k, a, b, (KIND,), 1, 0, 10, digest(k))
                  for k, a, b in (("ab", "a", "b"), ("bc", "b", "c"),
                                  ("bd", "b", "d"), ("cd", "c", "d")))
    log = []
    def driver(k):
        def deliver(data, coordinate):
            log.append(k)
            return data + b"!" if bad and k == "bc" else data
        return deliver
    carriers = tuple(CarrierBinding(e.channel_id, driver(e.channel_id), digest(e.channel_id))
                     for e in edges)
    runtime = AdaptiveBootstrap(SubstrateObservation(resources, edges),
                                BootstrapPolicy(frozenset(), frozenset(allowed), "owner"),
                                (), carriers)
    return runtime, log


def plan(runtime, coordinate=1):
    return plan_shared(runtime, "a", ("c", "d"), KIND, VALUE, GROUND, coordinate=coordinate)


def run(runtime, p, coordinate=1):
    return execute_shared(runtime, "a", ("c", "d"), KIND, VALUE, GROUND, p, coordinate=coordinate)


class SharedObservationTests(unittest.TestCase):
    def test_common_prefix_is_realized_once(self):
        runtime, log = fixture()
        p = plan(runtime)
        self.assertEqual(p["tree"], ["ab", "bc", "bd"])
        self.assertEqual(p["separate_path_hops"], 4)
        receipt = run(runtime, p)
        self.assertEqual(receipt["observations"], {"c": VALUE, "d": VALUE})
        self.assertEqual(log, ["ab", "bc", "bd"])
        self.assertEqual(receipt["transmissions"], 3)
        self.assertEqual(len(receipt["reports"]), 3)

    def test_cut_repair_does_not_grant_authority(self):
        runtime, log = fixture(("ab", "bc"))
        p = plan(runtime)
        self.assertEqual(p["reachable"], ["a", "b", "c"])
        self.assertEqual(p["missing"], ["d"])
        self.assertEqual(p["boundary_grants"], ["bd", "cd"])
        self.assertEqual(p["repairs"][0]["count"], 1)
        self.assertEqual(p["repairs"][0]["grants"], ["bd"])
        with self.assertRaises(BootstrapRefused):
            run(runtime, p)
        self.assertEqual(log, [])
        repaired, log = fixture(("ab", "bc", "bd"))
        with self.assertRaises(BootstrapRefused):
            run(repaired, p)
        self.assertEqual(run(repaired, plan(repaired))["transmissions"], 3)

    def test_expired_endpoints_and_unbound_carriers_are_not_repairs(self):
        runtime, _ = fixture()
        changed = SubstrateObservation(tuple(replace(r, expires_at=0) if r.resource_id == "d" else r
                                              for r in runtime.inventory.resources),
                                       runtime.inventory.channels)
        stale = AdaptiveBootstrap(changed, runtime.policy, (), tuple(runtime.carriers.values()))
        self.assertEqual(plan(stale)["repairs"], [{"target": "d", "status": "NO_OFFERED_PATH"}])
        missing = AdaptiveBootstrap(runtime.inventory, runtime.policy, (),
                                    tuple(c for k, c in runtime.carriers.items() if k not in ("bd", "cd")))
        self.assertEqual(plan(missing)["repairs"], [{"target": "d", "status": "NO_OFFERED_PATH"}])

    def test_tamper_stale_input_and_bad_carrier(self):
        runtime, log = fixture()
        p = plan(runtime)
        forged = json.loads(json.dumps(p))
        forged["tree"].pop()
        forged["digest"] = digest({k: v for k, v in forged.items() if k != "digest"})
        with self.assertRaises(BootstrapRefused):
            run(runtime, forged)
        with self.assertRaises(BootstrapRefused):
            run(runtime, p, 2)
        with self.assertRaises(BootstrapRefused):
            execute_shared(runtime, "a", ("c", "d"), KIND, {"label": 9}, GROUND, p, coordinate=1)
        self.assertEqual(log, [])
        bad, log = fixture(bad=True)
        with self.assertRaises(BootstrapRefused):
            run(bad, plan(bad))
        self.assertEqual(log, ["ab", "bc"])

    def test_random_graphs_against_subset_grant_oracle(self):
        rng = random.Random(20261125)
        for _ in range(180):
            ns = tuple("abcde")
            resources = tuple(ResourceObservation(n, "port", 0, 10, "observer", digest(n)) for n in ns)
            edges = tuple(ChannelObservation(a+b, a, b, (KIND,), 1, 0, 10, digest(a+b))
                          for a in ns for b in ns if a != b and rng.random() < .29)
            allowed = frozenset(e.channel_id for e in edges if rng.random() < .45)
            drivers = tuple(CarrierBinding(e.channel_id, lambda x, t: x, digest(e.channel_id)) for e in edges)
            rt = AdaptiveBootstrap(SubstrateObservation(resources, edges),
                                   BootstrapPolicy(frozenset(), allowed, "owner"), (), drivers)
            p = plan_shared(rt, "a", ("e",), KIND, VALUE, GROUND, coordinate=1)
            self.assertTrue(verify_shared_plan(rt, "a", ("e",), KIND, VALUE, GROUND, p, coordinate=1))
            from itertools import combinations
            denied = sorted({e.channel_id for e in edges} - allowed)
            optimum = None
            for n in range(len(denied)+1):
                for subset in combinations(denied, n):
                    permitted = allowed | set(subset)
                    reach = {"a"}
                    while True:
                        new = reach | {e.target for e in edges if e.source in reach and e.channel_id in permitted}
                        if new == reach:
                            break
                        reach = new
                    if "e" in reach:
                        optimum = n
                        break
                if optimum is not None:
                    break
            got = 0 if p["status"] == "READY" else p["repairs"][0].get("count")
            self.assertEqual(got, optimum)

    def test_native_owned_network(self):
        from mailcpu.owned_network import OwnedNetworkFabric
        fabric = OwnedNetworkFabric()
        for n in ("origin", "relay", "left", "right"):
            fabric.create_namespace(n)
        a = fabric.create_interface("origin", "port")
        b = fabric.create_interface("relay", "in")
        c = fabric.create_interface("relay", "l")
        d = fabric.create_interface("left", "port")
        e = fabric.create_interface("relay", "r")
        f = fabric.create_interface("right", "port")
        fabric.connect("ab", a, b)
        fabric.connect("cd", c, d)
        fabric.connect("ef", e, f)
        inventory = owned_network_probe(fabric, coordinate=1, carries=(KIND,))
        drivers = owned_network_carriers(fabric, inventory)
        chosen = {("origin/port", "relay/in"), ("relay/in", "left/port"), ("relay/in", "right/port")}
        allowed = frozenset(e.channel_id for e in inventory.channels if (e.source,e.target) in chosen)
        self.assertEqual(len(allowed), 3)
        rt = AdaptiveBootstrap(inventory, BootstrapPolicy(frozenset(), allowed, "owner"), (), drivers)
        targets = ("left/port", "right/port")
        p = plan_shared(rt, "origin/port", targets, KIND, VALUE, GROUND, coordinate=1)
        receipt = execute_shared(rt, "origin/port", targets, KIND, VALUE, GROUND, p, coordinate=1)
        self.assertEqual(receipt["observations"], {t: VALUE for t in targets})
        self.assertEqual(receipt["transmissions"], 3)
        self.assertEqual(p["separate_path_hops"], 4)
        self.assertTrue(fabric.journal.verify())


if __name__ == "__main__":
    unittest.main()
