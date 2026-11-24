"""Measure controller-only sparse attention with synthetic session-head fixtures."""
from dataclasses import dataclass
from hashlib import sha256
import json
from time import perf_counter
from types import SimpleNamespace

from mailcpu.attention import Budget, Offer, machine_scope, plan_attention
from mailcpu.computational_session import ComputationalSessionConflictError, ComputationalSessionStore
from mailcpu.head_attention import HeadAttentionIndex


@dataclass(frozen=True)
class FixtureHead:
    """Synthetic metadata only; not a native ComputationalSessionHead or proof."""
    revision: int
    checkpoint_digest: str
    lineage_manifest: object


class FixtureStore(ComputationalSessionStore):
    """Controller benchmark double; never used for native authority or storage."""
    observations = 0
    materializations = 0

    def __init__(self, namespace, identity):
        """Create an address and a synthetic revision without native initialization."""
        self.session_id=f'fab127.{namespace}.{identity:06x}'
        self.revision=1

    def head(self):
        """Construct deterministic fixture metadata, without quorum verification."""
        key=sha256(f'{self.session_id}:{self.revision}'.encode()).hexdigest()
        return FixtureHead(self.revision,key,SimpleNamespace(digest=sha256(key.encode()).hexdigest()))

    def observe_head(self):
        """Count synthetic observations."""
        type(self).observations+=1
        return self.head()

    def load_observed(self, observed):
        """Count fixture materializations; no actual payload reads."""
        if self.head()!=observed:
            raise ComputationalSessionConflictError('fixture stale head')
        type(self).materializations+=1
        return observed


def run():
    """Compare identical grants and refresh only changed fixture coordinates."""
    n,active,epochs=65536,64,256
    ns=sha256(b'fab020-local-fixture').hexdigest()
    demand=Budget(1,16,0,1)
    cap=Budget(4,64,0,4)
    ids=[(i*257+3)&0xffffff for i in range(n)]
    ids[-1]=0xffffff
    assert len(set(ids))==n
    stores={i:FixtureStore(ns,i) for i in ids}
    index=HeadAttentionIndex(ns)
    start=perf_counter()
    for j,i in enumerate(ids):
        index.refresh(stores[i],demand if j<active else None)
    initial=perf_counter()-start
    all_offers=[Offer(machine_scope(i),1,stores[i].head().checkpoint_digest,demand,j<active)
                for j,i in enumerate(ids)]
    start=perf_counter()
    dense=plan_attention(all_offers,cap,epoch=index.epoch)
    dense_time=perf_counter()-start
    start=perf_counter()
    sparse=index.plan(cap)
    sparse_time=perf_counter()-start
    assert dense.grants==sparse.grants
    before=FixtureStore.observations
    service={}
    materialized=0
    start=perf_counter()
    for _ in range(epochs):
        plan=index.plan(cap,service=service)
        assert index.verify(plan,cap,service=service)
        grant=plan.grants[0]
        store=stores[int(''.join(grant.scope),16)]
        assert index.load_grant(store,grant).revision==store.revision
        materialized+=1
        store.revision+=1
        index.refresh(store,demand)
        assert not index.verify(plan,cap,service=service)
        for j in range(1,7):
            prefix=grant.scope[:j]
            service[prefix]=service.get(prefix,0)+1
    elapsed=perf_counter()-start
    assert FixtureStore.observations-before==epochs and len(index.offers())==active
    return dict(workload='fixture session heads, exact native FAB-014 allocator and new index; no native quorum/M1 calls',
        addressable=2**24,observed=n,pending=active,grants_per_plan=4,
        initial_refresh_seconds=initial,dense_plan_seconds=dense_time,sparse_plan_seconds=sparse_time,
        equal_initial_grants=True,epochs=epochs,changed_head_observations=FixtureStore.observations-before,
        fixture_materializations=materialized,epoch_loop_seconds=elapsed,
        dense_active_nodes=dense.active_nodes,sparse_active_nodes=sparse.active_nodes)


if __name__=='__main__':
    print(json.dumps(run(),indent=2))
