"""NCB-003 cross-repo: original NCP-002 packet -> native E-CPU host authority.

The producer package is pinned in the dedicated eight-platform CI; these
tests skip when the separate public repository is not checked out. E-CPU's
independent verifier does NOT import the producer implementation.
"""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
import pytest

pytest.importorskip("navigable_compute.coupled",
                    reason="NCB-003 CI checks out the exact NCP-002 producer")
from navigable_compute.brief import ActionSketch, EffectCase, GroundBrief
from navigable_compute.coupled import (
    CoupledBrief,SharedResource,construct_coupled,navigate_coupled,
)
from navigable_compute.coupled_verify import verify_coupled
from mailcpu import (
    Capability,ComputationalAddress,ComputationalExecutionAdmissionCoordinator,
    ComputationalHostCatalogue,ComputationalHostLocus,HeadlessOS,
    OperatorRegistry,OperatorSpec,RouteMetric,RouteMetricKey,SystemIdentity,
    SystemSeed,SystemSeedEnvelope,VirtualBudget,VirtualGroundRef,
    VirtualLayerRuntime,VirtualLayerWorkload,VirtualOperatorRef,
)
from mailcpu.constructed_controller_admission import (
    CoupledControllerAdmissionError,NativeActionBinding,NativeResourceBinding,
    execute_constructed_action,verify_coupled_controller,
)
from mailcpu.semantic_translation import canonical_value_digest

METRICS=tuple(RouteMetricKey(name,unit) for name,unit in (
    ("latency","ticks"),("energy","units"),("bytes","bytes"),("risk","score"),
))


def _world():
    """Construct, do not manually fake, the peer's actual coupled Ground."""
    brief=GroundBrief(3,(2,),(0,),(),(
        ActionSketch("advance",(EffectCase(1,3,deltas=(-1,)),)),
        ActionSketch("hold",(EffectCase(0,3,deltas=(0,)),)),
    ))
    source=CoupledBrief((brief,brief),(
        SharedResource("shared-actuator",1,((0,"advance"),(1,"advance"))),
    ))
    candidate=construct_coupled(source)
    assert verify_coupled(source,candidate)
    return candidate


def _sha(value):
    """Rehash even malicious source edits to challenge the numerical checker."""
    return sha256(json.dumps(value,sort_keys=True,separators=(",",":"),
                             ensure_ascii=True).encode()).hexdigest()


def _resources(checked):
    """Independent receiver-owned description of the admitted resource palette."""
    return tuple(NativeResourceBinding(name,capacity,claims)
                 for name,capacity,claims in checked.resources)


def _native(packet, *, capability=True, incorrect=False):
    """Set up two independently registered native logical E-CPU operator hosts."""
    os=HeadlessOS()
    identity=SystemIdentity("ncb003-native-system",1)
    envelope=SystemSeedEnvelope(
        identity,"constructed-controller-source","ncb003",
        SystemSeed.from_system(os),
    )
    assert os.seed_admission.admit(envelope).accepted
    ground=VirtualGroundRef.from_envelope(envelope)
    catalogue=ComputationalHostCatalogue()
    runtimes={}
    calls=[]
    for factor in range(2):
        registry=OperatorRegistry()
        for operation in ("advance","hold"):
            spec=OperatorSpec(
                operator_id=f"ncb003.{operation}",version=1,
                description="Receiver-registered bounded pure transition",
                input_kind="object",output_kind="integer",
                substrates=("cpu",),required_rights=frozenset({"compute"}),
                base_energy=4,energy_per_byte=1,max_input_bytes=4096,
                max_output_bytes=64,deterministic=True,effect_mode="pure",
            )
            def make_handler(f=factor,a=operation):
                def handle(argument,workload):
                    calls.append((f,a,argument["source_state"]))
                    return (99 if incorrect else
                            argument["source_state"]-1 if a=="advance" else
                            argument["source_state"])
                return handle
            registry.register(spec,make_handler())
        runtime=VirtualLayerRuntime(
            registry,f"ncb003-node-{factor}",frozenset({"cpu"}),
        )
        pid=os.environment.kernel.spawn(
            f"ncb003-worker-{factor}",
            capabilities=(
                (Capability("/virtual-layer/operators",frozenset({"compute"})),)
                if capability else
                (Capability("/unrelated",frozenset({"read"})),)
            ),
            parent_pid=os.environment.init_pid,
        )
        for operation in ("advance","hold"):
            catalogue.register(ComputationalHostLocus.from_runtime(
                host_id=f"ncb003-host-{factor}",runtime=runtime,
                authority_pid=pid,operator_id=f"ncb003.{operation}",
                computational_ground_fingerprints=(packet["sha256"],),
                program_fingerprints=(packet["sha256"],),
                costs=(
                    RouteMetric("latency","ticks",3+factor),
                    RouteMetric("energy","units",16),
                    RouteMetric("bytes","bytes",256),
                    RouteMetric("risk","score",0),
                ),
                implementation_fingerprint=canonical_value_digest({
                    "handler":"ncb003.bound-operation.v1","factor":factor,
                    "operation":operation,
                }),
            ))
        runtimes[factor]=runtime
    return os,identity,ground,catalogue,runtimes,calls


def _bindings(controller,state,identity,ground,runtimes):
    """Bind each elected operation to a receiver-owned native operator address."""
    selected=controller.next_action(state)
    result=[]
    for factor,operation in enumerate(selected.names):
        if operation is None:
            continue
        spec,_=runtimes[factor].registry.resolve(f"ncb003.{operation}",1)
        workload=VirtualLayerWorkload(
            workload_id=(f"ncb003-{controller.packet_digest[:12]}-"
                         f"{'-'.join(str(x) for x in state)}-{factor}"),
            system=identity,ground=ground,
            intention={"goal":{"controller_digest":controller.packet_digest,
                               "action_digest":selected.digest}},
            operators=(VirtualOperatorRef(f"ncb003.{operation}",1,"cpu"),),
            input_value={
                "controller_digest":controller.packet_digest,
                "action_digest":selected.digest,
                "factor_index":factor,"source_state":state[factor],
                "action_name":operation,
            },
            budget=VirtualBudget(100000,100000,1000),
            logical_time=10+sum(state)*10+factor,
            eligible_nodes=(f"ncb003-node-{factor}",),max_hops=1,
        )
        address=ComputationalAddress.from_workload(
            workload,f"ncb003.{operation}",spec,controller.packet_digest,
            program_fingerprint=controller.packet_digest,metric_order=METRICS,
        )
        result.append(NativeActionBinding(
            factor,operation,f"ncb003-host-{factor}",address,runtimes[factor],
        ))
    return tuple(result)


def test_real_ncp_source_is_independently_checked() -> None:
    world=_world()
    verified=verify_coupled_controller(world.packet())
    assert verified.packet_digest==world.digest
    assert verified.convergence_bound==4
    assert verified.next_action((2,2)).rank==4
    alternate=navigate_coupled(world,1)
    different=verify_coupled_controller(alternate.packet())
    assert different.packet_digest!=verified.packet_digest
    assert different.policy!=verified.policy


def test_complete_constructed_machine_executes_through_native_hypervisor() -> None:
    world=_world()
    checked=verify_coupled_controller(world.packet())
    os,identity,ground,catalogue,runtimes,calls=_native(world.packet())
    coordinator=ComputationalExecutionAdmissionCoordinator(os)
    state=(2,2)
    receipts=[]
    for tick in range(4):
        bindings=_bindings(checked,state,identity,ground,runtimes)
        result=execute_constructed_action(
            checked,state,bindings,catalogue,coordinator,
            resources=_resources(checked),sequence=1+tick*16,
        )
        assert result.status=="verified_native_pure_step"
        assert result.observed in checked.next_action(state).allowed
        assert len(result.native_receipts)==len(bindings)
        assert all(r["status"]=="executed" for r in result.native_receipts)
        assert result.digest==_sha({k:v for k,v in result.to_dict().items()
                                    if k!="digest"})
        receipts.append(result)
        state=result.observed
    assert state==(0,0)
    assert len(receipts)==4 and len(calls)>=4
    with pytest.raises(CoupledControllerAdmissionError,match="terminal"):
        checked.next_action(state)


def test_missing_or_stale_host_refused_before_any_native_execution() -> None:
    world=_world()
    checked=verify_coupled_controller(world.packet())
    os,identity,ground,catalogue,runtimes,calls=_native(world.packet())
    bindings=_bindings(checked,(2,2),identity,ground,runtimes)
    coordinator=ComputationalExecutionAdmissionCoordinator(os)
    with pytest.raises(CoupledControllerAdmissionError,match="missing or extra"):
        execute_constructed_action(
            checked,(2,2),bindings[:-1],catalogue,coordinator,
            resources=_resources(checked),
        )
    assert not calls
    catalogue.remove(bindings[-1].host_id,bindings[-1].address.operator_id)
    with pytest.raises(CoupledControllerAdmissionError,match="native host capability"):
        execute_constructed_action(
            checked,(2,2),bindings,catalogue,coordinator,
            resources=_resources(checked),
        )
    assert not calls


def test_missing_compute_right_and_wrong_native_result_both_refused() -> None:
    world=_world()
    checked=verify_coupled_controller(world.packet())
    os,identity,ground,catalogue,runtimes,calls=_native(
        world.packet(),capability=False,
    )
    with pytest.raises(CoupledControllerAdmissionError,match="native host capability|Hypervisor"):
        execute_constructed_action(
            checked,(2,2),_bindings(checked,(2,2),identity,ground,runtimes),
            catalogue,ComputationalExecutionAdmissionCoordinator(os),
            resources=_resources(checked),
        )
    assert not calls
    os,identity,ground,catalogue,runtimes,calls=_native(
        world.packet(),incorrect=True,
    )
    with pytest.raises(CoupledControllerAdmissionError,match="violates declared Ground"):
        execute_constructed_action(
            checked,(2,2),_bindings(checked,(2,2),identity,ground,runtimes),
            catalogue,ComputationalExecutionAdmissionCoordinator(os),
            resources=_resources(checked),
        )
    assert calls


def test_rehashed_misrepresentation_is_not_a_certificate() -> None:
    base=_world().packet()
    alterations=[]
    a=deepcopy(base);a["source"]["resources"][0]["capacity"]=0
    alterations.append(a)
    a=deepcopy(base);a["rank"][a["states"].index([2,2])]=2
    alterations.append(a)
    a=deepcopy(base);a["policy"][a["states"].index([2,2])]=[0,0]
    alterations.append(a)
    a=deepcopy(base);a["instance_coordinate_decimal"]="1"
    alterations.append(a)
    a=deepcopy(base);a["source"]["factors"][0]["actions"][0]["cases"][0]["deltas"]=[-2]
    alterations.append(a)
    # Recomputed digests cannot make Python's bool==1 or 1.0==1 coercions
    # legal typed action/rank evidence.
    a=deepcopy(base);a["rank"][a["states"].index([1,0])]=True
    alterations.append(a)
    a=deepcopy(base);a["optimal"][a["states"].index([2,2])][0][0]=0.0
    alterations.append(a)
    for tampered in alterations:
        tampered["sha256"]=_sha({k:v for k,v in tampered.items() if k!="sha256"})
        with pytest.raises(CoupledControllerAdmissionError):
            verify_coupled_controller(tampered)
    with pytest.raises(CoupledControllerAdmissionError):
        verify_coupled_controller(base|{"external_authority":True})


def test_alternative_valid_controller_does_not_reuse_original_host_program_pin() -> None:
    world=_world()
    changed=navigate_coupled(world,1)
    alternate=verify_coupled_controller(changed.packet())
    os,identity,ground,catalogue,runtimes,calls=_native(world.packet())
    bindings=_bindings(alternate,(2,2),identity,ground,runtimes)
    with pytest.raises(CoupledControllerAdmissionError,match="native host capability"):
        execute_constructed_action(
            alternate,(2,2),bindings,catalogue,
            ComputationalExecutionAdmissionCoordinator(os),
            resources=_resources(alternate),
        )
    assert not calls


def test_receiver_declared_resource_policy_is_independent_of_mathematical_brief() -> None:
    """A constructed available action cannot invent receiver-owned capacity."""
    world=_world()
    checked=verify_coupled_controller(world.packet())
    os,identity,ground,catalogue,runtimes,calls=_native(world.packet())
    bindings=_bindings(checked,(2,2),identity,ground,runtimes)
    coordinator=ComputationalExecutionAdmissionCoordinator(os)
    for policy in (
        (),
        (NativeResourceBinding("shared-actuator",0,
                               ((0,"advance"),(1,"advance"))),),
        (NativeResourceBinding("shared-actuator",1,
                               ((0,"hold"),(1,"hold"))),),
    ):
        with pytest.raises(CoupledControllerAdmissionError,match="receiver.*resource"):
            execute_constructed_action(
                checked,(2,2),bindings,catalogue,coordinator,resources=policy,
            )
    assert calls==[]
