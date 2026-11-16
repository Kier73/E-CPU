"""MWS-001: weight-space identity, exact snapshot navigation, refusal tests."""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
import struct

import pytest

from mailcpu.computational_objects import ComputationalObjectStore
from mailcpu.model_weight_ground import (
    ModelParameterSpace, ModelSpaceNavigator, ModelWeightSnapshot, TensorSpace,
    WeightGroundRefused, ingest_safetensors_snapshot,
)


class LocalPages:
    """A plain in-memory E-CPU page-backing test double, not a new runtime store."""
    page_size = 4096

    def __init__(self):
        self.pages = {}

    def put_page(self, page: bytes) -> str:
        digest = sha256(page).hexdigest()
        self.pages[digest] = page
        return digest

    def get_page(self, digest: str) -> bytes:
        return self.pages[digest]


def _store():
    return ComputationalObjectStore(LocalPages())


def _space(model="trained.linear.f32", input_features=3):
    return ModelParameterSpace(model, {"activation": "linear", "input_features": input_features}, (
        TensorSpace("bias", "F32", (2,)),
        TensorSpace("weight", "F32", (2, input_features)),
    ))


def _tensors(scale=1.0, input_features=3):
    weights = [scale * (i + 1) / 8 for i in range(2 * input_features)]
    return {"bias": struct.pack("<ff", 0.25, -0.5),
            "weight": struct.pack("<" + "f" * len(weights), *weights)}


def _safetensors(path, tensors):
    """Write a valid tiny Safetensors artifact from explicit (dtype,shape,bytes) entries."""
    offset, header, body = 0, {}, bytearray()
    for name, (dtype, shape, data) in tensors.items():
        header[name] = {"dtype": dtype, "shape": list(shape), "data_offsets": [offset, offset + len(data)]}
        offset += len(data)
        body.extend(data)
    raw = json.dumps(header, separators=(",", ":")).encode("utf-8")
    path.write_bytes(struct.pack("<Q", len(raw)) + raw + body)


def test_distinct_model_families_are_disjoint_parameter_spaces():
    a, b = _space(), _space(model="other.linear", input_features=4)
    assert a.identity != b.identity
    assert a.to_dict()["tensors"][1]["shape"] == [2, 3]
    assert ModelParameterSpace.from_dict(a.to_dict()).identity == a.identity
    with pytest.raises(WeightGroundRefused, match="sorted"):
        ModelParameterSpace("linear", {}, tuple(reversed(a.tensors)))


def test_snapshot_is_exact_point_independent_of_host_and_page_allocation():
    space, raw = _space(), _tensors()
    store_a, store_b = _store(), _store()
    a = ModelWeightSnapshot.publish_tensors(space, store_a, raw)
    b = ModelWeightSnapshot.publish_tensors(space, store_b, raw)
    assert a.identity == b.identity
    assert a.verify_all(store_a)
    assert b.verify_all(store_b)
    assert ModelWeightSnapshot.from_dict(a.to_dict()).identity == a.identity
    assert a.space.representation_ref().content_digest == b.space.representation_ref().content_digest


def test_navigate_exact_trained_instance_parameter_bits_without_full_model_read():
    space = _space()
    store = _store()
    snapshot = ModelWeightSnapshot.publish_tensors(space, store, _tensors())
    atlas = ModelSpaceNavigator()
    sid = atlas.register_snapshot(snapshot)
    result = atlas.observe(sid, store, "weight", (1, 2))
    assert result["snapshot"] == sid
    assert result["flat_index"] == 5
    assert result["byte_offset"] == 20
    assert struct.unpack("<f", bytes.fromhex(result["raw_hex"]))[0] == pytest.approx(0.75)
    assert result["scope"] == "exact-parameter-bits-not-functional-inference"
    with pytest.raises(WeightGroundRefused, match="budget"):
        snapshot.tensor_raw(store, "weight", max_bytes=4)


def test_snapshot_difference_not_collapsed_to_functional_equivalence():
    store, space = _store(), _space()
    a = ModelWeightSnapshot.publish_tensors(space, store, _tensors(1.0))
    b = ModelWeightSnapshot.publish_tensors(space, store, _tensors(2.0))
    atlas = ModelSpaceNavigator()
    a_id, b_id = atlas.register_snapshot(a), atlas.register_snapshot(b)
    assert a_id != b_id
    assert atlas.same_parameters(a_id, a_id)
    assert not atlas.same_parameters(a_id, b_id)
    assert atlas.observe(b_id, store, "weight", [1, 2])["raw_hex"] != atlas.observe(a_id, store, "weight", [1, 2])["raw_hex"]


def test_model_weight_ground_rejects_incomplete_wrong_shape_and_unknown_snapshot():
    space, store = _space(), _store()
    with pytest.raises(WeightGroundRefused, match="tensor set"):
        ModelWeightSnapshot.publish_tensors(space, store, {"bias": _tensors()["bias"]})
    with pytest.raises(WeightGroundRefused, match="extent"):
        ModelWeightSnapshot.publish_tensors(space, store, {"bias": b"\x00" * 8, "weight": b"\x00" * 12})
    model = ModelWeightSnapshot.publish_tensors(space, store, _tensors())
    with pytest.raises(WeightGroundRefused, match="rank"):
        model.observe(store, "weight", (1,))
    with pytest.raises(WeightGroundRefused, match="outside"):
        model.observe(store, "weight", (1, 3))
    with pytest.raises(WeightGroundRefused, match="tensor is not"):
        model.observe(store, "unknown", (0,))
    with pytest.raises(WeightGroundRefused, match="registered"):
        ModelSpaceNavigator().navigate(model.identity)


def test_reject_tampered_manifest_and_page_payloads():
    store = _store()
    snapshot = ModelWeightSnapshot.publish_tensors(_space(), store, _tensors())
    tampered = deepcopy(snapshot.to_dict())
    tampered["manifests"]["weight"]["content_digest"] = "0" * 64
    with pytest.raises(Exception):
        ModelWeightSnapshot.from_dict(tampered)
    manifest = snapshot.manifest_for("weight")
    first = manifest.chunks[0].page_digest
    store.page_backing.pages[first] = b"\x12" * store.chunk_size
    with pytest.raises(Exception, match="digest"):
        snapshot.observe(store, "weight", (0, 0))


def test_snapshot_identity_refuses_rewritten_even_with_valid_manifest_hashes():
    store = _store()
    a = ModelWeightSnapshot.publish_tensors(_space(), store, _tensors())
    b = ModelWeightSnapshot.publish_tensors(_space(), store, _tensors(2.0))
    tampered = a.to_dict()
    tampered["manifests"]["weight"] = b.manifest_for("weight").to_dict()
    with pytest.raises(WeightGroundRefused, match="identity"):
        ModelWeightSnapshot.from_dict(tampered)


def test_safetensors_single_shard_is_true_content_address(tmp_path):
    tensors = _tensors()
    _safetensors(tmp_path / "model.safetensors", {
        "bias": ("F32", [2], tensors["bias"]),
        "weight": ("F32", [2, 3], tensors["weight"]),
    })
    store = _store()
    snapshot = ingest_safetensors_snapshot(tmp_path, _space(), store)
    assert snapshot.identity == ModelWeightSnapshot.publish_tensors(_space(), store, tensors).identity
    assert snapshot.verify_all(store)
    assert snapshot.tensor_raw(store, "bias") == tensors["bias"]


def test_safetensors_shards_follow_exact_index_and_do_not_cross_values(tmp_path):
    tensors = _tensors()
    _safetensors(tmp_path / "a.safetensors", {"bias": ("F32", [2], tensors["bias"])})
    _safetensors(tmp_path / "b.safetensors", {"weight": ("F32", [2, 3], tensors["weight"])})
    (tmp_path / "model.safetensors.index.json").write_text(json.dumps({
        "weight_map": {"bias": "a.safetensors", "weight": "b.safetensors"}}))
    obj = ingest_safetensors_snapshot(tmp_path, _space(), _store())
    assert obj.space.identity == _space().identity
    assert len(obj.manifests) == 2
    index = tmp_path / "model.safetensors.index.json"
    index.write_text(json.dumps({"weight_map": {"bias": "b.safetensors", "weight": "a.safetensors"}}))
    with pytest.raises(WeightGroundRefused, match="index"):
        ingest_safetensors_snapshot(tmp_path, _space(), _store())


def test_safetensors_rejects_undeclared_type_uncovered_offset_and_wrong_data(tmp_path):
    file = tmp_path / "model.safetensors"
    raw = _tensors()
    _safetensors(file, {"bias": ("BF16", [4], raw["bias"]), "weight": ("F32", [2, 3], raw["weight"])})
    with pytest.raises(WeightGroundRefused, match="geometry"):
        ingest_safetensors_snapshot(tmp_path, _space(), _store())
    _safetensors(file, {"bias": ("F32", [2], raw["bias"]), "weight": ("F32", [2, 3], raw["weight"])})
    file.write_bytes(file.read_bytes() + b"\xFF")
    with pytest.raises(WeightGroundRefused, match="unexplained"):
        ingest_safetensors_snapshot(tmp_path, _space(), _store())


def test_safetensors_bf16_retains_exact_bits_and_does_not_infer_float_semantics(tmp_path):
    space = ModelParameterSpace("bf16.tiny", {"purpose": "raw-bits"},
                                (TensorSpace("w", "BF16", (2,)),))
    raw = b"\x80\x3f\x00\x7f"  # exact little-endian representations
    _safetensors(tmp_path / "model.safetensors", {"w": ("BF16", [2], raw)})
    store = _store()
    snapshot = ingest_safetensors_snapshot(tmp_path, space, store)
    assert snapshot.observe(store, "w", (0,))["raw_hex"] == "803f"
    assert snapshot.observe(store, "w", (1,))["raw_hex"] == "007f"


def test_parameter_space_scalar_and_refusal_for_unknown_packing():
    tensor = TensorSpace("scalar", "F64", ())
    assert tensor.flat_index(()) == 0
    with pytest.raises(WeightGroundRefused, match="unsupported"):
        TensorSpace("quant", "Q4_K", (4096,))
    with pytest.raises(WeightGroundRefused, match="nonnegative"):
        TensorSpace("negative", "F32", (-2,))


def test_persistent_identity_is_independent_of_page_size():
    space = _space()
    a = ModelWeightSnapshot.publish_tensors(space, _store(), _tensors())
    class OtherBacking(LocalPages):
        page_size = 8192
    b = ModelWeightSnapshot.publish_tensors(space, ComputationalObjectStore(OtherBacking()), _tensors())
    assert a.identity == b.identity
    assert a.manifest_for("weight").manifest_digest != b.manifest_for("weight").manifest_digest


def test_large_parameter_space_exists_without_materializing_weights():
    # Parametric address space; this does not claim the payload is available.
    space = ModelParameterSpace("hypothetical.moe-235b", {"head_dim": 128},
                                (TensorSpace("expert.bank", "BF16", (235_000_000_000,)),))
    assert space.tensor("expert.bank").byte_size == 470_000_000_000
    assert len(space.identity) == 64
    assert ModelParameterSpace.from_dict(space.to_dict()).identity == space.identity


def test_architecture_metadata_cannot_mutate_after_identity():
    space = _space()
    first = space.identity
    with pytest.raises(TypeError):
        space.config["input_features"] = 999
    assert space.identity == first


def test_duplicate_safetensors_keys_are_refused(tmp_path):
    # json.loads would normally silently retain only the latter duplicate.
    header = b'{"w":{"dtype":"BF16","shape":[1],"data_offsets":[0,2]},"w":{"dtype":"BF16","shape":[1],"data_offsets":[0,2]}}'
    (tmp_path / "model.safetensors").write_bytes(struct.pack("<Q", len(header)) + header + b"\0\0")
    space = ModelParameterSpace("tiny", {}, (TensorSpace("w", "BF16", (1,)),))
    with pytest.raises(WeightGroundRefused, match="duplicate"):
        ingest_safetensors_snapshot(tmp_path, space, _store())
