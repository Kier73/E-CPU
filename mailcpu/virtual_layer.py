"""Typed Virtual Layer workloads and hypervisor-governed pure operators.

The workload carries intent and a coordinate into a hosted system. It never
carries executable code or authority. A receiving HeadlessOS reconstructs
capabilities locally and the existing hypervisor decides whether an operator
may execute.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

from .classifier import HypervisorArbitrationEvent, HypervisorDomain, HypervisorExecutionResult, HypervisorRequest
from .hypervisor_transport import HypervisorOperationChannel
from .seed import SystemIdentity, SystemSeedEnvelope


class VirtualLayerError(ValueError):
    """A Virtual Layer workload, operator, or execution request is invalid."""


_JSON_KINDS = frozenset({"any", "object", "array", "integer", "number", "string", "boolean", "null"})
_EFFECT_MODES = frozenset({"pure", "idempotent", "transactional"})
_SUBSTRATES = frozenset({"cpu", "gpu", "fpga", "dpu", "network", "memory", "sensor", "delay-loop"})


def _validate_json(value: Any, label: str) -> None:
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise VirtualLayerError(f"{label} contains a non-finite number")
        return
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise VirtualLayerError(f"{label} object keys must be strings")
        for item in value.values():
            _validate_json(item, label)
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            _validate_json(item, label)
        return
    raise VirtualLayerError(f"{label} contains a value outside the JSON domain")


def _canonical_bytes(value: Any, label: str) -> bytes:
    """Encode a finite JSON value canonically; reject lossy or non-finite values."""

    _validate_json(value, label)
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise VirtualLayerError(f"{label} must be a finite canonical JSON value") from exc


class _FrozenDict(dict):
    """JSON-serializable dictionary that refuses mutation after construction."""

    def _immutable(self, *args: Any, **kwargs: Any) -> None:
        raise TypeError("Virtual Layer values are immutable")

    __setitem__ = _immutable
    __delitem__ = _immutable
    clear = _immutable
    pop = _immutable
    popitem = _immutable
    setdefault = _immutable
    update = _immutable
    __ior__ = _immutable


def _freeze_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return _FrozenDict({key: _freeze_json(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item) for item in value)
    return value


def _copy_json(value: Any, label: str) -> Any:
    """Detach caller-owned JSON containers from a frozen workload/specification."""

    return json.loads(_canonical_bytes(value, label).decode("utf-8"))


def _digest(value: Any, label: str = "value") -> str:
    return hashlib.sha256(_canonical_bytes(value, label)).hexdigest()


def _label(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise VirtualLayerError(f"{name} must be a non-empty string")
    return value


def _operator_id(value: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", value) is None:
        raise VirtualLayerError("operator_id must be a safe 1-128 character identifier")
    return value


def _positive_int(value: int, name: str, *, allow_zero: bool = False) -> int:
    minimum = 0 if allow_zero else 1
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        relation = "non-negative" if allow_zero else "positive"
        raise VirtualLayerError(f"{name} must be a {relation} integer")
    return value


def _value_matches(value: Any, kind: str) -> bool:
    if kind == "any":
        return True
    if kind == "object":
        return isinstance(value, Mapping)
    if kind == "array":
        return isinstance(value, list)
    if kind == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if kind == "number":
        if isinstance(value, int) and not isinstance(value, bool):
            return True
        return isinstance(value, float) and math.isfinite(value)
    if kind == "string":
        return isinstance(value, str)
    if kind == "boolean":
        return isinstance(value, bool)
    if kind == "null":
        return value is None
    return False


@dataclass(frozen=True)
class VirtualGroundRef:
    """A content-verified ground coordinate, including its causal input frontier."""

    origin_digest: str
    state_digest: str
    coordinate: int
    frontier_digest: str

    def __post_init__(self) -> None:
        for name, value in (("origin_digest", self.origin_digest), ("state_digest", self.state_digest), ("frontier_digest", self.frontier_digest)):
            if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
                raise VirtualLayerError(f"{name} must be a lowercase SHA-256 digest")
        _positive_int(self.coordinate, "ground coordinate", allow_zero=True)

    def to_dict(self) -> dict[str, object]:
        """Serialize the immutable ground and frontier coordinate."""
        return {"origin_digest": self.origin_digest, "state_digest": self.state_digest, "coordinate": self.coordinate, "frontier_digest": self.frontier_digest}

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "VirtualGroundRef":
        """Reconstruct a ground reference from its typed JSON projection."""
        if not isinstance(payload, Mapping):
            raise VirtualLayerError("ground reference must be an object")
        return cls(payload.get("origin_digest"), payload.get("state_digest"), payload.get("coordinate"), payload.get("frontier_digest"))

    @classmethod
    def from_envelope(cls, envelope: Any) -> "VirtualGroundRef":
        """Project the exact origin, state, coordinate and admitted input frontier of a seed envelope."""
        if not isinstance(envelope, SystemSeedEnvelope):
            raise VirtualLayerError("ground envelope is not a SystemSeedEnvelope")
        receipts = [receipt.snapshot() for receipt in envelope.input_frontier]
        receipts.sort(key=lambda item: (item["source"], item["sequence"]))
        return cls(envelope.seed.origin_digest, envelope.state_digest, envelope.seed.coordinate, _digest(receipts, "seed input frontier"))


@dataclass(frozen=True)
class VirtualBudget:
    """Hard per-operation limits expressed in virtual accounting units."""

    max_energy: int
    max_bytes: int
    max_virtual_ticks: int

    def __post_init__(self) -> None:
        _positive_int(self.max_energy, "max_energy")
        _positive_int(self.max_bytes, "max_bytes")
        _positive_int(self.max_virtual_ticks, "max_virtual_ticks")

    def to_dict(self) -> dict[str, int]:
        """Serialize hard virtual resource limits."""
        return {"max_energy": self.max_energy, "max_bytes": self.max_bytes, "max_virtual_ticks": self.max_virtual_ticks}

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "VirtualBudget":
        """Reconstruct hard virtual resource limits from a typed mapping."""
        if not isinstance(payload, Mapping):
            raise VirtualLayerError("budget must be an object")
        return cls(payload.get("max_energy"), payload.get("max_bytes"), payload.get("max_virtual_ticks"))


@dataclass(frozen=True)
class VirtualOperatorRef:
    """A name/version reference to an operator; never an executable payload."""

    operator_id: str
    version: int = 1
    preferred_substrate: str | None = None
    target_node: str | None = None

    def __post_init__(self) -> None:
        _operator_id(self.operator_id)
        _positive_int(self.version, "operator version")
        if self.preferred_substrate is not None and (not isinstance(self.preferred_substrate, str) or self.preferred_substrate not in _SUBSTRATES):
            raise VirtualLayerError("preferred_substrate is not a registered substrate kind")
        if self.target_node is not None:
            _label(self.target_node, "target_node")

    def to_dict(self) -> dict[str, object]:
        """Serialize the full declarative operator contract."""
        return {"operator_id": self.operator_id, "version": self.version, "preferred_substrate": self.preferred_substrate, "target_node": self.target_node}

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "VirtualOperatorRef":
        """Reconstruct a name/version reference without accepting executable code."""
        if not isinstance(payload, Mapping):
            raise VirtualLayerError("operator reference must be an object")
        return cls(payload.get("operator_id", ""), payload.get("version", 1), payload.get("preferred_substrate"), payload.get("target_node"))


@dataclass(frozen=True)
class VirtualLayerWorkload:
    """Portable request describing a goal, ground coordinate, and allowed operator references."""

    workload_id: str
    system: SystemIdentity
    ground: VirtualGroundRef
    intention: Mapping[str, Any]
    operators: tuple[VirtualOperatorRef, ...]
    input_value: Any
    budget: VirtualBudget
    logical_time: int
    eligible_nodes: tuple[str, ...] = ()
    max_hops: int = 1
    schema_version: int = 1

    def __post_init__(self) -> None:
        _label(self.workload_id, "workload_id")
        if not isinstance(self.system, SystemIdentity):
            raise VirtualLayerError("system must be a SystemIdentity")
        if not isinstance(self.ground, VirtualGroundRef):
            raise VirtualLayerError("ground must be a VirtualGroundRef")
        if not isinstance(self.intention, Mapping) or "goal" not in self.intention:
            raise VirtualLayerError("intention must be an object containing a goal")
        intention = _copy_json(dict(self.intention), "intention")
        if not intention:
            raise VirtualLayerError("intention must not be empty")
        object.__setattr__(self, "intention", _freeze_json(intention))
        operators = tuple(self.operators)
        if not operators:
            raise VirtualLayerError("workload requires at least one ordered operator reference")
        if any(not isinstance(item, VirtualOperatorRef) for item in operators):
            raise VirtualLayerError("operators must contain VirtualOperatorRef values")
        object.__setattr__(self, "operators", operators)
        if len({item.operator_id for item in operators}) != len(operators):
            raise VirtualLayerError("workload operator IDs must be unique")
        object.__setattr__(self, "input_value", _freeze_json(_copy_json(self.input_value, "input_value")))
        if not isinstance(self.budget, VirtualBudget):
            raise VirtualLayerError("budget must be a VirtualBudget")
        _positive_int(self.logical_time, "logical_time", allow_zero=True)
        _positive_int(self.max_hops, "max_hops")
        _positive_int(self.schema_version, "schema_version")
        if self.schema_version != 1:
            raise VirtualLayerError("unsupported Virtual Layer workload schema version")
        if not isinstance(self.eligible_nodes, (tuple, list)):
            raise VirtualLayerError("eligible_nodes must be a sequence")
        nodes = tuple(_label(node, "eligible node") for node in self.eligible_nodes)
        if len(nodes) != len(set(nodes)):
            raise VirtualLayerError("eligible_nodes must be unique")
        object.__setattr__(self, "eligible_nodes", nodes)

    def operator_ref(self, operator_id: str) -> VirtualOperatorRef:
        """Resolve exactly one workload-authorized reference for an operator ID."""
        _operator_id(operator_id)
        matches = [item for item in self.operators if item.operator_id == operator_id]
        if len(matches) != 1:
            raise VirtualLayerError(f"operator is not authorized by workload: {operator_id}")
        return matches[0]

    def to_dict(self) -> dict[str, object]:
        """Serialize the complete portable workload envelope."""
        return {
            "kind": "virtual_layer.workload",
            "schema_version": self.schema_version,
            "workload_id": self.workload_id,
            "system": self.system.snapshot(),
            "ground": self.ground.to_dict(),
            "intention": _copy_json(dict(self.intention), "intention"),
            "operators": [item.to_dict() for item in self.operators],
            "input_value": _copy_json(self.input_value, "input_value"),
            "budget": self.budget.to_dict(),
            "logical_time": self.logical_time,
            "eligible_nodes": list(self.eligible_nodes),
            "max_hops": self.max_hops,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "VirtualLayerWorkload":
        """Reconstruct and validate a workload from its wire representation."""
        if not isinstance(payload, Mapping) or payload.get("kind") != "virtual_layer.workload":
            raise VirtualLayerError("invalid Virtual Layer workload envelope")
        raw_nodes = payload.get("eligible_nodes", [])
        if not isinstance(raw_nodes, list):
            raise VirtualLayerError("eligible_nodes must be a JSON array")
        system, ground, budget, intention = (payload.get(key) for key in ("system", "ground", "budget", "intention"))
        operators = payload.get("operators")
        if not all(isinstance(item, Mapping) for item in (system, ground, budget, intention)) or not isinstance(operators, list):
            raise VirtualLayerError("Virtual Layer workload is missing typed fields")
        try:
            return cls(
                payload.get("workload_id", ""), SystemIdentity.from_snapshot(system), VirtualGroundRef.from_dict(ground), intention,
                tuple(VirtualOperatorRef.from_dict(item) for item in operators), payload.get("input_value"), VirtualBudget.from_dict(budget),
                payload.get("logical_time"), tuple(raw_nodes), payload.get("max_hops", 1), payload.get("schema_version", 1),
            )
        except (TypeError, ValueError, KeyError) as exc:
            if isinstance(exc, VirtualLayerError):
                raise
            raise VirtualLayerError("Virtual Layer workload contains invalid typed fields") from exc

    @property
    def digest(self) -> str:
        """Return the SHA-256 identity of the complete canonical workload."""
        return _digest(self.to_dict(), "workload")


@dataclass(frozen=True)
class OperatorSpec:
    """Declarative operator contract; implementation functions remain node-local."""

    operator_id: str
    version: int
    description: str
    input_kind: str
    output_kind: str
    substrates: tuple[str, ...]
    required_rights: frozenset[str] = field(default_factory=lambda: frozenset({"compute"}))
    base_energy: int = 1
    energy_per_byte: int = 1
    max_input_bytes: int = 1_048_576
    max_output_bytes: int = 1_048_576
    deterministic: bool = True
    effect_mode: str = "pure"

    def __post_init__(self) -> None:
        _operator_id(self.operator_id)
        _label(self.description, "description")
        _positive_int(self.version, "operator version")
        if not isinstance(self.input_kind, str) or not isinstance(self.output_kind, str) or self.input_kind not in _JSON_KINDS or self.output_kind not in _JSON_KINDS:
            raise VirtualLayerError("operator input_kind/output_kind must be supported JSON kinds")
        if not isinstance(self.substrates, (tuple, list)):
            raise VirtualLayerError("operator substrates must be a sequence")
        substrates = tuple(self.substrates)
        if not substrates or any(not isinstance(item, str) or item not in _SUBSTRATES for item in substrates):
            raise VirtualLayerError("operator requires one or more supported substrates")
        if len(set(substrates)) != len(substrates):
            raise VirtualLayerError("operator substrates must be unique")
        object.__setattr__(self, "substrates", substrates)
        if not isinstance(self.required_rights, (set, frozenset, tuple, list)):
            raise VirtualLayerError("operator rights must be a collection")
        rights = frozenset(self.required_rights)
        if any(not isinstance(item, str) or not item for item in rights):
            raise VirtualLayerError("operator rights must be non-empty strings")
        object.__setattr__(self, "required_rights", rights)
        _positive_int(self.base_energy, "base_energy", allow_zero=True)
        _positive_int(self.energy_per_byte, "energy_per_byte", allow_zero=True)
        _positive_int(self.max_input_bytes, "max_input_bytes")
        _positive_int(self.max_output_bytes, "max_output_bytes")
        if not isinstance(self.deterministic, bool):
            raise VirtualLayerError("deterministic must be boolean")
        if not isinstance(self.effect_mode, str) or self.effect_mode not in _EFFECT_MODES:
            raise VirtualLayerError("unsupported operator effect_mode")

    @property
    def replay_safe(self) -> bool:
        """Only deterministic, side-effect-free handlers are admitted by this first executor."""
        return self.deterministic and self.effect_mode == "pure"

    @property
    def digest(self) -> str:
        """Return the content identity of this operator contract alone."""
        return _digest(self.to_dict(), "operator contract")

    def estimated_energy(self, input_bytes: int) -> int:
        """Estimate deterministic virtual energy from input bytes and contract coefficients."""
        _positive_int(input_bytes, "input_bytes", allow_zero=True)
        return self.base_energy + self.energy_per_byte * input_bytes

    def to_dict(self) -> dict[str, object]:
        """Serialize the full declarative operator contract."""
        return {
            "operator_id": self.operator_id, "version": self.version, "description": self.description,
            "input_kind": self.input_kind, "output_kind": self.output_kind, "substrates": list(self.substrates),
            "required_rights": sorted(self.required_rights), "base_energy": self.base_energy,
            "energy_per_byte": self.energy_per_byte, "max_input_bytes": self.max_input_bytes,
            "max_output_bytes": self.max_output_bytes, "deterministic": self.deterministic, "effect_mode": self.effect_mode,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "OperatorSpec":
        """Reconstruct a declarative operator contract from canonical catalog data."""
        if not isinstance(payload, Mapping):
            raise VirtualLayerError("operator specification must be an object")
        try:
            return cls(
                str(payload.get("operator_id", "")), payload.get("version"), payload.get("description", ""),
                payload.get("input_kind", ""), payload.get("output_kind", ""), tuple(payload.get("substrates", ())),
                frozenset(payload.get("required_rights", ("compute",))), payload.get("base_energy", 1),
                payload.get("energy_per_byte", 1), payload.get("max_input_bytes", 1_048_576),
                payload.get("max_output_bytes", 1_048_576), payload.get("deterministic", True), str(payload.get("effect_mode", "pure")),
            )
        except (TypeError, ValueError) as exc:
            if isinstance(exc, VirtualLayerError):
                raise
            raise VirtualLayerError("operator specification contains invalid fields") from exc


OperatorHandler = Callable[[Any, VirtualLayerWorkload], Any]


class OperatorRegistry:
    """Node-local, versioned operator catalog with a canonical manifest digest."""

    def __init__(self) -> None:
        self._entries: dict[tuple[str, int], tuple[OperatorSpec, OperatorHandler | None]] = {}

    def register(self, spec: OperatorSpec, handler: OperatorHandler) -> None:
        """Register a contract and its trusted node-local implementation atomically."""
        if not isinstance(spec, OperatorSpec) or not callable(handler):
            raise VirtualLayerError("register requires an OperatorSpec and callable local handler")
        key = (spec.operator_id, spec.version)
        if key in self._entries:
            raise VirtualLayerError(f"operator already registered: {spec.operator_id}@{spec.version}")
        self._entries[key] = (spec, handler)

    def declare(self, spec: OperatorSpec) -> None:
        """Install portable metadata without importing or executing remote code."""
        if not isinstance(spec, OperatorSpec):
            raise VirtualLayerError("registry declaration requires an OperatorSpec")
        key = (spec.operator_id, spec.version)
        if key in self._entries:
            raise VirtualLayerError(f"operator already registered: {spec.operator_id}@{spec.version}")
        self._entries[key] = (spec, None)

    def bind(self, operator_id: str, version: int, handler: OperatorHandler) -> None:
        """Bind a trusted node-local implementation to an already declared contract."""
        _operator_id(operator_id)
        _positive_int(version, "operator version")
        if not callable(handler):
            raise VirtualLayerError("operator handler must be callable")
        key = (operator_id, version)
        if key not in self._entries:
            raise VirtualLayerError(f"operator contract is not declared: {operator_id}@{version}")
        spec, previous = self._entries[key]
        if previous is not None:
            raise VirtualLayerError(f"operator handler already bound: {operator_id}@{version}")
        self._entries[key] = (spec, handler)

    def contract(self, operator_id: str, version: int = 1) -> OperatorSpec:
        """Return declarative metadata without requiring an executable local handler."""
        _operator_id(operator_id)
        _positive_int(version, "operator version")
        try:
            return self._entries[(operator_id, version)][0]
        except KeyError as exc:
            raise VirtualLayerError(f"operator contract is unavailable: {operator_id}@{version}") from exc

    def resolve(self, operator_id: str, version: int = 1) -> tuple[OperatorSpec, OperatorHandler]:
        """Return an available contract and local handler, refusing unbound declarations."""
        _operator_id(operator_id)
        _positive_int(version, "operator version")
        try:
            spec, handler = self._entries[(operator_id, version)]
        except KeyError as exc:
            raise VirtualLayerError(f"operator is unavailable: {operator_id}@{version}") from exc
        if handler is None:
            raise VirtualLayerError(f"operator has no trusted local implementation: {operator_id}@{version}")
        return spec, handler

    def specs(self) -> tuple[OperatorSpec, ...]:
        """Return all declared contracts in deterministic operator-ID order."""
        return tuple(self._entries[key][0] for key in sorted(self._entries))

    def manifest(self) -> dict[str, object]:
        """Return the canonical, executable-code-free operator catalog manifest."""
        return {"kind": "virtual_layer.operator_catalog", "version": 1, "operators": [spec.to_dict() for spec in self.specs()]}

    @property
    def digest(self) -> str:
        """Return the SHA-256 identity of the declarative operator manifest."""
        return _digest(self.manifest(), "operator manifest")

    def snapshot(self) -> dict[str, object]:
        """Return declarative state only; executable handlers must be rebound by the receiving node."""
        return self.manifest() | {"digest": self.digest}

    @classmethod
    def from_snapshot(cls, payload: Mapping[str, Any], handlers: Mapping[tuple[str, int], OperatorHandler] | None = None) -> "OperatorRegistry":
        """Restore contracts and bind only explicitly supplied node-local handlers."""
        if not isinstance(payload, Mapping) or payload.get("kind") != "virtual_layer.operator_catalog" or payload.get("version") != 1:
            raise VirtualLayerError("unsupported operator catalog snapshot")
        raw_specs = payload.get("operators")
        if not isinstance(raw_specs, list):
            raise VirtualLayerError("operator catalog must contain an operator list")
        registry = cls()
        for raw in raw_specs:
            if not isinstance(raw, Mapping):
                raise VirtualLayerError("operator catalog entry must be an object")
            registry.declare(OperatorSpec.from_dict(raw))
        expected = payload.get("digest")
        if expected is not None and expected != registry.digest:
            raise VirtualLayerError("operator catalog digest mismatch")
        for key, handler in (handlers or {}).items():
            if not isinstance(key, tuple) or len(key) != 2:
                raise VirtualLayerError("handler bindings must use (operator_id, version) keys")
            registry.bind(key[0], key[1], handler)
        return registry


@dataclass(frozen=True)
class VirtualLayerRuntime:
    """Adapter that executes pure operators through MailCPU's existing hypervisor and reliable operation channel."""

    registry: OperatorRegistry
    node_id: str
    substrates: frozenset[str]
    virtual_capacity: int = 64
    max_energy: int = 10_000_000
    max_bytes: int = 4_194_304
    max_virtual_ticks: int = 100_000

    def __post_init__(self) -> None:
        if not isinstance(self.registry, OperatorRegistry):
            raise VirtualLayerError("runtime requires an OperatorRegistry")
        _label(self.node_id, "node_id")
        substrates = frozenset(self.substrates)
        if not substrates or any(not isinstance(item, str) or item not in _SUBSTRATES for item in substrates):
            raise VirtualLayerError("runtime requires supported local substrates")
        object.__setattr__(self, "substrates", substrates)
        _positive_int(self.virtual_capacity, "virtual_capacity")
        _positive_int(self.max_energy, "local max_energy")
        _positive_int(self.max_bytes, "local max_bytes")
        _positive_int(self.max_virtual_ticks, "local max_virtual_ticks")

    def _resolve_operator(self, workload: VirtualLayerWorkload, operator_id: str, *, enforce_placement: bool = True, require_handler: bool = True) -> tuple[VirtualOperatorRef, OperatorSpec, OperatorHandler | None, Any, int, int, int]:
        """Validate the workload-to-operator binding and calculate deterministic virtual cost."""
        reference = workload.operator_ref(operator_id)
        spec, handler = self.registry.resolve(reference.operator_id, reference.version) if require_handler else (self.registry.contract(reference.operator_id, reference.version), None)
        if not spec.replay_safe:
            raise VirtualLayerError("distributed Virtual Layer execution requires deterministic pure operators")
        if reference.preferred_substrate is not None and reference.preferred_substrate not in spec.substrates:
            raise VirtualLayerError("operator does not support the requested preferred substrate")
        if enforce_placement:
            if not (self.substrates & set(spec.substrates)):
                raise VirtualLayerError("operator has no substrate supported by this node")
            if reference.preferred_substrate is not None and reference.preferred_substrate not in self.substrates:
                raise VirtualLayerError("preferred substrate is not available on this node")
            if reference.target_node is not None and reference.target_node != self.node_id:
                raise VirtualLayerError("operator is assigned to a different node")
            if workload.eligible_nodes and self.node_id not in workload.eligible_nodes:
                raise VirtualLayerError("this node is outside the workload's eligible node set")
        input_value = _copy_json(workload.input_value, "input_value")
        if not _value_matches(input_value, spec.input_kind):
            raise VirtualLayerError(f"operator input does not match {spec.input_kind}")
        input_bytes = len(_canonical_bytes(input_value, "input_value"))
        if input_bytes > spec.max_input_bytes or input_bytes > min(workload.budget.max_bytes, self.max_bytes):
            raise VirtualLayerError("operator input exceeds byte budget")
        energy = spec.estimated_energy(input_bytes)
        ticks = max(1, math.ceil(energy / self.virtual_capacity))
        if energy > min(workload.budget.max_energy, self.max_energy):
            raise VirtualLayerError("operator exceeds virtual energy budget")
        if ticks > min(workload.budget.max_virtual_ticks, self.max_virtual_ticks):
            raise VirtualLayerError("operator exceeds virtual tick budget")
        return reference, spec, handler, input_value, input_bytes, energy, ticks

    def _validate_ground(self, operating_system: Any, workload: VirtualLayerWorkload) -> None:
        """Require exact local admission of system identity, ground state, coordinate and causal frontier."""
        admission = getattr(operating_system, "seed_admission", None)
        if admission is None or not callable(getattr(admission, "current", None)):
            raise VirtualLayerError("host does not expose the admitted Virtual Ground registry")
        envelope = admission.current(workload.system.system_id)
        if envelope is None:
            raise VirtualLayerError("Virtual Ground is not admitted on this host")
        local_ground = VirtualGroundRef.from_envelope(envelope)
        if envelope.identity != workload.system or local_ground != workload.ground:
            raise VirtualLayerError("workload Virtual Ground or causal frontier is stale or mismatched")

    def build_event(self, source: str, channel: str, sequence: int, logical_time: int, workload: VirtualLayerWorkload, operator_id: str) -> HypervisorArbitrationEvent:
        """Build a typed operation event; it contains operator references, never executable code or authority."""
        if not isinstance(workload, VirtualLayerWorkload):
            raise VirtualLayerError("event construction requires a VirtualLayerWorkload")
        if logical_time != workload.logical_time:
            raise VirtualLayerError("event logical time must match workload logical time")
        reference, spec, _, input_value, input_bytes, energy, ticks = self._resolve_operator(workload, operator_id, enforce_placement=False, require_handler=False)
        operation = "cpu register arithmetic instruction scheduling program execution virtual layer pure operator transformation"
        resource = f"/virtual-layer/operators/{spec.operator_id}@{spec.version}"
        request = HypervisorRequest(
            operation=operation,
            resource=resource,
            payload={
                "workload": workload.to_dict(), "workload_digest": workload.digest,
                "operator_id": spec.operator_id, "operator_version": spec.version,
                "operator_contract_digest": spec.digest, "input_digest": _digest(input_value, "operator input"),
                "estimated_energy": energy, "estimated_virtual_ticks": ticks, "input_bytes": input_bytes,
            },
            required_rights=spec.required_rights, granted_rights=frozenset(), destructive=False,
        )
        return HypervisorArbitrationEvent(source, channel, sequence, logical_time, request)

    def _prepare_event(self, operating_system: Any, pid: int, event: HypervisorArbitrationEvent) -> tuple[HypervisorArbitrationEvent, Callable[[], dict[str, object]]]:
        """Validate a received event, rebuild local authority, and prepare its pure local handler."""
        if not isinstance(event, HypervisorArbitrationEvent):
            raise VirtualLayerError("received operation is not a HypervisorArbitrationEvent")
        if not callable(getattr(operating_system, "hypervisor_authorize_event", None)) or not hasattr(operating_system, "hypervisor_arbitration"):
            raise VirtualLayerError("host does not expose hypervisor event authorization and arbitration")
        request = event.request
        expected_operation = "cpu register arithmetic instruction scheduling program execution virtual layer pure operator transformation"
        if request.operation != expected_operation or request.destructive:
            raise VirtualLayerError("operation event does not match the Virtual Layer execution contract")
        payload = request.payload
        if not isinstance(payload, Mapping) or not isinstance(payload.get("workload"), Mapping):
            raise VirtualLayerError("operation event does not contain a typed workload")
        workload = VirtualLayerWorkload.from_dict(payload["workload"])
        if event.logical_time != workload.logical_time or payload.get("workload_digest") != workload.digest:
            raise VirtualLayerError("workload digest or event-time mismatch")
        operator_id, version = payload.get("operator_id"), payload.get("operator_version")
        if not isinstance(operator_id, str) or not isinstance(version, int) or isinstance(version, bool):
            raise VirtualLayerError("operation event has an invalid operator reference")
        reference, spec, handler, input_value, input_bytes, energy, ticks = self._resolve_operator(workload, operator_id)
        if payload.get("operator_contract_digest") != spec.digest:
            raise VirtualLayerError("operator contract does not match this execution node")
        if handler is None or reference.version != version:
            raise VirtualLayerError("operator implementation or version is unavailable")
        if request.resource != f"/virtual-layer/operators/{spec.operator_id}@{spec.version}" or request.required_rights != spec.required_rights:
            raise VirtualLayerError("operation resource or required rights differ from the local operator contract")
        if payload.get("input_digest") != _digest(input_value, "operator input"):
            raise VirtualLayerError("operator input digest mismatch")
        for field_name, expected in (("input_bytes", input_bytes), ("estimated_energy", energy), ("estimated_virtual_ticks", ticks)):
            claimed = payload.get(field_name)
            if not isinstance(claimed, int) or isinstance(claimed, bool) or claimed != expected:
                raise VirtualLayerError(f"operator {field_name} does not match local recalculation")
        self._validate_ground(operating_system, workload)
        authorized_event = operating_system.hypervisor_authorize_event(pid, event)

        def invoke() -> dict[str, object]:
            """Execute the local pure operator and return a canonical, digest-bound result effect."""
            result = handler(input_value, workload)
            if not _value_matches(result, spec.output_kind):
                raise VirtualLayerError(f"operator output does not match {spec.output_kind}")
            result_copy = _copy_json(result, "operator output")
            result_bytes = len(_canonical_bytes(result_copy, "operator output"))
            if result_bytes > spec.max_output_bytes or input_bytes + result_bytes > min(workload.budget.max_bytes, self.max_bytes):
                raise VirtualLayerError("operator output exceeds its declared or workload byte budget")
            return {
                "kind": "virtual_layer.operator_result", "schema_version": 1,
                "workload_id": workload.workload_id, "workload_digest": workload.digest,
                "operator_id": spec.operator_id, "operator_version": spec.version,
                "operator_contract_digest": spec.digest, "node_id": self.node_id,
                "substrate": reference.preferred_substrate or next(item for item in spec.substrates if item in self.substrates),
                "ground": workload.ground.to_dict(), "logical_time": workload.logical_time,
                "estimated_energy": energy, "estimated_virtual_ticks": ticks,
                "input_digest": _digest(input_value, "operator input"),
                "result_digest": _digest(result_copy, "operator output"), "result": result_copy,
            }

        return authorized_event, invoke

    def execute_operator(self, operating_system: Any, pid: int, source: str, channel: str, sequence: int, logical_time: int, workload: VirtualLayerWorkload, operator_id: str) -> HypervisorExecutionResult:
        """Execute one local pure operator through the existing hypervisor decision and effect ledgers."""
        event = self.build_event(source, channel, sequence, logical_time, workload, operator_id)
        authorized, invoke = self._prepare_event(operating_system, pid, event)
        return operating_system.hypervisor_arbitration.execute(authorized, {HypervisorDomain.CPU: invoke})

    def receive_and_execute(self, operation_channel: HypervisorOperationChannel, operating_system: Any, pid: int) -> HypervisorExecutionResult | None:
        """Receive a reliable operation frame, resolve its operator locally, authorize it, execute, then acknowledge."""
        if not isinstance(operation_channel, HypervisorOperationChannel):
            raise VirtualLayerError("remote execution requires a HypervisorOperationChannel")
        prepared: dict[str, Callable[[], dict[str, object]]] = {}

        def authorize(event: HypervisorArbitrationEvent) -> HypervisorArbitrationEvent:
            """Validate the workload and rebuild receiver-local capability grants before policy evaluation."""
            authorized, invoke = self._prepare_event(operating_system, pid, event)
            prepared["invoke"] = invoke
            return authorized

        def invoke_prepared() -> dict[str, object]:
            """Invoke the one handler prepared from the currently peeked and validated reliable event."""
            handler = prepared.get("invoke")
            if handler is None:
                raise VirtualLayerError("no Virtual Layer operator was prepared for the received event")
            return handler()

        return operation_channel.receive_and_execute(operating_system.hypervisor_arbitration, authorize, {HypervisorDomain.CPU: invoke_prepared})
