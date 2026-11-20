"""NCB-006: run actual concurrent/native, topology and crash tests as a benchmark.

The source is the pinned NCP-002 producer, not a mock action table. Each
measurement is a single real test pass with newly provisioned E-CPU/SQLite
receivers. The report is not signed and does not attest an external actuator.
"""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from time import perf_counter_ns

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"tests"))

from test_constructed_resource_contention import (  # noqa: E402
    _worlds,_minimal_source_generated_contention,
    test_source_generated_two_controller_schedule_obeys_receiver_capacity,
    test_topology_change_after_durable_reservation_refuses_and_releases,
    test_local_resource_policy_is_pinned_and_untrusted_packet_cannot_expand_it,
    test_separate_os_process_occupancy_blocks_then_recovers_after_release,
    test_hard_process_death_keeps_capacity_fenced_without_time_reclaim,
    test_failed_pure_handler_refuses_and_releases_its_claim,
)


def run()->dict:
    """Demand actual receiver-side conflict-free execution before reporting."""
    start=perf_counter_ns()
    first,second,_,_=_worlds()
    _,units=_minimal_source_generated_contention(first,second)
    if units!=[1,1]:
        raise AssertionError("source-selected minimal contention schedule changed")
    checks=(
        ("concurrent_two_controller_native_occupancy",
         test_source_generated_two_controller_schedule_obeys_receiver_capacity),
        ("host_loss_after_reservation_and_reprovision",
         test_topology_change_after_durable_reservation_refuses_and_releases),
        ("independent_receiver_resource_policy",
         test_local_resource_policy_is_pinned_and_untrusted_packet_cannot_expand_it),
        ("independent_process_live_claim_and_release",
         test_separate_os_process_occupancy_blocks_then_recovers_after_release),
        ("hard_crash_persists_fail_closed_claim",
         test_hard_process_death_keeps_capacity_fenced_without_time_reclaim),
        ("semantic_refusal_releases_pure_claim",
         test_failed_pure_handler_refuses_and_releases_its_claim),
    )
    records=[]
    for name,test in checks:
        with TemporaryDirectory() as temp:
            began=perf_counter_ns()
            test(Path(temp))
            elapsed=perf_counter_ns()-began
        records.append({
            "case":name,
            "verified":True,
            "elapsed_ns":elapsed,
        })
    result={
        "schema":"mailcpu.ncb006.contended-native-receiver-evidence.v1",
        "source_controller_digests":[first.packet_digest,second.packet_digest],
        "source_mathematical_capacity":first.resources[0][1],
        "source_generated_individual_claim_units":units,
        "source_generated_total_claim_units":sum(units),
        "minimal_conflict_claim_count":2,
        "verified_native_scenarios":len(checks),
        "scenarios":records,
        "crash_reclamation":False,
        "native_operation_kind":"receiver-registered pure E-CPU VirtualLayerRuntime",
        "old_static_admission_red_ci":"https://github.com/Kier73/E-CPU/actions/runs/44828590800",
        "measurements":"single-run wall time on each CI worker; no external actuator or network claims",
        "total_elapsed_ns":perf_counter_ns()-start,
    }
    raw=json.dumps(result,sort_keys=True,separators=(",",":"),
                   ensure_ascii=True).encode("ascii")
    result["sha256"]=sha256(raw).hexdigest()
    return result


def main()->None:
    """Emit readable evidence and save portable JSON for matrix artifacts."""
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument("--output",type=Path)
    args=parser.parse_args()
    result=run()
    body=json.dumps(result,sort_keys=True,indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(body+"\n",encoding="utf8")
    print(body)


if __name__=="__main__":
    main()
