"""MWS-002: exact, reconstructible Model Weight Grounds from existing E-CPU sources.

Recipes are *not* Ground admissions or execution capabilities. A recipe's
content identity is the MWS-001 snapshot identity, not its encoding, host, or
claimed functional equivalence. Each bounded read reconstructs and validates
its exact chunk using existing page objects or admitted Structural Memory.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
import json
import math
import re
from typing import Any, Mapping, Sequence

from .model_weight_ground import ModelParameterSpace, ModelWeightSnapshot, WeightGroundRefused

SCHEMA = "mailcpu.generative-weight-ground.v1"
_HEX = re.compile(r"[a-f0-9]{64}\Z")
_KINDS = frozenset({"stored", "replacement", "structural-law", "reindex"})
MAX_READ = 65536
MAX_EDITS = 8192
MAX_RANK = 32


class GenerativeGroundRefused(WeightGroundRefused):
    """A recipe, source, law, or claimed exact model point is not justified."""


def _number(value: Any, label: str, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise GenerativeGroundRefused(f"{label} must be an integer >= {minimum}")
    return value


def _hex(value: Any, label: str) -> str:
    if type(value) is not str or not _HEX.fullmatch(value):
        raise GenerativeGroundRefused(f"{label} must be a lowercase SHA256 digest")
    return value


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
                          allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, OverflowError) as exc:
        raise GenerativeGroundRefused("recipe is not finite canonical JSON") from exc


def _sha(data: bytes) -> str:
    return sha256(data).hexdigest()


def _hash(value: Any) -> str:
    return _sha(_canonical(value))


def _width(dtype: str) -> int:
    # Same exact storage domains as Model Weight Ground v1. No float arithmetic.
    return {"BOOL": 1, "U8": 1, "I8": 1, "F8_E4M3FN": 1, "F8_E5M2": 1,
            "I16": 2, "U16": 2, "F16": 2, "BF16": 2,
            "I32": 4, "U32": 4, "F32": 4,
            "I64": 8, "U64": 8, "F64": 8}[dtype]


def _chunks(length: int, chunk_size: int) -> int:
    return (length + chunk_size - 1) // chunk_size


def _exact_snapshot_id(space: ModelParameterSpace, tensor_digests: Sequence[tuple[str, str]]) -> str:
    # Retains the *exact* MWS-001 point identity ABI.
    return _hash({"schema": "mailcpu.model-weight-ground.v1.point", "space": space.identity,
                  "tensor_content": [[name, digest] for name, digest in tensor_digests]})


@dataclass(frozen=True)
class TensorRecipe:
    """One strictly typed, byte-exact tensor recipe with chunk commitments.

    The ``body_json`` is detached and immutable. The source is either an
    MWS-001 snapshot ID or a revision-pinned Structural Memory law. A 
    non-authoritative proposed recipe is never a signed/model-quality proof.
    """
    space_digest: str
    tensor_name: str
    kind: str
    target_digest: str
    byte_size: int
    chunk_size: int
    chunk_digests: tuple[str, ...]
    body_json: str

    def __post_init__(self) -> None:
        _hex(self.space_digest, "parameter space")
        _hex(self.target_digest, "target tensor")
        if type(self.tensor_name) is not str or not self.tensor_name or len(self.tensor_name) > 256:
            raise GenerativeGroundRefused("invalid tensor name")
        if self.kind not in _KINDS:
            raise GenerativeGroundRefused("unsupported tensor recipe kind")
        _number(self.byte_size, "tensor bytes")
        size = _number(self.chunk_size, "chunk size", minimum=1)
        if size > MAX_READ or size & (size - 1):
            raise GenerativeGroundRefused("chunk size must be power of two <= 65536")
        digests = tuple(self.chunk_digests)
        if len(digests) != _chunks(self.byte_size, size):
            raise GenerativeGroundRefused("chunk digest count does not match tensor extent")
        for digest in digests:
            _hex(digest, "tensor chunk")
        if not isinstance(self.body_json, str):
            raise GenerativeGroundRefused("recipe body must be canonical JSON text")
        try:
            body = json.loads(self.body_json)
        except (ValueError, TypeError) as exc:
            raise GenerativeGroundRefused("invalid recipe body") from exc
        if _canonical(body).decode("utf-8") != self.body_json or not isinstance(body, dict):
            raise GenerativeGroundRefused("recipe body is not canonical JSON object")
        if self.kind == "structural-law":
            if set(body) != {"memory_id", "revision", "spec_digest", "certificate_digest", "context_digest", "coordinate_start"}:
                raise GenerativeGroundRefused("structural-law source fields invalid")
            if type(body["memory_id"]) is not str or not body["memory_id"] or len(body["memory_id"]) > 256:
                raise GenerativeGroundRefused("invalid structural-law memory ID")
            _number(body["revision"], "law revision", minimum=1)
            _number(body["coordinate_start"], "law coordinate")
            for key in ("spec_digest", "certificate_digest", "context_digest"):
                _hex(body[key], key)
        elif self.kind == "stored":
            if set(body) != {"source_snapshot"}:
                raise GenerativeGroundRefused("stored source fields invalid")
            _hex(body["source_snapshot"], "source snapshot")
        elif self.kind == "replacement":
            if set(body) != {"source_snapshot", "edits"}:
                raise GenerativeGroundRefused("replacement source fields invalid")
            _hex(body["source_snapshot"], "source snapshot")
            self._check_edits(body["edits"])
        elif self.kind == "reindex":
            if set(body) != {"source_snapshot", "axis", "permutation"}:
                raise GenerativeGroundRefused("reindex source fields invalid")
            _hex(body["source_snapshot"], "source snapshot")
            _number(body["axis"], "permutation axis")
            perm = body["permutation"]
            if not isinstance(perm, list) or any(type(v) is not int for v in perm) or sorted(perm) != list(range(len(perm))):
                raise GenerativeGroundRefused("permutation must be a bijection")
        object.__setattr__(self, "chunk_digests", digests)

    def _check_edits(self, edits: Any) -> None:
        if not isinstance(edits, list) or not edits or len(edits) > MAX_EDITS:
            raise GenerativeGroundRefused("replacement requires bounded nonempty edits")
        last = -1
        for item in edits:
            if not isinstance(item, list) or len(item) != 2:
                raise GenerativeGroundRefused("replacement edit must be [element_index, bytes_hex]")
            index = _number(item[0], "replacement index")
            if index <= last:
                raise GenerativeGroundRefused("replacement indices must be sorted, unique")
            last = index
            if type(item[1]) is not str or len(item[1]) % 2 or not re.fullmatch(r"[a-f0-9]*", item[1]):
                raise GenerativeGroundRefused("replacement payload must be exact lowercase bytes hex")

    @property
    def body(self) -> dict[str, Any]:
        return json.loads(self.body_json)

    def to_dict(self) -> dict[str, Any]:
        return {"schema": SCHEMA + ".tensor", "space_digest": self.space_digest,
                "tensor_name": self.tensor_name, "kind": self.kind,
                "target_digest": self.target_digest, "byte_size": self.byte_size,
                "chunk_size": self.chunk_size, "chunk_digests": list(self.chunk_digests),
                "body": self.body, "recipe_digest": self.identity}

    @property
    def identity(self) -> str:
        data = {"schema": SCHEMA + ".tensor", "space_digest": self.space_digest,
                "tensor_name": self.tensor_name, "kind": self.kind,
                "target_digest": self.target_digest, "byte_size": self.byte_size,
                "chunk_size": self.chunk_size, "chunk_digests": list(self.chunk_digests),
                "body": self.body}
        return _hash(data)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TensorRecipe":
        fields = {"schema", "space_digest", "tensor_name", "kind", "target_digest", "byte_size",
                  "chunk_size", "chunk_digests", "body", "recipe_digest"}
        if not isinstance(value, Mapping) or set(value) != fields or value["schema"] != SCHEMA + ".tensor":
            raise GenerativeGroundRefused("tensor recipe schema mismatch")
        result = cls(value["space_digest"], value["tensor_name"], value["kind"],
                     value["target_digest"], value["byte_size"], value["chunk_size"],
                     tuple(value["chunk_digests"]), _canonical(value["body"]).decode("utf-8"))
        if result.identity != value["recipe_digest"]:
            raise GenerativeGroundRefused("tensor recipe digest mismatch")
        return result


def _recipe(space: ModelParameterSpace, name: str, kind: str, body: dict[str, Any],
            chunks: Sequence[bytes], *, chunk_size: int) -> TensorRecipe:
    tensor = space.tensor(name)
    if sum(map(len, chunks)) != tensor.byte_size or len(chunks) != _chunks(tensor.byte_size, chunk_size):
        raise GenerativeGroundRefused("reconstruction chunks do not cover declared tensor")
    whole = sha256()
    chunk_digests = []
    for index, chunk in enumerate(chunks):
        wanted = min(chunk_size, tensor.byte_size - index * chunk_size)
        if len(chunk) != wanted:
            raise GenerativeGroundRefused("noncanonical reconstruction chunk length")
        whole.update(chunk)
        chunk_digests.append(_sha(chunk))
    return TensorRecipe(space.identity, name, kind, whole.hexdigest(), tensor.byte_size, chunk_size,
                        tuple(chunk_digests), _canonical(body).decode("utf-8"))


def _source(space: ModelParameterSpace, name: str, identity: str,
            sources: Mapping[str, ModelWeightSnapshot]) -> ModelWeightSnapshot:
    _hex(identity, "snapshot source")
    source = sources.get(identity)
    if not isinstance(source, ModelWeightSnapshot) or source.identity != identity:
        raise GenerativeGroundRefused("source snapshot not registered or identity mismatched")
    if source.space.identity != space.identity or source.space.tensor(name).to_dict() != space.tensor(name).to_dict():
        raise GenerativeGroundRefused("source snapshot has different model parameter Ground")
    return source


def _read_chunk(space: ModelParameterSpace, recipe: TensorRecipe, chunk_index: int, *,
                store: Any, sources: Mapping[str, ModelWeightSnapshot],
                registry: Any = None) -> bytes:
    tensor = space.tensor(recipe.tensor_name)
    if recipe.space_digest != space.identity or recipe.byte_size != tensor.byte_size:
        raise GenerativeGroundRefused("recipe does not belong to model Ground")
    width = _width(tensor.dtype)
    if recipe.chunk_size % width:
        raise GenerativeGroundRefused("chunk divides a numerical element")
    if type(chunk_index) is not int or not 0 <= chunk_index < len(recipe.chunk_digests):
        raise GenerativeGroundRefused("invalid chunk index")
    offset = chunk_index * recipe.chunk_size
    length = min(recipe.chunk_size, recipe.byte_size - offset)
    if length % width:
        raise GenerativeGroundRefused("tensor byte extent not aligned to dtype")
    raw = _reconstruct_uncertified_chunk(space, recipe, chunk_index,
                                         store=store, sources=sources, registry=registry)
    if _sha(raw) != recipe.chunk_digests[chunk_index]:
        raise GenerativeGroundRefused("reconstructed chunk disagrees with committed target content")
    return raw


def _make_recipe(space: ModelParameterSpace, name: str, kind: str, body: dict[str, Any],
                 *, store: Any, sources: Mapping[str, ModelWeightSnapshot],
                 registry: Any = None, chunk_size: int = 4096) -> TensorRecipe:
    tensor = space.tensor(name)
    _number(chunk_size, "chunk size", minimum=1)
    if chunk_size > MAX_READ or chunk_size & (chunk_size - 1) or chunk_size % _width(tensor.dtype):
        raise GenerativeGroundRefused("chunk size must be a permitted aligned power of two")
    # Validate body and exact input-source relations before streaming.
    provisional = TensorRecipe(space.identity, name, kind, "0" * 64, tensor.byte_size, chunk_size,
                               tuple("0" * 64 for _ in range(_chunks(tensor.byte_size, chunk_size))),
                               _canonical(body).decode("utf-8"))
    # Creation is bounded by a per-chunk read, and builds only chunk hashes;
    # do NOT retain the whole tensor in the recipe or a second page store.
    whole = sha256()
    digests = []
    for index in range(len(provisional.chunk_digests)):
        # _read_chunk validates against a digest; temporary per-chunk data below
        # is computed by the exact same bounded source logic without the commitment.
        raw = _reconstruct_uncertified_chunk(space, provisional, index,
                                             store=store, sources=sources, registry=registry)
        digests.append(_sha(raw))
        whole.update(raw)
    return TensorRecipe(space.identity, name, kind, whole.hexdigest(), tensor.byte_size, chunk_size,
                        tuple(digests), provisional.body_json)


def _reconstruct_uncertified_chunk(space: ModelParameterSpace, provisional: TensorRecipe,
                                   index: int, *, store: Any,
                                   sources: Mapping[str, ModelWeightSnapshot], registry: Any) -> bytes:
    # Commitments are computed over the actual canonical source operations,
    # then rechecked on every later query by _read_chunk.
    offset = index * provisional.chunk_size
    length = min(provisional.chunk_size, provisional.byte_size - offset)
    body = provisional.body
    tensor = space.tensor(provisional.tensor_name)
    width = _width(tensor.dtype)
    if provisional.kind == "structural-law":
        if registry is None:
            raise GenerativeGroundRefused("missing receiver-owned Structural Memory registry")
        start = body["coordinate_start"] + offset
        values, receipt, _ = registry.read_revision_range(body["memory_id"], body["revision"], start, length)
        if (receipt.memory_id != body["memory_id"] or receipt.revision != body["revision"]
                or receipt.spec_digest != body["spec_digest"]
                or receipt.certificate_digest != body["certificate_digest"]
                or receipt.context_digest != body["context_digest"]
                or receipt.coordinate_start != start or receipt.length != length):
            raise GenerativeGroundRefused("Structural Memory source identity mismatch")
        if len(values) != length or any(type(v) is not int or not 0 <= v <= 255 for v in values):
            raise GenerativeGroundRefused("admitted generator is not a byte law")
        return bytes(values)
    # Delegate to the read implementation, using its digest guard for integrity.
    # _read_chunk is called with the exact digest of the same source extent.
    # Avoid recursion by creating the actual raw bytes directly.
    source = _source(space, provisional.tensor_name, body["source_snapshot"], sources)
    manifest = source.manifest_for(provisional.tensor_name)
    if provisional.kind == "stored":
        return store.read_range(manifest, offset, length)
    if provisional.kind == "replacement":
        edits = body["edits"]
        buf = bytearray(store.read_range(manifest, offset, length))
        for scalar, value_hex in edits:
            if scalar >= tensor.elements:
                raise GenerativeGroundRefused("replacement outside tensor extent")
            payload = bytes.fromhex(value_hex)
            if len(payload) != width:
                raise GenerativeGroundRefused("replacement has wrong element bit width")
            start = scalar * width
            if offset <= start < offset + length:
                if buf[start - offset:start - offset + width] == payload:
                    raise GenerativeGroundRefused("replacement is a redundant no-op")
                buf[start - offset:start - offset + width] = payload
        return bytes(buf)
    if provisional.kind == "reindex":
        axis, permutation = body["axis"], body["permutation"]
        if axis >= len(tensor.shape) or len(permutation) != tensor.shape[axis]:
            raise GenerativeGroundRefused("reindex axis/permutation mismatched tensor geometry")
        result = bytearray()
        for flat in range(offset // width, (offset + length) // width):
            coord = []
            rem = flat
            for dim in reversed(tensor.shape):
                coord.append(rem % dim)
                rem //= dim
            coord.reverse()
            coord[axis] = permutation[coord[axis]]
            result.extend(store.read_range(manifest, tensor.flat_index(coord) * width, width))
        return bytes(result)
    raise GenerativeGroundRefused("unsupported reconstruction recipe")


def recipe_from_stored(snapshot: ModelWeightSnapshot, name: str, store: Any,
                       *, chunk_size: int = 4096) -> TensorRecipe:
    return _make_recipe(snapshot.space, name, "stored", {"source_snapshot": snapshot.identity},
                        store=store, sources={snapshot.identity: snapshot}, chunk_size=chunk_size)


def recipe_from_replacements(snapshot: ModelWeightSnapshot, name: str,
                             replacements: Mapping[int, bytes], store: Any,
                             *, chunk_size: int = 4096) -> TensorRecipe:
    tensor = snapshot.space.tensor(name)
    width = _width(tensor.dtype)
    if not isinstance(replacements, Mapping) or not 0 < len(replacements) <= MAX_EDITS:
        raise GenerativeGroundRefused("replacement map must be nonempty and bounded")
    edits: list[list[Any]] = []
    if any(type(k) is not int for k in replacements):
        raise GenerativeGroundRefused("replacement element indices must be strict integers")
    for flat, payload in sorted(replacements.items()):
        _number(flat, "replacement element")
        if flat >= tensor.elements or type(payload) is not bytes or len(payload) != width:
            raise GenerativeGroundRefused("replacement outside tensor or wrong exact element encoding")
        edits.append([flat, payload.hex()])
    return _make_recipe(snapshot.space, name, "replacement",
                        {"source_snapshot": snapshot.identity, "edits": edits},
                        store=store, sources={snapshot.identity: snapshot}, chunk_size=chunk_size)


def recipe_from_reindex(snapshot: ModelWeightSnapshot, name: str, axis: int,
                        permutation: Sequence[int], store: Any, *, chunk_size: int = 4096) -> TensorRecipe:
    tensor = snapshot.space.tensor(name)
    _number(axis, "axis")
    if axis >= len(tensor.shape):
        raise GenerativeGroundRefused("reindex axis outside tensor rank")
    perm = tuple(permutation)
    if sorted(perm) != list(range(tensor.shape[axis])):
        raise GenerativeGroundRefused("axis permutation is not a bijection")
    return _make_recipe(snapshot.space, name, "reindex", {"source_snapshot": snapshot.identity,
                        "axis": axis, "permutation": list(perm)},
                        store=store, sources={snapshot.identity: snapshot}, chunk_size=chunk_size)


def recipe_from_structural_memory(space: ModelParameterSpace, name: str, version: Any,
                                  registry: Any, *, coordinate_start: int = 0,
                                  chunk_size: int = 4096) -> TensorRecipe:
    """Use an *already admitted* E-CPU Structural Memory revision; never self-admit."""
    _number(coordinate_start, "law coordinate")
    spec, cert = version.spec, version.certificate
    if spec.family not in ("int", "lcg", "gf2", "fgraph"):
        raise GenerativeGroundRefused("unsupported native structural generator")
    body = {"memory_id": spec.memory_id, "revision": spec.revision,
            "spec_digest": spec.digest, "certificate_digest": cert.digest,
            "context_digest": spec.context_digest, "coordinate_start": coordinate_start}
    return _make_recipe(space, name, "structural-law", body,
                        store=None, sources={}, registry=registry, chunk_size=chunk_size)


@dataclass(frozen=True)
class GenerativeModelSnapshot:
    """A model point with exact-content identity independent of reconstruction method."""
    space: ModelParameterSpace
    recipes: tuple[TensorRecipe, ...]
    expected_identity: str

    def __post_init__(self) -> None:
        if not isinstance(self.space, ModelParameterSpace):
            raise GenerativeGroundRefused("model space must be an admitted typed description")
        if not isinstance(self.recipes, (tuple, list)):
            raise GenerativeGroundRefused("tensor recipes must be a tuple")
        recipes = tuple(self.recipes)
        if len(recipes) != len(self.space.tensors):
            raise GenerativeGroundRefused("model is missing a declared tensor")
        for recipe, tensor in zip(recipes, self.space.tensors):
            if (not isinstance(recipe, TensorRecipe) or recipe.space_digest != self.space.identity
                    or recipe.tensor_name != tensor.name or recipe.byte_size != tensor.byte_size
                    or recipe.chunk_size % _width(tensor.dtype)):
                raise GenerativeGroundRefused("recipe tensor coordinate or layout does not match Ground")
            if recipe.kind == "replacement":
                for flat, payload in recipe.body["edits"]:
                    if flat >= tensor.elements or len(payload) != 2 * _width(tensor.dtype):
                        raise GenerativeGroundRefused("replacement does not fit tensor")
            if recipe.kind == "reindex":
                body = recipe.body
                if body["axis"] >= len(tensor.shape) or len(body["permutation"]) != tensor.shape[body["axis"]]:
                    raise GenerativeGroundRefused("reindex does not fit tensor")
        _hex(self.expected_identity, "expected snapshot")
        object.__setattr__(self, "recipes", recipes)
        if self.identity != self.expected_identity:
            raise GenerativeGroundRefused("declared trained-instance identity disagrees with tensor content")

    @property
    def identity(self) -> str:
        return _exact_snapshot_id(self.space, [(r.tensor_name, r.target_digest) for r in self.recipes])

    def to_dict(self) -> dict[str, Any]:
        return {"schema": SCHEMA + ".snapshot", "space": self.space.to_dict(),
                "recipes": [r.to_dict() for r in self.recipes], "identity": self.identity,
                "expected_identity": self.expected_identity}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "GenerativeModelSnapshot":
        required = {"schema", "space", "recipes", "identity", "expected_identity"}
        if not isinstance(value, Mapping) or set(value) != required or value["schema"] != SCHEMA + ".snapshot":
            raise GenerativeGroundRefused("generative snapshot schema mismatch")
        obj = cls(ModelParameterSpace.from_dict(value["space"]),
                  tuple(TensorRecipe.from_dict(r) for r in value["recipes"]),
                  value["expected_identity"])
        if obj.identity != value["identity"]:
            raise GenerativeGroundRefused("generative snapshot identity mismatch")
        return obj

    def tensor(self, name: str) -> TensorRecipe:
        for recipe in self.recipes:
            if recipe.tensor_name == name:
                return recipe
        raise GenerativeGroundRefused("unknown model tensor")

    def read_range(self, name: str, offset: int, length: int, *, store: Any,
                   sources: Mapping[str, ModelWeightSnapshot] = {},
                   registry: Any = None, max_bytes: int = MAX_READ) -> bytes:
        recipe = self.tensor(name)
        _number(offset, "range offset")
        _number(length, "range length")
        _number(max_bytes, "read budget", minimum=1)
        if length > min(max_bytes, MAX_READ) or offset + length > recipe.byte_size:
            raise GenerativeGroundRefused("range outside tensor or requested byte budget")
        if not length:
            return b""
        first, last = offset // recipe.chunk_size, (offset + length - 1) // recipe.chunk_size
        buf = bytearray()
        for index in range(first, last + 1):
            data = _read_chunk(self.space, recipe, index, store=store, sources=sources, registry=registry)
            chunk_base = index * recipe.chunk_size
            start = max(offset, chunk_base) - chunk_base
            end = min(offset + length, chunk_base + len(data)) - chunk_base
            buf.extend(data[start:end])
        if len(buf) != length:
            raise GenerativeGroundRefused("reconstruction was incomplete")
        return bytes(buf)

    def observe(self, name: str, coordinate: Sequence[int], *, store: Any,
                sources: Mapping[str, ModelWeightSnapshot] = {}, registry: Any = None) -> dict[str, Any]:
        tensor = self.space.tensor(name)
        flat = tensor.flat_index(coordinate)
        width = _width(tensor.dtype)
        raw = self.read_range(name, flat * width, width, store=store, sources=sources, registry=registry)
        return {"schema": SCHEMA + ".parameter-observation", "model_snapshot": self.identity,
                "parameter_space": self.space.identity, "tensor": name,
                "coordinate": list(coordinate), "dtype": tensor.dtype,
                "raw_hex": raw.hex(), "raw_sha256": _sha(raw),
                "recipe_digest": self.tensor(name).identity,
                "scope": "exact-bytes-only-not-inference-or-functional-equivalence"}

    def verify_all(self, *, store: Any, sources: Mapping[str, ModelWeightSnapshot] = {},
                   registry: Any = None) -> bool:
        for recipe in self.recipes:
            running = sha256()
            for index in range(len(recipe.chunk_digests)):
                running.update(_read_chunk(self.space, recipe, index, store=store,
                                           sources=sources, registry=registry))
            if running.hexdigest() != recipe.target_digest:
                raise GenerativeGroundRefused("full tensor digest disagrees with expected content")
        return True

    def materialize(self, *, store: Any, sources: Mapping[str, ModelWeightSnapshot] = {},
                    registry: Any = None) -> ModelWeightSnapshot:
        """Stream exact tensor bytes into an *existing* E-CPU ComputationalObjectStore."""
        class Stream:
            def __init__(self, snapshot: "GenerativeModelSnapshot", tensor: TensorRecipe):
                self.position = 0
                self.snapshot = snapshot
                self.tensor = tensor
            def read(self, amount: int) -> bytes:
                if self.position >= self.tensor.byte_size:
                    return b""
                amount = min(amount, MAX_READ, self.tensor.byte_size - self.position)
                result = self.snapshot.read_range(self.tensor.tensor_name, self.position, amount,
                                                  store=store, sources=sources, registry=registry)
                self.position += len(result)
                return result
        materialized = {}
        for recipe in self.recipes:
            manifest = store.put_stream(Stream(self, recipe), recipe.byte_size)
            if manifest.content_digest != recipe.target_digest:
                raise GenerativeGroundRefused("materialized tensor digest changed")
            materialized[recipe.tensor_name] = manifest
        snapshot = ModelWeightSnapshot.from_manifests(self.space, materialized)
        if snapshot.identity != self.expected_identity:
            raise GenerativeGroundRefused("materialized trained-instance coordinate changed")
        return snapshot


def select_exact_recipe(candidates: Sequence[TensorRecipe], *,
                        max_recipe_bytes: int | None = None) -> TensorRecipe:
    """Deterministic description-cost choice, never an assumed execution-speedup.

    Requires all candidates to target the same tensor content and Ground. A
    cheaper description need not be faster to reconstruct; measured work is
    separate from wire/metadata bytes.
    """
    if not isinstance(candidates, (tuple, list)) or not candidates:
        raise GenerativeGroundRefused("no recipe candidates")
    first = candidates[0]
    if not isinstance(first, TensorRecipe):
        raise GenerativeGroundRefused("candidate must be an exact TensorRecipe")
    if any(not isinstance(c, TensorRecipe) or
           (c.space_digest, c.tensor_name, c.target_digest, c.byte_size) !=
           (first.space_digest, first.tensor_name, first.target_digest, first.byte_size)
           for c in candidates):
        raise GenerativeGroundRefused("cannot compare recipes for different model instances")
    if max_recipe_bytes is not None:
        _number(max_recipe_bytes, "recipe byte budget")
    ranked = sorted(candidates, key=lambda c: (len(_canonical(c.to_dict())), c.identity))
    valid = [x for x in ranked if max_recipe_bytes is None or len(_canonical(x.to_dict())) <= max_recipe_bytes]
    if not valid:
        raise GenerativeGroundRefused("no recipe satisfies description budget")
    return valid[0]
