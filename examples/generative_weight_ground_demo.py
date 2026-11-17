"""MWS-002 reproducible direct Ground reconstruction over native E-CPU services.

Prints actual content and metadata accounting; not a trained-model result.
Run: python examples/generative_weight_ground_demo.py
"""
from __future__ import annotations

import hashlib
import json
import struct

from mailcpu.computational_objects import ComputationalObjectStore
from mailcpu.law_certifier import Law
from mailcpu.model_weight_ground import ModelParameterSpace, ModelWeightSnapshot, TensorSpace
from mailcpu.generative_weight_ground import (
    GenerativeModelSnapshot, recipe_from_stored, recipe_from_replacements,
    recipe_from_structural_memory,
)
from mailcpu.structural_memory import StructuralMemoryRegistry


class DemoPages:
    page_size = 4096

    def __init__(self):
        self.pages = {}

    def put_page(self, page):
        digest = hashlib.sha256(page).hexdigest()
        self.pages[digest] = page
        return digest

    def get_page(self, digest):
        return self.pages[digest]


def main() -> None:
    store = ComputationalObjectStore(DemoPages())
    size = 32768
    space = ModelParameterSpace("mws002.synthetic.mixed", {"purpose":"synthetic-exact-reconstruction"}, (
        TensorSpace("programmed.bytes", "U8", (size,)),
        TensorSpace("trained.delta", "BF16", (32,)),
    ))
    # The first tensor is deliberately a known law (not a claim about trained weights).
    law = Law("int", {"x0":17, "step":3, "mod":251}, 1, "GROUND")
    expected_program = bytes(law.navigate(i) for i in range(size))
    baseline_delta = bytes((x % 256 for x in range(64)))
    altered_delta = bytearray(baseline_delta)
    altered_delta[18:20] = b"\x55\xaa"  # exact BF16 bits, no rounding
    source = ModelWeightSnapshot.publish_tensors(space, store, {
        "programmed.bytes": expected_program, "trained.delta": baseline_delta,
    })
    target = ModelWeightSnapshot.publish_tensors(space, store, {
        "programmed.bytes": expected_program, "trained.delta": bytes(altered_delta),
    })

    # Receiver-owned admission. The descriptor never admits itself.
    registry = StructuralMemoryRegistry(admission_policy=lambda p:p.spec.domain=="model-weight-byte-law")
    context={"space":space.identity,"tensor":"programmed.bytes","kind":"exact-byte-law"}
    proposal = registry.propose("mws002-demo-byte-law", law,
        {i: law.navigate(i) for i in range(16)}, domain="model-weight-byte-law", context=context)
    version=registry.admit(proposal.proposal_id, expected_revision=0)
    law_route=recipe_from_structural_memory(space,"programmed.bytes",version,registry)
    delta_route=recipe_from_replacements(source,"trained.delta",{9:b"\x55\xaa"},store)
    generated=GenerativeModelSnapshot(space,(law_route,delta_route),target.identity)
    assert generated.verify_all(store=store,sources={source.identity:source},registry=registry)
    assert generated.materialize(store=store,sources={source.identity:source},registry=registry).identity==target.identity
    probe=generated.observe("trained.delta",(9,),store=store,sources={source.identity:source},registry=registry)
    metadata_bytes=len(json.dumps(generated.to_dict(),sort_keys=True,separators=(",", ":")).encode())
    dense_bytes=sum(t.byte_size for t in space.tensors)
    print(json.dumps({
        "schema":"mws002.demonstration.v1",
        "space_digest":space.identity,
        "source_snapshot":source.identity,
        "expected_snapshot":target.identity,
        "reconstructed_snapshot":generated.identity,
        "law_spec_digest":version.spec.digest,
        "law_certificate_digest":version.certificate.digest,
        "tensor_recipe_kinds":[r.kind for r in generated.recipes],
        "selected_parameter_raw_bits":probe["raw_hex"],
        "dense_tensor_bytes":dense_bytes,
        "recipe_description_bytes":metadata_bytes,
        "description_to_dense_ratio":round(metadata_bytes/dense_bytes,4),
        "scope":"synthetic exact bits, not trained LLM inference or storage elimination",
    },sort_keys=True,indent=2))


if __name__=="__main__":
    main()
