"""Matched synthetic signal workload for the durable pure-result bank."""
from hashlib import sha256
import json
from pathlib import Path
import random
import struct
import sys
from time import perf_counter
from mailcpu.shared_result_bank import PureContract, Consumer, ResultBank

WIDTH=64
FORMAT=struct.Struct('!64I')


def digest(raw):
    """Fixture content identity."""
    return sha256(raw).hexdigest()


CONTRACT=PureContract(digest(b'circular-autocorrelation-u8x64'),digest(b'public-synthetic-signal'),digest(b'packed-convolution-v1'),64,256)
NS=digest(b'fixture-machines')


def produce(raw):
    """Literal circular autocorrelation over 64 bytes."""
    assert len(raw)==WIDTH
    return FORMAT.pack(*(sum(raw[j]*raw[(j+k)%WIDTH] for j in range(WIDTH)) for k in range(WIDTH)))


def verify(raw, output):
    """Independently verify using packed exact integer convolution."""
    if len(raw)!=WIDTH or len(output)!=FORMAT.size:
        return False
    a=int.from_bytes(b''.join(bytes((x,0,0)) for x in raw),'little')
    b=int.from_bytes(b''.join(bytes((x,0,0)) for x in raw[::-1]),'little')
    c=a*b
    def coeff(j):
        """Select a carry-free 24-bit coefficient."""
        return ((c>>(24*j))&0xffffff) if 0<=j<2*WIDTH-1 else 0
    return output==FORMAT.pack(*(coeff(WIDTH-1+k)+coeff(k-1) for k in range(WIDTH)))


def run(root,n,groups):
    """Compare literal work, cold durable reuse, verified reopen and changed dependency."""
    rng=random.Random(127); sources=[rng.randbytes(WIDTH) for _ in range(groups)]
    inputs=[sources[i%groups] for i in range(n)]
    ids=[(i*257+3)&0xffffff for i in range(n)]
    ids[-1]=0xffffff
    assert len(set(ids))==n
    def private(outputs):
        """Apply distinct consumer projections, without claiming native commits."""
        return {i:(1,FORMAT.unpack(out)[j%64]+j*3) for j,(i,out) in enumerate(zip(ids,outputs))}
    t=perf_counter(); baseline=[]
    for raw in inputs:
        result=produce(raw); assert verify(raw,result); baseline.append(result)
    expected=private(baseline); baseline_s=perf_counter()-t
    path=root/f'{n}-{groups}.db'; bank=ResultBank(path,create=True)
    t=perf_counter(); actual=private(bank.resolve_batch(CONTRACT,inputs,produce,verify)); cold=perf_counter()-t
    assert actual==expected and (bank.produced,bank.checked)==(groups,groups)
    records=[Consumer(NS,i,1,digest(str(i).encode()),CONTRACT.key(raw)) for i,raw in zip(ids,inputs)]
    t=perf_counter(); bank.observe_consumers(records); index_s=perf_counter()-t; bank.close()
    bank=ResultBank(path); t=perf_counter(); warm=private(bank.resolve_batch(CONTRACT,inputs,produce,verify)); warm_s=perf_counter()-t
    assert warm==expected and bank.produced==0 and bank.checked==groups
    t=perf_counter(); changed=bank.affected(CONTRACT.key(sources[0]),NS); new=bytes([sources[0][0]^1])+sources[0][1:]
    before=(bank.produced,bank.checked); results=bank.resolve_batch(CONTRACT,[new]*len(changed),produce,verify)
    bank.observe_consumers([Consumer(NS,c.identity,2,digest((str(c.identity)+':2').encode()),CONTRACT.key(new)) for c in changed]); changed_s=perf_counter()-t
    assert len(changed)==n//groups and all(x==produce(new) for x in results)
    assert not bank.affected(CONTRACT.key(sources[0]),NS)
    assert (bank.produced-before[0],bank.checked-before[1])==(1,1)
    bank.close()
    return dict(consumers=n,distinct_inputs=groups,identical_projections=n,baseline_seconds=baseline_s,cold_seconds=cold,warm_reopen_seconds=warm_s,
                baseline_producer_calls=n,cold_producer_calls=groups,warm_producer_calls=0,warm_checker_calls=groups,dependency_index_seconds=index_s,
                changed_consumers=len(changed),changed_producer_calls=1,changed_checker_calls=1,changed_seconds=changed_s,database_bytes=path.stat().st_size)


if __name__=='__main__':
    root=Path(sys.argv[1]); root.mkdir(parents=True,exist_ok=True)
    print(json.dumps({'workload':'synthetic pure signal computation, local SQLite FULL, independent convolution verification, consumer projections not native M3 commits',
                      'runs':[run(root,4096,64),run(root,1024,1024),run(root,4096,1)]},indent=2))
