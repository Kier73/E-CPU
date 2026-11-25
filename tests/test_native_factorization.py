"""Native integration: preserve every original node and independently commit frontiers."""
from hashlib import sha256
import json
import pytest
from mailcpu.computation_dag import ComputationNode, NavigableComputationDAG
from mailcpu.factorized_intentions import Binding, unpack_source
from mailcpu.native_factorization import prepare_native, realize_native
from mailcpu.shared_result_bank import PureContract, ResultBank


def h(x):
    """Fixture digest."""
    return sha256(x).hexdigest()


CTX=h(b'context'); OTHER=h(b'other-context')


def graph(i,ctx=CTX):
    """Independent native graph with shared dependency cone and distinct output."""
    return NavigableComputationDAG([
        ComputationNode('a',1,'pure.add','cpu',ctx,(),{'value':2}),
        ComputationNode('b',1,'pure.add','cpu',ctx,('a',),{'value':3}),
        ComputationNode('c',1,'pure.add','cpu',ctx,('a','b'),{'value':i}),
    ])


def bindings(ctx):
    """Explicit trusted native operator and independent checker for fixture semantics."""
    def produce(raw):
        """Add payload and ordered predecessor integers."""
        p,*d=unpack_source(raw)
        return (json.loads(p)['value']+sum(int.from_bytes(x,'big') for x in d)).to_bytes(8,'big')
    def verify(raw,out):
        """Check the output by subtracting the source operands."""
        p,*d=unpack_source(raw)
        return len(out)==8 and int.from_bytes(out,'big')-sum(int.from_bytes(x,'big') for x in d)==json.loads(p)['value']
    return {('pure.add','cpu',ctx):Binding(PureContract(h(b'add'),ctx,h(b'check'),4096,8),produce,verify)}


def test_native_independent_frontiers(tmp_path):
    """Two common nodes, eight private results, eight independent graph histories."""
    graphs={str(i):graph(i) for i in range(8)}; b=bindings(CTX)
    prepared=prepare_native(graphs,b)
    assert len(prepared.plan.work)==10 and len(prepared.plan.members)==24
    bank=ResultBank(tmp_path/'bank.db',create=True)
    stats=realize_native(graphs,b,prepared,bank)
    assert stats=={'classes':10,'producers':10,'checks':10}
    for i,g in graphs.items():
        assert g.is_complete and len(g.committed_nodes)==3
        assert int(g.result('c')['value_hex'],16)==int(i)+7
        restored=NavigableComputationDAG.from_snapshot(g.snapshot())
        assert restored.digest==g.digest and restored.result('c')==g.result('c')
    assert len({g.digest for g in graphs.values()})==8
    bank.close(); bank=ResultBank(tmp_path/'bank.db')
    fresh={str(i):graph(i) for i in range(8)}
    stats=realize_native(fresh,b,prepare_native(fresh,b),bank)
    assert stats=={'classes':10,'producers':8,'checks':10}
    bank.close()


def test_native_scope_and_stale():
    """Foreign context or modified original graph cannot consume the old plan."""
    g={'a':graph(1),'b':graph(2,OTHER)}; b=bindings(CTX)
    with pytest.raises(ValueError,match='context missing'): prepare_native(g,b)
    b.update(bindings(OTHER)); p=prepare_native(g,b)
    assert len(p.plan.work)==6
    g['a']=graph(9)
    with pytest.raises(ValueError,match='stale'): realize_native(g,b,p)
    assert not any(x.committed_nodes for x in g.values())
    bad=bindings(CTX)
    old=bad[('pure.add','cpu',CTX)]
    bad[('pure.add','cpu',CTX)]=Binding(old.contract,lambda _:b'false',old.verify)
    g={'a':graph(1)}; p=prepare_native(g,bad)
    with pytest.raises(ValueError,match='verification refused'): realize_native(g,bad,p)
    assert not g['a'].committed_nodes
