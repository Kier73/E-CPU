"""Offline contract tests for INTERNET-001 independent remote observer."""
import base64
import hashlib
import unittest
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'examples'))
from verify_internet_git_ground import InternetGroundRefused, _sha1_git_blob, verify_remote_ground


class RemoteGitGroundTests(unittest.TestCase):
    def setUp(self):
        self.data = b'{"intention":"select-state","coordinate":72057594037928009}\n'
        self.sha1 = _sha1_git_blob(self.data)
        self.sha256 = hashlib.sha256(self.data).hexdigest()
        self.head = 'a' * 40
        self.tree = 'b' * 40
        self.repo = 'Kier73/E-CPU'
        self.branch = 'research/internet-native-ground-001-20261116'
        self.path = 'reports/internet-native-state/probe.json'
        self.records = {
            '/repos/' + self.repo + '/git/ref/heads/' + self.branch:
                {'object': {'type': 'commit', 'sha': self.head}},
            '/repos/' + self.repo + '/git/commits/' + self.head:
                {'tree': {'sha': self.tree}},
            '/repos/' + self.repo + '/git/trees/' + self.tree + '?recursive=1':
                {'truncated': False, 'tree': [{'path': self.path, 'type': 'blob', 'sha': self.sha1}]},
            '/repos/' + self.repo + '/git/blobs/' + self.sha1:
                {'sha': self.sha1, 'encoding': 'base64', 'content': base64.b64encode(self.data).decode()},
        }

    def check(self):
        return verify_remote_ground(self.records.__getitem__, repo=self.repo,
            branch=self.branch, expected_commit=self.head, path=self.path,
            expected_blob_sha1=self.sha1, expected_content_sha256=self.sha256)

    def test_complete_remote_reference(self):
        out = self.check()
        self.assertEqual(out['bytes'], len(self.data))
        self.assertEqual(out['observed_content_sha256'], self.sha256)

    def test_reject_stale_head_even_when_blob_exists(self):
        self.records['/repos/' + self.repo + '/git/ref/heads/' + self.branch]['object']['sha'] = 'c'*40
        with self.assertRaisesRegex(InternetGroundRefused, 'ref differs'):
            self.check()

    def test_reject_rehashed_wrong_content(self):
        self.records['/repos/' + self.repo + '/git/blobs/' + self.sha1]['content'] = base64.b64encode(b'different').decode()
        with self.assertRaisesRegex(InternetGroundRefused, 'independent reconstruction'):
            self.check()

    def test_reject_truncated_tree(self):
        self.records['/repos/' + self.repo + '/git/trees/' + self.tree + '?recursive=1']['truncated'] = True
        with self.assertRaisesRegex(InternetGroundRefused, 'incomplete'):
            self.check()

    def test_reject_wrong_path_and_ref_authority(self):
        with self.assertRaisesRegex(InternetGroundRefused, 'relative object'):
            verify_remote_ground(self.records.__getitem__, repo=self.repo, branch=self.branch,
                expected_commit=self.head, path='../secret', expected_blob_sha1=self.sha1,
                expected_content_sha256=self.sha256)
        with self.assertRaisesRegex(InternetGroundRefused, 'pinned intention'):
            verify_remote_ground(self.records.__getitem__, repo=self.repo, branch=self.branch,
                expected_commit='d'*40, path=self.path, expected_blob_sha1=self.sha1,
                expected_content_sha256=self.sha256)

    def test_missing_object_refuses(self):
        self.records['/repos/' + self.repo + '/git/trees/' + self.tree + '?recursive=1']['tree'] = []
        with self.assertRaisesRegex(InternetGroundRefused, 'ref does not address'):
            self.check()


if __name__ == '__main__':
    unittest.main()
