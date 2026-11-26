"""MGA-001/J: symbolic controller discovery and full state navigation."""
import random
import unittest
from dataclasses import replace
from mailcpu.symbolic_switching_ground import SymbolicSource,SymbolicPathLaw,discover,verify_closure
from mailcpu.substrate_bootstrap import BootstrapRefused


def source():
    n=128
    high=((1<<n)-1)^7
    features=(0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa8|1,
              0xccccccccccccccccccccccccccccccc8|2,
              0xf0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0|4)
    identity=tuple(1<<i for i in range(n))
    branches=[]
    for b in (0,1):
        target=(features[1],features[2],features[0]^(features[1] if b else 0))
        rows=list(identity)
        for i in range(3,n):
            rows[i]=identity[3+(i-3+1)%(n-3)]^(features[b] if i==3 else 0)
        for i in range(3):
            rows[i]=target[i]
            for j in range(3,n):
                if (features[i]&high)>>j&1:
                    rows[i]^=rows[j]
        branches.append(tuple(rows))
    actions=(((1,1,0),(0,1,1),(0,0,1)),((1,0,2),(1,1,0),(0,0,1)))
    return SymbolicSource(n,1<<40,features[:2],(3,),tuple(branches),actions)


class SymbolicTests(unittest.TestCase):
    def test_closure_and_navigation(self):
        s=source()
        g=discover(s)
        self.assertEqual(len(g.basis),3)
        self.assertTrue(verify_closure(s,g))
        law=SymbolicPathLaw(s,g)
        self.assertEqual(law.state_count,8)
        self.assertEqual(s.branch(2),s.branch(6))
        self.assertNotEqual(s.branch(s.step(2,(0,0))[0]),s.branch(s.step(6,(0,0))[0]))
        rng=random.Random(20261125)
        for i in range(32):
            c=rng.getrandbits(128)
            z=(rng.randrange(1<<40),rng.randrange(1<<40))
            path=law.form_path(c)
            t=i*3%113
            y=(c,z)
            for _ in range(t):
                y=s.step(*y)
            self.assertEqual(law.navigate(path,c,z,t),y)
            a,b=10**40+i,10**31+i*5
            mid=law.navigate(path,c,z,a)
            self.assertEqual(law.navigate(law.form_path(mid[0]),*mid,b),
                             law.navigate(path,c,z,a+b))
        c,z=7,(123456789120,98765432128)
        self.assertEqual(law.navigate(law.form_path(c),c,z,10**100+123),
                         (int("ffffffffffffffffffffffffffffff1d",16),(169175195666,345679010491)))

    def test_refusal(self):
        s=source()
        g=discover(s)
        with self.assertRaises(BootstrapRefused):
            discover(s,max_features=2)
        with self.assertRaises(BootstrapRefused):
            verify_closure(s,replace(g,guard_codes=(0,g.guard_codes[1])))
        with self.assertRaises(BootstrapRefused):
            verify_closure(s,replace(g,ancestry=g.ancestry[:-1]+(("guard",0,0,0),)))
        with self.assertRaises(BootstrapRefused):
            verify_closure(s,replace(g,branch_codes=((0,)*3,g.branch_codes[1])))
        with self.assertRaises(BootstrapRefused):
            verify_closure(replace(s,guard_terms=(1,)),g)


if __name__=="__main__":
    unittest.main()
