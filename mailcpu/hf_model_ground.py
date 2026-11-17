"""HFG-001: compile pinned Hugging Face neural descriptions into *nonexecuting*
E-CPU Ground frontiers. Consumes In-Formation-Space HFR/NSD evidence without
fetching tensor payloads, installing an inference engine or granting authority.

A Model Ground fixes meaning, not bytes. A per-layer NavigableComputationDAG
is an operation dependency description, never proof of neural execution.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from collections.abc import Iterator, Mapping
from typing import Any
import argparse
import json
import re
from pathlib import Path
from types import MappingProxyType

SCHEMA = "mailcpu.hf-model-ground.v1"
HFR_SCHEMA = "in-formation-space.neural-structure-description.v0.1"
_REPO = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*\Z")
_SHA = re.compile(r"[a-f0-9]{40}\Z")
_TENSOR = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]*\Z")
_DTYPES = {"F64":8,"F32":4,"BF16":2,"F16":2,"I64":8,"I32":4,"I16":2,"I8":1,"U8":1,"BOOL":1,
           "F8_E4M3FN":1,"F8_E5M2":1,"F8_E4M3":1,"F8_E4M3FNUZ":1,"F8_E5M2FNUZ":1,"F8_E8M0":1,"U16":2,"U32":4,"U64":8}

class HFModelGroundRefused(ValueError):
    """The purported observation does not suffice for a specified Ground."""


def canonical(value: Any) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
    except (ValueError, TypeError) as exc:
        raise HFModelGroundRefused("cannot canonically represent finite Ground data") from exc


def digest(value: Any) -> str:
    return sha256(canonical(value)).hexdigest()


def _freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({k:_freeze(v) for k,v in value.items()})
    if isinstance(value, (list,tuple)):
        return tuple(_freeze(v) for v in value)
    return value


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {k:_plain(v) for k,v in value.items()}
    if isinstance(value,(tuple,list)):
        return [_plain(v) for v in value]
    return value


def positive(config: Mapping[str, Any], key: str) -> int:
    v = config.get(key)
    if type(v) is not int or v <= 0:
        raise HFModelGroundRefused(f"{key} must be a strictly positive integer")
    return v


def _source(repo: str, revision: str) -> None:
    if not isinstance(repo, str) or not _REPO.fullmatch(repo):
        raise HFModelGroundRefused("model repository must be owner/name")
    if not isinstance(revision, str) or not _SHA.fullmatch(revision):
        raise HFModelGroundRefused("model revision must be a pinned, lowercase 40-hex commit")


def _validate_arch(config: Mapping[str, Any]) -> str:
    if not isinstance(config, Mapping):
        raise HFModelGroundRefused("config must be a mapping")
    family = config.get("model_type")
    if family not in ("qwen3", "qwen3_moe", "gpt_oss"):
        raise HFModelGroundRefused(f"model family {family!r} not yet semantically compiled")
    required = ("num_hidden_layers", "hidden_size", "num_attention_heads", "num_key_value_heads",
                "head_dim", "max_position_embeddings", "vocab_size")
    for key in required: positive(config, key)
    if positive(config, "num_attention_heads") % positive(config, "num_key_value_heads"):
        raise HFModelGroundRefused("query heads are not divisible into KV groups")
    if family != "qwen3":
        expert_key = "num_experts" if family == "qwen3_moe" else "num_local_experts"
        experts = positive(config, expert_key)
        if positive(config, "num_experts_per_tok") > experts:
            raise HFModelGroundRefused("active experts exceed available experts")
    if config.get("tie_word_embeddings") not in (True, False):
        raise HFModelGroundRefused("embedding tie policy must be explicit")
    eps = config.get("rms_norm_eps")
    if not isinstance(eps, (int, float)) or isinstance(eps, bool) or not (0 < eps < 1):
        raise HFModelGroundRefused("RMS normalization epsilon is absent or invalid")
    if family in ("qwen3", "qwen3_moe"):
        if family == "qwen3_moe":
            positive(config,"moe_intermediate_size")
            positive(config,"decoder_sparse_step")
        mlp_only = config.get("mlp_only_layers", [])
        if not isinstance(mlp_only, list) or any(type(i) is not int or not 0 <= i < config["num_hidden_layers"] for i in mlp_only):
            raise HFModelGroundRefused("MLP-only layer indices invalid")
        if len(set(mlp_only)) != len(mlp_only):
            raise HFModelGroundRefused("duplicate MLP-only layer index")
        if config.get("hidden_act") != "silu":
            raise HFModelGroundRefused("unimplemented Qwen3 activation semantics")
        if family == "qwen3_moe" and config.get("norm_topk_prob") not in (True,False):
            raise HFModelGroundRefused("Qwen3 MoE top-k normalization policy unknown")
        positive(config,"intermediate_size")
    else:
        positive(config,"intermediate_size")
        types = config.get("layer_types")
        if not isinstance(types, list) or len(types) != config["num_hidden_layers"] or any(x not in ("full_attention","sliding_attention") for x in types):
            raise HFModelGroundRefused("GPT-OSS per-layer attention types are required")
        if "sliding_attention" in types: positive(config,"sliding_window")
        quant = config.get("quantization_config", {})
        if not isinstance(quant, Mapping) or quant.get("quant_method") != "mxfp4":
            raise HFModelGroundRefused("unimplemented GPT-OSS quantized-expert interpretation")
        if config.get("swiglu_limit") is None:
            raise HFModelGroundRefused("GPT-OSS bounded gated activation contract missing")
        rope = config.get("rope_scaling")
        if not isinstance(rope, Mapping) or rope.get("rope_type") != "yarn":
            raise HFModelGroundRefused("GPT-OSS YaRN positional interpretation missing")
    return family


def _manifest(nsd: Mapping[str, Any]) -> tuple[tuple[str,str,tuple[int,...],int,str,int,str], ...]:
    if nsd.get("schema") != HFR_SCHEMA:
        raise HFModelGroundRefused("not an In-Formation-Space HFR neural structure description")
    observed = nsd.get("observed")
    if not isinstance(observed, Mapping):
        raise HFModelGroundRefused("HFR observation record missing")
    manifest = observed.get("tensor_manifest")
    files = observed.get("files")
    if not isinstance(manifest,list) or not manifest or not isinstance(files,list):
        raise HFModelGroundRefused("HFR tensor and file inventories required")
    shard_records = {f.get("path"):f for f in files if isinstance(f,dict) and f.get("role")=="safetensors-shard" and f.get("sha256_scope")=="8-byte-prefix-and-header-only"}
    if not shard_records:
        raise HFModelGroundRefused("no HFR header-verified shard records")
    names=set(); records=[]; intervals:dict[str,list[tuple[int,int]]]={}
    wm=observed.get("weight_map")
    if wm is not None and not isinstance(wm,Mapping):
        raise HFModelGroundRefused("invalid HFR weight index")
    for t in manifest:
        if not isinstance(t,Mapping): raise HFModelGroundRefused("malformed HFR tensor record")
        name,dtype,shape,shard,offsets=t.get("name"),t.get("dtype"),t.get("shape"),t.get("shard"),t.get("data_offsets")
        if not isinstance(name,str) or not _TENSOR.fullmatch(name) or name in names:
            raise HFModelGroundRefused("unsafe/duplicate HFR tensor name")
        if dtype not in _DTYPES or not isinstance(shape,list) or any(type(n) is not int or n<0 for n in shape):
            raise HFModelGroundRefused("HFR tensor dtype or shape invalid")
        if shard not in shard_records or not isinstance(offsets,list) or len(offsets)!=2 or any(type(n) is not int for n in offsets):
            raise HFModelGroundRefused("HFR tensor has no verified shard/range")
        f=shard_records[shard]
        header_sha=f.get("sha256")
        if not isinstance(header_sha,str) or not re.fullmatch(r"[0-9a-f]{64}",header_sha):
            raise HFModelGroundRefused("HFR header digest missing or invalid")
        if type(f.get("data_bytes")) is not int or f["data_bytes"]<0 or type(f.get("size_bytes")) is not int or f["size_bytes"]<=0 or type(f.get("header_bytes")) is not int or f["header_bytes"]<2:
            raise HFModelGroundRefused("HFR shard geometry incomplete")
        if f["size_bytes"]-8-f["header_bytes"]!=f["data_bytes"]:
            raise HFModelGroundRefused("HFR shard bytes disagree with header")
        a,b=offsets
        size=_DTYPES[dtype]
        for dim in shape: size*=dim
        if a<0 or b<a or b>f["data_bytes"] or b-a!=size or t.get("data_bytes")!=size:
            raise HFModelGroundRefused("HFR tensor extent disagrees with shape and dtype")
        if wm is not None and wm.get(name)!=shard:
            raise HFModelGroundRefused("tensor disagrees with HFR weight index")
        names.add(name);intervals.setdefault(shard,[]).append((a,b));records.append((name,dtype,tuple(shape),size,shard,a,header_sha))
    if wm is not None and set(wm)!=names:
        raise HFModelGroundRefused("HFR weight index inventory incomplete")
    for ranges in intervals.values():
        previous=0
        for a,b in sorted(ranges):
            if b>a and a<previous: raise HFModelGroundRefused("HFR header payload extents overlap")
            previous=max(previous,b)
    return tuple(sorted(records))


@dataclass(frozen=True)
class HFModelGround:
    repository: str
    revision: str
    configuration: dict[str,Any]
    generation: dict[str,Any] | None = None
    tokenizer_descriptor: dict[str,Any] | None = None
    tensor_inventory: tuple[tuple[str,str,tuple[int,...],int,str,int,str],...] = ()
    observation_scope: str = "config_only"

    def __post_init__(self) -> None:
        _source(self.repository, self.revision)
        _validate_arch(self.configuration)
        if self.observation_scope not in ("config_only","hfr_header_observed"):
            raise HFModelGroundRefused("unsupported evidence scope")
        if self.observation_scope=="hfr_header_observed" and not self.tensor_inventory:
            raise HFModelGroundRefused("HFR observation must contain tensors")
        if self.generation is not None and not isinstance(self.generation,dict):
            raise HFModelGroundRefused("generation descriptor must be object")
        if self.tokenizer_descriptor is not None and not isinstance(self.tokenizer_descriptor,dict):
            raise HFModelGroundRefused("tokenizer descriptor must be object")
        # Descriptors cannot be changed after their digest has become an address.
        object.__setattr__(self, "configuration", _freeze(json.loads(canonical(self.configuration))))
        if self.generation is not None:
            object.__setattr__(self, "generation", _freeze(json.loads(canonical(self.generation))))
        if self.tokenizer_descriptor is not None:
            object.__setattr__(self, "tokenizer_descriptor", _freeze(json.loads(canonical(self.tokenizer_descriptor))))
        object.__setattr__(self, "tensor_inventory", tuple((n,d,tuple(shape),size,shard,start,header_sha) for n,d,shape,size,shard,start,header_sha in self.tensor_inventory))
        canonical(self.to_dict())

    @classmethod
    def from_nsd(cls, nsd: Mapping[str,Any], *, generation: dict[str,Any]|None=None,
                 tokenizer_descriptor: dict[str,Any]|None=None)->"HFModelGround":
        if not isinstance(nsd,Mapping) or not isinstance(nsd.get("source"),Mapping) or not isinstance(nsd.get("observed"),Mapping):
            raise HFModelGroundRefused("NSD source and observation required")
        s=nsd["source"];o=nsd["observed"]
        _source(s.get("repository"),s.get("revision"))
        return cls(s["repository"],s["revision"],dict(o.get("configuration",{})),
                   generation,tokenizer_descriptor,_manifest(nsd),"hfr_header_observed")

    @property
    def family(self)->str: return self.configuration["model_type"]

    @property
    def descriptor_digest(self)->str: return digest(self.to_dict())

    def to_dict(self)->dict[str,Any]:
        return {"schema":SCHEMA,"source":{"repository":self.repository,"revision":self.revision},
                "configuration":_plain(self.configuration),"generation":_plain(self.generation),
                "tokenizer_descriptor":_plain(self.tokenizer_descriptor),
                "tensor_inventory":[{"name":n,"dtype":d,"shape":list(s),"data_bytes":b,
                                     "shard":shard,"data_offset":start,"header_digest":header_sha}
                                    for n,d,s,b,shard,start,header_sha in self.tensor_inventory],
                "observation_scope":self.observation_scope,
                "weights_fully_verified":False,"inference_executed":False,
                "tokenizer_bytes_verified":False}

    @property
    def architecture_ref(self)->Any:
        from .semantic_translation import RepresentationRef
        return RepresentationRef.from_payload("mailcpu.hf-model-structure",1,self.to_dict())

    def tensor_address(self,name:str)->dict[str,Any]:
        """Locate a reported header address; this never retrieves parameter bits."""
        if not isinstance(name,str) or not _TENSOR.fullmatch(name):
            raise HFModelGroundRefused("tensor name invalid")
        for n,d,shape,size,shard,start,header_sha in self.tensor_inventory:
            if n==name:
                return {"name":n,"dtype":d,"shape":list(shape),"shard":shard,
                        "offset_after_safetensors_header":start,"byte_length":size,
                        "header_digest":header_sha,"parameter_bytes_verified":False}
        raise HFModelGroundRefused("tensor address not present in supplied HFR inventory")

    def requirements(self)->dict[str,Any]:
        return {"weight_payload":"not acquired or checked by this observer",
                "weight_header_status":"HFR-reported; independently revalidate exact source" if self.tensor_inventory else "not observed",
                "tokenizer":"requires byte-bound tokenizer artifact and chat template",
                "operator_semantics":"requires receiver-admitted, numerical reference-checked realizers",
                "kv_state":"requires durable, consistent position-bound K/V state",
                "execution":"no neural arithmetic executed by a Ground descriptor"}

    def layer_kind(self,layer:int)->str:
        if type(layer) is not int or layer<0 or layer>=positive(self.configuration,"num_hidden_layers"):
            raise HFModelGroundRefused("layer coordinate outside model Ground")
        if self.family=="gpt_oss": return self.configuration["layer_types"][layer]
        if self.family=="qwen3": return "dense_mlp"
        if layer in self.configuration.get("mlp_only_layers",[]): return "dense_mlp"
        step=self.configuration["decoder_sparse_step"]
        return "moe" if (layer+1)%step==0 else "dense_mlp"

    def layer(self, layer:int, *, token_coordinate:int=0, phase:str="decode", previous_state_digest:str|None=None)->"LayerGround":
        self.layer_kind(layer)
        if type(token_coordinate) is not int or token_coordinate<0:
            raise HFModelGroundRefused("token coordinate must be nonnegative integer")
        if phase not in ("decode","prefill"):
            raise HFModelGroundRefused("unsupported inference phase")
        if token_coordinate>=positive(self.configuration,"max_position_embeddings"):
            raise HFModelGroundRefused("token coordinate beyond declared positional configuration")
        if previous_state_digest is not None and (not isinstance(previous_state_digest,str) or len(previous_state_digest)!=64 or any(c not in "0123456789abcdef" for c in previous_state_digest)):
            raise HFModelGroundRefused("previous hidden state requires content digest")
        return LayerGround(self,layer,token_coordinate,phase,previous_state_digest)

    def layers(self, *, token_coordinate:int=0, phase:str="decode")->Iterator["LayerGround"]:
        # Only one frontier is realized on demand; never compile 94 layers as a single bounded E-CPU DAG.
        for i in range(self.configuration["num_hidden_layers"]):
            yield self.layer(i,token_coordinate=token_coordinate,phase=phase)

    def start(self, *, token_coordinate:int=0, phase:str="prefill")->"BoundaryGround":
        self.layer(0,token_coordinate=token_coordinate,phase=phase)
        return BoundaryGround(self,"input",token_coordinate,phase)

    def finish(self, *, token_coordinate:int=0, phase:str="decode")->"BoundaryGround":
        self.layer(0,token_coordinate=token_coordinate,phase=phase)
        return BoundaryGround(self,"output",token_coordinate,phase)

    def order(self, *, token_coordinate:int=0, phase:str="decode")->Iterator["BoundaryGround|LayerGround"]:
        """Lazy whole-model order; inter-frontier state must be receipt-bound at realization."""
        yield self.start(token_coordinate=token_coordinate,phase=phase)
        yield from self.layers(token_coordinate=token_coordinate,phase=phase)
        yield self.finish(token_coordinate=token_coordinate,phase=phase)


@dataclass(frozen=True)
class Stage:
    name:str
    operation:str
    parents:tuple[str,...]
    information:dict[str,Any]

    def to_dict(self)->dict[str,Any]:
        return {"name":self.name,"operation":self.operation,"parents":list(self.parents),"information":self.information}


@dataclass(frozen=True)
class LayerGround:
    model:HFModelGround
    layer_index:int
    token_coordinate:int
    phase:str
    previous_state_digest:str|None=None

    @property
    def digest(self)->str:
        return digest({"model":self.model.descriptor_digest,"layer":self.layer_index,"token":self.token_coordinate,
                       "phase":self.phase,"predecessor":self.previous_state_digest})

    def steps(self)->tuple[Stage,...]:
        """A typed partial order. No router choices, numerical values or effects are fabricated."""
        c=self.model.configuration;family=self.model.family;i=self.layer_index
        stages=[]
        def add(name,op,parents,**info):
            if any(p not in {s.name for s in stages} for p in parents):
                raise HFModelGroundRefused("operation dependency not yet defined")
            stages.append(Stage(name,op,tuple(parents),dict(info)))
        add("input","ground.read_hidden_state",(),previous_state_digest=self.previous_state_digest)
        add("attn_norm","tensor.rms_norm",("input",),epsilon=c["rms_norm_eps"],weight=f"model.layers.{i}.input_layernorm.weight")
        for n in ("q","k","v"):
            add(n,"tensor.linear",("attn_norm",),tensor=f"model.layers.{i}.self_attn.{n}_proj.weight",heads=c["num_attention_heads"] if n=="q" else c["num_key_value_heads"],head_dim=c["head_dim"])
        if family in ("qwen3","qwen3_moe"):
            add("q_norm","tensor.rms_norm",("q",),weight=f"model.layers.{i}.self_attn.q_norm.weight",epsilon=c["rms_norm_eps"])
            add("k_norm","tensor.rms_norm",("k",),weight=f"model.layers.{i}.self_attn.k_norm.weight",epsilon=c["rms_norm_eps"])
            q,k="q_norm","k_norm"
        else:q,k="q","k"
        add("rope","tensor.rope",(q,k),theta=c.get("rope_theta"),rope_scaling=_plain(c.get("rope_scaling")),position=self.token_coordinate)
        add("kv_transition","inference.kv_state_transition",("rope","v"),phase=self.phase,position=self.token_coordinate,layer=i)
        attention_type=self.model.layer_kind(i) if family=="gpt_oss" else ("sliding_attention" if c.get("use_sliding_window") and i>=c.get("max_window_layers",0) else "full_attention")
        window=c.get("sliding_window") if attention_type=="sliding_attention" else None
        add("attention_mask","attention.causal_mask",("kv_transition",),attention_type=attention_type,window=window)
        add("attention","attention.scaled_dot_product",("rope","kv_transition","attention_mask"),head_dim=c["head_dim"],kv_groups=c["num_attention_heads"]//c["num_key_value_heads"],
            attention_sinks=(family=="gpt_oss"),sinks_weight=f"model.layers.{i}.self_attn.sinks" if family=="gpt_oss" else None)
        add("attn_out","tensor.linear",("attention",),tensor=f"model.layers.{i}.self_attn.o_proj.weight")
        add("attn_residual","tensor.add",("input","attn_out"))
        add("mlp_norm","tensor.rms_norm",("attn_residual",),epsilon=c["rms_norm_eps"],weight=f"model.layers.{i}.post_attention_layernorm.weight")
        if family in ("qwen3","qwen3_moe") and self.model.layer_kind(i)=="dense_mlp":
            add("dense_gate","tensor.linear_silu",("mlp_norm",),tensor=f"model.layers.{i}.mlp.gate_proj.weight")
            add("dense_up","tensor.linear",("mlp_norm",),tensor=f"model.layers.{i}.mlp.up_proj.weight")
            add("dense_interaction","tensor.multiply",("dense_gate","dense_up"))
            add("dense_down","tensor.linear",("dense_interaction",),tensor=f"model.layers.{i}.mlp.down_proj.weight")
            tail="dense_down"
        else:
            experts=c["num_experts"] if family=="qwen3_moe" else c["num_local_experts"]
            selected=c["num_experts_per_tok"]
            add("router_logits","moe.router_linear",("mlp_norm",),experts=experts,weight=f"model.layers.{i}.mlp."+("gate.weight" if family=="qwen3_moe" else "router.weight"),bias=family=="gpt_oss")
            if family=="qwen3_moe":
                add("router_probs","moe.softmax_all_experts",("router_logits",),fp32=True)
                add("route_topk","moe.topk_probs",("router_probs",),k=selected)
                add("route_weights","moe.renormalize_selected",("route_topk",),enabled=c["norm_topk_prob"])
            else:
                add("route_topk","moe.topk_logits",("router_logits",),k=selected)
                add("route_weights","moe.softmax_selected_logits",("route_topk",))
            add("expert_inputs","moe.bind_selected_expert_weights",("mlp_norm","route_weights"),
                selection="runtime-dependent; unselected tensors need not be materialized",
                layout="packed-gate-up-and-down" if family=="qwen3_moe" else "mxfp4-packed-with-bias",
                note="tensor binding must verify exact observed checkpoint names, shapes, encoding and available bytes")
            add("expert_eval","moe.evaluate_selected_experts",("expert_inputs",),
                activation="silu_gate_times_up" if family=="qwen3_moe" else "clamp_swiglu_alpha_limit_times_up_plus_one",
                swiglu_limit=c.get("swiglu_limit") if family=="gpt_oss" else None,
                swiglu_alpha=c.get("swiglu_alpha",1.702) if family=="gpt_oss" else None)
            add("expert_reduce","moe.weighted_reduce",("expert_eval","route_weights"))
            tail="expert_reduce"
        add("output","tensor.add",("attn_residual",tail),output="next-layer-hidden-state")
        return tuple(stages)

    def to_dict(self)->dict[str,Any]:
        return {"schema":SCHEMA+".layer", "model_descriptor":self.model.descriptor_digest,
                "layer":self.layer_index,"token_coordinate":self.token_coordinate,"phase":self.phase,
                "previous_state_digest":self.previous_state_digest,"steps":[s.to_dict() for s in self.steps()],
                "semantic_execution_status":"description-only-no-operator-invocations"}

    def compile_ecpu_dag(self)->Any:
        """Use E-CPU's existing bounded DAG, never a new scheduler or execution authority."""
        from .computation_dag import ComputationNode,NavigableComputationDAG
        context=self.digest
        nodes=[ComputationNode(s.name,1,s.operation,"/virtual-layer/operators",context,s.parents,
                    {"schema":SCHEMA+".operation","model":self.model.descriptor_digest,
                     "layer":self.layer_index,"position":self.token_coordinate,"phase":self.phase,
                     "specification":s.information,"execution_status":"not_executed"}) for s in self.steps()]
        return NavigableComputationDAG(nodes)


@dataclass(frozen=True)
class BoundaryGround:
    model:HFModelGround
    kind:str
    token_coordinate:int
    phase:str

    @property
    def digest(self)->str:
        return digest({"model":self.model.descriptor_digest,"kind":self.kind,
                       "token":self.token_coordinate,"phase":self.phase})

    def steps(self)->tuple[Stage,...]:
        def s(name,op,parents=(),**kwargs):return Stage(name,op,tuple(parents),dict(kwargs))
        if self.kind=="input":
            return (
                s("intent","inference.structured_intention"),
                s("template","tokenizer.chat_template",("intent",),identity="requires actual tokenizer/config bytes"),
                s("encode","tokenizer.encode",("template",),vocab_size=self.model.configuration["vocab_size"]),
                s("embed","tensor.embedding_lookup",("encode",),weight="model.embed_tokens.weight"),
                s("coordinates","inference.position_coordinate",("embed",),token_position=self.token_coordinate),
            )
        if self.kind=="output":
            gen=self.model.generation or {}
            return (
                s("input","ground.read_last_layer_output",(),requires="verified layer-state receipt"),
                s("norm","tensor.rms_norm",("input",),weight="model.norm.weight",epsilon=self.model.configuration["rms_norm_eps"]),
                s("logits","tensor.vocab_projection",("norm",),weight="lm_head.weight" if not self.model.configuration["tie_word_embeddings"] else "model.embed_tokens.weight"),
                s("policy","generation.logit_policy",("logits",),generation_config=_plain(gen)),
                s("select","generation.select_token",("policy",),rng="required if stochastic sampling"),
                s("commit","inference.advance_session",("select",),requires="E-CPU committed state lineage"),
                s("stop","generation.stop_or_continue",("commit",),eos_token_id=_plain(gen.get("eos_token_id",self.model.configuration.get("eos_token_id")))),
            )
        raise HFModelGroundRefused("unsupported boundary Ground kind")

    def compile_ecpu_dag(self)->Any:
        from .computation_dag import ComputationNode,NavigableComputationDAG
        nodes=[ComputationNode(item.name,1,item.operation,"/virtual-layer/operators",self.digest,item.parents,
                {"schema":SCHEMA+".boundary-operation","model":self.model.descriptor_digest,
                 "phase":self.phase,"position":self.token_coordinate,"specification":item.information,
                 "execution_status":"not_executed"}) for item in self.steps()]
        return NavigableComputationDAG(nodes)

    def to_dict(self)->dict[str,Any]:
        return {"schema":SCHEMA+".boundary", "model_descriptor":self.model.descriptor_digest,
                "kind":self.kind,"token_coordinate":self.token_coordinate,"phase":self.phase,
                "steps":[x.to_dict() for x in self.steps()],
                "semantic_execution_status":"description-only-no-operator-invocations"}


def _json(path: str)->dict[str,Any]:
    v=json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(v,dict): raise HFModelGroundRefused("file must contain JSON object")
    return v


def main(argv:list[str]|None=None)->int:
    p=argparse.ArgumentParser(description="Observe pinned HF metadata as a navigable E-CPU neural description (not inference)")
    group=p.add_mutually_exclusive_group(required=True)
    group.add_argument("--nsd",help="HFR-001 inspect_huggingface_model JSON")
    group.add_argument("--profiles",help="checked-in pinned config-profile JSON; config-only status")
    p.add_argument("--repository",help="select owner/model when --profiles has several model records")
    p.add_argument("--generation",help="pinned generation_config.json")
    p.add_argument("--tokenizer",help="pinned tokenizer descriptor, if obtained")
    p.add_argument("--layer",type=int,default=0)
    p.add_argument("--token",type=int,default=0)
    p.add_argument("--phase",choices=("prefill","decode"),default="decode")
    p.add_argument("--all-layers",action="store_true",help="report lazy frontier identities without materializing all DAGs")
    args=p.parse_args(argv)
    try:
        if args.nsd:
            model=HFModelGround.from_nsd(_json(args.nsd), generation=_json(args.generation) if args.generation else None,
                                      tokenizer_descriptor=_json(args.tokenizer) if args.tokenizer else None)
        else:
            profiles=_json(args.profiles).get("profiles",[])
            matched=[item for item in profiles if isinstance(item,dict) and item.get("repository")==args.repository]
            if len(matched)!=1:
                raise HFModelGroundRefused("select exactly one pinned profile using --repository")
            item=matched[0]
            model=HFModelGround(item["repository"],item["revision"],item["configuration"],
                              item.get("generation"),tokenizer_descriptor=None)
        if args.all_layers:
            out={"model":model.to_dict(),"model_identity":model.descriptor_digest,
                 "layer_digests":[lay.digest for lay in model.layers(token_coordinate=args.token,phase=args.phase)],
                 "requirements":model.requirements()}
        else:
            layer=model.layer(args.layer,token_coordinate=args.token,phase=args.phase)
            out={"model_identity":model.descriptor_digest,"requirements":model.requirements(),"layer":layer.to_dict()}
        print(json.dumps(out,indent=2,sort_keys=True,allow_nan=False))
    except (HFModelGroundRefused,ValueError,OSError) as exc:
        p.error(str(exc))
    return 0

if __name__=="__main__": raise SystemExit(main())
