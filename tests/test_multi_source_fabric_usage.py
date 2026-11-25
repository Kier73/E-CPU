"""MSF-001: source pins, independent external proofs and native E-CPU composition."""
from __future__ import annotations

from copy import deepcopy

import pytest

from examples.multi_source_fabric_usage import (
    MultiSourceFabricRefused, PINS, observe_git_source, run,
)


def source_responses(pins=PINS[:2]):
    responses = {}
    for idx, pin in enumerate(pins):
        prefix = f'https://api.github.com/repos/{pin.repository}'
        tree_sha = f'{idx + 1:040x}'
        namespace = pin.anchor_path.split('/')[0]
        responses[f'{prefix}/git/commits/{pin.commit_sha}'] = {
            'sha': pin.commit_sha, 'tree': {'sha': tree_sha}}
        responses[f'{prefix}/git/trees/{tree_sha}?recursive=1'] = {
            'sha': tree_sha, 'truncated': False, 'tree': [
                {'path': pin.anchor_path, 'type': 'blob',
                 'sha': pin.expected_blob_sha, 'size': pin.expected_blob_bytes},
                {'path': f'{namespace}/second.py', 'type': 'blob',
                 'sha': 'a' * 40, 'size': 11 + idx},
                {'path': f'{namespace}/third.py', 'type': 'blob',
                 'sha': 'b' * 40, 'size': 7 + idx},
            ]}
    return responses


def test_pinned_sources_form_distinct_content_addressed_grounds():
    store = source_responses()
    a, b = [observe_git_source(pin, store.__getitem__) for pin in PINS[:2]]
    assert a['ground_fingerprint'] != b['ground_fingerprint']
    assert a['bytes_requested_from_code_blobs'] == 0
    assert len(a['source_ground']['members']) == 3
    assert a['source_ground']['members'][0]['size'] == PINS[0].expected_blob_bytes


def test_tree_reordering_cannot_change_ground():
    store = source_responses()
    before = observe_git_source(PINS[0], store.__getitem__)
    tree = next(v for k, v in store.items() if '/git/trees/' in k)
    tree['tree'].reverse()
    after = observe_git_source(PINS[0], store.__getitem__)
    assert after['ground_fingerprint'] == before['ground_fingerprint']


@pytest.mark.parametrize('mutation', ['wrong_commit', 'wrong_blob', 'wrong_size',
                                       'truncated', 'duplicate_path', 'wrong_tree'])
def test_false_remote_evidence_is_refused(mutation):
    store = deepcopy(source_responses())
    commit = next(v for k, v in store.items() if '/git/commits/' in k)
    tree = next(v for k, v in store.items() if '/git/trees/' in k)
    if mutation == 'wrong_commit':
        commit['sha'] = 'f' * 40
    elif mutation == 'wrong_blob':
        tree['tree'][0]['sha'] = 'f' * 40
    elif mutation == 'wrong_size':
        tree['tree'][0]['size'] += 1
    elif mutation == 'truncated':
        tree['truncated'] = True
    elif mutation == 'duplicate_path':
        tree['tree'].append(dict(tree['tree'][0]))
    elif mutation == 'wrong_tree':
        tree['sha'] = 'f' * 40
    with pytest.raises(MultiSourceFabricRefused):
        observe_git_source(PINS[0], store.__getitem__)


def test_source_native_directory_and_owned_network_join():
    store = source_responses()
    result = run(PINS[:2], store.__getitem__)
    assert result['schema'] == 'mailcpu.multi-source-fabric-usage.v1'
    assert result['source_count'] == 2
    assert result['local_host_count'] == 3
    assert result['source_code_payload_bytes_fetched'] == 0
    assert all(x['owned_network_hops'] >= 2 for x in result['routed_receipts'])
    assert all(x['native']['local_admission'] == 'found' for x in result['routed_receipts'])
    assert all(x['native']['execution'] == 'executed' for x in result['routed_receipts'])
    assert result['join']['value'] == sum(
        sum(entry['size'] for entry in source['source_ground']['members'])
        for source in result['source_grounds'])


def test_duplicate_source_identifiers_are_refused_before_source_observation():
    with pytest.raises(MultiSourceFabricRefused, match='distinct'):
        run((PINS[0], PINS[0]), lambda _: pytest.fail('network should not be called'))
