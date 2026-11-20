"""NCB-005: reproduce minimal generated admission counterexamples and repairs.

Actual source Ground is built by the separate pinned NCP-002 producer.
E-CPU independently rechecks it and must refuse rehashed typed aliases before
an operator call. The program prints measured evidence, not an authority grant.
"""
from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
import sys
from time import perf_counter_ns

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"tests"))

from generated_counterexample_probe import (  # noqa: E402
    canonical,generate_and_reduce_alias,report_minimal_source_alias,
    discover_native_input_alias,
)
from generated_controller_conformance import run_conformance  # noqa: E402
from test_constructed_controller_admission import (  # noqa: E402
    _world,_native,_bindings,_resources,
)
from mailcpu import ComputationalExecutionAdmissionCoordinator  # noqa: E402
from mailcpu.constructed_controller_admission import (  # noqa: E402
    CoupledControllerAdmissionError,execute_constructed_action,
    verify_coupled_controller,
)


def run() -> dict:
    """Capture actual denial behavior alongside existing generated conformance."""
    started=perf_counter_ns()
    base,edits,bad=generate_and_reduce_alias()
    if len(edits)!=1:
        raise AssertionError("minimal source discrepancy was not produced")
    checked=verify_coupled_controller(base)
    try:
        verify_coupled_controller(bad)
    except CoupledControllerAdmissionError as exc:
        source_denial=str(exc)
    else:
        raise AssertionError("rehashed invalid type-alias certificate was admitted")
    source_record=report_minimal_source_alias()
    source_record["receiver_denied"]=True
    source_record["refusal_reason"]=source_denial
    world=_world()
    if checked.packet_digest!=world.digest:
        raise AssertionError("receiver did not qualify actual producer Ground")
    chosen=verify_coupled_controller(world.packet())
    state,factor,_=discover_native_input_alias(chosen)
    denials=[]
    for field,alias in (
        ("factor_index",True),("source_state",True),
        ("factor_index",1.0),("source_state",1.0),
    ):
        os,identity,ground,catalogue,runtimes,calls=_native(world.packet())
        native=ComputationalExecutionAdmissionCoordinator(os)
        all_bindings=list(_bindings(chosen,state,identity,ground,runtimes))
        idx=next(i for i,b in enumerate(all_bindings) if b.factor==factor)
        original=all_bindings[idx]
        payload=dict(original.address.workload.input_value)
        if type(payload[field]) is not int or payload[field]!=1:
            raise AssertionError("invalid source for native typed alias")
        payload[field]=alias
        changed_workload=replace(original.address.workload,input_value=payload)
        all_bindings[idx]=replace(original,address=replace(
            original.address,workload=changed_workload,
        ))
        try:
            execute_constructed_action(
                chosen,state,tuple(all_bindings),catalogue,native,
                resources=_resources(chosen),
                source=f"ncb005-research-{field}-{type(alias).__name__}",
            )
        except CoupledControllerAdmissionError as exc:
            explanation=str(exc)
        else:
            raise AssertionError("native input type alias was wrongly accepted")
        if calls or "runtime workload input" not in explanation:
            raise AssertionError("native operation was reached despite bad binding")
        denials.append({
            "field":field,"replacement_type":type(alias).__name__,
            "value":alias,"rejected_before_handler":True,
            "reason":explanation,
        })
    for form in (True,1.0):
        ambiguous=list(state)
        ambiguous[factor]=form
        try:
            chosen.next_action(tuple(ambiguous))
        except CoupledControllerAdmissionError:
            pass
        else:
            raise AssertionError("observer coordinate aliased an integer state")
    os,identity,ground,catalogue,runtimes,calls=_native(world.packet())
    normal=execute_constructed_action(
        chosen,state,_bindings(chosen,state,identity,ground,runtimes),
        catalogue,ComputationalExecutionAdmissionCoordinator(os),
        resources=_resources(chosen),source="ncb005-valid-native-control",
    )
    if normal.status!="verified_native_pure_step" or not calls:
        raise AssertionError("repair incorrectly disabled legitimate native execution")
    original_benchmark=run_conformance(max_instances=2)
    if (original_benchmark["generated_instances"]!=4
            or original_benchmark["generated_cases"]<20
            or not original_benchmark["unsupported_receiver_capacity_refused"]):
        raise AssertionError("original generated development coverage regressed")
    report={
        "schema":"mailcpu.ncb005.development-repair-evidence.v1",
        "original_parent_sha":"80ee5fc70fe97dac670fc57e84c903f85f3ae320",
        "independent_producer_sha":"e607fd80c00630f6b31e4c86b9b5ee8faebda410",
        "pre_repair_ci_run":"https://github.com/Kier73/E-CPU/actions/runs/44824034666",
        "minimal_certificate_counterexample":source_record,
        "native_input_alias_denials":denials,
        "runtime_observer_alias_denials":2,
        "positive_native_step_receipt":normal.digest,
        "existing_generated_instances":original_benchmark["generated_instances"],
        "existing_generated_cases":original_benchmark["generated_cases"],
        "native_handlers_called_on_invalid_inputs":0,
        "total_elapsed_ns":perf_counter_ns()-started,
        "scope":"exact finite JSON representations, native local pure actions; no external effects",
    }
    report["sha256"]=sha256(canonical(report)).hexdigest()
    return report


def main()->None:
    """Print evidence and optionally retain JSON for CI artifact comparison."""
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument("--output",type=Path)
    args=parser.parse_args()
    report=run()
    body=json.dumps(report,sort_keys=True,indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(body+"\n",encoding="utf8")
    print(body)


if __name__=="__main__":
    main()
