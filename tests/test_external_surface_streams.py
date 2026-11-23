"""HSS-002: structure-only remote observation, no model-shard acquisition.

The same read-only virtual processor operates on arbitrary model families and
huge external byte extents. Its outputs are structural Ground positions,
not synthetic neural inference or newly acquired model tensors.
"""
from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys

import pytest

from mailcpu.external_virtual_structure import (
    HTTPSMetadataObserver, MetadataNavigator, MetadataObservation,
    RemoteFile, SourceStructure, StructureRefused, VirtualRead,
    compile_virtual_read, metadata_url, project_browser_addresses, source_page,
)

REPO="deepseek-ai/DeepSeek-V4.1-Flash-1017"
PAGE="https://huggingface.co/"+REPO+"/tree/main"
REV="08c8657f02291e11b6f6b63e0e16014f8e748518"
ROOT="https://huggingface.co/api/models/"+REPO


def encode(value):
    return json.dumps(value,sort_keys=True,separators=(",",":")).encode()


class ModelMetadataOnly:
    """Fake remote metadata API with NO operation to retrieve model bytes."""
    def __init__(self,family="deepseek_v41",shards=48,extent=10**10):
        self.calls=[]
        self.model_info={"sha":REV,"config":{
            "model_type":family,"num_hidden_layers":128,
            "num_experts":256,"hidden_size":4096}}
        self.files=[
            {"path":"config.json","type":"file","size":1200},
            {"path":"tokenizer.json","type":"file","size":500000},
            {"path":"inference","type":"directory"},
            {"path":"inference/custom_kernel.py","type":"file","size":33000},
        ]+[
            {"path":f"model-{i:05d}-of-{shards:05d}.safetensors",
             "type":"file","size":extent+i,
             "lfs":{"sha256":f"{i:064x}"}}
            for i in range(1,shards+1)
        ]
    def read_metadata(self,url):
        assert url.startswith("https://huggingface.co/api/models/")
        assert "/resolve/" not in url
        self.calls.append(url)
        if url==ROOT or url==ROOT+"/revision/"+REV:
            return MetadataObservation(encode(self.model_info))
        if url==ROOT+"/tree/"+REV+"?recursive=true":
            return MetadataObservation(encode(self.files[:27]),{
                "link":f'<{ROOT}/tree/{REV}?recursive=true&cursor=27>; rel="next"'})
        if url==ROOT+"/tree/"+REV+"?recursive=true&cursor=27":
            return MetadataObservation(encode(self.files[27:]))
        raise AssertionError("undeclared metadata source: "+url)


def surface(**kwargs):
    observer=ModelMetadataOnly(**kwargs)
    tree=MetadataNavigator(observer).discover(PAGE)
    return tree,observer


def test_48_huge_external_model_shards_are_virtualized_from_three_metadata_observations():
    tree,observer=surface()
    assert tree.repository==REPO and tree.revision==REV
    assert tree.config["model_type"]=="deepseek_v41"
    assert len(tree.files)==51
    assert tree.declared_bytes>480*10**9
    assert len(observer.calls)==3
    assert all("/api/models/" in url and "/resolve/" not in url for url in observer.calls)
    assert SourceStructure.restore(tree.to_dict(),tree.ground_digest)==tree
    # Large payload: the hosted model has not been copied, partially or entirely.
    assert not hasattr(observer,"fetch") and not hasattr(observer,"read_range")


@pytest.mark.parametrize("name",[
    "deepseek_v41","qwen3","llama","mamba","audio","diffusion","unseen_type",
])
def test_any_model_type_has_same_source_structural_interpreter(name):
    tree,observer=surface(family=name)
    a=compile_virtual_read(tree,"source.architecture")
    assert a.to_dict()["result"]["observed_configuration"]["model_type"]==name
    b=compile_virtual_read(tree,"source.layer",{"index":127})
    assert b.to_dict()["result"]["declared_layers"]==128
    assert b.to_dict()["model_payload_bytes"]==0
    assert len(observer.calls)==3
    assert VirtualRead.restore(tree,b.to_dict(),b.digest).digest==b.digest


def test_source_extent_is_an_address_not_a_range_read_even_at_huge_offsets():
    tree,observer=surface(extent=10**27)
    model="model-00001-of-00048.safetensors"
    position=compile_virtual_read(
        tree,"source.extent",{"path":model,"offset":10**25,"length":10**21})
    result=position.to_dict()["result"]
    assert result["model_payload_bytes_read"]==0
    assert result["offset"]==10**25 and result["length"]==10**21
    assert tree.declared_bytes>10**28
    assert len(observer.calls)==3
    assert result["address"].endswith("/"+model)
    assert VirtualRead.restore(tree,position.to_dict(),position.digest).digest==position.digest


def test_virtual_reads_are_reconstructable_from_only_description_on_new_python_process():
    tree,observer=surface(extent=10**18)
    original=compile_virtual_read(tree,"source.file",{
        "path":"model-00017-of-00048.safetensors"})
    script=(
        "import json,sys;"
        "from mailcpu.external_virtual_structure import SourceStructure,VirtualRead;"
        "v=json.loads(sys.stdin.read());"
        "s=SourceStructure.restore(v['structure'],v['source_head']);"
        "p=VirtualRead.restore(s,v['position'],v['position_head']);"
        "print(json.dumps({'head':p.digest,'result':p.to_dict()['result']}))"
    )
    input_doc={
        "structure":tree.to_dict(),"source_head":tree.ground_digest,
        "position":original.to_dict(),"position_head":original.digest,
    }
    result=subprocess.run([sys.executable,"-c",script],input=json.dumps(input_doc),
                          text=True,capture_output=True,timeout=30,check=True)
    reconstruction=json.loads(result.stdout)
    assert reconstruction["head"]==original.digest
    assert reconstruction["result"]==original.to_dict()["result"]
    assert len(observer.calls)==3


def test_structural_read_is_actual_source_determined_computation():
    tree,_=surface()
    cat=compile_virtual_read(tree,"source.catalogue")
    info=cat.to_dict()
    assert info["result"]["files"]==51
    assert info["result"]["file_extensions"]["safetensors"]==48
    assert info["model_payload_reads"]==0
    assert [f["kind"] for f in info["frames"]]==[
        "ground.source","ground.intention","ground.realization"]
    assert info["frames"][2]["predecessor"]==info["frames"][1]["head"]
    assert VirtualRead.restore(tree,info,cat.digest).digest==cat.digest


def test_forged_coordinate_revision_index_or_control_frame_refused():
    tree,_=surface()
    original=compile_virtual_read(tree,"source.file",{"path":"config.json"})
    before=original.to_dict()
    for mutation in [
        {"result":dict(before["result"],declared_size_bytes=999)},
        {"source_head":"f"*64},
        {"frames":list(reversed(before["frames"]))},
        {"operation":"source.catalogue"},
    ]:
        corrupted=copy.deepcopy(before)
        corrupted.update(mutation)
        with pytest.raises(StructureRefused):
            VirtualRead.restore(tree,corrupted,original.digest)
    invalid=copy.deepcopy(tree.to_dict())
    invalid["revision"]="f"*40
    with pytest.raises(StructureRefused):
        SourceStructure.restore(invalid,tree.ground_digest)
    with pytest.raises(StructureRefused,match="exceeds"):
        compile_virtual_read(tree,"source.extent",{
            "path":"config.json","offset":1150,"length":100})
    with pytest.raises(StructureRefused,match="absent"):
        compile_virtual_read(tree,"source.file",{"path":"missing.safetensors"})


def test_no_source_payload_transport_operation_exists():
    observer=HTTPSMetadataObserver()
    for forbidden in [
        f"https://huggingface.co/{REPO}/resolve/main/model.safetensors",
        f"https://huggingface.co/api/models/{REPO}/resolve/main/shard",
        "http://huggingface.co/api/models/x/y",
        "https://localhost/api/models/x/y",
        "https://huggingface.co.evil.test/api/models/x/y",
    ]:
        with pytest.raises(StructureRefused):
            metadata_url(forbidden)
    assert not hasattr(observer,"fetch") and not hasattr(observer,"fetch_range")
    assert not hasattr(observer,"download") and not hasattr(observer,"read_bytes")


def test_browser_is_an_optional_remote_address_observer_not_a_data_loader():
    record=project_browser_addresses(PAGE,[
        f"/{REPO}/tree/main",f"/{REPO}/tree/main",
        "javascript:alert(1)","https://evil.example/download",
    ],origin="huggingface.co")
    assert record["addresses"]==[PAGE]
    assert record["model_payload_bytes"]==0
    with pytest.raises(StructureRefused):
        project_browser_addresses("http://localhost/page",[],origin="localhost")


def test_unknown_neural_math_cannot_be_inferred_from_source_addresses():
    tree,_=surface()
    with pytest.raises(StructureRefused):
        compile_virtual_read(tree,"model.forward",{"input":"hello"})
    with pytest.raises(StructureRefused):
        compile_virtual_read(tree,"source.extent",{
            "path":"model-00001-of-00048.safetensors","offset":0,"length":0})
    with pytest.raises(StructureRefused):
        compile_virtual_read(tree,"source.layer",{"index":128})
    no_config=SourceStructure(tree.repository,tree.revision,tree.files,{})
    with pytest.raises(StructureRefused,match="not source-declared"):
        compile_virtual_read(no_config,"source.layer",{"index":0})


def test_interpretation_cost_is_independent_of_declared_payload_size():
    modest,_=surface(extent=2**20)
    massive,_=surface(extent=2**100)
    task={"path":"model-00001-of-00048.safetensors",
          "offset":64,"length":4096}
    a=compile_virtual_read(modest,"source.extent",task)
    b=compile_virtual_read(massive,"source.extent",task)
    assert len(a.to_dict()["frames"])==len(b.to_dict()["frames"])==3
    assert a.to_dict()["model_payload_bytes"]==b.to_dict()["model_payload_bytes"]==0
    assert a.to_dict()["result"]["offset"]==b.to_dict()["result"]["offset"]==64
    assert massive.declared_bytes>2**100
    assert modest.declared_bytes<2**40


def test_metadata_refusal_on_wrong_revision_duplicate_file_or_paginated_escape():
    fake=ModelMetadataOnly()
    fake.model_info["sha"]="f"*40
    with pytest.raises(StructureRefused,match="revision"):
        MetadataNavigator(fake).discover("https://huggingface.co/"+REPO+"/tree/"+REV)
    duplicate=ModelMetadataOnly()
    duplicate.files.append(dict(duplicate.files[0],size=999))
    with pytest.raises(StructureRefused,match="contradictory"):
        MetadataNavigator(duplicate).discover(PAGE)
    with pytest.raises(StructureRefused,match="revision"):
        source_page("https://huggingface.co/"+REPO+"/tree/development")


def test_external_source_structural_read_executes_through_original_ecpu_hypervisor():
    """Original native VL runs the hosted source Ground under an admitted OS."""
    from mailcpu import (
        Capability, HeadlessOS, HypervisorAction, HypervisorPolicy,
        LexicalDecisionModel, OperatorRegistry, SystemIdentity, SystemSeed,
        SystemSeedEnvelope, VirtualBudget, VirtualGroundRef,
        VirtualLayerRuntime, VirtualLayerWorkload, VirtualOperatorRef,
    )
    from mailcpu.external_virtual_runtime import (
        OPERATOR_ID, register_virtual_structure,
    )
    structure, metadata = surface(extent=10**27)
    os = HeadlessOS()
    os.hypervisor.classifier = LexicalDecisionModel()
    os.hypervisor.policy = HypervisorPolicy(embedding_review_confidence=1.0)
    identity = SystemIdentity("hosted-source-virtual-interpreter", 1)
    envelope = SystemSeedEnvelope(identity, "executor", "virtual-layer",
                                  SystemSeed.from_system(os))
    assert os.seed_admission.admit(envelope).accepted
    ground = VirtualGroundRef.from_envelope(envelope)
    registry = OperatorRegistry()
    spec = register_virtual_structure(registry, structure)
    runtime = VirtualLayerRuntime(registry, "node-a", frozenset({"cpu"}))
    work = VirtualLayerWorkload(
        workload_id="hosted-deepseek-structural-read-001", system=identity,
        ground=ground, intention={"goal": "locate external model file without moving it"},
        operators=(VirtualOperatorRef(OPERATOR_ID, 1, "cpu"),),
        input_value={
            "source_head":structure.ground_digest,"operation":"source.extent",
            "arguments":{
                "path":"model-00001-of-00048.safetensors",
                "offset":10**25,"length":10**21,
            },
        },
        budget=VirtualBudget(30000, 30000, 100),
        logical_time=17, eligible_nodes=("node-a",),
    )
    pid=os.environment.kernel.spawn(
        "virtual-structure-interpreter",
        capabilities=(Capability("/virtual-layer/operators",
                                 frozenset({"compute"})),),
        parent_pid=os.environment.init_pid,
    )
    first=runtime.execute_operator(
        os,pid,"origin","virtual-layer",1,17,work,OPERATOR_ID,
    )
    assert first.action is HypervisorAction.ALLOW
    assert first.executed
    assert first.effect["kind"]=="virtual_layer.operator_result"
    result=first.effect["result"]
    assert result["model_payload_reads"]==0
    assert result["result"]["offset"]==10**25
    assert result["result"]["length"]==10**21
    assert result["source_head"]==structure.ground_digest
    assert result["position_digest"]==compile_virtual_read(
        structure,"source.extent",work.input_value["arguments"]).digest
    repeat=runtime.execute_operator(
        os,pid,"origin","virtual-layer",1,17,work,OPERATOR_ID,
    )
    assert repeat.replayed and repeat.effect==first.effect
    # Native Hypervisor remains the authority, not the external website.
    limited=os.environment.kernel.spawn(
        "unauthorized-external-structure",
        capabilities=(Capability("/safe",frozenset({"read"})),),
        parent_pid=os.environment.init_pid,
    )
    denied=runtime.execute_operator(
        os,limited,"origin","virtual-layer",2,17,work,OPERATOR_ID,
    )
    assert denied.action is HypervisorAction.DENY
    assert not denied.executed
    assert len(metadata.calls)==3
    assert os.environment.kernel.journal.verify()


def test_native_operator_registry_rebinds_description_on_replacement_host():
    """The new observer accepts only the same source and source-local handler."""
    from mailcpu import OperatorRegistry, VirtualLayerError
    from mailcpu.external_virtual_runtime import OPERATOR_ID, register_virtual_structure
    source,_ = surface()
    receiver=OperatorRegistry()
    register_virtual_structure(receiver,source)
    snapshot=receiver.snapshot()
    recovered=OperatorRegistry.from_snapshot(snapshot)
    assert recovered.digest==receiver.digest
    with pytest.raises(VirtualLayerError,match="trusted local implementation"):
        recovered.resolve(OPERATOR_ID,1)
    # The replacement host must install its own approved function.
    restored=SourceStructure.restore(source.to_dict(),source.ground_digest)
    new=OperatorRegistry()
    spec=register_virtual_structure(new,restored)
    assert new.digest==receiver.digest
    assert spec.digest==receiver.contract(OPERATOR_ID,1).digest
    handler=new.resolve(OPERATOR_ID,1)[1]
    correct={
        "source_head":source.ground_digest,"operation":"source.layer",
        "arguments":{"index":127},
    }
    position=handler(correct,None)
    assert position["result"]["declared_layers"]==128
    with pytest.raises(StructureRefused,match="differs"):
        handler({**correct,"source_head":"f"*64},None)
