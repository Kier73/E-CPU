"""MGA-001/H: coupled switching, ordered return maps and adversarial proofs."""
import random
import unittest
from dataclasses import replace
from mailcpu.switching_affine_ground import SwitchingLaw, form, verify, navigate
from mailcpu.substrate_bootstrap import BootstrapRefused


def source(q,m,mode):
    rng=random.Random(20261125+q+m)
    maps=[]
    for i in range(q*q):
        x,y=i%q,i//q
        j=(i+1)%(q*q) if mode=="cycle" else min(i+1,q*q-1) if mode=="tail" else rng.randrange(q*q)
        a,b,c,d=1+2*rng.randrange(16),rng.randrange(16),rng.randrange(16),1+2*rng.randrange(16)
        maps.append(((a,b,(j%q-a*x-b*y+q*rng.randrange(64))%m),
                     (c,d,(j//q-c*x-d*y+q*rng.randrange(64))%m),(0,0,1)))
    return SwitchingLaw(m,q,tuple(maps))


class SwitchingTests(unittest.TestCase):
    def test_exact_direct_and_semigroup(self):
        rng=random.Random(91)
        for q in (2,4,8):
            m=q*1024
            for mode in ("cycle","tail","random"):
                law=source(q,m,mode)
                for _ in range(12):
                    x=(rng.randrange(m),rng.randrange(m))
                    ground=form(law,law.index(x))
                    self.assertTrue(verify(law,ground))
                    t=rng.randrange(400)
                    y=x
                    for _ in range(t):
                        y=law.step(y)
                    self.assertEqual(navigate(law,ground,x,t),y)
                    u=10**70+rng.randrange(1000)
                    v=10**61+rng.randrange(1000)
                    mid=navigate(law,ground,x,u)
                    self.assertEqual(navigate(law,form(law,law.index(mid)),mid,v),
                                     navigate(law,ground,x,u+v))

    def test_transient_and_large_cycle(self):
        law=source(8,1<<40,"cycle")
        ground=form(law,0)
        self.assertEqual((ground.transient,ground.period),(0,64))
        self.assertEqual(navigate(law,ground,(0,0),10**100+123)[0]%8,3)
        tail=form(source(8,1<<40,"tail"),0)
        self.assertEqual((tail.transient,tail.period),(63,1))

    def test_bad_proof_budget_and_quotient(self):
        law=source(4,4096,"cycle")
        ground=form(law,0)
        with self.assertRaises(BootstrapRefused):
            form(law,0,max_visits=2)
        with self.assertRaises(BootstrapRefused):
            verify(law,replace(ground,path=(0,2,1)+ground.path[3:]))
        with self.assertRaises(BootstrapRefused):
            verify(law,replace(ground,prefix=(ground.prefix[0],)*len(ground.prefix)))
        with self.assertRaises(BootstrapRefused):
            navigate(law,ground,(1,0),1)
        with self.assertRaises(BootstrapRefused):
            verify(source(4,4096,"tail"),ground)
        with self.assertRaises(BootstrapRefused):
            SwitchingLaw(4095,4,law.matrices)


if __name__=="__main__":
    unittest.main()
