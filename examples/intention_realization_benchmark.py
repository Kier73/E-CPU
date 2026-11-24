"""Native ITR-001 benchmark over ONP-001's existing controlled source fixture.

Run from the E-CPU root: python examples/intention_realization_benchmark.py --trials 3
Inputs are desired outputs and admitted capability descriptions, not programs
or a choice of host. Measurements are local process intervals; warm reuse
requires a prior independently qualified source result. Does not download models.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
from test_observation_formed_processor import (
    request, offers, palette, policy, sensors, KEY, _observed_host_inventory,
)
from mailcpu.intention_realization_latency import (
    ReceiverCapacity, cold_realize, warm_realize, summarize_campaign,
)


def capacity(alpha=True):
    inv, fabric_policy, carriers = _observed_host_inventory(
        include_alpha=alpha, include_beta=True)
    return ReceiverCapacity(
        offers(), palette(), policy(), {"signed-local-source":KEY},
        inv, fabric_policy, carriers, ("alpha", "beta"), ("witness",),
        "input", "witness", 5,
    )


def cold(goal):
    sensor, log = sensors()
    counter = iter(range(1, 100))
    result, observed, formed = cold_realize(
        goal, capacity(), sensor, now=10,
        nonce_factory=lambda: f"{next(counter):032x}",
    )
    if log != [0, 1, 2]:
        raise AssertionError("Qualified cold source experiment probed unexpected coordinates")
    return result, observed, formed


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--trials",type=int,default=5)
    args=p.parse_args()
    if not 1<=args.trials<=30:raise SystemExit("trials must be in 1..30")
    seed, source, _ = cold(request(query=9))
    cold_records=[];warm_records=[]
    for _ in range(args.trials):
        c,_,_ = cold(request(query=7))
        w,_ = warm_realize(source,request(query=7),capacity(),now=10)
        cold_records.append(c);warm_records.append(w)
    comparison=summarize_campaign(seed,cold_records,warm_records)
    # Host loss triggers path formation without source reobservation.
    primary,pa=warm_realize(source,request(query=7),capacity(),now=10)
    replacement,pb=warm_realize(source,request(query=7),capacity(alpha=False),now=10)
    if (primary.machine_digest!=replacement.machine_digest or
        primary.output!=replacement.output or primary.route_digest==replacement.route_digest):
        raise AssertionError("Host rehome violated semantic identity or failed to change route")
    comparison["host_replacement"]={
        "unchanged_machine_digest":primary.machine_digest,
        "old_path_digest":primary.route_digest,
        "replacement_path_digest":replacement.route_digest,
        "old_total_ns":primary.total_ns,
        "replacement_total_ns":replacement.total_ns,
        "new_source_probes":0,
    }
    comparison["source_seed_goal"]="f(9)"
    comparison["same_compared_goal"]="f(7)"
    comparison["source_coefficients_supplied_to_constructor"]=False
    comparison["program_or_processor_supplied_to_constructor"]=False
    print(json.dumps(comparison,indent=2,sort_keys=True))


if __name__=="__main__":main()
