"""MGA-001/I: exact fibre aliases, minimal control state, nonlinear jumps."""
import unittest
from mailcpu.formed_switching_ground import FormedSwitchingLaw,normalize,verify_fibre
from mailcpu.switching_affine_ground import SwitchingLaw,form,navigate
from mailcpu.substrate_bootstrap import BootstrapRefused


def aliased_source():
    m=1<<40
    h=m//8
    matrices=[]
    for r in range(64):
        x,y=r%8,r//8
        c,d=(0,1) if x%2==0 else (1,0)
        matrices.append(((1+h*x,1+h*y,(c-h*x*x-h*y*y)%m),
                         (0,1,d),(0,0,1)))
    return SwitchingLaw(m,8,tuple(matrices))


class FormedSwitchingTests(unittest.TestCase):
    def test_fibre_and_minimality(self):
        law=aliased_source()
        formed=FormedSwitchingLaw(law)
        self.assertEqual(len(set(law.matrices)),64)
        self.assertEqual(len({normalize(law,r) for r in range(64)}),2)
        self.assertEqual(formed.state_count,4)
        for r in range(64):
            self.assertTrue(verify_fibre(law,r,normalize(law,r)))
            # Same x parity but different y parity: future switching differs.
            self.assertEqual(formed.machine.state_groups[r],formed.machine.state_groups[r%2+8*((r//8)%2)])
        for r in range(64):
            for j in range(16):
                x=(r%8+8*(r+1)*(j+31)*3,r//8+8*(r+1)*(j+31)*4)
                t=(r*17+j*31)%500
                g=formed.form_path(x)
                y=x
                for _ in range(t):
                    y=law.step(y)
                self.assertEqual(formed.navigate(g,x,t),y)
                u=10**70+r
                v=10**59+j
                mid=formed.navigate(g,x,u)
                self.assertEqual(formed.navigate(formed.form_path(mid),mid,v),
                                 formed.navigate(g,x,u+v))

    def test_huge_and_refusal(self):
        law=aliased_source()
        formed=FormedSwitchingLaw(law)
        x=(123456789120,98765432128)
        t=10**100+123
        g=formed.form_path(x)
        self.assertEqual(formed.navigate(g,x,t),(909984792262,831773184061))
        self.assertEqual(navigate(law,form(law,law.index(x)),x,t),formed.navigate(g,x,t))
        bad=((1,1,7),(0,1,0),(0,0,1))
        with self.assertRaises(BootstrapRefused):
            verify_fibre(law,0,bad)
        with self.assertRaises(BootstrapRefused):
            navigate(law,g,x,t)
        ident=((1,0,0),(0,1,0),(0,0,1))
        with self.assertRaises(BootstrapRefused):
            FormedSwitchingLaw(SwitchingLaw(1024,16,(ident,)*256))

    def test_singleton_fibres(self):
        ident=((1,0,0),(0,1,0),(0,0,1))
        law=SwitchingLaw(2,2,(ident,)*4)
        formed=FormedSwitchingLaw(law)
        for x in ((0,0),(1,0),(0,1),(1,1)):
            self.assertEqual(formed.navigate(formed.form_path(x),x,100),x)


if __name__=="__main__":
    unittest.main()
