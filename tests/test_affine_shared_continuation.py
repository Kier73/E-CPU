"""Native persistent affine continuation, changing intentions and host loss."""
import hashlib
import sqlite3
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from mailcpu.affine_shared_continuation import (
    Orbit, KIND, REQUEST, OPERATION, binding, retain, lookup, continue_observation,
)
from mailcpu.shared_result_bank import ResultBank
from mailcpu.substrate_bootstrap import (
    AdaptiveBootstrap, BootstrapPolicy, BootstrapRefused, CarrierBinding,
    ChannelObservation, OperationOffer, ResourceObservation, SubstrateObservation, digest,
)


class ContinuationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.banks = {n: ResultBank(Path(self.tmp.name)/f"{n}.db", create=True) for n in "abcd"}
        self.addCleanup(lambda: [b.close() for b in self.banks.values()])
        self.orbit = Orbit(5, 1, 65521, 314, digest("independent-source-epoch"))
        self.log = []

    def runtime(self, sites="abcd", edges=("ab","bc","bd"), grants=None):
        offer = OperationOffer(OPERATION, REQUEST, KIND, 1)
        resources = tuple(ResourceObservation(n, "port", 0, 10, "observer", digest(n), (offer,))
                          for n in sites)
        links = tuple(ChannelObservation(k, k[0], k[1], (KIND,), 1, 0, 10, digest(k))
                      for k in edges)
        def driver(k):
            def deliver(data, coordinate):
                self.log.append(k)
                return data
            return deliver
        return AdaptiveBootstrap(SubstrateObservation(resources, links),
                                 BootstrapPolicy(frozenset((n, OPERATION) for n in sites),
                                                 frozenset(edges if grants is None else grants), "owner"),
                                 tuple(binding(self.orbit, n) for n in sites),
                                 tuple(CarrierBinding(k, driver(k), digest(k)) for k in edges))

    def seed(self):
        retain(self.banks["a"], self.orbit, "a", "owner", self.orbit.value(0, self.orbit.x0))

    def test_new_intentions_survive_origin_loss_and_reopen(self):
        self.seed()
        t = 2**40 + 17
        first = continue_observation(self.runtime(), self.orbit, self.banks,
                                     [("a", 0)], t, ("c","d"), coordinate=1)
        self.assertEqual(self.log, ["ab","bc","bd"])
        self.assertEqual(first["retained_loci"], list("abcd"))
        self.assertEqual(first["dissemination"]["observations"]["c"], self.orbit.expected(t))
        self.assertEqual(first["horizon_bits"], 41)
        for n in "abcd":
            self.banks[n].close()
            self.banks[n] = ResultBank(Path(self.tmp.name)/f"{n}.db")
        self.log.clear()
        later = continue_observation(self.runtime("bcd", ("bc","bd")), self.orbit, self.banks,
                                     [("a",0),("b",t)], t+1, ("c","d"), coordinate=2)
        self.assertEqual(later["start"], {"locus":"b","coordinate":t,"delta":1})
        self.assertEqual(later["horizon_bits"], 1)
        self.assertEqual(later["cold_horizon_bits"], 41)
        self.assertEqual(self.log, ["bc","bd"])
        self.assertEqual(later["dissemination"]["observations"],
                         {n:self.orbit.expected(t+1) for n in "cd"})
        self.assertEqual(lookup(self.banks["b"], self.orbit, "b", "owner", t+1), self.orbit.expected(t+1))

    def test_warm_choice_and_missing_offers_do_not_produce(self):
        self.seed()
        for t in (3, 20):
            retain(self.banks["a"], self.orbit, "a", "owner", self.orbit.expected(t))
        before = self.banks["a"].produced
        result = continue_observation(self.runtime(), self.orbit, self.banks,
                                      [("a",3),("a",20),("a",21)], 22, ("a",), coordinate=1)
        self.assertEqual(result["start"]["coordinate"], 20)
        self.assertEqual(result["horizon_bits"], 2)
        self.assertIn(["a",21,"NOT_RETAINED"], result["candidates"])
        self.assertEqual(self.banks["a"].produced, before+1)  # only new result
        self.assertEqual(self.log, [])

    def test_authority_and_context_are_not_transferable(self):
        self.seed()
        self.assertIsNone(lookup(self.banks["a"], self.orbit, "b", "owner", 0))
        self.assertIsNone(lookup(self.banks["a"], self.orbit, "a", "other", 0))
        self.assertIsNone(lookup(self.banks["a"], replace(self.orbit,context=digest("new")),
                                 "a", "owner", 0))
        with self.assertRaises(BootstrapRefused):
            retain(self.banks["a"], self.orbit, "a", "owner", self.orbit.value(0, 0))
        with self.assertRaises(BootstrapRefused):
            continue_observation(self.runtime(grants=("ab","bc")), self.orbit, self.banks,
                                 [("a",0)], 8, ("d",), coordinate=1)
        self.assertEqual(self.log, [])

    def test_coherently_rehashed_false_retained_value_refused(self):
        self.seed()
        wrong = b'{"coordinate":0,"ground":"' + self.orbit.ground.encode() + b'","value":"00000000"}'
        with self.banks["a"].db:
            self.banks["a"].db.execute("UPDATE result SET output=?,output_digest=?",
                                       (wrong, hashlib.sha256(wrong).hexdigest()))
        with self.assertRaises(ValueError):
            continue_observation(self.runtime(), self.orbit, self.banks,
                                 [("a",0)], 8, ("d",), coordinate=1)
        self.assertEqual(self.log, [])

    def test_exact_repeated_continuations_against_direct_oracle(self):
        self.seed()
        previous = 0
        for t in (1, 2, 19, 1000, 1001, 2**32, 2**32+9):
            r = continue_observation(self.runtime(), self.orbit, self.banks,
                                     [("a",previous)], t, ("a","c"), coordinate=1)
            self.assertEqual(r["start"]["delta"], t-previous)
            self.assertEqual(r["dissemination"]["observations"]["c"], self.orbit.expected(t))
            previous = t


if __name__ == "__main__":
    unittest.main()
