"""HFG-001: source-pinned architectural and fail-closed Ground planning tests."""
from __future__ import annotations
import copy
import json
from pathlib import Path
import pytest
from mailcpu.hf_model_ground import HFModelGround, HFModelGroundRefused, HFR_SCHEMA, digest

PROFILE = Path(__file__).resolve().parents[1] / "examples" / "hf_pinned_model_configs.json"
DATA = json.loads(PROFILE.read_text())


def model(repo):
    item = next(i for i in DATA["profiles"] if i["repository"] == repo)
    return HFModelGround(item["repository"], item["revision"], copy.deepcopy(item["configuration"]), item.get("generation"))


def test_source_observation_is_explicitly_config_only():
    m = model("Qwen/Qwen3-235B-A22B")
    assert m.observation_scope == "config_only"
    assert not m.to_dict()["weights_fully_verified"]
    assert not m.to_dict()["inference_executed"]
    assert m.requirements()["weight_payload"].startswith("not acquired")
    assert len(m.revision)==40


def test_235b_is_lazy_and_size_independent():
    m = model("Qwen/Qwen3-235B-A22B")
    steps = m.layer(93,token_coordinate=17).steps()
    assert len(steps) < 256
    assert m.configuration["num_hidden_layers"] == 94
    assert m.configuration["num_experts"] == 128
    assert m.configuration["num_experts_per_tok"] == 8
    assert len(tuple(m.layers())) == 94
    assert sum(len(p.steps()) for p in m.order()) == 2080
    assert steps[-1].name == "output"


def test_30b_and_235b_share_law_but_not_instance_identity():
    small = model("Qwen/Qwen3-30B-A3B")
    large = model("Qwen/Qwen3-235B-A22B")
    assert small.descriptor_digest != large.descriptor_digest
    assert small.family == large.family == "qwen3_moe"
    assert len(tuple(small.layers())) == 48


def test_qwen_routing_order_is_softmax_all_then_topk_then_renorm():
    m=model("Qwen/Qwen3-235B-A22B")
    stages={s.name:s for s in m.layer(1).steps()}
    assert stages["router_probs"].operation == "moe.softmax_all_experts"
    assert stages["router_probs"].parents == ("router_logits",)
    assert stages["route_topk"].parents == ("router_probs",)
    assert stages["route_weights"].parents == ("route_topk",)
    assert stages["expert_inputs"].information["selection"].startswith("runtime-dependent")
    assert stages["q_norm"].operation=="tensor.rms_norm"
    assert stages["k_norm"].operation=="tensor.rms_norm"


def test_gptoss_router_is_different_and_interleaves_sliding_full():
    m=model("openai/gpt-oss-120b")
    a={s.name:s for s in m.layer(0).steps()}
    b={s.name:s for s in m.layer(1).steps()}
    assert m.family == "gpt_oss"
    assert a["attention_mask"].information["attention_type"] == "sliding_attention"
    assert a["attention_mask"].information["window"] == 128
    assert b["attention_mask"].information["attention_type"] == "full_attention"
    assert b["attention_mask"].information["window"] is None
    assert "q_norm" not in a
    assert a["route_topk"].operation == "moe.topk_logits"
    assert a["route_weights"].operation == "moe.softmax_selected_logits"
    assert a["attention"].information["attention_sinks"] is True
    assert a["expert_eval"].information["swiglu_alpha"] == 1.702
    assert len(tuple(m.layers()))==36


def test_model_end_to_end_order_has_no_eager_whole_model_dag():
    m=model("Qwen/Qwen3-235B-A22B")
    order=m.order(token_coordinate=34,phase="decode")
    first=next(order)
    assert first.kind=="input"
    assert first.steps()[1].operation=="tokenizer.chat_template"
    layer=next(order)
    assert layer.layer_index==0
    remaining=list(order)
    assert remaining[-1].kind=="output"
    assert remaining[-1].steps()[-1].operation=="generation.stop_or_continue"
    assert sum(getattr(x,"kind",None)=="output" for x in remaining)==1


def test_generator_keeps_input_configuration_snapshot_detached():
    item = next(i for i in DATA["profiles"] if i["repository"]=="Qwen/Qwen3-235B-A22B")
    conf=copy.deepcopy(item["configuration"])
    m=HFModelGround(item["repository"],item["revision"],conf)
    old=m.descriptor_digest
    conf["num_hidden_layers"]=1
    assert m.descriptor_digest==old
    assert m.configuration["num_hidden_layers"]==94


def test_unknown_family_and_missing_semantics_refuse():
    item=next(i for i in DATA["profiles"] if i["repository"]=="openai/gpt-oss-120b")
    config=copy.deepcopy(item["configuration"])
    config["model_type"]="new_future_model"
    with pytest.raises(HFModelGroundRefused,match="not yet semantically compiled"):
        HFModelGround(item["repository"],item["revision"],config)
    config=copy.deepcopy(item["configuration"])
    config["layer_types"]=config["layer_types"][:-1]
    with pytest.raises(HFModelGroundRefused,match="attention types"):
        HFModelGround(item["repository"],item["revision"],config)
    config=copy.deepcopy(item["configuration"])
    config["quantization_config"]={"quant_method":"fake"}
    with pytest.raises(HFModelGroundRefused,match="quantized"):
        HFModelGround(item["repository"],item["revision"],config)


def test_invalid_revision_positions_and_precision_are_rejected():
    m=model("Qwen/Qwen3-30B-A3B")
    with pytest.raises(HFModelGroundRefused,match="layer coordinate"):
        m.layer(1000)
    with pytest.raises(HFModelGroundRefused,match="token coordinate"):
        m.layer(0,token_coordinate=-1)
    with pytest.raises(HFModelGroundRefused,match="beyond"):
        m.layer(0,token_coordinate=m.configuration["max_position_embeddings"])
    with pytest.raises(HFModelGroundRefused,match="pinned"):
        HFModelGround(m.repository,"main",m.configuration)


def _fake_nsd(m):
    return {"schema":HFR_SCHEMA,"source":{"repository":m.repository,"revision":m.revision},
            "observed":{"configuration":m.to_dict()["configuration"],
                        "files":[{"path":"model.safetensors","role":"safetensors-shard","sha256_scope":"8-byte-prefix-and-header-only","sha256":"f"*64,"size_bytes":72,"data_bytes":48,"header_bytes":16}],
                        "weight_map":{"model.embed_tokens.weight":"model.safetensors","model.layers.0.self_attn.q_proj.weight":"model.safetensors"},
                        "tensor_manifest":[
                            {"name":"model.embed_tokens.weight","dtype":"BF16","shape":[2,3],"shard":"model.safetensors","data_offsets":[0,12],"data_bytes":12},
                            {"name":"model.layers.0.self_attn.q_proj.weight","dtype":"BF16","shape":[6,3],"shard":"model.safetensors","data_offsets":[12,48],"data_bytes":36}]}}


def test_hfr_headers_bind_tensor_shapes_but_not_weight_bytes():
    source=model("Qwen/Qwen3-235B-A22B")
    nsd=_fake_nsd(source)
    m=HFModelGround.from_nsd(nsd)
    assert m.observation_scope=="hfr_header_observed"
    assert len(m.tensor_inventory)==2
    assert not m.to_dict()["weights_fully_verified"]
    assert m.descriptor_digest != source.descriptor_digest
    location=m.tensor_address("model.embed_tokens.weight")
    assert location["offset_after_safetensors_header"]==0
    assert location["header_digest"]=="f"*64
    assert location["parameter_bytes_verified"] is False


def test_hfr_missing_shard_or_forged_offsets_rejected():
    m=model("Qwen/Qwen3-235B-A22B")
    x=_fake_nsd(m)
    x["observed"]["tensor_manifest"][0]["data_offsets"]=[1,13]
    with pytest.raises(HFModelGroundRefused,match="overlap|extent"):
        HFModelGround.from_nsd(x)
    x=_fake_nsd(m)
    x["observed"]["files"]=[]
    with pytest.raises(HFModelGroundRefused,match="header-verified"):
        HFModelGround.from_nsd(x)
    x=_fake_nsd(m)
    x["observed"]["weight_map"]["model.layers.0.self_attn.q_proj.weight"]="other.safetensors"
    with pytest.raises(HFModelGroundRefused,match="weight index"):
        HFModelGround.from_nsd(x)


def test_header_missing_exact_tensor_refuses():
    m=HFModelGround.from_nsd(_fake_nsd(model("Qwen/Qwen3-235B-A22B")))
    with pytest.raises(HFModelGroundRefused,match="not present"):
        m.tensor_address("model.layers.30.mlp.experts.gate_up_proj")


def test_model_descriptor_is_immutable_after_ground_construction():
    m=model("Qwen/Qwen3-235B-A22B")
    before=m.descriptor_digest
    with pytest.raises(TypeError):
        m.configuration["num_hidden_layers"] = 0
    assert m.descriptor_digest==before


def test_router_selection_never_invented_from_config():
    m=model("openai/gpt-oss-120b")
    d=m.layer(0).to_dict()
    expert=next(s for s in d["steps"] if s["name"]=="expert_inputs")
    assert "runtime-dependent" in expert["information"]["selection"]
    assert d["semantic_execution_status"]=="description-only-no-operator-invocations"


def test_dag_operations_have_canonical_dependency_order():
    m=model("Qwen/Qwen3-235B-A22B")
    steps=m.layer(0).steps()
    known=set()
    for s in steps:
        assert all(dep in known for dep in s.parents)
        known.add(s.name)
    assert len(known)==len(steps)


def test_generation_config_is_source_pinned_not_inferred():
    m=model("Qwen/Qwen3-235B-A22B")
    out={s.name:s for s in m.finish().steps()}
    assert out["policy"].information["generation_config"]["top_k"]==20
    assert out["policy"].information["generation_config"]["temperature"]==0.6
    assert out["select"].information["rng"]=="required if stochastic sampling"


def test_native_ecpu_dag_is_a_description_not_an_execution():
    pytest.importorskip("mailcpu.computation_dag")
    m=model("Qwen/Qwen3-235B-A22B")
    dag=m.layer(0).compile_ecpu_dag()
    assert len(dag.nodes)==len(m.layer(0).steps())
    assert len(dag.ready_nodes())==1
    assert not dag.is_complete()
    assert dag.committed_nodes==()
    assert m.start().compile_ecpu_dag().ready_nodes()
    assert m.finish().compile_ecpu_dag().ready_nodes()


def test_config_must_not_be_a_virtual_inference_claim():
    m=model("openai/gpt-oss-120b")
    assert m.requirements()["operator_semantics"].startswith("requires")
    assert len(m.order().__iter__().__next__().steps()) > 0


def test_all_family_plans_can_be_canonically_serialized():
    for item in DATA["profiles"]:
        m=HFModelGround(item["repository"],item["revision"],item["configuration"],item.get("generation"))
        json.dumps(m.layer(0).to_dict(),allow_nan=False)
        json.dumps(m.start().to_dict(),allow_nan=False)
        json.dumps(m.finish().to_dict(),allow_nan=False)
