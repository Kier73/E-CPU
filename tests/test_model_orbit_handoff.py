"""HFG-003: portable state identity/continuation. Local tests do not attest a remote observer."""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import numpy as np
import pytest

from mailcpu.computational_objects import ComputationalObjectStore
from mailcpu.hf_model_ground import HFModelGround, HFR_SCHEMA
from mailcpu.hf_layer_realization import (
    LayerWeightGround, _required_weights, _array_digest, realize_attention,
    realize_mlp, evaluate_with_reference,
)
from mailcpu.model_orbit_handoff import (
    ModelOrbitRefused, publish_layer_handoff, resume_model_orbit, _digest,
)


class Pages:
    page_size = 4096
    def __init__(self, pages=None): self.pages = {} if pages is None else dict(pages)
    def put_page(self, value: bytes) -> str:
        h=sha256(value).hexdigest();self.pages[h] = value;return h
    def get_page(self, identity: str) -> bytes: return self.pages[identity]


def _encode_bf16(value):
    x=np.asarray(value,dtype='<f4')
    return (x.view('<u4') >> 16).astype('<u2').tobytes()


def fixture():
    config=dict(model_type='qwen3',num_hidden_layers=3,hidden_size=16,
                num_attention_heads=4,num_key_value_heads=2,head_dim=4,
                intermediate_size=32,max_position_embeddings=128,vocab_size=80,
                rms_norm_eps=1e-6,rope_theta=10000.,hidden_act='silu',
                tie_word_embeddings=True,attention_bias=False,attention_dropout=0.)
    mock=HFModelGround('Kier73/LocalSynthetic','a'*40,config)
    rng=np.random.default_rng(732)
    raw,metadata={},[]
    cursor=0
    for layer in range(3):
        for name,shape in sorted(_required_weights(mock,layer).items()):
            if 'norm.weight' in name or 'layernorm.weight' in name:
                values=np.ones(shape,dtype='<f4')
            else:
                values=rng.normal(0,0.025,shape).astype('<f4')
            bits=_encode_bf16(values)
            raw[name]=bits
            metadata.append({'name':name,'dtype':'BF16','shape':list(shape),
                             'shard':'model.safetensors','data_offsets':[cursor,cursor+len(bits)],
                             'data_bytes':len(bits)})
            cursor+=len(bits)
    nsd={'schema':HFR_SCHEMA,
         'source':{'repository':mock.repository,'revision':mock.revision,'license_id':'test-only'},
         'observed':{'configuration':config,'tensor_manifest':metadata,
                     'files':[{'path':'model.safetensors','role':'safetensors-shard',
                               'sha256':'e'*64,'sha256_scope':'8-byte-prefix-and-header-only',
                               'size_bytes':cursor+8+1024,'header_bytes':1024,'data_bytes':cursor}],
                     'weight_map':{k:'model.safetensors' for k in raw}}}
    return HFModelGround.from_nsd(nsd),raw


def setup():
    model,raw=fixture()
    weightstore=ComputationalObjectStore(Pages())
    bindings=[LayerWeightGround.from_payloads(model,i,weightstore,
                    {k:raw[k] for k in _required_weights(model,i)}) for i in range(3)]
    state_store=ComputationalObjectStore(Pages())
    hidden=np.linspace(-.2,.2,32,dtype=np.float32).reshape(2,16)
    return model,bindings,state_store,hidden


def emit(binding,hidden,state_store, *, parent=None):
    # Unit-level issuer fixture. Actual native Hypervisor receipt is separately
    # REQUIRED by the GH workflow integration test; this synthetic receipt is
    # not claimed to be a proof of native E-CPU authorization.
    numeric=evaluate_with_reference(binding,hidden)
    out=realize_mlp(binding,realize_attention(binding,hidden))
    assert _array_digest(out)==numeric['result_digest']
    synthetic={
      'schema':'mailcpu.hfg002.qwen3-layer.v1.native-receipt',
      'model_ground':binding.model.descriptor_digest,
      'layer_ground':binding.identity,'weight_snapshot':binding.snapshot.identity,
      'input_digest':_array_digest(hidden),'output_digest':_array_digest(out),
      'independent_reference_checked':True,'dag_complete':True,
      'layer_math_executed':True,'synthetic_fixture_only':True,
    }
    state=publish_layer_handoff(binding,out,synthetic,state_store,
                                predecessor_state_digest=parent)
    return state,out,synthetic


def consume(model,state,producer,state_store,next_layer, *,parent=None):
    return resume_model_orbit(state,state_store,model=model,expected_next_layer=next_layer,
      expected_state_digest=state['state_digest'],
      expected_native_receipt_digest=_digest(producer),expected_predecessor_digest=parent)


def test_two_layer_continuation_after_original_observer_exits():
    model,bindings,original,hidden=setup()
    state0,numeric0,receipt0=emit(bindings[0],hidden,original)
    # The next executor begins with a new object store and a separately copied
    # M1 backing; no reference to the previous host's resident numpy arrays.
    replacement=ComputationalObjectStore(Pages(original.page_backing.pages))
    resumed=consume(model,state0,receipt0,replacement,1)
    np.testing.assert_array_equal(resumed,numeric0)
    state1,numeric1,receipt1=emit(bindings[1],resumed,replacement,parent=state0['state_digest'])
    final=consume(model,state1,receipt1,replacement,2,parent=state0['state_digest'])
    np.testing.assert_array_equal(final,numeric1)
    assert state1['model_descriptor']==state0['model_descriptor']
    assert state1['predecessor_state_digest']==state0['state_digest']
    assert state1['completed_layer']==1


def test_state_contains_one_hidden_tensor_not_entire_checkpoint_or_model():
    model,bindings,store,hidden=setup()
    state,output,receipt=emit(bindings[0],hidden,store)
    assert state['sequence_length']==2
    assert state['hidden_width']==16
    assert state['object_manifest']['size_bytes']==128
    assert state['model_descriptor']==model.descriptor_digest
    assert state['native_receipt_digest']==_digest(receipt)
    assert state['output_digest']==sha256(output.astype('<f4').tobytes()).hexdigest()
    assert all('weight' not in k or k=='weight_snapshot' for k in state)


def test_refuses_stale_external_head_even_when_record_is_internally_consistent():
    model,bindings,store,hidden=setup();state,_,receipt=emit(bindings[0],hidden,store)
    with pytest.raises(ModelOrbitRefused,match='high-water'):
        resume_model_orbit(state,store,model=model,expected_next_layer=1,
          expected_state_digest='a'*64,expected_native_receipt_digest=_digest(receipt))


def test_refuses_wrong_model_and_wrong_layer():
    model,bindings,store,hidden=setup();state,_,receipt=emit(bindings[0],hidden,store)
    different=HFModelGround('Kier73/Other','b'*40,dict(model.configuration))
    with pytest.raises(ModelOrbitRefused,match='model Ground identity'):
        consume(different,state,receipt,store,1)
    with pytest.raises(ModelOrbitRefused,match='layer coordinate'):
        consume(model,state,receipt,store,2)


def test_refuses_missing_or_replaced_pages_even_when_record_matches():
    model,bindings,store,hidden=setup();state,_,receipt=emit(bindings[0],hidden,store)
    chunk=state['object_manifest']['chunks'][0]['page_digest']
    store.page_backing.pages[chunk]=bytes(store.chunk_size)
    with pytest.raises(Exception,match='digest|mismatch'):
        consume(model,state,receipt,store,1)


def test_refuses_rehashed_record_when_other_observer_pins_original_head():
    model,bindings,store,hidden=setup();state,_,receipt=emit(bindings[0],hidden,store)
    changed=deepcopy(state);changed['layer_ground']='b'*64
    changed['state_digest']=_digest({k:v for k,v in changed.items() if k!='state_digest'})
    with pytest.raises(ModelOrbitRefused,match='high-water'):
        resume_model_orbit(changed,store,model=model,expected_next_layer=1,
           expected_state_digest=state['state_digest'],expected_native_receipt_digest=_digest(receipt))


def test_refuses_incorrect_output_digest_or_byte_geometry():
    model,bindings,store,hidden=setup();state,_,receipt=emit(bindings[0],hidden,store)
    bad=deepcopy(state);bad['sequence_length']=3
    bad['state_digest']=_digest({k:v for k,v in bad.items() if k!='state_digest'})
    with pytest.raises(ModelOrbitRefused,match='extent'):
        consume(model,bad,receipt,store,1)


def test_refuses_claimed_auth_without_native_metadata():
    model,bindings,store,hidden=setup()
    output=realize_mlp(bindings[0],realize_attention(bindings[0],hidden))
    with pytest.raises(ModelOrbitRefused,match='native layer verification'):
        publish_layer_handoff(bindings[0],output,{'output_digest':_array_digest(output)},store)


def test_refuses_changed_native_receipt_and_predecessor_lineage():
    model,bindings,store,hidden=setup();state,_,receipt=emit(bindings[0],hidden,store)
    with pytest.raises(ModelOrbitRefused,match='external evidence'):
        resume_model_orbit(state,store,model=model,expected_next_layer=1,
          expected_state_digest=state['state_digest'],expected_native_receipt_digest='a'*64)
    with pytest.raises(ModelOrbitRefused,match='predecessor lineage'):
        consume(model,state,receipt,store,1,parent='b'*64)


def test_state_decoder_rejects_extra_unknown_and_malformed_fields():
    model,bindings,store,hidden=setup();state,_,receipt=emit(bindings[0],hidden,store)
    wrong=deepcopy(state);wrong['unknown']='not authorized'
    with pytest.raises(ModelOrbitRefused,match='invalid fields'):
        consume(model,wrong,receipt,store,1)


def test_native_operator_output_sink_is_used_after_verified_dag():
    # Required on hosted CI, where the real HeadlessOS/Hypervisor exists.
    import mailcpu
    if not hasattr(mailcpu,'HeadlessOS'):
        pytest.skip('Native MailCPU is absent from this local isolated source tree')
    model,bindings,store,hidden=setup()
    from mailcpu.hf_layer_realization import NativeQwen3LayerHost
    outcome=NativeQwen3LayerHost(bindings[0]).execute(hidden,request_id='hfg003-native',
      output_sink=lambda tensor,receipt:publish_layer_handoff(bindings[0],tensor,receipt,store))
    assert outcome['dag_complete']
    exported=outcome['portable_output']
    recovered=resume_model_orbit(exported,store,model=model,expected_next_layer=1,
      expected_state_digest=exported['state_digest'],
      expected_native_receipt_digest=exported['native_receipt_digest'])
    assert _array_digest(recovered)==outcome['output_digest']


def test_lazy_layer_addresses_do_not_require_a_specific_host_or_full_model_allocations():
    """Metadata addressability is not numerical execution; no layer tensor allocated."""
    model,_=fixture()
    config=dict(model.configuration)
    config['num_hidden_layers']=94
    large=HFModelGround('Kier73/HypotheticalLarge','c'*40,config)
    target=large.layer(93,token_coordinate=57)
    assert target.layer_index==93
    assert large.layer_kind(93)=='dense_mlp'
    assert len(tuple(large.layers(token_coordinate=57)))==94
    assert large.to_dict()['inference_executed'] is False
