"""Evidence-bearing empirical profiles for computational placement.

Profiles compare repeated, correctness-checked end-to-end observations for the
same workload class and origin environment. They remain advisory: a profile
does not replace fabric resolution, receiver admission, or execution authority.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import re
from typing import Any, Mapping, Sequence

from .operation_timing import OperationTimingSample
from .program_dataflow_fabric import (
    DataflowAddFrontierReceipt,
    DataflowCompareFrontierReceipt,
    DataflowMultiplyFrontierReceipt,
)
from .temporal import CausalStamp, MonotonicReading

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_LABEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}\Z")
_PEER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_MAX_OBSERVATIONS = 100_000


class PlacementProfileError(ValueError):
    """A placement identity, empirical observation, or comparison is invalid."""


def _digest(value: Any, label: str) -> str:
    """Mathematics: require one lowercase SHA-256 identity."""
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise PlacementProfileError(f"{label} must be lowercase SHA-256 hex")
    return value


def _label(value: Any, label: str) -> str:
    """Mathematics: require a bounded stable identifier."""
    if not isinstance(value, str) or _LABEL.fullmatch(value) is None:
        raise PlacementProfileError(f"{label} is not a valid bounded identifier")
    return value


def _canonical_digest(value: Any) -> str:
    """Mathematics: identify finite JSON content by SHA256 of canonical UTF-8 encoding."""
    try:
        encoded = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise PlacementProfileError("profile content is not canonical finite JSON") from exc
    return hashlib.sha256(encoded).hexdigest()


def _sample_from_dict(payload: Mapping[str, Any]) -> OperationTimingSample:
    """Mathematics: restore a typed endpoint-local timing sample without crossing clock domains."""
    expected = {
        "phase", "actor_id", "segment", "correlation_id", "started", "ended",
        "elapsed_ns", "causal_start", "causal_end",
    }
    if not isinstance(payload, Mapping) or set(payload) != expected:
        raise PlacementProfileError("timing sample fields are malformed")
    for name in ("started", "ended"):
        if not isinstance(payload[name], Mapping) or set(payload[name]) != {
            "actor_id", "segment", "elapsed_ns"
        }:
            raise PlacementProfileError(f"timing sample {name} reading is malformed")
    try:
        sample = OperationTimingSample(
            phase=payload["phase"],
            actor_id=payload["actor_id"],
            segment=payload["segment"],
            correlation_id=payload["correlation_id"],
            started=MonotonicReading(**payload["started"]),
            ended=MonotonicReading(**payload["ended"]),
            causal_start=CausalStamp.from_dict(payload["causal_start"]),
            causal_end=CausalStamp.from_dict(payload["causal_end"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise PlacementProfileError("timing sample contains invalid typed clock evidence") from exc
    if type(payload["elapsed_ns"]) is not int or payload["elapsed_ns"] < 0:
        raise PlacementProfileError("timing sample elapsed duration must be a non-negative strict integer")
    if sample.elapsed_ns != payload["elapsed_ns"]:
        raise PlacementProfileError("timing sample elapsed duration differs from its monotonic readings")
    return sample


@dataclass(frozen=True)
class PlacementProfileKey:
    """Stable identity for one workload class, implementation, route and origin environment."""

    workload_class_digest: str
    operator_id: str
    operator_version: int
    operator_contract_digest: str
    computational_ground_fingerprint: str
    origin_environment_digest: str
    target_host_id: str
    implementation_fingerprint: str
    peer_path: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """Mathematics: validate the comparable semantic domain and one exact placement identity."""
        for name in (
            "workload_class_digest",
            "operator_contract_digest",
            "computational_ground_fingerprint",
            "origin_environment_digest",
            "implementation_fingerprint",
        ):
            _digest(getattr(self, name), name)
        _label(self.operator_id, "operator_id")
        _label(self.target_host_id, "target_host_id")
        if type(self.operator_version) is not int or self.operator_version < 1:
            raise PlacementProfileError("operator_version must be a positive strict integer")
        if not isinstance(self.peer_path, (tuple, list)):
            raise PlacementProfileError("peer_path must be a tuple or list of peer identities")
        path = tuple(self.peer_path)
        if any(not isinstance(item, str) or _PEER.fullmatch(item) is None for item in path):
            raise PlacementProfileError("peer_path contains an invalid peer identity")
        if len(set(path)) != len(path):
            raise PlacementProfileError("peer_path must be cycle-free")
        if path and len(path) < 2:
            raise PlacementProfileError("a remote peer_path must contain origin and destination")
        object.__setattr__(self, "peer_path", path)

    def comparison_payload(self) -> dict[str, Any]:
        """Mathematics: project only the identity dimensions that must match before timing comparisons."""
        return {
            "workload_class_digest": self.workload_class_digest,
            "operator_id": self.operator_id,
            "operator_version": self.operator_version,
            "operator_contract_digest": self.operator_contract_digest,
            "computational_ground_fingerprint": self.computational_ground_fingerprint,
            "origin_environment_digest": self.origin_environment_digest,
            "objective": "origin-total-completion-nanoseconds",
        }

    @property
    def comparison_digest(self) -> str:
        """Mathematics: identify the common workload and measurement environment."""
        return _canonical_digest(self.comparison_payload())

    def to_dict(self) -> dict[str, Any]:
        """Mathematics: serialize semantic, implementation, route and environment identities."""
        return {
            "schema": "mailcpu.placement-profile-key.v1",
            "workload_class_digest": self.workload_class_digest,
            "operator_id": self.operator_id,
            "operator_version": self.operator_version,
            "operator_contract_digest": self.operator_contract_digest,
            "computational_ground_fingerprint": self.computational_ground_fingerprint,
            "origin_environment_digest": self.origin_environment_digest,
            "target_host_id": self.target_host_id,
            "implementation_fingerprint": self.implementation_fingerprint,
            "peer_path": list(self.peer_path),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "PlacementProfileKey":
        """Mathematics: reconstruct a placement key only from its exact versioned field set."""
        expected = {
            "schema", "workload_class_digest", "operator_id", "operator_version",
            "operator_contract_digest", "computational_ground_fingerprint",
            "origin_environment_digest", "target_host_id", "implementation_fingerprint",
            "peer_path",
        }
        if not isinstance(payload, Mapping) or set(payload) != expected:
            raise PlacementProfileError("placement profile key fields are malformed")
        if payload["schema"] != "mailcpu.placement-profile-key.v1" or not isinstance(payload["peer_path"], list):
            raise PlacementProfileError("placement profile key schema or peer path is invalid")
        try:
            return cls(
                workload_class_digest=payload["workload_class_digest"],
                operator_id=payload["operator_id"],
                operator_version=payload["operator_version"],
                operator_contract_digest=payload["operator_contract_digest"],
                computational_ground_fingerprint=payload["computational_ground_fingerprint"],
                origin_environment_digest=payload["origin_environment_digest"],
                target_host_id=payload["target_host_id"],
                implementation_fingerprint=payload["implementation_fingerprint"],
                peer_path=tuple(payload["peer_path"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            if isinstance(exc, PlacementProfileError):
                raise
            raise PlacementProfileError("placement profile key contains invalid values") from exc

    @property
    def digest(self) -> str:
        """Mathematics: identify the complete placement profile key."""
        return _canonical_digest(self.to_dict())


@dataclass(frozen=True)
class PlacementObservation:
    """One correctness-checked total-completion sample bound to an exact execution identity."""

    profile_key_digest: str
    workload_digest: str
    timing_sample: OperationTimingSample
    execution_digest: str
    verification_digest: str
    verification_method: str
    route_receipt: DataflowAddFrontierReceipt | None = None

    def __post_init__(self) -> None:
        """Mathematics: admit only correlated total-completion durations with explicit verification evidence."""
        _digest(self.profile_key_digest, "profile_key_digest")
        _digest(self.workload_digest, "workload_digest")
        _digest(self.execution_digest, "execution_digest")
        _digest(self.verification_digest, "verification_digest")
        if not isinstance(self.timing_sample, OperationTimingSample):
            raise PlacementProfileError("timing_sample must be an OperationTimingSample")
        if self.timing_sample.phase != "total_completion":
            raise PlacementProfileError("placement profiles accept only total_completion samples")
        if self.timing_sample.correlation_id != self.workload_digest:
            raise PlacementProfileError("timing sample correlation does not match the exact workload digest")
        if self.timing_sample.elapsed_ns < 0:
            raise PlacementProfileError("timing sample duration cannot be negative")
        _label(self.verification_method, "verification_method")
        if self.route_receipt is not None and not isinstance(self.route_receipt, DataflowAddFrontierReceipt):
            raise PlacementProfileError("route_receipt must be a typed binary frontier receipt")

    @classmethod
    def from_timing_sample(
        cls,
        key: PlacementProfileKey,
        sample: OperationTimingSample,
        *,
        workload_digest: str,
        execution_digest: str,
        verification_digest: str,
        verification_method: str,
        route_receipt: DataflowAddFrontierReceipt | None = None,
    ) -> "PlacementObservation":
        """Mathematics: bind a measured operation to its remote receipt, when present, and verified result."""
        if not isinstance(key, PlacementProfileKey):
            raise PlacementProfileError("key must be a PlacementProfileKey")
        if key.peer_path:
            if not isinstance(route_receipt, DataflowAddFrontierReceipt):
                raise PlacementProfileError("remote placement requires a typed binary frontier receipt")
            if (
                route_receipt.host_id != key.target_host_id
                or route_receipt.implementation_fingerprint != key.implementation_fingerprint
                or route_receipt.peer_path != key.peer_path
            ):
                raise PlacementProfileError("frontier receipt does not match the profiled host, implementation, or route")
            if route_receipt.peer_id != key.peer_path[-1]:
                raise PlacementProfileError("frontier receipt terminal peer differs from the profiled route")
        elif route_receipt is not None:
            raise PlacementProfileError("local placement cannot carry a remote frontier receipt")
        return cls(
            profile_key_digest=key.digest,
            workload_digest=workload_digest,
            timing_sample=sample,
            execution_digest=execution_digest,
            verification_digest=verification_digest,
            verification_method=verification_method,
            route_receipt=route_receipt,
        )

    def to_dict(self) -> dict[str, Any]:
        """Mathematics: serialize clock provenance, exact workload identity and correctness evidence."""
        return {
            "schema": "mailcpu.placement-observation.v1",
            "profile_key_digest": self.profile_key_digest,
            "workload_digest": self.workload_digest,
            "timing_sample": self.timing_sample.to_dict(),
            "execution_digest": self.execution_digest,
            "verification_digest": self.verification_digest,
            "verification_method": self.verification_method,
            "route_receipt": None if self.route_receipt is None else self.route_receipt.to_dict(),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "PlacementObservation":
        """Mathematics: restore one observation and recompute its timing and evidence invariants."""
        expected = {
            "schema", "profile_key_digest", "workload_digest", "timing_sample",
            "execution_digest", "verification_digest", "verification_method",
            "route_receipt",
        }
        if not isinstance(payload, Mapping) or set(payload) != expected:
            raise PlacementProfileError("placement observation fields are malformed")
        if payload["schema"] != "mailcpu.placement-observation.v1":
            raise PlacementProfileError("placement observation schema is unsupported")
        if not isinstance(payload["timing_sample"], Mapping):
            raise PlacementProfileError("placement observation timing sample is malformed")
        raw_receipt = payload["route_receipt"]
        route_receipt = None
        if raw_receipt is not None:
            if not isinstance(raw_receipt, Mapping):
                raise PlacementProfileError("placement observation route receipt is malformed")
            receipt_schema = raw_receipt.get("schema")
            receipt_types = {
                "mailcpu.dataflow.add-frontier-receipt.v3": DataflowAddFrontierReceipt,
                "mailcpu.dataflow.compare-frontier-receipt.v1": DataflowCompareFrontierReceipt,
                "mailcpu.dataflow.multiply-frontier-receipt.v1": DataflowMultiplyFrontierReceipt,
            }
            receipt_type = receipt_types.get(receipt_schema)
            if receipt_type is None:
                raise PlacementProfileError("placement observation route receipt schema is unsupported")
            try:
                route_receipt = receipt_type.from_dict(raw_receipt)
            except (KeyError, TypeError, ValueError) as exc:
                raise PlacementProfileError("placement observation route receipt failed typed validation") from exc
        try:
            return cls(
                profile_key_digest=payload["profile_key_digest"],
                workload_digest=payload["workload_digest"],
                timing_sample=_sample_from_dict(payload["timing_sample"]),
                execution_digest=payload["execution_digest"],
                verification_digest=payload["verification_digest"],
                verification_method=payload["verification_method"],
                route_receipt=route_receipt,
            )
        except (KeyError, TypeError, ValueError) as exc:
            if isinstance(exc, PlacementProfileError):
                raise
            raise PlacementProfileError("placement observation contains invalid values") from exc

    @property
    def digest(self) -> str:
        """Mathematics: identify one immutable timing and verification observation."""
        return _canonical_digest(self.to_dict())


@dataclass(frozen=True)
class PlacementProfile:
    """Immutable collection of comparable empirical samples for one implementation and route."""

    key: PlacementProfileKey
    observations: tuple[PlacementObservation, ...]

    def __post_init__(self) -> None:
        """Mathematics: enforce one profile key, unique observations and a finite sample capacity."""
        if not isinstance(self.key, PlacementProfileKey):
            raise PlacementProfileError("profile requires a PlacementProfileKey")
        observations = tuple(self.observations)
        if not observations or len(observations) > _MAX_OBSERVATIONS:
            raise PlacementProfileError(f"profile requires 1..{_MAX_OBSERVATIONS} observations")
        if any(
            not isinstance(item, PlacementObservation) or item.profile_key_digest != self.key.digest
            for item in observations
        ):
            raise PlacementProfileError("profile observations do not share its exact placement key")
        for item in observations:
            receipt = item.route_receipt
            if self.key.peer_path:
                if receipt is None or (
                    receipt.host_id != self.key.target_host_id
                    or receipt.implementation_fingerprint != self.key.implementation_fingerprint
                    or receipt.peer_path != self.key.peer_path
                    or receipt.peer_id != self.key.peer_path[-1]
                ):
                    raise PlacementProfileError("profile route receipt differs from its exact placement key")
            elif receipt is not None:
                raise PlacementProfileError("local placement profile cannot contain a remote route receipt")
        digests = [item.digest for item in observations]
        if len(set(digests)) != len(digests):
            raise PlacementProfileError("profile contains duplicate observations")
        object.__setattr__(self, "observations", observations)

    def add(self, observation: PlacementObservation) -> "PlacementProfile":
        """Mathematics: return a new profile with one additional non-duplicate observation."""
        if not isinstance(observation, PlacementObservation):
            raise PlacementProfileError("add requires a PlacementObservation")
        if observation.profile_key_digest != self.key.digest:
            raise PlacementProfileError("observation belongs to a different placement profile")
        return PlacementProfile(self.key, self.observations + (observation,))

    @property
    def durations_ns(self) -> tuple[int, ...]:
        """Mathematics: project only endpoint-local elapsed durations, never absolute clock readings."""
        return tuple(item.timing_sample.elapsed_ns for item in self.observations)

    @property
    def summary(self) -> dict[str, int]:
        """Mathematics: compute deterministic integer summary statistics for one placement profile."""
        ordered = sorted(self.durations_ns)
        count = len(ordered)
        middle = count // 2
        median = ordered[middle] if count % 2 else (ordered[middle - 1] + ordered[middle]) // 2
        p95 = ordered[math.ceil((count - 1) * 0.95)]
        return {
            "count": count,
            "min_ns": ordered[0],
            "median_ns": median,
            "p95_ns": p95,
            "max_ns": ordered[-1],
            "mean_ns": sum(ordered) // count,
        }

    def _payload(self) -> dict[str, Any]:
        """Mathematics: project the key and ordered observations used by the profile digest."""
        return {
            "schema": "mailcpu.placement-profile.v1",
            "key": self.key.to_dict(),
            "observations": [item.to_dict() for item in self.observations],
        }

    @property
    def digest(self) -> str:
        """Mathematics: identify the complete profile and its evidence history."""
        return _canonical_digest(self._payload())

    def to_dict(self) -> dict[str, Any]:
        """Mathematics: serialize profile identity, exact samples and derived statistics."""
        return {
            **self._payload(),
            "summary": self.summary,
            "digest": self.digest,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "PlacementProfile":
        """Mathematics: restore and revalidate the complete empirical profile."""
        expected = {"schema", "key", "observations", "summary", "digest"}
        if not isinstance(payload, Mapping) or set(payload) != expected:
            raise PlacementProfileError("placement profile fields are malformed")
        if (
            payload["schema"] != "mailcpu.placement-profile.v1"
            or not isinstance(payload["key"], Mapping)
            or not isinstance(payload["observations"], list)
        ):
            raise PlacementProfileError("placement profile schema or nested collections are invalid")
        try:
            profile = cls(
                PlacementProfileKey.from_dict(payload["key"]),
                tuple(PlacementObservation.from_dict(item) for item in payload["observations"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            if isinstance(exc, PlacementProfileError):
                raise
            raise PlacementProfileError("placement profile contains invalid nested values") from exc
        summary = payload["summary"]
        if (
            not isinstance(summary, Mapping)
            or set(summary) != set(profile.summary)
            or any(type(value) is not int or value < 0 for value in summary.values())
            or summary != profile.summary
            or payload["digest"] != profile.digest
        ):
            raise PlacementProfileError("placement profile summary or digest does not match its evidence")
        return profile


@dataclass(frozen=True)
class PlacementRanking:
    """Non-authoritative comparison result for profiles sharing one workload and origin environment."""

    comparison_digest: str
    minimum_observations: int
    ordered_profile_digests: tuple[str, ...]
    insufficient_profiles: tuple[tuple[str, int], ...]

    def __post_init__(self) -> None:
        """Mathematics: ensure ranking completeness is explicit and every ranked profile is identified once."""
        _digest(self.comparison_digest, "comparison_digest")
        if type(self.minimum_observations) is not int or self.minimum_observations < 1:
            raise PlacementProfileError("minimum_observations must be a positive strict integer")
        ranked = tuple(self.ordered_profile_digests)
        insufficient = tuple(tuple(item) for item in self.insufficient_profiles)
        for item in ranked:
            _digest(item, "ranked profile digest")
        for item in insufficient:
            if len(item) != 2:
                raise PlacementProfileError("insufficient profile entry must contain digest and count")
            _digest(item[0], "insufficient profile digest")
            if type(item[1]) is not int or item[1] < 0:
                raise PlacementProfileError("insufficient profile count must be a non-negative strict integer")
        if len(set(ranked)) != len(ranked) or len({item[0] for item in insufficient}) != len(insufficient):
            raise PlacementProfileError("placement ranking contains duplicate profile identities")
        if bool(ranked) == bool(insufficient):
            raise PlacementProfileError("placement ranking must contain either a complete order or insufficient evidence")
        if ranked and insufficient:
            raise PlacementProfileError("incomplete evidence cannot produce a partial placement ranking")
        if any(count >= self.minimum_observations for _, count in insufficient):
            raise PlacementProfileError("insufficient profile entry meets the minimum observation count")
        if insufficient != tuple(sorted(insufficient)):
            raise PlacementProfileError("insufficient profile entries are not in canonical digest order")
        object.__setattr__(self, "ordered_profile_digests", ranked)
        object.__setattr__(self, "insufficient_profiles", insufficient)

    @property
    def complete(self) -> bool:
        """Mathematics: indicate whether every supplied placement met the minimum evidence threshold."""
        return not self.insufficient_profiles and bool(self.ordered_profile_digests)

    @property
    def best_profile_digest(self) -> str | None:
        """Mathematics: expose the empirical first choice only when the comparison is complete."""
        return self.ordered_profile_digests[0] if self.complete else None

    @property
    def recommendation_authoritative(self) -> bool:
        """Mathematics: placement comparisons never grant execution authority."""
        return False

    def _payload(self) -> dict[str, Any]:
        """Mathematics: project the exact comparison identity, profile order and insufficient-evidence set."""
        return {
            "schema": "mailcpu.placement-ranking.v1",
            "comparison_digest": self.comparison_digest,
            "minimum_observations": self.minimum_observations,
            "ordered_profile_digests": list(self.ordered_profile_digests),
            "insufficient_profiles": [
                {"profile_digest": digest, "observation_count": count}
                for digest, count in self.insufficient_profiles
            ],
        }

    @property
    def digest(self) -> str:
        """Mathematics: identify the exact ranking proposal without making it authoritative."""
        return _canonical_digest(self._payload())

    def to_dict(self) -> dict[str, Any]:
        """Mathematics: serialize ranked profiles and insufficient evidence without claiming authority."""
        return {
            **self._payload(),
            "digest": self.digest,
            "complete": self.complete,
            "best_profile_digest": self.best_profile_digest,
            "recommendation_authoritative": False,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "PlacementRanking":
        """Mathematics: restore a ranking only when completeness, ordering choice and advisory authority recompute exactly."""
        expected = {
            "schema", "comparison_digest", "minimum_observations",
            "ordered_profile_digests", "insufficient_profiles", "complete",
            "best_profile_digest", "recommendation_authoritative", "digest",
        }
        if not isinstance(payload, Mapping) or set(payload) != expected:
            raise PlacementProfileError("placement ranking fields are malformed")
        if (
            payload["schema"] != "mailcpu.placement-ranking.v1"
            or payload["recommendation_authoritative"] is not False
            or type(payload["complete"]) is not bool
            or not isinstance(payload["ordered_profile_digests"], list)
            or not isinstance(payload["insufficient_profiles"], list)
        ):
            raise PlacementProfileError("placement ranking schema, authority or nested values are invalid")
        insufficient = []
        for item in payload["insufficient_profiles"]:
            if not isinstance(item, Mapping) or set(item) != {"profile_digest", "observation_count"}:
                raise PlacementProfileError("placement ranking insufficient-profile entry is malformed")
            insufficient.append((item["profile_digest"], item["observation_count"]))
        try:
            ranking = cls(
                comparison_digest=payload["comparison_digest"],
                minimum_observations=payload["minimum_observations"],
                ordered_profile_digests=tuple(payload["ordered_profile_digests"]),
                insufficient_profiles=tuple(insufficient),
            )
        except (KeyError, TypeError, ValueError) as exc:
            if isinstance(exc, PlacementProfileError):
                raise
            raise PlacementProfileError("placement ranking contains invalid values") from exc
        if (
            payload["complete"] is not ranking.complete
            or payload["best_profile_digest"] != ranking.best_profile_digest
            or payload["digest"] != ranking.digest
        ):
            raise PlacementProfileError("placement ranking completeness or selected profile differs from its evidence")
        return ranking


def rank_placement_profiles(
    profiles: Sequence[PlacementProfile],
    *,
    minimum_observations: int = 3,
) -> PlacementRanking:
    """Mathematics: rank complete comparable profiles by median, p95, mean and stable placement identity."""
    if not isinstance(profiles, (tuple, list)) or len(profiles) < 2:
        raise PlacementProfileError("ranking requires at least two placement profiles")
    if type(minimum_observations) is not int or minimum_observations < 1:
        raise PlacementProfileError("minimum_observations must be a positive strict integer")
    selected = tuple(profiles)
    if any(not isinstance(item, PlacementProfile) for item in selected):
        raise PlacementProfileError("ranking inputs must be PlacementProfile values")
    if len({item.key.digest for item in selected}) != len(selected):
        raise PlacementProfileError("ranking contains duplicate placement profile keys")
    comparison_digests = {item.key.comparison_digest for item in selected}
    if len(comparison_digests) != 1:
        raise PlacementProfileError("placement profiles do not share a workload, operator, Ground and origin environment")
    comparison_digest = next(iter(comparison_digests))
    insufficient = tuple(sorted(
        (item.digest, item.summary["count"])
        for item in selected
        if item.summary["count"] < minimum_observations
    ))
    if insufficient:
        return PlacementRanking(comparison_digest, minimum_observations, (), insufficient)

    ordered = sorted(
        selected,
        key=lambda item: (
            item.summary["median_ns"],
            item.summary["p95_ns"],
            item.summary["mean_ns"],
            item.key.target_host_id,
            item.key.implementation_fingerprint,
            item.key.peer_path,
        ),
    )
    return PlacementRanking(
        comparison_digest,
        minimum_observations,
        tuple(item.digest for item in ordered),
        (),
    )


__all__ = [
    "PlacementObservation",
    "PlacementProfile",
    "PlacementProfileError",
    "PlacementProfileKey",
    "PlacementRanking",
    "rank_placement_profiles",
]
