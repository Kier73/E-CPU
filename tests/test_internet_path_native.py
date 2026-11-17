"""Native MailCPU adapter gates; full package required in GitHub Actions."""
from __future__ import annotations
import importlib.util
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'examples'))
NATIVE=importlib.util.find_spec('mailcpu') is not None

@unittest.skipUnless(NATIVE and shutil.which('nginx'),
                     'native E-CPU and local Nginx required')
class NativeInternetHttpPathTests(unittest.TestCase):
    def setUp(self):
        from probe_internet_path_nginx import NginxPath, make_data, verify_response
        self.temp=tempfile.TemporaryDirectory(prefix='internet003-native-')
        self.addCleanup(self.temp.cleanup)
        self.p=NginxPath(Path(self.temp.name))
        self.p.__enter__()
        self.addCleanup(lambda:self.p.__exit__(None,None,None))
        self.source=make_data()
        self.full=self.p.request(via_proxy=True)
        self.record=verify_response(self.full,current_source=self.source,mode='complete')

    def invoke(self,observed=None,mode='complete',source=None,admit=None,**kw):
        from native_http_path_bridge import admit_http_observation
        return admit_http_observation(observed if observed is not None else self.full,
            receiver_source=self.source if source is None else source,mode=mode,
            receiver_policy_digest='f'*64,observed_at=123,
            receiver_admit=admit if admit is not None else (lambda _:True),**kw)

    def test_native_transform_path_receipt(self):
        result=self.invoke()
        self.assertEqual(result['native_path']['stages'][0]['mode'],'transform')
        self.assertEqual(result['native_path']['stages'][0]['source'],'nginx.proxy.http')
        self.assertEqual(result['native_path']['verification_scope'],
                         'receiver_callbacks_not_external_attestation')
        self.assertEqual(result['native_receipt']['operation_id'],'http-source-bound-response')

    def test_refuses_locally_denied_or_nonboolean_permission(self):
        from mailcpu.observer_path_evidence import ObserverPathError
        for denied in (False,None,1):
            with self.subTest(denied=denied),self.assertRaises(ObserverPathError):
                self.invoke(admit=lambda _:denied)

    def test_refuses_mutated_input_and_unsanctioned_route(self):
        from probe_internet_path_nginx import InternetPathRefused,make_data
        with self.assertRaises(InternetPathRefused):
            self.invoke(source=make_data(mutation=True))
        with self.assertRaises(InternetPathRefused):
            self.invoke(observed=self.p.request(via_proxy=False))

    def test_admits_range_and_conditional_only_against_receiver_pins(self):
        from probe_internet_path_nginx import InternetPathRefused
        p=self.p
        limited=p.request(via_proxy=True,headers={'Range':'bytes=23-126'})
        narrowed=self.invoke(observed=limited,mode='range',offset=23,length=104)
        self.assertEqual(narrowed['native_path']['stages'][0]['mode'],'transform')
        selected=p.request(via_proxy=True,headers={'If-None-Match':self.record['etag']})
        result=self.invoke(observed=selected,mode='conditional',
                           supplied_etag=self.record['etag'],baseline_reference=self.record)
        self.assertEqual(result['native_receipt']['operation_id'],'http-source-bound-response')
        with self.assertRaises(InternetPathRefused):
            self.invoke(observed=selected,mode='conditional',supplied_etag=self.record['etag'])

if __name__=='__main__':unittest.main()
