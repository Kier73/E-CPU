"""Exact, host-neutral model weight Grounds over existing E-CPU byte objects.

An architecture is a space of tensor parameter coordinates. A snapshot selects
one exact point in that space by content hash; a typed address selects a scalar
or bounded contiguous range of its *bits*, without requiring a model runtime.
This module does not infer training history, knowledge, model functionality, or
functional equivalence from weights. It creates no independent page store or
execution/admission authority.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Sequence
import json
import math
import re
import struct

SCHEMA = "mailcpu.model-weight-ground.v1"
_DTYPES = {"BOOL": 1, "U8": 1, "I8": 1, "F8_E4M3FN": 1, "F8_E5M2": 1,
           "I16": 2, "U16": 2, "F16": 2, "BF16": 2,
           "I32": 4, "U32": 4, "F32": 4,
           "I64": 8, "U64": 8, "F64": 8}
_HEX = re.compile(r"[a-f0-9]{64}\Z")
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,255}\Z")


class WeightGroundRefused(ValueError):
    """Unjustified coordinate, identity, byte layout, or snapshot claim."""


def _validate_json(value: Any) -> None:
    if value is None or type(value) in (str, int, bool):
        return
    if type(value) is float and math.isfinite(value):
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            _validate_json(item)
        return
    if isinstance(value, dict) and all(type(k) is str for k in value):
        for item in value.values():
            _validate_json(item)
        return
    raise WeightGroundRefused("Ground metadata must contain finite JSON values and string keys")


def _freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({k: _freeze(v) for k, v in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(v) for v in value)
    return value


def _json_bytes(value: Any) -> bytes:
    _validate_json(value)
    try:
        return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
                          allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise WeightGroundRefused("Ground metadata is not finite canonical JSON") from exc


def _hash(value: Any) -> str:
    return sha256(_json_bytes(value)).hexdigest()


def _name(value: Any, label: str) -> str:
    if type(value) is not str or _NAME.fullmatch(value) is None or ".." in value.split("/"):
        raise WeightGroundRefused(f"invalid {label}")
    return value


def _digest(value: Any, label: str) -> str:
    if type(value) is not str or _HEX.fullmatch(value) is None:
        raise WeightGroundRefused(f"invalid {label} digest")
    return value


def _number(value: Any, label: str) -> int:
    if type(value) is not int or value < 0:
        raise WeightGroundRefused(f"{label} must be a nonnegative integer")
    return value


@dataclass(frozen=True)
class TensorSpace:
    """The exact bit-representation of all values in one named tensor."""

    name: str
    dtype: str
    shape: tuple[int, ...]

    def __post_init__(self) -> None:
        _name(self.name, "tensor name")
        if type(self.dtype) is not str or self.dtype not in _DTYPES:
            raise WeightGroundRefused("unsupported tensor element encoding (no implicit quantization)")
        if not isinstance(self.shape, (list, tuple)) or len(self.shape) > 32:
            raise WeightGroundRefused("tensor shape must be a finite rank <= 32")
        dims = tuple(_number(x, "tensor extent") for x in self.shape)
        object.__setattr__(self, "shape", dims)

    @property
    def elements(self) -> int:
        return math.prod(self.shape)

    @property
    def byte_size(self) -> int:
        return self.elements * _DTYPES[self.dtype]

    def flat_index(self, coordinate: Sequence[int]) -> int:
        if isinstance(coordinate, (str, bytes)) or not isinstance(coordinate, (tuple, list)) or len(coordinate) != len(self.shape):
            raise WeightGroundRefused("tensor coordinate rank disagrees with Ground")
        linear = 0
        for dim, pos in zip(self.shape, coordinate):
            idx = _number(pos, "tensor coordinate")
            if idx >= dim:
                raise WeightGroundRefused("tensor coordinate outside admitted extent")
            linear = linear * dim + idx
        return linear

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "dtype": self.dtype, "shape": list(self.shape),
                "layout": "C-contiguous", "byte_order": "little"}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TensorSpace":
        if not isinstance(value, Mapping) or set(value) != {"name", "dtype", "shape", "layout", "byte_order"}:
            raise WeightGroundRefused("tensor space schema differs")
        if value["layout"] != "C-contiguous" or value["byte_order"] != "little":
            raise WeightGroundRefused("tensor layout/endianness is not admitted")
        return cls(value["name"], value["dtype"], tuple(value["shape"]))


@dataclass(frozen=True)
class ModelParameterSpace:
    """One model architecture's parameter coordinates, independent of values."""

    architecture_id: str
    config: Mapping[str, Any]
    tensors: tuple[TensorSpace, ...]
    _config_json: str = field(init=False, repr=False)

    def __post_init__(self) -> None:
        _name(self.architecture_id, "architecture")
        if not isinstance(self.config, Mapping):
            raise WeightGroundRefused("architecture config must be a JSON mapping")
        encoded = _json_bytes(dict(self.config)).decode("utf-8")
        if not isinstance(self.tensors, (tuple, list)) or not self.tensors:
            raise WeightGroundRefused("model must declare tensor spaces")
        t = tuple(self.tensors)
        if any(not isinstance(x, TensorSpace) for x in t) or len({x.name for x in t}) != len(t):
            raise WeightGroundRefused("tensor spaces must be typed and uniquely named")
        if tuple(sorted(t, key=lambda x: x.name)) != t:
            raise WeightGroundRefused("tensor spaces must be sorted by name")
        object.__setattr__(self, "_config_json", encoded)
        object.__setattr__(self, "config", _freeze(json.loads(encoded)))
        object.__setattr__(self, "tensors", t)

    @property
    def identity(self) -> str:
        return _hash(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {"schema": SCHEMA + ".space", "architecture_id": self.architecture_id,
                "config": json.loads(self._config_json), "tensors": [t.to_dict() for t in self.tensors]}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ModelParameterSpace":
        if not isinstance(value, Mapping) or set(value) != {"schema", "architecture_id", "config", "tensors"} or value["schema"] != SCHEMA + ".space":
            raise WeightGroundRefused("parameter-space schema mismatch")
        return cls(value["architecture_id"], value["config"],
                   tuple(TensorSpace.from_dict(t) for t in value["tensors"]))

    def tensor(self, name: str) -> TensorSpace:
        for tensor in self.tensors:
            if tensor.name == name:
                return tensor
        raise WeightGroundRefused("tensor is not in this architecture's parameter space")

    def representation_ref(self) -> Any:
        """Reuse E-CPU's typed representation identity, not a competing Ground registry."""
        from .semantic_translation import RepresentationRef
        return RepresentationRef.from_payload(SCHEMA + ".space", 1, self.to_dict())


@dataclass(frozen=True)
class ModelWeightSnapshot:
    """An exact parameter-space point whose bytes are verified by existing page manifests."""

    space: ModelParameterSpace
    manifests: tuple[tuple[str, Any], ...]

    def __post_init__(self) -> None:
        if not isinstance(self.space, ModelParameterSpace):
            raise WeightGroundRefused("snapshot requires a model parameter space")
        pairs = tuple(self.manifests)
        if len(pairs) != len(self.space.tensors):
            raise WeightGroundRefused("snapshot is missing declared tensors")
        for (name, manifest), tensor in zip(pairs, self.space.tensors):
            if name != tensor.name or manifest.size_bytes != tensor.byte_size:
                raise WeightGroundRefused("snapshot tensor layout/byte extent differs from its Ground")
            _digest(manifest.content_digest, "tensor content")
            _digest(manifest.manifest_digest, "tensor manifest")
        object.__setattr__(self, "manifests", pairs)

    @classmethod
    def from_manifests(cls, space: ModelParameterSpace, manifests: Mapping[str, Any]) -> "ModelWeightSnapshot":
        if not isinstance(manifests, Mapping) or set(manifests) != {t.name for t in space.tensors}:
            raise WeightGroundRefused("snapshot must supply exactly all declared tensor payloads")
        from .computational_objects import ComputationalObjectManifest
        typed = {}
        for name, obj in manifests.items():
            typed[name] = obj if isinstance(obj, ComputationalObjectManifest) else ComputationalObjectManifest.from_dict(obj)
        return cls(space, tuple((t.name, typed[t.name]) for t in space.tensors))

    @classmethod
    def publish_tensors(cls, space: ModelParameterSpace, store: Any, raw_tensors: Mapping[str, bytes]) -> "ModelWeightSnapshot":
        if set(raw_tensors) != {t.name for t in space.tensors}:
            raise WeightGroundRefused("raw snapshot tensor set differs from architecture")
        manifests = {}
        for tensor in space.tensors:
            data = raw_tensors[tensor.name]
            if not isinstance(data, bytes) or len(data) != tensor.byte_size:
                raise WeightGroundRefused("raw tensor is not exact byte extent")
            manifests[tensor.name] = store.put_bytes(data)
        return cls.from_manifests(space, manifests)

    @property
    def identity(self) -> str:
        """Value identity independent of backing page size, location, and host."""
        return _hash({"schema": SCHEMA + ".point", "space": self.space.identity,
                      "tensor_content": [[name, manifest.content_digest] for name, manifest in self.manifests]})

    def manifest_for(self, name: str) -> Any:
        for tensor_name, manifest in self.manifests:
            if tensor_name == name:
                return manifest
        raise WeightGroundRefused("tensor not declared by model snapshot")

    def to_dict(self) -> dict[str, Any]:
        return {"schema": SCHEMA + ".snapshot", "space": self.space.to_dict(),
                "manifests": {name: m.to_dict() for name, m in self.manifests},
                "identity": self.identity}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ModelWeightSnapshot":
        if not isinstance(value, Mapping) or set(value) != {"schema", "space", "manifests", "identity"} or value["schema"] != SCHEMA + ".snapshot":
            raise WeightGroundRefused("snapshot schema mismatched")
        space = ModelParameterSpace.from_dict(value["space"])
        instance = cls.from_manifests(space, value["manifests"])
        if instance.identity != value["identity"]:
            raise WeightGroundRefused("snapshot parameter identity mismatched")
        return instance

    def observe(self, store: Any, name: str, coordinate: Sequence[int]) -> dict[str, Any]:
        """Navigate to exact parameter bits; read only intersecting certified backing page(s)."""
        tensor = self.space.tensor(name)
        flat = tensor.flat_index(coordinate)
        width = _DTYPES[tensor.dtype]
        off = flat * width
        manifest = self.manifest_for(name)
        raw = store.read_range(manifest, off, width)
        if not isinstance(raw, bytes) or len(raw) != width:
            raise WeightGroundRefused("backing did not return exact parameter bytes")
        return {"schema": SCHEMA + ".parameter-observation", "space": self.space.identity,
                "snapshot": self.identity, "tensor": name, "dtype": tensor.dtype,
                "coordinate": list(coordinate), "flat_index": flat,
                "byte_offset": off, "manifest_digest": manifest.manifest_digest,
                "raw_hex": raw.hex(), "raw_sha256": sha256(raw).hexdigest(),
                "scope": "exact-parameter-bits-not-functional-inference"}

    def verify_all(self, store: Any) -> bool:
        """Verify each tensor's complete content without materializing the entire model."""
        return all(store.verify(m) for _, m in self.manifests)

    def tensor_raw(self, store: Any, name: str, *, max_bytes: int = 1 << 20) -> bytes:
        """Explicitly budget a full tensor read; no implicit full-model materialization."""
        tensor = self.space.tensor(name)
        if tensor.byte_size > _number(max_bytes, "read budget"):
            raise WeightGroundRefused("tensor exceeds explicit materialization budget")
        return store.read_range(self.manifest_for(name), 0, tensor.byte_size)


@dataclass
class ModelSpaceNavigator:
    """Value-indexed constellation of snapshots; not a trainer or equivalence oracle."""
    snapshots: dict[str, ModelWeightSnapshot] = field(default_factory=dict)

    def register_snapshot(self, snapshot: ModelWeightSnapshot) -> str:
        """Index an already described snapshot; this does NOT authorize neural execution."""
        if not isinstance(snapshot, ModelWeightSnapshot):
            raise WeightGroundRefused("only typed snapshot descriptions may be indexed")
        self.snapshots[snapshot.identity] = snapshot
        return snapshot.identity

    def navigate(self, identity: str) -> ModelWeightSnapshot:
        _digest(identity, "model snapshot")
        try:
            return self.snapshots[identity]
        except KeyError as exc:
            raise WeightGroundRefused("model snapshot coordinate has not been registered") from exc

    def observe(self, identity: str, store: Any, tensor: str, coordinate: Sequence[int]) -> dict[str, Any]:
        return self.navigate(identity).observe(store, tensor, coordinate)

    def same_parameters(self, left: str, right: str) -> bool:
        """Exact value identity only; different parameters can still compute the same function."""
        return self.navigate(left).identity == self.navigate(right).identity


def _unique_json_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise WeightGroundRefused("duplicate JSON key in safetensors metadata")
        result[key] = value
    return result


def _safetensors_header(path: Path, *, max_header_bytes: int) -> tuple[dict[str, Any], int]:
    _number(max_header_bytes, "max_header_bytes")
    size = path.stat().st_size
    with path.open("rb") as handle:
        length_b = handle.read(8)
        if len(length_b) != 8:
            raise WeightGroundRefused("safetensors lacks 8-byte header length")
        header_n = struct.unpack("<Q", length_b)[0]
        if header_n < 2 or header_n > max_header_bytes or header_n > size - 8:
            raise WeightGroundRefused("safetensors header length exceeds admitted budget")
        raw = handle.read(header_n)
    if not raw.startswith(b"{") or len(raw) != header_n:
        raise WeightGroundRefused("safetensors header is not an encoded JSON object")
    try:
        header = json.loads(raw, object_pairs_hook=_unique_json_pairs)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise WeightGroundRefused("invalid safetensors JSON header") from exc
    if not isinstance(header, dict):
        raise WeightGroundRefused("safetensors header must be an object")
    metadata = header.pop("__metadata__", {})
    if not isinstance(metadata, dict) or any(type(k) is not str or type(v) is not str for k, v in metadata.items()):
        raise WeightGroundRefused("invalid safetensors metadata")
    used: list[tuple[int, int]] = []
    for name, info in header.items():
        _name(name, "safetensors tensor")
        if not isinstance(info, dict) or set(info) != {"dtype", "shape", "data_offsets"}:
            raise WeightGroundRefused("tensor header fields must match the safetensors format")
        space = TensorSpace(name, info["dtype"], tuple(info["shape"]))
        offsets = info["data_offsets"]
        if not isinstance(offsets, list) or len(offsets) != 2:
            raise WeightGroundRefused("invalid safetensors data offsets")
        a, b = map(lambda x: _number(x, "safetensors offset"), offsets)
        if b < a or b - a != space.byte_size:
            raise WeightGroundRefused("tensor content does not match declared shape and dtype")
        used.append((a, b))
    # Safetensors buffers must be fully covered with no holes, overlaps, or trailing payload.
    cursor = 0
    for a, b in sorted(used):
        if a != cursor:
            raise WeightGroundRefused("safetensors tensor offsets overlap or leave holes")
        cursor = b
    if cursor != size - 8 - header_n:
        raise WeightGroundRefused("safetensors data buffer has unexplained bytes")
    return header, 8 + header_n


def ingest_safetensors_snapshot(
    directory: str | Path,
    space: ModelParameterSpace,
    store: Any,
    *,
    max_header_bytes: int = 16 * 1024 * 1024,
) -> ModelWeightSnapshot:
    """Stream locally available single- or multi-shard Safetensors into existing E-CPU pages.

    Requires *all* declared tensors and validates optional Hugging Face index map.
    No weight payload is loaded in full; the store's put_stream hashes each chunk.
    """
    root = Path(directory)
    if not root.is_dir():
        raise WeightGroundRefused("model snapshot directory is not accessible")
    files = sorted(p for p in root.glob("*.safetensors") if p.is_file() and not p.is_symlink())
    if not files:
        raise WeightGroundRefused("no safetensors files in model snapshot directory")
    index_path = root / "model.safetensors.index.json"
    index: Mapping[str, str] | None = None
    if index_path.exists():
        idx = json.loads(index_path.read_text("utf-8"), object_pairs_hook=_unique_json_pairs)
        if not isinstance(idx, dict) or not isinstance(idx.get("weight_map"), dict):
            raise WeightGroundRefused("invalid safetensors index mapping")
        index = idx["weight_map"]
        if any(type(k) is not str or type(v) is not str for k, v in index.items()):
            raise WeightGroundRefused("index tensor-to-file mapping is invalid")
    found: dict[str, Any] = {}
    geometry = {t.name: t for t in space.tensors}
    for path in files:
        header, data_start = _safetensors_header(path, max_header_bytes=max_header_bytes)
        for name, info in header.items():
            if name in found or name not in geometry:
                raise WeightGroundRefused("duplicate or undeclared tensor in safetensors snapshot")
            expected = geometry[name]
            if info["dtype"] != expected.dtype or tuple(info["shape"]) != expected.shape:
                raise WeightGroundRefused("safetensors tensor geometry differs from model Ground")
            if index is not None and index.get(name) != path.name:
                raise WeightGroundRefused("safetensors index contradicts the shard's tensor location")
            start, end = info["data_offsets"]
            with path.open("rb") as handle:
                handle.seek(data_start + start)
                found[name] = store.put_stream(handle, end - start)
    if set(found) != set(geometry) or (index is not None and set(index) != set(geometry)):
        raise WeightGroundRefused("snapshot is incomplete or contains index-only tensors")
    return ModelWeightSnapshot.from_manifests(space, found)
