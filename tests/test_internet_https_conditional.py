"""Independent, offline checks for the optional read-only Internet WAN probe."""
import base64
import hashlib
from pathlib import Path
import sys
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'examples'))
from probe_internet_https_conditional import (ENDPOINT,BLOB_SHA1,SOURCE_SHA256,
    HttpsPathRefused, verify_live_https)
import json

class ConditionalServiceObserverTests(unittest.TestCase):
    def fixture(self, *, status=304, mutate=False):
        source=(b'E-CPU fixture original bytes for an offline source whose pins differ from live.')
        sha1=hashlib.sha1(b'blob '+str(len(source)).encode()+b'\0'+source).hexdigest()
        sha256=hashlib.sha256(source).hexdigest()
        # The WAN verifier also requires the official known external pins,
        # so a fake fixture cannot masquerade as actual WAN evidence.
        self.assertNotEqual(sha1,BLOB_SHA1)
        self.assertNotEqual(sha256,SOURCE_SHA256)
        return source,sha1,sha256

    def test_wrong_pin_is_refused_before_network(self):
        with self.assertRaisesRegex(HttpsPathRefused,'pins'):
            verify_live_https(lambda *a,**kw: self.fail('network called'),
                external_blob_sha1='0'*40,external_source_sha256=SOURCE_SHA256)

    def test_malformed_or_unpinned_200_cannot_be_admitted(self):
        from probe_internet_https_conditional import strict_json
        with self.assertRaises(HttpsPathRefused):strict_json(b'{"a":1,"a":2}')
        with self.assertRaises(HttpsPathRefused):strict_json(b'[]')
        bad={'status':200,'headers':{'etag':'"some-etag"'},'body':b'{}','elapsed_ns':12}
        with self.assertRaises(HttpsPathRefused):
            verify_live_https(lambda *a,**kw:bad,
                external_blob_sha1=BLOB_SHA1,external_source_sha256=SOURCE_SHA256)

    def test_invalid_http_validator_is_refused_without_network(self):
        from probe_internet_https_conditional import raw_https_request
        with self.assertRaises(HttpsPathRefused):raw_https_request('https://unapproved.site/path')
        with self.assertRaises(HttpsPathRefused):raw_https_request(ENDPOINT,etag='bad\r\nX-Evil:1')

    def test_forged_blob_encoded_with_a_wrong_sha_rejected(self):
        item={'sha':BLOB_SHA1,'encoding':'base64','content':base64.b64encode(b'fake').decode()}
        msg={'status':200,'headers':{'etag':'"version"'},'body':json.dumps(item).encode()}
        with self.assertRaises(HttpsPathRefused):
            verify_live_https(lambda *a,**kw:msg,
                external_blob_sha1=BLOB_SHA1,external_source_sha256=SOURCE_SHA256)

if __name__=='__main__':unittest.main()
