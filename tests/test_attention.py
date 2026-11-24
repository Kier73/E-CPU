from dataclasses import replace
from hashlib import sha256
import random
import pytest
from mailcpu.attention import Budget, Offer, machine_scope, plan_attention, verify_plan


def make(i, *path, demand=Budget(1,1,1,1), ready=True, revision=1):
    """Create a deterministic test observation."""
    return Offer(machine_scope(i,*path),revision,sha256(str((i,path,revision)).encode()).hexdigest(),demand,ready)


def test_budget_and_recursion():
    """Enforce ancestor capacity and bind plans to exact observations."""
    offers=[make(i,*p) for i in (0,1,0xffffff) for p in [('parent','child'),('parent','self')]]
    cap=Budget(4,4,4,4)
    limits={('0',):Budget(2,2,2,2),machine_scope(0):Budget(1,1,1,1)}
    plan=plan_attention(offers,cap,epoch=1,limits=limits)
    assert [o.scope for o in plan.grants]==[offers[i].scope for i in (0,4,2,5)]
    assert plan.spent==cap and not plan.authoritative
    assert verify_plan(plan,reversed(offers),cap,epoch=1,limits=limits)
    assert not verify_plan(plan,offers,cap,epoch=2,limits=limits)
    assert not verify_plan(plan,[replace(offers[0],revision=2),*offers[1:]],cap,epoch=1,limits=limits)
    assert not verify_plan(replace(plan,grants=plan.grants[::-1]),offers,cap,epoch=1,limits=limits)


def test_heterogeneous_and_service():
    """Select feasible demands and account for prior subtree service."""
    offers=[make(0,'a',demand=Budget(2,3)), make(0,'b',demand=Budget(1,0)),make(0xffffff,'a',demand=Budget(1,1)),make(123,'a',ready=False)]
    cap=Budget(2,1)
    plan=plan_attention(offers,cap,epoch=2,service={('0',):8})
    assert plan.grants==(offers[2],offers[1])
    assert plan.spent==cap
    assert plan_attention(offers,Budget(),epoch=0).grants==()
    assert plan_attention([],cap,epoch=0).active_nodes==1


def test_bad_input():
    """Refuse invalid identities, resource counts and ambiguous work leaves."""
    with pytest.raises(ValueError): machine_scope(2**24)
    with pytest.raises(ValueError): machine_scope(True)
    with pytest.raises(ValueError): Budget(-1)
    with pytest.raises(ValueError): plan_attention([make(1),make(1,'a')],Budget(1),epoch=0)
    with pytest.raises(ValueError): plan_attention([make(1),make(1)],Budget(1),epoch=0)


def test_random_conservation():
    """Check conservation and maximal feasible allocation over 100 seeded cases."""
    rng=random.Random(127)
    for epoch in range(100):
        offers=[make(i,'p',demand=Budget(rng.randrange(1,5),rng.randrange(5),rng.randrange(5),rng.randrange(5)),ready=rng.choice([True,True,False])) for i in rng.sample(range(2**24),64)]
        cap=Budget(30,30,30,30)
        limits={ (hex(i)[2:],):Budget(6,6,6,6) for i in range(16)}
        plan=plan_attention(offers,cap,epoch=epoch,limits=limits)
        assert plan.spent.fits(cap)
        for prefix,limit in limits.items():
            used=Budget()
            for o in plan.grants:
                if o.scope[:len(prefix)]==prefix: used=used.plus(o.demand)
            assert used.fits(limit)
        assert len(set(plan.grants))==len(plan.grants) and all(o.ready for o in plan.grants)
        for o in offers:
            if not o.ready or o in plan.grants: continue
            rem=cap.minus(plan.spent)
            for prefix,limit in limits.items():
                if o.scope[:len(prefix)]==prefix:
                    used=Budget()
                    for g in plan.grants:
                        if g.scope[:len(prefix)]==prefix: used=used.plus(g.demand)
                    rem=rem.meet(limit.minus(used))
            assert not o.demand.fits(rem)
        assert verify_plan(plan,offers,cap,epoch=epoch,limits=limits)


def test_sparse_full_address_capacity():
    """Measure bounded selection at 65,536 distinct active address identities."""
    offers=[make((i*2654435761)&0xffffff,'environment','worker') for i in range(65536)]
    cap=Budget(64,64,64,64)
    plan=plan_attention(offers,cap,epoch=0)
    assert len(plan.grants)==64 and plan.spent==cap
    assert plan.node_visits==577 and plan.active_nodes==294298
    assert verify_plan(plan,offers,cap,epoch=0)
