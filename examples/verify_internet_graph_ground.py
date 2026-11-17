"""INTERNET-002: independently check a Git service's *native* state-graph operator.

No E-CPU code runs at the remote Git service. A receiver-owned, externally
pinned finite experiment graph supplies the comparison oracle. HTTPS reads
observe actual server-side commit/branch relationships; client validation
rejects inconsistent or stale answers, including rehashed fabricated reports.

The test proves consistency for a bounded *service-level* Git graph. It does not
prove passive link computation, remote host attestation, unrestricted graph
inference, or authenticated network-layer computation between routers.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import time
from typing import Any, Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

SCHEMA = 'mailcpu.internet-native-git-graph-ground.v1'
RECEIPT_SCHEMA = 'mailcpu.internet-native-git-graph-observation.v1'
HEX40 = re.compile(r'[0-9a-f]{40}\Z')
HEX64 = re.compile(r'[0-9a-f]{64}\Z')
NODE = re.compile(r'[A-Za-z][A-Za-z0-9_-]{0,23}\Z')
BRANCH = re.compile(r'[A-Za-z0-9][A-Za-z0-9/_-]{0,127}\Z')
REPO = re.compile(r'[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}\Z')
MAX_MANIFEST = 64_000
MAX_REMOTE_RESPONSE = 1_000_000
MAX_NODES = 256
MAX_QUERIES = 128


class InternetGraphRefused(ValueError):
    """The Internet service's observation is not covered by the pinned Ground."""


def canonical(value: Any) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(',', ':'),
                          ensure_ascii=False, allow_nan=False).encode('utf-8')
    except (TypeError, ValueError) as exc:
        raise InternetGraphRefused('not finite canonical JSON') from exc


def digest(value: Any) -> str:
    return sha256(canonical(value)).hexdigest()


def no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise InternetGraphRefused('duplicate JSON field')
        result[key] = value
    return result


def pinned_manifest(data: bytes, *, expected_sha256: str) -> dict:
    if not isinstance(data, bytes) or len(data) > MAX_MANIFEST or not data:
        raise InternetGraphRefused('manifest byte budget exceeded')
    if type(expected_sha256) is not str or not HEX64.fullmatch(expected_sha256):
        raise InternetGraphRefused('receiver must supply a canonical outside manifest pin')
    if sha256(data).hexdigest() != expected_sha256:
        raise InternetGraphRefused('manifest differs from the receiver-owned outside pin')
    try:
        source = json.loads(data, object_pairs_hook=no_duplicate_keys)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InternetGraphRefused('malformed manifest') from exc
    validate_manifest(source)
    if data != canonical(source) + b'\n':
        raise InternetGraphRefused('manifest must be exact canonical JSON plus newline')
    return source


def validate_manifest(raw: Any) -> None:
    if type(raw) is not dict or set(raw) != {'schema', 'repository', 'root', 'nodes', 'refs', 'queries'}:
        raise InternetGraphRefused('unexpected graph manifest fields')
    if raw['schema'] != SCHEMA or type(raw['repository']) is not str or not REPO.fullmatch(raw['repository']):
        raise InternetGraphRefused('invalid graph schema or repository')
    nodes = raw['nodes']
    if type(nodes) is not dict or not (2 <= len(nodes) <= MAX_NODES):
        raise InternetGraphRefused('graph size outside bounded research domain')
    if type(raw['root']) is not str or raw['root'] not in nodes:
        raise InternetGraphRefused('missing externally pinned common root')
    ids = set()
    for name, entry in nodes.items():
        if type(name) is not str or not NODE.fullmatch(name):
            raise InternetGraphRefused('invalid graph node address')
        if type(entry) is not dict or set(entry) != {'sha', 'tree', 'parents'}:
            raise InternetGraphRefused('invalid node observation pin')
        if any(type(entry[k]) is not str or not HEX40.fullmatch(entry[k]) for k in ('sha', 'tree')):
            raise InternetGraphRefused('invalid Git commit or tree identity')
        if entry['sha'] in ids:
            raise InternetGraphRefused('one Git identity cannot denote two graph nodes')
        ids.add(entry['sha'])
        p = entry['parents']
        if type(p) is not list or (p if name == raw['root'] else not 1 <= len(p) <= 2):
            raise InternetGraphRefused('unsupported parent count or declared root')
        if len(p) != len(set(p)) or any(type(y) is not str or y not in nodes or y == name for y in p):
            raise InternetGraphRefused('missing, repeated, or self-referential parent')
    # The graph is a finite, controlled slice of a larger Git history; only the
    # separately pinned root is allowed to have parents outside the slice.
    colour = {}
    def visit(name):
        if colour.get(name) == 1:
            raise InternetGraphRefused('cyclic graph is not a Git DAG')
        if colour.get(name) == 2:
            return
        colour[name] = 1
        for p in nodes[name]['parents']:
            visit(p)
        colour[name] = 2
    for name in nodes:
        visit(name)
    for name in nodes:
        if raw['root'] not in ancestors(raw, name):
            raise InternetGraphRefused('unrooted or disconnected graph')
    refs = raw['refs']
    if type(refs) is not dict or not (1 <= len(refs) <= 8):
        raise InternetGraphRefused('invalid number of pinned remote references')
    for name, node in refs.items():
        if (type(name) is not str or not BRANCH.fullmatch(name) or '..' in name
                or '//' in name or name.endswith('/') or type(node) is not str or node not in nodes):
            raise InternetGraphRefused('untrusted remote reference or target')
    queries = raw['queries']
    if type(queries) is not list or not (1 <= len(queries) <= MAX_QUERIES):
        raise InternetGraphRefused('invalid query budget')
    seen = set()
    for pair in queries:
        if type(pair) is not list or len(pair) != 2 or any(type(x) is not str or x not in nodes for x in pair):
            raise InternetGraphRefused('unbound comparison query')
        key = tuple(pair)
        if key in seen:
            raise InternetGraphRefused('repeated native service query')
        seen.add(key)


def ancestors(manifest: Mapping[str, Any], name: str) -> frozenset[str]:
    nodes = manifest['nodes']
    # All call sites validate the graph first (except validate_manifest itself,
    # where the graph has already passed DFS cycle detection).
    seen: set[str] = set()
    stack = [name]
    while stack:
        item = stack.pop()
        if item in seen:
            continue
        seen.add(item)
        stack.extend(nodes[item]['parents'])
    return frozenset(seen)


def independent_comparison(manifest: Mapping[str, Any], base: str, head: str) -> dict:
    """Independent full-graph reference (not the GitHub comparison routine)."""
    nodes = manifest['nodes']
    if base not in nodes or head not in nodes:
        raise InternetGraphRefused('comparison outside declared finite Ground')
    base_anc = ancestors(manifest, base)
    head_anc = ancestors(manifest, head)
    ahead = len(head_anc - base_anc)
    behind = len(base_anc - head_anc)
    common = base_anc & head_anc
    # Maximal common ancestors: a common ancestor is not maximal if another
    # common ancestor descends from it. Git may have several merge bases in a
    # criss-cross merge; this experiment only admits a unique answer.
    maximal = [candidate for candidate in common if not any(
        other != candidate and candidate in ancestors(manifest, other)
        for other in common)]
    if len(maximal) != 1:
        raise InternetGraphRefused('non-unique merge base requires a richer result algebra')
    return {
        'status': ('identical' if not ahead and not behind else
                   'ahead' if not behind else 'behind' if not ahead else 'diverged'),
        'ahead_by': ahead,
        'behind_by': behind,
        'merge_base_sha': nodes[maximal[0]]['sha'],
        'total_commits': ahead,
    }


def verify_comparison(manifest: Mapping[str, Any], base: str, head: str,
                      response: Mapping[str, Any]) -> dict:
    expected = independent_comparison(manifest, base, head)
    if type(response) is not dict:
        raise InternetGraphRefused('remote comparison is not a mapping')
    if (type(response.get('status')) is not str or
            any(type(response.get(k)) is not int for k in ('ahead_by', 'behind_by', 'total_commits')) or
            type(response.get('merge_base_commit')) is not dict or
            type(response.get('base_commit')) is not dict):
        raise InternetGraphRefused('incomplete remote comparison')
    actual = {
        'status': response['status'],
        'ahead_by': response['ahead_by'],
        'behind_by': response['behind_by'],
        'merge_base_sha': response['merge_base_commit'].get('sha'),
        'total_commits': response['total_commits'],
    }
    if (actual != expected or response['base_commit'].get('sha') != manifest['nodes'][base]['sha']
            or response.get('too_large') is True):
        raise InternetGraphRefused('remote graph operator contradicts independent oracle')
    return {'base': base, 'head': head, **expected, 'comparison_digest': digest(actual)}


def observe_remote_graph(read: Callable[[str], Mapping[str, Any]], manifest: dict,
                         *, manifest_sha256: str) -> dict:
    """Observe Git service parent graph, refs and native compare operations.

    Completeness is bound to externally supplied node/branch/query pins. The
    receiver checks each returned parent edge, not merely response hashes.
    The root has historic Git parents outside the bounded slice; they are not
    included or audited by this experiment.
    """
    validate_manifest(manifest)
    if (type(manifest_sha256) is not str or not HEX64.fullmatch(manifest_sha256) or
            sha256(canonical(manifest) + b'\n').hexdigest() != manifest_sha256):
        raise InternetGraphRefused('manifest does not match outside pin')
    repository = manifest['repository']
    prefix = '/repos/' + repository
    nodes = manifest['nodes']
    for name, node in nodes.items():
        observed = read(prefix + '/git/commits/' + node['sha'])
        if type(observed) is not dict:
            raise InternetGraphRefused('Git commit observation malformed')
        if (observed.get('sha') != node['sha'] or
                type(observed.get('tree')) is not dict or
                observed['tree'].get('sha') != node['tree']):
            raise InternetGraphRefused('remote object identity or tree differs from pinned Ground')
        if name != manifest['root']:
            observed_parents = observed.get('parents')
            exact = [nodes[x]['sha'] for x in node['parents']]
            if (type(observed_parents) is not list or
                    [p.get('sha') if type(p) is dict else None for p in observed_parents] != exact):
                raise InternetGraphRefused('remote parent transitions contradict pinned causal Ground')
    observed_refs = []
    for branch, name in manifest['refs'].items():
        # GitHub ref endpoints permit URL-escaped slashes in branch names.
        observed = read(prefix + '/git/ref/heads/' + quote(branch, safe='/'))
        if (type(observed) is not dict or type(observed.get('object')) is not dict or
                observed['object'].get('type') != 'commit' or
                observed['object'].get('sha') != nodes[name]['sha']):
            raise InternetGraphRefused('remote reference no longer pins the declared state')
        observed_refs.append({'branch': branch, 'node': name, 'sha': nodes[name]['sha']})
    observations = []
    for base, head in manifest['queries']:
        path = prefix + '/compare/' + nodes[base]['sha'] + '...' + nodes[head]['sha']
        observations.append(verify_comparison(manifest, base, head, read(path)))
    body = {
        'schema': RECEIPT_SCHEMA,
        'repository': repository,
        'ground_manifest_sha256': manifest_sha256,
        'observed_root': nodes[manifest['root']]['sha'],
        'remote_commit_objects_checked': len(nodes),
        'remote_refs_checked': observed_refs,
        'remote_native_comparison_count': len(observations),
        'comparisons': observations,
        'semantic_scope': 'bounded-Git-service-DAG-ancestry-and-native-comparison',
        'non_claims': ['not-passive-link-arithmetic', 'not-remote-hardware-attestation',
                       'not-generalized-network-path-computation',
                       'not-proof-of-unchanging-future-service-state'],
    }
    return {**body, 'receipt_sha256': digest(body)}


def github_read_json(resource: str) -> dict:
    """Bounded HTTPS observation; token optional for an authorized GH Actions job.

    GitHub handles the Git DAG operation; this client performs no arithmetic
    at the service and never sends a state-changing HTTP method.
    """
    if (not resource.startswith('/repos/') or '?' in resource or '#' in resource
            or '/../' in resource or resource.endswith('/..') or '//' in resource):
        raise InternetGraphRefused('read resource not allowed')
    url = 'https://api.github.com' + resource
    headers = {'Accept': 'application/vnd.github+json',
               'User-Agent': 'E-CPU-INTERNET-002-independent-observer'}
    token = os.environ.get('GITHUB_TOKEN', '')
    if token:
        headers['Authorization'] = 'Bearer ' + token
    try:
        request = Request(url, headers=headers)
        with urlopen(request, timeout=15) as response:
            if response.status != 200:
                raise InternetGraphRefused('unexpected HTTPS observation code')
            body = response.read(MAX_REMOTE_RESPONSE + 1)
        if len(body) > MAX_REMOTE_RESPONSE:
            raise InternetGraphRefused('remote JSON exceeded byte budget')
        result = json.loads(body, object_pairs_hook=no_duplicate_keys)
        if type(result) is not dict:
            raise InternetGraphRefused('remote observation is not JSON object')
        return result
    except (URLError, HTTPError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InternetGraphRefused('Internet observation unavailable or malformed') from exc


def main() -> None:
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--manifest', type=Path, required=True)
    cli.add_argument('--expected-manifest-sha256', required=True)
    cli.add_argument('--out', type=Path, default=None)
    args = cli.parse_args()
    raw = args.manifest.read_bytes()
    manifest = pinned_manifest(raw, expected_sha256=args.expected_manifest_sha256)
    started = time.perf_counter_ns()
    report = observe_remote_graph(github_read_json, manifest,
                                  manifest_sha256=args.expected_manifest_sha256)
    report['sender_monotonic_elapsed_ns'] = time.perf_counter_ns() - started
    report['measurement_scope'] = 'entire HTTPS request-and-verification span; not propagation delay'
    encoded = json.dumps(report, sort_keys=True, indent=2) + '\n'
    if args.out is None:
        print(encoded, end='')
    else:
        # CI outputs are newly created rather than silently replacing a prior
        # accepted observer event.
        with args.out.open('x', encoding='utf-8') as output:
            output.write(encoded)


if __name__ == '__main__':
    main()
