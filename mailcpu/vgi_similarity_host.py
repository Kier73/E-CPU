"""E-CPU receiver-local Virtual Layer admission of VGI similarity-basis memories.

This module never accepts executable Python or an authoritative Ground from the
peer. The host operator is registered locally; a trusted pinned catalogue of
record bytes and exact identity pairs is provisioned outside the workload.
VGI independently rechecks all factors, basis transforms and local products.
The hypervisor, Transit and recovery ledgers remain E-CPU's sole authorities.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Mapping

from .virtual_layer import (
    OperatorRegistry, OperatorSpec, VirtualLayerError, VirtualLayerWorkload,
)

SIMILARITY_OPERATOR_ID = "vgi.similarity.navigate"
SIMILARITY_REQUEST_SCHEMA = "vgi.similarity.navigation-request.v1"
SIMILARITY_RECEIPT_SCHEMA = "vgi.similarity.navigation-effect.v1"
MAX_RECORD_BYTES = 1_048_576
MAX_EXPONENT_BITS = 256
_HEX = frozenset("0123456789abcdef")


class SimilarityHostError(VirtualLayerError):
    """Refused mathematical admission or receiver-local VGI execution."""


def _digest(value: Any) -> str:
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                             ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def _sha(value: Any, label: str) -> str:
    if type(value) is not str or len(value) != 64 or any(c not in _HEX for c in value):
        raise SimilarityHostError(f"{label} must be lowercase SHA-256")
    return value


@dataclass(frozen=True, slots=True)
class PinnedSimilarityRecord:
    """Trusted *local provisioning*, not a remote sender's authority claim.

    Caller must establish the graph/record identity pair through E-CPU's
    existing admission and provenance authorities. This class only checks
    the mathematical relation of that pair and freezes its data bytes.
    """

    memory_sha256: str
    graph_fingerprint: str
    content: bytes

    def __post_init__(self) -> None:
        _sha(self.memory_sha256, "memory_sha256")
        _sha(self.graph_fingerprint, "graph_fingerprint")
        if type(self.content) is not bytes or not (0 < len(self.content) <= MAX_RECORD_BYTES):
            raise SimilarityHostError("pinned mathematical record has invalid bounded bytes")


def _reconstruct(record: PinnedSimilarityRecord) -> Any:
    try:
        from vgi.structural_memory import admit_similarity_memory
    except ImportError as exc:
        raise SimilarityHostError("VGI GEOMETRY-FIRST-008 is not installed") from exc
    try:
        return admit_similarity_memory(
            record.content,
            expected_graph_fingerprint=record.graph_fingerprint,
            expected_memory_sha256=record.memory_sha256,
        )
    except (ValueError, TypeError) as exc:
        raise SimilarityHostError(f"pinned similarity memory mathematically refused: {exc}") from exc


class PinnedSimilarityCatalogue:
    """Immutable receiver-local catalogue populated by a separate admission step.

    Reading this catalogue is never a substitute for the E-CPU capability check.
    An operator resolves only the trusted records present at its creation.
    """

    def __init__(self, records: tuple[PinnedSimilarityRecord, ...]) -> None:
        if not isinstance(records, tuple) or any(not isinstance(v, PinnedSimilarityRecord) for v in records):
            raise SimilarityHostError("catalogue requires pinned trusted entries")
        if len({r.memory_sha256 for r in records}) != len(records):
            raise SimilarityHostError("duplicate pinned mathematical record")
        # Verify and reconstruct each mathematical object once on this host;
        # process death destroys this cache, so recovered hosts reverify.
        self._admitted = {r.memory_sha256: _reconstruct(r) for r in records}
        self._record_bytes = {r.memory_sha256: r.content for r in records}
        self._fingerprints = {r.memory_sha256: r.graph_fingerprint for r in records}

    def resolve(self, memory_sha256: str, graph_fingerprint: str) -> Any:
        identity = _sha(memory_sha256, "requested memory_sha256")
        graph = _sha(graph_fingerprint, "requested graph_fingerprint")
        if identity not in self._admitted or self._fingerprints[identity] != graph:
            raise SimilarityHostError("no trusted receiver-local admission for requested Ground")
        return self._admitted[identity]

    def record_bytes(self, memory_sha256: str) -> bytes:
        # For explicit E-CPU checkpoint/persistence integration only. No grant.
        return self._record_bytes[_sha(memory_sha256, "memory_sha256")]


def _request(raw: Any, max_exponent_bits: int) -> dict[str, Any]:
    if not isinstance(raw, Mapping) or set(raw) != {
        "schema", "memory_sha256", "graph_fingerprint", "initial", "logical_tick"
    }:
        raise SimilarityHostError("similarity workload must have exact typed fields")
    if raw["schema"] != SIMILARITY_REQUEST_SCHEMA:
        raise SimilarityHostError("unsupported similarity navigation request schema")
    _sha(raw["memory_sha256"], "memory_sha256")
    _sha(raw["graph_fingerprint"], "graph_fingerprint")
    tick = raw["logical_tick"]
    if type(tick) is not int or tick < 0 or tick.bit_length() > max_exponent_bits:
        raise SimilarityHostError("logical coordinate is invalid or exceeds supported exponent bits")
    initial = raw["initial"]
    if not isinstance(initial, Mapping) or set(initial) != {"space", "values"}:
        raise SimilarityHostError("initial state requires an exact typed vector envelope")
    if not isinstance(initial["values"], (list, tuple)) or any(type(x) is not int for x in initial["values"]):
        raise SimilarityHostError("initial state requires exact integer coordinates")
    return dict(raw)


def make_vgi_similarity_operator(
    catalogue: PinnedSimilarityCatalogue, *, max_exponent_bits: int = MAX_EXPONENT_BITS,
) -> tuple[OperatorSpec, Any]:
    """Node-local deterministic pure handler; E-CPU runtime owns all authority.

    E-CPU's workload budgets constrain the *physical operator execution*.
    The large mathematical logical tick is not an E-CPU scheduler-tick budget.
    The exact power exponent receives an independent bit-length bound here.
    """
    if not isinstance(catalogue, PinnedSimilarityCatalogue):
        raise SimilarityHostError("operator requires a trusted receiver-local catalogue")
    if type(max_exponent_bits) is not int or not 1 <= max_exponent_bits <= MAX_EXPONENT_BITS:
        raise SimilarityHostError("invalid bounded logical-time exponent size")
    spec = vgi_similarity_operator_spec()

    def handle(input_value: Any, workload: VirtualLayerWorkload) -> dict[str, Any]:
        if not isinstance(workload, VirtualLayerWorkload):
            raise SimilarityHostError("similarity execution requires a typed Virtual Layer workload")
        request = _request(input_value, max_exponent_bits)
        if request["logical_tick"].bit_length() > workload.budget.max_virtual_ticks:
            raise SimilarityHostError("powering step count exceeds receiver virtual tick budget")
        admitted = catalogue.resolve(request["memory_sha256"], request["graph_fingerprint"])
        try:
            from vgi.typed_operator_navigation import TypedVector
            frame = admitted.graph.domain
            if request["initial"]["space"] != frame.to_dict():
                raise SimilarityHostError("initial state has a different admitted typed frame")
            initial = TypedVector(frame, tuple(request["initial"]["values"]))
            receipt = admitted.state_at(initial, request["logical_tick"])
        except SimilarityHostError:
            raise
        except (TypeError, ValueError) as exc:
            raise SimilarityHostError(f"similarity navigation refused: {exc}") from exc
        outcome = {
            "schema": SIMILARITY_RECEIPT_SCHEMA,
            "system_ground": workload.ground.to_dict(),
            "computation_ground": {
                "memory_sha256": admitted.memory_sha256,
                "graph_fingerprint": admitted.graph_fingerprint,
                "certificate_fingerprint": admitted.certificate.fingerprint,
            },
            "navigation": receipt.to_dict(),
            "method": "verified_basis_memory_without_rediscovery",
        }
        # Native E-CPU authorities can attach the exact checkpointed revision
        # lineage. Legacy pinned catalogues still return their previous schema.
        native_anchor = getattr(catalogue, "native_anchor", None)
        if native_anchor is not None:
            if not callable(native_anchor):
                raise SimilarityHostError("native structural provenance provider is invalid")
            outcome["native_structural_memory"] = native_anchor()
        return {**outcome, "effect_digest": _digest(outcome)}

    return spec, handle


def vgi_similarity_operator_spec() -> OperatorSpec:
    """One exact declarative contract for senders and admitted receivers."""
    return OperatorSpec(
        operator_id=SIMILARITY_OPERATOR_ID,
        version=1,
        description="Navigate exact VGI similarity Ground using receiver-admitted structural memory",
        input_kind="object", output_kind="object", substrates=("cpu",),
        required_rights=frozenset({"compute"}),
        base_energy=64, energy_per_byte=1,
        max_input_bytes=16_384, max_output_bytes=16_384,
        deterministic=True, effect_mode="pure",
    )


def register_vgi_similarity_operator(registry: OperatorRegistry,
                                     catalogue: PinnedSimilarityCatalogue, *,
                                     max_exponent_bits: int = MAX_EXPONENT_BITS) -> OperatorSpec:
    if not isinstance(registry, OperatorRegistry):
        raise SimilarityHostError("node requires an E-CPU OperatorRegistry")
    spec, handler = make_vgi_similarity_operator(catalogue, max_exponent_bits=max_exponent_bits)
    registry.register(spec, handler)
    return spec


def vgi_similarity_implementation_fingerprint(implementation_type: type | None = None) -> str:
    """Exact local source identity, not an external host attestation.

    Bind the host adapter, Transit adapter, exact VGI math implementations,
    and any separately defined receiver class to the restore identity.
    """
    import sys
    import vgi
    root = Path(vgi.__file__).resolve().parent
    mailcpu_dir = Path(__file__).resolve().parent
    paths = {
        "mailcpu/vgi_similarity_host.py": Path(__file__).resolve(),
        "mailcpu/vgi_similarity_native_memory.py": mailcpu_dir / "vgi_similarity_native_memory.py",
        "mailcpu/transit_vgi_similarity.py": mailcpu_dir / "transit_vgi_similarity.py",
    }
    for name in ("affine.py", "typed_operator_navigation.py", "similarity_blocks.py", "structural_memory.py"):
        paths[f"vgi/{name}"] = root / name
    if implementation_type is not None:
        module = sys.modules.get(implementation_type.__module__)
        module_file = getattr(module, '__file__', None)
        if not isinstance(module_file, str) or not module_file:
            raise SimilarityHostError("receiver implementation class source is not inspectable")
        extension = Path(module_file).resolve()
        if extension.suffix != '.py' or not extension.is_file():
            raise SimilarityHostError("receiver implementation class source is missing")
        if extension not in paths.values():
            paths[f"receiver/{implementation_type.__module__.replace('.', '/')}.py"] = extension
    for path in paths.values():
        if not path.is_file():
            raise SimilarityHostError("required VGI/E-CPU interpreter source is unavailable")
    return _digest({
        "schema": "vgi.similarity.implementation-source.v1",
        "implementation_type": None if implementation_type is None else
        f"{implementation_type.__module__}.{implementation_type.__qualname__}",
        "files": [{"name": name, "sha256": sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()}
                  for name,path in sorted(paths.items())],
    })