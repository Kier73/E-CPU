"""Demonstrate two exact 10,000-parameter neural instances in one weight Ground.

This uses existing E-CPU weight compilation, content-addressed page storage,
and model-weight Ground coordinates. These are hand-constructed Boolean models,
not pretrained frontier-model checkpoints or a universal training-state oracle.
"""
from __future__ import annotations

from hashlib import sha256
import json
import struct

from mailcpu.computational_objects import ComputationalObjectStore
from mailcpu.model_weight_ground import ModelParameterSpace, ModelWeightSnapshot, ModelSpaceNavigator, TensorSpace
from mailcpu.weight_space import DenseReLUNetwork, compile_boolean_gate, edit_boolean_gate


class DemoPageBacking:
    page_size = 4096

    def __init__(self):
        self._pages: dict[str, bytes] = {}

    def put_page(self, page: bytes) -> str:
        key = sha256(page).hexdigest()
        self._pages[key] = page
        return key

    def get_page(self, key: str) -> bytes:
        return self._pages[key]


def family_for(model: DenseReLUNetwork) -> ModelParameterSpace:
    specs = []
    for layer, (input_width, output_width) in enumerate(zip(model.architecture[:-1], model.architecture[1:])):
        specs.extend((TensorSpace(f"layer.{layer}.bias", "F64", (output_width,)),
                      TensorSpace(f"layer.{layer}.weight", "F64", (output_width, input_width))))
    return ModelParameterSpace("mailcpu.weight-space.relu", {
        "activation": "relu-hidden-linear-output", "architecture": list(model.architecture),
        "layout": "output-major", "value_encoding": "IEEE-754 F64 little-endian",
    }, tuple(sorted(specs, key=lambda s: s.name)))


def tensors_for(model: DenseReLUNetwork) -> dict[str, bytes]:
    payload = {}
    for idx, (weights, biases) in enumerate(zip(model.weights, model.biases)):
        flat = [v for row in weights for v in row]
        payload[f"layer.{idx}.weight"] = struct.pack("<" + "d" * len(flat), *flat)
        payload[f"layer.{idx}.bias"] = struct.pack("<" + "d" * len(biases), *biases)
    return payload


def restore_model(snapshot: ModelWeightSnapshot, store: ComputationalObjectStore, gate: str) -> DenseReLUNetwork:
    """Materialize the bounded demo; the Ground API itself can read individual bytes."""
    dims = snapshot.space.config["architecture"]
    weights = []
    biases = []
    for layer, (input_width, output_width) in enumerate(zip(dims[:-1], dims[1:])):
        raw_w = snapshot.tensor_raw(store, f"layer.{layer}.weight", max_bytes=1 << 20)
        raw_b = snapshot.tensor_raw(store, f"layer.{layer}.bias", max_bytes=1 << 20)
        flat = struct.unpack("<" + "d" * (input_width * output_width), raw_w)
        biases.append(struct.unpack("<" + "d" * output_width, raw_b))
        weights.append([list(flat[i*input_width:(i+1)*input_width]) for i in range(output_width)])
    return DenseReLUNetwork(weights, biases, compiled_gate=gate, architecture=dims)


def main() -> dict:
    store = ComputationalObjectStore(DemoPageBacking())
    model = compile_boolean_gate("xor")
    family = family_for(model)
    original = ModelWeightSnapshot.publish_tensors(family, store, tensors_for(model))
    intervention = edit_boolean_gate(model, "and")
    edited = ModelWeightSnapshot.publish_tensors(family, store, tensors_for(model))
    assert intervention.changed_parameters == 2
    assert family.identity == original.space.identity == edited.space.identity
    assert original.identity != edited.identity
    nav = ModelSpaceNavigator()
    nav.register_snapshot(original)
    nav.register_snapshot(edited)
    before = restore_model(ModelWeightSnapshot.from_dict(original.to_dict()), store, "xor")
    after = restore_model(ModelWeightSnapshot.from_dict(edited.to_dict()), store, "and")
    inputs = ((0,0),(0,1),(1,0),(1,1))
    assert all(before.predict(*bits) == bits[0] ^ bits[1] for bits in inputs)
    assert all(after.predict(*bits) == bits[0] & bits[1] for bits in inputs)
    i = len(model.architecture) - 2
    coord = (0, 0)
    first = nav.observe(original.identity, store, f"layer.{i}.weight", coord)
    last = nav.observe(edited.identity, store, f"layer.{i}.weight", coord)
    report = {
        "schema": "mailcpu.model-weight-ground-demo.v1",
        "architecture_ground": family.identity,
        "snapshots": {"xor": original.identity, "and": edited.identity},
        "parameter_count": model.parameter_count,
        "edited_coordinates": [x.to_dict() for x in intervention.coordinates],
        "sampled_parameter_before": first["raw_hex"],
        "sampled_parameter_after": last["raw_hex"],
        "full_domain_checked": len(inputs),
        "backing_resident_pages": len(store.page_backing._pages),
        "scope": "exact-bounded-Boolean-model-snapshots; no pretrained-weight or universal-equivalence claim",
    }
    return report


if __name__ == "__main__":
    print(json.dumps(main(), indent=2, sort_keys=True))
