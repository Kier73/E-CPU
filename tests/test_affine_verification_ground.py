"""MGA-001/E: reusable exact map verification and receiver integration."""
import json
import random
import unittest
from dataclasses import replace

from mailcpu.affine_verification_ground import (
    AffineVerificationGround, cold_multiplications, warm_multiplications,
    preparation_multiplications, profile, select_width,
)
from mailcpu.affine_shared_continuation import Orbit, retain, lookup, continue_observation
from mailcpu.runtime_qualification import affine_expected
from mailcpu.substrate_bootstrap import BootstrapRefused, digest
from test_affine_shared_continuation import ContinuationTests


class VerificationGroundTests(unittest.TestCase):
    def test_all_widths_against_native_and_sequential(self):
        rng = random.Random(20261125)
        for w in range(1,9):
            for a,c,m in [(5,1,65521),(0,7,16),(1,3,8),(6,2,12),(0,0,2)]:
                ground = AffineVerificationGround.form(a,c,m,w)
                restored = AffineVerificationGround.restore(json.loads(json.dumps(ground.snapshot())),law=(a,c,m))
                for _ in range(30):
                    x = rng.randrange(m)
                    t = rng.randrange(1<<63)
                    self.assertEqual(restored.advance(x,t),affine_expected(a,c,m,x,t))
                for x in range(min(m,8)):
                    y=x
                    for t in range(40):
                        self.assertEqual(ground.advance(x,t),y)
                        y=(a*y+c)%m

    def test_tamper_rehashed_and_scope(self):
        g=AffineVerificationGround.form(5,1,65521,4)
        raw=g.snapshot()
        raw["rows"][9][7][0]=(raw["rows"][9][7][0]+1)%65521
        raw["digest"]=digest({k:v for k,v in raw.items() if k!="digest"})
        with self.assertRaises(BootstrapRefused):
            AffineVerificationGround.restore(raw,law=(5,1,65521))
        with self.assertRaises(BootstrapRefused):
            AffineVerificationGround.restore(g.snapshot(),law=(5,2,65521))
        with self.assertRaises(BootstrapRefused):
            g.expected(Orbit(5,2,65521,314,digest("context")),1)
        for t in (-1,1<<63,True):
            with self.assertRaises(BootstrapRefused):
                g.advance(3,t)

    def test_aliased_rows_do_not_skip_boundary_checks(self):
        # width 1 has equal-sized rows; repeated object identity must not
        # bypass arithmetic checks at the row boundary.
        row=((1,0),(5,1))
        with self.assertRaises(BootstrapRefused):
            AffineVerificationGround(5,1,65521,1,(row,)*63)

    def test_cost_model_and_cold_selection(self):
        t=(1<<63)-1
        self.assertEqual(cold_multiplications(t),253)
        self.assertEqual(warm_multiplications(t,4),16)
        self.assertEqual(preparation_multiplications(4),(584,494))
        self.assertIsNone(select_width([1])["selected"])
        self.assertIsNone(select_width([t]*1000,max_entries=0)["selected"])
        choice=select_width([t]*1000)
        self.assertIsNotNone(choice["selected"])
        p=profile([t]*1000,choice["selected"])
        self.assertLess(p["total"],p["cold"])
        self.assertEqual(p["total"],p["producer"]+p["admission"]+p["queries"])


class NativeVerificationIntegration(unittest.TestCase):
    def test_retained_new_intention_uses_compiled_source_check(self):
        fixture=ContinuationTests()
        fixture.setUp()
        try:
            orbit=fixture.orbit
            g=AffineVerificationGround.form(orbit.a,orbit.c,orbit.m,4)
            retain(fixture.banks["a"],orbit,"a","owner",orbit.value(0,orbit.x0),verification_ground=g)
            t=2**40+17
            first=continue_observation(fixture.runtime(),orbit,fixture.banks,[("a",0)],t,("c","d"),
                                       coordinate=1,verification_ground=g)
            self.assertEqual(first["dissemination"]["observations"]["c"],orbit.expected(t))
            restored=AffineVerificationGround.restore(g.snapshot(),law=(orbit.a,orbit.c,orbit.m))
            second=continue_observation(fixture.runtime("bcd",("bc","bd")),orbit,fixture.banks,
                                        [("b",t)],t+1,("c","d"),coordinate=2,verification_ground=restored)
            self.assertEqual(second["start"]["delta"],1)
            self.assertEqual(lookup(fixture.banks["c"],orbit,"c","owner",t+1,verification_ground=restored),
                             orbit.expected(t+1))
        finally:
            fixture.doCleanups()


if __name__=="__main__":
    unittest.main()
