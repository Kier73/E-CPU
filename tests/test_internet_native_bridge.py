"""INTERNET-002 E-CPU-native observer-path gating; requires real mailcpu package."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'examples'))
sys.path.insert(0,str(ROOT/'tests'))

NATIVE=importlib.util.find_spec('mailcpu') is not None


@unittest.skipUnless(NATIVE,'requires full native E-CPU package (hosted gate)')
class NativeGitObserverPathTests(unittest.TestCase):
    def setUp(self):
        from test_internet_graph_ground import NativeInternetGraphTests
        self.fixture=NativeInternetGraphTests('test_all_nine_native_service_operations')
        self.fixture.setUp()

    def invoke(self,admit=lambda _: True,base='A4',head='B5'):
        from native_git_observer_bridge import native_git_observation
        return native_git_observation(self.fixture.records.__getitem__,
            self.fixture.spec,manifest_sha256=self.fixture.outside_pin,
            base=base,head=head,receiver_policy_digest='7'*64,
            observed_at=8,receiver_admit=admit)

    def test_existing_observer_path_wraps_native_service_without_carrier(self):
        result=self.invoke()
        stage=result['native_observer_path']['stages']
        self.assertEqual(len(stage),1)
        self.assertEqual(stage[0]['mode'],'observe')
        self.assertEqual(stage[0]['source'],'github.git.compare')
        self.assertEqual(result['native_observer_receipt']['operation_id'],'git-compare-projection')
        self.assertEqual(result['native_observer_path']['verification_scope'],
                         'receiver_callbacks_not_external_attestation')

    def test_local_policy_refusal_is_authoritative(self):
        from mailcpu.observer_path_evidence import ObserverPathError
        with self.assertRaisesRegex(ObserverPathError,'did not admit'):
            self.invoke(admit=lambda _: False)
        with self.assertRaisesRegex(ObserverPathError,'did not admit'):
            self.invoke(admit=lambda _: 1)

    def test_changed_remote_parent_refuses_before_native_promotion(self):
        from verify_internet_graph_ground import InternetGraphRefused
        path=self.fixture.prefix+'/git/commits/'+self.fixture.nodes['M']['sha']
        self.fixture.records[path]['parents']=[]
        with self.assertRaisesRegex(InternetGraphRefused,'parent transitions'):
            self.invoke()

    def test_unlisted_intention_is_refused(self):
        from verify_internet_graph_ground import InternetGraphRefused
        with self.assertRaisesRegex(InternetGraphRefused,'does not belong'):
            self.invoke(base='B4',head='A4')


if __name__=='__main__':unittest.main()
