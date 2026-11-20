"""NCB-004: use constructed processor spaces to generate E-CPU regression tests.

This is a DEVELOPMENT benchmark, not a synthetic claim of performance gain.
Actual Navigable-Compute NCP-002 selects complete controller implementations;
their enabled states/actions become test cases for E-CPU's existing native
ComputerHost resolver, Hypervisor and independent Ground interpreter.

The separate fixed tiny arithmetic oracle is only a sanity baseline for this
precisely declared advance/hold test vocabulary, not a general theorem.
"""
from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
from time import perf_counter_ns
from typing import Any

from navigable_compute.coupled import CoupledBrief, SharedResource, construct_coupled, navigate_coupled
from navigable_compute.coupled_verify import verify_coupled

from mailcpu import ComputationalExecutionAdmissionCoordinator
from mailcpu.constructed_controller_admission import (
    CoupledControllerAdmissionError, NativeResourceBinding,
    execute_constructed_action,verify_coupled_controller,
)
from test_constructed_controller_admission import _world,_native,_bindings


def _canonical(document: dict[str,Any]) -> bytes:
    """Encode a reproducible untrusted JSON evidence report."""
    return json.dumps(document,sort_keys=True,separators=(",",":"),
                      ensure_ascii=True,allow_nan=False).encode()


def _independent_receiver_capacity() -> tuple[NativeResourceBinding,...]:
    """Receiver policy is configured independently of the producer's brief."""
    return (NativeResourceBinding(
        "shared-actuator",1,((0,"advance"),(1,"advance")),
    ),)


def _oracle(state: tuple[int,...], names: tuple[str|None,...]) -> tuple[int,...]:
    """A deliberately tiny independent direct-step reference for this fixture."""
    return tuple(
        state[i]-1 if name=="advance" else state[i]
        for i,name in enumerate(names)
    )


def run_conformance(*, max_instances: int=4) -> dict[str,Any]:
    """Generate source-driven tests, exercise native handlers and record costs.

    The mathematical producer chooses every controller and action in this
    experiment. The developer supplies only the target invariants and the
    independent receiver-registered operator semantics. Any mismatch is an
    actionable regression, not a successful observation.
    """
    if type(max_instances) is not int or not 1<=max_instances<=12:
        raise ValueError("max_instances must be a strict bounded test budget")
    suite_start=perf_counter_ns()
    base=_world()
    variants=(
        ("shared-capacity",base.source),
        ("joint-unsafe",replace(base.source,unsafe_joint=((1,1),))),
    )
    records=[]
    total_actions=0
    total_steps=0
    fingerprint_set=set()
    scenarios=0
    for name,description in variants:
        started=perf_counter_ns()
        constructed=construct_coupled(description)
        construction_ns=perf_counter_ns()-started
        started=perf_counter_ns()
        if not verify_coupled(description,constructed):
            raise AssertionError("producer independent verifier refused its construction")
        producer_verification_ns=perf_counter_ns()-started
        coordinates=tuple(dict.fromkeys((
            0,1,constructed.optimal_laws//2,constructed.optimal_laws-1,
        )))[:max_instances]
        if not coordinates or any(x<0 or x>=constructed.optimal_laws for x in coordinates):
            raise AssertionError("invalid generated processor instance coordinates")
        variant_cases=0
        for k in coordinates:
            if k==0:
                instance=constructed
            else:
                instance=navigate_coupled(constructed,k)
            if not verify_coupled(description,instance):
                raise AssertionError("selected processor is not source-qualified")
            packet=instance.packet()
            fingerprint_set.add(packet["sha256"])
            bytes_on_wire=len(_canonical(packet))
            started=perf_counter_ns()
            checked=verify_coupled_controller(packet)
            receiver_proof_ns=perf_counter_ns()-started
            if checked.packet_digest!=instance.digest:
                raise AssertionError("native proof did not bind selected instance")
            os,identity,ground,catalogue,runtimes,calls=_native(packet)
            coordinator=ComputationalExecutionAdmissionCoordinator(os)
            case_count=0
            result_ns=0
            baseline_ns=0
            observed_actions=[]
            # Exercise ALL winning nonterminal states in this small product,
            # not just the successful path from the original initial state.
            for index,state in enumerate(checked.states):
                if checked.ranks[index]<1:
                    continue
                selected=checked.next_action(state)
                bindings=_bindings(checked,state,identity,ground,runtimes)
                began=perf_counter_ns()
                expected=_oracle(state,selected.names)
                baseline_ns+=perf_counter_ns()-began
                if expected not in selected.allowed:
                    raise AssertionError("test oracle disagrees with constructor's possible relation")
                began=perf_counter_ns()
                observed=execute_constructed_action(
                    checked,state,bindings,catalogue,coordinator,
                    resources=_independent_receiver_capacity(),
                    source=f"ncb004-{name}-{k}",
                    sequence=1+case_count*16,
                )
                result_ns+=perf_counter_ns()-began
                if (observed.observed!=expected
                        or observed.observed not in selected.allowed
                        or observed.status!="verified_native_pure_step"):
                    raise AssertionError("native observation violates a generated conformance case")
                native_count=len(observed.native_receipts)
                if native_count!=len(bindings):
                    raise AssertionError("native execution receipts do not match selected operations")
                total_actions+=native_count
                observed_actions.extend(selected.names)
                case_count+=1
                total_steps+=1
            if len(calls)!=sum(
                len(tuple(name for name in checked.next_action(state).names if name is not None))
                for i,state in enumerate(checked.states) if checked.ranks[i]>0
            ):
                raise AssertionError("native handler call count disagrees with verified receipt count")
            if not case_count or result_ns<=0 or bytes_on_wire<=0:
                raise AssertionError("generated suite was vacuous")
            records.append({
                "source_case":name,
                "instance_coordinate_decimal":str(k),
                "controller_sha256":instance.digest,
                "source_sha256":checked.source_digest,
                "policy_count_decimal":str(instance.optimal_laws),
                "source_state_count":len(checked.states),
                "source_winning_states_tested":case_count,
                "native_handler_invocations":len(calls),
                "unique_selected_actions":sorted({
                    x for x in observed_actions if x is not None
                }),
                "packet_bytes":bytes_on_wire,
                "construction_ns":construction_ns,
                "producer_verification_ns":producer_verification_ns,
                "receiver_verification_ns":receiver_proof_ns,
                "direct_reference_steps_ns":baseline_ns,
                "native_verified_steps_ns":result_ns,
                "source_ground_verified":True,
                "native_receiver_verified":True,
            })
            scenarios+=1
            variant_cases+=case_count
        if variant_cases==0:
            raise AssertionError("generated coupled case produced no covered states")

    # Demonstrate that actual capacity is NOT granted by source invention.
    larger=replace(base.source,resources=(
        SharedResource("shared-actuator",2,((0,"advance"),(1,"advance"))),
    ))
    admissible=construct_coupled(larger)
    changed=verify_coupled_controller(admissible.packet())
    os,identity,ground,catalogue,runtimes,calls=_native(admissible.packet())
    from mailcpu.constructed_controller_admission import execute_constructed_action
    rejected_capacity=False
    try:
        execute_constructed_action(
            changed,(2,2),_bindings(changed,(2,2),identity,ground,runtimes),
            catalogue,ComputationalExecutionAdmissionCoordinator(os),
            resources=_independent_receiver_capacity(),
        )
    except CoupledControllerAdmissionError as exc:
        rejected_capacity="receiver has not qualified" in str(exc)
    if not rejected_capacity or calls:
        raise AssertionError("mathematically valid but receiver-unsupported capacity was not refused")

    report={
        "schema":"mailcpu.ncb004.generated-development-conformance.v1",
        "purpose":"source-constructed controller variants generate actual native E-CPU regression cases",
        "source_repository":"Kier73/Navigable-Compute",
        "source_commit":"e607fd80c00630f6b31e4c86b9b5ee8faebda410",
        "benchmarked_system":"Kier73/E-CPU native NCB-003",
        "generated_cases":total_steps,
        "generated_instances":scenarios,
        "distinct_instance_digests":len(fingerprint_set),
        "native_handler_invocations":total_actions,
        "unsupported_receiver_capacity_refused":True,
        "runs":[*records],
        "total_suite_elapsed_ns":perf_counter_ns()-suite_start,
        "claims":{
            "source":"mathematical constructed possibilities; explicit finite assumption",
            "receiver":"native local registered pure operators and Hypervisor; no external effects",
            "performance":"report wall clock overhead and direct oracle baseline; no speedup or independent hardware claimed",
        },
    }
    report["sha256"]=sha256(_canonical(report)).hexdigest()
    return report


def main() -> None:
    """Emit benchmark evidence on the actual current E-CPU code in this checkout."""
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument("--output",type=Path)
    parser.add_argument("--max-instances",type=int,default=4)
    args=parser.parse_args()
    record=run_conformance(max_instances=args.max_instances)
    value=json.dumps(record,sort_keys=True,indent=2)
    if args.output is not None:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(value+"\n",encoding="utf8")
    print(value)


if __name__=="__main__":
    main()
