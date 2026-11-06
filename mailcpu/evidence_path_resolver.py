"""Evidence-indexed routing between verified semantic representations.

This module composes existing non-executable TranslationContract edges into
bounded multi-criteria routes. It does not execute a route or issue authority.
Every edge is tied to one exact comparison case; optional Transit evidence
can additionally bind an edge to a receiver-committed operation and oracle.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import heapq
import json
import re
import threading
from typing import Any, Mapping, Sequence

from .headless import HeadlessOS
from .kernel import ProcessStatus
from .semantic_translation import (
    CapabilityRequirement,
    ObservationComparison,
    RepresentationRef,
    ResourceBound,
    SemanticTranslationError,
    TransitOracleEvidence,
    TransitTranslationEvidence,
    TranslationContract,
    canonical_value_digest,
)


_EVIDENCE_PATH_SCHEMA = "mailcpu.evidence-path-catalogue.v1"
_EVIDENCE_PATH_RESULT_SCHEMA = "mailcpu.evidence-path-result.v1"
_IDENTIFIER = re.compile(r"[A-Za-z][A-Za-z0-9_.:-]{0,63}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_MAX_CATALOGUE_EDGES = 10_000
_MAX_ROUTE_EFFECT_BYTES = 131_072


class EvidencePathError(ValueError):
    """A route, evidence edge, catalogue, or bounded resolution request is invalid."""


class EvidenceStrength(str, Enum):
    """Minimum evidence tier required for a route edge."""

    PAIRED_CASE = "paired_case"
    INDEPENDENT_ORACLE = "independent_oracle"


class EvidencePathStatus(str, Enum):
    """Non-authoritative outcome of one evidence-indexed path search."""

    FOUND = "found"
    ALREADY_AT_TARGET = "already_at_target"
    UNREACHABLE = "unreachable"
    BLOCKED = "blocked"
    BUDGET_EXHAUSTED = "budget_exhausted"


class EvidencePathBlockerCode(str, Enum):
    """Reason one edge or candidate continuation was excluded."""

    CONTEXT_MISMATCH = "context_mismatch"
    PRECONDITION_MISSING = "precondition_missing"
    INVARIANT_MISSING = "invariant_missing"
    AUTHORITY_MISSING = "authority_missing"
    EVIDENCE_INSUFFICIENT = "evidence_insufficient"
    METRIC_MISMATCH = "metric_mismatch"
    RESOURCE_LIMIT = "resource_limit"
    HOP_LIMIT = "hop_limit"


def _identifier(value: Any, label: str) -> str:
    """Mathematics: require value∈[A-Za-z][A-Za-z0-9_.:-]^{0,63}."""
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise EvidencePathError(f"{label} must be a safe 1-64 character identifier")
    return value


def _digest(value: Any, label: str) -> str:
    """Mathematics: require value∈{0,…,9,a,…,f}^{64}."""
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise EvidencePathError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _plain(value: Any) -> Any:
    """Mathematics: recursively project frozen mappings and tuples into detached JSON values."""
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(item) for item in value]
    return value


def _canonical_bytes(value: Any) -> bytes:
    """Mathematics: define the unique sorted compact UTF-8 encoding of a JSON value."""
    try:
        return json.dumps(
            _plain(value),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise EvidencePathError(f"value is outside canonical JSON: {exc}") from exc


def _freeze(value: Any) -> Any:
    """Mathematics: recursively detach JSON maps and sequences into immutable containers."""
    if isinstance(value, Mapping):
        return _FrozenDict({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (tuple, list)):
        return tuple(_freeze(item) for item in value)
    return value


class _FrozenDict(dict):
    """JSON-compatible dictionary that rejects mutation after construction."""

    def _immutable(self, *args: Any, **kwargs: Any) -> None:
        """Mathematics: map every mutation attempt to a TypeError."""
        raise TypeError("evidence-path values are immutable")

    __setitem__ = _immutable
    __delitem__ = _immutable
    clear = _immutable
    pop = _immutable
    popitem = _immutable
    setdefault = _immutable
    update = _immutable
    __ior__ = _immutable


@dataclass(frozen=True, order=True)
class RouteMetricKey:
    """A named, unit-bearing dimension used to compare route costs."""

    name: str
    unit: str

    def __post_init__(self) -> None:
        """Mathematics: require stable metric and unit identifiers before addition or comparison."""
        _identifier(self.name, "route metric name")
        _identifier(self.unit, "route metric unit")

    def to_dict(self) -> dict[str, str]:
        """Mathematics: serialize the ordered pair (metric name, unit)."""
        return {"name": self.name, "unit": self.unit}

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "RouteMetricKey":
        """Mathematics: reconstruct a route metric key from its exact two-field schema."""
        if not isinstance(payload, Mapping) or set(payload) != {"name", "unit"}:
            raise EvidencePathError("route metric key fields are invalid")
        return cls(payload["name"], payload["unit"])


@dataclass(frozen=True, order=True)
class RouteMetric:
    """A non-negative integer amount in one explicitly named metric unit."""

    name: str
    unit: str
    amount: int

    def __post_init__(self) -> None:
        """Mathematics: require name/unit identity and amount∈ℤ with amount≥0, excluding Booleans."""
        _identifier(self.name, "route metric name")
        _identifier(self.unit, "route metric unit")
        if type(self.amount) is not int or self.amount < 0:
            raise EvidencePathError("route metric amount must be a non-negative strict integer")

    @property
    def key(self) -> RouteMetricKey:
        """Mathematics: project (name,unit,amount) to the dimension key (name,unit)."""
        return RouteMetricKey(self.name, self.unit)

    def to_dict(self) -> dict[str, Any]:
        """Mathematics: serialize the metric as its identity and non-negative amount."""
        return {"name": self.name, "unit": self.unit, "amount": self.amount}

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "RouteMetric":
        """Mathematics: reconstruct a route metric from its exact three-field schema."""
        if not isinstance(payload, Mapping) or set(payload) != {"name", "unit", "amount"}:
            raise EvidencePathError("route metric fields are invalid")
        return cls(payload["name"], payload["unit"], payload["amount"])


@dataclass(frozen=True)
class EvidencePathEdge:
    """One directed representation translation with exact-case evidence and declared cost."""

    contract: TranslationContract
    comparison: ObservationComparison
    costs: tuple[RouteMetric, ...]
    oracle_evidence: TransitOracleEvidence | None = None
    transit_evidence: TransitTranslationEvidence | None = None
    observed_effect: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        """Mathematics: admit an edge only when π(source)=π(target), all evidence identities align, and declared costs respect any matching contract bounds."""
        if not isinstance(self.contract, TranslationContract):
            raise EvidencePathError("edge contract must be a TranslationContract")
        if not isinstance(self.comparison, ObservationComparison):
            raise EvidencePathError("edge comparison must be an ObservationComparison")
        if (
            self.comparison.contract_digest != self.contract.digest
            or self.comparison.projection_digest != self.contract.observation.projection_digest
            or not self.comparison.equivalent
        ):
            raise EvidencePathError("edge comparison is not a successful check of its exact contract and projection")

        metrics = tuple(self.costs)
        if not metrics or any(not isinstance(item, RouteMetric) for item in metrics):
            raise EvidencePathError("every route edge requires a non-empty typed cost vector")
        if len({item.name for item in metrics}) != len(metrics):
            raise EvidencePathError("route edge cost metric names must be unique")
        metrics = tuple(sorted(metrics, key=lambda item: item.name))
        object.__setattr__(self, "costs", metrics)

        bounds = {item.name: item for item in self.contract.resource_bounds}
        for metric in metrics:
            bound = bounds.get(metric.name)
            if bound is not None:
                if bound.unit != metric.unit:
                    raise EvidencePathError(
                        f"route metric {metric.name!r} unit differs from its translation resource bound"
                    )
                if metric.amount > bound.maximum:
                    raise EvidencePathError(
                        f"route metric {metric.name!r} exceeds its translation resource bound"
                    )

        if self.oracle_evidence is not None:
            if not isinstance(self.oracle_evidence, TransitOracleEvidence):
                raise EvidencePathError("oracle_evidence must be TransitOracleEvidence or None")
            if not self.oracle_evidence.equivalent:
                raise EvidencePathError("route oracle evidence must have an equivalent observation")
            if self.contract.source.content_digest != self.oracle_evidence.request_fingerprint:
                raise EvidencePathError("oracle request fingerprint does not match the edge source representation")
            if self.transit_evidence is None:
                raise EvidencePathError("independent Transit oracle evidence must remain bound to its translation evidence")

        if self.transit_evidence is not None:
            if not isinstance(self.transit_evidence, TransitTranslationEvidence):
                raise EvidencePathError("transit_evidence must be TransitTranslationEvidence or None")
            if (
                self.transit_evidence.contract != self.contract
                or self.transit_evidence.comparison != self.comparison
                or self.oracle_evidence is None
                or self.transit_evidence.request_fingerprint != self.oracle_evidence.request_fingerprint
            ):
                raise EvidencePathError("Transit evidence, oracle, contract, and comparison do not share one identity")
            if not isinstance(self.observed_effect, Mapping):
                raise EvidencePathError("Transit-backed edges require the committed raw observed effect")
            effect = json.loads(_canonical_bytes(self.observed_effect).decode("utf-8"))
            encoded_effect = _canonical_bytes(effect)
            if len(encoded_effect) > _MAX_ROUTE_EFFECT_BYTES:
                raise EvidencePathError("observed Transit effect exceeds the route evidence byte limit")
            if canonical_value_digest(effect) != self.transit_evidence.effect_digest:
                raise EvidencePathError("observed effect digest does not match Transit translation evidence")
            try:
                self.oracle_evidence.validate_against_effect(
                    effect,
                    request_fingerprint=self.transit_evidence.request_fingerprint,
                )
            except SemanticTranslationError as exc:
                raise EvidencePathError(f"Transit oracle evidence does not match its effect: {exc}") from exc
            object.__setattr__(self, "observed_effect", _freeze(effect))
        elif self.observed_effect is not None:
            raise EvidencePathError("observed_effect is reserved for receiver-committed Transit edges")

    @classmethod
    def from_execution_result(
        cls,
        result: Any,
        costs: Sequence[RouteMetric],
    ) -> "EvidencePathEdge":
        """Create an edge from a receiver-committed result after strict translation and oracle validation. Mathematics: admit e only when the outer execution, translation, oracle, and raw effect bindings agree."""
        from .classifier import HypervisorExecutionResult

        if not isinstance(result, HypervisorExecutionResult) or not isinstance(result.effect, Mapping):
            raise EvidencePathError("route ingestion requires an object-valued HypervisorExecutionResult")
        raw_translation = result.effect.get("_semantic_translation")
        raw_oracle = result.effect.get("_semantic_oracle")
        if not isinstance(raw_translation, Mapping) or not isinstance(raw_oracle, Mapping):
            raise EvidencePathError("receiver result is missing translation or independent oracle evidence")
        try:
            translation = TransitTranslationEvidence.from_dict(raw_translation)
            translation.validate_execution_result(result, require_oracle=True)
            oracle = TransitOracleEvidence.from_dict(raw_oracle)
        except SemanticTranslationError as exc:
            raise EvidencePathError(f"receiver execution evidence is invalid: {exc}") from exc
        raw_effect = {
            key: value for key, value in result.effect.items()
            if key not in {"_semantic_translation", "_semantic_oracle"}
        }
        return cls(
            contract=translation.contract,
            comparison=translation.comparison,
            costs=tuple(costs),
            oracle_evidence=oracle,
            transit_evidence=translation,
            observed_effect=raw_effect,
        )

    @property
    def source(self) -> RepresentationRef:
        """Mathematics: define the directed graph source node as contract.source."""
        return self.contract.source

    @property
    def target(self) -> RepresentationRef:
        """Mathematics: define the directed graph target node as contract.target."""
        return self.contract.target

    @property
    def evidence_strength(self) -> EvidenceStrength:
        """Mathematics: strength(e)=INDEPENDENT_ORACLE iff oracle_evidence(e) exists, else PAIRED_CASE."""
        return (
            EvidenceStrength.INDEPENDENT_ORACLE
            if self.oracle_evidence is not None
            else EvidenceStrength.PAIRED_CASE
        )

    @property
    def edge_id(self) -> str:
        """Mathematics: identify the full directed edge and evidence by H(canonical_json(edge))."""
        return canonical_value_digest(self.to_dict())

    @property
    def digest(self) -> str:
        """Mathematics: return H(canonical_json(edge.to_dict()))."""
        return self.edge_id

    def to_dict(self) -> dict[str, Any]:
        """Mathematics: serialize the exact contract, paired evidence, additive cost vector, and optional receiver oracle record."""
        return {
            "schema": "mailcpu.evidence-path-edge.v1",
            "contract": self.contract.to_dict(),
            "comparison": self.comparison.to_dict(),
            "costs": [item.to_dict() for item in self.costs],
            "oracle_evidence": None if self.oracle_evidence is None else self.oracle_evidence.to_dict(),
            "transit_evidence": None if self.transit_evidence is None else self.transit_evidence.to_dict(),
            "observed_effect": None if self.observed_effect is None else _plain(self.observed_effect),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "EvidencePathEdge":
        """Mathematics: reconstruct an edge only when its contract, observation, oracle, effect, and costs satisfy the same edge invariants."""
        expected = {
            "schema", "contract", "comparison", "costs",
            "oracle_evidence", "transit_evidence", "observed_effect",
        }
        if (
            not isinstance(payload, Mapping)
            or set(payload) != expected
            or payload["schema"] != "mailcpu.evidence-path-edge.v1"
        ):
            raise EvidencePathError("evidence path edge schema or fields are invalid")
        if not isinstance(payload["contract"], Mapping) or not isinstance(payload["comparison"], Mapping):
            raise EvidencePathError("edge contract and comparison must be objects")
        if not isinstance(payload["costs"], (tuple, list)):
            raise EvidencePathError("edge costs must be an array")
        for name in ("oracle_evidence", "transit_evidence"):
            if payload[name] is not None and not isinstance(payload[name], Mapping):
                raise EvidencePathError(f"edge {name} must be an object or null")
        return cls(
            contract=TranslationContract.from_dict(payload["contract"]),
            comparison=ObservationComparison.from_dict(payload["comparison"]),
            costs=tuple(RouteMetric.from_dict(item) for item in payload["costs"]),
            oracle_evidence=(
                None if payload["oracle_evidence"] is None
                else TransitOracleEvidence.from_dict(payload["oracle_evidence"])
            ),
            transit_evidence=(
                None if payload["transit_evidence"] is None
                else TransitTranslationEvidence.from_dict(payload["transit_evidence"])
            ),
            observed_effect=payload["observed_effect"],
        )


class EvidencePathCatalogue:
    """Bounded local index of evidence-backed representation translations."""

    def __init__(self, *, max_edges: int = _MAX_CATALOGUE_EDGES) -> None:
        """Mathematics: initialize a finite edge map with cardinality bounded by max_edges."""
        if type(max_edges) is not int or not 1 <= max_edges <= _MAX_CATALOGUE_EDGES:
            raise EvidencePathError(f"max_edges must be between 1 and {_MAX_CATALOGUE_EDGES}")
        self.max_edges = max_edges
        self._edges: dict[str, EvidencePathEdge] = {}
        self._lock = threading.RLock()

    @property
    def edges(self) -> tuple[EvidencePathEdge, ...]:
        """Mathematics: return the finite projection of the edge map sorted by content-addressed edge identity."""
        with self._lock:
            return tuple(self._edges[key] for key in sorted(self._edges))

    @property
    def digest(self) -> str:
        """Mathematics: identify catalogue contents and its edge ceiling by canonical SHA-256."""
        return canonical_value_digest(self.to_dict())

    def register(self, edge: EvidencePathEdge) -> str:
        """Mathematics: insert e under H(e), preserving unique keys and |catalogue|≤max_edges."""
        if not isinstance(edge, EvidencePathEdge):
            raise EvidencePathError("catalogue accepts only EvidencePathEdge values")
        edge_id = edge.edge_id
        with self._lock:
            existing = self._edges.get(edge_id)
            if existing is not None:
                if existing != edge:
                    raise EvidencePathError("route edge digest collision")
                return edge_id
            if len(self._edges) >= self.max_edges:
                raise EvidencePathError("evidence path catalogue edge limit reached")
            self._edges[edge_id] = edge
        return edge_id

    def register_execution_result(
        self,
        result: Any,
        costs: Sequence[RouteMetric],
    ) -> str:
        """Mathematics: construct e=from_execution_result(r,costs) and insert it under H(e)."""
        return self.register(EvidencePathEdge.from_execution_result(result, costs))

    def remove(self, edge_id: str) -> bool:
        """Mathematics: delete only the map entry keyed by edge_id=H(e) and report whether it existed."""
        _digest(edge_id, "edge_id")
        with self._lock:
            return self._edges.pop(edge_id, None) is not None

    def to_dict(self) -> dict[str, Any]:
        """Mathematics: serialize each registered edge exactly once in ascending digest order."""
        with self._lock:
            return {
                "schema": _EVIDENCE_PATH_SCHEMA,
                "max_edges": self.max_edges,
                "edges": [self._edges[key].to_dict() for key in sorted(self._edges)],
            }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "EvidencePathCatalogue":
        """Mathematics: invert the catalogue projection only when every reconstructed edge satisfies its invariants."""
        if (
            not isinstance(payload, Mapping)
            or set(payload) != {"schema", "max_edges", "edges"}
            or payload["schema"] != _EVIDENCE_PATH_SCHEMA
            or not isinstance(payload["edges"], (tuple, list))
        ):
            raise EvidencePathError("evidence path catalogue schema or fields are invalid")
        catalogue = cls(max_edges=payload["max_edges"])
        if len(payload["edges"]) > catalogue.max_edges:
            raise EvidencePathError("stored edge count exceeds catalogue limit")
        for raw_edge in payload["edges"]:
            if not isinstance(raw_edge, Mapping):
                raise EvidencePathError("stored catalogue edge must be an object")
            catalogue.register(EvidencePathEdge.from_dict(raw_edge))
        return catalogue


@dataclass(frozen=True)
class EvidencePathRequest:
    """Exact source-to-target route query and its accepted context, evidence, costs, and budgets."""

    source: RepresentationRef
    target: RepresentationRef
    context_digest: str
    metric_order: tuple[RouteMetricKey, ...]
    resource_ceilings: tuple[RouteMetric, ...] = ()
    satisfied_preconditions: tuple[str, ...] = ()
    satisfied_invariants: tuple[str, ...] = ()
    minimum_evidence: EvidenceStrength = EvidenceStrength.PAIRED_CASE
    max_hops: int = 64
    max_expansions: int = 10_000
    accepted_context_digests: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """Mathematics: validate exact endpoints/context, an ordered additive metric basis, digest gates, and finite search ceilings."""
        if not isinstance(self.source, RepresentationRef) or not isinstance(self.target, RepresentationRef):
            raise EvidencePathError("route source and target must be RepresentationRef values")
        _digest(self.context_digest, "route context_digest")
        accepted_contexts = tuple(self.accepted_context_digests)
        if len(accepted_contexts) > 64:
            raise EvidencePathError("accepted_context_digests exceeds the 64-context request limit")
        for value in accepted_contexts:
            _digest(value, "accepted_context_digests")
        if len(set(accepted_contexts)) != len(accepted_contexts):
            raise EvidencePathError("accepted_context_digests must be unique")
        accepted_contexts = tuple(sorted(set(accepted_contexts) | {self.context_digest}))
        object.__setattr__(self, "accepted_context_digests", accepted_contexts)
        metrics = tuple(self.metric_order)
        if not metrics or any(not isinstance(item, RouteMetricKey) for item in metrics):
            raise EvidencePathError("metric_order must be a non-empty sequence of RouteMetricKey values")
        if len({item.name for item in metrics}) != len(metrics):
            raise EvidencePathError("metric_order names must be unique")
        object.__setattr__(self, "metric_order", metrics)
        ceilings = tuple(self.resource_ceilings)
        if any(not isinstance(item, RouteMetric) for item in ceilings):
            raise EvidencePathError("resource_ceilings must contain RouteMetric values")
        if len({item.name for item in ceilings}) != len(ceilings):
            raise EvidencePathError("resource ceiling names must be unique")
        metric_by_name = {item.name: item for item in metrics}
        for ceiling in ceilings:
            key = metric_by_name.get(ceiling.name)
            if key is None or key.unit != ceiling.unit:
                raise EvidencePathError("resource ceiling is outside the requested metric basis or has a mismatched unit")
        object.__setattr__(self, "resource_ceilings", tuple(sorted(ceilings, key=lambda item: item.name)))
        for field_name in ("satisfied_preconditions", "satisfied_invariants"):
            values = tuple(getattr(self, field_name))
            for value in values:
                _digest(value, field_name)
            if len(set(values)) != len(values):
                raise EvidencePathError(f"{field_name} must be unique")
            object.__setattr__(self, field_name, tuple(sorted(values)))
        try:
            minimum = (
                self.minimum_evidence
                if isinstance(self.minimum_evidence, EvidenceStrength)
                else EvidenceStrength(self.minimum_evidence)
            )
        except (TypeError, ValueError) as exc:
            raise EvidencePathError("minimum_evidence is invalid") from exc
        object.__setattr__(self, "minimum_evidence", minimum)
        for name, value in (("max_hops", self.max_hops), ("max_expansions", self.max_expansions)):
            if type(value) is not int or value < 1:
                raise EvidencePathError(f"{name} must be a positive strict integer")

    @property
    def digest(self) -> str:
        """Mathematics: identify endpoints, exact context, evidence gates, objective order, and budgets."""
        return canonical_value_digest(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        """Mathematics: serialize the complete query tuple while omitting grants and executable content."""
        return {
            "schema": "mailcpu.evidence-path-request.v1",
            "source": self.source.to_dict(),
            "target": self.target.to_dict(),
            "context_digest": self.context_digest,
            "accepted_context_digests": list(self.accepted_context_digests),
            "metric_order": [item.to_dict() for item in self.metric_order],
            "resource_ceilings": [item.to_dict() for item in self.resource_ceilings],
            "satisfied_preconditions": list(self.satisfied_preconditions),
            "satisfied_invariants": list(self.satisfied_invariants),
            "minimum_evidence": self.minimum_evidence.value,
            "max_hops": self.max_hops,
            "max_expansions": self.max_expansions,
        }


@dataclass(frozen=True)
class EvidencePathBlocker:
    """One deterministic reason an edge or continuation was excluded."""

    edge_id: str
    code: EvidencePathBlockerCode
    metric_name: str | None = None

    def __post_init__(self) -> None:
        """Mathematics: validate an edge digest, typed blocker code, and optional metric identity."""
        _digest(self.edge_id, "blocker edge_id")
        try:
            code = self.code if isinstance(self.code, EvidencePathBlockerCode) else EvidencePathBlockerCode(self.code)
        except (TypeError, ValueError) as exc:
            raise EvidencePathError("route blocker code is invalid") from exc
        object.__setattr__(self, "code", code)
        if self.metric_name is not None:
            _identifier(self.metric_name, "blocker metric_name")

    def to_dict(self) -> dict[str, Any]:
        """Mathematics: serialize one blocker as (edge_id,code,optional_metric_name)."""
        return {"edge_id": self.edge_id, "code": self.code.value, "metric_name": self.metric_name}


@dataclass(frozen=True)
class EvidencePathResult:
    """Non-authoritative route proposal with the exact catalogue/context and selected cost vector."""

    status: EvidencePathStatus
    request_digest: str
    catalogue_digest: str
    context_digest: str
    authority_digest: str
    edge_ids: tuple[str, ...] = ()
    total_costs: tuple[RouteMetric, ...] = ()
    evidence_strength: EvidenceStrength | None = None
    expanded_labels: int = 0
    blockers: tuple[EvidencePathBlocker, ...] = ()

    def __post_init__(self) -> None:
        """Mathematics: require route endpoints to be represented by a finite result, non-authoritative status, and canonical blockers/costs."""
        try:
            status = self.status if isinstance(self.status, EvidencePathStatus) else EvidencePathStatus(self.status)
        except (TypeError, ValueError) as exc:
            raise EvidencePathError("route result status is invalid") from exc
        object.__setattr__(self, "status", status)
        for name in ("request_digest", "catalogue_digest", "context_digest", "authority_digest"):
            _digest(getattr(self, name), name)
        if type(self.expanded_labels) is not int or self.expanded_labels < 0:
            raise EvidencePathError("expanded_labels must be a non-negative strict integer")
        edge_ids = tuple(self.edge_ids)
        for edge_id in edge_ids:
            _digest(edge_id, "route edge_id")
        object.__setattr__(self, "edge_ids", edge_ids)
        costs = tuple(self.total_costs)
        if any(not isinstance(item, RouteMetric) for item in costs) or len({item.name for item in costs}) != len(costs):
            raise EvidencePathError("total_costs must contain unique typed route metrics")
        object.__setattr__(self, "total_costs", tuple(sorted(costs, key=lambda item: item.name)))
        if self.evidence_strength is not None:
            try:
                strength = (
                    self.evidence_strength
                    if isinstance(self.evidence_strength, EvidenceStrength)
                    else EvidenceStrength(self.evidence_strength)
                )
            except (TypeError, ValueError) as exc:
                raise EvidencePathError("route result evidence strength is invalid") from exc
            object.__setattr__(self, "evidence_strength", strength)
        blockers = tuple(self.blockers)
        if any(not isinstance(item, EvidencePathBlocker) for item in blockers):
            raise EvidencePathError("route blockers must be EvidencePathBlocker values")
        unique_blockers = set(blockers)
        object.__setattr__(
            self,
            "blockers",
            tuple(sorted(
                unique_blockers,
                key=lambda item: (item.edge_id, item.code.value, item.metric_name or ""),
            )),
        )
        if status is EvidencePathStatus.FOUND and (not edge_ids or self.evidence_strength is None):
            raise EvidencePathError("FOUND route must contain at least one edge and an evidence tier")
        if status is EvidencePathStatus.ALREADY_AT_TARGET and edge_ids:
            raise EvidencePathError("ALREADY_AT_TARGET cannot contain edges")
        if status not in {EvidencePathStatus.FOUND, EvidencePathStatus.ALREADY_AT_TARGET}:
            if edge_ids or costs or self.evidence_strength is not None:
                raise EvidencePathError("non-successful route results cannot contain a selected path")

    @property
    def authoritative(self) -> bool:
        """Mathematics: route search never grants authority; authoritative is identically false."""
        return False

    @property
    def digest(self) -> str:
        """Mathematics: identify the complete route proposal by canonical SHA-256."""
        return canonical_value_digest(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        """Mathematics: serialize the route proposal and retain authoritative=False."""
        return {
            "schema": _EVIDENCE_PATH_RESULT_SCHEMA,
            "authoritative": False,
            "status": self.status.value,
            "request_digest": self.request_digest,
            "catalogue_digest": self.catalogue_digest,
            "context_digest": self.context_digest,
            "authority_digest": self.authority_digest,
            "edge_ids": list(self.edge_ids),
            "total_costs": [item.to_dict() for item in self.total_costs],
            "evidence_strength": None if self.evidence_strength is None else self.evidence_strength.value,
            "expanded_labels": self.expanded_labels,
            "blockers": [item.to_dict() for item in self.blockers],
        }


@dataclass(frozen=True)
class _SearchLabel:
    """One partial route and its accumulated additive cost vector."""

    label_id: int
    node: RepresentationRef
    costs: tuple[int, ...]
    edge_ids: tuple[str, ...]
    visited: frozenset[RepresentationRef]


def _label_dominates(left: _SearchLabel, right: _SearchLabel) -> bool:
    """Mathematics: left dominates right when costs are componentwise no greater and left forbids no additional revisit."""
    if not left.visited.issubset(right.visited):
        return False
    if not all(a <= b for a, b in zip(left.costs, right.costs)):
        return False
    strict_cost = any(a < b for a, b in zip(left.costs, right.costs))
    if strict_cost or left.visited != right.visited:
        return True
    return (len(left.edge_ids), left.edge_ids) <= (len(right.edge_ids), right.edge_ids)


def _topology_reachable(
    source: RepresentationRef,
    target: RepresentationRef,
    edges: Sequence[EvidencePathEdge],
) -> bool:
    """Mathematics: decide finite directed reachability over all registered edges, ignoring request filters."""
    adjacency: dict[RepresentationRef, list[RepresentationRef]] = {}
    for edge in edges:
        adjacency.setdefault(edge.source, []).append(edge.target)
    pending = [source]
    visited = {source}
    while pending:
        current = pending.pop()
        if current == target:
            return True
        for following in adjacency.get(current, ()):
            if following not in visited:
                visited.add(following)
                pending.append(following)
    return False


def _local_capability_snapshot(
    operating_system: HeadlessOS,
    pid: int,
) -> tuple[tuple[tuple[str, tuple[str, ...]], ...], str]:
    """Mathematics: read C_pid={(resource,rights)} from the live process and compute H(pid,C_pid)."""
    if not isinstance(operating_system, HeadlessOS):
        raise EvidencePathError("route resolution requires a receiver HeadlessOS")
    if type(pid) is not int or pid < 1:
        raise EvidencePathError("route resolution pid must be a positive strict integer")
    try:
        process = operating_system.environment.kernel._process(pid)
    except Exception as exc:
        raise EvidencePathError(f"receiver process {pid} cannot be resolved") from exc
    if process.status is ProcessStatus.EXITED:
        raise EvidencePathError("exited receiver process cannot resolve executable paths")
    capabilities = tuple(
        sorted(
            (
                capability.resource,
                tuple(sorted(capability.rights)),
            )
            for capability in process.capabilities
        )
    )
    authority_digest = canonical_value_digest({
        "pid": pid,
        "capabilities": [
            {"resource": resource, "rights": list(rights)}
            for resource, rights in capabilities
        ],
    })
    return capabilities, authority_digest


def _has_live_authority(
    edge: EvidencePathEdge,
    capabilities: Sequence[tuple[str, tuple[str, ...]]],
) -> bool:
    """Mathematics: require ∀(resource,rights), ∀right∈rights, ∃local capability that allows(resource,right)."""
    from .kernel import Capability

    local = tuple(Capability(resource, frozenset(rights)) for resource, rights in capabilities)
    return all(
        any(capability.allows(requirement.resource, right) for capability in local)
        for requirement in edge.contract.authority_requirements
        for right in requirement.rights
    )


class EvidencePathResolver:
    """Resolve the least-cost evidence-backed route that satisfies the live receiver boundary."""

    def resolve(
        self,
        catalogue: EvidencePathCatalogue,
        request: EvidencePathRequest,
        operating_system: HeadlessOS,
        pid: int,
    ) -> EvidencePathResult:
        """Mathematics: find the lexicographically least feasible additive cost vector by bounded label-setting search under live authority and evidence gates."""
        if not isinstance(catalogue, EvidencePathCatalogue):
            raise EvidencePathError("catalogue must be an EvidencePathCatalogue")
        if not isinstance(request, EvidencePathRequest):
            raise EvidencePathError("request must be an EvidencePathRequest")
        edges = catalogue.edges
        if len(edges) > catalogue.max_edges:
            raise EvidencePathError("catalogue exceeds its declared edge ceiling")
        capabilities, authority_digest = _local_capability_snapshot(operating_system, pid)
        if request.source == request.target:
            return EvidencePathResult(
                EvidencePathStatus.ALREADY_AT_TARGET,
                request.digest,
                catalogue.digest,
                request.context_digest,
                authority_digest,
            )

        metric_names = tuple(item.name for item in request.metric_order)
        metric_units = {item.name: item.unit for item in request.metric_order}
        ceilings = {item.name: item.amount for item in request.resource_ceilings}
        zero_costs = tuple(0 for _ in request.metric_order)
        adjacency: dict[RepresentationRef, list[EvidencePathEdge]] = {}
        blockers: set[EvidencePathBlocker] = set()

        for edge in edges:
            reasons: list[EvidencePathBlockerCode] = []
            if edge.contract.context_digest not in request.accepted_context_digests:
                reasons.append(EvidencePathBlockerCode.CONTEXT_MISMATCH)
            if not set(edge.contract.precondition_digests).issubset(request.satisfied_preconditions):
                reasons.append(EvidencePathBlockerCode.PRECONDITION_MISSING)
            if not set(edge.contract.invariant_digests).issubset(request.satisfied_invariants):
                reasons.append(EvidencePathBlockerCode.INVARIANT_MISSING)
            if (
                request.minimum_evidence is EvidenceStrength.INDEPENDENT_ORACLE
                and edge.evidence_strength is not EvidenceStrength.INDEPENDENT_ORACLE
            ):
                reasons.append(EvidencePathBlockerCode.EVIDENCE_INSUFFICIENT)
            if not _has_live_authority(edge, capabilities):
                reasons.append(EvidencePathBlockerCode.AUTHORITY_MISSING)

            cost_by_name = {item.name: item for item in edge.costs}
            if set(cost_by_name) != set(metric_names) or any(
                cost_by_name[name].unit != metric_units[name] for name in metric_names if name in cost_by_name
            ):
                reasons.append(EvidencePathBlockerCode.METRIC_MISMATCH)

            if reasons:
                for reason in reasons:
                    blockers.add(EvidencePathBlocker(edge.edge_id, reason))
                continue
            adjacency.setdefault(edge.source, []).append(edge)

        for outgoing in adjacency.values():
            outgoing.sort(key=lambda item: item.edge_id)

        label_serial = 0
        initial = _SearchLabel(0, request.source, zero_costs, (), frozenset({request.source}))
        labels: dict[int, _SearchLabel] = {0: initial}
        active: set[int] = {0}
        frontier: dict[RepresentationRef, list[int]] = {request.source: [0]}
        heap: list[tuple[tuple[int, ...], int, tuple[str, ...], int]] = [
            (zero_costs, 0, (), 0)
        ]
        expanded = 0
        hit_hop_limit = False

        while heap:
            objective, hops, path_key, label_id = heapq.heappop(heap)
            if label_id not in active:
                continue
            label = labels[label_id]
            if label.node == request.target:
                by_name = {
                    name: amount for name, amount in zip(metric_names, label.costs)
                }
                selected_costs = tuple(
                    RouteMetric(name, metric_units[name], by_name[name])
                    for name in metric_names
                )
                selected_edges = [next(edge for edge in edges if edge.edge_id == edge_id) for edge_id in label.edge_ids]
                strength = (
                    EvidenceStrength.INDEPENDENT_ORACLE
                    if all(edge.evidence_strength is EvidenceStrength.INDEPENDENT_ORACLE for edge in selected_edges)
                    else EvidenceStrength.PAIRED_CASE
                )
                return EvidencePathResult(
                    EvidencePathStatus.FOUND,
                    request.digest,
                    catalogue.digest,
                    request.context_digest,
                    authority_digest,
                    label.edge_ids,
                    selected_costs,
                    strength,
                    expanded,
                    tuple(blockers),
                )

            if expanded >= request.max_expansions:
                return EvidencePathResult(
                    EvidencePathStatus.BUDGET_EXHAUSTED,
                    request.digest,
                    catalogue.digest,
                    request.context_digest,
                    authority_digest,
                    expanded_labels=expanded,
                    blockers=tuple(blockers),
                )
            expanded += 1

            for edge in adjacency.get(label.node, ()):
                if edge.target in label.visited:
                    continue
                if len(label.edge_ids) >= request.max_hops:
                    hit_hop_limit = True
                    blockers.add(EvidencePathBlocker(edge.edge_id, EvidencePathBlockerCode.HOP_LIMIT))
                    continue
                edge_costs = {item.name: item.amount for item in edge.costs}
                candidate_costs = tuple(
                    current + edge_costs[name]
                    for current, name in zip(label.costs, metric_names)
                )
                exceeded = [
                    name for name, limit in ceilings.items()
                    if candidate_costs[metric_names.index(name)] > limit
                ]
                if exceeded:
                    for name in exceeded:
                        blockers.add(
                            EvidencePathBlocker(
                                edge.edge_id,
                                EvidencePathBlockerCode.RESOURCE_LIMIT,
                                name,
                            )
                        )
                    continue

                label_serial += 1
                candidate = _SearchLabel(
                    label_serial,
                    edge.target,
                    candidate_costs,
                    label.edge_ids + (edge.edge_id,),
                    label.visited | {edge.target},
                )
                current_frontier = frontier.setdefault(edge.target, [])
                if any(_label_dominates(labels[item], candidate) for item in current_frontier if item in active):
                    continue
                dominated = [
                    item for item in current_frontier
                    if item in active and _label_dominates(candidate, labels[item])
                ]
                for item in dominated:
                    active.discard(item)
                current_frontier[:] = [item for item in current_frontier if item in active]
                current_frontier.append(candidate.label_id)
                labels[candidate.label_id] = candidate
                active.add(candidate.label_id)
                priority = tuple(candidate_costs[metric_names.index(name)] for name in metric_names)
                heapq.heappush(
                    heap,
                    (
                        priority,
                        len(candidate.edge_ids),
                        candidate.edge_ids,
                        candidate.label_id,
                    ),
                )

        topology_exists = _topology_reachable(request.source, request.target, edges)
        if hit_hop_limit:
            status = EvidencePathStatus.BUDGET_EXHAUSTED
        elif topology_exists:
            status = EvidencePathStatus.BLOCKED
        else:
            status = EvidencePathStatus.UNREACHABLE
        return EvidencePathResult(
            status,
            request.digest,
            catalogue.digest,
            request.context_digest,
            authority_digest,
            expanded_labels=expanded,
            blockers=tuple(blockers),
        )
