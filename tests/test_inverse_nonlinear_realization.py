"""ITR-002: actual CIG-017 source proofs versus E-CPU SAB/INTENT host realization."""
from __future__ import annotations

from dataclasses import replace
import copy
import json

import pytest

from mailcpu.inverse_nonlinear_realization import (
    NonlinearIntention, SourceObservation, NonlinearCapacity, ReceiverProofMemory,
    NonlinearRealizationRefused, compare_realizations, direct_realize,
    formed_realize, qualify_observation,
)
from mailcpu.substrate_bootstrap import (
    BootstrapPolicy, BootstrapRefused, CarrierBinding, ChannelObservation,
    OperationOffer, ResourceObservation, SubstrateObservation, digest,
    verify_bootstrap_report,
)


def gate_source():
    """Original source states x3=x1&x2; x5=x3|x4; no algorithm in intention."""
    return NonlinearIntention(
        5,
        ((-1,-2,3),(1,-3),(2,-3),(-3,-4,5),(3,-5),(4,-5)),
        ((1,),(2,),(4,)), (5,),
    )


def state_for(a, b, c):
    x3 = a & b
    x5 = x3 | c
    return SourceObservation(a | (b << 1) | (x3 << 2) | (c << 3) | (x5 << 4))


def capacity(*, alpha=True, beta=True, shadow=False, approved=("alpha","beta")):
    resources = [ResourceObservation("input", "observation-locus", 1, 30,
                                     "resource-observer", digest({"host":"input"}), ()),
                 ResourceObservation("witness", "observation-locus", 1, 30,
                                     "resource-observer", digest({"host":"witness"}),
                                     (OperationOffer("proof.observe.boolean.v1", "proof.state.v1", "proof.observed.v1", 1),
                                      OperationOffer("form.observe.v1", "form.state.v1", "form.observed.v1", 1)))]
    channels=[]
    for host, allowed, price in (("alpha",alpha,1),("beta",beta,5),("shadow",shadow,1)):
        if not allowed: continue
        resources.append(ResourceObservation(host,"observation-locus",1,30,
                           "resource-observer",digest({"host":host}),(
                             OperationOffer("proof.decode.boolean.v1", "proof.code.v1", "proof.state.v1", price),
                             OperationOffer("form.execute.compact.v1", "form.request.v1", "form.state.v1", price),
                             OperationOffer("form.execute.general.v1", "form.request.v1", "form.state.v1", price))))
        for op in ("proof.code.v1","proof.state.v1","form.request.v1","form.state.v1"):
            src,dst = ("input",host) if op in ("proof.code.v1","form.request.v1") else (host,"witness")
            channels.append(ChannelObservation(f"{host}-{op.replace('.','-')}",src,dst,
                                               (op,),1,1,30,digest({"channel":[host,op]}),8192))
    inventory=SubstrateObservation(tuple(resources),tuple(channels))
    policy=BootstrapPolicy(frozenset(
        {(host,op) for host in approved for op in
         ("proof.decode.boolean.v1","form.execute.compact.v1","form.execute.general.v1")}
        | {("witness","proof.observe.boolean.v1"),("witness","form.observe.v1")}),
        frozenset(c.channel_id for c in channels),"receiver-owned-nonlinear-admission")
    carriers=tuple(CarrierBinding(c.channel_id,lambda raw,t: raw,
                                  digest({"carrier":c.channel_id})) for c in channels)
    return NonlinearCapacity(inventory,policy,carriers,tuple(approved),
                             ("witness",),"input","witness",5)


def source_chain(k):
    """Produce a typed CNF fixture; the compiler is passed only clauses and predicates."""
    assert k >= 3
    cnf=[]
    for i in range(1,k):
        a=1 if i==1 else k+i-1
        b=i+1
        out=k+i
        if i%2:
            cnf.extend([(-a,-b,out),(a,-out),(b,-out)])
        else:
            cnf.extend([(a,b,-out),(-a,out),(-b,out)])
    return NonlinearIntention(2*k-1,tuple(cnf),tuple((i,) for i in range(1,k+1)),(2*k-1,))


def source_chain_model(k,mask):
    bits=[(mask>>i)&1 for i in range(k)]
    full=mask
    prev=bits[0]
    for i in range(1,k):
        prev=(prev&bits[i]) if i%2 else (prev|bits[i])
        full |= prev << (k+i-1)
    return SourceObservation(full)


def test_actual_cig_circuit_decoder_and_independent_formed_processor():
    goal=gate_source();obs=state_for(1,1,0); memory=ReceiverProofMemory()
    direct=direct_realize(goal,obs,capacity(),memory)
    formed,native=formed_realize(goal,obs,capacity())
    assert compare_realizations(direct,formed)["result"]==1
    assert direct.proof_constructed and len(memory)==1
    assert direct.source_probes==formed.source_probes==0
    assert direct.proof_digest and formed.machine_digest
    assert direct.path_digest!=formed.path_digest
    assert any(step.locus=="alpha" for step in native.plan.steps)
    assert native.machine.register_bits==1
    assert verify_bootstrap_report(native.report,native.task,native.plan)
    assert direct.total_ns>0 and formed.total_ns>0
    assert set(direct.spans_ns)=={
        "proof_acquire_and_admit","source_observation_qualification",
        "host_route_discovery","native_execution_and_check","result_audit"}


def test_warm_proof_memory_never_recomputes_or_mutates_proof():
    goal=gate_source();mem=ReceiverProofMemory()
    cold=direct_realize(goal,state_for(1,0,0),capacity(),mem)
    warm=direct_realize(goal,state_for(0,0,1),capacity(),mem)
    assert cold.proof_constructed and not warm.proof_constructed
    assert cold.result==0 and warm.result==1
    assert cold.proof_digest==warm.proof_digest
    proof,created=mem.get_or_construct(goal)
    assert not created
    proof["decoder"]["gates"][0]["table"][0]^=1
    proof2,created=mem.get_or_construct(goal)
    assert not created and proof2!=proof


def test_changed_source_invalidates_proof_identity():
    goal=gate_source();mem=ReceiverProofMemory()
    original=direct_realize(goal,state_for(0,1,0),capacity(),mem)
    changed=NonlinearIntention(5,goal.source+((-5,),),goal.observations,goal.target)
    with pytest.raises(NonlinearRealizationRefused):
        direct_realize(changed,state_for(1,1,0),capacity(),mem)
    assert original.intention_digest!=changed.fingerprint
    assert len(mem)==2  # newly checked source proof, but changed witness refused


def test_wrong_original_source_state_is_refused_before_host():
    goal=gate_source();mem=ReceiverProofMemory()
    with pytest.raises(NonlinearRealizationRefused, match="contradicts"):
        direct_realize(goal,SourceObservation(0b00101),capacity(),mem)
    with pytest.raises(NonlinearRealizationRefused):
        qualify_observation(goal,SourceObservation(1<<6))
    with pytest.raises(NonlinearRealizationRefused):
        SourceObservation(-1)


def test_host_loss_reselects_fabric_without_changing_decoder_identity():
    goal=gate_source();obs=state_for(1,1,1);mem=ReceiverProofMemory()
    a=direct_realize(goal,obs,capacity(),mem)
    b=direct_realize(goal,obs,capacity(alpha=False),mem)
    assert a.result==b.result==1
    assert a.proof_digest==b.proof_digest
    assert a.path_digest!=b.path_digest
    assert not b.proof_constructed
    fa,na=formed_realize(goal,obs,capacity())
    fb,nb=formed_realize(goal,obs,capacity(alpha=False))
    assert fa.result==fb.result
    assert fa.machine_digest==fb.machine_digest
    assert fa.path_digest!=fb.path_digest
    assert any(step.locus=="beta" for step in nb.plan.steps)


def test_inert_capability_advertisement_never_grants_execution():
    goal=gate_source();obs=state_for(0,0,1)
    # A lower-cost advertised but unapproved executor is not a callable permission.
    good=direct_realize(goal,obs,capacity(shadow=True),ReceiverProofMemory())
    assert good.result==1
    bad=capacity(alpha=False,beta=False,shadow=True)
    with pytest.raises(BootstrapRefused):
        direct_realize(goal,obs,bad,ReceiverProofMemory())


def test_insufficient_observation_returns_checked_counterexample():
    goal=NonlinearIntention(3,(),((1,2),),(1,))
    mem=ReceiverProofMemory()
    proof,created=mem.get_or_construct(goal)
    assert created and proof["status"]=="INSUFFICIENT"
    assert len(proof["witness"])==2
    with pytest.raises(NonlinearRealizationRefused,match="insufficient"):
        direct_realize(goal,SourceObservation(1),capacity(),mem)
    with pytest.raises(NonlinearRealizationRefused,match="insufficient"):
        formed_realize(goal,SourceObservation(1),capacity())


def test_budget_unknown_is_never_promoted_to_source_proof():
    goal=NonlinearIntention(4,(),((1,2),(-3,4)),(1,2,-3,4))
    mem=ReceiverProofMemory()
    with pytest.raises(NonlinearRealizationRefused,match="UNKNOWN"):
        mem.get_or_construct(goal,mode="paired",width=1)
    assert len(mem)==0


def test_large_nonlinear_source_direct_while_full_enumeration_refuses():
    goal=source_chain(12)
    observed=source_chain_model(12,0xB63)
    mem=ReceiverProofMemory()
    direct=direct_realize(goal,observed,capacity(),mem)
    assert direct.mode=="source-qualified-direct-decoder"
    proof,_=mem.get_or_construct(goal)
    assert proof["route"]=="circuit"
    assert direct.proof_constructed
    with pytest.raises(NonlinearRealizationRefused,match="enumeration budget"):
        formed_realize(goal,observed,capacity())


def test_all_small_nonlinear_inputs_agree_without_handpicked_target():
    goal=gate_source();mem=ReceiverProofMemory()
    for a in (0,1):
        for b in (0,1):
            for c in (0,1):
                observed=state_for(a,b,c)
                direct=direct_realize(goal,observed,capacity(),mem)
                formed,_=formed_realize(goal,observed,capacity())
                assert compare_realizations(direct,formed)["result"]==((a&b)|c)
    assert len(mem)==1


def test_cross_intention_comparison_cannot_reuse_changed_target():
    a=gate_source();b=NonlinearIntention(a.variables,a.source,a.observations,(-5,))
    obs=state_for(1,1,0)
    da=direct_realize(a,obs,capacity(),ReceiverProofMemory())
    fb,_=formed_realize(b,obs,capacity())
    with pytest.raises(NonlinearRealizationRefused):
        compare_realizations(da,fb)


def test_receipt_phase_costs_and_content_bound_identity():
    goal=gate_source();obs=state_for(1,1,1)
    a=direct_realize(goal,obs,capacity(),ReceiverProofMemory())
    b=formed_realize(goal,obs,capacity())[0]
    report=compare_realizations(a,b)
    assert report["direct_ns"]==sum(report["direct_spans_ns"].values())
    assert report["formed_ns"]==sum(report["formed_spans_ns"].values())
    assert report["direct_proof_digest"]==a.proof_digest
    assert report["formed_machine_digest"]==b.machine_digest
    assert json.loads(json.dumps(report))==report
