"""HFG-002: real numerical Qwen3 layer algebra; fake bytes model local, real Hub only in CI."""
from __future__ import annotations

import copy
import importlib.util
import sys
import types
from dataclasses import dataclass
from hashlib import sha256
import numpy as np
import pytest

from mailcpu.hf_model_ground import HFModelGround, HFR_SCHEMA
from mailcpu.hf_layer_realization import (_required_weights, LayerWeightGround,
    LayerRealizationRefused, realize_attention, realize_mlp, reference_torch,
    evaluate_with_reference,NativeQwen3LayerHost)


@dataclass(frozen=True)
class Manifest:
    size_bytes: int
    content_digest: str
    manifest_digest: str


# Local subset lacks the full E-CPU distribution. The actual CI uses the
# real ComputationalObjectManifest; this shim exists only to test weight math.
if importlib.util.find_spec('mailcpu.computational_objects') is None:
    mod = types.ModuleType('mailcpu.computational_objects')
    mod.ComputationalObjectManifest = Manifest
    sys.modules['mailcpu.computational_objects'] = mod


class LocalPages:
    """A local test backing only; GH execution uses E-CPU's actual object store."""
    def __init__(self):self.data={}
    def put_bytes(self,raw):
        digest=sha256(raw).hexdigest();self.data[digest]=raw
        return Manifest(len(raw),digest,sha256(f'{len(raw)}:{digest}'.encode()).hexdigest())
    def read_range(self,manifest,offset,length):
        b=self.data[manifest.content_digest]
        if sha256(b).hexdigest()!=manifest.content_digest:raise ValueError('content digest tampered')
        return b[offset:offset+length]
    def verify(self,manifest):
        return sha256(self.data[manifest.content_digest]).hexdigest()==manifest.content_digest


def _bits(x):
    y=np.asarray(x,dtype='<f4').view('<u4')
    return (y >> 16).astype('<u2').tobytes()


def example_config():
    return dict(model_type='qwen3', num_hidden_layers=2,hidden_size=16,
        num_attention_heads=4,num_key_value_heads=2,head_dim=4,
        intermediate_size=32,max_position_embeddings=128,vocab_size=80,
        rms_norm_eps=1e-6,rope_theta=10000.0,hidden_act='silu',tie_word_embeddings=True,
        attention_bias=False,attention_dropout=0.0)


def source_observation(*, config=None,source_name='Qwen/Experimental',source_sha='1'*40):
    config=config or example_config()
    # A SYNTHETIC test header; never presented as bytes from Hugging Face.
    mock=HFModelGround(source_name,source_sha,config)
    required=_required_weights(mock,0)
    rng=np.random.default_rng(403)
    data={}
    for name,shape in sorted(required.items()):
        if name.endswith('norm.weight') or 'layernorm.weight' in name:
            w=np.ones(shape,dtype=np.float32)
        else:
            w=rng.standard_normal(shape).astype(np.float32)*np.float32(0.025)
        data[name]=_bits(w)
    cursor=0
    tensors=[]
    for name,raw in sorted(data.items()):
        tensors.append(dict(name=name,dtype='BF16',shape=list(required[name]),
                            shard='model.safetensors',data_offsets=[cursor,cursor+len(raw)],
                            data_bytes=len(raw)))
        cursor+=len(raw)
    nsd={"schema":HFR_SCHEMA,
         "source":{"repository":source_name,"revision":source_sha,"license_id":"test-only"},
         "observed":{"configuration":config,"tensor_manifest":tensors,
                     "files":[{"path":"model.safetensors","role":"safetensors-shard",
                               "sha256":"e"*64,"sha256_scope":"8-byte-prefix-and-header-only",
                               "size_bytes":cursor+8+1024,"header_bytes":1024,"data_bytes":cursor}],
                     "weight_map":{name:'model.safetensors' for name in data}}}
    return nsd,data


def make_binding():
    nsd,payloads=source_observation()
    model=HFModelGround.from_nsd(nsd)
    store=LocalPages()
    return LayerWeightGround.from_payloads(model,0,store,payloads)


def test_qwen3_dense_model_descriptor_has_attention_then_swiglu():
    nsd,_=source_observation()
    model=HFModelGround.from_nsd(nsd)
    assert model.layer_kind(0)=='dense_mlp'
    ops=[x.operation for x in model.layer(0).steps()]
    assert ops.index('tensor.rope')<ops.index('attention.scaled_dot_product')<ops.index('tensor.linear_silu')
    assert 'moe.router_linear' not in ops
    assert model.tensor_address('model.layers.0.self_attn.q_norm.weight')['dtype']=='BF16'
    assert model.to_dict()['weights_fully_verified'] is False


def test_exact_pretrained_subspace_binding_and_raw_bits():
    binding=make_binding()
    assert len(binding.payload_evidence)==11
    assert binding.snapshot.verify_all(binding.store)
    assert binding.snapshot.space.config['ground_descriptor']==binding.model.descriptor_digest
    a=binding.snapshot.observe(binding.store,'model.layers.0.self_attn.q_norm.weight',[0])
    assert a['raw_hex']==_bits([1.0]).hex()
    assert not binding.evidence()['full_model_weights_verified']


def test_full_layer_matches_independent_torch_fp32_bf16_inputs():
    pytest.importorskip('torch')
    binding=make_binding()
    x=np.linspace(-0.25,0.25,48,dtype=np.float32).reshape(3,16)
    result=evaluate_with_reference(binding,x,start_position=4)
    assert result['reference_checked'] and result['layer_math_executed']
    assert result['max_absolute_error']<2e-3
    assert result['input_digest']!=result['result_digest']


def test_attention_is_causal_across_two_tokens():
    binding=make_binding()
    x=np.linspace(-0.3,0.3,48,dtype=np.float32).reshape(3,16)
    first=realize_attention(binding,x)
    changed=x.copy();changed[2,:]+=1.0
    after=realize_attention(binding,changed)
    np.testing.assert_allclose(first[:2],after[:2],atol=1e-6,rtol=1e-6)
    assert not np.allclose(first[2],after[2])


def test_two_stage_mlp_exposes_numeric_output():
    binding=make_binding()
    x=np.ones((2,16),dtype=np.float32)*0.1
    a=realize_attention(binding,x)
    out=realize_mlp(binding,a)
    assert out.shape==x.shape
    assert not np.array_equal(out,x)
    assert not np.array_equal(out,a)


def test_header_shape_tampering_rejected():
    nsd,raw=source_observation()
    damaged=copy.deepcopy(nsd)
    damaged['observed']['tensor_manifest'][0]['shape'][0]+=1
    with pytest.raises(Exception,match='extent|size|shape|byte'):
        LayerWeightGround.from_payloads(HFModelGround.from_nsd(damaged),0,LocalPages(),raw)


def test_source_weight_missing_refused():
    nsd,raw=source_observation()
    raw.pop(next(iter(raw)))
    with pytest.raises(LayerRealizationRefused,match='exact 11-tensor'):
        LayerWeightGround.from_payloads(HFModelGround.from_nsd(nsd),0,LocalPages(),raw)


def test_wrong_model_family_does_not_admit_qwen3_numerical_executor():
    config=example_config();config['model_type']='gpt2'
    with pytest.raises(Exception):HFModelGround('Qwen/Test','2'*40,config)


def test_mismatched_stored_tensor_detected_before_execution():
    binding=make_binding()
    name=next(name for name,_ in binding.snapshot.manifests)
    manifest=binding.snapshot.manifest_for(name)
    binding.store.data[manifest.content_digest]=b'\0'*manifest.size_bytes
    with pytest.raises(ValueError,match='tampered'):
        binding.weight(name.removeprefix('model.layers.0.'))


def test_refuse_non_finite_or_unbounded_input():
    binding=make_binding()
    with pytest.raises(LayerRealizationRefused,match='non-finite'):
        realize_attention(binding,[[float('nan')]*16])
    with pytest.raises(LayerRealizationRefused,match='sequence'):
        realize_attention(binding,np.zeros((17,16),dtype=np.float32))
    with pytest.raises(LayerRealizationRefused,match='position'):
        realize_attention(binding,np.zeros((2,16),dtype=np.float32),start_position=127)


def test_native_mailcpu_authorization_and_dag_integration():
    pytest.importorskip('mailcpu.computation_dag')
    pytest.importorskip('mailcpu.headless')
    pytest.importorskip('mailcpu.virtual_layer')
    binding=make_binding()
    x=np.linspace(-0.1,0.1,32,dtype=np.float32).reshape(2,16)
    report=NativeQwen3LayerHost(binding).execute(x,request_id='native-local-1')
    assert report['dag_complete'] and report['independent_reference_checked']
    assert len(report['stage_receipts'])==2
    with pytest.raises(LayerRealizationRefused,match='Hypervisor'):
        NativeQwen3LayerHost(binding,allow_compute=False).execute(x,request_id='denied-native-2')


def test_hfr_source_evidence_is_bound_to_actual_payload_bits():
    nsd, raw=source_observation()
    ground=HFModelGround.from_nsd(nsd)
    records=[]
    for tensor in nsd['observed']['tensor_manifest']:
        name=tensor['name']
        start,end=tensor['data_offsets']
        records.append({'name':name,'shard':tensor['shard'],'dtype':tensor['dtype'],
                        'shape':tensor['shape'],'size_bytes':len(raw[name]),
                        'payload_sha256':sha256(raw[name]).hexdigest(),
                        'payload_sha256_scope':'complete-selected-tensor-payload',
                        'shard_header_sha256':'e'*64,
                        'absolute_byte_range':[8+1024+start,8+1024+end-1]})
    b=LayerWeightGround.from_payloads(ground,0,LocalPages(),raw,hfr_evidence=records)
    assert b.source_observer_verified
    assert b.evidence()['hfr_source_ranges_verified']
    damaged=copy.deepcopy(records)
    damaged[0]['payload_sha256']='0'*64
    with pytest.raises(LayerRealizationRefused,match='HFR selected tensor evidence'):
        LayerWeightGround.from_payloads(ground,0,LocalPages(),raw,hfr_evidence=damaged)
