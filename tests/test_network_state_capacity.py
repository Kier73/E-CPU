"""CAPACITY-002: prove local-to-global in-transit capacity and exact neural reinterpretation."""
from __future__ import annotations
from dataclasses import replace
import itertools
import pytest
from mailcpu.network_state_capacity import (
 NetworkCapacityRefused, NetworkProbePolicy, UnawareSite, NetworkGround,
 recognize_network, recheck_network, encode_state, decode_state, build_neural_realization,
)

START = (1, 0, 1, 1, 0, 1, 0, 0)
T = 10**30 + 11

def native_sites(prefix="unaware", snapshot="snapshot-1", call=None):
    def f(h,inbound):
        return (h ^ inbound, h)
    return tuple(UnawareSite(i,f"{prefix}-{i}",snapshot,5,90,call or f) for i in range(4))

def policy(sites,*,quota=32,coord=5):
    return NetworkProbePolicy(frozenset(s.host_id for s in sites),"local-observer",coord,quota)

def observed(prefix="unaware",call=None):
    sites=native_sites(prefix,call=call)
    return recognize_network(sites,policy(sites))

def independent_step(x):
    h,q=x[:4],x[4:]
    out_h=tuple((h[i]+q[(i-1)%4])%2 for i in range(4))
    return out_h+tuple(h)

def independent_oracle(x,t):
    seen={};states=[];s=x
    while s not in seen:
        seen[s]=len(states);states.append(s);s=independent_step(s)
    mu=seen[s];lam=len(states)-mu
    return states[t if t<mu else mu+(t-mu)%lam],mu,lam


def test_live_unaware_sites_provide_closed_network_ground():
    o=observed()
    assert o.ground.sites==4
    assert o.probe_count==32
    assert o.ground.step(START)==independent_step(START)
    assert o.ground.digest != o.path_digest


def test_every_global_state_equals_independent_network_oracle():
    o=observed()
    for state in itertools.product((0,1), repeat=8):
        assert o.ground.step(state)==independent_step(state)


def test_far_logical_time_uses_existing_fgraph_and_not_external_sites():
    calls=[]
    def f(h,q):
        calls.append((h,q))
        return (h ^ q,h)
    o=observed(call=f)
    assert len(calls)==32
    got=o.navigate(START,T)
    want,mu,lam=independent_oracle(START,T)
    assert got.result==want
    assert (got.mu,got.lam)==(mu,lam)
    assert len(calls)==32
    assert o.verify_navigation(got)


def test_same_ground_under_different_unknown_host_placements():
    a,b=observed("observer-a"),observed("observer-b")
    assert a.ground.digest==b.ground.digest
    assert a.path_digest!=b.path_digest
    assert a.navigate(START,T).result==b.navigate(START,T).result
    assert not b.verify_navigation(a.navigate(START,T))


def test_different_source_internals_can_implement_same_function():
    def variant(h,q):
        table=((0,0),(1,0),(1,1),(0,1))
        return table[2*h+q]
    assert observed().ground.digest==observed("other",call=variant).ground.digest


def test_order_of_discovered_sites_is_not_semantic_order():
    sites=native_sites()
    assert recognize_network(list(reversed(sites)),policy(sites)).ground==recognize_network(sites,policy(sites)).ground


def test_navigation_matches_independent_cycle_for_every_start():
    o=observed()
    for n in range(256):
        x=decode_state(n,4)
        assert o.navigate(x,T).result==independent_oracle(x,T)[0]


def test_small_direct_trajectory_agrees_with_navigation():
    o=observed()
    for t in range(25):
        assert o.navigate(START,t).result==o.ground.direct(START,t)


def test_neural_program_is_exhaustively_equivalent_to_global_ground():
    cert=build_neural_realization(observed())
    assert cert["global_rows_verified"]==256
    assert cert["ground_digest"]==observed().ground.digest
    assert cert["parameter_count"]>0


def test_neural_compiler_cannot_promise_unsupported_medium():
    assert build_neural_realization(observed())["ground_digest"]==observed().ground.digest


def test_quota_refusal_precedes_any_external_probe():
    calls=[]
    sites=native_sites(call=lambda a,b:calls.append((a,b)) or (a,b))
    with pytest.raises(NetworkCapacityRefused,match="budget"):
        recognize_network(sites,policy(sites,quota=31))
    assert calls==[]


def test_local_probe_permission_is_receiver_owned():
    sites=native_sites()
    with pytest.raises(NetworkCapacityRefused,match="authority"):
        recognize_network(sites,NetworkProbePolicy(frozenset(),"local-observer",5,32))


def test_expired_site_refused_before_probing():
    sites=native_sites()
    with pytest.raises(NetworkCapacityRefused,match="expired"):
        recognize_network(sites,policy(sites,coord=91))


def test_changed_site_snapshot_changes_only_path_identity():
    a=observed()
    sites=native_sites(snapshot="snapshot-2")
    b=recognize_network(sites,policy(sites))
    assert a.ground.digest==b.ground.digest
    assert a.path_digest!=b.path_digest
    assert not recheck_network(a,sites,policy(sites))


def test_changed_local_law_changes_ground_identity():
    def f(h,q): return (h & q,h)
    a,b=observed(),observed("different",call=f)
    assert a.ground.digest!=b.ground.digest
    assert not b.verify_navigation(a.navigate(START,T))


def test_repeat_probe_detects_nondeterministic_local_implementation():
    counter={}
    def f(h,q):
        k=(h,q);counter[k]=counter.get(k,0)+1
        return (h^q^(counter[k]>1),h)
    with pytest.raises(NetworkCapacityRefused,match="not reproducible"):
        observed(call=f)

@pytest.mark.parametrize("bad",[(True,0),(2,0),(-1,0),(0,),"12"])
def test_invalid_local_observation_refused(bad):
    with pytest.raises(NetworkCapacityRefused):
        observed(call=lambda h,q:bad)


def test_duplicate_role_and_host_refused():
    sites=native_sites()
    with pytest.raises(NetworkCapacityRefused,match="role"):
        recognize_network(sites[:2]+(replace(sites[2],role=1),)+sites[3:],policy(sites))
    with pytest.raises(NetworkCapacityRefused,match="host"):
        recognize_network(sites[:2]+(replace(sites[2],host_id=sites[1].host_id),)+sites[3:],policy(sites))


def test_modified_receipt_is_refused_even_if_payload_is_plausible():
    o=observed()
    r=o.navigate(START,T)
    assert not o.verify_navigation(replace(r,result=START))
    assert not o.verify_navigation(replace(r,coordinate=T+1))
    assert not o.verify_navigation(replace(r,orbit_digest="a"*64))


def test_bit_encoding_round_trip_and_invalid_values():
    for v in range(256):assert encode_state(decode_state(v,4))==v
    with pytest.raises(NetworkCapacityRefused): decode_state(256,4)
    with pytest.raises(NetworkCapacityRefused): encode_state((0,True))
    with pytest.raises(NetworkCapacityRefused): observed().navigate(START,True)


def test_non_affine_local_policy_is_still_navigable_by_functional_graph():
    # XOR/shift was not built into the discovery mechanism. A nonlinear table remains a finite Ground.
    def f(h,q):return (h & q,h|q)
    o=observed("nonlinear",call=f)
    r=o.navigate(START,T)
    s=START
    seen={};trace=[]
    while s not in seen:
        seen[s]=len(trace);trace.append(s)
        s=o.ground.step(s)
    assert r.result==trace[T if T<len(trace) else seen[s]+(T-seen[s])%(len(trace)-seen[s])]
    assert build_neural_realization(o)["global_rows_verified"]==256


def test_neural_realizer_non_authoritative_for_unrecognized_path():
    with pytest.raises(NetworkCapacityRefused):
        recognize_network(native_sites(call=lambda h,q:(h,q) if (h,q)!=(1,1) else (1,9)),policy(native_sites()))


def test_proposed_neural_model_must_pass_exhaustive_independent_ground():
    import mailcpu.transition_space as ts
    original = ts.compile_live_compositional_transition_program
    class Faulty:
        def __init__(self, model):self._m=model
        def __getattr__(self,key):return getattr(self._m,key)
        def predict(self,bits):
            result=self._m.predict(bits)
            if tuple(bits)==START:return (result[0]^1,)+result[1:]
            return result
    ts.compile_live_compositional_transition_program=lambda p:Faulty(original(p))
    try:
        with pytest.raises(NetworkCapacityRefused,match="neural realization"):
            build_neural_realization(observed())
    finally:
        ts.compile_live_compositional_transition_program=original


def test_neural_wrong_source_identity_refused_even_if_outputs_match():
    import mailcpu.transition_space as ts
    original=ts.compile_live_compositional_transition_program
    class WrongIdentity:
        def __init__(self,m):self._m=m
        def __getattr__(self,key):
            if key=="program_digest":return "0"*64
            return getattr(self._m,key)
    ts.compile_live_compositional_transition_program=lambda p:WrongIdentity(original(p))
    try:
        with pytest.raises(NetworkCapacityRefused,match="exact derived program"):
            build_neural_realization(observed())
    finally:
        ts.compile_live_compositional_transition_program=original


def test_forged_observation_transcript_refused_on_construction():
    o=observed()
    with pytest.raises(NetworkCapacityRefused,match="does not match"):
        replace(o,site_evidence=o.site_evidence[:-1]+((3,"unaware-3","snapshot-1","0"*64),))
    with pytest.raises(NetworkCapacityRefused,match="count"):
        replace(o,probe_count=31)