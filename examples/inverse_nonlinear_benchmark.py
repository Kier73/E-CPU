"""ITR-002 reproducible native CIG-017/E-CPU end-to-end benchmark.

Run with IFS CIG-017 sources on PYTHONPATH, e.g. from project checkout:
PYTHONPATH=upstream/ifs/experiments/pnp-ground-navigation/cut_intention:tests \
    python examples/inverse_nonlinear_benchmark.py
"""
from __future__ import annotations

import json
from pathlib import Path
from statistics import median
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tests"))
from test_inverse_nonlinear_realization import (  # noqa: E402
    capacity, gate_source, source_chain, source_chain_model, state_for,
)
from mailcpu.inverse_nonlinear_realization import (  # noqa: E402
    ReceiverProofMemory, ReceiverSourceSectionMemory, realize_from_observation_code,
    direct_realize, formed_realize, compare_realizations,
    NonlinearRealizationRefused,
)


def measured(goal, observed, trials=5):
    cold, warm, formed, section_cold, section_warm = [], [], [], [], []
    for _ in range(trials):
        cap=capacity(); memory=ReceiverProofMemory()
        r0=direct_realize(goal, observed, cap, memory)
        r1=direct_realize(goal, observed, cap, memory)
        if not r0.proof_constructed or r1.proof_constructed or r0.result!=r1.result:
            raise RuntimeError("source proof reuse did not preserve verified result")
        cold.append(r0); warm.append(r1)
        # Separate cold seed; no source model is given to this pathway.
        section_proofs=ReceiverProofMemory()
        sections=ReceiverSourceSectionMemory()
        s0=realize_from_observation_code(goal,r0.source_code,cap,section_proofs,sections)
        s1=realize_from_observation_code(goal,r0.source_code,cap,section_proofs,sections)
        assert s0.result==s1.result==r0.result
        section_cold.append(s0); section_warm.append(s1)
        try:
            r2,_=formed_realize(goal, observed, cap)
        except NonlinearRealizationRefused as exc:
            if str(exc) not in ("formed baseline source enumeration budget exceeded",
                                "formed source exceeds 64-state quotient envelope"):
                raise
        else:
            compare_realizations(r0,r2)
            formed.append(r2)
    def summary(rows):
        if not rows:return {"status":"UNAVAILABLE_ABOVE_FINITE_BASELINE_BUDGET"}
        keys=tuple(rows[0].spans_ns)
        return {"status":"VERIFIED", "median_end_to_end_ns":int(median(r.total_ns for r in rows)),
                "median_phase_ns":{k:int(median(r.spans_ns[k] for r in rows)) for k in keys},
                "observed_result":rows[0].result, "source_code":rows[0].source_code,
                "host_path_digest":rows[0].path_digest,
                "proof_constructed_per_trial":[r.proof_constructed for r in rows]}
    return {"variables":goal.variables,"source_clauses":len(goal.source),
            "observed_predicates":len(goal.observations),
            "intention_digest":goal.fingerprint,
            "cold_proof_direct":summary(cold),
            "warm_proof_direct":summary(warm),
            "cold_total_image_section_direct":summary(section_cold),
            "warm_total_image_section_direct":summary(section_warm),
            "cold_independent_formed":summary(formed),
            "trials":trials}


def main():
    cases=(
        ("two-nonlinear-gates",gate_source(),state_for(1,1,0)),
        ("nonlinear-chain-7",source_chain(7),source_chain_model(7,0b1011011)),
        ("nonlinear-chain-12",source_chain(12),source_chain_model(12,0xB63)),
    )
    output={"schema":"mailcpu.itr002.benchmark.v1",
            "scope":"in-process mathematical source witness, CIG-017 proof, SAB-001 local authorized carriers; no network", "campaign":{}}
    for name,goal,observed in cases:
        output["campaign"][name]=measured(goal,observed)
    print(json.dumps(output,indent=2,sort_keys=True))
    return output

if __name__=="__main__":main()
