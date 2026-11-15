"""Opaque path has no E-CPU installation or awareness of the observer."""
import unittest
import json
from dataclasses import replace
from hashlib import sha256
from mailcpu.latent_path_capacity import (
    CapacityRefused, CapacityCertificate, recognize_capacity,
    verify_live_capacity,
)

CONTEXT = sha256(b"capacity-observation-local-contract").hexdigest()


class UnawarePath:
    """A pre-existing communication relation composed of two opaque stages."""
    def __init__(self, first=(3, 5), second=(7, 11), mod=101):
        self.first, self.second, self.mod = first, second, mod
        self.calls = 0

    def transmit(self, x):
        self.calls += 1
        wire_state = (self.first[0]*x + self.first[1]) % self.mod
        return (self.second[0]*wire_state + self.second[1]) % self.mod


def independent_power(a, b, mod, x, tick):
    # Separate affine monoid exponentiation used only as an independent oracle.
    la, lb = 1, 0
    while tick:
        if tick & 1:
            la, lb = a*la % mod, (a*lb + b) % mod
        a, b = a*a % mod, (a*b + b) % mod
        tick >>= 1
    return (la*x + lb) % mod


def independent_finite_orbit(path, x0, tick):
    """Separate bounded state-enumeration oracle; no exponentiation or E-CPU."""
    seen = {}
    values = []
    x = x0
    while x not in seen:
        seen[x] = len(values)
        values.append(x)
        x = path.transmit(x)
    mu = seen[x]
    period = len(values) - mu
    index = tick if tick < len(values) else mu + (tick - mu) % period
    return values[index]


class CapacityTests(unittest.TestCase):
    def cert(self, path=None):
        path = path or UnawarePath()
        return recognize_capacity(path.transmit, path_id="anonymous-connection-a",
                                  snapshot_id="epoch-1", context_digest=CONTEXT,
                                  modulus=path.mod)

    def test_preexisting_path_certifies_without_ecpu_installation(self):
        p=UnawarePath(); c=self.cert(p)
        self.assertEqual((c.multiplier,c.increment),(21,46))
        self.assertEqual(p.calls,101)
        self.assertEqual(c.coverage,"whole_declared_finite_domain_one_snapshot")

    def test_independent_realizers_share_semantic_ground_not_evidence(self):
        left=self.cert()
        right=recognize_capacity(UnawarePath(first=(1,0),second=(21,46)).transmit,
                                 path_id="different-connection",snapshot_id="epoch-b",
                                 context_digest=CONTEXT,modulus=101)
        self.assertEqual(left.ground_digest,right.ground_digest)
        self.assertNotEqual(left.evidence_digest,right.evidence_digest)
        for t in [0,1,2,10,10**30+11]:
            self.assertEqual(left.state_at(39,t),right.state_at(39,t))

    def test_jump_large_coordinate_matches_independent_oracle(self):
        c=self.cert()
        for t in [0,1,2,3,39,101,12345,10**30+11]:
            self.assertEqual(c.state_at(39,t),independent_power(21,46,101,39,t))

    def test_huge_coordinate_matches_finite_orbit_cycle_oracle(self):
        p=UnawarePath(); c=self.cert(p)
        for initial in (0,1,39,100):
            self.assertEqual(c.state_at(initial,10**30+11),
                             independent_finite_orbit(p,initial,10**30+11))

    def test_short_time_matches_actual_repeated_path_traversal(self):
        p=UnawarePath(); c=self.cert(p); x=39
        for t in range(30):
            self.assertEqual(c.state_at(39,t),x)
            x=p.transmit(x)

    def test_single_hidden_exception_refuses_full_domain(self):
        p=UnawarePath()
        def malicious(x):
            r=p.transmit(x)
            return (r+1)%101 if x==88 else r
        with self.assertRaises(CapacityRefused):
            recognize_capacity(malicious,path_id="anomalous-path",snapshot_id="e1",
                               context_digest=CONTEXT,modulus=101)

    def test_quadratic_path_refused(self):
        with self.assertRaises(CapacityRefused):
            recognize_capacity(lambda x:x*x%101,path_id="quadratic",snapshot_id="e1",
                               context_digest=CONTEXT,modulus=101)

    def test_round_trip_independent_certificate_reconstruction(self):
        c=self.cert()
        data=json.loads(json.dumps(c.to_dict()))
        self.assertEqual(CapacityCertificate.from_dict(data),c)

    def test_tampered_outputs_refused(self):
        c=self.cert(); data=c.to_dict(); data["outputs"][77]=(data["outputs"][77]+1)%101
        with self.assertRaises(CapacityRefused):CapacityCertificate.from_dict(data)

    def test_forged_ground_refused(self):
        c=self.cert();data=c.to_dict();data["ground_digest"]="0"*64
        with self.assertRaises(CapacityRefused):CapacityCertificate.from_dict(data)

    def test_wrong_schema_or_extra_field_refused(self):
        c=self.cert();d=c.to_dict();d["foreign_authority"]=True
        with self.assertRaises(CapacityRefused):CapacityCertificate.from_dict(d)

    def test_stale_snapshot_and_changed_relation_refused(self):
        p=UnawarePath(); c=self.cert(p)
        self.assertTrue(verify_live_capacity(c,p.transmit,snapshot_id="epoch-1",context_digest=CONTEXT))
        with self.assertRaises(CapacityRefused):
            verify_live_capacity(c,p.transmit,snapshot_id="epoch-2",context_digest=CONTEXT)
        p.second=(7,12)
        with self.assertRaises(CapacityRefused):
            verify_live_capacity(c,p.transmit,snapshot_id="epoch-1",context_digest=CONTEXT)

    def test_wrong_context_refused(self):
        c=self.cert()
        with self.assertRaises(CapacityRefused):
            verify_live_capacity(c,UnawarePath().transmit,snapshot_id="epoch-1",context_digest="0"*64)

    def test_strict_numeric_bounds(self):
        c=self.cert()
        for args in [(True,0),(0,True),(101,0),(0,-1)]:
            with self.assertRaises(CapacityRefused):c.state_at(*args)
        with self.assertRaises(CapacityRefused):
            recognize_capacity(lambda x:x,path_id="overbound",snapshot_id="e1",context_digest=CONTEXT,modulus=1000)

    def test_composite_modulus_is_also_supported(self):
        p=UnawarePath(first=(2,7),second=(5,9),mod=120)
        c=self.cert(p)
        self.assertEqual((c.multiplier,c.increment),(10,44))
        for t in [0,1,2,999999999]:
            self.assertEqual(c.state_at(22,t),independent_power(10,44,120,22,t))

    def test_no_probe_after_certificate_for_symbolic_navigation(self):
        p=UnawarePath();c=self.cert(p);before=p.calls
        self.assertIsInstance(c.state_at(39,10**30+11),int)
        self.assertEqual(p.calls,before)

    def test_path_metadata_cannot_mint_authority(self):
        c=self.cert(); self.assertNotIn("authorized",c.to_dict())
        self.assertNotIn("verified_host",c.to_dict())


if __name__ == "__main__":unittest.main()