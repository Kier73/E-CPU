"""Adversarial replay of an independently pinned local HTTP report."""
from __future__ import annotations
import copy
from pathlib import Path
import sys
import json
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'examples'))
from verify_internet_path_report import verify_record, read_report
from probe_internet_path_nginx import InternetPathRefused, digest, make_data

class ReportEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report=read_report(ROOT/'reports/local_nginx_path.json') if (ROOT/'reports/local_nginx_path.json').is_file() else None
        cls.pin=digest(make_data())

    def check(self,record=None):
        return verify_record(record if record is not None else self.report,
                             receiver_expected_source_sha256=self.pin)

    def test_independent_report_replay_consistency(self):
        if self.report is None:self.skipTest('checked-in local report not present')
        res=self.check()
        self.assertEqual(res['records_checked'],80)
        self.assertIn('consistency-only',res['classification'])

    def test_missing_or_changed_receiver_pin_refused(self):
        if self.report is None:self.skipTest('checked-in local report not present')
        with self.assertRaises(InternetPathRefused):
            verify_record(self.report,receiver_expected_source_sha256='0'*64)

    def test_fake_rehashed_one_offline_range_refused(self):
        if self.report is None:self.skipTest('checked-in local report not present')
        bad=copy.deepcopy(self.report)
        bad['offline_qualified_receipts'][1]['response_body_sha256']='f'*64
        with self.assertRaises(InternetPathRefused):self.check(bad)

    def test_fake_304_source_revision_refused(self):
        if self.report is None:self.skipTest('checked-in local report not present')
        bad=copy.deepcopy(self.report)
        bad['offline_qualified_receipts'][2]['source_sha256']=bad['changed_source_sha256']
        with self.assertRaises(InternetPathRefused):self.check(bad)

    def test_forged_origin_offline_control_refused(self):
        if self.report is None:self.skipTest('checked-in local report not present')
        bad=copy.deepcopy(self.report)
        bad['origin_offline_proxy_bypass_status']=200
        with self.assertRaises(InternetPathRefused):self.check(bad)

    def test_duplicate_record_json_refused(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as root:
            p=Path(root)/'bad.json'
            p.write_text('{"schema":"one","schema":"another"}')
            with self.assertRaises(InternetPathRefused):read_report(p)

if __name__=='__main__':unittest.main()
