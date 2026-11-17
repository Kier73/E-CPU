"""INTERNET-003 real TCP Nginx path and independent refusal tests."""
from __future__ import annotations
import importlib.util
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

HERE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(HERE/'examples'))
from probe_internet_path_nginx import (InternetPathRefused, NginxPath,
        make_data, verify_response, digest, experiment)


class IndependentResponseTests(unittest.TestCase):
    def setUp(self):
        self.source=make_data()
        self.basic={'status':200,'headers':{'etag':'"abc"'},'body':self.source,
                    'route':'direct-origin','elapsed_ns':5}

    def test_complete(self):
        self.assertEqual(verify_response(self.basic,current_source=self.source,
                                         mode='complete')['source_sha256'],digest(self.source))

    def test_changed_full_source_is_not_a_valid_result(self):
        with self.assertRaisesRegex(InternetPathRefused,'source pin'):
            verify_response(self.basic,current_source=make_data(mutation=True),mode='complete')

    def test_wrong_full_result_refuses_even_if_metadata_is_rehashed(self):
        altered={**self.basic,'body':b'changed'}
        with self.assertRaises(InternetPathRefused):
            verify_response(altered,current_source=self.source,mode='complete')

    def test_conditional_needs_independent_complete_observation(self):
        reference=verify_response(self.basic,current_source=self.source,mode='complete')
        response={'status':304,'headers':{'etag':'"abc"'},'body':b'', 'route':'proxy', 'elapsed_ns':8}
        self.assertEqual(verify_response(response,current_source=self.source,mode='conditional',
              supplied_etag='"abc"',baseline_reference=reference)['status'],304)
        for wrong in (None,{}, {**reference,'source_sha256':'0'*64},
                      {**reference,'etag':'"stale"'}, {**reference,'status':206}):
            with self.subTest(wrong=wrong),self.assertRaises(InternetPathRefused):
                verify_response(response,current_source=self.source,mode='conditional',
                    supplied_etag='"abc"',baseline_reference=wrong)

    def test_conditional_refuses_changed_origin_or_forged_tag(self):
        reference=verify_response(self.basic,current_source=self.source,mode='complete')
        response={'status':304,'headers':{'etag':'"abc"'},'body':b'', 'route':'proxy', 'elapsed_ns':8}
        with self.assertRaises(InternetPathRefused):
            verify_response(response,current_source=make_data(mutation=True),
                mode='conditional',supplied_etag='"abc"',baseline_reference=reference)
        for changed in ({**response,'headers':{'etag':'"another"'}},
                        {**response,'body':b'liar'}, {**response,'status':200}):
            with self.subTest(changed=changed),self.assertRaises(InternetPathRefused):
                verify_response(changed,current_source=self.source,mode='conditional',
                    supplied_etag='"abc"',baseline_reference=reference)

    def test_exact_range(self):
        result={**self.basic,'status':206,'body':self.source[21:222],
                'headers':{'etag':'"abc"','content-range':f'bytes 21-221/{len(self.source)}'}}
        self.assertEqual(verify_response(result,current_source=self.source,
                mode='range',offset=21,length=201)['payload_bytes'],201)
        with self.assertRaises(InternetPathRefused):
            verify_response(result,current_source=self.source,mode='range',offset=22,length=201)

    def test_range_rehash_or_wrong_metadata_refused(self):
        result={**self.basic,'status':206,'body':self.source[21:222],
                'headers':{'etag':'"abc"','content-range':f'bytes 21-221/{len(self.source)}'}}
        for bad in ({**result,'body':result['body']+b'x'},
                    {**result,'headers':{**result['headers'],'content-range':'bytes 21-221/4'}},
                    {**result,'status':200}):
            with self.subTest(bad=bad),self.assertRaises(InternetPathRefused):
                verify_response(bad,current_source=self.source,mode='range',offset=21,length=201)

    def test_invalid_ground_and_request_parameters(self):
        for mode in ('unknown', 'gzip-range', ''):
            with self.subTest(mode=mode),self.assertRaises(InternetPathRefused):
                verify_response(self.basic,current_source=self.source,mode=mode)
        for offset,length in ((-1,100),(1,-1),(len(self.source),1),(0,None)):
            with self.subTest(offset=offset,length=length),self.assertRaises(InternetPathRefused):
                verify_response({**self.basic,'status':206},current_source=self.source,
                    mode='range',offset=offset,length=length)

    def test_bad_encoding_or_bad_response_type(self):
        for obj in ({**self.basic,'body':'raw'},
                    {**self.basic,'headers':'etag'},
                    {**self.basic,'status':True},
                    {**self.basic,'headers':{'etag':'"abc"','content-encoding':'gzip'}}):
            with self.subTest(obj=str(obj)[:40]),self.assertRaises((InternetPathRefused,OSError)):
                verify_response(obj,current_source=self.source,mode='complete')

    def test_wrong_compression_scope_refuses(self):
        import gzip
        compressed=gzip.compress(self.source)
        msg={**self.basic,'body':compressed,'headers':{'content-encoding':'gzip','etag':'W/"abc"'}}
        self.assertEqual(verify_response(msg,current_source=self.source,mode='complete')['payload_bytes'],len(compressed))
        msg['body']=gzip.compress(self.source+b'other')
        with self.assertRaises(InternetPathRefused):
            verify_response(msg,current_source=self.source,mode='complete')


@unittest.skipUnless(shutil.which('nginx') is not None,'requires already installed nginx binary')
class RealNginxProtocolTests(unittest.TestCase):
    def test_entire_real_protocol_path_with_origin_loss(self):
        report=experiment()
        self.assertEqual(report['cache_hit'],'HIT')
        self.assertEqual(report['cache_miss'],'MISS')
        self.assertTrue(report['origin_get_avoided_on_warm'])
        self.assertTrue(report['changed_source_refused_against_stale_cache'])
        self.assertTrue(report['origin_offline_after_stop'])
        self.assertEqual(report['origin_offline_proxy_bypass_status'],502)
        self.assertEqual(report['offline_qualified_queries'],80)
        self.assertEqual(report['offline_statuses'],{'200':40,'206':20,'304':20})
        self.assertLess(report['compressed_bytes'],report['source_bytes'])

    def test_live_negative_precondition_range_and_if_range(self):
        with tempfile.TemporaryDirectory(prefix='internet003-tests-') as root:
            with NginxPath(Path(root)) as p:
                original=make_data()
                result=p.request(via_proxy=True)
                reference=verify_response(result,current_source=original,mode='complete')
                # A missing ETag does not prevent regular GET, but cannot prove a 304.
                changed=p.request(via_proxy=True,headers={'If-None-Match':'"unrelated"'})
                self.assertEqual(changed['status'],200)
                self.assertEqual(changed['body'],original)
                invalid=p.request(via_proxy=True,headers={'Range':f'bytes={len(original)+3}-{len(original)+8}'})
                self.assertEqual(invalid['status'],416)
                # Mismatched If-Range means send complete representation instead.
                ifrange=p.request(via_proxy=True,headers={'Range':'bytes=2-101','If-Range':'"wrong"'})
                self.assertEqual(ifrange['status'],200)
                self.assertEqual(ifrange['body'],original)


if __name__=='__main__':unittest.main()
