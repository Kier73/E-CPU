"""SAB-010: active construction from bounded, receiver-owned primitive capabilities."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

from mailcpu.capability_construction import (
    ACTIVATE, APPLY, COMPOSE, STAGE, CapabilityConstructionCompiler,
    ConstructionInventory, ConstructionPlan, ConstructionPolicy,
    ConstructionRefused, PrimitiveBinding, bind_receiving_surface, observe_gate,
)
from mailcpu.active_host_formation import FormationPolicy, LocalInterpreterSurface
from mailcpu.ground_native_realization import (
    AffineGround, GroundIntention, TwoPortArithmeticGate, RealizationPolicy,
    realize_under_contract, verify_receipt, independent_observation,
)

GROUND = AffineGround(5, 7, 65521, 19)
COORD = 10**12 + 913
INTENTION = GroundIntention("sab010-formed-from-primitives", GROUND, COORD)


def gate_bindings(*, coordinate=COORD, lease=COORD+100, compose_cost=1, apply_cost=1, modulus=65521):
    """Observe actual functions of two independently addressable simulated gates."""
    a = TwoPortArithmeticGate("port-composition", modulus)
    b = TwoPortArithmeticGate("port-observation", modulus)
    return (
        observe_gate(a, locus="compose-port", operation=COMPOSE,
                     coordinate=coordinate, lease_until=lease, cost=compose_cost),
        observe_gate(b, locus="apply-port", operation=APPLY,
                     coordinate=coordinate, lease_until=lease, cost=apply_cost),
    )


def policies(*bindings, expiry=COORD+100, max_quanta=1000, max_events=256):
    return ConstructionPolicy(frozenset((b.locus,b.operation) for b in bindings),
                              expiry, max_quanta, max_events)


class CapabilityConstructionTests(unittest.TestCase):
    """Check formation from partial primitives, not advertised complete operators."""

    def setUp(self):
        self.home=tempfile.TemporaryDirectory(prefix="sab010-test-")
        self.addCleanup(self.home.cleanup)
        self.root=Path(self.home.name)

    def receiving_bindings(self, *, engine="python", surface_id="receiving-code", cost=1):
        folder=self.root/surface_id
        folder.mkdir(parents=True,exist_ok=True)
        exe=sys.executable if engine=="python" else shutil.which("node")
        if exe is None:
            self.skipTest("Node.js is not installed")
        staging=LocalInterpreterSurface(surface_id,engine,folder,exe)
        activating=LocalInterpreterSurface(surface_id,engine,folder,exe)
        a=bind_receiving_surface(staging,locus="stage-resource",operation=STAGE,
                                 coordinate=COORD,lease_until=COORD+100,cost=cost)
        b=bind_receiving_surface(activating,locus="engine-resource",operation=ACTIVATE,
                                 coordinate=COORD,lease_until=COORD+100,cost=cost)
        return a,b,folder

    def test_two_distinct_ports_form_one_navigator(self):
        a,b=gate_bindings()
        self.assertFalse(hasattr(a.implementation,"execute_ground"))
        self.assertFalse(hasattr(b.implementation,"execute_ground"))
        compiler=CapabilityConstructionCompiler(ConstructionInventory((a,b)),policies(a,b))
        plan=compiler.compile(INTENTION)
        self.assertEqual(plan.recipe,"gate-algebra")
        self.assertEqual(plan.bindings,(("compose-port",COMPOSE),("apply-port",APPLY)))
        formed,receipt=compiler.form(INTENTION,plan)
        self.assertEqual(receipt.payload["output"],{"value":46511})
        self.assertEqual(receipt.payload["event_count"],59)
        self.assertEqual(receipt.payload["evidence"]["port_count"],2)
        self.assertTrue({x["locus"] for x in receipt.payload["events"]} == {"compose-port","apply-port"})
        self.assertFalse(receipt.payload["physical_host_attested"])
        self.assertEqual(formed.method,"constructed.gate-algebra")

    def test_empty_code_surface_is_formed_without_preinstalled_handler(self):
        a,b,folder=self.receiving_bindings()
        self.assertEqual(list(folder.iterdir()),[])
        compiler=CapabilityConstructionCompiler(ConstructionInventory((a,b)),policies(a,b))
        plan=compiler.compile(INTENTION)
        self.assertEqual(plan.recipe,"formed-seed")
        grant=FormationPolicy(frozenset({("receiving-code","python")}),COORD+100)
        formed,receipt=compiler.form(INTENTION,plan,formation_policy=grant)
        self.assertEqual(receipt.payload["output"],{"value":46511})
        self.assertTrue((folder/"ecpu-seed.py").exists())
        self.assertTrue(receipt.payload["evidence"]["runtime_installed_by_receiver"])
        self.assertEqual(formed.surface.surface_id,"receiving-code")

    @unittest.skipUnless(shutil.which("node"),"Node.js is required")
    def test_javascript_surface_is_formed_from_same_primitive_vocabulary(self):
        a,b,folder=self.receiving_bindings(engine="javascript")
        compiler=CapabilityConstructionCompiler(ConstructionInventory((a,b)),policies(a,b))
        formed,receipt=compiler.form(INTENTION,compiler.compile(INTENTION),
            formation_policy=FormationPolicy(frozenset({("receiving-code","javascript")}),COORD+100))
        self.assertEqual(receipt.payload["output"],{"value":46511})
        self.assertTrue((folder/"ecpu-seed.js").exists())
        self.assertEqual(formed.method,"formed.javascript")

    def test_formed_code_survives_fresh_controller_and_process(self):
        a,b,folder=self.receiving_bindings()
        grant=FormationPolicy(frozenset({("receiving-code","python")}),COORD+100)
        compiler=CapabilityConstructionCompiler(ConstructionInventory((a,b)),policies(a,b))
        _,r1=compiler.form(INTENTION,compiler.compile(INTENTION),formation_policy=grant)
        # Controller and locally pinned adapters can be reconstructed without
        # installing new code; every observe spawns a new process.
        a2,b2,_=self.receiving_bindings()
        second=CapabilityConstructionCompiler(ConstructionInventory((a2,b2)),policies(a2,b2))
        _,r2=second.form(INTENTION,second.compile(INTENTION),formation_policy=grant)
        self.assertEqual(r1.payload["output"],r2.payload["output"])
        self.assertEqual(r1.payload["evidence"]["manifest"],r2.payload["evidence"]["manifest"])

    def test_planner_chooses_challenged_ports_when_cheaper(self):
        ga,gb=gate_bindings(compose_cost=1,apply_cost=1)
        sa,sb,_=self.receiving_bindings(cost=500)
        all_=(ga,gb,sa,sb)
        compiler=CapabilityConstructionCompiler(ConstructionInventory(all_),policies(*all_))
        self.assertEqual(compiler.compile(INTENTION).recipe,"gate-algebra")

    def test_planner_chooses_seed_when_cheaper(self):
        ga,gb=gate_bindings(compose_cost=100,apply_cost=100)
        sa,sb,_=self.receiving_bindings(cost=1)
        compiler=CapabilityConstructionCompiler(ConstructionInventory((ga,gb,sa,sb)),policies(ga,gb,sa,sb))
        self.assertEqual(compiler.compile(INTENTION).recipe,"formed-seed")

    def test_missing_apply_refuses_math_construction(self):
        a,_=gate_bindings()
        compiler=CapabilityConstructionCompiler(ConstructionInventory((a,)),policies(a))
        with self.assertRaises(ConstructionRefused):compiler.compile(INTENTION)

    def test_receiving_storage_without_activation_is_not_execution(self):
        a,_,folder=self.receiving_bindings()
        compiler=CapabilityConstructionCompiler(ConstructionInventory((a,)),policies(a))
        with self.assertRaises(ConstructionRefused):compiler.compile(INTENTION)
        self.assertEqual(list(folder.iterdir()),[])

    def test_activation_without_stage_refused(self):
        _,b,_=self.receiving_bindings()
        compiler=CapabilityConstructionCompiler(ConstructionInventory((b,)),policies(b))
        with self.assertRaises(ConstructionRefused):compiler.compile(INTENTION)

    def test_mismatched_stage_activate_rejected(self):
        a,_,folder=self.receiving_bindings(surface_id="code-A")
        _,b,_=self.receiving_bindings(surface_id="code-B")
        c=CapabilityConstructionCompiler(ConstructionInventory((a,b)),policies(a,b))
        with self.assertRaises(ConstructionRefused):c.compile(INTENTION)
        self.assertEqual(list(folder.iterdir()),[])

    def test_expired_binding_is_not_eligible(self):
        a,b=gate_bindings(lease=COORD-1,coordinate=COORD-2)
        c=CapabilityConstructionCompiler(ConstructionInventory((a,b)),policies(a,b))
        with self.assertRaises(ConstructionRefused):c.compile(INTENTION)

    def test_expired_construction_permission_refused(self):
        a,b=gate_bindings()
        c=CapabilityConstructionCompiler(ConstructionInventory((a,b)),policies(a,b,expiry=COORD-1))
        with self.assertRaises(ConstructionRefused):c.compile(INTENTION)

    def test_changed_permission_invalidates_existing_plan(self):
        a,b=gate_bindings()
        c=CapabilityConstructionCompiler(ConstructionInventory((a,b)),policies(a,b))
        p=c.compile(INTENTION)
        c.authority=ConstructionPolicy(frozenset({(a.locus,a.operation)}),COORD+100)
        with self.assertRaises(ConstructionRefused):c.form(INTENTION,p)

    def test_changed_primitive_observation_invalidates_plan(self):
        a,b=gate_bindings()
        c=CapabilityConstructionCompiler(ConstructionInventory((a,b)),policies(a,b))
        p=c.compile(INTENTION)
        c.inventory=ConstructionInventory((replace(a,estimated_quanta=2),b))
        with self.assertRaises(ConstructionRefused):c.form(INTENTION,p)

    def test_reversed_evidence_not_equivalent(self):
        a,b=gate_bindings()
        c=CapabilityConstructionCompiler(ConstructionInventory((a,b)),policies(a,b))
        p=c.compile(INTENTION)
        altered=replace(p,bindings=tuple(reversed(p.bindings)))
        with self.assertRaises(ConstructionRefused):c.form(INTENTION,altered)

    def test_no_formation_grant_refuses_before_staging(self):
        a,b,folder=self.receiving_bindings()
        c=CapabilityConstructionCompiler(ConstructionInventory((a,b)),policies(a,b))
        with self.assertRaises(ConstructionRefused):c.form(INTENTION,c.compile(INTENTION))
        self.assertEqual(list(folder.iterdir()),[])

    def test_wrong_formation_grant_refuses_before_staging(self):
        a,b,folder=self.receiving_bindings()
        c=CapabilityConstructionCompiler(ConstructionInventory((a,b)),policies(a,b))
        bad=FormationPolicy(frozenset({("other-surface","python")}),COORD+100)
        with self.assertRaises(ConstructionRefused):c.form(INTENTION,c.compile(INTENTION),formation_policy=bad)
        self.assertEqual(list(folder.iterdir()),[])

    def test_resource_cost_bound_prevents_construction(self):
        a,b=gate_bindings(compose_cost=50,apply_cost=50)
        c=CapabilityConstructionCompiler(ConstructionInventory((a,b)),policies(a,b,max_quanta=10))
        with self.assertRaises(ConstructionRefused):c.compile(INTENTION)

    def test_event_budget_blocks_distant_gate_path(self):
        a,b=gate_bindings()
        c=CapabilityConstructionCompiler(ConstructionInventory((a,b)),policies(a,b,max_events=20))
        with self.assertRaises(ConstructionRefused):c.compile(INTENTION)

    def test_wrong_modulus_blocks_port_candidate(self):
        a,b=gate_bindings(modulus=97)
        c=CapabilityConstructionCompiler(ConstructionInventory((a,b)),policies(a,b))
        with self.assertRaises(ConstructionRefused):c.compile(INTENTION)

    def test_runtime_port_corruption_refused_by_ground_oracle(self):
        class AdversarialGate(TwoPortArithmeticGate):
            def invoke(self,opcode,frame):
                value=super().invoke(opcode,frame)
                if opcode=="compose" and frame.get("first")==[1,0]:
                    return (0,0)
                return value
        a=AdversarialGate("lying-compose",65521)
        b=TwoPortArithmeticGate("correct-apply",65521)
        ga=observe_gate(a,locus="lying",operation=COMPOSE,coordinate=COORD,lease_until=COORD+1)
        gb=observe_gate(b,locus="good",operation=APPLY,coordinate=COORD,lease_until=COORD+1)
        compiler=CapabilityConstructionCompiler(ConstructionInventory((ga,gb)),policies(ga,gb))
        plan=compiler.compile(INTENTION)
        with self.assertRaises((ConstructionRefused,ValueError)):compiler.form(INTENTION,plan)

    def test_wrong_port_response_during_qualification_rejected(self):
        class Liar:
            modulus=65521
            def invoke(self,opcode,frame):return 8
        with self.assertRaises(ConstructionRefused):
            observe_gate(Liar(),locus="lying",operation=COMPOSE,coordinate=COORD,lease_until=COORD+1)

    def test_boolean_cost_and_lease_refused(self):
        a,b=gate_bindings()
        with self.assertRaises(ConstructionRefused):replace(a,estimated_quanta=True)
        with self.assertRaises(ConstructionRefused):replace(a,expires_at=True)
        with self.assertRaises(ConstructionRefused):ConstructionPolicy(frozenset({(a.locus,COMPOSE)}),True)

    def test_duplicate_primitive_at_locus_refused(self):
        a,b=gate_bindings()
        with self.assertRaises(ConstructionRefused):ConstructionInventory((a,a,b))

    def test_unknown_primitive_cannot_promote_advertisement(self):
        a,b=gate_bindings()
        with self.assertRaises(ConstructionRefused):replace(a,operation="arbitrary.remote.exec")
        with self.assertRaises(ConstructionRefused):ConstructionPolicy(frozenset({("any","*")}),COORD+1)

    def test_small_coordinate_requires_only_apply(self):
        a,b=gate_bindings(coordinate=0,lease=COORD+100)
        zero=GroundIntention("zero",GROUND,0)
        c=CapabilityConstructionCompiler(ConstructionInventory((a,b)),policies(a,b))
        # The bound ports may also be present at 0; their challenge is independent of time.
        _,receipt=c.form(zero,c.compile(zero))
        self.assertEqual(receipt.payload["output"],{"value":GROUND.seed})
        self.assertEqual(receipt.payload["event_count"],1)

    def test_distinct_ground_and_observer_not_interchangeable(self):
        a,b=gate_bindings()
        c=CapabilityConstructionCompiler(ConstructionInventory((a,b)),policies(a,b))
        _,receipt=c.form(INTENTION,c.compile(INTENTION))
        other=GroundIntention("different",GROUND,COORD)
        policy=RealizationPolicy(frozenset({(receipt.payload["locus"],receipt.payload["method"])}),COORD+100)
        with self.assertRaises(ValueError):verify_receipt(receipt,other,policy)


if __name__ == "__main__":
    unittest.main()
