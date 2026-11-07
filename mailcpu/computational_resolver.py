"""Mathematics: Semantic addressing and non-authoritative resolution of computational host loci.

A computational address names a workload, its computational Ground, program
identity (when exact), state/input coordinate, and output observation. A local
catalogue advertises logical hosts; resolution checks that metadata against the
workload and live receiver capabilities, then returns a digest-bound route
witness. It never grants authority or executes an operator.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
import math
import re
from typing import Any, Mapping, Sequence

from .evidence_path_resolver import RouteMetric, RouteMetricKey
from .headless import HeadlessOS
from .kernel import ProcessStatus
from .semantic_translation import canonical_value_digest
from .structural_memory import StructuralMemoryError, StructuralMemoryReadReceipt
from .virtual_layer import (
    OperatorSpec,
    VirtualLayerError,
    VirtualLayerRuntime,
    VirtualLayerWorkload,
    virtual_layer_operator_resource,
)

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_HOST_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}\Z")
_DEFAULT_METRICS = (
    RouteMetricKey("latency", "ticks"),
    RouteMetricKey("energy", "units"),
    RouteMetricKey("bytes", "bytes"),
    RouteMetricKey("risk", "score"),
)
_MAX_LOCI = 4096


class ComputationalResolutionError(ValueError):
    """Mathematics: A semantic address or computational-host catalogue is invalid."""


class ComputationalResolutionStatus(str, Enum):
    """Mathematics: Non-authoritative outcome of one bounded local semantic-address resolution."""

    FOUND = "found"
    UNREACHABLE = "unreachable"
    BLOCKED = "blocked"
    BUDGET_EXHAUSTED = "budget_exhausted"


class ComputationalBlockerCode(str, Enum):
    """Mathematics: Deterministic reason why one candidate host cannot satisfy an address."""

    OPERATOR_MISMATCH = "operator_mismatch"
    CONTRACT_MISMATCH = "contract_mismatch"
    GROUND_MISMATCH = "ground_mismatch"
    PROGRAM_MISMATCH = "program_mismatch"
    PLACEMENT_MISMATCH = "placement_mismatch"
    SUBSTRATE_MISMATCH = "substrate_mismatch"
    OBSERVATION_MISMATCH = "observation_mismatch"
    INPUT_MISMATCH = "input_mismatch"
    STATE_UNAVAILABLE = "state_unavailable"
    AUTHORITY_MISSING = "authority_missing"
    HOST_UNAVAILABLE = "host_unavailable"
    RESOURCE_LIMIT = "resource_limit"
    METRIC_MISMATCH = "metric_mismatch"


def _label(value: Any, name: str, maximum: int = 256) -> str:
    """Mathematics: Validate one bounded non-empty identifier or display label."""
    if not isinstance(value, str) or not value or value.strip() != value or len(value.encode("utf-8")) > maximum:
        raise ComputationalResolutionError(f"{name} must be non-empty trimmed text of at most {maximum} UTF-8 bytes")
    return value


def _digest(value: Any, name: str) -> str:
    """Mathematics: Require a lowercase SHA-256 digest string."""
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ComputationalResolutionError(f"{name} must be a lowercase SHA-256 digest")
    return value


def _canonical_bytes(value: Any) -> bytes:
    """Mathematics: Encode a detached JSON value using the resolver's canonical byte form."""
    try:
        return json.dumps(
            _plain(value),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ComputationalResolutionError("address value is outside finite canonical JSON") from exc


def _plain(value: Any) -> Any:
    """Mathematics: Detach frozen mappings and tuples into ordinary JSON containers."""
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


def _value_matches(value: Any, kind: str) -> bool:
    """Mathematics: Check whether an inline JSON value matches a Virtual Layer input kind."""
    if kind == "any":
        return True
    if kind == "object":
        return isinstance(value, Mapping)
    if kind == "array":
        return isinstance(value, (tuple, list))
    if kind == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if kind == "number":
        return (isinstance(value, int) and not isinstance(value, bool)) or (
            isinstance(value, float) and math.isfinite(value)
        )
    if kind == "string":
        return isinstance(value, str)
    if kind == "boolean":
        return isinstance(value, bool)
    if kind == "null":
        return value is None
    return False


@dataclass(frozen=True)
class ComputationalAddress:
    """Mathematics: Portable semantic address; it contains no executable handler or authority."""

    workload: VirtualLayerWorkload
    operator_id: str
    operator_contract_digest: str
    computational_ground_fingerprint: str
    program_fingerprint: str | None
    observation_kind: str
    metric_order: tuple[RouteMetricKey, ...] = _DEFAULT_METRICS
    resource_ceilings: tuple[RouteMetric, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.workload, VirtualLayerWorkload):
            raise ComputationalResolutionError("computational address requires a VirtualLayerWorkload")
        _label(self.operator_id, "operator_id", 128)
        _digest(self.operator_contract_digest, "operator_contract_digest")
        _digest(self.computational_ground_fingerprint, "computational_ground_fingerprint")
        if self.program_fingerprint is not None:
            _digest(self.program_fingerprint, "program_fingerprint")
        _label(self.observation_kind, "observation_kind", 64)
        try:
            reference = self.workload.operator_ref(self.operator_id)
        except VirtualLayerError as exc:
            raise ComputationalResolutionError(str(exc)) from exc
        metrics = tuple(self.metric_order)
        if not metrics or any(not isinstance(item, RouteMetricKey) for item in metrics):
            raise ComputationalResolutionError("metric_order must contain RouteMetricKey values")
        if len({item.name for item in metrics}) != len(metrics):
            raise ComputationalResolutionError("metric_order names must be unique")
        object.__setattr__(self, "metric_order", metrics)
        ceilings = tuple(self.resource_ceilings)
        if any(not isinstance(item, RouteMetric) for item in ceilings):
            raise ComputationalResolutionError("resource_ceilings must contain RouteMetric values")
        if len({item.name for item in ceilings}) != len(ceilings):
            raise ComputationalResolutionError("resource ceiling names must be unique")
        by_name = {item.name: item for item in metrics}
        for ceiling in ceilings:
            key = by_name.get(ceiling.name)
            if key is None or key.unit != ceiling.unit:
                raise ComputationalResolutionError("resource ceiling is outside the address metric basis")
        object.__setattr__(self, "resource_ceilings", tuple(sorted(ceilings, key=lambda item: item.name)))
        if reference.version < 1:
            raise ComputationalResolutionError("operator version must be positive")

    @classmethod
    def from_workload(
        cls,
        workload: VirtualLayerWorkload,
        operator_id: str,
        operator_spec: OperatorSpec,
        computational_ground_fingerprint: str,
        *,
        program_fingerprint: str | None = None,
        metric_order: Sequence[RouteMetricKey] = _DEFAULT_METRICS,
        resource_ceilings: Sequence[RouteMetric] = (),
    ) -> "ComputationalAddress":
        """Mathematics: Bind the address to the exact locally declared operator contract."""
        if not isinstance(operator_spec, OperatorSpec):
            raise ComputationalResolutionError("address construction requires an OperatorSpec")
        try:
            reference = workload.operator_ref(operator_id)
        except (AttributeError, VirtualLayerError) as exc:
            raise ComputationalResolutionError(str(exc)) from exc
        if reference.version != operator_spec.version or reference.operator_id != operator_spec.operator_id:
            raise ComputationalResolutionError("operator specification differs from the workload operator reference")
        return cls(
            workload=workload,
            operator_id=operator_id,
            operator_contract_digest=operator_spec.digest,
            computational_ground_fingerprint=computational_ground_fingerprint,
            program_fingerprint=program_fingerprint,
            observation_kind=operator_spec.output_kind,
            metric_order=tuple(metric_order),
            resource_ceilings=tuple(resource_ceilings),
        )

    @property
    def input_digest(self) -> str:
        """Mathematics: Return the identity of the exact inline input envelope."""
        return canonical_value_digest(_plain(self.workload.input_value))

    @property
    def state_digest(self) -> str:
        """Mathematics: Return the identity of inline input plus pinned Structural Memory coordinates."""
        reference = self.workload.operator_ref(self.operator_id)
        return canonical_value_digest({
            "input_digest": self.input_digest,
            "structural_memory": [item.to_dict() for item in reference.structural_memory],
        })

    @property
    def digest(self) -> str:
        """Mathematics: Return the content identity of this complete semantic address."""
        return canonical_value_digest(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        """Mathematics: Serialize the typed workload address without code or authority."""
        return {
            "schema": "mailcpu.computational-address.v1",
            "workload": self.workload.to_dict(),
            "operator_id": self.operator_id,
            "operator_contract_digest": self.operator_contract_digest,
            "computational_ground_fingerprint": self.computational_ground_fingerprint,
            "program_fingerprint": self.program_fingerprint,
            "observation_kind": self.observation_kind,
            "metric_order": [item.to_dict() for item in self.metric_order],
            "resource_ceilings": [item.to_dict() for item in self.resource_ceilings],
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ComputationalAddress":
        """Mathematics: Reconstruct an address only from its exact versioned JSON schema."""
        expected = {
            "schema", "workload", "operator_id", "operator_contract_digest",
            "computational_ground_fingerprint", "program_fingerprint",
            "observation_kind", "metric_order", "resource_ceilings",
        }
        if (
            not isinstance(payload, Mapping)
            or set(payload) != expected
            or payload.get("schema") != "mailcpu.computational-address.v1"
            or not isinstance(payload.get("workload"), Mapping)
            or not isinstance(payload.get("metric_order"), list)
            or not isinstance(payload.get("resource_ceilings"), list)
        ):
            raise ComputationalResolutionError("computational address schema or fields are invalid")
        return cls(
            workload=VirtualLayerWorkload.from_dict(payload["workload"]),
            operator_id=payload["operator_id"],
            operator_contract_digest=payload["operator_contract_digest"],
            computational_ground_fingerprint=payload["computational_ground_fingerprint"],
            program_fingerprint=payload["program_fingerprint"],
            observation_kind=payload["observation_kind"],
            metric_order=tuple(RouteMetricKey.from_dict(item) for item in payload["metric_order"]),
            resource_ceilings=tuple(RouteMetric.from_dict(item) for item in payload["resource_ceilings"]),
        )


@dataclass(frozen=True)
class ComputationalHostLocus:
    """Mathematics: Local declarative advertisement for one logical host/operator pair."""

    host_id: str
    node_id: str
    authority_pid: int
    operator_spec: OperatorSpec
    substrates: tuple[str, ...]
    computational_ground_fingerprints: tuple[str, ...]
    program_fingerprints: tuple[str, ...]
    supports_ground_program_compilation: bool
    supports_structural_memory: bool
    implementation_fingerprint: str | None
    costs: tuple[RouteMetric, ...]
    virtual_capacity: int
    max_energy: int
    max_bytes: int
    max_virtual_ticks: int

    def __post_init__(self) -> None:
        if not isinstance(self.host_id, str) or _HOST_ID.fullmatch(self.host_id) is None:
            raise ComputationalResolutionError("host_id must be a safe logical-host identifier")
        _label(self.node_id, "node_id", 128)
        if type(self.authority_pid) is not int or self.authority_pid < 1:
            raise ComputationalResolutionError("authority_pid must be a positive strict integer")
        if not isinstance(self.operator_spec, OperatorSpec):
            raise ComputationalResolutionError("host locus requires an OperatorSpec")
        substrates = tuple(self.substrates)
        if not substrates or any(item not in self.operator_spec.substrates for item in substrates):
            raise ComputationalResolutionError("host substrates must be supported by the operator contract")
        if len(set(substrates)) != len(substrates):
            raise ComputationalResolutionError("host substrates must be unique")
        object.__setattr__(self, "substrates", tuple(sorted(substrates)))
        grounds = tuple(self.computational_ground_fingerprints)
        for value in grounds:
            _digest(value, "host computational Ground fingerprint")
        if not grounds or len(set(grounds)) != len(grounds):
            raise ComputationalResolutionError("host must advertise unique computational Ground fingerprints")
        object.__setattr__(self, "computational_ground_fingerprints", tuple(sorted(grounds)))
        programs = tuple(self.program_fingerprints)
        for value in programs:
            _digest(value, "host program fingerprint")
        if len(set(programs)) != len(programs):
            raise ComputationalResolutionError("host program fingerprints must be unique")
        object.__setattr__(self, "program_fingerprints", tuple(sorted(programs)))
        if not isinstance(self.supports_ground_program_compilation, bool):
            raise ComputationalResolutionError("supports_ground_program_compilation must be boolean")
        if not isinstance(self.supports_structural_memory, bool):
            raise ComputationalResolutionError("supports_structural_memory must be boolean")
        if self.implementation_fingerprint is not None:
            _digest(self.implementation_fingerprint, "host implementation_fingerprint")
        metrics = tuple(self.costs)
        if not metrics or any(not isinstance(item, RouteMetric) for item in metrics):
            raise ComputationalResolutionError("host locus requires a non-empty cost vector")
        if len({item.name for item in metrics}) != len(metrics):
            raise ComputationalResolutionError("host cost metric names must be unique")
        object.__setattr__(self, "costs", tuple(sorted(metrics, key=lambda item: item.name)))
        for name in ("virtual_capacity", "max_energy", "max_bytes", "max_virtual_ticks"):
            value = getattr(self, name)
            if type(value) is not int or value < 1:
                raise ComputationalResolutionError(f"{name} must be a positive strict integer")

    @classmethod
    def from_runtime(
        cls,
        host_id: str,
        runtime: VirtualLayerRuntime,
        authority_pid: int,
        operator_id: str,
        computational_ground_fingerprints: Sequence[str],
        costs: Sequence[RouteMetric],
        *,
        program_fingerprints: Sequence[str] = (),
        supports_ground_program_compilation: bool = False,
        version: int = 1,
        supports_structural_memory: bool = False,
        implementation_fingerprint: str | None = None,
    ) -> "ComputationalHostLocus":
        """Mathematics: Create an advertisement from a trusted local runtime and its declarative operator contract."""
        if not isinstance(runtime, VirtualLayerRuntime):
            raise ComputationalResolutionError("host-locus registration requires a VirtualLayerRuntime")
        try:
            spec = runtime.registry.contract(operator_id, version)
        except VirtualLayerError as exc:
            raise ComputationalResolutionError(str(exc)) from exc
        return cls(
            host_id=host_id,
            node_id=runtime.node_id,
            authority_pid=authority_pid,
            operator_spec=spec,
            substrates=tuple(runtime.substrates & set(spec.substrates)),
            computational_ground_fingerprints=tuple(computational_ground_fingerprints),
            program_fingerprints=tuple(program_fingerprints),
            supports_ground_program_compilation=supports_ground_program_compilation,
            supports_structural_memory=supports_structural_memory,
            implementation_fingerprint=implementation_fingerprint,
            costs=tuple(costs),
            virtual_capacity=runtime.virtual_capacity,
            max_energy=runtime.max_energy,
            max_bytes=runtime.max_bytes,
            max_virtual_ticks=runtime.max_virtual_ticks,
        )

    @property
    def resource(self) -> str:
        """Mathematics: Return the capability-safe resource path for this operator version."""
        return virtual_layer_operator_resource(self.operator_spec.operator_id, self.operator_spec.version)

    @property
    def locus_digest(self) -> str:
        """Mathematics: Return a stable digest of this logical host/operator advertisement."""
        return canonical_value_digest(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        """Mathematics: Serialize portable locus metadata; the local authority PID is never exported."""
        return {
            "host_id": self.host_id,
            "node_id": self.node_id,
            "operator_spec": self.operator_spec.to_dict(),
            "substrates": list(self.substrates),
            "computational_ground_fingerprints": list(self.computational_ground_fingerprints),
            "program_fingerprints": list(self.program_fingerprints),
            "supports_ground_program_compilation": self.supports_ground_program_compilation,
            "supports_structural_memory": self.supports_structural_memory,
            "implementation_fingerprint": self.implementation_fingerprint,
            "costs": [item.to_dict() for item in self.costs],
            "virtual_capacity": self.virtual_capacity,
            "max_energy": self.max_energy,
            "max_bytes": self.max_bytes,
            "max_virtual_ticks": self.max_virtual_ticks,
        }


class ComputationalHostCatalogue:
    """Mathematics: Bounded local catalogue of independently addressable logical host loci."""

    def __init__(self, loci: Sequence[ComputationalHostLocus] = (), *, max_loci: int = _MAX_LOCI) -> None:
        if type(max_loci) is not int or max_loci < 1 or max_loci > _MAX_LOCI:
            raise ComputationalResolutionError(f"max_loci must be in [1, {_MAX_LOCI}]")
        self.max_loci = max_loci
        self._loci: dict[tuple[str, str, int], ComputationalHostLocus] = {}
        for locus in loci:
            self.register(locus)

    @property
    def loci(self) -> tuple[ComputationalHostLocus, ...]:
        """Mathematics: Return the local locus catalogue in stable identity order."""
        return tuple(self._loci[key] for key in sorted(self._loci))

    def register(self, locus: ComputationalHostLocus) -> str:
        """Mathematics: Register one immutable logical host/operator advertisement."""
        if not isinstance(locus, ComputationalHostLocus):
            raise ComputationalResolutionError("catalogue accepts only ComputationalHostLocus values")
        key = (locus.host_id, locus.operator_spec.operator_id, locus.operator_spec.version)
        if key in self._loci:
            if self._loci[key] == locus:
                return locus.locus_digest
            raise ComputationalResolutionError("logical host/operator locus is already registered differently")
        if len(self._loci) >= self.max_loci:
            raise ComputationalResolutionError("computational host catalogue exceeds its locus ceiling")
        self._loci[key] = locus
        return locus.locus_digest

    def remove(self, host_id: str, operator_id: str, version: int = 1) -> bool:
        """Mathematics: Remove one exact logical host/operator locus, returning whether it existed."""
        return self._loci.pop((host_id, operator_id, version), None) is not None

    def to_dict(self) -> dict[str, Any]:
        """Mathematics: Serialize the declarative catalogue while omitting local authority PIDs."""
        return {
            "schema": "mailcpu.computational-host-catalogue.v1",
            "max_loci": self.max_loci,
            "loci": [item.to_dict() for item in self.loci],
        }

    @property
    def digest(self) -> str:
        """Mathematics: Return a stable digest of the ordered declarative host catalogue."""
        return canonical_value_digest(self.to_dict())


@dataclass(frozen=True)
class ComputationalResolutionBlocker:
    """Mathematics: One candidate exclusion with a stable code and logical host identity."""

    host_id: str
    code: ComputationalBlockerCode
    detail: str = ""

    def __post_init__(self) -> None:
        _label(self.host_id, "blocker host_id", 128)
        if not isinstance(self.code, ComputationalBlockerCode):
            object.__setattr__(self, "code", ComputationalBlockerCode(self.code))
        if not isinstance(self.detail, str):
            raise ComputationalResolutionError("blocker detail must be text")

    def to_dict(self) -> dict[str, Any]:
        """Mathematics: Serialize one deterministic candidate blocker."""
        return {"host_id": self.host_id, "code": self.code.value, "detail": self.detail}


@dataclass(frozen=True)
class ComputationalRouteWitness:
    """Mathematics: Non-authoritative single-locus route proposal bound to exact address and live capability evidence."""

    address_digest: str
    catalogue_digest: str
    host_id: str
    node_id: str
    authority_digest: str
    system_ground_digest: str
    operator_id: str
    operator_version: int
    operator_contract_digest: str
    computational_ground_fingerprint: str
    program_fingerprint: str | None
    implementation_fingerprint: str | None
    resource: str
    substrate: str
    input_digest: str
    state_digest: str
    logical_time: int
    observation_kind: str
    state_sources: tuple[str, ...]
    estimated_input_bytes: int
    estimated_energy: int
    estimated_virtual_ticks: int
    costs: tuple[RouteMetric, ...]

    def __post_init__(self) -> None:
        """Mathematics: Validate every identity and accounting field carried by this route proof."""
        for name in (
            "address_digest", "catalogue_digest", "authority_digest",
            "system_ground_digest", "operator_contract_digest",
            "computational_ground_fingerprint", "input_digest", "state_digest",
        ):
            _digest(getattr(self, name), name)
        if self.program_fingerprint is not None:
            _digest(self.program_fingerprint, "program_fingerprint")
        if self.implementation_fingerprint is not None:
            _digest(self.implementation_fingerprint, "implementation_fingerprint")
        _label(self.host_id, "host_id", 128)
        _label(self.node_id, "node_id", 128)
        _label(self.operator_id, "operator_id", 128)
        _label(self.resource, "resource")
        _label(self.substrate, "substrate", 64)
        _label(self.observation_kind, "observation_kind", 64)
        if type(self.operator_version) is not int or self.operator_version < 1:
            raise ComputationalResolutionError("operator_version must be a positive strict integer")
        if type(self.logical_time) is not int or self.logical_time < 0:
            raise ComputationalResolutionError("logical_time must be a non-negative strict integer")
        for name in ("estimated_input_bytes", "estimated_energy", "estimated_virtual_ticks"):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise ComputationalResolutionError(f"{name} must be a non-negative strict integer")
        sources = tuple(self.state_sources)
        if not sources or any(not isinstance(item, str) or not item for item in sources):
            raise ComputationalResolutionError("state_sources must contain non-empty coordinates")
        if len(set(sources)) != len(sources):
            raise ComputationalResolutionError("state_sources must be unique")
        object.__setattr__(self, "state_sources", sources)
        costs = tuple(self.costs)
        if not costs or any(not isinstance(item, RouteMetric) for item in costs):
            raise ComputationalResolutionError("route witness requires a non-empty typed cost vector")
        if len({item.name for item in costs}) != len(costs):
            raise ComputationalResolutionError("route witness cost metric names must be unique")
        object.__setattr__(self, "costs", tuple(sorted(costs, key=lambda item: item.name)))

    @property
    def authoritative(self) -> bool:
        """Mathematics: Route discovery is non-authoritative by construction."""
        return False

    @property
    def digest(self) -> str:
        """Mathematics: Return the stable identity of this route witness."""
        return canonical_value_digest(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        """Mathematics: Serialize all route, Ground, state, authority, cost, and implementation identities."""
        return {
            "schema": "mailcpu.computational-route-witness.v1",
            "authoritative": False,
            "address_digest": self.address_digest,
            "catalogue_digest": self.catalogue_digest,
            "host_id": self.host_id,
            "node_id": self.node_id,
            "authority_digest": self.authority_digest,
            "system_ground_digest": self.system_ground_digest,
            "operator_id": self.operator_id,
            "operator_version": self.operator_version,
            "operator_contract_digest": self.operator_contract_digest,
            "computational_ground_fingerprint": self.computational_ground_fingerprint,
            "program_fingerprint": self.program_fingerprint,
            "implementation_fingerprint": self.implementation_fingerprint,
            "resource": self.resource,
            "substrate": self.substrate,
            "input_digest": self.input_digest,
            "state_digest": self.state_digest,
            "logical_time": self.logical_time,
            "observation_kind": self.observation_kind,
            "state_sources": list(self.state_sources),
            "estimated_input_bytes": self.estimated_input_bytes,
            "estimated_energy": self.estimated_energy,
            "estimated_virtual_ticks": self.estimated_virtual_ticks,
            "costs": [item.to_dict() for item in self.costs],
        }


@dataclass(frozen=True)
class ComputationalResolutionResult:
    """Mathematics: Non-authoritative resolution result; execution and hypervisor admission remain separate."""

    status: ComputationalResolutionStatus
    address_digest: str
    catalogue_digest: str
    candidate_count: int
    witness: ComputationalRouteWitness | None = None
    blockers: tuple[ComputationalResolutionBlocker, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.status, ComputationalResolutionStatus):
            object.__setattr__(self, "status", ComputationalResolutionStatus(self.status))
        _digest(self.address_digest, "address_digest")
        _digest(self.catalogue_digest, "catalogue_digest")
        if type(self.candidate_count) is not int or self.candidate_count < 0:
            raise ComputationalResolutionError("candidate_count must be a non-negative strict integer")
        if self.witness is not None and not isinstance(self.witness, ComputationalRouteWitness):
            raise ComputationalResolutionError("witness must be a ComputationalRouteWitness or None")
        if self.status is ComputationalResolutionStatus.FOUND:
            if self.candidate_count < 1:
                raise ComputationalResolutionError("FOUND result requires at least one candidate")
            if self.witness.address_digest != self.address_digest or self.witness.catalogue_digest != self.catalogue_digest:
                raise ComputationalResolutionError("route witness belongs to a different address or catalogue")
        blockers = tuple(self.blockers)
        if any(not isinstance(item, ComputationalResolutionBlocker) for item in blockers):
            raise ComputationalResolutionError("blockers must contain ComputationalResolutionBlocker values")
        object.__setattr__(
            self,
            "blockers",
            tuple(sorted(set(blockers), key=lambda item: (item.host_id, item.code.value, item.detail))),
        )
        if self.status is ComputationalResolutionStatus.FOUND and self.witness is None:
            raise ComputationalResolutionError("FOUND result requires a route witness")
        if self.status is not ComputationalResolutionStatus.FOUND and self.witness is not None:
            raise ComputationalResolutionError("non-FOUND result cannot contain a route witness")

    @property
    def authoritative(self) -> bool:
        """Mathematics: A route proposal never authorizes or executes an operation."""
        return False

    @property
    def digest(self) -> str:
        """Mathematics: Return the stable identity of this complete resolution result."""
        return canonical_value_digest(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        """Mathematics: Serialize the outcome, selected witness, and deterministic blockers."""
        return {
            "schema": "mailcpu.computational-resolution-result.v1",
            "authoritative": False,
            "status": self.status.value,
            "address_digest": self.address_digest,
            "catalogue_digest": self.catalogue_digest,
            "candidate_count": self.candidate_count,
            "witness": None if self.witness is None else self.witness.to_dict(),
            "blockers": [item.to_dict() for item in self.blockers],
        }


class ComputationalAddressResolver:
    """Mathematics: Resolve a semantic address to the lowest-cost eligible local logical host."""

    def resolve(
        self,
        address: ComputationalAddress,
        catalogue: ComputationalHostCatalogue,
        operating_system: HeadlessOS,
    ) -> ComputationalResolutionResult:
        """Mathematics: Resolve an address against trusted local advertisements and live receiver capabilities."""
        if not isinstance(address, ComputationalAddress):
            raise ComputationalResolutionError("resolve requires a ComputationalAddress")
        if not isinstance(catalogue, ComputationalHostCatalogue):
            raise ComputationalResolutionError("resolve requires a ComputationalHostCatalogue")
        if not isinstance(operating_system, HeadlessOS):
            raise ComputationalResolutionError("local computational resolution requires a HeadlessOS")
        address_digest = address.digest
        catalogue_digest = catalogue.digest
        workload = address.workload
        reference = workload.operator_ref(address.operator_id)

        try:
            admission = operating_system.seed_admission.current(workload.system.system_id)
        except Exception as exc:
            raise ComputationalResolutionError(f"cannot inspect local System Ground admission: {exc}") from exc
        if admission is None:
            return ComputationalResolutionResult(
                ComputationalResolutionStatus.BLOCKED,
                address_digest,
                catalogue_digest,
                0,
                blockers=(ComputationalResolutionBlocker(
                    "system-ground",
                    ComputationalBlockerCode.GROUND_MISMATCH,
                    "requested System Ground is not admitted on this receiver",
                ),),
            )
        from .virtual_layer import VirtualGroundRef
        if admission.identity != workload.system or VirtualGroundRef.from_envelope(admission) != workload.ground:
            return ComputationalResolutionResult(
                ComputationalResolutionStatus.BLOCKED,
                address_digest,
                catalogue_digest,
                0,
                blockers=(ComputationalResolutionBlocker(
                    "system-ground",
                    ComputationalBlockerCode.GROUND_MISMATCH,
                    "requested System Ground or causal frontier is stale or mismatched",
                ),),
            )
        system_ground_digest = canonical_value_digest(workload.ground.to_dict())

        candidates = tuple(
            locus for locus in catalogue.loci
            if locus.operator_spec.operator_id == address.operator_id
            and locus.operator_spec.version == reference.version
        )
        if not candidates:
            return ComputationalResolutionResult(
                ComputationalResolutionStatus.UNREACHABLE,
                address_digest,
                catalogue_digest,
                0,
            )

        blockers: list[ComputationalResolutionBlocker] = []
        selected: list[tuple[tuple[int, ...], str, str, ComputationalRouteWitness]] = []
        hit_resource_limit = False
        input_value = _plain(workload.input_value)
        input_bytes = len(_canonical_bytes(input_value)) + sum(
            len(_canonical_bytes(item.to_dict())) for item in reference.structural_memory
        )
        ceilings = {item.name: item.amount for item in address.resource_ceilings}
        metric_units = {item.name: item.unit for item in address.metric_order}
        resource = virtual_layer_operator_resource(address.operator_id, reference.version)

        for locus in candidates:
            spec = locus.operator_spec
            reason: tuple[ComputationalBlockerCode, str] | None = None
            if spec.digest != address.operator_contract_digest:
                reason = (ComputationalBlockerCode.CONTRACT_MISMATCH, "operator contract digest differs")
            elif not spec.replay_safe:
                reason = (ComputationalBlockerCode.CONTRACT_MISMATCH, "only deterministic pure operators can be resolved")
            elif address.computational_ground_fingerprint not in locus.computational_ground_fingerprints:
                reason = (ComputationalBlockerCode.GROUND_MISMATCH, "computational Ground is not supported by this host")
            elif (
                address.program_fingerprint is None
                and not locus.supports_ground_program_compilation
            ):
                reason = (ComputationalBlockerCode.PROGRAM_MISMATCH, "address has no exact program pin and host does not advertise Ground-bounded compilation")
            elif (
                address.program_fingerprint is not None
                and address.program_fingerprint not in locus.program_fingerprints
            ):
                reason = (ComputationalBlockerCode.PROGRAM_MISMATCH, "exact program fingerprint is not registered by this host")
            elif reference.target_node is not None and reference.target_node != locus.node_id:
                reason = (ComputationalBlockerCode.PLACEMENT_MISMATCH, "operator reference targets a different node")
            elif workload.eligible_nodes and locus.node_id not in workload.eligible_nodes:
                reason = (ComputationalBlockerCode.PLACEMENT_MISMATCH, "host node is outside the eligible node set")
            elif (
                (reference.preferred_substrate is not None and reference.preferred_substrate not in locus.substrates)
                or not (set(locus.substrates) & set(spec.substrates))
            ):
                reason = (ComputationalBlockerCode.SUBSTRATE_MISMATCH, "host has no eligible operator substrate")
            elif address.observation_kind != spec.output_kind:
                reason = (ComputationalBlockerCode.OBSERVATION_MISMATCH, "requested observation kind differs from operator output")
            elif not _value_matches(input_value, spec.input_kind):
                reason = (ComputationalBlockerCode.INPUT_MISMATCH, "input value differs from operator input kind")
            elif input_bytes > min(spec.max_input_bytes, workload.budget.max_bytes, locus.max_bytes):
                reason = (ComputationalBlockerCode.RESOURCE_LIMIT, "input description exceeds a byte bound")
                hit_resource_limit = True

            if reason is None and reference.structural_memory:
                if not locus.supports_structural_memory:
                    reason = (ComputationalBlockerCode.STATE_UNAVAILABLE, "host does not advertise Structural Memory input resolution")
                else:
                    try:
                        process = operating_system.environment.kernel._process(locus.authority_pid)
                    except Exception:
                        process = None
                    if process is None or process.status is ProcessStatus.EXITED:
                        reason = (ComputationalBlockerCode.HOST_UNAVAILABLE, "local authority process is unavailable")
                    elif not any(
                        capability.allows("/structural-memory/read", "read")
                        for capability in process.capabilities
                    ):
                        reason = (ComputationalBlockerCode.AUTHORITY_MISSING, "Structural Memory read capability is absent")
                    else:
                        for memory_ref in reference.structural_memory:
                            try:
                                receipt = operating_system.structural_memory.read_revision(
                                    memory_ref.memory_id,
                                    memory_ref.revision,
                                    memory_ref.coordinate,
                                    context=dict(memory_ref.context),
                                )
                            except StructuralMemoryError:
                                reason = (ComputationalBlockerCode.STATE_UNAVAILABLE, "a pinned Structural Memory coordinate is unavailable")
                                break
                            if (
                                not isinstance(receipt, StructuralMemoryReadReceipt)
                                or receipt.memory_id != memory_ref.memory_id
                                or receipt.revision != memory_ref.revision
                                or receipt.coordinate != memory_ref.coordinate
                                or receipt.spec_digest != memory_ref.spec_digest
                                or receipt.certificate_digest != memory_ref.certificate_digest
                                or receipt.context_digest != canonical_value_digest(_plain(memory_ref.context))
                            ):
                                reason = (ComputationalBlockerCode.STATE_UNAVAILABLE, "Structural Memory receipt does not match its pinned address")
                                break

            if reason is None:
                try:
                    process = operating_system.environment.kernel._process(locus.authority_pid)
                except Exception:
                    process = None
                if process is None or process.status is ProcessStatus.EXITED:
                    reason = (ComputationalBlockerCode.HOST_UNAVAILABLE, "local host authority process is unavailable")

            authority_digest = ""
            if reason is None:
                local_capabilities = tuple(
                    sorted(
                        (
                            capability.resource,
                            tuple(sorted(capability.rights)),
                        )
                        for capability in process.capabilities
                    )
                )
                authority_digest = canonical_value_digest({
                    "pid": locus.authority_pid,
                    "capabilities": [
                        {"resource": path, "rights": list(rights)}
                        for path, rights in local_capabilities
                    ],
                })
                if not all(
                    any(
                        capability.allows(resource, right)
                        for capability in process.capabilities
                    )
                    for right in spec.required_rights
                ):
                    reason = (ComputationalBlockerCode.AUTHORITY_MISSING, "operator capability is not present on the selected local host")
            if reason is None:
                energy = spec.estimated_energy(input_bytes)
                ticks = max(1, math.ceil(energy / locus.virtual_capacity))
                if (
                    energy > min(workload.budget.max_energy, locus.max_energy)
                    or ticks > min(workload.budget.max_virtual_ticks, locus.max_virtual_ticks)
                ):
                    reason = (ComputationalBlockerCode.RESOURCE_LIMIT, "operator energy or virtual-tick budget is exceeded")
                    hit_resource_limit = True

            cost_by_name = {item.name: item for item in locus.costs}
            if reason is None and (
                set(cost_by_name) != set(metric_units)
                or any(cost_by_name[name].unit != metric_units[name] for name in metric_units)
            ):
                reason = (ComputationalBlockerCode.METRIC_MISMATCH, "host cost dimensions differ from the request objective")
            if reason is None:
                exceeded = [
                    name for name, maximum in ceilings.items()
                    if cost_by_name[name].amount > maximum
                ]
                if exceeded:
                    reason = (ComputationalBlockerCode.RESOURCE_LIMIT, "host route cost exceeds " + ", ".join(sorted(exceeded)))
                    hit_resource_limit = True

            if reason is not None:
                blockers.append(ComputationalResolutionBlocker(locus.host_id, reason[0], reason[1]))
                continue

            substrate = (
                reference.preferred_substrate
                if reference.preferred_substrate is not None
                else sorted(set(locus.substrates) & set(spec.substrates))[0]
            )
            state_sources = tuple(
                f"structural-memory:{item.memory_id}@{item.revision}:{item.coordinate}"
                for item in reference.structural_memory
            ) or ("inline-input",)
            witness = ComputationalRouteWitness(
                address_digest=address_digest,
                catalogue_digest=catalogue_digest,
                host_id=locus.host_id,
                node_id=locus.node_id,
                authority_digest=authority_digest,
                system_ground_digest=system_ground_digest,
                operator_id=address.operator_id,
                operator_version=reference.version,
                operator_contract_digest=spec.digest,
                computational_ground_fingerprint=address.computational_ground_fingerprint,
                program_fingerprint=address.program_fingerprint,
                implementation_fingerprint=locus.implementation_fingerprint,
                resource=resource,
                substrate=substrate,
                input_digest=address.input_digest,
                state_digest=address.state_digest,
                logical_time=workload.logical_time,
                observation_kind=address.observation_kind,
                state_sources=state_sources,
                estimated_input_bytes=input_bytes,
                estimated_energy=energy,
                estimated_virtual_ticks=ticks,
                costs=tuple(cost_by_name[name] for name in metric_units),
            )
            cost_key = tuple(cost_by_name[item.name].amount for item in address.metric_order)
            selected.append((cost_key, locus.host_id, locus.node_id, witness))

        if selected:
            selected.sort(key=lambda item: (item[0], item[1], item[2]))
            return ComputationalResolutionResult(
                ComputationalResolutionStatus.FOUND,
                address_digest,
                catalogue_digest,
                len(candidates),
                selected[0][3],
                tuple(blockers),
            )
        status = (
            ComputationalResolutionStatus.BUDGET_EXHAUSTED
            if hit_resource_limit
            else ComputationalResolutionStatus.BLOCKED
        )
        return ComputationalResolutionResult(
            status,
            address_digest,
            catalogue_digest,
            len(candidates),
            blockers=tuple(blockers),
        )
