"""GEOMETRY-TRANSIT-001 lab: mathematical record transfer, SIGKILL and restore.

Two different OS PIDs transfer a VGI certificate over localhost TCP. A fresh
receiver verifies exact identity/proof, persists the record and a result cut
before it can be killed, then another PID reconstructs the same result.

THIS IS NOT the E-CPU Transit ledger or quorum recovery protocol. Those must
be tested separately with the actual mailcpu runtime and CI. Localhost TCP is
unauthenticated; trusted expected digests arrive via an independent test path.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
from typing import Any

MAX_PAYLOAD=1_048_576


def _json(value: object) -> bytes:
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()


def _digest(value: object) -> str:
    return hashlib.sha256(_json(value)).hexdigest()


def _write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_name(path.name+'.tmp')
    with tmp.open('wb') as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp,path)
    if os.name != 'nt':
        fd=os.open(path.parent,os.O_RDONLY)
        try:os.fsync(fd)
        finally:os.close(fd)


def _recv_all(s:socket.socket,n:int)->bytes:
    if n<0 or n>MAX_PAYLOAD: raise ValueError('transfer payload outside finite bound')
    parts=[]
    while n:
        part=s.recv(n)
        if not part:raise EOFError('truncated transfer')
        parts.append(part)
        n-=len(part)
    return b''.join(parts)


def _recv_payload(s:socket.socket)->bytes:
    n=int.from_bytes(_recv_all(s,4),'big')
    if n<=0 or n>MAX_PAYLOAD:raise ValueError('invalid bounded record length')
    payload=_recv_all(s,n)
    if s.recv(1):raise ValueError('unexpected trailing transfer bytes')
    return payload


def _tiny_matmul(a,b,p):
    n=len(a)
    return tuple(tuple(sum(a[i][k]*b[k][j] for k in range(n))%p for j in range(n)) for i in range(n))


def _inv(a,p):
    n=len(a); rows=[list(row)+[int(i==j) for j in range(n)] for i,row in enumerate(a)]
    for i in range(n):
        pivot=next((j for j in range(i,n) if rows[j][i]%p),None)
        if pivot is None:raise ValueError('noninvertible mixing matrix')
        rows[i],rows[pivot]=rows[pivot],rows[i]
        scale=pow(rows[i][i]%p,-1,p)
        rows[i]=[v*scale%p for v in rows[i]]
        for j in range(n):
            if i!=j:
                t=rows[j][i]
                rows[j]=[(v-t*w)%p for v,w in zip(rows[j],rows[i])]
    return tuple(tuple(row[n:]) for row in rows)


def build_lab_ground():
    """Construct concealed direct sum; supplier doesn't hand its basis to VGI."""
    from vgi.typed_operator_navigation import DenseMap,FiniteSpace,OperatorChain
    from vgi.similarity_blocks import CertifiedSimilarityBlocks
    from vgi.structural_memory import export_similarity_memory
    p=101;n=6
    frame=FiniteSpace('source-substrate',n,p)
    # Diagonal block coefficients deliberately differ, and each pair of
    # block factors need not commute with one another.
    blocks=[
        (((2,1),(1,1)),((1,3),(2,4))),
        (((3,2),(1,2)),((2,1),(4,1))),
        (((4,1),(1,3)),((1,4),(3,2))),
    ]
    matrices=[]
    for part in (0,1):
        b=[[0]*n for _ in range(n)]
        for index,group in enumerate(blocks):
            for i in range(2):
                for j in range(2):b[2*index+i][2*index+j]=group[part][i][j]
        matrices.append(tuple(tuple(row) for row in b))
    # A full-support reproducible matrix; deterministic exact modular inverse.
    mixing=((1,1,1,1,0,0),(0,1,1,0,1,1),(1,0,1,1,0,1),
            (0,1,0,1,1,1),(1,1,0,0,1,1),(1,0,1,1,1,0))
    try: inv=_inv(mixing,p)
    except ValueError:
        mixing=tuple(tuple((int(i==j)+(1 if j==i+1 else 0)) for j in range(n)) for i in range(n))
        inv=_inv(mixing,p)
    factors=[]
    for i,b in enumerate(matrices):
        a=_tiny_matmul(_tiny_matmul(mixing,b,p),inv,p)
        factors.append(DenseMap(f'substrate-operator-{i}',frame,frame,a))
    graph=OperatorChain(tuple(factors))
    cert=CertifiedSimilarityBlocks.discover(graph,max_candidates=48)
    if cert.block_sizes != (2,2,2):
        # A valid different split is acceptable; protocol verifies any split.
        if len(cert.block_sizes)<2:raise AssertionError('no useful split certified')
    return graph,cert,export_similarity_memory(cert)


def _navigation(record:bytes,graph_sha:str,mem_sha:str,tick:int,initial:tuple[int,...]):
    from vgi.structural_memory import admit_similarity_memory
    from vgi.typed_operator_navigation import TypedVector
    from vgi.similarity_blocks import CertifiedSimilarityBlocks
    # A receiver must never discover the basis: only independent proof checks.
    original=CertifiedSimilarityBlocks.discover
    def forbidden(*args,**kwargs):
        raise AssertionError('receiver attempted expensive basis rediscovery')
    CertifiedSimilarityBlocks.discover=classmethod(lambda cls,*args,**kwargs:forbidden())
    try:
        admitted=admit_similarity_memory(record,expected_graph_fingerprint=graph_sha,
                                         expected_memory_sha256=mem_sha)
        receipt=admitted.state_at(TypedVector(admitted.graph.domain,initial),tick)
    finally:
        CertifiedSimilarityBlocks.discover=original
    return admitted,receipt


def producer(port_path:Path,alter:bool=False)->None:
    begun=time.perf_counter_ns()
    graph,cert,payload=build_lab_ground()
    discovery_ms=round((time.perf_counter_ns()-begun)/1e6,3)
    from vgi.structural_memory import admit_similarity_memory
    admitted=admit_similarity_memory(payload,expected_graph_fingerprint=graph.fingerprint)
    with socket.socket(socket.AF_INET,socket.SOCK_STREAM) as listener:
        listener.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
        listener.bind(('127.0.0.1',0));listener.listen(1);listener.settimeout(20)
        info={'pid':os.getpid(),'port':listener.getsockname()[1],
              'graph_fingerprint':graph.fingerprint,'memory_sha256':admitted.memory_sha256,
              'record_bytes':len(payload),'discovered_blocks':list(cert.block_sizes),
              'discovery_ms':discovery_ms}
        _write_atomic(port_path,_json(info))
        c,_=listener.accept()
        with c:
            c.settimeout(10)
            if alter:payload=payload[:-1]+bytes([payload[-1]^1])
            c.sendall(len(payload).to_bytes(4,'big')+payload)
            c.shutdown(socket.SHUT_WR)


def receiver(port:int,root:Path,graph_sha:str,mem_sha:str,tick:int,initial:tuple[int,...]):
    with socket.create_connection(('127.0.0.1',port),timeout=15) as s:
        s.settimeout(10)
        data=_recv_payload(s)
    begun=time.perf_counter_ns()
    admitted,receipt=_navigation(data,graph_sha,mem_sha,tick,initial)
    verify_ms=round((time.perf_counter_ns()-begun)/1e6,3)
    _write_atomic(root/'record.json',data)
    out={'schema':'VGI-PortableTransfer-LabCut-1','stage':'after_mathematical_verification',
         'producer_graph_fingerprint':graph_sha,'memory_sha256':mem_sha,
         'certificate_fingerprint':admitted.certificate.fingerprint,
         'receiver_pid':os.getpid(),'initial':list(initial),'tick':str(tick),
         'result':list(receipt.inner.result.values),
         'receipt_digest':_digest(receipt.to_dict()),
         'discovery_ran_on_receiver':False,'verification_ms':verify_ms,
         'scope':'math_record_durability_not_transit_commit_ledger'}
    _write_atomic(root/'cut.json',_json(out))
    print(json.dumps({'ready':True,**out}),flush=True)
    # The parent forcibly terminates this process AFTER durable publication.
    while True:time.sleep(10)


def restored(root:Path,graph_sha:str,mem_sha:str)->dict[str,Any]:
    data=(root/'record.json').read_bytes()
    cut=json.loads((root/'cut.json').read_text())
    if cut.get('memory_sha256')!=mem_sha or cut.get('producer_graph_fingerprint')!=graph_sha:
        raise ValueError('recovery cut is not pinned to the expected mathematical Ground')
    # Both the persistent data and the recorded result must reverify.
    initial=tuple(cut['initial']);tick=int(cut['tick'])
    begun=time.perf_counter_ns()
    admitted,receipt=_navigation(data,graph_sha,mem_sha,tick,initial)
    verify_ms=round((time.perf_counter_ns()-begun)/1e6,3)
    if (list(receipt.inner.result.values)!=cut['result']
        or _digest(receipt.to_dict())!=cut['receipt_digest']
        or admitted.certificate.fingerprint!=cut['certificate_fingerprint']):
        raise ValueError('recovered mathematical state differs from durable verified cut')
    out={'status':'verified_after_abrupt_death','pid':os.getpid(),
         'prior_pid':cut['receiver_pid'],'graph_fingerprint':graph_sha,
         'memory_sha256':mem_sha,'result':cut['result'],
         'receipt_digest':cut['receipt_digest'],
         'rediscovery':False,'recomputed_after_restart':True,
         'reverification_ms':verify_ms,
         'transit_effect_replay_verified':False}
    _write_atomic(root/'restored.json',_json(out))
    return out


def wait_file(path:Path,process:subprocess.Popen[str],timeout:float=25):
    until=time.monotonic()+timeout
    while time.monotonic()<until:
        if path.exists():return json.loads(path.read_text())
        if process.poll() is not None:
            out,err=process.communicate(timeout=2)
            raise RuntimeError('child exited before publishing: '+repr((process.returncode,out,err)))
        time.sleep(.015)
    raise TimeoutError(f'timed out awaiting {path}')


def orchestrate(root:Path,*,tamper:bool=False)->dict[str,Any]:
    script=Path(__file__).resolve()
    root.mkdir(parents=True,exist_ok=True)
    producer_p:subprocess.Popen[str]|None=None
    receiver_p:subprocess.Popen[str]|None=None
    try:
        producer_p=subprocess.Popen([sys.executable,str(script),'producer',str(root/'producer.json'),
                                     'tamper' if tamper else 'clean'],
                                    stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        info=wait_file(root/'producer.json',producer_p)
        g,m=info['graph_fingerprint'],info['memory_sha256']
        tick=10**30+11
        initial=tuple((i*i+7*i+3)%101 for i in range(6))
        receiver_p=subprocess.Popen([sys.executable,str(script),'receiver',str(info['port']),str(root),
                                     g,m,str(tick),','.join(map(str,initial))],
                                    stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        if tamper:
            _,err=receiver_p.communicate(timeout=25)
            if receiver_p.returncode==0 or (root/'cut.json').exists():
                raise AssertionError('tampered untrusted transfer was accepted')
            return {'tampered_transfer_rejected':True,'receiver_exit_code':receiver_p.returncode,
                    'receiver_error':err.strip().splitlines()[-1] if err.strip() else '',
                    'expected_ground_fingerprint':g}
        cut=wait_file(root/'cut.json',receiver_p)
        assert cut['receiver_pid']==receiver_p.pid
        receiver_p.kill()
        receiver_p.communicate(timeout=5)
        assert receiver_p.returncode!=0
        # Fresh mathematical verifier: a distinct PID reads only durable data.
        restart=subprocess.run([sys.executable,str(script),'restore',str(root),g,m],
                               capture_output=True,text=True,timeout=25,check=True)
        restored_data=json.loads(restart.stdout)
        if restored_data['pid']==cut['receiver_pid']:
            raise AssertionError('restore reused the terminated process')
        from vgi.structural_memory import admit_similarity_memory
        from vgi.typed_operator_navigation import TypedVector,PreparedTemporalOperator
        data=(root/'record.json').read_bytes()
        admitted=admit_similarity_memory(data,expected_graph_fingerprint=g,expected_memory_sha256=m)
        expected=PreparedTemporalOperator.from_chain(admitted.graph).state_at(
            TypedVector(admitted.graph.domain,initial),tick).result.values
        if tuple(restored_data['result'])!=expected:
            raise AssertionError('restored result mismatches independent dense power')
        return {'experiment':'GEOMETRY-TRANSIT-001','producer_pid':info['pid'],
                'receiver_pid':cut['receiver_pid'],'recovered_pid':restored_data['pid'],
                'different_receiver_process':True,'record_bytes':info['record_bytes'],
                'graph_fingerprint':g,'memory_sha256':m,'block_sizes':info['discovered_blocks'],
                'logical_tick':str(tick),'result':restored_data['result'],
                'certificate_fingerprint':cut['certificate_fingerprint'],
                'discovery_ms_single':info['discovery_ms'],
                'original_receiver_verification_ms_single':cut['verification_ms'],
                'recovered_receiver_verification_ms_single':restored_data['reverification_ms'],
                'result_matches_dense_reference':True,'no_basis_rediscovery':True,
                'stored_cut_digest':cut['receipt_digest'],
                'restored_receipt_digest':restored_data['receipt_digest'],
                'mathematical_state_recomputed_after_death':True,
                'transit_effect_replay_verified':False}
    finally:
        for p in (producer_p,receiver_p):
            if p is not None and p.poll() is None:
                p.kill();p.communicate(timeout=5)


def main(argv=None):
    ap=argparse.ArgumentParser()
    sub=ap.add_subparsers(dest='mode',required=True)
    prod=sub.add_parser('producer');prod.add_argument('path',type=Path);prod.add_argument('alter',choices=['tamper','clean'])
    recv=sub.add_parser('receiver');recv.add_argument('port',type=int);recv.add_argument('root',type=Path);
    recv.add_argument('graph');recv.add_argument('memory');recv.add_argument('tick',type=int);recv.add_argument('initial')
    restore=sub.add_parser('restore');restore.add_argument('root',type=Path);restore.add_argument('graph');restore.add_argument('memory')
    allp=sub.add_parser('experiment');allp.add_argument('--root',type=Path)
    bad=sub.add_parser('negative');bad.add_argument('--root',type=Path)
    opts=ap.parse_args(argv)
    if opts.mode=='producer':producer(opts.path,alter=opts.alter=='tamper')
    elif opts.mode=='receiver':receiver(opts.port,opts.root,opts.graph,opts.memory,opts.tick,tuple(map(int,opts.initial.split(','))))
    elif opts.mode=='restore':print(json.dumps(restored(opts.root,opts.graph,opts.memory)),flush=True)
    elif opts.mode in {'experiment','negative'}:
        if opts.root is None:
            with tempfile.TemporaryDirectory(prefix='vgi-cross-process-') as tmp:
                data=orchestrate(Path(tmp),tamper=opts.mode=='negative')
        else:data=orchestrate(opts.root,tamper=opts.mode=='negative')
        print(json.dumps(data,indent=2,sort_keys=True))


if __name__=='__main__':main()