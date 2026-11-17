"""INTERNET-002 offline oracle and adversarial observer verification tests."""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'examples'))
from verify_internet_graph_ground import (
    InternetGraphRefused, ancestors, canonical, independent_comparison,
    no_duplicate_keys, observe_remote_graph, pinned_manifest,
    validate_manifest, verify_comparison, github_read_json,
)


class NativeInternetGraphTests(unittest.TestCase):
    def setUp(self) -> None:
        raw = (ROOT / 'reports/internet_002_graph.json').read_bytes()
        self.outside_pin = sha256(raw).hexdigest()
        self.spec = pinned_manifest(raw, expected_sha256=self.outside_pin)
        self.nodes = self.spec['nodes']
        self.prefix = '/repos/' + self.spec['repository']
        self.records = {}
        for name, node in self.nodes.items():
            ps = [self.nodes[p]['sha'] for p in node['parents']]
            if name == self.spec['root']:
                ps = ['6fd416facdb2aefd6fc7d66a06b014e3d31b5a52']
            self.records[self.prefix+'/git/commits/'+node['sha']] = {
                'sha': node['sha'], 'tree': {'sha': node['tree']},
                'parents': [{'sha': p} for p in ps],
            }
        for ref, name in self.spec['refs'].items():
            self.records[self.prefix+'/git/ref/heads/'+ref] = {
                'object': {'type': 'commit', 'sha': self.nodes[name]['sha']}}
        for base, head in self.spec['queries']:
            expected = independent_comparison(self.spec, base, head)
            self.records[self.compare_path(base, head)] = {
                **{k:v for k,v in expected.items() if k!='merge_base_sha'},
                'merge_base_commit': {'sha': expected['merge_base_sha']},
                'base_commit': {'sha': self.nodes[base]['sha']},
                'too_large': False,
            }

    def compare_path(self, base, head):
        return (self.prefix+'/compare/'+self.nodes[base]['sha']+
                '...'+self.nodes[head]['sha'])

    def observe(self):
        return observe_remote_graph(self.records.__getitem__,
                                    self.spec, manifest_sha256=self.outside_pin)

    def test_all_nine_native_service_operations(self):
        report = self.observe()
        self.assertEqual(report['remote_native_comparison_count'], 9)
        self.assertEqual(report['remote_commit_objects_checked'], 12)
        self.assertEqual(len(report['remote_refs_checked']), 3)
        for row in report['comparisons']:
            expected = independent_comparison(self.spec, row['base'], row['head'])
            self.assertEqual(row['merge_base_sha'], expected['merge_base_sha'])
            self.assertEqual(row['ahead_by'], expected['ahead_by'])
            self.assertEqual(row['behind_by'], expected['behind_by'])
        self.assertEqual(report['receipt_sha256'], sha256(canonical({
            k:v for k,v in report.items() if k!='receipt_sha256'})).hexdigest())

    def test_divergent_heads_unique_merge_base(self):
        result = independent_comparison(self.spec,'A4','B5')
        self.assertEqual((result['status'],result['ahead_by'],result['behind_by']),('diverged',5,4))
        self.assertEqual(result['merge_base_sha'],self.nodes['R']['sha'])

    def test_merger_does_not_replay_predecessor_nodes(self):
        value = independent_comparison(self.spec,'A4','M2')
        self.assertEqual(value['ahead_by'],7)
        self.assertEqual(value['behind_by'],0)
        self.assertEqual(value['merge_base_sha'],self.nodes['A4']['sha'])
        value = independent_comparison(self.spec,'B5','M2')
        self.assertEqual(value['ahead_by'],6)

    def test_reverse_intention_is_not_inverse_physical_execution(self):
        value=independent_comparison(self.spec,'M2','A4')
        self.assertEqual((value['status'],value['ahead_by'],value['behind_by']),('behind',0,7))

    def test_native_comparison_wrong_result_and_new_hash_refused(self):
        self.records[self.compare_path('A4','B5')]['ahead_by']=999
        self.records[self.compare_path('A4','B5')]['digest']='0'*64
        with self.assertRaisesRegex(InternetGraphRefused,'independent oracle'):
            self.observe()

    def test_missing_second_merge_parent_refused(self):
        path=self.prefix+'/git/commits/'+self.nodes['M']['sha']
        self.records[path]['parents']=self.records[path]['parents'][:1]
        with self.assertRaisesRegex(InternetGraphRefused,'parent transitions'):
            self.observe()

    def test_changed_remote_tree_refused(self):
        path=self.prefix+'/git/commits/'+self.nodes['B3']['sha']
        self.records[path]['tree']['sha']='a'*40
        with self.assertRaisesRegex(InternetGraphRefused,'object identity or tree'):
            self.observe()

    def test_stale_branch_refused(self):
        path=self.prefix+'/git/ref/heads/research/internet-002-graph-a'
        self.records[path]['object']['sha']=self.nodes['A3']['sha']
        with self.assertRaisesRegex(InternetGraphRefused,'no longer pins'):
            self.observe()

    def test_altered_merge_base_refused_even_when_counts_match(self):
        self.records[self.compare_path('A4','B5')]['merge_base_commit']['sha']=self.nodes['A1']['sha']
        with self.assertRaisesRegex(InternetGraphRefused,'independent oracle'):
            self.observe()

    def test_truncated_remote_comparison_refused(self):
        self.records[self.compare_path('R','A4')]['too_large']=True
        with self.assertRaisesRegex(InternetGraphRefused,'independent oracle'):
            self.observe()

    def test_wrong_outside_pin_refused_before_network(self):
        raw=(ROOT/'reports/internet_002_graph.json').read_bytes()
        with self.assertRaisesRegex(InternetGraphRefused,'outside pin'):
            pinned_manifest(raw,expected_sha256='0'*64)
        with self.assertRaisesRegex(InternetGraphRefused,'outside pin'):
            observe_remote_graph(self.records.__getitem__,self.spec,manifest_sha256='a'*64)

    def test_noncanonical_json_and_duplicate_keys_refused(self):
        raw=(ROOT/'reports/internet_002_graph.json').read_bytes()
        bad=b' '+raw
        with self.assertRaisesRegex(InternetGraphRefused,'canonical'):
            pinned_manifest(bad,expected_sha256=sha256(bad).hexdigest())
        with self.assertRaisesRegex(InternetGraphRefused,'duplicate JSON'):
            json.loads('{"schema":1,"schema":2}',object_pairs_hook=no_duplicate_keys)

    def test_cyclic_and_disconnected_candidate_rejected(self):
        example=deepcopy(self.spec)
        example['nodes']['A1']['parents']=['A4']
        with self.assertRaisesRegex(InternetGraphRefused,'cyclic'):
            validate_manifest(example)
        example=deepcopy(self.spec)
        example['nodes']['B1']['parents']=['B2']
        with self.assertRaisesRegex(InternetGraphRefused,'cyclic'):
            validate_manifest(example)

    def test_unknown_query_or_ref_not_admitted(self):
        example=deepcopy(self.spec)
        example['queries'].append(['A1','unobserved'])
        with self.assertRaisesRegex(InternetGraphRefused,'unbound comparison'):
            validate_manifest(example)
        example=deepcopy(self.spec)
        example['refs']['../../secrets']='A4'
        with self.assertRaisesRegex(InternetGraphRefused,'untrusted remote reference'):
            validate_manifest(example)

    def test_duplicate_node_aliased_sha_refused(self):
        example=deepcopy(self.spec)
        example['nodes']['A1']['sha']=example['nodes']['A2']['sha']
        with self.assertRaisesRegex(InternetGraphRefused,'one Git identity'):
            validate_manifest(example)

    def test_multiple_merge_bases_not_silently_guessed(self):
        example=deepcopy(self.spec)
        example['nodes']['X']={'sha':'a'*40,'tree':'b'*40,'parents':['A4','B5']}
        example['nodes']['Y']={'sha':'c'*40,'tree':'b'*40,'parents':['B5','A4']}
        validate_manifest(example)
        with self.assertRaisesRegex(InternetGraphRefused,'non-unique merge base'):
            independent_comparison(example,'X','Y')

    def test_uri_reader_does_not_access_arbitrary_endpoints(self):
        with self.assertRaisesRegex(InternetGraphRefused,'resource not allowed'):
            github_read_json('https://somewhere.example/secrets')
        with self.assertRaisesRegex(InternetGraphRefused,'resource not allowed'):
            github_read_json('/repos/../../somewhere')

    def test_physical_link_claim_explicitly_not_asserted(self):
        report=self.observe()
        self.assertIn('not-passive-link-arithmetic',report['non_claims'])
        self.assertIn('not-remote-hardware-attestation',report['non_claims'])


if __name__=='__main__':
    unittest.main()
