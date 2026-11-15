"""Physical-process E-CPU recovery of a committed VGI similarity navigation.

Only enabled by dedicated integration CI with GEOMETRY-FIRST-008 installed.
This tests the EXISTING E-CPU reliable channels, quorum-sealed checkpoint and
execution ledger rather than implementing a new replay authority.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

pytest.importorskip('vgi.structural_memory')

ROOT=Path(__file__).resolve().parents[1]
HELPERS=ROOT/'tests'/'helpers'
if str(HELPERS) not in sys.path:
    sys.path.insert(0,str(HELPERS))

from mailcpu import (  # noqa: E402
    HypervisorOperationChannel, HypervisorOperationResultChannel,
    ReliabilityPolicy, ReliableChannel, SocketTransport,
    VirtualBudget, VirtualGroundRef, VirtualLayerWorkload, VirtualOperatorRef,
)
from mailcpu.vgi_similarity_host import (  # noqa: E402
    SIMILARITY_OPERATOR_ID, SIMILARITY_REQUEST_SCHEMA,
)
from mailcpu.transit_vgi_similarity import build_vgi_similarity_event  # noqa: E402
from vgi.typed_operator_navigation import TypedVector, PreparedTemporalOperator  # noqa: E402
from vgi.structural_memory import admit_similarity_memory  # noqa: E402
from examples.vgi_similarity_transfer_process import build_lab_ground  # noqa: E402
from vgi_continuity_support import NODE_ID, SYSTEM_ID, configure_receiver  # noqa: E402
from vgi_semantic_continuity_worker import make_store, write_json_durable  # noqa: E402

CHANNEL='vgi-similarity-continuity'


def _wait_ready(proc:subprocess.Popen[str]):
    assert proc.stdout is not None
    line=proc.stdout.readline()
    if not line:
        o,e=proc.communicate(timeout=5)
        raise AssertionError(f'no listening receiver: {proc.returncode}, {o}, {e}')
    return json.loads(line)


def _wait_marker(path:Path,proc:subprocess.Popen[str],timeout:float=40):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        if path.is_file():return json.loads(path.read_text())
        if proc.poll() is not None:
            o,e=proc.communicate(timeout=5)
            raise AssertionError(f'worker exited before durable cut: {proc.returncode}, {o}, {e}')
        time.sleep(.01)
    raise AssertionError('receiver did not publish committed recovery checkpoint')


def _clients(ready:dict):
    request_t=SocketTransport.connect('127.0.0.1',int(ready['request_port']),'client','worker')
    response_t=SocketTransport.connect('127.0.0.1',int(ready['response_port']),'client','worker')
    policy=ReliabilityPolicy(lease_ticks=1,max_attempts=5,window_size=8)
    request=HypervisorOperationChannel(ReliableChannel(request_t,'client','worker',CHANNEL,policy))
    response=HypervisorOperationResultChannel(ReliableChannel(
        response_t,'client','client',CHANNEL+'.result',policy,peer='worker'),
        'client',CHANNEL)
    return (request_t,response_t),request,response


def _await_response(channel,proc,timeout:float=35):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        x=channel.receive()
        if x is not None:return x
        if proc.poll() is not None:
            o,e=proc.communicate(timeout=5)
            raise AssertionError(f'restored receiver exited: {proc.returncode} {o} {e}')
        time.sleep(.003)
    raise AssertionError('no recovered similarity effect arrived')


def _await_ack(channel):
    deadline=time.monotonic()+15
    ack=[]
    while channel.pending_sequences() and time.monotonic()<deadline:
        ack.extend(channel.process_ack());time.sleep(.005)
    assert channel.pending_sequences()==()
    assert tuple(ack)==(1,)


def test_similarity_ground_survives_transit_commit_crash_and_bundle_restore(tmp_path:Path):
    """Sender holds intent; receiver dies after commit, new PID replays receipt without re-execution."""
    graph,cert,record=build_lab_ground()
    admitted=admit_similarity_memory(record,expected_graph_fingerprint=graph.fingerprint)
    # Provision the immutable record independently of peer-provided event
    # bytes. The test's out-of-band pins stand for an admitted provenance
    # authority; they do not themselves establish production authorization.
    (tmp_path/'admitted-basis.json').write_bytes(record)
    write_json_durable(tmp_path/'trusted-pins.json',{
        'schema':'vgi.similarity.test-pins.v1',
        'memory_sha256':admitted.memory_sha256,
        'graph_fingerprint':graph.fingerprint,
    })
    _,envelope=configure_receiver()
    initial=TypedVector(graph.domain,(2,4,8,16,32,64))
    tick=10**30+11
    workload=VirtualLayerWorkload(
        workload_id='similarity-transit-recovery-001',
        system=SYSTEM_ID,
        ground=VirtualGroundRef.from_envelope(envelope),
        intention={'goal':{'kind':'navigate-admitted-similarity-ground'}},
        operators=(VirtualOperatorRef(SIMILARITY_OPERATOR_ID,1,'cpu'),),
        input_value={
            'schema':SIMILARITY_REQUEST_SCHEMA,
            'memory_sha256':admitted.memory_sha256,
            'graph_fingerprint':graph.fingerprint,
            'initial':initial.to_dict(),
            'logical_tick':tick,
        },
        budget=VirtualBudget(100_000,1_000_000,1_000),
        logical_time=7,eligible_nodes=(NODE_ID,),max_hops=2,
    )
    expected=PreparedTemporalOperator.from_chain(graph).state_at(initial,tick).result.values
    worker=ROOT/'tests'/'helpers'/'vgi_similarity_continuity_worker.py'
    receiver_checkpoint=tmp_path/'receiver-similarity-session.json'
    requester_checkpoint=tmp_path/'requester-similarity-session.json'
    ready_file=tmp_path/'requester-ready.json'
    marker=tmp_path/'committed-cut.json'
    restored_path=tmp_path/'restored-result.json'
    first=None;second=None;transports=[]
    try:
        first=subprocess.Popen([
            sys.executable,str(worker),'prepare',str(receiver_checkpoint),
            str(requester_checkpoint),str(tmp_path),str(ready_file),str(marker),
        ],cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,bufsize=1)
        ready=_wait_ready(first)
        network,req,resp=_clients(ready)
        transports.extend(network)
        event=build_vgi_similarity_event(workload,'client',CHANNEL,1,workload.logical_time)
        assert req.send(event)==1
        write_json_durable(requester_checkpoint,{
            'kind':'mailcpu.vgi-similarity.requester-checkpoint.v1',
            'event':event.to_dict(),
            'request_channel':req.channel.snapshot(),
            'response_channel':resp.snapshot(),
        })
        write_json_durable(ready_file,{'ready':True})
        cut=_wait_marker(marker,first)
        assert cut['pid']==first.pid != os.getpid()
        assert cut['capture_cut']=='after_execution_commit'
        assert cut['backend_calls_before_kill']==1
        assert cut['execution_ledger_entries']==1
        assert cut['commit_record_count']==1
        assert cut['journal_valid'] is True
        assert cut['memory_sha256']==admitted.memory_sha256
        assert cut['graph_fingerprint']==graph.fingerprint
        assert tuple(cut['result'])==expected
        assert cut['session_phase']=='request-ready'
        assert len(cut['navigation_effect_digest'])==64
        sealed=make_store(tmp_path).load_latest()
        assert sealed.manifest.capture_cut=='after_execution_commit'
        assert sealed.manifest.digest==cut['bundle_manifest_digest']
        content=json.loads(sealed.receiver_checkpoint.decode('utf-8'))
        effects=content['state']['receiver']['hypervisor_arbitration']['executions']
        assert len(effects)==1
        committed=effects[0]['effect']
        assert committed['result']['effect_digest']==cut['navigation_effect_digest']
        assert committed['result']['navigation']['inner']['result']['values']==list(expected)
        request_snapshot=req.channel.snapshot()
        response_snapshot=resp.snapshot()
        assert req.channel.pending_sequences()==(1,)
        assert resp.channel.peek() is None
        first.kill();first.communicate(timeout=10)
        assert first.returncode!=0
        for t in network:t.close()
        second=subprocess.Popen([
            sys.executable,str(worker),'restore',str(tmp_path),str(restored_path),
        ],cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,bufsize=1)
        ready2=_wait_ready(second)
        inbound=SocketTransport.connect('127.0.0.1',int(ready2['request_port']),'client','worker')
        outbound=SocketTransport.connect('127.0.0.1',int(ready2['response_port']),'client','worker')
        transports.extend((inbound,outbound))
        req=HypervisorOperationChannel(ReliableChannel.from_snapshot(request_snapshot,inbound))
        resp=HypervisorOperationResultChannel.from_snapshot(response_snapshot,outbound)
        assert req.channel.pending_sequences()==(1,)
        assert req.channel.retransmit(1) is True
        replay=_await_response(resp,second)
        assert replay.executed is True
        assert replay.action.value=='allow'
        assert replay.effect==committed
        assert replay.effect['result']['navigation']['inner']['result']['values']==list(expected)
        _await_ack(req.channel)
        stdout,stderr=second.communicate(timeout=30)
        assert second.returncode==0,(stdout,stderr)
        result=json.loads(restored_path.read_text())
        assert result['pid']==second.pid != cut['pid']
        assert result['stage']=='replayed'
        assert result['replayed'] is True
        assert result['backend_calls_after_restart']==0
        assert result['effect_digest']==cut['effect_digest']
        assert result['navigation_effect_digest']==cut['navigation_effect_digest']
        assert result['memory_sha256']==admitted.memory_sha256
        assert result['graph_fingerprint']==graph.fingerprint
        assert result['execution_ledger_entries']==1
        assert result['commit_record_count']==1
        assert result['replay_record_count']==1
        assert result['journal_valid'] is True
        assert make_store(tmp_path).load_latest().manifest==sealed.manifest
    finally:
        for proc in (first,second):
            if proc is not None and proc.poll() is None:
                proc.kill();proc.communicate(timeout=10)
        for transport in transports:
            if not transport.closed:transport.close()