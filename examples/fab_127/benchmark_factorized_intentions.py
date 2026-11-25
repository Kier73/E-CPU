"""Synthetic exact multi-stage signal workflows; independent literal controls."""
from hashlib import sha256
from pathlib import Path
import json
import random
import struct
import sys
from time import perf_counter
from mailcpu.factorized_intentions import Binding, Node, Intention, factorize, execute, unpack_source, _frame
from mailcpu.shared_result_bank import PureContract, ResultBank

W=128
FMT=struct.Struct('!128I')

def h(x):
    """Fixture digest."""
    return sha256(x).hexdigest()

def signal(raw):
    """Read source signal or derive a new signal from the previous exact result."""
    p,*d=unpack_source(raw)
    if p==b'cascade' and len(d)==1:
        return bytes(x%256 for x in FMT.unpack(d[0]))
    assert len(p)==W and not d
    return p

def corr(raw):
    """Literal circular autocorrelation."""
    x=signal(raw)
    return FMT.pack(*(sum(x[j]*x[(j+k)%W] for j in range(W)) for k in range(W)))

def check_corr(raw,out):
    """Independent carry-free convolution identity."""
    x=signal(raw)
    a=int.from_bytes(b''.join(bytes((v,0,0)) for v in x),'little')
    b=int.from_bytes(b''.join(bytes((v,0,0)) for v in x[::-1]),'little')
    c=a*b
    def coeff(j):
        """Extract one exact coefficient, with zero outside the linear convolution."""
        return ((c>>(24*j))&0xffffff) if 0<=j<2*W-1 else 0
    return out==FMT.pack(*(coeff(W-1+k)+coeff(k-1) for k in range(W)))

def project(raw):
    """Distinct private projection from both common stages."""
    p,a,b=unpack_source(raw); j=int.from_bytes(p,'big')
    return (FMT.unpack(a)[j%W]+3*FMT.unpack(b)[(j*5)%W]+j).to_bytes(8,'big')

def check_projection(raw,out):
    """Direct offset-based projection check."""
    p,a,b=unpack_source(raw); j=int.from_bytes(p,'big')
    return len(out)==8 and int.from_bytes(out,'big')==int.from_bytes(a[4*(j%W):4*(j%W+1)],'big')+3*int.from_bytes(b[4*((j*5)%W):4*((j*5)%W+1)],'big')+j

B={
    'corr':Binding(PureContract(h(b'corr-128'),h(b'public-signal'),h(b'packed-24'),4096,512),corr,check_corr),
    'project':Binding(PureContract(h(b'project'),h(b'public-signal'),h(b'offset-check'),4096,8),project,check_projection),
}

def make(j,source):
    """A distinct three-stage live workflow plus an unused branch."""
    return Intention(f'{j:06x}',(Node('signal','corr',source),Node('cascade','corr',b'cascade',('signal',)),Node('private','project',j.to_bytes(4,'big'),('signal','cascade')),Node('unused','corr',bytes(reversed(source)))),('private',))

def literal(intent):
    """Separate literal computation and verification of the requested three stages."""
    a,b,c,_=intent.nodes
    s=_frame([a.payload]); x=corr(s); assert check_corr(s,x)
    s=_frame([b.payload,x]); y=corr(s); assert check_corr(s,y)
    s=_frame([c.payload,x,y]); z=project(s); assert check_projection(s,z)
    return z

def run(root,n,g):
    """Compare full literal work, formation, verified execution and durable reuse."""
    r=random.Random(24); sources=[r.randbytes(W) for _ in range(g)]
    family=tuple(make(i,sources[i%g]) for i in range(n))
    t=perf_counter(); expected={i.name:literal(i) for i in family}; baseline=perf_counter()-t
    t=perf_counter(); p=factorize(family,B); formation=perf_counter()-t
    def projected(values,plan):
        """Retain each original selected output identity."""
        return {i:values[i,node] for i,node,_ in plan.outputs}
    t=perf_counter(); values,stats=execute(family,B,p); realization=perf_counter()-t
    assert projected(values,p)==expected and stats['producers']==2*g+n
    bank=ResultBank(root/f'{n}-{g}.db',create=True)
    t=perf_counter(); v,cold=execute(family,B,p,bank); cold_s=perf_counter()-t; assert projected(v,p)==expected
    bank.close(); bank=ResultBank(root/f'{n}-{g}.db')
    t=perf_counter(); v,warm=execute(family,B,p,bank); warm_s=perf_counter()-t; assert projected(v,p)==expected
    assert warm['producers']==(n if n>g else 3*n)
    t=perf_counter(); key=p.members[0][2]; affected=set(p.affected(key)); new=bytes([sources[0][0]^1])+sources[0][1:]
    changed=tuple(make(int(i.name,16),new) for i in family if i.name in affected)
    new_plan=factorize(changed,B); cv,cs=execute(changed,B,new_plan,bank); changed_s=perf_counter()-t
    assert len(affected)==n//g and projected(cv,new_plan)=={i.name:literal(i) for i in changed}
    bank.close()
    return dict(workflows=n,distinct_inputs=g,declared_nodes=4*n,live_nodes=3*n,classes=len(p.work),omitted_nodes=n,baseline_producers=3*n,baseline_seconds=baseline,formation_seconds=formation,verified_execution_seconds=realization,cold_seconds=cold_s,warm_seconds=warm_s,cold=cold,warm=warm,affected=len(affected),changed=cs,changed_seconds=changed_s,exact_outputs=n,database_bytes=(root/f'{n}-{g}.db').stat().st_size)

if __name__=='__main__':
    root=Path(sys.argv[1]); root.mkdir(parents=True,exist_ok=True)
    print(json.dumps({'workload':'synthetic three-stage exact signal workflows; pure operations, not native session commits','runs':[run(root,1024,32),run(root,256,256),run(root,1024,1)]},indent=2))
