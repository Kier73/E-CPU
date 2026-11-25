"""Dependency qualification, coalescent convergence and unseen intentions."""
import itertools
import unittest
from mailcpu.affine_verification_ground import AffineVerificationGround
from mailcpu.affine_vocabulary import AffineVocabulary,discover
from mailcpu.affine_coalescent import CoalescentVocabulary,contribution
from mailcpu.runtime_qualification import affine_expected
from mailcpu.substrate_bootstrap import BootstrapRefused,digest


class CoalescenceTests(unittest.TestCase):
    def setUp(self):
        self.basis=AffineVerificationGround.form(5,1,65521,1)
        self.empty=CoalescentVocabulary.empty(self.basis)

    def test_independent_discovery_and_cross_composition(self):
        motifs=[sum(1<<i for i in range(j,36,3)) for j in range(3)]
        locals=[AffineVocabulary.form(self.basis,discover([t]*64)[0]) for t in motifs]
        packets=[contribution(self.basis,v.rules) for v in locals]
        union=self.empty.ingest(packets)
        for order in itertools.permutations(packets):
            self.assertEqual(self.empty.ingest(order).packet(),union.packet())
        self.assertEqual(union.ingest(packets).packet(),union.packet())
        self.assertEqual(self.empty.ingest(packets[:1]).ingest(packets[1:]).packet(),union.packet())
        train=[motifs[i%3]|motifs[(i+1)%3] for i in range(96)]
        evolved,packet,ledger=union.learn(train)
        self.assertEqual(ledger["rules"],3)
        self.assertEqual(len(union.rules),33)
        self.assertEqual(len(evolved.rules),36)
        for a,b,_,_ in packet["rules"]:
            self.assertTrue(any(a==t for t in motifs))
            self.assertTrue(any(b==t for t in motifs))
            self.assertFalse(any(a|b in {u|v for u,v,_,_ in local.rules} for local in locals))
        # Cross-contributor dependency packet alone is insufficient.
        with self.assertRaises(BootstrapRefused):
            self.empty.ingest([packet])
        self.assertEqual(self.empty.ingest([packet,*packets]).packet(),evolved.packet())
        held=[((motifs[0]|motifs[1]|motifs[2]) if i%4==0 else
               motifs[i%3]|motifs[(i+1)%3])|((i+1)<<36) for i in range(1024)]
        self.assertEqual(evolved.profile(held)["total"],7045)
        self.assertLess(evolved.profile(held)["total"],union.profile(held)["total"])
        for i,t in enumerate(held):
            self.assertEqual(evolved.advance(i,t),affine_expected(5,1,65521,i,t))

    def test_tamper_and_foreign_scope_are_atomic(self):
        v=AffineVocabulary.form(self.basis,((1,2),(3,4)))
        packet=contribution(self.basis,v.rules)
        valid=self.empty.ingest([packet])
        before=valid.packet()
        forged=contribution(self.basis,((1,2,v.rules[0][2],(v.rules[0][3]+1)%65521),))
        with self.assertRaises(BootstrapRefused):
            valid.ingest([forged])
        self.assertEqual(valid.packet(),before)
        foreign=AffineVerificationGround.form(5,2,65521,1)
        with self.assertRaises(BootstrapRefused):
            valid.ingest([contribution(foreign,())])
        self.assertEqual(valid.learn([7]*100,max_pair_visits=0)[0],valid)

    def test_alternative_proofs_coalesce(self):
        v=AffineVocabulary.form(self.basis,((1,2),(2,4),(3,4),(1,6)))
        result=self.empty.ingest([contribution(self.basis,v.rules)])
        self.assertEqual(len(result.rules),4)
        self.assertEqual(result.recipe(7),(7,))
        self.assertEqual(result.advance(314,7),affine_expected(5,1,65521,314,7))


if __name__=="__main__":
    unittest.main()
