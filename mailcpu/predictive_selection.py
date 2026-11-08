"""Evidence-bound predictive description selection over composed Virtual Grounds.

This is an offline evaluator. It compares already-admitted component laws against
independently observed, observer-receipted states. Selection never mutates
Structural Memory, promotes a hypervisor policy, or treats a planned fabric
route as proof of execution.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import json
import math
import re
from collections import defaultdict
from typing import Any, Mapping, Sequence

from .classifier import HypervisorAction, HypervisorExecutionResult
from .computational_fabric import ComputationalFabricRouteWitness
from .composed_ground import (
    ComposedComponentAddress,
    ComposedGroundError,
    ComposedVirtualGroundAddress,
    ComposedVirtualGroundNavigator,
)
from .evidence_path_resolver import RouteMetric
from .observer_orbit import (
    ObserverContract,
    ObserverOrbitError,
    ObserverReceipt,
    verify_observer_receipt,
)
from .semantic_translation import canonical_value_digest
from .structural_memory import StructuralMemoryError, StructuralMemoryRegistry
from .temporal import SchedulerReading


_SCHEMA = "mailcpu.predictive-description-selection.v1"
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


class PredictiveSelectionError(ValueError):
    """An experiment, observation, candidate description, or selection report is invalid."""


def _canonical_json(value: Any, label: str) -> str:
    """Mathematics: encode a finite JSON value as its unique sorted-key compact UTF-8 representation."""
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise PredictiveSelectionError(f"{label} is outside the finite JSON domain") from exc


def _digest(value: Any, label: str = "value") -> str:
    """Mathematics: compute SHA-256 over the canonical JSON representation of a finite value."""
    return hashlib.sha256(_canonical_json(value, label).encode("utf-8")).hexdigest()


def _require_digest(value: Any, label: str) -> str:
    """Mathematics: require one lowercase 256-bit SHA-256 identity."""
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise PredictiveSelectionError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _require_identifier(value: Any, label: str) -> str:
    """Mathematics: constrain candidate and component labels to a bounded safe alphabet."""
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise PredictiveSelectionError(f"{label} must be a safe 1-128 character identifier")
    return value


def _require_label(value: Any, label: str) -> str:
    """Mathematics: require a bounded non-empty label without narrowing existing host identity syntax."""
    if not isinstance(value, str) or not value.strip() or len(value) > 256:
        raise PredictiveSelectionError(f"{label} must be non-empty text of at most 256 characters")
    return value


def _require_int(value: Any, label: str, *, minimum: int = 0) -> int:
    """Mathematics: require value in the integer interval [minimum, infinity), excluding Boolean subtypes."""
    if type(value) is not int or value < minimum:
        raise PredictiveSelectionError(f"{label} must be an integer >= {minimum}")
    return value


def _read_path(state: Mapping[str, Any], path: Sequence[str], label: str) -> Any:
    """Mathematics: evaluate a finite nested-object projection at one declared component path."""
    current: Any = state
    for part in path:
        if not isinstance(current, Mapping) or part not in current:
            raise PredictiveSelectionError(f"{label} is missing component field path {tuple(path)!r}")
        current = current[part]
    return current


def _validate_component_value(value: Any, value_kind: str, label: str) -> None:
    """Mathematics: enforce the integer, byte, or bit scalar subdomain without Boolean/integer coercion."""
    if value_kind == "integer":
        valid = type(value) is int
    elif value_kind == "byte":
        valid = type(value) is int and 0 <= value <= 255
    elif value_kind == "bit":
        valid = type(value) is int and value in (0, 1)
    else:
        valid = False
    if not valid:
        raise PredictiveSelectionError(f"{label} does not satisfy component scalar kind {value_kind!r}")


def _flatten_leaves(value: Any, prefix: tuple[str, ...] = ()) -> dict[tuple[str, ...], Any]:
    """Mathematics: map each finite JSON leaf path to its value, treating arrays as atomic ordered values."""
    if isinstance(value, Mapping) and value:
        result: dict[tuple[str, ...], Any] = {}
        for key in sorted(value):
            result.update(_flatten_leaves(value[key], prefix + (key,)))
        return result
    return {prefix: value}


def _leaf_difference_count(left: Any, right: Any) -> int:
    """Mathematics: count unequal leaves in the union of two finite JSON path maps."""
    left_leaves = _flatten_leaves(left)
    right_leaves = _flatten_leaves(right)
    sentinel = object()
    differences = 0
    for path in set(left_leaves) | set(right_leaves):
        left_value = left_leaves.get(path, sentinel)
        right_value = right_leaves.get(path, sentinel)
        if left_value is sentinel or right_value is sentinel:
            differences += 1
        elif _canonical_json(left_value, "left state leaf") != _canonical_json(right_value, "right state leaf"):
            differences += 1
    return differences


def _unmodeled_change_count(
    template: Mapping[str, Any],
    observed: Mapping[str, Any],
    component_paths: Sequence[tuple[str, ...]],
) -> int:
    """Mathematics: count observed/template leaf changes outside the candidate's declared component coordinates."""
    before = _flatten_leaves(template)
    after = _flatten_leaves(observed)
    sentinel = object()
    changed = 0
    for path in set(before) | set(after):
        if path in component_paths:
            continue
        before_value = before.get(path, sentinel)
        after_value = after.get(path, sentinel)
        if before_value is sentinel or after_value is sentinel:
            changed += 1
        elif _canonical_json(before_value, "template leaf") != _canonical_json(after_value, "observed leaf"):
            changed += 1
    return changed


def predictive_experiment_digest(address: ComposedVirtualGroundAddress) -> str:
    """Mathematics: identify the common experiment while excluding candidate-specific generator revisions."""
    if not isinstance(address, ComposedVirtualGroundAddress):
        raise PredictiveSelectionError("experiment digest requires a ComposedVirtualGroundAddress")
    payload = {
        "schema": "mailcpu.predictive-experiment.v1",
        "system_identity": address.system_identity.snapshot(),
        "base_ground": address.base_ground.to_dict(),
        "computational_ground": address.computational_ground.to_dict(),
        "scheduler_id": address.coordinate.scheduler_id,
        "state_schema": address.state_schema.to_dict(),
        "template_json": address.template_json,
        "extensions": address.to_dict()["extensions"],
        "components": [
            {
                "component_id": item.component_id,
                "field_path": list(item.field_path),
                "representation": item.representation.to_dict(),
                "value_kind": item.value_kind,
            }
            for item in address.components
        ],
    }
    return _digest(payload, "predictive experiment identity")


@dataclass(frozen=True)
class PredictiveExecutionEvidence:
    """One executed hypervisor effect with optional, explicitly non-authoritative fabric route context."""

    result_digest: str
    source: str
    channel: str
    sequence: int
    logical_time: int
    decision_receipt: str
    fingerprint: str
    action: str
    executed: bool
    replayed: bool
    node_id: str | None
    substrate: str | None
    estimated_energy: int | None
    estimated_virtual_ticks: int | None
    measured_metrics_json: str
    route_witness_digest: str | None = None
    route_network_costs: tuple[RouteMetric, ...] = ()
    route_host_costs: tuple[RouteMetric, ...] = ()
    route_total_costs: tuple[RouteMetric, ...] = ()
    route_witness_json: str | None = None

    def __post_init__(self) -> None:
        _require_digest(self.result_digest, "hypervisor result digest")
        _require_digest(self.decision_receipt, "hypervisor decision receipt")
        _require_digest(self.fingerprint, "hypervisor fingerprint")
        _require_label(self.source, "hypervisor source")
        _require_label(self.channel, "hypervisor channel")
        _require_int(self.sequence, "hypervisor sequence", minimum=1)
        _require_int(self.logical_time, "hypervisor logical time")
        if self.action != HypervisorAction.ALLOW.value or self.executed is not True:
            raise PredictiveSelectionError("execution evidence requires an ALLOW decision and executed effect")
        if type(self.replayed) is not bool:
            raise PredictiveSelectionError("hypervisor replayed flag must be Boolean")
        if self.node_id is not None:
            _require_label(self.node_id, "execution node_id")
        if self.substrate is not None:
            _require_label(self.substrate, "execution substrate")
        for label, value in (
            ("estimated_energy", self.estimated_energy),
            ("estimated_virtual_ticks", self.estimated_virtual_ticks),
        ):
            if value is not None:
                _require_int(value, label)
        try:
            measured = json.loads(self.measured_metrics_json)
        except (TypeError, json.JSONDecodeError) as exc:
            raise PredictiveSelectionError("measured_metrics_json is malformed") from exc
        if not isinstance(measured, dict) or _canonical_json(measured, "measured metrics") != self.measured_metrics_json:
            raise PredictiveSelectionError("measured_metrics_json must be a canonical object")
        for key, value in measured.items():
            _require_identifier(key, "measurement name")
            if (
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or not math.isfinite(value)
                or value < 0
            ):
                raise PredictiveSelectionError("measured execution metrics must be finite and non-negative")
        if self.route_witness_digest is not None:
            _require_digest(self.route_witness_digest, "route witness digest")
        route_sets = (
            self.route_network_costs,
            self.route_host_costs,
            self.route_total_costs,
        )
        for values in route_sets:
            if not isinstance(values, (tuple, list)) or any(not isinstance(item, RouteMetric) for item in values):
                raise PredictiveSelectionError("route evidence must contain typed RouteMetric values")
        if self.route_witness_digest is None and (any(route_sets) or self.route_witness_json is not None):
            raise PredictiveSelectionError("route metrics and content require a bound route witness digest")
        if self.route_witness_digest is not None:
            if any(not values for values in route_sets) or not isinstance(self.route_witness_json, str):
                raise PredictiveSelectionError("a route witness must preserve its content and all three cost decompositions")
            try:
                route_payload = json.loads(self.route_witness_json)
            except json.JSONDecodeError as exc:
                raise PredictiveSelectionError("route witness JSON is malformed") from exc
            if not isinstance(route_payload, Mapping) or _canonical_json(route_payload, "route witness") != self.route_witness_json:
                raise PredictiveSelectionError("route witness JSON must be canonical")
            try:
                restored_route = ComputationalFabricRouteWitness.from_dict(route_payload)
            except ValueError as exc:
                raise PredictiveSelectionError("route witness failed structural validation") from exc
            if (
                restored_route.digest != self.route_witness_digest
                or restored_route.authoritative is not False
                or restored_route.network_costs != tuple(self.route_network_costs)
                or restored_route.host_costs != tuple(self.route_host_costs)
                or restored_route.total_costs != tuple(self.route_total_costs)
            ):
                raise PredictiveSelectionError("route witness digest, authority or cost vectors differ from the retained evidence")
        object.__setattr__(self, "route_network_costs", tuple(self.route_network_costs))
        object.__setattr__(self, "route_host_costs", tuple(self.route_host_costs))
        object.__setattr__(self, "route_total_costs", tuple(self.route_total_costs))

    @classmethod
    def from_hypervisor_result(
        cls,
        result: HypervisorExecutionResult,
        *,
        route_witness: ComputationalFabricRouteWitness | None = None,
    ) -> "PredictiveExecutionEvidence":
        """Mathematics: retain cost and provenance only for an executed effect returned by the host hypervisor."""
        if not isinstance(result, HypervisorExecutionResult):
            raise PredictiveSelectionError("execution evidence requires a HypervisorExecutionResult")
        if result.action is not HypervisorAction.ALLOW or result.executed is not True:
            raise PredictiveSelectionError("hypervisor result is not an executed ALLOW effect")
        effect = result.effect
        if not isinstance(effect, Mapping) or effect.get("kind") != "virtual_layer.operator_result":
            raise PredictiveSelectionError("hypervisor effect is not a typed Virtual Layer operator result")
        energy = effect.get("estimated_energy")
        ticks = effect.get("estimated_virtual_ticks")
        if energy is not None:
            _require_int(energy, "estimated_energy")
        if ticks is not None:
            _require_int(ticks, "estimated_virtual_ticks")
        measurement = effect.get("measurement")
        if measurement is None and isinstance(effect.get("result"), Mapping):
            measurement = effect["result"].get("measurement")
        if measurement is None:
            measurement = {}
        if not isinstance(measurement, Mapping):
            raise PredictiveSelectionError("Virtual Layer measurement payload must be an object")
        normalized_measurement: dict[str, int | float] = {}
        for key, value in measurement.items():
            if (
                isinstance(key, str)
                and _IDENTIFIER.fullmatch(key) is not None
                and isinstance(value, (int, float))
                and not isinstance(value, bool)
                and math.isfinite(value)
                and value >= 0
            ):
                normalized_measurement[key] = value
        route_digest = None
        network_costs: tuple[RouteMetric, ...] = ()
        host_costs: tuple[RouteMetric, ...] = ()
        total_costs: tuple[RouteMetric, ...] = ()
        route_json = None
        if route_witness is not None:
            if not isinstance(route_witness, ComputationalFabricRouteWitness):
                raise PredictiveSelectionError("route_witness must be a ComputationalFabricRouteWitness")
            if route_witness.authoritative is not False:
                raise PredictiveSelectionError("fabric route evidence must remain non-authoritative")
            if effect.get("node_id") != route_witness.target_host.node_id:
                raise PredictiveSelectionError("fabric route target node differs from the hypervisor execution node")
            route_digest = route_witness.digest
            network_costs = route_witness.network_costs
            host_costs = route_witness.host_costs
            total_costs = route_witness.total_costs
            route_json = _canonical_json(route_witness.to_dict(), "route witness")
        return cls(
            result_digest=_digest(result.to_dict(), "hypervisor execution result"),
            source=result.source,
            channel=result.channel,
            sequence=result.sequence,
            logical_time=result.logical_time,
            decision_receipt=result.decision_receipt,
            fingerprint=result.fingerprint,
            action=result.action.value,
            executed=result.executed,
            replayed=result.replayed,
            node_id=effect.get("node_id") if isinstance(effect.get("node_id"), str) else None,
            substrate=effect.get("substrate") if isinstance(effect.get("substrate"), str) else None,
            estimated_energy=energy,
            estimated_virtual_ticks=ticks,
            measured_metrics_json=_canonical_json(normalized_measurement, "measured execution metrics"),
            route_witness_digest=route_digest,
            route_network_costs=network_costs,
            route_host_costs=host_costs,
            route_total_costs=total_costs,
            route_witness_json=route_json,
        )

    @property
    def measured_metrics(self) -> dict[str, int | float]:
        """Mathematics: decode a detached view of the observed numeric handler measurements."""
        return json.loads(self.measured_metrics_json)

    def to_dict(self) -> dict[str, Any]:
        """Mathematics: serialize executed-result provenance, measured values, and separated route-cost evidence."""
        return {
            "schema": "mailcpu.predictive-execution-evidence.v1",
            "result_digest": self.result_digest,
            "source": self.source,
            "channel": self.channel,
            "sequence": self.sequence,
            "logical_time": self.logical_time,
            "decision_receipt": self.decision_receipt,
            "fingerprint": self.fingerprint,
            "action": self.action,
            "executed": self.executed,
            "replayed": self.replayed,
            "node_id": self.node_id,
            "substrate": self.substrate,
            "estimated_energy": self.estimated_energy,
            "estimated_virtual_ticks": self.estimated_virtual_ticks,
            "measured_metrics": self.measured_metrics,
            "route_witness_digest": self.route_witness_digest,
            "route_network_costs": [item.to_dict() for item in self.route_network_costs],
            "route_host_costs": [item.to_dict() for item in self.route_host_costs],
            "route_total_costs": [item.to_dict() for item in self.route_total_costs],
            "route_witness": None if self.route_witness_json is None else json.loads(self.route_witness_json),
            "route_authoritative": False if self.route_witness_digest is not None else None,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "PredictiveExecutionEvidence":
        """Mathematics: reconstruct the exact typed execution-evidence projection and revalidate its route boundary."""
        expected = {
            "schema", "result_digest", "source", "channel", "sequence", "logical_time",
            "decision_receipt", "fingerprint", "action", "executed", "replayed", "node_id",
            "substrate", "estimated_energy", "estimated_virtual_ticks", "measured_metrics",
            "route_witness_digest", "route_network_costs", "route_host_costs",
            "route_total_costs", "route_witness", "route_authoritative",
        }
        if not isinstance(payload, Mapping) or set(payload) != expected:
            raise PredictiveSelectionError("execution evidence fields are invalid")
        if payload["schema"] != "mailcpu.predictive-execution-evidence.v1":
            raise PredictiveSelectionError("unsupported execution evidence schema")
        if payload["route_authoritative"] is not (
            False if payload["route_witness_digest"] is not None else None
        ):
            raise PredictiveSelectionError("route authority marker is invalid")
        metrics = payload["measured_metrics"]
        if not isinstance(metrics, Mapping):
            raise PredictiveSelectionError("measured_metrics must be an object")
        return cls(
            result_digest=payload["result_digest"],
            source=payload["source"],
            channel=payload["channel"],
            sequence=payload["sequence"],
            logical_time=payload["logical_time"],
            decision_receipt=payload["decision_receipt"],
            fingerprint=payload["fingerprint"],
            action=payload["action"],
            executed=payload["executed"],
            replayed=payload["replayed"],
            node_id=payload["node_id"],
            substrate=payload["substrate"],
            estimated_energy=payload["estimated_energy"],
            estimated_virtual_ticks=payload["estimated_virtual_ticks"],
            measured_metrics_json=_canonical_json(dict(metrics), "measured execution metrics"),
            route_witness_digest=payload["route_witness_digest"],
            route_network_costs=tuple(RouteMetric.from_dict(item) for item in payload["route_network_costs"]),
            route_host_costs=tuple(RouteMetric.from_dict(item) for item in payload["route_host_costs"]),
            route_total_costs=tuple(RouteMetric.from_dict(item) for item in payload["route_total_costs"]),
            route_witness_json=(
                None if payload["route_witness"] is None
                else _canonical_json(payload["route_witness"], "route witness")
            ),
        )


@dataclass(frozen=True)
class PredictiveGroundObservation:
    """Independent state label bound to an ObserverContract and typed scheduler coordinate."""

    tick: int
    state_json: str
    experiment_digest: str
    observer_contract: ObserverContract
    observer_receipt: ObserverReceipt
    execution_evidence: PredictiveExecutionEvidence | None = None

    def __post_init__(self) -> None:
        _require_int(self.tick, "observation tick")
        _require_digest(self.experiment_digest, "observation experiment digest")
        if not isinstance(self.observer_contract, ObserverContract):
            raise PredictiveSelectionError("observation requires an ObserverContract")
        if not isinstance(self.observer_receipt, ObserverReceipt):
            raise PredictiveSelectionError("observation requires an ObserverReceipt")
        try:
            state = json.loads(self.state_json)
        except (TypeError, json.JSONDecodeError) as exc:
            raise PredictiveSelectionError("observed state JSON is malformed") from exc
        if not isinstance(state, dict) or _canonical_json(state, "observed state") != self.state_json:
            raise PredictiveSelectionError("observed state must be a canonical JSON object")
        contract = self.observer_contract
        receipt = self.observer_receipt
        if contract.context_digest != self.experiment_digest:
            raise PredictiveSelectionError("observer contract is not bound to this predictive experiment")
        if not verify_observer_receipt(contract, receipt):
            raise PredictiveSelectionError("observer receipt does not verify against its exact contract")
        if _canonical_json(receipt.projection, "observer projection") != self.state_json:
            raise PredictiveSelectionError("observer projection differs from the supplied observed state")
        frame = receipt.time_frame
        if frame is None or frame.scheduler is None:
            raise PredictiveSelectionError("observer receipt must carry a typed scheduler coordinate")
        if frame.scheduler.tick != self.tick:
            raise PredictiveSelectionError("observer receipt scheduler tick differs from observation tick")
        if self.execution_evidence is not None:
            if not isinstance(self.execution_evidence, PredictiveExecutionEvidence):
                raise PredictiveSelectionError("execution_evidence has an unsupported type")
            if self.execution_evidence.logical_time != self.tick:
                raise PredictiveSelectionError("hypervisor execution time differs from observation tick")
        if receipt.subject_state_after_digest is not None:
            if receipt.subject_state_after_digest != canonical_value_digest(state):
                raise PredictiveSelectionError("observer subject after-digest differs from observed state")

    @classmethod
    def capture(
        cls,
        address: ComposedVirtualGroundAddress,
        observed_state: Mapping[str, Any],
        contract: ObserverContract,
        receipt: ObserverReceipt,
        *,
        execution_evidence: PredictiveExecutionEvidence | None = None,
    ) -> "PredictiveGroundObservation":
        """Mathematics: bind an independently supplied state and ObserverReceipt to the experiment's schema and clock."""
        if not isinstance(address, ComposedVirtualGroundAddress):
            raise PredictiveSelectionError("capture requires a ComposedVirtualGroundAddress")
        if contract.subject != address.state_schema or contract.interpretation != address.computational_ground:
            raise PredictiveSelectionError("observer subject or interpretation differs from the composed Ground")
        if receipt.time_frame is None or receipt.time_frame.scheduler is None:
            raise PredictiveSelectionError("observer receipt lacks a typed scheduler reading")
        if receipt.time_frame.scheduler.scheduler_id != address.coordinate.scheduler_id:
            raise PredictiveSelectionError("observer scheduler identity differs from the composed Ground")
        state_json = _canonical_json(dict(observed_state), "observed state")
        return cls(
            tick=receipt.time_frame.scheduler.tick,
            state_json=state_json,
            experiment_digest=predictive_experiment_digest(address),
            observer_contract=contract,
            observer_receipt=receipt,
            execution_evidence=execution_evidence,
        )

    @property
    def observed_state(self) -> dict[str, Any]:
        """Mathematics: decode a detached state object from the immutable canonical sample."""
        return json.loads(self.state_json)

    @property
    def digest(self) -> str:
        """Mathematics: identify the exact state label, observer receipt, coordinate, and execution evidence."""
        return _digest(self.to_dict(), "predictive observation")

    def to_dict(self) -> dict[str, Any]:
        """Mathematics: serialize state content separately from its observer provenance and operational evidence."""
        return {
            "schema": "mailcpu.predictive-ground-observation.v1",
            "tick": self.tick,
            "state_json": self.state_json,
            "state_digest": canonical_value_digest(self.observed_state),
            "experiment_digest": self.experiment_digest,
            "observer_contract": self.observer_contract.to_dict(),
            "observer_receipt": self.observer_receipt.to_dict(),
            "execution_evidence": None if self.execution_evidence is None else self.execution_evidence.to_dict(),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "PredictiveGroundObservation":
        """Mathematics: reconstruct an observer-receipted state sample and rerun all local integrity checks."""
        expected = {
            "schema", "tick", "state_json", "state_digest", "experiment_digest",
            "observer_contract", "observer_receipt", "execution_evidence",
        }
        if not isinstance(payload, Mapping) or set(payload) != expected:
            raise PredictiveSelectionError("predictive observation fields are invalid")
        if payload["schema"] != "mailcpu.predictive-ground-observation.v1":
            raise PredictiveSelectionError("unsupported predictive observation schema")
        contract = ObserverContract.from_dict(payload["observer_contract"])
        receipt = ObserverReceipt.from_dict(payload["observer_receipt"])
        raw_evidence = payload["execution_evidence"]
        evidence = None if raw_evidence is None else PredictiveExecutionEvidence.from_dict(raw_evidence)
        result = cls(
            tick=payload["tick"],
            state_json=payload["state_json"],
            experiment_digest=payload["experiment_digest"],
            observer_contract=contract,
            observer_receipt=receipt,
            execution_evidence=evidence,
        )
        if payload["state_digest"] != canonical_value_digest(result.observed_state):
            raise PredictiveSelectionError("predictive observation state digest mismatch")
        return result


@dataclass(frozen=True)
class PredictiveDescriptionCandidate:
    """One fixed composed description whose component revisions are already admitted."""

    candidate_id: str
    address: ComposedVirtualGroundAddress

    def __post_init__(self) -> None:
        _require_identifier(self.candidate_id, "candidate_id")
        if not isinstance(self.address, ComposedVirtualGroundAddress):
            raise PredictiveSelectionError("candidate address must be a ComposedVirtualGroundAddress")

    @property
    def experiment_digest(self) -> str:
        """Mathematics: return the common experiment identity independent of the selected generator basis."""
        return predictive_experiment_digest(self.address)

    @property
    def digest(self) -> str:
        """Mathematics: identify a candidate name and its full pinned composed address."""
        return _digest(
            {"candidate_id": self.candidate_id, "address": self.address.to_dict()},
            "predictive candidate",
        )

    def to_dict(self) -> dict[str, Any]:
        """Mathematics: serialize the candidate identity and its immutable composed Virtual Ground address."""
        return {
            "schema": "mailcpu.predictive-description-candidate.v1",
            "candidate_id": self.candidate_id,
            "address": self.address.to_dict(),
            "candidate_digest": self.digest,
        }


@dataclass(frozen=True)
class PredictivePartitionMetrics:
    """Predictive coverage, conditional accuracy, residuals, and algorithmic work for one chronological partition."""

    partition: str
    sample_count: int
    covered_samples: int
    expected_components: int
    predicted_components: int
    correct_components: int
    exact_state_matches: int
    residual_leaf_count: int
    unmodeled_changed_leaf_count: int
    navigation_work_units: int
    navigation_evidence_digest: str
    distinct_observed_component_states: int
    distinct_predicted_component_states: int
    distinct_matched_component_states: int
    component_state_space_coverage: float
    refusal_counts: tuple[tuple[str, int], ...]
    coverage_ratio: float
    component_accuracy: float
    predictive_yield: float
    full_state_match_rate: float

    def __post_init__(self) -> None:
        if self.partition not in {"development", "validation", "test"}:
            raise PredictiveSelectionError("unknown predictive partition")
        for name in (
            "sample_count", "covered_samples", "expected_components", "predicted_components",
            "correct_components", "exact_state_matches", "residual_leaf_count",
            "unmodeled_changed_leaf_count", "navigation_work_units",
            "distinct_observed_component_states", "distinct_predicted_component_states",
            "distinct_matched_component_states",
        ):
            _require_int(getattr(self, name), name)
        if self.covered_samples > self.sample_count or self.exact_state_matches > self.covered_samples:
            raise PredictiveSelectionError("partition sample counters are inconsistent")
        if (
            self.distinct_observed_component_states > self.sample_count
            or self.distinct_predicted_component_states > self.covered_samples
            or self.distinct_matched_component_states > min(
                self.distinct_observed_component_states,
                self.distinct_predicted_component_states,
            )
            or sum(count for _, count in self.refusal_counts) > self.sample_count
        ):
            raise PredictiveSelectionError("partition distinct-state or refusal counters are inconsistent")
        if self.correct_components > self.predicted_components or self.predicted_components > self.expected_components:
            raise PredictiveSelectionError("partition component counters are inconsistent")
        _require_digest(self.navigation_evidence_digest, "navigation evidence digest")
        if self.distinct_matched_component_states > self.distinct_observed_component_states:
            raise PredictiveSelectionError("matched component-state count exceeds observed distinct states")
        for name in ("coverage_ratio", "component_accuracy", "predictive_yield", "full_state_match_rate", "component_state_space_coverage"):
            value = getattr(self, name)
            if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value) or not 0 <= value <= 1:
                raise PredictiveSelectionError(f"{name} must be a finite ratio in [0, 1]")
        refusals = tuple(sorted(tuple(item) for item in self.refusal_counts))
        for item in refusals:
            if len(item) != 2 or not isinstance(item[0], str):
                raise PredictiveSelectionError("refusal_counts must contain (error_name,count) pairs")
            _require_int(item[1], "refusal count")
        object.__setattr__(self, "refusal_counts", refusals)
        expected_ratios = {
            "coverage_ratio": self.covered_samples / self.sample_count if self.sample_count else 0.0,
            "component_accuracy": self.correct_components / self.predicted_components if self.predicted_components else 0.0,
            "predictive_yield": self.correct_components / self.expected_components if self.expected_components else 0.0,
            "full_state_match_rate": self.exact_state_matches / self.sample_count if self.sample_count else 0.0,
            "component_state_space_coverage": (
                self.distinct_matched_component_states / self.distinct_observed_component_states
                if self.distinct_observed_component_states else 0.0
            ),
        }
        if any(
            not math.isclose(getattr(self, name), expected, rel_tol=1e-12, abs_tol=1e-12)
            for name, expected in expected_ratios.items()
        ):
            raise PredictiveSelectionError("partition ratios do not agree with their integer evidence counts")

    @property
    def mean_navigation_work_units(self) -> float:
        """Mathematics: average the declared algorithmic work proxy over attempted sample coordinates."""
        return self.navigation_work_units / self.sample_count if self.sample_count else 0.0

    def to_dict(self) -> dict[str, Any]:
        """Mathematics: serialize integer evidence counts and their explicitly derived predictive ratios."""
        return {
            "partition": self.partition,
            "sample_count": self.sample_count,
            "covered_samples": self.covered_samples,
            "expected_components": self.expected_components,
            "predicted_components": self.predicted_components,
            "correct_components": self.correct_components,
            "exact_state_matches": self.exact_state_matches,
            "residual_leaf_count": self.residual_leaf_count,
            "unmodeled_changed_leaf_count": self.unmodeled_changed_leaf_count,
            "navigation_work_units": self.navigation_work_units,
            "navigation_evidence_digest": self.navigation_evidence_digest,
            "distinct_observed_component_states": self.distinct_observed_component_states,
            "distinct_predicted_component_states": self.distinct_predicted_component_states,
            "distinct_matched_component_states": self.distinct_matched_component_states,
            "component_state_space_coverage": self.component_state_space_coverage,
            "mean_navigation_work_units": self.mean_navigation_work_units,
            "refusal_counts": [{"error": name, "count": count} for name, count in self.refusal_counts],
            "coverage_ratio": self.coverage_ratio,
            "component_accuracy": self.component_accuracy,
            "predictive_yield": self.predictive_yield,
            "full_state_match_rate": self.full_state_match_rate,
        }


@dataclass(frozen=True)
class PredictiveCandidateEvaluation:
    """One candidate's cost profile and per-partition predictions."""

    candidate_id: str
    candidate_digest: str
    description_digest: str
    description_bytes: int
    verification_witness_units: int
    generator_profiles: tuple[tuple[str, str, str], ...]
    partitions: tuple[PredictivePartitionMetrics, ...]

    def __post_init__(self) -> None:
        _require_identifier(self.candidate_id, "candidate evaluation id")
        _require_digest(self.candidate_digest, "candidate digest")
        _require_digest(self.description_digest, "description digest")
        _require_int(self.description_bytes, "description bytes")
        _require_int(self.verification_witness_units, "verification witness units")
        profiles = tuple(sorted(tuple(item) for item in self.generator_profiles))
        if any(len(item) != 3 or any(not isinstance(part, str) for part in item) for item in profiles):
            raise PredictiveSelectionError("generator profiles must be component/family/complexity triples")
        partitions = tuple(self.partitions)
        if any(not isinstance(item, PredictivePartitionMetrics) for item in partitions):
            raise PredictiveSelectionError("candidate partitions must contain typed predictive metrics")
        if {item.partition for item in partitions} != {"development", "validation", "test"}:
            raise PredictiveSelectionError("candidate evaluation must report all three chronological partitions")
        object.__setattr__(self, "generator_profiles", profiles)
        object.__setattr__(self, "partitions", tuple(sorted(partitions, key=lambda item: item.partition)))

    def partition(self, name: str) -> PredictivePartitionMetrics:
        """Mathematics: select the unique immutable metrics record for a chronological partition."""
        for item in self.partitions:
            if item.partition == name:
                return item
        raise PredictiveSelectionError(f"candidate has no {name!r} partition")

    def to_dict(self) -> dict[str, Any]:
        """Mathematics: serialize description identity, structural cost, certificate cost, and all split results."""
        return {
            "candidate_id": self.candidate_id,
            "candidate_digest": self.candidate_digest,
            "description_digest": self.description_digest,
            "description_bytes": self.description_bytes,
            "verification_witness_units": self.verification_witness_units,
            "generator_profiles": [
                {"component_id": component_id, "family": family, "complexity_bound": complexity}
                for component_id, family, complexity in self.generator_profiles
            ],
            "partitions": [item.to_dict() for item in self.partitions],
        }


@dataclass(frozen=True)
class PredictiveSelectionReport:
    """Portable, non-authoritative candidate ranking with an untouched chronological test partition."""

    experiment_digest: str
    sample_digest: str
    development_through_tick: int
    validation_through_tick: int
    partition_counts: tuple[tuple[str, int], ...]
    ranking: tuple[str, ...]
    pareto_frontier: tuple[str, ...]
    selected_candidate_id: str
    evaluations: tuple[PredictiveCandidateEvaluation, ...]
    operational_profile_json: str
    recommendation_authoritative: bool = False

    def __post_init__(self) -> None:
        _require_digest(self.experiment_digest, "report experiment digest")
        _require_digest(self.sample_digest, "report sample digest")
        _require_int(self.development_through_tick, "development cutoff")
        _require_int(self.validation_through_tick, "validation cutoff", minimum=self.development_through_tick + 1)
        counts = tuple(sorted(tuple(item) for item in self.partition_counts))
        if {item[0] for item in counts} != {"development", "validation", "test"}:
            raise PredictiveSelectionError("report partition counts must name all chronological splits")
        for _, count in counts:
            _require_int(count, "partition count")
        evaluations = tuple(self.evaluations)
        if not evaluations or any(not isinstance(item, PredictiveCandidateEvaluation) for item in evaluations):
            raise PredictiveSelectionError("selection report requires candidate evaluations")
        ids = [item.candidate_id for item in evaluations]
        if len(set(ids)) != len(ids) or set(self.ranking) != set(ids) or len(self.ranking) != len(ids):
            raise PredictiveSelectionError("selection ranking must include every candidate exactly once")
        if self.selected_candidate_id not in ids or self.selected_candidate_id != self.ranking[0]:
            raise PredictiveSelectionError("selected candidate must be the top-ranked candidate")
        if not self.pareto_frontier or not set(self.pareto_frontier).issubset(ids):
            raise PredictiveSelectionError("report Pareto frontier is invalid")
        if self.recommendation_authoritative is not False:
            raise PredictiveSelectionError("predictive selection recommendations are never execution authority")
        try:
            profile = json.loads(self.operational_profile_json)
        except (TypeError, json.JSONDecodeError) as exc:
            raise PredictiveSelectionError("operational profile JSON is malformed") from exc
        if not isinstance(profile, dict) or _canonical_json(profile, "operational profile") != self.operational_profile_json:
            raise PredictiveSelectionError("operational profile must be canonical JSON")
        object.__setattr__(self, "partition_counts", counts)
        object.__setattr__(self, "evaluations", tuple(sorted(evaluations, key=lambda item: item.candidate_id)))

    def identity_payload(self) -> dict[str, Any]:
        """Mathematics: project every split, rank, cost and evidence summary into one report identity."""
        return {
            "schema": _SCHEMA,
            "experiment_digest": self.experiment_digest,
            "sample_digest": self.sample_digest,
            "development_through_tick": self.development_through_tick,
            "validation_through_tick": self.validation_through_tick,
            "partition_counts": [{"partition": name, "count": count} for name, count in self.partition_counts],
            "ranking": list(self.ranking),
            "pareto_frontier": list(self.pareto_frontier),
            "selected_candidate_id": self.selected_candidate_id,
            "candidate_evaluations": [item.to_dict() for item in self.evaluations],
            "operational_profile": json.loads(self.operational_profile_json),
            "recommendation_authoritative": False,
            "selection_scope": "offline-predictive-description-recommendation",
        }

    @property
    def digest(self) -> str:
        """Mathematics: identify the complete immutable selection report by canonical SHA-256."""
        return _digest(self.identity_payload(), "predictive selection report")

    def to_dict(self) -> dict[str, Any]:
        """Mathematics: serialize the report identity together with its reproducible content digest."""
        return {**self.identity_payload(), "report_digest": self.digest}


def _address_at_tick(address: ComposedVirtualGroundAddress, tick: int) -> ComposedVirtualGroundAddress:
    """Mathematics: rebind every component's relative generator coordinate to one observed absolute scheduler tick."""
    _require_int(tick, "prediction tick")
    if tick < address.base_ground.coordinate:
        raise PredictiveSelectionError("prediction tick precedes the candidate's base Virtual Ground")
    coordinate = SchedulerReading(address.coordinate.scheduler_id, tick)
    offset = tick - address.base_ground.coordinate
    components: list[ComposedComponentAddress] = []
    for component in address.components:
        memory_ref = replace(component.orbit_address.structural_memory, coordinate=offset)
        orbit_address = replace(
            component.orbit_address,
            coordinate=coordinate,
            structural_memory=memory_ref,
        )
        components.append(replace(component, orbit_address=orbit_address))
    return replace(address, coordinate=coordinate, components=tuple(components))


def _navigation_work_units(family: str, parameters: Mapping[str, Any], order: int, coordinate: int) -> int:
    """Mathematics: produce a deterministic asymptotic work proxy without enumerating intermediate states."""
    if family in {"int", "fgraph"}:
        return 1
    if family == "lcg":
        modulus = parameters.get("mod")
        if type(modulus) is not int or modulus < 2:
            raise PredictiveSelectionError("admitted LCG description has an invalid modulus")
        return max(1, coordinate.bit_length())
    if family == "gf2":
        return max(1, order ** 3 * max(1, (coordinate + 1).bit_length()))
    raise PredictiveSelectionError(f"unsupported generator family {family!r}")


class PredictiveDescriptionSelector:
    """Evaluate admitted composed descriptions against independently receipted state observations."""

    def __init__(self, registry: StructuralMemoryRegistry) -> None:
        """Mathematics: bind selection to one receiver-local Structural Memory admission registry."""
        if not isinstance(registry, StructuralMemoryRegistry):
            raise PredictiveSelectionError("selector requires a StructuralMemoryRegistry")
        self.registry = registry
        self.navigator = ComposedVirtualGroundNavigator(registry)

    def _description_profile(
        self,
        candidate: PredictiveDescriptionCandidate,
    ) -> tuple[str, int, int, tuple[tuple[str, str, str], ...], tuple[Any, ...]]:
        """Mathematics: bind complete admitted specs and certificates into description size and verification cost."""
        component_descriptions: list[dict[str, Any]] = []
        versions: list[Any] = []
        profiles: list[tuple[str, str, str]] = []
        verification_units = 0
        for component in candidate.address.components:
            memory_ref = component.orbit_address.structural_memory
            try:
                version = self.registry.version_for_revision(memory_ref.memory_id, memory_ref.revision)
            except StructuralMemoryError as exc:
                raise PredictiveSelectionError(
                    f"candidate {candidate.candidate_id!r} references a non-admitted Structural Memory revision"
                ) from exc
            if (
                version.spec.digest != memory_ref.spec_digest
                or version.certificate.digest != memory_ref.certificate_digest
                or version.spec.context != json.loads(_canonical_json(dict(memory_ref.context), "component memory context"))
            ):
                raise PredictiveSelectionError(
                    f"candidate {candidate.candidate_id!r} has a component revision/certificate mismatch"
                )
            component_descriptions.append({
                "component_id": component.component_id,
                "field_path": list(component.field_path),
                "representation": component.representation.to_dict(),
                "value_kind": component.value_kind,
                "spec": version.spec.to_dict(),
                "certificate": version.certificate.to_dict(),
            })
            versions.append(version)
            verification_units += version.certificate.witness_count
            profiles.append((component.component_id, version.spec.family, {
                "int": "O(1)",
                "fgraph": "O(1) indexed generator read",
                "lcg": "O(log m)",
                "gf2": "O(L^3 log t)",
            }[version.spec.family]))
        description = {
            "schema": "mailcpu.predictive-description.v1",
            "experiment_digest": candidate.experiment_digest,
            "components": component_descriptions,
        }
        encoded = _canonical_json(description, "candidate description")
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest(), len(encoded.encode("utf-8")), verification_units, tuple(sorted(profiles)), tuple(versions)

    def _partition(
        self,
        candidate: PredictiveDescriptionCandidate,
        samples: Sequence[PredictiveGroundObservation],
        versions: Sequence[Any],
        partition: str,
    ) -> PredictivePartitionMetrics:
        """Mathematics: compare direct generator values with observer labels over one chronologically fixed sample partition."""
        sample_count = len(samples)
        component_count = len(candidate.address.components)
        expected_components = sample_count * component_count
        covered = 0
        predicted_components = 0
        correct_components = 0
        exact_state_matches = 0
        residual_leaf_count = 0
        unmodeled_changed_leaf_count = 0
        navigation_work_units = 0
        refusal_counts: dict[str, int] = defaultdict(int)
        navigation_evidence: list[dict[str, Any]] = []
        observed_component_states: set[str] = set()
        predicted_component_states: set[str] = set()
        matched_component_states: set[str] = set()
        template = candidate.address.template
        component_paths = tuple(item.field_path for item in candidate.address.components)

        for sample in samples:
            observed = sample.observed_state
            unmodeled_changed_leaf_count += _unmodeled_change_count(
                template, observed, component_paths
            )
            observed_vector = []
            for component in candidate.address.components:
                expected = _read_path(observed, component.field_path, "observed state")
                _validate_component_value(expected, component.value_kind, "observed component")
                observed_vector.append([component.component_id, expected])
            observed_vector_json = _canonical_json(observed_vector, "observed component state")
            observed_component_states.add(observed_vector_json)
            relative_coordinate = sample.tick - candidate.address.base_ground.coordinate
            for version in versions:
                navigation_work_units += _navigation_work_units(
                    version.spec.family,
                    version.spec.parameters,
                    version.spec.order,
                    relative_coordinate,
                )
            try:
                sample_address = _address_at_tick(candidate.address, sample.tick)
                result = self.navigator.locate(sample_address)
            except (ComposedGroundError, StructuralMemoryError, ObserverOrbitError) as exc:
                refusal_counts["guarded_navigation_refusal"] += 1
                navigation_evidence.append({
                    "tick": sample.tick,
                    "disposition": "refused",
                    "error_type": type(exc).__name__,
                })
                continue
            if result.expanded_states != 0:
                raise PredictiveSelectionError("candidate evaluation unexpectedly expanded intermediate states")
            covered += 1
            predicted_components += component_count
            projection = result.projection
            navigation_evidence.append({
                "tick": sample.tick,
                "disposition": "predicted",
                "address_digest": projection.address_digest,
                "state_digest": projection.state_digest,
                "projection_digest": projection.projection_digest,
                "read_evidence_digest": projection.evidence_digest,
            })
            predicted_by_id = {
                item.address.component_id: item.projection.value
                for item in projection.components
            }
            predicted_vector = [
                [component.component_id, predicted_by_id[component.component_id]]
                for component in candidate.address.components
            ]
            predicted_vector_json = _canonical_json(predicted_vector, "predicted component state")
            predicted_component_states.add(predicted_vector_json)
            if predicted_vector_json == observed_vector_json:
                matched_component_states.add(observed_vector_json)
            for component in candidate.address.components:
                actual = predicted_by_id[component.component_id]
                expected = _read_path(observed, component.field_path, "observed state")
                if actual == expected:
                    correct_components += 1
            if projection.state_digest == canonical_value_digest(observed):
                exact_state_matches += 1
            residual_leaf_count += _leaf_difference_count(projection.state, observed)

        component_accuracy = (
            correct_components / predicted_components if predicted_components else 0.0
        )
        coverage_ratio = covered / sample_count if sample_count else 0.0
        predictive_yield = (
            correct_components / expected_components if expected_components else 0.0
        )
        full_state_match_rate = (
            exact_state_matches / sample_count if sample_count else 0.0
        )
        return PredictivePartitionMetrics(
            partition=partition,
            sample_count=sample_count,
            covered_samples=covered,
            expected_components=expected_components,
            predicted_components=predicted_components,
            correct_components=correct_components,
            exact_state_matches=exact_state_matches,
            residual_leaf_count=residual_leaf_count,
            unmodeled_changed_leaf_count=unmodeled_changed_leaf_count,
            navigation_work_units=navigation_work_units,
            navigation_evidence_digest=_digest(navigation_evidence, "partition navigation evidence"),
            distinct_observed_component_states=len(observed_component_states),
            distinct_predicted_component_states=len(predicted_component_states),
            distinct_matched_component_states=len(matched_component_states),
            component_state_space_coverage=(
                len(matched_component_states) / len(observed_component_states)
                if observed_component_states else 0.0
            ),
            refusal_counts=tuple(sorted(refusal_counts.items())),
            coverage_ratio=coverage_ratio,
            component_accuracy=component_accuracy,
            predictive_yield=predictive_yield,
            full_state_match_rate=full_state_match_rate,
        )

    @staticmethod
    def _dominates(
        left: PredictiveCandidateEvaluation,
        right: PredictiveCandidateEvaluation,
    ) -> bool:
        """Mathematics: test Pareto dominance across validation yield, coverage, accuracy and three explicit costs."""
        lm = left.partition("validation")
        rm = right.partition("validation")
        left_values = (
            lm.predictive_yield,
            lm.component_state_space_coverage,
            lm.coverage_ratio,
            lm.component_accuracy,
            lm.full_state_match_rate,
            -left.description_bytes,
            -lm.mean_navigation_work_units,
            -left.verification_witness_units,
        )
        right_values = (
            rm.predictive_yield,
            rm.component_state_space_coverage,
            rm.coverage_ratio,
            rm.component_accuracy,
            rm.full_state_match_rate,
            -right.description_bytes,
            -rm.mean_navigation_work_units,
            -right.verification_witness_units,
        )
        no_worse = all(a >= b for a, b in zip(left_values, right_values))
        strictly_better = any(a > b for a, b in zip(left_values, right_values))
        return no_worse and strictly_better

    @staticmethod
    def _operational_profile(
        samples: Sequence[PredictiveGroundObservation],
    ) -> dict[str, Any]:
        """Mathematics: aggregate actual hypervisor execution evidence separately from estimated fabric route costs."""
        evidence = [item.execution_evidence for item in samples if item.execution_evidence is not None]
        measured_totals: dict[str, float] = defaultdict(float)
        route_totals: dict[tuple[str, str, str], int] = defaultdict(int)
        route_count = 0
        estimated_energy = 0
        estimated_ticks = 0
        energy_count = 0
        tick_count = 0
        for item in evidence:
            if item.estimated_energy is not None:
                estimated_energy += item.estimated_energy
                energy_count += 1
            if item.estimated_virtual_ticks is not None:
                estimated_ticks += item.estimated_virtual_ticks
                tick_count += 1
            for name, value in item.measured_metrics.items():
                measured_totals[name] += float(value)
            if item.route_witness_digest is not None:
                route_count += 1
                for metric in item.route_network_costs:
                    route_totals[("network", metric.name, metric.unit)] += metric.amount
                for metric in item.route_host_costs:
                    route_totals[("host", metric.name, metric.unit)] += metric.amount
                for metric in item.route_total_costs:
                    route_totals[("total", metric.name, metric.unit)] += metric.amount
        return {
            "hypervisor_executed_samples": len(evidence),
            "hypervisor_replayed_samples": sum(1 for item in evidence if item.replayed),
            "estimated_energy_sum": estimated_energy,
            "estimated_energy_sample_count": energy_count,
            "estimated_virtual_ticks_sum": estimated_ticks,
            "estimated_virtual_tick_sample_count": tick_count,
            "measured_metric_sums": dict(sorted(measured_totals.items())),
            "fabric_route_witness_samples": route_count,
            "fabric_route_cost_sums": [
                {"cost_scope": scope, "name": name, "unit": unit, "amount": amount}
                for (scope, name, unit), amount in sorted(route_totals.items())
            ],
            "authority_boundary": {
                "hypervisor": "executed ALLOW effect from a receiver-local HypervisorExecutionResult",
                "fabric": "non-authoritative route estimate; never execution proof",
            },
            "metric_boundary": {
                "estimated_energy": "Virtual Layer contract estimate, not physical energy measurement",
                "estimated_virtual_ticks": "Virtual Layer scheduling estimate, not elapsed wall time",
                "measured_metric_sums": "sum of explicitly reported numeric handler measurements",
                "fabric_route_cost_sums": "sum of typed route metric amounts in their declared units",
            },
        }

    def evaluate(
        self,
        candidates: Sequence[PredictiveDescriptionCandidate],
        observations: Sequence[PredictiveGroundObservation],
        *,
        development_through_tick: int,
        validation_through_tick: int,
    ) -> PredictiveSelectionReport:
        """Select among admitted descriptions using validation Pareto dominance and a later untouched test partition.

        Mathematics:
        Split samples by logical scheduler coordinate:
          development: t <= d
          validation:  d < t <= v
          test:        t > v

        Candidate ranking is based only on validation. The test partition is
        scored after ranking and cannot affect the recommendation. No candidate
        law is fitted or re-admitted by this evaluator.
        """
        if not isinstance(candidates, (tuple, list)) or not candidates:
            raise PredictiveSelectionError("at least one predictive description candidate is required")
        if not isinstance(observations, (tuple, list)) or not observations:
            raise PredictiveSelectionError("at least one independent observation is required")
        development_cutoff = _require_int(development_through_tick, "development cutoff")
        validation_cutoff = _require_int(
            validation_through_tick,
            "validation cutoff",
            minimum=development_cutoff + 1,
        )
        candidate_values = tuple(candidates)
        observation_values = tuple(observations)
        if any(not isinstance(item, PredictiveDescriptionCandidate) for item in candidate_values):
            raise PredictiveSelectionError("candidates must contain PredictiveDescriptionCandidate values")
        if any(not isinstance(item, PredictiveGroundObservation) for item in observation_values):
            raise PredictiveSelectionError("observations must contain PredictiveGroundObservation values")
        candidate_ids = [item.candidate_id for item in candidate_values]
        if len(set(candidate_ids)) != len(candidate_ids):
            raise PredictiveSelectionError("candidate IDs must be unique")
        experiment_digest = candidate_values[0].experiment_digest
        if any(item.experiment_digest != experiment_digest for item in candidate_values):
            raise PredictiveSelectionError("all candidates must describe the same structural/interpreted experiment")
        if any(item.experiment_digest != experiment_digest for item in observation_values):
            raise PredictiveSelectionError("observation sample belongs to a different predictive experiment")
        expected_address = candidate_values[0].address
        for sample in observation_values:
            if (
                sample.observer_contract.subject != expected_address.state_schema
                or sample.observer_contract.interpretation != expected_address.computational_ground
            ):
                raise PredictiveSelectionError("observer subject or interpretation differs from the composed Ground")
            frame = sample.observer_receipt.time_frame
            if frame is None or frame.scheduler is None or frame.scheduler.scheduler_id != expected_address.coordinate.scheduler_id:
                raise PredictiveSelectionError("observer receipt scheduler identity differs from the composed Ground")
        ordered_samples = tuple(sorted(observation_values, key=lambda item: item.tick))
        ticks = [item.tick for item in ordered_samples]
        if len(set(ticks)) != len(ticks):
            raise PredictiveSelectionError("observation scheduler ticks must be unique")
        if any(item.tick < candidate_values[0].address.base_ground.coordinate for item in ordered_samples):
            raise PredictiveSelectionError("an observation precedes the experiment's base Virtual Ground")
        development = tuple(item for item in ordered_samples if item.tick <= development_cutoff)
        validation = tuple(
            item for item in ordered_samples
            if development_cutoff < item.tick <= validation_cutoff
        )
        test = tuple(item for item in ordered_samples if item.tick > validation_cutoff)
        if not development:
            raise PredictiveSelectionError("development partition must contain at least one observation")
        if not validation:
            raise PredictiveSelectionError("validation partition must contain at least one observation")
        partitions = (
            ("development", development),
            ("validation", validation),
            ("test", test),
        )

        for candidate in candidate_values:
            if candidate.address.base_ground != candidate_values[0].address.base_ground:
                raise PredictiveSelectionError("candidate base Virtual Grounds differ")
            if candidate.address.coordinate.scheduler_id != candidate_values[0].address.coordinate.scheduler_id:
                raise PredictiveSelectionError("candidate scheduler identities differ")
            for sample in ordered_samples:
                for component in candidate.address.components:
                    value = _read_path(sample.observed_state, component.field_path, "observed state")
                    _validate_component_value(value, component.value_kind, "observed component")

        evaluation_values: list[PredictiveCandidateEvaluation] = []
        for candidate in candidate_values:
            description_digest, description_bytes, verification_units, profiles, versions = self._description_profile(candidate)
            split_metrics = tuple(
                self._partition(candidate, samples, versions, name)
                for name, samples in partitions
            )
            evaluation_values.append(
                PredictiveCandidateEvaluation(
                    candidate_id=candidate.candidate_id,
                    candidate_digest=candidate.digest,
                    description_digest=description_digest,
                    description_bytes=description_bytes,
                    verification_witness_units=verification_units,
                    generator_profiles=profiles,
                    partitions=split_metrics,
                )
            )

        by_id = {item.candidate_id: item for item in evaluation_values}
        frontier = tuple(sorted(
            item.candidate_id
            for item in evaluation_values
            if not any(
                other.candidate_id != item.candidate_id and self._dominates(other, item)
                for other in evaluation_values
            )
        ))

        def ranking_key(candidate_id: str) -> tuple[Any, ...]:
            """Mathematics: Order candidates by validation prediction, then explicit navigation, description, and verification costs."""
            evaluation = by_id[candidate_id]
            metrics = evaluation.partition("validation")
            return (
                -metrics.predictive_yield,
                -metrics.component_state_space_coverage,
                -metrics.coverage_ratio,
                -metrics.component_accuracy,
                -metrics.full_state_match_rate,
                metrics.mean_navigation_work_units,
                evaluation.description_bytes,
                evaluation.verification_witness_units,
                candidate_id,
            )

        frontier_order = sorted(frontier, key=ranking_key)
        dominated_order = sorted(
            (item.candidate_id for item in evaluation_values if item.candidate_id not in frontier),
            key=ranking_key,
        )
        ranking = tuple(frontier_order + dominated_order)
        sample_digest = _digest(
            [item.to_dict() for item in ordered_samples],
            "predictive observation sequence",
        )
        operational_profile = self._operational_profile(ordered_samples)
        return PredictiveSelectionReport(
            experiment_digest=experiment_digest,
            sample_digest=sample_digest,
            development_through_tick=development_cutoff,
            validation_through_tick=validation_cutoff,
            partition_counts=tuple((name, len(samples)) for name, samples in partitions),
            ranking=ranking,
            pareto_frontier=frontier_order,
            selected_candidate_id=ranking[0],
            evaluations=tuple(evaluation_values),
            operational_profile_json=_canonical_json(operational_profile, "operational profile"),
            recommendation_authoritative=False,
        )
