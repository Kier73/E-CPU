"""Matched ITR-003 proof formation, selected realization and host re-placement."""
import json
import random
import sys
from pathlib import Path
from time import perf_counter_ns

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tests"))
from test_inverse_nonlinear_realization import capacity
from mailcpu.shared_intention_realization import SharedIntentionSession
from mailcpu.inverse_nonlinear_realization import NonlinearRealizationRefused
from run_shared_proof import source, oracle


def trial(k, mixed, count=16):
    """Match ordered targets, source and observation codes across both routes."""
    n, clauses, q, targets, ids = source(k, mixed)
    cap, replacement = capacity(), capacity(alpha=False)
    start = perf_counter_ns()
    shared = SharedIntentionSession(n, clauses, q, targets)
    shared_admission = perf_counter_ns()-start
    start = perf_counter_ns()
    singles = [SharedIntentionSession(n, clauses, q, (f,)) for f in targets]
    single_admission = perf_counter_ns()-start
    shared_raw=shared.receipt()
    single_raw=[s.receipt() for s in singles]
    size=lambda r:len(json.dumps(r,sort_keys=True,separators=(",",":")).encode())
    rng=random.Random(203000+k+int(mixed))
    codes=[0,(1<<k)-1]+[rng.getrandbits(k) for _ in range(count-2)]
    ledger={"shared":[], "single":[], "full":[], "rehome":[]}
    for i,code in enumerate(codes):
        target=i%len(targets)
        expected=oracle(code,k,mixed,ids)
        # Separate per-goal sessions pay their own initial source-section cost.
        a=shared.realize_code(code,(target,),cap)
        b=singles[target].realize_code(code,(0,),cap)
        c=shared.realize_code(code,tuple(range(len(targets))),cap)
        assert a["values"]==b["values"]==[expected[target]]
        assert c["values"]==expected
        assert a["evaluated_gates"]<=c["evaluated_gates"]
        assert a["ground"]==c["ground"]==shared.ground_digest
        ledger["shared"].append(a);ledger["single"].append(b);ledger["full"].append(c)
        if i==0:
            d=shared.realize_code(code,(target,),replacement)
            assert a["ground"]==d["ground"] and a["values"]==d["values"]
            assert a["plan_digest"]!=d["plan_digest"]
            assert "alpha" in a["hosts"] and "beta" in d["hosts"]
            ledger["rehome"].append(d)
    def summarize(rows):
        """Charge all measured phases including constructive image qualification."""
        keys=set().union(*(x["spans_ns"] for x in rows))
        return {"queries":len(rows), "total_query_ns":sum(sum(x["spans_ns"].values()) for x in rows),
                "phase_ns":{key:sum(r["spans_ns"].get(key,0) for r in rows) for key in sorted(keys)},
                "gate_evaluations":sum(r["evaluated_gates"] for r in rows),
                "section_constructions":sum(r["section_constructed"] for r in rows)}
    return {"variables":n,"observations":k,"source_clauses":len(clauses),
            "target_count":len(targets),"mixed":mixed,
            "shared_admission_ns":shared_admission,"independent_admission_ns":single_admission,
            "shared_admission_phases":shared.admission_ns,
            "shared_receipt_bytes":size(shared_raw),
            "independent_receipt_bytes":sum(map(size,single_raw)),
            "shared_gate_count":len(shared_raw["circuit"]["gates"]),
            "independent_gate_count":sum(len(r["circuit"]["gates"]) for r in single_raw),
            "shared_resolution_pairs":shared_raw["prefix_pairs"]+sum(g["pairs"] for g in shared_raw["goals"]),
            "independent_resolution_pairs":sum(r["prefix_pairs"]+sum(g["pairs"] for g in r["goals"]) for r in single_raw),
            "query_summaries":{name:summarize(rows) for name,rows in ledger.items()},
            "verified_host_replacement":True}


def main():
    """Report an inclusive local campaign; no physical network timing claim."""
    result={"schema":"mailcpu.itr003.benchmark.v1",
            "scope":"pinned IFS CIG-019 proof and CIG-021 section; SAB local carriers; same source and target codes",
            "campaign":[trial(k,mixed) for mixed in (True,False) for k in (32,128,512)]}
    print(json.dumps(result,indent=2,sort_keys=True))
    return result


if __name__=="__main__":
    main()
