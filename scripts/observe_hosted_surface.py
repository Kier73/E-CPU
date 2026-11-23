"""Interpret an external model page as a Virtual Layer structural Ground.

NO MODEL DOWNLOADING: only source-host metadata API observations. The program
never asks for a checkpoint byte range, loads a model, or materializes tensors.
The declared external size affects neither virtual address geometry nor the
number of control frames needed for one source-structural intention.

Example:
 python -m scripts.observe_hosted_surface \
   --url https://huggingface.co/deepseek-ai/DeepSeek-V4.1-Flash-1017/tree/main \
   --out artifacts/deepseek-virtual-structure.json
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from time import perf_counter_ns

from mailcpu.external_virtual_structure import (
    HTTPSMetadataObserver, MetadataNavigator, SourceStructure,
    VirtualRead, compile_virtual_read,
)


def run(url:str,*,rounds:int=2000,expected_revision:str|None=None)->dict:
    if type(rounds) is not int or not 1<=rounds<=100000:
        raise ValueError("interpretation trial count outside measured budget")
    observer=HTTPSMetadataObserver(timeout=15.0)
    start=perf_counter_ns()
    source=MetadataNavigator(observer).discover(url)
    discovery_ns=perf_counter_ns()-start
    if expected_revision and source.revision!=expected_revision:
        raise ValueError("source revision differs from independently required version")
    restored=SourceStructure.restore(source.to_dict(),source.ground_digest)
    assert restored.ground_digest==source.ground_digest
    query="source.catalogue"
    first=compile_virtual_read(source,query)
    VirtualRead.restore(restored,first.to_dict(),first.digest)
    begin=perf_counter_ns()
    for _ in range(rounds):
        result=compile_virtual_read(restored,query)
        if result.to_dict()["result"]!=first.to_dict()["result"]:
            raise AssertionError("source information changed across structural navigation")
    elapsed=perf_counter_ns()-begin
    refs=[f for f in source.files if f.path.endswith(".safetensors")]
    one=None
    if refs:
        last=refs[-1]
        if last.size_bytes:
            one=compile_virtual_read(source,"source.extent",{
                "path":last.path,"offset":last.size_bytes-1,"length":1}).to_dict()
            assert one["result"]["model_payload_bytes_read"]==0
            VirtualRead.restore(restored,one,one["position_digest"])
    return {
        "schema":"mailcpu.hss002-virtual-host-observation.v1",
        "source_page":url,
        "repository":source.repository,"source_revision":source.revision,
        "structural_ground_digest":source.ground_digest,
        "declared_external_bytes":source.declared_bytes,
        "declared_files":len(source.files),
        "declared_safetensors_files":len(refs),
        "source_declared_model_type":source.config.get("model_type"),
        "source_structural_semantics":first.to_dict()["result"],
        "large_file_last_byte_virtual_address":one and one["result"],
        "metadata_observation_count":observer.calls,
        "metadata_observation_bytes":observer.metadata_bytes,
        "model_payload_bytes_transferred":0,
        "model_payload_shards_acquired":0,
        "model_payload_partial_ranges_acquired":0,
        "model_runtime_started":False,
        "virtual_control_frames":len(first.to_dict()["frames"]),
        "structural_reinterpretations":rounds,
        "discovery_wall_ns":discovery_ns,
        "structural_interpretation_total_ns":elapsed,
        "structural_interpretation_mean_ns":elapsed/rounds,
        "source_ground":source.to_dict(),
        "pure_execution_identity":first.digest,
        "scope":"description_read_and_virtual_structural_computation_not_neural_inference",
    }


def main()->int:
    p=argparse.ArgumentParser(description="Read the *structure* of a hosted external model")
    p.add_argument("--url",required=True)
    p.add_argument("--rounds",type=int,default=2000)
    p.add_argument("--expected-revision")
    p.add_argument("--out",type=Path)
    args=p.parse_args()
    report=run(args.url,rounds=args.rounds,expected_revision=args.expected_revision)
    print(json.dumps({k:v for k,v in report.items() if k!="source_ground"},
                     indent=2,sort_keys=True))
    if args.out is not None:
        args.out.parent.mkdir(parents=True,exist_ok=True)
        args.out.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
