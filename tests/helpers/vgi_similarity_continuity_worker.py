"""Actual E-CPU Transit/Hypervisor receiver for similarity-basis crash replay.

Reuses the proven VGI semantic-continuity recovery bundle, seed membership,
transport, and quorum authority fixtures. Unlike the separate socket-only lab,
this process proves replay of a committed effect without backend re-entry.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[2]
HELPERS=Path(__file__).resolve().parent
sys.path[:0]=[str(ROOT),str(HELPERS)]

from mailcpu import (  # noqa: E402
    Capability, TransitBackendRouter, TransitComputeSession, TransitComputeWorker,
    HypervisorOperationChannel, HypervisorOperationResultChannel,
    ReliabilityPolicy, ReliableChannel,
)
from mailcpu.transit_vgi_similarity import TransitVGISimilarityHost  # noqa: E402
from mailcpu.vgi_similarity_host import (  # noqa: E402
    PinnedSimilarityCatalogue, PinnedSimilarityRecord,
)
from vgi_continuity_support import NODE_ID, configure_receiver  # noqa: E402
from vgi_semantic_continuity_worker import (  # noqa: E402
    make_store, write_json_durable, open_server_sockets,
    accept_worker_transports, serve_next,
)

CHANNEL='vgi-similarity-continuity'


def _digest(value:object)->str:
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),
                                     ensure_ascii=False,allow_nan=False).encode()).hexdigest()


def catalogue_from_trusted_root(root:Path)->PinnedSimilarityCatalogue:
    """Reopen only an externally pinned local record; no peer-supplied authority."""
    pins=json.loads((root/'trusted-pins.json').read_text(encoding='utf-8'))
    if set(pins)!={'schema','memory_sha256','graph_fingerprint'} or pins['schema']!='vgi.similarity.test-pins.v1':
        raise ValueError('trusted receiver catalogue manifest is malformed')
    record=(root/'admitted-basis.json').read_bytes()
    pinned=PinnedSimilarityRecord(pins['memory_sha256'],pins['graph_fingerprint'],record)
    return PinnedSimilarityCatalogue((pinned,))


class CountingTransitVGISimilarityHost(TransitVGISimilarityHost):
    def __init__(self,operating_system,authority_pid,root:Path):
        super().__init__(operating_system,authority_pid,catalogue_from_trusted_root(root),node_id=NODE_ID)
        self.calls=0

    def handle(self,event):
        self.calls+=1
        return super().handle(event)


def make_session(request_transport,response_transport,root:Path):
    operating_system,_=configure_receiver()
    pid=operating_system.environment.kernel.spawn(
        'similarity-transit-worker',
        capabilities=(Capability('/virtual-layer/operators',frozenset({'compute'})),),
        parent_pid=operating_system.environment.init_pid,
    )
    host=CountingTransitVGISimilarityHost(operating_system,pid,root)
    router=TransitBackendRouter();router.register_backend(host)
    policy=ReliabilityPolicy(lease_ticks=1,max_attempts=5,window_size=8)
    request=HypervisorOperationChannel(ReliableChannel(
        request_transport,'worker','worker',CHANNEL,policy,peer='client'))
    response=HypervisorOperationResultChannel(ReliableChannel(
        response_transport,'worker','client',CHANNEL+'.result',policy,peer='client'),
        'client',CHANNEL)
    session=TransitComputeSession(TransitComputeWorker(operating_system,pid,router),
                                  request,response)
    return session,host


def restored_router(os_,pid,root:Path,hosts:list):
    host=CountingTransitVGISimilarityHost(os_,pid,root)
    hosts.append(host)
    router=TransitBackendRouter();router.register_backend(host)
    return router


def prepare(checkpoint:Path,requester:Path,root:Path,ready:Path,marker:Path):
    req_l,resp_l,req_port,resp_port=open_server_sockets()
    print(json.dumps({'pid':os.getpid(),'mode':'prepare',
                      'request_port':req_port,'response_port':resp_port}),flush=True)
    req_t,resp_t=accept_worker_transports(req_l,resp_l)
    session,host=make_session(req_t,resp_t,root)
    deadline=time.monotonic()+30
    while not ready.exists() and time.monotonic()<deadline:time.sleep(.005)
    if not ready.exists():raise TimeoutError('requester checkpoint was not persisted')

    def after_commit(stage:str)->None:
        if stage!='after_execution_commit':return
        checkpoint_digest=session.save_checkpoint(str(checkpoint),allow_inflight=True)
        sealed=make_store(root).seal(requester,checkpoint,'after_execution_commit')
        os_=session.worker.operating_system
        executions=os_.hypervisor_arbitration.snapshot()['executions']
        if len(executions)!=1:raise AssertionError('expected one original committed effect')
        effect=executions[0]['effect']
        receipt=effect['result']
        journal=os_.environment.kernel.journal.snapshot()
        cut={
            'pid':os.getpid(),'capture_cut':'after_execution_commit',
            'checkpoint_digest':checkpoint_digest,
            'bundle_generation':sealed.generation,
            'bundle_manifest_digest':sealed.manifest.digest,
            'backend_calls_before_kill':host.calls,
            'execution_ledger_entries':len(executions),
            'commit_record_count':sum(r['kind']=='hypervisor.execution.commit' for r in journal),
            'effect_digest':_digest(effect),
            'navigation_effect_digest':receipt['effect_digest'],
            'memory_sha256':receipt['computation_ground']['memory_sha256'],
            'graph_fingerprint':receipt['computation_ground']['graph_fingerprint'],
            'certificate_fingerprint':receipt['computation_ground']['certificate_fingerprint'],
            'result':receipt['navigation']['inner']['result']['values'],
            'journal_valid':os_.environment.kernel.journal.verify(),
            'session_phase':session.phase,
        }
        write_json_durable(marker,cut)
        while True:time.sleep(60)

    while time.monotonic()<deadline:
        result=session.serve_once(fault_hook=after_commit)
        if result is not None:
            raise AssertionError('receiver escaped the forced after-commit crash cut')
        time.sleep(.002)
    raise TimeoutError('no similarity event reached receiver')


def restore(root:Path,result_path:Path):
    req_l,resp_l,req_port,resp_port=open_server_sockets()
    print(json.dumps({'pid':os.getpid(),'mode':'restore',
                      'request_port':req_port,'response_port':resp_port}),flush=True)
    req_t,resp_t=accept_worker_transports(req_l,resp_l)
    bundle=make_store(root).load_latest()
    if bundle.manifest.capture_cut!='after_execution_commit':
        raise AssertionError('receiver recovery did not originate at committed high-water cut')
    hosts:list[CountingTransitVGISimilarityHost]=[]
    session=bundle.restore_receiver_session(
        req_t,resp_t,
        compute_host_factory=lambda os_,pid:restored_router(os_,pid,root,hosts),
    )
    if len(hosts)!=1 or hosts[0].calls!=0:
        raise AssertionError('restored backend was unexpectedly entered')
    replay=serve_next(session)
    if not replay.replayed or not replay.executed:
        raise AssertionError('committed similarity effect was not replayed')
    if hosts[0].calls!=0:
        raise AssertionError('backend recomputed a previously committed effect')
    effect=replay.effect
    receipt=effect['result']
    journal=session.worker.operating_system.environment.kernel.journal.snapshot()
    result={
        'pid':os.getpid(),'stage':'replayed','replayed':replay.replayed,
        'backend_calls_after_restart':hosts[0].calls,
        'bundle_generation':bundle.generation,
        'bundle_manifest_digest':bundle.manifest.digest,
        'effect_digest':_digest(effect),
        'navigation_effect_digest':receipt['effect_digest'],
        'memory_sha256':receipt['computation_ground']['memory_sha256'],
        'graph_fingerprint':receipt['computation_ground']['graph_fingerprint'],
        'result':receipt['navigation']['inner']['result']['values'],
        'execution_ledger_entries':len(session.worker.operating_system.hypervisor_arbitration.snapshot()['executions']),
        'commit_record_count':sum(r['kind']=='hypervisor.execution.commit' for r in journal),
        'replay_record_count':sum(r['kind']=='hypervisor.execution.replay' for r in journal),
        'journal_valid':session.worker.operating_system.environment.kernel.journal.verify(),
    }
    write_json_durable(result_path,result)
    deadline=time.monotonic()+20
    while session.response.channel.pending_sequences() and time.monotonic()<deadline:
        session.response.channel.process_ack()
        time.sleep(.005)
    if session.response.channel.pending_sequences():
        raise TimeoutError('restored similarity response was not acknowledged')
    req_t.close();resp_t.close()


def main(args:list[str])->int:
    if len(args)==6 and args[0]=='prepare':
        prepare(*(Path(v) for v in args[1:]));return 0
    if len(args)==3 and args[0]=='restore':
        restore(Path(args[1]),Path(args[2]));return 0
    raise SystemExit('prepare CHECKPOINT REQUESTER ROOT READY MARKER | restore ROOT RESULT')


if __name__=='__main__':raise SystemExit(main(sys.argv[1:]))