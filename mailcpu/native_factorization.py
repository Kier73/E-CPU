"""Opt-in adapter retaining original native DAG identities and frontier commits."""
from dataclasses import dataclass
from hashlib import sha256
import json

from .computation_dag import NavigableComputationDAG
from .factorized_intentions import Binding, Intention, Node, Plan, factorize, execute


def _canonical(value):
    """Encode the original native JSON payload without changing its semantics."""
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode('utf-8')


@dataclass(frozen=True)
class NativePreparation:
    """An exact native graph family and its proposed structural realization."""
    graphs: tuple
    plan: Plan


def _project(graphs,bindings):
    """Bind exact native operation/resource/context triples to pure-only work."""
    intentions=[]; identities=[]; selected={}
    if len({id(g) for g in graphs.values()})!=len(graphs):
        raise ValueError('native graph instance reused')
    for name,graph in sorted(graphs.items()):
        if not isinstance(graph,NavigableComputationDAG) or graph.committed_nodes:
            raise ValueError('adapter requires fresh receiver-owned native DAGs')
        before=graph.digest
        pending={n.node_id:n for n in graph.nodes}; nodes=[]; seen=set()
        while pending:
            ready=[n for n in pending.values() if all(d in seen for d in n.dependencies)]
            if not ready: raise ValueError('native graph topology changed')
            for n in ready:
                triple=(n.operation,n.resource,n.context_digest)
                b=bindings.get(triple)
                if not isinstance(b,Binding) or b.contract.context!=n.context_digest:
                    raise ValueError('native pure binding or context missing')
                alias=sha256(_canonical(triple)).hexdigest()
                if selected.setdefault(alias,b)!=b:
                    raise ValueError('native binding identity conflict')
                nodes.append(Node(n.node_id,alias,_canonical(n.payload),n.dependencies))
                seen.add(n.node_id); del pending[n.node_id]
        if graph.digest!=before or graph.committed_nodes:
            raise ValueError('native graph changed during observation')
        # Every original native node must receive a result. Selective cones are
        # available in the pure core; this adapter deliberately preserves full DAGs.
        intentions.append(Intention(name,tuple(nodes),tuple(n.name for n in nodes)))
        identities.append((name,before))
    return tuple(intentions),selected,tuple(identities)


def prepare_native(graphs,bindings):
    """Form a pure realization plan for independent, fresh native DAGs."""
    intentions,selected,identities=_project(graphs,bindings)
    return NativePreparation(identities,factorize(intentions,selected))


def realize_native(graphs,bindings,prepared,bank=None):
    """Recheck the source, verify all results, publish each native ready frontier.

    The caller must own every graph exclusively for the duration. Result schema
    is opt-in; unrelated native operators are not automatically supported.
    Frontiers are atomic in each graph, not across graphs or external effects.
    """
    intentions,selected,identities=_project(graphs,bindings)
    if not isinstance(prepared,NativePreparation) or prepared.graphs!=identities:
        raise ValueError('native preparation is stale or foreign')
    values,stats=execute(intentions,selected,prepared.plan,bank)
    keys={(i,n):k for i,n,k in prepared.plan.members}
    expected=dict(identities)
    for name,graph in sorted(graphs.items()):
        if graph.digest!=expected[name] or graph.committed_nodes:
            raise ValueError('native graph changed before publication')
        while not graph.is_complete:
            if graph.digest!=expected[name]: raise ValueError('native graph revised')
            ready=tuple(n.node_id for n in graph.ready_nodes())
            results={n:{'schema':'mailcpu.fabric.pure-result.v1','value_hex':values[name,n].hex(),'factor_key':keys[name,n]} for n in ready}
            graph.commit_frontier(results,expected_node_ids=ready)
    return stats
