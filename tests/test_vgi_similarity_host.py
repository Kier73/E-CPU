"""E-CPU Virtual Layer tests for portable VGI basis memories.

CI must provision GEOMETRY-FIRST-008 VGI explicitly (see dedicated workflow),
not silently use the older VGI commit in E-CPU's default optional extra.
"""
from __future__ import annotations

from dataclasses import replace
import json

import pytest

pytest.importorskip('vgi.structural_memory')

from mailcpu import (
    Capability, HeadlessOS, HypervisorAction, HypervisorPolicy,
    LexicalDecisionModel, OperatorRegistry, SystemIdentity, SystemSeed,
    SystemSeedEnvelope, VirtualBudget, VirtualGroundRef, VirtualLayerRuntime,
    VirtualLayerWorkload, VirtualOperatorRef,
)
from mailcpu.vgi_similarity_host import (
    MAX_EXPONENT_BITS, PinnedSimilarityCatalogue, PinnedSimilarityRecord,
    SimilarityHostError, SIMILARITY_OPERATOR_ID, SIMILARITY_REQUEST_SCHEMA,
    make_vgi_similarity_operator, vgi_similarity_implementation_fingerprint,
)
from mailcpu.transit_vgi_similarity import (
    SIMILARITY_RESOURCE, TransitVGISimilarityHost,
    build_vgi_similarity_event,
)
from examples.vgi_similarity_transfer_process import build_lab_ground
from vgi.typed_operator_navigation import TypedVector, PreparedTemporalOperator
from vgi.structural_memory import admit_similarity_memory, verify_portable_similarity_receipt


@pytest.fixture(scope='module')
def lab():
    graph, certificate, payload = build_lab_ground()
    memory = admit_similarity_memory(payload, expected_graph_fingerprint=graph.fingerprint)
    pinned = PinnedSimilarityRecord(memory.memory_sha256, graph.fingerprint, payload)
    catalogue = PinnedSimilarityCatalogue((pinned,))
    return graph, certificate, memory, pinned, catalogue


def _host(lab):
    graph, _certificate, memory, pinned, catalogue = lab
    os = HeadlessOS()
    os.hypervisor.classifier = LexicalDecisionModel()
    os.hypervisor.policy = HypervisorPolicy(embedding_review_confidence=1.0)
    identity = SystemIdentity('vgi-similarity-hosted-system', 1)
    envelope = SystemSeedEnvelope(identity, 'similarity-executor', 'sim-navigation',
                                  SystemSeed.from_system(os))
    assert os.seed_admission.admit(envelope).accepted
    initial = TypedVector(graph.domain, (2, 4, 8, 16, 32, 64))
    tick = 10**30+11
    request = {
        'schema':SIMILARITY_REQUEST_SCHEMA,
        'memory_sha256':memory.memory_sha256,
        'graph_fingerprint':graph.fingerprint,
        'initial':initial.to_dict(),
        'logical_tick':tick,
    }
    workload = VirtualLayerWorkload(
        workload_id='similarity-task-001', system=identity,
        ground=VirtualGroundRef.from_envelope(envelope),
        intention={'goal':{'kind':'navigate-certified-similarity-ground'}},
        operators=(VirtualOperatorRef(SIMILARITY_OPERATOR_ID,1,'cpu'),),
        input_value=request,
        budget=VirtualBudget(100_000, 1_000_000, 1_000),
        logical_time=7,eligible_nodes=('node-vgi',),max_hops=2,
    )
    registry=OperatorRegistry()
    spec,handler=make_vgi_similarity_operator(catalogue)
    calls=[]
    def counted(value, work):
        calls.append(work.workload_id)
        return handler(value,work)
    registry.register(spec,counted)
    runtime=VirtualLayerRuntime(registry,'node-vgi',frozenset({'cpu'}))
    worker=os.environment.kernel.spawn(
        'similarity-worker',
        capabilities=(Capability('/virtual-layer/operators',frozenset({'compute'})),),
        parent_pid=os.environment.init_pid,
    )
    return os,workload,runtime,worker,calls,initial


def test_virtual_layer_authorized_navigation_binds_both_grounds(lab):
    graph,cert,admitted,pinned,catalogue=lab
    host,workload,runtime,pid,calls,initial=_host(lab)
    first=runtime.execute_operator(host,pid,'peer','sim',1,
                                   workload.logical_time,workload,SIMILARITY_OPERATOR_ID)
    assert first.action is HypervisorAction.ALLOW
    assert first.executed is True
    effect=first.effect['result']
    assert effect['schema']=='vgi.similarity.navigation-effect.v1'
    assert effect['computation_ground']['memory_sha256']==admitted.memory_sha256
    assert effect['computation_ground']['graph_fingerprint']==graph.fingerprint
    assert effect['system_ground']==workload.ground.to_dict()
    expected=PreparedTemporalOperator.from_chain(graph).state_at(
        initial,workload.input_value['logical_tick']).result.values
    assert effect['navigation']['inner']['result']['values']==list(expected)
    assert len(effect['effect_digest'])==64
    assert calls==['similarity-task-001']
    second=runtime.execute_operator(host,pid,'peer','sim',1,
                                    workload.logical_time,workload,SIMILARITY_OPERATOR_ID)
    assert second.replayed is True
    assert second.effect == first.effect
    assert calls==['similarity-task-001']
    assert host.environment.kernel.journal.verify()


def test_trusted_catalogue_refuses_unprovisioned_or_changed_records(lab):
    graph,cert,admitted,pinned,catalogue=lab
    host,workload,runtime,pid,calls,initial=_host(lab)
    spec,handler=make_vgi_similarity_operator(catalogue)
    bad=dict(workload.input_value)
    bad['memory_sha256']='0'*64
    with pytest.raises(SimilarityHostError,match='no trusted'):
        handler(bad,workload)
    bad=dict(workload.input_value)
    bad['graph_fingerprint']='0'*64
    with pytest.raises(SimilarityHostError,match='no trusted'):
        handler(bad,workload)
    bad=dict(workload.input_value)
    bad['initial']={'space':{'frame':'foreign','dimension':6,'ring':'Z/modulus Z','modulus':101},
                    'values':[2,4,8,16,32,64]}
    with pytest.raises(SimilarityHostError,match='typed frame'):
        handler(bad,workload)
    bad=json.loads(json.dumps(workload.input_value))
    bad['initial']['extra']='untrusted'
    with pytest.raises(SimilarityHostError,match='typed vector'):
        handler(bad,workload)
    corrupted=pinned.content.replace(b'"source-substrate"',b'"substituted-source"')
    with pytest.raises(SimilarityHostError,match='mathematically refused'):
        PinnedSimilarityCatalogue((replace(pinned,content=corrupted),))
    with pytest.raises(SimilarityHostError,match='mathematically refused'):
        PinnedSimilarityCatalogue((replace(pinned,graph_fingerprint='0'*64),))


def test_logical_time_and_payload_bounds_fail_closed(lab):
    graph,cert,admitted,pinned,catalogue=lab
    _,workload,_,_,_,_=_host(lab)
    _,handler=make_vgi_similarity_operator(catalogue,max_exponent_bits=256)
    for value in (-1,True,1<<256):
        bad={**workload.input_value,'logical_tick':value}
        with pytest.raises(SimilarityHostError,match='logical coordinate'):
            handler(bad,workload)
    for key,value in [('schema','wrong-schema'),('unexpected',True)]:
        bad={**workload.input_value,key:value}
        with pytest.raises(SimilarityHostError):handler(bad,workload)
    with pytest.raises(SimilarityHostError,match='exponent'):
        make_vgi_similarity_operator(catalogue,max_exponent_bits=MAX_EXPONENT_BITS+1)


def test_missing_compute_capability_refused_before_local_handler(lab):
    graph,cert,admitted,pinned,catalogue=lab
    host,workload,runtime,worker,calls,initial=_host(lab)
    pid=host.environment.kernel.spawn('no-similarity-compute-rights',capabilities=(),
                                       parent_pid=host.environment.init_pid)
    denied=runtime.execute_operator(host,pid,'peer','sim-no-rights',4,
                                    workload.logical_time,workload,SIMILARITY_OPERATOR_ID)
    assert denied.action is HypervisorAction.DENY
    assert denied.executed is False
    assert denied.effect is None
    assert calls==[]


def test_transit_wrapper_uses_exact_contract_and_receiver_identity(lab):
    graph,cert,admitted,pinned,catalogue=lab
    host,workload,runtime,pid,calls,initial=_host(lab)
    node=TransitVGISimilarityHost(host,pid,catalogue,node_id='node-vgi')
    assert node.resource_name == SIMILARITY_RESOURCE
    assert node.implementation_fingerprint == vgi_similarity_implementation_fingerprint(type(node))
    assert node.registry.contract(SIMILARITY_OPERATOR_ID,1).digest == \
        runtime.registry.contract(SIMILARITY_OPERATOR_ID,1).digest
    event=build_vgi_similarity_event(workload,'peer','similarity',1,workload.logical_time)
    assert event.request.resource == SIMILARITY_RESOURCE
    assert event.request.operation == node.operation_name
    assert event.request.destructive is False
    assert node.implementation_fingerprint != '0'*64