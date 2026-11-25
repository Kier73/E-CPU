"""MSF-001: run one E-CPU computational directory against pinned external source fabrics.

Four independently versioned public Git repositories are *source observers*,
not authenticated E-CPU peers. GitHub's deployed commit/tree services supply
source-ground metadata. A real local E-CPU Virtual Layer/Hypervisor executes
source-ground-bound pure reductions; an OwnedNetworkFabric routes their compact
receipts through separate logical namespaces into a final native reduction.

The source bytes themselves are never downloaded, imported, or executed.
The owned network is an in-process simulation, not live WAN forwarding.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from mailcpu import (
    Capability, ComputationalAddress, ComputationalAddressResolver,
    ComputationalExecutionAdmissionCoordinator, ComputationalFabricAuthority,
    ComputationalFabricDirectory, ComputationalFabricResolver,
    ComputationalFabricStatus, ComputationalHostCatalogue,
    ComputationalHostLocus, ComputationalPeerEndpoint, HeadlessOS,
    OperatorRegistry, OperatorSpec, RouteMetric, RouteMetricKey,
    SystemIdentity, SystemSeed, SystemSeedEnvelope, VirtualBudget,
    VirtualGroundRef, VirtualLayerRuntime, VirtualLayerWorkload,
    VirtualOperatorRef,
)
from mailcpu.classifier import HypervisorPolicy
from mailcpu.owned_network import OwnedNetworkFabric

SCHEMA = 'mailcpu.multi-source-fabric-usage.v1'
_SHA40 = re.compile(r'[0-9a-f]{40}\Z')
_REPO = re.compile(r'Kier73/[A-Za-z0-9_.-]+\Z')
_PATH = re.compile(r'[A-Za-z0-9_.+@/-]+\Z')
METRICS = (
    RouteMetricKey('latency', 'ticks'),
    RouteMetricKey('energy', 'units'),
    RouteMetricKey('bytes', 'bytes'),
    RouteMetricKey('risk', 'score'),
)
PROGRAM_FP = hashlib.sha256(b'MSF-001.source-ground-program.v1').hexdigest()
IMPL_FP = hashlib.sha256(b'MSF-001.native-receiver-reductions.v1').hexdigest()
MAX_REMOTE_BYTES = 2_000_000
MAX_ENTRIES = 5_000
SAMPLE_FILES = 12


class MultiSourceFabricRefused(ValueError):
    """A source observation or local execution disagrees with the pinned intention."""


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      allow_nan=False, ensure_ascii=False).encode('utf-8')


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def require(ok: bool, reason: str) -> None:
    if not ok:
        raise MultiSourceFabricRefused(reason)


@dataclass(frozen=True)
class SourcePin:
    name: str
    repository: str
    commit_sha: str
    anchor_path: str
    expected_blob_sha: str
    expected_blob_bytes: int

    def __post_init__(self) -> None:
        require(bool(re.fullmatch('[a-z][a-z0-9_]{1,18}', self.name)), 'invalid source identity')
        require(bool(_REPO.fullmatch(self.repository)), 'source repository is not allowlisted')
        require(bool(_SHA40.fullmatch(self.commit_sha)), 'source must pin exact commit')
        require(bool(_SHA40.fullmatch(self.expected_blob_sha)), 'source must pin exact blob')
        require(bool(_PATH.fullmatch(self.anchor_path)) and
                not any(p in ('', '.', '..') for p in self.anchor_path.split('/')),
                'source must pin safe path')
        require(type(self.expected_blob_bytes) is int and self.expected_blob_bytes >= 0,
                'source must pin a nonnegative size')


PINS = (
    SourcePin('ecpu', 'Kier73/E-CPU', '6f05be0b4ecbb53c5f64580c7b82ee531fdd1f73',
              'mailcpu/computational_fabric.py', '36c51aa475e4f04a1ba07dc2ab726c9780ef083f', 115053),
    SourcePin('vgi', 'Kier73/Virtual-Ground-Interpreter', 'ae3f949b7d0b2aaa42236bc7cc37e9857384b174',
              'theory_development/build_07/cross_observer_invariants.py', '646e771a4870384eccac0419be54eee62b2d7c11', 37987),
    SourcePin('ifs', 'Kier73/In-Formation-Space', 'ccf7dfb88a52c458ee9dd00e26ffbaecf5b2af9c',
              'bridges/authority-lineage/authority_lineage.py', '12e609221eae22315d1be5e413968f4313e3dea2', 38311),
    SourcePin('vli', 'Kier73/VL-I', '00fd4026dc3c35bc130d2d09ab9d88b354616d7b',
              'examples/external_source_trial.py', 'f15926280772c43b8f61288bd417dba8de7cde2e', 1961),
)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        raise MultiSourceFabricRefused('GitHub API redirects are not admitted')


def github_get_json(url: str) -> Mapping[str, Any]:
    """Bounded read-only GET of one exact public GitHub object API endpoint."""
    require(url.startswith('https://api.github.com/repos/Kier73/') and
            ('/git/commits/' in url or '/git/trees/' in url),
            'attempt to observe unapproved URL')
    opener = build_opener(NoRedirect())
    req = Request(url, headers={'Accept': 'application/vnd.github+json',
                                'User-Agent': 'E-CPU-MSF-001',
                                'X-GitHub-Api-Version': '2022-11-28'})
    try:
        with opener.open(req, timeout=12) as response:
            require(response.status == 200, 'GitHub API did not return 200')
            raw = response.read(MAX_REMOTE_BYTES + 1)
    except (HTTPError, URLError, TimeoutError) as exc:
        raise MultiSourceFabricRefused('GitHub source observation failed') from exc
    require(len(raw) <= MAX_REMOTE_BYTES, 'metadata response exceeded byte budget')
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'duplicate JSON key')
            result[key] = value
        return result
    try:
        result = json.loads(raw, object_pairs_hook=pairs,
                            parse_constant=lambda _: require(False, 'nonfinite metadata'))
    except (ValueError, UnicodeError) as exc:
        raise MultiSourceFabricRefused('remote metadata is invalid JSON') from exc
    require(isinstance(result, dict), 'remote metadata is not an object')
    return result


def observe_git_source(pin: SourcePin, read: Callable[[str], Mapping[str, Any]]) -> dict[str, Any]:
    """Pin commit -> tree -> declared anchor and derive a source-structural Ground."""
    prefix = f'https://api.github.com/repos/{pin.repository}'
    commit = read(f'{prefix}/git/commits/{pin.commit_sha}')
    require(isinstance(commit, Mapping) and commit.get('sha') == pin.commit_sha,
            'commit response does not match receiver-selected pin')
    ctree = commit.get('tree')
    require(isinstance(ctree, Mapping) and
            isinstance(ctree.get('sha'), str) and _SHA40.fullmatch(ctree['sha']),
            'commit does not bind a Git tree')
    tree_sha = ctree['sha']
    tree = read(f'{prefix}/git/trees/{tree_sha}?recursive=1')
    require(isinstance(tree, Mapping) and tree.get('sha') == tree_sha and
            tree.get('truncated') is False and isinstance(tree.get('tree'), list),
            'recursive tree observation is incomplete or mismatched')
    entries = tree['tree']
    require(0 < len(entries) <= MAX_ENTRIES, 'tree entry count exceeds observation budget')
    by_path = {}
    for item in entries:
        require(isinstance(item, Mapping) and isinstance(item.get('path'), str),
                'tree entry is malformed')
        path = item['path']
        require(path not in by_path, 'tree contains duplicate source paths')
        by_path[path] = item
    anchor = by_path.get(pin.anchor_path)
    require(anchor is not None and anchor.get('type') == 'blob' and
            anchor.get('sha') == pin.expected_blob_sha and
            type(anchor.get('size')) is int and anchor['size'] == pin.expected_blob_bytes,
            'pinned anchor blob or size disagrees with observed Git tree')
    # Only a small bounded metadata sample crosses the source-ground boundary.
    namespace = pin.anchor_path.split('/')[0] + '/'
    files = sorted((x for x in entries if x.get('type') == 'blob' and
                    x['path'].startswith(namespace) and
                    isinstance(x.get('sha'), str) and _SHA40.fullmatch(x['sha']) and
                    type(x.get('size')) is int and x['size'] >= 0),
                   key=lambda x: x['path'])[:SAMPLE_FILES]
    require(bool(files), 'source namespace has no qualified blob entries')
    members = [{'path': x['path'], 'blob_sha': x['sha'], 'size': x['size']} for x in files]
    ground = {'repository': pin.repository, 'commit': pin.commit_sha, 'tree': tree_sha,
              'anchor': pin.anchor_path, 'anchor_sha': pin.expected_blob_sha,
              'anchor_bytes': pin.expected_blob_bytes, 'members': members}
    return {'name': pin.name, 'source_ground': ground,
            'ground_fingerprint': digest(ground), 'tree_entries_observed': len(entries),
            'bytes_requested_from_code_blobs': 0}


def _spec(operation_id: str, output_kind: str) -> OperatorSpec:
    return OperatorSpec(
        operator_id=operation_id, version=1,
        description='Pure source-structure integer reduction',
        input_kind='object', output_kind=output_kind,
        substrates=('cpu',), required_rights=frozenset({'compute'}),
        base_energy=5, energy_per_byte=1, max_input_bytes=8192,
        max_output_bytes=1024, deterministic=True, effect_mode='pure',
    )


def _costs() -> tuple[RouteMetric, ...]:
    return (RouteMetric('latency', 'ticks', 1), RouteMetric('energy', 'units', 5),
            RouteMetric('bytes', 'bytes', 128), RouteMetric('risk', 'score', 0))


def _run_native(observed: list[dict[str, Any]]) -> dict[str, Any]:
    """E-CPU native route proposal -> local admission -> Hypervisor execution."""
    os_ = HeadlessOS()
    os_.hypervisor.policy = HypervisorPolicy(review_confidence=0.0,
        automatic_confidence=0.0, destructive_confidence=0.0,
        danger_review_probability=1.0)
    system = SystemIdentity('msf001-runtime', 1)
    envelope = SystemSeedEnvelope(system, 'msf001', 'msf001', SystemSeed.from_system(os_))
    require(os_.seed_admission.admit(envelope).accepted, 'native source seed not admitted')
    ground = VirtualGroundRef.from_envelope(envelope)
    registry = OperatorRegistry()
    source_spec = _spec('msf.source.reduce', 'integer')
    join_spec = _spec('msf.source.join', 'integer')

    def source_handler(value, _workload):
        require(isinstance(value, dict) and isinstance(value.get('members'), list),
                'source-native input lacks declared members')
        require(0 < len(value['members']) <= SAMPLE_FILES, 'invalid source member count')
        return sum(item['size'] for item in value['members'])

    def join_handler(value, _workload):
        require(isinstance(value, dict) and isinstance(value.get('values'), list),
                'join-native input lacks source values')
        return sum(value['values'])

    registry.register(source_spec, source_handler)
    registry.register(join_spec, join_handler)
    runtime = VirtualLayerRuntime(registry, 'msf-node', frozenset({'cpu'}))
    pid = os_.environment.kernel.spawn(
        'msf-source-observer',
        capabilities=(Capability('/virtual-layer/operators', frozenset({'compute'})),),
        parent_pid=os_.environment.init_pid,
    )
    endpoint = ComputationalPeerEndpoint('msf-receiver', 'msf-receiver.fabric.test',
                                        '127.0.0.1', 443)
    authority = ComputationalFabricAuthority(endpoint)
    loci = []
    for item in observed:
        loci.append(ComputationalHostLocus.from_runtime(
            host_id='msf-' + item['name'], runtime=runtime, authority_pid=pid,
            operator_id=source_spec.operator_id,
            computational_ground_fingerprints=(item['ground_fingerprint'],),
            program_fingerprints=(PROGRAM_FP,), costs=_costs(),
            implementation_fingerprint=IMPL_FP,
        ))
    joint_ground = digest({'ordered_sources': [
        [x['name'], x['ground_fingerprint']] for x in observed]})
    loci.append(ComputationalHostLocus.from_runtime(
        host_id='msf-join', runtime=runtime, authority_pid=pid,
        operator_id=join_spec.operator_id,
        computational_ground_fingerprints=(joint_ground,),
        program_fingerprints=(PROGRAM_FP,), costs=_costs(),
        implementation_fingerprint=IMPL_FP,
    ))
    for locus in loci:
        authority.register_host(locus)
    directory = ComputationalFabricDirectory(endpoint.peer_id, {})
    directory.register_local_snapshot(authority.snapshot())
    catalogue = ComputationalHostCatalogue(tuple(loci))
    resolver = ComputationalFabricResolver()
    n = 0

    def execute(label: str, spec: OperatorSpec, ground_fp: str, value: dict) -> tuple[int, dict]:
        nonlocal n
        n += 1
        workload = VirtualLayerWorkload(
            workload_id='msf-' + label, system=system, ground=ground,
            intention={'goal': {'kind': 'source-structure-reduction', 'label': label}},
            operators=(VirtualOperatorRef(spec.operator_id, 1, 'cpu'),),
            input_value=value, budget=VirtualBudget(100_000, 100_000, 100_000),
            logical_time=n, eligible_nodes=('msf-node',), max_hops=1,
        )
        address = ComputationalAddress.from_workload(
            workload, spec.operator_id, spec, ground_fp,
            program_fingerprint=PROGRAM_FP, metric_order=METRICS,
        )
        route = resolver.resolve(address, directory, origin_peer_id=endpoint.peer_id)
        require(route.status is ComputationalFabricStatus.FOUND and
                route.witness is not None and not route.authoritative,
                'local directory failed to select a source Ground host')
        qualified = ComputationalAddressResolver().resolve(address, catalogue, os_)
        require(qualified.status.value == 'found' and qualified.witness is not None,
                'native destination rejected selected source operator')
        result = ComputationalExecutionAdmissionCoordinator(os_).execute(
            address, qualified.witness, catalogue, runtime, source='msf-source-observer',
            channel='msf.source.execution', sequence=n,
        )
        require(result.accepted and result.executed and result.execution is not None,
                'native Hypervisor refused source-ground computation')
        output = result.execution.effect['result']
        require(type(output) is int and output >= 0, 'native source returned invalid integer')
        return output, {'host': route.witness.target_host.host_id,
                        'peer_path': list(route.witness.peer_path),
                        'route_digest': route.witness.digest,
                        'local_admission': qualified.status.value,
                        'execution': result.status.value}

    network = OwnedNetworkFabric()
    network.create_namespace('msf-core')
    sink = network.create_interface('msf-core', 'sink')
    source_values = {}
    routes = []
    for item in observed:
        name = item['name']
        network.create_namespace('msf-' + name)
        source_port = network.create_interface('msf-' + name, 'out')
        ingress = network.create_interface('msf-core', name)
        network.connect('msf-link-' + name, source_port, ingress)
        value, receipt = execute(name, source_spec, item['ground_fingerprint'],
                                {'members': item['source_ground']['members']})
        source_values[name] = value
        wire = canonical({'source': name, 'ground': item['ground_fingerprint'],
                          'value': value, 'route_digest': receipt['route_digest']})
        network.send_routed(source_port, sink, wire, logical_time=len(routes) + 1)
        frame = network.receive(sink)
        require(frame is not None and frame.payload == wire and len(frame.route) >= 3,
                'owned-network source receipt was not routed')
        actual = json.loads(frame.payload)
        require(actual['source'] == name and actual['ground'] == item['ground_fingerprint']
                and actual['value'] == sum(x['size'] for x in item['source_ground']['members']),
                'receiver observed an inconsistent native source reduction')
        routes.append({'source': name, 'native': receipt,
                       'owned_network_hops': len(frame.route) - 1,
                       'payload_bytes': len(wire)})
    combined, joined_receipt = execute('join', join_spec, joint_ground,
                                      {'values': [source_values[item['name']] for item in observed]})
    require(combined == sum(source_values.values()), 'source-reduction join disagrees with oracle')
    return {'schema': SCHEMA, 'source_count': len(observed),
            'directory_digest': directory.digest, 'local_host_count': len(directory.hosts),
            'source_grounds': [dict(item) for item in observed],
            'routed_receipts': routes, 'join': {'value': combined, **joined_receipt},
            'source_code_payload_bytes_fetched': 0,
            'total_owned_network_bytes': sum(x['payload_bytes'] for x in routes),
            'scope': 'live-git-metadata-if-live; local-Hypervisor-execution; owned-network-in-process-routing'}


def run(pins: tuple[SourcePin, ...], read: Callable[[str], Mapping[str, Any]]) -> dict[str, Any]:
    require(2 <= len(pins) <= 8 and len({p.name for p in pins}) == len(pins),
            'experiment requires 2-8 distinct externally pinned sources')
    observations = [observe_git_source(pin, read) for pin in pins]
    return _run_native(observations)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true',
                        help='Perform bounded, real HTTPS observations of pinned public Git metadata')
    parser.add_argument('--output', default='-', help='Report JSON path, or - for stdout')
    args = parser.parse_args()
    require(args.live, 'explicit --live needed; no synthetic network observations are supplied by CLI')
    report = run(PINS, github_get_json)
    rendered = json.dumps(report, sort_keys=True, indent=2) + '\n'
    if args.output == '-':
        print(rendered, end='')
    else:
        from pathlib import Path
        Path(args.output).write_text(rendered, encoding='utf-8')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
