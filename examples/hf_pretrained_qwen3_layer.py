"""HFG-002: acquire ONLY first-layer tensor ranges from pinned Hugging Face.

Requires the pinned In-Formation-Space HFR checkout. Produces real numerical
observations with source/bytes evidence but never saves or publishes raw weights.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys

REPOSITORY = 'Qwen/Qwen3-0.6B'
REVISION = '167b8104f88905a951069f5f95f9776908da5f68'
IFS_REVISION = 'c9716242725be65937fda1dd7b6cb778ca1def91'


class LocalPageBacking:
    """Test-only page backing for E-CPU ComputationalObjectStore, no new authority."""
    page_size = 4096
    def __init__(self):self.pages={}
    def put_page(self,data):
        identity=sha256(data).hexdigest()
        self.pages[identity]=data
        return identity
    def get_page(self,identity):return self.pages[identity]


def run(*,ifs_root:Path,output:Path,native:bool,layer:int=0)->dict:
    from mailcpu.hf_model_ground import HFModelGround
    from mailcpu.hf_layer_realization import (_required_weights,LayerWeightGround,
             evaluate_with_reference,NativeQwen3LayerHost)
    from mailcpu.computational_objects import ComputationalObjectStore
    import numpy as np
    sys.path.insert(0,str(ifs_root))
    from experiments.external_neural_structure_reading.hub import (
         inspect_huggingface_model,fetch_selected_tensor_payloads)
    nsd=inspect_huggingface_model(REPOSITORY,REVISION,license_id='apache-2.0')
    if nsd['source']['revision']!=REVISION:
        raise RuntimeError('Hugging Face revision not pinned as requested')
    ground=HFModelGround.from_nsd(nsd)
    if ground.family!='qwen3':raise RuntimeError('requested checkpoint is not dense Qwen3')
    targets=_required_weights(ground,layer)
    if len(targets)!=11:raise RuntimeError('unexpected pretrained parameter inventory')
    raws,download_records=fetch_selected_tensor_payloads(
        nsd,list(targets),max_total_bytes=64*1024*1024,max_tensor_bytes=16*1024*1024)
    store=ComputationalObjectStore(LocalPageBacking())
    weight_ground=LayerWeightGround.from_payloads(ground,layer,store,raws,hfr_evidence=download_records)
    # Input is explicit and reproducible: actual pretrained layer parameters,
    # but NOT an embedding obtained by running the full model.
    positions=np.arange(2*ground.configuration['hidden_size'],dtype=np.float32)
    hidden=(np.sin(positions/13)*np.float32(0.05)).reshape(2,ground.configuration['hidden_size'])
    if native:
        outcome=NativeQwen3LayerHost(weight_ground).execute(hidden,request_id='hfg002-real-pretrained-1')
    else:
        outcome=evaluate_with_reference(weight_ground,hidden)
    # Source evidence is separable from the E-CPU local weight snapshot.
    report={"schema":"mailcpu.hfg002.real-hf-run.v1", "repository":REPOSITORY,
            "revision":REVISION,"ifs_reader_revision":IFS_REVISION,
            "model_descriptor":ground.descriptor_digest,
            "observed_safetensors_tensor_count":len(nsd['observed']['tensor_manifest']),
            "selected_tensor_count":len(raws),
            "selected_tensor_bytes":sum(len(b) for b in raws.values()),
            "selected_source_fetch_records":download_records,
            "weight_binding":weight_ground.evidence(),"numeric_result":outcome,
            "weight_data_embedded_in_report":False,
            "whole_model_checkpoint_downloaded":False,
            "full_model_forward_executed":False}
    # Verify no tensor bytes were accidentally included in provenance output.
    data=json.dumps(report,indent=2,sort_keys=True,allow_nan=False)
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(data+'\n',encoding='utf-8')
    print(json.dumps({"source":f'{REPOSITORY}@{REVISION}',"tensor_bytes":report['selected_tensor_bytes'],
                      "tensor_count":len(raws),"native":native,
                      "verified":outcome.get('reference_checked',outcome.get('independent_reference_checked')),
                      "output":str(output)},sort_keys=True))
    return report


def main(argv:list[str]|None=None)->int:
    p=argparse.ArgumentParser(description='HFG-002: pinned real Qwen3 layer, exact ranges, independent numerics')
    p.add_argument('--ifs-root',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--native',action='store_true')
    p.add_argument('--layer',type=int,default=0)
    args=p.parse_args(argv)
    run(ifs_root=args.ifs_root,output=args.output,native=args.native,layer=args.layer)
    return 0
if __name__=='__main__':raise SystemExit(main())
