"""INTENT-001: intention-selected finite processor, authorized path, and re-formation."""

from __future__ import annotations

from dataclasses import replace
from itertools import product
import unittest

from mailcpu.intention_formed_fabric import (
    FiniteObserverLaw, form_observer_machine, realize_formed_intention,
    verify_formed_machine,
)
from mailcpu.substrate_bootstrap import (
    BootstrapPolicy, BootstrapRefused, CarrierBinding, ChannelObservation,
    OperationOffer, ResourceObservation, SubstrateObservation, digest,
    verify_bootstrap_report,
)


LAW = FiniteObserverLaw(
    states=tuple(f"s{i}" for i in range(8)),
    actions=("forward", "backward"),
    fields=("parity", "identity"),
    transitions=tuple(((i + 1) % 8, (i - 1) % 8) for i in range(8)),
    observations=tuple((i % 2, i) for i in range(8)),
)


def resource(host, offers=(), expiry=30):
    """Make an observed, but not necessarily admitted, finite host capability."""
    return ResourceObservation(host, "observation-locus", 1, expiry, "untrusted-sensor",
                               digest({"observation": host}), tuple(offers))


def channel(edge, source, target, kind, cost=1, expiry=30):
    """Make a directed typed path with a finite observation lease."""
    return ChannelObservation(edge, source, target, (kind,), cost, 1, expiry,
                              digest({"edge": edge}), 8192)


def environment(include_a=True, include_b=True, include_general=True, *,
                remote_offer=False, expired=False):
    """Build alternative compact and general paths without a preselected executor."""
    resources = [resource("origin"), resource("witness", (
        OperationOffer("form.observe.v1", "form.state.v1", "form.observed.v1", 1),))]
    channels = []
    for host, operation, cost, include in (
        ("compact-a", "form.execute.compact.v1", 1, include_a),
        ("compact-b", "form.execute.compact.v1", 9, include_b),
        ("general", "form.execute.general.v1", 3, include_general),
    ):
        if include:
            resources.append(resource(host, (OperationOffer(operation, "form.request.v1", "form.state.v1", cost),),
                                      expiry=2 if expired else 30))
            channels.extend((channel(host+"-in", "origin", host, "form.request.v1", expiry=2 if expired else 30),
                             channel(host+"-out", host, "witness", "form.state.v1", expiry=2 if expired else 30)))
    if remote_offer:
        resources.append(resource("remote", (OperationOffer(
            "form.execute.compact.v1", "form.request.v1", "form.state.v1", 1),)))
        channels.extend((channel("remote-in", "origin", "remote", "form.request.v1"),
                         channel("remote-out", "remote", "witness", "form.state.v1")))
    inventory = SubstrateObservation(tuple(resources), tuple(channels))
    policy = BootstrapPolicy(
        frozenset({("compact-a", "form.execute.compact.v1"),
                   ("compact-b", "form.execute.compact.v1"),
                   ("general", "form.execute.general.v1"),
                   ("witness", "form.observe.v1")}),
        frozenset(edge.channel_id for edge in channels), "receiver-owned-admission",
    )
    carriers = tuple(CarrierBinding(edge.channel_id, lambda raw, t: raw,
                                    digest({"owned-test-driver": edge.channel_id}))
                     for edge in channels)
    return inventory, policy, carriers


def run(fields, *, initial="s3", word=("forward", "forward", "backward"),
        environment_args=None, policy=None, carriers=None, interpreter_ids=None,
        observer_ids=("witness",), coordinate=5):
    """Request a result with no explicit processor or route in its intention."""
    inv, default_policy, default_carriers = environment(**(environment_args or {}))
    return realize_formed_intention(
        LAW, fields, initial, word, inv, policy or default_policy,
        carriers if carriers is not None else default_carriers,
        admitted_interpreters=interpreter_ids if interpreter_ids is not None
        else ("compact-a", "compact-b", "general"),
        admitted_observers=observer_ids, ingress="origin", observer="witness",
        coordinate=coordinate,
    )


class ObserverFormedFabricTests(unittest.TestCase):
    """Source-check generated processors and inspect actual native bootstrap steps."""

    def test_same_source_different_intention_forms_different_processor_and_path(self):
        parity = run(("parity",))
        exact = run(("identity",))
        self.assertEqual(parity.machine.register_bits, 1)
        self.assertEqual(len(parity.machine.groups), 2)
        self.assertEqual(exact.machine.register_bits, 3)
        self.assertEqual(len(exact.machine.groups), 8)
        self.assertEqual(parity.machine.operation, "form.execute.compact.v1")
        self.assertEqual(exact.machine.operation, "form.execute.general.v1")
        self.assertNotEqual(parity.machine.fingerprint, exact.machine.fingerprint)
        self.assertIn("compact-a", [step.locus for step in parity.plan.steps])
        self.assertIn("general", [step.locus for step in exact.plan.steps])
        self.assertNotIn("general", [step.locus for step in parity.plan.steps])
        self.assertEqual(parity.report["output"]["observation"], {"parity": 0})
        self.assertEqual(exact.report["output"]["observation"], {"identity": 4})
        self.assertTrue(verify_bootstrap_report(parity.report, parity.task, parity.plan))
        self.assertTrue(verify_bootstrap_report(exact.report, exact.task, exact.plan))
        self.assertEqual(parity.report["receiver_oracle_checked_steps"], 2)
        self.assertFalse(parity.report["physical_independence_attested"])

    def test_reformation_on_loss_of_preferred_host_preserves_intention_identity(self):
        before = run(("parity",))
        after = run(("parity",), environment_args={"include_a": False})
        self.assertEqual(before.machine.fingerprint, after.machine.fingerprint)
        self.assertEqual(before.task.ground_digest, after.task.ground_digest)
        self.assertEqual(before.report["output"], after.report["output"])
        self.assertNotEqual(before.plan.fingerprint, after.plan.fingerprint)
        self.assertIn("compact-b", [step.locus for step in after.plan.steps])

    def test_source_equivalence_for_all_small_intended_action_words(self):
        for fields in (("parity",), ("identity",), ("parity", "identity")):
            machine = form_observer_machine(LAW, fields)
            self.assertTrue(verify_formed_machine(LAW, machine))
            for initial in LAW.states:
                for steps in range(5):
                    for word in product(LAW.actions, repeat=steps):
                        result = machine.apply({"initial_state": initial, "word": list(word)})
                        self.assertEqual(result["observation"], LAW.replay(initial, word, fields))

    def test_advertisement_is_not_an_execution_capability(self):
        inv, policy, carriers = environment(remote_offer=True)
        with self.assertRaisesRegex(BootstrapRefused, "no admitted"):
            realize_formed_intention(
                LAW, ("parity",), "s0", ("forward",), inv,
                BootstrapPolicy(frozenset({("remote", "form.execute.compact.v1"),
                                         ("witness", "form.observe.v1")}),
                                policy.allowed_channels, "receiver-owned"),
                carriers, admitted_interpreters=("compact-a", "compact-b"),
                admitted_observers=("witness",),
                ingress="origin", observer="witness", coordinate=5,
            )
        # A remote offer is also powerless without a locally bound handler.
        with self.assertRaisesRegex(BootstrapRefused, "no admitted"):
            run(("parity",), interpreter_ids=())

    def test_revoked_receiver_authority_and_expired_observations_refuse(self):
        inv, policy, carriers = environment()
        denied = BootstrapPolicy(
            frozenset({("witness", "form.observe.v1")}),
            policy.allowed_channels, policy.authority_id,
        )
        with self.assertRaisesRegex(BootstrapRefused, "no admitted"):
            realize_formed_intention(
                LAW, ("parity",), "s0", (), inv, denied, carriers,
                admitted_interpreters=("compact-a", "compact-b"),
                admitted_observers=("witness",),
                ingress="origin", observer="witness", coordinate=5,
            )
        with self.assertRaisesRegex(BootstrapRefused, "no admitted"):
            run(("identity",), environment_args={"expired": True})

    def test_broken_transport_does_not_become_a_successful_result(self):
        inv, policy, carriers = environment()
        poisoned = tuple(replace(c, deliver=lambda raw, t: raw + b"!") for c in carriers)
        with self.assertRaisesRegex(BootstrapRefused, "altered"):
            realize_formed_intention(
                LAW, ("parity",), "s0", ("forward",), inv, policy, poisoned,
                admitted_interpreters=("compact-a",),
                admitted_observers=("witness",),
                ingress="origin", observer="witness", coordinate=5,
            )

    def test_rehashed_wrong_quotient_or_source_fails_exact_audit(self):
        machine = form_observer_machine(LAW, ("parity",))
        wrong = replace(machine, transitions=((0, 0), (0, 0)))
        self.assertNotEqual(wrong.fingerprint, machine.fingerprint)
        with self.assertRaisesRegex(BootstrapRefused, "source-equivalent"):
            verify_formed_machine(LAW, wrong)
        wrong_source = replace(LAW, transitions=tuple(((i + 2) % 8, (i - 1) % 8) for i in range(8)))
        with self.assertRaisesRegex(BootstrapRefused, "not bound"):
            verify_formed_machine(wrong_source, machine)

    def test_rehashed_oversplit_quotient_cannot_claim_minimality(self):
        machine = form_observer_machine(LAW, ("parity",))
        oversplit = replace(
            machine, groups=tuple((i,) for i in range(8)),
            state_groups=tuple(range(8)),
            outputs=tuple((i % 2,) for i in range(8)),
            transitions=LAW.transitions,
        )
        with self.assertRaisesRegex(BootstrapRefused, "not observationally minimal"):
            verify_formed_machine(LAW, oversplit)

    def test_future_observations_split_currently_indistinguishable_states(self):
        law = FiniteObserverLaw(
            ("a", "b", "c"), ("tick",), ("seen",),
            ((2,), (1,), (2,)), ((0,), (0,), (1,)),
        )
        machine = form_observer_machine(law, ("seen",))
        self.assertEqual(len(machine.groups), 3)
        self.assertEqual(machine.apply({"initial_state": "a", "word": ["tick"]})["observation"], {"seen": 1})
        self.assertEqual(machine.apply({"initial_state": "b", "word": ["tick"]})["observation"], {"seen": 0})

    def test_intention_forms_processor_over_native_owned_multihop_fabric(self):
        from mailcpu.owned_network import OwnedNetworkFabric
        from mailcpu.substrate_bootstrap import owned_network_probe, owned_network_carriers

        fabric = OwnedNetworkFabric()
        for namespace in ("origin", "bridge", "compact", "general", "witness"):
            fabric.create_namespace(namespace)
        def port(namespace, interface):
            """Create a real owned-network address in an existing namespace."""
            return fabric.create_interface(namespace, interface)
        start = port("origin", "p0")
        bi, bc, bg = port("bridge", "ingress"), port("bridge", "toc"), port("bridge", "tog")
        ci, co = port("compact", "in"), port("compact", "out")
        gi, go = port("general", "in"), port("general", "out")
        wc, wg = port("witness", "inc"), port("witness", "ing")
        for link, left, right in (
            ("origin-bridge", start, bi), ("bridge-compact", bc, ci),
            ("bridge-general", bg, gi), ("compact-witness", co, wc),
            ("general-witness", go, wg),
        ):
            fabric.connect(link, left, right)
        self.assertGreater(len(fabric.find_route(start, ci)), 2)
        offers = {
            "compact/in": (OperationOffer(
                "form.execute.compact.v1", "form.request.v1", "form.state.v1", 1),),
            "general/in": (OperationOffer(
                "form.execute.general.v1", "form.request.v1", "form.state.v1", 2),),
            "witness/inc": (OperationOffer(
                "form.observe.v1", "form.state.v1", "form.observed.v1", 1),),
        }
        inv = owned_network_probe(
            fabric, coordinate=12, offers=offers,
            carries=("form.request.v1", "form.state.v1", "form.observed.v1"),
        )
        drivers = owned_network_carriers(fabric, inv)
        policy = BootstrapPolicy(
            frozenset({("compact/in", "form.execute.compact.v1"),
                       ("general/in", "form.execute.general.v1"),
                       ("witness/inc", "form.observe.v1")}),
            frozenset(edge.channel_id for edge in inv.channels),
            "local-owned-fabric-admission",
        )
        results = {}
        for fields in (("parity",), ("identity",)):
            outcome = realize_formed_intention(
                LAW, fields, "s3", ("forward", "forward", "backward"),
                inv, policy, drivers, admitted_interpreters=("compact/in", "general/in"),
                admitted_observers=("witness/inc",),
                ingress="origin/p0", observer="witness/inc", coordinate=12,
            )
            results[fields[0]] = outcome
            self.assertTrue(verify_bootstrap_report(outcome.report, outcome.task, outcome.plan))
            self.assertGreaterEqual(sum(s.kind == "carry" for s in outcome.plan.steps), 2)
            self.assertFalse(outcome.report["physical_independence_attested"])
        self.assertIn("compact/in", [step.locus for step in results["parity"].plan.steps])
        self.assertIn("general/in", [step.locus for step in results["identity"].plan.steps])
        self.assertEqual(results["parity"].report["output"]["observation"], {"parity": 0})
        self.assertEqual(results["identity"].report["output"]["observation"], {"identity": 4})
        self.assertTrue(fabric.journal.verify())

    def test_generated_machine_rejects_unmodeled_state_or_action(self):
        machine = form_observer_machine(LAW, ("parity",))
        with self.assertRaises(BootstrapRefused):
            machine.apply({"initial_state": "invented", "word": []})
        with self.assertRaises(BootstrapRefused):
            machine.apply({"initial_state": "s0", "word": ["teleport"]})
        with self.assertRaises(BootstrapRefused):
            form_observer_machine(LAW, ("unknown-field",))
        with self.assertRaises(BootstrapRefused):
            FiniteObserverLaw(("s0",), ("tick",), ("v",), ((2,),), ((0,),))

    def test_typed_observations_distinguish_boolean_from_integer(self):
        # JSON Booleans and integers must not collapse because Python True == 1.
        source = FiniteObserverLaw(
            ("true-state", "one-state"), ("stay",), ("value",),
            ((0,), (1,)), ((True,), (1,)),
        )
        machine = form_observer_machine(source, ("value",))
        self.assertEqual(len(machine.groups), 2)
        self.assertTrue(verify_formed_machine(source, machine))
        forged = replace(machine, outputs=((1,), (1,)))
        with self.assertRaisesRegex(BootstrapRefused, "source-equivalent"):
            verify_formed_machine(source, forged)

    def test_unsupported_intention_has_no_inferred_host_even_if_general_exists(self):
        with self.assertRaisesRegex(BootstrapRefused, "no admitted"):
            run(("parity",), environment_args={"include_a": False, "include_b": False})


if __name__ == "__main__":
    unittest.main()
