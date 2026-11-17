"""HFG-003: a model-layer state remains addressable after its observer-host exits.

The numerical operator is HFG-002, source identity is HFG-001, and byte storage is
M1 ComputationalObjectStore. This module creates no scheduler, storage layer,
recovery quorum, or operator authority. Digests are integrity pins, NOT remote
identity attestations. A trusted caller must supply an external expected head.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from .computational_objects import ComputationalObjectManifest, ComputationalObjectStore
from .hf_layer_realization import LayerWeightGround, LayerRealizationRefused, _array_digest
from .hf_model_ground import HFModelGround

SCHEMA = "mailcpu.hfg003.model-orbit-handoff.v1"
FIELDS = frozenset({
    "schema", "model_descriptor", "repository", "revision", "completed_layer",
    "next_layer", "start_position", "sequence_length", "hidden_width", "dtype",
    "input_digest", "output_digest", "weight_snapshot", "layer_ground",
    "native_receipt_digest", "predecessor_state_digest", "object_manifest", "state_digest",
})


class ModelOrbitRefused(ValueError):
    """A model, state coordinate, predecessor, byte object or receipt is invalid."""


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ModelOrbitRefused("state is not finite canonical JSON") from exc


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _digest(value: Any) -> str:
    return _sha(_canonical(value))


def _hex(value: Any, name: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise ModelOrbitRefused(f"{name} must be an exact SHA-256 digest")
    return value


def _int(value: Any, name: str, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise ModelOrbitRefused(f"{name} must be a strict integer >= {minimum}")
    return value


def _record(record: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(record, Mapping) or set(record) != FIELDS:
        raise ModelOrbitRefused("portable Ground state has invalid fields")
    result = json.loads(_canonical(dict(record)))
    if result["schema"] != SCHEMA or result["dtype"] != "F32LE":
        raise ModelOrbitRefused("unsupported portable Ground state format")
    for field in ("model_descriptor", "output_digest", "input_digest", "weight_snapshot",
                  "layer_ground", "native_receipt_digest", "state_digest"):
        _hex(result[field], field)
    if result["predecessor_state_digest"] is not None:
        _hex(result["predecessor_state_digest"], "predecessor_state_digest")
    for field in ("completed_layer", "next_layer", "start_position", "sequence_length", "hidden_width"):
        _int(result[field], field, 1 if field in ("sequence_length", "hidden_width") else 0)
    if result["next_layer"] != result["completed_layer"] + 1:
        raise ModelOrbitRefused("nonadjacent model layer transition")
    if not isinstance(result["repository"], str) or not isinstance(result["revision"], str):
        raise ModelOrbitRefused("model source is malformed")
    if _digest({k:v for k,v in result.items() if k!="state_digest"}) != result["state_digest"]:
        raise ModelOrbitRefused("portable state digest does not match the complete record")
    manifest = ComputationalObjectManifest.from_dict(result["object_manifest"])
    if manifest.size_bytes != result["sequence_length"] * result["hidden_width"] * 4:
        raise ModelOrbitRefused("tensor object extent differs from declared F32 state")
    if manifest.content_digest != result["output_digest"]:
        raise ModelOrbitRefused("object manifest contradicts committed neural output")
    return result


def publish_layer_handoff(binding: LayerWeightGround, output: Any, native_receipt: Mapping[str, Any],
                          store: ComputationalObjectStore, *, position: int = 0,
                          predecessor_state_digest: str | None = None) -> dict[str, Any]:
    """Persist a *verified* native layer output as a receiver-neutral M1 state.

    Called from the receiving process AFTER its authorized operator and reference
    check. A serialized caller-supplied receipt is never an authority grant.
    """
    import numpy as np
    model = binding.model
    layer = binding.layer_index
    if not isinstance(store, ComputationalObjectStore):
        raise ModelOrbitRefused("existing E-CPU ComputationalObjectStore required")
    if not isinstance(native_receipt, Mapping) or (
        native_receipt.get("schema") != "mailcpu.hfg002.qwen3-layer.v1.native-receipt"
        or native_receipt.get("independent_reference_checked") is not True
        or native_receipt.get("dag_complete") is not True
        or native_receipt.get("layer_math_executed") is not True
        or native_receipt.get("model_ground") != model.descriptor_digest
        or native_receipt.get("layer_ground") != binding.identity
        or native_receipt.get("weight_snapshot") != binding.snapshot.identity
    ):
        raise ModelOrbitRefused("a complete native layer verification receipt is required")
    x = np.asarray(output, dtype="<f4")
    if (x.ndim != 2 or x.shape[1] != model.configuration["hidden_size"]
            or not 1 <= len(x) <= 16 or not np.isfinite(x).all()):
        raise ModelOrbitRefused("portable hidden state shape or values are invalid")
    if _array_digest(x) != native_receipt.get("output_digest"):
        raise ModelOrbitRefused("native numerical output is not bound to its receipt")
    if type(position) is not int or position < 0 or position + len(x) > model.configuration["max_position_embeddings"]:
        raise ModelOrbitRefused("state position exceeds admitted model configuration")
    if predecessor_state_digest is not None:
        _hex(predecessor_state_digest, "predecessor_state_digest")
    raw = x.tobytes(order="C")
    manifest = store.put_bytes(raw)
    if manifest.content_digest != _sha(raw) or not store.verify(manifest):
        raise ModelOrbitRefused("E-CPU M1 object did not retain exact output bits")
    value = {
        "schema":SCHEMA, "model_descriptor":model.descriptor_digest,
        "repository":model.repository, "revision":model.revision,
        "completed_layer":layer, "next_layer":layer+1, "start_position":position,
        "sequence_length":len(x), "hidden_width":x.shape[1], "dtype":"F32LE",
        "input_digest":native_receipt["input_digest"], "output_digest":_sha(raw),
        "weight_snapshot":binding.snapshot.identity,"layer_ground":binding.identity,
        "native_receipt_digest":_digest(dict(native_receipt)),
        "predecessor_state_digest":predecessor_state_digest,
        "object_manifest":manifest.to_dict(),
    }
    value["state_digest"] = _digest(value)
    return _record(value)


def resume_model_orbit(record: Mapping[str, Any], store: ComputationalObjectStore, *,
                       model: HFModelGround, expected_next_layer: int,
                       expected_state_digest: str, expected_native_receipt_digest: str,
                       expected_predecessor_digest: str | None = None) -> Any:
    """Read layer output on a different observer with external pin/receipt checks.

    The external pins must come from receiver-owned authority or a separately
    authenticated controller, never simply from the untrusted record itself.
    """
    import numpy as np
    x = _record(record)
    if not isinstance(store, ComputationalObjectStore):
        raise ModelOrbitRefused("existing E-CPU M1 store required")
    if not isinstance(model, HFModelGround) or x["model_descriptor"] != model.descriptor_digest:
        raise ModelOrbitRefused("model Ground identity does not match continuation")
    if (x["repository"] != model.repository or x["revision"] != model.revision
            or x["hidden_width"] != model.configuration["hidden_size"]):
        raise ModelOrbitRefused("model source and width differ")
    if (type(expected_next_layer) is not int or x["next_layer"] != expected_next_layer
            or expected_next_layer >= model.configuration["num_hidden_layers"]):
        raise ModelOrbitRefused("layer coordinate does not continue this model")
    if x["state_digest"] != _hex(expected_state_digest,"external state head"):
        raise ModelOrbitRefused("state revision differs from external high-water pin")
    if x["native_receipt_digest"] != _hex(expected_native_receipt_digest,"external native receipt"):
        raise ModelOrbitRefused("native operation result differs from external evidence pin")
    if expected_predecessor_digest != x["predecessor_state_digest"]:
        raise ModelOrbitRefused("predecessor lineage digest differs")
    manifest = ComputationalObjectManifest.from_dict(x["object_manifest"])
    data = store.read_bytes(manifest)
    if _sha(data) != x["output_digest"]:
        raise ModelOrbitRefused("retained predecessor parameter bits are corrupted")
    tensor = np.frombuffer(data, dtype="<f4").reshape(x["sequence_length"],x["hidden_width"]).copy()
    if not np.isfinite(tensor).all():
        raise ModelOrbitRefused("retained predecessor state contains nonfinite values")
    return tensor
