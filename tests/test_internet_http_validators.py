"""Receiver-only offline HTTP conditional protocol contract tests."""
import json
from pathlib import Path
import sys
import unittest
from hashlib import sha256
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'examples'))
from probe_internet_http_validators import HTTPGroundRefused,observe_conditional_protocol,request_commit


class HTTPConditionalContractTests(unittest.TestCase):
    def setUp(self):
        self.repo='Kier73/E-CPU'
        self.commit='9a34c11147db7d8619b65b6058fa121ab9b1c43c'
        self.body=json.dumps({'sha':self.commit}).encode()
        self.etag='"stable-entity-validator"'

    def case(self,status,body,etag):
        return {'status':status,'body':body,'etag':etag,'entity_bytes_received':len(body),
                'entity_sha256':sha256(body).hexdigest(),'requester_elapsed_ns':201,
                'cache_control':'private,max-age=60','age':None,'via':None,'github_request_id':None}

    def read(self,repo,commit,tag):
        self.assertEqual((repo,commit),(self.repo,self.commit))
        if tag is None:return self.case(200,self.body,self.etag)
        if tag==self.etag:return self.case(304,b'',self.etag)
        return self.case(200,self.body,self.etag)

    def test_true_condition_and_negative_control(self):
        report=observe_conditional_protocol(self.read,repo=self.repo,commit_sha=self.commit)
        self.assertEqual(report['verdict'],'held-out-conditional-304-and-200-observed')
        self.assertEqual([z['status'] for z in report['observations']],[200,304,200])
        self.assertEqual(report['observations'][1]['entity_bytes_received'],0)

    def test_missing_validator_refused(self):
        def read(repo,commit,tag):
            return self.case(200,self.body,None)
        with self.assertRaisesRegex(HTTPGroundRefused,'validator'):
            observe_conditional_protocol(read,repo=self.repo,commit_sha=self.commit)

    def test_mismatched_response_refuses_claim_not_network(self):
        def read(repo,commit,tag):
            return self.case(200,self.body,self.etag)
        report=observe_conditional_protocol(read,repo=self.repo,commit_sha=self.commit)
        self.assertEqual(report['verdict'],'conditional-behavior-not-established-on-this-path')

    def test_tampered_body_measurement_refused(self):
        def read(repo,commit,tag):
            obs=self.read(repo,commit,tag)
            if tag==self.etag:obs['entity_sha256']='0'*64
            return obs
        with self.assertRaisesRegex(HTTPGroundRefused,'integrity'):
            observe_conditional_protocol(read,repo=self.repo,commit_sha=self.commit)

    def test_initial_commit_identity_pinned(self):
        def read(repo,commit,tag):
            return self.case(200,b'{"sha":"other"}',self.etag)
        with self.assertRaisesRegex(HTTPGroundRefused,'externally pinned'):
            observe_conditional_protocol(read,repo=self.repo,commit_sha=self.commit)

    def test_http_endpoint_does_not_allow_other_domains(self):
        with self.assertRaisesRegex(HTTPGroundRefused,'unadmitted'):
            request_commit('some.site@bad.example','0'*40)
        with self.assertRaisesRegex(HTTPGroundRefused,'unadmitted'):
            request_commit('Kier73/E-CPU','../../untrusted')


if __name__=='__main__':unittest.main()
