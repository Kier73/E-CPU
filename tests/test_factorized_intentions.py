from dataclasses import replace
from hashlib import sha256
import pytest
from mailcpu.factorized_intentions import Binding, Node, Intention, factorize, verify_plan, execute, unpack_source
from mailcpu.shared_result_bank import PureContract, ResultBank


def h(x): return sha256(x).hexdigest()


def bind(op,ctx=b'ctx'):
    def produce(raw):
        p,*ds=unpack_source(raw)
        vals=[int.from_bytes(x,'big') for x in ds]
        v=int.from_bytes(p,'big')+sum((j+1)*x for j,x in enumerate(vals))
        return v.to_bytes(8,'big')
    def verify(raw,result): return result==produce(raw)
    return Binding(PureContract(h(op),h(ctx),h(b'checker'),4096,8),produce,verify)


def family():
    return tuple(Intention(str(j),(Node('a','add',b'\x02'),Node('b','add',b'\x03',('a',)),Node('c','add',bytes([j]),('a','b','a')),Node('dead','add',b'ignored')),('c',)) for j in range(8))


def test_share_and_slice(tmp_path):
    intents=family(); bindings={'add':bind(b'add')}; plan=factorize(intents,bindings)
    assert len(plan.work)==10 and len(plan.members)==24 and len(plan.outputs)==8
    assert len(plan.affected(plan.work[0].key))==8
    bank=ResultBank(tmp_path/'bank.db',create=True)
    values,stats=execute(intents,bindings,plan,bank)
    assert [int.from_bytes(values[str(i),'c'],'big') for i in range(8)]==[18+i for i in range(8)]
    assert stats=={'classes':10,'producers':10,'checks':10}
    assert ('0','dead') not in values
    bank.close(); bank=ResultBank(tmp_path/'bank.db')
    other,stats=execute(intents,bindings,plan,bank)
    assert other==values and stats=={'classes':10,'producers':8,'checks':10}
    bank.close()


def test_exact_semantics_and_order():
    b={'add':bind(b'add'),'other':bind(b'add',b'different')}
    n=(Node('a','add',b'\x02'),Node('b','add',b'\x03'),Node('c','add',b'',('a','b')),Node('d','add',b'',('b','a')),Node('e','other',b'\x02'))
    w=Intention('w',n,('c','d','e')); p=factorize([w],b)
    assert len(p.work)==5
    values,_=execute([w],b,p)
    assert int.from_bytes(values['w','c'],'big')==8
    assert int.from_bytes(values['w','d'],'big')==7
    with pytest.raises(ValueError): verify_plan([w],{'add':bind(b'add',b'changed'),'other':b['other']},p)


def test_tamper():
    f=family(); b={'add':bind(b'add')}; p=factorize(f,b)
    for bad in (replace(p,members=p.members[:-1]),replace(p,work=p.work+(p.work[0],)),replace(p,outputs=p.outputs[:-1]),replace(p,members=(('0','a',p.work[1].key),)+p.members[1:]),replace(p,work=(replace(p.work[0],payload=b'forged'),)+p.work[1:])):
        with pytest.raises(ValueError): execute(f,b,bad)
    broken=replace(b['add'],produce=lambda _:b'false')
    with pytest.raises(ValueError,match='verification refused'): execute(f,{'add':broken},p)
    with pytest.raises(ValueError): factorize(f,{})
    with pytest.raises(ValueError): Intention('cycle',(Node('a','add',b'',('a',)),),('a',))


def test_partial_change():
    f=family(); b={'add':bind(b'add')}; p=factorize(f,b); before,_=execute(f,b,p)
    n=replace(f[0].nodes[0],payload=b'\x04'); change=replace(f[0],nodes=(n,)+f[0].nodes[1:]); new=(change,)+f[1:]
    q=factorize(new,b); after,_=execute(new,b,q)
    assert all(before[str(j),'c']==after[str(j),'c'] for j in range(1,8)) and before['0','c']!=after['0','c']
    assert p.affected(p.work[0].key)==tuple(str(j) for j in range(8))
    with pytest.raises(ValueError): verify_plan(new,b,p)
