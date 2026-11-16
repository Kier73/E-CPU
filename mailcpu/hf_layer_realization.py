"""HFG-002 — exact-source Qwen3 layer realization using E-CPU model/weight Grounds.

This is the first *numerical* realization of an HFG-001 layer. It consumes the
verified raw payloads selected by IFS HFR-001, commits them to E-CPU MWS-001
ComputationalObjectStore, and evaluates a real Qwen3 dense decoder layer. No
full-model execution, automatic law discovery, or unearned weight reconstruction
is claimed. Native dispatch uses the existing E-CPU VirtualLayerRuntime.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Mapping
import argparse
import json
import math
import re

from .hf_model_ground import HFModelGround, HFModelGroundRefused
from .model_weight_ground import ModelParameterSpace, ModelWeightSnapshot, TensorSpace

SCHEMA = "mailcpu.hfg002.qwen3-layer.v1"
MAX_SEQUENCE = 16    # per-query experimental budget, NOT a model-space bound
MAX_TENSOR_BYTES = 16 * 1024 * 1024
_DTYPE_WIDTH = {"BF16": 2, "F16": 2, "F32": 4}


class LayerRealizationRefused(ValueError):
    """Requested layer, payload, Ground, observation or realization not admissible."""


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def _digest(value: Any) -> str:
    return sha256(_canonical(value)).hexdigest()


def _array_digest(x: Any) -> str:
    import numpy as np
    return sha256(np.asarray(x, dtype="<f4").tobytes(order="C")).hexdigest()


def _checked_hidden(hidden: Any, width: int) -> Any:
    import numpy as np
    arr = np.asarray(hidden, dtype=np.float32)
    if arr.ndim != 2 or not 1 <= len(arr) <= MAX_SEQUENCE or arr.shape[1] != width:
        raise LayerRealizationRefused("hidden state shape or query sequence budget invalid")
    if not np.isfinite(arr).all():
        raise LayerRealizationRefused("hidden state contains non-finite values")
    return arr.copy()


def _required_weights(model: HFModelGround, layer: int) -> dict[str, tuple[int, ...]]:
    if model.family != "qwen3":
        raise LayerRealizationRefused("HFG-002 numerical kernels are admitted only for dense Qwen3")
    c = model.configuration
    h, q, kv, d, f = (c[k] for k in ("hidden_size", "num_attention_heads", "num_key_value_heads",
                                    "head_dim", "intermediate_size"))
    p = f"model.layers.{layer}."
    return {p+k: v for k,v in {
        "input_layernorm.weight": (h,),
        "post_attention_layernorm.weight": (h,),
        "self_attn.q_proj.weight": (q*d,h),
        "self_attn.k_proj.weight": (kv*d,h),
        "self_attn.v_proj.weight": (kv*d,h),
        "self_attn.o_proj.weight": (h,q*d),
        "self_attn.q_norm.weight": (d,),
        "self_attn.k_norm.weight": (d,),
        "mlp.gate_proj.weight": (f,h),
        "mlp.up_proj.weight": (f,h),
        "mlp.down_proj.weight": (h,f),
    }.items()}


def _decode_tensor(raw: bytes, dtype: str, shape: tuple[int,...]) -> Any:
    import numpy as np
    if dtype not in _DTYPE_WIDTH or len(raw) != math.prod(shape)*_DTYPE_WIDTH[dtype]:
        raise LayerRealizationRefused("tensor payload bytes contradict dtype and shape")
    if dtype == "BF16":
        array = (np.frombuffer(raw, dtype="<u2").astype("<u4") << 16).view("<f4")
    elif dtype == "F16":
        array = np.frombuffer(raw, dtype="<f2").astype("<f4")
    else:
        array = np.frombuffer(raw, dtype="<f4")
    result = array.reshape(shape).copy()
    if not np.isfinite(result).all():
        raise LayerRealizationRefused("non-finite pretrained tensor not admitted for this f32 prototype")
    return result


@dataclass
class LayerWeightGround:
    model: HFModelGround
    layer_index: int
    snapshot: ModelWeightSnapshot
    store: Any
    payload_evidence: tuple[dict[str,Any], ...]
    source_observer_verified: bool = False

    @classmethod
    def from_payloads(cls, model: HFModelGround, layer: int, store: Any,
                      payloads: Mapping[str,bytes], *,
                      hfr_evidence: list[dict[str,Any]] | None = None) -> "LayerWeightGround":
        """Bind real tensor bytes to observed HFR header inventory; no trust in filenames."""
        model.layer(layer)
        required = _required_weights(model, layer)
        if set(payloads) != set(required):
            raise LayerRealizationRefused("exact 11-tensor layer payload set required")
        source_records = {}
        if hfr_evidence is not None:
            if (not isinstance(hfr_evidence,list) or len(hfr_evidence)!=len(required)
                    or any(not isinstance(x,dict) or not isinstance(x.get('name'),str) for x in hfr_evidence)):
                raise LayerRealizationRefused("HFR source records must cover all selected tensors")
            source_records={item['name']:item for item in hfr_evidence}
            if set(source_records)!=set(required) or len(source_records)!=len(hfr_evidence):
                raise LayerRealizationRefused("HFR source observation names differ from selected tensors")
        tensors, evidence = [], []
        for name, shape in sorted(required.items()):
            if model.observation_scope != "hfr_header_observed":
                # Explicitly constructed model descriptors are allowed only in
                # tests with config-only status; never claim Hub provenance.
                raise LayerRealizationRefused("pretrained payload binding requires actual HFR header observation")
            address = model.tensor_address(name)
            dtype = address["dtype"]
            if dtype not in _DTYPE_WIDTH or tuple(address["shape"]) != shape:
                raise LayerRealizationRefused(f"observed tensor encoding/shape unsupported: {name}")
            raw = payloads[name]
            if not isinstance(raw,bytes) or len(raw)!=address["byte_length"] or len(raw)>MAX_TENSOR_BYTES:
                raise LayerRealizationRefused(f"parameter bytes missing or outside budget: {name}")
            if hfr_evidence is not None:
                observed=source_records[name]
                if (observed.get('shard')!=address['shard']
                        or observed.get('dtype')!=dtype
                        or observed.get('shape')!=list(shape)
                        or observed.get('size_bytes')!=len(raw)
                        or observed.get('shard_header_sha256')!=address['header_digest']
                        or observed.get('payload_sha256')!=sha256(raw).hexdigest()
                        or observed.get('payload_sha256_scope')!='complete-selected-tensor-payload'):
                    raise LayerRealizationRefused("HFR selected tensor evidence differs from received bytes")
                observed_range=observed.get('absolute_byte_range')
                if (not isinstance(observed_range,list) or len(observed_range)!=2
                        or any(type(v) is not int for v in observed_range)
                        or observed_range[1]-observed_range[0]+1!=len(raw)):
                    raise LayerRealizationRefused("HFR selected tensor byte range is not exact")
            _decode_tensor(raw,dtype,shape)  # preflight dtype/finite policy
            tensors.append(TensorSpace(name,dtype,shape))
            evidence.append({"name":name,"dtype":dtype,"shape":list(shape),
                             "source_shard":address["shard"],"source_header":address["header_digest"],
                             "payload_sha256":sha256(raw).hexdigest(),"payload_bytes":len(raw),
                             "byte_scope":"verified-selected-parameter-bytes"})
        space=ModelParameterSpace(f"hf.{model.repository.replace('/', '.')}.layer-{layer}",
                                   {"ground_descriptor":model.descriptor_digest,
                                    "source_repository":model.repository,"source_revision":model.revision,
                                    "layer_index":layer,"numerical_policy":"bf16-source-f32-arithmetic"},
                                   tuple(tensors))
        snapshot=ModelWeightSnapshot.publish_tensors(space,store,payloads)
        if not snapshot.verify_all(store):
            raise LayerRealizationRefused("E-CPU object store did not verify supplied tensor payloads")
        return cls(model,layer,snapshot,store,tuple(evidence),hfr_evidence is not None)

    @property
    def identity(self) -> str:
        return _digest({"schema":SCHEMA,"model":self.model.descriptor_digest,
                        "snapshot":self.snapshot.identity,"layer":self.layer_index,
                        "numerical_policy":"bf16-source-f32-arithmetic"})

    def weight(self, suffix: str) -> Any:
        name=f"model.layers.{self.layer_index}.{suffix}"
        tensor=self.snapshot.space.tensor(name)
        if tensor.byte_size > MAX_TENSOR_BYTES:
            raise LayerRealizationRefused("tensor exceeds explicit read budget")
        # Always go through existing E-CPU's hash-checked pages rather than
        # retaining an unsigned raw dictionary from the producer.
        return _decode_tensor(self.snapshot.tensor_raw(self.store,name,max_bytes=MAX_TENSOR_BYTES),
                              tensor.dtype,tensor.shape)

    def evidence(self) -> dict[str,Any]:
        return {"schema":SCHEMA,"model_ground":self.model.descriptor_digest,
                "layer_ground":self.identity,"layer":self.layer_index,
                "weight_snapshot":self.snapshot.identity,
                "numerical_policy":"bf16-source-f32-arithmetic",
                "tensor_payloads":list(self.payload_evidence),
                "hfr_source_ranges_verified":self.source_observer_verified,
                "full_model_weights_verified":False,"model_forward_executed":False}


def _rms(x: Any, w: Any, eps: float) -> Any:
    import numpy as np
    return (x * np.reciprocal(np.sqrt(np.mean(x*x,axis=-1,keepdims=True)+np.float32(eps)))) * w


def _rope(x: Any, cos: Any, sin: Any) -> Any:
    import numpy as np
    half=x.shape[-1]//2
    rotated=np.concatenate((-x[...,half:],x[...,:half]),axis=-1)
    return x*cos[:,None,:]+rotated*sin[:,None,:]


def realize_attention(binding: LayerWeightGround, hidden: Any, *, start_position:int=0) -> Any:
    """One real numerical Qwen3 GQA/RoPE attention and first residual."""
    import numpy as np
    c=binding.model.configuration
    h,qh,kvh,d,eps = (c[k] for k in ("hidden_size","num_attention_heads","num_key_value_heads","head_dim","rms_norm_eps"))
    if type(start_position) is not int or start_position<0 or start_position+len(hidden)>c["max_position_embeddings"]:
        raise LayerRealizationRefused("requested position outside pinned Ground")
    x=_checked_hidden(hidden,h)
    normalized=_rms(x,binding.weight("input_layernorm.weight"),eps)
    q=(normalized @ binding.weight("self_attn.q_proj.weight").T).reshape(len(x),qh,d)
    k=(normalized @ binding.weight("self_attn.k_proj.weight").T).reshape(len(x),kvh,d)
    v=(normalized @ binding.weight("self_attn.v_proj.weight").T).reshape(len(x),kvh,d)
    q=_rms(q,binding.weight("self_attn.q_norm.weight"),eps)
    k=_rms(k,binding.weight("self_attn.k_norm.weight"),eps)
    theta=float(c["rope_theta"])
    freqs=np.power(theta,-np.arange(0,d,2,dtype=np.float32)/np.float32(d)).astype(np.float32)
    angles=np.outer(np.arange(start_position,start_position+len(x),dtype=np.float32),freqs)
    emb=np.concatenate((angles,angles),axis=-1)
    co=np.cos(emb).astype(np.float32);si=np.sin(emb).astype(np.float32)
    q=_rope(q,co,si);k=_rope(k,co,si)
    repeats=qh//kvh
    k=np.repeat(k,repeats,axis=1);v=np.repeat(v,repeats,axis=1)
    scores=np.einsum('thd,shd->hts',q,k)/np.float32(math.sqrt(d))
    for token_idx in range(len(x)):
        scores[:,token_idx,token_idx+1:]=-np.inf
    scores=scores-np.max(scores,axis=-1,keepdims=True)
    probabilities=np.exp(scores)
    probabilities=probabilities/np.sum(probabilities,axis=-1,keepdims=True)
    attended=np.einsum('hts,shd->thd',probabilities,v).reshape(len(x),qh*d)
    projected=attended @ binding.weight("self_attn.o_proj.weight").T
    result=x+projected
    if not np.isfinite(result).all():raise LayerRealizationRefused("non-finite attention result")
    return result.astype(np.float32)


def realize_mlp(binding: LayerWeightGround, attention_output: Any) -> Any:
    """Qwen3 post-attention RMSNorm, SiLU-gated FFN and second residual."""
    import numpy as np
    c=binding.model.configuration
    x=_checked_hidden(attention_output,c["hidden_size"])
    norm=_rms(x,binding.weight("post_attention_layernorm.weight"),c["rms_norm_eps"])
    gate=norm @ binding.weight("mlp.gate_proj.weight").T
    up=norm @ binding.weight("mlp.up_proj.weight").T
    activated=gate/(np.float32(1)+np.exp(-gate))
    output=(activated*up) @ binding.weight("mlp.down_proj.weight").T
    result=(x+output).astype(np.float32)
    if not np.isfinite(result).all():raise LayerRealizationRefused("non-finite SwiGLU result")
    return result


def reference_torch(binding: LayerWeightGround, hidden: Any, *, start_position:int=0) -> Any:
    """Separately implemented PyTorch numerical reference; NOT E-CPU authority."""
    import torch
    import numpy as np
    c=binding.model.configuration
    x=torch.from_numpy(_checked_hidden(hidden,c["hidden_size"]))
    W=lambda name:torch.from_numpy(binding.weight(name))
    eps=c["rms_norm_eps"]
    def norm(y,w):
        return y*torch.rsqrt(torch.mean(y*y,dim=-1,keepdim=True)+eps)*w
    v=norm(x,W("input_layernorm.weight"))
    hq,hkv,d=c["num_attention_heads"],c["num_key_value_heads"],c["head_dim"]
    q=torch.nn.functional.linear(v,W("self_attn.q_proj.weight")).reshape(len(x),hq,d)
    k=torch.nn.functional.linear(v,W("self_attn.k_proj.weight")).reshape(len(x),hkv,d)
    val=torch.nn.functional.linear(v,W("self_attn.v_proj.weight")).reshape(len(x),hkv,d)
    q=norm(q,W("self_attn.q_norm.weight"));k=norm(k,W("self_attn.k_norm.weight"))
    inv=torch.pow(torch.tensor(float(c["rope_theta"])), -torch.arange(0,d,2,dtype=torch.float32)/d)
    positions=torch.arange(start_position,start_position+len(x),dtype=torch.float32)
    angle=positions[:,None]*inv
    emb=torch.cat((angle,angle),dim=-1)
    cos, sin=emb.cos()[:,None,:],emb.sin()[:,None,:]
    def rotate_half(y):
        h=y.shape[-1]//2
        return torch.cat((-y[...,h:],y[...,:h]),dim=-1)
    q=q*cos+rotate_half(q)*sin
    k=k*cos+rotate_half(k)*sin
    k=k.repeat_interleave(hq//hkv,dim=1)
    val=val.repeat_interleave(hq//hkv,dim=1)
    scores=torch.einsum("thd,shd->hts",q,k)*(d**-0.5)
    mask=torch.ones(len(x),len(x),dtype=torch.bool).tril()
    scores=scores.masked_fill(~mask[None,:,:],float('-inf'))
    probabilities=torch.softmax(scores,dim=-1)
    atten=torch.einsum("hts,shd->thd",probabilities,val).reshape(len(x),hq*d)
    res=x+torch.nn.functional.linear(atten,W("self_attn.o_proj.weight"))
    y=norm(res,W("post_attention_layernorm.weight"))
    gate=torch.nn.functional.linear(y,W("mlp.gate_proj.weight"))
    up=torch.nn.functional.linear(y,W("mlp.up_proj.weight"))
    mlp=torch.nn.functional.linear(torch.nn.functional.silu(gate)*up,W("mlp.down_proj.weight"))
    return (res+mlp).detach().numpy()


def evaluate_with_reference(binding: LayerWeightGround, hidden: Any, *, start_position:int=0,
                            atol:float=2e-3, rtol:float=2e-3)->dict[str,Any]:
    """Compare a full native-model Ground layer with independent PyTorch."""
    import numpy as np
    result=realize_mlp(binding,realize_attention(binding,hidden,start_position=start_position))
    oracle=reference_torch(binding,hidden,start_position=start_position)
    difference=np.abs(result-oracle)
    verified=bool(np.allclose(result,oracle,atol=atol,rtol=rtol))
    if not verified:
        raise LayerRealizationRefused("full neural-layer output differs from independent PyTorch oracle")
    return {"schema":SCHEMA+".verification","layer_ground":binding.identity,
            "weight_snapshot":binding.snapshot.identity,
            "input_digest":_array_digest(hidden),"result_digest":_array_digest(result),
            "reference_digest":_array_digest(oracle),"max_absolute_error":float(np.max(difference)),
            "atol":atol,"rtol":rtol,"reference_checked":True,
            "layer_math_executed":True,"full_model_forward_executed":False}


class NativeQwen3LayerHost:
    """Two admitted, ordered pure operators on ONE existing MailCPU HeadlessOS.

    NumPy is the current numerical realizer for known semantics, not a new
    Hypervisor, scheduler, Ground authority, or claim of path-native arithmetic.
    """
    def __init__(self,binding:LayerWeightGround,*,allow_compute:bool=True):
        from mailcpu import (HeadlessOS,Capability,OperatorRegistry,OperatorSpec,
                             SystemIdentity,SystemSeed,SystemSeedEnvelope,
                             VirtualGroundRef,VirtualLayerRuntime)
        from mailcpu.classifier import HypervisorPolicy,LexicalDecisionModel
        self.binding=binding
        self.system=HeadlessOS()
        self.system.hypervisor.classifier=LexicalDecisionModel()
        self.system.hypervisor.policy=HypervisorPolicy(review_confidence=0.0,automatic_confidence=0.0,
                   destructive_confidence=0.0,danger_review_probability=1.0,
                   embedding_review_confidence=1.0)
        self.node_id="hfg002-"+binding.identity[:16]
        self.identity=SystemIdentity(self.node_id,1)
        envelope=SystemSeedEnvelope(self.identity,"hfg-layer","hfg002",SystemSeed.from_system(self.system))
        if not self.system.seed_admission.admit(envelope).accepted:
            raise LayerRealizationRefused("receiver Ground seed admission refused")
        self.ground=VirtualGroundRef.from_envelope(envelope)
        registry=OperatorRegistry()
        self.specs={}
        self.staged={}
        self.outputs={}
        for stage in ("attention","mlp"):
            op="hfg002.qwen3."+stage
            spec=OperatorSpec(operator_id=op,version=1,
                     description="Receiver-owned pinned Qwen3 layer "+stage,
                     input_kind="object",output_kind="object",substrates=("cpu",),
                     required_rights=frozenset({"compute"}),
                     max_input_bytes=100_000,max_output_bytes=4096,
                     base_energy=2,energy_per_byte=1,deterministic=True,effect_mode="pure")
            registry.register(spec, lambda request, workload,stage=stage:self._handle(stage,request))
            self.specs[stage]=spec
        self.runtime=VirtualLayerRuntime(registry,self.node_id,frozenset({"cpu"}))
        cap=Capability("/virtual-layer/operators",frozenset({"compute"})) if allow_compute else Capability("/unrelated",frozenset({"read"}))
        self.pid=self.system.environment.kernel.spawn(self.node_id,capabilities=(cap,),
                          parent_pid=self.system.environment.init_pid)

    def _handle(self,stage:str,request:Any)->dict[str,Any]:
        if not isinstance(request,dict) or set(request)!={"request_id","layer_ground","stage","input_digest","position"}:
            raise LayerRealizationRefused("receiver operator requires exact bound request fields")
        if request["layer_ground"]!=self.binding.identity or request["stage"]!=stage:
            raise LayerRealizationRefused("receiver operator input Ground or stage identity mismatch")
        rid=request["request_id"]
        state=self.staged.get(rid)
        if state is None or state["stage"]!=stage or _array_digest(state["input"])!=request["input_digest"]:
            raise LayerRealizationRefused("no validated predecessor input at receiver")
        result=(realize_attention(self.binding,state["input"],start_position=request["position"])
                if stage=="attention" else realize_mlp(self.binding,state["input"]))
        self.outputs[(rid,stage)]=result
        return {"stage":stage,"layer_ground":self.binding.identity,"input_digest":request["input_digest"],
                "output_digest":_array_digest(result),"position":request["position"]}

    def _invoke(self,stage:str,rid:str,input_state:Any,position:int,sequence:int)->dict[str,Any]:
        from mailcpu import VirtualBudget,VirtualLayerWorkload,VirtualOperatorRef
        from mailcpu.classifier import HypervisorAction
        self.staged[rid]={"stage":stage,"input":input_state}
        request={"request_id":rid,"layer_ground":self.binding.identity,
                 "stage":stage,"input_digest":_array_digest(input_state),"position":position}
        op=self.specs[stage]
        workload=VirtualLayerWorkload(workload_id="hfg002."+rid+"."+stage,
            system=self.identity,ground=self.ground,
            intention={"goal":"verified-neural-layer-stage","ground":self.binding.identity,"stage":stage},
            operators=(VirtualOperatorRef(op.operator_id,1,"cpu",self.node_id),),
            input_value=request,budget=VirtualBudget(1_000_000,100_000,1_000_000),
            logical_time=sequence,eligible_nodes=(self.node_id,),max_hops=1)
        try:
            result=self.runtime.execute_operator(self.system,self.pid,"hfg002-requester",
                    "hfg002."+stage,sequence,sequence,workload,op.operator_id)
        finally:
            self.staged.pop(rid,None)
        if result.action is not HypervisorAction.ALLOW or not result.executed:
            raise LayerRealizationRefused("receiver Hypervisor refused neural stage " + stage)
        output=self.outputs.pop((rid,stage),None)
        if output is None or not isinstance(result.effect,dict) or result.effect.get("kind")!="virtual_layer.operator_result":
            raise LayerRealizationRefused("E-CPU did not return authorized neural operation result")
        envelope=result.effect["result"]
        if envelope.get("output_digest")!=_array_digest(output):
            raise LayerRealizationRefused("operator receipt differs from resident tensor output")
        if not self.system.environment.kernel.journal.verify():
            raise LayerRealizationRefused("receiver execution journal failed verification")
        return {"tensor":output,"receipt":envelope,"operator_contract":op.digest,
                "e_cpu_fingerprint":result.fingerprint}

    def execute(self,hidden:Any,*,request_id:str="hfg002-query-0",position:int=0)->dict[str,Any]:
        from mailcpu.computation_dag import ComputationNode,NavigableComputationDAG
        if type(request_id) is not str or not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}",request_id):
            raise LayerRealizationRefused("invalid request identity")
        x=_checked_hidden(hidden,self.binding.model.configuration["hidden_size"])
        if position<0 or position+len(x)>self.binding.model.configuration["max_position_embeddings"]:
            raise LayerRealizationRefused("position outside Ground")
        ctx=_digest({"layer":self.binding.identity,"request":request_id,"position":position,
                     "input":_array_digest(x)})
        dag=NavigableComputationDAG((
            ComputationNode("input",1,"ground.read_hidden_state","/model/weights",ctx,(),
                {"model":self.binding.model.descriptor_digest,"snapshot":self.binding.snapshot.identity,
                 "input_digest":_array_digest(x)}),
            ComputationNode("attention",1,"hfg002.qwen3.attention","/virtual-layer/operators",ctx,("input",),
                {"layer_ground":self.binding.identity,"position":position}),
            ComputationNode("mlp",1,"hfg002.qwen3.mlp","/virtual-layer/operators",ctx,("attention",),
                {"layer_ground":self.binding.identity,"position":position}),
        ))
        dag.commit("input",{"input_digest":_array_digest(x),"layer_ground":self.binding.identity})
        if tuple(n.node_id for n in dag.ready_nodes())!=("attention",):
            raise LayerRealizationRefused("attention dependency is not ready")
        a=self._invoke("attention",request_id,x,position,1)
        dag.commit("attention",{k:v for k,v in a.items() if k!="tensor"})
        if tuple(n.node_id for n in dag.ready_nodes())!=("mlp",):
            raise LayerRealizationRefused("MLP dependency was not opened")
        m=self._invoke("mlp",request_id,a["tensor"],position,2)
        dag.commit("mlp",{k:v for k,v in m.items() if k!="tensor"})
        if not dag.is_complete or NavigableComputationDAG.from_snapshot(dag.snapshot()).digest!=dag.digest:
            raise LayerRealizationRefused("committed E-CPU DAG did not reconstruct")
        reference=reference_torch(self.binding,x,start_position=position)
        import numpy as np
        diff=np.abs(m["tensor"]-reference)
        if not np.allclose(m["tensor"],reference,atol=2e-3,rtol=2e-3):
            raise LayerRealizationRefused("native E-CPU layer result contradicts PyTorch reference")
        return {"schema":SCHEMA+".native-receipt","model_ground":self.binding.model.descriptor_digest,
                "layer_ground":self.binding.identity,"weight_snapshot":self.binding.snapshot.identity,
                "input_digest":_array_digest(x),"output_digest":_array_digest(m["tensor"]),
                "dag_digest":dag.digest,"dag_complete":True,
                "stage_receipts":[a["receipt"],m["receipt"]],
                "operator_contracts":[a["operator_contract"],m["operator_contract"]],
                "max_absolute_reference_error":float(np.max(diff)),
                "independent_reference_checked":True,"layer_math_executed":True,
                "full_model_forward_executed":False}


def main(argv:list[str]|None=None)->int:
    parser=argparse.ArgumentParser(description="HFG-002 pinned Qwen3 layer numerical Ground; no full-model claim")
    parser.add_argument("--nsd",required=True,help="IFS header observation JSON")
    parser.add_argument("--tensor-dir",required=True,help="directory containing selected raw tensor payloads")
    parser.add_argument("--layer",type=int,default=0)
    parser.add_argument("--native",action="store_true",help="require actual E-CPU Hypervisor and DAG")
    parser.add_argument("--output")
    args=parser.parse_args(argv)
    from pathlib import Path
    from hashlib import sha256
    try:
        from .computational_objects import ComputationalObjectStore
        from .model_weight_ground import ModelWeightSnapshot
        class LocalPages:
            page_size=4096
            def __init__(self):self.pages={}
            def put_page(self,p):
                h=sha256(p).hexdigest();self.pages[h]=p;return h
            def get_page(self,h):return self.pages[h]
        nsd=json.loads(Path(args.nsd).read_text(encoding="utf-8"))
        model=HFModelGround.from_nsd(nsd)
        names=_required_weights(model,args.layer)
        root=Path(args.tensor_dir)
        payloads={name:(root/(name.replace(".","__")+".bin")).read_bytes() for name in names}
        store=ComputationalObjectStore(LocalPages())
        binding=LayerWeightGround.from_payloads(model,args.layer,store,payloads)
        import numpy as np
        init=np.sin(np.arange(model.configuration["hidden_size"],dtype=np.float32)/13)[None,:]*np.float32(0.05)
        if args.native:
            result=NativeQwen3LayerHost(binding).execute(init)
        else:
            result=evaluate_with_reference(binding,init)
        record={"weights":binding.evidence(),"result":result}
        rendered=json.dumps(record,indent=2,sort_keys=True,allow_nan=False)+"\n"
        if args.output:Path(args.output).write_text(rendered,encoding="utf-8")
        else:print(rendered)
    except (HFModelGroundRefused,LayerRealizationRefused,OSError,ValueError) as exc:
        parser.error(str(exc))
    return 0

if __name__=="__main__":raise SystemExit(main())
