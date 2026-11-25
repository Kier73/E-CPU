"""Matched native DAG commitments and snapshot reconstruction across 512 workflows."""
from hashlib import sha256
import json
import random
from time import perf_counter
from pathlib import Path
import sys
from mailcpu.computation_dag import ComputationNode, NavigableComputationDAG
from mailcpu.factorized_intentions import Binding, _frame, unpack_source
from mailcpu.native_factorization import prepare_native, realize_native
from mailcpu.shared_result_bank import PureContract, ResultBank
from benchmark_factorized_intentions import B, W, h, literal, make

CTX=h(b'fab024-native-signal')


def translate(raw):
    """Decode the native JSON payload and retain exact ordered dependency operands."""
    p,*d=unpack_source(raw)
    return _frame([bytes.fromhex(json.loads(p)['payload']),*d])


def binding(name):
    """Adapt the exact fixture operator to original native JSON node payloads."""
    original=B[name]
    def produce(raw):
        """Realize the original signal operator after typed input translation."""
        return original.produce(translate(raw))
    def verify(raw,out):
        """Check against the original independent mathematical relation."""
        return original.verify(translate(raw),out)
    return Binding(PureContract(h(('native-'+name).encode()),CTX,original.contract.verifier,4096,original.contract.max_result),produce,verify)


def graphs(family):
    """Construct an independent native DAG for every original workflow."""
    return {i.name:NavigableComputationDAG(ComputationNode(n.name,1,n.binding,'cpu',CTX,n.deps,{'payload':n.payload.hex()}) for n in i.nodes if n.name!='unused') for i in family}


def run(root):
    """Compare literal native frontiers with factorized native frontiers byte-for-byte."""
    n,g=512,16
    rng=random.Random(73); sources=[rng.randbytes(W) for _ in range(g)]
    ids=[(i*65537+3)&0xffffff for i in range(n)];ids[-1]=0xffffff
    assert len(set(ids))==n
    family=tuple(make(i,sources[j%g]) for j,i in enumerate(ids))
    normal=graphs(family); shared=graphs(family)
    bindings={(name,'cpu',CTX):binding(name) for name in B}
    t=perf_counter(); prepared=prepare_native(shared,bindings); formation=perf_counter()-t
    keys={(i,n):k for i,n,k in prepared.plan.members}
    t=perf_counter(); literal_producers=0
    for name,graph in sorted(normal.items()):
        while not graph.is_complete:
            ready=graph.ready_nodes(); results={}
            for node in ready:
                b=bindings[node.operation,node.resource,node.context_digest]
                payload=json.dumps(node.payload,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()
                inp=_frame([payload,*(bytes.fromhex(graph.result(d)['value_hex']) for d in node.dependencies)])
                out=b.produce(inp); assert b.verify(inp,out); literal_producers+=1
                results[node.node_id]={'schema':'mailcpu.fabric.pure-result.v1','value_hex':out.hex(),'factor_key':keys[name,node.node_id]}
            graph.commit_frontier(results,expected_node_ids=tuple(x.node_id for x in ready))
    baseline=perf_counter()-t
    t=perf_counter(); stats=realize_native(shared,bindings,prepared); realization=perf_counter()-t
    t=perf_counter(); exact=0
    for name,graph in shared.items():
        snap=graph.snapshot(); assert snap==normal[name].snapshot()
        recovered=NavigableComputationDAG.from_snapshot(snap)
        assert recovered.snapshot()==snap and recovered.is_complete
        exact+=1
    restore_s=perf_counter()-t
    # Cold durable path and fresh graph reopen: same native frontier identities.
    path=root/'native.db'; bank=ResultBank(path,create=True)
    cold_graphs=graphs(family); t=perf_counter(); cold_stats=realize_native(cold_graphs,bindings,prepared,bank); cold=perf_counter()-t
    bank.close(); bank=ResultBank(path); warm_graphs=graphs(family)
    t=perf_counter(); warm_stats=realize_native(warm_graphs,bindings,prepared,bank); warm=perf_counter()-t; bank.close()
    assert all(cold_graphs[i].snapshot()==warm_graphs[i].snapshot()==shared[i].snapshot() for i in shared)
    return dict(native_dags=n,distinct_inputs=g,native_nodes=3*n,shared_classes=len(prepared.plan.work),literal_producers=literal_producers,stats=stats,
                formation_seconds=formation,literal_native_seconds=baseline,factorized_native_seconds=realization,cold_native_seconds=cold,warm_native_seconds=warm,cold_stats=cold_stats,warm_stats=warm_stats,
                exact_native_snapshots=exact,verify_and_restore_seconds=restore_s,database_bytes=path.stat().st_size)

if __name__=='__main__':
    root=Path(sys.argv[1]);root.mkdir(parents=True,exist_ok=True)
    print(json.dumps(run(root),indent=2))
