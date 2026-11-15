"""CAPACITY-002: reproducible finite in-transit network recognition demonstration."""
from __future__ import annotations
import json
import statistics
import time
from mailcpu.network_state_capacity import (
    UnawareSite, NetworkProbePolicy, recognize_network, build_neural_realization
)

INITIAL=(1,0,1,1,0,1,0,0)
TARGET=10**30+11


def reference_local(h, incoming):
    """This test-only unknown component pre-exists its observer's E-CPU description."""
    return h ^ incoming, h


def alternative_local(h,incoming):
    """Different local implementation with the same observed information relation."""
    return ((h + incoming) % 2, h)


def build_sites(prefix, operation):
    """Form the four explicitly permitted, individually probed observer loci."""
    return tuple(UnawareSite(i,f"{prefix}-{i}",f"{prefix}-snapshot",5,100,operation) for i in range(4))


def run(include_neural=True):
    """Measure finite local recognition, then reuse a Ground at a remote coordinate."""
    paths=[]
    timings=[]
    for prefix,operation in (("preexisting-a",reference_local),("preexisting-b",alternative_local)):
        sites=build_sites(prefix,operation)
        p=NetworkProbePolicy(frozenset(x.host_id for x in sites),"receiver-owned-observer",5)
        t0=time.perf_counter_ns()
        observation=recognize_network(sites,p)
        timings.append(time.perf_counter_ns()-t0)
        paths.append(observation)
    first,second=paths
    if first.ground.digest!=second.ground.digest or first.path_digest==second.path_digest:
        raise AssertionError("path semantic separation violated")
    t0=time.perf_counter_ns()
    receipt=first.navigate(INITIAL,TARGET)
    elapsed=time.perf_counter_ns()-t0
    if second.navigate(INITIAL,TARGET).result != receipt.result or not first.verify_navigation(receipt):
        raise AssertionError("independently reconstructed network failed exact check")
    report={
      "schema":"mailcpu.capacity-002-reference.v1",
      "scope":"finite software observer/network-state experiment",
      "sites":4, "global_state_bits":8, "global_state_count":256,
      "unique_local_rows_observed":16,
      "total_local_probe_calls_including_repeats":first.probe_count,
      "ground_digest":first.ground.digest,
      "path_digests":[first.path_digest,second.path_digest],
      "same_ground_distinct_path":True,
      "initial_state":list(INITIAL),
      "logical_coordinate":str(TARGET),
      "result":list(receipt.result),
      "orbit_preperiod":receipt.mu,"orbit_period":receipt.lam,
      "orbit_digest":receipt.orbit_digest,
      "external_path_invocations_during_navigation":0,
      "local_recognition_ns":timings,
      "local_navigation_including_finite_orbit_preparation_ns":elapsed,
      "external_physical_network_test":False,
      "full_ecpu_runtime_verified":False,
    }
    if include_neural:
        neural=build_neural_realization(first)
        report["neural"]={
            "verification":"checked over every global state",
            "ground_digest":neural["ground_digest"],
            "program_digest":neural["program_digest"],
            "model_digest":neural["model_digest"],
            "architecture":list(neural["architecture"]),
            "parameters":neural["parameter_count"],
            "global_rows_verified":neural["global_rows_verified"],
            "note":"compiled exact Boolean realization; not a trained model or execution authority"
        }
    return report


if __name__=="__main__":
    print(json.dumps(run(),indent=2,sort_keys=True))