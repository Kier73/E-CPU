"""MWS-002: exact recipe reconstruction, tamper refusal and non-equivalence cases."""
from __future__ import annotations

from dataclasses import replace
import copy
from hashlib import sha256
import itertools
import struct

import pytest

from mailcpu.computational_objects import ComputationalObjectStore
from mailcpu.model_weight_ground import ModelParameterSpace, ModelWeightSnapshot, TensorSpace
from mailcpu.generative_weight_ground import (
    GenerativeGroundRefused, GenerativeModelSnapshot, TensorRecipe,
    recipe_from_replacements, recipe_from_reindex, recipe_from_stored,
    recipe_from_structural_memory, select_exact_recipe,
)


class Pages:
    page_size = 4096

    def __init__(self):
        self.pages = {}

    def put_page(self, raw):
        digest = sha256(raw).hexdigest()
        self.pages[digest] = raw
        return digest

    def get_page(self, digest):
        return self.pages[digest]


def _store():
    return ComputationalObjectStore(Pages())


def _space():
    return ModelParameterSpace("example.linear", {"input": 4, "output": 3}, (
        TensorSpace("bias", "F32", (3,)),
        TensorSpace("weight", "F32", (3, 4)),
    ))


def _tensor_values():
    return {"bias": struct.pack("<3f", 0.25, 0.5, -1.0),
            "weight": struct.pack("<12f", *(float(x) / 4 for x in range(12)))}


def _snapshot(store, *, target=False):
    data = _tensor_values()
    if target:
        w = bytearray(data["weight"])
        w[5 * 4:6 * 4] = struct.pack("<f", 25.0)
        data["weight"] = bytes(w)
    return ModelWeightSnapshot.publish_tensors(_space(), store, data)


def _gen(source, target, store):
    bias = recipe_from_stored(source, "bias", store, chunk_size=16)
    patch = recipe_from_replacements(source, "weight", {5: struct.pack("<f", 25.0)}, store, chunk_size=16)
    return GenerativeModelSnapshot(_space(), (bias, patch), target.identity)


def test_sparse_edit_reconstructs_exact_snapshot_identity_and_bits():
    store = _store()
    source, target = _snapshot(store), _snapshot(store, target=True)
    gen = _gen(source, target, store)
    sources = {source.identity: source}
    assert gen.identity == target.identity
    assert gen.verify_all(store=store, sources=sources)
    assert gen.read_range("weight", 15, 9, store=store, sources=sources) == target.tensor_raw(store, "weight")[15:24]
    value = gen.observe("weight", (1, 1), store=store, sources=sources)
    assert value["raw_hex"] == struct.pack("<f", 25).hex()
    assert value["model_snapshot"] == target.identity
    materialized = gen.materialize(store=store, sources=sources)
    assert materialized.identity == target.identity
    assert materialized.tensor_raw(store, "weight") == target.tensor_raw(store, "weight")
    assert len(gen.to_dict().__repr__()) < 6000  # recipe does not contain dense weights


def test_generator_record_roundtrip_preserves_exact_target_identity():
    store = _store()
    source, target = _snapshot(store), _snapshot(store, target=True)
    gen = _gen(source, target, store)
    restored = GenerativeModelSnapshot.from_dict(gen.to_dict())
    assert restored.identity == target.identity
    assert restored.observe("weight", (1, 1), store=store, sources={source.identity: source}) == gen.observe(
        "weight", (1, 1), store=store, sources={source.identity: source})
    assert all(TensorRecipe.from_dict(r.to_dict()).identity == r.identity for r in gen.recipes)


def test_wrong_snapshot_identity_is_refused_instead_of_relabelled_as_trained_instance():
    store = _store()
    source, target = _snapshot(store), _snapshot(store, target=True)
    gen = _gen(source, target, store)
    with pytest.raises(GenerativeGroundRefused, match="trained-instance identity"):
        GenerativeModelSnapshot(gen.space, gen.recipes, source.identity)


def test_wrong_model_architecture_and_missing_tensor_are_refused():
    store = _store()
    source, target = _snapshot(store), _snapshot(store, target=True)
    gen = _gen(source, target, store)
    with pytest.raises(GenerativeGroundRefused, match="missing a declared tensor"):
        GenerativeModelSnapshot(gen.space, gen.recipes[:1], gen.identity)
    different = ModelParameterSpace("other.architecture", {}, gen.space.tensors)
    with pytest.raises(GenerativeGroundRefused, match="parameter space|model Ground|tensor coordinate"):
        GenerativeModelSnapshot(different, gen.recipes, gen.identity)


def test_forged_recipe_digest_and_changed_patch_are_refused():
    store = _store()
    source, target = _snapshot(store), _snapshot(store, target=True)
    gen = _gen(source, target, store)
    payload = gen.to_dict()
    tampered = copy.deepcopy(payload)
    tampered["recipes"][1]["body"]["edits"][0][1] = struct.pack("<f", 24).hex()
    with pytest.raises(GenerativeGroundRefused, match="recipe digest"):
        GenerativeModelSnapshot.from_dict(tampered)
    # Even a recomputed recipe digest cannot silently change the target identity
    changed = recipe_from_replacements(source, "weight", {5: struct.pack("<f", 24.0)}, store, chunk_size=16)
    with pytest.raises(GenerativeGroundRefused, match="trained-instance identity"):
        GenerativeModelSnapshot(gen.space, (gen.recipes[0], changed), gen.expected_identity)


def test_recipe_refuses_missing_source_replaced_pages_or_wrong_snapshot_source():
    store = _store()
    source, target = _snapshot(store), _snapshot(store, target=True)
    gen = _gen(source, target, store)
    with pytest.raises(GenerativeGroundRefused, match="source snapshot"):
        gen.verify_all(store=store, sources={})
    manifest = source.manifest_for("weight")
    store.page_backing.pages[manifest.chunks[0].page_digest] = bytes(store.chunk_size)
    with pytest.raises(Exception, match="digest"):
        gen.observe("weight", (1, 1), store=store, sources={source.identity: source})


def test_replacements_reject_duplicate_unbounded_wrong_width_and_no_op():
    store, source = _store(), None
    source = _snapshot(store)
    with pytest.raises(GenerativeGroundRefused, match="wrong exact element"):
        recipe_from_replacements(source, "weight", {0: b"\x00"}, store)
    with pytest.raises(GenerativeGroundRefused, match="outside tensor"):
        recipe_from_replacements(source, "weight", {99: struct.pack("<f", 1)}, store)
    with pytest.raises(GenerativeGroundRefused, match="no-op"):
        recipe_from_replacements(source, "weight", {0: struct.pack("<f", 0)}, store)
    with pytest.raises(GenerativeGroundRefused, match="strict integers"):
        recipe_from_replacements(source, "weight", {True: struct.pack("<f", 1)}, store)


def test_explicit_read_budget_and_hash_checked_materialization():
    store = _store()
    source, target = _snapshot(store), _snapshot(store, target=True)
    gen = _gen(source, target, store)
    with pytest.raises(GenerativeGroundRefused, match="budget"):
        gen.read_range("weight", 0, 48, store=store, sources={source.identity: source}, max_bytes=20)
    with pytest.raises(GenerativeGroundRefused, match="outside"):
        gen.read_range("weight", 49, 1, store=store, sources={source.identity: source})
    tampered = copy.deepcopy(gen.to_dict())
    tampered["recipes"][1]["chunk_digests"][0] = "0" * 64
    with pytest.raises(GenerativeGroundRefused, match="recipe digest"):
        GenerativeModelSnapshot.from_dict(tampered)


def test_reindex_is_exact_coordinate_navigation_not_automatic_functional_equivalence():
    store = _store()
    space = ModelParameterSpace("tiny.relu", {"activation": "relu"}, (
        TensorSpace("hidden.bias", "F32", (3,)),
        TensorSpace("hidden.weight", "F32", (3, 2)),
        TensorSpace("output.weight", "F32", (1, 3)),
    ))
    tensors = {
        "hidden.bias": struct.pack("<3f", 0, 1, 2),
        "hidden.weight": struct.pack("<6f", 1, 0, 0, 2, 1, 1),
        "output.weight": struct.pack("<3f", 3, 5, 7),
    }
    original = ModelWeightSnapshot.publish_tensors(space, store, tensors)
    p = (2, 0, 1)  # output position -> original position
    routes = (
        recipe_from_reindex(original, "hidden.bias", 0, p, store),
        recipe_from_reindex(original, "hidden.weight", 0, p, store),
        recipe_from_reindex(original, "output.weight", 1, p, store),
    )
    # An independently published snapshot of the same intended permutation.
    expected = {
        "hidden.bias": struct.pack("<3f", 2, 0, 1),
        "hidden.weight": struct.pack("<6f", 1, 1, 1, 0, 0, 2),
        "output.weight": struct.pack("<3f", 7, 3, 5),
    }
    target = ModelWeightSnapshot.publish_tensors(space, store, expected)
    generated = GenerativeModelSnapshot(space, routes, target.identity)
    assert generated.verify_all(store=store, sources={original.identity: original})
    assert generated.materialize(store=store, sources={original.identity: original}).identity == target.identity
    # This equality depends on compensating all connected tensors, and holds
    # only for this declared finite test (not every neural architecture).
    def run(weights):
        a = struct.unpack("<6f", weights["hidden.weight"])
        b = struct.unpack("<3f", weights["hidden.bias"])
        o = struct.unpack("<3f", weights["output.weight"])
        return tuple(sum(o[i] * max(0.0, a[2*i]*x + a[2*i+1]*y + b[i])
                         for i in range(3)) for x,y in itertools.product((0,1), repeat=2))
    assert run(tensors) == run(expected)
    bad = dict(expected)
    bad["output.weight"] = tensors["output.weight"]
    assert run(tensors) != run(bad)  # uncompensated permutation is not equivalent
    with pytest.raises(GenerativeGroundRefused, match="bijection"):
        recipe_from_reindex(original, "hidden.bias", 0, (0, 0, 1), store)


def test_recipe_selection_refuses_mixed_targets_and_reports_description_only():
    store = _store()
    source, target = _snapshot(store), _snapshot(store, target=True)
    patch = recipe_from_replacements(source, "weight", {5: struct.pack("<f", 25.0)}, store, chunk_size=16)
    same = TensorRecipe.from_dict(patch.to_dict())
    assert select_exact_recipe([patch, same]).identity == patch.identity
    with pytest.raises(GenerativeGroundRefused, match="different model instances"):
        select_exact_recipe([patch, recipe_from_stored(source, "weight", store, chunk_size=16)])
    with pytest.raises(GenerativeGroundRefused, match="budget"):
        select_exact_recipe([patch], max_recipe_bytes=10)


def test_law_source_requires_existing_registered_exact_revision():
    # A stub models *only* the external registry interface; the real registry
    # integration test below checks HeadlessOS's actual admission semantics.
    from types import SimpleNamespace
    class FakeRegistry:
        def read_revision_range(self, memory_id, revision, coordinate_start, count):
            receipt = SimpleNamespace(memory_id=memory_id, revision=revision,
                spec_digest="a"*64, certificate_digest="b"*64, context_digest="c"*64,
                coordinate_start=coordinate_start, length=count)
            return tuple((17 + 3 * n) % 251 for n in range(coordinate_start, coordinate_start+count)), receipt, ()
    registry = FakeRegistry()
    version = SimpleNamespace(spec=SimpleNamespace(memory_id="weight.bytes", revision=1, family="int",
        digest="a"*64, context_digest="c"*64),
        certificate=SimpleNamespace(digest="b"*64))
    space = ModelParameterSpace("model.gen", {}, (TensorSpace("w", "BF16", (16,)),))
    expected_bytes = bytes((17 + 3 * i) % 251 for i in range(32))
    store = _store()
    baseline = ModelWeightSnapshot.publish_tensors(space, store, {"w":expected_bytes})
    recipe = recipe_from_structural_memory(space,"w",version,registry,chunk_size=8)
    gen = GenerativeModelSnapshot(space,(recipe,),baseline.identity)
    assert gen.verify_all(store=store,registry=registry)
    assert gen.observe("w",(3,),store=store,registry=registry)["raw_hex"] == expected_bytes[6:8].hex()
    with pytest.raises(GenerativeGroundRefused, match="Structural Memory registry"):
        gen.observe("w",(3,),store=store)
    class FakeTampered(FakeRegistry):
        def read_revision_range(self,*args):
            vals, receipt, ids = super().read_revision_range(*args)
            receipt.spec_digest = "f"*64
            return vals, receipt, ids
    with pytest.raises(GenerativeGroundRefused, match="source identity"):
        gen.observe("w",(3,),store=store,registry=FakeTampered())


def test_native_structural_memory_admission_and_revision_pinned_law():
    pytest.importorskip("mailcpu.structural_memory")
    from mailcpu.structural_memory import StructuralMemoryRegistry
    from mailcpu.law_certifier import Law
    store = _store()
    space = ModelParameterSpace("real.admitted.byte.generator", {}, (TensorSpace("w", "U8", (24,)),))
    law = Law("lcg", {"a": 5,"c":1,"mod":256,"x0":31}, 1, "GROUND")
    registry = StructuralMemoryRegistry(admission_policy=lambda p: p.spec.domain == "model-weight-byte-law")
    context = {"purpose": "exact-byte-weight-ground", "space_digest": space.identity, "tensor": "w"}
    proposal = registry.propose("model-weight-gen-001", law, {i:law.navigate(i) for i in range(12)},
                                domain="model-weight-byte-law", context=context)
    version = registry.admit(proposal.proposal_id, expected_revision=0)
    expected = bytes(law.navigate(i) for i in range(24))
    target = ModelWeightSnapshot.publish_tensors(space, store, {"w":expected})
    recipe = recipe_from_structural_memory(space,"w",version,registry,chunk_size=8)
    gen = GenerativeModelSnapshot(space,(recipe,),target.identity)
    assert gen.verify_all(store=store,registry=registry)
    assert gen.materialize(store=store,registry=registry).identity == target.identity
    # A second admitted revision must not silently redirect a pinned recipe.
    revised = registry.propose_context_revision("model-weight-gen-001", {**context,"epoch": 2},
                                               {i:law.navigate(i) for i in range(12)})
    registry.admit(revised.proposal_id, expected_revision=1)
    assert gen.verify_all(store=store,registry=registry)


def test_native_unadmitted_law_refused_even_with_correct_formula():
    pytest.importorskip("mailcpu.structural_memory")
    from mailcpu.structural_memory import StructuralMemoryRegistry
    from mailcpu.law_certifier import Law
    space = ModelParameterSpace("refused-law", {}, (TensorSpace("w", "U8", (4,)),))
    law = Law("int", {"x0":3,"step":1,"mod":256}, 1,"GROUND")
    registry = StructuralMemoryRegistry(admission_policy=lambda proposal: False)
    proposal = registry.propose("not-admitted",law,{0:3,1:4,2:5,3:6})
    with pytest.raises(Exception,match="admission|policy|authorize"):
        registry.admit(proposal.proposal_id,expected_revision=0)
    # A staged proposal never has a committed revision to read.
    from types import SimpleNamespace
    version = SimpleNamespace(spec=proposal.spec,certificate=proposal.certificate)
    with pytest.raises(Exception,match="admitted|no admitted"):
        recipe_from_structural_memory(space,"w",version,registry,chunk_size=4)


def test_long_tensor_law_description_is_compact_and_random_access_is_exact():
    """A synthetic 128 KiB tensor tests addressability, not trained-model compressibility."""
    from types import SimpleNamespace
    spec = SimpleNamespace(memory_id="law-large",revision=1,family="int",
                           digest="a"*64,context_digest="b"*64)
    version = SimpleNamespace(spec=spec, certificate=SimpleNamespace(digest="c"*64))
    class BoundedRegistry:
        def read_revision_range(self,memory_id,revision,start,count):
            assert 0 < count <= 65536
            receipt = SimpleNamespace(memory_id=memory_id,revision=revision,
                coordinate_start=start,length=count,spec_digest=spec.digest,
                certificate_digest=version.certificate.digest,context_digest=spec.context_digest)
            return tuple((3*i+19)%251 for i in range(start,start+count)),receipt,()
    reg=BoundedRegistry()
    length=128*1024
    space=ModelParameterSpace("synthetic.law.large",{},(TensorSpace("w","U8",(length,)),))
    store=_store()
    expected=bytes((3*i+19)%251 for i in range(length))
    oracle=ModelWeightSnapshot.publish_tensors(space,store,{"w":expected})
    recipe=recipe_from_structural_memory(space,"w",version,reg,chunk_size=4096)
    generated=GenerativeModelSnapshot(space,(recipe,),oracle.identity)
    assert len(str(generated.to_dict()).encode()) < length//10
    for i in [0,1,4095,4096,4097,length-1]:
        assert generated.observe("w",(i,),store=store,registry=reg)["raw_hex"]==expected[i:i+1].hex()
    assert generated.materialize(store=store,registry=reg).identity == oracle.identity


def test_target_can_be_reconstructed_when_its_pages_were_never_stored_on_receiver():
    receiver_store = _store()
    independent_oracle_store = _store()
    source = _snapshot(receiver_store)
    target = _snapshot(independent_oracle_store, target=True)
    assert target.identity != source.identity
    assert target.manifest_for("weight").chunks[0].page_digest not in receiver_store.page_backing.pages
    gen = _gen(source, target, receiver_store)
    restored = gen.materialize(store=receiver_store, sources={source.identity: source})
    assert restored.identity == target.identity
    assert restored.tensor_raw(receiver_store, "weight") == target.tensor_raw(independent_oracle_store, "weight")
