"""WIRE-001: use actual NCR-007 mathematics as E-CPU's transported processor Ground.

Focused CI checks out a fixed Navigable-Compute commit and verifies its
original polynomial and Koopman source independently on receipt. This test
never claims the locally simulated owned fabric is a physical Internet path.
"""

from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
import json
import unittest

from mailcpu.cross_repository_nonlinear_ground import admit_ncr007_finite_packet
from mailcpu.intention_formed_fabric import (
    form_observer_machine, realize_formed_intention, verify_formed_machine,
)
from mailcpu.owned_network import OwnedNetworkFabric
from mailcpu.substrate_bootstrap import (
    BootstrapPolicy, BootstrapRefused, OperationOffer, owned_network_probe,
    owned_network_carriers, verify_bootstrap_report,
)

try:
    from navigable_compute.nonlinear_koopman import (
        PolynomialInvariants, construct_polynomial_laws,
        construct_koopman_ground, navigate_nonlinear, canonical,
    )
    from navigable_compute.nonlinear_koopman_verify import (
        verify_polynomial_laws, verify_koopman_ground, verify_nonlinear_result,
    )
    from navigable_compute.nonlinear_koopman_wire import (
        encode_nonlinear, decode_nonlinear,
    )
    NCR_INSTALLED = True
except ImportError:
    NCR_INSTALLED = False

PINNED_COMMIT = "559a1a813012d13ed37c04e2a117467e34ed3cb1"


def fixture():
    """Derive source operators solely from upstream invariant descriptions, not E-CPU tables."""
    description = PolynomialInvariants(
        4, (0, 1, 1, 2), (0, 1, 2, 3),
        ((1, 2), (3,), (3,), ()), 2,
        ((1,), (1 << 3,)),
    )
    family = construct_polynomial_laws(description, (31, 17))
    assert verify_polynomial_laws(family)
    ground = construct_koopman_ground(family)
    assert verify_koopman_ground(family, ground)
    distant = navigate_nonlinear(family, ground, 15, (0,), 10 ** 40 + 17)
    assert verify_nonlinear_result(family, ground, distant)
    packet = encode_nonlinear(family, ground, distant)
    return family, ground, distant, packet


def owned_topology():
    """Create a genuine E-CPU simulated multi-hop sender, two interpreters and witness."""
    fabric = OwnedNetworkFabric()
    for namespace in ("source", "bridge", "compact", "general", "witness"):
        fabric.create_namespace(namespace)
    def port(ns, interface):
        """Bind an up, large-MTU owned-network interface to one simulator namespace."""
        return fabric.create_interface(ns, interface, mtu=65_535)
    source = port("source", "origin")
    bridge_in, bridge_compact, bridge_general = (
        port("bridge", "incoming"), port("bridge", "to-compact"),
        port("bridge", "to-general"),
    )
    compact_in, compact_out = port("compact", "in"), port("compact", "out")
    general_in, general_out = port("general", "in"), port("general", "out")
    witness_compact, witness_general = (
        port("witness", "from-compact"), port("witness", "from-general"),
    )
    for link, left, right in (
        ("source-bridge", source, bridge_in),
        ("bridge-compact", bridge_compact, compact_in),
        ("bridge-general", bridge_general, general_in),
        ("compact-witness", compact_out, witness_compact),
        ("general-witness", general_out, witness_general),
    ):
        fabric.connect(link, left, right)
    offers = {
        "compact/in": (OperationOffer(
            "form.execute.compact.v1", "form.request.v1", "form.state.v1", 1),),
        "general/in": (OperationOffer(
            "form.execute.general.v1", "form.request.v1", "form.state.v1", 2),),
        "witness/from-compact": (OperationOffer(
            "form.observe.v1", "form.state.v1", "form.observed.v1", 1),),
    }
    inventory = owned_network_probe(
        fabric, coordinate=10, offers=offers,
        carries=("form.request.v1", "form.state.v1", "form.observed.v1"),
    )
    policy = BootstrapPolicy(
        frozenset((
            ("compact/in", "form.execute.compact.v1"),
            ("general/in", "form.execute.general.v1"),
            ("witness/from-compact", "form.observe.v1"),
        )),
        frozenset(e.channel_id for e in inventory.channels),
        "owned-cpu-observer",
    )
    carriers = owned_network_carriers(fabric, inventory)
    return fabric, source, witness_compact, inventory, policy, carriers


@unittest.skipUnless(NCR_INSTALLED, "optional pinned Navigable-Compute source not installed")
class NonlinearForeignWireUsageTests(unittest.TestCase):
    """A live exercised coupling of two repositories' independently checked mathematical structure."""

    def test_math_packet_crosses_native_multihop_fabric_and_forms_two_processors(self):
        family, ground, distant, packet = fixture()
        self.assertTrue(any(monomial.bit_count() > 1
                            for operator in family.operators for row in operator.rows for monomial in row))
        fabric, source, receiver, inventory, policy, carriers = owned_topology()
        self.assertGreater(len(fabric.find_route(source, receiver)), 2)
        fabric.send_routed(source, receiver, packet, logical_time=10)
        received = fabric.receive(receiver)
        self.assertIsNotNone(received)
        self.assertEqual(received.payload, packet)
        self.assertGreater(len(received.route), 2)

        capsule = admit_ncr007_finite_packet(
            received.payload, receiver_expected_sha256=sha256(packet).hexdigest(),
            source_commit=PINNED_COMMIT,
        )
        self.assertEqual(capsule.foreign_law_sha256, family.digest)
        self.assertEqual(capsule.foreign_ground_sha256, ground.digest)
        self.assertEqual(capsule.foreign_result_sha256, distant.digest)
        self.assertEqual(capsule.source.states, tuple(f"s{i}" for i in range(16)))

        # NCR-007 lifts nonlinear dynamics into exact observer-feature
        # coordinates; E-CPU independently constructs the minimal explicit
        # finite future-observer quotient. Their equivalence relations
        # must coincide, not merely happen to produce one matching value.
        full = form_observer_machine(capsule.source, capsule.fields)
        self.assertTrue(verify_formed_machine(capsule.source, full))
        for x in range(16):
            for y in range(16):
                self.assertEqual(
                    full.state_groups[x] == full.state_groups[y],
                    ground.project(x) == ground.project(y),
                    (x, y),
                )

        executed = {}
        for field in ("observer1", "observer0"):
            outcome = realize_formed_intention(
                capsule.source, (field,), "s15", ("a0", "a1", "a0"),
                inventory, policy, carriers,
                admitted_interpreters=("compact/in", "general/in"),
                admitted_observers=("witness/from-compact",),
                ingress="source/origin", observer="witness/from-compact",
                coordinate=10,
            )
            executed[field] = outcome
            state = 15
            for action in (0, 1, 0):
                state = family.operators[action].apply(state)
            bit = int(field[-1])
            self.assertEqual(
                outcome.report["output"]["observation"][field],
                (family.project_observer(state) >> bit) & 1,
            )
            self.assertTrue(verify_bootstrap_report(outcome.report, outcome.task, outcome.plan))
            self.assertGreaterEqual(sum(step.kind == "carry" for step in outcome.plan.steps), 2)
            self.assertFalse(outcome.report["physical_independence_attested"])
        self.assertEqual(len(executed["observer1"].machine.groups), 2)
        self.assertEqual(executed["observer1"].machine.operation, "form.execute.compact.v1")
        self.assertEqual(executed["observer0"].machine.operation, "form.execute.general.v1")
        self.assertIn("compact/in", [s.locus for s in executed["observer1"].plan.steps])
        self.assertIn("general/in", [s.locus for s in executed["observer0"].plan.steps])
        self.assertNotEqual(executed["observer0"].plan.fingerprint,
                            executed["observer1"].plan.fingerprint)

        # Distant mathematical observation is checked by NCR's original
        # independent source audit; no 10**40-step trace is transported.
        self.assertEqual(decode_nonlinear(received.payload)[2], distant)
        self.assertTrue(fabric.journal.verify())

    def test_changed_packet_bytes_and_self_rehashed_wrong_math_are_refused(self):
        family, ground, distant, packet = fixture()
        original_digest = sha256(packet).hexdigest()
        damaged = packet[:-1] + bytes([packet[-1] ^ 1])
        with self.assertRaisesRegex(BootstrapRefused, "differs"):
            admit_ncr007_finite_packet(damaged, receiver_expected_sha256=original_digest,
                                       source_commit=PINNED_COMMIT)
        doc = json.loads(packet)
        row = doc["data"]["ground"]["operator_rows"][0]
        row[0] = "1" if row[0] != "1" else "0"
        ground_packet = doc["data"]["ground"]
        ground_packet["sha256"] = sha256(canonical({
            k: v for k, v in ground_packet.items() if k != "sha256"
        })).hexdigest()
        forged = canonical(doc)
        with self.assertRaisesRegex(BootstrapRefused, "audit refused"):
            admit_ncr007_finite_packet(forged,
                receiver_expected_sha256=sha256(forged).hexdigest(),
                source_commit=PINNED_COMMIT)
        with self.assertRaisesRegex(BootstrapRefused, "exact 40-hex"):
            admit_ncr007_finite_packet(packet,receiver_expected_sha256=original_digest,
                                       source_commit="main")

    def test_mathematical_packet_does_not_authorize_host_execution(self):
        family, ground, distant, packet = fixture()
        capsule = admit_ncr007_finite_packet(
            packet, receiver_expected_sha256=sha256(packet).hexdigest(),
            source_commit=PINNED_COMMIT,
        )
        _, _, _, inventory, policy, carriers = owned_topology()
        no_operators = BootstrapPolicy(frozenset({
            ("witness/from-compact", "form.observe.v1"),
        }), policy.allowed_channels, policy.authority_id)
        with self.assertRaisesRegex(BootstrapRefused, "no admitted"):
            realize_formed_intention(
                capsule.source, ("observer1",), "s15", ("a0",), inventory,
                no_operators, carriers,
                admitted_interpreters=("compact/in", "general/in"),
                admitted_observers=("witness/from-compact",),
                ingress="source/origin", observer="witness/from-compact",
                coordinate=10,
            )


if __name__ == "__main__":
    unittest.main()
