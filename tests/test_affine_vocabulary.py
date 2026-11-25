"""Independent native oracle and held-out workload."""
import json
import random
import unittest
from mailcpu.affine_verification_ground import AffineVerificationGround
from mailcpu.affine_vocabulary import AffineVocabulary, discover
from mailcpu.runtime_qualification import affine_expected
from mailcpu.substrate_bootstrap import BootstrapRefused,digest


class VocabularyTests(unittest.TestCase):
    def test_heldout(self):
        rng=random.Random(20261125)
        masks=[sum(1<<i for i in range(j,63,7)) for j in range(7)]
        def draw(n):
            return [masks[rng.randrange(7)] | (1<<rng.randrange(63)) |
                    (1<<rng.randrange(63)) for _ in range(n)]
        train,test=draw(400),draw(1000)
        pairs,ledger=discover(train)
        v=AffineVocabulary.form(AffineVerificationGround.form(5,1,65521,1),pairs)
        v=AffineVocabulary.restore(json.loads(json.dumps(v.snapshot())),law=(5,1,65521))
        self.assertGreater(len(pairs),0)
        self.assertGreater(len(set(test)-set(train)),0)
        self.assertLess(v.profile(test)["total"],v.profile(test)["binary_total"])
        for t in test+[0,1,(1<<63)-1]+[rng.randrange(1<<63) for _ in range(500)]:
            x=rng.randrange(65521)
            self.assertEqual(v.advance(x,t),affine_expected(5,1,65521,x,t))

    def test_admission(self):
        b=AffineVerificationGround.form(5,1,65521,1)
        self.assertEqual(discover([3]*20,max_pair_visits=0)[0],())
        self.assertEqual(discover([3])[0],())
        v=AffineVocabulary.form(b,((1,2),(3,4)))
        raw=v.snapshot()
        raw["rules"][-1][-1]=(raw["rules"][-1][-1]+1)%65521
        raw["digest"]=digest({k:x for k,x in raw.items() if k!="digest"})
        with self.assertRaises(BootstrapRefused):
            AffineVocabulary.restore(raw,law=(5,1,65521))
        with self.assertRaises(BootstrapRefused):
            AffineVocabulary.form(b,((1,2),(1,3)))
        with self.assertRaises(BootstrapRefused):
            AffineVocabulary.form(b,((3,4),))
        with self.assertRaises(BootstrapRefused):
            AffineVocabulary.restore(v.snapshot(),law=(5,2,65521))

    def test_noninvertible(self):
        for a,c,m in [(0,3,8),(6,2,12),(1,1,7)]:
            v=AffineVocabulary.form(AffineVerificationGround.form(a,c,m,1),((1,2),(3,4)))
            for x in range(m):
                for t in range(64):
                    self.assertEqual(v.advance(x,t),affine_expected(a,c,m,x,t))


if __name__=="__main__":
    unittest.main()
