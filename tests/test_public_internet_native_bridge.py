"""Native MailCPU contract test: never mistake URL contents for authority."""
import importlib.util
from hashlib import sha256
import unittest

try:
    NATIVE = importlib.util.find_spec('mailcpu.observer_path_evidence') is not None
except ModuleNotFoundError:
    NATIVE = False

from mailcpu.public_internet_navigation import Policy, Response, navigate


@unittest.skipUnless(NATIVE, "requires full native E-CPU repository package")
class NativePublicBridgeTests(unittest.TestCase):
    def setUp(self):
        self.policy = Policy((9293,), 793)
        def fetch(url, **kw):
            return Response(
                b'<html><title>TCP</title><a href="rfc793.html">old</a></html>'
                if url.endswith('9293.html') else
                b'<html><title>RFC793</title></html>',200,"text/html")
        self.capsule = navigate(self.policy, fetch)

    def test_receiver_admission_creates_native_receipt(self):
        from examples.native_public_navigation_bridge import admit_navigation
        result = admit_navigation(self.capsule,self.policy,
            expected_capsule_sha256=self.capsule['capsule_digest'],
            receiver_policy_digest=sha256(b'local-receiver-policy').hexdigest(),
            observed_at=7,receiver_admit=lambda stage: stage.mode=='observe')
        self.assertEqual(result['observation']['status'],'reached_observed_target')
        self.assertEqual(len(result['native_observer_path']['stages']),1)

    def test_receiver_refuses_without_authority(self):
        from examples.native_public_navigation_bridge import admit_navigation
        with self.assertRaises(Exception):
            admit_navigation(self.capsule,self.policy,
                receiver_policy_digest=sha256(b'local-receiver-policy').hexdigest(),
                observed_at=7,receiver_admit=lambda stage: False)

    def test_receiver_refuses_outside_capsule_pin(self):
        from examples.native_public_navigation_bridge import admit_navigation
        with self.assertRaises(Exception):
            admit_navigation(self.capsule,self.policy,expected_capsule_sha256='0'*64,
                receiver_policy_digest=sha256(b'local-receiver-policy').hexdigest(),
                observed_at=7,receiver_admit=lambda stage: True)


if __name__ == '__main__': unittest.main()
